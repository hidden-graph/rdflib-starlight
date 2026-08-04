"""Targeted compatibility shim for a confirmed bug in plain rdflib's own
SPARQL evaluator (``rdflib.plugins.sparql.evaluate``) - not the algebra
translator (see ``algebra_translator_patches.py`` for those) and not the
arithmetic/numeric-function evaluation bugs (see ``operator_patches.py``).
See ``docs/rdflib-upstream-issues.md`` issue 5 for the full write-up,
including the standalone plain-rdflib reproduction and the root-cause trace
this patch is based on.

This is the most important of the patches in this package to have applied
correctly: unlike the algebra-translator bugs (which fail loudly, with a
``ParseException`` or similar on the malformed regenerated text) and the
arithmetic bugs (wrong but well-formed output), this one silently produces
wrong query *results* with no error or warning at all.

Same idempotent apply-once pattern as ``operator_patches.py``/
``algebra_translator_patches.py``.
"""

from __future__ import annotations

from rdflib import Variable
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
