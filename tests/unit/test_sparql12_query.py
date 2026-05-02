"""
Integration tests for StarlightGraph.query() with SPARQL 1.2 triple-term syntax.

Each test class corresponds to one query example from sparql12_design.md.
The shared dataset matches the one defined at the top of that document.
"""

import pytest
from rdflib import URIRef, Literal
from rdflib.namespace import RDF

from starlight.graph.starlight_graph import StarlightGraph
from starlight.model.triple import TripleTerm

EX = 'http://example.org/'

DATASET = """
@prefix :    <http://example.org/> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

:alice :says <<( :bob :knows :carol )>> .

:stmt1 rdf:reifies <<( :bob :knows :carol )>> ;
       :confidence "0.9" ;
       :source :WikiData .

:bob :knows :carol {| :since "2020" ; :via :LinkedIn |} .

<<( :bob :knows :carol )>> :verifiedBy :ResearchTeam .
"""


@pytest.fixture
def g():
    sg = StarlightGraph()
    sg.parse(data=DATASET, format='turtle12')
    return sg


def _uris(rows, var):
    return {row[var] for row in rows}


# ---------------------------------------------------------------------------
# Q1 — Triple term in object position (reification)
# ---------------------------------------------------------------------------

class TestQ1:
    def test_finds_named_reifier(self, g):
        r = g.query("""
            PREFIX :   <http://example.org/>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?stmt WHERE {
              ?stmt rdf:reifies <<( :bob :knows :carol )>> .
            }
        """)
        stmts = _uris(r.bindings, r.vars[0])
        assert URIRef(EX + 'stmt1') in stmts

    def test_finds_anonymous_reifier(self, g):
        r = g.query("""
            PREFIX :   <http://example.org/>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?stmt WHERE {
              ?stmt rdf:reifies <<( :bob :knows :carol )>> .
            }
        """)
        stmts = _uris(r.bindings, r.vars[0])
        assert len(stmts) == 2

    def test_no_result_for_unknown_triple_term(self, g):
        r = g.query("""
            PREFIX :   <http://example.org/>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?stmt WHERE {
              ?stmt rdf:reifies <<( :x :y :z )>> .
            }
        """)
        assert r.bindings == []


# ---------------------------------------------------------------------------
# Q2 — Triple term as subject
# ---------------------------------------------------------------------------

class TestQ2:
    def test_triple_term_as_subject(self, g):
        r = g.query("""
            PREFIX :   <http://example.org/>
            SELECT ?who WHERE {
              <<( :bob :knows :carol )>> :verifiedBy ?who .
            }
        """)
        who = {row[r.vars[0]] for row in r.bindings}
        assert who == {URIRef(EX + 'ResearchTeam')}


# ---------------------------------------------------------------------------
# Q3 — Triple term in object position (non-reification)
# ---------------------------------------------------------------------------

class TestQ3:
    def test_triple_term_as_object(self, g):
        r = g.query("""
            PREFIX :   <http://example.org/>
            SELECT ?who WHERE {
              ?who :says <<( :bob :knows :carol )>> .
            }
        """)
        who = {row[r.vars[0]] for row in r.bindings}
        assert who == {URIRef(EX + 'alice')}


# ---------------------------------------------------------------------------
# Q4 — Variable triple term components
# ---------------------------------------------------------------------------

class TestQ4:
    def test_variable_components_bind_correctly(self, g):
        r = g.query("""
            PREFIX :   <http://example.org/>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?stmt ?s ?p ?o WHERE {
              ?stmt rdf:reifies <<( ?s ?p ?o )>> .
            }
        """)
        s_var, p_var, o_var = r.vars[1], r.vars[2], r.vars[3]
        for row in r.bindings:
            assert row[s_var] == URIRef(EX + 'bob')
            assert row[p_var] == URIRef(EX + 'knows')
            assert row[o_var] == URIRef(EX + 'carol')

    def test_two_reifiers_returned(self, g):
        r = g.query("""
            PREFIX :   <http://example.org/>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?stmt ?s ?p ?o WHERE {
              ?stmt rdf:reifies <<( ?s ?p ?o )>> .
            }
        """)
        assert len(r.bindings) == 2


# ---------------------------------------------------------------------------
# Q5 — OPTIONAL annotations on a reifier
# ---------------------------------------------------------------------------

