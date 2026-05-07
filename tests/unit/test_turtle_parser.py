"""
Unit tests for starlight.parsers.turtle_parser.

Tests cover plain Turtle 1.1 parsing (compared against rdflib) and
RDF 1.2 features (triple terms, reification, annotations).
"""

import pytest
from rdflib import Graph, URIRef, Literal, BNode
from rdflib.namespace import RDF, XSD

from starlight.parsers.turtle_parser import StarlightTurtleParser, SL_NS

EX = 'http://example.org/'
SL_TRIPLE_TERM  = URIRef(SL_NS + 'TripleTerm')
SL_REIFICATION  = URIRef(SL_NS + 'Reification')
RDF_REIFIES     = URIRef('http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies')


# ---------------------------------------------------------------------------
# Plain Turtle 1.1 — must match rdflib's native parser
# ---------------------------------------------------------------------------

class TestPlainTurtle:
    def test_simple_iri_triple(self, parser, fixture_ttl):
        g = parser.parse(fixture_ttl('simple.ttl'))
        assert (URIRef(EX+'alice'), URIRef(EX+'knows'), URIRef(EX+'bob')) in g

    def test_string_literal(self, parser, fixture_ttl):
        g = parser.parse(fixture_ttl('simple.ttl'))
        assert (URIRef(EX+'bob'), URIRef(EX+'name'), Literal('Bob')) in g

    def test_integer_literal(self, parser, fixture_ttl):
        g = parser.parse(fixture_ttl('simple.ttl'))
        assert (URIRef(EX+'alice'), URIRef(EX+'age'), Literal(30, datatype=XSD.integer)) in g

    def test_boolean_literal(self, parser, fixture_ttl):
        g = parser.parse(fixture_ttl('simple.ttl'))
        assert (URIRef(EX+'bob'), URIRef(EX+'active'), Literal(True, datatype=XSD.boolean)) in g

    def test_float_literal(self, parser, fixture_ttl):
        g = parser.parse(fixture_ttl('literals.ttl'))
        assert (URIRef(EX+'s'), URIRef(EX+'float'), Literal(3.14, datatype=XSD.decimal)) in g

    def test_typed_literal(self, parser, fixture_ttl):
        g = parser.parse(fixture_ttl('literals.ttl'))
        date_node = Literal('2024-01-01', datatype=URIRef('http://www.w3.org/2001/XMLSchema#date'))
        assert (URIRef(EX+'s'), URIRef(EX+'typed'), date_node) in g

    def test_lang_literal(self, parser, fixture_ttl):
        g = parser.parse(fixture_ttl('literals.ttl'))
        assert (URIRef(EX+'s'), URIRef(EX+'lang'), Literal('bonjour', lang='fr')) in g

    def test_rdf_type_abbreviation(self, parser):
        g = parser.parse('@prefix ex: <http://example.org/> .\nex:s a ex:Thing .\n')
        assert (URIRef(EX+'s'), RDF.type, URIRef(EX+'Thing')) in g

    def test_multiple_predicates_semicolon(self, parser):
        g = parser.parse('@prefix ex: <http://example.org/> .\nex:s ex:p ex:o ; ex:q ex:z .\n')
        assert len(list(g.triples((URIRef(EX+'s'), None, None)))) == 2

    def test_multiple_objects_comma(self, parser):
        g = parser.parse('@prefix ex: <http://example.org/> .\nex:s ex:p ex:o , ex:o2 .\n')
        assert len(list(g.triples((URIRef(EX+'s'), URIRef(EX+'p'), None)))) == 2

    def test_matches_rdflib_for_simple_file(self, parser, fixture_ttl):
        data = fixture_ttl('simple.ttl')
        g_ours = parser.parse(data)
        g_rdflib = Graph()
        g_rdflib.parse(data=data, format='turtle')
        for triple in g_rdflib:
            assert triple in g_ours, f"Triple missing from starlight output: {triple}"


