# rdflib Upstream Issues

*Last reviewed: 2026-08-03*

Bugs found in plain `rdflib` (https://github.com/RDFLib/rdflib) while building this repo's own SPARQL 1.2 support on top of it. Every reproduction below uses only plain `rdflib`, no `starlight`/`rdflib-starlight` code at all, so each is reproducible standalone against a stock `rdflib` install. All confirmed against `rdflib` 7.6.0 (the version this project currently pins).

## Status Summary

All six issues are planned to be reported upstream - each a clean, unambiguous, spec-mapping or self-consistency bug with a minimal plain-`rdflib` reproduction. None has been filed yet (no existing GitHub issue/PR search performed yet - do that before actually opening any). All six now have a real fix applied *in this repo* (not just an avoidance workaround) - see the table below for which module each lives in. This repo's own SPARQL query pipeline is intended to route every query through this project's SPARQL 1.2 → algebra → `translateAlgebra`-based regeneration path, not just a downstream test suite, so all six are patched here directly rather than left as point-avoidances in one consumer's own code.

| # | Issue | Reporting upstream? | Fix in this repo |
| --- | --- | --- | --- |
| 1 | `MultiplicativeExpression` (`*`/`/`) never applies SPARQL 1.1's numeric type-promotion rules | **Yes** (not yet filed) | `starlight/query/operator_patches.py::patch_multiplicative_expression_type_promotion` |
| 2 | `Builtin_CEIL`/`Builtin_FLOOR`/`Builtin_ROUND` (and whole-number division) lose XSD decimal's canonical lexical form | **Yes** (not yet filed) | `starlight/query/operator_patches.py::patch_decimal_result_lexical_form` |
| 3 | `_AlgebraTranslator`'s `BGP` branch emits text its own parser can't re-parse (blank-node adjacency) | **Yes** (not yet filed) | `starlight/query/algebra_translator_patches.py::patch_algebra_translator_bugs` (also independently fixed in the downstream `sparql1.2_to_rdf` project's own serializer, which doesn't fall through to this repo's patched method for this branch) |
| 4 | `translateAlgebra` mis-nests `UNION` branches that each contain a subquery + `BIND` | **Yes** (not yet filed) | `starlight/query/algebra_translator_patches.py::patch_algebra_translator_bugs` |
| 5 | Evaluator bug: a `BIND` referencing an earlier hoisted `BIND`'s variable, inside a `UNION` branch, followed by a join, gives duplicated/wrong results | **Yes** (not yet filed) | `starlight/query/evaluate_patches.py::patch_evalextend_forgotten_bind_vars` (real fix, not just the avoidance `_inline_ground_triple_terms` used before this) |
| 6 | `RelationalExpression`'s list-handling guard is inverted (`isinstance(list, type(node.other))`), so multi-value `IN`/`NOT IN` always crashes `translateAlgebra` | **Yes** (not yet filed) | `starlight/query/algebra_translator_patches.py::patch_algebra_translator_bugs` (also independently fixed in the downstream `sparql1.2_to_rdf` project's own serializer, which doesn't fall through to this repo's patched method for this branch) |

Issues 1-2 were found while triaging the W3C SHACL 1.2 test suite's remaining failures in the downstream `starShacl`/`pyshacl-starlight` project (that suite's own `node-expr/shnex-sparql/{multiply,divide,ceil,floor,round}.ttl` and `sparql/rules/rectangle-*.ttl` fixtures) - see that repo's `docs/starlight-upstream-change-log.md` 2026-08-01 entries for the full downstream-impact writeup.

Issues 3-6 were found while building RDF 1.2 triple-term support in the downstream `sparql1.2_to_rdf` project (which extends rdflib's own grammar/algebra rather than depending on this repo's text-rewrite pipeline for its own representation - see that project's `CLAUDE.md`) and, for issue 5 specifically, while fixing this repo's own `sparql12_to_11.py` rewriter's handling of a triple term inside a `VALUES` clause (see this repo's `CHANGELOG.md`/git history around 2026-08-03). All four are now patched directly in this repo (`starlight/query/algebra_translator_patches.py` for 3/4/6, `starlight/query/evaluate_patches.py` for 5), applied eagerly at import time the same way issues 1-2 already were - not just left as downstream-only workarounds, since this repo's own pipeline is expected to exercise all of these paths going forward.

## How To Use

Each entry uses this structure - the `##` heading plus `###` subheadings - so it can be pasted directly into a GitHub issue with minimal editing (title = the `##` heading text, body = everything from "rdflib version" through "Suggested fix"; "Status" is doc-only tracking, not part of the issue body):

- `## Issue N - <title> (found <date>)`
- `**rdflib version:** <version> (<file/function>)`
- `### Description`
- `### Reproduction` (minimal, plain `rdflib`)
- `### Expected behavior`
- `### Actual behavior`
- `### Suspected root cause`
- `### Impact`
- `### Suggested fix`
- `### Possible workaround`
- `### Status` (`found`, `reported` + issue link, `fixed upstream`)

## Entries

