# Changelog

## 0.1.0 — 2026-05-14

Initial public release.

### Features

- **`StarlightGraph`** — drop-in replacement for `rdflib.Graph` with full RDF 1.2 support
- **Triple terms** — `TripleTerm` objects as first-class Python values; content-addressed internal encoding (`tt:HASH`)
- **All annotation forms** — parses and serializes `{| |}`, `~ :r`, `<<( )>>`, and `<< >>` syntax
- **SPARQL 1.2** — triple-term patterns rewritten to SPARQL 1.1 for `rdflib` compatibility; `isTripleTerm()`, `SUBJECT()`, `PREDICATE()`, `OBJECT()` functions supported
- **CONSTRUCT queries** — result graph is a `StarlightGraph` with TripleTerms correctly restored
- **8 serialization formats** — `turtle12`, `longturtle12`, `nt12`, `nq12`, `trig12`, `trix12`, `rdfxml12`, `jsonld12`
- **W3C conformance** — passes the W3C Turtle 1.1 test suite
- **Multiple backends** — in-memory (default), SQL via `rdflib-sqlalchemy`, Apache Fuseki (`rdf-1.1` and `rdf-star` modes), Oxigraph (`rdf-1.2` native mode)
- **PEP 561** — `py.typed` marker included; package is typed
