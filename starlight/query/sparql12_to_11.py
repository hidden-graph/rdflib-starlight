"""Translate a small SPARQL 1.2 subset into SPARQL 1.1 graph patterns.

The current focus is triple-term graph patterns such as::

    ?stmt rdf:reifies <<( :s :p :o )>> .
    <<( ?s :p ?o )>> :verifiedBy ?who .

Those forms are rewritten into ordinary SPARQL 1.1 basic graph patterns over
the internal starlight encoding used by ``StarlightGraph``'s rdflib store.

This module does not attempt to parse the full SPARQL grammar. It is a scoped,
string-based rewriter designed to preserve the lexical block in which a triple
term appears, so OPTIONAL/UNION branch semantics remain local.
"""

from __future__ import annotations

import re as _re
from dataclasses import dataclass, field

RDF_SUBJECT     = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#subject>"
RDF_PREDICATE   = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#predicate>"
RDF_OBJECT      = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#object>"
RDF_REIFIES     = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies>"
TT_NS_PREFIX    = "https://github.com/hidden-graph/rdflib-starlight/ns/tt#"
DIRLANG_NS_PREFIX = "https://github.com/hidden-graph/rdflib-starlight/ns/dirlang#"

# SPARQL-callable function computing the same content-addressed tt:HASH URIRef
# that StarlightGraph._intern_tt() assigns on write. Used to BIND a triple-term
# variable that a CONSTRUCT template needs but that has no existing WHERE-clause
# match to bind it from (i.e. the template is minting a triple term that was
# never previously used as a value anywhere in the graph).
TT_HASH_FN = f"<{TT_NS_PREFIX}fn/hash>"


def _register_tt_hash_function() -> None:
    from rdflib import BNode, URIRef
    from rdflib.plugins.sparql.operators import register_custom_function
    from rdflib.plugins.sparql.sparql import SPARQLError

    from starlight.model.encoding import TT_NS, tt_hash, term_key, remember_tt_hash

    def _tt_hash_fn(s, p, o):
        # RDF 1.2 (17.4.6, TRIPLE()): a triple term's subject must be an
        # IRI or blank node, predicate an IRI - never a Literal in either
        # position (object has no such restriction). Confirmed via a real
        # W3C test (triple-on-literals): TRIPLE(?subject, ?predicate,
        # ?object) with a VALUES row binding ?subject/?predicate to a
        # Literal is expected to leave ?triple *unbound* for that row, not
        # silently construct an invalid triple term - SPARQLError
        # specifically (not ValueError) is what makes that happen: it's
        # the one exception type evalExtend's own error handling catches
        # and turns into "this BIND target stays unbound", instead of
        # aborting the whole query.
        if not isinstance(s, (URIRef, BNode)):
            raise SPARQLError(f"TRIPLE(): subject must be an IRI or blank node, not {s!r}")
        if not isinstance(p, URIRef):
            raise SPARQLError(f"TRIPLE(): predicate must be an IRI, not {p!r}")
        # A triple term is internally represented as a plain TT_NS-prefixed
        # URIRef (the whole point of the encoding) - so the isinstance
        # checks above alone don't catch "subject/predicate is *itself* a
        # triple term", which RDF 1.2 forbids just as much as a Literal
        # there (triple terms are only ever legal in object position).
        # Confirmed via a real W3C test (triple-on-triple-terms): a VALUES
        # row binding ?subject to a ground <<( )>> value must also leave
        # ?triple unbound, not silently construct a nested-in-subject-
        # position triple term - which would crash downstream anyway (see
        # TripleTerm.__init__'s own, separate guard against exactly this).
        if str(s).startswith(TT_NS):
            raise SPARQLError("TRIPLE(): subject must not itself be a triple term")
        if str(p).startswith(TT_NS):
            raise SPARQLError("TRIPLE(): predicate must not itself be a triple term")
        uri = URIRef(TT_NS + tt_hash(term_key(s), term_key(p), term_key(o)))
        # s/p/o here are rdflib's own already-resolved terms (this function
        # runs at SPARQL *evaluation* time, after parsing/prefix-resolution,
        # not at this module's text-rewrite time) - remembering them lets
        # StarlightGraph._restore() reconstruct a proper TripleTerm for a
        # value that was computed but never written to any graph. See
        # starlight.model.encoding's _TT_HASH_MEMO docstring.
        remember_tt_hash(uri, s, p, o)
        return uri

    register_custom_function(URIRef(TT_HASH_FN[1:-1]), _tt_hash_fn, override=True)


# Deliberate import-time side effect: this mutates rdflib's *global*
# CUSTOM_EVALS/function registry the moment this module is imported, not on
# first use. override=True is intentional too - re-importing this module (or
# a reload) re-registers idempotently under the same TT_HASH_FN URI rather
# than raising on a duplicate registration, since it's always the same
# function. The tradeoff: nothing else in the process may register a
# different function at this exact URI and expect it to stick - acceptable
# here since TT_NS/DIRLANG_NS are starlight's own namespaces, not shared with
# any other library.
_register_tt_hash_function()

# SPARQL-callable functions computing SUBJECT()/PREDICATE()/OBJECT() of a
# triple-term value (its tt:HASH URIRef). Registered as `raw=True` custom
# functions (rdflib passes the already-evaluated Expr plus the live
# evaluation Context, giving access to ctx.graph for a real store lookup -
# confirmed via rdflib's own operators.Function/register_custom_function:
# raw functions receive (e, ctx), e.expr already holds evaluated arguments,
# and default_cast's own raw=True builtins use e.expr[0] as a plain already-
# resolved term the same way).
#
# Needed because the *previous* mechanism (rewriting SUBJECT(?tt) into a
# `?tt rdf:subject ?fresh_var .` graph-pattern *match*, still used by
# nothing after this change - see _rewrite_bind_accessors/
# _rewrite_triple_functions/_rewrite_group_content's inline handling, all
# updated to emit a call to these functions instead) only works when ?tt's
# value was already written to some graph. A value computed fresh via
# TT_HASH_FN in a BIND/VALUES/FILTER expression (e.g. `BIND(TRIPLE(:s,:p,:o)
# AS ?t)` with no matching WHERE-clause pattern at all) was never written
# anywhere, so that match can never succeed - confirmed as a real,
# reproducible bug via a W3C test (expr-2): SUBJECT(?t)/etc. on such a ?t
# silently produced zero rows instead of the correct answer. These
# functions check _TT_HASH_MEMO (populated by TT_HASH_FN for exactly this
# "constructed but never written" case - see remember_tt_hash's own
# docstring) first, falling back to a real ctx.graph dereference for a
# value that *was* written to the graph - covering both cases uniformly
# through one mechanism, rather than needing the rewriter to know in
# advance (impossible at text-rewrite time) which case a given occurrence
# is.
_TT_ACCESSOR_FN = {
    'SUBJECT':   f"<{TT_NS_PREFIX}fn/subject>",
    'PREDICATE': f"<{TT_NS_PREFIX}fn/predicate>",
    'OBJECT':    f"<{TT_NS_PREFIX}fn/object>",
}


def _register_tt_accessor_functions() -> None:
    from rdflib import URIRef
    from rdflib.namespace import RDF
    from rdflib.plugins.sparql.operators import register_custom_function
    from rdflib.plugins.sparql.sparql import SPARQLError

    from starlight.model.encoding import TT_NS, lookup_tt_hash

    def _make_accessor(label: str, index: int, pred):
        def _accessor(e, ctx):
            if len(e.expr) != 1:
                raise SPARQLError(f"{label}() requires exactly 1 argument")
            uri = e.expr[0]
            if not (isinstance(uri, URIRef) and str(uri).startswith(TT_NS)):
                raise SPARQLError(f"{label}(): argument is not a triple term")
            remembered = lookup_tt_hash(uri)
            if remembered is not None:
                return remembered[index]
            # ctx.graph, not always a plain QueryContext: evalFilter (unlike
            # evalExtend) always calls .eval() with a FrozenBindings
            # (ctx.forget(...)), which has no .graph of its own - only its
            # own .ctx attribute (FrozenBindings.__init__ stashes the real
            # QueryContext there) does. Confirmed as a real, reproducible
            # bug via a W3C test (expr-2): SUBJECT()/PREDICATE()/OBJECT()
            # called directly inside FILTER (as opposed to BIND, which
            # always passes a real QueryContext through unchanged) raised
            # AttributeError - masked by rdflib's own Result.bindings
            # property swallowing it and misreporting "no attribute
            # 'bindings'" instead, since an AttributeError escaping a
            # property getter makes Python fall back to __getattr__.
            # Same fallback pattern already established by this module's
            # sibling patch, evaluate_patches.py's
            # _patched_relational_expression, for the identical reason.
            graph = getattr(ctx, "graph", None) or getattr(getattr(ctx, "ctx", None), "graph", None)
            if graph is None:
                raise SPARQLError(f"{label}(): no graph available in this evaluation context")
            value = graph.value(uri, pred)
            if value is None:
                raise SPARQLError(f"{label}(): {uri!r} is not a known triple term")
            return value

        return _accessor

    for name, index, pred in (
        ('SUBJECT', 0, RDF.subject),
        ('PREDICATE', 1, RDF.predicate),
        ('OBJECT', 2, RDF.object),
    ):
        register_custom_function(
            URIRef(_TT_ACCESSOR_FN[name][1:-1]), _make_accessor(name, index, pred),
            override=True, raw=True,
        )


_register_tt_accessor_functions()

_TRIPLE_FUNC_RE = _re.compile(
    r'\b(SUBJECT|PREDICATE|OBJECT)\s*\(\s*([?$][A-Za-z_][A-Za-z0-9_]*)\s*\)',
    _re.IGNORECASE,
)

# SUBJECT/PREDICATE/OBJECT applied directly to a <<( )>> literal rather than
# a bound variable, e.g. SUBJECT(<<( :a :b :c )>>) - detected separately from
# _TRIPLE_FUNC_RE above (which only matches a bare-variable argument) and
# desugared by _rewrite_triple_accessor_literals(), which runs much earlier
# in the pipeline. Lookahead only, like _TRIPLE_CALL_RE - the actual call is
# consumed with _consume_balanced() since its content can itself contain
# nested parens/triple terms that a regex can't reliably bound.
_TRIPLE_ACCESSOR_LITERAL_RE = _re.compile(
    r'\b(SUBJECT|PREDICATE|OBJECT)\s*(?=\(\s*<<\()', _re.IGNORECASE,
)
_ACCESSOR_TO_INDEX = {'SUBJECT': 0, 'PREDICATE': 1, 'OBJECT': 2}
# isTRIPLE is the SPARQL 1.2 spec's own name (17.4.6); isTripleTerm is starlight's
# original, more descriptive spelling predating that section's stabilization. Both
# are accepted so a query copied verbatim from the spec or another RDF 1.2 tool
# works unchanged.
_IS_TT_RE = _re.compile(r'\bis(?:TripleTerm|Triple)\s*\(\s*([?$][A-Za-z_][A-Za-z0-9_]*)\s*\)', _re.IGNORECASE)

# TRIPLE(s, p, o) is the SPARQL 1.2 spec's function-call constructor for a triple
# term (17.4.6) - the spec treats it as equivalent to writing <<( s p o )>> as a
# term. Detected here only to decide whether the (costlier) rewrite pass below is
# needed; the actual conversion happens in _rewrite_triple_calls().
_TRIPLE_CALL_RE = _re.compile(r'\bTRIPLE\s*(?=\()', _re.IGNORECASE)

