from starlight.query import rewrite_sparql12_to_11


def test_rewrite_returns_unchanged_query_without_triple_terms():
    query = "SELECT * WHERE { ?s ?p ?o . }"
    assert rewrite_sparql12_to_11(query) == query


def test_rewrite_object_triple_term_in_basic_graph_pattern():
    # <<( :bob :knows :carol )>> is fully ground (no variables), so it is
    # constructed as a value via BIND(tt_hash(...)) rather than matched via
    # rdf:subject/predicate/object patterns - a query about a triple that
    # doesn't exist must not cause it to be written/registered, mirroring how
    # an IRI that doesn't exist in the graph is still a valid term to ask
    # about. See _rewrite_triple_term's "elif all_ground" branch.
    query = """
PREFIX : <http://example.org/>
SELECT * WHERE {
  ?stmt rdf:reifies <<( :bob :knows :carol )>> .
}
""".strip()

    rewritten = rewrite_sparql12_to_11(query)

    assert "BIND(<https://github.com/hidden-graph/rdflib-starlight/ns/tt#fn/hash>(:bob, :knows, :carol) AS ?__tt0)" in rewritten
    assert "?stmt rdf:reifies ?__tt0 ." in rewritten


def test_rewrite_subject_triple_term_in_basic_graph_pattern():
    # Ground triple term in subject position: same BIND-based construction
    # as the object-position case above.
    query = """
PREFIX : <http://example.org/>
SELECT * WHERE {
  <<( :bob :knows :carol )>> :verifiedBy ?team .
}
""".strip()

    rewritten = rewrite_sparql12_to_11(query)

    assert "BIND(<https://github.com/hidden-graph/rdflib-starlight/ns/tt#fn/hash>(:bob, :knows, :carol) AS ?__tt0)" in rewritten
    assert "?__tt0 :verifiedBy ?team ." in rewritten


def test_rewrite_nested_triple_term():
    # Both the inner and outer triple terms are fully ground, so each gets
    # its own BIND; the outer BIND references the inner's variable.
    query = """
PREFIX : <http://example.org/>
SELECT * WHERE {
  ?stmt rdf:reifies <<( <<( :a :b :c )>> :p :o )>> .
}
""".strip()

    rewritten = rewrite_sparql12_to_11(query)

    assert "?stmt rdf:reifies ?__tt1 ." in rewritten
    assert "BIND(<https://github.com/hidden-graph/rdflib-starlight/ns/tt#fn/hash>(:a, :b, :c) AS ?__tt0)" in rewritten
    assert "BIND(<https://github.com/hidden-graph/rdflib-starlight/ns/tt#fn/hash>(?__tt0, :p, :o) AS ?__tt1)" in rewritten


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


def test_rewrite_subject_function_in_select_projection_without_where_keyword():
    # WHERE is optional in SPARQL for SELECT ("SELECT (...) { }" is valid).
    # _rewrite_triple_functions used to locate its injection point by
    # searching for literal "WHERE {" text with no fallback, silently
    # dropping the injected BIND when that keyword was absent - leaving
    # ?__tt0 permanently unbound instead of raising or working. Fixed by
    # _find_group_pattern_start, shared with the ground-TRIPLE()-as-value
    # BIND injection (see test_dataset_query.py::TestAsk::
    # test_ask_false_when_no_match for that sibling fix).
    #
    # Injects a BIND calling the registered tt:fn/subject accessor function,
    # not a rdf:subject *match* pattern (which only works when ?tt's value
    # was already written to some graph - see the module-level comment
    # above _TT_ACCESSOR_FN in sparql12_to_11.py for why a real function is
    # needed instead).
    query = "SELECT (SUBJECT(?tt) AS ?s) { }"
    rewritten = rewrite_sparql12_to_11(query)

    assert "BIND(<https://github.com/hidden-graph/rdflib-starlight/ns/tt#fn/subject>(?tt) AS ?__tt0)" in rewritten

    from rdflib.plugins.sparql.parser import parseQuery
    parseQuery(rewritten)  # must not raise


def test_rewrite_accepts_dollar_sigil_for_accessor_functions():
    # $this/$value are the sigil convention SHACL-SPARQL constraints use for
    # focus-node/value bindings; $var and ?var are interchangeable valid SPARQL.
    query = """
PREFIX : <http://example.org/>
SELECT $this $value WHERE {
  FILTER(PREDICATE($value) != :knows)
}
""".strip()

    rewritten = rewrite_sparql12_to_11(query)

    assert "$value" in rewritten
    assert "PREDICATE(" not in rewritten
    assert "BIND(<https://github.com/hidden-graph/rdflib-starlight/ns/tt#fn/predicate>($value) AS ?__tt0)" in rewritten


