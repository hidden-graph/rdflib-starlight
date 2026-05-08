"""
benchmarks/bench_oxigraph.py

In-memory vs rdf-1.2/Oxigraph (in-memory) at increasing scale.

Oxigraph is a Rust-based RDF 1.2 native store. Triple terms are stored and
queried using the final RDF 1.2 <<( s p o )>> syntax with no translation
layer. StarlightGraph sends queries directly to Oxigraph's HTTP endpoint;
results arrive as type:"triple" JSON and are converted to TripleTerm objects.

This test uses Oxigraph in in-memory mode (no --location flag) for fair
comparison with Fuseki's dbType=mem configuration.

Scales: 50K, 250K, 500K TTs (10% reification rate throughout).

Run:
    docker run -d --name oxigraph-bench -p 7979:7878 \\
        ghcr.io/oxigraph/oxigraph serve --bind 0.0.0.0:7878
    .venv/bin/python benchmarks/bench_oxigraph.py
"""

import gc
import statistics
import sys
import time

import requests
from rdflib import URIRef, Literal
from rdflib.namespace import XSD
from rdflib.plugins.stores.sparqlstore import SPARQLUpdateStore

sys.path.insert(0, '.')
from starlight.graph import StarlightGraph
from starlight.model.triple import TripleTerm
from starlight.backends.native import sparql_term

EX          = 'http://example.org/'
RDF_REIFIES = URIRef('http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies')
EX_CONF     = URIRef(EX + 'confidence')
GRAPH_URI   = URIRef(EX + 'bench')

BASE_URL    = 'http://localhost:7979'
QUERY_URL   = f'{BASE_URL}/query'
UPDATE_URL  = f'{BASE_URL}/update'
BACKEND     = 'rdf-1.2'

SCALES      = [50_000, 250_000, 500_000]
REPEATS     = 3
BATCH_SIZE  = 500


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------

def _uri(n):
    return URIRef(f'{EX}n{n}')


def build_dataset(n_tt):
    triples = []
    pred_bound = URIRef(f'{EX}n{50_000}')
    for i in range(n_tt):
        tt = TripleTerm(_uri(i), _uri(i % 200 + 50_000), _uri(i % 100 + 60_000))
        triples.append((_uri(i), _uri(i % 200 + 50_000), _uri(i % 100 + 60_000)))
        if i < n_tt // 10:
            stmt = _uri(f'stmt{i}')
            conf = round(0.5 + (i % 10) / 20, 2)
            triples.append((stmt, RDF_REIFIES, tt))
            triples.append((stmt, EX_CONF, Literal(str(conf), datatype=XSD.decimal)))
    return triples, pred_bound


# ---------------------------------------------------------------------------
# Oxigraph helpers  (no named graph — Oxigraph default graph)
# ---------------------------------------------------------------------------

def _clear():
    requests.post(
        UPDATE_URL,
        data='DELETE WHERE { ?s ?p ?o }'.encode(),
        headers={'Content-Type': 'application/sparql-update'},
        timeout=30,
    ).raise_for_status()


def _batch_insert(triples):
    """Send triples using RDF 1.2 <<( )>> syntax for TripleTerms."""
    buf = []

    def flush():
        body = 'INSERT DATA {\n' + ''.join(buf) + '}\n'
        requests.post(
            UPDATE_URL,
            data=body.encode('utf-8'),
            headers={'Content-Type': 'application/sparql-update'},
            timeout=60,
        ).raise_for_status()
        buf.clear()

    for s, p, o in triples:
        s_str = sparql_term(s, BACKEND)
        p_str = sparql_term(p, BACKEND)
        o_str = sparql_term(o, BACKEND)
        buf.append(f'  {s_str} {p_str} {o_str} .\n')
        if len(buf) >= BATCH_SIZE:
            flush()
    if buf:
        flush()


def _triple_count():
    resp = requests.post(
        QUERY_URL,
        data='SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }'.encode(),
        headers={'Content-Type': 'application/sparql-query',
                 'Accept': 'application/sparql-results+json'},
        timeout=30,
    )
    resp.raise_for_status()
    return int(resp.json()['results']['bindings'][0]['n']['value'])


# ---------------------------------------------------------------------------
# Queries — no named graph wrapper; Oxigraph default graph holds all data
# ---------------------------------------------------------------------------

def _queries(pred_bound):
    return [
        ('All reified TTs  (single TT pattern)',  f"""
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
SELECT ?stmt ?s ?p ?o WHERE {{
    ?stmt rdf:reifies <<( ?s ?p ?o )>> .
}}"""),
        ('Reified + confidence>0.7  (TT + join)', f"""
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX ex:  <{EX}>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT ?stmt ?s ?p ?o WHERE {{
    ?stmt rdf:reifies <<( ?s ?p ?o )>> .
    ?stmt ex:confidence ?c .
    FILTER(xsd:decimal(?c) > 0.7)
}}"""),
        ('Partial TT match  (bound predicate)',   f"""
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
SELECT ?stmt ?s ?o WHERE {{
    ?stmt rdf:reifies <<( ?s <{pred_bound}> ?o )>> .
}}"""),
    ]


# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------

def timeit(fn, repeats=REPEATS):
    times = []
    for _ in range(repeats):
        gc.collect()
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    return statistics.median(times)


def fmt_ms(s):
    ms = s * 1000
    return f'{ms/1000:.2f} s' if ms >= 1000 else f'{ms:.1f} ms'


def fmt_tps(n, s):
    return f'{n / s:,.0f} t/s'


# ---------------------------------------------------------------------------
# In-memory baseline
# ---------------------------------------------------------------------------

def _inmem_queries(pred_bound):
    return [
        ('All reified TTs  (single TT pattern)',  f"""
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
SELECT ?stmt ?s ?p ?o WHERE {{ ?stmt rdf:reifies <<( ?s ?p ?o )>> . }}"""),
        ('Reified + confidence>0.7  (TT + join)', f"""
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX ex:  <{EX}>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT ?stmt ?s ?p ?o WHERE {{
    ?stmt rdf:reifies <<( ?s ?p ?o )>> .
    ?stmt ex:confidence ?c .
    FILTER(xsd:decimal(?c) > 0.7)
}}"""),
        ('Partial TT match  (bound predicate)',   f"""
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
SELECT ?stmt ?s ?o WHERE {{ ?stmt rdf:reifies <<( ?s <{pred_bound}> ?o )>> . }}"""),
    ]


def run_inmemory(triples, pred_bound):
    print(f'\n  --- In-memory ---')
    g = StarlightGraph()
    t0 = time.perf_counter()
    g.addN((s, p, o, g) for s, p, o in triples)
    load_t = time.perf_counter() - t0
    print(f'  Load : {fmt_ms(load_t)}  ({fmt_tps(len(triples), load_t)})')
    print(f'  Queries (median of {REPEATS}):')
    queries = _inmem_queries(pred_bound)
    col = max(len(q[0]) for q in queries)
    for label, q in queries:
        t = timeit(lambda q=q: list(g.query(q)))
        rc = len(list(g.query(q)))
        print(f'    {label:<{col}}  {fmt_ms(t):>10}  ({rc} rows)')


# ---------------------------------------------------------------------------
# Oxigraph runner
# ---------------------------------------------------------------------------

def run_oxigraph(triples, pred_bound):
    print(f'\n  --- rdf-1.2 / Oxigraph (in-memory) ---')
    print(f'  Physical triples to load: {len(triples):,}  (native RDF 1.2 storage)', flush=True)

    _clear()
    t0 = time.perf_counter()
    _batch_insert(triples)
    load_t = time.perf_counter() - t0
    stored = _triple_count()
    print(f'  Load : {fmt_ms(load_t)}  ({fmt_tps(len(triples), load_t)})  [{stored:,} in Oxigraph]')

    store = SPARQLUpdateStore(
        query_endpoint=QUERY_URL,
        update_endpoint=UPDATE_URL,
    )
    g = StarlightGraph(store=store, identifier=GRAPH_URI, backend=BACKEND)

    print(f'  Queries (median of {REPEATS}):')
    queries = _queries(pred_bound)
    col = max(len(q[0]) for q in queries)
    for label, q in queries:
        t = timeit(lambda q=q: list(g.query(q)))
        rc = len(list(g.query(q)))
        print(f'    {label:<{col}}  {fmt_ms(t):>10}  ({rc} rows)')

    _clear()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    try:
        requests.get(BASE_URL, timeout=2).raise_for_status()
    except Exception:
        print(f'ERROR: Oxigraph not reachable at {BASE_URL}')
        print('Start with: docker run -d --name oxigraph-bench -p 7979:7878 \\')
        print('    ghcr.io/oxigraph/oxigraph serve --bind 0.0.0.0:7878')
        sys.exit(1)

    print('StarlightGraph — in-memory vs rdf-1.2/Oxigraph scaling benchmark')
    print(f'Python {sys.version.split()[0]}  |  Oxigraph (latest)  |  {QUERY_URL}')
    print('Storage: in-memory (no --location)')

    for n in SCALES:
        n_reif = n // 10
        print(f'\n{"=" * 65}')
        print(f'  N = {n:,} TTs  |  {n_reif:,} reifications  |  {n_reif:,} annotations')
        print(f'{"=" * 65}')
        triples, pred_bound = build_dataset(n)
        run_inmemory(triples, pred_bound)
        run_oxigraph(triples, pred_bound)

    print('\nDone.')
