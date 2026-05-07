"""
starlight.serializers.trix12

Serialize a StarlightGraph or StarlightDataset context to TriX 1.2 XML.

TriX is an XML-based named-graph format (http://www.w3.org/2004/03/trix/).
Each graph is a <graph> element containing <triple> elements.  This serializer
extends the standard with <tripleTerm> for RDF 1.2 triple terms, which may
appear in both subject and object positions.

Entry point:  serialize_trix12(g) -> str
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from rdflib import URIRef, BNode, Literal

from starlight.model.triple import TripleTerm

TRIX_NS = 'http://www.w3.org/2004/03/trix/trix-1/'
_XML_NS = 'http://www.w3.org/XML/1998/namespace'

_T = f'{{{TRIX_NS}}}'    # shorthand: '{ns}' prefix for element tags


def _term_elem(node, parent: ET.Element) -> ET.Element:
    """Append a TriX term element for *node* to *parent* and return it."""
    if isinstance(node, TripleTerm):
        tt = ET.SubElement(parent, f'{_T}tripleTerm')
        _term_elem(node.subject,   tt)
        _term_elem(node.predicate, tt)
        _term_elem(node.object,    tt)
        return tt

    if isinstance(node, URIRef):
        el = ET.SubElement(parent, f'{_T}uri')
        el.text = str(node)
        return el

    if isinstance(node, BNode):
        el = ET.SubElement(parent, f'{_T}id')
        el.text = str(node)
        return el

    if isinstance(node, Literal):
        if node.language:
            el = ET.SubElement(parent, f'{_T}plainLiteral')
            el.set(f'{{{_XML_NS}}}lang', node.language)
            el.text = str(node)
            return el
        dt = str(node.datatype) if node.datatype else 'http://www.w3.org/2001/XMLSchema#string'
        el = ET.SubElement(parent, f'{_T}typedLiteral')
        el.set('datatype', dt)
        el.text = str(node)
        return el

    raise TypeError(f'Unexpected node type: {type(node).__name__}: {node!r}')


def _sort_triple(t: tuple) -> tuple:
    return (str(t[0]), str(t[1]), str(t[2]))


def _append_graph(g, root: ET.Element) -> None:
    """Append a <graph> element for *g* to *root*."""
    graph_elem = ET.SubElement(root, f'{_T}graph')
    if isinstance(g.identifier, URIRef):
        uri_elem = ET.SubElement(graph_elem, f'{_T}uri')
        uri_elem.text = str(g.identifier)

    for s, p, o in sorted(g.triples((None, None, None)), key=_sort_triple):
        triple_elem = ET.SubElement(graph_elem, f'{_T}triple')
        _term_elem(s, triple_elem)
        _term_elem(p, triple_elem)
        _term_elem(o, triple_elem)


def serialize_trix12(g) -> str:
    """Serialize a StarlightGraph to TriX 1.2 XML text.

    Named graph identifier → <uri> as first child of <graph>.
    BNode identifier        → anonymous <graph> (default/unnamed graph).
    Triple terms emitted as <tripleTerm> with three nested term elements.
    """
    ET.register_namespace('', TRIX_NS)
    ET.register_namespace('xml', _XML_NS)

    root = ET.Element(f'{_T}TriX')
    _append_graph(g, root)

    ET.indent(root, space='  ')
    body = ET.tostring(root, encoding='unicode')
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{body}\n'


def serialize_trix12_dataset(ds) -> str:
    """Serialize a StarlightDataset to TriX 1.2 XML text.

    Each non-empty named graph becomes a separate <graph> block.
    """
    ET.register_namespace('', TRIX_NS)
    ET.register_namespace('xml', _XML_NS)

    root = ET.Element(f'{_T}TriX')
    for sg in ds.contexts():
        if len(sg) == 0:
            continue
        _append_graph(sg, root)

    ET.indent(root, space='  ')
    body = ET.tostring(root, encoding='unicode')
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{body}\n'
