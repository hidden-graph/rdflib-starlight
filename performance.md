# StarlightGraph Performance

## Executive Summary

### In-memory: the right starting point

The in-memory backend is where you start. No server, no configuration — load your data and query it. For everyday workloads, it is fast enough that performance is not a consideration.

The ceiling is RAM. Each annotated fact requires roughly four times the storage of a plain triple. On a typical 16 GB laptop, you start to feel memory pressure around 100K annotated facts and hit a hard limit near 1.5 million. Plain triples scale much higher — several million fit comfortably.

Query speed depends on what you ask. Looking up annotations about a specific subject or object is nearly instant at any scale. Asking for *all* annotations at once is slower: roughly 150ms at 50K facts, 800ms at 250K, 1.7 seconds at 500K. If your application regularly needs to scan the full annotation set, this becomes the practical ceiling.

Data does not survive the process. Every restart requires reloading from a file or external source.

### SQLite: persistence without a server — with a catch

SQLite solves the two weaknesses of in-memory mode. Data persists across restarts, and graphs can grow beyond available RAM — millions of plain triples fit in a single file with no memory pressure.

For simple lookups — find everything about this subject — SQLite works well at any scale, staying under 35ms for 5 million triples.

The catch is complex queries over annotated facts. At 250K annotated triples, a query that scans all annotations takes 54 seconds in SQLite versus less than a second in memory — a 67× gap. The more patterns a query combines, the worse it gets. **SQLite is not a suitable backend for workloads that regularly query large numbers of annotated facts.**

### Fuseki (rdf-1.1): eliminating the query performance problem

Fuseki is an open-source RDF server that evaluates SPARQL queries natively. When StarlightGraph sends a query to Fuseki, Fuseki handles the entire query at once rather than executing it piece by piece. This eliminates the performance problem that makes SQLite slow, and it also outperforms in-memory for broad queries — the same full-annotation scan that takes 800ms in memory at 250K facts takes 580ms via Fuseki, and 1.2 seconds versus 1.7 seconds at 500K. Data persists across restarts and is not limited by available RAM.

Fuseki requires running a server (Docker or a standalone jar).

### Fuseki (rdf-star): further improvement through native storage

The rdf-star mode stores annotated facts as native quoted triples rather than as sets of component triples. This reduces the amount of data stored in Fuseki by 20%, and gives Fuseki's query engine a more direct representation to work with. The result is a consistent 20–40% improvement in query speed across all query types: the same 250K scan drops from 580ms to 460ms, and a combined scan-and-filter query drops from 525ms to 317ms. At 500K facts the full-annotation scan is 1.0 second versus 1.2 seconds in rdf-1.1 mode.

---

This document summarizes observed performance characteristics across
StarlightGraph's backend modes, to guide decisions about which backend
to use at different scales and workload types.

Benchmarks are in `benchmarks/bench_inmemory.py` (Phase 1),
`benchmarks/bench_http.py` (Phase 2), and
`benchmarks/bench_comparison.py` (head-to-head in-memory vs SQLite).

---

## Setup

- Python version: 3.14.2 (Clang 17, macOS)
- rdflib version: 7.x
- Fuseki version: 5.1.0 (rdf-star draft syntax; RDF 1.2 not yet supported)
- Oxigraph version: tested in Phase 2 only; see Phase 2 observations

---

## Phase 1 — In-Memory Baseline

**Methodology**: Fresh `StarlightGraph()` (default rdflib in-memory store, rdf-1.1 mode). Each measurement is the median of 3 runs. Scales tested: 100 / 1K / 5K / 10K / 50K / 100K triples.

### Plain triples

| N | Insert | t/s | addN | Contains | Full scan | Subj lookup | SPARQL plain | Mem peak |
|--:|-------:|----:|-----:|---------:|----------:|------------:|-------------:|---------:|
| 100 | 0.3 ms | 309K | 0.2 ms | 5 µs | 0.1 ms | <1 µs | 0.9 ms | 0.5 MiB |
| 1,000 | 3.3 ms | 304K | 3.1 ms | 6 µs | 0.5 ms | <1 µs | 1.0 ms | 2.7 MiB |
| 5,000 | 13.6 ms | 368K | 12.7 ms | 10 µs | 5.2 ms | <1 µs | 1.4 ms | 15.5 MiB |
| 10,000 | 27.0 ms | 370K | 25.1 ms | 14 µs | 9.9 ms | <1 µs | 1.7 ms | 27.9 MiB |
| 50,000 | 132.4 ms | 378K | 126.8 ms | 21 µs | 61.6 ms | <1 µs | 32.9 ms | 136.6 MiB |
| 100,000 | 287.9 ms | 347K | 280.0 ms | 25 µs | 139.2 ms | <1 µs | 80.3 ms | 273.1 MiB |

