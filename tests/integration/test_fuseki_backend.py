"""
tests/integration/test_fuseki_backend.py

Integration tests for StarlightGraph backed by Apache Jena Fuseki via
rdflib's SPARQLUpdateStore.

Requires a running Fuseki instance:
    docker run -d --name fuseki-test -p 3030:3030 -e ADMIN_PASSWORD=admin stain/jena-fuseki

Create an in-memory dataset before running:
    curl -X POST http://localhost:3030/$/datasets -u admin:admin \\
         -H "Content-Type: application/x-www-form-urlencoded" \\
         --data "dbName=starlight&dbType=mem"

Run:
    .venv/bin/pytest tests/integration/ -v
"""

import pytest
import requests

from rdflib import URIRef, Literal
from rdflib.namespace import XSD
from rdflib.plugins.stores.sparqlstore import SPARQLUpdateStore

from starlight.graph import StarlightGraph
from starlight.model.triple import TripleTerm

# ---------------------------------------------------------------------------
# Endpoint config
# ---------------------------------------------------------------------------

FUSEKI_BASE   = 'http://localhost:3030/starlight'
QUERY_URL     = f'{FUSEKI_BASE}/query'
UPDATE_URL    = f'{FUSEKI_BASE}/update'
GRAPH_URI     = URIRef('http://example.org/test-graph')

EX        = 'http://example.org/'
RDF_NS    = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'
RDF_REIF  = URIRef(RDF_NS + 'reifies')
EX_CONF   = URIRef(EX + 'confidence')


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _fuseki_available() -> bool:
    try:
        r = requests.get('http://localhost:3030/$/ping', timeout=2)
        return r.status_code == 200
    except Exception:
        return False


fuseki = pytest.mark.skipif(
    not _fuseki_available(),
    reason='Fuseki not running — start with: docker run -d --name fuseki-test -p 3030:3030 -e ADMIN_PASSWORD=admin stain/jena-fuseki',
)


def _make_store() -> SPARQLUpdateStore:
    store = SPARQLUpdateStore(
        query_endpoint=QUERY_URL,
        update_endpoint=UPDATE_URL,
        auth=('admin', 'admin'),
    )
    return store


def _clear_graph():
    """Delete all triples from the test graph between tests."""
    requests.post(
        UPDATE_URL,
        data=f'CLEAR SILENT GRAPH <{GRAPH_URI}>',
        headers={'Content-Type': 'application/sparql-update'},
        auth=('admin', 'admin'),
        timeout=10,
    ).raise_for_status()


@pytest.fixture
def sg():
    """Fresh StarlightGraph backed by Fuseki, cleared before each test (rdf-1.1 mode)."""
    _clear_graph()
    g = StarlightGraph(store=_make_store(), identifier=GRAPH_URI)
    g.bind('ex', EX)
    yield g


@pytest.fixture
def sg_native():
    """Fresh StarlightGraph backed by Fuseki in rdf-star native mode."""
    _clear_graph()
    g = StarlightGraph(store=_make_store(), identifier=GRAPH_URI, backend='rdf-star')
    g.bind('ex', EX)
    yield g


# ---------------------------------------------------------------------------
# Basic round-trip
# ---------------------------------------------------------------------------

@fuseki
class TestFusekiRoundTrip:

    def test_plain_triple_write_read(self, sg):
        s, p, o = URIRef(EX+'alice'), URIRef(EX+'knows'), URIRef(EX+'bob')
        sg.add((s, p, o))
        assert (s, p, o) in sg

    def test_triple_term_write_read(self, sg):
        tt  = TripleTerm(URIRef(EX+'alice'), URIRef(EX+'knows'), URIRef(EX+'bob'))
        stmt = URIRef(EX+'stmt1')
        sg.add((stmt, RDF_REIF, tt))
        sg._build_registry_from_store()   # reload registry as if fresh connection

        results = list(sg.triples((stmt, RDF_REIF, None)))
        assert len(results) == 1
        _, _, restored = results[0]
        assert isinstance(restored, TripleTerm)
        assert restored == tt

    def test_triple_term_encoding_hidden(self, sg):
        """Encoding triples (rdf:subject/predicate/object) are not surfaced."""
        tt = TripleTerm(URIRef(EX+'a'), URIRef(EX+'b'), URIRef(EX+'c'))
        sg.add((URIRef(EX+'stmt'), RDF_REIF, tt))
        visible = list(sg.triples((None, None, None)))
        predicates = {p for _, p, _ in visible}
        assert URIRef(RDF_NS + 'subject')   not in predicates
        assert URIRef(RDF_NS + 'predicate') not in predicates
        assert URIRef(RDF_NS + 'object')    not in predicates

    def test_multiple_triple_terms(self, sg):
        tts = [
            TripleTerm(URIRef(EX+f'a{i}'), URIRef(EX+'rel'), URIRef(EX+f'b{i}'))
            for i in range(5)
        ]
        for i, tt in enumerate(tts):
            sg.add((URIRef(EX+f'stmt{i}'), RDF_REIF, tt))
        sg._build_registry_from_store()
        assert len(list(sg.triple_terms())) == 5



