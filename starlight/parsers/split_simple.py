import re

def next_token(s):
    """Return (token, remaining) for the next atomic token in s (pre-stripped).

    Handles <<(...)>> quoted triple terms, <IRI>, triple-quoted strings,
    single-quoted strings, [...] blank nodes, (...) collections, and plain tokens.
    """
    if not s:
        return None, ''
    if s.startswith('<<('):
        i = 3
        depth = 1
        while i < len(s):
            if s[i:i+3] == ')>>':
                depth -= 1
                if depth == 0:
                    return s[:i+3], s[i+3:].lstrip()
                i += 3
            elif s[i:i+2] == '<<':
                depth += 1
                i += 2
            else:
                i += 1
        return s, ''
    if s.startswith('<<'):
        # << s p o >> embedded triple syntax (RDF*)
        i, depth, in_iri = 2, 1, False
        while i < len(s):
            if in_iri:
                if s[i] == '>':
                    in_iri = False
                i += 1
                continue
            if s[i:i+2] == '<<':
                depth += 1
                i += 2
            elif s[i:i+2] == '>>':
                depth -= 1
                if depth == 0:
                    return s[:i+2], s[i+2:].lstrip()
                i += 2
            elif s[i] == '<':
                in_iri = True
                i += 1
            else:
                i += 1
        return s, ''
    if s.startswith('<'):
        end = s.find('>', 1)
        return (s[:end+1], s[end+1:].lstrip()) if end != -1 else (s, '')
    if s.startswith('"""') or s.startswith("'''"):
        q = s[:3]
        i = 3
        while i <= len(s) - 3:
            if s[i:i+3] == q:
                return s[:i+3], s[i+3:].lstrip()
            i += 1
        return s, ''
    if s.startswith('"') or s.startswith("'"):
        q = s[0]
        i = 1
        while i < len(s):
            if s[i] == '\\':
                i += 2
                continue
            if s[i] == q:
                return s[:i+1], s[i+1:].lstrip()
            i += 1
        return s, ''
    if s.startswith('['):
        i, depth, in_str, str_char = 1, 1, False, ''
        while i < len(s) and depth > 0:
            c = s[i]
            if in_str:
                if c == str_char:
                    in_str = False
            elif c in ('"', "'"):
                in_str, str_char = True, c
            elif c == '[':
                depth += 1
            elif c == ']':
                depth -= 1
            i += 1
        return s[:i], s[i:].lstrip()
    if s.startswith('('):
        i, depth, in_str, str_char = 1, 1, False, ''
        while i < len(s) and depth > 0:
            c = s[i]
            if in_str:
                if c == str_char:
                    in_str = False
            elif c in ('"', "'"):
                in_str, str_char = True, c
            elif c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
            i += 1
        return s[:i], s[i:].lstrip()
    i = 0
    while i < len(s) and not s[i].isspace() and s[i] != '<':
        i += 1
    return s[:i], s[i:].lstrip()

def consume_annotation_block(s):
    """s starts with '{|'. Return (body_str, remaining). Handles nested {| |} and strings."""
    i, depth = 2, 1
    in_str, str_char = False, ''
    while i < len(s):
        c = s[i]
        if in_str:
            if c == '\\' and i + 1 < len(s):
                i += 2; continue
            if c == str_char:
                in_str = False
            i += 1; continue
        if c in ('"', "'"):
            in_str, str_char = True, c
            i += 1; continue
        if s[i:i+2] == '{|':
            depth += 1; i += 2
        elif s[i:i+2] == '|}':
            depth -= 1
            if depth == 0:
                return s[2:i].strip(), s[i+2:].lstrip()
            i += 2
        else:
            i += 1
    return s[2:].strip(), ''

def split_obj_and_annotations(s):
    """Split 'obj [~ reifier [{| body |}]]* [{| body |}]*' into (obj_token, [(reifier_or_None, body_or_None), ...])."""
    s = s.strip()
    obj_tok, rest = next_token(s)
    rest = rest.strip()
    # Consume ^^dtype or @lang suffix attached to a literal
    while rest.startswith('^^') or (rest.startswith('@') and len(rest) > 1 and rest[1].isalpha()):
        suffix, rest = next_token(rest)
        obj_tok += suffix
        rest = rest.strip()
    annotations = []
    while rest:
        if rest.startswith('~'):
            rest = rest[1:].lstrip()
            reifier, rest = next_token(rest)
            rest = rest.strip()
            if not reifier:
                break
            if rest.startswith('{|'):
                body, rest = consume_annotation_block(rest)
                rest = rest.strip()
                annotations.append((reifier, body))
            else:
                annotations.append((reifier, None))
        elif rest.startswith('{|'):
            body, rest = consume_annotation_block(rest)
            rest = rest.strip()
            annotations.append((None, body))
        else:
            break
    return obj_tok, annotations

def split_statements(data: str):
    stmts = []
    buf = ''
    depth = {'[': 0, '(': 0, '{': 0, '<': 0}
    in_string = False
    string_char = ''
    i = 0
    while i < len(data):
        # Special handling: If at start of line, check for PREFIX/BASE directive
        at_line_start = (i == 0 or data[i-1] in ('\n', '\r'))
        if at_line_start:
            # Look ahead for PREFIX/BASE (with or without @, case-insensitive)
            found_directive = False
            for kw in ('@prefix', 'prefix', '@base', 'base'):
                if data[i:i+len(kw)].lower() == kw:
                    # Find end of line
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

