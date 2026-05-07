"""
starlight.parsers.syntax

Statement-level parsing for Turtle 1.2. Splits raw text into statements,
classifies them, extracts predicate-object fields, and expands blank-node
shorthand and RDF collections into flat triple dicts.
"""

import re
from starlight.parsers.lexer import next_token, split_obj_and_annotations


def coerce_object(s):
    """Coerce a plain token to a Python value when the type is unambiguous."""
    s = s.strip()
    if s == 'true':
        return True
    if s == 'false':
        return False
    if re.match(r'^[+-]?[0-9]+$', s):
        return int(s)
    if re.match(r'^[+-]?[0-9]*\.[0-9]+(?:[eE][+-]?[0-9]+)?$', s) or \
       re.match(r'^[+-]?[0-9]+[eE][+-]?[0-9]+$', s):
        return float(s)
    return s


def _split_on_delimiter(text, delim):
    """Split text on delim at bracket-depth 0, respecting strings."""
    parts = []
    buf = ''
    depth = 0
    in_str = False
    str_char = ''
    for ch in text:
        if in_str:
            buf += ch
            if ch == str_char:
                in_str = False
            continue
        if ch in ('"', "'"):
            in_str, str_char = True, ch
            buf += ch
            continue
        if ch in '[({':
            depth += 1
        elif ch in '])}':
            depth -= 1
        if ch == delim and depth == 0:
            if buf.strip():
                parts.append(buf.strip())
            buf = ''
        else:
            buf += ch
    if buf.strip():
        parts.append(buf.strip())
    return parts


def split_statements(data):
    """Split Turtle text into a list of statement strings."""
    stmts = []
    buf = ''
    depth = {'[': 0, '(': 0, '{': 0, '<': 0}
    in_string = False
    string_char = ''
    i = 0
    while i < len(data):
        at_line_start = (i == 0 or data[i-1] in ('\n', '\r'))
        if at_line_start:
            found_directive = False
            for kw in ('@version', '@prefix', 'prefix', '@base', 'base', 'version'):
                if data[i:i+len(kw)].lower() == kw:
                    line_end = data.find('\n', i)
                    if line_end == -1:
                        line_end = len(data)
                    stmt = data[i:line_end].strip()
                    if stmt:
                        if buf.strip():
                            stmts.append(buf.strip())
                            buf = ''
                        stmts.append(stmt)
                    i = line_end + 1
                    found_directive = True
                    break
            if found_directive:
                continue
        c = data[i]
        if in_string:
            buf += c
            if c == string_char:
                if data[i:i+3] == string_char * 3:
                    buf += data[i+1:i+3]
                    i += 2
                    in_string = False
                elif data[i-1] != '\\':
                    in_string = False
            i += 1
            continue
        if c in ('"', "'"):
            if data[i:i+3] == c * 3:
                in_string = True
                string_char = c
                buf += c * 3
                i += 3
                continue
            else:
                in_string = True
                string_char = c
        elif c in '[({<':
            depth[c] += 1
        elif c in '])}>':
            if c == ']':   depth['['] = max(0, depth['['] - 1)
            elif c == ')': depth['('] = max(0, depth['('] - 1)
            elif c == '}': depth['{'] = max(0, depth['{'] - 1)
            elif c == '>': depth['<'] = max(0, depth['<'] - 1)
        if c in ('\n', '\r') and not in_string:
            i += 1
            continue
        if c == '.' and all(v == 0 for v in depth.values()):
            if i + 1 < len(data) and data[i+1] in ('\n', '\r'):
                buf += c
                stmts.append(buf.strip())
                buf = ''
                i += 1
                if i + 1 < len(data) and data[i] == '\r' and data[i+1] == '\n':
                    i += 1
                continue
        buf += c
        i += 1
    if buf.strip():
        stmts.append(buf.strip())
    return stmts


def classify_statement(stmt):
    """Return 'version', 'prefix', 'base', or 'triple'."""
    s = stmt.strip().lower()
    if s.startswith('@version') or s.startswith('version'):
        return 'version'
    if s.startswith('@prefix') or s.startswith('prefix'):
        return 'prefix'
    if s.startswith('@base') or s.startswith('base'):
        return 'base'
    return 'triple'