class TestBlankNodes:
    def test_blank_node_object(self, parser, fixture_ttl):
        g = parser.parse(fixture_ttl('blank_nodes.ttl'))
        addrs = list(g.objects(URIRef(EX+'alice'), URIRef(EX+'address')))
        assert len(addrs) == 1
        assert isinstance(addrs[0], BNode)

    def test_blank_node_inner_triple(self, parser, fixture_ttl):
        g = parser.parse(fixture_ttl('blank_nodes.ttl'))
        addrs = list(g.objects(URIRef(EX+'alice'), URIRef(EX+'address')))
        bnode = addrs[0]
        cities = list(g.objects(bnode, URIRef(EX+'city')))
        assert cities == [Literal('Springfield')]

    def test_collection_head_is_bnode(self, parser, fixture_ttl):
        g = parser.parse(fixture_ttl('blank_nodes.ttl'))
        items = list(g.objects(URIRef(EX+'doc'), URIRef(EX+'items')))
        assert len(items) == 1
        assert isinstance(items[0], BNode)

    def test_collection_has_rdf_first(self, parser, fixture_ttl):
        g = parser.parse(fixture_ttl('blank_nodes.ttl'))
        items_head = list(g.objects(URIRef(EX+'doc'), URIRef(EX+'items')))[0]
        firsts = list(g.objects(items_head, RDF.first))
        assert firsts == [URIRef(EX+'a')]


# ---------------------------------------------------------------------------
# RDF 1.2 features
# ---------------------------------------------------------------------------

class TestTripleTerms:
    def test_triple_term_creates_sl_node(self, parser):
        g = parser.parse(
            'PREFIX ex: <http://example.org/>\n'
            'ex:r rdf:reifies <<( ex:s ex:p ex:o )>> .\n'
        )
        tt_nodes = list(g.subjects(RDF.type, SL_TRIPLE_TERM))
        assert len(tt_nodes) == 1

    def test_triple_term_has_subject(self, parser):
        g = parser.parse(
            'PREFIX ex: <http://example.org/>\n'
            'ex:r rdf:reifies <<( ex:s ex:p ex:o )>> .\n'
        )
        tt = list(g.subjects(RDF.type, SL_TRIPLE_TERM))[0]
        assert list(g.objects(tt, RDF.subject)) == [URIRef(EX+'s')]

    def test_triple_term_deduplication(self, parser):
        g = parser.parse(
            'PREFIX ex: <http://example.org/>\n'
            'ex:r1 rdf:reifies <<( ex:s ex:p ex:o )>> .\n'
            'ex:r2 rdf:reifies <<( ex:s ex:p ex:o )>> .\n'
        )
        tt_nodes = list(g.subjects(RDF.type, SL_TRIPLE_TERM))
        assert len(tt_nodes) == 1

    def test_two_distinct_triple_terms(self, parser):
        g = parser.parse(
            'PREFIX ex: <http://example.org/>\n'
            'ex:r1 rdf:reifies <<( ex:s ex:p ex:o )>> .\n'
            'ex:r2 rdf:reifies <<( ex:a ex:b ex:c )>> .\n'
        )
        tt_nodes = list(g.subjects(RDF.type, SL_TRIPLE_TERM))
        assert len(tt_nodes) == 2


class TestReification:
    def test_reification_shorthand_as_subject(self, parser):
        g = parser.parse(
            'PREFIX ex: <http://example.org/>\n'
            '<< ex:s ex:p ex:o >> ex:q ex:z .\n'
        )
        reif_nodes = list(g.subjects(RDF.type, SL_REIFICATION))
        assert len(reif_nodes) == 1

    def test_reification_node_tagged(self, parser):
        g = parser.parse(
            'PREFIX ex: <http://example.org/>\n'
            '<< ex:s ex:p ex:o >> ex:q ex:z .\n'
        )
        reif = list(g.subjects(RDF.type, SL_REIFICATION))[0]
        tt_nodes = list(g.objects(reif, RDF_REIFIES))
        assert len(tt_nodes) == 1
        assert list(g.objects(tt_nodes[0], RDF.type)) == [SL_TRIPLE_TERM]


