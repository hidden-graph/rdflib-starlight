"""Translate a small SPARQL 1.2 subset into SPARQL 1.1 graph patterns.

The current focus is triple-term graph patterns such as::

    ?stmt rdf:reifies <<( :s :p :o )>> .
    <<( ?s :p ?o )>> :verifiedBy ?who .

Those forms are rewritten into ordinary SPARQL 1.1 basic graph patterns over
the internal starlight encoding used by ``StarlightGraph``'s rdflib store.

This module does not attempt to parse the full SPARQL grammar. It is a scoped,
string-based rewriter designed to preserve the lexical block in which a triple
term appears, so OPTIONAL/UNION branch semantics remain local.
"""

from __future__ import annotations

from dataclasses import dataclass

RDF_SUBJECT = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#subject>"
RDF_PREDICATE = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#predicate>"
RDF_OBJECT = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#object>"


@dataclass
class _RewriteState:
    next_var_index: int = 0

    def new_var(self) -> str:
        name = f"?__tt{self.next_var_index}"
        self.next_var_index += 1
        return name


def rewrite_sparql12_to_11(query: str) -> str:
    """Rewrite triple-term graph patterns into SPARQL 1.1 patterns.

    The function is intentionally conservative. Queries that do not contain the
    ``<<( ... )>>`` triple-term syntax are returned unchanged.
    """
    if "<<(" not in query:
        return query
    state = _RewriteState()
    return _rewrite_group_content(query, state)


def _rewrite_group_content(text: str, state: _RewriteState) -> str:
    result: list[str] = []
    pending_patterns: list[str] = []
    buffer: list[str] = []
    i = 0

    while i < len(text):
        if text.startswith("#", i):
            comment_end = text.find("\n", i)
            if comment_end == -1:
                buffer.append(text[i:])
                i = len(text)
            else:
                buffer.append(text[i:comment_end + 1])
                i = comment_end + 1
            continue

        if text.startswith('"""', i) or text.startswith("'''", i):
            literal, i = _consume_string(text, i, text[i:i + 3])
            buffer.append(literal)
            continue

        if text[i] in {'"', "'"}:
            literal, i = _consume_string(text, i, text[i])
            buffer.append(literal)
            continue

        if text[i] == '<' and not text.startswith("<<(", i):
            iri, i = _consume_iri(text, i)
            buffer.append(iri)
            continue

        if text.startswith("<<(", i):
            replacement, patterns, i = _rewrite_triple_term(text, i, state)
            buffer.append(replacement)
            pending_patterns.extend(patterns)
            continue

        if text[i] == '{':
            inner, i = _consume_balanced(text, i, '{', '}')
            rewritten = _rewrite_group_content(inner[1:-1], state)
            buffer.append('{')
            buffer.append(rewritten)
            buffer.append('}')
            continue

        if text[i] == '.' and pending_patterns:
            buffer.append(text[i])
            buffer.append(_emit_pending_patterns(pending_patterns))
            i += 1
            pending_patterns.clear()
            continue

        if text[i] == '}' and pending_patterns:
            buffer.append(_emit_pending_patterns(pending_patterns))
            pending_patterns.clear()
            buffer.append(text[i])
            i += 1
            continue

        buffer.append(text[i])
        i += 1

    if pending_patterns:
        buffer.append(_emit_pending_patterns(pending_patterns))

    result.extend(buffer)
    return ''.join(result)


def _rewrite_triple_term(text: str, start: int, state: _RewriteState) -> tuple[str, list[str], int]:
    token, end = _consume_triple_term(text, start)
    inner = token[3:-3].strip()
    parts = _split_top_level_terms(inner)
    if len(parts) != 3:
        raise ValueError(f"Triple term must contain exactly 3 terms: {token}")

    subject_token, subject_patterns = _rewrite_term(parts[0], state)
    predicate_token, predicate_patterns = _rewrite_term(parts[1], state)
    object_token, object_patterns = _rewrite_term(parts[2], state)

    tt_var = state.new_var()
    patterns = []
    patterns.extend(subject_patterns)
    patterns.extend(predicate_patterns)
    patterns.extend(object_patterns)
    patterns.append(f"{tt_var} {RDF_SUBJECT} {subject_token} .")
    patterns.append(f"{tt_var} {RDF_PREDICATE} {predicate_token} .")
    patterns.append(f"{tt_var} {RDF_OBJECT} {object_token} .")
    return tt_var, patterns, end


