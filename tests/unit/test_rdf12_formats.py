"""
Unit tests for RDF 1.2 format parsing and serialization.

Covers N-Triples 1.2 (nt12), N-Quads 1.2 (nq12), and TriG 1.2 (trig12)
via StarlightGraph.parse() and StarlightGraph.serialize().
"""

import pytest
from rdflib import URIRef, BNode, Literal
from rdflib.namespace import RDF, XSD

from starlight.graph.starlight_graph import StarlightGraph, RDF_REIFIES
from starlight.model.triple import TripleTerm

EX = 'http://example.org/'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ex(local):
    return URIRef(EX + local)


def round_trip(g, fmt):
    """Serialize g to fmt, parse into a fresh graph, return both serialized text and new graph."""
    text = g.serialize(format=fmt)
    g2 = StarlightGraph()
    g2.parse(data=text, format=fmt)
    return text, g2


# ---------------------------------------------------------------------------
# N-Triples 1.2 — parsing
# ---------------------------------------------------------------------------

class TestNT12Parse:
    def test_plain_triple(self):
        nt = '<http://example.org/s> <http://example.org/p> <http://example.org/o> .\n'
        g = StarlightGraph()
        g.parse(data=nt, format='nt12')
        assert (ex('s'), ex('p'), ex('o')) in g

    def test_literal_object(self):
        nt = '<http://example.org/s> <http://example.org/p> "hello" .\n'
        g = StarlightGraph()
        g.parse(data=nt, format='nt12')
        assert Literal('hello') in list(g.objects(ex('s'), ex('p')))

    def test_typed_literal(self):
        nt = f'<{EX}s> <{EX}age> "42"^^<{XSD}integer> .\n'
        g = StarlightGraph()
        g.parse(data=nt, format='nt12')
        objs = list(g.objects(ex('s'), ex('age')))
        assert any(str(o) == '42' for o in objs)

    def test_lang_tagged_literal(self):
        nt = f'<{EX}s> <{EX}label> "hello"@en .\n'
        g = StarlightGraph()
        g.parse(data=nt, format='nt12')
        objs = list(g.objects(ex('s'), ex('label')))
        assert any(getattr(o, 'language', None) == 'en' for o in objs)

    def test_bnode_subject(self):
        nt = '_:b0 <http://example.org/p> <http://example.org/o> .\n'
        g = StarlightGraph()
        g.parse(data=nt, format='nt12')
        assert len(g) == 1

    def test_triple_term_subject(self):
        nt = f'<<( <{EX}s> <{EX}p> <{EX}o> )>> <{EX}claimedBy> <{EX}alice> .\n'
        g = StarlightGraph()
        g.parse(data=nt, format='nt12')
        tt = TripleTerm(ex('s'), ex('p'), ex('o'))
        assert g.has_triple_term(ex('s'), ex('p'), ex('o'))
        subjs = list(g.subjects(ex('claimedBy'), ex('alice')))
        assert tt in subjs

    def test_triple_term_object(self):
        nt = f'<{EX}stmt1> <{RDF_REIFIES}> <<( <{EX}alice> <{EX}knows> <{EX}bob> )>> .\n'
        g = StarlightGraph()
        g.parse(data=nt, format='nt12')
        assert g.has_triple_term(ex('alice'), ex('knows'), ex('bob'))
        tt = TripleTerm(ex('alice'), ex('knows'), ex('bob'))
        objs = list(g.objects(ex('stmt1'), RDF_REIFIES))
        assert tt in objs

    def test_nested_triple_term(self):
        nt = (
            f'<{EX}stmt1> <{RDF_REIFIES}> '
            f'<<( <<( <{EX}a> <{EX}b> <{EX}c> )>> <{EX}p> <{EX}o> )>> .\n'
        )
        g = StarlightGraph()
        g.parse(data=nt, format='nt12')
        inner_tt = TripleTerm(ex('a'), ex('b'), ex('c'))
        outer_tt = TripleTerm(inner_tt, ex('p'), ex('o'))
        assert outer_tt in list(g.objects(ex('stmt1'), RDF_REIFIES))

    def test_comment_lines_ignored(self):
        nt = f'# This is a comment\n<{EX}p> <{EX}q> <{EX}r> .\n'
        g = StarlightGraph()
        g.parse(data=nt, format='nt12')
        assert len(g) == 1

    def test_escape_in_literal(self):
        nt = f'<{EX}s> <{EX}p> "line1\\nline2" .\n'
        g = StarlightGraph()
        g.parse(data=nt, format='nt12')
        objs = list(g.objects(ex('s'), ex('p')))
        assert any('\n' in str(o) for o in objs)


