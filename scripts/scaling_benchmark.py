"""
scripts/scaling_benchmark.py

Scaling benchmark: compare StarlightGraph in-memory vs SQLite backend.

For N reified triples, measures:
  - Load time (generate + add to store)
  - First query  (cold — raw execution graph cache not yet built)
  - Repeat query (warm — raw execution graph cache in memory)
  - Peak memory   (in-memory store only, via tracemalloc)

Run from the project root:
    .venv/bin/python scripts/scaling_benchmark.py
"""

import gc
import os
import sys
import tempfile
import time
import tracemalloc

import rdflib_sqlalchemy
rdflib_sqlalchemy.registerplugins()

from rdflib import URIRef, Literal
from rdflib.namespace import XSD

from starlight.graph import StarlightGraph
from starlight.model.triple import TripleTerm

EX        = 'http://example.org/'
RDF_NS    = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'
RDF_REIF  = URIRef(RDF_NS + 'reifies')
EX_CONF   = URIRef(EX + 'confidence')
EX_SOURCE = URIRef(EX + 'source')
GRAPH_URI = URIRef(EX + 'bench')

REPEAT_QUERIES = 3   # how many warm queries to average

# Note on SQLite write performance:
# rdflib-sqlalchemy issues one SQL transaction per add() call.  Each reified
# triple here produces 3 application triples + 3 encoding triples = 6 INSERTs.
# This is the worst-case pattern for per-row commit overhead.  A production
# deployment would use a store that supports batch writes (e.g. PostgreSQL
# with SQLAlchemy connection pooling, or a native RDF store like Oxigraph).

QUERY = f"""
PREFIX ex:  <{EX}>
PREFIX rdf: <{RDF_NS}>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

SELECT ?stmt ?s ?o ?conf WHERE {{
    ?stmt rdf:reifies ?tt .
    ?tt   rdf:subject ?s ;
          rdf:object  ?o .
    ?stmt ex:confidence ?conf .
    FILTER(xsd:decimal(?conf) > 0.5)
}}
ORDER BY ?stmt
"""

N_VALUES = [100, 250, 500, 1_000]


# ---------------------------------------------------------------------------
# Data generation
# ---------------------------------------------------------------------------

def build_triples(n: int) -> list[tuple]:
    """Return n unique (stmt, rdf:reifies, TripleTerm) triples plus metadata."""
    triples = []
    for i in range(n):
        subj  = URIRef(f'{EX}entity_{i}')
        obj   = URIRef(f'{EX}entity_{(i + 1) % n}')
        tt    = TripleTerm(subj, URIRef(EX + 'relatesTo'), obj)
        stmt  = URIRef(f'{EX}stmt_{i}')
        conf  = round(0.1 + (i % 10) * 0.09, 2)   # 0.10 .. 0.91
        src   = URIRef(f'{EX}source_{i % 5}')
        triples.append((stmt, RDF_REIF,  tt))
        triples.append((stmt, EX_CONF,   Literal(str(conf), datatype=XSD.decimal)))
        triples.append((stmt, EX_SOURCE, src))
    return triples


# ---------------------------------------------------------------------------
# Timing helpers
# ---------------------------------------------------------------------------

def _ms(seconds: float) -> str:
    if seconds >= 1:
        return f'{seconds:.2f} s '
    return f'{seconds * 1000:.1f} ms'


def time_query(sg: StarlightGraph, warm: bool) -> float:
    t0 = time.perf_counter()
    rows = list(sg.query(QUERY))
    return time.perf_counter() - t0, len(rows)


# ---------------------------------------------------------------------------
# Benchmark runners
# ---------------------------------------------------------------------------

def bench_memory(triples: list[tuple]) -> dict:
    gc.collect()
    tracemalloc.start()

    t0 = time.perf_counter()
    sg = StarlightGraph()
    sg.bind('ex', EX)
    for triple in triples:
        sg.add(triple)
    load_time = time.perf_counter() - t0

    peak_bytes = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()

    q1_time, n_rows = time_query(sg, warm=False)

    warm_times = []
    for _ in range(REPEAT_QUERIES):
        t, _ = time_query(sg, warm=True)
        warm_times.append(t)
    q_warm = sum(warm_times) / len(warm_times)

    return {
        'load':   load_time,
        'q1':     q1_time,
        'q_warm': q_warm,
        'rows':   n_rows,
        'mem_mb': peak_bytes / 1_048_576,
    }


def bench_sqlite(triples: list[tuple], db_path: str) -> dict:
    # --- write pass ---
    t0 = time.perf_counter()
    writer = StarlightGraph(store='SQLAlchemy', identifier=GRAPH_URI)
    writer.open(f'sqlite:///{db_path}', create=True)
    writer.bind('ex', EX)
    for triple in triples:
        writer.add(triple)
    writer.close()
    load_time = time.perf_counter() - t0

    # --- read pass ---
    sg = StarlightGraph(store='SQLAlchemy', identifier=GRAPH_URI)
    sg.open(f'sqlite:///{db_path}', create=False)

    q1_time, n_rows = time_query(sg, warm=False)

    warm_times = []
    for _ in range(REPEAT_QUERIES):
        t, _ = time_query(sg, warm=True)
        warm_times.append(t)
    q_warm = sum(warm_times) / len(warm_times)

    sg.close()
    return {
        'load':    load_time,
        'q1':      q1_time,
        'q_warm':  q_warm,
        'rows':    n_rows,
        'db_kb':   os.path.getsize(db_path) // 1024,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print('StarlightGraph — scaling benchmark')
    print(f'Repeat queries (warm): {REPEAT_QUERIES}')
    print(f'N values: {N_VALUES}\n')

    hdr = (
        f'{"N":>7}  '
        f'{"":^38}  '
        f'{"":^38}'
    )
    hdr2 = (
        f'{"N":>7}  '
        f'{"── In-memory ──────────────────────":^38}  '
        f'{"── SQLite ─────────────────────────":^38}'
    )
    hdr3 = (
        f'{"":>7}  '
        f'{"load":>8} {"q1 (cold)":>10} {"q (warm)":>10} {"rows":>5} {"mem":>7}  '
        f'{"load":>8} {"q1 (cold)":>10} {"q (warm)":>10} {"rows":>5} {"db":>7}'
    )
    print(hdr2)
    print(hdr3)
    print('─' * 100)

    for n in N_VALUES:
        triples = build_triples(n)

        mem = bench_memory(triples)

        db_fd, db_path = tempfile.mkstemp(suffix='.db')
        os.close(db_fd)
        os.unlink(db_path)   # let SQLAlchemy create it fresh
        try:
            sql = bench_sqlite(triples, db_path)
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

        expected_rows = sum(1 for i in range(n) if round(0.1 + (i % 10) * 0.09, 2) > 0.5)

        assert mem['rows'] == expected_rows, \
            f'Memory: expected {expected_rows} rows, got {mem["rows"]}'
        assert sql['rows'] == expected_rows, \
            f'SQLite: expected {expected_rows} rows, got {sql["rows"]}'

        print(
            f'{n:>7}  '
            f'{_ms(mem["load"]):>8} {_ms(mem["q1"]):>10} {_ms(mem["q_warm"]):>10} '
            f'{mem["rows"]:>5} {mem["mem_mb"]:>6.1f}M  '
            f'{_ms(sql["load"]):>8} {_ms(sql["q1"]):>10} {_ms(sql["q_warm"]):>10} '
            f'{sql["rows"]:>5} {sql["db_kb"]:>5}KB'
        )

    print('\nAll row-count assertions passed.')


if __name__ == '__main__':
    main()