def test_rewrite_subject_of_triple_term_literal_extracts_component_directly():
    # SUBJECT(<<( s p o )>>) - the accessor applied directly to a literal, not
    # a bound variable - needs no store lookup at all (unlike SUBJECT(?tt)):
    # the components are already spelled out right there in the query text,
    # so this desugars straight to the subject term, with no injected
    # rdf:subject binding pattern. Found missing via property-based fuzz
    # testing 2026-07-17 (_TRIPLE_FUNC_RE only ever matched a bare-variable
    # argument); see _rewrite_triple_accessor_literals.
    query = "PREFIX : <http://example.org/>\nSELECT (SUBJECT(<<( :a :b :c )>>) AS ?s) WHERE {}"

    rewritten = rewrite_sparql12_to_11(query)

    assert "SUBJECT(" not in rewritten
    assert rewritten == "PREFIX : <http://example.org/>\nSELECT (:a AS ?s) WHERE {}"

    from rdflib.plugins.sparql.parser import parseQuery
    parseQuery(rewritten)  # must not raise


def test_rewrite_predicate_and_object_of_triple_constructor_literal():
    # Same as above but via the TRIPLE(...) constructor spelling, and for
    # PREDICATE()/OBJECT() rather than SUBJECT() - TRIPLE(...) is desugared to
    # <<( )>> before _rewrite_triple_accessor_literals runs, so both spellings
    # are handled uniformly.
    query = "PREFIX : <http://example.org/>\nSELECT (PREDICATE(TRIPLE(:a, :b, :c)) AS ?p) (OBJECT(TRIPLE(:a, :b, :c)) AS ?o) WHERE {}"

    rewritten = rewrite_sparql12_to_11(query)

    assert "TRIPLE(" not in rewritten
    assert "PREDICATE(" not in rewritten
    assert "OBJECT(" not in rewritten
    assert ":b AS ?p" in rewritten
    assert ":c AS ?o" in rewritten


def test_rewrite_subject_of_nested_ground_triple_term_literal_still_constructs():
    # The extracted component can itself be a triple term (nesting) - it must
    # still go through the normal ground-value BIND construction path (see
    # test_rewrite_nested_triple_term), not leak as raw <<( )>> text.
    query = (
        "PREFIX : <http://example.org/>\n"
        "SELECT (SUBJECT(<<( <<( :a :b :c )>> :p :o )>>) AS ?s) WHERE {}"
    )

    rewritten = rewrite_sparql12_to_11(query)

    assert "SUBJECT(" not in rewritten
    assert "<<(" not in rewritten
    assert "BIND(<https://github.com/hidden-graph/rdflib-starlight/ns/tt#fn/hash>(:a, :b, :c) AS ?__tt0)" in rewritten
    assert "SELECT (?__tt0 AS ?s)" in rewritten

    from rdflib.plugins.sparql.parser import parseQuery
    parseQuery(rewritten)  # must not raise


def test_rewrite_object_of_triple_term_literal_with_variable_component():
    # A variable inside the literal argument passes through unchanged - this
    # is a pure textual extraction, not a match/lookup.
    query = (
        "PREFIX : <http://example.org/>\n"
        "ASK { FILTER(OBJECT(<<( ?s :p :c )>>) = :c) }"
    )

    rewritten = rewrite_sparql12_to_11(query)

    assert rewritten == "PREFIX : <http://example.org/>\nASK { FILTER(:c = :c) }"


def test_rewrite_accepts_dollar_sigil_for_is_triple_term():
    query = """
PREFIX : <http://example.org/>
SELECT $this $value WHERE {
  FILTER(isTripleTerm($value))
}
""".strip()

    rewritten = rewrite_sparql12_to_11(query)

    assert "isTripleTerm" not in rewritten
    assert "STRSTARTS(STR($value)" in rewritten


def test_construct_bind_for_new_triple_term_placed_after_where_patterns():
    # A BIND injected to mint a triple-term value used only in the CONSTRUCT
    # template must land *after* the WHERE clause's own patterns when its
    # components (here ?z) are bound by those patterns, not before - SPARQL
    # silently drops a BIND's result if its inputs aren't bound yet, it
    # doesn't error, so a misplaced BIND fails quietly rather than loudly.
    query = """
PREFIX : <http://example.org/>
CONSTRUCT {
  ?this :reach ?z .
  ?this :witness <<( ?this :reach ?z )>> .
}
WHERE {
  ?this :reach ?y .
  ?y :reach ?z .
}
""".strip()

    rewritten = rewrite_sparql12_to_11(query)

    where_start = rewritten.index("WHERE {")
    where_body = rewritten[where_start:]
    bind_pos = where_body.index("BIND(")
    pattern_pos = where_body.index("?this :reach ?y")
    assert pattern_pos < bind_pos, "BIND must come after the patterns that bind its inputs"