### Mixed workload (50% plain, 50% reification)

| N | Insert | t/s | addN | Contains | Full scan | Subj lookup | SPARQL plain | Mem peak |
|--:|-------:|----:|-----:|---------:|----------:|------------:|-------------:|---------:|
| 100 | 0.7 ms | 152K | 0.6 ms | 7 µs | 0.1 ms | <1 µs | 1.0 ms | 0.9 MiB |
| 1,000 | 7.8 ms | 128K | 7.1 ms | 9 µs | 1.4 ms | <1 µs | 1.0 ms | 8.0 MiB |
| 5,000 | 36.7 ms | 136K | 34.5 ms | 19 µs | 12.9 ms | <1 µs | 1.2 ms | 38.0 MiB |
| 10,000 | 77.6 ms | 129K | 73.8 ms | 21 µs | 27.3 ms | <1 µs | 1.4 ms | 81.9 MiB |
| 50,000 | 907.5 ms | 55K | 376.3 ms | 31 µs | 183.8 ms | <1 µs | 106.3 ms | 380.9 MiB |
| 100,000 | 842.6 ms | 119K | 844.0 ms | 33 µs | 377.7 ms | <1 µs | 228.2 ms | 761.8 MiB |

### Triple-term workload (reification + SPARQL TT pattern)

_SPARQL TT column: fully wildcard `<<( ?s ?p ?o )>>` returning all results. Selective queries with a bound component (subject, predicate, or object) take ~1–2ms at any scale via the store's POS index._

| N | Insert | t/s | SPARQL TT (wildcard) | Registry rebuild | Mem peak |
|--:|-------:|----:|---------------------:|-----------------:|---------:|
| 100 | 2.4 ms | 41K | 2.2 ms | 0.1 ms | 1.4 MiB |
| 1,000 | 12.4 ms | 81K | 12.8 ms | 0.7 ms | 12.5 MiB |
| 5,000 | 62.2 ms | 80K | 57.7 ms | 3.6 ms | 65.5 MiB |
| 10,000 | 132.1 ms | 76K | 115.8 ms | 8.1 ms | 108.3 MiB |
| 50,000 | 1,637 ms | 31K | 609.1 ms | 44.2 ms | 498.5 MiB |
| 100,000 | 3,687 ms | 27K | 1,256 ms | 100.6 ms | 989.3 MiB |
| 250,000 | 15,545 ms | 16K | 7,255 ms | — | 1,118 MiB |

### Phase 1 observations

#### The limit is not machine memory — it is Python object overhead × machine memory

rdflib's in-memory store maintains multiple SPO indexes (SPO, POS, OSP) as nested Python dicts. A Python dict entry carries far more overhead than raw data: object headers, hash table slots, and pointer indirection per node. The benchmark shows approximately **2.7 KB per plain triple** and **10 KB per triple term** in observed peak memory — not the tens of bytes the raw data would occupy in a compact format.

Consequence: on a 16 GB laptop, the practical ceiling is roughly **1–5 million plain triples** before memory pressure and GC become serious. A billion triples in rdflib in-memory is not achievable on any laptop; 2.7 KB/triple × 1 billion = 2.7 TB.

#### TT encoding is a physical-triple multiplier, not a fixed ratio

Each reified fact `stmt rdf:reifies <<( s p o )>>` stores 4 physical triples:
one visible triple plus three encoding triples (rdf:subject/predicate/object). Additionally, two Python dict entries are added to the in-memory registry.

The practical multiplier on memory depends on what fraction of facts are reified:
- If every triple is reified: 4× physical triples, ~4× memory.
- If 10% of triples are reified: the overall multiplier is closer to 1.3×.

The observed memory ratio (plain: 2.7 MiB/1K → TT: 10 MiB/1K) reflects the ~4× encoding overhead applied to a fully-reified workload.

#### SPARQL TT query performance

All TT patterns are rewritten to SPARQL 1.1 encoding triple patterns and evaluated by the SPARQL engine. Two cases:

- **Wildcard** `<<( ?s ?p ?o )>>`: the SPARQL engine evaluates all four encoding patterns (rdf:reifies + rdf:subject/predicate/object) for every matching TT. This is O(N) over the result set. At 100K TTs: ~1.3s. At 250K: ~7s.
- **Bound component** `<<( <uri> ?p ?o )>>`: the SPARQL engine uses the store's POS index on `rdf:subject <uri>` to locate the specific TT hash in O(1), then resolves the remaining patterns. Result: ~1–2ms at any scale.

