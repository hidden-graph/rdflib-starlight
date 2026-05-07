"""
starlight.parsers.turtle_parser

Parses Turtle 1.2 text into an rdflib.Graph, expanding RDF 1.2 quoted-triple
syntax (<<( )>>, << >>, {| |}, ~ reifier) into the starlight internal encoding:

  Triple terms  → content-addressed URIRefs under tt: namespace
  Anon reifiers → plain BNodes (anonymous by nature)
  Named reifiers → unchanged (already named URIs)

Entry point: StarlightTurtleParser().parse(data)
"""

import re
from urllib.parse import urljoin
from rdflib import Graph, URIRef, BNode, Literal
from rdflib.namespace import RDF, XSD
from starlight.parsers import lexer as _lexer
from starlight.parsers import syntax as _syntax
from starlight.model.encoding import TT_NS, RR_NS, tt_hash

# Legacy sl: constants — kept for the intermediate build phase only;
# stripped from the final graph by _skolemize_encoding().
SL_NS          = 'http://starlight.org/ns#'
SL_TRIPLE_TERM = URIRef(SL_NS + 'TripleTerm')
SL_REIFICATION = URIRef(SL_NS + 'Reification')
RDF_REIFIES    = URIRef('http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies')


# ---------------------------------------------------------------------------
# Pure helpers — no per-parse state
# ---------------------------------------------------------------------------

def _is_qt_term(val):
    """True if val is <<( s p o )>> triple-term syntax."""
    if not isinstance(val, str):
        return False
    s = val.strip()
    if s.startswith('<<(') and s.endswith(')>>'):
        return True
    if s.startswith('<<') and s.endswith('>>'):
        inner = s[2:-2].strip()
        return inner.startswith('(') and inner.endswith(')')
    return False


def _is_qt_reif(val):
    """True if val is << s p o >> reification-shorthand syntax (no parens)."""
    if not isinstance(val, str):
        return False
    s = val.strip()
    if not (s.startswith('<<') and s.endswith('>>')):
        return False
    if s.startswith('<<('):
        return False
    inner = s[2:-2].strip()
    return not (inner.startswith('(') and inner.endswith(')'))


def _is_qt(val):
    return _is_qt_term(val) or _is_qt_reif(val)


def _has_reifier(val):
    """True if val is << s p o ~ r >> (inline reifier)."""
    if not isinstance(val, str):
        return False
    s = val.strip()
    if not (s.startswith('<<') and s.endswith('>>')):
        return False
    if s.startswith('<<('):
        return False
    inner = s[2:-2].strip()
    if inner.startswith('(') and inner.endswith(')'):
        return False
    if '~' not in inner:
        return False
    _, r1 = _lexer.next_token(inner)
    _, r2 = _lexer.next_token(r1)
    _, r3 = _lexer.next_token(r2)
    return r3.strip().startswith('~')


def _get_reifier_parts(val):
    """Extract (triple_term_str, reifier_str_or_None) from << s p o ~ r >>."""
    inner = val.strip()[2:-2].strip()
    ts, r1 = _lexer.next_token(inner)
    tp, r2 = _lexer.next_token(r1)
    to, r3 = _lexer.next_token(r2)
    after_tilde = r3.strip()[1:].strip()
    return f'<<( {ts} {tp} {to} )>>', (after_tilde if after_tilde else None)


def _norm_qt(val):
    """Normalise any quoted-triple form to <<( s p o )>> for use as a cache key."""
    s = val.strip()
    inner = s[2:-2].strip()
    if inner.startswith('(') and inner.endswith(')'):
        inner = inner[1:-1].strip()
    ts, r1 = _lexer.next_token(inner)
    tp, r2 = _lexer.next_token(r1)
    to, r3 = _lexer.next_token(r2)
    while r3.startswith('^^') or (r3.startswith('@') and len(r3) > 1 and r3[1].isalpha()):
        suffix, r3 = _lexer.next_token(r3)
        to += suffix
        r3 = r3.strip()
    return f'<<( {ts} {tp} {to} )>>'


