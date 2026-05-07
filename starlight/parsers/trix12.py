"""
starlight.parsers.trix12

Parse TriX 1.2 XML into triples, preserving or merging named-graph structure.

TriX is an XML-based named-graph format. Each <graph> block contains <triple>
elements whose three children are term nodes.  This parser extends standard
TriX with <tripleTerm> for RDF 1.2 triple terms, which may appear in both
subject and object positions.

Entry points:
    parse_trix12(text)        -> list of (s, p, o)            (merges all graphs)
    parse_trix12_named(text)  -> list of (graph_id, triples)  (preserves structure)
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from rdflib import URIRef, BNode, Literal

from starlight.model.triple import TripleTerm

TRIX_NS  = 'http://www.w3.org/2004/03/trix/trix-1/'
_XML_NS  = 'http://www.w3.org/XML/1998/namespace'

_TAG_URI         = f'{{{TRIX_NS}}}uri'
_TAG_ID          = f'{{{TRIX_NS}}}id'
_TAG_PLAIN       = f'{{{TRIX_NS}}}plainLiteral'
_TAG_TYPED       = f'{{{TRIX_NS}}}typedLiteral'
_TAG_TRIPLE_TERM = f'{{{TRIX_NS}}}tripleTerm'
_TAG_TRIPLE      = f'{{{TRIX_NS}}}triple'
_TAG_GRAPH       = f'{{{TRIX_NS}}}graph'


def _parse_term(elem: ET.Element):
    """Convert a TriX term element to an rdflib node or TripleTerm."""
    tag = elem.tag

    if tag == _TAG_URI:
        return URIRef((elem.text or '').strip())

    if tag == _TAG_ID:
        return BNode((elem.text or '').strip())

    if tag == _TAG_PLAIN:
        lang = elem.get(f'{{{_XML_NS}}}lang')
        return Literal(elem.text or '', lang=lang if lang else None)

    if tag == _TAG_TYPED:
        datatype = elem.get('datatype', '')
        return Literal(elem.text or '', datatype=URIRef(datatype))

    if tag == _TAG_TRIPLE_TERM:
        children = list(elem)
        if len(children) != 3:
            raise ValueError(
                f'<tripleTerm> must have exactly 3 children, got {len(children)}'
            )
        return TripleTerm(
            _parse_term(children[0]),
            _parse_term(children[1]),
            _parse_term(children[2]),
        )

    raise ValueError(f'Unknown TriX term element: {tag!r}')


def _parse_graph(graph_elem: ET.Element) -> tuple[URIRef | None, list[tuple]]:
    """Parse a <graph> element; return (graph_id, triples).

    The graph is named when its first child is a <uri> element.
    """
    children = list(graph_elem)
    if not children:
        return None, []

    graph_id: URIRef | None = None
    start = 0
    if children[0].tag == _TAG_URI:
        graph_id = URIRef((children[0].text or '').strip())
        start = 1

    triples: list[tuple] = []
    for child in children[start:]:
        if child.tag != _TAG_TRIPLE:
            continue
        terms = list(child)
        if len(terms) != 3:
            raise ValueError(f'<triple> must have exactly 3 children, got {len(terms)}')
        s = _parse_term(terms[0])
        p = _parse_term(terms[1])
        o = _parse_term(terms[2])
        triples.append((s, p, o))

    return graph_id, triples


def _iter_graphs(text: str):
    """Yield (graph_id, triples) pairs from a TriX document."""
    root = ET.fromstring(text)
    tag_trix = f'{{{TRIX_NS}}}TriX'
    # Accept both the namespaced and the bare root tag for robustness
    if root.tag not in (tag_trix, 'TriX'):
        raise ValueError(f'Expected <TriX> root element, got {root.tag!r}')
    for child in root:
        if child.tag == _TAG_GRAPH:
            yield _parse_graph(child)


def parse_trix12(text: str) -> list[tuple]:
    """Parse TriX 1.2 text; return list of (s, p, o) triples.

    All named graphs are merged. Subjects and objects may be TripleTerm
    instances for RDF 1.2 triple terms.
    """
    triples: list[tuple] = []
    for _gid, graph_triples in _iter_graphs(text):
        triples.extend(graph_triples)
    return triples


def parse_trix12_named(text: str) -> list[tuple[URIRef | None, list[tuple]]]:
    """Parse TriX 1.2 text; return list of (graph_id, triples).

    graph_id is None for anonymous/default graphs, a URIRef for named graphs.
    Subjects and objects may be TripleTerm instances.
    """
    return [(gid, triples) for gid, triples in _iter_graphs(text) if triples]
