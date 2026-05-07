"""
Unit tests for starlight.serializers.turtle12.

Each test parses a TTL 1.2 snippet, serializes it back, then re-parses the
output and checks graph isomorphism — confirming a faithful round-trip.
"""

import pytest
from rdflib import URIRef, Literal
from rdflib.namespace import RDF
from rdflib.compare import isomorphic

from starlight.graph.starlight_graph import StarlightGraph, RDF_REIFIES
from starlight.model.triple import TripleTerm
from starlight.serializers.turtle12 import serialize_turtle12

EX = 'http://example/'


def _roundtrip(ttl12_text):
    """Parse TTL 1.2 → StarlightGraph → serialize → re-parse.

    Returns (raw1, raw2, output_text) where raw1/raw2 are plain rdflib.Graphs
    with the SL internal encoding, suitable for isomorphic() comparison.
    """
    from starlight.parsers.turtle_parser import StarlightTurtleParser
    raw1 = StarlightTurtleParser().parse(ttl12_text)
    sg1 = StarlightGraph.from_rdflib(raw1)
    out = serialize_turtle12(sg1)
    raw2 = StarlightTurtleParser().parse(out)
    return raw1, raw2, out


# ---------------------------------------------------------------------------
# Output contains <<( )>> notation
# ---------------------------------------------------------------------------

class TestTtl12Notation:
    def test_tt_as_object_written_with_angle_brackets(self, parser):
        raw = parser.parse(
            '@prefix : <http://example/> .\n'
            ':s :p <<( :a :b :c )>> .\n'
        )
        out = serialize_turtle12(raw)
        assert '<<(' in out
        assert ':a' in out
        assert ':b' in out
        assert ':c' in out

    def test_tt_as_subject_written_with_angle_brackets(self, parser):
        raw = parser.parse(
            '@prefix : <http://example/> .\n'
            '<<( :a :b :c )>> :p :o .\n'
        )
        out = serialize_turtle12(raw)
        assert '<<(' in out

    def test_no_sl_tripleTerm_type_in_output(self, parser):
        raw = parser.parse(
            '@prefix : <http://example/> .\n'
            ':s rdf:reifies <<( :a :b :c )>> .\n'
        )
        out = serialize_turtle12(raw)
        assert 'TripleTerm' not in out

    def test_no_sl_reification_type_in_output(self, parser):
        raw = parser.parse(
            '@prefix : <http://example/> .\n'
            ':s :p :o {| :ann :val |} .\n'
        )
        out = serialize_turtle12(raw)
        assert 'Reification' not in out

    def test_encoding_predicates_absent(self, parser):
        raw = parser.parse(
            '@prefix : <http://example/> .\n'
            ':s rdf:reifies <<( :a :b :c )>> .\n'
        )
        out = serialize_turtle12(raw)
        assert 'rdf:subject'   not in out
        assert 'rdf:predicate' not in out
        assert 'rdf:object'    not in out


# ---------------------------------------------------------------------------
# Round-trip isomorphism
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_tt_as_object(self):
        raw1, raw2, _ = _roundtrip(
            '@prefix : <http://example/> .\n'
            ':s :p <<( :a :b :c )>> .\n'
        )
        assert isomorphic(raw1, raw2)

    def test_tt_as_subject(self):
        raw1, raw2, _ = _roundtrip(
            '@prefix : <http://example/> .\n'
            '<<( :a :b :c )>> :p :o .\n'
        )
        assert isomorphic(raw1, raw2)

    def test_annotation(self):
        raw1, raw2, _ = _roundtrip(
            '@prefix : <http://example/> .\n'
            ':s :p :o {| :ann :val |} .\n'
        )
        assert isomorphic(raw1, raw2)

    def test_annotation_multi(self):
        raw1, raw2, _ = _roundtrip(
            '@prefix : <http://example/> .\n'
            ':s :p :o {| :ann1 :val1 ; :ann2 :val2 |} .\n'
        )
        assert isomorphic(raw1, raw2)

    def test_explicit_reifier(self):
        raw1, raw2, _ = _roundtrip(
            '@prefix : <http://example/> .\n'
            ':s :p :o ~ :i {| :ann :val |} .\n'
        )
        assert isomorphic(raw1, raw2)

    def test_shared_tt(self):
        raw1, raw2, _ = _roundtrip(
            '@prefix : <http://example/> .\n'
            '[] rdf:reifies <<( :a :b :c )>> ; :p :o .\n'
            '[] rdf:reifies <<( :a :b :c )>> ; :p1 :o1 .\n'
        )
        assert isomorphic(raw1, raw2)

    def test_tt_as_subject_with_property(self):
        raw1, raw2, _ = _roundtrip(
            '@prefix : <http://example/> .\n'
            '<<( :a :b :c )>> :funny true .\n'
        )
        assert isomorphic(raw1, raw2)

    def test_nested_tt(self):
        raw1, raw2, _ = _roundtrip(
            '@prefix : <http://example/> .\n'
            ':r rdf:reifies <<( <<( :a :b :c )>> :p :o )>> .\n'
        )
        assert isomorphic(raw1, raw2)

    def test_plain_turtle_unchanged(self):
        raw1, raw2, _ = _roundtrip(
            '@prefix : <http://example/> .\n'
            ':alice :knows :bob .\n'
            ':bob :name "Bob" .\n'
        )
        assert isomorphic(raw1, raw2)

    def test_ex1_full(self):
        raw1, raw2, _ = _roundtrip(
            '@prefix : <http://example/> .\n'
            '[] :p :o ; rdf:reifies <<( :a :b :c )>> .\n'
            '[] :p1 :o1 ; rdf:reifies <<( :a :b :c )>> .\n'
            '<<( :a :b :c )>> :funny true .\n'
        )
        assert isomorphic(raw1, raw2)


