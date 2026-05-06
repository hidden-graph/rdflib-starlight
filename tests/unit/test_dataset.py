"""
Unit tests for StarlightDataset.

Covers: multi-graph TriG 1.2 parsing, named-graph context access,
quad iteration, TriG 1.2 / N-Quads 1.2 serialization, and round-trip.
"""

import pytest
from rdflib import URIRef, Literal, BNode
from rdflib.namespace import RDF

from starlight.graph import StarlightDataset, StarlightGraph
from starlight.graph.starlight_graph import RDF_REIFIES
from starlight.model.triple import TripleTerm

EX = 'http://example.org/'
G1 = URIRef(EX + 'graph1')
G2 = URIRef(EX + 'graph2')


def ex(local):
    return URIRef(EX + local)


TRIG_BASIC = f"""\
@prefix ex: <{EX}> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

GRAPH <{EX}graph1> {{
  ex:s ex:p ex:o .
  ex:stmt1 rdf:reifies <<( ex:alice ex:knows ex:bob )>> .
  ex:stmt1 ex:confidence "0.9" .
}}

GRAPH <{EX}graph2> {{
  ex:stmt2 rdf:reifies <<( ex:bob ex:likes ex:carol )>> .
  ex:stmt2 ex:source ex:newspaper .
}}
"""

TRIG_WITH_DEFAULT = f"""\
@prefix ex: <{EX}> .

ex:default_s ex:default_p ex:default_o .

GRAPH <{EX}named> {{
  ex:named_s ex:named_p ex:named_o .
}}
"""

TRIG_NESTED_TT = f"""\
@prefix ex: <{EX}> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

GRAPH <{EX}graph1> {{
  ex:stmt rdf:reifies <<( <<( ex:a ex:b ex:c )>> ex:p ex:o )>> .
}}
"""


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestConstruction:
    def test_is_dataset(self):
        from rdflib import Dataset
        ds = StarlightDataset()
        assert isinstance(ds, Dataset)

    def test_empty_on_init(self):
        ds = StarlightDataset()
        assert list(ds.contexts()) == [] or all(len(g) == 0 for g in ds.contexts())


# ---------------------------------------------------------------------------
# Parse TriG 1.2
# ---------------------------------------------------------------------------

class TestParseTriG12:
    def test_named_graph_context_is_starlight_graph(self):
        ds = StarlightDataset()
        ds.parse(data=TRIG_BASIC, format='trig12')
        g1 = ds.get_context(G1)
        assert isinstance(g1, StarlightGraph)

    def test_named_graph_plain_triples(self):
        ds = StarlightDataset()
        ds.parse(data=TRIG_BASIC, format='trig12')
        g1 = ds.get_context(G1)
        assert (ex('s'), ex('p'), ex('o')) in g1

    def test_named_graph_has_triple_term(self):
        ds = StarlightDataset()
        ds.parse(data=TRIG_BASIC, format='trig12')
        g1 = ds.get_context(G1)
        assert g1.has_triple_term(ex('alice'), ex('knows'), ex('bob'))

    def test_named_graph_triple_term_in_object(self):
        ds = StarlightDataset()
        ds.parse(data=TRIG_BASIC, format='trig12')
        g1 = ds.get_context(G1)
        tt = TripleTerm(ex('alice'), ex('knows'), ex('bob'))
        objs = list(g1.objects(ex('stmt1'), RDF_REIFIES))
        assert tt in objs

    def test_two_named_graphs_independent(self):
        ds = StarlightDataset()
        ds.parse(data=TRIG_BASIC, format='trig12')
        g1 = ds.get_context(G1)
        g2 = ds.get_context(G2)
        assert g1.has_triple_term(ex('alice'), ex('knows'), ex('bob'))
        assert not g1.has_triple_term(ex('bob'), ex('likes'), ex('carol'))
        assert g2.has_triple_term(ex('bob'), ex('likes'), ex('carol'))
        assert not g2.has_triple_term(ex('alice'), ex('knows'), ex('bob'))

    def test_triple_terms_not_visible_across_graphs(self):
        ds = StarlightDataset()
        ds.parse(data=TRIG_BASIC, format='trig12')
        g2 = ds.get_context(G2)
        tt = TripleTerm(ex('alice'), ex('knows'), ex('bob'))
        objs = list(g2.objects(ex('stmt1'), RDF_REIFIES))
        assert tt not in objs

    def test_default_graph_triples_accessible(self):
        ds = StarlightDataset()
        ds.parse(data=TRIG_WITH_DEFAULT, format='trig12')
        found = any(
            (ex('default_s'), ex('default_p'), ex('default_o')) in g
            for g in ds.contexts()
        )
        assert found

    def test_named_graph_triple_count(self):
        ds = StarlightDataset()
        ds.parse(data=TRIG_BASIC, format='trig12')
        g1 = ds.get_context(G1)
        assert len(g1) == 3  # s/p/o, stmt1/reifies/TT, stmt1/confidence/0.9

    def test_nested_triple_term(self):
        ds = StarlightDataset()
        ds.parse(data=TRIG_NESTED_TT, format='trig12')
        g1 = ds.get_context(G1)
        inner = TripleTerm(ex('a'), ex('b'), ex('c'))
        outer = TripleTerm(inner, ex('p'), ex('o'))
        objs = list(g1.objects(ex('stmt'), RDF_REIFIES))
        assert outer in objs


