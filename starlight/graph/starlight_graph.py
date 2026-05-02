"""
starlight.graph.starlight_graph

StarlightGraph — rdflib.Graph subclass with RDF 1.2 triple-term support.

A plain Python 3-tuple in any node position is treated as an inline TripleTerm.
All rdflib.Graph methods work identically; core traversal methods are extended
to accept and return TripleTerm objects while hiding the internal encoding.

Encoding: triple terms are stored as content-addressed URIRefs under TT_NS
(same triple content always maps to the same URI). The rdf:subject/predicate/object
triples that define the encoding are hidden from callers.
"""

from rdflib import Graph, URIRef, BNode
from rdflib.namespace import RDF
from starlight.model.triple import TripleTerm
from starlight.model.encoding import TT_NS, tt_hash

SL_NS           = 'http://starlight.org/ns#'
SL_TRIPLE_TERM  = URIRef(SL_NS + 'TripleTerm')   # kept for export / backward compat
SL_REIFICATION  = URIRef(SL_NS + 'Reification')  # kept for export / backward compat
RDF_REIFIES     = URIRef('http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies')

# Predicates used in the internal TripleTerm URIRef encoding
_ENCODING_PREDS = frozenset({RDF.subject, RDF.predicate, RDF.object})

# Unbound reference to Graph.triples — used to bypass our override safely
_raw_triples = Graph.triples

# Sentinel returned by _coerce_tt_read when a TripleTerm is not in the registry.
# Distinct from None (which means wildcard) so callers can detect "no match".
_TT_NOT_FOUND = object()


def _is_tt_like(node):
    return isinstance(node, (TripleTerm, tuple)) and (
        isinstance(node, TripleTerm) or len(node) == 3
    )


