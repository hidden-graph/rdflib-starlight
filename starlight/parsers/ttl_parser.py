# Unified Turtle parser using robust split_simple logic
import importlib.util
import json
import os
import re
import rdflib
from rdflib import Graph, URIRef, BNode, Literal
from rdflib.namespace import RDF

class StarlightTurtleParser:
    def __init__(self):
        # Dynamically import split_simple from the same directory
        split_simple_path = os.path.join(os.path.dirname(__file__), 'split_simple.py')
        spec = importlib.util.spec_from_file_location('split_simple', split_simple_path)
        self.split_simple = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.split_simple)

    def parse(self, data: str, json_debug_path=None):
        """
        Parse Turtle using robust split_simple logic.
        1. Build a canonical JSON object representing all statements (prefix, base, triples, etc).
        2. Optionally output this JSON for debugging.
        3. In a second pass, extract prefixes and base, then build the rdflib.Graph from the JSON.
        Returns an rdflib.Graph object.
        """
        # --- 1. Preprocess input: remove comments and blank lines ---
        lines = [line for line in data.splitlines() if line.strip() and not line.strip().startswith('#')]
        data_no_comments = '\n'.join(lines)

        # --- 2. Split into statements using robust logic ---
        stmts = self.split_simple.split_statements(data_no_comments)
        canonical_json = {'prefixes': [], 'bases': [], 'triples': []}

        # --- 3. Classify, extract, and expand each statement into canonical JSON ---
        blank_counter = [0]
        for stmt in stmts:
            typ = self.split_simple.classify_statement(stmt)
            fields = self.split_simple.extract_fields(stmt, typ, blank_counter)
            if typ == 'prefix' and 'prefix' in fields and 'iri' in fields:
                canonical_json['prefixes'].append({'prefix': fields['prefix'], 'iri': fields['iri']})
            elif typ == 'base' and 'iri' in fields:
                canonical_json['bases'].append({'iri': fields['iri']})
            elif typ == 'triple' and 'triple_set' in fields:
                expanded = self.split_simple.expand_triple_set(fields['triple_set'], blank_counter)
                canonical_json['triples'].extend(expanded)

        # --- 3.5. Expand quoted triples into reification triples in canonical JSON ---
        def is_qt_term(val):
            """<<( s p o )>> or << ( s p o ) >> — TripleTerm (inner content wrapped in parens)."""
            if not isinstance(val, str):
                return False
            s = val.strip()
            if s.startswith('<<(') and s.endswith(')>>'):
                return True
            if s.startswith('<<') and s.endswith('>>'):
                inner = s[2:-2].strip()
                return inner.startswith('(') and inner.endswith(')')
            return False

        def is_qt_reif(val):
            """<< s p o >> (inner NOT wrapped in parens) — Reification shorthand."""
            if not isinstance(val, str):
                return False
            s = val.strip()
            if not (s.startswith('<<') and s.endswith('>>')):
                return False
            if s.startswith('<<('):
                return False
            inner = s[2:-2].strip()
            return not (inner.startswith('(') and inner.endswith(')'))

        def is_qt(val):
            return is_qt_term(val) or is_qt_reif(val)

        def norm_qt(val):
            """Normalise any quoted triple form to <<( s p o )>> for the TripleTerm cache."""
            s = val.strip()
            inner = s[2:-2].strip()
            if inner.startswith('(') and inner.endswith(')'):
                inner = inner[1:-1].strip()

            # Canonicalise token spacing so <<:a :b :c>> and <<(:a :b :c)>>
            # produce the same cache key.
            ts, r1 = self.split_simple.next_token(inner)
            tp, r2 = self.split_simple.next_token(r1)
            to, r3 = self.split_simple.next_token(r2)
            while r3.startswith('^^') or (r3.startswith('@') and len(r3) > 1 and r3[1].isalpha()):
                suffix, r3 = self.split_simple.next_token(r3)
                to += suffix
                r3 = r3.strip()

            return f'<<( {ts} {tp} {to} )>>'

        def has_reifier(val):
            """<< s p o ~ r >> — has a reifier after ~."""
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
            _, r1 = self.split_simple.next_token(inner)
            _, r2 = self.split_simple.next_token(r1)
            _, r3 = self.split_simple.next_token(r2)
            return r3.strip().startswith('~')

        def get_reifier_parts(val):
            """Extract (triple_term_str, reifier_str or None) from << s p o ~ r >>."""
            inner = val.strip()[2:-2].strip()
            ts, r1 = self.split_simple.next_token(inner)
            tp, r2 = self.split_simple.next_token(r1)
            to, r3 = self.split_simple.next_token(r2)
            after_tilde = r3.strip()[1:].strip()  # drop leading ~
            return f'<<( {ts} {tp} {to} )>>', (after_tilde if after_tilde else None)

        qt_cache = {}  # normalised qt_str -> bnode_str; avoids duplicate TripleTerm triples

        def qt_to_json(qt_str):
            """Return (term_bnode, [triples]) for a <<( s p o )>> triple term, recursively.
            Identical triple terms reuse the same blank node."""
            val = norm_qt(qt_str.strip())  # always work in <<( )>> canonical form
            if val in qt_cache:
                return qt_cache[val], []

            inner = val[3:-3].strip()  # always <<( )>> form here
            subj_str, rest  = self.split_simple.next_token(inner)
            pred_str, rest2 = self.split_simple.next_token(rest)
            obj_str, rest3  = self.split_simple.next_token(rest2)
            # consume ^^dtype or @lang suffix on the object literal
            while rest3.startswith('^^') or (rest3.startswith('@') and len(rest3) > 1 and rest3[1].isalpha()):
                suffix, rest3 = self.split_simple.next_token(rest3)
                obj_str += suffix
                rest3 = rest3.strip()

            if pred_str == 'a':
                pred_str = 'rdf:type'

            all_extras = []
            if is_qt(subj_str):
                subj_str, extras = qt_to_json(norm_qt(subj_str))
                all_extras.extend(extras)
            if is_qt(obj_str):
                obj_str, extras = qt_to_json(norm_qt(obj_str))
                all_extras.extend(extras)
            else:
                obj_str = self.split_simple.coerce_object(obj_str) if obj_str else ''

            bnode = f'_:si_{blank_counter[0]}'
            blank_counter[0] += 1
            qt_cache[val] = bnode
            all_extras.extend([
                {'subject': bnode, 'predicate': 'rdf:subject',   'object': subj_str or ''},
                {'subject': bnode, 'predicate': 'rdf:predicate', 'object': pred_str or ''},
                {'subject': bnode, 'predicate': 'rdf:object',    'object': obj_str  or ''},
                {'subject': bnode, 'predicate': 'rdf:type',      'object': 'sl:TripleTerm'},
            ])
            return bnode, all_extras

        def qt_reif_to_json(qt_str):
            """<< s p o >> in subject position → a new Reification bnode that rdf:reifies the TripleTerm.
            The TripleTerm itself is created (or reused) via qt_to_json."""
            term_bnode, term_extras = qt_to_json(norm_qt(qt_str))
            reif_bnode = f'_:si_{blank_counter[0]}'
            blank_counter[0] += 1
            return reif_bnode, term_extras + [
                {'subject': reif_bnode, 'predicate': 'rdf:reifies', 'object': term_bnode},
            ]

        def expand_qt_in_triple(s, p, o):
            """Expand quoted triple syntax in s and o. Returns (s, p, o, extra_triples)."""
            extras = []
            if is_qt_term(s):
                s, e = qt_to_json(s); extras.extend(e)
            elif has_reifier(s):
                tt_str, reif = get_reifier_parts(s)
                tb, e = qt_to_json(tt_str); extras.extend(e)
                s = reif if reif else f'_:si_{blank_counter[0]}'
                if not reif: blank_counter[0] += 1
                extras.append({'subject': s, 'predicate': 'rdf:reifies', 'object': tb})
            elif is_qt_reif(s):
                s, e = qt_reif_to_json(s); extras.extend(e)

            # PATCH: If predicate is rdf:reifies and object is a quoted triple, expand directly
            if p == 'rdf:reifies' and (is_qt_term(o) or is_qt_reif(o)):
                bnode, e = qt_to_json(norm_qt(o))
                extras.extend(e)
                o = bnode
            else:
                if is_qt_term(o):
                    o, e = qt_to_json(norm_qt(o)); extras.extend(e)
                elif has_reifier(o):
                    tt_str, reif = get_reifier_parts(o)
                    tb, e = qt_to_json(tt_str); extras.extend(e)
                    o = reif if reif else f'_:si_{blank_counter[0]}'
                    if not reif: blank_counter[0] += 1
                    extras.append({'subject': o, 'predicate': 'rdf:reifies', 'object': tb})
                elif is_qt_reif(o):
                    tb, e = qt_to_json(norm_qt(o)); extras.extend(e)
                    rb = f'_:si_{blank_counter[0]}'; blank_counter[0] += 1
                    extras.append({'subject': rb, 'predicate': 'rdf:reifies', 'object': tb})
                    o = rb
            return s, p, o, extras

        def expand_annotation(subj_str, pred_str, obj_str, annotations):
            """Return extra triples for {| ... |} annotation specs on triple (subj_str, pred_str, obj_str)."""
            extras = []
            term_bnode, term_extras = qt_to_json(f'<<( {subj_str} {pred_str} {obj_str} )>>')
            extras.extend(term_extras)
            for reifier, ann_body in annotations:
                reif_bnode = reifier if reifier else f'_:si_{blank_counter[0]}'
                if not reifier: blank_counter[0] += 1
                extras.append({'subject': reif_bnode, 'predicate': 'rdf:reifies', 'object': term_bnode})
                if ann_body:
                    fake_stmt = f'{reif_bnode} {ann_body} .'
                    ann_fields = self.split_simple.extract_fields(fake_stmt, 'triple', blank_counter)
                    if ann_fields and 'triple_set' in ann_fields:
                        for t in self.split_simple.expand_triple_set(ann_fields['triple_set'], blank_counter):
                            as_, ap, ao, ae = expand_qt_in_triple(t['subject'], t['predicate'], t['object'])
                            ao_str = ao if isinstance(ao, str) else t.get('object_str', str(t['object']))
                            if t.get('annotations'):
                                extras.extend(expand_annotation(as_, ap, ao_str, t['annotations']))
                            extras.append({'subject': as_, 'predicate': ap, 'object': ao})
                            extras.extend(ae)
            return extras

        # DEBUG: Print canonical JSON before expansion
        import sys
        if hasattr(sys, '_getframe') and sys._getframe(1).f_globals.get('__name__') == '__main__':
            print('CANONICAL JSON:', json.dumps(canonical_json, indent=2))

        expanded_triples = []
        for triple in canonical_json['triples']:
            s, p, o = triple['subject'], triple['predicate'], triple['object']
            s, p, o, qt_extras = expand_qt_in_triple(s, p, o)
            expanded_triples.append({'subject': s, 'predicate': p, 'object': o})
            expanded_triples.extend(qt_extras)
            if triple.get('annotations'):
                ann_obj = o if isinstance(o, str) else triple.get('object_str', str(triple['object']))
                expanded_triples.extend(expand_annotation(s, p, ann_obj, triple['annotations']))

        # DEBUG: Print expanded triples after expansion
        if hasattr(sys, '_getframe') and sys._getframe(1).f_globals.get('__name__') == '__main__':
            print('EXPANDED TRIPLES:', json.dumps(expanded_triples, indent=2))

        # --- 3.6. Tag rdf:reifies subjects as sl:Reification ---
        reification_subjects = {
            t['subject'] for t in expanded_triples if t['predicate'] == 'rdf:reifies'
        }
        for subj in reification_subjects:
            expanded_triples.append({'subject': subj, 'predicate': 'rdf:type', 'object': 'sl:Reification'})

        canonical_json['triples'] = expanded_triples

        # --- 4. Optionally output canonical JSON for debugging ---
        if json_debug_path:
            with open(json_debug_path, 'w') as jout:
                json.dump(canonical_json, jout, indent=2)

        # --- 5. Extract prefix_map and base_uri from canonical JSON ---
        prefix_map = {p['prefix']: p['iri'] for p in canonical_json['prefixes']}
        prefix_map.setdefault('rdf', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#')
        prefix_map.setdefault('sl',  'http://starlight.org/ns#')
        base_uri = canonical_json['bases'][0]['iri'] if canonical_json['bases'] else None

        # --- 6. Build rdflib.Graph ---
        g = Graph()
        for prefix, iri in prefix_map.items():
            g.bind(prefix, iri)
        if base_uri:
            g.base = base_uri

        from rdflib.namespace import XSD

        def unescape_string(s):
            result = []
            i = 0
            while i < len(s):
                if s[i] == '\\' and i + 1 < len(s):
                    c = s[i + 1]
                    if c == 'n':   result.append('\n')
                    elif c == 't': result.append('\t')
                    elif c == 'r': result.append('\r')
                    elif c == '"': result.append('"')
                    elif c == "'": result.append("'")
                    elif c == '\\': result.append('\\')
                    else: result.append('\\'); result.append(c)
                    i += 2
                else:
                    result.append(s[i])
                    i += 1
            return ''.join(result)

        def resolve_iri(val):
            if isinstance(val, dict) and 'value' in val and 'type' in val:
                if val['type'] == 'int':
                    return Literal(val['value'], datatype=XSD.integer)
                elif val['type'] == 'float':
                    return Literal(val['value'], datatype=XSD.decimal)
                elif val['type'] == 'bool':
                    return Literal(val['value'], datatype=XSD.boolean)
                else:
                    return Literal(val['value'])
            if not isinstance(val, str):
                return Literal(val)
            val = val.strip()
            if val.startswith('<') and val.endswith('>'):
                inner = val[1:-1]
                if base_uri and not re.match(r'^[a-zA-Z][a-zA-Z0-9+\-.]*:', inner):
                    return URIRef(base_uri + inner)
                return URIRef(inner)
            if ':' in val and not val.startswith('http') and not val.startswith('<') and not val.startswith('_:'):
                pref, local = val.split(':', 1)
                if pref in prefix_map:
                    return URIRef(prefix_map[pref] + local)
                return URIRef(val)
            elif val.startswith('_:'):
                return BNode(val[2:])
            elif base_uri and not (val.startswith('http') or val.startswith('_:')):
                return URIRef(base_uri + val)
            elif val.startswith('http'):
                return URIRef(val)
            return Literal(val)

        # --- 7. Add all triples to the graph ---
        for triple in canonical_json['triples']:
            s, p, o = triple['subject'], triple['predicate'], triple['object']
            s_node = resolve_iri(s)
            if isinstance(p, str) and p == 'a':
                p_node = RDF.type
            else:
                p_node = resolve_iri(p)
            if isinstance(o, bool):
                o_node = Literal(o, datatype=XSD.boolean)
            elif isinstance(o, int):
                o_node = Literal(o, datatype=XSD.integer)
            elif isinstance(o, float):
                o_node = Literal(o, datatype=XSD.decimal)
            elif isinstance(o, dict) and 'value' in o and 'type' in o:
                o_node = resolve_iri(o)
            elif isinstance(o, str):
                if o.startswith('_:'):
                    o_node = BNode(o[2:])
                elif o.startswith('http') or o.startswith('<'):
                    o_node = resolve_iri(o)
                elif o.startswith('"""') and o.endswith('"""'):
                    o_node = Literal(unescape_string(o[3:-3]))
                elif o.startswith('"') and o.endswith('"'):
                    o_node = Literal(unescape_string(o[1:-1]))
                elif '^^' in o:
                    lit, dtype = o.split('^^', 1)
                    lit = lit.strip('"')
                    dtype_uri = resolve_iri(dtype)
                    o_node = Literal(unescape_string(lit), datatype=dtype_uri)
                elif '@' in o and o.startswith('"'):
                    lit, lang = o.rsplit('@', 1)
                    lit = lit.strip('"')
                    o_node = Literal(unescape_string(lit), lang=lang)
                elif ':' in o:
                    o_node = resolve_iri(o)
                else:
                    o_node = Literal(o)
            else:
                o_node = resolve_iri(o)
            g.add((s_node, p_node, o_node))
        return g
