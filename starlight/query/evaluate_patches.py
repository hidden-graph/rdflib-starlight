"""Targeted compatibility shims for the in-memory backend's SPARQL
*evaluator* (``rdflib.plugins.sparql.evaluate``/``operators``) - not the
algebra translator (see ``algebra_translator_patches.py`` for those) and not
the arithmetic/numeric-function evaluation bugs (see
``operator_patches.py``).

Two different categories of shim live here:

1. ``patch_evalextend_forgotten_bind_vars``/``patch_construct_skips_encoding_solutions``
   fix confirmed bugs in *plain rdflib itself* (see
   ``docs/rdflib-upstream-issues.md`` issue 5 for the first). This is the
   most important category to have applied correctly: unlike the
   algebra-translator bugs (which fail loudly, with a ``ParseException`` or
   similar on the malformed regenerated text) and the arithmetic bugs
   (wrong but well-formed output), these silently produce wrong query
   *results* with no error or warning at all.

2. ``patch_relational_expression_tt_hash_equality`` is a different kind of
   thing - not a plain-rdflib bug (rdflib's own ``=``/``!=`` behavior is
   entirely correct for the plain ``URIRef``s it's actually given), but a
   necessary complement to this library's own in-memory tt:HASH encoding:
   a triple term is stored as an opaque, content-addressed URIRef, which
   hides the RDF 1.2 value-equality semantics (recursing into components,
   applying numeric/etc value equality per SPARQL's own literal-equality
   rules) that a real triple-term-aware engine (Oxigraph, Fuseki) already
   gives for free. See its own docstring below for the full detail.

Same idempotent apply-once pattern as ``operator_patches.py``/
``algebra_translator_patches.py``.
"""

from __future__ import annotations

from rdflib import Literal, URIRef, Variable
from rdflib.namespace import RDF
from rdflib.plugins.sparql import evaluate
from rdflib.plugins.sparql.parserutils import CompValue
from rdflib.plugins.sparql.sparql import SPARQLError

_evaluate_patch_status: bool | None = None


def _expr_free_vars(expr) -> set:
    """The set of variables ``expr`` itself references, read from the
    ``_vars`` bookkeeping rdflib's own ``_addVars`` pass already computes
    for every node in the algebra tree (``algebra.py``, run once during
    ``translateQuery`` - *not* ``translateUpdate``, which never runs this
    pass at all, so this is frequently empty/missing in an Update context)
    - except for a bare ``Variable``, which has no such attribute (it
    isn't a ``CompValue``) but whose own free-variable set is trivially
    itself.

    Deliberately not ``expr.get("_vars", set())`` - ``CompValue.get`` is
    *not* ``dict.get``: its actual signature is
    ``get(self, a, variables=False, errors=False)``, so a second
    positional argument is interpreted as the ``variables`` flag, not a
    default value, and a missing key falls back to returning the key
    string itself (``OrderedDict.get(self, a, a)``) - confirmed a real,
    reproducible ``TypeError: unsupported operand type(s) for |: 'set'
    and 'str'`` when first tried, from unioning a ``set`` with the literal
    string ``"_vars"``. Plain ``in``/``[]`` access (via the underlying
    ``dict`` interface ``CompValue`` inherits, unaffected by its own
    ``get`` override) avoids this entirely.
    """
    if isinstance(expr, Variable):
        return {expr}
    if isinstance(expr, CompValue):
        vars_ = dict.get(expr, "_vars")
        return vars_ if isinstance(vars_, set) else set()
    return set()