# VERSION "1.2" - the SPARQL 1.2 Query prologue's optional leading version
# directive (sec 4.3), e.g. the spec's own example:
#     VERSION "1.2"
#     PREFIX : <http://example/>
#     SELECT ...
# rdflib's SPARQL 1.1 parser has no notion of this directive at all and
# raises a ParseException on it unconditionally, even for this exact
# spec-example text - so it must always be stripped before further
# processing, in _strip_version_directive() below, regardless of whether any
# conformance warning ends up firing.
_VERSION_DIRECTIVE_RE = _re.compile(r'^\s*VERSION\s+([\'"])((?:(?!\1).)*)\1\s*', _re.IGNORECASE)


def _strip_version_directive(query: str) -> tuple[str, str | None]:
    """Strip a leading VERSION "label" prologue directive.

    Returns (query_with_directive_removed, label_or_None). See the RDF12
    conformance-warning wiring in _rewrite_sparql12_to_11_tracked, which
    uses the returned label - if any - to warn (never raise; see
    starlight.model.conformance) on an unrecognized label or a "1.2-basic"
    declaration contradicted by the query's actual content.
    """
    m = _VERSION_DIRECTIVE_RE.match(query)
    if not m:
        return query, None
    return query[m.end():], m.group(2)

# RDF 1.2 base-direction functions (SPARQL 1.2 Query sec 17.4.2), rewritten by
# _rewrite_dirlang_and_strlangdir() below. Unlike SUBJECT/PREDICATE/OBJECT,
# none of these need WHERE-clause pattern injection - they rewrite to plain
# expression built-ins (DATATYPE/STR/STRSTARTS/... or, for STRLANGDIR, the
# registered constructor function below) evaluated against the internal
# dirlang: datatype-URI encoding (see starlight.model.dirlangstring).
#
# STRLANGDIR is a SPARQL-callable function (registered like TT_HASH_FN) rather
# than a pure STRDT/IRI/CONCAT/LCASE expression: a plain expression can't
# validate its direction argument at all - it would silently build a
# well-formed-looking but wrong Literal, with no diagnostic. Registering a
# real function lets it validate at construction time and raise SPARQLError
# for a bad direction like "sideways" - which rdflib's evaluator (evalExtend,
# for BIND/SELECT-projection expressions) specifically catches and treats as
# "leave the variable unbound for this solution", the same "type error in an
# expression" semantics a real SPARQL 1.2 engine uses (confirmed directly
# against live Fuseki 5.5.0 and Oxigraph 0.5.9 2026-07-16: an invalid
# direction there doesn't abort the query or drop the row, it just leaves
# that one binding's variable missing). A plain ValueError wouldn't get this
# treatment - rdflib's evalExtend only catches SPARQLError specifically, so
# anything else propagates and aborts the *entire* query, discarding every
# other row too - confirmed as a real, avoidable difference from native
# engines, not a defensible one, so this isn't a "fail fast" tradeoff being
# kept deliberately; it's just matching what a real engine already does.
DIRLANG_CONSTRUCT_FN = f"<{DIRLANG_NS_PREFIX}fn/construct>"

# A word boundary before "LANG"/"hasLANG" never matches inside
# "LANGDIR"/"hasLANGDIR"/"STRLANGDIR" (no \b between contiguous letters), so
# these five names are mutually exclusive regardless of scan order - the
# recursive descent below only needs the earliest match among them.
_DIRLANG_FUNC_RES = {
    name: _re.compile(rf'\b{name}\s*(?=\()', _re.IGNORECASE)
    for name in ('STRLANGDIR', 'hasLANGDIR', 'LANGDIR', 'hasLANG', 'LANG')
}


def _register_dirlang_construct_function() -> None:
    from rdflib import URIRef, Literal
    from rdflib.plugins.sparql.operators import register_custom_function
    from rdflib.plugins.sparql.sparql import SPARQLError

    from starlight.model.encoding import encode_dirlang_datatype

    def _dirlang_construct_fn(lex, lang, direction):
        lang_str = str(lang).lower()
        dir_str = str(direction).lower()
        if dir_str not in ('ltr', 'rtl'):
            # SPARQLError specifically (not ValueError): this is what
            # rdflib's evaluator recognizes as a SPARQL expression type
            # error and converts to "unbound", matching native engines -
            # see the module-level comment above DIRLANG_CONSTRUCT_FN.
            raise SPARQLError(f'STRLANGDIR: direction must be "ltr" or "rtl", got {dir_str!r}')
        return Literal(str(lex), datatype=encode_dirlang_datatype(lang_str, dir_str))

    register_custom_function(URIRef(DIRLANG_CONSTRUCT_FN[1:-1]), _dirlang_construct_fn, override=True)


# Same deliberate import-time global-registry mutation as
# _register_tt_hash_function() above, and the same reasoning applies.
_register_dirlang_construct_function()


def _rewrite_dirlang_literals(query: str) -> str:
    """Rewrite RDF 1.2 "text"@lang--dir literal syntax, wherever it appears,
    into a call to the registered dirlang: constructor function.

    A literal written directly in a query (as opposed to a value read from
    already-stored data via a bound variable, which already works correctly)
    is never rewritten anywhere else in this module: LANGDIR()/STRLANGDIR()/
    etc. only touch the *function calls* wrapping their arguments, not the
    lexical form of a literal argument itself. Left alone, "hi"@en--rtl is
    handed to rdflib's SPARQL 1.1 parser as-is, which has no notion of the
    --dir suffix and raises a ParseException on the "--" it doesn't expect.

    Runs early, before anything else, so every later pass only ever sees
    plain SPARQL 1.1-parseable text. Emits a *directly typed literal*
    (``"text"^^<dirlang-encoded-datatype-uri>``), computed here at rewrite
    time via the exact same `{lang}--{direction}` URI shape
    `starlight.model.encoding.encode_dirlang_datatype` uses for storage -
    not a call to the registered dirlang: constructor function (used
    elsewhere in this module, for STRLANGDIR()'s *dynamic*-argument case,
    where the language/direction aren't known until evaluation time). A
    directly typed literal, unlike a function call, is valid SPARQL syntax
    in every position a literal can appear - term slots (VALUES rows,
    ordinary triple patterns) included, not just expression positions
    (BIND/FILTER). Confirmed as a real, previously-broken case via a W3C
    test (triple-on-str-literals): a "text"@lang--dir literal written
    directly inside a VALUES row produced a bare function-call token where
    SPARQL's DataBlockValue grammar requires an actual ground term,
    raising a ParseException at the VALUES keyword itself.
    """
    if '--' not in query:
        return query

    lang_dir_re = _re.compile(r'@([A-Za-z]+(?:-[A-Za-z0-9]+)*)--([A-Za-z]+)')
    result: list[str] = []
    i = 0
    n = len(query)
    while i < n:
        if query.startswith('#', i):
            comment_end = query.find('\n', i)
            if comment_end == -1:
                result.append(query[i:])
                break
            result.append(query[i:comment_end + 1])
            i = comment_end + 1
            continue

        if query.startswith('"""', i) or query.startswith("'''", i):
            token, j = _consume_string(query, i, query[i:i + 3])
        elif query[i] in ('"', "'"):
            token, j = _consume_string(query, i, query[i])
        else:
            result.append(query[i])
            i += 1
            continue

        m = lang_dir_re.match(query, j)
        if m:
            lang, direction = m.group(1).lower(), m.group(2).lower()
            result.append(f'{token}^^<{DIRLANG_NS_PREFIX}{lang}--{direction}>')
            i = m.end()
        else:
            result.append(token)
            i = j

    return ''.join(result)


def _dirlang_langdir(v: str) -> str:
    return (f'IF(STRSTARTS(STR(DATATYPE({v})), "{DIRLANG_NS_PREFIX}"), '
             f'STRAFTER(STR(DATATYPE({v})), "--"), "")')


def _dirlang_has_langdir(v: str) -> str:
    return f'STRSTARTS(STR(DATATYPE({v})), "{DIRLANG_NS_PREFIX}")'


def _dirlang_lang(v: str) -> str:
    return (f'IF(STRSTARTS(STR(DATATYPE({v})), "{DIRLANG_NS_PREFIX}"), '
             f'STRBEFORE(STRAFTER(STR(DATATYPE({v})), "{DIRLANG_NS_PREFIX}"), "--"), '
             f'LANG({v}))')


def _dirlang_has_lang(v: str) -> str:
    return f'(STRSTARTS(STR(DATATYPE({v})), "{DIRLANG_NS_PREFIX}") || (LANG({v}) != ""))'


_DIRLANG_UNARY_TEMPLATES = {
    'LANGDIR':     _dirlang_langdir,
    'hasLANGDIR':  _dirlang_has_langdir,
    'LANG':        _dirlang_lang,
    'hasLANG':     _dirlang_has_lang,
}


def _rewrite_dirlang_and_strlangdir(query: str) -> str:
    """Rewrite LANGDIR/hasLANGDIR/LANG/hasLANG/STRLANGDIR (SPARQL 1.2 Query
    sec 17.4.2) against the internal dirlang: datatype-URI encoding.

    Recursive descent (like _rewrite_triple_calls): each call's argument(s)
    are rewritten first, so nesting - e.g. ``LANGDIR(STRLANGDIR(...))`` or
    ``hasLANGDIR(IF(..., ?x, ?y))`` - resolves correctly, unlike a plain regex
    substitution which can only match a single bare variable argument.

    LANG()/hasLANG() are rewritten unconditionally whenever present (even in a
    query that never touches a dirLangString) - the rewritten form is a strict
    generalization: its IF-condition is simply false and it falls back to
    plain LANG(v)/"has an ordinary language tag" for every other literal.
    """
    result: list[str] = []
    i = 0
    while True:
        best_match = None
        best_name = None
        for name, pat in _DIRLANG_FUNC_RES.items():
            m = pat.search(query, i)
            if m is not None and (best_match is None or m.start() < best_match.start()):
                best_match = m
                best_name = name
        if best_match is None:
            result.append(query[i:])
            break

        result.append(query[i:best_match.start()])
        call_span, end = _consume_balanced(query, best_match.end(), '(', ')')
        inner = call_span[1:-1]

        if best_name == 'STRLANGDIR':
            args = _split_top_level_args(inner)
            if len(args) != 3:
                raise ValueError(f"STRLANGDIR() requires exactly 3 arguments: {query[best_match.start():end]}")
            lex, lang, direction = (_rewrite_dirlang_and_strlangdir(a) for a in args)
            result.append(f'{DIRLANG_CONSTRUCT_FN}({lex}, {lang}, {direction})')
        else:
            arg = _rewrite_dirlang_and_strlangdir(inner.strip())
            result.append(_DIRLANG_UNARY_TEMPLATES[best_name](arg))

        i = end
    return ''.join(result)

# BIND(SUBJECT(?tt) AS ?s)  →  BIND(<tt:fn/subject>(?tt) AS ?s)  (in-place, no outer injection)
# $tt/$s are equally valid SPARQL variable syntax (the sigils are interchangeable)
# and are the convention SHACL-SPARQL constraints use for $this/$value.
_BIND_ACCESSOR_RE = _re.compile(
    r'\bBIND\s*\(\s*(SUBJECT|PREDICATE|OBJECT)\s*\(\s*([?$][A-Za-z_]\w*)\s*\)\s+AS\s+([?$][A-Za-z_]\w*)\s*\)',
    _re.IGNORECASE,
)

# A SPARQL term: variable, full IRI, prefixed name, default-prefix name,
# quoted literal (simple), blank node, or rdf:type shorthand 'a'.
_T = (
    r'(?:'
    r'[?$][A-Za-z_]\w*'                                      # variable
    r'|<[^>]+>'                                              # full IRI
    r'|"[^"\\]*(?:\\.[^"\\]*)*"'                             # double-quoted literal
    r"|'[^'\\]*(?:\\.[^'\\]*)*'"                             # single-quoted literal
    r'|[A-Za-z_]\w*:[A-Za-z_]\w*'                           # prefixed name  prefix:local
    r'|:[A-Za-z_]\w*'                                        # default-prefix name  :local
    r'|_:[A-Za-z_]\w*'                                       # blank node
    r'|\ba\b'                                                # rdf:type shorthand
    r'|[+-]?(?:\d+\.?\d*|\d*\.\d+)(?:[eE][+-]?\d+)?'       # numeric literal
    r')'
)