class TestAnnotations:
    def test_annotation_emits_main_triple(self, parser):
        g = parser.parse(
            'PREFIX ex: <http://example.org/>\n'
            'ex:s ex:p ex:o {| ex:certainty "0.9" |} .\n'
        )
        assert (URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o')) in g

    def test_annotation_creates_reification(self, parser):
        g = parser.parse(
            'PREFIX ex: <http://example.org/>\n'
            'ex:s ex:p ex:o {| ex:certainty "0.9" |} .\n'
        )
        reif_nodes = list(g.subjects(RDF.type, SL_REIFICATION))
        assert len(reif_nodes) == 1

    def test_annotation_triple_attached_to_reifier(self, parser):
        g = parser.parse(
            'PREFIX ex: <http://example.org/>\n'
            'ex:s ex:p ex:o {| ex:certainty "0.9" |} .\n'
        )
        reif = list(g.subjects(RDF.type, SL_REIFICATION))[0]
        vals = list(g.objects(reif, URIRef(EX+'certainty')))
        assert vals == [Literal('0.9')]

    def test_explicit_reifier(self, parser):
        g = parser.parse(
            'PREFIX ex: <http://example.org/>\n'
            'ex:s ex:p ex:o ~ ex:stmt {| ex:certainty "0.9" |} .\n'
        )
        assert (URIRef(EX+'stmt'), RDF_REIFIES, None) in [(s, p, None) for s, p, o in g]
        vals = list(g.objects(URIRef(EX+'stmt'), URIRef(EX+'certainty')))
        assert vals == [Literal('0.9')]

    def test_multiple_annotations(self, parser):
        g = parser.parse(
            'PREFIX ex: <http://example.org/>\n'
            'ex:s ex:p ex:o {| ex:a "1" ; ex:b "2" |} .\n'
        )
        reif = list(g.subjects(RDF.type, SL_REIFICATION))[0]
        ann_a = list(g.objects(reif, URIRef(EX+'a')))
        ann_b = list(g.objects(reif, URIRef(EX+'b')))
        assert ann_a == [Literal('1')]
        assert ann_b == [Literal('2')]


# ---------------------------------------------------------------------------
# RDF 1.2 version declaration parsing
# ---------------------------------------------------------------------------

class TestVersionDirective:
    def test_turtle_version_directive_ignored(self, parser):
        """@version "1.2" . is silently consumed; triples parse normally."""
        ttl = f'@version "1.2" .\n@prefix ex: <{EX}> .\nex:s ex:p ex:o .\n'
        g = parser.parse(ttl)
        assert (URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o')) in g

    def test_sparql_version_directive_ignored(self, parser):
        """VERSION "1.2" (no period) is silently consumed; triples parse normally."""
        ttl = f'VERSION "1.2"\n@prefix ex: <{EX}> .\nex:s ex:p ex:o .\n'
        g = parser.parse(ttl)
        assert (URIRef(EX+'s'), URIRef(EX+'p'), URIRef(EX+'o')) in g

    def test_version_directive_with_triple_terms(self, parser):
        """@version directive does not interfere with triple-term parsing."""
        RDF_REIFIES = URIRef('http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies')
        ttl = (
            '@version "1.2" .\n'
            f'@prefix ex: <{EX}> .\n'
            '@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .\n'
            'ex:stmt rdf:reifies <<( ex:alice ex:knows ex:bob )>> .\n'
        )
        g = parser.parse(ttl)
        from starlight.graph import StarlightGraph
        sg = StarlightGraph.from_rdflib(g)
        assert len(list(sg.triple_terms())) == 1

    def test_round_trip_preserves_version(self, parser):
        """Serialize with @version, re-parse, verify data intact."""
        from starlight.graph import StarlightGraph
        from starlight.model.triple import TripleTerm
        RDF_REIFIES = URIRef('http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies')
        sg = StarlightGraph()
        sg.bind('ex', EX)
        tt = TripleTerm(URIRef(EX+'alice'), URIRef(EX+'knows'), URIRef(EX+'bob'))
        sg.add((URIRef(EX+'stmt1'), RDF_REIFIES, tt))
        out = sg.serialize(format='turtle12')
        assert '@version "1.2" .' in out
        g2 = parser.parse(out)
        sg2 = StarlightGraph.from_rdflib(g2)
        assert sg2.has_triple_term(URIRef(EX+'alice'), URIRef(EX+'knows'), URIRef(EX+'bob'))


# ---------------------------------------------------------------------------
# Base URI resolution (RFC 3986)
# ---------------------------------------------------------------------------

class TestBaseURI:
    def test_fragment_relative(self, parser):
        """<#name> resolved against @base gives base + fragment."""
        ttl = (
            '@base <http://example.org/> .\n'
            '@prefix ex: <http://example.org/> .\n'
            '<#alice> ex:knows <#bob> .\n'
        )
        g = parser.parse(ttl)
        assert (URIRef('http://example.org/#alice'), URIRef(EX+'knows'), URIRef('http://example.org/#bob')) in g

    def test_path_relative(self, parser):
        """A path-relative IRI is resolved against the base."""
        ttl = (
            '@base <http://example.org/data/> .\n'
            '@prefix ex: <http://example.org/> .\n'
            '<alice> ex:knows <bob> .\n'
        )
        g = parser.parse(ttl)
        assert (URIRef('http://example.org/data/alice'), URIRef(EX+'knows'), URIRef('http://example.org/data/bob')) in g

    def test_dot_dot_navigation(self, parser):
        """<../other> navigates up from the base path."""
        ttl = (
            '@base <http://example.org/a/b/> .\n'
            '@prefix ex: <http://example.org/> .\n'
            '<../../alice> ex:knows ex:bob .\n'
        )
        g = parser.parse(ttl)
        assert (URIRef('http://example.org/alice'), URIRef(EX+'knows'), URIRef(EX+'bob')) in g

    def test_multiple_base_declarations(self, parser):
        """Each @base affects only the triples that follow it."""
        ttl = (
            '@base <http://example.org/a/> .\n'
            '@prefix ex: <http://example.org/> .\n'
            '<x> ex:type ex:A .\n'
            '@base <http://example.org/b/> .\n'
            '<y> ex:type ex:B .\n'
        )
        g = parser.parse(ttl)
        assert (URIRef('http://example.org/a/x'), URIRef(EX+'type'), URIRef(EX+'A')) in g
        assert (URIRef('http://example.org/b/y'), URIRef(EX+'type'), URIRef(EX+'B')) in g

    def test_second_base_relative_to_first(self, parser):
        """A relative @base is resolved against the active base."""
        ttl = (
            '@base <http://example.org/> .\n'
            '@prefix ex: <http://example.org/> .\n'
            '@base <sub/> .\n'
            '<item> ex:type ex:Thing .\n'
        )
        g = parser.parse(ttl)
        assert (URIRef('http://example.org/sub/item'), URIRef(EX+'type'), URIRef(EX+'Thing')) in g

    def test_absolute_iri_unaffected_by_base(self, parser):
        """Absolute IRIs are never modified by @base."""
        ttl = (
            '@base <http://example.org/> .\n'
            '<http://other.org/alice> <http://other.org/knows> <http://other.org/bob> .\n'
        )
        g = parser.parse(ttl)
        assert (
            URIRef('http://other.org/alice'),
            URIRef('http://other.org/knows'),
            URIRef('http://other.org/bob'),
        ) in g

    def test_g_base_set_to_last_base(self, parser):
        """g.base is set to the last active @base declaration."""
        ttl = (
            '@base <http://example.org/a/> .\n'
            '@base <http://example.org/b/> .\n'
            '<x> <http://example.org/p> <http://example.org/o> .\n'
        )
        g = parser.parse(ttl)
        assert str(g.base) == 'http://example.org/b/'