# ---------------------------------------------------------------------------
# StarlightGraph API on named contexts
# ---------------------------------------------------------------------------

class TestContextAPI:
    def test_triple_terms_method(self):
        ds = StarlightDataset()
        ds.parse(data=TRIG_BASIC, format='trig12')
        g1 = ds.get_context(G1)
        tts = list(g1.triple_terms())
        assert len(tts) == 1
        assert tts[0] == TripleTerm(ex('alice'), ex('knows'), ex('bob'))

    def test_reifications_method(self):
        ds = StarlightDataset()
        ds.parse(data=TRIG_BASIC, format='trig12')
        g1 = ds.get_context(G1)
        tt = TripleTerm(ex('alice'), ex('knows'), ex('bob'))
        reifiers = list(g1.reifications(TT=tt))
        assert ex('stmt1') in reifiers

    def test_encoding_triples_hidden_in_context(self):
        ds = StarlightDataset()
        ds.parse(data=TRIG_BASIC, format='trig12')
        g1 = ds.get_context(G1)
        enc_triples = [
            (s, p, o) for s, p, o in g1.triples((None, None, None))
            if str(p) in (
                'http://www.w3.org/1999/02/22-rdf-syntax-ns#subject',
                'http://www.w3.org/1999/02/22-rdf-syntax-ns#predicate',
                'http://www.w3.org/1999/02/22-rdf-syntax-ns#object',
            )
        ]
        assert enc_triples == []

    def test_same_context_returned_on_repeated_get(self):
        ds = StarlightDataset()
        ds.parse(data=TRIG_BASIC, format='trig12')
        g1a = ds.get_context(G1)
        g1b = ds.get_context(G1)
        assert g1a is g1b


# ---------------------------------------------------------------------------
# Quad iteration
# ---------------------------------------------------------------------------

class TestQuads:
    def test_quads_include_both_graphs(self):
        ds = StarlightDataset()
        ds.parse(data=TRIG_BASIC, format='trig12')
        graphs_seen = {str(g.identifier) for _, _, _, g in ds.quads()}
        assert str(G1) in graphs_seen
        assert str(G2) in graphs_seen

    def test_quads_restore_triple_terms(self):
        ds = StarlightDataset()
        ds.parse(data=TRIG_BASIC, format='trig12')
        tt = TripleTerm(ex('alice'), ex('knows'), ex('bob'))
        matching = [
            (s, p, o, g) for s, p, o, g in ds.quads()
            if o == tt
        ]
        assert len(matching) == 1
        assert matching[0][3].identifier == G1

    def test_quads_context_is_starlight_graph(self):
        ds = StarlightDataset()
        ds.parse(data=TRIG_BASIC, format='trig12')
        for _, _, _, g in ds.quads():
            assert isinstance(g, StarlightGraph)

    def test_quads_no_encoding_triples(self):
        ds = StarlightDataset()
        ds.parse(data=TRIG_BASIC, format='trig12')
        enc_preds = {
            'http://www.w3.org/1999/02/22-rdf-syntax-ns#subject',
            'http://www.w3.org/1999/02/22-rdf-syntax-ns#predicate',
            'http://www.w3.org/1999/02/22-rdf-syntax-ns#object',
        }
        for _, p, _, _ in ds.quads():
            assert str(p) not in enc_preds

    def test_triples_union_view(self):
        ds = StarlightDataset()
        ds.parse(data=TRIG_BASIC, format='trig12')
        all_triples = list(ds.triples((None, None, None)))
        subjects = {str(s) for s, _, _ in all_triples}
        assert EX + 's' in subjects
        assert EX + 'stmt2' in subjects


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