# << s p o ~ reifier >> pred obj  — annotation subject with explicit reifier
#
# `<<`/`>>` boundaries use `\s*` (optional whitespace), not `\s+`: SPARQL's
# own tokenization doesn't require whitespace immediately after `<<` or
# immediately before/after `>>` (neither is a valid continuation character
# for whatever term follows/precedes), so `<<:a :b :c>> ?p ?o` (no space
# around the delimiters at all) is perfectly valid SPARQL syntax - and real,
# not contrived: the W3C SPARQL 1.2 test suite's own `basic-2.rq` fixture
# uses exactly this shape. Requiring `\s+` there was confirmed a real bug,
# not a simplification with no practical impact - it silently failed to
# rewrite (and therefore failed to parse at all) any query written this
# way, which turned out to be the majority of the affected fixtures once
# checked. `\s+` is kept between the *terms themselves* (s/p/o and the
# trailing pred/obj) - those genuinely do need separating whitespace, since
# e.g. two adjacent prefixed names with no space between them would
# tokenize as one.
#
# The bracket reifier-shorthand forms themselves (`<<s p o>>`/
# `<<s p o ~ r>>`) are NOT handled by a regex at all - see
# _consume_reifier_term/_rewrite_reifier_term below, wired into
# _rewrite_group_content's character scanner. A regex anchored on "subject
# position, immediately followed by pred+obj" (which is what used to live
# here) can't express "usable in ANY term position" - object, nested inside
# another reifier/triple term, or standing alone as a whole statement with
# no trailing pred/obj at all (`<<s p o ~ r>> .`) - all real shapes the W3C
# test suite exercises. The scanner-based approach handles all of them
# uniformly, the same way <<( )>> ground/pattern triple terms already are.

# s p o {| ap av ; ap2 av2 |}  — inline annotation block
_ANN_BLOCK_RE = _re.compile(
    rf'({_T})\s+({_T})\s+({_T})\s*\{{\|\s*(.*?)\s*\|\}}',
    _re.DOTALL,
)

# s p o ~?r  — reifier binding (tilde must be surrounded by whitespace)
_TILDE_RE = _re.compile(
    rf'({_T})\s+({_T})\s+({_T})\s+~\s+([?$][A-Za-z_]\w*)',
)


@dataclass
class _RewriteState:
    next_var_index: int = 0
    _content_cache: dict = field(default_factory=dict, init=False, repr=False)
    generated_vars: set  = field(default_factory=set,  init=False, repr=False)
    pending_binds: list  = field(default_factory=list, init=False, repr=False)
    in_construct_template: bool = field(default=False, init=False, repr=False)
    # BINDs for fully-ground (variable-free) TRIPLE()/<<( )>> values used as a
    # plain expression, not a graph-pattern term - see _rewrite_triple_term.
    # Unlike pending_binds (CONSTRUCT-template minting, relocated to the
    # *end* of the WHERE clause since it depends on that clause's own
    # bindings), these have no dependency on anything else in the query, so
    # they're hoisted to the very *start* of the WHERE clause instead: that's
    # the only placement that's guaranteed to precede every possible use of
    # the variable, including the containing statement itself (e.g.
    # `?stmt rdf:reifies TRIPLE(:a,:b,:c)` needs its BIND before that same
    # triple pattern, not after it).
    pending_ground_binds: list = field(default_factory=list, init=False, repr=False)

    def new_var(self) -> str:
        var_name = f"__tt{self.next_var_index}"
        self.next_var_index += 1
        self.generated_vars.add(var_name)
        return f"?{var_name}"

    def var_for_content(self, content_key: str) -> str:
        if content_key not in self._content_cache:
            self._content_cache[content_key] = self.new_var()
        return self._content_cache[content_key]


_CONSTRUCT_RE = _re.compile(r'\bCONSTRUCT\s*(?=\{)', _re.IGNORECASE)
_WHERE_RE = _re.compile(r'\bWHERE\s*(?=\{)', _re.IGNORECASE)
_CONSTRUCT_WHERE_SHORTHAND_RE = _re.compile(r'\bCONSTRUCT\s+WHERE\s*(?=\{)', _re.IGNORECASE)


def _try_split_construct_where(query: str):
    """Split ``... CONSTRUCT { template } WHERE { where } ...`` into
    ``(prologue, template_inner, where_inner, epilogue)`` - or, for the
    ``CONSTRUCT WHERE { pattern }`` shorthand (the pattern serves as *both*
    the WHERE clause and the template - SPARQL's own defined equivalence),
    ``(prologue, pattern, pattern, epilogue)``: the same source text
    returned as both halves, so the caller's already-existing two-pass
    rewrite (matching semantics for ``where_inner``, fresh-per-solution
    ``in_construct_template=True`` semantics for ``template_inner`` - see
    _rewrite_construct_query) runs on it twice independently, exactly as if
    it had been written out in the explicit two-block form. Confirmed
    necessary, not just convenient: before this, a WHERE-less split ran
    the entire shorthand as an ordinary (non-template) WHERE clause once,
    which - for an annotation block (``{| ap av |}``) inside it - used the
    WHERE-clause reifier-*matching* semantics for what is also the
    CONSTRUCT template's own reifier, instead of minting a fresh one for
    the template as ordinary CONSTRUCT semantics require for any
    otherwise-unbound blank-node-shaped template part. The official W3C
    SPARQL 1.2 fixture ``construct-5`` expects exactly two distinct
    reifiers for this shape (one from matching, one freshly constructed);
    the old single-pass behavior produced one shared node instead.

    Returns ``None`` for any other query form (SELECT/ASK/DESCRIBE, or a
    CONSTRUCT form this simple two-block split doesn't recognize) so callers
    can fall back to the single-pass rewrite unchanged.
    """
    m = _CONSTRUCT_RE.search(query)
    if m:
        try:
            brace_start = query.index('{', m.end())
            template_span, after_template = _consume_balanced(query, brace_start, '{', '}')

            wm = _WHERE_RE.search(query, after_template)
            if not wm or query[after_template:wm.start()].strip():
                return None

            where_brace_start = query.index('{', wm.end())
            where_span, after_where = _consume_balanced(query, where_brace_start, '{', '}')
        except ValueError:
            return None

        prologue = query[:m.start()]
        epilogue = query[after_where:]
        return prologue, template_span[1:-1], where_span[1:-1], epilogue

    sm = _CONSTRUCT_WHERE_SHORTHAND_RE.search(query)
    if sm:
        try:
            brace_start = query.index('{', sm.end())
            pattern_span, after_pattern = _consume_balanced(query, brace_start, '{', '}')
        except ValueError:
            return None

        prologue = query[:sm.start()]
        epilogue = query[after_pattern:]
        pattern_inner = pattern_span[1:-1]
        return prologue, pattern_inner, pattern_inner, epilogue

    return None


def _find_group_pattern_start(query: str) -> int | None:
    """Index just after the outermost group graph pattern's opening brace.

    Prefers an explicit ``WHERE {``. Falls back to the first ``{`` in the
    query when the WHERE keyword is absent - it's optional in SPARQL for
    SELECT/ASK/DESCRIBE (e.g. plain ``ASK { ... }``), and neither the
    prologue (BASE/PREFIX) nor a SELECT variable list/dataset clause can
    contain a brace, so the first one is always the group graph pattern's.
    Returns None only if the query has no ``{`` at all.

    Shared by every pass that needs to inject content at the very start of
    the WHERE clause: _inject_ground_binds_into_where (ground TRIPLE()/
    <<( )>> BINDs) and _rewrite_triple_functions (SUBJECT/PREDICATE/OBJECT
    binding triples for a SELECT-projection call). Both used to search for
    literal "WHERE {" text with no fallback, silently dropping their
    injected content on a WHERE-less query - fixed once here rather than
    per call site.
    """
    where_m = _re.search(r'\bWHERE\s*\{', query, _re.IGNORECASE)
    if where_m:
        return where_m.end()
    brace_m = _re.search(r'\{', query)
    return brace_m.end() if brace_m else None


def _find_group_pattern_end(query: str) -> int | None:
    """Index of the outermost group graph pattern's own matching closing
    brace - the companion to _find_group_pattern_start, for content that
    must be appended *after* everything already in the WHERE clause rather
    than prepended before it.

    Needed because a BIND, unlike a BGP triple match, is evaluated in
    sequence and must textually follow whatever pattern binds its own
    argument variable, or that variable is still unbound when the BIND
    runs. Confirmed as a real, reproducible regression (TestQ7,
    `SELECT ?who (SUBJECT(?tt) AS ?knower) WHERE { ?who :says ?tt . }`):
    _rewrite_triple_functions used to inject its accessor-function BIND at
    _find_group_pattern_start's position (the very start of WHERE, correct
    for the *previous* rdf:subject-match-pattern mechanism, which - like
    any BGP triple - joins order-independently) - placing
    `BIND(<tt:fn/subject>(?tt) AS ?__tt0)` *before* `?who :says ?tt .`
    itself, so ?tt was still unbound when the BIND evaluated, silently
    producing an unbound ?knower instead of raising.
    """
    start = _find_group_pattern_start(query)
    if start is None:
        return None
    _, end = _consume_balanced(query, start - 1, '{', '}')
    return end - 1


def _inject_ground_binds_into_where(query: str, state: "_RewriteState") -> str:
    """Insert state.pending_ground_binds right after the WHERE clause's own
    opening brace, so they precede everything else in the query - see
    _RewriteState.pending_ground_binds. Used for the SELECT/ASK/DESCRIBE
    path; _rewrite_construct_query handles the CONSTRUCT path itself, since
    it already assembles the WHERE clause text directly.
    """
    if not state.pending_ground_binds:
        return query
    insert_pos = _find_group_pattern_start(query)
    if insert_pos is None:
        state.pending_ground_binds.clear()
        return query
    prefix = "\n  " + "\n  ".join(state.pending_ground_binds) + "\n  "
    state.pending_ground_binds.clear()
    return query[:insert_pos] + prefix + query[insert_pos:]


def _rewrite_construct_query(query: str, state: "_RewriteState") -> str:
    """Rewrite a ``CONSTRUCT { template } WHERE { where }`` query.

    The WHERE clause is rewritten first so that any triple-term content
    already resolvable by matching existing data registers its variable
    before the template is processed. The template is then rewritten with
    ``state.in_construct_template`` set, so any triple-term content that
    appears *only* in the template (never matched in WHERE) gets a computed
    BIND — collected into ``state.pending_binds`` — instead of relying on a
    pre-existing match. Collected BINDs are spliced into the WHERE clause
    (since a CONSTRUCT template cannot itself contain a BIND), appended
    *after* the WHERE clause's own patterns rather than before them: a BIND's
    component variables (e.g. ``?z`` bound only via ordinary WHERE matching,
    not a constant) must already be bound by the time the BIND evaluates, or
    SPARQL silently drops that binding instead of erroring.

    ``state.pending_ground_binds`` (fully-ground TRIPLE()/<<( )>> values used
    as a plain expression - see _rewrite_triple_term) go the *opposite* way:
    prepended *before* the WHERE clause's own content, since they have no
    dependency on it and must be available to everything, including the
    WHERE clause's own patterns.
    """
    split = _try_split_construct_where(query)
    if split is None:
        query = _rewrite_block_forms(query, state, in_construct_template=False)
        return _inject_ground_binds_into_where(_rewrite_group_content(query, state), state)

    prologue, template_inner, where_inner, epilogue = split
    where_inner = _rewrite_block_forms(where_inner, state, in_construct_template=False)
    rewritten_where = _rewrite_group_content(where_inner, state, handle_funcs=True)
    state.in_construct_template = True
    template_inner = _rewrite_block_forms(template_inner, state, in_construct_template=True)
    rewritten_template = _rewrite_group_content(template_inner, state, handle_funcs=True)
    state.in_construct_template = False

    ground_prefix = ""
    if state.pending_ground_binds:
        ground_prefix = "\n  " + "\n  ".join(state.pending_ground_binds) + "\n  "
        state.pending_ground_binds.clear()

    bind_suffix = ""
    if state.pending_binds:
        bind_suffix = "\n  " + "\n  ".join(state.pending_binds) + "\n  "

    return f"{prologue}CONSTRUCT {{{rewritten_template}}} WHERE {{{ground_prefix}{rewritten_where}{bind_suffix}}}{epilogue}"


