"""
tests/integration/test_oxigraph_backend.py

Integration tests for StarlightGraph backed by Oxigraph via rdf-1.2 native mode.

Oxigraph speaks the final W3C RDF 1.2 <<( )>> syntax natively and returns
"type":"triple" in SPARQL JSON results.

Requires a running Oxigraph instance:
    docker run -d --name oxigraph-test -p 7878:7878 \\
      ghcr.io/oxigraph/oxigraph serve --location /data --bind 0.0.0.0:7878

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

OXIGRAPH_BASE = 'http://localhost:7878'
QUERY_URL     = f'{OXIGRAPH_BASE}/query'
UPDATE_URL    = f'{OXIGRAPH_BASE}/update'
GRAPH_URI     = URIRef('http://example.org/test-graph')

EX       = 'http://example.org/'
RDF_NS   = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'
RDF_REIF = URIRef(RDF_NS + 'reifies')
EX_CONF  = URIRef(EX + 'confidence')


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _oxigraph_available() -> bool:
    try:
        r = requests.get(OXIGRAPH_BASE, timeout=2)
        return r.status_code == 200
    except Exception:
        return False


oxigraph = pytest.mark.skipif(
    not _oxigraph_available(),
    reason='Oxigraph not running — start with: '
           'docker run -d --name oxigraph-test -p 7878:7878 '
           'ghcr.io/oxigraph/oxigraph serve --location /data --bind 0.0.0.0:7878',
)


def _make_store() -> SPARQLUpdateStore:
    return SPARQLUpdateStore(query_endpoint=QUERY_URL, update_endpoint=UPDATE_URL)


def _clear_graph():
    requests.post(
        UPDATE_URL,
        data=f'CLEAR SILENT GRAPH <{GRAPH_URI}>',
        headers={'Content-Type': 'application/sparql-update'},
        timeout=10,
    ).raise_for_status()


@pytest.fixture
def sg():
    """Fresh StarlightGraph backed by Oxigraph in rdf-1.2 native mode."""
    _clear_graph()
    g = StarlightGraph(store=_make_store(), identifier=GRAPH_URI, backend='rdf-1.2')
    g.bind('ex', EX)
    yield g


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------

@oxigraph
class TestOxigraphRoundTrip:

    def test_plain_triple_write_read(self, sg):
        s, p, o = URIRef(EX+'alice'), URIRef(EX+'knows'), URIRef(EX+'bob')
        sg.add((s, p, o))
        assert (s, p, o) in sg

    def test_triple_term_write_read(self, sg):
        tt   = TripleTerm(URIRef(EX+'alice'), URIRef(EX+'knows'), URIRef(EX+'bob'))
        stmt = URIRef(EX+'stmt1')
        sg.add((stmt, RDF_REIF, tt))
        results = list(sg.triples((stmt, RDF_REIF, None)))
        assert len(results) == 1
        _, _, restored = results[0]
        assert isinstance(restored, TripleTerm)
        assert restored == tt

    def test_triple_term_in_subject_rejected(self, sg):
        """Triple terms in subject position are outside RDF 1.2 and must be rejected."""
        tt = TripleTerm(URIRef(EX+'a'), URIRef(EX+'b'), URIRef(EX+'c'))
        with pytest.raises(ValueError, match='subject position'):
            sg.add((tt, URIRef(EX+'prop'), URIRef(EX+'val')))

    def test_wildcard_triples(self, sg):
        sg.add((URIRef(EX+'s1'), URIRef(EX+'p'), URIRef(EX+'o1')))
        sg.add((URIRef(EX+'s2'), URIRef(EX+'p'), URIRef(EX+'o2')))
        results = list(sg.triples((None, URIRef(EX+'p'), None)))
        assert len(results) == 2

    def test_contains(self, sg):
        s, p, o = URIRef(EX+'alice'), URIRef(EX+'knows'), URIRef(EX+'bob')
        assert (s, p, o) not in sg
        sg.add((s, p, o))
        assert (s, p, o) in sg

    def test_triple_term_as_subject_of_triple_term_rejected(self, sg):
        """A triple term cannot be the subject component of another triple term (RDF 1.2)."""
        inner = TripleTerm(URIRef(EX+'a'), URIRef(EX+'b'), URIRef(EX+'c'))
        with pytest.raises(ValueError, match='subject of a triple term'):
            TripleTerm(inner, URIRef(EX+'says'), URIRef(EX+'d'))

    def test_triple_term_in_object_of_triple_term_allowed(self, sg):
        """A triple term IS allowed in the object position of another triple term."""
        inner = TripleTerm(URIRef(EX+'a'), URIRef(EX+'b'), URIRef(EX+'c'))
        outer = TripleTerm(URIRef(EX+'s'), URIRef(EX+'p'), inner)
        sg.add((URIRef(EX+'stmt'), RDF_REIF, outer))
        results = list(sg.triples((URIRef(EX+'stmt'), RDF_REIF, None)))
        assert len(results) == 1
        restored = results[0][2]
        assert isinstance(restored, TripleTerm)
        assert isinstance(restored.object, TripleTerm)
        assert restored.object == inner

    def test_no_encoding_triples_visible(self, sg):
        """Native rdf-1.2 mode stores no tt:HASH encoding triples."""
        tt = TripleTerm(URIRef(EX+'a'), URIRef(EX+'b'), URIRef(EX+'c'))
        sg.add((URIRef(EX+'stmt'), RDF_REIF, tt))
        predicates = {p for _, p, _ in sg.triples((None, None, None))}
        assert URIRef(RDF_NS + 'subject')   not in predicates
        assert URIRef(RDF_NS + 'predicate') not in predicates
        assert URIRef(RDF_NS + 'object')    not in predicates


# ---------------------------------------------------------------------------
# SPARQL queries — rdf-1.2 syntax passed through unchanged
# ---------------------------------------------------------------------------

@oxigraph
class TestOxigraphSPARQL:

    def _load(self, sg):
        sg.add((URIRef(EX+'stmt1'), RDF_REIF,
                TripleTerm(URIRef(EX+'alice'), URIRef(EX+'knows'), URIRef(EX+'bob'))))
        sg.add((URIRef(EX+'stmt1'), EX_CONF,
                Literal('0.9', datatype=XSD.decimal)))
        sg.add((URIRef(EX+'stmt2'), RDF_REIF,
                TripleTerm(URIRef(EX+'bob'), URIRef(EX+'likes'), URIRef(EX+'carol'))))
        sg.add((URIRef(EX+'stmt2'), EX_CONF,
                Literal('0.4', datatype=XSD.decimal)))

    def test_select_reified_triples(self, sg):
        self._load(sg)
        q = f"""
        PREFIX ex: <{EX}>
        PREFIX rdf: <{RDF_NS}>
        SELECT ?stmt ?tt WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?stmt rdf:reifies ?tt .
            }}
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
        PREFIX rdf: <{RDF_NS}>
        SELECT ?tt WHERE {{
            GRAPH <{GRAPH_URI}> {{
                <{EX}stmt1> rdf:reifies ?tt .
            }}
        }}
        """
        rows = list(sg.query(q))
        assert len(rows) == 1
        assert isinstance(rows[0][0], TripleTerm)
        assert rows[0][0] == TripleTerm(
            URIRef(EX+'alice'), URIRef(EX+'knows'), URIRef(EX+'bob')
        )

    def test_sparql12_triple_term_pattern(self, sg):
        """SPARQL 1.2 <<( )>> syntax is sent directly to Oxigraph unchanged."""
        self._load(sg)
        q = f"""
        PREFIX ex: <{EX}>
        PREFIX rdf: <{RDF_NS}>
        SELECT ?stmt ?s ?o WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?stmt rdf:reifies <<( ?s ex:knows ?o )>> .
            }}
        }}
        """
        rows = list(sg.query(q))
        assert len(rows) == 1
        assert rows[0][1] == URIRef(EX+'alice')
        assert rows[0][2] == URIRef(EX+'bob')

    def test_filter_by_confidence(self, sg):
        self._load(sg)
        q = f"""
        PREFIX ex: <{EX}>
        PREFIX rdf: <{RDF_NS}>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        SELECT ?stmt WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?stmt rdf:reifies <<( ?s ?p ?o )>> .
                ?stmt ex:confidence ?conf .
                FILTER(xsd:decimal(?conf) > 0.5)
            }}
        }}
        """
        rows = list(sg.query(q))
        assert len(rows) == 1
        assert rows[0][0] == URIRef(EX+'stmt1')

    def test_ask_query(self, sg):
        sg.add((URIRef(EX+'alice'), URIRef(EX+'knows'), URIRef(EX+'bob')))
        q = f'ASK {{ GRAPH <{GRAPH_URI}> {{ <{EX}alice> <{EX}knows> <{EX}bob> . }} }}'
        r = sg.query(q)
        assert r.askAnswer is True

    def test_12_syntax_not_rewritten(self, sg):
        """Verify <<( )>> is NOT rewritten to << >> for rdf-1.2 mode."""
        from starlight.backends.native import rewrite_12_to_backend
        original = 'SELECT ?x WHERE { ?x rdf:reifies <<( ex:a ex:b ex:c )>> . }'
        result   = rewrite_12_to_backend(original, 'rdf-1.2')
        assert result == original
