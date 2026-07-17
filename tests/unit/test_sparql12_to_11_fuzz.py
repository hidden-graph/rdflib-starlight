"""
Property-based fuzz testing for starlight.query.sparql12_to_11's rewriter.

The rewriter is a hand-rolled, ~1,100-line text scanner (not a full SPARQL
grammar), and every bug found in it during the 2026-07-16 session (SELECT-
projection placement, nested isTRIPLE, dirlang literals, and the ASK-without-
WHERE ground-BIND bug) was found via live cross-engine comparison or manual
triage - not by the existing example-based unit tests, despite those tests
exercising the same code paths. This module checks one cheap, purely
syntactic property across a combinatorial grid the example-based tests don't
enumerate: rewrite_sparql12_to_11()'s output must always be parseable SPARQL
1.1, regardless of query form, explicit-vs-omitted WHERE keyword, ground-vs-
variable/nested triple-term components, or which graph-pattern block the
triple term sits inside. It does not check *semantic* correctness (that's
what the example-based tests in test_sparql12_to_11.py and
test_sparql12_query.py are for) - only "does this produce valid SPARQL 1.1
that rdflib's real parser accepts."

Gap found while first designing this suite, same day: SUBJECT()/PREDICATE()/
OBJECT() only accepted a bare variable argument (SUBJECT(?tt)); calling one
directly on a <<( )>>/TRIPLE(...) literal (SUBJECT(<<( :a :b :c )>>)) raised
a ParseException rather than being rewritten. Fixed via
_rewrite_triple_accessor_literals() in sparql12_to_11.py; see
test_accessor_of_triple_term_literal_rewrites_to_valid_sparql below and the
example-based regression tests in test_sparql12_to_11.py /
test_sparql12_query.py::TestQ22.
"""

from hypothesis import given, settings, strategies as st
from rdflib.plugins.sparql.parser import parseQuery

from starlight.query import rewrite_sparql12_to_11

EX = 'http://example.org/'

# ---------------------------------------------------------------------------
# Triple-term occurrences: ground, variable, nested-ground, mixed, and the
# TRIPLE() constructor spelling (which desugars to <<( )>> up front).
# ---------------------------------------------------------------------------

_GROUND_TT = f'<<( <{EX}a> <{EX}b> <{EX}c> )>>'
_VAR_TT = f'<<( ?s <{EX}b> ?o )>>'
_NESTED_GROUND_TT = f'<<( {_GROUND_TT} <{EX}p> <{EX}o2> )>>'
_MIXED_TT = f'<<( ?s <{EX}b> {_GROUND_TT} )>>'
_TRIPLE_FN_GROUND = f'TRIPLE(<{EX}a>, <{EX}b>, <{EX}c>)'
_NESTED_TRIPLE_FN = f'TRIPLE({_TRIPLE_FN_GROUND}, <{EX}p>, <{EX}o2>)'

TT_OCCURRENCES = (_GROUND_TT, _VAR_TT, _NESTED_GROUND_TT, _MIXED_TT, _TRIPLE_FN_GROUND)
GROUND_OCCURRENCES = (_GROUND_TT, _NESTED_GROUND_TT, _TRIPLE_FN_GROUND, _NESTED_TRIPLE_FN)


def _pattern(occurrence: str) -> str:
    return f'?stmt <{EX}reifies> {occurrence} .'


# ---------------------------------------------------------------------------
# Block placements: where the triple-term pattern sits within the query.
# ---------------------------------------------------------------------------

WRAPPERS = {
    'bare':     lambda p: p,
    'graph':    lambda p: f'GRAPH <{EX}g> {{ {p} }}',
    'optional': lambda p: f'OPTIONAL {{ {p} }}',
    'union':    lambda p: f'{{ {p} }} UNION {{ ?x <{EX}y> ?z . }}',
}

# ---------------------------------------------------------------------------
# Query-form templates for a triple term used as a graph-pattern term.
# WHERE is grammatically optional for SELECT/ASK/DESCRIBE but mandatory for
# CONSTRUCT, so there's no construct/no-where variant.
# ---------------------------------------------------------------------------

