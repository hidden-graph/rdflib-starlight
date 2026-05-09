# rdflib-starlight

RDF 1.2 extension for [rdflib](https://github.com/RDFLib/rdflib) — first-class triple terms, reification, annotation folding, and SPARQL 1.2 query rewriting.

```
pip install rdflib-starlight
```

## Quick start

```python
from starlight.graph.starlight_graph import StarlightGraph

g = StarlightGraph()
g.parse(data="""
    PREFIX : <http://example.org/>
    :alice :says <<( :bob :knows :carol )>> .
    :bob :knows :carol {| :since "2020" ; :confidence "0.9" |} .
""", format='turtle')

# SPARQL 1.2
results = g.query("""
    PREFIX : <http://example.org/>
    SELECT ?stmt ?since WHERE {
      ?stmt rdf:reifies <<( :bob :knows :carol )>> .
      OPTIONAL { ?stmt :since ?since . }
    }
""")

# Serialize back to Turtle 1.2 with annotation folding
print(g.serialize(format='turtle'))
```

Output:
```turtle
@version "1.2" .
@prefix : <http://example.org/> .

:alice :says <<( :bob :knows :carol )>> .
:bob :knows :carol {| :confidence "0.9" ; :since "2020" |} .
```

## Features

- **Full RDF 1.2 data model** — `TripleTerm` as a first-class Python object
- **8 serialization formats** with triple term support
- **SPARQL 1.2** — query and update rewriting to SPARQL 1.1 for broad backend compatibility
- **Annotation folding** — serializer emits compact `{| |}`, `~ :r`, and `<< >>` syntax automatically
- **W3C conformance** — passes the W3C Turtle 1.2 test suite
- **Multiple backends** — in-memory, rdflib store plugins (rdflib-sqlalchemy, Sleepycat), Fuseki, Oxigraph

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

## Reification syntax

All four RDF 1.2 annotation forms are supported in both parsing and serialization:

```turtle
# Triple term in object position
:stmt rdf:reifies <<( :alice :knows :bob )>> .

# Inline annotation block (asserted triple)
:alice :knows :bob {| :since "2020" |} .

# Named reifier
:alice :knows :bob ~ :stmt {| :confidence "0.9" |} .

# Reification shorthand as subject (unasserted)
<< :alice :knows :bob >> :verifiedBy :ResearchTeam .
```

## Backends

```python
# In-memory (default)
g = StarlightGraph()

# rdflib store plugin (e.g. rdflib-sqlalchemy)
g = StarlightGraph(store='SQLAlchemy')
g.open('sqlite:///graph.db', create=True)

# Fuseki (rdf-1.1 encoding)
g = StarlightGraph(backend='rdf-1.1', query_url='http://localhost:3030/ds/sparql',
                   update_url='http://localhost:3030/ds/update')

# Oxigraph (native RDF 1.2)
g = StarlightGraph(backend='rdf-1.2', query_url='http://localhost:7878/query',
                   update_url='http://localhost:7878/update')
```

## Requirements

- Python 3.10+
- rdflib >= 7.0

## License

MIT