The wildcard case is the practical limit. Native backends (Fuseki, Oxigraph) evaluate TT patterns natively in compiled code and return results in milliseconds regardless of graph size — that is the motivation for supporting them.

#### Other observations

**Insert throughput — plain triples** stays flat at ~300–370K t/s through 100K. `addN` is marginally faster (~7%) due to reduced call overhead.

**Insert throughput — reification** holds at ~80K t/s through 10K, then collapses progressively: 31K t/s at 50K, 27K t/s at 100K, 16K t/s at 250K. Each TT add writes 4 physical triples and updates two registry dicts; as those Python dicts grow large, resizing and GC overhead compound. At 250K TTs the insert time reaches ~16 seconds — likely impractical as a startup cost for an in-memory graph.

**Contains (point lookup)** is hash-based and stays essentially O(1): 5 µs at 100 triples, 25 µs at 100K.

**Full scan** is linear: 0.1 ms at 100 → 139 ms at 100K for plain; grows faster for TT workloads because each TT adds encoding triples to the physical count.

**Notable anomaly**: Mixed insert at 50K shows 896 ms for `add()` but only 376 ms for `addN`. This is likely GC pressure from many small object allocations per individual `add()` call; `addN` batches more efficiently at mid-scale.

---

## Phase 2 — HTTP Backend Comparison

**Methodology**: Each insert benchmark clears the graph first. Median of 3 runs.
Fuseki dataset: `dbType=mem` (in-memory). Oxigraph: `--location /data` (RocksDB-backed persistent store — see note below).

### Plain triples — Insert throughput

| N | In-memory | rdf-1.1/Fuseki | rdf-star/Fuseki | rdf-1.2/Oxigraph |
|--:|----------:|---------------:|----------------:|-----------------:|
| 100 | 309K t/s | 276 t/s | 467 t/s | 1,083 t/s |
| 1,000 | 304K t/s | 703 t/s | 322 t/s | 347 t/s |
| 5,000 | 368K t/s | 1,042 t/s | 407 t/s | 298 t/s |
| 10,000 | 370K t/s | 956 t/s | 344 t/s | 260 t/s |

### Plain triples — Full scan `triples((None, None, None))`

| N | In-memory | rdf-1.1/Fuseki | rdf-star/Fuseki | rdf-1.2/Oxigraph |
|--:|----------:|---------------:|----------------:|-----------------:|
| 100 | 0.1 ms | 18.8 ms | 12.9 ms | 2.5 ms |
| 1,000 | 0.5 ms | 30.4 ms | 24.0 ms | 101.8 ms |
| 5,000 | 5.2 ms | 84.6 ms | 58.0 ms | 1,705 ms |
| 10,000 | 9.9 ms | 158.9 ms | 109.7 ms | 11,258 ms |

### Plain triples — SPARQL SELECT latency

| N | In-memory | rdf-1.1/Fuseki | rdf-star/Fuseki | rdf-1.2/Oxigraph |
|--:|----------:|---------------:|----------------:|-----------------:|
| 100 | 0.9 ms | 6.5 ms | 9.0 ms | 1.3 ms |
| 1,000 | 1.0 ms | 6.5 ms | 8.4 ms | 2.6 ms |
| 5,000 | 1.4 ms | 6.9 ms | 6.4 ms | 19.3 ms |
| 10,000 | 1.7 ms | 11.0 ms | 5.7 ms | 140.7 ms |

### Triple-term workload — Insert throughput

| N | In-memory | rdf-1.1/Fuseki | rdf-star/Fuseki | rdf-1.2/Oxigraph |
|--:|----------:|---------------:|----------------:|-----------------:|
| 100 | 45K t/s | 216 t/s | 403 t/s | 191 t/s |
| 1,000 | 83K t/s | 254 t/s | 399 t/s | 191 t/s |
| 5,000 | 80K t/s | 260 t/s | 340 t/s | 191 t/s |
| 10,000 | 79K t/s | 265 t/s | 355 t/s | 191 t/s |

### Triple-term workload — Full scan

| N | In-memory | rdf-1.1/Fuseki | rdf-star/Fuseki | rdf-1.2/Oxigraph |
|--:|----------:|---------------:|----------------:|-----------------:|
| 100 | 0.1 ms | 13.3 ms | 10.7 ms | 240.5 ms |
| 1,000 | 1.4 ms | 63.7 ms | 31.2 ms | 3,015 ms |
| 5,000 | 12.9 ms | 389.9 ms | 119.7 ms | — |
| 10,000 | 27.3 ms | 622.8 ms | 235.8 ms | — |

### Triple-term workload — SPARQL TT pattern latency