class TestQ5:
    def test_named_reifier_has_confidence(self, g):
        r = g.query("""
            PREFIX :   <http://example.org/>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?stmt ?conf ?source WHERE {
              ?stmt rdf:reifies <<( :bob :knows :carol )>> .
              OPTIONAL { ?stmt :confidence ?conf . }
              OPTIONAL { ?stmt :source ?source . }
            }
        """)
        stmt_var, conf_var, src_var = r.vars[0], r.vars[1], r.vars[2]
        by_stmt = {row[stmt_var]: row for row in r.bindings}
        stmt1 = by_stmt[URIRef(EX + 'stmt1')]
        assert stmt1[conf_var] == Literal('0.9')
        assert stmt1[src_var] == URIRef(EX + 'WikiData')

    def test_anonymous_reifier_has_no_confidence(self, g):
        r = g.query("""
            PREFIX :   <http://example.org/>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?stmt ?conf WHERE {
              ?stmt rdf:reifies <<( :bob :knows :carol )>> .
              OPTIONAL { ?stmt :confidence ?conf . }
            }
        """)
        stmt_var, conf_var = r.vars[0], r.vars[1]
        stmt1_rows = [row for row in r.bindings if row[stmt_var] == URIRef(EX + 'stmt1')]
        anon_rows  = [row for row in r.bindings if row[stmt_var] != URIRef(EX + 'stmt1')]
        assert stmt1_rows[0][conf_var] == Literal('0.9')
        assert anon_rows[0][conf_var] is None


# ---------------------------------------------------------------------------
# Q6 — Triple term selected as a variable (post-processing)
# ---------------------------------------------------------------------------

class TestQ6:
    def test_tt_restored_to_triple_term_object(self, g):
        r = g.query("""
            PREFIX :   <http://example.org/>
            SELECT ?who ?tt WHERE {
              ?who :says ?tt .
            }
        """)
        tt_var = r.vars[1]
        tt = r.bindings[0][tt_var]
        assert isinstance(tt, TripleTerm)

    def test_tt_components_correct(self, g):
        r = g.query("""
            PREFIX :   <http://example.org/>
            SELECT ?who ?tt WHERE {
              ?who :says ?tt .
            }
        """)
        tt = r.bindings[0][r.vars[1]]
        assert tt.subject   == URIRef(EX + 'bob')
        assert tt.predicate == URIRef(EX + 'knows')
        assert tt.object    == URIRef(EX + 'carol')


# ---------------------------------------------------------------------------
# Q10 — Reifier and triple term as a unit
# ---------------------------------------------------------------------------

class TestQ10:
    def test_tt_in_object_position_restored(self, g):
        r = g.query("""
            PREFIX :   <http://example.org/>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?stmt ?tt WHERE {
              ?stmt rdf:reifies ?tt .
            }
        """)
        tt_var = r.vars[1]
        tts = {row[tt_var] for row in r.bindings}
        assert len(tts) == 1
        tt = next(iter(tts))
        assert isinstance(tt, TripleTerm)
        assert tt == TripleTerm(URIRef(EX+'bob'), URIRef(EX+'knows'), URIRef(EX+'carol'))

    def test_two_reifiers_one_triple_term(self, g):
        r = g.query("""
            PREFIX :   <http://example.org/>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?stmt ?tt WHERE {
              ?stmt rdf:reifies ?tt .
            }
        """)
        assert len(r.bindings) == 2


# ---------------------------------------------------------------------------
# Q11 — ASK with triple term
# ---------------------------------------------------------------------------

class TestQ11:
    def test_ask_true(self, g):
        r = g.query("""
            PREFIX :   <http://example.org/>
            ASK {
              <<( :bob :knows :carol )>> :verifiedBy :ResearchTeam .
            }
        """)
        assert r.askAnswer is True

    def test_ask_false(self, g):
        r = g.query("""
            PREFIX :   <http://example.org/>
            ASK {
              <<( :bob :knows :carol )>> :verifiedBy :nobody .
            }
        """)
        assert r.askAnswer is False


# ---------------------------------------------------------------------------
# Q12 — CONSTRUCT returns a StarlightGraph
# ---------------------------------------------------------------------------

class TestQ12:
    def test_construct_returns_starlight_graph(self, g):
        r = g.query("""
            PREFIX :   <http://example.org/>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            CONSTRUCT { ?stmt :hasConfidence ?conf . }
            WHERE {
              ?stmt rdf:reifies <<( :bob :knows :carol )>> .
              ?stmt :confidence ?conf .
            }
        """)
        assert isinstance(r.graph, StarlightGraph)

    def test_construct_plain_triple_content(self, g):
        r = g.query("""
            PREFIX :   <http://example.org/>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            CONSTRUCT { ?stmt :hasConfidence ?conf . }
            WHERE {
              ?stmt rdf:reifies <<( :bob :knows :carol )>> .
              ?stmt :confidence ?conf .
            }
        """)
        triples = list(r.graph.triples((None, URIRef(EX+'hasConfidence'), None)))
        assert len(triples) == 1
        s, _, o = triples[0]
        assert s == URIRef(EX + 'stmt1')
        assert o == Literal('0.9')