# ---------------------------------------------------------------------------
# isTRIPLE() / TRIPLE(s, p, o) — SPARQL 1.2 spec-name aliases
# ---------------------------------------------------------------------------

def test_rewrite_accepts_is_triple_spec_alias():
    query = """
PREFIX : <http://example.org/>
SELECT * WHERE {
  ?sub ?pred ?t .
  FILTER(isTRIPLE(?t))
}
""".strip()

    rewritten = rewrite_sparql12_to_11(query)

    assert "isTRIPLE" not in rewritten
    assert "STRSTARTS(STR(?t)" in rewritten


def test_rewrite_triple_constructor_in_bind():
    # The spec's own worked example (SPARQL 1.2 Query 17.4.6) uses BIND with
    # <<( )>> syntax for exactly this; TRIPLE(...) must desugar identically.
    query = """
PREFIX :   <http://example.org/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
SELECT ?s ?date WHERE {
  ?s ?p ?o .
  BIND( TRIPLE(?s, ?p, ?o) AS ?tt )
  :myreifier rdf:reifies ?tt .
  :myreifier :tripleAdded ?date .
}
""".strip()

    literal_form = query.replace("TRIPLE(?s, ?p, ?o)", "<<( ?s ?p ?o )>>")

    assert rewrite_sparql12_to_11(query) == rewrite_sparql12_to_11(literal_form)
    assert "TRIPLE(" not in rewrite_sparql12_to_11(query)


def test_rewrite_triple_constructor_in_graph_pattern_position():
    # TRIPLE(:bob, :knows, :carol) desugars to <<( :bob :knows :carol )>>,
    # which is fully ground - so, like the <<( )>> spelling, it constructs a
    # BIND'd value rather than matching-pattern text (see
    # test_rewrite_object_triple_term_in_basic_graph_pattern).
    query = """
PREFIX :   <http://example.org/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
SELECT ?stmt WHERE {
  ?stmt rdf:reifies TRIPLE(:bob, :knows, :carol) .
}
""".strip()

    rewritten = rewrite_sparql12_to_11(query)

    assert "TRIPLE(" not in rewritten
    assert "BIND(<https://github.com/hidden-graph/rdflib-starlight/ns/tt#fn/hash>(:bob, :knows, :carol) AS ?__tt0)" in rewritten
    assert "?stmt rdf:reifies ?__tt0 ." in rewritten


def test_rewrite_nested_triple_constructor_calls():
    query = """
PREFIX : <http://example.org/>
SELECT * WHERE {
  ?r rdf:reifies TRIPLE(:alice, :believes, TRIPLE(:bob, :knows, :dave)) .
}
""".strip()

    rewritten = rewrite_sparql12_to_11(query)

    assert "TRIPLE(" not in rewritten
    assert "BIND(<https://github.com/hidden-graph/rdflib-starlight/ns/tt#fn/hash>(:bob, :knows, :dave) AS ?__tt0)" in rewritten
    assert "BIND(<https://github.com/hidden-graph/rdflib-starlight/ns/tt#fn/hash>(:alice, :believes, ?__tt0) AS ?__tt1)" in rewritten
    assert "?r rdf:reifies ?__tt1 ." in rewritten


def test_rewrite_triple_constructor_mints_in_construct_template():
    # Reuses the CONSTRUCT-template minting path (BIND with the internal hash
    # function) exactly as the literal <<( )>> spelling does, since TRIPLE()
    # desugars to it before construct-template handling runs.
    query = """
PREFIX : <http://example.org/>
CONSTRUCT {
  ?this :reach ?z .
  ?this :witness TRIPLE(?this, :reach, ?z) .
}
WHERE {
  ?this :reach ?y .
  ?y :reach ?z .
}
""".strip()

    rewritten = rewrite_sparql12_to_11(query)

    assert "TRIPLE(" not in rewritten
    assert "BIND(<https://github.com/hidden-graph/rdflib-starlight/ns/tt#fn/hash>(" in rewritten


def test_triple_constructor_wrong_arity_raises():
    import pytest
    query = "SELECT * WHERE { ?s ?p ?o . FILTER(?o = TRIPLE(?s, ?p)) }"
    with pytest.raises(ValueError, match="exactly 3 arguments"):
        rewrite_sparql12_to_11(query)