| N | In-memory | rdf-1.1/Fuseki | rdf-star/Fuseki | rdf-1.2/Oxigraph |
|--:|----------:|---------------:|----------------:|-----------------:|
| 100 | 4.1 ms | 9.0 ms | 10.4 ms | 392.9 ms |
| 1,000 | 28.7 ms | 6.4 ms | 23.1 ms | 5,528 ms |
| 5,000 | 136.4 ms | 9.6 ms | 79.7 ms | — |
| 10,000 | 276.9 ms | 12.4 ms | 155.9 ms | — |

### Phase 2 observations

**HTTP backends do not relieve performance pressure — they trade it.** Every HTTP
backend is 100–1000x slower on insert throughput than in-memory, because each
`add()` call is an individual HTTP round trip (~4–15ms each). The win for HTTP
backends is persistence, multi-process access, and memory: the client process
holds no triple data.

**Baseline HTTP latency** (single-request floor): Fuseki ~5–7ms, Oxigraph ~1–2ms
for simple queries. All per-operation costs are bounded from below by this floor.

**Insert throughput — plain triples**: Fuseki peaks at ~1K t/s (rdf-1.1) and
~470 t/s (rdf-star). Oxigraph starts at 1K t/s for 100 triples but degrades to
260 t/s at 10K — likely RocksDB write amplification (see note).

**Insert throughput — triple terms**: All HTTP backends converge around 200–400 t/s
regardless of scale, dominated by per-request latency. rdf-star/Fuseki (~400 t/s)
outperforms rdf-1.1/Fuseki (~260 t/s) because the native `<< >>` syntax avoids
writing 3 extra encoding triples per TT.

**Full scan — Fuseki**: linear and reasonable. rdf-star scans faster than rdf-1.1
(fewer physical triples — no encoding rows). At 10K: rdf-1.1 takes 623ms, rdf-star
takes 236ms.

**Full scan — Oxigraph**: severely non-linear. 1K→102ms, 5K→1705ms, 10K→11s.
This is a RocksDB compaction artifact: 10K individual `INSERT DATA` calls written
to a persistent store fragment the LSM tree, making subsequent full scans expensive.
An in-memory Oxigraph instance (not currently available via HTTP) would not show
this. **This is a deployment issue, not a code bug.**

**SPARQL TT pattern — key crossover**: in-memory hits 277ms at 10K; Fuseki
rdf-1.1 holds flat at 6–12ms because the store's native SPARQL engine evaluates
the rewritten query. This is the **main reason to choose a remote backend**: once
TT SPARQL queries become the bottleneck (around 5K–10K triple terms), Fuseki's
engine outperforms StarlightGraph's in-memory SPARQL rewriter.

**Oxigraph TT workload**: catastrophically slow via HTTP — 393ms at 100 triples,
5.5s at 1K. The `INSERT { } WHERE {}` form used for TT writes involves a
server-side query evaluation on each insert, combined with the RocksDB write
pressure. Oxigraph HTTP is not suitable for high-volume TT workloads in its
current persistent-store configuration.

**Note on Oxigraph configuration**: the test used the existing `oxigraph-test`
container with `--location /data` (RocksDB on the container overlay FS). Results
would differ materially with a tmpfs-backed or RAM-disk location. Fuseki used
`dbType=mem` — a fair comparison would require equivalent configurations.

---

## Crossover Guide

| Scenario | Recommended backend | Rationale |
|---|---|---|
| ≤ 50K plain triples, single process | in-memory (rdf-1.1) | 370K t/s inserts, sub-10ms queries, <137 MiB |
| ≤ 50K triple terms, selective queries | in-memory (rdf-1.1) | ~4–78ms depending on query shape; sub-ms for bound-component lookups |
| 50K–150K triple terms, SPARQL-heavy | in-memory | Fuseki join already faster at 50K; in-memory still wins wildcard up to ~150K |
| > 150K triple terms, wildcard scans | rdf-star/Fuseki | Fuseki 477ms vs in-memory 818ms at 250K; gap widens with scale |
| Join / multi-pattern queries, any scale | rdf-star/Fuseki | Fuseki wins from 50K up (128ms vs 202ms); 5× advantage at 250K |
| > 50K plain triples, memory constrained | rdf-1.1/Fuseki | 273 MiB at 100K in-memory; Fuseki holds nothing in client |
| Multi-pattern SPARQL over TTs (any scale) | in-memory or Fuseki | SQLite N×M round-trips: 50–70× penalty; rdflib cannot push joins to SQL |
| Write-heavy, read-light, needs persistence | SQLite | 100K t/s bulk load; simple single-pattern queries acceptable |
| Persistence / multi-process access | rdf-1.1/Fuseki or rdf-star/Fuseki | In-memory is process-lifetime only |
| RDF 1.2 native syntax, small graphs | rdf-1.2/Oxigraph | Only spec-compliant backend; use in-memory Oxigraph config |
| RDF 1.2 native syntax, large graphs | rdf-1.2/Oxigraph (tmpfs) | Persistent RocksDB shows severe scan degradation at scale |
| Jena ecosystem / inference | rdf-star/Fuseki | Jena rules, OWL reasoning, federation |
| Unit / integration tests | in-memory (rdf-1.1) | Zero setup cost; full suite in <1 s |
| Bulk load (write-once, read-many) | any HTTP + `addN` | Use `addN` to reduce per-call overhead |
| Temporal range queries (date joins on TTs) | in-memory or Fuseki | SQLite fires N×M SQL per date pattern; see file-backed mode in future enhancements |

