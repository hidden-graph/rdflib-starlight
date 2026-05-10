# Benchmarks

Performance benchmarks for rdflib-starlight across all supported backends.

## Requirements

Each script targets a specific backend. Install only what you need:

| Script | Requires |
|---|---|
| `bench_inmemory.py` | No server — runs standalone |
| `bench_fuseki.py` | Apache Fuseki running on `localhost:3030` |
| `bench_fuseki_rdf11.py` | Apache Fuseki (RDF 1.1 mode) on `localhost:3030` |
| `bench_fuseki_rdfstar.py` | Apache Fuseki (RDF-star mode) on `localhost:3030` |
| `bench_oxigraph.py` | Oxigraph running on `localhost:7878` |
| `bench_http.py` | Any SPARQL endpoint |

## Running

```bash
# In-memory — no server needed
python benchmarks/bench_inmemory.py

# Fuseki — start server first, then:
python benchmarks/bench_fuseki.py
```

## Starting Fuseki

Download Apache Fuseki from https://jena.apache.org/download/ and run:

```bash
./fuseki-server --mem /ds
```

## Starting Oxigraph

Download Oxigraph from https://github.com/oxigraph/oxigraph and run:

```bash
./oxigraph serve --location /tmp/oxigraph
```

## Results summary

See [performance.md](../performance.md) for benchmark results and backend recommendations.
