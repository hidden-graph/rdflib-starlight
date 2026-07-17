"""
starlight.backends.native

HTTP-level utilities for the native RDF 1.2 backend.

rdflib 7.x does not handle "type":"triple" in SPARQL JSON results, so these
functions bypass rdflib's SPARQL stack and talk directly to SPARQL endpoints
via HTTP.

Public API used by StarlightGraph:
    sparql_term(node)                   → SPARQL inline string
    http_select(url, sparql, auth)      → (vars, bindings)
    http_construct(url, sparql, auth)   → (body_bytes, content_type)
    http_update(url, sparql, auth)      → None
    http_ask(url, sparql, auth)         → bool
    build_result(vars_, bindings)       → rdflib.query.Result

The endpoint (e.g. Apache Jena Fuseki 5.5+, Oxigraph) speaks SPARQL 1.2
natively - triple-term syntax (<<( s p o )>>), TRIPLE()/isTRIPLE(), and the
base-direction functions (LANGDIR/hasLANGDIR/STRLANGDIR/LANG/hasLANG) are all
sent straight through with no rewriting, confirmed 2026-07-16 against live
Fuseki 5.5.0 and Oxigraph 0.5.9. This is a different code path from the
default rdf-1.1 backend's rewrite_sparql12_to_11()
(starlight/query/sparql12_to_11.py), which never runs here - see
StarlightGraph._native_query()/_native_add()/_native_triples().
"""

from __future__ import annotations

import requests
from rdflib import URIRef, Literal, BNode
from rdflib.term import Variable
from rdflib.query import Result

from starlight.model.triple import TripleTerm
from starlight.model.dirlangstring import DirLangString


# ---------------------------------------------------------------------------
# Term serialization
# ---------------------------------------------------------------------------

def sparql_term(node) -> str:
    """Serialize an RDF node to its SPARQL inline string.

    TripleTerms are rendered as <<( s p o )>>. A DirLangString is rendered as
    the real "text"@lang--dir lexical form - unlike TripleTerm's tt:HASH
    encoding, the native RDF 1.2 endpoint understands this syntax directly, so
    no internal encoding is involved here at all. All other nodes use
    rdflib's .n3() which produces correct SPARQL syntax.
    """
    if isinstance(node, TripleTerm):
        s = sparql_term(node.subject)
        p = sparql_term(node.predicate)
        o = sparql_term(node.object)
        return f'<<( {s} {p} {o} )>>'
    if isinstance(node, DirLangString):
        escaped = node.value.replace('\\', '\\\\').replace('"', '\\"')
        return f'"{escaped}"@{node.language}--{node.direction}'
    return node.n3()


# ---------------------------------------------------------------------------
# JSON result parsing
# ---------------------------------------------------------------------------

def _parse_json_term(term_dict: dict):
    """Convert a SPARQL JSON binding term to an rdflib node, DirLangString, or TripleTerm."""
    t = term_dict['type']
    if t == 'uri':
        return URIRef(term_dict['value'])
    if t == 'bnode':
        return BNode(term_dict['value'])
    if t in ('literal', 'typed-literal'):
        lang  = term_dict.get('xml:lang')
        dtype = term_dict.get('datatype')
        # Confirmed 2026-07-16 against live Fuseki 5.5.0 and Oxigraph 0.5.9
        # (both agree independently): the SPARQL 1.2 JSON Results key is
        # "its:dir", mirroring the its:dir attribute RDF/XML 1.2 also uses -
        # not "direction", which was an earlier unverified guess. Returned
        # directly as a DirLangString rather than the internal dirlang:
        # Literal encoding, since native-backend results never round-trip
        # through StarlightGraph._restore() - same as how a "triple" binding
        # below returns a TripleTerm directly.
        direction = term_dict.get('its:dir')
        if lang and direction:
            from starlight.model.dirlangstring import DirLangString
            return DirLangString(term_dict['value'], lang, direction)
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

    Requests Turtle, which the endpoint supports and which
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
