def parse_json_value(val):
    # Try to parse as int, float, or bool, else return as string
    if isinstance(val, str):
        v = val.strip()
        # Boolean
        if v == 'true':
            return True
        if v == 'false':
            return False
        # Integer
        try:
            if v.startswith('0') and len(v) > 1 and v[1].isdigit():
                # Leading zero, treat as string (e.g., 0123)
                return v
            return int(v)
        except Exception:
            pass
        # Float (including scientific notation)
        try:
            if any(c in v for c in '.eE'):
                return float(v)
        except Exception:
            pass
    return val
import sys
import json

def split_statements(data: str):
    stmts = []
    buf = ''
    depth = {'[': 0, '(': 0, '{': 0, '<': 0}
    in_string = False
    string_char = ''
    i = 0
    while i < len(data):
        c = data[i]
        if in_string:
            buf += c
            if c == string_char:
                # Handle triple-quoted strings
                if data[i:i+3] == string_char*3:
                    buf += data[i+1:i+3]
                    i += 2
                    in_string = False
                elif data[i-1] != '\\':
                    in_string = False
            i += 1
            continue
        if c in ('"', "'"):
            # Start of string
            if data[i:i+3] == c*3:
                in_string = True
                string_char = c
                buf += c*3
                i += 3
                continue
            else:
                in_string = True
                string_char = c
        elif c in '[({<':
            depth[c] += 1
        elif c in '])}>':
            if c == ']':
                depth['['] = max(0, depth['['] - 1)
            elif c == ')':
                depth['('] = max(0, depth['('] - 1)
            elif c == '}':
                depth['{'] = max(0, depth['{'] - 1)
            elif c == '>':
                depth['<'] = max(0, depth['<'] - 1)
        # Remove newlines unless inside a string
        if c in ('\n', '\r') and not in_string:
            i += 1
            continue
        # Improved: treat period followed by line break as statement end if not in structure
        if c == '.' and all(v == 0 for v in depth.values()):
            # Look ahead for line break
            if i + 1 < len(data) and data[i+1] in ('\n', '\r'):
                buf += c
                stmts.append(buf.strip())
                buf = ''
                i += 1
                # Skip possible \r\n
                if i + 1 < len(data) and data[i] == '\r' and data[i+1] == '\n':
                    i += 1
                continue
        buf += c
        i += 1
    if buf.strip():
        stmts.append(buf.strip())
    return stmts