class StarlightGraph(Graph):
    """rdflib.Graph extended with RDF 1.2 triple-term support.

    Triple terms are represented as Python 3-tuples or TripleTerm objects.
    Internally they are encoded as content-addressed URIRefs under TT_NS in
    the rdflib store; that encoding is completely hidden from callers.

    All unoverridden rdflib.Graph methods (namespace management, SPARQL,
    serialization, etc.) are inherited and work without modification.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tt_registry: dict = {}   # canonical (s_key, p, o_key) -> URIRef
        self._tt_nodes: dict = {}      # URIRef -> TripleTerm

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _coerce_tt(self, node):
        """Translate a tuple/TripleTerm to its internal URIRef, creating it if new.
        Use only on write paths (add, add_reification). For reads use _coerce_tt_read."""
        if node is None:
            return None
        if isinstance(node, TripleTerm):
            return self._intern_tt(node)
        if isinstance(node, tuple) and len(node) == 3:
            if all(x is not None for x in node):
                return self._intern_tt(TripleTerm(*node))
            return None
        return node

    def _coerce_tt_read(self, node):
        """Translate a tuple/TripleTerm to its URIRef for read-only paths.
        Returns _TT_NOT_FOUND if the TripleTerm is not registered — never creates."""
        if node is None:
            return None
        if isinstance(node, TripleTerm):
            return self._tt_registry.get(node._key(), _TT_NOT_FOUND)
        if isinstance(node, tuple) and len(node) == 3:
            if all(x is not None for x in node):
                return self._tt_registry.get(TripleTerm(*node)._key(), _TT_NOT_FOUND)
            return None
        return node

    def _intern_tt(self, tt: TripleTerm) -> URIRef:
        """Return the content-addressed URIRef encoding of tt, creating it if new."""
        key = tt._key()
        if key in self._tt_registry:
            return self._tt_registry[key]
        # Coerce nested triple terms to their URIRef form first
        s_n = self._coerce_tt(tt.subject) if _is_tt_like(tt.subject) else tt.subject
        o_n = self._coerce_tt(tt.object)  if _is_tt_like(tt.object)  else tt.object
        uri = URIRef(TT_NS + tt_hash(str(s_n), str(tt.predicate), str(o_n)))
        self._tt_registry[key] = uri
        self._tt_nodes[uri] = tt
        super().add((uri, RDF.subject,   s_n))
        super().add((uri, RDF.predicate, tt.predicate))
        super().add((uri, RDF.object,    o_n))
        return uri

    def _restore(self, node):
        """Convert a TT URIRef to TripleTerm; pass all other nodes through."""
        if isinstance(node, URIRef) and str(node).startswith(TT_NS):
            tt = self._tt_nodes.get(node)
            if tt is not None:
                return tt
        return node

    def _is_encoding_triple(self, s, p, o):
        """True if (s, p, o) is internal infrastructure that must not be surfaced."""
        if isinstance(s, URIRef) and str(s).startswith(TT_NS) and p in _ENCODING_PREDS:
            return True
        return False

    def _build_registry_from_store(self):
        """Scan the underlying store for TT_NS URIRefs and populate the registry.

        Used by from_rdflib() after bulk-copying an existing parsed graph.
        Handles nested triple terms by reconstructing inner TTs first.
        """
        tt_uris = set(
            s for s, p, o in _raw_triples(self, (None, RDF.subject, None))
            if isinstance(s, URIRef) and str(s).startswith(TT_NS)
        )

        def reconstruct(uri):
            if uri in self._tt_nodes:
                return self._tt_nodes[uri]
            s_n = next((o for _, _, o in _raw_triples(self, (uri, RDF.subject,   None))), None)
            p_n = next((o for _, _, o in _raw_triples(self, (uri, RDF.predicate, None))), None)
            o_n = next((o for _, _, o in _raw_triples(self, (uri, RDF.object,    None))), None)
            s = reconstruct(s_n) if isinstance(s_n, URIRef) and str(s_n).startswith(TT_NS) else s_n
            o = reconstruct(o_n) if isinstance(o_n, URIRef) and str(o_n).startswith(TT_NS) else o_n
            tt = TripleTerm(s, p_n, o)
            self._tt_registry[tt._key()] = uri
            self._tt_nodes[uri] = tt
            return tt

        for uri in tt_uris:
            reconstruct(uri)

    # ------------------------------------------------------------------
    # Overridden rdflib.Graph methods
    # ------------------------------------------------------------------

    def add(self, s_or_triple, p=None, obj=None):
        """Add a triple. Tuples in subject/object positions are treated as TripleTerms.

        Supports both rdflib-compatible single-tuple form and extended
        positional-argument form:
            g.add((s, p, o))              # plain triple
            g.add((s, p, o), q, z)        # triple term as subject
            g.add(s, p, (a, b, c))        # triple term as object
        """
        if p is None and obj is None:
            s, p, obj = s_or_triple
        else:
            s = s_or_triple
        super().add((self._coerce_tt(s), p, self._coerce_tt(obj)))

    def remove(self, triple):
        """Remove a triple. Returns immediately if a TripleTerm in the pattern is not registered."""
        s, p, obj = triple
        s_n, o_n = self._coerce_tt_read(s), self._coerce_tt_read(obj)
        if s_n is _TT_NOT_FOUND or o_n is _TT_NOT_FOUND:
            return
        super().remove((s_n, p, o_n))

    def triples(self, triple):
        """Iterate triples matching the pattern. Filters internal encoding triples.

        TripleTerms in results are returned as TripleTerm objects, not raw URIRefs.
        Returns nothing if a TripleTerm in the pattern is not registered in this graph.
        """
        s, p, obj = triple
        s_n, o_n = self._coerce_tt_read(s), self._coerce_tt_read(obj)
        if s_n is _TT_NOT_FOUND or o_n is _TT_NOT_FOUND:
            return
        for s_r, p_r, o_r in super().triples((s_n, p, o_n)):
            if not self._is_encoding_triple(s_r, p_r, o_r):
                yield (self._restore(s_r), p_r, self._restore(o_r))

    def __contains__(self, triple):
        """Test triple membership. Returns False if a TripleTerm in the pattern is not registered."""
        s, p, obj = triple
        s_n, o_n = self._coerce_tt_read(s), self._coerce_tt_read(obj)
        if s_n is _TT_NOT_FOUND or o_n is _TT_NOT_FOUND:
            return False
        return super().__contains__((s_n, p, o_n))

    def __len__(self):
        """Count of visible (non-encoding) triples."""
        return sum(1 for _ in self.triples((None, None, None)))

    # ------------------------------------------------------------------
    # RDF 1.2-specific additions
    # ------------------------------------------------------------------

    def add_reifier(self, predicate, obj, name=None):
        """Assert a reifier triple and return the reifier node.

        If name is given it is used as the reifier URIRef; otherwise a fresh
        BNode is created. The triple (reifier, predicate, obj) is added to the
        graph and the reifier is returned for use with add_reification().

            stmt = g.add_reifier(EX.reported, EX.NYTimes, name=EX.stmt1)
            g.add_reification(stmt, (EX.a, EX.b, EX.c))

            # or inline:
            g.add_reification(g.add_reifier(EX.reported, EX.NYTimes), triple)
        """
        reifier = URIRef(name) if name is not None else BNode()
        super().add((reifier, predicate, obj))
        return reifier

    def add_reification(self, reifier, triple_term):
        """Add a reification: reifier rdf:reifies triple_term."""
        tt = triple_term if isinstance(triple_term, TripleTerm) else TripleTerm(*triple_term)
        tt_uri = self._intern_tt(tt)
        super().add((reifier, RDF_REIFIES, tt_uri))

    def reifications(self, TT=None, predicate=None, object=None):
        """Yield reifier nodes matching the given filters.

        TT        -- only reifiers that rdf:reifies this triple term
        predicate -- only reifiers that have (reifier, predicate, ?) in the graph
        object    -- only reifiers that have (reifier, ?, object) in the graph

        Filters combine: reifications(TT=t, predicate=p, object=o) returns
        reifiers that reify t AND have (reifier, p, o) in the graph.
        """
        # Step 1 — candidate reifiers from TT filter (fast path via rdf:reifies index)
        if TT is not None:
            tt_uri = self._coerce_tt_read(TT)
            if tt_uri is None or tt_uri is _TT_NOT_FOUND:
                return
            tt_reifiers = {r for r, _, _ in super().triples((None, RDF_REIFIES, tt_uri))}
        else:
            tt_reifiers = None  # no TT filter

        # Step 2 — candidate reifiers from predicate/object filter
        if predicate is not None or object is not None:
            prop_reifiers = {s for s, _, _ in super().triples((None, predicate, object))
                             if not str(s).startswith(TT_NS)}
        else:
            prop_reifiers = None  # no property filter

        # Step 3 — intersect whichever filters are active
        if tt_reifiers is not None and prop_reifiers is not None:
            candidates = tt_reifiers & prop_reifiers
        elif tt_reifiers is not None:
            candidates = tt_reifiers
        elif prop_reifiers is not None:
            # keep only nodes that are actually reifiers
            all_reifiers = {r for r, _, _ in super().triples((None, RDF_REIFIES, None))}
            candidates = prop_reifiers & all_reifiers
        else:
            candidates = {r for r, _, _ in super().triples((None, RDF_REIFIES, None))}

        yield from candidates

    def reified_triples(self, reifier):
        """Yield the TripleTerms reified by the given reifier node."""
        for _, _, o in super().triples((reifier, RDF_REIFIES, None)):
            if isinstance(o, URIRef) and str(o).startswith(TT_NS):
                tt = self._tt_nodes.get(o)
                if tt is not None:
                    yield tt

    def triple_terms(self, subject=None, predicate=None, object=None):
        """Yield all TripleTerms registered in this graph, with optional filters.

        Any combination of subject, predicate, object narrows the results:
            g.triple_terms()                        # all triple terms
            g.triple_terms(predicate=EX.knows)      # all TTs with that predicate
            g.triple_terms(EX.bob, EX.knows, None)  # any TT with that s and p
        """
        for tt in self._tt_nodes.values():
            if subject   is not None and tt.subject   != subject:   continue
            if predicate is not None and tt.predicate != predicate: continue
            if object    is not None and tt.object    != object:    continue
            yield tt

    def has_triple_term(self, subject, predicate, object):
        """Return True if a TripleTerm with these exact components exists in the graph."""
        key = TripleTerm(subject, predicate, object)._key()
        return key in self._tt_registry

    def reifiers(self, TT):
        """Yield all reifier nodes that rdf:reifies the given triple term."""
        yield from self.reifications(TT=TT)

    def remove_reification(self, reifier):
        """Remove the rdf:reifies triple(s) for the given reifier."""
        super().remove((reifier, RDF_REIFIES, None))

    def parse(self, source=None, publicID=None, format=None,
              location=None, file=None, data=None, **kwargs):
        """Parse RDF data into the graph. format='turtle12' accepts Turtle 1.2 syntax."""
        if format == 'turtle12':
            from pathlib import Path
            from starlight.parsers.turtle_parser import StarlightTurtleParser, _skolemize_encoding
            if data is not None:
                text = data
            elif file is not None:
                text = file.read() if hasattr(file, 'read') else Path(file).read_text()
            elif location is not None:
                text = Path(location).read_text()
            elif source is not None:
                p = Path(source) if isinstance(source, (str, Path)) else None
                if p and p.exists():
                    text = p.read_text()
                elif isinstance(source, str):
                    text = source
                else:
                    raise ValueError(f'Cannot read source: {source!r}')
            else:
                raise ValueError('No source data to parse')
            raw = StarlightTurtleParser().parse(text)
            processed = _skolemize_encoding(raw)
            for prefix, ns in processed.namespaces():
                self.bind(prefix, ns)
            for triple in processed:
                super().add(triple)
            self._build_registry_from_store()
            return self
        return super().parse(source=source, publicID=publicID, format=format,
                             location=location, file=file, data=data, **kwargs)

    def serialize(self, destination=None, format='turtle', **kwargs):
        """Serialize the graph. format='turtle12' produces Turtle 1.2 with <<( )>> notation."""
        if format == 'turtle12':
            from starlight.serializers.turtle12 import serialize_turtle12
            text = serialize_turtle12(self)
            if destination is not None:
                with open(destination, 'w', encoding='utf-8') as f:
                    f.write(text)
                return destination
            return text
        return super().serialize(destination=destination, format=format, **kwargs)

    @classmethod
    def from_rdflib(cls, source_graph):
        """Wrap a plain rdflib.Graph (e.g., from StarlightTurtleParser).

        Namespace bindings, triples, and the TripleTerm registry are all
        copied from the source graph.  If the source uses the intermediate
        BNode TT encoding (with sl:TripleTerm type markers), it is converted
        to content-addressed tt: URIRefs before copying.
        """
        from starlight.parsers.turtle_parser import _skolemize_encoding
        processed = _skolemize_encoding(source_graph)
        g = cls()
        for prefix, ns in processed.namespaces():
            g.bind(prefix, ns)
        for triple in processed:
            super(StarlightGraph, g).add(triple)
        g._build_registry_from_store()
        return g