| # | Title | Found |
| --- | --- | --- |
| 1 | `MultiplicativeExpression` doesn't apply SPARQL 1.1's numeric type-promotion rules for `*` | 2026-08-01 |
| 2 | `CEIL`/`FLOOR`/`ROUND`/whole-number division construct a non-canonical `xsd:decimal` lexical form | 2026-08-01 |
| 3 | `_AlgebraTranslator`'s `BGP` branch emits text its own parser can't re-parse (blank-node adjacency) | 2026-08-03 |
| 4 | `translateAlgebra` mis-nests `UNION` branches that each contain a subquery + `BIND` | 2026-08-03 |
| 5 | A `BIND` referencing an earlier hoisted `BIND`'s variable, inside a `UNION` branch, followed by a join, gives duplicated/wrong results | 2026-08-03 |
| 6 | `RelationalExpression`'s list-handling guard is inverted, so multi-value `IN`/`NOT IN` always crashes `translateAlgebra` | 2026-08-03 |

## Issue 1 - `MultiplicativeExpression` doesn't apply SPARQL 1.1's numeric type-promotion rules for `*` (found 2026-08-01)

**rdflib version:** 7.6.0 (`rdflib/plugins/sparql/operators.py::MultiplicativeExpression`)

### Description

SPARQL 1.1's numeric operator mapping (following XPath/XQuery Functions and Operators' `op:numeric-multiply`) defines `xs:integer * xs:integer` as producing `xs:integer` - integer is closed under multiplication. rdflib's own `AdditiveExpression` (`+`/`-`) gets this right: it computes a promoted result datatype via `type_promotion(dt, term.datatype)` and constructs the final value as `Literal(res, datatype=dt)`. `MultiplicativeExpression` does not do this at all - it always accumulates the result via Python's `Decimal(...)`, then returns a bare `Literal(res)` with no explicit `datatype=`, letting rdflib infer the datatype purely from the Python value's own type. Since the accumulator is always a `Decimal`, the result is always `xsd:decimal`, regardless of what datatype the actual operands had.

### Reproduction

```python
from rdflib import Graph, Literal, XSD

g = Graph()
result = list(g.query(
    "SELECT (?a * ?b AS ?r) WHERE {}",
    initBindings={"a": Literal(6, datatype=XSD.integer), "b": Literal(7, datatype=XSD.integer)},
))[0][0]
print(result, result.datatype)
```

### Expected behavior

`42` with datatype `http://www.w3.org/2001/XMLSchema#integer` - matching SPARQL 1.1's own type-promotion table, and matching what `6 + 7` (via the sibling `AdditiveExpression`) already correctly does.

### Actual behavior

```
42 http://www.w3.org/2001/XMLSchema#decimal
```

Confirmed independently against two other real SPARQL engines evaluating the identical query over the identical bindings: Apache Jena's ARQ (via Fuseki 5.5+) and Oxigraph both return `xsd:integer`, matching the expected behavior above - only rdflib's own evaluator gets this wrong.

### Suspected root cause

```python
def MultiplicativeExpression(e, ctx):
    expr = e.expr
    other = e.other
    if other is None:
        return expr
    try:
        res: Union[Decimal, float]
        res = Decimal(numeric(expr))
        for op, f in zip(e.op, other):
            f = numeric(f)
            if type(f) == float:
                res = float(res)
            if op == "*":
                res *= f
            else:
                res /= f
    except (InvalidOperation, ZeroDivisionError):
        raise SPARQLError("divide by 0")
    return Literal(res)
```

Compare with `AdditiveExpression`, a few lines below in the same file, which tracks `dt = type_promotion(dt, term.datatype)` per operand and returns `Literal(res, datatype=dt)` - `MultiplicativeExpression` never does either of these.

### Impact

Any SPARQL query computing `xs:integer * xs:integer` (a `BIND`, a `CONSTRUCT` template, a `SELECT` projection expression) gets an incorrectly-typed result - `xsd:decimal` instead of `xsd:integer` - with no error or warning. Under RDF 1.2's literal term-equality rules (exact datatype and lexical form match required, not just value equality), this also means the resulting literal is not term-equal to what a spec-conformant computation would produce, breaking any downstream comparison that relies on exact term equality.

### Suggested fix

Track a promoted result datatype the same way `AdditiveExpression` already does, and pass it explicitly to the final `Literal(...)` call:

```python
def MultiplicativeExpression(e, ctx):
    expr = e.expr
    other = e.other
    if other is None:
        return expr
    try:
        res: Union[Decimal, float]
        res = Decimal(numeric(expr))
        dt = expr.datatype
        for op, f in zip(e.op, other):
            n = numeric(f)
            if type(n) == float:
                res = float(res)
            if op == "*":
                res *= n
                dt = type_promotion(dt, f.datatype)
            else:
                res /= n
                # op:numeric-divide always promotes to at least xsd:decimal,
                # even for two integers - type_promotion(integer, integer)
                # alone would incorrectly keep xsd:integer here.
                promoted = type_promotion(dt, f.datatype)
                dt = XSD.decimal if promoted == XSD.integer else promoted
    except (InvalidOperation, ZeroDivisionError):
        raise SPARQLError("divide by 0")
    return Literal(res, datatype=dt)
```

### Possible workaround

