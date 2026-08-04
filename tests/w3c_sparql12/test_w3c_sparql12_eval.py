"""W3C SPARQL 1.2 test suite - execution correctness, run against
StarlightGraph directly.

This is deliberately the "B vs A" check, not the "C vs A" check the
downstream sparql1_2_to_rdf project's own tests/test_w3c_sparql12.py does:
the *original* W3C query text is executed here exactly as published, with
zero involvement from sparql1_2_to_rdf's own SPARQL-1.2-to-algebra-to-text
translation pipeline. Any failure reported here is a real, standalone
starlight/rdflib execution defect, independent of anything that project's
own translation might separately get right or wrong - a query that fails
here would still fail even if that project's translation pipeline were
perfect. See docs/rdflib-upstream-issues.md for confirmed rdflib bugs found
via this same test suite while building sparql1_2_to_rdf.

Two test shapes:
1. QueryEvaluationTest (SELECT-shaped, .srj expected results) - compare
   bindings, order/set-independent. `.srx`-only tests (no `.srj`) are
   skipped - this harness's JSON results parser has no XML counterpart.
2. QueryEvaluationTest (CONSTRUCT-shaped, .ttl expected results) - compare
   by graph isomorphism, after skolemizing any TripleTerm value to a
   stable URIRef first (see _skolemize_graph - rdflib.compare.to_isomorphic
   requires every term to be a real rdflib.term.Node, which
   starlight.model.triple.TripleTerm deliberately isn't), AND mapping any
   anonymous-reifier rr:N URIRef (starlight's own internal skolemization of
   an anonymous reifier - see starlight/model/encoding.py's RR_NS) back to
   a fresh BNode first. The latter is necessary, not cosmetic: rr:N
   numbering is assignment-order-dependent (confirmed via construct-3 -
   actual and expected mint the same reifiers in different orders, so e.g.
   "rr#0" on one side is "rr#3" on the other for the structurally same
   reifier), and to_isomorphic's blank-node canonicalization - which is
   exactly the "up to consistent relabeling" comparison this needs - only
   applies to genuine BNodes, not arbitrary URIRefs regardless of
   namespace.

UpdateEvaluationTest is collected (via the shared index) but not exercised
here - this file is scoped to query evaluation.
"""

from __future__ import annotations

import pytest
from rdflib import BNode, Graph, URIRef
from rdflib.compare import to_isomorphic
from rdflib.graph import DATASET_DEFAULT_GRAPH_ID
from rdflib.namespace import RDF
from rdflib.plugins.stores.sparqlstore import SPARQLUpdateStore

from starlight.graph.starlight_dataset import StarlightDataset
from starlight.graph.starlight_graph import StarlightGraph
from starlight.model.encoding import RR_NS
from starlight.model.triple import TripleTerm

from .harness import (
    bindings_match,
    clear_oxigraph,
    data_format,
    load_index,
    oxigraph_available,
    OXIGRAPH_QUERY_URL,
    OXIGRAPH_UPDATE_URL,
    parse_srj,
)

_DATASET_FORMATS = {"trig12", "nq12"}


def _new_graph(entry) -> StarlightGraph | StarlightDataset:
    """A fixture's data may define named graphs (TriG/N-Quads) - those need a
    real multi-graph Dataset, not a single StarlightGraph (which raises "You
    performed a query operation requiring a dataset" the moment a query uses
    GRAPH against data that was never loaded into any graph at all, since a
    lone StarlightGraph has no notion of a graph name other than its own).
    StarlightDataset.query()/.parse() have the same shape as StarlightGraph's
    own (confirmed by reading starlight_dataset.py), so callers don't need to
    branch on which one they got back.
    """
    if entry.data_file and data_format(entry) in _DATASET_FORMATS:
        return StarlightDataset()
    return StarlightGraph()


def _new_oxigraph_graph(entry) -> StarlightGraph | StarlightDataset:
    """Same shape as _new_graph(), but backed by a live Oxigraph endpoint via
    the native rdf-1.2 backend instead of the in-memory default - no special
    loading path of its own, same .parse()/.query() calls either way.

    A plain (non-dataset) StarlightGraph is given
    ``rdflib.graph.DATASET_DEFAULT_GRAPH_ID`` as its identifier rather than
    an arbitrary graph name: that sentinel is what tells the native
    backend's write/read paths (StarlightGraph._native_scoped()) this graph
    stands for a dataset's own default graph, so its triples go to the
    endpoint's real (unnamed) default graph - the same place an unmodified
    query with no GRAPH clause looks by default. Anything else would need
    the query text itself changed to add a GRAPH wrapper, which defeats the
    point of this whole test file (running each W3C query exactly as
    published, see the module docstring).
    """
    store = SPARQLUpdateStore(query_endpoint=OXIGRAPH_QUERY_URL, update_endpoint=OXIGRAPH_UPDATE_URL)
    if entry.data_file and data_format(entry) in _DATASET_FORMATS:
        return StarlightDataset(store=store, backend="rdf-1.2")
    return StarlightGraph(store=store, identifier=DATASET_DEFAULT_GRAPH_ID, backend="rdf-1.2")


