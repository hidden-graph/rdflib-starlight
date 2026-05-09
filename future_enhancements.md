# Starlight Future Enhancements

## Open Design Questions

- **RDF version declaration** — All four RDF 1.2 formats now emit a version hint when triple terms are present (`@version "1.2" .` for Turtle/TriG; `VERSION "1.2"` for N-Triples/N-Quads) and their parsers silently skip the declaration. No open items remain here.
- **Annotation syntax in serializer** — Emit the compact `{| |}` annotation shorthand or always use explicit `rdf:reifies` triples? The compact form is more readable but requires pattern-matching at serialize time (see Serializer section).
- **Backend database integration** — Both cases are implemented. (1) RDF 1.1 backend: TripleTerms encoded as `tt:HASH` URIRefs, SPARQL 1.2 rewritten to 1.1 before sending, `tt:HASH` URIRefs restored on return. (2) RDF 1.2 native backend: native quoted triples written to Fuseki (rdf-star) and Oxigraph (rdf-1.2) via HTTP; results converted from the store's quoted-triple JSON format back to TripleTerm objects. Open item: **embedded `pyoxigraph`** (see Backends section).

---

## rdflib 8 Compatibility

rdflib 8.0.0a0 (pre-release, from GitHub `main`) was tested against the full suite. One failure was found and fixed: `sl:Reification` marker triples injected during parsing were missing `_base_uri`, causing relative IRI subjects on `rdf:reifies` triples to be stored unresolved. The fix is in `main` (commit `60c343e`). Branch `rdf8-branch` exists for continued compatibility work when rdflib 8 reaches a stable release.

---

## Format Coverage

### Implemented RDF 1.2 formats

| Starlight format | rdflib alias(es) | Parse | Serialize | Notes |
|---|---|:---:|:---:|---|
| `turtle12` | `turtle`, `ttl`, `text/turtle` | ✅ | ✅ | Full RDF 1.2 with `<<( )>>` |
| `nt12` | `nt`, `ntriples`, `nt11` | ✅ | ✅ | Flat line-per-triple; single graph |
| `nq12` | `nquads` | ✅ | ✅ | N-Quads 1.2; StarlightDataset |
| `trig12` | `trig` | ✅ | ✅ | Named GRAPH blocks; StarlightDataset |
| `jsonld12` | `json-ld`, `application/ld+json` | ✅ | ✅ | tt:HASH nodes; rdflib JSON-LD parser used for input |
| `longturtle12` | `longturtle` | ✅ | ✅ | One triple per line; no subject/predicate grouping; parses via `turtle12` |
| `trix12` | `trix`, `application/trix` | ✅ | ✅ | XML `<graph>/<triple>` blocks; `<tripleTerm>` for RDF 1.2; StarlightDataset |
| `rdfxml12` | `xml`, `application/rdf+xml` | ✅ | ✅ | `<rdf:TripleTerm>` elements; inline for objects, nodeID for subjects |

### Formats not yet extended to RDF 1.2

**N3 / Notation3** (`n3`, `text/n3`) — Effort: Very Low
N3 is a superset of Turtle. Our Turtle 1.2 parser already handles any triple-term syntax that appears there. The extra N3 constructs — formulae (`{ }`), `@forAll`, and `@forSome` — are outside RDF 1.2 scope and are not part of the RDF standard; they add first-order logic / reasoning capabilities that RDF deliberately omits. rdflib's own `n3` parser can read these constructs and stores formulae as embedded `Graph` objects, but does not execute the rules.

A lightweight `n3-12` alias that routes to `turtle12` gives full coverage for N3 files that are effectively Turtle with RDF 1.2 features at near-zero cost. For files that use genuine N3 logic constructs, we could fall back to rdflib's native `n3` parser and then import the resulting plain triples into a StarlightGraph — this would silently drop formulae but would allow Starlight to accept any file rdflib can accept.

*Note: decide whether we want a graceful rdflib fallback path so Starlight can parse any file rdflib handles, even when it cannot round-trip the N3-specific constructs.*

### Not applicable

| Format | Reason |
|---|---|
| `hext` | HTML extraction; not an RDF authoring format |
| `patch` | SPARQL Update diff format; separate concern from RDF 1.2 triple terms |

---

## Deferred Enhancements

### Serializer

**Annotation folding (`{| |}` syntax)** — ✅ Done
All five reification cases are handled by `_build_fold_map()` in `serialize_turtle12()`:
1. Asserted triple, anonymous reifier → `{| ann val |}` inline syntax
2. Asserted triple, named reifier → `~ :r {| ann val |}` tilde syntax
3. Unasserted triple, anonymous reifier(s) → `<<( s p o )>>` used as subject (multiple anonymous reifiers on same TT are merged)
4. Unasserted triple, named reifier → explicit subject (identity preserved, no compact form)
5. Many-to-one (NYT pattern: one reifier, multiple TTs) → explicit subject

**Reification shorthand as subject (`<< s p o >>` syntax)**
When a reification node appears only as subject (never as object), the RDF 1.2 Turtle grammar allows the `<< s p o >>` subject shorthand (without parens) rather than a separate triple. Currently not implemented — `<<( s p o )>>` with parens is always used.

---

### Parser

**Base URI resolution** — ✅ Done
`urljoin` (RFC 3986) replaces naive string concatenation in `_to_node`. Each `@base` declaration is resolved against the previously active base, and each triple is stamped with its active base at parse time so that multiple `@base` declarations in one file each apply only to the triples that follow them. `g.base` is set to the last active base. `_base_uri` is also propagated to injected `sl:Reification` marker triples so that relative IRI reifier subjects resolve correctly.

