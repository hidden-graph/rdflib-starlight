# Apache Jena / Fuseki Upstream Issues

*Last reviewed: 2026-08-04*

Bugs found in [Apache Jena](https://github.com/apache/jena) (via Fuseki, the native `rdf-1.2` backend's second real SPARQL-star HTTP engine option - see `starlight/backends/native.py`'s own module docstring: this repo does zero query/data rewriting for either native-backend engine, so what the engine accepts and returns is exactly what a client sees) while cross-checking a finding from the downstream `sparql1.2_to_rdf` project's adversarial round-trip test battery against a second engine. Confirmed against Fuseki `5.5.0`. Reproduction uses the official W3C SPARQL 1.2 test suite's own fixture data/expected results as ground truth, not a hand-picked adversarial case.

Same entry structure/conventions as `docs/rdflib-upstream-issues.md` (see that file's "How To Use" section) - `##`/`###` headings pastable directly into a GitHub issue.

## Status Summary

| # | Issue | Reporting upstream? |
| --- | --- | --- |
| 1 | `TRIPLE(subject, predicate, object)` fails to reject a triple-term-valued `subject` argument (constructs an invalid nested-subject triple term instead), while correctly rejecting the identical case for the `predicate` argument | **Yes** (not yet filed) |

## Entries

| # | Title | Found |
| --- | --- | --- |
| 1 | `TRIPLE()` doesn't validate its `subject` argument the way it already validates `predicate` | 2026-08-04 |

## Issue 1 - `TRIPLE()` doesn't validate its `subject` argument the way it already validates `predicate` (found 2026-08-04)

**Fuseki version:** 5.5.0 (SPARQL query evaluation, `TRIPLE(...)` builtin function)

### Description

Per RDF 1.2's own term model (confirmed via the [RDF 1.2 Turtle grammar](https://www.w3.org/TR/rdf12-turtle/#grammar-production-tripleTerm): `ttSubject ::= iri | BlankNode`, no `tripleTerm` alternative - nesting is only legal in *object* position), a triple term's own subject can never itself be a triple term. The official W3C SPARQL 1.2 test suite's `expression/triple-on-triple-terms` fixture tests exactly this: it evaluates `TRIPLE(?subject, ?predicate, ?object)` across `VALUES` rows where each of `?subject`/`?predicate`/`?object` in turn is bound to a triple term, and its own expected results (`triple-on-triple-terms.srj`) show `?triple` correctly left **unbound** when `?subject` or `?predicate` is a triple term, and correctly **bound** (nesting permitted) when only `?object` is. Fuseki gets the `?predicate` case right - `?triple` is correctly left unbound - but gets the `?subject` case wrong: it constructs and returns `?triple` bound to an actual nested-subject triple term, which is not a valid RDF 1.2 term at all.

### Reproduction

```bash
curl -G http://localhost:3030/starlight/query --data-urlencode 'query=
PREFIX : <http://example/>
SELECT ?subject ?triple {
  VALUES ?subject { (<<(:x :y :z)>>) }
  BIND(TRIPLE(?subject, :b, :c) AS ?triple)
}'
```

(Any dataset works - the store can be empty; `?subject` is bound directly by `VALUES`, not looked up.)

### Expected behavior

Per the official W3C fixture's own expected results (`tests/w3c_sparql12/data/expression/triple-on-triple-terms.srj` in the downstream `sparql1.2_to_rdf` project, or directly at `https://w3c.github.io/rdf-tests/sparql/sparql12/expression/triple-on-triple-terms.srj`): `?triple` unbound (no `"triple"` key in that row's JSON binding) - `TRIPLE()`'s own evaluation should fail when its `subject` argument isn't a valid triple-term subject (`iri`/`BlankNode`), the same way it already correctly fails for an invalid `predicate` argument.

### Actual behavior

```json
{
  "subject": {"type": "triple", "value": {"subject": {"type":"uri","value":"http://example/x"}, "predicate": {"type":"uri","value":"http://example/y"}, "object": {"type":"uri","value":"http://example/z"}}},
  "triple":  {"type": "triple", "value": {
      "subject": {"type": "triple", "value": {"subject": {"type":"uri","value":"http://example/x"}, "predicate": {"type":"uri","value":"http://example/y"}, "object": {"type":"uri","value":"http://example/z"}}},
      "predicate": {"type": "uri", "value": "http://example/b"},
      "object":    {"type": "uri", "value": "http://example/c"}
  }}
}
```

`?triple` is bound to a triple term whose own `subject` is itself a triple term - not a valid RDF 1.2 term under any reading of the spec.

### Suspected root cause

Not confirmed against Jena's own source (not inspected directly). The clean contrast between the correctly-rejected `predicate` case and the incorrectly-accepted `subject` case suggests `TRIPLE()`'s implementation validates its second argument's type but is simply missing the equivalent check on its first argument - i.e. a one-sided validation gap, not a deeper structural issue (object position is, correctly, unrestricted for either).

### Impact

Any query using `TRIPLE()` where the `subject` argument might be (or might evaluate to) a triple term-valued expression silently constructs invalid RDF 1.2 data as a query result, rather than the spec-mandated unbound/error outcome. Concretely hit by a downstream consumer (`starlight`'s own native-backend result parser, `starlight/backends/native.py`) - decoding this result required a `TripleTerm` object whose own constructor already validates the *same* RDF 1.2 rule Jena's `TRIPLE()` should have enforced during evaluation, and raised - see this repo's own fix for making that failure mode graceful instead of an unhandled crash (`CHANGELOG.md`, "native-backend result parsing" entry, same date).

### Suggested fix

Add the same subject-position validation `TRIPLE()`'s implementation already applies to its `predicate` argument, applied to `subject` as well: if the evaluated `subject` argument is a triple term (rather than an IRI or blank node), the function should raise an expression-evaluation error (causing the containing `BIND`/projection to leave its target variable unbound, per ordinary SPARQL expression-error semantics) rather than constructing the invalid term.

### Possible workaround

Avoid passing a triple-term-valued expression as `TRIPLE()`'s first argument. If a query might do so unpredictably (e.g. a generic, round-tripped query where the shape isn't known ahead of time), validate/filter `TRIPLE()`'s result client-side rather than trusting Fuseki's response to already be valid RDF 1.2 - which is what this repo now does (see the `native.py` fix referenced above).

### Status

Found 2026-08-04 while cross-checking a downstream `sparql1.2_to_rdf` project finding against Fuseki as a second engine (see this repo's own `docs/rdflib-upstream-issues.md`/git history around 2026-08-04 for the Oxigraph-side investigation that prompted this cross-check - that specific Oxigraph finding turned out to be a failure-mode/status-code question on a query that can never match real data either way, not worth reporting on its own, but running the same adversarial+W3C-conformance test battery against Fuseki as a second data point surfaced this separate, genuine correctness bug via the official W3C fixture's own expected-results file). Not yet filed upstream.
