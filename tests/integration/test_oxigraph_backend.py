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

from starlight.graph import StarlightGraph, StarlightDataset
from starlight.model.triple import TripleTerm

# See test_fuseki_backend.py's identical pytestmark for why this is here.
pytestmark = pytest.mark.integration

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


@oxigraph
class TestOxigraphTurtle12Parse:
    """.parse(format='turtle12'/'trig12') on a native-backend graph used to
    write the rdf-1.1 backend's own tt:HASH skolemized encoding fragments
    directly into the store (StarlightGraph.parse()'s turtle12/trig12
    branches called super().add(triple), bypassing the backend-aware
    StarlightGraph.add() override that routes to _native_add()) - so a
    triple term parsed from text (as opposed to added via the .add()
    Python API, which was never affected) came back from .triples() as
    the raw rdf:subject/predicate/object encoding-triple fragments
    instead of a real TripleTerm object, and rdf:reifies lookups against
    such data never matched anything real. Confirmed to affect both
    simple and nested triple terms, and to break starShacl's
    sh:reifierShape/sh:reificationRequired end to end (the discovery
    path). Fixed by decoding the skolemized encoding back into real
    TripleTerm objects (turtle_parser.decode_tt_encoded_triples) before
    writing native-backend data, so it goes through self.add() ->
    _native_add() instead.
    """

    def test_simple_triple_term_decodes_correctly(self, sg):
        sg.parse(data='''
            @prefix ex: <http://example.org/> .
            ex:alice ex:says <<( ex:bob ex:knows ex:carol )>> .
        ''', format='turtle12')
        results = list(sg.triples((URIRef(EX + 'alice'), URIRef(EX + 'says'), None)))
        assert len(results) == 1
        restored = results[0][2]
        assert isinstance(restored, TripleTerm)
        assert restored == TripleTerm(URIRef(EX + 'bob'), URIRef(EX + 'knows'), URIRef(EX + 'carol'))

    def test_nested_triple_term_decodes_correctly(self, sg):
        sg.parse(data='''
            @prefix ex: <http://example.org/> .
            @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
            ex:reifier1 rdf:reifies <<( ex:stmt1 ex:claim <<( ex:bob ex:knows ex:carol )>> )>> .
        ''', format='turtle12')
        results = list(sg.triples((URIRef(EX + 'reifier1'), RDF_REIF, None)))
        assert len(results) == 1
        restored = results[0][2]
        assert isinstance(restored, TripleTerm)
        assert isinstance(restored.object, TripleTerm)
        assert restored == TripleTerm(
            URIRef(EX + 'stmt1'), URIRef(EX + 'claim'),
            TripleTerm(URIRef(EX + 'bob'), URIRef(EX + 'knows'), URIRef(EX + 'carol')),
        )

    def test_no_encoding_triples_visible_after_parse(self, sg):
        sg.parse(data='''
            @prefix ex: <http://example.org/> .
            @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
            ex:reifier1 rdf:reifies <<( ex:stmt1 ex:claim <<( ex:bob ex:knows ex:carol )>> )>> .
        ''', format='turtle12')
        predicates = {p for _, p, _ in sg.triples((None, None, None))}
        assert URIRef(RDF_NS + 'subject')   not in predicates
        assert URIRef(RDF_NS + 'predicate') not in predicates
        assert URIRef(RDF_NS + 'object')    not in predicates

    def test_rdf_reifies_lookup_matches_parsed_data(self, sg):
        """The end-to-end scenario that surfaced this bug: a shape checking
        for reifiers of a statement-level triple must actually find them
        when the data was loaded via .parse(), not just via .add()."""
        sg.parse(data='''
            @prefix ex: <http://example.org/> .
            @prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
            ex:stmt1 ex:claim <<( ex:bob ex:knows ex:carol )>> .
            ex:reifier1 rdf:reifies <<( ex:stmt1 ex:claim <<( ex:bob ex:knows ex:carol )>> )>> ;
              ex:confidence "0.9" .
        ''', format='turtle12')
        target = TripleTerm(
            URIRef(EX + 'stmt1'), URIRef(EX + 'claim'),
            TripleTerm(URIRef(EX + 'bob'), URIRef(EX + 'knows'), URIRef(EX + 'carol')),
        )
        reifiers = [s for s, _, o in sg.triples((None, RDF_REIF, None)) if o == target]
        assert reifiers == [URIRef(EX + 'reifier1')]

    def test_trig12_parse_decodes_correctly(self, sg):
        sg.parse(data='''
            @prefix ex: <http://example.org/> .
            GRAPH ex:g1 { ex:alice ex:says <<( ex:bob ex:knows ex:carol )>> . }
        ''', format='trig12')
        results = list(sg.triples((URIRef(EX + 'alice'), URIRef(EX + 'says'), None)))
        assert len(results) == 1
        restored = results[0][2]
        assert isinstance(restored, TripleTerm)
        assert restored == TripleTerm(URIRef(EX + 'bob'), URIRef(EX + 'knows'), URIRef(EX + 'carol'))