# ---------------------------------------------------------------------------
# N-Triples 1.2 — serialization
# ---------------------------------------------------------------------------

class TestNT12Serialize:
    def test_plain_triple(self):
        g = StarlightGraph()
        g.add((ex('s'), ex('p'), ex('o')))
        text = g.serialize(format='nt12')
        assert f'<{EX}s>' in text
        assert f'<{EX}p>' in text
        assert f'<{EX}o>' in text
        assert text.endswith('\n')

    def test_triple_term_as_subject(self):
        g = StarlightGraph()
        tt = TripleTerm(ex('a'), ex('b'), ex('c'))
        g.add((tt, ex('claimedBy'), ex('alice')))
        text = g.serialize(format='nt12')
        assert '<<(' in text
        assert f'<{EX}a>' in text

    def test_triple_term_as_object(self):
        g = StarlightGraph()
        tt = TripleTerm(ex('alice'), ex('knows'), ex('bob'))
        g.add((ex('stmt1'), RDF_REIFIES, tt))
        text = g.serialize(format='nt12')
        assert '<<(' in text
        assert f'<{EX}alice>' in text

    def test_literal_serialized_with_datatype(self):
        g = StarlightGraph()
        g.add((ex('s'), ex('p'), Literal('hello')))
        text = g.serialize(format='nt12')
        assert '"hello"' in text
        assert 'xsd' in text.lower() or 'XMLSchema' in text

    def test_bnode_serialized(self):
        g = StarlightGraph()
        bn = BNode()
        g.add((bn, ex('p'), ex('o')))
        text = g.serialize(format='nt12')
        assert '_:' in text


# ---------------------------------------------------------------------------
# N-Triples 1.2 — round-trip
# ---------------------------------------------------------------------------

class TestNT12RoundTrip:
    def test_plain_triple_roundtrip(self):
        g = StarlightGraph()
        g.add((ex('s'), ex('p'), ex('o')))
        _, g2 = round_trip(g, 'nt12')
        assert (ex('s'), ex('p'), ex('o')) in g2

    def test_triple_term_subject_roundtrip(self):
        g = StarlightGraph()
        tt = TripleTerm(ex('alice'), ex('knows'), ex('bob'))
        g.add((tt, ex('claimedBy'), ex('news')))
        _, g2 = round_trip(g, 'nt12')
        assert g2.has_triple_term(ex('alice'), ex('knows'), ex('bob'))
        subjs = list(g2.subjects(ex('claimedBy'), ex('news')))
        assert tt in subjs

    def test_triple_term_object_roundtrip(self):
        g = StarlightGraph()
        tt = TripleTerm(ex('s'), ex('p'), ex('o'))
        g.add((ex('stmt1'), RDF_REIFIES, tt))
        _, g2 = round_trip(g, 'nt12')
        objs = list(g2.objects(ex('stmt1'), RDF_REIFIES))
        assert tt in objs

    def test_nested_triple_term_roundtrip(self):
        g = StarlightGraph()
        inner = TripleTerm(ex('a'), ex('b'), ex('c'))
        outer = TripleTerm(inner, ex('p'), ex('o'))
        g.add((ex('stmt'), RDF_REIFIES, outer))
        _, g2 = round_trip(g, 'nt12')
        objs = list(g2.objects(ex('stmt'), RDF_REIFIES))
        assert outer in objs

    def test_length_preserved(self):
        g = StarlightGraph()
        tt = TripleTerm(ex('s'), ex('p'), ex('o'))
        g.add((ex('stmt1'), RDF_REIFIES, tt))
        g.add((ex('stmt1'), ex('confidence'), Literal('0.9')))
        g.add((ex('s'), ex('p'), ex('o')))
        _, g2 = round_trip(g, 'nt12')
        assert len(g2) == len(g)


