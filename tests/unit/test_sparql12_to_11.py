from starlight.query import rewrite_sparql12_to_11


def test_rewrite_returns_unchanged_query_without_triple_terms():
    query = "SELECT * WHERE { ?s ?p ?o . }"
    assert rewrite_sparql12_to_11(query) == query


def test_rewrite_object_triple_term_in_basic_graph_pattern():
    query = """
PREFIX : <http://example.org/>
SELECT * WHERE {
  ?stmt rdf:reifies <<( :bob :knows :carol )>> .
}
""".strip()

    rewritten = rewrite_sparql12_to_11(query)

    assert "?stmt rdf:reifies ?__tt0 ." in rewritten
    assert "?__tt0 <http://www.w3.org/1999/02/22-rdf-syntax-ns#subject> :bob ." in rewritten
    assert "?__tt0 <http://www.w3.org/1999/02/22-rdf-syntax-ns#predicate> :knows ." in rewritten
    assert "?__tt0 <http://www.w3.org/1999/02/22-rdf-syntax-ns#object> :carol ." in rewritten


def test_rewrite_subject_triple_term_in_basic_graph_pattern():
    query = """
PREFIX : <http://example.org/>
SELECT * WHERE {
  <<( :bob :knows :carol )>> :verifiedBy ?team .
}
""".strip()

    rewritten = rewrite_sparql12_to_11(query)

    assert "?__tt0 :verifiedBy ?team ." in rewritten
    assert "?__tt0 <http://www.w3.org/1999/02/22-rdf-syntax-ns#subject> :bob ." in rewritten


def test_rewrite_nested_triple_term():
    query = """
PREFIX : <http://example.org/>
SELECT * WHERE {
  ?stmt rdf:reifies <<( <<( :a :b :c )>> :p :o )>> .
}
""".strip()

    rewritten = rewrite_sparql12_to_11(query)

    assert "?stmt rdf:reifies ?__tt1 ." in rewritten
    assert "?__tt0 <http://www.w3.org/1999/02/22-rdf-syntax-ns#subject> :a ." in rewritten
    assert "?__tt1 <http://www.w3.org/1999/02/22-rdf-syntax-ns#subject> ?__tt0 ." in rewritten


def test_rewrite_keeps_optional_scope_local():
    query = """
PREFIX : <http://example.org/>
SELECT * WHERE {
  OPTIONAL {
    ?stmt rdf:reifies <<( ?s :p ?o )>> .
  }
}
""".strip()

    rewritten = rewrite_sparql12_to_11(query)

    optional_start = rewritten.index("OPTIONAL {")
    optional_end = rewritten.index("}", optional_start)
    optional_block = rewritten[optional_start:optional_end]
    assert "?stmt rdf:reifies ?__tt0 ." in optional_block
    assert "?__tt0 <http://www.w3.org/1999/02/22-rdf-syntax-ns#subject> ?s ." in optional_block