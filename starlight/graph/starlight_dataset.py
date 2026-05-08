"""
starlight.graph.starlight_dataset

StarlightDataset — an RDF 1.2 dataset where every named-graph context is a
StarlightGraph with full triple-term support.

Terminology: "RDF dataset" is the term used by RDF 1.2, SPARQL, TriG, and
N-Quads.  rdflib models this as ``Dataset`` (default graph is an explicit,
independent graph, not a union of named graphs).

Typical usage::

    from starlight.graph import StarlightDataset

    ds = StarlightDataset()
    ds.parse("knowledge_base.trig", format="trig12")

    g1 = ds.get_context(URIRef("http://example.org/graph1"))
    # g1 is a StarlightGraph — all TripleTerm API available
    for tt in g1.triple_terms():
        print(tt)

    for s, p, o, g in ds.quads():
        print(s, p, o, "in", g.identifier)

    ds.serialize("out.trig", format="trig12")
"""

from __future__ import annotations

import weakref
from pathlib import Path
from rdflib import Dataset, Graph, URIRef, BNode
from rdflib.graph import DATASET_DEFAULT_GRAPH_ID
from rdflib.namespace import RDF

from starlight.graph.starlight_graph import StarlightGraph, VALID_BACKENDS, _raw_triples
from starlight.model.encoding import TT_NS

_ENCODING_PREDS = frozenset({RDF.subject, RDF.predicate, RDF.object})

_raw_graph_add = Graph.add