# ---------------------------------------------------------------------------
# SPARQL 1.2 queries via Fuseki
# ---------------------------------------------------------------------------

@fuseki
class TestFusekiSPARQL:

    def _load(self, sg):
        sg.add((URIRef(EX+'stmt1'), RDF_REIF,
                TripleTerm(URIRef(EX+'alice'), URIRef(EX+'knows'), URIRef(EX+'bob'))))
        sg.add((URIRef(EX+'stmt1'), EX_CONF,
                Literal('0.9', datatype=XSD.decimal)))
        sg.add((URIRef(EX+'stmt2'), RDF_REIF,
                TripleTerm(URIRef(EX+'bob'), URIRef(EX+'likes'), URIRef(EX+'carol'))))
        sg.add((URIRef(EX+'stmt2'), EX_CONF,
                Literal('0.4', datatype=XSD.decimal)))
        sg._build_registry_from_store()

    def test_select_reified_triples(self, sg):
        self._load(sg)
        q = f"""
        PREFIX ex: <{EX}>
        PREFIX rdf: <{RDF_NS}>
        SELECT ?stmt ?tt WHERE {{
            ?stmt rdf:reifies ?tt .
        }}
        """
        rows = list(sg.query(q))
        assert len(rows) == 2
        stmts = {r[0] for r in rows}
        assert URIRef(EX+'stmt1') in stmts
        assert URIRef(EX+'stmt2') in stmts

    def test_triple_term_restored_in_results(self, sg):
        self._load(sg)
        q = f"""
        PREFIX ex: <{EX}>
        PREFIX rdf: <{RDF_NS}>
        SELECT ?tt WHERE {{
            <{EX}stmt1> rdf:reifies ?tt .
        }}
        """
        rows = list(sg.query(q))
        assert len(rows) == 1
        assert isinstance(rows[0][0], TripleTerm)
        assert rows[0][0] == TripleTerm(
            URIRef(EX+'alice'), URIRef(EX+'knows'), URIRef(EX+'bob')
        )

    def test_sparql12_triple_term_pattern(self, sg):
        """SPARQL 1.2 <<( )>> pattern is rewritten and executed via Fuseki."""
        self._load(sg)
        q = f"""
        PREFIX ex: <{EX}>
        PREFIX rdf: <{RDF_NS}>
        SELECT ?stmt ?s ?o WHERE {{
            ?stmt rdf:reifies <<( ?s ex:knows ?o )>> .
        }}
        """
        rows = list(sg.query(q))
        assert len(rows) == 1
        assert rows[0][1] == URIRef(EX+'alice')
        assert rows[0][2] == URIRef(EX+'bob')

    def test_filter_by_confidence(self, sg):
        """Combined triple-term pattern + FILTER sent to Fuseki."""
        self._load(sg)
        q = f"""
        PREFIX ex: <{EX}>
        PREFIX rdf: <{RDF_NS}>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        SELECT ?stmt WHERE {{
            ?stmt rdf:reifies <<( ?s ?p ?o )>> .
            ?stmt ex:confidence ?conf .
            FILTER(xsd:decimal(?conf) > 0.5)
        }}
        """
        rows = list(sg.query(q))
        assert len(rows) == 1
        assert rows[0][0] == URIRef(EX+'stmt1')


# ---------------------------------------------------------------------------
# Bulk write via addN
# ---------------------------------------------------------------------------

@fuseki
class TestFusekiBulkWrite:

    def test_addN_writes_all_triples(self, sg):
        n = 20
        triples = [
            (URIRef(EX+f'stmt{i}'), RDF_REIF,
             TripleTerm(URIRef(EX+f'a{i}'), URIRef(EX+'rel'), URIRef(EX+f'b{i}')))
            for i in range(n)
        ]
        sg.addN((s, p, o, sg) for s, p, o in triples)
        sg._build_registry_from_store()
        assert len(list(sg.triple_terms())) == n

    def test_addN_triple_terms_restorable(self, sg):
        tt = TripleTerm(URIRef(EX+'x'), URIRef(EX+'y'), URIRef(EX+'z'))
        sg.addN([(URIRef(EX+'stmt'), RDF_REIF, tt, sg)])
        sg._build_registry_from_store()
        results = list(sg.triples((URIRef(EX+'stmt'), RDF_REIF, None)))
        assert len(results) == 1
        assert isinstance(results[0][2], TripleTerm)
        assert results[0][2] == tt