def _rewrite_term(term: str, state: _RewriteState) -> tuple[str, list[str]]:
    stripped = term.strip()
    if stripped.startswith("<<("):
        replacement, patterns, _ = _rewrite_triple_term(stripped, 0, state)
        return replacement, patterns
    return stripped, []


def _emit_pending_patterns(patterns: list[str]) -> str:
    return "\n  " + "\n  ".join(patterns) + "\n"


def _split_top_level_terms(text: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    i = 0
    depth_paren = 0
    depth_bracket = 0

    while i < len(text):
        if text.startswith('"""', i) or text.startswith("'''", i):
            literal, i = _consume_string(text, i, text[i:i + 3])
            current.append(literal)
            continue

        if text[i] in {'"', "'"}:
            literal, i = _consume_string(text, i, text[i])
            current.append(literal)
            continue

        if text[i] == '<' and not text.startswith("<<(", i):
            iri, i = _consume_iri(text, i)
            current.append(iri)
            continue

        if text.startswith("<<(", i):
            triple_term, i = _consume_triple_term(text, i)
            current.append(triple_term)
            continue

        if text[i] == '(':
            depth_paren += 1
        elif text[i] == ')':
            depth_paren = max(depth_paren - 1, 0)
        elif text[i] == '[':
            depth_bracket += 1
        elif text[i] == ']':
            depth_bracket = max(depth_bracket - 1, 0)

        if text[i].isspace() and depth_paren == 0 and depth_bracket == 0:
            if current:
                parts.append(''.join(current).strip())
                current.clear()
            i += 1
            continue

        current.append(text[i])
        i += 1

    if current:
        parts.append(''.join(current).strip())
    return [part for part in parts if part]


def _consume_triple_term(text: str, start: int) -> tuple[str, int]:
    if not text.startswith("<<(", start):
        raise ValueError("Triple term must start with '<<('")
    i = start + 3
    depth = 1

    while i < len(text):
        if text.startswith('"""', i) or text.startswith("'''", i):
            _, i = _consume_string(text, i, text[i:i + 3])
            continue

        if text[i] in {'"', "'"}:
            _, i = _consume_string(text, i, text[i])
            continue

        if text[i] == '<' and not text.startswith("<<(", i):
            _, i = _consume_iri(text, i)
            continue

        if text.startswith("<<(", i):
            depth += 1
            i += 3
            continue

        if text.startswith(")>>", i):
            depth -= 1
            i += 3
            if depth == 0:
                return text[start:i], i
            continue

        i += 1

    raise ValueError("Unterminated triple term")


def _consume_balanced(text: str, start: int, opener: str, closer: str) -> tuple[str, int]:
    if text[start] != opener:
        raise ValueError(f"Expected {opener!r}")
    i = start + 1
    depth = 1

    while i < len(text):
        if text.startswith('"""', i) or text.startswith("'''", i):
            _, i = _consume_string(text, i, text[i:i + 3])
            continue

        if text[i] in {'"', "'"}:
            _, i = _consume_string(text, i, text[i])
            continue

        if text[i] == '<' and not text.startswith("<<(", i):
            _, i = _consume_iri(text, i)
            continue

        if text.startswith("<<(", i):
            _, i = _consume_triple_term(text, i)
            continue

        if text[i] == opener:
            depth += 1
        elif text[i] == closer:
            depth -= 1
            if depth == 0:
                return text[start:i + 1], i + 1
        i += 1

    raise ValueError(f"Unterminated {opener}{closer} block")


def _consume_string(text: str, start: int, delimiter: str) -> tuple[str, int]:
    i = start + len(delimiter)
    while i < len(text):
        if text.startswith('\\', i):
            i += 2
            continue
        if text.startswith(delimiter, i):
            i += len(delimiter)
            return text[start:i], i
        i += 1
    raise ValueError("Unterminated string literal")


def _consume_iri(text: str, start: int) -> tuple[str, int]:
    i = start + 1
    while i < len(text):
        if text.startswith('\\', i):
            i += 2
            continue
        if text[i] == '>':
            return text[start:i + 1], i + 1
        i += 1
    raise ValueError("Unterminated IRI")