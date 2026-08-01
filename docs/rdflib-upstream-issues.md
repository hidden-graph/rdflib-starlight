# rdflib Upstream Issues

*Last reviewed: 2026-08-01*

Bugs found in plain `rdflib` (https://github.com/RDFLib/rdflib) - specifically its SPARQL 1.1 expression evaluator, `rdflib/plugins/sparql/operators.py` - while building this repo's own SPARQL 1.2 support on top of it. Every reproduction below uses only plain `rdflib`, no `starlight`/`rdflib-starlight` code at all, so each is reproducible standalone against a stock `rdflib` install. Both confirmed against `rdflib` 7.6.0 (the version this project currently pins).

## Status Summary

Both issues are planned to be reported upstream - each a clean, unambiguous, spec-mapping bug with a minimal plain-`rdflib` reproduction. Neither has been filed yet (no existing GitHub issue/PR search performed yet - do that before actually opening either).

| # | Issue | Reporting upstream? | Workaround in this repo |
| --- | --- | --- | --- |
| 1 | `MultiplicativeExpression` (`*`/`/`) never applies SPARQL 1.1's numeric type-promotion rules | **Yes** (not yet filed) | Yes, `starlight/query/operator_patches.py::patch_multiplicative_expression_type_promotion` |
| 2 | `Builtin_CEIL`/`Builtin_FLOOR`/`Builtin_ROUND` (and whole-number division) lose XSD decimal's canonical lexical form | **Yes** (not yet filed) | Yes, `starlight/query/operator_patches.py::patch_decimal_result_lexical_form` |

Both were found while triaging the W3C SHACL 1.2 test suite's remaining failures in the downstream `starShacl`/`pyshacl-starlight` project (that suite's own `node-expr/shnex-sparql/{multiply,divide,ceil,floor,round}.ttl` and `sparql/rules/rectangle-*.ttl` fixtures) - see that repo's `docs/starlight-upstream-change-log.md` 2026-08-01 entries for the full downstream-impact writeup. Both are patched in this repo (`starlight/query/operator_patches.py`, applied eagerly at import time) rather than left broken, since a stock `rdflib` install can't be assumed to have either fix yet.

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
