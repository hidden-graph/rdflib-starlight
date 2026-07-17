# Changelog

## Unreleased

RDF 1.2/SPARQL 1.2 conformance hardening since 0.1.0:

- **RDF 1.2 VERSION-directive conformance checking** (`RDF12ConformanceWarning`) across Turtle, N-Triples, N-Quads, TriG, RDF/XML, SPARQL, and the native `rdf-1.2` backend.
- **Full W3C conformance** — the Turtle 1.2 test suite went from 29 to 103 tests (added the syntax-conformance cases alongside eval), which surfaced and fixed real gaps: stricter `TurtleSyntaxError` handling, predicate/subject position validation for triple terms and reified triples, annotation-block arity, VERSION directive grammar, base-direction case sensitivity, and surrogate-escape rejection.
- **`isomorphic()`** now correctly handles TripleTerms containing blank nodes, and is more rigorous generally (was previously using rdflib's own approximate check).
- Fixed several SPARQL 1.2→1.1 rewriter bugs (WHERE-less queries, bare `TRIPLE()` in a SELECT projection, nested `isTRIPLE()`).
- Adopted Apache Jena's real TriX convention; fixed an RDF/XML `rdf:version` data-corruption bug.
- Removed the obsolete `rdf-star` backend mode (superseded by `rdf-1.2`).
- Assorted smaller fixes: `tt:HASH` collision risk, the `sqlalchemy` extra failing to install on a fresh environment, query/update state leaking across calls.

## 0.1.0 — 2026-05-14

Initial public release.

### Features

- **`StarlightGraph`** — drop-in replacement for `rdflib.Graph` with full RDF 1.2 support
- **Triple terms** — `TripleTerm` objects as first-class Python values; content-addressed internal encoding (`tt:HASH`)
- **All annotation forms** — parses and serializes `{| |}`, `~ :r`, `<<( )>>`, and `<< >>` syntax
- **SPARQL 1.2** — triple-term patterns rewritten to SPARQL 1.1 for `rdflib` compatibility; `isTripleTerm()`, `SUBJECT()`, `PREDICATE()`, `OBJECT()` functions supported
- **CONSTRUCT queries** — result graph is a `StarlightGraph` with TripleTerms correctly restored
- **8 serialization formats** — `turtle12`, `longturtle12`, `nt12`, `nq12`, `trig12`, `trix12`, `rdfxml12`, `jsonld12`
- **W3C conformance** — passes the W3C Turtle 1.2 test suite (29 `TestTurtleEval` cases)
- **Multiple backends** — in-memory (default), SQL via `rdflib-sqlalchemy`, Apache Fuseki (`rdf-1.1` and `rdf-star` modes), Oxigraph (`rdf-1.2` native mode)
- **PEP 561** — `py.typed` marker included; package is typed