@oxigraph
class TestOxigraphDatasetTrig12Parse:
    """StarlightDataset.parse(format='trig12') had the same bug as
    StarlightGraph.parse() above (see TestOxigraphTurtle12Parse), but in a
    separate code path: it called the module-level ``_raw_graph_add``
    (rdflib's base ``Graph.add()``) unconditionally, regardless of backend,
    instead of dispatching through the per-context StarlightGraph's
    backend-aware ``.add()``. Same fix applied: on a native-backend context,
    decode the parser's tt:HASH encoding back into real TripleTerm objects
    before writing, so it goes through ``_native_add()``.
    """

    def _dataset(self):
        _clear_graph()
        store = _make_store()
        return StarlightDataset(store=store, backend='rdf-1.2')

    def test_named_graph_triple_term_decodes_correctly(self):
        ds = self._dataset()
        ds.parse(data=f'''
            @prefix ex: <{EX}> .
            GRAPH <{GRAPH_URI}> {{ ex:alice ex:says <<( ex:bob ex:knows ex:carol )>> . }}
        ''', format='trig12')
        g1 = ds.get_context(GRAPH_URI)
        results = list(g1.triples((URIRef(EX + 'alice'), URIRef(EX + 'says'), None)))
        assert len(results) == 1
        restored = results[0][2]
        assert isinstance(restored, TripleTerm)
        assert restored == TripleTerm(URIRef(EX + 'bob'), URIRef(EX + 'knows'), URIRef(EX + 'carol'))

    def test_no_encoding_triples_visible_after_parse(self):
        ds = self._dataset()
        ds.parse(data=f'''
            @prefix ex: <{EX}> .
            @prefix rdf: <{RDF_NS}> .
            GRAPH <{GRAPH_URI}> {{
                ex:reifier1 rdf:reifies <<( ex:stmt1 ex:claim <<( ex:bob ex:knows ex:carol )>> )>> .
            }}
        ''', format='trig12')
        g1 = ds.get_context(GRAPH_URI)
        predicates = {p for _, p, _ in g1.triples((None, None, None))}
        assert URIRef(RDF_NS + 'subject')   not in predicates
        assert URIRef(RDF_NS + 'predicate') not in predicates
        assert URIRef(RDF_NS + 'object')    not in predicates