def patch_evalextend_forgotten_bind_vars() -> bool:
    """Fix a confirmed rdflib bug: ``evalExtend`` (``BIND``/``SELECT (expr
    AS ?v)`` evaluation) forgets a variable its own ``expr`` depends on
    before evaluating that ``expr``, whenever that variable isn't *also* a
    pattern variable of the ``Extend`` node's own local ``p`` (e.g. `{
    BIND(?t0 AS ?o) }` with an empty local pattern, where ``?t0`` was bound
    by an *earlier, outer* ``BIND``). The forgotten variable makes ``expr``
    evaluate against an unbound variable, which raises internally and is
    silently swallowed by ``evalExtend``'s own ``except SPARQLError: yield
    c`` - yielding the row with the *target* variable (``?o`` here) left
    completely unbound instead, rather than raising or skipping the row.
    An unbound variable later joined against (e.g. ``?s :p ?o .``) then
    matches *anything*, producing extra, wrong results with no error at
    all. See ``docs/rdflib-upstream-issues.md`` issue 5 for the full
    root-cause trace (down to ``algebra.py``'s ``_addVars`` "Extend" case,
    which the root cause - not just the trigger shape - is confirmed
    against).

    Fix: union in ``expr``'s own free variables (see ``_expr_free_vars``)
    before forgetting, so a variable ``expr`` genuinely depends on is never
    forgotten regardless of whether static analysis attributed it to this
    ``Extend`` node's own ``_vars``. This is the same evaluation
    ``evalExtend`` already performs, unchanged in every other respect -
    only the ``_except`` set passed to ``c.forget(...)`` differs.

    Idempotent and defensive, matching the established
    ``operator_patches.py``/``algebra_translator_patches.py`` idiom -
    returns ``False`` without raising if rdflib's internals don't match
    what this shim expects.
    """
    global _evaluate_patch_status
    if _evaluate_patch_status is not None:
        return _evaluate_patch_status

    try:
        original_eval_extend = evaluate.evalExtend
        if getattr(original_eval_extend, "_starlight_evalextend_patch", False):
            _evaluate_patch_status = True
            return True

        _eval = evaluate._eval
        evalPart = evaluate.evalPart

        def _patched_eval_extend(ctx, extend):
            for c in evalPart(ctx, extend.p):
                try:
                    # extend._vars can genuinely be None, not just "unset
                    # defaulting to an empty set": rdflib's own
                    # translateUpdate never runs the _addVars/analyse pass
                    # at all (confirmed - unlike translateQuery, which
                    # always does), so any Extend node arising from a
                    # SPARQL Update's WHERE-clause processing has no
                    # "_vars" attribute computed whatsoever. `None | a_set`
                    # raises TypeError, so this can't just reuse the
                    # ordinary "attribute defaults to None" CompValue
                    # convention here - confirmed a real, reproducible
                    # crash on Update evaluation when first tried.
                    except_vars = (extend._vars or set()) | _expr_free_vars(extend.expr)
                    e = _eval(extend.expr, c.forget(ctx, _except=except_vars))
                    if isinstance(e, SPARQLError):
                        raise e

                    yield c.merge({extend.var: e})

                except SPARQLError:
                    yield c

        _patched_eval_extend._starlight_evalextend_patch = True  # type: ignore[attr-defined]
        evaluate.evalExtend = _patched_eval_extend
        _evaluate_patch_status = True
    except Exception:
        _evaluate_patch_status = False

    return _evaluate_patch_status


_construct_patch_status: bool | None = None


def patch_construct_skips_encoding_solutions() -> bool:
    """Fix a real, general gap (not an rdflib bug - a starlight-side one):
    ``StarlightGraph.query()``/``StarlightDataset.query()`` execute the
    rewritten SPARQL 1.1 text against a *raw*, unfiltered view of the
    underlying store (``raw = Graph(store=self.store, ...)`` in
    ``starlight_graph.py``) - deliberately, since triple-term pattern
    rewriting (``sparql12_to_11.py``) needs to match the internal
    ``rdf:subject``/``rdf:predicate``/``rdf:object`` encoding triples
    directly. An *unconstrained* pattern like a bare ``?s ?p ?o .`` matches
    those internal triples too, alongside ordinary user-visible ones.

    For SELECT, ``starlight.model.encoding.restore_select_bindings`` already
    drops any result row that incidentally matched these internal triples
    (a TT_NS-prefixed URIRef paired with an encoding predicate as a bound
    *value* - never something a real query result should surface). CONSTRUCT
    has no equivalent: rdflib's own ``evalConstructQuery`` iterates WHERE
    solutions and instantiates the template for every one, with no per-
    solution filtering hook. Confirmed via two real W3C SPARQL 1.2 test
    fixtures (construct-3, expr-1), both using an unconstrained ``?s ?p ?o``
    inside a CONSTRUCT/GRAPH block over data that already contains
    reification/triple-term encoding triples: the template silently wrapped
    an internal row (e.g. ``tt:HASH rdf:subject :a``) into a bogus *nested*
    triple term, which then crashed downstream in
    ``StarlightGraph.from_rdflib``/``_restore`` with "the subject of a
    triple term must be an IRI or blank node, not a triple term" - not a
    query-authoring mistake, a leak of storage internals into CONSTRUCT
    output that should never have been visible in the first place.

    Fix: the same skip-check ``restore_select_bindings`` already applies to
    SELECT rows, applied here per-solution before templating instead of
    per-output-row after.
    """
    global _construct_patch_status
    if _construct_patch_status is not None:
        return _construct_patch_status

    try:
        original_eval_construct = evaluate.evalConstructQuery
        if getattr(original_eval_construct, "_starlight_construct_patch", False):
            _construct_patch_status = True
            return True

        from rdflib import Graph, URIRef

        from starlight.model.encoding import ENCODING_PREDS, TT_NS

        evalPart = evaluate.evalPart
        _fillTemplate = evaluate._fillTemplate

        def _is_encoding_solution(c) -> bool:
            values = list(c.values())
            return (
                any(isinstance(v, URIRef) and str(v).startswith(TT_NS) for v in values)
                and bool(ENCODING_PREDS.intersection(values))
            )

        def _patched_eval_construct_query(ctx, query):
            template = query.template
            if not template:
                # a construct-where query
                template = query.p.p.triples  # query->project->bgp ...

            graph = Graph()
            for c in evalPart(ctx, query.p):
                if _is_encoding_solution(c):
                    continue
                graph += _fillTemplate(template, c)

            return {"type_": "CONSTRUCT", "graph": graph}

        _patched_eval_construct_query._starlight_construct_patch = True  # type: ignore[attr-defined]
        evaluate.evalConstructQuery = _patched_eval_construct_query
        _construct_patch_status = True
    except Exception:
        _construct_patch_status = False

    return _construct_patch_status