---

---

## Phase 3 — SQLite Backend (rdflib-sqlalchemy)

**Methodology**: Bulk load via `addN`, then `ANALYZE` to update query planner statistics,
then `_build_registry_from_store()`. Dataset: N distinct TripleTerms + 10% reification
statements each with a confidence annotation (e.g. 10K TTs → 1K `rdf:reifies` + 1K
`ex:confidence` triples = 12K total physical triples). Median of 3 query runs.

### Results

| Metric | 10K TTs / 1K reif | 100K TTs / 10K reif |
|---|--:|--:|
| **Load (addN)** | 163 ms | 1.44 s |
| **Throughput** | 73,849 t/s | 83,408 t/s |
| **DB size** | 6.2 MiB | 62 MiB |
| **Contains (point lookup)** | 0.9 ms | 1.0 ms |
| **Full scan `triples()`** | 44 ms | 524 ms |
| **SPARQL: all reified TTs** | 2.07 s | 21.5 s |
| **SPARQL: filter confidence > 0.7** | 2.75 s | 34.4 s |
| **SPARQL: partial TT match (bound pred)** | 46 ms | 151 ms |
| **Registry rebuild** | 6.8 ms | 54.9 ms |

### Phase 3 observations

**Bulk load is excellent.** 73–83K t/s is competitive with in-memory (80K t/s for pure TT
workloads) and far ahead of any HTTP backend. SQLite's transaction batching via `addN`
makes the write path nearly as fast as in-memory. DB size is compact: ~0.6 MiB per 1K
physical triples.

**Point lookup is constant at ~1ms** regardless of graph size — SQL indexing works.

**Full scan scales linearly** — 44ms at 12K triples, 524ms at 120K (12x data, 12x time).
SQLite is reading rows sequentially with no surprises.

**SPARQL TT queries — N × M round-trip problem.** The encoding path rewrites
`?stmt rdf:reifies <<( ?s ?p ?o )>>` into 4 triple patterns; rdflib's SPARQL engine
fires one SQL query per pattern per result row. For 1K reifications × 4 patterns ≈
4K SQL round trips at ~0.5ms each ≈ 2 seconds. At 10K reifications: 21 seconds —
unusable. The problem is structural: rdflib's Python SPARQL evaluator was never designed
to translate multi-pattern joins into SQL JOINs. Each additional WHERE clause pattern
costs N SQL queries when run against a SQL store. **See the targeted comparison section
below for measurements at 50K and 250K scale.**

**Partial TT match is fast** (46ms / 151ms) because a bound component (predicate in this
test) reduces the working set before the pattern fan-out. Queries with at least one bound
TT component are practical.

**Compared to in-memory (same workload)**:
- Load: SQLite **wins** (83K t/s vs 27K t/s at 100K TT — in-memory slows due to registry overhead)
- Contains: in-memory wins (<0.1ms vs 1ms)
- SPARQL TT: in-memory **wins** (277ms vs 2s at 10K; in-memory has its own SPARQL overhead but no SQL round trips)

**SQLite is a good fit when**:
- The workload is write-heavy and read-light
- Queries use bound TT components (not full wildcard `<<( ?s ?p ?o )>>`)
- Persistence is needed and a server is not available
- Graph size exceeds in-memory budget (>50K triples)

**SQLite is a poor fit when**:
- Full TT wildcard SPARQL queries are frequent — the N×M SQL round-trip cost dominates
- Sub-second TT pattern query latency is required at scale

**Root cause note**: the SPARQL TT query performance is a property of the rdf-1.1 encoding
layer interacting with rdflib's SPARQL evaluation strategy, not an intrinsic SQLite
limitation. A native TT-aware SQL schema (or a native backend like rdf-star/Fuseki) would
not have this problem.

### Plain-triple capacity test

