# StarlightGraph Performance

## Executive Summary

### In-memory: the right starting point

The in-memory backend is where you start. No server, no configuration — load your data and query it. For everyday workloads, it is fast enough that performance is not a consideration.

The ceiling is RAM. Each annotated fact requires roughly four times the storage of a plain triple. On a typical 16 GB laptop, you start to feel memory pressure around 100K annotated facts and hit a hard limit near 1.5 million. Plain triples scale much higher — several million fit comfortably.

Query speed depends on what you ask. Looking up annotations about a specific subject or object is nearly instant at any scale. Asking for *all* annotations at once is slower: roughly 150ms at 50K facts, 800ms at 250K, 1.7 seconds at 500K. If your application regularly needs to scan the full annotation set, this becomes a limitation.

Data does not survive using in-memory. Every restart requires reloading from a file or other external source.

### SQLite: persistence without a server — with a catch

SQLite solves two weaknesses of in-memory mode. Data persists across restarts, and graphs can grow beyond available RAM — millions of plain triples fit in a single file with no memory pressure.

For simple lookups — find everything about this subject — SQLite works well at any scale, staying under 35ms for 5 million triples.

A challenge is complex queries over annotated facts. At 250K annotated triples, a query that scans all annotations takes 54 seconds in SQLite versus less than a second in memory — a 67× gap. The more patterns a query combines, the worse it gets. **SQLite is not a suitable backend for workloads that regularly query large numbers of annotated facts.**

### Fuseki (rdf-1.1): eliminating the query performance problem

Fuseki is an open-source RDF server that evaluates SPARQL queries natively. When StarlightGraph sends a query to Fuseki, Fuseki handles the entire query at once rather than executing it piece by piece. This eliminates the performance problem that makes SQLite slow, and it also outperforms in-memory for broad queries — the same full-annotation scan that takes 800ms in memory at 250K facts takes 580ms via Fuseki, and 1.2 seconds versus 1.7 seconds at 500K. Data persists across restarts and is not limited by available RAM.

Fuseki requires running a server.

### Fuseki (rdf-star): further improvement through native storage

The rdf-star mode stores annotated facts as native quoted triples rather than as sets of component triples. This reduces the amount of data stored in Fuseki by 20%, and gives Fuseki's query engine a more direct rdf-star representation to work with. The result is a consistent 20–40% improvement in query speed across all query types: the same 250K scan drops from 580ms to 460ms, and a combined scan-and-filter query drops from 525ms to 317ms. At 500K facts the full-annotation scan is 1.0 second versus 1.2 seconds in rdf-1.1 mode.

Note that Fuseki supports an older rdf-star version than RDF 1.2.  

### Oxigraph (rdf-1.2): the fastest backend

Oxigraph is a Rust-based RDF 1.2 store. Running in in-memory mode, it is the fastest backend for broad queries at every scale tested. At 250K annotated facts, the full-annotation scan takes 168ms — 4.8× faster than in-memory Python, 2.7× faster than rdf-star/Fuseki. The combined scan-and-filter query takes 122ms, versus 317ms in Fuseki and 1.49 seconds in memory. The advantage comes from Oxigraph's compiled Rust SPARQL engine, native RDF 1.2 quoted-triple storage, and zero JVM overhead.

The only case where Oxigraph does not putperform is single lookups (finding all annotations for a specific subject or object), where Python's in-memory dict lookup at ~4ms beats Oxigraph's 30–100ms HTTP round-trip. For workloads dominated by broad scans or joins, Oxigraph is the clear choice. Like Fuseki, it requires running a server.

Oxigraph also ships as `pyoxigraph`, a Python extension that embeds the Rust library in-process with no HTTP overhead. This was not benchmarked here: users choosing direct-mode Oxigraph will generally not be using rdflib or StarlightGraph, since pyoxigraph exposes its own query API rather than the rdflib `Graph` interface.
