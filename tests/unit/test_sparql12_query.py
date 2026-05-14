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

<< :bob :knows :carol >> :verifiedBy :ResearchTeam .
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
        assert len(stmts) == 3  # stmt1 (named) + anon from {| |} + anon from << >>

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
        # << >> (reification shorthand) in SPARQL subject position matches via reifier
        r = g.query("""
            PREFIX :   <http://example.org/>
            SELECT ?who WHERE {
              << :bob :knows :carol >> :verifiedBy ?who .
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
        assert len(r.bindings) == 3  # stmt1 + anon from {| |} + anon from << >>


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

    def test_tt_str_uses_prefixed_names(self, g):
        r = g.query("""
            PREFIX :   <http://example.org/>
            SELECT ?who ?tt WHERE {
              ?who :says ?tt .
            }
        """)
        tt = r.bindings[0][r.vars[1]]
        assert str(tt) == '<<( :bob :knows :carol )>>'

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
# Q7 — SUBJECT / PREDICATE / OBJECT functions
# ---------------------------------------------------------------------------

class TestQ7:
    def test_subject_predicate_object_all_components(self, g):
        r = g.query("""
            PREFIX :   <http://example.org/>
            SELECT ?who (SUBJECT(?tt) AS ?knower) (PREDICATE(?tt) AS ?rel) (OBJECT(?tt) AS ?known) WHERE {
              ?who :says ?tt .
            }
        """)
        assert len(r.bindings) == 1
        row = r.bindings[0]
        knower = row[r.vars[1]]
        rel    = row[r.vars[2]]
        known  = row[r.vars[3]]
        assert knower == URIRef(EX + 'bob')
        assert rel    == URIRef(EX + 'knows')
        assert known  == URIRef(EX + 'carol')

    def test_subject_only(self, g):
        r = g.query("""
            PREFIX :   <http://example.org/>
            SELECT ?who (SUBJECT(?tt) AS ?knower) WHERE {
              ?who :says ?tt .
            }
        """)
        assert r.bindings[0][r.vars[1]] == URIRef(EX + 'bob')


# ---------------------------------------------------------------------------
# Q8 — Annotation patterns
# ---------------------------------------------------------------------------

class TestQ8:
    def test_annotation_subject_all_annotations(self, g):
        r = g.query("""
            PREFIX :   <http://example.org/>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?s ?p ?o ?pred ?val WHERE {
              << ?s ?p ?o >> ?pred ?val .
              FILTER(?pred != rdf:reifies)
            }
        """)
        pred_var, val_var = r.vars[3], r.vars[4]
        preds = {row[pred_var] for row in r.bindings}
        assert URIRef(EX + 'since')      in preds
        assert URIRef(EX + 'via')        in preds
        assert URIRef(EX + 'confidence') in preds
        assert URIRef(EX + 'source')     in preds

    def test_annotation_subject_base_triple_bound(self, g):
        r = g.query("""
            PREFIX :   <http://example.org/>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT DISTINCT ?s ?p ?o WHERE {
              << ?s ?p ?o >> ?pred ?val .
            }
        """)
        assert len(r.bindings) == 1
        row = r.bindings[0]
        assert row[r.vars[0]] == URIRef(EX + 'bob')
        assert row[r.vars[1]] == URIRef(EX + 'knows')
        assert row[r.vars[2]] == URIRef(EX + 'carol')

    def test_inline_annotation_block(self, g):
        r = g.query("""
            PREFIX :   <http://example.org/>
            SELECT ?since WHERE {
              :bob :knows :carol {| :since ?since |} .
            }
        """)
        assert len(r.bindings) == 1
        assert r.bindings[0][r.vars[0]] == Literal('2020')

    def test_tilde_reifier_binding(self, g):
        r = g.query("""
            PREFIX :   <http://example.org/>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?r ?pred ?val WHERE {
              :bob :knows :carol ~ ?r .
              ?r ?pred ?val .
              FILTER(?pred != rdf:reifies)
            }
        """)
        assert len(r.bindings) == 5  # 2 from stmt1 + 2 from {| |} + 1 from << >> reifier
        preds = {row[r.vars[1]] for row in r.bindings}
        assert URIRef(EX + 'since')       in preds
        assert URIRef(EX + 'via')         in preds
        assert URIRef(EX + 'confidence')  in preds
        assert URIRef(EX + 'source')      in preds
        assert URIRef(EX + 'verifiedBy')  in preds


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
        assert len(r.bindings) == 3  # stmt1 + anon from {| |} + anon from << >>


# ---------------------------------------------------------------------------
# Q11 — ASK with triple term
# ---------------------------------------------------------------------------

class TestQ11:
    def test_ask_true(self, g):
        # << >> (reification shorthand) in SPARQL matches via reifier of the triple
        r = g.query("""
            PREFIX :   <http://example.org/>
            ASK {
              << :bob :knows :carol >> :verifiedBy :ResearchTeam .
            }
        """)
        assert r.askAnswer is True

    def test_ask_false(self, g):
        r = g.query("""
            PREFIX :   <http://example.org/>
            ASK {
              << :bob :knows :carol >> :verifiedBy :nobody .
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

    def test_construct_always_starlight_graph_no_tt(self, g):
        r = g.query("""
            PREFIX :   <http://example.org/>
            CONSTRUCT { :a :b :c . }
            WHERE { :alice :says ?tt . }
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


# ---------------------------------------------------------------------------
# Q13 — isTripleTerm and assertion check
# ---------------------------------------------------------------------------

class TestQ13:
    def test_is_triple_term_finds_tt(self, g):
        r = g.query("""
            PREFIX :   <http://example.org/>
            SELECT DISTINCT ?tt WHERE {
              { ?s ?p ?tt } UNION { ?tt ?p ?o }
              FILTER(isTripleTerm(?tt))
            }
        """)
        tts = [row[r.vars[0]] for row in r.bindings]
        assert len(tts) == 1
        assert isinstance(tts[0], TripleTerm)

    def test_bind_components_via_subject_predicate_object(self, g):
        r = g.query("""
            PREFIX :   <http://example.org/>
            SELECT DISTINCT ?tt ?s ?p ?o WHERE {
              { ?sub ?pred ?tt } UNION { ?tt ?pred ?obj }
              FILTER(isTripleTerm(?tt))
              BIND(SUBJECT(?tt) AS ?s)
              BIND(PREDICATE(?tt) AS ?p)
              BIND(OBJECT(?tt) AS ?o)
            }
        """)
        assert len(r.bindings) == 1
        row = r.bindings[0]
        assert isinstance(row[r.vars[0]], TripleTerm)
        assert row[r.vars[1]] == URIRef(EX + 'bob')
        assert row[r.vars[2]] == URIRef(EX + 'knows')
        assert row[r.vars[3]] == URIRef(EX + 'carol')

    def test_assertion_check_via_ask(self, g):
        # The base triple :bob :knows :carol is asserted (via {| |} annotation)
        r = g.query("""
            PREFIX :   <http://example.org/>
            SELECT DISTINCT ?tt ?s ?p ?o WHERE {
              { ?sub ?pred ?tt } UNION { ?tt ?pred ?obj }
              FILTER(isTripleTerm(?tt))
              BIND(SUBJECT(?tt) AS ?s)
              BIND(PREDICATE(?tt) AS ?p)
              BIND(OBJECT(?tt) AS ?o)
              ?s ?p ?o .
            }
        """)
        assert len(r.bindings) == 1


# ---------------------------------------------------------------------------
# Q14 — CONSTRUCT with <<( )>> in template and WHERE clause
# ---------------------------------------------------------------------------

class TestQ14:
    def test_construct_triple_term_same_variable(self, g):
        # <<( ?s ?p ?o )>> in the CONSTRUCT template must get the same variable
        # as the same pattern in WHERE. Before the content-based variable fix,
        # the rewriter assigned different sequential variables to each block,
        # so the CONSTRUCT template's encoding triples were never bound and the
        # result graph contained no reification triples.
        r = g.query("""
            PREFIX :   <http://example.org/>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            CONSTRUCT {
              ?s ?p ?o .
              ?stmt rdf:reifies <<( ?s ?p ?o )>> .
              ?stmt ?attr ?val .
            } WHERE {
              ?stmt rdf:reifies <<( ?s ?p ?o )>> .
              ?stmt ?attr ?val .
              FILTER(?attr != rdf:reifies)
            }
        """)
        assert isinstance(r.graph, StarlightGraph)
        RDF_REIFIES = URIRef('http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies')
        reifies_triples = list(r.graph.triples((None, RDF_REIFIES, None)))
        assert len(reifies_triples) >= 1, "CONSTRUCT result must contain rdf:reifies triple"
        _, _, obj = reifies_triples[0]
        assert isinstance(obj, TripleTerm), f"Object of rdf:reifies must be TripleTerm, got {type(obj)}"
        assert obj == TripleTerm(URIRef(EX + 'bob'), URIRef(EX + 'knows'), URIRef(EX + 'carol'))

    def test_construct_triple_term_serializable(self, g):
        r = g.query("""
            PREFIX :   <http://example.org/>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            CONSTRUCT {
              ?stmt rdf:reifies <<( :bob :knows :carol )>> .
              ?stmt ?attr ?val .
            } WHERE {
              ?stmt rdf:reifies <<( :bob :knows :carol )>> .
              ?stmt ?attr ?val .
              FILTER(?attr != rdf:reifies)
            }
        """)
        ttl = r.graph.serialize(format='turtle12')
        assert '<<(' in ttl or 'reifies' in ttl