def _rewrite_triple_calls(query: str) -> str:
    """Rewrite ``TRIPLE(s, p, o)`` constructor calls to ``<<( s p o )>>``.

    Runs before every other pass so the rest of the pipeline only ever has to
    handle one spelling of a triple term - matching, nesting, and CONSTRUCT-
    template minting (``_rewrite_triple_term``) all apply unchanged to the
    result. Arguments are recursively converted first so a nested ``TRIPLE(...)``
    call (or a literal ``<<( )>>`` argument) is fully desugared before being
    wrapped, since the whitespace-splitting in ``_split_top_level_terms``
    treats an unconverted ``TRIPLE(a, b, c)`` argument as one opaque token
    rather than something to recurse into.
    """
    result: list[str] = []
    i = 0
    while True:
        m = _TRIPLE_CALL_RE.search(query, i)
        if not m:
            result.append(query[i:])
            break
        result.append(query[i:m.start()])
        call_span, end = _consume_balanced(query, m.end(), '(', ')')
        args = _split_top_level_args(call_span[1:-1])
        if len(args) != 3:
            raise ValueError(f"TRIPLE() requires exactly 3 arguments: {query[m.start():end]}")
        rewritten_args = [_rewrite_triple_calls(a) for a in args]
        result.append("<<( " + " ".join(rewritten_args) + " )>>")
        i = end
    return ''.join(result)


_VALUES_KEYWORD_RE = _re.compile(r'\bVALUES\b', _re.IGNORECASE)


def _consume_values_clause(text: str, start: int) -> tuple[str, int] | None:
    """Consume one ``VALUES (...) { ... }`` / ``VALUES ?v { ... }`` clause
    starting at the ``VALUES`` keyword (index ``start``). Returns
    ``(full_matched_text, end_index)``, or ``None`` if what follows
    ``VALUES`` isn't actually shaped like a values clause (defensive only -
    ``\\bVALUES\\b`` already rules out most false positives; this just
    avoids raising on genuinely malformed input, leaving it for the real
    SPARQL parser downstream to reject with a proper error)."""
    i = start + len('VALUES')
    while i < len(text) and text[i].isspace():
        i += 1
    if i >= len(text):
        return None
    if text[i] == '(':
        _, i = _consume_balanced(text, i, '(', ')')
    elif text[i] in ('?', '$'):
        i += 1
        while i < len(text) and (text[i].isalnum() or text[i] == '_'):
            i += 1
    else:
        return None
    while i < len(text) and text[i].isspace():
        i += 1
    if i >= len(text) or text[i] != '{':
        return None
    _, i = _consume_balanced(text, i, '{', '}')
    return text[start:i], i


def _rewrite_values_clause(clause: str) -> str | None:
    """Rewrite one ``VALUES`` clause (``clause`` is the full text starting
    at ``VALUES`` and ending after the matching ``}``, as returned by
    ``_consume_values_clause``) into an equivalent UNION-of-BIND-groups
    form, IF any row contains a ground triple term (``<<( )>>`` -
    ``TRIPLE(...)`` calls are already normalised to this spelling by the
    time this runs, see ``_rewrite_sparql12_to_11_tracked``'s call order).
    Returns ``None`` (caller keeps the clause verbatim) when no row
    contains one - the ordinary ``VALUES`` form is already correct
    SPARQL 1.1 and needs no rewriting at all.

    Why this is needed, not just a stylistic alternative: a VALUES row's
    values must each be a syntactically *ground* term (SPARQL's own
    ``DataBlockValue`` production is
    ``iri | RDFLiteral | NumericLiteral | BooleanLiteral | 'UNDEF'`` - no
    variable alternative at all). This module's usual strategy for a
    fully-ground triple term elsewhere (mint ``tt:fn/hash(...)`` as a
    fresh variable via a hoisted ``BIND``, then substitute that *variable*
    in place of the original ``<<( )>>`` text - see
    ``_rewrite_triple_term``'s "elif all_ground" branch) produces exactly
    that illegal shape when "in place" happens to be a VALUES row
    (``VALUES (?o) { (?__tt0) }`` is a syntax error: a bare variable is
    never a legal ``DataBlockValue``) - confirmed as a real, reproducible
    failure via the W3C SPARQL 1.2 test suite's `basic-8`/`basic-9`
    (``VALUES ?o { <<( :s :p "o" )>> ... }``), which is what surfaced this
    gap. ``VALUES`` is already defined to be semantics-equivalent to
    unioning each row's bindings as alternative solutions (the standard
    "``VALUES`` desugars to a ``UNION`` of ``BIND``s" reading) - rewriting
    to that form sidesteps the ``DataBlockValue`` restriction entirely,
    since a ``BIND``'s right-hand side is an ordinary *expression*
    position, where ``tt:fn/hash(...)`` already substitutes correctly in
    place with no hoisting at all (``_rewrite_triple_term``'s "elif
    is_expression" branch, reused completely unchanged by the rest of the
    pipeline once this function hands back BIND-shaped text - this
    function only reshapes the surrounding syntax; the per-term rewriting
    itself is whatever the rest of the pipeline already does correctly to
    any other expression-position triple term).
    """
    i = len('VALUES')
    while clause[i].isspace():
        i += 1
    parenthesized_vars = clause[i] == '('
    if parenthesized_vars:
        varlist_text, i = _consume_balanced(clause, i, '(', ')')
        variables = _split_top_level_terms(varlist_text[1:-1])
    else:
        j = i
        while not clause[j].isspace() and clause[j] != '{':
            j += 1
        variables = [clause[i:j]]
        i = j
    while clause[i].isspace():
        i += 1
    data_block_text, i = _consume_balanced(clause, i, '{', '}')
    data_inner = data_block_text[1:-1]

    if '<<(' not in data_inner:
        return None

    if parenthesized_vars:
        rows = []
        j = 0
        while j < len(data_inner):
            if data_inner[j].isspace():
                j += 1
                continue
            row_text, j = _consume_balanced(data_inner, j, '(', ')')
            rows.append(_split_top_level_terms(row_text[1:-1]))
    else:
        rows = [[tok] for tok in _split_top_level_terms(data_inner)]

    branches = []
    for row in rows:
        binds = []
        for var, val in zip(variables, row):
            if val.upper() == 'UNDEF':
                continue
            var_name = var if var.startswith(('?', '$')) else '?' + var
            binds.append(f'BIND({_inline_ground_triple_terms(val)} AS {var_name})')
        branches.append('{ ' + ' '.join(binds) + ' }')

    return '{ ' + ' UNION '.join(branches) + ' }'


def _inline_ground_triple_terms(token: str) -> str:
    """Recursively rewrite every ``<<( s p o )>>`` inside ``token`` to
    inline ``tt:fn/hash(s, p, o)`` text - with no hoisting to a top-level
    ``BIND`` and no sharing via ``state.pending_ground_binds``/
    ``_content_cache`` at all, unlike ``_rewrite_triple_term``'s own
    "elif all_ground" branch (see its comment for why that branch checks
    ``all_ground`` *before* ``is_expression``, and why this function exists
    as a separate, narrower path instead of just calling it).

    Used only by ``_rewrite_values_clause``, where it's not just an
    optimization but a correctness requirement: every value in a VALUES
    row is *already* guaranteed fully ground by SPARQL's own grammar
    (``DataBlockValue`` has no variable alternative), so there is never a
    matching-pattern case to consider here - but a hoisted, shared
    ``BIND(tt:fn/hash(...) AS ?__ttN)`` referenced from *inside* one of
    this function's UNION branches hits a real, confirmed rdflib evaluator
    bug: a ``BIND`` that reads an *earlier* hoisted ``BIND``'s variable,
    inside a ``UNION`` branch, followed by a join outside the union,
    produces duplicated/wrong results. Reproduced with plain, unmodified
    rdflib (``BIND(:v1 AS ?t). {{BIND(?t AS ?o)}UNION{...}} ?s :p ?o.``
    gives wrong results; inlining the value directly instead of `?t` gives
    the correct ones) - independent of anything starlight- or
    triple-term-specific, first surfaced via the W3C SPARQL 1.2 test suite
    (`basic-8`, triple terms inside VALUES). Each UNION branch generated by
    ``_rewrite_values_clause`` needs to be fully self-contained rather than
    referencing shared hoisted state, which is exactly what this function
    guarantees by never touching ``state`` at all.
    """
    token = token.strip()
    if not token.startswith('<<('):
        if token == 'a':
            # The bare "a" (rdf:type) predicate shorthand is only legal in
            # an actual triple-pattern predicate slot, never as a general
            # term/expression - confirmed a real, reproducible ParseException
            # via a W3C test (triple-on-triple-terms, VALUES row containing
            # <<(:x a :z)>>): embedding "a" verbatim as a tt:fn/hash(...)
            # argument produces `tt:fn/hash(:x, a, :z)`, which plain rdflib
            # rejects (`BIND(<fn>(:x, a, :z) AS ?x)` fails to parse
            # standalone too, confirmed independent of this VALUES-rewriting
            # path specifically).
            return '<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>'
        return token
    inner = token[3:-3].strip()
    parts = _split_top_level_terms(inner)
    if len(parts) != 3:
        raise ValueError(f"Triple term must contain exactly 3 terms: {token}")
    s, p, o = (_inline_ground_triple_terms(part) for part in parts)
    return f'{TT_HASH_FN}({s}, {p}, {o})'


def _rewrite_values_blocks(query: str) -> str:
    """Find every ``VALUES`` clause in ``query`` and, for each whose data
    block contains a ground triple term, replace it with an equivalent
    UNION-of-BIND-groups form via ``_rewrite_values_clause`` - see that
    function's own docstring for why. VALUES clauses with no triple term
    in any row are left completely untouched (the overwhelming majority -
    this pass is a no-op for any query that doesn't mix ``VALUES`` with
    ``<<( )>>``/``TRIPLE(...)``).

    Runs as an early, standalone pass - before the rest of this module's
    ``<<( )>>`` handling (``_rewrite_group_content`` et al.) - so that
    generic triple-term processing downstream only ever sees a triple term
    in a position it already handles correctly (an ordinary graph-pattern
    term slot, or - after this pass has run - a BIND's expression
    position), never inside a raw VALUES row it can't safely rewrite in
    place.

    Uses the same character-scanning conventions as the rest of this
    module (skip strings/IRIs/comments verbatim, everything else copied
    through) rather than a single regex, since ``VALUES`` can legitimately
    appear as a substring of other text (inside a string literal, an IRI,
    a comment) that must not be touched.
    """
    buffer: list[str] = []
    i = 0
    n = len(query)
    while i < n:
        if query.startswith('#', i):
            end = query.find('\n', i)
            end = n if end == -1 else end + 1
            buffer.append(query[i:end])
            i = end
            continue
        if query.startswith('"""', i) or query.startswith("'''", i):
            literal, i = _consume_string(query, i, query[i:i + 3])
            buffer.append(literal)
            continue
        if query[i] in {'"', "'"}:
            literal, i = _consume_string(query, i, query[i])
            buffer.append(literal)
            continue
        if query[i] == '<' and not query.startswith("<<(", i):
            iri, i = _consume_iri(query, i)
            buffer.append(iri)
            continue
        if _VALUES_KEYWORD_RE.match(query, i):
            consumed = _consume_values_clause(query, i)
            if consumed is not None:
                clause_text, end = consumed
                rewritten = _rewrite_values_clause(clause_text)
                buffer.append(rewritten if rewritten is not None else clause_text)
                i = end
                continue
        buffer.append(query[i])
        i += 1
    return ''.join(buffer)