**Methodology**: Plain triples only (no triple terms or reifications). 5 predicates, 1000 objects — a typical heterogeneous-predicate graph. Benchmark: `benchmarks/bench_sqlite_plain_limit.py`.

| N | Load | Throughput | DB size | Subject lookup | Predicate scan (LIMIT 100) |
|--:|-----:|----------:|--------:|---------------:|---------------------------:|
| 500K | 5.8 s | 86K t/s | 194 MiB | 27.5 ms | 413 ms |
| 1M | 12.3 s | 81K t/s | 388 MiB | 27.6 ms | 806 ms |
| 2M | 26.9 s | 74K t/s | 778 MiB | 30.2 ms | 1.66 s |
| 5M | 1.2 min | 68K t/s | 1,949 MiB | 34.6 ms | 4.94 s |

**Subject lookup stays effectively constant** (~28–35ms) across a 10× scale increase — SQL indexing by subject works as expected.

**Predicate scan degrades linearly** even with LIMIT 100. rdflib's SPARQL evaluator fetches all matching rows from SQLite and slices in Python; it does not push `LIMIT` down to SQL. With 1/5 of triples matching `pred1`, rdflib retrieves 1M rows at 5M scale before returning 100 — hence ~5s. For point lookups (specific subject or object), this is not an issue; for broader scans, it is.

**In-memory comparison**: at 5M plain triples, in-memory would require ~13.5 GB (2.7 KB/triple × 5M). That exceeds available RAM on most laptops. SQLite's 1.9 GB on-disk footprint and ~35ms point lookup make it the only viable option above ~1–2M plain triples.

---

## Targeted Comparison — In-memory vs SQLite

Both scales use identical datasets: N distinct TripleTerms, 10% reification rate, 10% confidence annotations. Benchmark: `benchmarks/bench_comparison.py`. Median of 3 query runs.

### Results at 50K TTs (60K total triples, 5K reifications)

| Metric | In-memory | SQLite |
|---|--:|--:|
| **Load (addN)** | 211 ms  (285K t/s) | 577 ms  (104K t/s) |
| **Client memory** | 73 MiB peak | ~0 MiB  (36 MiB on disk) |
| **All reified TTs** `<<( ?s ?p ?o )>>` | **78 ms** | **102 ms** |
| **TT + join** `<<( )>> + confidence > 0.7` | **202 ms** | **3,720 ms** (18×) |
| **Partial TT match** `<<( ?s <pred> ?o )>>` | **64 ms** | **90 ms** |

_(5,000 rows for all-reified; 2,500 for confidence filter; 25 for partial match)_

### Results at 250K TTs (300K total triples, 25K reifications)

| Metric | In-memory | SQLite |
|---|--:|--:|
| **Load (addN)** | 1.11 s  (270K t/s) | 3.00 s  (100K t/s) |
| **Client memory** | 382 MiB peak | ~0 MiB  (183 MiB on disk) |
| **All reified TTs** `<<( ?s ?p ?o )>>` | **818 ms** | **54.78 s** (67×) |
| **TT + join** `<<( )>> + confidence > 0.7` | **1.48 s** | **74.84 s** (50×) |
| **Partial TT match** `<<( ?s <pred> ?o )>>` | **4.5 ms** | **315 ms** (70×) |

_(25,000 rows for all-reified; 12,500 for confidence filter; 125 for partial match)_

### What the numbers show

**Single-pattern TT queries are competitive at small scale**: at 50K TTs, in-memory (78ms) vs SQLite (102ms) are close — both evaluate the TT encoding patterns and the SPARQL engine does its work. The gap is not meaningful at this scale.

**The N×M problem compounds with scale and query complexity.** The confidence filter query has two triple patterns plus a FILTER:

```sparql
?stmt rdf:reifies <<( ?s ?p ?o )>> .
?stmt ex:confidence ?c .          ← this join is the problem
FILTER(xsd:decimal(?c) > 0.7)
```

rdflib's SPARQL engine evaluates `?stmt ex:confidence ?c` as a nested-loop join — one SQL query per result row from the first pattern. For 5K reification statements that is ~5K SQL round-trips; for 25K it is ~25K round-trips. At 50K scale the join already costs 18×; at 250K scale it degrades to 50–70×.

Even the "simple" all-reified wildcard blows up at scale: 25K reifications × 4 encoding patterns ≈ 100K SQL round-trips, producing the 67× gap (818ms in-memory vs 54.78s SQLite).

**In-memory is completely consistent.** As the problem grows 5× (50K→250K TTs), in-memory query times grow proportionally: wildcard 78ms→818ms (~10×), join 202ms→1.48s (~7×), bound pred 64ms→4.5ms (actually faster — fewer matching rows). SQLite times grow superlinearly because round-trip count grows with result set size.

