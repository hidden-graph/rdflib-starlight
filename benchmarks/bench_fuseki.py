"""
benchmarks/bench_fuseki.py

rdf-1.1/Fuseki vs rdf-star/Fuseki at 50K and 250K TTs.

Both backends use identical datasets. rdf-1.1 expands TripleTerms to
tt:HASH URIRefs + 3 encoding triples before sending to Fuseki; rdf-star
stores native quoted triples. In both cases Fuseki receives and evaluates
the complete SPARQL query — there is no N×M round-trip problem.

Queries tested (same three as bench_comparison.py):
  1. All reified TTs — single TT pattern          : <<( ?s ?p ?o )>>
  2. Reified TTs with confidence > 0.7 — TT + join
  3. Partial TT match — TT with bound predicate   : <<( ?s <pred> ?o )>>

Fuseki requirements:
  docker run -d --name fuseki-bench -p 3030:3030 -e ADMIN_PASSWORD=admin stain/jena-fuseki
  curl -s -X POST http://localhost:3030/$/datasets -u admin:admin \\
       -H "Content-Type: application/x-www-form-urlencoded" \\
       --data "dbName=bench&dbType=mem"

Run:
    .venv/bin/python benchmarks/bench_fuseki.py
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
from starlight.model.encoding import TT_NS, tt_hash
from starlight.backends.native import sparql_term

EX          = 'http://example.org/'
RDF_REIFIES = URIRef('http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies')
RDF_SUBJECT  = URIRef('http://www.w3.org/1999/02/22-rdf-syntax-ns#subject')
RDF_PRED     = URIRef('http://www.w3.org/1999/02/22-rdf-syntax-ns#predicate')
RDF_OBJECT   = URIRef('http://www.w3.org/1999/02/22-rdf-syntax-ns#object')
EX_CONF     = URIRef(EX + 'confidence')
GRAPH_URI   = URIRef(EX + 'bench')

QUERY_URL   = 'http://localhost:3030/bench/query'
UPDATE_URL  = 'http://localhost:3030/bench/update'
AUTH        = ('admin', 'admin')

SCALES      = [50_000, 250_000]
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


def expand_rdf11(triples):
    """Expand TripleTerms to tt:HASH URIRefs + encoding triples for rdf-1.1 storage."""
    out = []
    seen = set()

    def encode(tt):
        s = encode(tt.subject)   if isinstance(tt.subject, TripleTerm)   else tt.subject
        o = encode(tt.object)    if isinstance(tt.object,  TripleTerm)   else tt.object
        uri = URIRef(TT_NS + tt_hash(str(s), str(tt.predicate), str(o)))
        if uri not in seen:
            seen.add(uri)
            out.append((uri, RDF_SUBJECT, s))
            out.append((uri, RDF_PRED,    tt.predicate))
            out.append((uri, RDF_OBJECT,  o))
        return uri

    plain = []
    for s, p, o in triples:
        if isinstance(o, TripleTerm):
            plain.append((s, p, encode(o)))
        else:
            plain.append((s, p, o))

    return plain + out


# ---------------------------------------------------------------------------
# Fuseki helpers
# ---------------------------------------------------------------------------

def _clear():
    requests.post(
        UPDATE_URL,
        data=f'CLEAR SILENT GRAPH <{GRAPH_URI}>'.encode(),
        headers={'Content-Type': 'application/sparql-update'},
        auth=AUTH, timeout=30,
    ).raise_for_status()


def _flush(buf):
    body = (
        f'INSERT DATA {{\n  GRAPH <{GRAPH_URI}> {{\n'
        + ''.join(buf)
        + '  }\n}\n'
    )
    requests.post(
        UPDATE_URL,
        data=body.encode('utf-8'),
        headers={'Content-Type': 'application/sparql-update'},
        auth=AUTH, timeout=60,
    ).raise_for_status()
    buf.clear()


def _batch_insert(triples, backend):
    buf = []
    for s, p, o in triples:
        s_str = sparql_term(s, backend)
        p_str = sparql_term(p, backend)
        o_str = sparql_term(o, backend)
        buf.append(f'    {s_str} {p_str} {o_str} .\n')
        if len(buf) >= BATCH_SIZE:
            _flush(buf)
    if buf:
        _flush(buf)


def _triple_count():
    resp = requests.post(
        QUERY_URL,
        data=f'SELECT (COUNT(*) AS ?n) WHERE {{ GRAPH <{GRAPH_URI}> {{ ?s ?p ?o }} }}'.encode(),
        headers={'Content-Type': 'application/sparql-query',
                 'Accept': 'application/sparql-results+json'},
        auth=AUTH, timeout=30,
    )
    resp.raise_for_status()
    return int(resp.json()['results']['bindings'][0]['n']['value'])


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def _queries(pred_bound):
    return [
        ('All reified TTs  (single TT pattern)',  f"""
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
SELECT ?stmt ?s ?p ?o WHERE {{
    GRAPH <{GRAPH_URI}> {{ ?stmt rdf:reifies <<( ?s ?p ?o )>> . }}
}}"""),
        ('Reified + confidence>0.7  (TT + join)', f"""
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX ex:  <{EX}>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT ?stmt ?s ?p ?o WHERE {{
    GRAPH <{GRAPH_URI}> {{
        ?stmt rdf:reifies <<( ?s ?p ?o )>> .
        ?stmt ex:confidence ?c .
        FILTER(xsd:decimal(?c) > 0.7)
    }}
}}"""),
        ('Partial TT match  (bound predicate)',   f"""
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
SELECT ?stmt ?s ?o WHERE {{
    GRAPH <{GRAPH_URI}> {{ ?stmt rdf:reifies <<( ?s <{pred_bound}> ?o )>> . }}
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
# Runner
# ---------------------------------------------------------------------------

def run(backend, n_tt):
    n_reif = n_tt // 10
    print(f'\n{"=" * 65}')
    print(f'  Backend: {backend}  |  N = {n_tt:,} TTs  |  {n_reif:,} reifications')
    print(f'{"=" * 65}')

    triples, pred_bound = build_dataset(n_tt)

    if backend == 'rdf-1.1':
        load_triples = expand_rdf11(triples)
    else:
        load_triples = triples

    n_total = len(load_triples)
    print(f'  Physical triples to load: {n_total:,}  (batch size: {BATCH_SIZE})', flush=True)

    _clear()
    t0 = time.perf_counter()
    _batch_insert(load_triples, backend)
    load_t = time.perf_counter() - t0

    stored = _triple_count()
    print(f'  Load time : {fmt_ms(load_t)}  ({fmt_tps(n_total, load_t)})')
    print(f'  Triples   : {stored:,} (Fuseki count)')

    store = SPARQLUpdateStore(
        query_endpoint=QUERY_URL,
        update_endpoint=UPDATE_URL,
        auth=AUTH,
    )
    g = StarlightGraph(store=store, identifier=GRAPH_URI, backend=backend)
    queries = _queries(pred_bound)
    col = max(len(q[0]) for q in queries)

    print(f'\n  Queries (median of {REPEATS} runs):')
    for label, q in queries:
        t = timeit(lambda q=q: list(g.query(q)))
        result_count = len(list(g.query(q)))
        print(f'    {label:<{col}}  {fmt_ms(t):>10}  ({result_count} rows)')

    _clear()


if __name__ == '__main__':
    try:
        requests.get('http://localhost:3030/$/ping', timeout=2).raise_for_status()
    except Exception:
        print('ERROR: Fuseki not reachable at localhost:3030 — start it first.')
        sys.exit(1)

    print('StarlightGraph — rdf-1.1 vs rdf-star / Fuseki comparison')
    print(f'Python {sys.version.split()[0]}')
    print(f'Fuseki: {QUERY_URL}')

    for n in SCALES:
        for backend in ('rdf-1.1', 'rdf-star'):
            run(backend, n)

    print('\nDone.')
