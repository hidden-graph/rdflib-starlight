# Starlight Future Enhancements

## Format Coverage

| Starlight format | rdflib alias(es) | Parse | Serialize | Notes |
|---|---|:---:|:---:|---|
| `turtle12` | `turtle`, `ttl`, `text/turtle` | ✅ | ✅ | Full RDF 1.2 with `<<( )>>` and `{| |}` annotation folding |
| `nt12` | `nt`, `ntriples`, `nt11` | ✅ | ✅ | Flat line-per-triple; single graph |
| `nq12` | `nquads` | ✅ | ✅ | N-Quads 1.2; StarlightDataset |
| `trig12` | `trig` | ✅ | ✅ | Named GRAPH blocks; StarlightDataset |
| `jsonld12` | `json-ld`, `application/ld+json` | ✅ | ✅ | tt:HASH nodes; rdflib JSON-LD parser used for input |
| `longturtle12` | `longturtle` | ✅ | ✅ | One triple per line; no subject/predicate grouping |
| `trix12` | `trix`, `application/trix` | ✅ | ✅ | XML `<graph>/<triple>` blocks; `<tripleTerm>` for RDF 1.2 |
| `rdfxml12` | `xml`, `application/rdf+xml` | ✅ | ✅ | `<rdf:TripleTerm>` elements; inline for objects, nodeID for subjects |
| `n3` / `n3-12` / `text/n3` | — | ✅ | — | Routes to `turtle12`; N3 logic constructs (formulae, `@forAll`) are out of scope for RDF 1.2 |

---

## Open Items

### Backends

**Direct `pyoxigraph` embedded backend**
`pyoxigraph` (Rust bindings) provides a `Store` object with native RDF 1.2 support — no HTTP server required. `Store()` is in-memory; `Store(path=...)` is RocksDB-backed and persistent. A new backend mode (e.g. `'oxigraph-embedded'`) would call `pyoxigraph.Store` directly instead of the HTTP functions, eliminating the Docker/server dependency entirely and enabling fast in-process testing against a real RDF 1.2 store.

At 250K TTs, Oxigraph via HTTP delivers 168ms wildcard scans and 122ms join queries. Embedded mode would eliminate the ~30ms HTTP round-trip floor, making Oxigraph competitive on point lookups as well. The main integration cost is translating between `pyoxigraph` term types and rdflib `URIRef`/`Literal`/`BNode`/`TripleTerm`.

---

## rdflib 8 Compatibility

rdflib 8.0.0a0 (pre-release) was tested; one bug was found and fixed (commit `60c343e`). Branch `rdf8-branch` exists for continued work. Revisit when a stable release arrives.
