"""
benchmarks/bench_fuseki_rdf11.py

In-memory vs rdf-1.1/Fuseki at increasing scale.

Key hypothesis: rdf-1.1/Fuseki does NOT have the N×M SQL round-trip problem
because StarlightGraph sends the *complete* rewritten SPARQL query to Fuseki
in a single HTTP request. Fuseki's own engine evaluates joins natively.
Expected: query times grow with result size (O(N)) but not superlinearly.

rdf-1.1 stores TripleTerms as tt:HASH URIRefs with encoding triples
(rdf:subject/predicate/object). The SPARQL rewrite converts <<( ?s ?p ?o )>>
to encoding-triple patterns; Fuseki evaluates those patterns as a native join.

Scales: 50K, 250K, 500K TTs (10% reification rate throughout).

Run:
    .venv/bin/python benchmarks/bench_fuseki_rdf11.py
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
from starlight.backends.native import sparql_term as _sparql_term

EX          = 'http://example.org/'
RDF_REIFIES = URIRef('http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies')
RDF_SUBJECT = URIRef('http://www.w3.org/1999/02/22-rdf-syntax-ns#subject')
RDF_PRED    = URIRef('http://www.w3.org/1999/02/22-rdf-syntax-ns#predicate')
RDF_OBJECT  = URIRef('http://www.w3.org/1999/02/22-rdf-syntax-ns#object')
EX_CONF     = URIRef(EX + 'confidence')
GRAPH_URI   = URIRef(EX + 'bench')

QUERY_URL   = 'http://localhost:3030/bench/query'
UPDATE_URL  = 'http://localhost:3030/bench/update'
AUTH        = ('admin', 'admin')

SCALES      = [50_000, 250_000, 500_000]
REPEATS     = 3
BATCH_SIZE  = 500


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------

def _uri(n):
    return URIRef(f'{EX}n{n}')


def build_dataset(n_tt):
    """Same shape as bench_comparison.py: N TTs, 10% reified, 10% annotated."""
    triples = []
    pred_bound = URIRef(f'{EX}n{50_000}')   # i%200==0 shares this predicate
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
    """Replace TripleTerm objects with tt:HASH URIRefs + encoding triples."""
    plain, encoding = [], []
    seen = set()

    def encode(tt):
        s = encode(tt.subject) if isinstance(tt.subject, TripleTerm) else tt.subject
        o = encode(tt.object)  if isinstance(tt.object,  TripleTerm) else tt.object
        uri = URIRef(TT_NS + tt_hash(str(s), str(tt.predicate), str(o)))
        if uri not in seen:
            seen.add(uri)
            encoding.append((uri, RDF_SUBJECT, s))
            encoding.append((uri, RDF_PRED,    tt.predicate))
            encoding.append((uri, RDF_OBJECT,  o))
        return uri

    for s, p, o in triples:
        plain.append((s, p, encode(o) if isinstance(o, TripleTerm) else o))

    return plain + encoding


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


def _batch_insert_rdf11(triples):
    """Send plain (no TripleTerm) triples to Fuseki in batches."""
    buf = []

    def flush():
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

    for s, p, o in triples:
        buf.append(f'    {s.n3()} {p.n3()} {o.n3()} .\n')
        if len(buf) >= BATCH_SIZE:
            flush()
    if buf:
        flush()


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

def _queries(pred_bound, named_graph=False):
    """Return the three benchmark queries.
    named_graph=True wraps patterns in GRAPH <uri> for Fuseki named-graph context.
    named_graph=False omits the wrapper for single-graph (in-memory) queries.
    """
    def wrap(body):
        if named_graph:
            return f'GRAPH <{GRAPH_URI}> {{\n        {body}\n    }}'
        return body

    return [
        ('All reified TTs  (single TT pattern)',  f"""
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
SELECT ?stmt ?s ?p ?o WHERE {{
    {wrap('?stmt rdf:reifies <<( ?s ?p ?o )>> .')}
}}"""),
        ('Reified + confidence>0.7  (TT + join)', f"""
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX ex:  <{EX}>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT ?stmt ?s ?p ?o WHERE {{
    {wrap('?stmt rdf:reifies <<( ?s ?p ?o )>> .\n        ?stmt ex:confidence ?c .\n        FILTER(xsd:decimal(?c) > 0.7)')}
}}"""),
        ('Partial TT match  (bound predicate)',   f"""
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
SELECT ?stmt ?s ?o WHERE {{
    {wrap(f'?stmt rdf:reifies <<( ?s <{pred_bound}> ?o )>> .')}
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
# In-memory runner
# ---------------------------------------------------------------------------

def run_inmemory(triples, pred_bound, n_tt):
    print(f'\n  --- In-memory ---')
    g = StarlightGraph()
    t0 = time.perf_counter()
    g.addN((s, p, o, g) for s, p, o in triples)
    load_t = time.perf_counter() - t0
    print(f'  Load : {fmt_ms(load_t)}  ({fmt_tps(len(triples), load_t)})')
    print(f'  Queries (median of {REPEATS}):')
    queries = _queries(pred_bound, named_graph=False)
    col = max(len(q[0]) for q in queries)
    for label, q in queries:
        t = timeit(lambda q=q: list(g.query(q)))
        rc = len(list(g.query(q)))
        print(f'    {label:<{col}}  {fmt_ms(t):>10}  ({rc} rows)')


# ---------------------------------------------------------------------------
# Fuseki rdf-1.1 runner
# ---------------------------------------------------------------------------

def run_fuseki_rdf11(triples, pred_bound, n_tt):
    print(f'\n  --- rdf-1.1 / Fuseki ---')
    encoded = expand_rdf11(triples)
    print(f'  Physical triples: {len(encoded):,}  ({len(encoded)-len(triples):,} encoding triples added)', flush=True)

    _clear()
    t0 = time.perf_counter()
    _batch_insert_rdf11(encoded)
    load_t = time.perf_counter() - t0
    stored = _triple_count()
    print(f'  Load : {fmt_ms(load_t)}  ({fmt_tps(len(encoded), load_t)})  [{stored:,} in Fuseki]')

    store = SPARQLUpdateStore(
        query_endpoint=QUERY_URL,
        update_endpoint=UPDATE_URL,
        auth=AUTH,
    )
    g = StarlightGraph(store=store, identifier=GRAPH_URI, backend='rdf-1.1')

    print(f'  Queries (median of {REPEATS}):')
    # No GRAPH wrapper: rdflib scopes to the Graph identifier automatically via
    # store.triples(). A GRAPH clause in rdflib's SPARQL evaluator looks for
    # named-graph contexts in the local Python Graph object — finds none.
    queries = _queries(pred_bound, named_graph=False)
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
        requests.get('http://localhost:3030/$/ping', timeout=2).raise_for_status()
    except Exception:
        print('ERROR: Fuseki not reachable at localhost:3030')
        sys.exit(1)

    print('StarlightGraph — in-memory vs rdf-1.1/Fuseki scaling benchmark')
    print(f'Python {sys.version.split()[0]}  |  Fuseki 5.1.0  |  {QUERY_URL}')

    for n in SCALES:
        n_reif = n // 10
        print(f'\n{"=" * 65}')
        print(f'  N = {n:,} TTs  |  {n_reif:,} reifications  |  {n_reif:,} annotations')
        print(f'{"=" * 65}')
        triples, pred_bound = build_dataset(n)
        run_inmemory(triples, pred_bound, n)
        run_fuseki_rdf11(triples, pred_bound, n)

    print('\nDone.')
