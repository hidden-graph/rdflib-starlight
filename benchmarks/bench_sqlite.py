"""
benchmarks/bench_sqlite.py

SQLite backend performance benchmark for StarlightGraph.

Dataset shape:
  - N distinct TripleTerms, each a unique fact
  - 10% of TTs have an explicit reification statement + confidence annotation
    (e.g. 10K TTs → 1K reifications, 100K TTs → 10K reifications)

Phases:
  1. Bulk load all triples via addN
  2. Run ANALYZE so SQLite's query planner has accurate statistics
  3. Measure query performance on the stable, indexed store

Run:
    .venv/bin/python benchmarks/bench_sqlite.py
"""

import gc
import os
import statistics
import sys
import tempfile
import time

from rdflib import plugin, URIRef, Literal
from rdflib.namespace import XSD
from rdflib.store import Store
from rdflib_sqlalchemy import registerplugins

sys.path.insert(0, '.')
from starlight.graph import StarlightGraph
from starlight.model.triple import TripleTerm

registerplugins()

EX          = 'http://example.org/'
RDF_REIFIES = URIRef('http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies')
EX_CONF     = URIRef(EX + 'confidence')
GRAPH_URI   = URIRef(EX + 'bench')

SCALES  = [10_000, 100_000]
REPEATS = 3


# ---------------------------------------------------------------------------
# Data generation
# ---------------------------------------------------------------------------

def _uri(n):
    return URIRef(f'{EX}n{n}')


def build_dataset(n_tt):
    """Return (all_triples, reif_stmts) for n_tt triple terms, 10% reified."""
    n_reif = n_tt // 10
    triples = []

    for i in range(n_tt):
        tt = TripleTerm(_uri(i), _uri(i % 200 + 50_000), _uri(i % 100 + 60_000))
        # every TT also appears as a plain asserted fact
        triples.append((_uri(i), _uri(i % 200 + 50_000), _uri(i % 100 + 60_000)))

        if i < n_reif:
            stmt = _uri(f'stmt{i}')
            confidence = round(0.5 + (i % 10) / 20, 2)   # 0.50 – 0.95
            triples.append((stmt, RDF_REIFIES, tt))
            triples.append((stmt, EX_CONF, Literal(str(confidence), datatype=XSD.decimal)))

    return triples, n_reif


# ---------------------------------------------------------------------------
# Store helpers
# ---------------------------------------------------------------------------

def _make_store(db_path):
    store = plugin.get('SQLAlchemy', Store)(identifier=GRAPH_URI)
    store.open(f'sqlite:///{db_path}', create=True)
    return store


def _analyze(store):
    """Run ANALYZE so SQLite query planner has accurate statistics."""
    from sqlalchemy import text
    with store.engine.begin() as conn:
        conn.execute(text('ANALYZE'))


# ---------------------------------------------------------------------------
# Timing helper
# ---------------------------------------------------------------------------

def timeit(fn, repeats=REPEATS):
    times = []
    for _ in range(repeats):
        gc.collect()
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    return statistics.median(times)


# ---------------------------------------------------------------------------
# Benchmarks
# ---------------------------------------------------------------------------

def bench_bulk_load(triples, db_path):
    """Bulk-load all triples via addN. Returns (seconds, graph)."""
    store = _make_store(db_path)
    g = StarlightGraph(store=store, identifier=GRAPH_URI)

    t0 = time.perf_counter()
    g.addN((s, p, o, g) for s, p, o in triples)
    elapsed = time.perf_counter() - t0

    _analyze(store)
    g._build_registry_from_store()
    return elapsed, g


def bench_contains(g, triples):
    """Point lookup for a known triple."""
    probe = triples[len(triples) // 2]

    def run():
        _ = probe in g

    return timeit(run, repeats=10)


def bench_full_scan(g):
    """Exhaust triples((None, None, None))."""
    def run():
        _ = list(g.triples((None, None, None)))
    return timeit(run)


def bench_sparql_all_reified(g):
    """Find all reification statements — no filter."""
    q = f"""
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    SELECT ?stmt ?s ?p ?o WHERE {{
        ?stmt rdf:reifies <<( ?s ?p ?o )>> .
    }}
    """
    def run():
        _ = list(g.query(q))
    return timeit(run)


def bench_sparql_filter_confidence(g):
    """Reified TTs with confidence > 0.7."""
    q = f"""
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    PREFIX ex:  <{EX}>
    PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
    SELECT ?stmt ?s ?p ?o WHERE {{
        ?stmt rdf:reifies <<( ?s ?p ?o )>> .
        ?stmt ex:confidence ?c .
        FILTER(xsd:decimal(?c) > 0.7)
    }}
    """
    def run():
        _ = list(g.query(q))
    return timeit(run)


def bench_sparql_partial_tt(g):
    """Find reified TTs with a specific predicate."""
    # predicate URI index 0 maps to _uri(0 % 200 + 50_000) = _uri(50000)
    pred = _uri(50_000)
    q = f"""
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    SELECT ?stmt ?s ?o WHERE {{
        ?stmt rdf:reifies <<( ?s <{pred}> ?o )>> .
    }}
    """
    def run():
        _ = list(g.query(q))
    return timeit(run)


def bench_registry_rebuild(g):
    """Cost of reconnect — full registry rebuild from store."""
    def run():
        g._build_registry_from_store()
    return timeit(run)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def fmt_ms(s):
    ms = s * 1000
    if ms >= 1000:
        return f'{ms/1000:.2f} s'
    return f'{ms:.1f} ms'

def fmt_tps(n, s):
    return f'{n / s:,.0f} t/s'


def run(n_tt):
    print(f'\n{"=" * 65}')
    print(f'  N = {n_tt:,} TTs  |  {n_tt // 10:,} reifications  |  {n_tt // 10:,} confidence annotations')
    print(f'{"=" * 65}')

    triples, n_reif = build_dataset(n_tt)
    n_total = len(triples)
    print(f'  Total physical triples to load: {n_total:,}')

    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name

    try:
        print(f'\n  [1] Bulk load + ANALYZE + registry rebuild...')
        load_t, g = bench_bulk_load(triples, db_path)
        db_size = os.path.getsize(db_path) / 1024 / 1024
        print(f'      Load time : {fmt_ms(load_t)}  ({fmt_tps(n_total, load_t)})')
        print(f'      DB size   : {db_size:.1f} MiB')
        print(f'      Graph len : {len(g):,}  (visible triples)')

        print(f'\n  [2] Query benchmarks (median of {REPEATS} runs)')

        contains_t  = bench_contains(g, triples)
        full_t      = bench_full_scan(g)
        all_reif_t  = bench_sparql_all_reified(g)
        filter_t    = bench_sparql_filter_confidence(g)
        partial_t   = bench_sparql_partial_tt(g)
        rebuild_t   = bench_registry_rebuild(g)

        rows = [
            ('Point lookup (contains)',       contains_t),
            ('Full scan triples()',           full_t),
            ('SPARQL: all reified TTs',       all_reif_t),
            ('SPARQL: filter confidence>0.7', filter_t),
            ('SPARQL: partial TT match',      partial_t),
            ('Registry rebuild',              rebuild_t),
        ]

        col = max(len(r[0]) for r in rows)
        for label, t in rows:
            print(f'      {label:<{col}}  {fmt_ms(t):>10}')

        g.store.close()
    finally:
        os.unlink(db_path)


if __name__ == '__main__':
    print('StarlightGraph — SQLite backend performance benchmark')
    print(f'Python {sys.version.split()[0]}')

    for n in SCALES:
        run(n)

    print('\nDone.')