Monkeypatch the specific `Comp` grammar-node object inside rdflib's already-built pyparsing SPARQL grammar tree (`rdflib.plugins.sparql.parser.MultiplicativeExpression.setEvalFn(...)`) with a corrected implementation - `Comp.postParse` reads `self.evalfn` fresh on every query parse (a mutable instance attribute, not a closure baked in at grammar-definition time), so this takes effect for every future `.query()` call without touching rdflib's own installed files. See `starlight/query/operator_patches.py::patch_multiplicative_expression_type_promotion` in this repo for a full implementation.

### Status

Found 2026-08-01 while triaging the downstream `starShacl` project's W3C SHACL 1.2 test suite failures. Reporting upstream planned, not yet filed. Worked around in this repo (`starlight/query/operator_patches.py`) in the meantime.

## Issue 2 - `CEIL`/`FLOOR`/`ROUND`/whole-number division construct a non-canonical `xsd:decimal` lexical form (found 2026-08-01)

**rdflib version:** 7.6.0 (`rdflib/plugins/sparql/operators.py::Builtin_CEIL`/`Builtin_FLOOR`/`Builtin_ROUND`/`MultiplicativeExpression`)

### Description

XSD 1.1's canonical lexical representation for `decimal` requires a decimal point with at least one digit on each side (e.g. `"4.0"`, not `"4"`) - `"4"` is a valid, but non-canonical, member of `decimal`'s lexical space. `Builtin_CEIL`/`Builtin_FLOOR`/`Builtin_ROUND` correctly preserve the argument's original datatype (`xsd:decimal`, `xsd:float`, etc.) but construct the result value via a raw Python `int` (`Literal(int(math.ceil(...)), datatype=l_.datatype)`) - and a plain `int` lexicalizes as e.g. `"4"`, dropping the required trailing `.0` whenever the datatype is `xsd:decimal`. `MultiplicativeExpression`'s `/` operator has the identical defect for a whole-number division result (e.g. `84 / 2`), even once Issue 1 above is fixed and the datatype itself is already correct.

### Reproduction

```python
from decimal import Decimal
from rdflib import Graph, Literal

print(repr(Literal(Decimal(42))))    # datatype correct, lexical form wrong
print(repr(Literal(Decimal('42.0')))) # canonical, when the input already has it

g = Graph()
print(list(g.query("SELECT (CEIL(3.2) AS ?r) WHERE {}"))[0][0])
print(list(g.query("SELECT (84 / 2 AS ?r) WHERE {}"))[0][0])
```

### Expected behavior

```
Literal('42.0', datatype=xsd:decimal)   # for Literal(Decimal(42))
4.0   # CEIL(3.2)
42.0  # 84 / 2
```

Confirmed independently against Apache Jena's ARQ (via Fuseki 5.5+), which produces exactly `"4.0"`/`"42.0"` for these two queries - matching the expected behavior above.

### Actual behavior

```
Literal('42', datatype=xsd:decimal)
4
42
```

Note: Oxigraph's own native SPARQL engine also produces the non-canonical `"4"`/`"42"` here, same as rdflib - this specific example isn't universal ground truth across every engine, but Jena/ARQ's agreement with the canonical-form expectation, plus XSD 1.1's own explicit textual requirement, is strong evidence rdflib's behavior is the actual bug, not a matter of implementation taste.

### Suspected root cause

```python
def Builtin_CEIL(expr, ctx):
    l_ = expr.arg
    return Literal(int(math.ceil(numeric(l_))), datatype=l_.datatype)
```

Passing a raw Python `int` value alongside an explicit `datatype=xsd:decimal` doesn't make rdflib's `Literal()` constructor reformat the lexical string to be canonical for that datatype - lexicalization is dispatched purely by the Python value's own type (`int` → `str(int)`, no decimal point ever), regardless of the `datatype=` argument. Confirmed via `Literal(Decimal(42))` vs `Literal(Decimal('42.0'))` above: only a value that already carries the fractional-zero digit (constructed from a string, not an `int`) preserves it. `Builtin_FLOOR`/`Builtin_ROUND` share the identical pattern; `MultiplicativeExpression`'s `/` branch shares the same underlying `Decimal`-without-a-preserved-fraction issue for a whole-number result.

### Impact

Any SPARQL query using `CEIL`/`FLOOR`/`ROUND` on a decimal-typed value, or dividing two values to a whole-number result, produces a literal whose lexical form isn't the value's own XSD canonical form. Value-equal comparisons are unaffected, but under RDF 1.2's stricter literal term-equality (exact lexical form required, not just value) this literal will not be term-equal to a canonically-serialized one - the same category of correctness gap as Issue 1.

### Suggested fix

Construct the result as a string with the fractional part explicit, or reuse `Decimal`'s own string-preserving construction, before handing it to `Literal(..., datatype=...)` - e.g. for `Builtin_CEIL`: `Literal(f"{int(math.ceil(numeric(l_)))}.0" if l_.datatype == XSD.decimal else int(math.ceil(numeric(l_))), datatype=l_.datatype)`, or more generally, a shared helper that appends `.0` to any whole-number `xsd:decimal` result across all four call sites (`Builtin_CEIL`, `Builtin_FLOOR`, `Builtin_ROUND`, `MultiplicativeExpression`'s `/` branch).

### Possible workaround