# ---------------------------------------------------------------------------
# StarlightGraph.serialize(format='turtle12') integration
# ---------------------------------------------------------------------------

class TestSerializeMethod:
    def test_sg_serialize_turtle12(self, parser):
        raw = parser.parse(
            '@prefix : <http://example/> .\n'
            ':s :p <<( :a :b :c )>> .\n'
        )
        sg = StarlightGraph.from_rdflib(raw)
        out = sg.serialize(format='turtle12')
        assert '<<(' in out
        assert 'TripleTerm' not in out

    def test_sg_serialize_default_still_works(self, parser):
        raw = parser.parse(
            '@prefix : <http://example/> .\n'
            ':alice :knows :bob .\n'
        )
        sg = StarlightGraph.from_rdflib(raw)
        out = sg.serialize(format='turtle')
        assert ':alice' in out

    def test_sg_serialize_turtle12_from_add(self):
        sg = StarlightGraph()
        sg.add((URIRef(EX+'r'), RDF_REIFIES, (URIRef(EX+'a'), URIRef(EX+'b'), URIRef(EX+'c'))))
        out = sg.serialize(format='turtle12')
        assert '<<(' in out
        assert 'TripleTerm' not in out


# ---------------------------------------------------------------------------
# RDF 1.2 version declaration
# ---------------------------------------------------------------------------

class TestVersionDeclaration:
    def test_version_emitted_when_triple_terms_present(self):
        sg = StarlightGraph()
        sg.add((URIRef(EX+'stmt'), RDF_REIFIES,
                TripleTerm(URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o'))))
        out = sg.serialize(format='turtle12')
        assert '@version "1.2" .' in out

    def test_version_before_prefix_lines(self):
        sg = StarlightGraph()
        sg.bind('ex', EX)
        sg.add((URIRef(EX+'stmt'), RDF_REIFIES,
                TripleTerm(URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o'))))
        out = sg.serialize(format='turtle12')
        lines = out.splitlines()
        version_idx = next(i for i, l in enumerate(lines) if '@version' in l)
        prefix_idx  = next(i for i, l in enumerate(lines) if '@prefix' in l)
        assert version_idx < prefix_idx

    def test_version_not_emitted_for_plain_graph(self):
        sg = StarlightGraph()
        sg.add((URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o')))
        out = sg.serialize(format='turtle12')
        assert '@version' not in out

    def test_version_not_emitted_for_empty_graph(self):
        sg = StarlightGraph()
        out = sg.serialize(format='turtle12')
        assert '@version' not in out

# ---------------------------------------------------------------------------
# longturtle12 serializer
# ---------------------------------------------------------------------------

class TestLongTurtle12:
    def test_one_triple_per_line(self):
        sg = StarlightGraph()
        sg.add((URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o1')))
        sg.add((URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o2')))
        out = sg.serialize(format='longturtle12')
        triple_lines = [l for l in out.splitlines() if l.strip() and not l.startswith('@')]
        assert len(triple_lines) == 2

    def test_no_semicolon_grouping(self):
        sg = StarlightGraph()
        sg.add((URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o')))
        sg.add((URIRef(EX+'s'), URIRef(EX+'q'), URIRef(EX+'z')))
        out = sg.serialize(format='longturtle12')
        assert ';' not in out

    def test_no_comma_grouping(self):
        sg = StarlightGraph()
        sg.add((URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o1')))
        sg.add((URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o2')))
        out = sg.serialize(format='longturtle12')
        assert ',' not in out

    def test_triple_term_serialized(self):
        sg = StarlightGraph()
        tt = TripleTerm(URIRef(EX+'a'), URIRef(EX+'b'), URIRef(EX+'c'))
        sg.add((URIRef(EX+'stmt'), RDF_REIFIES, tt))
        out = sg.serialize(format='longturtle12')
        assert '<<(' in out

    def test_version_emitted_with_triple_terms(self):
        sg = StarlightGraph()
        tt = TripleTerm(URIRef(EX+'a'), URIRef(EX+'b'), URIRef(EX+'c'))
        sg.add((URIRef(EX+'stmt'), RDF_REIFIES, tt))
        out = sg.serialize(format='longturtle12')
        assert '@version "1.2" .' in out

    def test_version_not_emitted_for_plain_graph(self):
        sg = StarlightGraph()
        sg.add((URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o')))
        out = sg.serialize(format='longturtle12')
        assert '@version' not in out

    def test_round_trip_plain_triples(self):
        sg = StarlightGraph()
        sg.add((URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o')))
        sg.add((URIRef(EX+'s'), URIRef(EX+'q'), Literal('hello')))
        out = sg.serialize(format='longturtle12')
        sg2 = StarlightGraph()
        sg2.parse(data=out, format='longturtle12')
        assert (URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o')) in sg2
        assert (URIRef(EX+'s'), URIRef(EX+'q'), Literal('hello')) in sg2

    def test_round_trip_triple_term(self):
        sg = StarlightGraph()
        tt = TripleTerm(URIRef(EX+'alice'), URIRef(EX+'knows'), URIRef(EX+'bob'))
        sg.add((URIRef(EX+'stmt'), RDF_REIFIES, tt))
        out = sg.serialize(format='longturtle12')
        sg2 = StarlightGraph()
        sg2.parse(data=out, format='longturtle12')
        assert sg2.has_triple_term(URIRef(EX+'alice'), URIRef(EX+'knows'), URIRef(EX+'bob'))

    def test_parse_via_longturtle12_alias(self):
        ttl = (
            f'@prefix ex: <{EX}> .\n'
            f'ex:s ex:p ex:o .\n'
        )
        sg = StarlightGraph()
        sg.parse(data=ttl, format='longturtle12')
        assert (URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o')) in sg
