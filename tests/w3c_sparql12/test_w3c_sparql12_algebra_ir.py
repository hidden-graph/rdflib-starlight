"""W3C SPARQL 1.2 test suite - execution correctness, run against
StarlightGraph(sparql_pipeline='algebra_ir') - the opt-in sparql1_2_to_rdf-
based SPARQL 1.2 engine (see the cross-repo migration plan), compared
against the *same official* `.srj`/`.ttl` ground truth
test_w3c_sparql12_eval.py's own in-memory (legacy-pipeline) tests already
check against.

This is Phase 2's parity check: not "does algebra_ir agree with the legacy
rewriter" directly (which would need both in the same process - see below
for why that's deliberately avoided), but the stronger, equally meaningful
claim "does algebra_ir achieve the same result as the legacy pipeline
against the same independent, official ground truth." Two suites agreeing
with the same external oracle is a valid, complete substitute for comparing
them to each other directly.

Deliberately a **separate file and a separate pytest marker** (`algebra_ir`,
see pyproject.toml) from test_w3c_sparql12_eval.py, run as its own pytest
invocation - not a style choice. Running algebra_ir-pipeline and
legacy-pipeline tests together in one pytest process is a confirmed,
reproducible way to corrupt sparql1_2_to_rdf's grammar installation via a
pytest assertion-rewrite/pyparsing-streamline interaction (see
docs/testing-strategy.md tier 5 and sparql1_2_to_rdf/CLAUDE.md finding #31
for the full write-up - not fully root-caused despite substantial
investigation, but reliably avoided by never mixing the two in one process).

Scope: now covers the full 40-fixture SELECT/CONSTRUCT slice, including the
4 entries whose data needs a real multi-graph Dataset (TriG/N-Quads) -
StarlightDataset gained `sparql_pipeline` support (Phase 2 extension), so
these no longer need excluding the way they did when this file was first
written (Phase 1, StarlightGraph-only).
"""

from __future__ import annotations

import pytest

from starlight.graph.starlight_dataset import StarlightDataset
from starlight.graph.starlight_graph import StarlightGraph

from .harness import bindings_match, data_format, load_index, parse_srj

pytestmark = pytest.mark.algebra_ir

_DATASET_FORMATS = {"trig12", "nq12"}


def _new_graph(entry) -> StarlightGraph | StarlightDataset:
    """Mirrors test_w3c_sparql12_eval.py's own _new_graph() - a fixture
    whose data defines named graphs (TriG/N-Quads) needs a real multi-graph
    Dataset, not a single StarlightGraph."""
    if entry.data_file and data_format(entry) in _DATASET_FORMATS:
        return StarlightDataset(sparql_pipeline="algebra_ir")
    return StarlightGraph(sparql_pipeline="algebra_ir")


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

_no_data = pytest.mark.skipif(
    not ALL_ENTRIES,
    reason="W3C SPARQL 1.2 test data not fetched - run download_w3c_sparql12_tests.py",
)

# Same known-divergence mechanism test_w3c_sparql12_eval.py uses, kept as
# its own copy (not imported) so this table's contents don't depend on that
# file's own unrelated in-memory-backend divergence list. (The CONSTRUCT
# test below does still import one pure helper, _skolemize_graph, from that
# module - a plain Python import, not a pytest-collection dependency:
# pytest already discovers and collects that file independently via its own
# glob, on every run of `tests/`, regardless of this import. Safe alongside
# the separate-marker/separate-invocation split above, which is specifically
# about not *executing* both pipelines' tests in one process - confirmed
# that plain collection of both files together, without running both, does
# not trigger the corruption.)
_KNOWN_DIVERGENCES: dict = {
    # LANGDIR is a genuine RDF 1.2 base-direction feature this project's
    # own grammar12.py addition (see the migration plan's Phase 0a) needed
    # to add from scratch, unlike every other feature here, which
    # sparql1_2_to_rdf already supported before this migration started -
    # left empty for now; populate per-fixture if a real divergence from
    # the legacy pipeline's own already-passing behavior turns up.
}


def _mark_known_divergences(entries, known: dict):
    return [
        pytest.param(e, marks=pytest.mark.xfail(strict=True, reason=known[key]))
        if (key := e.test_iri.rsplit("#", 1)[-1]) in known
        else e
        for e in entries
    ]


EVAL_SELECT = _mark_known_divergences(EVAL_SELECT, _KNOWN_DIVERGENCES)
EVAL_CONSTRUCT = _mark_known_divergences(EVAL_CONSTRUCT, _KNOWN_DIVERGENCES)


@_no_data
@pytest.mark.parametrize("entry", EVAL_SELECT, ids=lambda e: e.test_iri)
def test_eval_select_algebra_ir(entry):
    query_text = entry.read(entry.query_file)
    expected = parse_srj(entry.read(entry.result_file))

    g = _new_graph(entry)
    if entry.data_file:
        g.parse(data=entry.read(entry.data_file), format=data_format(entry))

    actual = [{k: v for k, v in dict(row).items() if v is not None} for row in g.query(query_text).bindings]
    assert bindings_match(actual, expected)


@_no_data
@pytest.mark.parametrize("entry", EVAL_CONSTRUCT, ids=lambda e: e.test_iri)
def test_eval_construct_algebra_ir(entry):
    from rdflib.compare import to_isomorphic

    from .test_w3c_sparql12_eval import _skolemize_graph

    query_text = entry.read(entry.query_file)
    expected_graph = StarlightGraph()
    expected_graph.parse(data=entry.read(entry.result_file), format="turtle12")

    g = _new_graph(entry)
    if entry.data_file:
        g.parse(data=entry.read(entry.data_file), format=data_format(entry))

    actual_graph = g.query(query_text).graph
    assert to_isomorphic(_skolemize_graph(actual_graph)) == to_isomorphic(_skolemize_graph(expected_graph))