Same monkeypatch technique as Issue 1 - `rdflib.plugins.sparql.parser.BuiltInCall`'s grammar tree is walked to find the `Builtin_CEIL`/`Builtin_FLOOR`/`Builtin_ROUND` `Comp` nodes (not top-level named grammar variables, unlike `MultiplicativeExpression`), and each is given a corrected `evalfn` that runs the original computation through a shared `_canonicalize_decimal_lexical_form()` helper before returning. See `starlight/query/operator_patches.py::patch_decimal_result_lexical_form` in this repo for a full implementation, including the grammar-tree-walking helper (`_find_comp`).

### Status

Found 2026-08-01 while triaging the downstream `starShacl` project's W3C SHACL 1.2 test suite failures. Reporting upstream planned, not yet filed. Worked around in this repo (`starlight/query/operator_patches.py`) in the meantime. A closely related, separate quirk (`Builtin_SECONDS()` returning `"0"` rather than a zero-padded `"00"`) was also investigated during this work and found to be a downstream test-suite fixture artifact, not an rdflib bug - `"0"` is not canonical either (canonical would be `"0.0"`, the same rule as above), but the fixture's specific zero-padding expectation has no basis in `SECONDS()`'s own specification and isn't produced by any of the three engines checked (rdflib, Jena/ARQ, Oxigraph) - not included as a third issue here.

## Issue 3 - `_AlgebraTranslator`'s `BGP` branch emits text its own parser can't re-parse (found 2026-08-03)

**rdflib version:** 7.6.0 (`rdflib/plugins/sparql/algebra.py::_AlgebraTranslator.sparql_query_text`, `"BGP"` branch)

### Description

`translateAlgebra`'s own `BGP` branch joins each triple's `.n3()` text with `"".join(...)` - no separator at all between one triple's trailing `"."` and the next triple's leading term. When a triple ending in a blank-node object is immediately followed (in triple-list order) by a triple whose subject is a blank node, the resulting text has zero whitespace between them (e.g. `..._:x._:x...`), and rdflib's own SPARQL parser fails to re-tokenize this correctly - `translateAlgebra`'s output is not guaranteed to be re-parseable by rdflib's own `prepareQuery`, even for a query rdflib itself just produced this text from.

### Reproduction

```python
from rdflib.plugins.sparql.processor import prepareQuery

prepareQuery("SELECT * {_:y <http://ex/p1> _:x._:x <http://ex/p2> <http://ex/o2>.}")
```

### Expected behavior

Parses successfully - this is syntactically ordinary Turtle-style triple-list SPARQL, and is exactly the shape `translateAlgebra` itself would produce for a `BGP` containing these two triples in this order (confirmed separately: this is not a hand-picked adversarial string, it's the literal output shape for e.g. two chained blank-node-linking triples).

### Actual behavior

```
pyparsing.exceptions.ParseException: Expected SelectQuery, found ':'  (at char 34), (line:1, col:35)
```

pointing at the second `_:x`. Inserting a single space (`_:x. _:x`) fixes it with no other change.

### Suspected root cause

```python
elif node.name == "BGP":
    triples = "".join(
        triple[0].n3() + " " + triple[1].n3() + " " + triple[2].n3() + "."
        for triple in node.triples
    )
    self._replace("{BGP}", triples)
```

Each triple's own three terms are space-separated, but the trailing `"."` has no following separator before the next triple's `"".join`-concatenated text begins - so `BLANK_NODE_LABEL`'s own tokenization (plausibly greedy-then-backtrack behavior around the trailing `.`, since a blank node label's own grammar can include an internal `.`, just not a trailing one) can't recover when a `.` is immediately followed by another blank-node label with no whitespace to signal the triple boundary unambiguously.

### Impact

Any code that round-trips a `BGP` through `translateAlgebra` back into text and then re-parses that text (rather than just displaying it) can hit an unparseable result purely from term ordering/adjacency, with no indication anything is wrong until the re-parse fails. Confirmed to affect real-world content, not just this minimal repro: reification/annotation-derived triples (`rdf:subject`/`predicate`/`object`/`reifies`), which are blank-node-heavy by construction, hit this constantly in practice.

### Suggested fix

Add a separator after each triple's trailing `"."` - e.g. `+ ". "` instead of `+ "."` in the generator expression above. A single-token change; doesn't affect any other branch's formatting conventions.

### Possible workaround / fix applied

