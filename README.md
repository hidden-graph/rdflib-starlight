# rdflib-starlight

**RDF 1.2** was published as a W3C Candidate Recommendation on April 7, 2026. It represents the formal standardization of RDF-star, a community-driven extension to RDF that had been under development since 2019. The primary change RDF 1.2 introduces is **reification** — the ability to make statements *about* statements. RDF 1.2 makes reification a first-class feature of the data model through **triple terms** — triples that can themselves appear as the object of other triples.

**rdflib** (current version 7.6.0) is based on RDF 1.1 and does not support the reification features of RDF 1.2.

**rdflib-starlight** is a lightweight wrapper that extends rdflib to handle the reification features of RDF 1.2. It is intended to remain relevant until rdflib is updated to incorporate the final RDF 1.2 specification.

rdflib-starlight works by translating RDF 1.2 data and queries into RDF 1.1 format internally, so that rdflib can process them natively. It can operate fully in-memory, or use the backend storage options supported by rdflib — including Fuseki, SQL, and Oxigraph. When the backend natively supports RDF 1.2, rdflib-starlight delegates storage and querying to it directly.

```
pip install rdflib-starlight
```

## What it looks like

```turtle
# Who said what, with supporting evidence
:bob :knows :carol {| :since "2020" ; :source :Wikipedia ; :confidence "0.9" |} .

# Alice's statement refers to the same fact as a triple term
:alice :says <<( :bob :knows :carol )>> .

# The research team verified it independently
<< :bob :knows :carol >> :verifiedBy :ResearchTeam .
```

Loading and querying this in Python:

```python
from starlight.graph.starlight_graph import StarlightGraph

g = StarlightGraph()
g.parse('facts.ttl')

# Find all sources for a specific fact
results = g.query("""
    PREFIX : <http://example.org/>
    SELECT ?stmt ?source WHERE {
      ?stmt rdf:reifies <<( :bob :knows :carol )>> .
      OPTIONAL { ?stmt :source ?source . }
    }
""")
```

Serializing back produces clean, compact Turtle 1.2 — the library folds reification
structures into the shortest valid syntax automatically:

```turtle
@version "1.2" .
@prefix : <http://example.org/> .

:alice :says <<( :bob :knows :carol )>> .
:bob :knows :carol {| :confidence "0.9" ; :since "2020" ; :source :Wikipedia |} .
<< :bob :knows :carol >> :verifiedBy :ResearchTeam .
```

## Key features

- **Drop-in replacement for rdflib.Graph** — `StarlightGraph` subclasses `rdflib.Graph`; existing rdflib code works unchanged
- **Full RDF 1.2 data model** — triple terms are first-class Python objects (`TripleTerm`), not encoded strings
- **All annotation forms** — parses and serializes `{| |}`, `~ :r`, `<<( )>>`, and `<< >>` syntax
- **SPARQL 1.2** — queries with triple term patterns are rewritten transparently to SPARQL 1.1 for broad backend compatibility
- **8 serialization formats** — Turtle, N-Triples, N-Quads, TriG, JSON-LD, TriX, RDF/XML, longturtle
- **W3C conformance** — passes the W3C Turtle 1.2 test suite
- **Multiple backends** — in-memory, SQL (via rdflib-sqlalchemy), Apache Fuseki, Oxigraph

## Format support

| Format | Parse | Serialize |
|---|:---:|:---:|
| Turtle 1.2 (`turtle`, `ttl`) | ✅ | ✅ |
| N-Triples 1.2 (`nt`) | ✅ | ✅ |
| N-Quads 1.2 (`nquads`) | ✅ | ✅ |
| TriG 1.2 (`trig`) | ✅ | ✅ |
| JSON-LD 1.2 (`json-ld`) | ✅ | ✅ |
| Long Turtle 1.2 (`longturtle`) | ✅ | ✅ |
| TriX 1.2 (`trix`) | ✅ | ✅ |
| RDF/XML 1.2 (`xml`) | ✅ | ✅ |
| N3 / Notation3 (`n3`) | ✅ | — |

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

# Oxigraph — native RDF 1.2 store
g = StarlightGraph(backend='rdf-1.2',
                   query_url='http://localhost:7878/query',
                   update_url='http://localhost:7878/update')
```

## Requirements

- Python 3.10+
- rdflib >= 7.0

## License

MIT
