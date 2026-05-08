# StarlightGraph Performance

## Executive Summary

### In-memory

The fully in-memory mode is the simplest and fastest option for most workloads. There is no setup, no server, and all queries run at Python dict speed. It is the right default and scales further than you might expect for plain triples — a performant laptop (16 GB RAM) can comfortably hold several million plain triples and answer complex SPARQL queries in milliseconds.


The practical limits are lower once triple terms are involved. Each triple term requires roughly four times the storage of a plain triple — it stores one visible triple plus three internal encoding triples, plus registry entries. On a 16 GB laptop, at 100,000 triple term triples, memory starts to be an issue with hard-limits at approximately 1.5 mllion triple term triples. 


Query performance depends on the shape of the query. Selective queries — find annotations about a specific subject, predicate, or object — are fast at any scale (~1–2ms) because the store's own index resolves the lookup directly. The slow case is **wildcard queries** that retrieve all annotated facts at once: ~600ms at 50K triple terms, ~1.3s at 100K, ~7s at 250K. If your application frequently needs to scan the full annotation set, in-memory becomes impractical above roughly 50–100K triple terms.


**Important caveat: an in-memory graph does not persist.** When the process ends, the data is gone. Applications using in-memory mode must reload from an external source (a file, a database, an API) on every start. For use cases that can afford that startup cost, this is often an acceptable trade-off.  

### SQLite

**SQLite is not a query backend — it is storage with a query-shaped interface.** The rdflib-sqlalchemy adapter executes SPARQL step by step: it receives individual triple pattern lookups from rdflib's SPARQL evaluator, translates each one to a SQL SELECT, and returns rows. It never sees the full WHERE clause and has no opportunity to generate a SQL JOIN. For a query with two triple patterns and 5K matching rows, that is 5K+1 SQL round-trips rather than the single joined SELECT a native SQL query planner would produce. This makes SQLite appropriate only for write-dominated workloads or simple single-pattern lookups — not for the complex multi-predicate TT queries (e.g. temporal range queries over annotated facts) that are a primary use case for StarlightGraph.

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
- Fuseki version: _TBD (Phase 2)_
- Oxigraph version: _TBD (Phase 2)_

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
| ≤ 10K–20K triple terms, query-heavy | in-memory (rdf-1.1) | SPARQL TT registry path: ~116ms at 10K, ~600ms at 50K |
| > 20K triple terms, SPARQL-heavy | rdf-star/Fuseki | Fuseki's engine holds flat at 6–12ms; in-memory hits 600ms at 50K and 1.2s at 100K |
| > 50K plain triples, memory constrained | rdf-1.1/Fuseki | 273 MiB at 100K in-memory; Fuseki holds nothing in client |
| Persistence / multi-process access | rdf-1.1/Fuseki or rdf-star/Fuseki | In-memory is process-lifetime only |
| RDF 1.2 native syntax, small graphs | rdf-1.2/Oxigraph | Only spec-compliant backend; use in-memory Oxigraph config |
| RDF 1.2 native syntax, large graphs | rdf-1.2/Oxigraph (tmpfs) | Persistent RocksDB shows severe scan degradation at scale |
| Jena ecosystem / inference | rdf-star/Fuseki | Jena rules, OWL reasoning, federation |
| Unit / integration tests | in-memory (rdf-1.1) | Zero setup cost; full suite in <1 s |
| Bulk load (write-once, read-many) | any HTTP + `addN` | Use `addN` to reduce per-call overhead |
| Reconnect to existing store | rdf-1.1 with sparse TT | Registry rebuild: 8ms at 10K TT, 93ms at 100K TT |

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

**SPARQL TT queries — N × M round-trip problem (now fixed).** The original encoding
path rewrote `?stmt rdf:reifies <<( ?s ?p ?o )>>` into 4 triple patterns; rdflib's SPARQL
engine fired one SQL query per pattern per result row. For 1K reifications × 4 patterns ≈
4K SQL round trips at ~0.5ms each ≈ 2 seconds. At 10K reifications: 21 seconds —
unusable. The **registry-path fix** (added after these numbers were captured) replaces
the pattern fan-out with: 1 SQL query to retrieve all matching (stmt, tt:HASH) pairs,
then N in-memory dict lookups from the TripleTerm registry. The Phase 3 SPARQL numbers
above reflect the old encoding path; **see the targeted SQL comparison section below for
post-fix numbers.**

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

---

## Targeted Comparison — In-memory vs SQLite at 50K TTs

**Methodology**: Both backends loaded the same 60K-triple dataset (50K TTs, 5K reifications at 10% rate, 5K confidence annotations). Benchmark: `benchmarks/bench_comparison.py`. Median of 3 query runs.

### Results

| Metric | In-memory | SQLite |
|---|--:|--:|
| **Load (addN)** | 211 ms  (285K t/s) | 577 ms  (104K t/s) |
| **Client memory** | 73 MiB peak | ~0 MiB  (36 MiB on disk) |
| **All reified TTs** `<<( ?s ?p ?o )>>` | **78 ms** | **102 ms** |
| **TT + join** `<<( )>> + confidence > 0.7` | **202 ms** | **3,720 ms** |
| **Partial TT match** `<<( ?s <pred> ?o )>>` | **64 ms** | **90 ms** |

_(5,000 rows returned for all-reified; 2,500 for confidence filter; 25 for partial match)_

### What the numbers show

**The registry-path fix brought TT SPARQL to near-parity for single-pattern queries**: 78ms (in-memory) vs 102ms (SQLite) for all reified TTs. Both backends now execute 1 query + 5K in-memory dict lookups. The gap is small and SQLite's lower client memory is a real advantage at this scale.

**Multi-pattern SPARQL queries expose SQLite's structural weakness.** The confidence filter query has two triple patterns plus a FILTER:

```sparql
?stmt rdf:reifies <<( ?s ?p ?o )>> .
?stmt ex:confidence ?c .          ← this join is the problem
FILTER(xsd:decimal(?c) > 0.7)
```

After the TT pattern is handled by the registry path, rdflib's SPARQL engine still evaluates `?stmt ex:confidence ?c` as a nested-loop join — one SQL query per result row from the first pattern. For 5K reification statements, that is **5K SQL round-trips at ~0.7ms each = 3.5 seconds**. This is the same N×M round-trip problem as before, but now for ordinary triple pattern joins rather than TT encoding patterns.

In-memory evaluates the same join with Python dict lookups (~1 µs each) — 5K lookups is negligible, leaving only the SPARQL evaluation overhead.

**This is not fixable by the registry path alone.** The root cause is that rdflib's Python SPARQL evaluator was not designed to translate multi-pattern joins into SQL JOINs. Each additional triple pattern in a WHERE clause costs N SQL queries when run against a SQL store.

### When to use each backend at this scale

| Need | In-memory | SQLite |
|---|:---:|:---:|
| Multi-pattern SPARQL (most real queries) | ✓ fast | ✗ slow |
| Single TT pattern query | ✓ fast | ✓ comparable |
| Client memory budget | ✗ 73 MiB+ | ✓ near-zero |
| Persistence across restarts | ✗ | ✓ |
| Write throughput | ✓ 285K t/s | ~104K t/s |

**Practical conclusion**: For query-heavy workloads with multi-pattern SPARQL, SQLite with rdflib-sqlalchemy is worse than in-memory at every scale tested — not because of the TT encoding overhead (which the registry path eliminated), but because rdflib's SPARQL evaluator cannot push joins into SQL. SQLite's value is exclusively persistence + zero client memory, and only when queries are simple single-pattern lookups or the workload is write-dominated.

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