---

### Graph API

**`subjects()` / `objects()` with triple-term wildcards** — ✅ Already works
rdflib's `subjects()`, `objects()`, and `predicates()` all call `self.triples()` internally, so our wildcard fan-out is invoked automatically. No overrides needed. Verified: `g.subjects(RDF_REIFIES, (EX.alice, None, None))` returns all reifiers whose triple term has alice as subject.

**`from_rdflib` zero-copy variant**
`from_rdflib()` currently copies all triples into a new graph. A zero-copy variant would wrap the source graph's store directly, useful for large graphs loaded by rdflib tooling.

---

### Multi-graph (StarlightDataset)

**`query()` raw execution graph** — ✅ Cached
rdflib's `Memory` store stores the actual `StarlightGraph` Python objects as context keys. When the SPARQL engine evaluates `GRAPH ?g { }` it calls `contexts()` and then `triples()` on each returned object — which invokes `StarlightGraph.triples()` and filters encoding triples, breaking the rewritten SPARQL 1.1 patterns. A separate plain `Dataset` with unoverridden `Graph` contexts is required. `_build_raw_execution_graph()` now caches that plain `Dataset` and invalidates it only on `parse()` or `update()`, so the copy is paid at most once per mutation cycle.

---

### Model

**Immutability enforcement on `TripleTerm`** — ✅ Done
`__setattr__` now raises `AttributeError` on any post-init write to `subject`, `predicate`, or `object`. `_namespace_manager` remains freely settable (display-only mutable state, set by `_restore()`).

---

### Backends

**SQLite write-through mode**
A hybrid persistence model where SQLite is used purely as a durability layer and never as a query target. On startup the full graph is loaded from SQLite into memory; all subsequent `add()`/`remove()` calls write through to both the in-memory store and SQLite atomically; all `query()` calls run entirely in memory. SQLite is never asked to evaluate SPARQL, so the N×M round-trip problem does not apply.

```python
g = StarlightGraph.open_sqlite('graph.db')   # load into memory from SQLite
g.add(triple)                                # writes to in-memory + SQLite
list(g.query(sparql))                        # runs in-memory only
```

This occupies a useful position between pure in-memory (fast, no persistence) and SQLite-only (persistent, slow complex queries):

| | In-memory | SQLite write-through | SQLite-only |
|---|:---:|:---:|:---:|
| Query speed | ✓ fast | ✓ fast | ✗ N×M penalty |
| Persistence | ✗ | ✓ | ✓ |
| Server required | ✗ | ✗ | ✗ |
| Dataset fits in RAM | required | required | not required |
| Incremental writes | ✗ | ✓ | ✓ |

The write-through approach differs from the file-backed mode below in one key way: writes are incremental (each `add()` is one SQL INSERT) rather than requiring a full re-serialize on save, and recovery is immediate — no parse step on startup.

Implementation notes: `add()` and `addN()` would call `super()` for the in-memory path and then issue a parameterized SQL INSERT on the SQLite connection. `remove()` issues a DELETE. A transaction context manager around `addN()` batches the SQL writes to avoid per-triple commit overhead. The startup load uses the existing `_build_registry_from_store()` path.

**File-backed in-memory persistence mode**
A `StarlightGraph` persistence model that separates storage from query execution: the graph lives entirely in memory (fast queries, no SQL round-trip overhead) but serializes to and loads from a file on disk (Turtle 1.2 or N-Triples 1.2) for durability. The motivating use case is temporal queries — e.g. "all reified triples effective between two dates" — which require joining a TT pattern with two additional date predicates. Against a SQL backend, that query triggers N SQL round-trips per pattern (rdflib's SPARQL evaluator cannot push joins into SQL); against an in-memory store the same query runs in a single SPARQL pass.

The core capability already exists: `StarlightGraph().parse('graph.ttl')` loads into memory; `g.serialize('graph.ttl')` writes back. What is missing is a first-class lifecycle API:

```python
g = StarlightGraph.open('graph.ttl')    # load into memory, remember path
g.add(triple)                           # mutate in-memory
g.save()                                # write back to same path
g.close()                               # optional: clear memory
```

Possible extensions: `auto_save=True` flag to write on every mutation; async/periodic flush for long-running processes; atomic write (write to `.tmp`, then rename) to avoid corruption on crash.

Trade-offs vs SQLite: startup cost is loading the full file (vs SQLite's registry-only rebuild); no concurrent multi-process access; all data must fit in RAM. Appropriate when the graph fits in memory and query performance matters more than write-through durability.

**Direct `pyoxigraph` embedded backend**
`pyoxigraph` (Rust bindings) provides a `Store` object with native RDF 1.2 support — no HTTP server required. `Store()` is in-memory; `Store(path=...)` is RocksDB-backed and persistent. A new backend mode (e.g. `'oxigraph-embedded'`) would call `pyoxigraph.Store` directly instead of the HTTP functions, eliminating the Docker/server dependency entirely and enabling fast in-process testing against a real RDF 1.2 store.

The HTTP-mode benchmark (`bench_oxigraph.py`) gives a baseline: at 250K TTs, Oxigraph via HTTP delivers 168ms wildcard scans and 122ms join queries — already the fastest backend. Embedded mode would eliminate the ~30ms HTTP round-trip floor, making Oxigraph competitive on point lookups as well. The main integration cost is translating between `pyoxigraph` term types and rdflib `URIRef`/`Literal`/`BNode`/`TripleTerm`.