FORM_TEMPLATES = {
    'select_where':      lambda p: f'SELECT * WHERE {{ {p} }}',
    'select_no_where':    lambda p: f'SELECT * {{ {p} }}',
    'ask_where':          lambda p: f'ASK WHERE {{ {p} }}',
    'ask_no_where':       lambda p: f'ASK {{ {p} }}',
    'construct':          lambda p: f'CONSTRUCT {{ ?stmt <{EX}reifies> ?anything . }} WHERE {{ {p} }}',
    'describe_where':     lambda p: f'DESCRIBE ?stmt WHERE {{ {p} }}',
    'describe_no_where':  lambda p: f'DESCRIBE ?stmt {{ {p} }}',
}

# ---------------------------------------------------------------------------
# Query-form templates for a *ground* triple term used as a bare value
# (SELECT projection / FILTER), the class of bug the ASK-without-WHERE
# ground-BIND fix (2026-07-16) belongs to.
# ---------------------------------------------------------------------------

PROJECTION_TEMPLATES = {
    'select_proj_where':     lambda occ: f'SELECT ({occ} AS ?t) WHERE {{}}',
    'select_proj_no_where':  lambda occ: f'SELECT ({occ} AS ?t) {{}}',
    'ask_filter_where':      lambda occ: f'ASK WHERE {{ FILTER(isTRIPLE({occ})) }}',
    'ask_filter_no_where':   lambda occ: f'ASK {{ FILTER(isTRIPLE({occ})) }}',
}


# ---------------------------------------------------------------------------
# Query-form templates for SUBJECT()/PREDICATE()/OBJECT() applied directly to
# a triple-term literal (any occurrence - ground or with variables, since
# this is pure textual extraction, not a match/lookup - see
# _rewrite_triple_accessor_literals). Self-equality inside FILTER rather than
# isTRIPLE()/BOUND() deliberately: isTRIPLE() has its own bare-variable-only
# argument restriction and BOUND() is grammatically variable-only in real
# SPARQL, so either would risk conflating a different, separate gap with the
# one this template set targets.
# ---------------------------------------------------------------------------

ACCESSOR_NAMES = ('SUBJECT', 'PREDICATE', 'OBJECT')

ACCESSOR_FORM_TEMPLATES = {
    'select_where':    lambda call: f'SELECT ({call} AS ?x) WHERE {{}}',
    'select_no_where': lambda call: f'SELECT ({call} AS ?x) {{}}',
    'ask_where':       lambda call: f'ASK WHERE {{ FILTER({call} = {call}) }}',
    'ask_no_where':    lambda call: f'ASK {{ FILTER({call} = {call}) }}',
}


def _assert_rewrites_to_valid_sparql(query: str) -> None:
    rewritten = rewrite_sparql12_to_11(query)
    parseQuery(rewritten)  # raises pyparsing.ParseException on invalid syntax


@settings(max_examples=200, deadline=None)
@given(
    occurrence=st.sampled_from(TT_OCCURRENCES),
    wrapper_name=st.sampled_from(sorted(WRAPPERS)),
    form_name=st.sampled_from(sorted(FORM_TEMPLATES)),
)
def test_triple_term_pattern_rewrites_to_valid_sparql(occurrence, wrapper_name, form_name):
    pattern = WRAPPERS[wrapper_name](_pattern(occurrence))
    query = FORM_TEMPLATES[form_name](pattern)
    _assert_rewrites_to_valid_sparql(query)


@settings(max_examples=50, deadline=None)
@given(
    occurrence=st.sampled_from(GROUND_OCCURRENCES),
    form_name=st.sampled_from(sorted(PROJECTION_TEMPLATES)),
)
def test_ground_triple_term_value_rewrites_to_valid_sparql(occurrence, form_name):
    query = PROJECTION_TEMPLATES[form_name](occurrence)
    _assert_rewrites_to_valid_sparql(query)


@settings(max_examples=100, deadline=None)
@given(
    accessor=st.sampled_from(ACCESSOR_NAMES),
    occurrence=st.sampled_from(TT_OCCURRENCES),
    form_name=st.sampled_from(sorted(ACCESSOR_FORM_TEMPLATES)),
)
def test_accessor_of_triple_term_literal_rewrites_to_valid_sparql(accessor, occurrence, form_name):
    call = f'{accessor}({occurrence})'
    query = ACCESSOR_FORM_TEMPLATES[form_name](call)
    _assert_rewrites_to_valid_sparql(query)
