# Starlight Future Enhancements

## Open Design Questions

- **RDF version declaration** — All four RDF 1.2 formats now emit a version hint when triple terms are present (`@version "1.2" .` for Turtle/TriG; `VERSION "1.2"` for N-Triples/N-Quads) and their parsers silently skip the declaration. No open items remain here.
- **Annotation syntax in serializer** — Emit the compact `{| |}` annotation shorthand or always use explicit `rdf:reifies` triples? The compact form is more readable but requires pattern-matching at serialize time (see Serializer section).
- **Backend database integration** — How to persist the tt:HASH encoding and TripleTerm registry in a triple store (e.g. GraphDB, Stardog, Apache Jena Fuseki). Custom IRI prefix conventions or named-graph sidecars are candidate approaches.  (Note - need to determine whehter the backend supprots rdf1.2 or not.  if it does not, then we write and query 1.1 trasnforamtions.  if it does, then we have the opportunity to write and query 1.2 with quoted triples.)

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

### Formats not yet extended to RDF 1.2

**N3 / Notation3** (`n3`, `text/n3`) — Effort: Very Low
N3 is a superset of Turtle. Our Turtle 1.2 parser already handles any triple-term syntax that appears there. The extra N3 constructs — formulae (`{ }`), `@forAll`, and `@forSome` — are outside RDF 1.2 scope and are not part of the RDF standard; they add first-order logic / reasoning capabilities that RDF deliberately omits. rdflib's own `n3` parser can read these constructs and stores formulae as embedded `Graph` objects, but does not execute the rules.

A lightweight `n3-12` alias that routes to `turtle12` gives full coverage for N3 files that are effectively Turtle with RDF 1.2 features at near-zero cost. For files that use genuine N3 logic constructs, we could fall back to rdflib's native `n3` parser and then import the resulting plain triples into a StarlightGraph — this would silently drop formulae but would allow Starlight to accept any file rdflib can accept.

*Note: decide whether we want a graceful rdflib fallback path so Starlight can parse any file rdflib handles, even when it cannot round-trip the N3-specific constructs.*

**longturtle** (`longturtle`) — ✅ Implemented as `longturtle12`
One triple per line; no subject or predicate grouping; `@version` and `@prefix` handling identical to `turtle12`. Parse routes to the Turtle 1.2 parser (longturtle is valid Turtle).

**RDF/XML** (`xml`, `application/rdf+xml`, `pretty-xml`) — Effort: High
The RDF 1.2 spec defines XML serialization for triple terms via a new `rdf:TripleTerm` element and a `rdf:reifies` attribute on property elements. rdflib's existing `rdf+xml` plugin does not support these constructs; a custom XML parser/serializer is needed. RDF/XML remains widely used for OWL ontologies.

**TriX** (`trix`, `application/trix`) — Effort: Medium-High
XML-based named-graph format. Extending to RDF 1.2 follows the same pattern as RDF/XML. Less widely deployed but useful for XML-native toolchains.

### Not applicable

| Format | Reason |
|---|---|
| `hext` | HTML extraction; not an RDF authoring format |
| `patch` | SPARQL Update diff format; separate concern from RDF 1.2 triple terms |

---

## Deferred Enhancements

### Serializer

**Annotation folding (`{| |}` syntax)**
Currently annotations serialize as separate `rdf:reifies` blocks:
```turtle
:s :p :o .
_:b0 :ann :val ;
    rdf:reifies <<( :s :p :o )>> .
```
A smarter serializer detects this pattern and folds it into inline annotation syntax:
```turtle
:s :p :o {| :ann :val |} .
```
Requires recognizing that a reification bnode's only non-annotation triple is `rdf:reifies`, and that the triple term matches an asserted triple in the graph.

**Named reifier folding (`~ :id` syntax)**
Same as annotation folding but for named reifiers. When a named URI is the reifier, emit:
```turtle
:s :p :o ~ :stmt {| :ann :val |} .
```

**Reification shorthand as subject (`<< s p o >>` syntax)**
When a reification node appears only as subject (never as object), the RDF 1.2 Turtle grammar allows the `<< s p o >>` subject shorthand rather than a separate triple.

---

### Parser

**Base URI resolution**
The parser records `@base` declarations but does not fully resolve relative IRIs against the base. Full RFC 3986 resolution is needed for strict conformance.

---

### Graph API

**`subjects()` / `objects()` with triple-term wildcards**
`g.objects(subject, predicate=(None, EX.knows, None))` — `triples()` now supports wildcard tuple patterns, but the convenience methods `subjects()`, `objects()`, and `predicates()` delegate to rdflib's implementation which does not pass tuple patterns through. These would need thin overrides.

**`from_rdflib` zero-copy variant**
`from_rdflib()` currently copies all triples into a new graph. A zero-copy variant would wrap the source graph's store directly, useful for large graphs loaded by rdflib tooling.

---

### Multi-graph (StarlightDataset)

**`query()` copies all triples per call**
`_build_raw_execution_graph()` constructs a fresh plain `Dataset` on each `query()` call to ensure encoding triples are visible to the SPARQL engine's `GRAPH ?g` enumeration. For large datasets this is expensive. A cached raw graph that is invalidated on `update()` / `parse()` would reduce this to an amortized cost.

---

### Model

**Immutability enforcement on `TripleTerm`**
`TripleTerm.__slots__` is defined but `__setattr__` is not overridden, so the three slots can still be written after construction. Add `__setattr__` to raise `AttributeError` on any post-init write, enforcing the value-type contract.
