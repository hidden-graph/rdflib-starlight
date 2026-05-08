"""
benchmarks/bench_sqlite_plain_limit.py

Upper-limit test: plain triples only, SQLite backend.
Tests 500K, 1M, 2M, 5M plain triples with a simple SPARQL SELECT.
Goal: find where SQLite load time or query time becomes impractical.

Run:
    .venv/bin/python benchmarks/bench_sqlite_plain_limit.py
"""

import gc
import os
import statistics
import sys
import tempfile
import time

from rdflib import plugin, URIRef
from rdflib.store import Store
from rdflib_sqlalchemy import registerplugins

sys.path.insert(0, '.')
from starlight.graph import StarlightGraph

registerplugins()

EX        = 'http://example.org/'
GRAPH_URI = URIRef(EX + 'bench')
REPEATS   = 3
SCALES    = [500_000, 1_000_000, 2_000_000, 5_000_000]

SPARQL_SUBJECT = f"""
SELECT ?p ?o WHERE {{
    <{EX}n250000> ?p ?o .
}}
"""

SPARQL_PREDICATE = f"""
SELECT ?s ?o WHERE {{
    ?s <{EX}pred1> ?o .
}}
LIMIT 100
"""


def _uri(n):
    return URIRef(f'{EX}n{n}')


def build_triples(n):
    # 5 distinct predicates, 1000 distinct objects
    for i in range(n):
        yield (_uri(i), URIRef(f'{EX}pred{i % 5}'), _uri(i % 1000 + 1_000_000))


def fmt_ms(s):
    if s >= 60:
        return f'{s/60:.1f} min'
    if s >= 1:
        return f'{s:.2f} s'
    return f'{s*1000:.1f} ms'


def fmt_tps(n, s):
    return f'{n / s:,.0f} t/s'


def run(n, db_path):
    print(f'\n{"=" * 60}')
    print(f'  N = {n:,} plain triples')
    print(f'{"=" * 60}')

    store = plugin.get('SQLAlchemy', Store)(identifier=GRAPH_URI)
    store.open(f'sqlite:///{db_path}', create=True)
    g = StarlightGraph(store=store, identifier=GRAPH_URI)

    print(f'  Loading...', flush=True)
    t0 = time.perf_counter()
    g.addN((s, p, o, g) for s, p, o in build_triples(n))
    load_t = time.perf_counter() - t0

    from sqlalchemy import text
    with store.engine.begin() as conn:
        conn.execute(text('ANALYZE'))

    db_size = os.path.getsize(db_path) / 1024 / 1024
    print(f'  Load time : {fmt_ms(load_t)}  ({fmt_tps(n, load_t)})')
    print(f'  DB size   : {db_size:.1f} MiB')
    print(f'  Triples   : {len(g):,}')

    print(f'  Queries (median of {REPEATS}):')

    # Subject lookup — single URI, small result
    subj_times = []
    for _ in range(REPEATS):
        gc.collect()
        t0 = time.perf_counter()
        list(g.query(SPARQL_SUBJECT))
        subj_times.append(time.perf_counter() - t0)
    subj_t = statistics.median(subj_times)

    # Predicate scan with LIMIT — returns 100 rows
    pred_times = []
    for _ in range(REPEATS):
        gc.collect()
        t0 = time.perf_counter()
        list(g.query(SPARQL_PREDICATE))
        pred_times.append(time.perf_counter() - t0)
    pred_t = statistics.median(pred_times)

    print(f'    Subject lookup (?p ?o for fixed subject)  {fmt_ms(subj_t):>10}')
    print(f'    Predicate scan (LIMIT 100)               {fmt_ms(pred_t):>10}')

    store.close()


if __name__ == '__main__':
    print('StarlightGraph — SQLite plain-triple upper-limit benchmark')
    print(f'Python {sys.version.split()[0]}')

    for n in SCALES:
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        try:
            run(n, db_path)
        except Exception as e:
            print(f'  FAILED at {n:,}: {e}')
            break
        finally:
            try:
                os.unlink(db_path)
            except OSError:
                pass

    print('\nDone.')