@oxigraph
class TestOxigraphDatasetQuery:
    """StarlightDataset.query() had no native-backend dispatch at all: unlike
    StarlightGraph.query() (which routed to its own native-only query logic
    for self._is_native), it always queried a plain in-memory copy built by
    _build_raw_execution_graph(). That copy is built via rdflib's base
    Graph.triples(), which for a native-backend context runs a plain SPARQL
    1.1 SELECT ?s ?p ?o against the remote store and cannot represent a
    "type":"triple" binding - so any dataset query whose result contained a
    triple-term-valued binding crashed with
    TypeError: unknown binding type. Fixed by giving StarlightDataset and
    StarlightGraph a shared starlight.backends.native.native_query() (a
    native-backed dataset's contexts all share one store, so this is exactly
    the same underlying HTTP operation for both).
    """

    def _dataset(self):
        _clear_graph()
        store = _make_store()
        return StarlightDataset(store=store, backend='rdf-1.2')

    def test_select_with_triple_term_binding(self):
        ds = self._dataset()
        g1 = ds.get_context(GRAPH_URI)
        tt = TripleTerm(URIRef(EX+'alice'), URIRef(EX+'knows'), URIRef(EX+'bob'))
        g1.add((URIRef(EX+'stmt1'), RDF_REIF, tt))

        q = f"""
        PREFIX rdf: <{RDF_NS}>
        SELECT ?tt WHERE {{
            GRAPH <{GRAPH_URI}> {{ <{EX}stmt1> rdf:reifies ?tt }}
        }}
        """
        rows = list(ds.query(q))
        assert len(rows) == 1
        assert isinstance(rows[0][0], TripleTerm)
        assert rows[0][0] == tt

    def test_ask(self):
        ds = self._dataset()
        g1 = ds.get_context(GRAPH_URI)
        g1.add((URIRef(EX+'a'), URIRef(EX+'b'), URIRef(EX+'c')))
        r = ds.query(f'ASK {{ GRAPH <{GRAPH_URI}> {{ ?s ?p ?o }} }}')
        assert r.askAnswer is True

    def test_construct_restores_triple_terms(self):
        ds = self._dataset()
        g1 = ds.get_context(GRAPH_URI)
        tt = TripleTerm(URIRef(EX+'alice'), URIRef(EX+'knows'), URIRef(EX+'bob'))
        g1.add((URIRef(EX+'stmt1'), RDF_REIF, tt))

        q = f"""
        PREFIX rdf: <{RDF_NS}>
        CONSTRUCT {{ ?s rdf:reifies ?tt }} WHERE {{
            GRAPH <{GRAPH_URI}> {{ ?s rdf:reifies ?tt }}
        }}
        """
        r = ds.query(q)
        results = list(r.graph.triples((None, RDF_REIF, None)))
        assert len(results) == 1
        assert results[0][2] == tt


@oxigraph
class TestOxigraphDatasetUpdate:
    """StarlightDataset.update() against a remote store 400'd on any update
    text containing its own ``GRAPH <uri> { }`` clause - the normal way to
    target a named graph from dataset-level SPARQL - because rdflib's own
    ``Dataset(store=...).update()`` always wraps the whole update in an
    extra ``GRAPH <urn:x-rdflib:default> { }`` block (SPARQLStore's
    ``_is_contextual()`` doesn't recognize ``Dataset``'s default-graph
    sentinel as exempt), producing an illegal nested GRAPH block. Confirmed
    against real Oxigraph with a plain (no triple terms) INSERT DATA.  Fixed
    by bypassing rdflib's dispatch and sending the update over HTTP directly
    for any store with query/update endpoints - same as
    StarlightGraph.update()'s existing native-backend path.
    """

    def _dataset(self):
        _clear_graph()
        store = _make_store()
        return StarlightDataset(store=store, backend='rdf-1.2')

    def test_insert_data_with_graph_clause(self):
        ds = self._dataset()
        ds.update(f'INSERT DATA {{ GRAPH <{GRAPH_URI}> {{ <{EX}a> <{EX}b> <{EX}c> . }} }}')
        g1 = ds.get_context(GRAPH_URI)
        assert (URIRef(EX+'a'), URIRef(EX+'b'), URIRef(EX+'c')) in g1

    def test_insert_where_with_graph_clause(self):
        ds = self._dataset()
        g1 = ds.get_context(GRAPH_URI)
        g1.add((URIRef(EX+'a'), URIRef(EX+'b'), URIRef(EX+'c')))
        ds.update(f"""
            INSERT {{ GRAPH <{GRAPH_URI}> {{ ?s <{EX}marked> ?o }} }}
            WHERE {{ GRAPH <{GRAPH_URI}> {{ ?s <{EX}b> ?o }} }}
        """)
        assert (URIRef(EX+'a'), URIRef(EX+'marked'), URIRef(EX+'c')) in g1


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

    def test_12_syntax_passed_through_unchanged(self, sg):
        """<<( )>> SPARQL 1.2 syntax goes straight to Oxigraph - no rewriting layer."""
        sg.add((URIRef(EX+'stmt'), RDF_REIF, TripleTerm(URIRef(EX+'a'), URIRef(EX+'b'), URIRef(EX+'c'))))
        q = f"""
        PREFIX ex: <{EX}>
        PREFIX rdf: <{RDF_NS}>
        SELECT ?x WHERE {{
            GRAPH <{GRAPH_URI}> {{
                ?x rdf:reifies <<( ex:a ex:b ex:c )>> .
            }}
        }}
        """
        rows = list(sg.query(q))
        assert len(rows) == 1
        assert rows[0][0] == URIRef(EX+'stmt')