# ---------------------------------------------------------------------------
# tt:HASH-aware `=`/`!=` - restores RDF 1.2 triple-term value-equality for
# the in-memory backend specifically.
# ---------------------------------------------------------------------------

_relational_expression_patch_status: bool | None = None


def _decode_tt_hash(graph, node):
    """Decode `node` (a tt:HASH URIRef) into its raw (subject, predicate,
    object) encoding triples, read directly from `graph`. Returns None for
    anything that isn't a tt:HASH URIRef with encoding triples present in
    `graph`.

    Deliberately *not* recursive - `subject`/`object` are returned exactly
    as read (which may themselves be a nested tt:HASH URIRef, or may not),
    never pre-decoded into a tuple here. `_tt_aware_eq` is what recurses,
    by calling this function again on each component it compares - keeping
    every value this function ever returns a single, consistent shape (an
    rdflib term, never a tuple) is what makes that recursion correct;
    pre-decoding a nested component here produced a tuple one level too
    early, which `_tt_aware_eq`'s own recursive call then couldn't
    re-decode (`isinstance(node, URIRef)` is false for a tuple), silently
    falling through to `a.eq(b)` on two raw tuples and crashing - confirmed
    a real bug this way, not a hypothetical, via the W3C `op-2` fixture's
    own nested-triple-term case.

    Deliberately reads the *graph's own* rdf:subject/predicate/object
    triples rather than a `StarlightGraph._tt_nodes` Python-side registry:
    the graph object seen during query evaluation (`ctx.graph`) is a bare
    `rdflib.Graph` view over the same store (see
    `StarlightGraph.query()` - `raw = Graph(store=self.store, ...)`), not
    the `StarlightGraph` instance itself, so `_tt_nodes` isn't reachable
    from here. Reading the on-store encoding triples directly works
    identically to (and is the same technique as) `StarlightGraph.
    _build_registry_from_store()`'s own reconstruction.
    """
    from starlight.model.encoding import TT_NS

    if not (isinstance(node, URIRef) and str(node).startswith(TT_NS)):
        return None
    s = graph.value(node, RDF.subject)
    p = graph.value(node, RDF.predicate)
    o = graph.value(node, RDF.object)
    if s is None or p is None or o is None:
        return None
    return (s, p, o)


def _tt_aware_eq(graph, a, b) -> bool:
    """RDF 1.2 term-equality between `a`/`b`: decode either side that's a
    tt:HASH URIRef into its (subject, predicate, object) components first,
    recursing - restores the value-equality semantics the opaque encoding
    otherwise hides (e.g. ``TRIPLE(:a,:b,123) = TRIPLE(:a,:b,123.0)`` must
    be true - numeric value equality on the differing object - despite the
    two encoded tt:HASH URIs being different, unrelated strings, since the
    hash is computed from *lexical* form - see
    ``starlight/model/encoding.py::tt_hash``).

    Falls through to plain ``Identifier.eq()`` - which already correctly
    implements SPARQL's own literal value-equality (numeric/date/etc,
    per-datatype) - for any component that isn't itself a tt:HASH URIRef on
    either side, so this only adds recursion where the opaque encoding
    would otherwise have masked it; ordinary IRI/BNode/Literal comparisons
    are unaffected.
    """
    da = _decode_tt_hash(graph, a)
    db = _decode_tt_hash(graph, b)
    if da is None and db is None:
        return a.eq(b)
    if da is None or db is None:
        return False  # one side is a triple term, the other isn't - never equal
    return (
        _tt_aware_eq(graph, da[0], db[0])
        and da[1].eq(db[1])  # predicate is never itself a triple term (RDF 1.2)
        and _tt_aware_eq(graph, da[2], db[2])
    )


