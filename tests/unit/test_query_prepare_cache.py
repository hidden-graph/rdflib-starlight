"""Regression tests for the prepared-query cache (starlight.query.query_cache).

StarlightGraph.query()/StarlightDataset.query() used to rewrite (SPARQL 1.2 ->
1.1) and parse the query text fresh on every call, even when the same query
text is evaluated repeatedly with only initBindings differing - exactly how
pySHACL evaluates a SHACL-AF sh:construct rule or sh:sparql constraint (once
per focus node, per iteration). These tests confirm the cache actually
eliminates the redundant work, stays correct across differing
initNs/initBindings/data mutations, and doesn't change any query's result.
"""

import rdflib.plugins.sparql as _sparql_mod
import pytest
from rdflib import Namespace

from starlight.graph.starlight_dataset import StarlightDataset
from starlight.graph.starlight_graph import StarlightGraph

EX = Namespace("http://example.org/")
EX2 = Namespace("http://example2.org/")


@pytest.fixture
def counting_prepare_query(monkeypatch):
    """Count real calls to rdflib.plugins.sparql.prepareQuery, patched at
    every import site that could hold a reference to it."""
    calls = {"n": 0}
    original = _sparql_mod.prepareQuery

    def counting(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(_sparql_mod, "prepareQuery", counting)
    monkeypatch.setattr("starlight.query.query_cache.prepareQuery", counting)
    return calls


def test_repeated_identical_query_parses_once(counting_prepare_query):
    g = StarlightGraph()
    g.bind("ex", EX)
    g.add((EX.a, EX.p, EX.b))

    q = "SELECT ?o WHERE { ex:a ex:p ?o }"
    for _ in range(5):
        list(g.query(q, initNs={"ex": EX}))

    assert counting_prepare_query["n"] == 1


def test_different_query_text_parses_again(counting_prepare_query):
    g = StarlightGraph()
    g.bind("ex", EX)
    g.add((EX.a, EX.p, EX.b))
    g.add((EX.c, EX.p, EX.d))

    list(g.query("SELECT ?o WHERE { ex:a ex:p ?o }", initNs={"ex": EX}))
    list(g.query("SELECT ?o WHERE { ex:c ex:p ?o }", initNs={"ex": EX}))

    assert counting_prepare_query["n"] == 2


def test_repeated_query_with_different_bindings_gives_correct_results():
    """The motivating pySHACL pattern: same query text, different
    initBindings per call - each call must still resolve independently and
    correctly, not accidentally share state through the cache."""
    g = StarlightGraph()
    g.bind("ex", EX)
    g.add((EX.alice, EX.knows, EX.bob))
    g.add((EX.bob, EX.knows, EX.carol))

    q = "SELECT ?friend WHERE { ?this ex:knows ?friend }"
    for focus, expected in [(EX.alice, EX.bob), (EX.bob, EX.carol), (EX.alice, EX.bob)]:
        rows = list(g.query(q, initNs={"ex": EX}, initBindings={"this": focus}))
        assert rows == [(expected,)]


def test_different_effective_namespaces_do_not_collide(counting_prepare_query):
    """Same query text, different initNs mappings must each be parsed with
    their own prefixes - reusing a cache entry prepared for a different
    initNs would silently resolve the wrong prefix."""
    g = StarlightGraph()
    g.bind("ex", EX)
    g.bind("ex2", EX2)
    g.add((EX.alice, EX.p, EX.first))
    g.add((EX2.alice, EX2.p, EX2.second))

    q = "SELECT ?o WHERE { ex:alice ex:p ?o }"
    rows_ex = list(g.query(q, initNs={"ex": EX}))
    assert rows_ex == [(EX.first,)]

    # Same literal query text, but "ex:" now resolves to a different
    # namespace - must not reuse the first cache entry.
    rows_ex2 = list(g.query(q, initNs={"ex": EX2}))
    assert rows_ex2 == [(EX2.second,)]
    assert counting_prepare_query["n"] == 2


def test_cache_does_not_serve_stale_data_after_mutation():
    """The cache is keyed on query text/namespaces/base, not graph content -
    confirms new triples added between two identical-query calls are still
    visible (the parsed query is reused, but it's evaluated fresh against
    current data each time, not memoized results)."""
    g = StarlightGraph()
    g.bind("ex", EX)
    g.add((EX.a, EX.p, EX.b))

    q = "SELECT ?o WHERE { ex:a ex:p ?o }"
    first = list(g.query(q, initNs={"ex": EX}))
    assert first == [(EX.b,)]

    g.add((EX.a, EX.p, EX.c))
    second = list(g.query(q, initNs={"ex": EX}))
    assert sorted(second) == sorted([(EX.b,), (EX.c,)])


def test_construct_rule_repeated_per_focus_node_matches_pyshacl_pattern():
    """sh:construct-style repeated CONSTRUCT calls, one per focus node, same
    query text each time - the exact shape that motivated this cache."""
    g = StarlightGraph()
    g.bind("ex", EX)
    g.add((EX.alice, EX.knows, EX.bob))
    g.add((EX.bob, EX.knows, EX.carol))

    q = "CONSTRUCT { ?this ex:metFriend ?friend } WHERE { ?this ex:knows ?friend }"
    expected = {
        EX.alice: (EX.alice, EX.metFriend, EX.bob),
        EX.bob: (EX.bob, EX.metFriend, EX.carol),
    }
    for focus, expected_triple in expected.items():
        result = g.query(q, initNs={"ex": EX}, initBindings={"this": focus})
        assert list(result.graph) == [expected_triple]


def test_triple_term_query_still_correct_with_cache():
    """A genuine SPARQL 1.2 triple-term pattern, rewritten to SPARQL 1.1 by
    the cached preparation path - confirms the rewrite (not just the parse)
    is still applied correctly when served from cache."""
    g = StarlightGraph()
    g.bind("ex", EX)
    g.parse(data="@prefix ex: <http://example.org/> .\nex:alice ex:says <<( ex:bob ex:knows ex:carol )>> .\n", format="turtle12")

    q = "SELECT ?s ?p ?o WHERE { ex:alice ex:says <<( ?s ?p ?o )>> }"
    for _ in range(3):
        rows = list(g.query(q, initNs={"ex": EX}))
        assert rows == [(EX.bob, EX.knows, EX.carol)]


def test_dataset_repeated_query_parses_once(counting_prepare_query):
    ds = StarlightDataset()
    ds.bind("ex", EX)
    g1 = ds.get_context(EX.g1)
    g1.add((EX.a, EX.p, EX.b))

    q = "SELECT ?o WHERE { GRAPH ex:g1 { ex:a ex:p ?o } }"
    for _ in range(4):
        list(ds.query(q, initNs={"ex": EX}))

    assert counting_prepare_query["n"] == 1


def test_dataset_query_correct_across_repeated_calls_with_bindings():
    ds = StarlightDataset()
    ds.bind("ex", EX)
    g1 = ds.get_context(EX.g1)
    g1.add((EX.alice, EX.knows, EX.bob))
    g1.add((EX.bob, EX.knows, EX.carol))

    q = "SELECT ?friend WHERE { GRAPH ?g { ?this ex:knows ?friend } }"
    for focus, expected in [(EX.alice, EX.bob), (EX.bob, EX.carol)]:
        rows = list(ds.query(q, initNs={"ex": EX}, initBindings={"this": focus, "g": EX.g1}))
        assert rows == [(expected,)]
