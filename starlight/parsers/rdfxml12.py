"""
starlight.parsers.rdfxml12

Parse RDF/XML 1.2 text into (s, p, o) triples with TripleTerm objects.

rdflib's existing RDF/XML parser already handles <rdf:TripleTerm> elements,
producing blank nodes typed as rdf:TripleTerm with rdf:subject/predicate/object
triples.  This module converts that bnode-based encoding back to TripleTerm
objects so StarlightGraph.add() can re-encode them as tt: URIRefs.

Entry point:
    parse_rdfxml12(text) -> list of (s, p, o)
"""

from __future__ import annotations

import rdflib
from rdflib import URIRef, BNode, Literal
from rdflib.namespace import RDF

from starlight.model.triple import TripleTerm

_RDF_NS          = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'
_RDF_TRIPLE_TERM = URIRef(_RDF_NS + 'TripleTerm')
_ENCODING_PREDS  = frozenset({RDF.type, RDF.subject, RDF.predicate, RDF.object})


def _convert_bnodes(raw: rdflib.Graph) -> list[tuple]:
    """Convert the bnode-based rdf:TripleTerm encoding in *raw* to TripleTerm objects.

    Returns a list of (s, p, o) with TripleTerm objects where the bnode
    encoding triples used to be.
    """
    # Identify all bnodes that represent triple terms
    tt_bnodes: dict[BNode, tuple] = {}
    for bnode in raw.subjects(RDF.type, _RDF_TRIPLE_TERM):
        if not isinstance(bnode, BNode):
            continue
        s_list = list(raw.objects(bnode, RDF.subject))
        p_list = list(raw.objects(bnode, RDF.predicate))
        o_list = list(raw.objects(bnode, RDF.object))
        if len(s_list) == 1 and len(p_list) == 1 and len(o_list) == 1:
            tt_bnodes[bnode] = (s_list[0], p_list[0], o_list[0])

    # Recursively build TripleTerm objects (handles nested triple terms)
    tt_cache: dict[BNode, TripleTerm] = {}

    def _build(bnode: BNode) -> TripleTerm:
        if bnode in tt_cache:
            return tt_cache[bnode]
        s_n, p_n, o_n = tt_bnodes[bnode]
        s = _build(s_n) if isinstance(s_n, BNode) and s_n in tt_bnodes else s_n
        o = _build(o_n) if isinstance(o_n, BNode) and o_n in tt_bnodes else o_n
        tt = TripleTerm(s, p_n, o)
        tt_cache[bnode] = tt
        return tt

    for bn in tt_bnodes:
        _build(bn)

    # Collect non-encoding triples, substituting TripleTerm objects for bnodes
    result: list[tuple] = []
    for s, p, o in raw:
        # Skip encoding triples that belong to a tt bnode
        if isinstance(s, BNode) and s in tt_bnodes and p in _ENCODING_PREDS:
            continue
        s_out = tt_cache.get(s, s) if isinstance(s, BNode) else s
        o_out = tt_cache.get(o, o) if isinstance(o, BNode) else o
        result.append((s_out, p, o_out))

    return result


def parse_rdfxml12(text: str) -> list[tuple]:
    """Parse RDF/XML 1.2 text; return list of (s, p, o) triples.

    <rdf:TripleTerm> elements are converted to TripleTerm objects.
    Subjects and objects may be TripleTerm instances.
    """
    raw = rdflib.Graph()
    raw.parse(data=text, format='xml')
    return _convert_bnodes(raw)
