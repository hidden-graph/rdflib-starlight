"""
Tests for starlight.backends.native.rewrite_12_to_backend.

Covers the rdf-star backend's handling of SPARQL 1.2 annotation syntax
and the rdf-1.2 pass-through behaviour.
"""

import pytest
from starlight.backends.native import rewrite_12_to_backend


# ---------------------------------------------------------------------------
# rdf-1.2 backend — always passes through unchanged
# ---------------------------------------------------------------------------

class TestRdf12Backend:
    def test_passthrough_plain_sparql(self):
        q = "SELECT ?s ?p ?o WHERE { ?s ?p ?o . }"
        assert rewrite_12_to_backend(q, 'rdf-1.2') == q

    def test_passthrough_triple_term_syntax(self):
        q = "SELECT ?pred WHERE { <<( :a :b :c )>> ?pred ?val . }"
        assert rewrite_12_to_backend(q, 'rdf-1.2') == q

    def test_passthrough_annotation_block(self):
        q = "SELECT ?c WHERE { :a :b :c {| :confidence ?c |} . }"
        assert rewrite_12_to_backend(q, 'rdf-1.2') == q

    def test_passthrough_annotation_subject(self):
        q = "SELECT ?c WHERE { << :a :b :c >> :confidence ?c . }"
        assert rewrite_12_to_backend(q, 'rdf-1.2') == q

    def test_passthrough_tilde(self):
        q = "SELECT ?r WHERE { :a :b :c ~ ?r . }"
        assert rewrite_12_to_backend(q, 'rdf-1.2') == q

    def test_passthrough_subject_function(self):
        q = "SELECT (SUBJECT(?tt) AS ?s) WHERE { ?x :knows ?tt . }"
        assert rewrite_12_to_backend(q, 'rdf-1.2') == q

    def test_passthrough_is_triple_term(self):
        q = "SELECT ?tt WHERE { ?s ?p ?tt . FILTER(isTripleTerm(?tt)) }"
        assert rewrite_12_to_backend(q, 'rdf-1.2') == q


# ---------------------------------------------------------------------------
# rdf-star backend — <<( )>> → << >>
# ---------------------------------------------------------------------------

class TestRdfStarTripleTerm:
    def test_simple_triple_term_rewritten(self):
        q = "SELECT ?pred WHERE { <<( :a :b :c )>> ?pred ?val . }"
        out = rewrite_12_to_backend(q, 'rdf-star')
        assert '<<(' not in out
        assert '<< :a :b :c >>' in out

    def test_nested_triple_term_rewritten(self):
        q = "SELECT ?p WHERE { <<( <<( :a :b :c )>> :p :o )>> :pred ?x . }"
        out = rewrite_12_to_backend(q, 'rdf-star')
        assert '<<(' not in out
        assert '<< << :a :b :c >> :p :o >>' in out

    def test_no_change_when_no_triple_term(self):
        q = "SELECT ?s WHERE { ?s ?p ?o . }"
        assert rewrite_12_to_backend(q, 'rdf-star') == q

    def test_annotation_subject_passed_through(self):
        # << s p o >> pred obj is already valid Jena RDF-star syntax
        q = "SELECT ?c WHERE { << :a :b :c >> :confidence ?c . }"
        out = rewrite_12_to_backend(q, 'rdf-star')
        assert '<< :a :b :c >> :confidence ?c' in out


# ---------------------------------------------------------------------------
# rdf-star backend — {| |} annotation blocks
# ---------------------------------------------------------------------------

class TestRdfStarAnnotationBlocks:
    def test_single_annotation_pair(self):
        q = "SELECT ?c WHERE { :a :b :c {| :confidence ?c |} . }"
        out = rewrite_12_to_backend(q, 'rdf-star')
        assert '{|' not in out
        assert ':a :b :c' in out
        assert '<< :a :b :c >> :confidence ?c' in out

    def test_multiple_annotation_pairs(self):
        q = "SELECT ?c ?src WHERE { :a :b :c {| :confidence ?c ; :source ?src |} . }"
        out = rewrite_12_to_backend(q, 'rdf-star')
        assert '{|' not in out
        assert '<< :a :b :c >> :confidence ?c' in out
        assert '<< :a :b :c >> :source ?src' in out

    def test_base_triple_preserved(self):
        q = "SELECT ?c WHERE { :a :b :c {| :confidence ?c |} . }"
        out = rewrite_12_to_backend(q, 'rdf-star')
        assert ':a :b :c' in out

    def test_variable_terms_in_annotation(self):
        q = "SELECT ?c WHERE { ?s ?p ?o {| :confidence ?c |} . }"
        out = rewrite_12_to_backend(q, 'rdf-star')
        assert '{|' not in out
        assert '<< ?s ?p ?o >> :confidence ?c' in out


# ---------------------------------------------------------------------------
# rdf-star backend — ~?r raises NotImplementedError
# ---------------------------------------------------------------------------

class TestRdfStarTilde:
    def test_tilde_raises_not_implemented(self):
        q = "SELECT ?r WHERE { :a :b :c ~ ?r . }"
        with pytest.raises(NotImplementedError, match="~?r"):
            rewrite_12_to_backend(q, 'rdf-star')

    def test_tilde_error_mentions_rdf12_backend(self):
        q = "SELECT ?r WHERE { :a :b :c ~ ?r . }"
        with pytest.raises(NotImplementedError, match="rdf-1.2"):
            rewrite_12_to_backend(q, 'rdf-star')


# ---------------------------------------------------------------------------
# rdf-star backend — SUBJECT/PREDICATE/OBJECT, isTripleTerm passed through
# ---------------------------------------------------------------------------

class TestRdfStarPassthroughFunctions:
    def test_subject_function_passed_through(self):
        q = "SELECT (SUBJECT(?tt) AS ?s) WHERE { ?x :knows ?tt . }"
        out = rewrite_12_to_backend(q, 'rdf-star')
        assert 'SUBJECT(?tt)' in out

    def test_is_triple_term_passed_through(self):
        q = "SELECT ?tt WHERE { ?s ?p ?tt . FILTER(isTripleTerm(?tt)) }"
        out = rewrite_12_to_backend(q, 'rdf-star')
        assert 'isTripleTerm(?tt)' in out