def _rewrite_triple_accessor_literals(query: str) -> str:
    """Desugar SUBJECT/PREDICATE/OBJECT(<<( s p o )>>) - the accessor applied
    directly to a triple-term literal - to the relevant component (s, p, or
    o) directly.

    This is an exact, pass-order-independent textual equivalence, unlike
    SUBJECT(?tt): a bound-variable argument needs a store lookup (an injected
    ?tt rdf:subject ?fresh binding pattern - see _rewrite_triple_functions /
    _rewrite_group_content's inline handling), but a literal <<( s p o )>>
    argument already spells out all three components right there in the
    query text, so there is nothing to look up - SUBJECT(<<( s p o )>>) means
    exactly s. Runs right after _rewrite_triple_calls (so a TRIPLE(...)-
    spelled argument has already become <<( )>> uniformly) and before every
    other pass, so a component that is itself a nested <<( )>>/TRIPLE(...)
    is left as plain text at this call's former position for the normal
    downstream passes to rewrite - the same as if it had been written
    directly there to begin with. Also means this works identically whether
    the call sits inside a WHERE-clause block or bare in a SELECT projection,
    with no separate "outside any block yet" injection logic needed at all
    (contrast the bare-variable case's _rewrite_triple_functions).

    Found missing via property-based fuzz testing 2026-07-17 - the bare-
    variable-only _TRIPLE_FUNC_RE regex silently failed to match this form,
    reaching rdflib's SPARQL 1.1 parser as literal, unparseable text.
    """
    result: list[str] = []
    i = 0
    while True:
        m = _TRIPLE_ACCESSOR_LITERAL_RE.search(query, i)
        if not m:
            result.append(query[i:])
            break
        result.append(query[i:m.start()])
        paren_start = query.index('(', m.end())
        call_span, end = _consume_balanced(query, paren_start, '(', ')')
        inner = call_span[1:-1].strip()
        tt_token, tt_end = _consume_triple_term(inner, 0)
        if tt_end != len(inner):
            raise ValueError(
                f"{m.group(1).upper()}() applied to a triple-term literal takes exactly "
                f"one <<( )>> argument: {query[m.start():end]}"
            )
        parts = _split_top_level_terms(tt_token[3:-3].strip())
        if len(parts) != 3:
            raise ValueError(f"Triple term must contain exactly 3 terms: {tt_token}")
        idx = _ACCESSOR_TO_INDEX[m.group(1).upper()]
        result.append(_rewrite_triple_accessor_literals(parts[idx]))
        i = end
    return ''.join(result)


def _split_top_level_args(text: str) -> list[str]:
    """Split a ``TRIPLE(...)`` argument list on top-level commas.

    Mirrors ``_split_top_level_terms`` (which splits on whitespace for
    ``<<( )>>`` content) but splits on ``,`` instead, since function-call
    arguments are comma-separated. Strings, IRIs, and nested ``<<( )>>``
    triple terms are treated as atomic; parens/brackets are depth-tracked so
    a comma inside a nested call or list isn't mistaken for an argument
    separator.
    """
    parts: list[str] = []
    current: list[str] = []
    i = 0
    depth = 0

    while i < len(text):
        if text.startswith('"""', i) or text.startswith("'''", i):
            literal, i = _consume_string(text, i, text[i:i + 3])
            current.append(literal)
            continue

        if text[i] in {'"', "'"}:
            literal, i = _consume_string(text, i, text[i])
            current.append(literal)
            continue

        if text[i] == '<' and not text.startswith("<<(", i):
            iri, i = _consume_iri(text, i)
            current.append(iri)
            continue

        if text.startswith("<<(", i):
            triple_term, i = _consume_triple_term(text, i)
            current.append(triple_term)
            continue

        if text[i] in '([':
            depth += 1
        elif text[i] in ')]':
            depth -= 1

        if text[i] == ',' and depth == 0:
            parts.append(''.join(current).strip())
            current.clear()
            i += 1
            continue

        current.append(text[i])
        i += 1

    if current:
        parts.append(''.join(current).strip())
    return [part for part in parts if part]


def _rewrite_sparql12_to_11_tracked(query: str) -> tuple[str, frozenset]:
    """Internal rewriter that also returns the set of generated variable names.

    Returns ``(rewritten_query, generated_tt_vars)`` where ``generated_tt_vars``
    is a ``frozenset[str]`` of rdflib ``Variable`` name strings (without ``?``)
    that were generated by this call, e.g. ``frozenset({'__tt0', '__tt1'})``.
    Callers that only need the string should use ``rewrite_sparql12_to_11``.
    """
    query, declared_version = _strip_version_directive(query)
    # Captured before _rewrite_dirlang_literals runs, since that pass rewrites
    # away the "--" in a literal "text"@lang--dir - this is the precise
    # signal that the query directly contains a dirLangString value (as
    # opposed to merely calling a LANGDIR-family function on some bound
    # variable that might hold any kind of literal).
    uses_dirlangstring = '--' in query
    query = _rewrite_dirlang_literals(query)

    if _TRIPLE_CALL_RE.search(query):
        query = _rewrite_triple_calls(query)

    if '<<(' in query and _VALUES_KEYWORD_RE.search(query):
        # Must run after _rewrite_triple_calls (so a TRIPLE(...)-spelled
        # VALUES row value is already <<( )>> by now, matching what
        # _rewrite_values_clause's detection looks for) and before every
        # other pass below that would otherwise treat a triple term inside
        # a VALUES row as an ordinary graph-pattern term slot - see
        # _rewrite_values_blocks's own docstring for why that's wrong.
        query = _rewrite_values_blocks(query)

    if _TRIPLE_ACCESSOR_LITERAL_RE.search(query):
        # Must run after _rewrite_triple_calls (so a TRIPLE(...)-spelled
        # argument is already <<( )>> by now) and before needs_tt/needs_func
        # are computed below, so those flags reflect what's actually left in
        # the query rather than a SUBJECT(<<( )>>) call this pass already
        # resolved away.
        query = _rewrite_triple_accessor_literals(query)

    if 'LANG' in query.upper():
        query = _rewrite_dirlang_and_strlangdir(query)

    needs_tt   = "<<(" in query
    needs_bare_reifier = _re.search(r'<<(?!\()', query) is not None
    needs_ann  = needs_bare_reifier or '{|' in query or '~' in query
    needs_func = _TRIPLE_FUNC_RE.search(query) is not None
    needs_istt = _IS_TT_RE.search(query) is not None

    if declared_version is not None:
        from starlight.model.conformance import check_version_conformance
        check_version_conformance(
            declared_version,
            uses_triple_term=needs_tt or needs_ann,
            uses_dirlangstring=uses_dirlangstring,
            context='SPARQL query',
        )

    if not (needs_tt or needs_ann or needs_func or needs_istt):
        return query, frozenset()

    state = _RewriteState()

    if needs_func:
        # BIND(SUBJECT(?tt) AS ?s) → ?tt <rdf:subject> ?s  in-place.
        # This keeps the binding triple inside the same group graph pattern (and
        # named-graph scope) as the original BIND, which is essential for correct
        # evaluation when the BIND appears inside a GRAPH { } clause.
        query = _rewrite_bind_accessors(query)
        needs_func = bool(_TRIPLE_FUNC_RE.search(query))

    # Run _rewrite_group_content (and, for a CONSTRUCT query, the {| |}
    # annotation-block form - see _rewrite_construct_query, which calls
    # _rewrite_block_forms itself with the right in_construct_template
    # value for each of the template/WHERE clauses) whenever there are
    # <<( )>>/bare <<...>> patterns, {| |} blocks, or non-BIND function
    # calls needing inline injection inside blocks. This must run BEFORE
    # _rewrite_tilde_form below - see that function's own docstring for why
    # (its regex has no awareness of surrounding << >> brackets, so an
    # unresolved bracket reifier term's own internal " ~ " would otherwise
    # be misread as the bracket-free "s p o ~ r" form).
    if needs_tt or needs_bare_reifier or needs_func or '{|' in query or "<<(" in query:
        query = _rewrite_construct_query(query, state)

    if '~' in query:
        query = _rewrite_tilde_form(query, state)

    # After inline handling, any remaining SUBJECT/PREDICATE/OBJECT calls live
    # outside {…} blocks (SELECT projections, HAVING, ORDER BY).  Inject their
    # binding triples at the WHERE level — correct for those clause positions.
    if needs_func and _TRIPLE_FUNC_RE.search(query):
        query = _rewrite_triple_functions(query, state)

    if _IS_TT_RE.search(query):
        # Runs last, after <<( )>>/TRIPLE(...) have already been reduced to
        # plain variables by the passes above - isTRIPLE's argument must be a
        # bare variable for this regex to match (isTRIPLE(?x)), and a nested
        # triple-term expression like isTRIPLE(TRIPLE(...)) only becomes that
        # shape once the inner call has been desugared and its component
        # triples correctly placed inside the WHERE clause. Running this
        # earlier would either miss the nested case entirely or - worse -
        # leave a literal "isTRIPLE(...)" in the output after the inner
        # <<( )>> is separately rewritten to a variable, which the SPARQL 1.1
        # engine doesn't recognize as a function at all.
        #
        # Deliberately re-searching here rather than trusting the
        # early-computed needs_istt: that flag reflects the *pre-rewrite*
        # text, where a nested-expression argument doesn't match this regex
        # yet, so it can be False here even when this block needs to run -
        # needs_istt still matters for the early bail-out check above (a
        # query where isTRIPLE(?x) - bare variable - is the *only* SPARQL 1.2
        # construct present).
        #
        # STRSTARTS alone is sufficient and correct: every TT_NS-prefixed
        # URIRef is created exclusively by _intern_tt() (or its addN/parser
        # equivalents), which always writes the rdf:subject/predicate/object
        # encoding triples in the same call before returning the URI - so
        # there is no state where such a URI exists without them. Every other
        # TT_NS membership check in this codebase (_is_encoding_triple,
        # _restore, _build_registry_from_store) already relies on the prefix
        # alone with no separate existence check, so this matches established
        # invariants, not a new assumption.
        #
        # This used to also wrap an `EXISTS { ?x rdf:subject [] } &&` guard,
        # which is unnecessary per the above - and actively wrong to keep: it
        # hits a genuine rdflib limitation (confirmed independently of this
        # codebase, with a bare rdflib.Graph()) where `EXISTS {...} && ...`
        # raises deep inside the evaluator ("What do I do with this
        # CompValue?") when used in a `(expr AS ?var)` position (SELECT
        # projection or BIND), while the identical expression works fine
        # inside FILTER(...). Every prior isTripleTerm()/isTRIPLE() test only
        # ever used it inside FILTER, so this was never triggered before.
        query = _IS_TT_RE.sub(
            lambda m: f'STRSTARTS(STR({m.group(1)}), "{TT_NS_PREFIX}")',
            query,
        )

    if state.generated_vars:
        query = _exclude_generated_vars_from_select_star(query, state.generated_vars)

    return query, frozenset(state.generated_vars)


_SELECT_STAR_RE = _re.compile(r'\bSELECT\s+((?:DISTINCT|REDUCED)\s+)?\*', _re.IGNORECASE)
_VAR_RE = _re.compile(r'[?$][A-Za-z_]\w*')


