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

    def _coerce_choices(self, node):
        """Coerce a subject/object slot in triples_choices.

        Returns (coerced, skip):
          skip=True  → the caller should yield nothing (TripleTerm not in registry)
          skip=False → coerced is the value or list to pass to the store
        """
        if node is None:
            return None, False
        if _is_tt_like(node):
            c = self._coerce_tt_read(node)
            return (None, True) if c is _TT_NOT_FOUND else (c, False)
        if isinstance(node, list):
            out = []
            for item in node:
                if _is_tt_like(item):
                    c = self._coerce_tt_read(item)
                    if c is not _TT_NOT_FOUND:
                        out.append(c)
                else:
                    out.append(item)
            return out, False
        return node, False

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
                tt._namespace_manager = self.namespace_manager
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

    def addN(self, quads):
        """Add multiple quads. Coerces TripleTerms in subject/object positions."""
        super().addN([(self._coerce_tt(s), p, self._coerce_tt(o), ctx) for s, p, o, ctx in quads])

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

    def triples_choices(self, triple, context=None):
        """Iterate triples matching a choices pattern. Filters encoding triples; restores TripleTerms.

        Each position may be None (wildcard), a single node, or a list of nodes.
        TripleTerms not registered in this graph are silently dropped from lists;
        an unregistered single TripleTerm causes the method to yield nothing.
        """
        s, p, o = triple
        s_n, skip_s = self._coerce_choices(s)
        o_n, skip_o = self._coerce_choices(o)
        if skip_s or skip_o:
            return
        for s_r, p_r, o_r in super().triples_choices((s_n, p, o_n), context=context):
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

    def query(self, query_object, processor='sparql', result='sparql',
              initNs=None, initBindings=None, use_store_provided=True, **kwargs):
        """Execute a SPARQL query. Triple-term patterns are rewritten to SPARQL 1.1.

        The rewritten query runs against a plain Graph view of the same store so
        that encoding triples (rdf:subject/predicate/object on tt: URIRefs) are
        visible to the SPARQL engine. Results are post-processed to restore tt:HASH
        URIRefs back to TripleTerm objects.
        """
        from starlight.query.sparql12_to_11 import rewrite_sparql12_to_11
        if isinstance(query_object, str):
            query_object = rewrite_sparql12_to_11(query_object)
        raw = Graph(store=self.store, identifier=self.identifier)
        for prefix, ns in self.namespaces():
            raw.bind(prefix, ns)
        r = raw.query(query_object, processor=processor, result=result,
                      initNs=initNs, initBindings=initBindings,
                      use_store_provided=use_store_provided, **kwargs)
        if r.type == 'SELECT':
            r.bindings = [
                {var: self._restore(row.get(var)) if row.get(var) is not None else None
                 for var in r.vars}
                for row in r.bindings
            ]
        elif r.type == 'CONSTRUCT':
            r.graph = StarlightGraph.from_rdflib(r.graph)
        return r

    def update(self, update_object, processor='sparql',
              initNs=None, initBindings=None, use_store_provided=True, **kwargs):
        """Execute a SPARQL UPDATE. Triple-term patterns are rewritten to SPARQL 1.1.

        Supported:
        - ``<<( )>>`` in WHERE clauses (DELETE/INSERT WHERE forms)
        - Ground ``<<( )>>`` in INSERT DATA / DELETE DATA blocks
        - ``<<( )>>`` in INSERT/DELETE templates (subject position): evaluated
          via a post-processing SELECT pass against the same WHERE clause
        """
        from starlight.query.sparql12_to_11 import rewrite_sparql12_to_11
        if isinstance(update_object, str):
            update_object = self._preprocess_data_updates(update_object)
            tt_templates, where_str = self._extract_tt_template_info(update_object)
            update_object = rewrite_sparql12_to_11(update_object)
        else:
            tt_templates, where_str = [], None
        raw = Graph(store=self.store, identifier=self.identifier)
        for prefix, ns in self.namespaces():
            raw.bind(prefix, ns)
        raw.update(update_object, processor=processor,
                   initNs=initNs, initBindings=initBindings,
                   use_store_provided=use_store_provided, **kwargs)
        self._build_registry_from_store()
        if tt_templates and where_str:
            self._execute_tt_template_triples(tt_templates, where_str)
        return None

    def _preprocess_data_updates(self, update_str: str) -> str:
        """Handle INSERT/DELETE DATA blocks containing ground triple terms.

        Each such block is parsed as Turtle 1.2; triples are added or removed
        via the Python API, and the block is replaced with an empty no-op so the
        remainder of the query can be passed to the SPARQL rewriter safely.
        """
        import re
        if '<<(' not in update_str:
            return update_str

        from starlight.query.sparql12_to_11 import _consume_balanced
        from starlight.parsers.turtle_parser import StarlightTurtleParser, _skolemize_encoding

        turtle_prefixes = self._sparql_prefixes_to_turtle(update_str)
        _DATA_RE = re.compile(r'\b(INSERT|DELETE)\s+DATA\s*\{', re.IGNORECASE)

        result = []
        i = 0
        while i < len(update_str):
            m = _DATA_RE.search(update_str, i)
            if m is None:
                result.append(update_str[i:])
                break
            result.append(update_str[i:m.start()])
            op = m.group(1).upper()
            brace_start = m.end() - 1  # position of '{'
            block, j = _consume_balanced(update_str, brace_start, '{', '}')
            data_content = block[1:-1]

            if '<<(' in data_content:
                turtle_text = f'{turtle_prefixes}\n{data_content}'
                raw_g = StarlightTurtleParser().parse(turtle_text)
                processed = _skolemize_encoding(raw_g)
                if op == 'INSERT':
                    for triple in processed:
                        super().add(triple)
                    self._build_registry_from_store()
                else:
                    for s, p, o in processed:
                        if not self._is_encoding_triple(s, p, o):
                            super().remove((s, p, o))
                result.append(f'{m.group(1)} DATA {{}}')
            else:
                result.append(update_str[m.start():j])
            i = j

        return ''.join(result)

    def _sparql_prefixes_to_turtle(self, query_str: str) -> str:
        """Convert PREFIX declarations in a SPARQL string to Turtle @prefix lines.
        Graph's own namespace bindings are included as fallback."""
        import re
        prefixes: dict[str, str] = {}
        for m in re.finditer(r'\bPREFIX\s+(\w*:)\s*(<[^>]+>)', query_str, re.IGNORECASE):
            prefixes[m.group(1)] = m.group(2)
        for prefix, ns in self.namespaces():
            key = f'{prefix}:' if prefix else ':'
            if key not in prefixes:
                prefixes[key] = f'<{ns}>'
        return '\n'.join(f'@prefix {k} {v} .' for k, v in prefixes.items())

    def _extract_tt_template_info(self, update_str: str):
        """Scan INSERT/DELETE template blocks for <<( )>>-subject triples.

        Returns (tt_templates, where_str).
        tt_templates: list of (is_insert, tt_s, tt_p, tt_o, pred_tok, obj_tok)
          where each token is a variable string (``?name``) or a ground term string.
        where_str: the full ``WHERE { ... }`` block, or None.

        Handles <<( )>> in both subject and object positions of template triples.

        Each record in tt_templates is ``(is_insert, subj, pred_tok, obj)`` where
        ``subj`` and ``obj`` are either a plain token string or a 3-tuple
        ``(s_tok, p_tok, o_tok)`` when the position holds a triple term.
        """
        import re
        from starlight.query.sparql12_to_11 import (
            _consume_balanced, _consume_triple_term, _split_top_level_terms, _T,
        )
        if '<<(' not in update_str:
            return [], None

        _TMPL_RE = re.compile(r'\b(INSERT|DELETE)\s*\{', re.IGNORECASE)
        _WHERE_RE = re.compile(r'\bWHERE\s*\{', re.IGNORECASE)
        _TERM_RE  = re.compile(_T)

        def _read_node(text, pos):
            """Read one term or <<( )>> from text at pos. Returns (node, new_pos)
            where node is a string token or a (s,p,o) tuple for a triple term."""
            if text.startswith('<<(', pos):
                tt_tok, pos = _consume_triple_term(text, pos)
                parts = _split_top_level_terms(tt_tok[3:-3].strip())
                return (tuple(parts) if len(parts) == 3 else tt_tok), pos
            m = _TERM_RE.match(text, pos)
            if m:
                return m.group(0), m.end()
            return None, pos

        tt_templates = []
        i = 0
        while i < len(update_str):
            m = _TMPL_RE.search(update_str, i)
            if m is None:
                break
            is_insert = m.group(1).upper() == 'INSERT'
            brace_start = m.end() - 1
            block, j = _consume_balanced(update_str, brace_start, '{', '}')
            content = block[1:-1]

            if '<<(' in content:
                k = 0
                while k < len(content):
                    while k < len(content) and content[k].isspace():
                        k += 1
                    if k >= len(content):
                        break

                    subj, k = _read_node(content, k)
                    if subj is None:
                        k += 1
                        continue

                    while k < len(content) and content[k].isspace():
                        k += 1

                    # collect pred-obj pairs, same subject (;-separated)
                    while k < len(content) and content[k] not in '.}':
                        while k < len(content) and content[k].isspace():
                            k += 1
                        if k >= len(content) or content[k] in '.}':
                            break

                        pm = _TERM_RE.match(content, k)
                        if not pm:
                            break
                        pred_tok = pm.group(0)
                        k = pm.end()

                        while k < len(content) and content[k].isspace():
                            k += 1

                        obj, k = _read_node(content, k)
                        if obj is None:
                            break

                        if isinstance(subj, tuple) or isinstance(obj, tuple):
                            tt_templates.append((is_insert, subj, pred_tok, obj))

                        while k < len(content) and content[k].isspace():
                            k += 1
                        if k < len(content) and content[k] == ';':
                            k += 1
                            continue
                        if k < len(content) and content[k] == '.':
                            k += 1
                        break
            i = j

        if not tt_templates:
            return [], None

        m_w = _WHERE_RE.search(update_str)
        if m_w is None:
            return [], None
        w_block, _ = _consume_balanced(update_str, m_w.end() - 1, '{', '}')
        return tt_templates, 'WHERE ' + w_block

    def _execute_tt_template_triples(self, tt_templates: list, where_str: str) -> None:
        """Run WHERE as SELECT; for each binding evaluate TT templates and add/remove."""
        from starlight.query.sparql12_to_11 import rewrite_sparql12_to_11

        def _vars(val):
            if isinstance(val, tuple):
                return {t for t in val if isinstance(t, str) and t.startswith('?')}
            return {val} if isinstance(val, str) and val.startswith('?') else set()

        all_vars: set = set()
        for _, subj, pred_tok, obj in tt_templates:
            all_vars |= _vars(subj) | _vars(obj)
            if pred_tok.startswith('?'):
                all_vars.add(pred_tok)

        var_list = ' '.join(sorted(all_vars)) if all_vars else '*'
        prefix_lines = '\n'.join(
            f'PREFIX {p}: <{ns}>' for p, ns in self.namespaces() if p
        )
        select_q = rewrite_sparql12_to_11(
            f'{prefix_lines}\nSELECT DISTINCT {var_list} {where_str}'
        )

        raw = Graph(store=self.store, identifier=self.identifier)
        for p, ns in self.namespaces():
            raw.bind(p, ns)
        r = raw.query(select_q)

        def _eval_node(val, row):
            if isinstance(val, tuple):
                tt_s, tt_p, tt_o = val
                sv = self._eval_template_tok(tt_s, row)
                pv = self._eval_template_tok(tt_p, row)
                ov = self._eval_template_tok(tt_o, row)
                return None if None in (sv, pv, ov) else TripleTerm(sv, pv, ov)
            return self._eval_template_tok(val, row)

        for row in r.bindings:
            for is_insert, subj, pred_tok, obj in tt_templates:
                s    = _eval_node(subj, row)
                pred = self._eval_template_tok(pred_tok, row)
                o    = _eval_node(obj, row)
                if None in (s, pred, o):
                    continue
                if is_insert:
                    self.add((s, pred, o))
                else:
                    self.remove((s, pred, o))

    def _eval_template_tok(self, tok: str, row: dict):
        """Evaluate a SPARQL token (variable or ground term) against a binding row."""
        from rdflib import URIRef, Literal
        from rdflib.term import Variable
        tok = tok.strip()
        if tok.startswith('?'):
            return row.get(Variable(tok[1:]))
        if tok.startswith('<') and tok.endswith('>'):
            return URIRef(tok[1:-1])
        if tok == 'a':
            return RDF.type
        if ':' in tok:
            colon = tok.index(':')
            prefix, local = tok[:colon], tok[colon + 1:]
            for p, ns in self.namespaces():
                if str(p) == prefix:
                    return URIRef(str(ns) + local)
        if (tok.startswith('"') and tok.endswith('"')) or \
           (tok.startswith("'") and tok.endswith("'")):
            return Literal(tok[1:-1])
        return None

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