class TestSerialize:
    def test_serialize_produces_graph_blocks(self):
        ds = StarlightDataset()
        ds.parse(data=TRIG_BASIC, format='trig12')
        out = ds.serialize(format='trig12')
        assert 'GRAPH' in out
        assert f'<{G1}>' in out
        assert f'<{G2}>' in out

    def test_serialize_triple_terms_present(self):
        ds = StarlightDataset()
        ds.parse(data=TRIG_BASIC, format='trig12')
        out = ds.serialize(format='trig12')
        assert '<<(' in out

    def test_prefixes_before_graph_blocks(self):
        ds = StarlightDataset()
        ds.parse(data=TRIG_BASIC, format='trig12')
        out = ds.serialize(format='trig12')
        lines = out.splitlines()
        prefix_idx = next((i for i, l in enumerate(lines) if '@prefix' in l), None)
        graph_idx  = next((i for i, l in enumerate(lines) if 'GRAPH' in l), None)
        assert prefix_idx is not None
        assert graph_idx is not None
        assert prefix_idx < graph_idx


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_plain_triple_roundtrip(self):
        ds = StarlightDataset()
        ds.parse(data=TRIG_BASIC, format='trig12')
        out = ds.serialize(format='trig12')
        ds2 = StarlightDataset()
        ds2.parse(data=out, format='trig12')
        g1 = ds2.get_context(G1)
        assert (ex('s'), ex('p'), ex('o')) in g1

    def test_triple_term_roundtrip(self):
        ds = StarlightDataset()
        ds.parse(data=TRIG_BASIC, format='trig12')
        out = ds.serialize(format='trig12')
        ds2 = StarlightDataset()
        ds2.parse(data=out, format='trig12')
        g1 = ds2.get_context(G1)
        g2 = ds2.get_context(G2)
        assert g1.has_triple_term(ex('alice'), ex('knows'), ex('bob'))
        assert g2.has_triple_term(ex('bob'), ex('likes'), ex('carol'))

    def test_graph_isolation_preserved_after_roundtrip(self):
        ds = StarlightDataset()
        ds.parse(data=TRIG_BASIC, format='trig12')
        out = ds.serialize(format='trig12')
        ds2 = StarlightDataset()
        ds2.parse(data=out, format='trig12')
        g1 = ds2.get_context(G1)
        g2 = ds2.get_context(G2)
        assert not g2.has_triple_term(ex('alice'), ex('knows'), ex('bob'))
        assert not g1.has_triple_term(ex('bob'), ex('likes'), ex('carol'))

    def test_triple_count_preserved(self):
        ds = StarlightDataset()
        ds.parse(data=TRIG_BASIC, format='trig12')
        g1_before = len(ds.get_context(G1))
        g2_before = len(ds.get_context(G2))

        out = ds.serialize(format='trig12')
        ds2 = StarlightDataset()
        ds2.parse(data=out, format='trig12')

        assert len(ds2.get_context(G1)) == g1_before
        assert len(ds2.get_context(G2)) == g2_before


# ---------------------------------------------------------------------------
# N-Quads 1.2 multi-graph
# ---------------------------------------------------------------------------

NQ_BASIC = (
    f'<{EX}s> <{EX}p> <{EX}o> <{EX}graph1> .\n'
    f'<{EX}stmt1> <http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies> '
    f'<<( <{EX}alice> <{EX}knows> <{EX}bob> )>> <{EX}graph1> .\n'
    f'<{EX}stmt1> <{EX}confidence> "0.9" <{EX}graph1> .\n'
    f'<{EX}stmt2> <http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies> '
    f'<<( <{EX}bob> <{EX}likes> <{EX}carol> )>> <{EX}graph2> .\n'
    f'<{EX}stmt2> <{EX}source> <{EX}newspaper> <{EX}graph2> .\n'
)