def _exclude_generated_vars_from_select_star(query: str, generated_vars: set) -> str:
    """A bare ``SELECT *`` (with or without ``DISTINCT``/``REDUCED``)
    projects every variable in scope - which, after this module's own
    rewriting has run, now includes whatever internal bookkeeping
    variables (``?__tt0``, ``?__tt1``, ...) it minted along the way for
    triple-term/annotation/reifier handling. Those were never part of the
    original query and must not leak into the result set. Confirmed a
    real, reproducible bug via the W3C SPARQL 1.2 test suite's own
    `basic-3` (`SELECT * { <<?s :b :c>> ?p ?o }`): the actual result rows
    included `?__tt0`/`?__tt1` bindings alongside the real `?s`/`?p`/`?o`
    ones, which the expected results obviously never contain.

    Fixed by expanding a bare `*` into an explicit variable list -
    every variable mentioned anywhere in the (already fully rewritten)
    query text, in first-occurrence order, excluding `generated_vars` -
    rather than trying to suppress the generated variables some other way
    after the fact (SPARQL has no per-variable "hide from *" mechanism,
    so an explicit list is the only way to reproduce "everything the user
    originally wrote, nothing this rewriter separately introduced").

    A no-op if there's no bare `SELECT *` in `query` at all (the far more
    common case - a query with an explicit projection list was never
    affected by this in the first place, since a rewriter-generated
    variable was never going to appear in a list it didn't write).
    """
    m = _SELECT_STAR_RE.search(query)
    if m is None:
        return query

    seen: list[str] = []
    seen_set: set = set()
    for var_match in _VAR_RE.finditer(query):
        name = var_match.group(0)
        bare = name[1:]
        if bare in generated_vars or name in seen_set:
            continue
        seen_set.add(name)
        seen.append(name)

    if not seen:
        # Every variable in the query was internally generated (e.g. a
        # fully-ground pattern with no user-visible variables at all) -
        # SPARQL doesn't allow an empty projection list, so there's
        # nothing sensible to substitute; leave "*" as-is rather than
        # produce invalid syntax. (This also means the query would have
        # produced a result set entirely of internal bookkeeping vars
        # before this fix - an edge case, not the common one this fix
        # targets.)
        return query

    replacement = " ".join(seen)
    return query[: m.start()] + m.group(0).replace("*", replacement, 1) + query[m.end() :]


def rewrite_sparql12_to_11(query: str) -> str:
    """Rewrite SPARQL 1.2 triple-term syntax to SPARQL 1.1.

    Handles:
    - ``<<( s p o )>>`` triple-term patterns in WHERE clauses
    - ``<< s p o >> pred obj`` annotation subject patterns (anonymous reifier)
    - ``<< s p o ~ reifier >> pred obj`` annotation subject with explicit reifier
    - ``s p o {| ap av ; ... |}`` inline annotation blocks
    - ``s p o ~?r`` reifier-binding shorthand
    - ``SUBJECT(?tt)``, ``PREDICATE(?tt)``, ``OBJECT(?tt)`` function calls
    - ``isTripleTerm(?x)`` filter function, and its spec-name alias ``isTRIPLE(?x)``
    - ``TRIPLE(s, p, o)`` constructor function - the spec's function-call form of
      ``<<( s p o )>>``; desugared to it before any other rewriting runs
    - ``LANGDIR(?x)``, ``hasLANGDIR(?x)``, ``STRLANGDIR(lex, lang, dir)`` - RDF 1.2
      base-direction functions (SPARQL 1.2 Query sec 17.4.2), evaluated against
      the internal dirlang: datatype-URI encoding of a DirLangString
    - ``LANG(?x)`` and ``hasLANG(?x)`` are upgraded so both also recognize a
      DirLangString the same way they already handle a plain rdf:langString

    Queries with none of these forms are returned unchanged.
    """
    return _rewrite_sparql12_to_11_tracked(query)[0]


def _rewrite_bind_accessors(query: str) -> str:
    """Rewrite BIND(SUBJECT(?tt) AS ?s) → BIND(<tt:fn/subject>(?tt) AS ?s).

    A function call substituted in place like this needs no positional
    awareness at all (unlike the old rdf:subject-*match*-pattern rewrite
    this replaced, whose own docstring used to explain why the matching
    triple had to be injected *inside* the same group graph pattern as the
    BIND - essential there because rdflib's SPARQL engine doesn't propagate
    outer-scope variable bindings into a BIND/FILTER expression inside a
    named-graph scope, so a matching pattern placed anywhere else could
    silently fail to see ?tt's value at all). See the module-level comment
    above _TT_ACCESSOR_FN for why a real function, not a pattern match, is
    needed in the first place.
    """
    def _replace(m: _re.Match) -> str:
        func = m.group(1).upper()
        tt_var, result_var = m.group(2), m.group(3)
        return f"BIND({_TT_ACCESSOR_FN[func]}({tt_var}) AS {result_var})"
    return _BIND_ACCESSOR_RE.sub(_replace, query)


def _rewrite_tilde_form(query: str, state: _RewriteState) -> str:
    """Pre-pass: convert the plain-text (bracket-free) ``s p o ~?r``
    annotation form into an explicit ``rdf:reifies <<( )>>`` pattern.

    The bracket forms (``<<s p o>>``, ``<<s p o ~ r>>``) are a completely
    separate mechanism - see _consume_reifier_term/_rewrite_reifier_term,
    wired into _rewrite_group_content's character scanner - and MUST already
    have run (see _rewrite_sparql12_to_11_tracked's call order) before this
    function does, precisely so `_TILDE_RE` below - which has no awareness
    of surrounding `<<`/`>>` at all - can't accidentally match the
    ``?s ?p ?o ~ ?t`` *inside* an unresolved ``<< ?s ?p ?o ~ ?t >>``, which
    would silently strip the bracket form's semantics (it does NOT assert
    the base triple, unlike this one) and leave stray `<<`/`>>` characters
    in the output.

    No CONSTRUCT-template variant is needed (unlike _rewrite_block_forms
    below) - nothing in the current test set uses this bracket-free form
    inside a CONSTRUCT template, only in ordinary WHERE-clause position.

    Limitation: term matching uses a simplified regex that covers variables,
    prefixed names, full IRIs, and simple literals. Complex literals with
    embedded spaces or datatype suffixes are not handled.
    """
    # Component patterns first (bind ?__tt via the selective rdf:subject index),
    # then find reifiers, then validate the base-triple assertion last.
    # Putting s p o last avoids a full triple-scan when s/p/o are variables.
    def _tilde(m: _re.Match) -> str:
        s, p, o, r = m.group(1), m.group(2), m.group(3), m.group(4)
        tt_var = state.new_var()
        return (f"{tt_var} {RDF_SUBJECT} {s} .\n  "
                f"{tt_var} {RDF_PREDICATE} {p} .\n  "
                f"{tt_var} {RDF_OBJECT} {o} .\n  "
                f"{r} {RDF_REIFIES} {tt_var} .\n  "
                f"{s} {p} {o}")

    return _TILDE_RE.sub(_tilde, query)


def _rewrite_block_forms(text: str, state: _RewriteState, in_construct_template: bool = False) -> str:
    """Pre-pass: convert ``s p o {| ap av ; ... |}`` inline annotation
    blocks into an explicit ``rdf:reifies <<( )>>`` pattern.

    Called separately on the WHERE clause (``in_construct_template=False``)
    and, when present, the CONSTRUCT template (``in_construct_template=True``)
    by _rewrite_construct_query - NOT as one global pass over the whole
    reassembled query text the way _rewrite_tilde_form is, because unlike
    that form this one genuinely behaves differently in the two positions:
    a CONSTRUCT template has no WHERE-clause match to bind tt_var/r_var
    from (the template may be minting a reification that never existed in
    the data), so both must be *computed* via a relocated BIND, mirroring
    _rewrite_reifier_term's own in_construct_template branch - see that
    function's docstring for why BNODE() is the right per-solution-scoped
    choice for the anonymous reifier. The base triple assertion
    (``{s} {p} {o}``) is still emitted unconditionally either way: even in
    template position, this statement is the ONLY place that base triple
    is written (confirmed via construct-4's own expected output, which
    includes both the plain base triple and its annotation).

    Same regex-simplification limitation as _rewrite_tilde_form above.
    """
    def _ann_block(m: _re.Match) -> str:
        s, p, o = m.group(1), m.group(2), m.group(3)
        pairs = [pair.strip() for pair in m.group(4).split(';') if pair.strip()]
        r_var = state.new_var()
        tt_var = state.new_var()
        if in_construct_template:
            state.pending_binds.append(
                f"BIND({TT_HASH_FN}({s}, {p}, {o}) AS {tt_var})"
            )
            state.pending_binds.append(f"BIND(BNODE() AS {r_var})")
        parts = [f"{tt_var} {RDF_SUBJECT} {s}",
                 f"{tt_var} {RDF_PREDICATE} {p}",
                 f"{tt_var} {RDF_OBJECT} {o}",
                 f"{r_var} {RDF_REIFIES} {tt_var}"]
        parts.extend(f"{r_var} {pair}" for pair in pairs)
        parts.append(f"{s} {p} {o}")
        return " .\n  ".join(parts)

    return _ANN_BLOCK_RE.sub(_ann_block, text)


def _rewrite_triple_functions(query: str, state: _RewriteState) -> str:
    """Rewrite SUBJECT/PREDICATE/OBJECT(?var) calls.

    Each call is replaced with a fresh variable; a BIND computing it via
    the registered accessor function (see the module-level comment above
    _TT_ACCESSOR_FN) is injected at the *end* of the outermost WHERE { }
    body, after everything already there, so the variable it reads (?var)
    is already bound by the time the BIND evaluates - see
    _find_group_pattern_end's own docstring for the regression this fixes
    (unlike the *previous* mechanism this replaced - an order-independent
    rdf:subject *match* pattern - a BIND is evaluated in sequence and must
    textually follow whatever binds its own argument).
    """
    injected: list[str] = []

    def replacer(m: _re.Match) -> str:
        fn = _TT_ACCESSOR_FN[m.group(1).upper()]
        src_var = m.group(2)
        new_var = state.new_var()
        injected.append(f"BIND({fn}({src_var}) AS {new_var})")
        return new_var

    result = _TRIPLE_FUNC_RE.sub(replacer, query)

    if injected:
        insert_pos = _find_group_pattern_end(result)
        if insert_pos is not None:
            result = (result[:insert_pos]
                      + "\n  " + "\n  ".join(injected) + "\n  "
                      + result[insert_pos:])

    return result