def extract_fields(stmt, typ, blank_counter=None):
    """Parse a single statement string into a fields dict."""
    s = stmt.strip()
    if typ == 'prefix':
        m = re.match(r'@?prefix\s+([\w-]*)\s*:\s*<([^>]+)>', s, re.IGNORECASE)
        if m:
            return {'prefix': m.group(1), 'iri': m.group(2)}
    elif typ == 'base':
        m = re.match(r'@?base\s*<([^>]+)>', s, re.IGNORECASE)
        if m:
            return {'iri': m.group(1)}
    elif typ == 'triple':
        body = s.rstrip('.')
        subj, rest = next_token(body.strip())
        if subj == '[]' and blank_counter is not None:
            subj = f'_:sl_{blank_counter[0]}'
            blank_counter[0] += 1
        if subj and rest:
            triple_set = []
            for group in _split_on_delimiter(rest, ';'):
                pred, obj_str = next_token(group)
                if not pred or not obj_str:
                    continue
                for obj in _split_on_delimiter(obj_str, ','):
                    obj_tok, annotations = split_obj_and_annotations(obj)
                    entry = {
                        'subject': subj,
                        'predicate': pred,
                        'object': coerce_object(obj_tok),
                    }
                    if annotations:
                        entry['annotations'] = annotations
                        entry['object_str'] = obj_tok
                    triple_set.append(entry)
            return {'triple_set': triple_set}
    return {}


def expand_triple_set(triple_set, blank_counter):
    """Expand [ ] blank nodes and ( ) collections into flat triple dicts.
    Returns a new list with all shorthand forms resolved."""
    result = []
    needs_reexpand = False

    for triple in triple_set:
        subj = triple['subject']
        pred = triple['predicate']
        obj = triple['object']
        obj_s = obj.strip() if isinstance(obj, str) else obj

        if isinstance(obj_s, str) and obj_s.startswith('[') and obj_s.endswith(']'):
            bnode = f'_:sl_{blank_counter[0]}'
            blank_counter[0] += 1
            head = {'subject': subj, 'predicate': pred, 'object': bnode}
            if triple.get('annotations'):
                head['annotations'] = triple['annotations']
                head['object_str'] = bnode
            result.append(head)
            inner = obj_s[1:-1].strip()
            if inner:
                inner_fields = extract_fields(f'{bnode} {inner} .', 'triple', blank_counter)
                if inner_fields and 'triple_set' in inner_fields:
                    result.extend(expand_triple_set(inner_fields['triple_set'], blank_counter))

        elif isinstance(obj_s, str) and obj_s.startswith('(') and obj_s.endswith(')'):
            elements = _parse_collection_elements(obj_s[1:-1].strip())
            if not elements:
                head = {'subject': subj, 'predicate': pred, 'object': 'rdf:nil'}
                if triple.get('annotations'):
                    head['annotations'] = triple['annotations']
                    head['object_str'] = 'rdf:nil'
                result.append(head)
                continue
            list_head = f'_:sl_{blank_counter[0]}'
            blank_counter[0] += 1
            head = {'subject': subj, 'predicate': pred, 'object': list_head}
            if triple.get('annotations'):
                head['annotations'] = triple['annotations']
                head['object_str'] = list_head
            result.append(head)
            current = list_head
            for idx, el in enumerate(elements):
                result.append({'subject': current, 'predicate': 'rdf:first', 'object': el.strip()})
                if idx < len(elements) - 1:
                    next_bnode = f'_:sl_{blank_counter[0]}'
                    blank_counter[0] += 1
                    result.append({'subject': current, 'predicate': 'rdf:rest', 'object': next_bnode})
                    current = next_bnode
                else:
                    result.append({'subject': current, 'predicate': 'rdf:rest', 'object': 'rdf:nil'})
            needs_reexpand = True

        else:
            result.append(triple)

    return expand_triple_set(result, blank_counter) if needs_reexpand else result


def _parse_collection_elements(inside):
    """Parse space-separated elements from the inside of a ( ... ) collection."""
    elements = []
    buf = ''
    depth = 0
    in_str = False
    str_char = ''
    for c in inside:
        if in_str:
            buf += c
            if c == str_char:
                in_str = False
            continue
        if c in ('"', "'"):
            in_str, str_char = True, c
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
    return elements
