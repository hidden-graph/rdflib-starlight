# rdflib-starlight

**RDF 1.2** was published as a W3C Candidate Recommendation on April 7, 2026. It represents the formal standardization of RDF-star, a community-driven extension to RDF that had been under development since 2019. The primary change RDF 1.2 introduces is **reification** — the ability to make statements *about* statements. RDF 1.2 makes reification a first-class feature of the data model through **triple terms** — triples that can themselves appear as the object of other triples.

**rdflib** (current version 7.6.0) is based on RDF 1.1 and does not support the reification features of RDF 1.2.

**rdflib-starlight** is a lightweight wrapper that extends rdflib to handle the reification features of RDF 1.2. It is intended to remain relevant until rdflib is updated to incorporate the final RDF 1.2 specification.

rdflib-starlight works by translating RDF 1.2 data and queries into RDF 1.1 format internally, so that rdflib can process them natively. It can operate fully in-memory, or use the backend storage options supported by rdflib — including Fuseki, SQL, and Oxigraph. When the backend natively supports RDF 1.2, rdflib-starlight delegates storage and querying to it directly.

> **Scope note:** rdflib-starlight focuses on reification — the RDF 1.2 feature most immediately useful to developers. Other RDF 1.2 additions, such as base-direction support for language-tagged literals (`"text"@en--ltr`), are not currently implemented.

```
pip install rdflib-starlight
```

## Key features

- **Drop-in replacement for rdflib.Graph** — `StarlightGraph` subclasses `rdflib.Graph`; existing rdflib code works unchanged
- **Full RDF 1.2 data model** — triple terms are first-class Python objects (`TripleTerm`), not encoded strings
- **All annotation forms** — parses and serializes `{| |}`, `~ :r`, `<<( )>>`, and `<< >>` syntax
- **SPARQL 1.2** — queries with triple term patterns are rewritten to SPARQL 1.1 for compatibility
- **8 serialization formats** — Turtle, N-Triples, N-Quads, TriG, JSON-LD, TriX, RDF/XML, longturtle
- **W3C conformance** — passes the W3C Turtle 1.2 test suite
- **Multiple backends** — in-memory, SQL (via rdflib-sqlalchemy), Apache Fuseki, Oxigraph

## Requirements

- Python 3.10+
- rdflib >= 7.0

## Quick start

Use `StarlightGraph` in place of `rdflib.Graph`. Everything else stays the same — parse, query, and serialize just as you would with rdflib.

Given an input file `example.ttl`:

```turtle
@prefix : <http://example.org/> .

:bob :knows :carol {| :since "2020" ; :source :Wikipedia |} .
:alice :says <<( :bob :knows :carol )>> .
:alice :believes <<( :bob :knows :mike )>> .
```

The last triple uses an **unasserted triple term** — `:bob :knows :mike` is referenced as a value without being a standalone fact in the graph.

```python
from starlight.graph.starlight_graph import StarlightGraph

g = StarlightGraph()
g.parse('example.ttl')

# Query using SPARQL 1.2 triple-term patterns
results = g.query("""
    PREFIX : <http://example.org/>
    SELECT ?source WHERE {
      ?stmt rdf:reifies <<( :bob :knows :carol )>> .
      ?stmt :source ?source .
    }
""")
for row in results:
    print(row.source)
```

```
http://example.org/Wikipedia
```

Use a CONSTRUCT query to rebuild the annotated triple from variables, then serialize — the serializer folds the reification into compact annotation syntax automatically:

```python
result = g.query("""
    PREFIX : <http://example.org/>
    CONSTRUCT {
        ?s ?p ?o .
        ?stmt rdf:reifies <<( ?s ?p ?o )>> .
        ?stmt ?attr ?val .
    }
    WHERE {
        ?stmt rdf:reifies <<( ?s ?p ?o )>> .
        ?stmt ?attr ?val .
    }
""")
print(result.serialize(format='turtle'))
```

```turtle
@version "1.2" .
@prefix : <http://example.org/> .

:bob :knows :carol {| :since "2020" ; :source :Wikipedia |} .
```

## Backends

```python
# In-memory (default) — fastest, no setup required
g = StarlightGraph()

# Persistent SQL store via rdflib-sqlalchemy
g = StarlightGraph(store='SQLAlchemy')
g.open('sqlite:///graph.db', create=True)

# Apache Fuseki — SPARQL endpoint with RDF 1.1 encoding
g = StarlightGraph(backend='rdf-1.1',
                   query_url='http://localhost:3030/ds/sparql',
                   update_url='http://localhost:3030/ds/update')

# Apache Fuseki — SPARQL endpoint with RDF star encoding (not RDF 1.2 compliant)
g = StarlightGraph(backend='rdf-star',
                   query_url='http://localhost:3030/ds/sparql',
                   update_url='http://localhost:3030/ds/update')

# Oxigraph — native RDF 1.2 store
g = StarlightGraph(backend='rdf-1.2',
                   query_url='http://localhost:7878/query',
                   update_url='http://localhost:7878/update')
```

## License

MIT