def _unescape(s):
    """Expand Turtle string escape sequences including \\uXXXX and \\UXXXXXXXX."""
    result = []
    i = 0
    while i < len(s):
        if s[i] == '\\' and i + 1 < len(s):
            c = s[i + 1]
            if   c == 'n':  result.append('\n'); i += 2
            elif c == 't':  result.append('\t'); i += 2
            elif c == 'r':  result.append('\r'); i += 2
            elif c == '"':  result.append('"');  i += 2
            elif c == "'":  result.append("'");  i += 2
            elif c == '\\': result.append('\\'); i += 2
            elif c == 'u' and i + 5 <= len(s):
                result.append(chr(int(s[i+2:i+6], 16))); i += 6
            elif c == 'U' and i + 9 <= len(s):
                result.append(chr(int(s[i+2:i+10], 16))); i += 10
            else:
                result.append('\\'); result.append(c); i += 2
        else:
            result.append(s[i]); i += 1
    return ''.join(result)


def _split_literal(val):
    """Split a Turtle literal token into (content_str, suffix_str, kind).

    kind is '^^' for typed literals, '@' for language-tagged, '' for plain.
    Correctly skips ^^ and @ sequences that appear inside the quoted string.
    """
    q = val[:3] if val[:3] in ('"""', "'''") else val[0]
    i = len(q)
    while i < len(val):
        if val[i] == '\\':
            i += 2
            continue
        if val[i:i+len(q)] == q:
            content = val[len(q):i]
            rest = val[i+len(q):]
            if rest.startswith('^^'):
                return content, rest[2:].strip(), '^^'
            if rest.startswith('@'):
                return content, rest[1:], '@'
            return content, '', ''
        i += 1
    return val[len(q):], '', ''


def _to_node(val, prefix_map, base_uri):
    """Convert a string token or coerced Python value to an rdflib term."""
    if isinstance(val, bool):
        return Literal(val, datatype=XSD.boolean)
    if isinstance(val, int):
        return Literal(val, datatype=XSD.integer)
    if isinstance(val, float):
        return Literal(val, datatype=XSD.decimal)
    if not isinstance(val, str):
        return Literal(str(val))

    val = val.strip()

    if val.startswith('_:'):
        return BNode(val[2:])

    if val.startswith('<') and val.endswith('>'):
        inner = val[1:-1]
        if base_uri and not re.match(r'^[a-zA-Z][a-zA-Z0-9+\-.]*:', inner):
            return URIRef(urljoin(base_uri, inner))
        return URIRef(inner)

    if val.startswith(('"""', "'''", '"', "'")):
        content, suffix, kind = _split_literal(val)
        text = _unescape(content)
        if kind == '^^':
            return Literal(text, datatype=_to_node(suffix, prefix_map, base_uri))
        if kind == '@':
            return Literal(text, lang=suffix)
        return Literal(text)

    if val == 'a':
        return RDF.type

    if ':' in val:
        pref, local = val.split(':', 1)
        if pref in prefix_map:
            return URIRef(prefix_map[pref] + local)
        if val.startswith('http'):
            return URIRef(val)
        return URIRef(val)

    if base_uri:
        return URIRef(urljoin(base_uri, val))

    return Literal(val)


# ---------------------------------------------------------------------------
# Per-parse stateful expander
# ---------------------------------------------------------------------------

