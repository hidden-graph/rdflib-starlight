"""Starlight-aware wrappers for rdflib SPARQL parse/prepare functions.

These wrappers accept SPARQL 1.2 syntax and return parse trees that preserve
SPARQL 1.2 structure.  The strategy for ``parseQuery`` and ``parseUpdate`` is:

  1. Rewrite SPARQL 1.2 → SPARQL 1.1 text (``rewrite_sparql12_to_11``)
  2. Parse the SPARQL 1.1 with rdflib's parser
  3. Detect the encoding triple-patterns injected by the rewriter and remove
     them from the parse tree, replacing the internal ``?__ttN`` variables with
     ``CompValue('TripleTerm', subject=…, predicate=…, object=…)`` nodes that
     preserve the original triple-term structure.

``prepareQuery`` and ``prepareUpdate`` rewrite to SPARQL 1.1 before delegating
to rdflib because the compiled algebra must be SPARQL 1.1-compatible for rdflib
to execute it.

Use these instead of the rdflib originals when working with SPARQL 1.2 queries::

    from starlight.query import parseQuery, prepareQuery, parseUpdate, prepareUpdate

    # All of these now accept SPARQL 1.2 triple-term syntax
    parseQuery("SELECT ?s WHERE { <<( ?s ?p ?o )>> ex:certainty ?c }")
    prepareQuery("SELECT ?s WHERE { <<( ?s ?p ?o )>> ex:certainty ?c }")
    parseUpdate("DELETE WHERE { <<( ?s ?p ?o )>> ?pred ?val }")
    prepareUpdate("DELETE WHERE { <<( ?s ?p ?o )>> ?pred ?val }")
"""

from __future__ import annotations

from .sparql12_to_11 import rewrite_sparql12_to_11, _rewrite_sparql12_to_11_tracked

_RDF_SUBJECT   = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#subject'
_RDF_PREDICATE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#predicate'
_RDF_OBJECT    = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#object'


def _extract_path_iri(predicate_node):
    """Return the underlying URIRef from a simple PathAlternative predicate, or None."""
    from rdflib import URIRef
    from rdflib.plugins.sparql.parserutils import CompValue
    try:
        if isinstance(predicate_node, CompValue) and predicate_node.name == 'PathAlternative':
            iri = predicate_node['part'][0]['part'][0]['part']
            return iri if isinstance(iri, URIRef) else None
    except (KeyError, IndexError, TypeError, AttributeError):
        pass
    if isinstance(predicate_node, __import__('rdflib').URIRef):
        return predicate_node
    return None


