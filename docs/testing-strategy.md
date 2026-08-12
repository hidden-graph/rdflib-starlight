# Testing Strategy

*Last reviewed: 2026-08-11*

Five tiers, each answering a different question. Run the first two on every
change; the rest when you're touching something they specifically cover.

## 1. Unit + W3C conformance — correctness, in-memory

**Question:** does the code do what it's supposed to?

```bash
pytest tests/ -m "not integration and not algebra_ir" -v
```

Runs on every push/PR (`.github/workflows/test.yml`, Python 3.10–3.13). Covers:

- `tests/unit/` — component-level tests against the default in-memory backend.
- `tests/w3c_sparql12/` — the W3C SPARQL 1.2 conformance suite, evaluated against the in-memory backend and (parametrized, self-skipping) live Oxigraph/Fuseki when reachable.

No server required; this is the tier every contribution must pass.

## 2. Integration — real backends, real stores

**Question:** does behavior actually hold once a real store is in the loop, not just rdflib's own in-memory graph?

```bash
pytest tests/ -m "integration and not algebra_ir" -v
```

Covers three backend families, each in its own file under `tests/integration/`:

| File | Backend | Needs |
|---|---|---|
| `test_fuseki_backend.py` | Apache Jena Fuseki, `rdf-1.1` and `rdf-1.2` modes | `docker run ... atomgraph/fuseki` — see the file's own docstring |
| `test_oxigraph_backend.py` | Oxigraph, native `rdf-1.2` | `docker run ... ghcr.io/oxigraph/oxigraph` — see the file's own docstring |
| `test_sqlalchemy_backend.py` | SQLite via `rdflib-sqlalchemy`, `rdf-1.1` | the `sqlalchemy` extra (`pip install -e ".[sqlalchemy]"`) — no server |

Every test class self-skips (`skipif`) when its backend isn't reachable, so this is safe to run with only some backends up — each file's docstring has the exact command for the one it needs.

**In CI**: Oxigraph runs as a GitHub Actions service container (its default image already serves on `:7878`, no config needed) alongside the SQLite tests, which need no server at all. **Fuseki does not run in CI** — its image needs dataset-creation arguments at startup that a service container can't supply — so Fuseki coverage is manual-only for now; this was a deliberate scope call, not an oversight, and may change later.

## 3. Cross-backend parity — same query, same answer, everywhere

**Question:** does the same operation produce the same observable result regardless of which backend is running it? This is the project's core value proposition.

```bash
pytest tests/integration/test_cross_backend_parity.py -v
```

Technically part of tier 2 (same marker, same CI wiring) but called out separately because it's checking something the other integration tests don't: not "does backend X work," but "does backend X agree with backend Y and with in-memory." Each backend's scenarios skip independently if that backend isn't reachable.

## 4. Benchmarks — where to expect degradation

**Question:** not "is it correct" but "how does it degrade as data grows, and which backend should I pick for this workload." These are timing scripts, not pass/fail tests — no `pytest` marker, run directly:

```bash
python benchmarks/bench_inmemory.py   # no server needed
python benchmarks/bench_http.py       # Fuseki and/or Oxigraph — skips whichever isn't reachable
python benchmarks/bench_scaling.py    # same
```

See `benchmarks/README.md` for setup and what each script measures. Run these manually before a release, or after any change likely to affect performance (encoding scheme, query rewriting, backend dispatch) — not on every commit; results are noisy on shared CI runners and there's no fixed pass/fail threshold to gate on.

**Known degradation points**, from the last full run (`docs/performance.md`, re-measured 2026-07-17 — re-run `bench_scaling.py` before trusting these numbers on a materially different codebase or dataset shape):

