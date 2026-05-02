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
from starlight.model.triple import TripleTerm, Statement
from starlight.model.encoding import TT_NS, tt_hash

SL_NS           = 'http://starlight.org/ns#'
SL_TRIPLE_TERM  = URIRef(SL_NS + 'TripleTerm')   # kept for export / backward compat
SL_REIFICATION  = URIRef(SL_NS + 'Reification')  # kept for export / backward compat
RDF_REIFIES     = URIRef('http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies')

# Predicates used in the internal TripleTerm URIRef encoding
_ENCODING_PREDS = frozenset({RDF.subject, RDF.predicate, RDF.object})

# Unbound reference to Graph.triples — used to bypass our override safely
_raw_triples = Graph.triples


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
        """Translate a tuple/TripleTerm to its internal URIRef. None-safe."""
        if node is None:
            return None
        if isinstance(node, TripleTerm):
            return self._intern_tt(node)
        if isinstance(node, tuple) and len(node) == 3:
            if all(x is not None for x in node):
                return self._intern_tt(TripleTerm(*node))
            # tuple with None components = wildcard pattern; treat as None
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
        """Remove a triple. Tuples in subject/object positions are coerced to TripleTerms."""
        s, p, obj = triple
        super().remove((self._coerce_tt(s), p, self._coerce_tt(obj)))

    def triples(self, triple):
        """Iterate triples matching the pattern. Filters internal encoding triples.

        TripleTerms in results are returned as TripleTerm objects, not raw URIRefs.
        Tuples in the pattern are coerced to TripleTerm lookups.
        """
        s, p, obj = triple
        for s_r, p_r, o_r in super().triples((self._coerce_tt(s), p, self._coerce_tt(obj))):
            if not self._is_encoding_triple(s_r, p_r, o_r):
                yield (self._restore(s_r), p_r, self._restore(o_r))

    def __contains__(self, triple):
        """Test triple membership. Tuples are coerced to TripleTerms."""
        s, p, obj = triple
        return super().__contains__((self._coerce_tt(s), p, self._coerce_tt(obj)))

    def __len__(self):
        """Count of visible (non-encoding) triples."""
        return sum(1 for _ in self.triples((None, None, None)))

    # ------------------------------------------------------------------
    # RDF 1.2-specific additions
    # ------------------------------------------------------------------

    def add_statement(self, statement: Statement):
        """Add a reification: reifier rdf:reifies triple_term."""
        tt_uri = self._intern_tt(statement.triple_term)
        super().add((statement.reifier, RDF_REIFIES, tt_uri))

    def statements(self, triple_term=None, reifier=None):
        """Yield Statement objects matching the given filter.

        triple_term -- only statements reifying this triple term
        reifier     -- only statements with this reifier
        Neither     -- all statements in the graph
        """
        if triple_term is not None:
            tt_uri = self._coerce_tt(triple_term)
            if tt_uri is None:
                return
            tt = self._tt_nodes.get(tt_uri)
            if tt is None:
                return
            for r, _, _ in super().triples((None, RDF_REIFIES, tt_uri)):
                yield Statement(r, tt)
        elif reifier is not None:
            for _, _, o in super().triples((reifier, RDF_REIFIES, None)):
                if isinstance(o, URIRef) and str(o).startswith(TT_NS):
                    tt = self._tt_nodes.get(o)
                    if tt is not None:
                        yield Statement(reifier, tt)
        else:
            seen = set()
            for r, _, o in super().triples((None, RDF_REIFIES, None)):
                if isinstance(o, URIRef) and str(o).startswith(TT_NS) and r not in seen:
                    tt = self._tt_nodes.get(o)
                    if tt is not None:
                        seen.add(r)
                        yield Statement(r, tt)

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