def _restore_sparql12_in_tree(parse_result, generated_tt_vars: frozenset):
    """Post-process a rdflib SPARQL 1.1 parse tree to restore SPARQL 1.2 nodes.

    Detects the encoding triple-patterns that ``_rewrite_sparql12_to_11_tracked``
    injects for ``<<( s p o )>>`` triple terms::

        ?__ttN  rdf:subject   <s>
        ?__ttN  rdf:predicate <p>
        ?__ttN  rdf:object    <o>

    Only variables whose names appear in ``generated_tt_vars`` (the exact set
    produced during this parse) are treated as encoding variables.  User-written
    variables that happen to share the ``__tt`` prefix are left untouched.

    These are removed from every ``TriplesBlock`` in the tree.  Each generated
    ``?__ttN`` variable is then replaced everywhere in the parse tree with a
    ``CompValue('TripleTerm', subject=…, predicate=…, object=…)`` node whose
    children carry the original (potentially nested) SPARQL 1.2 terms.

    Returns the modified ``parse_result`` in place.  Queries with no SPARQL 1.2
    encoding patterns are returned unchanged.
    """
    from rdflib import URIRef, Variable
    from rdflib.plugins.sparql.parserutils import CompValue

    def _is_tt_var(node) -> bool:
        return isinstance(node, Variable) and str(node) in generated_tt_vars

    rdf_s = URIRef(_RDF_SUBJECT)
    rdf_p = URIRef(_RDF_PREDICATE)
    rdf_o = URIRef(_RDF_OBJECT)

    # ------------------------------------------------------------------
    # Phase 1 — collect encoding triples and strip them from TriplesBlocks
    # ------------------------------------------------------------------
    encoding: dict[str, dict] = {}   # var_name → {'s': node, 'p': node, 'o': node}

    def _strip_triples_block(triples):
        """Remove encoding triples; record their s/p/o mappings."""
        remaining = []
        for t in triples:
            if len(t) < 3:
                remaining.append(t)
                continue
            s, p, o = t[0], t[1], t[2]
            if _is_tt_var(s):
                iri = _extract_path_iri(p)
                if iri == rdf_s:
                    encoding.setdefault(str(s), {})['s'] = o
                    continue
                elif iri == rdf_p:
                    encoding.setdefault(str(s), {})['p'] = o
                    continue
                elif iri == rdf_o:
                    encoding.setdefault(str(s), {})['o'] = o
                    continue
            remaining.append(t)
        return remaining

    def _walk_collect(node):
        if isinstance(node, CompValue):
            if node.name == 'TriplesBlock':
                node['triples'] = _strip_triples_block(node.get('triples', []))
            for v in node.values():
                _walk_collect(v)
        elif isinstance(node, list):
            for item in node:
                _walk_collect(item)

    for item in parse_result:
        if isinstance(item, (CompValue, list)):
            _walk_collect(item)

    if not encoding:
        return parse_result

    # ------------------------------------------------------------------
    # Phase 2 — build TripleTerm CompValue nodes (resolve nested TTs first)
    # ------------------------------------------------------------------
    tt_map: dict[str, CompValue] = {}

    def _resolve(var_name: str):
        if var_name in tt_map:
            return tt_map[var_name]
        parts = encoding.get(var_name, {})
        if not all(k in parts for k in ('s', 'p', 'o')):
            return None
        sv, pv, ov = parts['s'], parts['p'], parts['o']
        s = _resolve(str(sv)) if _is_tt_var(sv) else sv
        o = _resolve(str(ov)) if _is_tt_var(ov) else ov
        if s is None or o is None:
            return None
        node = CompValue('TripleTerm', subject=s, predicate=pv, object=o)
        tt_map[var_name] = node
        return node

    for var_name in list(encoding):
        _resolve(var_name)

    if not tt_map:
        return parse_result

    # ------------------------------------------------------------------
    # Phase 3 — replace Variable('__ttN') with TripleTerm nodes everywhere
    # ------------------------------------------------------------------

    def _sub(node):
        """Return the replacement node if node is a __ttN variable, else node."""
        return tt_map.get(str(node), node) if _is_tt_var(node) else node

    def _walk_replace(node):
        if isinstance(node, CompValue):
            if node.name == 'TriplesBlock':
                for t in node.get('triples', []):
                    if _is_tt_var(t[0]):
                        t[0] = _sub(t[0])
                    if len(t) >= 3 and _is_tt_var(t[2]):
                        t[2] = _sub(t[2])
            for k, v in list(node.items()):
                new_v = _sub(v)
                if new_v is not v:
                    node[k] = new_v
                else:
                    _walk_replace(v)
        elif isinstance(node, list):
            for i, item in enumerate(node):
                new_item = _sub(item)
                if new_item is not item:
                    node[i] = new_item
                else:
                    _walk_replace(item)

    for item in parse_result:
        if isinstance(item, (CompValue, list)):
            _walk_replace(item)

    return parse_result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parseQuery(q):
    """Parse a SPARQL 1.2 SELECT/ASK/CONSTRUCT/DESCRIBE query string.

    Rewrites SPARQL 1.2 triple-term syntax to SPARQL 1.1, calls
    ``rdflib.plugins.sparql.parser.parseQuery``, then post-processes the
    result to replace the internal encoding variables with
    ``CompValue('TripleTerm', subject=…, predicate=…, object=…)`` nodes that
    preserve the original SPARQL 1.2 structure.

    Returns a pyparsing ``ParseResults`` tree — same type as the rdflib function.
    """
    from rdflib.plugins.sparql.parser import parseQuery as _parseQuery
    tt_vars: frozenset = frozenset()
    if isinstance(q, str):
        q, tt_vars = _rewrite_sparql12_to_11_tracked(q)
    result = _parseQuery(q)
    return _restore_sparql12_in_tree(result, tt_vars)