class StarlightDataset(Dataset):
    """An RDF dataset where every named-graph context is a StarlightGraph.

    All RDF 1.2 triple-term handling (encoding, filtering, restoration) is
    delegated to per-context StarlightGraph instances.  The shared store holds
    the tt: URIRef encoding triples; each StarlightGraph's registry maps those
    back to TripleTerm objects.

    The default graph is an explicit, independent graph (``default_union=False``
    per the RDF dataset spec and rdflib 7 default).  Pass
    ``default_union=True`` to make the default graph a union of all named graphs.

    Public API additions vs Dataset:
        parse(format='trig12')      — load TriG 1.2 with triple-term support
        parse(format='nq12')        — load N-Quads 1.2 with triple-term support
        serialize(format='trig12')  — emit TriG 1.2 with triple-term support
        serialize(format='nq12')    — emit N-Quads 1.2 with triple-term support
        get_context(identifier)     — returns StarlightGraph (not plain Graph)
        contexts()                  — yields StarlightGraph instances
        quads()                     — yields (s, p, o, StarlightGraph) with
                                      TripleTerms restored; encoding triples filtered
    """

    def __init__(self, *args, backend: str = 'rdf-1.1', **kwargs):
        if backend not in VALID_BACKENDS:
            raise ValueError(f"backend must be one of {sorted(VALID_BACKENDS)}, got {backend!r}")
        super().__init__(*args, **kwargs)
        self._backend = backend
        self._sg_cache: dict[str, StarlightGraph] = {}
        self._raw_execution_graph: Dataset | None = None

    # ------------------------------------------------------------------
    # Persistent store lifecycle
    # ------------------------------------------------------------------

    def open(self, configuration, create: bool = False):
        """Open a persistent store and rebuild all per-context TripleTerm registries.

        The store backend is not a Starlight dependency — install and configure
        it separately, then pass store='StoreName' to the constructor.

        Example::

            ds = StarlightDataset(store='Sleepycat')
            ds.open('/path/to/db', create=True)
        """
        result = super().open(configuration, create)
        self._sg_cache.clear()
        self._raw_execution_graph = None
        for ctx in super(Dataset, self).contexts():
            self.get_context(ctx.identifier)
        return result

    def close(self, commit_pending_transaction: bool = False):
        """Close the underlying store, optionally committing pending writes."""
        self.store.close(commit_pending_transaction=commit_pending_transaction)

    # ------------------------------------------------------------------
    # Context access
    # ------------------------------------------------------------------

    def _register_sg(self, sg: StarlightGraph) -> StarlightGraph:
        """Cache a StarlightGraph context and wire its invalidation callback.

        The callback uses a weakref so the dataset is not kept alive by its
        own contexts.
        """
        ds_ref = weakref.ref(self)

        def _invalidate():
            ds = ds_ref()
            if ds is not None:
                ds._raw_execution_graph = None

        sg._invalidate_callback = _invalidate
        self._sg_cache[str(sg.identifier)] = sg
        return sg

    def get_context(self, identifier, quoted: bool = False, base=None) -> StarlightGraph:
        """Return the StarlightGraph for the named graph with the given identifier.

        If the graph was populated via parse(), its TripleTerm registry is
        already current.  If the context was added through other means, the
        registry is rebuilt on first access.
        """
        key = str(identifier)
        if key not in self._sg_cache:
            sg = StarlightGraph(
                store=self.store,
                identifier=identifier,
                namespace_manager=self.namespace_manager,
                backend=self._backend,
            )
            sg._build_registry_from_store()
            self._register_sg(sg)
        return self._sg_cache[key]

    def contexts(self, triple=None):
        """Yield a StarlightGraph for every named graph in this dataset."""
        for ctx in super(Dataset, self).contexts(triple):
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
        # Bypass Dataset.quads() (which yields bare URIRef graph identifiers)
        # and call the grandparent implementation directly so the 4th element
        # is a Graph object with .identifier.
        for s_r, p_r, o_r, g in super(Dataset, self).quads(triple):
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

    def _load_context(self, identifier, namespaces=()) -> StarlightGraph:
        """Create (or update) a StarlightGraph context and register its namespaces."""
        sg = StarlightGraph(
            store=self.store,
            identifier=identifier,
            namespace_manager=self.namespace_manager,
            backend=self._backend,
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
    ) -> 'StarlightDataset':
        """Parse RDF data into named-graph contexts.

        format='trig12'  — TriG 1.2; each GRAPH block becomes a StarlightGraph.
        format='nq12'   — N-Quads 1.2; each distinct graph name becomes a StarlightGraph.
        format='trix12' — TriX 1.2 XML; each <graph> block becomes a StarlightGraph.
        All other formats delegate to rdflib (no triple-term support).
        """
        if format not in ('trig12', 'nq12', 'trix12'):
            return super().parse(
                source=source, publicID=publicID, format=format,
                location=location, file=file, data=data, **kwargs,
            )

        text = self._read_source(source, publicID, location, file, data)

        if format == 'trig12':
            from starlight.parsers.trig12 import parse_trig12_named
            for graph_id, triples, namespaces in parse_trig12_named(text):
                identifier = DATASET_DEFAULT_GRAPH_ID if graph_id is None else graph_id
                sg = self._load_context(identifier, namespaces)
                for triple in triples:
                    _raw_graph_add(sg, triple)
                sg._build_registry_from_store()
                self._register_sg(sg)

        elif format == 'nq12':
            from starlight.parsers.ntriples12 import parse_nquads12
            from collections import defaultdict
            by_graph: dict = defaultdict(list)
            for s, p, o, graph_id in parse_nquads12(text):
                key = graph_id if graph_id is not None else DATASET_DEFAULT_GRAPH_ID
                by_graph[key].append((s, p, o))
            for identifier, triples in by_graph.items():
                sg = self._load_context(identifier)
                for triple in triples:
                    sg.add(triple)
                self._register_sg(sg)

        elif format == 'trix12':
            from starlight.parsers.trix12 import parse_trix12_named
            for graph_id, triples in parse_trix12_named(text):
                identifier = DATASET_DEFAULT_GRAPH_ID if graph_id is None else graph_id
                sg = self._load_context(identifier)
                for triple in triples:
                    sg.add(triple)
                self._register_sg(sg)

        self._raw_execution_graph = None
        return self

    # ------------------------------------------------------------------
    # Query / Update with SPARQL-star support
    # ------------------------------------------------------------------

    def _restore_any(self, node):
        """Restore a tt:HASH URIRef to a TripleTerm by searching all cached graph registries."""
        if not (isinstance(node, URIRef) and str(node).startswith(TT_NS)):
            return node
        for sg in self._sg_cache.values():
            tt = sg._tt_nodes.get(node)
            if tt is not None:
                return tt
        return node

    def _build_raw_execution_graph(self) -> Dataset:
        """Build (and cache) a plain Dataset containing all raw triples including encoding triples.

        rdflib's Memory store stores the actual StarlightGraph Python objects as
        context keys.  When the SPARQL engine evaluates GRAPH ?g it calls
        contexts() and then triples() on each returned object — which would
        invoke StarlightGraph.triples() and filter encoding triples, breaking
        the rewritten SPARQL 1.1 triple-term patterns.  A separate Dataset with
        plain Graph contexts sidesteps this.

        The result is cached and reused until the next parse() or update() call.
        """
        if self._raw_execution_graph is not None:
            return self._raw_execution_graph
        raw = Dataset()
        for prefix, ns in self.namespaces():
            raw.bind(prefix, ns)
        for sg in self._sg_cache.values():
            raw_ctx = raw.get_context(sg.identifier)
            for t in _raw_triples(sg, (None, None, None)):
                raw_ctx.add(t)
        self._raw_execution_graph = raw
        return raw

    def query(self, query_object, processor='sparql', result='sparql',
              initNs=None, initBindings=None, use_store_provided=True, **kwargs):
        """Execute a SPARQL query across all named graphs with SPARQL-star support.

        Triple-term patterns (``<<( )>>``, ``{| |}``, ``~``, SUBJECT/PREDICATE/
        OBJECT functions, isTripleTerm) are rewritten to SPARQL 1.1 before
        execution.  SELECT result rows are post-processed to restore tt:HASH
        URIRefs back to TripleTerm objects.
        """
        from starlight.query.sparql12_to_11 import rewrite_sparql12_to_11
        if isinstance(query_object, str):
            query_object = rewrite_sparql12_to_11(query_object)
        raw = self._build_raw_execution_graph()
        r = raw.query(query_object, processor=processor, result=result,
                      initNs=initNs, initBindings=initBindings,
                      use_store_provided=use_store_provided, **kwargs)
        if r.type == 'SELECT':
            r.bindings = [
                {var: self._restore_any(row.get(var)) if row.get(var) is not None else None
                 for var in r.vars}
                for row in r.bindings
            ]
        elif r.type == 'CONSTRUCT':
            r.graph = StarlightGraph.from_rdflib(r.graph)
        return r

    def update(self, update_object, processor='sparql',
               initNs=None, initBindings=None, use_store_provided=True, **kwargs):
        """Execute a SPARQL UPDATE across named graphs with SPARQL-star support.

        Triple-term patterns in WHERE clauses are rewritten to SPARQL 1.1.
        All cached per-graph registries are rebuilt after execution so that
        newly added triple terms are immediately visible.

        Limitation: ground ``<<( )>>`` inside ``INSERT DATA { GRAPH <uri> { } }``
        blocks is not supported — use ``ds.get_context(uri).add(triple)`` instead.
        """
        from starlight.query.sparql12_to_11 import rewrite_sparql12_to_11
        if isinstance(update_object, str):
            update_object = rewrite_sparql12_to_11(update_object)
        raw = Dataset(store=self.store)
        for prefix, ns in self.namespaces():
            raw.bind(prefix, ns)
        raw.update(update_object, processor=processor,
                   initNs=initNs, initBindings=initBindings,
                   use_store_provided=use_store_provided, **kwargs)
        for sg in self._sg_cache.values():
            sg._build_registry_from_store()
        self._raw_execution_graph = None
        return None

    def serialize(self, destination=None, format='trig', **kwargs) -> str | None:
        """Serialize this dataset.

        format='trig12'  — TriG 1.2 with GRAPH blocks and <<( )>> triple terms.
        format='nq12'   — N-Quads 1.2 with <<( )>> triple terms; one quad per line.
        format='trix12' — TriX 1.2 XML with <graph> blocks and <tripleTerm> elements.
        All other formats delegate to rdflib.
        """
        if format not in ('trig12', 'nq12', 'trix12'):
            return super().serialize(destination=destination, format=format, **kwargs)

        if format == 'nq12':
            from starlight.serializers.ntriples12 import serialize_nquads12
            has_tt = any(getattr(sg, '_tt_nodes', None) for sg in self.contexts())
            header = 'VERSION "1.2"\n' if has_tt else ''
            lines: list[str] = []
            for sg in self.contexts():
                if len(sg) == 0:
                    continue
                chunk = serialize_nquads12(sg, _include_header=False)
                if chunk.strip():
                    lines.append(chunk.rstrip('\n'))
            text = header + '\n'.join(lines) + ('\n' if lines else '')

        elif format == 'trix12':
            from starlight.serializers.trix12 import serialize_trix12_dataset
            text = serialize_trix12_dataset(self)

        else:  # trig12
            from starlight.serializers.turtle12 import serialize_turtle12

            all_prefix_lines: set[str] = set()
            has_version = False
            graph_entries: list[tuple] = []

            for sg in self.contexts():
                if len(sg) == 0:
                    continue
                turtle_text = serialize_turtle12(sg)
                body_lines = []
                for ln in turtle_text.splitlines():
                    if ln.startswith('@prefix'):
                        all_prefix_lines.add(ln)
                    elif ln.startswith('@version'):
                        has_version = True
                    else:
                        body_lines.append(ln)
                body = '\n'.join(body_lines).strip()
                if body:
                    graph_entries.append((sg.identifier, body))

            blocks: list[str] = []
            if has_version:
                blocks.append('@version "1.2" .')
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