def _rewrite_group_content(text: str, state: _RewriteState,
                           handle_funcs: bool = False,
                           in_expression: bool = False) -> str:
    """Rewrite <<( )>> triple-term patterns and, when handle_funcs is True,
    SUBJECT/PREDICATE/OBJECT function calls inline within the current block.

    handle_funcs is False at the outermost call (SELECT/WHERE level) so that
    accessor functions in SELECT projections are left for _rewrite_triple_functions
    to handle via WHERE-level injection (correct for that clause position).
    It is set to True for all recursive calls (inside { } blocks) so that
    functions inside GRAPH, OPTIONAL, UNION etc. inject their binding triple
    within the same named-graph scope rather than at the outer WHERE level.

    in_expression (together with the local paren_depth counter below) tracks
    whether the text currently being scanned sits inside an *expression*
    context - BIND(...), a SELECT projection's (expr AS ?var), FILTER(...),
    or a nested function-call argument - as opposed to a bare graph-pattern
    term slot (a subject/predicate/object position in an ordinary `s p o .`
    statement). A non-ground <<( )>>/TRIPLE(...) occurrence needs *different*
    semantics in each: a pattern-term slot means "find an existing triple
    term whose components match", but an expression position means "compute
    the triple-term value from whatever these sub-expressions evaluate to
    right now" - there is nothing to match against, since the value may never
    have been written to the graph at all (see _rewrite_triple_term's
    "elif is_expression" branch). SPARQL has no bare-parenthesized grouping
    for graph patterns themselves (only for expressions and for `{ }` group
    graph patterns, which don't affect this counter), so "currently inside an
    unclosed '('" reliably identifies an expression context with purely
    string-level scanning - no full grammar parse needed.
    """
    result: list[str] = []
    pending_patterns: list[str] = []
    buffer: list[str] = []
    i = 0
    paren_depth = 0

    while i < len(text):
        if text.startswith("#", i):
            comment_end = text.find("\n", i)
            if comment_end == -1:
                buffer.append(text[i:])
                i = len(text)
            else:
                buffer.append(text[i:comment_end + 1])
                i = comment_end + 1
            continue

        if text.startswith('"""', i) or text.startswith("'''", i):
            literal, i = _consume_string(text, i, text[i:i + 3])
            buffer.append(literal)
            continue

        if text[i] in {'"', "'"}:
            literal, i = _consume_string(text, i, text[i])
            buffer.append(literal)
            continue

        if text[i] == '<' and not text.startswith("<<", i):
            iri, i = _consume_iri(text, i)
            buffer.append(iri)
            continue

        if text.startswith("<<(", i):
            is_expr_here = in_expression or paren_depth > 0
            replacement, patterns, i, _is_ground = _rewrite_triple_term(
                text, i, state, is_expression=is_expr_here,
            )
            buffer.append(replacement)
            pending_patterns.extend(patterns)
            continue

        if text.startswith("<<", i):
            is_expr_here = in_expression or paren_depth > 0
            if _at_statement_start(text, i) and _stmt_end_follows(text, _consume_reifier_term(text, i)[1]):
                # The ENTIRE current statement is just this reifier term
                # (e.g. "<< ?s ?p ?o ~ ?t >> ." with nothing before or
                # after it) - there is no enclosing "s p o ." triple whose
                # trailing "." the usual pending_patterns-flush-at-'.'
                # mechanism (below) can piggyback on, since substituting
                # just the reifier in place would leave a syntactically
                # invalid dangling "?t ." behind. Emit the match patterns
                # directly as this statement's own content instead - each
                # already self-terminated with " .", so this is already a
                # complete, valid TriplesBlock on its own.
                _, patterns, i = _rewrite_reifier_term(text, i, state, is_expression=is_expr_here)
                buffer.append(_emit_pending_patterns(patterns))
                j = i
                while j < len(text) and text[j].isspace():
                    j += 1
                if j < len(text) and text[j] == '.':
                    i = j + 1
                continue
            replacement, patterns, i = _rewrite_reifier_term(
                text, i, state, is_expression=is_expr_here,
            )
            buffer.append(replacement)
            pending_patterns.extend(patterns)
            continue

        # Inline SUBJECT/PREDICATE/OBJECT detection — only inside blocks.
        # Injects a BIND computing the accessor function (see the
        # module-level comment above _TT_ACCESSOR_FN) into the current
        # group graph pattern via pending_patterns, which is emitted at the
        # next '.' or '}' boundary. This keeps the BIND in the same
        # named-graph scope as the function call - essential when it's
        # inside a GRAPH { } clause (rdflib's SPARQL engine doesn't
        # propagate outer-scope variable bindings into a BIND/FILTER
        # expression inside a named-graph scope).
        if handle_funcs and text[i].isalpha():
            m = _TRIPLE_FUNC_RE.match(text, i)
            if m:
                func = m.group(1).upper()
                tt_var = m.group(2)
                fresh_var = state.new_var()
                buffer.append(fresh_var)
                pending_patterns.append(f"BIND({_TT_ACCESSOR_FN[func]}({tt_var}) AS {fresh_var})")
                i = m.end()
                continue

        if text[i] == '{':
            inner, i = _consume_balanced(text, i, '{', '}')
            inner_content = inner[1:-1]
            if pending_patterns:
                # A <<( )>> (or a TRIPLE(...) desugared to one) appeared before
                # any {} block at all - e.g. in a bare SELECT projection with
                # no BIND, ahead of the WHERE clause. There is nowhere upstream
                # of this point to put its matching pattern (SPARQL has no
                # constraint syntax outside a graph pattern block), so it must
                # go inside the first block encountered, which for a
                # SELECT/ASK/DESCRIBE query is the WHERE clause itself.
                # Leaving it to fall through to the end-of-string flush below
                # would land it after the query's closing brace - invalid syntax.
                inner_content = _emit_pending_patterns(pending_patterns) + inner_content
                pending_patterns.clear()
            rewritten = _rewrite_group_content(
                inner_content, state, handle_funcs=True,
                in_expression=(in_expression or paren_depth > 0),
            )
            buffer.append('{')
            buffer.append(rewritten)
            buffer.append('}')
            continue

        if text[i] == '.' and pending_patterns:
            buffer.append(text[i])
            buffer.append(_emit_pending_patterns(pending_patterns))
            i += 1
            pending_patterns.clear()
            continue

        if text[i] == '}' and pending_patterns:
            buffer.append(' .')
            buffer.append(_emit_pending_patterns(pending_patterns))
            pending_patterns.clear()
            buffer.append(text[i])
            i += 1
            continue

        if text[i] == '(':
            paren_depth += 1
        elif text[i] == ')':
            paren_depth = max(paren_depth - 1, 0)

        buffer.append(text[i])
        i += 1

    if pending_patterns:
        buffer.append(' .')
        buffer.append(_emit_pending_patterns(pending_patterns))

    result.extend(buffer)
    return ''.join(result)


def _rewrite_triple_term(
    text: str, start: int, state: _RewriteState, is_expression: bool = False
) -> tuple[str, list[str], int, bool]:
    """Rewrite one <<( s p o )>> occurrence. Returns (tt_var, patterns, end,
    is_ground) where is_ground is True iff s, p, and o are all variable-free
    (recursively, for a nested triple term) - see the "elif all_ground"
    branch below for what that unlocks.

    is_expression (see _rewrite_group_content's docstring for how it's
    computed) marks that this occurrence sits inside an expression context
    (BIND/FILTER/SELECT-projection/nested function argument) rather than a
    graph-pattern term slot - see the "elif is_expression" branch below.
    """
    token, end = _consume_triple_term(text, start)
    inner = token[3:-3].strip()
    parts = _split_top_level_terms(inner)
    if len(parts) != 3:
        raise ValueError(f"Triple term must contain exactly 3 terms: {token}")

    subject_token, subject_patterns, subject_ground = _rewrite_term(parts[0], state, is_expression)
    predicate_token, predicate_patterns, predicate_ground = _rewrite_term(parts[1], state, is_expression)
    object_token, object_patterns, object_ground = _rewrite_term(parts[2], state, is_expression)
    all_ground = subject_ground and predicate_ground and object_ground

    content_key = f"{subject_token} {predicate_token} {object_token}"
    is_new = content_key not in state._content_cache
    tt_var = state.var_for_content(content_key)

    patterns = []
    patterns.extend(subject_patterns)
    patterns.extend(predicate_patterns)
    patterns.extend(object_patterns)

    if state.in_construct_template:
        if is_new:
            # No WHERE-clause occurrence of this triple term exists to bind
            # tt_var from — mint it deterministically instead of requiring it
            # to already be registered in the graph. Collected separately
            # since a CONSTRUCT template cannot itself contain a BIND; the
            # caller relocates these into the WHERE clause.
            state.pending_binds.append(
                f"BIND({TT_HASH_FN}({subject_token}, {predicate_token}, {object_token}) AS {tt_var})"
            )
        # The constructed *output* graph needs its own encoding triples for
        # this value regardless of is_new (harmless if repeated - CONSTRUCT
        # naturally deduplicates identical output triples).
        patterns.append(f"{tt_var} {RDF_SUBJECT} {subject_token} .")
        patterns.append(f"{tt_var} {RDF_PREDICATE} {predicate_token} .")
        patterns.append(f"{tt_var} {RDF_OBJECT} {object_token} .")
    elif all_ground:
        # Fully ground (no variables anywhere, recursively): this is a value,
        # like a literal IRI, not a lookup - it must always construct
        # successfully regardless of whether it was ever written to the
        # graph, and must never have the side effect of writing anything (a
        # read-only SELECT/ASK/FILTER must stay read-only). Routed to
        # state.pending_ground_binds (hoisted to the top of the WHERE clause
        # by the caller) rather than appended to `patterns` here: unlike the
        # rdf:subject/predicate/object matching patterns in the branches
        # below - which are order-independent, just another triple pattern
        # joined into the same basic graph pattern - a BIND is evaluated in
        # sequence and must textually precede anything that reads tt_var,
        # which this function's local "defer to the next '.' or '}'"
        # placement can't guarantee: e.g. for
        # `?stmt rdf:reifies TRIPLE(:a,:b,:c)`, tt_var is read by the very
        # statement being rewritten, immediately at this position.
        #
        # Checked before is_expression (not after - tried swapping the two
        # once, see git history if curious) so that e.g.
        # `isTRIPLE(TRIPLE(a,b,c))` still desugars to `isTRIPLE(?__tt0)` -
        # a bare-variable argument, which is what _IS_TT_RE's own regex
        # requires to recognize and rewrite it (it only matches
        # `isTRIPLE([?$]var)`, never a nested function-call argument).
        # Swapping the order breaks that specific downstream consumer
        # (confirmed: caused test_is_triple_of_nested_triple_constructor
        # and several sibling tests to regress) even though it would have
        # been the more locally-obvious fix for a different, narrower
        # problem - see _rewrite_values_clause's own docstring for how that
        # problem (a real rdflib evaluator bug involving a hoisted BIND
        # variable referenced inside a UNION branch) is actually fixed
        # instead, entirely inside VALUES-clause handling, without touching
        # this function's existing, relied-upon branch order at all.
        if is_new:
            state.pending_ground_binds.append(
                f"BIND({TT_HASH_FN}({subject_token}, {predicate_token}, {object_token}) AS {tt_var}) ."
            )
    elif is_expression:
        # Non-ground (contains a variable), but used as a plain expression -
        # not a graph-pattern term slot. There is no WHERE-clause pattern to
        # match here (the else branch's rdf:subject/predicate/object lookup
        # would require this exact triple term to already be registered in
        # the store, which it may never have been - e.g. TRIPLE(?a0, ?a1,
        # ?a2) with ?a0/?a1/?a2 bound only via initBindings, no matching
        # WHERE pattern at all). An expression position already accepts an
        # arbitrary SPARQL expression syntactically (unlike a bare
        # subject/object slot, which requires an actual term), so substitute
        # the hash-function call directly in place instead of minting a
        # fresh variable + hoisted BIND: its arguments resolve against
        # whatever bindings are already in scope at evaluation time, exactly
        # like any other function call embedded in that same expression.
        return (
            f"{TT_HASH_FN}({subject_token}, {predicate_token}, {object_token})",
            patterns,
            end,
            all_ground,
        )
    else:
        patterns.append(f"{tt_var} {RDF_SUBJECT} {subject_token} .")
        patterns.append(f"{tt_var} {RDF_PREDICATE} {predicate_token} .")
        patterns.append(f"{tt_var} {RDF_OBJECT} {object_token} .")

    return tt_var, patterns, end, all_ground