class _Expander:
    """Holds mutable state for quoted-triple expansion within a single parse() call."""

    def __init__(self, blank_counter):
        self.blank_counter = blank_counter
        self.qt_cache = {}

    def _alloc(self):
        n = f'_:si_{self.blank_counter[0]}'
        self.blank_counter[0] += 1
        return n

    def qt_to_json(self, qt_str):
        """Return (term_bnode_str, [extra_triples]) for a <<( s p o )>> term.
        Identical triple terms reuse the same bnode via qt_cache."""
        val = _norm_qt(qt_str.strip())
        if val in self.qt_cache:
            return self.qt_cache[val], []

        inner = val[3:-3].strip()
        subj_str, rest  = _lexer.next_token(inner)
        pred_str, rest2 = _lexer.next_token(rest)
        obj_str,  rest3 = _lexer.next_token(rest2)
        while rest3.startswith('^^') or (rest3.startswith('@') and len(rest3) > 1 and rest3[1].isalpha()):
            suffix, rest3 = _lexer.next_token(rest3)
            obj_str += suffix
            rest3 = rest3.strip()

        if pred_str == 'a':
            pred_str = 'rdf:type'

        extras = []
        if _is_qt(subj_str):
            subj_str, e = self.qt_to_json(_norm_qt(subj_str))
            extras.extend(e)
        if _is_qt(obj_str):
            obj_str, e = self.qt_to_json(_norm_qt(obj_str))
            extras.extend(e)
        else:
            obj_str = _syntax.coerce_object(obj_str) if obj_str else ''

        bnode = self._alloc()
        self.qt_cache[val] = bnode
        extras.extend([
            {'subject': bnode, 'predicate': 'rdf:subject',   'object': subj_str or ''},
            {'subject': bnode, 'predicate': 'rdf:predicate', 'object': pred_str or ''},
            {'subject': bnode, 'predicate': 'rdf:object',    'object': obj_str  or ''},
            {'subject': bnode, 'predicate': 'rdf:type',      'object': 'sl:TripleTerm'},
        ])
        return bnode, extras

    def qt_reif_to_json(self, qt_str):
        """<< s p o >> → a new Reification bnode that rdf:reifies the TripleTerm."""
        term_bnode, term_extras = self.qt_to_json(_norm_qt(qt_str))
        reif_bnode = self._alloc()
        return reif_bnode, term_extras + [
            {'subject': reif_bnode, 'predicate': 'rdf:reifies', 'object': term_bnode},
        ]

    def expand_qt_in_triple(self, s, p, o):
        """Expand quoted-triple syntax in subject and object positions.
        Returns (s, p, o, extra_triples)."""
        extras = []

        if _is_qt_term(s):
            s, e = self.qt_to_json(s)
            extras.extend(e)
        elif _has_reifier(s):
            tt_str, reif = _get_reifier_parts(s)
            tb, e = self.qt_to_json(tt_str)
            extras.extend(e)
            s = reif if reif else self._alloc()
            extras.append({'subject': s, 'predicate': 'rdf:reifies', 'object': tb})
        elif _is_qt_reif(s):
            s, e = self.qt_reif_to_json(s)
            extras.extend(e)

        if p == 'rdf:reifies' and _is_qt(o):
            bnode, e = self.qt_to_json(_norm_qt(o))
            extras.extend(e)
            o = bnode
        else:
            if _is_qt_term(o):
                o, e = self.qt_to_json(_norm_qt(o))
                extras.extend(e)
            elif _has_reifier(o):
                tt_str, reif = _get_reifier_parts(o)
                tb, e = self.qt_to_json(tt_str)
                extras.extend(e)
                o = reif if reif else self._alloc()
                extras.append({'subject': o, 'predicate': 'rdf:reifies', 'object': tb})
            elif _is_qt_reif(o):
                tb, e = self.qt_to_json(_norm_qt(o))
                extras.extend(e)
                rb = self._alloc()
                extras.append({'subject': rb, 'predicate': 'rdf:reifies', 'object': tb})
                o = rb

        return s, p, o, extras

    def expand_annotation(self, subj_str, pred_str, obj_str, annotations):
        """Return extra triples for {| ... |} annotation specs on (subj, pred, obj)."""
        extras = []
        term_bnode, term_extras = self.qt_to_json(f'<<( {subj_str} {pred_str} {obj_str} )>>')
        extras.extend(term_extras)
        for reifier, ann_body in annotations:
            reif_bnode = reifier if reifier else self._alloc()
            extras.append({'subject': reif_bnode, 'predicate': 'rdf:reifies', 'object': term_bnode})
            if ann_body:
                ann_fields = _syntax.extract_fields(
                    f'{reif_bnode} {ann_body} .', 'triple', self.blank_counter
                )
                if ann_fields and 'triple_set' in ann_fields:
                    for t in _syntax.expand_triple_set(ann_fields['triple_set'], self.blank_counter):
                        es, ep, eo, ee = self.expand_qt_in_triple(
                            t['subject'], t['predicate'], t['object']
                        )
                        ao_str = eo if isinstance(eo, str) else t.get('object_str', str(t['object']))
                        if t.get('annotations'):
                            extras.extend(self.expand_annotation(es, ep, ao_str, t['annotations']))
                        extras.append({'subject': es, 'predicate': ep, 'object': eo})
                        extras.extend(ee)
        return extras


