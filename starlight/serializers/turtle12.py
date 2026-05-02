"""
starlight.serializers.turtle12

Serialize a StarlightGraph (or a raw rdflib.Graph with the SL internal
encoding) to Turtle 1.2 text, writing triple terms as <<( s p o )>>.

Entry point: serialize_turtle12(graph) -> str

Approach: walk sg.triples() directly — which already returns TripleTerm objects
and filters encoding triples — rather than post-processing rdflib's Turtle output.
This avoids the inline-bnode problem (rdflib collapses bnodes with no outgoing
triples to `[ ]`, losing their ID).
"""

from collections import defaultdict
from rdflib import BNode, URIRef, Literal
from rdflib.namespace import RDF

from starlight.model.triple import TripleTerm
from starlight.model.encoding import TT_NS, RR_NS

SL_NS = 'http://starlight.org/ns#'
_RDF_NS = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'
_INTERNAL_NS = {SL_NS, TT_NS, RR_NS}


def _node_to_ttl(node, ns_mgr):
    """Format an rdflib node as a Turtle token using namespace prefixes."""
    if isinstance(node, URIRef):
        # Anonymous reifier URIs are internal — serialize as blank nodes so
        # re-parsing re-assigns them via _skolemize_encoding for round-trip stability.
        s = str(node)
        if s.startswith(RR_NS):
            return '_:rr_' + s[len(RR_NS):]
        try:
            qn = ns_mgr.qname(s)
            # rdflib returns bare local names for the empty prefix ('' → 'a' not ':a')
            if ':' not in qn:
                qn = ':' + qn
            return qn
        except Exception:
            return f'<{node}>'
    if isinstance(node, BNode):
        return f'_:{node}'
    if isinstance(node, Literal):
        escaped = str(node).replace('\\', '\\\\').replace('"', '\\"')
        if node.language:
            return f'"{escaped}"@{node.language}'
        if node.datatype and str(node.datatype) != 'http://www.w3.org/2001/XMLSchema#string':
            try:
                dt = ns_mgr.qname(str(node.datatype))
            except Exception:
                dt = f'<{node.datatype}>'
            return f'"{escaped}"^^{dt}'
        return f'"{escaped}"'
    return str(node)


def _tt_to_str(tt, ns_mgr):
    """Recursively format a TripleTerm as <<( s p o )>>."""
    s = _tt_to_str(tt.subject,  ns_mgr) if isinstance(tt.subject,  TripleTerm) else _node_to_ttl(tt.subject,  ns_mgr)
    p = _node_to_ttl(tt.predicate, ns_mgr)
    o = _tt_to_str(tt.object,   ns_mgr) if isinstance(tt.object,   TripleTerm) else _node_to_ttl(tt.object,   ns_mgr)
    return f'<<( {s} {p} {o} )>>'


def _fmt(node, ns_mgr):
    """Format any node (including TripleTerm) as a Turtle string."""
    if isinstance(node, TripleTerm):
        return _tt_to_str(node, ns_mgr)
    return _node_to_ttl(node, ns_mgr)


def _sort_key(node):
    if isinstance(node, URIRef):
        return (0, str(node))
    if isinstance(node, BNode):
        return (1, str(node))
    return (2, str(getattr(node, '_key', lambda: node)()))


def serialize_turtle12(graph) -> str:
    """Serialize a StarlightGraph or rdflib.Graph (with SL encoding) to Turtle 1.2.

    Triple terms are emitted as <<( s p o )>>. Internal encoding triples
    (sl:TripleTerm, sl:Reification, rdf:subject/predicate/object) are omitted.
    Only namespace prefixes actually used in the graph are emitted.
    """
    from starlight.graph.starlight_graph import StarlightGraph

    sg = graph if isinstance(graph, StarlightGraph) else StarlightGraph.from_rdflib(graph)
    ns_mgr = sg.namespace_manager

    # --- Pass 1: generate triple lines, collecting used URIRef strings ---
    by_subj: dict = defaultdict(lambda: defaultdict(list))
    used_uris: set = set()

    def _fmt_collect(node, ns_mgr):
        """Format node and record any URIRef string for prefix filtering."""
        if isinstance(node, TripleTerm):
            _collect_tt(node)
            return _tt_to_str(node, ns_mgr)
        if isinstance(node, URIRef) and not str(node).startswith(RR_NS):
            used_uris.add(str(node))
        elif isinstance(node, Literal) and node.datatype:
            used_uris.add(str(node.datatype))
        return _node_to_ttl(node, ns_mgr)

    def _collect_tt(tt):
        for part in (tt.subject, tt.predicate, tt.object):
            if isinstance(part, TripleTerm):
                _collect_tt(part)
            elif isinstance(part, URIRef):
                used_uris.add(str(part))

    for s, p, o in sg.triples((None, None, None)):
        by_subj[s][p].append(o)

    triple_lines = []
    for subj in sorted(by_subj.keys(), key=_sort_key):
        s_str = _fmt_collect(subj, ns_mgr)
        pred_items = sorted(by_subj[subj].items(), key=lambda x: str(x[0]))
        n_preds = len(pred_items)

        for i, (pred, objs) in enumerate(pred_items):
            used_uris.add(str(pred))
            p_str = _fmt(pred, ns_mgr)
            is_last_pred = (i == n_preds - 1)
            o_combined = ', '.join(_fmt_collect(o, ns_mgr) for o in objs)
            end = ' .' if is_last_pred else ' ;'

            if i == 0:
                triple_lines.append(f'{s_str} {p_str} {o_combined}{end}')
            else:
                triple_lines.append(f'    {p_str} {o_combined}{end}')

        triple_lines.append('')

    # --- Pass 2: emit only used prefix declarations ---
    prefix_lines = []
    for prefix, ns_uri in sorted(sg.namespaces(), key=lambda x: x[0]):
        ns = str(ns_uri)
        if ns in _INTERNAL_NS:
            continue
        if any(u.startswith(ns) for u in used_uris):
            prefix_lines.append(f'@prefix {prefix}: <{ns_uri}> .')

    if _RDF_NS not in {str(ns) for _, ns in sg.namespaces()}:
        prefix_lines.append(f'@prefix rdf: <{_RDF_NS}> .')

    prefix_lines.append('')

    return '\n'.join(prefix_lines + triple_lines)