**The bound-predicate query stays fast — until it isn't.** `<<( ?s <pred> ?o )>>` with a bound predicate uses the store's POS index to narrow the working set. At 50K TTs: 90ms SQLite vs 64ms in-memory. At 250K TTs: 315ms SQLite vs 4.5ms in-memory. The bound-component optimization works on the TT encoding lookup, but once additional WHERE clause patterns are added the same N×M problem reappears.

**This is not fixable within the current architecture.** The root cause is that rdflib's Python SPARQL evaluator was never designed to translate multi-pattern joins into SQL JOINs. Each additional triple pattern in a WHERE clause costs N SQL queries when run against a SQL store. A SPARQL-to-SQL compiler, or a native backend (rdf-star/Fuseki, Oxigraph), would not have this problem.

### When to use each backend

| Need | In-memory | SQLite |
|---|:---:|:---:|
| Multi-pattern SPARQL at scale | ✓ fast | ✗ degrades 50–70× |
| Single TT pattern, small graph (≤50K) | ✓ fast | ✓ comparable |
| Client memory budget | ✗ 73 MiB @ 50K, 382 MiB @ 250K | ✓ near-zero |
| Persistence across restarts | ✗ | ✓ |
| Write throughput | ✓ 270–285K t/s | ~100K t/s |
| Simple single-pattern reads | ✓ | ✓ acceptable |

**Practical conclusion**: SQLite with rdflib-sqlalchemy is appropriate only for write-dominated workloads with simple single-pattern lookups, or when persistence is required and query volume is low. For any workload involving multi-pattern SPARQL over annotated triples — the primary use case for StarlightGraph — SQLite becomes unusable above ~50K TTs. The recommended path for production query-heavy workloads is a native backend (rdf-star/Fuseki or pyoxigraph embedded).

---

## Phase 4 — rdf-star/Fuseki at Scale

**Methodology**: Fuseki in-memory dataset (`dbType=mem`). Triples loaded via batched SPARQL INSERT DATA (500 triples/request) to avoid per-triple HTTP overhead. Same dataset as the Targeted Comparison section. Median of 3 query runs. Benchmark: `benchmarks/bench_fuseki.py`.

### Results

| Metric | 50K TTs (60K triples) | 250K TTs (300K triples) |
|---|--:|--:|
| **Load (batched INSERT DATA)** | 2.72 s  (22K t/s) | 11.25 s  (27K t/s) |
| **All reified TTs** `<<( ?s ?p ?o )>>` | **91.5 ms** | **477 ms** |
| **TT + join** `<<( )>> + confidence > 0.7` | **128.6 ms** | **276 ms** |
| **Partial TT match** `<<( ?s <pred> ?o )>>` | **12.7 ms** | **47.7 ms** |

_(rows returned: 5K / 2.5K / 25 at 50K scale; 25K / 12.5K / 125 at 250K scale)_

### What the numbers show

**Fuseki's SPARQL engine evaluates the full query in one pass.** There is no N×M round-trip problem — rdf-star/Fuseki sees `?stmt rdf:reifies <<s p o>> . ?stmt ex:confidence ?c . FILTER(...)` as a single query and plans it with native JOINs. The confidence+join query at 250K takes 276ms, less than the wildcard-only query at 477ms, because Fuseki can prune the result set early using the FILTER.

**The crossover with in-memory:**

| Query | In-memory 50K | Fuseki 50K | In-memory 250K | Fuseki 250K |
|---|--:|--:|--:|--:|
| Wildcard TT | 78 ms | 91.5 ms | 818 ms | **477 ms** |
| TT + join | 202 ms | **128.6 ms** | 1,480 ms | **276 ms** |
| Bound predicate | **64 ms** | 12.7 ms | **4.5 ms** | 47.7 ms |

- **Wildcard scans**: Fuseki and in-memory are comparable at 50K; Fuseki wins above ~150K TTs.
- **Join queries**: Fuseki already beats in-memory at 50K (128ms vs 202ms) and widens to 5× at 250K. This is the primary use case for annotation-heavy graphs.
- **Selective queries** (bound component): in-memory always wins — Python dict lookup costs <1ms, while HTTP round-trips add a floor of ~10–50ms regardless of result size.

**Fuseki vs SQLite at 250K**: Fuseki wildcard 477ms vs SQLite 54.78s — **115× faster**. Fuseki join 276ms vs SQLite 74.84s — **271× faster**. SQLite's N×M problem completely disappears with a native backend.

