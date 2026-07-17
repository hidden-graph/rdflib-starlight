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

from starlight.graph.starlight_graph import StarlightGraph, _check_native_version_conformance
from starlight.graph.starlight_dataset import StarlightDataset
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

    def test_version_1_1_with_triple_term_warns(self):
        # "1.1" means plain RDF 1.1 syntax/semantics - it excludes triple
        # terms/dirLangString at least as strictly as "1.2-basic" does, so a
        # query declaring "1.1" but using a triple term should warn too, not
        # just "1.2-basic".
        g = StarlightGraph()
        q = f"""VERSION "1.1"
            PREFIX : <{EX}>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?s WHERE {{ ?s rdf:reifies <<( :a :b :c )>> . }}
        """
        with pytest.warns(RDF12ConformanceWarning, match='1.1'):
            g.query(q)


class TestNativeBackendVersionConformance:
    """StarlightGraph(backend='rdf-1.2') sends SPARQL straight through to a
    real endpoint via HTTP with zero rewriting (correct - Fuseki/Oxigraph
    understand VERSION natively), which means query()/update() never call
    rewrite_sparql12_to_11 and so never ran this check at all until fixed.

    Confirmed live 2026-07-17 against Fuseki 5.5.0 and Oxigraph: both
    execute a VERSION "1.2-basic" + <<( )>> query normally (HTTP 200) with
    no warning or error signal anywhere in the response - so without this
    fix, a native-backend StarlightGraph would silently never emit
    RDF12ConformanceWarning for the identical query the default in-memory
    backend does warn on, an inconsistency this project otherwise takes
    care to avoid (see tests/integration/test_cross_backend_parity.py).

    _check_native_version_conformance() is pure Python logic with no network
    dependency (the network call happens after it, in _native_query()/
    http_update()), so it's tested directly here rather than requiring a
    live backend.
    """

    def test_1_2_basic_with_triple_term_warns(self):
        q = f"""VERSION "1.2-basic"
            PREFIX : <{EX}>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT ?s WHERE {{ ?s rdf:reifies <<( :a :b :c )>> . }}
        """
        with pytest.warns(RDF12ConformanceWarning, match='1.2-basic'):
            _check_native_version_conformance(q)

    def test_1_2_basic_without_triple_term_does_not_warn(self, recwarn):
        q = f'VERSION "1.2-basic"\nPREFIX : <{EX}>\nSELECT * WHERE {{ ?s ?p ?o }}'
        _check_native_version_conformance(q)
        assert not any(issubclass(w.category, RDF12ConformanceWarning) for w in recwarn.list)

    def test_no_version_directive_does_not_warn(self, recwarn):
        _check_native_version_conformance('SELECT * WHERE { ?s ?p ?o }')
        assert not any(issubclass(w.category, RDF12ConformanceWarning) for w in recwarn.list)

    def test_unrecognized_version_label_warns(self):
        with pytest.warns(RDF12ConformanceWarning, match='unrecognized'):
            _check_native_version_conformance('VERSION "9.9"\nSELECT * WHERE { ?s ?p ?o }')


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

    def test_1_1_with_triple_term_warns(self):
        # "1.1" excludes RDF 1.2 features at least as strictly as
        # "1.2-basic" - see TestSparqlVersionDirective.test_version_1_1_with_triple_term_warns.
        data = f"""@version "1.1" .
            @prefix : <{EX}> .
            :stmt rdf:reifies <<( :bob :knows :carol )>> .
        """
        g = StarlightGraph()
        with pytest.warns(RDF12ConformanceWarning, match='1.1'):
            g.parse(data=data, format='turtle12')