Owning the serializer downstream (rather than depending on `_AlgebraTranslator`'s `BGP` branch unmodified) makes this a one-line fix: the downstream `sparql1.2_to_rdf` project's own `serialize12.py::_triples_text` (which already needed to override the `BGP` branch for an unrelated reason - rendering its own `TripleTermNode` values) adds the trailing space there. Also now patched directly in this repo (`starlight/query/algebra_translator_patches.py::patch_algebra_translator_bugs`), monkeypatching `_AlgebraTranslator.sparql_query_text` itself rather than depending on every consumer to subclass around it - this protects any consumer that doesn't happen to have its own independent fix the way `sparql1.2_to_rdf` does.

### Status

Found 2026-08-03 while triaging W3C SPARQL 1.2 test suite failures in the downstream `sparql1.2_to_rdf` project (misdiagnosed at first, before finding the actual root cause, as "starlight's own Turtle parser rejecting nested `<<...>>` data syntax" - it surfaces while executing *regenerated* query text, which can look superficially similar to a data-parsing failure). Reporting upstream planned, not yet filed. Fixed both in the downstream project's own serializer and directly in this repo.

## Issue 4 - `translateAlgebra` mis-nests `UNION` branches that each contain a subquery + `BIND` (found 2026-08-03)

**rdflib version:** 7.6.0 (`rdflib/plugins/sparql/algebra.py::_AlgebraTranslator.sparql_query_text`, `"Extend"` branch)

### Description

When a query has multiple `UNION` branches, each containing its own subquery followed by its own `BIND(... AS ?sameVar)` (the same projected variable name reused across branches - a common pattern for "compute one column differently per alternative"), `translateAlgebra` nests each branch's `AS` expression *inside* the previous branch's, instead of keeping them as separate, sibling `BIND`-equivalent projections. The regenerated text is syntactically invalid.

### Reproduction

```python
from rdflib.plugins.sparql.processor import prepareQuery
from rdflib.plugins.sparql.algebra import translateAlgebra

text = """SELECT * WHERE {
   { { SELECT ?v { ?s ?p ?v } ORDER BY ?v LIMIT 1 } BIND('B-1' as ?index) }
   UNION
   { { SELECT ?v { ?s ?p ?v } ORDER BY ?v OFFSET 1 LIMIT 1 } BIND('B-2' AS ?index) }
}"""
q = prepareQuery(text)
print(translateAlgebra(q))
```

### Expected behavior

Regenerated text that re-parses and evaluates to the same results as the original - each `UNION` branch's own `BIND` should stay scoped to that branch, e.g. something shaped like `SELECT ?v ?index { { {SELECT ?v {...}} BIND('B-1' AS ?index) } UNION { {SELECT ?v {...}} BIND('B-2' AS ?index) } }`.

### Actual behavior

```
SELECT ("B-1" as ("B-2" as ?index)) ?v{{{SELECT ?v{?s ?p ?v.}ORDER BY ?v OFFSET 0 LIMIT 1}}UNION{{SELECT ?v{?s ?p ?v.}ORDER BY ?v OFFSET 1 LIMIT 1}}}
```

`"B-2"`'s `BIND` ends up nested *inside* `"B-1"`'s `AS` expression, in the `SELECT` clause's own projection list - not scoped to either `UNION` branch at all, and not valid SPARQL (an `AS` expression's own target can't itself be another `AS` expression). With more `UNION` branches (the real-world trigger - a 20-branch chain, one per desired sample), this compounds arbitrarily deep, one nesting level per branch.

### Suspected root cause

```python
elif node.name == "Extend":
    query_string = self._alg_translation.lower()
    select_occurrences = query_string.count("-*-select-*-")
    self._replace(
        node.var.n3(),
        "(" + self.convert_node_arg(node.expr) + " as " + node.var.n3() + ")",
        search_from_match="-*-select-*-",
        search_from_match_occurrence=select_occurrences,
    )
```

`_replace`'s `search_from_match`/`search_from_match_occurrence` mechanism is a crude attempt to scope a replacement to "starting from the Nth `-*-select-*-` marker in the accumulated string so far" - but it operates on `self._alg_translation` as one global, flat string, matching literal substrings (`node.var.n3()`, e.g. the literal text `"?index"`) with no actual tree-scoping. When multiple sibling `UNION` branches *each* contribute their own nested subquery (each adding its own `-*-select-*-` marker) *and* their own `Extend`/`BIND` targeting the *same* variable name, an earlier branch's already-substituted `"(... as ?index)"` text still literally contains the substring `"?index"` inside it - which a *later* branch's own replacement, searching from an occurrence count that doesn't actually disambiguate between "a fresh, not-yet-replaced `?index`" and "`?index` appearing inside an already-completed replacement from a sibling branch," can match and wrap around instead of the placeholder it was actually meant to fill.

### Impact

Any query using multiple `UNION` branches that each independently subquery-and-`BIND` the same projected variable name produces invalid, unparseable output from `translateAlgebra`. This is a natural, not contrived, pattern - e.g. generating labeled samples from different offsets/orderings of the same underlying data, one `UNION` branch per label (the real trigger, from the W3C SPARQL 1.2 test suite's own `ORDER BY` reification tests).

### Suggested fix (as reported upstream) / fix applied here

The general structural fix (replace the literal-variable-name-as-search-target approach with a per-`Extend`-node-instance unique placeholder) is a larger change than this repo needed to make. The actual fix applied (`starlight/query/algebra_translator_patches.py::patch_algebra_translator_bugs`, `"Extend"` branch) sidesteps the whole placeholder-scoping problem instead: it never searches the accumulated text for a bare variable occurrence to wrap at all. It renders the `Extend` node in place, using the same `"{NodeName}"` child-placeholder convention every other branch (`Join`/`LeftJoin`/`Union`/`Graph`/...) already uses:

```python
self._replace(
    "{Extend}",
    "{" + node.p.name + "}BIND(" + self.convert_node_arg(node.expr) + " AS " + node.var.n3() + ")",
)
```

i.e. always emit an explicit, in-place `BIND(expr AS var)` statement at the `Extend` node's own tree position, rather than hoisting into the outer `SELECT` clause's projection list. This is a safe, general substitution regardless of the original SPARQL syntax (`SELECT (expr AS ?v) ...` and an ordinary in-place `BIND(expr AS ?v)` collapse to the identical `Extend` algebra shape, and SPARQL treats the two textual forms as fully equivalent for a single `Extend`) - it just also happens to be correct when there are multiple sibling `Extend` nodes targeting the same variable, which the original approach wasn't.

Two real bugs surfaced while implementing this, both fixed:
- Must **not** `return node` after this branch (unlike the `"BGP"` branch) - `node.p`'s own placeholder still needs `_traverse`'s later recursion to resolve it; returning early left a literal, unresolved `"{ToMultiSet}"`/`"{BGP}"` in the output and skipped the `"-*-select-*- -> SELECT"` marker cleanup entirely.
- Must **not** emit a trailing `"."` after the `BIND(...)` (unlike most statement-producing branches) - this repo's *own* `sparql12_to_11.py` rewriter (`_rewrite_bind_accessors`) separately matches the literal text shape `BIND(SUBJECT(?tt) AS ?s)` and substitutes it wholesale with `?tt <rdf:subject> ?s .`, including its own trailing period - a trailing period from this branch too produced a real, reproducible double-period (`?s . .`, a syntax error) once regenerated text fed into that specific downstream rewriter. SPARQL's own grammar makes the separator between a `GraphPatternNotTriples` element and whatever follows optional, so omitting it entirely is safe.

### Status

Found 2026-08-03 while triaging W3C SPARQL 1.2 test suite failures in the downstream `sparql1.2_to_rdf` project (`order-1`/`order-2` in that project's test suite). Root-caused down to the `"Extend"` branch's search-and-wrap mechanism (see Suspected root cause) the same day. Reporting upstream planned, not yet filed. Fixed directly in this repo (`starlight/query/algebra_translator_patches.py`), verified against both a 2-branch and 3-branch reproduction (structural reparse *and* actual query execution compared against the pre-fix/non-`UNION` equivalent), with zero regressions across this repo's own suite (772 passed) and the downstream `sparql1.2_to_rdf` project's suite (108 core + 198/218 W3C, both unchanged).

## Issue 5 - A `BIND` referencing an earlier hoisted `BIND`'s variable, inside a `UNION` branch, followed by a join, gives duplicated/wrong results (found 2026-08-03)

**rdflib version:** 7.6.0 (SPARQL algebra evaluator, `rdflib/plugins/sparql/evaluate.py` - exact function not yet isolated further than "the `UNION`/`Extend`/`Join` evaluation interaction"; see Suspected root cause)

### Description

A query that first `BIND`s one or more values to variables, then uses those variables (not the original values) inside separate `BIND`s nested in different `UNION` branches, then joins against the `UNION`'s result outside the union, produces extra and/or incorrectly-matching result rows - as if the join were evaluated against a looser or unfiltered condition than the `UNION` branches actually express. Using the original literal values directly inside each `UNION` branch's `BIND` (no indirection through an earlier, separately-hoisted `BIND`) gives the correct results for the identical logical query.

### Reproduction

```python
from rdflib import Graph

g = Graph()
g.parse(data="""
@prefix : <http://ex/> .
:s0 :p :vX .
:s1 :p :v1 .
:s2 :p :v2 .
""", format="turtle")

# Wrong: hoisted-BIND indirection
q_wrong = """PREFIX : <http://ex/>
SELECT ?s WHERE {
  BIND(:v1 AS ?t0) . BIND(:v2 AS ?t1) .
  { { BIND(?t0 AS ?o) } UNION { BIND(?t1 AS ?o) } }
  ?s :p ?o .
}"""
print("wrong:", list(g.query(q_wrong)))

# Correct: direct values, no indirection
q_right = """PREFIX : <http://ex/>
SELECT ?s WHERE {
  { { BIND(:v1 AS ?o) } UNION { BIND(:v2 AS ?o) } }
  ?s :p ?o .
}"""
print("right:", list(g.query(q_right)))
```

### Expected behavior

Both queries are logically equivalent (`?t0`/`?t1` are each bound to exactly one fixed value, unconditionally, before the union) and should return the identical two rows: `:s1`, `:s2` (`:s0` correctly excluded - `:vX` matches neither value).

### Actual behavior

`q_right` (direct values) correctly returns exactly `[(:s1,), (:s2,)]`. `q_wrong` (hoisted-`BIND`-then-referenced-inside-`UNION`) returns six rows: `:s1`, `:s2`, and `:s0` (wrong - shouldn't match at all), each duplicated:
```
wrong: [(s2,), (s0,), (s1,), (s2,), (s0,), (s1,)]
right: [(s1,), (s2,)]
```

### Suspected root cause

Fully isolated by tracing (not guessed): `algebra.py::_addVars`'s `"Extend"` case computes `x["_vars"]` deliberately *excluding* any variable that appears only inside `extend.expr` -

```python
elif x.name == "Extend":
    # vars only used in the expr for a bind should not be included
    x["_vars"] = reduce(
        operator.or_,
        [child for child, part in zip(children, x) if part != "expr"],
        set(),
    )
```

- and `evaluate.py::evalExtend` then uses that same `_vars` set as if it were "every variable this BIND depends on to evaluate its RHS":

```python
e = _eval(extend.expr, c.forget(ctx, _except=extend._vars))
```

For the ordinary case (`?s :p ?x . BIND(?x + 1 AS ?y)`), this happens to work: `?x` survives into `Extend._vars` anyway, because it's *also* a pattern variable of `extend.p` (the preceding BGP) - a completely separate path from the deliberately-excluded `expr` path. But when a `BIND`'s RHS references a variable that is *not* re-derivable from its own local `extend.p` - e.g. `{ BIND(?t0 AS ?o) }`, where the local pattern `p` is empty and `?t0` was bound by an *earlier, outer* `BIND` outside this `Extend`'s own subtree entirely - `Extend._vars` ends up `{o}` only, never `{t0, o}`. `evalExtend`'s `c.forget(ctx, _except={o})` then forgets the incoming `?t0` binding *before* evaluating `extend.expr` (`t0`), so `_eval` runs against a context where `?t0` is unbound. Confirmed directly by instrumenting `evalExtend`:

```
evalExtend: expr= t0 var= o extend._vars= {Variable('o')}
  incoming binding c: {t0: <http://ex/v1>, t1: <http://ex/v2>}
  after forget: {}
```

`_eval` on an unbound bare variable raises `SPARQLError`, which `evalExtend`'s own `except SPARQLError: yield c` swallows - yielding the binding *without* ever merging in `?o` at all, leaving `?o` completely unbound rather than raising or skipping the row. A later `?s :p ?o .` with `?o` unbound then matches *any* `:p` triple, which is exactly the observed "extra, wrong, and duplicated" symptom - it isn't really a `UNION`-specific bug at all; `UNION` is just the natural way to end up with a `BIND` whose local pattern doesn't contain the variable its `expr` needs (each branch's own local pattern is empty/unrelated to the outer hoisted `BIND`s).

### Impact

Any query using this pattern - a `BIND` whose RHS expression references a variable bound *outside* that `BIND`'s own local pattern subtree (most naturally hit via `UNION`, but not exclusively) - silently produces wrong results (an incorrectly-unconstrained variable) with no error at all, which is a more dangerous failure mode than the parse-time crashes in issues 1-4/6 (those fail loudly; this one doesn't).

### Suggested fix / fix applied

In `evalExtend`, don't trust `extend._vars` alone to capture everything `extend.expr` depends on - union in the expr's own free variables directly before forgetting. Applied directly in this repo (`starlight/query/evaluate_patches.py::patch_evalextend_forgotten_bind_vars`):

```python
except_vars = (extend._vars or set()) | _expr_free_vars(extend.expr)
e = _eval(extend.expr, c.forget(ctx, _except=except_vars))
```

where `_expr_free_vars` reads the same `_vars` bookkeeping `_addVars` already computes for every `CompValue` node (trivial for the bare-`Variable` case that triggers this - its own free-variable set is itself - and already correctly populated for a compound expression like `?x + 1`, just never consulted here for `Extend` specifically before this fix).

Two real bugs surfaced while implementing this, both fixed:
- `extend._vars` can genuinely be `None`, not just "unset defaulting to an empty set": `translateUpdate` never runs the `_addVars`/`analyse` pass at all (unlike `translateQuery`, which always does - a pre-existing, separately-confirmed finding from the downstream `sparql1.2_to_rdf` project), so any `Extend` node arising from a SPARQL Update's `WHERE`-clause processing has no `"_vars"` at all. `None | a_set` raises `TypeError` - confirmed a real crash on Update evaluation (`test_sparql12_update.py`) before adding the `or set()` fallback.
- `CompValue.get` is **not** `dict.get` - its actual signature is `get(self, a, variables=False, errors=False)`, so `expr.get("_vars", set())` passes the `set()` as the `variables` flag, not a default value, and a missing key falls back to returning the key string itself (`OrderedDict.get(self, a, a)`). This produced a real, reproducible `TypeError: unsupported operand type(s) for |: 'set' and 'str'` (unioning a set with the literal string `"_vars"`) before switching to plain `dict.get(expr, "_vars")` (the unbound method, called explicitly, bypassing `CompValue`'s own override).

Neither `_addVars`'s own "exclude expr-only vars" rule for `Extend` nor `evalExtend`'s reliance on it needed to change - the fix only widens what `evalExtend` itself additionally keeps in scope before evaluating, without touching the static-analysis pass at all.

### Status

Found 2026-08-03 while fixing this repo's own `sparql12_to_11.py` rewriter's handling of a triple term inside a `VALUES` clause (a `VALUES`-to-`UNION`-of-`BIND`s desugaring hit this exact bug when its branches referenced this repo's *existing*, separate ground-triple-term hoisting mechanism instead of inlining directly - see this repo's git history/`CHANGELOG.md` around 2026-08-03 for that fix, `_inline_ground_triple_terms`, which remains in place as a second, independent layer of avoidance on top of this direct fix). Root-caused down to `_addVars`'s `"Extend"` case and `evalExtend`'s reliance on it (see Suspected root cause) on 2026-08-03, then patched directly the same day (`starlight/query/evaluate_patches.py`) per direct instruction, given this repo's SPARQL pipeline is intended to route every query through this path going forward - not left as an avoidance-only workaround. Verified against the original minimal reproduction (now returns the correct 2 rows instead of 6, with no `:s0` false match) and zero regressions across this repo's own suite (772 passed, including the SPARQL Update suite the `None`-handling bug above was caught by) and the downstream `sparql1.2_to_rdf` project's suite (108 core + 198/218 W3C, both unchanged). Reporting upstream still planned, not yet filed.

## Issue 6 - `RelationalExpression`'s list-handling guard is inverted, so multi-value `IN`/`NOT IN` always crashes `translateAlgebra` (found 2026-08-03)

**rdflib version:** 7.6.0 (`rdflib/plugins/sparql/algebra.py::_AlgebraTranslator.sparql_query_text`, `"RelationalExpression"` branch)

### Description

SPARQL's `IN`/`NOT IN` operators take a comma-separated list of expressions on their right-hand side (`?x IN (v1, v2, v3)`), represented in rdflib's algebra as `node.other` being a Python `list`. The `RelationalExpression` branch's own guard meant to detect this case, `isinstance(list, type(node.other))`, is backwards from the intended `isinstance(node.other, list)` - it asks "is the class object `list` itself an instance of `type(node.other)`", which is never `True` for any value of `node.other` (the class `list` is an instance of `type`, never of itself or of any other class). This makes the correct list-rendering branch unreachable dead code; every `IN`/`NOT IN` with more than zero values in the list falls through to the `else` branch, which passes the *entire list* as one argument to `convert_node_arg` - a method with no case for a bare Python `list` at all - raising instead of rendering.

### Reproduction

```python
from rdflib.plugins.sparql.processor import prepareQuery
from rdflib.plugins.sparql.algebra import translateAlgebra

q = prepareQuery("PREFIX : <http://ex/> SELECT * WHERE { ?s :p ?o . FILTER(?o IN (:a, :b, :c)) }")
translateAlgebra(q)
```

No triple terms, no RDF 1.2 syntax, no `starlight`/downstream-project code involved at all - a plain SPARQL 1.1 `FILTER ... IN (...)` with more than one value.

### Expected behavior

Regenerated text like `... FILTER(?o IN (<http://ex/a>, <http://ex/b>, <http://ex/c>)) ...` - the base case this branch's own (unreachable) list-handling code is clearly *trying* to produce (its logic, if it ever ran, is correct: `"(" + ", ".join(self.convert_node_arg(expr) for expr in node.other) + ")"`).

### Actual behavior

```
rdflib.plugins.sparql.algebra.ExpressionNotCoveredException: The expression [rdflib.term.URIRef('http://ex/a'), rdflib.term.URIRef('http://ex/b'), rdflib.term.URIRef('http://ex/c')] might not be covered yet.
```

### Suspected root cause

```python
elif node.name == "RelationalExpression":
    expr = self.convert_node_arg(node.expr)
    op = node.op
    if isinstance(list, type(node.other)):
        other = (
            "(" + ", ".join(self.convert_node_arg(expr) for expr in node.other) + ")"
        )
    else:
        other = self.convert_node_arg(node.other)
    condition = "{left} {operator} {right}".format(left=expr, operator=op, right=other)
    self._replace("{RelationalExpression}", condition)
```

`isinstance(list, type(node.other))` has its two arguments backwards - should be `isinstance(node.other, list)`.

### Impact

Any `translateAlgebra` call on a query containing `IN`/`NOT IN` with two or more values in the list crashes unconditionally - a very common, ordinary SPARQL 1.1 construct, with no RDF 1.2/triple-term involvement needed to trigger it at all. (A single-value `IN (v1)` doesn't crash - `node.other` for exactly one value may not always be a `list` depending on how the parser builds it - but this hasn't been checked closely, since it's not the interesting case.)

### Suggested fix

```python
if isinstance(node.other, list):
```

A one-token fix - swap the two arguments to `isinstance`.

### Possible workaround / fix applied

Same shape as issue 3: owning the serializer downstream makes this a small, local override. The downstream `sparql1.2_to_rdf` project's `serialize12.py` adds a `"RelationalExpression"` branch ahead of the base class's own, with the corrected `isinstance` check, plus `TripleTermNode`-aware rendering per list element (its own additional need, on top of just fixing rdflib's bug). Also now patched directly in this repo (`starlight/query/algebra_translator_patches.py::patch_algebra_translator_bugs`) - the branch there deliberately does **not** `return node` afterward (unlike the `"BGP"` branch): `node.expr`/`node.other`'s items can themselves be `CompValue` nodes needing `_traverse`'s own later per-child recursion to resolve their own placeholders, and returning early was confirmed to leave those unresolved in the output when first tried.

### Status

Found 2026-08-03 while triaging W3C SPARQL 1.2 test suite failures in the downstream `sparql1.2_to_rdf` project (`basic-9`, `FILTER (?o IN (<<( :s :p "o" )>>, ...))`). Reporting upstream planned, not yet filed. Fixed both in the downstream project's own serializer and directly in this repo.