# ---------------------------------------------------------------------------
# N-Quads 1.2
# ---------------------------------------------------------------------------

class TestNQ12:
    def test_parse_ignores_graph_name(self):
        nq = (
            f'<{EX}s> <{EX}p> <{EX}o> <{EX}graph1> .\n'
            f'<{EX}a> <{EX}b> <{EX}c> <{EX}graph2> .\n'
        )
        g = StarlightGraph()
        g.parse(data=nq, format='nq12')
        # Both triples should be merged into this graph
        assert (ex('s'), ex('p'), ex('o')) in g
        assert (ex('a'), ex('b'), ex('c')) in g

    def test_parse_triple_term_in_nquads(self):
        nq = (
            f'<{EX}stmt1> <{RDF_REIFIES}> '
            f'<<( <{EX}alice> <{EX}knows> <{EX}bob> )>> '
            f'<{EX}graph1> .\n'
        )
        g = StarlightGraph()
        g.parse(data=nq, format='nq12')
        assert g.has_triple_term(ex('alice'), ex('knows'), ex('bob'))

    def test_serialize_includes_graph_name(self):
        g = StarlightGraph(identifier=ex('mygraph'))
        g.add((ex('s'), ex('p'), ex('o')))
        text = g.serialize(format='nq12')
        assert f'<{EX}mygraph>' in text
        assert f'<{EX}s>' in text

    def test_serialize_triple_term_nquads(self):
        g = StarlightGraph(identifier=ex('mygraph'))
        tt = TripleTerm(ex('alice'), ex('knows'), ex('bob'))
        g.add((ex('stmt1'), RDF_REIFIES, tt))
        text = g.serialize(format='nq12')
        assert '<<(' in text
        assert f'<{EX}mygraph>' in text

    def test_roundtrip_nquads(self):
        g = StarlightGraph(identifier=ex('mygraph'))
        tt = TripleTerm(ex('s'), ex('p'), ex('o'))
        g.add((ex('stmt'), RDF_REIFIES, tt))
        g.add((ex('a'), ex('b'), ex('c')))
        text = g.serialize(format='nq12')
        g2 = StarlightGraph()
        g2.parse(data=text, format='nq12')
        assert (ex('a'), ex('b'), ex('c')) in g2
        assert g2.has_triple_term(ex('s'), ex('p'), ex('o'))


# ---------------------------------------------------------------------------
# TriG 1.2 — parsing
# ---------------------------------------------------------------------------

class TestTriG12Parse:
    def test_default_graph_triple(self):
        trig = f'<{EX}s> <{EX}p> <{EX}o> .\n'
        g = StarlightGraph()
        g.parse(data=trig, format='trig12')
        assert (ex('s'), ex('p'), ex('o')) in g

    def test_named_graph_block(self):
        trig = (
            f'@prefix ex: <{EX}> .\n'
            f'GRAPH <{EX}g1> {{\n'
            f'  ex:s ex:p ex:o .\n'
            f'}}\n'
        )
        g = StarlightGraph()
        g.parse(data=trig, format='trig12')
        assert (ex('s'), ex('p'), ex('o')) in g

    def test_triple_term_in_named_graph(self):
        trig = (
            f'@prefix ex: <{EX}> .\n'
            f'@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .\n'
            f'GRAPH <{EX}g1> {{\n'
            f'  ex:stmt1 rdf:reifies <<( ex:alice ex:knows ex:bob )>> .\n'
            f'}}\n'
        )
        g = StarlightGraph()
        g.parse(data=trig, format='trig12')
        assert g.has_triple_term(ex('alice'), ex('knows'), ex('bob'))

    def test_multiple_named_graphs_merged(self):
        trig = (
            f'@prefix ex: <{EX}> .\n'
            f'GRAPH <{EX}g1> {{\n'
            f'  ex:a ex:b ex:c .\n'
            f'}}\n'
            f'GRAPH <{EX}g2> {{\n'
            f'  ex:x ex:y ex:z .\n'
            f'}}\n'
        )
        g = StarlightGraph()
        g.parse(data=trig, format='trig12')
        assert (ex('a'), ex('b'), ex('c')) in g
        assert (ex('x'), ex('y'), ex('z')) in g

    def test_default_and_named_graph_merged(self):
        trig = (
            f'@prefix ex: <{EX}> .\n'
            f'ex:default ex:graph ex:triple .\n'
            f'GRAPH <{EX}g1> {{\n'
            f'  ex:named ex:graph ex:triple .\n'
            f'}}\n'
        )
        g = StarlightGraph()
        g.parse(data=trig, format='trig12')
        assert (ex('default'), ex('graph'), ex('triple')) in g
        assert (ex('named'), ex('graph'), ex('triple')) in g


