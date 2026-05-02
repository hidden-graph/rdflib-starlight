"""
Unit tests for starlight.graph.StarlightGraph.

Covers: rdflib compatibility, TripleTerm add/query, filtering of internal
encoding triples, from_rdflib(), and Statement operations.
"""

import pytest
from rdflib import Graph, URIRef, Literal, BNode
from rdflib.namespace import RDF

from starlight.graph.starlight_graph import StarlightGraph, RDF_REIFIES
from starlight.model.triple import TripleTerm

EX = 'http://example.org/'


@pytest.fixture
def sg():
    return StarlightGraph()


# ---------------------------------------------------------------------------
# rdflib compatibility
# ---------------------------------------------------------------------------

class TestRdflibCompat:
    def test_isinstance_rdflib_graph(self, sg):
        assert isinstance(sg, Graph)

    def test_add_plain_triple(self, sg):
        sg.add((URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o')))
        assert (URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o')) in sg

    def test_add_three_args(self, sg):
        sg.add(URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o'))
        assert (URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o')) in sg

    def test_add_literal_object(self, sg):
        sg.add((URIRef(EX+'s'), URIRef(EX+'p'), Literal('hello')))
        objs = list(sg.objects(URIRef(EX+'s'), URIRef(EX+'p')))
        assert Literal('hello') in objs

    def test_len_counts_only_user_triples(self, sg):
        sg.add((URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o')))
        sg.add((URIRef(EX+'a'), URIRef(EX+'b'), URIRef(EX+'c')))
        assert len(sg) == 2

    def test_remove_triple(self, sg):
        sg.add((URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o')))
        sg.remove((URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o')))
        assert (URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o')) not in sg

    def test_triples_wildcard(self, sg):
        sg.add((URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o')))
        results = list(sg.triples((None, None, None)))
        assert len(results) == 1

    def test_subjects_method(self, sg):
        sg.add((URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o')))
        subs = list(sg.subjects(URIRef(EX+'p'), URIRef(EX+'o')))
        assert URIRef(EX+'s') in subs

    def test_objects_method(self, sg):
        sg.add((URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o')))
        objs = list(sg.objects(URIRef(EX+'s'), URIRef(EX+'p')))
        assert URIRef(EX+'o') in objs


# ---------------------------------------------------------------------------
# TripleTerm in add / triples / __contains__
# ---------------------------------------------------------------------------

class TestTripleTermAdd:
    def test_add_tt_object_as_tuple(self, sg):
        sg.add((URIRef(EX+'r'), RDF_REIFIES, (URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o'))))
        results = list(sg.triples((URIRef(EX+'r'), RDF_REIFIES, None)))
        assert len(results) == 1
        _, _, o = results[0]
        assert isinstance(o, TripleTerm)
        assert o == TripleTerm(URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o'))

    def test_add_tt_subject_positional(self, sg):
        sg.add((URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o')), URIRef(EX+'q'), URIRef(EX+'z'))
        results = list(sg.triples((None, URIRef(EX+'q'), URIRef(EX+'z'))))
        assert len(results) == 1
        s, _, _ = results[0]
        assert isinstance(s, TripleTerm)
        assert s == TripleTerm(URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o'))

    def test_add_tt_subject_single_tuple_form(self, sg):
        triple = ((URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o')), URIRef(EX+'q'), URIRef(EX+'z'))
        sg.add(triple)
        results = list(sg.triples((None, URIRef(EX+'q'), None)))
        assert len(results) == 1

    def test_contains_tt_subject(self, sg):
        sg.add((URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o')), URIRef(EX+'q'), URIRef(EX+'z'))
        assert ((URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o')), URIRef(EX+'q'), URIRef(EX+'z')) in sg

    def test_contains_tt_object(self, sg):
        sg.add((URIRef(EX+'r'), RDF_REIFIES, (URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o'))))
        assert (URIRef(EX+'r'), RDF_REIFIES, (URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o'))) in sg

    def test_tt_deduplication(self, sg):
        sg.add((URIRef(EX+'r1'), RDF_REIFIES, (URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o'))))
        sg.add((URIRef(EX+'r2'), RDF_REIFIES, (URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o'))))
        assert len(sg) == 2  # two visible triples, one shared TT bnode

    def test_two_distinct_tt_objects(self, sg):
        sg.add((URIRef(EX+'r1'), RDF_REIFIES, (URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o'))))
        sg.add((URIRef(EX+'r2'), RDF_REIFIES, (URIRef(EX+'a'), URIRef(EX+'b'), URIRef(EX+'c'))))
        assert len(sg) == 2


# ---------------------------------------------------------------------------
# Encoding triples are hidden from traversal
# ---------------------------------------------------------------------------

class TestEncodingHidden:
    def test_encoding_triples_not_in_triples(self, sg):
        sg.add((URIRef(EX+'r'), RDF_REIFIES, (URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o'))))
        preds = {p for _, p, _ in sg.triples((None, None, None))}
        assert RDF.subject   not in preds
        assert RDF.predicate not in preds
        assert RDF.object    not in preds

    def test_sl_triple_term_type_hidden(self, sg):
        from starlight.graph.starlight_graph import SL_TRIPLE_TERM
        sg.add((URIRef(EX+'r'), RDF_REIFIES, (URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o'))))
        objs = list(sg.objects(predicate=RDF.type))
        assert SL_TRIPLE_TERM not in objs

    def test_sl_reification_type_hidden(self, sg):
        from starlight.graph.starlight_graph import SL_REIFICATION
        sg.add_reification(URIRef(EX+'stmt'), (URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o')))
        objs = list(sg.objects(predicate=RDF.type))
        assert SL_REIFICATION not in objs

    def test_len_excludes_encoding(self, sg):
        sg.add((URIRef(EX+'r'), RDF_REIFIES, (URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o'))))
        assert len(sg) == 1  # only the rdf:reifies triple; 3 encoding triples hidden


# ---------------------------------------------------------------------------
# from_rdflib — wrapping the parser output
# ---------------------------------------------------------------------------

class TestFromRdflib:
    def test_from_rdflib_plain_triples(self):
        raw = Graph()
        raw.add((URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o')))
        sg = StarlightGraph.from_rdflib(raw)
        assert (URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o')) in sg

    def test_from_rdflib_builds_tt_registry(self, parser):
        raw = parser.parse(
            'PREFIX ex: <http://example.org/>\n'
            'ex:r rdf:reifies <<( ex:s ex:p ex:o )>> .\n'
        )
        sg = StarlightGraph.from_rdflib(raw)
        results = list(sg.triples((URIRef(EX+'r'), RDF_REIFIES, None)))
        assert len(results) == 1
        _, _, o = results[0]
        assert isinstance(o, TripleTerm)

    def test_from_rdflib_tt_values(self, parser):
        raw = parser.parse(
            'PREFIX ex: <http://example.org/>\n'
            'ex:r rdf:reifies <<( ex:s ex:p ex:o )>> .\n'
        )
        sg = StarlightGraph.from_rdflib(raw)
        _, _, tt = next(iter(sg.triples((URIRef(EX+'r'), RDF_REIFIES, None))))
        assert tt.subject   == URIRef(EX+'s')
        assert tt.predicate == URIRef(EX+'p')
        assert tt.object    == URIRef(EX+'o')

    def test_from_rdflib_len_excludes_encoding(self, parser):
        raw = parser.parse(
            'PREFIX ex: <http://example.org/>\n'
            'ex:r rdf:reifies <<( ex:s ex:p ex:o )>> .\n'
        )
        sg = StarlightGraph.from_rdflib(raw)
        assert len(sg) == 1

    def test_from_rdflib_nested_tt(self, parser):
        raw = parser.parse(
            'PREFIX ex: <http://example.org/>\n'
            'ex:r rdf:reifies <<( <<( ex:a ex:b ex:c )>> ex:p ex:o )>> .\n'
        )
        sg = StarlightGraph.from_rdflib(raw)
        _, _, outer = next(iter(sg.triples((URIRef(EX+'r'), RDF_REIFIES, None))))
        assert isinstance(outer, TripleTerm)
        assert isinstance(outer.subject, TripleTerm)
        assert outer.subject == TripleTerm(URIRef(EX+'a'), URIRef(EX+'b'), URIRef(EX+'c'))


# ---------------------------------------------------------------------------
# Statement operations
# ---------------------------------------------------------------------------

class TestStatements:
    def test_add_reification_visible_as_reifies_triple(self, sg):
        sg.add_reification(URIRef(EX+'stmt'), (URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o')))
        results = list(sg.triples((URIRef(EX+'stmt'), RDF_REIFIES, None)))
        assert len(results) == 1
        _, _, o = results[0]
        assert isinstance(o, TripleTerm)

    def test_reifications_by_reifier(self, sg):
        sg.add_reification(URIRef(EX+'stmt'), (URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o')))
        reifiers = list(sg.reifications(TT=(URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o'))))
        assert URIRef(EX+'stmt') in reifiers
        tts = list(sg.reified_triples(URIRef(EX+'stmt')))
        assert tts[0] == TripleTerm(URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o'))

    def test_reifications_by_triple_term(self, sg):
        sg.add_reification(URIRef(EX+'stmt'), (URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o')))
        tt = (URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o'))
        reifiers = list(sg.reifications(TT=tt))
        assert len(reifiers) == 1

    def test_reifications_all(self, sg):
        sg.add_reification(URIRef(EX+'stmt1'), (URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o')))
        sg.add_reification(URIRef(EX+'stmt2'), (URIRef(EX+'a'), URIRef(EX+'b'), URIRef(EX+'c')))
        reifiers = list(sg.reifications())
        assert len(reifiers) == 2

    def test_statement_len(self, sg):
        sg.add_reification(URIRef(EX+'stmt'), (URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o')))
        assert len(sg) == 1  # only rdf:reifies triple visible; 3 encoding triples hidden
