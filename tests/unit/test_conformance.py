"""
End-to-end tests for VERSION-directive handling and RDF12ConformanceWarning.

RDF 1.2 Concepts sec 2.1 and SPARQL 1.2 Query sec 4.3 define three version
labels - "1.2" (full), "1.2-basic" (excludes triple terms and dirLangString),
"1.1" (legacy) - and explicitly say the VERSION directive is only a hint: a
processor "is not required to reject features that are outside the
announced version (but could signal them with a warning)". Starlight signals
via RDF12ConformanceWarning, never a hard error - see
starlight/model/conformance.py.

Also regression-tests a real bug found while checking this against the live
spec text: a SPARQL 1.2 query starting with VERSION "1.2" (the spec's own
example form) previously raised a ParseException on the in-memory backend,
since sparql12_to_11.py never stripped the directive before handing the
query to rdflib's SPARQL 1.1 parser.
"""

import pytest

from starlight.graph.starlight_graph import StarlightGraph
from starlight.model.conformance import RDF12ConformanceWarning

EX = 'http://example.org/'


class TestSparqlVersionDirective:
    def test_version_directive_no_longer_raises(self):
        # The exact motivating bug: this is valid SPARQL 1.2 syntax (the
        # spec's own example form) and previously raised ParseException.
        g = StarlightGraph()
        r = g.query('VERSION "1.2"\nSELECT * WHERE { ?s ?p ?o }')
        assert list(r) == []

    def test_version_directive_single_quoted(self):
        g = StarlightGraph()
        r = g.query("VERSION '1.2'\nSELECT * WHERE { ?s ?p ?o }")
        assert list(r) == []

    def test_version_1_2_basic_with_triple_term_warns(self):
        g = StarlightGraph()
        q = f"""VERSION "1.2-basic"
            PREFIX : <{EX}>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?s WHERE {{ ?s rdf:reifies <<( :a :b :c )>> . }}
        """
        with pytest.warns(RDF12ConformanceWarning, match='1.2-basic'):
            g.query(q)

    def test_version_1_2_basic_without_triple_term_does_not_warn(self, recwarn):
        g = StarlightGraph()
        q = f'VERSION "1.2-basic"\nPREFIX : <{EX}>\nSELECT * WHERE {{ ?s ?p ?o }}'
        g.query(q)
        assert not any(issubclass(w.category, RDF12ConformanceWarning) for w in recwarn.list)

    def test_version_1_2_full_with_triple_term_does_not_warn(self, recwarn):
        g = StarlightGraph()
        q = f"""VERSION "1.2"
            PREFIX : <{EX}>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?s WHERE {{ ?s rdf:reifies <<( :a :b :c )>> . }}
        """
        g.query(q)
        assert not any(issubclass(w.category, RDF12ConformanceWarning) for w in recwarn.list)

    def test_unrecognized_version_label_warns(self):
        g = StarlightGraph()
        q = 'VERSION "9.9"\nSELECT * WHERE { ?s ?p ?o }'
        with pytest.warns(RDF12ConformanceWarning, match='unrecognized'):
            g.query(q)

    def test_no_version_directive_does_not_warn(self, recwarn):
        g = StarlightGraph()
        g.query('SELECT * WHERE { ?s ?p ?o }')
        assert not any(issubclass(w.category, RDF12ConformanceWarning) for w in recwarn.list)


class TestTurtleVersionDirective:
    def test_1_2_basic_with_triple_term_warns(self):
        data = f"""@version "1.2-basic" .
            @prefix : <{EX}> .
            :stmt rdf:reifies <<( :bob :knows :carol )>> .
        """
        g = StarlightGraph()
        with pytest.warns(RDF12ConformanceWarning, match='1.2-basic'):
            g.parse(data=data, format='turtle12')

    def test_1_2_full_with_triple_term_does_not_warn(self, recwarn):
        data = f"""@version "1.2" .
            @prefix : <{EX}> .
            :stmt rdf:reifies <<( :bob :knows :carol )>> .
        """
        g = StarlightGraph()
        g.parse(data=data, format='turtle12')
        assert not any(issubclass(w.category, RDF12ConformanceWarning) for w in recwarn.list)

    def test_no_version_directive_does_not_warn(self, recwarn):
        data = f'@prefix : <{EX}> .\n:s :p :o .\n'
        g = StarlightGraph()
        g.parse(data=data, format='turtle12')
        assert not any(issubclass(w.category, RDF12ConformanceWarning) for w in recwarn.list)

    def test_unrecognized_version_label_warns(self):
        data = f'@version "9.9" .\n@prefix : <{EX}> .\n:s :p :o .\n'
        g = StarlightGraph()
        with pytest.warns(RDF12ConformanceWarning, match='unrecognized'):
            g.parse(data=data, format='turtle12')