def _rewrite_reifier_term(
    text: str, start: int, state: _RewriteState, is_expression: bool = False
) -> tuple[str, list[str], int]:
    """Rewrite one bare ``<<s p o>>``/``<<s p o ~ r>>`` reifier-shorthand
    occurrence. Returns (replacement, patterns, end) where `replacement` is
    always the *reifier* - a fresh variable, or the given one after ``~`` -
    never the underlying triple term's own tt_var. That's not an
    implementation detail: a triple term only ever appears as the OBJECT of
    the internal ``rdf:reifies`` triple these patterns assert; nowhere else
    is it a legal substitutable value for this syntax (unlike a ground
    ``<<( s p o )>>``, which IS itself a value - see _rewrite_triple_term).

    Unlike _rewrite_triple_term, there's no content-cache/dedup here:
    `<<s p o>>` used twice is "some (possibly different) reifier of (s,p,o)"
    each time, not a shared value, so each occurrence always mints its own
    fresh tt_var/reifier variable.
    """
    token, end = _consume_reifier_term(text, start)
    inner = token[2:-2].strip()
    tokens = _split_top_level_terms(inner)
    if len(tokens) == 3:
        s_raw, p_raw, o_raw = tokens
        explicit_reifier = None
    elif len(tokens) == 5 and tokens[3] == '~':
        s_raw, p_raw, o_raw, _, explicit_reifier = tokens
    else:
        raise ValueError(f"Reifier term must be '<<s p o>>' or '<<s p o ~ r>>': {token}")

    subject_token, subject_patterns, _ = _rewrite_term(s_raw, state, is_expression)
    predicate_token, predicate_patterns, _ = _rewrite_term(p_raw, state, is_expression)
    object_token, object_patterns, _ = _rewrite_term(o_raw, state, is_expression)

    patterns = []
    patterns.extend(subject_patterns)
    patterns.extend(predicate_patterns)
    patterns.extend(object_patterns)

    tt_var = state.new_var()
    r_token = explicit_reifier if explicit_reifier is not None else state.new_var()

    if state.in_construct_template:
        # Mirrors _rewrite_triple_term's own in_construct_template branch:
        # there is no WHERE-clause occurrence to match tt_var/r_token from
        # (the template may be minting a reification that never existed
        # anywhere in the data), so both must be *computed*, not matched.
        # BNODE() is the standard SPARQL 1.1 builtin for "a fresh blank node,
        # scoped per output solution the same way an ordinary blank node
        # written directly in a CONSTRUCT template would be" - exactly the
        # scoping an anonymous reifier needs here.
        state.pending_binds.append(
            f"BIND({TT_HASH_FN}({subject_token}, {predicate_token}, {object_token}) AS {tt_var})"
        )
        if explicit_reifier is None:
            state.pending_binds.append(f"BIND(BNODE() AS {r_token})")
    patterns.append(f"{tt_var} {RDF_SUBJECT} {subject_token} .")
    patterns.append(f"{tt_var} {RDF_PREDICATE} {predicate_token} .")
    patterns.append(f"{tt_var} {RDF_OBJECT} {object_token} .")
    patterns.append(f"{r_token} {RDF_REIFIES} {tt_var} .")

    return r_token, patterns, end


def _at_statement_start(text: str, pos: int) -> bool:
    """True if, scanning backward from `pos` over whitespace, the nearest
    non-whitespace character is a statement/block boundary ('.' or '{') or
    there isn't one (start of text) - i.e. nothing has been written for the
    *current* statement yet. Combined with _stmt_end_follows, this is how
    _rewrite_group_content tells "<<s p o ~ r>> ." (the entire statement is
    just the reifier term - see _rewrite_group_content's own handling) apart
    from "<<s p o>> pred obj ." (reifier term as an ordinary leading subject,
    with more to come) or "?s ?p <<s p o>> ." (reifier term as an object -
    not the start of its statement at all)."""
    j = pos - 1
    while j >= 0 and text[j].isspace():
        j -= 1
    return j < 0 or text[j] in '.{'


def _stmt_end_follows(text: str, pos: int) -> bool:
    """True if, scanning forward from `pos` over whitespace, the next
    character is a statement/block boundary ('.' or '}') or there isn't one
    (end of text) - see _at_statement_start."""
    j = pos
    while j < len(text) and text[j].isspace():
        j += 1
    return j >= len(text) or text[j] in '.}'


def _rewrite_term(term: str, state: _RewriteState, is_expression: bool = False) -> tuple[str, list[str], bool]:
    stripped = term.strip()
    if stripped.startswith("<<("):
        replacement, patterns, _, is_ground = _rewrite_triple_term(stripped, 0, state, is_expression)
        return replacement, patterns, is_ground
    if stripped.startswith("<<"):
        # Bare <<s p o>>/<<s p o ~ r>> reifier-shorthand term - always
        # substitutes to the reifier (a fresh variable, or the given one),
        # never to a ground/pre-computable value the way <<( )>> can - see
        # _rewrite_reifier_term. "not ground" is the conservative, always-
        # correct answer here even when every one of s/p/o and an explicit
        # reifier are themselves ground: nothing currently needs treating
        # that narrower case as ground too.
        replacement, patterns, _ = _rewrite_reifier_term(stripped, 0, state, is_expression)
        return replacement, patterns, False
    # A blank node - either a labelled `_:x` (what the sparql1_2_to_rdf
    # project's own algebra-regenerated text always uses for an anonymous
    # reifier - see the W3C eval-triple-terms/pattern-6 fixture, which
    # motivated this check) or an anonymous `[...]`/`[]` - is, like a
    # variable, something that must be *matched* against whatever already
    # exists in the data, never something with a fixed, computable value:
    # a query's own blank node labels are existentially-quantified pattern
    # variables scoped to that query, per SPARQL's own semantics, not a
    # constant the way a ground IRI/Literal is. Treating one as "ground"
    # here previously let it reach _rewrite_triple_term's "elif all_ground"
    # branch, which tries to *compute* this triple term's hash via
    # `BIND(<tt#fn/hash>(_:x, ...) AS ...)` - but a blank node can never be
    # a legal function-call argument in SPARQL at all (confirmed via a
    # minimal, plain-rdflib reproduction: `BIND(<urn:fn>(_:b) AS ?x)` fails
    # to parse), so this produced unparseable rewritten text whenever a
    # triple term's own subject/object happened to be a blank node -
    # reproducibly via pattern-6's `<< <<:s :p2 :o>> :p3 :z>> :q ?q` (the
    # reification shorthand's own anonymous reifier for the inner
    # `<<:s :p2 :o>>` becomes exactly this kind of blank node once
    # round-tripped through the sparql1_2_to_rdf project's own RDF algebra
    # encoding).
    is_ground = not (
        stripped.startswith('?') or stripped.startswith('$')
        or stripped.startswith('_:') or stripped.startswith('[')
    )
    return stripped, [], is_ground


def _emit_pending_patterns(patterns: list[str]) -> str:
    return "\n  " + "\n  ".join(patterns) + "\n"


def _split_top_level_terms(text: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    i = 0
    depth_paren = 0
    depth_bracket = 0

    while i < len(text):
        if text.startswith('"""', i) or text.startswith("'''", i):
            literal, i = _consume_string(text, i, text[i:i + 3])
            current.append(literal)
            continue

        if text[i] in {'"', "'"}:
            literal, i = _consume_string(text, i, text[i])
            current.append(literal)
            continue

        if text[i] == '<' and not text.startswith("<<", i):
            iri, i = _consume_iri(text, i)
            current.append(iri)
            continue

        if text.startswith("<<(", i):
            triple_term, i = _consume_triple_term(text, i)
            current.append(triple_term)
            continue

        if text.startswith("<<", i):
            reifier_term, i = _consume_reifier_term(text, i)
            current.append(reifier_term)
            continue

        if text[i] == '(':
            depth_paren += 1
        elif text[i] == ')':
            depth_paren = max(depth_paren - 1, 0)
        elif text[i] == '[':
            depth_bracket += 1
        elif text[i] == ']':
            depth_bracket = max(depth_bracket - 1, 0)

        if text[i].isspace() and depth_paren == 0 and depth_bracket == 0:
            if current:
                parts.append(''.join(current).strip())
                current.clear()
            i += 1
            continue

        current.append(text[i])
        i += 1

    if current:
        parts.append(''.join(current).strip())
    return [part for part in parts if part]


def _consume_triple_term(text: str, start: int) -> tuple[str, int]:
    if not text.startswith("<<(", start):
        raise ValueError("Triple term must start with '<<('")
    i = start + 3
    depth = 1

    while i < len(text):
        if text.startswith('"""', i) or text.startswith("'''", i):
            _, i = _consume_string(text, i, text[i:i + 3])
            continue

        if text[i] in {'"', "'"}:
            _, i = _consume_string(text, i, text[i])
            continue

        if text[i] == '<' and not text.startswith("<<(", i):
            _, i = _consume_iri(text, i)
            continue

        if text.startswith("<<(", i):
            depth += 1
            i += 3
            continue

        if text.startswith(")>>", i):
            depth -= 1
            i += 3
            if depth == 0:
                return text[start:i], i
            continue

        i += 1

    raise ValueError("Unterminated triple term")


def _consume_reifier_term(text: str, start: int) -> tuple[str, int]:
    """Consume one bare ``<<...>>`` reifier-shorthand occurrence starting at
    `start` (``text[start:start+2] == '<<'``, and NOT immediately followed by
    ``(`` - that's _consume_triple_term's ground/pattern ``<<( )>>`` form
    instead, a completely different production). Mirrors
    _consume_triple_term's own nesting/string/IRI handling, extended to also
    recognize a nested BARE reifier term (not just a nested ground ``<<( )>>``
    one) inside its own content - real W3C test data nests both kinds, e.g.
    ``<< <<:s :p2 :o>> :p3 :z>>`` (bare nested inside bare) and
    ``<<?s ?p <<( ?st ?pt ?ot )>> >>`` (ground nested inside bare)."""
    if not (text.startswith("<<", start) and not text.startswith("<<(", start)):
        raise ValueError("Reifier term must start with '<<' (not '<<(')")
    i = start + 2
    depth = 1

    while i < len(text):
        if text.startswith('"""', i) or text.startswith("'''", i):
            _, i = _consume_string(text, i, text[i:i + 3])
            continue

        if text[i] in {'"', "'"}:
            _, i = _consume_string(text, i, text[i])
            continue

        if text[i] == '<' and not text.startswith("<<", i):
            _, i = _consume_iri(text, i)
            continue

        if text.startswith("<<(", i):
            _, i = _consume_triple_term(text, i)
            continue

        if text.startswith(">>", i):
            depth -= 1
            i += 2
            if depth == 0:
                return text[start:i], i
            continue

        if text.startswith("<<", i):
            depth += 1
            i += 2
            continue

        i += 1

    raise ValueError("Unterminated reifier term")


def _consume_balanced(text: str, start: int, opener: str, closer: str) -> tuple[str, int]:
    if text[start] != opener:
        raise ValueError(f"Expected {opener!r}")
    i = start + 1
    depth = 1

    while i < len(text):
        if text.startswith('"""', i) or text.startswith("'''", i):
            _, i = _consume_string(text, i, text[i:i + 3])
            continue

        if text[i] in {'"', "'"}:
            _, i = _consume_string(text, i, text[i])
            continue

        if text[i] == '<' and not text.startswith("<<(", i):
            _, i = _consume_iri(text, i)
            continue

        if text.startswith("<<(", i):
            _, i = _consume_triple_term(text, i)
            continue

        if text[i] == opener:
            depth += 1
        elif text[i] == closer:
            depth -= 1
            if depth == 0:
                return text[start:i + 1], i + 1
        i += 1

    raise ValueError(f"Unterminated {opener}{closer} block")


def _consume_string(text: str, start: int, delimiter: str) -> tuple[str, int]:
    i = start + len(delimiter)
    while i < len(text):
        if text.startswith('\\', i):
            i += 2
            continue
        if text.startswith(delimiter, i):
            i += len(delimiter)
            return text[start:i], i
        i += 1
    raise ValueError("Unterminated string literal")


def _consume_iri(text: str, start: int) -> tuple[str, int]:
    i = start + 1
    while i < len(text):
        if text.startswith('\\', i):
            i += 2
            continue
        if text[i] == '>':
            return text[start:i + 1], i + 1
        i += 1

    raise ValueError("Unterminated IRI")