class TestNQ12MultiGraph:
    def test_parse_two_named_graphs(self):
        ds = StarlightDataset()
        ds.parse(data=NQ_BASIC, format='nq12')
        g1 = ds.get_context(G1)
        g2 = ds.get_context(G2)
        assert isinstance(g1, StarlightGraph)
        assert isinstance(g2, StarlightGraph)

    def test_triple_term_in_graph1(self):
        ds = StarlightDataset()
        ds.parse(data=NQ_BASIC, format='nq12')
        g1 = ds.get_context(G1)
        assert g1.has_triple_term(ex('alice'), ex('knows'), ex('bob'))

    def test_triple_term_in_graph2(self):
        ds = StarlightDataset()
        ds.parse(data=NQ_BASIC, format='nq12')
        g2 = ds.get_context(G2)
        assert g2.has_triple_term(ex('bob'), ex('likes'), ex('carol'))

    def test_graph_isolation(self):
        ds = StarlightDataset()
        ds.parse(data=NQ_BASIC, format='nq12')
        g1 = ds.get_context(G1)
        g2 = ds.get_context(G2)
        assert not g1.has_triple_term(ex('bob'), ex('likes'), ex('carol'))
        assert not g2.has_triple_term(ex('alice'), ex('knows'), ex('bob'))

    def test_plain_triple_in_named_graph(self):
        ds = StarlightDataset()
        ds.parse(data=NQ_BASIC, format='nq12')
        g1 = ds.get_context(G1)
        assert (ex('s'), ex('p'), ex('o')) in g1

    def test_serialize_nq12_includes_graph_names(self):
        ds = StarlightDataset()
        ds.parse(data=NQ_BASIC, format='nq12')
        out = ds.serialize(format='nq12')
        assert f'<{EX}graph1>' in out
        assert f'<{EX}graph2>' in out

    def test_serialize_nq12_triple_terms(self):
        ds = StarlightDataset()
        ds.parse(data=NQ_BASIC, format='nq12')
        out = ds.serialize(format='nq12')
        assert '<<(' in out

    def test_nq12_roundtrip(self):
        ds = StarlightDataset()
        ds.parse(data=NQ_BASIC, format='nq12')
        out = ds.serialize(format='nq12')
        ds2 = StarlightDataset()
        ds2.parse(data=out, format='nq12')
        g1 = ds2.get_context(G1)
        g2 = ds2.get_context(G2)
        assert g1.has_triple_term(ex('alice'), ex('knows'), ex('bob'))
        assert g2.has_triple_term(ex('bob'), ex('likes'), ex('carol'))
        assert not g2.has_triple_term(ex('alice'), ex('knows'), ex('bob'))

    def test_nq12_triple_count_preserved(self):
        ds = StarlightDataset()
        ds.parse(data=NQ_BASIC, format='nq12')
        before = {str(G1): len(ds.get_context(G1)), str(G2): len(ds.get_context(G2))}
        out = ds.serialize(format='nq12')
        ds2 = StarlightDataset()
        ds2.parse(data=out, format='nq12')
        assert len(ds2.get_context(G1)) == before[str(G1)]
        assert len(ds2.get_context(G2)) == before[str(G2)]

    def test_cross_format_trig_to_nq12(self):
        """Parse TriG 1.2, serialize to N-Quads 1.2, re-parse — data preserved."""
        ds = StarlightDataset()
        ds.parse(data=TRIG_BASIC, format='trig12')
        out = ds.serialize(format='nq12')
        ds2 = StarlightDataset()
        ds2.parse(data=out, format='nq12')
        assert ds2.get_context(G1).has_triple_term(ex('alice'), ex('knows'), ex('bob'))
        assert ds2.get_context(G2).has_triple_term(ex('bob'), ex('likes'), ex('carol'))

    def test_cross_format_nq12_to_trig(self):
        """Parse N-Quads 1.2, serialize to TriG 1.2, re-parse — data preserved."""
        ds = StarlightDataset()
        ds.parse(data=NQ_BASIC, format='nq12')
        out = ds.serialize(format='trig12')
        assert 'GRAPH' in out
        ds2 = StarlightDataset()
        ds2.parse(data=out, format='trig12')
        assert ds2.get_context(G1).has_triple_term(ex('alice'), ex('knows'), ex('bob'))
        assert ds2.get_context(G2).has_triple_term(ex('bob'), ex('likes'), ex('carol'))
