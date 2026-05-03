# areas of research.
1. look at how other tools that have implemented rdf 1.2 handle serilization and query before making changes
2. how do we intergrate with back-end databases




# Future Enhancements


 1. Consider an option to retain rr:hash on serialization to 1.2
2. parsing and serializing to other formats
3. all supported output formats 
4, (maybe we build on version 8 stable release)
4. per rdf 1.2 specification a triple can not be the subject of a triple. - should we allow
5. how to announce RDF version
6. should we serialize just to normal form of 1.2 or provide options for ttl
7. ~~review all out-of-box serialization formats and compare to our implementation~~ → see **Format Coverage** section below.




Ideas deferred from active development. Grouped by layer.

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

### rdflib formats not yet extended to RDF 1.2

**N3 / Notation3** (`n3`, `text/n3`)
N3 is a strict superset of Turtle, so our Turtle 1.2 parser already handles any triple-term syntax that also appears in Turtle.  The extra N3 constructs (formulae `{ }`, `@forAll`, `@forSome`) are not part of RDF 1.2 and do not require 1.2 treatment.  A lightweight `n3-12` format alias that routes to `turtle12` (with an explicit caveat that formulae are not supported) would give full coverage at near-zero cost.  Effort: **Very Low**.

**RDF/XML** (`xml`, `application/rdf+xml`, `pretty-xml`)
The RDF 1.2 spec defines XML serialization of triple terms via a new `rdf:TripleTerm` element containing `rdf:subject`, `rdf:predicate`, `rdf:object` child elements, and `rdf:reifies` as an attribute on property elements.  Implementing this requires writing a custom XML parser/serializer (rdflib's `rdf+xml` plugin does not support these constructs).  RDF/XML is still widely used for OWL ontologies and Linked Data.  Effort: **High**.

**TriX** (`trix`, `application/trix`)
TriX is an XML named-graph format.  Extending it to RDF 1.2 follows the same pattern as RDF/XML — new XML elements for triple terms — but it is less widely deployed than RDF/XML.  Effort: **Medium-High**.

**longturtle** (`longturtle`)
`longturtle` is rdflib's verbose Turtle variant (expanded predicates, one triple per line).  It uses exactly the same grammar as Turtle, so a `longturtle12` serializer could be a thin wrapper around `serialize_turtle12` that disables prefix folding and subject grouping.  Parsing `longturtle` already works via `turtle12` since the grammar is a subset.  Effort: **Very Low**.

### Not applicable

| Format | Reason |
|---|---|
| `hext` | HTML extraction; not an RDF authoring format |
| `patch` | SPARQL Update diff format; separate concern from RDF 1.2 triple terms |

---

## Serializer

**Annotation folding (`{| |}` syntax)**
Currently annotations serialize as separate `rdf:reifies` blocks:
```turtle
:s :p :o .
_:b0 :ann :val ;
    rdf:reifies <<( :s :p :o )>> .
```
A smarter serializer could detect this pattern and fold it back into inline annotation syntax:
```turtle
:s :p :o {| :ann :val |} .
```
Requires recognizing that a reification bnode's only non-annotation triple is `rdf:reifies`, and that the triple term matches a main triple in the graph.

**Named reifier folding (`~ :id` syntax)**
Same as annotation folding but for named reifiers. When a named URI is the reifier, emit:
```turtle
:s :p :o ~ :stmt {| :ann :val |} .
```

**Reification shorthand as subject (`<< s p o >>` syntax)**
When a reification node is used only as subject (and not as object of any triple), emit the `<< s p o >>` subject shorthand rather than a separate triple.

**Compact output — skip unused built-in prefixes**
rdflib's default NamespaceManager registers ~30 well-known prefixes (brick, csvw, foaf, etc.). The serializer currently emits all of them. Filter to only prefixes whose namespace actually appears in the graph's triples.

**N-Triples 1.2 serializer**
Flat line-per-triple format with `<<( s p o )>>` in node positions. Simpler than Turtle 1.2 (no prefix folding needed).

---

## Parser

**`StarlightGraph.parse(format="turtle12")` integration**
Currently `StarlightTurtleParser` must be called directly and the result wrapped with `from_rdflib()`. Wire TTL 1.2 parsing into `StarlightGraph.parse()` so the full pipeline is one call:
```python
g = StarlightGraph()
g.parse("data.ttl", format="turtle12")
```

**N-Triples 1.2 parser**
A simpler sibling to the TTL 1.2 parser — flat line format, no prefix declarations. The lexer already handles `<<( )>>` tokens so most of the work is already done.

**Base URI resolution**
The parser records `@base` declarations but does not fully resolve relative IRIs against the base. Full RFC 3986 resolution would be needed for strict conformance.

---

## Graph

**`StarlightGraph.triples()` wildcard triple-term patterns**
Pattern `(None, EX.mentions, (None, None, None))` should match any triple where the object is a triple term. Currently `(None, None, None)` as a tuple is treated as a wildcard that returns no results (collapsed to `None`). Implementing this requires iterating all known TT bnodes and doing a union query.

**`subjects()` / `objects()` with triple-term wildcards**
Same as above — `g.objects(subject=EX.s, predicate=(None, EX.knows, None))` finds all objects of triples whose subject is a triple term matching the inner pattern.

**`StarlightGraph.__iter__`**
Currently inherits rdflib's `__iter__` which yields raw bnodes for triple terms. Override to yield restored `TripleTerm` objects, so `for s, p, o in g:` works consistently with `g.triples()`.

**`from_rdflib` without copying**
The current `from_rdflib()` copies all triples into a new graph. A zero-copy variant could wrap the source graph's store directly, useful for large graphs.

---

## Query (SPARQL-star)

**SPARQL-star pattern rewriting**
Rewrite queries containing triple-term patterns like `<<?s :knows ?o>>` into equivalent SPARQL 1.1 queries over the internal bnode encoding before passing to rdflib's query engine.

**`StarlightGraph.query()` override**
Override `query()` to intercept and rewrite SPARQL-star syntax, then delegate to `super().query()`.

---

## Model

**`TripleTerm.n3()` method**
Add an `n3()` method so TripleTerm works with rdflib utilities that expect rdflib terms (e.g., `rdflib.compare.isomorphic()`). Currently these utilities fail because TripleTerm lacks the rdflib term interface.

**Immutability enforcement**
`TripleTerm.__slots__` is defined but `__setattr__` is not overridden, so the slots can still be written after construction. Add `__setattr__` to enforce true immutability.