# ---------------------------------------------------------------------------
# Public parser class
# ---------------------------------------------------------------------------

def _skolemize_encoding(g: Graph) -> Graph:
    """Replace intermediate bnodes with stable URIRefs and strip sl: type triples.

    The parser builds a graph with anonymous bnodes and sl:TripleTerm /
    sl:Reification type markers as a convenient intermediate.  This function
    post-processes that graph into the final encoding:

      * Each TT bnode → URIRef(TT_NS + content_hash)   (deduplicated by content)
      * Each anon reifier bnode → URIRef(RR_NS + N)     (sequential, distinct)
      * sl:TripleTerm and sl:Reification type triples → removed
      * sl: namespace binding → removed; tt: and rr: added
    """
    # --- find TT bnodes (tagged sl:TripleTerm in intermediate graph) ---
    tt_bnodes = frozenset(
        s for s, p, o in g.triples((None, RDF.type, SL_TRIPLE_TERM))
        if isinstance(s, BNode)
    )

    # --- topological sort: inner TTs before outer TTs ---
    sorted_tt: list = []
    visited: set = set()

    def _visit(bn):
        if bn in visited:
            return
        s_n = next(g.objects(bn, RDF.subject),   None)
        o_n = next(g.objects(bn, RDF.object),    None)
        if s_n in tt_bnodes:
            _visit(s_n)
        if o_n in tt_bnodes:
            _visit(o_n)
        visited.add(bn)
        sorted_tt.append(bn)

    for bn in tt_bnodes:
        _visit(bn)

    # --- compute content-addressed URIs ---
    bn_to_uri: dict = {}
    for bn in sorted_tt:
        s_n = next(g.objects(bn, RDF.subject),   None)
        p_n = next(g.objects(bn, RDF.predicate), None)
        o_n = next(g.objects(bn, RDF.object),    None)
        s_key = str(bn_to_uri.get(s_n, s_n))
        p_key = str(p_n)
        o_key = str(bn_to_uri.get(o_n, o_n))
        bn_to_uri[bn] = URIRef(TT_NS + tt_hash(s_key, p_key, o_key))

    # --- map anonymous reifier bnodes to rr:N URIRefs ---
    reif_bnodes = sorted(
        {s for s, p, o in g.triples((None, RDF_REIFIES, None)) if isinstance(s, BNode)},
        key=str,
    )
    for i, bn in enumerate(reif_bnodes):
        bn_to_uri[bn] = URIRef(RR_NS + str(i))

    # --- rebuild graph with substitutions, dropping sl: type triples ---
    new_g = Graph()
    for prefix, ns in g.namespaces():
        if str(ns) != SL_NS:
            new_g.bind(prefix, ns)
    new_g.bind('tt', TT_NS)
    if reif_bnodes:
        new_g.bind('rr', RR_NS)

    for s, p, o in g:
        if p == RDF.type and o in (SL_TRIPLE_TERM, SL_REIFICATION):
            continue
        s2 = bn_to_uri.get(s, s) if isinstance(s, BNode) else s
        o2 = bn_to_uri.get(o, o) if isinstance(o, BNode) else o
        new_g.add((s2, p, o2))

    return new_g


