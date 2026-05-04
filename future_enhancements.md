# Starlight Future Enhancements

## Open Design Questions

- **RDF version declaration** — Should serialized output include a version marker (e.g. a comment or magic token) so consumers know they are reading RDF 1.2? No standard mechanism exists yet.
- **Annotation syntax in serializer** — Emit the compact `{| |}` annotation shorthand or always use explicit `rdf:reifies` triples? The compact form is more readable but requires pattern-matching at serialize time (see Serializer section).
- **Backend database integration** — How to persist the tt:HASH encoding and TripleTerm registry in a triple store (e.g. GraphDB, Stardog, Apache Jena Fuseki). Custom IRI prefix conventions or named-graph sidecars are candidate approaches.

---

## Format Coverage

### Implemented RDF 1.2 formats

| Starlight format | rdflib alias(es) | Parse | Serialize | Notes |
|---|---|:---:|:---:|---|
| `turtle12` | `turtle`, `ttl`, `text/turtle` | ✅ | ✅ | Full RDF 1.2 with `<<( )>>` |
| `nt12` | `nt`, `ntriples`, `nt11` | ✅ | ✅ | Flat line-per-triple; single graph |
| `nq12` | `nquads` | ✅ | ✅ | N-Quads 1.2; StarlightConjunctiveGraph |
| `trig12` | `trig` | ✅ | ✅ | Named GRAPH blocks; StarlightConjunctiveGraph |
| `jsonld12` | `json-ld`, `application/ld+json` | ✅ | ✅ | tt:HASH nodes; rdflib JSON-LD parser used for input |

### Formats not yet extended to RDF 1.2

**N3 / Notation3** (`n3`, `text/n3`) — Effort: Very Low
N3 is a superset of Turtle. Our Turtle 1.2 parser already handles any triple-term syntax that appears there. The extra N3 constructs (formulae `{ }`, `@forAll`, `@forSome`) are outside RDF 1.2 scope. A lightweight `n3-12` alias that routes to `turtle12` (with a caveat that formulae are unsupported) gives full coverage at near-zero cost.

**longturtle** (`longturtle`) — Effort: Very Low
rdflib's verbose Turtle variant (one triple per line, no grouping). A `longturtle12` serializer is a thin wrapper over `serialize_turtle12` that disables subject grouping and predicate folding. Parsing already works via `turtle12`.

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

**Compact output — skip unused built-in prefixes**
rdflib's default NamespaceManager registers ~30 well-known prefixes (brick, csvw, foaf, etc.). The serializer currently emits all of them. Filter to only prefixes whose namespace appears in the graph's actual triples.

---

### Parser

**Base URI resolution**
The parser records `@base` declarations but does not fully resolve relative IRIs against the base. Full RFC 3986 resolution is needed for strict conformance.

---

### Graph API

**`StarlightGraph.triples()` wildcard triple-term patterns**
`(None, EX.mentions, (None, None, None))` should match any triple whose object is a triple term. Currently a tuple in the pattern position is collapsed to `None`. Implementing this requires iterating known tt: URIRefs and doing a union query.

**`subjects()` / `objects()` with triple-term wildcards**
Same as above — e.g. `g.objects(EX.s, predicate=(None, EX.knows, None))` should find all objects of triples whose subject matches a triple-term pattern.

**`StarlightGraph.__iter__`**
Inherits rdflib's `__iter__`, which yields raw bnode encodings for triple terms. Override to yield restored `TripleTerm` objects so `for s, p, o in g:` is consistent with `g.triples()`.

**`from_rdflib` zero-copy variant**
`from_rdflib()` currently copies all triples into a new graph. A zero-copy variant would wrap the source graph's store directly, useful for large graphs loaded by rdflib tooling.

---

### Multi-graph (StarlightConjunctiveGraph)

**`StarlightConjunctiveGraph.query()`**
The conjunctive graph has no `query()` override, so SPARQL-star patterns are not rewritten when querying across named graphs. Override `query()` to apply the same `rewrite_sparql12_to_11` logic used by `StarlightGraph.query()`, then post-process results to restore TripleTerms across all contexts.

**`StarlightConjunctiveGraph.update()`**
Same gap as `query()` — SPARQL UPDATE with triple-term patterns is not rewritten for the multi-graph case. After UPDATE execution, per-graph registries may also need rebuilding via `_build_registry_from_store()`.

---

### Model

**Immutability enforcement on `TripleTerm`**
`TripleTerm.__slots__` is defined but `__setattr__` is not overridden, so the three slots can still be written after construction. Add `__setattr__` to raise `AttributeError` on any post-init write, enforcing the value-type contract.