# ---------------------------------------------------------------------------
# Regressions found via a live three-way (in-memory / Oxigraph / Fuseki)
# behavior comparison, 2026-07-16 — see docs/future_enhancements.md.
# ---------------------------------------------------------------------------

def test_triple_bare_in_select_projection_places_patterns_in_where():
    # TRIPLE(...) used directly in a SELECT projection, no BIND, no other
    # <<( )>> anywhere in the query - all three components are ground, so
    # this constructs a value via BIND(tt_hash(...)) (see
    # test_rewrite_object_triple_term_in_basic_graph_pattern). That BIND must
    # land *inside* the WHERE clause, not after its closing brace (which
    # previously produced syntactically invalid SPARQL - a ParseException,
    # not just a wrong answer).
    query = "SELECT (TRIPLE(<http://example.org/a>, <http://example.org/b>, <http://example.org/c>) AS ?t) WHERE {}"
    rewritten = rewrite_sparql12_to_11(query)

    where_start = rewritten.index("WHERE {")
    where_end = rewritten.index("}", where_start)
    where_body = rewritten[where_start:where_end]
    assert "BIND(<https://github.com/hidden-graph/rdflib-starlight/ns/tt#fn/hash>(" in where_body
    # nothing should follow the WHERE block's own closing brace
    assert rewritten[where_end + 1:].strip() == ""


def test_is_triple_of_nested_triple_constructor():
    # isTRIPLE(TRIPLE(...)) - the inner TRIPLE(...) must be fully reduced to a
    # plain variable (with its matching pattern correctly placed) *before*
    # isTRIPLE's own regex - which only matches a bare variable argument -
    # ever sees it, or isTRIPLE(...) is left as literal, unparseable text.
    query = "SELECT (isTRIPLE(TRIPLE(<http://example.org/a>, <http://example.org/b>, <http://example.org/c>)) AS ?v) WHERE {}"
    rewritten = rewrite_sparql12_to_11(query)

    assert "isTRIPLE(" not in rewritten
    assert "TRIPLE(" not in rewritten
    # Must not use EXISTS: rdflib has a confirmed, independent-of-this-codebase
    # limitation where `EXISTS {...} && ...` raises inside a SELECT-projection
    # AS-expression (works fine inside FILTER). STRSTARTS alone is sufficient -
    # every TT_NS-prefixed URIRef is created exclusively by _intern_tt(), which
    # always writes its encoding triples in the same call.
    assert "EXISTS" not in rewritten
    assert 'STRSTARTS(STR(?__tt0), "https://github.com/hidden-graph/rdflib-starlight/ns/tt#")' in rewritten


def test_triple_constructor_with_all_initbindings_args_constructs_a_value():
    # Found 2026-07-31 via pyshacl-starlight: TRIPLE(?a0, ?a1, ?a2) with all
    # three arguments bound only via initBindings (no WHERE-clause graph
    # pattern to match them against - exactly how a SPARQL-node-expression
    # caller evaluates a `sparql:triple(...)` call) used to return zero rows.
    # Root cause: this SELECT-projection expression sits inside an unclosed
    # '(' (the projection's own parens) when the rewriter's group-content
    # scan reaches TRIPLE(...) - an *expression* position - but the old code
    # only ever branched on groundedness, so a non-ground occurrence (?a0/
    # ?a1/?a2 are variables) always fell through to the "graph-pattern
    # match" branch: `?__tt0 rdf:subject ?a0 . ...`, requiring a triple term
    # with exactly these components to already be registered in the store,
    # which initBindings-only values never are. Fixed by tracking expression
    # vs. graph-pattern-term position (an unclosed paren means expression)
    # and, for non-ground expression-position triple terms, substituting the
    # hash-function call directly in place instead of a matching pattern.
    query = "SELECT (TRIPLE(?a0, ?a1, ?a2) AS ?r) WHERE {}"
    rewritten = rewrite_sparql12_to_11(query)

    assert "TRIPLE(" not in rewritten
    assert (
        "SELECT (<https://github.com/hidden-graph/rdflib-starlight/ns/tt#fn/hash>"
        "(?a0, ?a1, ?a2) AS ?r) WHERE {}" == rewritten
    )

    from rdflib import URIRef
    from starlight.graph.starlight_graph import StarlightGraph

    g = StarlightGraph()
    rows = list(g.query(
        "SELECT (TRIPLE(?a0, ?a1, ?a2) AS ?r) WHERE {}",
        initBindings={
            "a0": URIRef("http://example.org/s"),
            "a1": URIRef("http://example.org/p"),
            "a2": URIRef("http://example.org/o"),
        },
    ))
    assert len(rows) == 1
    from starlight.model.triple import TripleTerm
    assert rows[0][0] == TripleTerm(
        URIRef("http://example.org/s"), URIRef("http://example.org/p"), URIRef("http://example.org/o"),
    )