class StarlightTurtleParser:

    def parse(self, data: str, debug: bool = False) -> Graph:
        """Parse Turtle 1.2 text and return an rdflib.Graph.

        The graph uses the starlight internal blank-node encoding for RDF 1.2
        triple terms and reification. Pass debug=True to print intermediate
        representations to stdout.
        """
        lines = [l for l in data.splitlines() if l.strip() and not l.strip().startswith('#')]
        data_clean = '\n'.join(lines)

        blank_counter = [0]
        canonical = {'prefixes': [], 'bases': [], 'triples': []}
        current_base = None

        for stmt in _syntax.split_statements(data_clean):
            typ = _syntax.classify_statement(stmt)
            fields = _syntax.extract_fields(stmt, typ, blank_counter)
            if typ == 'version':
                pass  # informational hint; no data to extract
            elif typ == 'prefix' and 'prefix' in fields and 'iri' in fields:
                canonical['prefixes'].append({'prefix': fields['prefix'], 'iri': fields['iri']})
            elif typ == 'base' and 'iri' in fields:
                raw = fields['iri']
                current_base = urljoin(current_base, raw) if current_base else raw
                canonical['bases'].append({'iri': current_base})
            elif typ == 'triple' and 'triple_set' in fields:
                triples = _syntax.expand_triple_set(fields['triple_set'], blank_counter)
                for t in triples:
                    t['_base_uri'] = current_base
                canonical['triples'].extend(triples
                )

        if debug:
            import json
            print('CANONICAL:', json.dumps(canonical, indent=2, default=str))

        expander = _Expander(blank_counter)
        expanded = []
        for triple in canonical['triples']:
            s, p, o = triple['subject'], triple['predicate'], triple['object']
            t_base = triple.get('_base_uri')
            s, p, o, extras = expander.expand_qt_in_triple(s, p, o)
            expanded.append({'subject': s, 'predicate': p, 'object': o, '_base_uri': t_base})
            for e in extras:
                e['_base_uri'] = t_base
            expanded.extend(extras)
            if triple.get('annotations'):
                ann_obj = o if isinstance(o, str) else triple.get('object_str', str(triple['object']))
                ann_extras = expander.expand_annotation(s, p, ann_obj, triple['annotations'])
                for e in ann_extras:
                    e['_base_uri'] = t_base
                expanded.extend(ann_extras)

        if debug:
            import json
            print('EXPANDED:', json.dumps(expanded, indent=2, default=str))

        prefix_map = {p['prefix']: p['iri'] for p in canonical['prefixes']}
        prefix_map.setdefault('rdf', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#')
        prefix_map.setdefault('sl',  SL_NS)   # needed for intermediate sl:TripleTerm triples

        # Add sl:Reification markers so _skolemize_encoding can find reifier bnodes
        reif_subjects = {t['subject'] for t in expanded if t['predicate'] == 'rdf:reifies'}
        for subj in reif_subjects:
            expanded.append({'subject': subj, 'predicate': 'rdf:type', 'object': 'sl:Reification'})

        g = Graph()
        for prefix, iri in prefix_map.items():
            g.bind(prefix, iri)
        if current_base:
            g.base = current_base

        for triple in expanded:
            t_base = triple.get('_base_uri')
            s_node = _to_node(triple['subject'], prefix_map, t_base)
            p_raw = triple['predicate']
            p_node = RDF.type if p_raw == 'a' else _to_node(p_raw, prefix_map, t_base)
            o_node = _to_node(triple['object'], prefix_map, t_base)
            g.add((s_node, p_node, o_node))

        return g
