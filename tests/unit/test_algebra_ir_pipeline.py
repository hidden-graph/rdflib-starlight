"""Confirms StarlightGraph(sparql_pipeline='algebra_ir') - the opt-in
sparql1_2_to_rdf-based SPARQL 1.2 execution path (see the cross-repo
migration plan) - against the default in-memory backend. Covers every RDF
1.2 feature this path is meant to replace starlight's own
sparql12_to_11.py rewriter for: triple-term patterns/construction/
accessors, and the four dirLangString functions added to sparql1_2_to_rdf
specifically to close the gap found while planning this migration
(LANGDIR/hasLANGDIR/hasLANG/STRLANGDIR - see that project's grammar12.py).

Remote-store coverage (the harder case - custom-function decomposition via
starlight.query.remote_decompose, and the CONSTRUCT-with-custom-function
NotImplementedError guard) lives in tests/integration/test_fuseki_backend.py
instead, since it needs a live server.

Marked `algebra_ir` (see pyproject.toml) - run as its own pytest invocation,
not together with the default suite. Confirmed: running this file alongside
legacy-pipeline tests in one pytest process can corrupt sparql1_2_to_rdf's
grammar installation via a pytest assertion-rewrite interaction - not a bug
in the pipeline itself (this file passes cleanly every time run alone; see
docs/testing-strategy.md for the full writeup and the exact command).
"""

from __future__ import annotations

import pytest
from rdflib import Literal, URIRef

from starlight.graph.starlight_graph import StarlightGraph
from starlight.model.dirlangstring import DirLangString
from starlight.model.triple import TripleTerm

pytestmark = pytest.mark.algebra_ir

EX = "http://ex/"
RDF_REIFIES = URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies")


def test_invalid_pipeline_value_rejected():
    with pytest.raises(ValueError):
        StarlightGraph(sparql_pipeline="bogus")


def test_triple_term_pattern_match():
    g = StarlightGraph(sparql_pipeline="algebra_ir")
    tt = TripleTerm(URIRef(EX + "a"), URIRef(EX + "b"), URIRef(EX + "c"))
    g.add((URIRef(EX + "stmt"), RDF_REIFIES, tt))
    r = g.query(f"PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> "
                f"SELECT ?tt WHERE {{ ?stmt rdf:reifies ?tt }}")
    assert r.bindings[0][r.vars[0]] == tt


def test_triple_constructor_function():
    g = StarlightGraph(sparql_pipeline="algebra_ir")
    r = g.query(f"SELECT (TRIPLE(<{EX}a>, <{EX}b>, <{EX}c>) AS ?t) WHERE {{}}")
    assert r.bindings[0][r.vars[0]] == TripleTerm(
        URIRef(EX + "a"), URIRef(EX + "b"), URIRef(EX + "c"))


def test_is_triple_and_accessors():
    g = StarlightGraph(sparql_pipeline="algebra_ir")
    tt = TripleTerm(URIRef(EX + "a"), URIRef(EX + "b"), URIRef(EX + "c"))
    g.add((URIRef(EX + "stmt"), RDF_REIFIES, tt))
    r = g.query(
        f"PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> "
        f"SELECT ?s WHERE {{ ?stmt rdf:reifies ?tt . "
        f"FILTER(isTRIPLE(?tt)) BIND(SUBJECT(?tt) AS ?s) }}"
    )
    assert r.bindings[0][r.vars[0]] == URIRef(EX + "a")


def test_langdir_hasLangdir():
    g = StarlightGraph(sparql_pipeline="algebra_ir")
    g.add((URIRef(EX + "s"), URIRef(EX + "p"), DirLangString("hi", "en", "rtl")))
    r = g.query(
        f"PREFIX : <{EX}> SELECT (LANGDIR(?o) AS ?d) (hasLANGDIR(?o) AS ?h) "
        f"WHERE {{ :s :p ?o }}"
    )
    row = r.bindings[0]
    assert row[r.vars[0]] == Literal("rtl")
    assert row[r.vars[1]] == Literal(True)


def test_lang_on_dirlangstring():
    g = StarlightGraph(sparql_pipeline="algebra_ir")
    g.add((URIRef(EX + "s"), URIRef(EX + "p"), DirLangString("hi", "en", "rtl")))
    r = g.query(f"PREFIX : <{EX}> SELECT (LANG(?o) AS ?l) WHERE {{ :s :p ?o }}")
    assert r.bindings[0][r.vars[0]] == Literal("en")


def test_haslang_on_ordinary_langtagged_literal():
    g = StarlightGraph(sparql_pipeline="algebra_ir")
    g.add((URIRef(EX + "s"), URIRef(EX + "p"), Literal("hi", lang="en")))
    r = g.query(f"PREFIX : <{EX}> SELECT (hasLANG(?o) AS ?h) WHERE {{ :s :p ?o }}")
    assert r.bindings[0][r.vars[0]] == Literal(True)


def test_strlangdir_constructs_dirlangstring():
    g = StarlightGraph(sparql_pipeline="algebra_ir")
    r = g.query('SELECT (STRLANGDIR("hi", "en", "ltr") AS ?r) WHERE {}')
    assert r.bindings[0][r.vars[0]] == DirLangString("hi", "en", "ltr")


def test_construct_mints_triple_term():
    g = StarlightGraph(sparql_pipeline="algebra_ir")
    g.add((URIRef(EX + "a"), URIRef(EX + "b"), URIRef(EX + "c")))
    r = g.query(
        f"PREFIX : <{EX}> CONSTRUCT {{ :dave :claims <<( :a :b :c )>> }} "
        f"WHERE {{ :a :b :c }}"
    )
    triples = list(r.graph)
    assert len(triples) == 1
    s, p, o = triples[0]
    assert (s, p) == (URIRef(EX + "dave"), URIRef(EX + "claims"))
    assert o == TripleTerm(URIRef(EX + "a"), URIRef(EX + "b"), URIRef(EX + "c"))


def test_initns_falls_back_to_legacy_pipeline_without_error():
    # A known, documented limitation for this first pass (see
    # VALID_SPARQL_PIPELINES's own comment): prepare_query_12 has no
    # initNs parameter, so a call supplying one falls back to the legacy
    # rewrite_sparql12_to_11 path instead of erroring - confirmed here it
    # still produces the correct result via that fallback.
    g = StarlightGraph(sparql_pipeline="algebra_ir")
    g.add((URIRef(EX + "a"), URIRef(EX + "b"), URIRef(EX + "c")))
    r = g.query("SELECT ?s WHERE { ?s :b :c }", initNs={"": EX})
    assert r.bindings[0][r.vars[0]] == URIRef(EX + "a")