def prepareQuery(queryString: str, initNs=None, base=None):
    """Parse and translate a SPARQL 1.2 query string to an rdflib ``Query`` object.

    Rewrites SPARQL 1.2 triple-term syntax to SPARQL 1.1, then delegates to
    ``rdflib.plugins.sparql.processor.prepareQuery``.  The compiled algebra is
    SPARQL 1.1; the rewriting is transparent at execution time.

    The returned ``Query`` object can be passed directly to
    ``StarlightGraph.query()`` or ``rdflib.Graph.query()``.
    """
    from rdflib.plugins.sparql import prepareQuery as _prepareQuery
    queryString = rewrite_sparql12_to_11(queryString)
    return _prepareQuery(queryString, initNs=initNs, base=base)


def parseUpdate(q):
    """Parse a SPARQL 1.2 Update request string.

    Rewrites SPARQL 1.2 triple-term syntax to SPARQL 1.1, calls
    ``rdflib.plugins.sparql.parser.parseUpdate``, then post-processes the
    result to restore ``TripleTerm`` nodes (same strategy as ``parseQuery``).

    Returns an rdflib ``CompValue`` object — same type as the rdflib function.
    """
    from rdflib.plugins.sparql.parser import parseUpdate as _parseUpdate
    tt_vars: frozenset = frozenset()
    if isinstance(q, str):
        q, tt_vars = _rewrite_sparql12_to_11_tracked(q)
    result = _parseUpdate(q)
    return _restore_sparql12_in_tree(result, tt_vars)


def prepareUpdate(updateString: str, initNs=None, base=None):
    """Parse and translate a SPARQL 1.2 Update request string to an rdflib ``Update`` object.

    Rewrites SPARQL 1.2 triple-term syntax to SPARQL 1.1, then delegates to
    ``rdflib.plugins.sparql.prepareUpdate``.  The compiled form is SPARQL 1.1.

    The returned ``Update`` object can be passed directly to
    ``StarlightGraph.update()`` or ``rdflib.Graph.update()``.
    """
    from rdflib.plugins.sparql import prepareUpdate as _prepareUpdate
    updateString = rewrite_sparql12_to_11(updateString)
    return _prepareUpdate(updateString, initNs=initNs, base=base)


def processUpdate(graph, updateString: str, initBindings=None, initNs=None, base=None):
    """Execute a SPARQL 1.2 Update against a graph.

    This is the SPARQL 1.2-aware replacement for
    ``rdflib.plugins.sparql.processUpdate``.  The rdflib original calls
    ``parseUpdate()`` directly, bypassing any ``graph.update()`` override.
    This wrapper rewrites SPARQL 1.2 syntax first, then delegates to
    ``graph.update()`` for ``StarlightGraph``/``StarlightDataset`` instances
    (so their registry rebuild and native-backend routing still happen) or
    falls back to rdflib's ``processUpdate`` for plain graphs.
    """
    if isinstance(updateString, str):
        updateString = rewrite_sparql12_to_11(updateString)
    # Prefer graph.update() for Starlight graphs so StarlightGraph post-processing
    # (registry rebuild, _invalidate_callback, native backend routing) fires.
    # Check via attribute rather than isinstance to avoid a circular import.
    if hasattr(graph, '_tt_registry') or hasattr(graph, '_sg_cache'):
        graph.update(updateString, initBindings=initBindings, initNs=initNs)
        return
    from rdflib.plugins.sparql import processUpdate as _processUpdate
    _processUpdate(graph, updateString, initBindings=initBindings, initNs=initNs, base=base)