def _looks_like_tt_hash(node) -> bool:
    from starlight.model.encoding import TT_NS

    return isinstance(node, URIRef) and str(node).startswith(TT_NS)


def patch_relational_expression_tt_hash_equality() -> bool:
    """Patch ``RelationalExpression`` (the ``=``/``!=``/``<``/etc. FILTER
    comparison grammar production) so that ``=``/``!=`` between two tt:HASH
    URIRefs (the in-memory backend's opaque, content-addressed encoding of
    a triple term) applies real RDF 1.2 value-equality (see
    ``_tt_aware_eq`` above) instead of stock rdflib's plain URIRef string
    equality, which can only ever agree with ``sameTerm`` - never true for
    two triple terms differing only in a component's lexical form (e.g.
    ``123`` vs ``123.0``), which SPARQL's own value-equality rules require.

    Confirmed via the W3C SPARQL 1.2 test suite's own ``eval-triple-terms/
    op-2`` fixture (``FILTER(!sameTerm(?left,?right)) FILTER(?left =
    ?right)`` over two triple terms differing only in a literal's lexical
    form) - previously an unconditional empty result against the in-memory
    backend; see ``tests/w3c_sparql12/test_w3c_sparql12_eval.py``'s
    (now-removed) ``op-2`` entry in ``_IN_MEMORY_KNOWN_DIVERGENCES``.

    Only intervenes when at least one operand is a tt:HASH URIRef - zero
    behavior change, and negligible overhead (one cheap ``isinstance``/
    prefix check), for the overwhelmingly common case of comparing ordinary
    terms. Falls through to the original evalfn for ``<``/``>``/``<=``/
    ``>=``/``IN``/``NOT IN`` unconditionally - RDF 1.2 doesn't define an
    ordering over triple terms the way it does over term *kinds* for
    ``ORDER BY`` (a separate, harder gap - see
    ``_IN_MEMORY_KNOWN_DIVERGENCES``'s ``order-1``/``order-2`` entries,
    not attempted here), so widening this patch to those operators isn't
    attempted.

    Idempotent and defensive, matching the established
    ``operator_patches.py``/``algebra_translator_patches.py`` idiom -
    returns ``False`` without raising if rdflib's internals don't match
    what this shim expects.
    """
    global _relational_expression_patch_status
    if _relational_expression_patch_status is not None:
        return _relational_expression_patch_status

    try:
        from rdflib.plugins.sparql import parser as rdflib_sparql_parser

        comp = rdflib_sparql_parser.RelationalExpression
        original_evalfn = comp.evalfn
        if getattr(original_evalfn, "_starlight_tt_hash_equality_patch", False):
            _relational_expression_patch_status = True
            return True

        def _patched_relational_expression(e, ctx):
            if e.op in ("=", "!="):
                expr_val = e.expr
                other_val = e.other
                if (
                    other_val is not None
                    and not isinstance(other_val, list)
                    and (_looks_like_tt_hash(expr_val) or _looks_like_tt_hash(other_val))
                ):
                    graph = getattr(ctx, "graph", None) or getattr(getattr(ctx, "ctx", None), "graph", None)
                    if graph is not None:
                        result = _tt_aware_eq(graph, expr_val, other_val)
                        return Literal(result if e.op == "=" else not result)
            return original_evalfn(e, ctx)

        _patched_relational_expression._starlight_tt_hash_equality_patch = True  # type: ignore[attr-defined]
        comp.setEvalFn(_patched_relational_expression)
        _relational_expression_patch_status = True
    except Exception:
        _relational_expression_patch_status = False

    return _relational_expression_patch_status


# ---------------------------------------------------------------------------
# tt:HASH-aware ORDER BY - restores RDF 1.2 term-kind ordering for the
# in-memory backend specifically.
# ---------------------------------------------------------------------------

_order_by_patch_status: bool | None = None