# ---------------------------------------------------------------------------
# TriG 1.2 — serialization
# ---------------------------------------------------------------------------

class TestTriG12Serialize:
    def test_default_graph_is_plain_turtle(self):
        g = StarlightGraph()  # default BNode identifier
        g.add((ex('s'), ex('p'), ex('o')))
        text = g.serialize(format='trig12')
        assert 'GRAPH' not in text
        assert f'<{EX}' in text

    def test_named_graph_wrapped(self):
        g = StarlightGraph(identifier=ex('mygraph'))
        g.add((ex('s'), ex('p'), ex('o')))
        text = g.serialize(format='trig12')
        assert 'GRAPH' in text
        assert f'<{EX}mygraph>' in text

    def test_triple_term_in_trig(self):
        g = StarlightGraph(identifier=ex('mygraph'))
        tt = TripleTerm(ex('alice'), ex('knows'), ex('bob'))
        g.add((ex('stmt1'), RDF_REIFIES, tt))
        text = g.serialize(format='trig12')
        assert '<<(' in text
        assert 'GRAPH' in text

    def test_prefixes_before_graph_block(self):
        g = StarlightGraph(identifier=ex('mygraph'))
        g.bind('ex', EX)
        g.add((ex('s'), ex('p'), ex('o')))
        text = g.serialize(format='trig12')
        lines = text.strip().splitlines()
        # Prefix declarations should come before GRAPH block
        prefix_idx = next((i for i, l in enumerate(lines) if '@prefix' in l), None)
        graph_idx  = next((i for i, l in enumerate(lines) if 'GRAPH' in l), None)
        if prefix_idx is not None and graph_idx is not None:
            assert prefix_idx < graph_idx


# ---------------------------------------------------------------------------
# TriG 1.2 — round-trip
# ---------------------------------------------------------------------------

class TestTriG12RoundTrip:
    def test_plain_triple_roundtrip(self):
        g = StarlightGraph()
        g.add((ex('s'), ex('p'), ex('o')))
        _, g2 = round_trip(g, 'trig12')
        assert (ex('s'), ex('p'), ex('o')) in g2

    def test_triple_term_roundtrip(self):
        g = StarlightGraph()
        tt = TripleTerm(ex('alice'), ex('knows'), ex('bob'))
        g.add((ex('stmt1'), RDF_REIFIES, tt))
        _, g2 = round_trip(g, 'trig12')
        assert g2.has_triple_term(ex('alice'), ex('knows'), ex('bob'))
        objs = list(g2.objects(ex('stmt1'), RDF_REIFIES))
        assert tt in objs

    def test_length_preserved(self):
        g = StarlightGraph()
        tt = TripleTerm(ex('s'), ex('p'), ex('o'))
        g.add((ex('stmt1'), RDF_REIFIES, tt))
        g.add((ex('stmt1'), ex('confidence'), Literal('0.9')))
        g.add((ex('s'), ex('p'), ex('o')))
        _, g2 = round_trip(g, 'trig12')
        assert len(g2) == len(g)