ALL_ENTRIES = load_index()

EVAL_SELECT = [
    e
    for e in ALL_ENTRIES
    if e.test_type == "QueryEvaluationTest" and e.result_file.endswith(".srj")
]
EVAL_CONSTRUCT = [
    e
    for e in ALL_ENTRIES
    if e.test_type == "QueryEvaluationTest" and e.result_file.endswith(".ttl")
]

# Known, understood divergences between Oxigraph and the in-memory backend -
# not starlight bugs, so not "fixed" here, but also not silently masked.
# Each is an xfail(strict=True): if Oxigraph's own behavior ever changes to
# match, the xfail flips to an unexpected pass (XPASS) and fails loudly
# rather than staying silently green. Same pattern already used by
# tests/integration/test_cross_backend_parity.py's numeric-lexical-form gap.
#
# order-1/order-2 (ORDER BY across a blank node/IRI/literal/triple-term) used
# to be here too - blank nodes had to be skolemized to a BN_NS URI to survive
# StarlightGraph._native_add()'s one-HTTP-request-per-triple write path (see
# backends/native.py's skolemize_bnode()), which made Oxigraph's own engine
# treat them as URIs rather than blank nodes for ORDER BY's term-kind rule.
# Fixed 2026-08-04 by StarlightGraph._native_add_many(): StarlightGraph.parse()/
# addN() now batch every triple for one graph into a single SPARQL Update
# request, so real (unskolemized) blank-node syntax survives correctly - see
# its own docstring for why that's safe there specifically (every triple
# lands in the *same* request) but not for the single-triple add() path,
# which still skolemizes and still needs to (a blank node reused across
# separate add() calls, or across StarlightDataset named-graph contexts,
# still only has request-scoped identity without it).
_OXIGRAPH_KNOWN_DIVERGENCES = {
    "op-2": (
        "Oxigraph does not preserve the canonical xsd:decimal lexical form on "
        "round-trip (e.g. \"123.0\" comes back as \"123\") - same underlying "
        "gap as test_cross_backend_parity.py's numeric-lexical-form xfail, "
        "here surfacing through a triple-term-valued FILTER(sameTerm/=) "
        "comparison instead of CEIL/FLOOR/division."
    ),
}


def _mark_known_oxigraph_divergences(entries):
    """Wrap each entry whose test_iri is a known Oxigraph divergence (see
    _OXIGRAPH_KNOWN_DIVERGENCES) in pytest.param(..., marks=xfail); every
    other entry passes through unchanged."""
    return [
        pytest.param(e, marks=pytest.mark.xfail(strict=True, reason=_OXIGRAPH_KNOWN_DIVERGENCES[key]))
        if (key := e.test_iri.rsplit("#", 1)[-1]) in _OXIGRAPH_KNOWN_DIVERGENCES
        else e
        for e in entries
    ]


EVAL_SELECT_OXIGRAPH = _mark_known_oxigraph_divergences(EVAL_SELECT)

_no_data = pytest.mark.skipif(
    not ALL_ENTRIES,
    reason="W3C SPARQL 1.2 test data not fetched - run download_w3c_sparql12_tests.py",
)

_oxigraph = pytest.mark.skipif(
    not oxigraph_available(),
    reason="Oxigraph not running - start with: "
    "docker run -d --name oxigraph-test -p 7878:7878 "
    "ghcr.io/oxigraph/oxigraph serve --location /data --bind 0.0.0.0:7878",
)


# Marker predicates for _skolemize_graph()'s TripleTerm encoding below -
# deliberately *not* the real rdf:subject/predicate/object (which some
# fixture could conceivably use as ordinary data in some other test, and
# comparing rdf:subject/predicate/object triples this function *didn't*
# generate against ones it did would be a real, if unlikely, false-match
# risk) - a private, test-only namespace makes a collision impossible.
_SKOLEM_NS = "urn:starlight-test:skolem-tt#"
_SK_SUBJECT   = URIRef(_SKOLEM_NS + "subject")
_SK_PREDICATE = URIRef(_SKOLEM_NS + "predicate")
_SK_OBJECT    = URIRef(_SKOLEM_NS + "object")
_SK_TT_MARKER = URIRef(_SKOLEM_NS + "TripleTerm")