- **In-memory**: fine up to ~100K annotated facts; memory pressure sets in around there, hard ceiling near 1.5M. Full-annotation scans (not single lookups, which stay near-instant) slow from ~150ms at 50K to ~1.7s at 500K.
- **SQLite**: single-subject/object lookups stay fast (<35ms) even at millions of plain triples, but a full annotation scan is **67× slower than in-memory** at 250K annotated facts (54s vs <1s) — not a suitable backend for workloads that regularly query large numbers of annotated facts.
- **Fuseki (`rdf-1.1`)**: eliminates SQLite's scan problem and beats in-memory on broad scans past ~250K facts, at the cost of running a server.
- **Fuseki (`rdf-1.2`)**: same server cost, but native triple-term storage cuts stored triples ~20% and query time 35–48% versus `rdf-1.1` encoding.
- **Oxigraph (`rdf-1.2`)**: fastest backend for broad scans/joins at every scale tested (194ms full-scan at 250K, 4.7× faster than in-memory); the one place it loses is single-subject/object lookup, where in-memory's plain dict lookup (~2ms) beats Oxigraph's HTTP round-trip (13–36ms).

For the full write-up and backend recommendations, see `docs/performance.md`.

## 5. `algebra_ir` pipeline — the opt-in sparql1_2_to_rdf-based SPARQL engine

**Question:** does `StarlightGraph(sparql_pipeline='algebra_ir')` — the new, grammar/algebra-IR-based SPARQL 1.2 engine (see the cross-repo migration plan) that's meant to eventually replace `starlight/query/sparql12_to_11.py`'s hand-rolled text rewriter — work correctly?

```bash
pytest tests/ -m "algebra_ir" -v
```

Covers `tests/unit/test_algebra_ir_pipeline.py` (in-memory `StarlightGraph`, hand-built cases), `tests/unit/test_algebra_ir_dataset_update.py` (in-memory `StarlightDataset`, mirrors `test_dataset_query.py`'s own SELECT/ASK/CONSTRUCT/UPDATE scenarios — the harder multi-graph/quad case, including UPDATE parity), `tests/integration/test_fuseki_backend.py::TestFusekiAlgebraIrPipeline` (live Fuseki, needs the server per tier 2), and `tests/w3c_sparql12/test_w3c_sparql12_algebra_ir.py` — the real parity check: runs **all 40** W3C SPARQL 1.2 SELECT/CONSTRUCT fixtures (including the 4 that need a real multi-graph `StarlightDataset`, now that it has `sparql_pipeline` support) through `algebra_ir` and compares against the *same official* `.srj`/`.ttl` ground truth `test_w3c_sparql12_eval.py`'s own legacy-pipeline tests already check against — both suites independently agreeing with the same external oracle stands in for comparing them to each other directly (see that file's own docstring for why). **Must be run as its own, separate `pytest` invocation, not combined with tiers 1/2's `-m` expressions** (both already exclude it via `and not algebra_ir`) — this is not a style preference, it's a real, confirmed workaround:

**Known issue**: running `algebra_ir`-marked tests together with the legacy-pipeline tests in the *same* pytest process can corrupt `sparql1_2_to_rdf`'s grammar installation (`sparql1_2_to_rdf/grammar12.py`) — `TRIPLE()`-family syntax stops parsing partway through the run, with no code change and no data involved. Root-caused as far as: it's a real interaction with pytest's assertion-rewriting import hook (`--assert=plain` avoids it entirely) colliding with pyparsing's own grammar-streamlining optimization (`PrimaryExpression`'s `.exprs` list gets reset to a pristine, un-extended state — same Python object, confirmed via `id()`, not a duplicate import). Two real mitigations are already in place in `sparql1_2_to_rdf` itself (a state-based idempotency check replacing the old call-once boolean flag, and a retry-with-forced-reinstall on parse failure — both in `grammar12.py`/`parse12.py`) but neither fully closes this specific case. **Not a bug in the pipeline's own logic** — every test in both suites passes cleanly, every time, when either runs alone (confirmed repeatedly); this is purely a test-process-isolation artifact. CI runs it as its own step for exactly this reason.

For everything else about the `algebra_ir` pipeline itself (design, phased rollout, what's done vs. not), see the migration plan and `sparql1_2_to_rdf`'s own `CLAUDE.md`.