def test_triple_constructor_in_bind_with_where_bound_vars_still_matches_literal_form():
    # test_rewrite_triple_constructor_in_bind (above) already asserts
    # TRIPLE(?s, ?p, ?o) and the literal <<( ?s ?p ?o )>> spelling rewrite
    # identically when used in a BIND. Confirms *why* that equivalence is
    # still correct after the expression/pattern-position fix: BIND(...) is
    # itself an expression context (an unclosed '(' at the point the triple
    # term is scanned), so both spellings now take the "elif is_expression"
    # inline-substitution path - a real behavior change from the pre-fix
    # "always try to match a WHERE-clause pattern" branch, not just a
    # coincidental re-confirmation of old output.
    query = """
PREFIX : <http://example.org/>
SELECT ?s ?date WHERE {
  ?s ?p ?o .
  BIND( TRIPLE(?s, ?p, ?o) AS ?tt )
  :myreifier rdf:reifies ?tt .
}
""".strip()
    rewritten = rewrite_sparql12_to_11(query)

    assert "TRIPLE(" not in rewritten
    assert "BIND( <https://github.com/hidden-graph/rdflib-starlight/ns/tt#fn/hash>(?s, ?p, ?o) AS ?tt )" in rewritten
    # No rdf:subject/predicate/object matching pattern should have been
    # injected - there is nothing to match, ?tt is computed, not looked up.
    assert "rdf-syntax-ns#subject" not in rewritten


def test_is_triple_term_alias_also_avoids_exists():
    # sanity: bare-variable form still rewrites correctly and without EXISTS
    query = "SELECT (isTripleTerm(?x) AS ?v) WHERE { ?s ?p ?x }"
    rewritten = rewrite_sparql12_to_11(query)
    assert "isTripleTerm(" not in rewritten
    assert "EXISTS" not in rewritten
    assert 'STRSTARTS(STR(?x), "https://github.com/hidden-graph/rdflib-starlight/ns/tt#")' in rewritten


def test_dirlang_literal_directly_in_function_argument():
    # A "text"@lang--dir literal written directly in a query (as opposed to a
    # variable bound from stored data, which already worked) must not be
    # handed unchanged to rdflib's SPARQL 1.1 parser - it has no notion of
    # the --dir suffix and raises a ParseException on the "--" it doesn't
    # expect. It must be rewritten to a directly typed literal using the
    # same dirlang-encoded datatype URI storage uses (not a function call -
    # that only works in expression positions, not term slots like a VALUES
    # row; a directly typed literal works everywhere. See
    # starlight.model.encoding.encode_dirlang_datatype).
    query = 'SELECT (LANGDIR("hi"@en--rtl) AS ?dir) WHERE {}'
    rewritten = rewrite_sparql12_to_11(query)

    assert '@en--rtl' not in rewritten
    assert 'fn/construct' not in rewritten
    assert '"hi"^^<https://github.com/hidden-graph/rdflib-starlight/ns/dirlang#en--rtl>' in rewritten


def test_dirlang_literal_single_quoted_and_triple_quoted():
    rewritten = rewrite_sparql12_to_11("SELECT (LANG('hi'@en--rtl) AS ?l) WHERE {}")
    assert "'hi'^^<https://github.com/hidden-graph/rdflib-starlight/ns/dirlang#en--rtl>" in rewritten

    rewritten2 = rewrite_sparql12_to_11('SELECT (LANG("""hi there"""@en--rtl) AS ?l) WHERE {}')
    assert '"""hi there"""^^<https://github.com/hidden-graph/rdflib-starlight/ns/dirlang#en--rtl>' in rewritten2


def test_dirlang_literal_untouched_when_no_direction_suffix():
    # Plain "text"@lang (no --dir) is already valid SPARQL 1.1 and the literal
    # itself must be left alone (LANG(...) still gets its usual upgrade
    # wrapper, unconditionally, regardless of whether the argument happens to
    # use dirlang syntax - that part is untouched by this test).
    rewritten = rewrite_sparql12_to_11('SELECT (LANG("hi"@en) AS ?l) WHERE {}')
    assert '"hi"@en)' in rewritten
    assert 'fn/construct' not in rewritten