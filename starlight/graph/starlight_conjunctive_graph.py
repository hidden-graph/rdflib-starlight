"""
starlight.graph.starlight_conjunctive_graph

StarlightConjunctiveGraph — multi-graph container where every named-graph
context is a StarlightGraph with full RDF 1.2 triple-term support.

Typical usage::

    from starlight.graph import StarlightConjunctiveGraph

    cg = StarlightConjunctiveGraph()
    cg.parse("knowledge_base.trig", format="trig12")

    g1 = cg.get_context(URIRef("http://example.org/graph1"))
    # g1 is a StarlightGraph — all TripleTerm API available
    for tt in g1.triple_terms():
        print(tt)

    for s, p, o, g in cg.quads():
        print(s, p, o, "in", g.identifier)

    cg.serialize("out.trig", format="trig12")

Note: ``ConjunctiveGraph`` is deprecated in rdflib 7; this class inherits
from it for maximum compatibility but the same approach can be applied to
``rdflib.Dataset`` via an identical override pattern.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from rdflib import ConjunctiveGraph, Graph, URIRef, BNode
from rdflib.namespace import RDF

from starlight.graph.starlight_graph import StarlightGraph, _raw_triples
from starlight.model.encoding import TT_NS

# Encoding predicates — used to filter internal triples from quad results
_ENCODING_PREDS = frozenset({RDF.subject, RDF.predicate, RDF.object})

# Unbound Graph.add to bypass StarlightGraph.add when loading tt:-encoded triples
_raw_graph_add = Graph.add


class StarlightConjunctiveGraph(ConjunctiveGraph):
    """A ConjunctiveGraph where every named-graph context is a StarlightGraph.

    All RDF 1.2 triple-term handling (encoding, filtering, restoration) is
    delegated to the per-context StarlightGraph instances.  The shared store
    holds the tt: URIRef encoding triples; each StarlightGraph's registry maps
    those back to TripleTerm objects.

    Public API additions vs ConjunctiveGraph:
        parse(format='trig12')      — load TriG 1.2 with triple-term support
        serialize(format='trig12')  — emit TriG 1.2 with triple-term support
        get_context(identifier)     — returns StarlightGraph (not plain Graph)
        contexts()                  — yields StarlightGraph instances
        quads()                     — yields (s, p, o, StarlightGraph) with
                                      TripleTerms restored; encoding triples filtered
    """

    def __init__(self, *args, **kwargs):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', DeprecationWarning)
            super().__init__(*args, **kwargs)
        self._sg_cache: dict[str, StarlightGraph] = {}

    # ------------------------------------------------------------------
    # Context access
    # ------------------------------------------------------------------

    def get_context(
        self,
        identifier,
        quoted: bool = False,
        base=None,
    ) -> StarlightGraph:
        """Return the StarlightGraph for the named graph with the given identifier.

        If the graph was populated via parse(), its TripleTerm registry is
        already current.  If the context was added through other means (e.g.,
        direct store manipulation), the registry is rebuilt on first access.
        """
        key = str(identifier)
        if key not in self._sg_cache:
            sg = StarlightGraph(
                store=self.store,
                identifier=identifier,
                namespace_manager=self.namespace_manager,
            )
            sg._build_registry_from_store()
            self._sg_cache[key] = sg
        return self._sg_cache[key]

    def contexts(self, triple=None):
        """Yield a StarlightGraph for every named graph in this dataset."""
        for ctx in super().contexts(triple=triple):
            yield self.get_context(ctx.identifier)

    # ------------------------------------------------------------------
    # Quad iteration with TripleTerm restoration
    # ------------------------------------------------------------------

    def _is_encoding_triple(self, s, p, o) -> bool:
        return (
            isinstance(s, URIRef)
            and str(s).startswith(TT_NS)
            and p in _ENCODING_PREDS
        )

    def quads(self, triple=(None, None, None)):
        """Yield (s, p, o, StarlightGraph) with encoding triples filtered out
        and tt:HASH URIRefs restored to TripleTerm objects."""
        for s_r, p_r, o_r, g in super().quads(triple):
            if self._is_encoding_triple(s_r, p_r, o_r):
                continue
            sg = self.get_context(g.identifier)
            yield sg._restore(s_r), p_r, sg._restore(o_r), sg

    def triples(self, triple=(None, None, None)):
        """Yield (s, p, o) from the union of all named graphs.

        Encoding triples are filtered; TripleTerms are restored.
        The same triple may appear more than once if it exists in multiple graphs.
        """
        for s, p, o, _g in self.quads(triple):
            yield s, p, o

    # ------------------------------------------------------------------
    # Parse / Serialize
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Internal parse helpers
    # ------------------------------------------------------------------

    def _read_source(self, source, publicID, location, file, data) -> str:
        """Resolve any of the rdflib source arguments to a text string."""
        if data is not None:
            return data
        if file is not None:
            return file.read() if hasattr(file, 'read') else Path(file).read_text()
        if location is not None:
            return Path(location).read_text()
        if source is not None:
            p = Path(source) if isinstance(source, (str, Path)) else None
            if p and p.exists():
                return p.read_text()
            if isinstance(source, str):
                return source
            raise ValueError(f'Cannot read source: {source!r}')
        raise ValueError('No source data provided')

    def _load_context(self, identifier, triples, namespaces=()) -> StarlightGraph:
        """Create (or update) a StarlightGraph context and populate its registry.

        *triples* may be either tt:-encoded (s,p,o) tuples (use _raw_graph_add)
        or tuples containing TripleTerm objects (use sg.add for coercion).
        The caller controls which path via the *encoded* flag on the calling site.
        """
        sg = StarlightGraph(
            store=self.store,
            identifier=identifier,
            namespace_manager=self.namespace_manager,
        )
        for prefix, ns in namespaces:
            sg.bind(prefix, ns)
            self.bind(prefix, ns)
        return sg

    # ------------------------------------------------------------------
    # Parse / Serialize
    # ------------------------------------------------------------------

    def parse(
        self,
        source=None,
        publicID=None,
        format=None,
        location=None,
        file=None,
        data=None,
        **kwargs,
    ) -> 'StarlightConjunctiveGraph':
        """Parse RDF data into named-graph contexts.

        format='trig12' — TriG 1.2; each GRAPH block becomes a StarlightGraph.
        format='nq12'   — N-Quads 1.2; each distinct graph name becomes a StarlightGraph.
        All other formats delegate to rdflib (no triple-term support).
        """
        if format not in ('trig12', 'nq12'):
            return super().parse(
                source=source, publicID=publicID, format=format,
                location=location, file=file, data=data, **kwargs,
            )

        text = self._read_source(source, publicID, location, file, data)

        if format == 'trig12':
            from starlight.parsers.trig12 import parse_trig12_named
            for graph_id, triples, namespaces in parse_trig12_named(text):
                identifier = self.default_context.identifier if graph_id is None else graph_id
                sg = self._load_context(identifier, [], namespaces)
                for triple in triples:
                    _raw_graph_add(sg, triple)   # already tt:-encoded
                sg._build_registry_from_store()
                self._sg_cache[str(identifier)] = sg

        elif format == 'nq12':
            from starlight.parsers.ntriples12 import parse_nquads12
            from collections import defaultdict
            by_graph: dict = defaultdict(list)
            for s, p, o, graph_id in parse_nquads12(text):
                key = graph_id if graph_id is not None else self.default_context.identifier
                by_graph[key].append((s, p, o))
            for identifier, triples in by_graph.items():
                sg = self._load_context(identifier, [])
                for triple in triples:
                    sg.add(triple)              # TripleTerm objects — coerce via sg.add
                self._sg_cache[str(identifier)] = sg

        return self

    def serialize(self, destination=None, format='trig', **kwargs) -> str | None:
        """Serialize this dataset.

        format='trig12' — TriG 1.2 with GRAPH blocks and <<( )>> triple terms.
        format='nq12'   — N-Quads 1.2 with <<( )>> triple terms; one quad per line.
        All other formats delegate to rdflib.
        """
        if format not in ('trig12', 'nq12'):
            return super().serialize(destination=destination, format=format, **kwargs)

        from starlight.serializers.turtle12 import serialize_turtle12

        # Collect all prefix declarations across contexts
        if format == 'nq12':
            from starlight.serializers.ntriples12 import serialize_nquads12
            lines: list[str] = []
            for sg in self.contexts():
                if len(sg) == 0:
                    continue
                chunk = serialize_nquads12(sg)
                if chunk.strip():
                    lines.append(chunk.rstrip('\n'))
            text = '\n'.join(lines) + ('\n' if lines else '')

        else:  # trig12
            from starlight.serializers.turtle12 import serialize_turtle12

            # Collect prefix declarations and graph bodies in two passes so
            # that auto-generated prefixes (e.g. ns1:) from any context are
            # included in the shared header rather than being silently dropped.
            all_prefix_lines: set[str] = set()
            graph_entries: list[tuple] = []   # (identifier, body_text)

            for sg in self.contexts():
                if len(sg) == 0:
                    continue
                turtle_text = serialize_turtle12(sg)
                body_lines = []
                for ln in turtle_text.splitlines():
                    if ln.startswith('@prefix'):
                        all_prefix_lines.add(ln)
                    else:
                        body_lines.append(ln)
                body = '\n'.join(body_lines).strip()
                if body:
                    graph_entries.append((sg.identifier, body))

            blocks: list[str] = []
            if all_prefix_lines:
                blocks.append('\n'.join(sorted(all_prefix_lines)))

            indent = '    '
            for identifier, body in graph_entries:
                if isinstance(identifier, BNode):
                    blocks.append(body)
                else:
                    indented = '\n'.join(
                        indent + ln if ln.strip() else ln
                        for ln in body.splitlines()
                    )
                    blocks.append(f'GRAPH <{identifier}> {{\n{indented}\n}}')

            text = '\n\n'.join(blocks) + '\n'

        if destination is not None:
            with open(destination, 'w', encoding='utf-8') as f:
                f.write(text)
            return destination
        return text
