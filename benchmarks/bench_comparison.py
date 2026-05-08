"""
benchmarks/bench_comparison.py

Head-to-head: in-memory vs SQLite at 50K TTs with 10% reification rate.

Both backends use an identical dataset so results are directly comparable:
  - 50K distinct TripleTerms, each also stored as a plain assertion triple
  - 5K reification statements  (10% of TTs)
  - 5K ex:confidence annotations on those statements

Queries tested:
  1. All reified TTs — single TT pattern, no join     : <<( ?s ?p ?o )>>
  2. Reified TTs with confidence > 0.7 — TT + join    : <<( )>> + confidence join
  3. Partial TT match — TT with bound predicate        : <<( ?s <pred> ?o )>>

Run:
    .venv/bin/python benchmarks/bench_comparison.py
"""

import gc
import os
import statistics
import sys
import tempfile
import time
import tracemalloc

from rdflib import plugin, URIRef, Literal
from rdflib.namespace import XSD
from rdflib.store import Store
from rdflib_sqlalchemy import registerplugins

sys.path.insert(0, '.')
from starlight.graph import StarlightGraph
from starlight.model.triple import TripleTerm

registerplugins()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EX          = 'http://example.org/'
RDF_REIFIES = URIRef('http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies')
EX_CONF     = URIRef(EX + 'confidence')
GRAPH_URI   = URIRef(EX + 'bench')

N_TT        = 50_000
N_REIF      = N_TT // 10   # 5,000
REPEATS     = 3
PRED_BOUND  = URIRef(f'{EX}n50000')  # predicate shared by i=0,200,400,... → ~250 TTs in reif set

# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------

def _uri(n):
    return URIRef(f'{EX}n{n}')


def build_dataset():
    """Returns list of (s, p, o) triples for both backends.

    Each triple where o is a TripleTerm is encoded by StarlightGraph on insert;
    plain assertion triples use raw URIRefs so no encoding occurs.
    """
    triples = []
    for i in range(N_TT):
        tt = TripleTerm(_uri(i), _uri(i % 200 + 50_000), _uri(i % 100 + 60_000))
        triples.append((_uri(i), _uri(i % 200 + 50_000), _uri(i % 100 + 60_000)))
        if i < N_REIF:
            stmt = _uri(f'stmt{i}')
            conf = round(0.5 + (i % 10) / 20, 2)
            triples.append((stmt, RDF_REIFIES, tt))
            triples.append((stmt, EX_CONF, Literal(str(conf), datatype=XSD.decimal)))
    return triples

# ---------------------------------------------------------------------------
# Timing helpers
# ---------------------------------------------------------------------------

def timeit(fn, repeats=REPEATS):
    times = []
    for _ in range(repeats):
        gc.collect()
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    return statistics.median(times)


def measure_peak_mib(fn):
    gc.collect()
    tracemalloc.start()
    fn()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return peak / 1024 / 1024

# ---------------------------------------------------------------------------
# Queries (identical for both backends)
# ---------------------------------------------------------------------------

Q_ALL_REIFIED = f"""
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
SELECT ?stmt ?s ?p ?o WHERE {{
    ?stmt rdf:reifies <<( ?s ?p ?o )>> .
}}
"""

Q_FILTER_CONFIDENCE = f"""
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX ex:  <{EX}>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT ?stmt ?s ?p ?o WHERE {{
    ?stmt rdf:reifies <<( ?s ?p ?o )>> .
    ?stmt ex:confidence ?c .
    FILTER(xsd:decimal(?c) > 0.7)
}}
"""

Q_PARTIAL_TT = f"""
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
SELECT ?stmt ?s ?o WHERE {{
    ?stmt rdf:reifies <<( ?s <{PRED_BOUND}> ?o )>> .
}}
"""

# ---------------------------------------------------------------------------
# In-memory backend
# ---------------------------------------------------------------------------

def run_inmemory(triples):
    print('\n--- In-memory backend ---')

    # Load
    def do_load():
        g = StarlightGraph()
        g.addN((s, p, o, g) for s, p, o in triples)
        return g

    load_t = timeit(do_load)
    g = do_load()
    mem_mib = measure_peak_mib(do_load)

    print(f'  Load time  : {fmt_ms(load_t)}  ({fmt_tps(len(triples), load_t)})')
    print(f'  Client mem : {mem_mib:.0f} MiB peak (tracemalloc)')
    print(f'  Triples    : {len(g):,} visible')

    print(f'\n  Queries (median of {REPEATS} runs):')
    _run_queries(g)
    return g


# ---------------------------------------------------------------------------
# SQLite backend
# ---------------------------------------------------------------------------

def run_sqlite(triples):
    print('\n--- SQLite backend ---')

    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(db_fd)

    try:
        def do_load():
            store = plugin.get('SQLAlchemy', Store)(identifier=GRAPH_URI)
            store.open(f'sqlite:///{db_path}', create=True)
            g = StarlightGraph(store=store, identifier=GRAPH_URI)
            g.addN((s, p, o, g) for s, p, o in triples)
            from sqlalchemy import text
            with store.engine.begin() as conn:
                conn.execute(text('ANALYZE'))
            g._build_registry_from_store()
            return g

        load_t = timeit(do_load)
        g = do_load()
        db_mib = os.path.getsize(db_path) / 1024 / 1024

        print(f'  Load time  : {fmt_ms(load_t)}  ({fmt_tps(len(triples), load_t)})')
        print(f'  DB size    : {db_mib:.1f} MiB  (client holds no triple data)')
        print(f'  Triples    : {len(g):,} visible')

        print(f'\n  Queries (median of {REPEATS} runs):')
        _run_queries(g)
        g.store.close()
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# Shared query runner
# ---------------------------------------------------------------------------

def _run_queries(g):
    rows = [
        ('All reified TTs  (single TT pattern)',        Q_ALL_REIFIED),
        ('Reified + confidence>0.7  (TT + join)',        Q_FILTER_CONFIDENCE),
        ('Partial TT match  (bound predicate)',          Q_PARTIAL_TT),
    ]
    col = max(len(r[0]) for r in rows)
    for label, q in rows:
        t = timeit(lambda q=q: list(g.query(q)))
        result_count = len(list(g.query(q)))
        print(f'    {label:<{col}}  {fmt_ms(t):>10}  ({result_count} rows)')


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def fmt_ms(s):
    ms = s * 1000
    if ms >= 1000:
        return f'{ms/1000:.2f} s'
    return f'{ms:.1f} ms'


def fmt_tps(n, s):
    return f'{n / s:,.0f} t/s'


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    print('StarlightGraph — in-memory vs SQLite head-to-head comparison')
    print(f'Python {sys.version.split()[0]}')
    print(f'\nDataset: {N_TT:,} TTs  |  {N_REIF:,} reifications (10%)  |  {N_REIF:,} confidence annotations')
    print(f'Input triples: {N_TT + N_REIF * 2:,}')

    triples = build_dataset()

    run_inmemory(triples)
    run_sqlite(triples)

    print('\nDone.')