# ---------------------------------------------------------------------------
# TRIPLE()/isTRIPLE() and the RDF 1.2 base-direction SPARQL functions,
# passed through unchanged to Oxigraph - confirmed 2026-07-16, Oxigraph 0.5.9
# natively supports all of them.
# ---------------------------------------------------------------------------

@oxigraph
class TestOxigraphRdf12SparqlFunctions:

    def test_triple_constructor_function(self, sg):
        r = sg.query(f"""
            SELECT (TRIPLE(<{EX}a>, <{EX}b>, <{EX}c>) AS ?t) WHERE {{}}
        """)
        assert r.bindings[0][r.vars[0]] == TripleTerm(URIRef(EX+'a'), URIRef(EX+'b'), URIRef(EX+'c'))

    def test_is_triple_spec_name(self, sg):
        r = sg.query(f"""
            SELECT (isTRIPLE(TRIPLE(<{EX}a>, <{EX}b>, <{EX}c>)) AS ?v) WHERE {{}}
        """)
        assert r.bindings[0][r.vars[0]] == Literal(True)

    def test_dirlangstring_write_read(self, sg):
        from starlight.model.dirlangstring import DirLangString
        d = DirLangString('hello', 'en', 'rtl')
        sg.add((URIRef(EX+'s'), URIRef(EX+'p'), d))
        results = list(sg.triples((URIRef(EX+'s'), URIRef(EX+'p'), None)))
        assert results == [(URIRef(EX+'s'), URIRef(EX+'p'), d)]

    def test_dirlangstring_construct_round_trip(self, sg):
        from starlight.model.dirlangstring import DirLangString
        d = DirLangString('hola', 'es', 'ltr')
        sg.add((URIRef(EX+'s'), URIRef(EX+'p'), d))
        r = sg.query(f'CONSTRUCT {{ ?s ?p ?o }} WHERE {{ GRAPH <{GRAPH_URI}> {{ ?s ?p ?o }} }}')
        assert (URIRef(EX+'s'), URIRef(EX+'p'), d) in r.graph

    def test_langdir_hasLangdir_strlangdir(self, sg):
        r = sg.query("""
            SELECT (LANGDIR("hi"@en--rtl) AS ?dir)
                   (hasLANGDIR("hi"@en--rtl) AS ?hd)
                   (STRLANGDIR("hi", "en", "ltr") AS ?sld)
                   (LANG("hi"@en--rtl) AS ?l)
                   (hasLANG("hi"@en--rtl) AS ?hl)
            WHERE {}
        """)
        from starlight.model.dirlangstring import DirLangString
        row = r.bindings[0]
        assert row[r.vars[0]] == Literal('rtl')
        assert row[r.vars[1]] == Literal(True)
        assert row[r.vars[2]] == DirLangString('hi', 'en', 'ltr')
        assert row[r.vars[3]] == Literal('en')
        assert row[r.vars[4]] == Literal(True)
