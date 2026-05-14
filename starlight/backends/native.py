"""
starlight.backends.native

HTTP-level utilities for native RDF 1.2 backends (rdf-star and rdf-1.2 modes).

rdflib 7.x does not handle "type":"triple" in SPARQL JSON results, so these
functions bypass rdflib's SPARQL stack and talk directly to SPARQL endpoints
via HTTP.

Public API used by StarlightGraph:
    sparql_term(node, backend)          → SPARQL inline string
    rewrite_12_to_backend(query, mode)  → query string with correct TT syntax
    http_select(url, sparql, auth)      → (vars, bindings)
    http_construct(url, sparql, auth)   → (body_bytes, content_type)
    http_update(url, sparql, auth)      → None
    http_ask(url, sparql, auth)         → bool
    build_result(vars_, bindings)       → rdflib.query.Result
"""

from __future__ import annotations

import requests
from rdflib import URIRef, Literal, BNode
from rdflib.term import Variable
from rdflib.query import Result

from starlight.model.triple import TripleTerm


# ---------------------------------------------------------------------------
# Term serialization
# ---------------------------------------------------------------------------

def sparql_term(node, backend: str) -> str:
    """Serialize an RDF node to its SPARQL inline string for the given backend.

    TripleTerms are rendered as:
      rdf-star  ->  << s p o >>
      rdf-1.2   ->  <<( s p o )>>
    All other nodes use rdflib's .n3() which produces correct SPARQL syntax.
    """
    if isinstance(node, TripleTerm):
        s = sparql_term(node.subject,   backend)
        p = sparql_term(node.predicate, backend)
        o = sparql_term(node.object,    backend)
        if backend == 'rdf-1.2':
            return f'<<( {s} {p} {o} )>>'
        return f'<< {s} {p} {o} >>'
    return node.n3()


# ---------------------------------------------------------------------------
# SPARQL 1.2 → backend syntax rewrite
# ---------------------------------------------------------------------------

def rewrite_12_to_backend(query: str, backend: str) -> str:
    """Rewrite SPARQL 1.2 <<( )>> triple-term syntax to the backend's form.

    - rdf-1.2:  pass through unchanged (the backend speaks final-spec syntax)
    - rdf-star: <<( s p o )>> → << s p o >> (Jena RDF-star draft syntax)

    Handles nested triple terms correctly.
    """
    if backend == 'rdf-1.2' or '<<(' not in query:
        return query
    from starlight.query.sparql12_to_11 import _consume_triple_term
    result = []
    i = 0
    while i < len(query):
        if query.startswith('<<(', i):
            token, j = _consume_triple_term(query, i)
            inner = token[3:-3].strip()
            inner = rewrite_12_to_backend(inner, backend)
            result.append(f'<< {inner} >>')
            i = j
        else:
            result.append(query[i])
            i += 1
    return ''.join(result)


# ---------------------------------------------------------------------------
# JSON result parsing
# ---------------------------------------------------------------------------

def _parse_json_term(term_dict: dict):
    """Convert a SPARQL JSON binding term to an rdflib node or TripleTerm."""
    t = term_dict['type']
    if t == 'uri':
        return URIRef(term_dict['value'])
    if t == 'bnode':
        return BNode(term_dict['value'])
    if t in ('literal', 'typed-literal'):
        lang  = term_dict.get('xml:lang')
        dtype = term_dict.get('datatype')
        if lang:
            return Literal(term_dict['value'], lang=lang)
        if dtype:
            return Literal(term_dict['value'], datatype=URIRef(dtype))
        return Literal(term_dict['value'])
    if t == 'triple':
        v = term_dict['value']
        s = _parse_json_term(v['subject'])
        p = _parse_json_term(v['predicate'])
        o = _parse_json_term(v['object'])
        return TripleTerm(s, p, o)
    raise ValueError(f'Unknown SPARQL JSON term type: {t!r}')


def _parse_bindings(data: dict) -> tuple[list[Variable], list[dict]]:
    """Parse the bindings section of a SPARQL JSON SELECT response."""
    vars_ = [Variable(v) for v in data['head']['vars']]
    bindings = []
    for row in data['results']['bindings']:
        binding = {}
        for v in vars_:
            raw = row.get(str(v))   # str(Variable('o')) == 'o', not '?o'
            if raw is not None:
                binding[v] = _parse_json_term(raw)
        bindings.append(binding)
    return vars_, bindings


# ---------------------------------------------------------------------------
# HTTP execution
# ---------------------------------------------------------------------------

def http_select(query_url: str, sparql: str, extra_headers: dict | None = None) -> tuple[list, list]:
    """Execute a SPARQL SELECT and return (vars, bindings).

    Handles "type":"triple" in results — converting them to TripleTerm objects.
    """
    headers = {
        'Content-Type': 'application/sparql-query',
        'Accept': 'application/sparql-results+json',
    }
    if extra_headers:
        headers.update(extra_headers)
    resp = requests.post(query_url, data=sparql.encode('utf-8'), headers=headers, timeout=30)
    resp.raise_for_status()
    return _parse_bindings(resp.json())


def http_construct(query_url: str, sparql: str, extra_headers: dict | None = None) -> tuple[bytes, str]:
    """Execute a SPARQL CONSTRUCT or DESCRIBE and return (body_bytes, content_type).

    Requests Turtle, which both rdf-star and rdf-1.2 backends support and which
    StarlightGraph.parse() handles natively including triple-term syntax.
    """
    headers = {
        'Content-Type': 'application/sparql-query',
        'Accept': 'text/turtle',
    }
    if extra_headers:
        headers.update(extra_headers)
    resp = requests.post(query_url, data=sparql.encode('utf-8'), headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.content, resp.headers.get('Content-Type', 'text/turtle')


def http_update(update_url: str, sparql: str, extra_headers: dict | None = None) -> None:
    """Execute a SPARQL UPDATE against the endpoint."""
    headers = {'Content-Type': 'application/sparql-update'}
    if extra_headers:
        headers.update(extra_headers)
    resp = requests.post(update_url, data=sparql.encode('utf-8'), headers=headers, timeout=30)
    resp.raise_for_status()


def http_ask(query_url: str, sparql: str, extra_headers: dict | None = None) -> bool:
    """Execute a SPARQL ASK and return the boolean result."""
    headers = {
        'Content-Type': 'application/sparql-query',
        'Accept': 'application/sparql-results+json',
    }
    if extra_headers:
        headers.update(extra_headers)
    resp = requests.post(query_url, data=sparql.encode('utf-8'), headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json().get('boolean', False)


def build_result(vars_: list, bindings: list) -> Result:
    """Construct an rdflib Result object from pre-parsed SELECT data."""
    r = Result('SELECT')
    r.vars = vars_
    r.bindings = bindings
    return r
