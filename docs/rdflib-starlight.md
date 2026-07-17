# rdflib-starlight — Architecture & Design

## What is it

rdflib-starlight is an extension layer over [rdflib](https://rdflib.readthedocs.io/) that adds first-class support for **RDF 1.2**, including triple terms, `rdf:reifies` reification, and SPARQL 1.2 syntax.

It is not a replacement for rdflib. It wraps rdflib's RDF 1.1 storage and execution engine with a translation layer that hides the internal RDF 1.1 encoding.

---

## Core Concepts

**TripleTerm** — An RDF 1.2 triple term `<<( s p o )>>` in object position. In Python, represented as a `TripleTerm(s, p, o)` instance. A plain 3-tuple in object position is automatically promoted to a TripleTerm.

**Content-addressed encoding** — TripleTerms are stored internally as `tt:HASH` URIRefs, where the hash is a SHA-256 content address of the triple's components. The same triple term always maps to the same URI, enabling identity comparison without a central registry. The encoding is invisible to all public APIs.

**DirLangString** — An RDF 1.2 base-direction-tagged literal `"text"@lang--dir` (e.g. `"مرحبا"@ar--rtl`). In Python, represented as a `DirLangString(value, language, direction)` instance. Internally it's a plain `rdflib.Literal` whose `datatype=` URI packs `(language, direction)` — `Literal(text, lang="en--rtl")` itself raises in rdflib, but validation never fires for `datatype=`. Unlike TripleTerm, no registry is needed: the encoding is a pure function of the value, so decoding happens wherever `StarlightGraph` already restores a result to the caller.

**StarlightGraph** — The main entry point. A subclass of `rdflib.Graph` that intercepts reads and writes to encode/decode TripleTerms transparently. All rdflib traversal methods (`subjects()`, `objects()`, iteration, etc.) inherit correct TripleTerm behaviour automatically because they all funnel through the overridden `triples()` method.

**StarlightDataset** — A subclass of `rdflib.Dataset` for multi-graph RDF 1.2. Each named graph is a `StarlightGraph` with its own TripleTerm registry.

**Backends** — The default backend stores triples in rdflib's in-memory store and rewrites SPARQL 1.2 queries to SPARQL 1.1 before execution. The native `rdf-1.2` backend bypasses rdflib's SPARQL stack and talks directly to a SPARQL endpoint via HTTP, passing queries through in the endpoint's native syntax (confirmed against Fuseki 5.5+ and Oxigraph). An earlier `rdf-star` backend targeting an older, pre-standardization Jena draft syntax was removed 2026-07-16 after live testing found it broken against current Fuseki — see `docs/future_enhancements.md`.

---

## Package Structure

| Module | Responsibility |
|---|---|
| `starlight/model/` | `TripleTerm` class and `tt_hash()` content-address function |
| `starlight/graph/` | `StarlightGraph` and `StarlightDataset` — the public API |
| `starlight/parsers/` | Format-specific RDF 1.2 parsers (Turtle 1.2, N-Triples 1.2, N-Quads 1.2, TriG 1.2) |
| `starlight/serializers/` | Format-specific RDF 1.2 serializers (same formats) |
| `starlight/query/` | SPARQL 1.2 → SPARQL 1.1 rewriter for the default backend |
| `starlight/backends/` | HTTP utilities for the native rdf-1.2 endpoint |

---



## Further Reading

- [starlight_vs_rdflib.md](starlight_vs_rdflib.md) — full method-by-method coverage tracker: what is overridden, what is inherited, what is Starlight-only
- [sparql12_design.md](sparql12_design.md) — SPARQL 1.2 query support, rewrite strategy, and query examples
- [starlight_graph_model.md](starlight_graph_model.md) — internal graph model and encoding details