# ---------------------------------------------------------------------------
# Native rdf-star backend (Jena << >> syntax, no encoding layer)
# ---------------------------------------------------------------------------

@fuseki
class TestFusekiNativeRdfStar:

    def test_plain_triple_write_read(self, sg_native):
        s, p, o = URIRef(EX+'alice'), URIRef(EX+'knows'), URIRef(EX+'bob')
        sg_native.add((s, p, o))
        assert (s, p, o) in sg_native

    def test_triple_term_write_read(self, sg_native):
        tt   = TripleTerm(URIRef(EX+'alice'), URIRef(EX+'knows'), URIRef(EX+'bob'))
        stmt = URIRef(EX+'stmt1')
        sg_native.add((stmt, RDF_REIF, tt))
        results = list(sg_native.triples((stmt, RDF_REIF, None)))
        assert len(results) == 1
        _, _, restored = results[0]
        assert isinstance(restored, TripleTerm)
        assert restored == tt

    def test_wildcard_triples(self, sg_native):
        sg_native.add((URIRef(EX+'s1'), URIRef(EX+'p'), URIRef(EX+'o1')))
        sg_native.add((URIRef(EX+'s2'), URIRef(EX+'p'), URIRef(EX+'o2')))
        results = list(sg_native.triples((None, URIRef(EX+'p'), None)))
        assert len(results) == 2

    def test_contains(self, sg_native):
        s, p, o = URIRef(EX+'alice'), URIRef(EX+'knows'), URIRef(EX+'bob')
        assert (s, p, o) not in sg_native
        sg_native.add((s, p, o))
        assert (s, p, o) in sg_native

    def test_query_plain_select(self, sg_native):
        sg_native.add((URIRef(EX+'alice'), URIRef(EX+'knows'), URIRef(EX+'bob')))
        q = f'SELECT ?o WHERE {{ GRAPH <{GRAPH_URI}> {{ <{EX}alice> <{EX}knows> ?o . }} }}'
        rows = list(sg_native.query(q))
        assert len(rows) == 1
        assert rows[0][0] == URIRef(EX+'bob')

    def test_query_triple_term_pattern(self, sg_native):
        tt = TripleTerm(URIRef(EX+'alice'), URIRef(EX+'knows'), URIRef(EX+'bob'))
        sg_native.add((URIRef(EX+'stmt1'), RDF_REIF, tt))
        q = f"""
        PREFIX rdf: <{RDF_NS}>
        SELECT ?tt WHERE {{
            GRAPH <{GRAPH_URI}> {{
                <{EX}stmt1> rdf:reifies ?tt .
            }}
        }}
        """
        rows = list(sg_native.query(q))
        assert len(rows) == 1
        assert isinstance(rows[0][0], TripleTerm)
        assert rows[0][0] == tt

    def test_query_sparql12_syntax_rewritten(self, sg_native):
        """SPARQL 1.2 <<( )>> is rewritten to << >> before sending to Fuseki."""
        tt = TripleTerm(URIRef(EX+'alice'), URIRef(EX+'knows'), URIRef(EX+'bob'))
        sg_native.add((URIRef(EX+'stmt1'), RDF_REIF, tt))
        q = f"""
        PREFIX ex: <{EX}>
        PREFIX rdf: <{RDF_NS}>
        SELECT ?stmt WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?stmt rdf:reifies <<( ex:alice ex:knows ex:bob )>> .
            }}
        }}
        """
        rows = list(sg_native.query(q))
        assert len(rows) == 1
        assert rows[0][0] == URIRef(EX+'stmt1')

    def test_no_encoding_triples_visible(self, sg_native):
        """Native mode stores no tt:HASH encoding triples."""
        tt = TripleTerm(URIRef(EX+'a'), URIRef(EX+'b'), URIRef(EX+'c'))
        sg_native.add((URIRef(EX+'stmt'), RDF_REIF, tt))
        predicates = {p for _, p, _ in sg_native.triples((None, None, None))}
        assert URIRef(RDF_NS + 'subject')   not in predicates
        assert URIRef(RDF_NS + 'predicate') not in predicates
        assert URIRef(RDF_NS + 'object')    not in predicates