def main():
    with open('samples/complex.ttl', 'r', encoding='utf-8') as f:
        data = f.read()
    # Remove comments and blank lines
    lines = [line for line in data.splitlines() if line.strip() and not line.strip().startswith('#')]
    data_no_comments = '\n'.join(lines)
    stmts = split_statements(data_no_comments)

    import re

    def classify_statement(stmt):
        s = stmt.strip()
        if s.lower().startswith('@prefix') or s.lower().startswith('prefix'):
            return 'prefix'
        elif s.lower().startswith('@base') or s.lower().startswith('base'):
            return 'base'
        elif s.lower().startswith('@directive') or s.lower().startswith('directive'):
            return 'directive'
        else:
            return 'triple'

    def extract_fields(stmt, typ):
        s = stmt.strip()
        if typ == 'prefix':
            # Match: @prefix prefix: <IRI> .
            m = re.match(r'@?prefix\s+([\w-]+):\s*<([^>]+)>', s, re.IGNORECASE)
            if m:
                return {'prefix': m.group(1), 'iri': m.group(2)}
        elif typ == 'base' or typ == 'directive':
            # Match: @base <IRI> . or @directive <IRI> .
            m = re.match(r'@?(base|directive)\s*<([^>]+)>', s, re.IGNORECASE)
            if m:
                return {'iri': m.group(2)}
        elif typ == 'triple':
            # Try to extract subject, predicate, object (handles ; and ,)
            triple_pat = r'^(\S+)\s+(.+?)\s*\.$'
            m = re.match(triple_pat, s, re.DOTALL)
            if m:
                subj = m.group(1)
                rest = m.group(2)
                # Split on ; for predicate groups
                triple_set = []
                pred_obj_groups = []
                buf = ''
                depth = 0
                for ch in rest:
                    if ch in '[({':
                        depth += 1
                    elif ch in '])}':
                        depth -= 1
                    if ch == ';' and depth == 0:
                        pred_obj_groups.append(buf.strip())
                        buf = ''
                    else:
                        buf += ch
                if buf.strip():
                    pred_obj_groups.append(buf.strip())
                # Track the first predicate/object pair as they appear in the original statement
                first_pred = None
                first_obj = None
                for group in pred_obj_groups:
                    # Split on , for multiple objects for same predicate
                    # Find predicate (first token)
                    parts = group.split(None, 1)
                    if len(parts) < 2:
                        continue
                    pred = parts[0]
                    objs = []
                    obj_buf = ''
                    depth2 = 0
                    in_str = False
                    str_char = ''
                    for i, c in enumerate(parts[1]):
                        if in_str:
                            obj_buf += c
                            if c == str_char:
                                in_str = False
                            continue
                        if c in ('"', "'"):
                            in_str = True
                            str_char = c
                        elif c in '[({':
                            depth2 += 1
                        elif c in '])}':
                            depth2 -= 1
                        if c == ',' and depth2 == 0 and not in_str:
                            objs.append(obj_buf.strip())
                            obj_buf = ''
                        else:
                            obj_buf += c
                    if obj_buf.strip():
                        objs.append(obj_buf.strip())
                    for idx, obj in enumerate(objs):
                        triple_set.append({'subject': subj, 'predicate': pred, 'object': parse_json_value(obj)})
                        if first_pred is None and first_obj is None:
                            first_pred = pred
                            first_obj = parse_json_value(obj)
                # For backward compatibility, extract first triple as it appears in the original statement
                result = {'raw_triple': {
                    'subject': subj,
                    'predicate': first_pred,
                    'object': first_obj
                }}
                result['triple_set'] = triple_set
                return result
        return {}

    # Output to complex.txt
    with open('complex.txt', 'w', encoding='utf-8') as out:
        for stmt in stmts:
            out.write(stmt + '\n---\n')

    # Output to complex.json with type and extracted fields

    # --- Recursive triple_set expansion ---
    def expand_triple_set(triple_set, blank_counter):
        import copy
        changed = False
        new_triples = []
        def parse_json_value(val):
            # Try to parse as int, float, or bool, else return as string
            if isinstance(val, str):
                v = val.strip()
                # Boolean
                if v == 'true':
                    return True
                if v == 'false':
                    return False
                # Integer
                try:
                    if v.startswith('0') and len(v) > 1 and v[1].isdigit():
                        # Leading zero, treat as string (e.g., 0123)
                        return v
                    return int(v)
                except Exception:
                    pass
                # Float (including scientific notation)
                try:
                    if any(c in v for c in '.eE'):
                        return float(v)
                except Exception:
                    pass
            return val

        for triple in triple_set:
            subj, pred, obj = triple['subject'], triple['predicate'], triple['object']
            obj_strip = obj.strip() if isinstance(obj, str) else obj
            # Expand blank node: [ ... ]
            if isinstance(obj_strip, str) and obj_strip.startswith('[') and obj_strip.endswith(']'):
                bnode = f'_:sl_{blank_counter[0]}'
                blank_counter[0] += 1
                new_triples.append({'subject': subj, 'predicate': pred, 'object': bnode})
                changed = True
                inner = obj_strip[1:-1].strip()
                fake_stmt = f'{bnode} {inner} .'
                inner_fields = extract_fields(fake_stmt, 'triple')
                if inner_fields and 'triple_set' in inner_fields:
                    expanded_inner = expand_triple_set(inner_fields['triple_set'], blank_counter)
                    for t in expanded_inner:
                        new_triples.append(t)
            # Expand Turtle list: ( ... )
            elif isinstance(obj_strip, str) and obj_strip.startswith('(') and obj_strip.endswith(')'):
                # Parse list elements, handling nested lists and blank nodes
                elements = []
                buf = ''
                depth = 0
                in_str = False
                str_char = ''
                inside = obj_strip[1:-1].strip()
                for i, c in enumerate(inside):
                    if in_str:
                        buf += c
                        if c == str_char:
                            in_str = False
                        continue
                    if c in ('"', "'"):
                        in_str = True
                        str_char = c
                        buf += c
                        continue
                    if c in '[(':
                        depth += 1
                    elif c in '])':
                        depth -= 1
                    if c.isspace() and depth == 0 and buf.strip():
                        elements.append(buf.strip())
                        buf = ''
                    else:
                        buf += c
                if buf.strip():
                    elements.append(buf.strip())
                # Now expand each element recursively
                # Assign a blank node for the list head
                list_head = f'_:sl_{blank_counter[0]}'
                blank_counter[0] += 1
                new_triples.append({'subject': subj, 'predicate': pred, 'object': list_head})
                changed = True
                current = list_head
                for idx, el in enumerate(elements):
                    # If element is a blank node or list, expand it recursively
                    el_strip = el.strip()
                    if el_strip.startswith('[') and el_strip.endswith(']'):
                        bnode = f'_:sl_{blank_counter[0]}'
                        blank_counter[0] += 1
                        # Add rdf:first triple
                        new_triples.append({'subject': current, 'predicate': 'rdf:first', 'object': bnode})
                        # Expand the blank node
                        inner = el_strip[1:-1].strip()
                        fake_stmt = f'{bnode} {inner} .'
                        inner_fields = extract_fields(fake_stmt, 'triple')
                        if inner_fields and 'triple_set' in inner_fields:
                            expanded_inner = expand_triple_set(inner_fields['triple_set'], blank_counter)
                            for t in expanded_inner:
                                new_triples.append(t)
                    elif el_strip.startswith('(') and el_strip.endswith(')'):
                        # Nested list: expand recursively
                        nested_head = f'_:sl_{blank_counter[0]}'
                        blank_counter[0] += 1
                        new_triples.append({'subject': current, 'predicate': 'rdf:first', 'object': nested_head})
                        # Recursively expand the nested list
                        fake_triple = {'subject': current, 'predicate': 'rdf:first', 'object': el_strip}
                        nested_triples = expand_triple_set([{'subject': current, 'predicate': 'rdf:first', 'object': el_strip}], blank_counter)
                        for t in nested_triples:
                            if t['subject'] != current or t['predicate'] != 'rdf:first':
                                new_triples.append(t)
                    else:
                        # Normal element
                        new_triples.append({'subject': current, 'predicate': 'rdf:first', 'object': el_strip})
                    # Prepare for rdf:rest
                    if idx < len(elements) - 1:
                        next_bnode = f'_:sl_{blank_counter[0]}'
                        blank_counter[0] += 1
                        new_triples.append({'subject': current, 'predicate': 'rdf:rest', 'object': next_bnode})
                        current = next_bnode
                    else:
                        new_triples.append({'subject': current, 'predicate': 'rdf:rest', 'object': 'rdf:nil'})
            else:
                # For all other objects, parse as native JSON value if possible
                new_triple = dict(triple)
                new_triple['object'] = parse_json_value(triple['object'])
                new_triples.append(new_triple)
        # If changed, recurse
        if changed:
            return expand_triple_set(new_triples, blank_counter)
        else:
            return new_triples

    json_obj = []
    blank_counter = [0]  # Shared across all statements for unique blank node IDs
    for stmt in stmts:
        typ = classify_statement(stmt)
        fields = extract_fields(stmt, typ)
        entry = {'statement': stmt, 'type': typ}
        if typ == 'triple' and 'triple_set' in fields:
            # Save the original raw_triple before expansion
            original_raw_triple = fields.get('raw_triple')
            expanded = expand_triple_set(fields['triple_set'], blank_counter)
            fields['triple_set'] = expanded
            # Restore the original raw_triple (do not mutate)
            if original_raw_triple:
                fields['raw_triple'] = original_raw_triple
        entry.update(fields)
        json_obj.append(entry)

    with open('complex.json', 'w', encoding='utf-8') as jout:
        json.dump(json_obj, jout, indent=2)

if __name__ == '__main__':
    main()