class TestNTriplesNQuadsVersionDirective:
    """N-Triples/N-Quads: the VERSION line was already recognized by the
    parser but only to discard it like a comment, never extracting the
    label - found by asking "does our VERSION support extend to other
    formats?" and actually checking, same day as the Turtle/SPARQL fix."""

    def test_1_2_basic_with_triple_term_warns_nt(self):
        data = (
            'VERSION "1.2-basic"\n'
            f'<{EX}stmt> <http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies> '
            f'<<( <{EX}a> <{EX}b> <{EX}c> )>> .\n'
        )
        g = StarlightGraph()
        with pytest.warns(RDF12ConformanceWarning, match='1.2-basic'):
            g.parse(data=data, format='nt12')

    def test_1_2_basic_with_triple_term_warns_nq(self):
        data = (
            'VERSION "1.2-basic"\n'
            f'<{EX}stmt> <http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies> '
            f'<<( <{EX}a> <{EX}b> <{EX}c> )>> <{EX}g> .\n'
        )
        g = StarlightGraph()
        with pytest.warns(RDF12ConformanceWarning, match='1.2-basic'):
            g.parse(data=data, format='nq12')

    def test_no_version_directive_does_not_warn(self, recwarn):
        data = f'<{EX}s> <{EX}p> <{EX}o> .\n'
        g = StarlightGraph()
        g.parse(data=data, format='nt12')
        assert not any(issubclass(w.category, RDF12ConformanceWarning) for w in recwarn.list)

    def test_version_1_2_full_does_not_warn(self, recwarn):
        data = (
            'VERSION "1.2"\n'
            f'<{EX}stmt> <http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies> '
            f'<<( <{EX}a> <{EX}b> <{EX}c> )>> .\n'
        )
        g = StarlightGraph()
        g.parse(data=data, format='nt12')
        assert not any(issubclass(w.category, RDF12ConformanceWarning) for w in recwarn.list)

    def test_dataset_nq12_warns(self):
        data = (
            'VERSION "1.2-basic"\n'
            f'<{EX}stmt> <http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies> '
            f'<<( <{EX}a> <{EX}b> <{EX}c> )>> <{EX}g> .\n'
        )
        ds = StarlightDataset()
        with pytest.warns(RDF12ConformanceWarning, match='1.2-basic'):
            ds.parse(data=data, format='nq12')


class TestTrigVersionDirective:
    """TriG: the document-level VERSION directive was silently dropped
    entirely - the per-GRAPH-block Turtle parser calls never surfaced it to
    either StarlightGraph.parse() or StarlightDataset.parse()."""

    def test_starlight_graph_trig12_warns(self):
        data = f"""VERSION "1.2-basic"
            PREFIX : <{EX}>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            GRAPH :g1 {{
              :stmt rdf:reifies <<( :bob :knows :carol )>> .
            }}
        """
        g = StarlightGraph()
        with pytest.warns(RDF12ConformanceWarning, match='1.2-basic'):
            g.parse(data=data, format='trig12')

    def test_starlight_dataset_trig12_warns(self):
        data = f"""VERSION "1.2-basic"
            PREFIX : <{EX}>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            GRAPH :g1 {{
              :stmt rdf:reifies <<( :bob :knows :carol )>> .
            }}
        """
        ds = StarlightDataset()
        with pytest.warns(RDF12ConformanceWarning, match='1.2-basic'):
            ds.parse(data=data, format='trig12')

    def test_no_version_directive_does_not_warn(self, recwarn):
        data = f"""PREFIX : <{EX}>
            GRAPH :g1 {{ :s :p :o . }}
        """
        g = StarlightGraph()
        g.parse(data=data, format='trig12')
        assert not any(issubclass(w.category, RDF12ConformanceWarning) for w in recwarn.list)

    def test_version_1_2_full_does_not_warn(self, recwarn):
        data = f"""VERSION "1.2"
            PREFIX : <{EX}>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            GRAPH :g1 {{
              :stmt rdf:reifies <<( :bob :knows :carol )>> .
            }}
        """
        g = StarlightGraph()
        g.parse(data=data, format='trig12')
        assert not any(issubclass(w.category, RDF12ConformanceWarning) for w in recwarn.list)
