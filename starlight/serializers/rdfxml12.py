"""
starlight.serializers.rdfxml12

Serialize a StarlightGraph to RDF/XML 1.2.

Triple terms in object position are emitted as inline <rdf:TripleTerm> elements.
Triple terms in subject position are emitted as top-level <rdf:TripleTerm>
elements with rdf:nodeID, which is valid RDF/XML (a typed node element that also
carries property elements).  When the same TripleTerm appears in both roles,
the object reference uses rdf:nodeID to point to the top-level element.

Predicate IRIs must be QName-able (i.e. splittable at a '#' or '/' boundary
with a non-digit local name).  IRIs that cannot be expressed as QNames raise
ValueError.

Entry point:  serialize_rdfxml12(graph) -> str
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import defaultdict
from rdflib import URIRef, BNode, Literal

from starlight.model.triple import TripleTerm

_RDF_NS  = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'
_XML_NS  = 'http://www.w3.org/XML/1998/namespace'
_XSD_STR = 'http://www.w3.org/2001/XMLSchema#string'

_R = f'{{{_RDF_NS}}}'


# ---------------------------------------------------------------------------
# IRI → Clark-notation tag
# ---------------------------------------------------------------------------

def _split_iri(iri: str) -> tuple[str, str]:
    """Split an IRI into (namespace_uri, local_name).

    Tries '#' first, then '/'.  Raises ValueError if the local name cannot
    form a valid XML name start character.
    """
    for sep in ('#', '/'):
        if sep in iri:
            idx = iri.rfind(sep)
            ns, local = iri[:idx + 1], iri[idx + 1:]
            if local and (local[0].isalpha() or local[0] == '_'):
                return ns, local
    raise ValueError(f'Cannot express as a QName: {iri!r}')


def _clark(iri: str) -> str:
    """Return Clark-notation tag {ns}local for *iri*."""
    ns, local = _split_iri(iri)
    return f'{{{ns}}}{local}'


# ---------------------------------------------------------------------------
# Namespace registration
# ---------------------------------------------------------------------------

def _register_ns(sg) -> None:
    """Register graph namespaces with ElementTree so prefixes are stable."""
    ET.register_namespace('rdf', _RDF_NS)
    ET.register_namespace('xml', _XML_NS)
    for prefix, ns_uri in sg.namespaces():
        if prefix and str(ns_uri) not in (_RDF_NS, _XML_NS):
            ET.register_namespace(prefix, str(ns_uri))


# ---------------------------------------------------------------------------
# Object serialization helpers
# ---------------------------------------------------------------------------

def _inline_tt_structure(parent: ET.Element, tt: TripleTerm, tt_nodeids: dict) -> None:
    """Append <rdf:subject>, <rdf:predicate>, <rdf:object> children for *tt*."""
    for rdf_role, component in (
        ('subject',   tt.subject),
        ('predicate', tt.predicate),
        ('object',    tt.object),
    ):
        child = ET.SubElement(parent, f'{_R}{rdf_role}')
        _set_object(child, component, tt_nodeids)


def _set_object(prop: ET.Element, obj, tt_nodeids: dict) -> None:
    """Configure *prop* for the given object node (attribute or nested element)."""
    if isinstance(obj, URIRef):
        prop.set(f'{_R}resource', str(obj))

    elif isinstance(obj, BNode):
        prop.set(f'{_R}nodeID', str(obj))

    elif isinstance(obj, Literal):
        prop.text = str(obj)
        if obj.language:
            prop.set(f'{{{_XML_NS}}}lang', obj.language)
        elif obj.datatype and str(obj.datatype) != _XSD_STR:
            prop.set(f'{_R}datatype', str(obj.datatype))

    elif isinstance(obj, TripleTerm):
        if obj in tt_nodeids:
            # Reference the top-level element by its nodeID
            prop.set(f'{_R}nodeID', tt_nodeids[obj])
        else:
            # Inline: anonymous TripleTerm appears only as an object
            tt_elem = ET.SubElement(prop, f'{_R}TripleTerm')
            _inline_tt_structure(tt_elem, obj, tt_nodeids)

    else:
        raise TypeError(f'Unexpected object type: {type(obj).__name__}: {obj!r}')


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def serialize_rdfxml12(graph) -> str:
    """Serialize a StarlightGraph to RDF/XML 1.2 text.

    Triple terms in object position → inline <rdf:TripleTerm>.
    Triple terms in subject position → top-level <rdf:TripleTerm rdf:nodeID=...>.
    When the same TripleTerm appears in both roles, the object uses rdf:nodeID.
    """
    from starlight.graph.starlight_graph import StarlightGraph

    sg = graph if isinstance(graph, StarlightGraph) else StarlightGraph.from_rdflib(graph)
    _register_ns(sg)

    # --- Pass 1: find TripleTerms that appear as subjects → assign nodeIDs ---
    tt_nodeids: dict[TripleTerm, str] = {}
    _counter = [0]

    def _ensure_id(tt: TripleTerm) -> str:
        if tt not in tt_nodeids:
            tt_nodeids[tt] = f'tt{_counter[0]}'
            _counter[0] += 1
        return tt_nodeids[tt]

    for s, _p, _o in sg.triples((None, None, None)):
        if isinstance(s, TripleTerm):
            _ensure_id(s)

    # --- Pass 2: group triples by subject ---
    by_subj: dict = defaultdict(list)
    for s, p, o in sg.triples((None, None, None)):
        by_subj[s].append((p, o))

    # --- Pass 3: build XML ---
    root = ET.Element(f'{_R}RDF')

    def _sort_key(node) -> str:
        return str(node)

    for subj in sorted(by_subj.keys(), key=_sort_key):
        pred_objs = by_subj[subj]

        if isinstance(subj, TripleTerm):
            # Top-level typed node element
            desc = ET.SubElement(root, f'{_R}TripleTerm')
            desc.set(f'{_R}nodeID', tt_nodeids[subj])
            _inline_tt_structure(desc, subj, tt_nodeids)
        elif isinstance(subj, URIRef):
            desc = ET.SubElement(root, f'{_R}Description')
            desc.set(f'{_R}about', str(subj))
        else:  # BNode
            desc = ET.SubElement(root, f'{_R}Description')
            desc.set(f'{_R}nodeID', str(subj))

        for pred, obj in sorted(pred_objs, key=lambda x: (str(x[0]), str(x[1]))):
            prop_tag = _clark(str(pred))
            prop = ET.SubElement(desc, prop_tag)
            _set_object(prop, obj, tt_nodeids)

    ET.indent(root, space='  ')
    body = ET.tostring(root, encoding='unicode')
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{body}\n'