def _skolemize_graph(graph) -> Graph:
    """Convert every TripleTerm value in `graph` into ordinary triples on a
    fresh BNode, and every RR_NS anonymous-reifier URIRef into a fresh
    BNode too, so the whole thing can be handed to
    rdflib.compare.to_isomorphic() (which requires every term to be a real
    rdflib.term.Node - TripleTerm deliberately isn't one, and rr:N is a
    starlight-internal skolemization of what's really an anonymous
    reifier - see starlight/model/encoding.py's RR_NS).

    An earlier version of this function instead collapsed each TripleTerm
    into a *single* content-hashed URIRef (hashing its own already-
    skolemized subject/predicate/object). That broke the very "up to
    consistent BNode relabeling" comparison to_isomorphic() exists to do:
    hashing in a component's specific (arbitrary) BNode label baked
    non-canonical identity into a value to_isomorphic was never told it
    could relabel, so two graphs that actually *were* isomorphic (same
    structure, different arbitrary BNode label for "the" anonymous
    reifier) hashed to different URIs and compared as unequal - confirmed
    via construct-3/expr-1, both of which mix an RR_NS-mapped-to-BNode
    reifier with a TripleTerm nesting it.

    Encoding a TripleTerm as ordinary triples on a *fresh* BNode instead
    sidesteps the problem entirely, rather than working around it: BNode
    canonicalization is exactly what to_isomorphic() already does
    correctly, so representing "this is a triple term with these
    components" as ordinary triples (the same rdf:subject/predicate/object
    *shape* starlight's own on-disk tt: encoding already uses - see
    starlight.parsers.turtle_parser.decode_tt_encoded_triples - though with
    different, collision-proof predicates, see _SK_SUBJECT et al above)
    rather than pre-collapsing it into one opaque value lets
    to_isomorphic() do the comparison itself instead of this function
    trying to pre-empt it.
    """
    out = Graph()
    rr_to_bnode: dict = {}

    def skolemize(term):
        if isinstance(term, TripleTerm):
            node = BNode()
            out.add((node, RDF.type, _SK_TT_MARKER))
            out.add((node, _SK_SUBJECT, skolemize(term.subject)))
            out.add((node, _SK_PREDICATE, skolemize(term.predicate)))
            out.add((node, _SK_OBJECT, skolemize(term.object)))
            return node
        if isinstance(term, URIRef) and str(term).startswith(RR_NS):
            if term not in rr_to_bnode:
                rr_to_bnode[term] = BNode()
            return rr_to_bnode[term]
        return term

    for s, p, o in graph:
        out.add((skolemize(s), p, skolemize(o)))
    return out


@_no_data
@pytest.mark.parametrize("entry", EVAL_SELECT, ids=lambda e: e.test_iri)
def test_eval_select_original_query(entry):
    query_text = entry.read(entry.query_file)
    expected = parse_srj(entry.read(entry.result_file))

    g = _new_graph(entry)
    if entry.data_file:
        g.parse(data=entry.read(entry.data_file), format=data_format(entry))

    actual = [{k: v for k, v in dict(row).items() if v is not None} for row in g.query(query_text).bindings]
    assert bindings_match(actual, expected)


@_no_data
@pytest.mark.parametrize("entry", EVAL_CONSTRUCT, ids=lambda e: e.test_iri)
def test_eval_construct_original_query(entry):
    query_text = entry.read(entry.query_file)
    expected_graph = StarlightGraph()
    expected_graph.parse(data=entry.read(entry.result_file), format="turtle12")

    g = _new_graph(entry)
    if entry.data_file:
        g.parse(data=entry.read(entry.data_file), format=data_format(entry))

    actual_graph = g.query(query_text).graph
    assert to_isomorphic(_skolemize_graph(actual_graph)) == to_isomorphic(_skolemize_graph(expected_graph))


# ---------------------------------------------------------------------------
# Same two checks, run against a live Oxigraph endpoint instead of the
# in-memory backend, via _new_oxigraph_graph() - the exact same .parse()/
# .query() calls as the in-memory tests above, no special loading path.
# Still the original, unmodified W3C query text either way.
# ---------------------------------------------------------------------------

@_no_data
@_oxigraph
@pytest.mark.parametrize("entry", EVAL_SELECT_OXIGRAPH, ids=lambda e: e.test_iri)
def test_eval_select_original_query_oxigraph(entry):
    query_text = entry.read(entry.query_file)
    expected = parse_srj(entry.read(entry.result_file))

    clear_oxigraph()
    g = _new_oxigraph_graph(entry)
    if entry.data_file:
        g.parse(data=entry.read(entry.data_file), format=data_format(entry))

    actual = [{k: v for k, v in dict(row).items() if v is not None} for row in g.query(query_text).bindings]
    assert bindings_match(actual, expected)


@_no_data
@_oxigraph
@pytest.mark.parametrize("entry", EVAL_CONSTRUCT, ids=lambda e: e.test_iri)
def test_eval_construct_original_query_oxigraph(entry):
    query_text = entry.read(entry.query_file)
    expected_graph = StarlightGraph()
    expected_graph.parse(data=entry.read(entry.result_file), format="turtle12")

    clear_oxigraph()
    g = _new_oxigraph_graph(entry)
    if entry.data_file:
        g.parse(data=entry.read(entry.data_file), format=data_format(entry))

    actual_graph = g.query(query_text).graph
    assert to_isomorphic(_skolemize_graph(actual_graph)) == to_isomorphic(_skolemize_graph(expected_graph))