def _tt_aware_sort_key(graph, v):
    """RDF 1.2 term-kind-aware ORDER BY sort key for `v` - unbound < blank
    node < IRI < literal < triple term, matching stock rdflib's own
    ``evaluate._val`` bucketing exactly for every kind *except* triple
    terms, which stock rdflib has no bucket for at all (a tt:HASH URIRef
    sorts as bucket 2, indistinguishable from an ordinary IRI, since rdflib
    predates RDF 1.2 triple terms entirely).

    A tt:HASH URIRef gets its own bucket (4, after literal) and, within
    that bucket, is ordered by its own (subject, predicate, object) -
    recursively applying this same function to each component (predicate
    is always a plain IRI - RDF 1.2 forbids it being a triple term - but
    object may itself be a nested tt:HASH URIRef, needing the same
    recursive bucketing again). Confirmed against the W3C SPARQL 1.2
    eval-triple-terms/order-2 fixture's own expected order, which requires
    exactly this: subject-then-predicate-then-object, each individually
    term-kind-bucketed - not e.g. a flat hash/string comparison.

    Every non-triple-term bucket's second tuple element is deliberately
    kept exactly what stock ``_val`` would use (raw ``Literal`` for the
    literal bucket, so ``Literal.__lt__``'s own value-aware numeric/date/etc
    comparison still applies unchanged; ``str(v)`` for BNode/IRI, matching
    plain string comparison, since neither overrides ``__lt__`` specially)
    - this patch only ever *adds* the missing triple-term bucket, never
    changes how any other kind compares against its own kind.
    """
    from rdflib import BNode, Literal, URIRef, Variable

    if isinstance(v, Variable):
        return (0, "")
    if isinstance(v, BNode):
        return (1, str(v))
    if isinstance(v, URIRef):
        decoded = _decode_tt_hash(graph, v)
        if decoded is not None:
            s, p, o = decoded
            return (
                4,
                (
                    _tt_aware_sort_key(graph, s),
                    _tt_aware_sort_key(graph, p),
                    _tt_aware_sort_key(graph, o),
                ),
            )
        return (2, str(v))
    if isinstance(v, Literal):
        return (3, v)
    return (5, str(v))


def patch_order_by_tt_hash_term_kind() -> bool:
    """Patch ``evalOrderBy`` so a tt:HASH URIRef (the in-memory backend's
    opaque, content-addressed encoding of a triple term) sorts in its own,
    RDF-1.2-mandated term-kind bucket - after literals - instead of stock
    rdflib's ``_val``, which has no bucket for triple terms at all (rdflib
    predates RDF 1.2) and so sorts it as an ordinary IRI, intermixed with
    real IRIs. See ``_tt_aware_sort_key`` above for the full detail.

    Confirmed via the W3C SPARQL 1.2 test suite's own ``eval-triple-terms/
    order-1``/``order-2`` fixtures (``ORDER BY`` across mixed blank-node/
    IRI/literal/triple-term values, several distinct triple terms in
    ``order-2`` specifically) - previously wrong ordering against the
    in-memory backend; see ``tests/w3c_sparql12/test_w3c_sparql12_eval.py``'s
    (now-removed) ``order-1``/``order-2`` entries in
    ``_IN_MEMORY_KNOWN_DIVERGENCES``.

    ``_val`` itself is used exactly once in stock rdflib
    (``rdflib.plugins.sparql.evaluate``, inside ``evalOrderBy`` only) -
    confirmed by inspection, not assumed - so replacing ``evalOrderBy``
    wholesale (rather than trying to patch ``_val`` in place, which has no
    way to reach the graph a raw value needs decoding against) is safe and
    complete; no other code path depends on ``_val``'s own bucketing.

    Idempotent and defensive, matching the established
    ``operator_patches.py``/``algebra_translator_patches.py`` idiom -
    returns ``False`` without raising if rdflib's internals don't match
    what this shim expects.
    """
    global _order_by_patch_status
    if _order_by_patch_status is not None:
        return _order_by_patch_status

    try:
        original_eval_order_by = evaluate.evalOrderBy
        if getattr(original_eval_order_by, "_starlight_order_by_patch", False):
            _order_by_patch_status = True
            return True

        evalPart = evaluate.evalPart

        def _patched_eval_order_by(ctx, part):
            res = evalPart(ctx, part.p)
            graph = getattr(ctx, "graph", None) or getattr(getattr(ctx, "ctx", None), "graph", None)

            from rdflib.plugins.sparql.evaluate import value

            for e in reversed(part.expr):
                reverse = bool(e.order and e.order == "DESC")
                res = sorted(
                    res,
                    key=lambda x: _tt_aware_sort_key(graph, value(x, e.expr, variables=True)),
                    reverse=reverse,
                )
            return res

        _patched_eval_order_by._starlight_order_by_patch = True  # type: ignore[attr-defined]
        evaluate.evalOrderBy = _patched_eval_order_by
        _order_by_patch_status = True
    except Exception:
        _order_by_patch_status = False

    return _order_by_patch_status
