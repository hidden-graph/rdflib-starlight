"""Starlight — RDF 1.2 / RDF-star graph library built on rdflib.

Re-exports the most commonly needed rdflib primitives so downstream code can
import everything from ``starlight`` rather than mixing ``starlight.*`` and
``rdflib.*`` imports.
"""

# Core rdflib term types
from rdflib import BNode, Literal, URIRef, Variable

# Namespace utilities
from rdflib import Namespace
from rdflib.namespace import RDF, RDFS, XSD

# Graph / dataset base classes (aliased so consumers can stay on starlight.*)
from rdflib import Graph, Dataset
from rdflib.collection import Collection

# Starlight-specific additions
from starlight.model.triple import TripleTerm
from starlight.model.dirlangstring import DirLangString
from starlight.graph.starlight_graph import StarlightGraph
from starlight.graph.starlight_dataset import StarlightDataset
from starlight.parsers.errors import TurtleSyntaxError

# Compatibility shims for confirmed bugs in plain rdflib's own SPARQL
# arithmetic evaluation - applied eagerly so every consumer gets
# spec-correct results. See starlight/query/operator_patches.py.
from starlight.query.operator_patches import apply_all_operator_patches as _apply_all_operator_patches

# Compatibility shims for confirmed bugs in plain rdflib's own
# _AlgebraTranslator/translateAlgebra (algebra-tree-to-SPARQL-text
# serialization, not evaluation) - applied eagerly for the same reason.
# Not exercised by starlight's own pipeline (it never calls
# translateAlgebra itself), but protects any other consumer that does. See
# starlight/query/algebra_translator_patches.py and
# docs/rdflib-upstream-issues.md issues 3, 4, and 6.
from starlight.query.algebra_translator_patches import (
    patch_algebra_translator_bugs as _patch_algebra_translator_bugs,
)

# Compatibility shim for a confirmed bug in plain rdflib's own SPARQL
# *evaluator* (evalExtend/BIND) - the most important of these patches,
# since the bug it fixes silently produces wrong query results with no
# error at all, rather than failing loudly. Applies to every query
# evaluated through rdflib, including starlight's own (unlike the
# algebra-translator patches above, this one *is* exercised by starlight's
# own pipeline). See starlight/query/evaluate_patches.py and
# docs/rdflib-upstream-issues.md issue 5.
from starlight.query.evaluate_patches import (
    patch_evalextend_forgotten_bind_vars as _patch_evalextend_forgotten_bind_vars,
)

# Same confirmed rdflib bug as the evalExtend patch immediately above,
# reached through FILTER instead of BIND (evalFilter's own
# `c.forget(ctx, _except=part._vars)`) - not covered by that patch, since
# it only touches evalExtend. See
# starlight/query/evaluate_patches.py::patch_evalfilter_forgotten_vars.
from starlight.query.evaluate_patches import (
    patch_evalfilter_forgotten_vars as _patch_evalfilter_forgotten_vars,
)

# Fix for a confirmed bug in plain rdflib's own evalModify (a different
# module, rdflib.plugins.sparql.update, from the evalExtend/evalFilter
# patches above): it writes DELETE/INSERT changes through
# ctx.dataset.default_context instead of ctx.graph whenever ctx.graph isn't
# exactly a bare Graph instance - silently failing to remove/insert a
# triple-term-valued triple against this library's own in-memory backend,
# even though the WHERE clause matches correctly. See
# starlight/query/evaluate_patches.py::patch_evalmodify_default_graph_selection.
from starlight.query.evaluate_patches import (
    patch_evalmodify_default_graph_selection as _patch_evalmodify_default_graph_selection,
)

# Compatibility shim for a second, distinct confirmed bug in plain rdflib's
# own SPARQL evaluator (evalJoin/evalLazyJoin) - same root cause as the
# evalExtend patch above (a BIND's own expression-only variables aren't
# visible in _vars), but affects join *ordering* rather than evalExtend's
# own variable-forgetting, and isn't covered by that fix. See
# starlight/query/evaluate_patches.py::patch_lazy_join_expr_dependency_order.
from starlight.query.evaluate_patches import (
    patch_lazy_join_expr_dependency_order as _patch_lazy_join_expr_dependency_order,
)

# Fix for a starlight-side (not rdflib) gap: CONSTRUCT has no equivalent of
# SELECT's own encoding-triple row filtering, so an unconstrained WHERE
# pattern (e.g. a bare `?s ?p ?o`) can leak internal rdf:subject/predicate/
# object encoding triples into CONSTRUCT output. See
# starlight/query/evaluate_patches.py's own docstring for the full
# root-cause trace.
from starlight.query.evaluate_patches import (
    patch_construct_skips_encoding_solutions as _patch_construct_skips_encoding_solutions,
)

# Fix for a starlight-side (not rdflib) gap: the in-memory backend's
# tt:HASH encoding is opaque to stock rdflib's `=`/`!=`, which can only ever
# agree with `sameTerm` for two different encoded URIRefs - never true for
# two triple terms differing only in a component's lexical form, which
# SPARQL's own value-equality rules require. See
# starlight/query/evaluate_patches.py::patch_relational_expression_tt_hash_equality.
from starlight.query.evaluate_patches import (
    patch_relational_expression_tt_hash_equality as _patch_relational_expression_tt_hash_equality,
)

# Fix for a starlight-side (not rdflib) gap: the in-memory backend's
# tt:HASH encoding is opaque to stock rdflib's ORDER BY comparator, which
# has no term-kind bucket for triple terms at all (rdflib predates RDF 1.2)
# and so sorts one as an ordinary IRI instead of in its own, RDF-1.2-
# mandated bucket after literals. See
# starlight/query/evaluate_patches.py::patch_order_by_tt_hash_term_kind.
from starlight.query.evaluate_patches import (
    patch_order_by_tt_hash_term_kind as _patch_order_by_tt_hash_term_kind,
)

# Fix for a starlight-side (not rdflib) gap: an *unconstrained* BGP match
# (e.g. a bare `?s ?p ?o` inside a nested SELECT subquery, not just
# CONSTRUCT - see patch_construct_skips_encoding_solutions above, which only
# covers that one case) can incidentally match the in-memory backend's own
# internal tt:HASH encoding triples. See
# starlight/query/evaluate_patches.py::patch_bgp_skips_encoding_triples.
from starlight.query.evaluate_patches import (
    patch_bgp_skips_encoding_triples as _patch_bgp_skips_encoding_triples,
)

_apply_all_operator_patches()
_patch_algebra_translator_bugs()
_patch_evalextend_forgotten_bind_vars()
_patch_evalfilter_forgotten_vars()
_patch_evalmodify_default_graph_selection()
_patch_lazy_join_expr_dependency_order()
_patch_construct_skips_encoding_solutions()
_patch_relational_expression_tt_hash_equality()
_patch_order_by_tt_hash_term_kind()
_patch_bgp_skips_encoding_triples()

__all__ = [
    # rdflib primitives
    "BNode",
    "Literal",
    "URIRef",
    "Variable",
    # namespaces
    "Namespace",
    "RDF",
    "RDFS",
    "XSD",
    # graph types
    "Graph",
    "Dataset",
    "Collection",
    # starlight additions
    "TripleTerm",
    "DirLangString",
    "StarlightGraph",
    "StarlightDataset",
    "TurtleSyntaxError",
]