def classify_statement(stmt):
    s = stmt.strip()
    if s.lower().startswith('@prefix') or s.lower().startswith('prefix'):
        return 'prefix'
    elif s.lower().startswith('@base') or s.lower().startswith('base'):
        return 'base'
    else:
        return 'triple'

def coerce_object(s):
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

def extract_fields(stmt, typ):
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
        body = s.rstrip()
        if body.endswith('.'):
            body = body[:-1].rstrip()
        subj, rest = next_token(body.strip())
        if subj and rest:
            triple_set = []
            pred_obj_groups = []
            buf = ''
            depth = 0
            in_str = False
            str_char = ''
            for ch in rest:
                if in_str:
                    buf += ch
                    if ch == str_char:
                        in_str = False
                    continue
                if ch in ('"', "'"):
                    in_str = True
                    str_char = ch
                    buf += ch
                    continue
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

            for group in pred_obj_groups:
                pred, obj_str = next_token(group)
                if not pred or not obj_str:
                    continue
                # Split on ',' for object lists, respecting nesting and strings
                objs = []
                buf = ''
                depth = 0
                in_str = False
                str_char = ''
                for ch in obj_str:
                    if in_str:
                        buf += ch
                        if ch == str_char:
                            in_str = False
                        continue
                    if ch in ('"', "'"):
                        in_str = True
                        str_char = ch
                        buf += ch
                        continue
                    if ch in '[({':
                        depth += 1
                    elif ch in '])}':
                        depth -= 1
                    if ch == ',' and depth == 0:
                        if buf.strip():
                            objs.append(buf.strip())
                        buf = ''
                    else:
                        buf += ch
                if buf.strip():
                    objs.append(buf.strip())

                for obj in objs:
                    obj_tok, annotations = split_obj_and_annotations(obj)
                    entry = {'subject': subj, 'predicate': pred, 'object': coerce_object(obj_tok)}
                    if annotations:
                        entry['annotations'] = annotations
                        entry['object_str'] = obj_tok
                    triple_set.append(entry)

            return {'triple_set': triple_set}
    return {}

def expand_triple_set(triple_set, blank_counter):
    changed = False
    new_triples = []
    for triple in triple_set:
        subj, pred, obj = triple['subject'], triple['predicate'], triple['object']
        obj_strip = obj.strip() if isinstance(obj, str) else obj
        # Expand blank node: [ ... ]
        if isinstance(obj_strip, str) and obj_strip.startswith('[') and obj_strip.endswith(']'):
            bnode = f'_:sl_{blank_counter[0]}'
            blank_counter[0] += 1
            head = {'subject': subj, 'predicate': pred, 'object': bnode}
            if triple.get('annotations'):
                head['annotations'] = triple['annotations']
                head['object_str'] = bnode
            new_triples.append(head)
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
            if not elements:
                head = {'subject': subj, 'predicate': pred, 'object': 'rdf:nil'}
                if triple.get('annotations'):
                    head['annotations'] = triple['annotations']
                    head['object_str'] = 'rdf:nil'
                new_triples.append(head)
                changed = True
                continue
            list_head = f'_:sl_{blank_counter[0]}'
            blank_counter[0] += 1
            head = {'subject': subj, 'predicate': pred, 'object': list_head}
            if triple.get('annotations'):
                head['annotations'] = triple['annotations']
                head['object_str'] = list_head
            new_triples.append(head)
            changed = True
            current = list_head
            for idx, el in enumerate(elements):
                el_strip = el.strip()
                if el_strip.startswith('[') and el_strip.endswith(']'):
                    bnode = f'_:sl_{blank_counter[0]}'
                    blank_counter[0] += 1
                    new_triples.append({'subject': current, 'predicate': 'rdf:first', 'object': bnode})
                    inner = el_strip[1:-1].strip()
                    fake_stmt = f'{bnode} {inner} .'
                    inner_fields = extract_fields(fake_stmt, 'triple')
                    if inner_fields and 'triple_set' in inner_fields:
                        expanded_inner = expand_triple_set(inner_fields['triple_set'], blank_counter)
                        for t in expanded_inner:
                            new_triples.append(t)
                elif el_strip.startswith('(') and el_strip.endswith(')'):
                    nested_head = f'_:sl_{blank_counter[0]}'
                    blank_counter[0] += 1
                    new_triples.append({'subject': current, 'predicate': 'rdf:first', 'object': nested_head})
                    fake_triple = {'subject': current, 'predicate': 'rdf:first', 'object': el_strip}
                    nested_triples = expand_triple_set([fake_triple], blank_counter)
                    for t in nested_triples:
                        if t['subject'] != current or t['predicate'] != 'rdf:first':
                            new_triples.append(t)
                else:
                    new_triples.append({'subject': current, 'predicate': 'rdf:first', 'object': el_strip})
                if idx < len(elements) - 1:
                    next_bnode = f'_:sl_{blank_counter[0]}'
                    blank_counter[0] += 1
                    new_triples.append({'subject': current, 'predicate': 'rdf:rest', 'object': next_bnode})
                    current = next_bnode
                else:
                    new_triples.append({'subject': current, 'predicate': 'rdf:rest', 'object': 'rdf:nil'})
        else:
            new_triples.append(triple)
    if changed:
        return expand_triple_set(new_triples, blank_counter)
    else:
        return new_triples