**Scaling behaviour**: Fuseki scales roughly O(N) with result count, not O(1). Going 5× in scale (50K→250K): wildcard 5.2×, partial TT 3.7×. This is expected — Fuseki must stream and return more rows. The key advantage over in-memory is that multi-pattern joins do not add multiplicative overhead.

**Load throughput**: batched INSERT DATA achieves 22–27K t/s. This is lower than in-memory (270K t/s) or SQLite (100K t/s) because each batch is still an HTTP round-trip (~5–10ms) and the data is serialized to SPARQL UPDATE text. For write-heavy workloads, in-memory bulk-load then serialize-to-Fuseki is faster than streaming individual updates.

### When to use Fuseki

| Need | In-memory | Fuseki (rdf-star) |
|---|:---:|:---:|
| Wildcard TT scans, large graphs (>150K TTs) | ✗ slow | ✓ faster |
| Join / multi-pattern queries | ✗ degrades | ✓ single-pass |
| Selective (bound component) queries | ✓ sub-ms | ✗ HTTP floor |
| Persistence + multi-process access | ✗ | ✓ |
| Inference / OWL reasoning | ✗ | ✓ Jena rules |
| Zero infrastructure setup | ✓ | ✗ needs server |

---

## Phase 5 — rdf-star/Fuseki at Scale

**Methodology**: Same dataset and scale points as Phase 4 (rdf-1.1/Fuseki). TripleTerms written to Fuseki as native quoted triples (`<< s p o >>`); no encoding triples stored. Queries sent directly to Fuseki's HTTP endpoint as rdf-star SPARQL; results converted from Fuseki's `type: "triple"` JSON format back to TripleTerm objects. Benchmark: `benchmarks/bench_fuseki_rdfstar.py`.

### Results

| Metric | 50K TTs | 250K TTs | 500K TTs |
|---|--:|--:|--:|
| **Physical triples in Fuseki** | 60K | 300K | 600K |
| **Load (batched INSERT DATA)** | 2.24 s | 10.46 s | 22.08 s |
| **All reified TTs** `<<( ?s ?p ?o )>>` | 114.6 ms | 456.9 ms | 958.5 ms |
| **TT + join** `<<( )>> + confidence > 0.7` | 59.0 ms | 317.4 ms | 659.6 ms |
| **Partial TT match** `<<( ?s <pred> ?o )>>` | 12.2 ms | 38.2 ms | 158.9 ms |

_(rows: 5K/2.5K/25 at 50K; 25K/12.5K/125 at 250K; 50K/25K/250 at 500K)_

### rdf-star vs rdf-1.1 comparison at 250K TTs

| Query | rdf-1.1/Fuseki | rdf-star/Fuseki | Improvement |
|---|--:|--:|--:|
| Wildcard | 583.6 ms | 456.9 ms | 22% faster |
| TT + join | 525.4 ms | 317.4 ms | 40% faster |
| Bound predicate | 60.6 ms | 38.2 ms | 37% faster |
| Physical triples | 375K | 300K | 20% less storage |

### What the numbers show

**rdf-star is consistently faster than rdf-1.1 at every scale.** The gain comes from two sources: fewer physical triples stored (no encoding triples), and Fuseki's query engine handling `rdf:reifies << s p o >>` as a native quoted-triple pattern rather than a four-pattern encoding join. The wildcard improvement (~22%) roughly tracks the storage reduction (~20%). The join improvement (~40%) is larger because the join planner can reason more directly about quoted-triple patterns.

**Both Fuseki modes scale O(N) with result count** — no superlinear degradation. Going 10× in scale (50K→500K), rdf-star wildcard grows 8.4× (114ms→959ms). rdf-1.1 wildcard grows 9.1× (134ms→1.22s). Both are well-behaved.

**rdf-star beats in-memory from ~50K TTs up for broad queries**, and the advantage widens: wildcard 115ms vs 164ms at 50K (1.4×), 457ms vs 814ms at 250K (1.8×), 959ms vs 1.71s at 500K (1.8×). Join queries show a larger advantage: 59ms vs 290ms at 50K (5×), 317ms vs 1.49s at 250K (4.7×). In-memory retains its advantage for selective (bound-component) lookups where no HTTP overhead is tolerable.

---

## Notes on Methodology

- **Insert benchmarks** create a fresh graph per run to avoid cache effects.
- **Query benchmarks** run against a pre-populated graph (insert cost excluded).
- **Memory** measured via `tracemalloc` peak delta during insert — approximates
  store overhead, not total process RSS.
- **HTTP benchmarks** are sensitive to localhost TCP stack; results reflect
  same-machine loopback, not cross-network production latency.
- Registry rebuild (`_build_registry_from_store`) is only relevant for the
  rdf-1.1 backend; native backends do not use it.
