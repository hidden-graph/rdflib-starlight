"""
starlight.parsers.lexer

Character-level tokenization for Turtle 1.2. Handles all token forms:
<<( )>> triple terms, << >> reification shorthand, <IRI>, quoted strings,
[ ] blank nodes, ( ) collections, and plain whitespace-delimited tokens.
"""


def next_token(s):
    """Return (token, remaining) for the next atomic token in s (pre-stripped)."""
    if not s:
        return None, ''

    if s.startswith('<<('):
        i, depth = 3, 1
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
                i += 2
                continue
            if c == str_char:
                in_str = False
            i += 1
            continue
        if c in ('"', "'"):
            in_str, str_char = True, c
            i += 1
            continue
        if s[i:i+2] == '{|':
            depth += 1
            i += 2
        elif s[i:i+2] == '|}':
            depth -= 1
            if depth == 0:
                return s[2:i].strip(), s[i+2:].lstrip()
            i += 2
        else:
            i += 1
    return s[2:].strip(), ''


def split_obj_and_annotations(s):
    """Split 'obj [~ reifier [{| body |}]]* [{| body |}]*' into
    (obj_token, [(reifier_or_None, body_or_None), ...])."""
    s = s.strip()
    obj_tok, rest = next_token(s)
    rest = rest.strip()
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
                annotations.append((reifier, body))
            else:
                annotations.append((reifier, None))
            rest = rest.strip()
        elif rest.startswith('{|'):
            body, rest = consume_annotation_block(rest)
            annotations.append((None, body))
            rest = rest.strip()
        else:
            break
    return obj_tok, annotations
