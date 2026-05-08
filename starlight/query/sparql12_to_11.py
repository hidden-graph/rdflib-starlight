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

import re as _re
from dataclasses import dataclass

RDF_SUBJECT   = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#subject>"
RDF_PREDICATE = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#predicate>"
RDF_OBJECT    = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#object>"
TT_NS_PREFIX  = "http://starlight.org/ns/tt#"

_TRIPLE_FUNC_RE = _re.compile(
    r'\b(SUBJECT|PREDICATE|OBJECT)\s*\(\s*(\?[A-Za-z_][A-Za-z0-9_]*)\s*\)',
    _re.IGNORECASE,
)
_IS_TT_RE = _re.compile(r'\bisTripleTerm\s*\(\s*(\?[A-Za-z_][A-Za-z0-9_]*)\s*\)', _re.IGNORECASE)

_FUNC_TO_PRED = {
    'SUBJECT':   RDF_SUBJECT,
    'PREDICATE': RDF_PREDICATE,
    'OBJECT':    RDF_OBJECT,
}

# BIND(SUBJECT(?tt) AS ?s)  →  ?tt <rdf:subject> ?s  (in-place, no outer injection)
_BIND_ACCESSOR_RE = _re.compile(
    r'\bBIND\s*\(\s*(SUBJECT|PREDICATE|OBJECT)\s*\(\s*(\?[A-Za-z_]\w*)\s*\)\s+AS\s+(\?[A-Za-z_]\w*)\s*\)',
    _re.IGNORECASE,
)

# A SPARQL term: variable, full IRI, prefixed name, default-prefix name,
# quoted literal (simple), blank node, or rdf:type shorthand 'a'.
_T = (
    r'(?:'
    r'\?[A-Za-z_]\w*'               # variable
    r'|<[^>]+>'                     # full IRI
    r'|"[^"\\]*(?:\\.[^"\\]*)*"'    # double-quoted literal
    r"|'[^'\\]*(?:\\.[^'\\]*)*'"    # single-quoted literal
    r'|[A-Za-z_]\w*:[A-Za-z_]\w*'  # prefixed name  prefix:local
    r'|:[A-Za-z_]\w*'               # default-prefix name  :local
    r'|_:[A-Za-z_]\w*'              # blank node
    r'|\ba\b'                       # rdf:type shorthand
    r')'
)

# << s p o >> pred obj  — annotation subject pattern
_ANN_SUBJECT_RE = _re.compile(
    rf'<<\s+({_T})\s+({_T})\s+({_T})\s*>>\s+({_T})\s+({_T})',
)

# s p o {| ap av ; ap2 av2 |}  — inline annotation block
_ANN_BLOCK_RE = _re.compile(
    rf'({_T})\s+({_T})\s+({_T})\s*\{{\|\s*(.*?)\s*\|\}}',
    _re.DOTALL,
)

# s p o ~?r  — reifier binding (tilde must be surrounded by whitespace)
_TILDE_RE = _re.compile(
    rf'({_T})\s+({_T})\s+({_T})\s+~\s+(\?[A-Za-z_]\w*)',
)


@dataclass
class _RewriteState:
    next_var_index: int = 0

    def new_var(self) -> str:
        name = f"?__tt{self.next_var_index}"
        self.next_var_index += 1
        return name


def rewrite_sparql12_to_11(query: str) -> str:
    """Rewrite SPARQL 1.2 triple-term syntax to SPARQL 1.1.

    Handles:
    - ``<<( s p o )>>`` triple-term patterns in WHERE clauses
    - ``<< s p o >> pred obj`` annotation subject patterns
    - ``s p o {| ap av ; ... |}`` inline annotation blocks
    - ``s p o ~?r`` reifier-binding shorthand
    - ``SUBJECT(?tt)``, ``PREDICATE(?tt)``, ``OBJECT(?tt)`` function calls
    - ``isTripleTerm(?x)`` filter function

    Queries with none of these forms are returned unchanged.
    """
    needs_tt   = "<<(" in query
    needs_ann  = _re.search(r'<<[^(]|\{\|', query) is not None or '~' in query
    needs_func = _TRIPLE_FUNC_RE.search(query) is not None
    needs_istt = _IS_TT_RE.search(query) is not None

    if not (needs_tt or needs_ann or needs_func or needs_istt):
        return query

    state = _RewriteState()

    if needs_istt:
        query = _IS_TT_RE.sub(
            lambda m: f'STRSTARTS(STR({m.group(1)}), "{TT_NS_PREFIX}")',
            query,
        )

    if needs_ann:
        query = _rewrite_annotation_forms(query, state)

    if needs_func:
        # BIND(SUBJECT(?tt) AS ?s) → ?tt <rdf:subject> ?s  in-place.
        # This keeps the binding triple inside the same group graph pattern (and
        # named-graph scope) as the original BIND, which is essential for correct
        # evaluation when the BIND appears inside a GRAPH { } clause.
        query = _rewrite_bind_accessors(query)
        needs_func = bool(_TRIPLE_FUNC_RE.search(query))

    # Run _rewrite_group_content when there are <<( )>> patterns OR when there
    # are non-BIND function calls that need inline injection inside blocks.
    if needs_tt or needs_func or "<<(" in query:
        query = _rewrite_group_content(query, state)

    # After inline handling, any remaining SUBJECT/PREDICATE/OBJECT calls live
    # outside {…} blocks (SELECT projections, HAVING, ORDER BY).  Inject their
    # binding triples at the WHERE level — correct for those clause positions.
    if needs_func and _TRIPLE_FUNC_RE.search(query):
        query = _rewrite_triple_functions(query, state)

    return query


def _rewrite_bind_accessors(query: str) -> str:
    """Rewrite BIND(SUBJECT(?tt) AS ?s) → ?tt <rdf:subject> ?s in place.

    Unlike the WHERE-level injection used for SELECT-projection function calls,
    this keeps the binding triple inside the same group graph pattern as the
    original BIND.  That is essential when the BIND appears inside a GRAPH { }
    clause: rdflib's SPARQL engine does not propagate outer-scope variable
    bindings into BIND or FILTER expressions inside a named-graph scope.
    """
    def _replace(m: _re.Match) -> str:
        func = m.group(1).upper()
        tt_var, result_var = m.group(2), m.group(3)
        return f"{tt_var} {_FUNC_TO_PRED[func]} {result_var} ."
    return _BIND_ACCESSOR_RE.sub(_replace, query)


def _rewrite_annotation_forms(query: str, state: _RewriteState) -> str:
    """Pre-pass: convert << >>, {| |}, and ~?r annotation forms.

    All three forms are sugar for: assert the base triple, then query or bind
    the reifier. Each rewrites to an explicit ``rdf:reifies <<( )>>`` pattern
    that the main ``<<( )>>`` rewriter then expands.

    Limitation: term matching uses a simplified regex that covers variables,
    prefixed names, full IRIs, and simple literals. Complex literals with
    embedded spaces or datatype suffixes are not handled.
    """
    # Pass 1: s p o ~?r  →  s p o . ?r rdf:reifies <<( s p o )>>
    def _tilde(m: _re.Match) -> str:
        s, p, o, r = m.group(1), m.group(2), m.group(3), m.group(4)
        return f"{s} {p} {o} .\n  {r} rdf:reifies <<( {s} {p} {o} )>>"

    query = _TILDE_RE.sub(_tilde, query)

    # Pass 2: s p o {| ap av ; ... |}  →  s p o . ?__rN rdf:reifies <<( s p o )>> . ?__rN ap av . ...
    def _ann_block(m: _re.Match) -> str:
        s, p, o = m.group(1), m.group(2), m.group(3)
        pairs = [pair.strip() for pair in m.group(4).split(';') if pair.strip()]
        r_var = state.new_var()
        parts = [f"{s} {p} {o}",
                 f"{r_var} rdf:reifies <<( {s} {p} {o} )>>"]
        parts.extend(f"{r_var} {pair}" for pair in pairs)
        return " .\n  ".join(parts)

    query = _ANN_BLOCK_RE.sub(_ann_block, query)

    # Pass 3: << s p o >> pred obj  →  s p o . ?__rN rdf:reifies <<( s p o )>> . ?__rN pred obj
    def _ann_subject(m: _re.Match) -> str:
        s, p, o = m.group(1), m.group(2), m.group(3)
        pred, obj = m.group(4), m.group(5)
        r_var = state.new_var()
        return (f"{s} {p} {o} .\n  "
                f"{r_var} rdf:reifies <<( {s} {p} {o} )>> .\n  "
                f"{r_var} {pred} {obj}")

    query = _ANN_SUBJECT_RE.sub(_ann_subject, query)

    return query


def _rewrite_triple_functions(query: str, state: _RewriteState) -> str:
    """Rewrite SUBJECT/PREDICATE/OBJECT(?var) calls.

    Each call is replaced with a fresh variable; the corresponding
    rdf:subject/predicate/object triple is injected at the start of the
    outermost WHERE { } body so the variable is bound before SELECT sees it.
    """
    injected: list[str] = []

    def replacer(m: _re.Match) -> str:
        pred = _FUNC_TO_PRED[m.group(1).upper()]
        src_var = m.group(2)
        new_var = state.new_var()
        injected.append(f"{src_var} {pred} {new_var} .")
        return new_var

    result = _TRIPLE_FUNC_RE.sub(replacer, query)

    if injected:
        where_m = _re.search(r'\bWHERE\s*\{', result, _re.IGNORECASE)
        if where_m:
            insert_pos = where_m.end()
            result = (result[:insert_pos]
                      + "\n  " + "\n  ".join(injected)
                      + result[insert_pos:])

    return result


def _rewrite_group_content(text: str, state: _RewriteState,
                           handle_funcs: bool = False) -> str:
    """Rewrite <<( )>> triple-term patterns and, when handle_funcs is True,
    SUBJECT/PREDICATE/OBJECT function calls inline within the current block.

    handle_funcs is False at the outermost call (SELECT/WHERE level) so that
    accessor functions in SELECT projections are left for _rewrite_triple_functions
    to handle via WHERE-level injection (correct for that clause position).
    It is set to True for all recursive calls (inside { } blocks) so that
    functions inside GRAPH, OPTIONAL, UNION etc. inject their binding triple
    within the same named-graph scope rather than at the outer WHERE level.
    """
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

        # Inline SUBJECT/PREDICATE/OBJECT detection — only inside blocks.
        # Injects the binding triple into the current group graph pattern via
        # pending_patterns, which is emitted at the next '.' or '}' boundary.
        # This keeps the triple in the same named-graph scope as the function call.
        if handle_funcs and text[i].isalpha():
            m = _TRIPLE_FUNC_RE.match(text, i)
            if m:
                func = m.group(1).upper()
                tt_var = m.group(2)
                fresh_var = state.new_var()
                buffer.append(fresh_var)
                pending_patterns.append(f"{tt_var} {_FUNC_TO_PRED[func]} {fresh_var} .")
                i = m.end()
                continue

        if text[i] == '{':
            inner, i = _consume_balanced(text, i, '{', '}')
            rewritten = _rewrite_group_content(inner[1:-1], state, handle_funcs=True)
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
            buffer.append(' .')
            buffer.append(_emit_pending_patterns(pending_patterns))
            pending_patterns.clear()
            buffer.append(text[i])
            i += 1
            continue

        buffer.append(text[i])
        i += 1

    if pending_patterns:
        buffer.append(' .')
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


# ---------------------------------------------------------------------------
# Registry-based simplified rewriting (avoids N×M encoding triple queries)
# ---------------------------------------------------------------------------

def _is_sparql_var(spec: str) -> bool:
    return spec.startswith('?')


@dataclass
class TtDescriptor:
    """Describes a single <<( )>> pattern replaced by a plain variable.

    var      — the fresh internal variable, e.g. '?__tt0'
    s_spec   — SPARQL term string for the subject   component ('?s' or '<uri>')
    p_spec   — SPARQL term string for the predicate component
    o_spec   — SPARQL term string for the object    component
    """
    var: str
    s_spec: str
    p_spec: str
    o_spec: str

    @property
    def can_resolve(self) -> bool:
        """True when every non-variable spec is a full <IRI> we can compare directly.

        Prefixed names (ex:foo), literals, and the rdf:type shorthand 'a' would
        need a prefix-expansion context we don't have here; those fall back to the
        encoding rewriter instead.
        """
        return all(
            _is_sparql_var(s) or (s.startswith('<') and s.endswith('>'))
            for s in (self.s_spec, self.p_spec, self.o_spec)
        )


def _rewrite_tt_simplified(text: str, start: int, state: _RewriteState
                            ) -> tuple[str, TtDescriptor | None, int]:
    """Replace one <<( s p o )>> with a plain variable.

    Returns (var_token, descriptor, end_pos).

    If any component is itself a nested TT (complex case), returns descriptor=None
    to signal the caller should fall back to the encoding rewriter.
    """
    token, end = _consume_triple_term(text, start)
    inner = token[3:-3].strip()
    parts = _split_top_level_terms(inner)
    if len(parts) != 3:
        raise ValueError(f"Triple term must contain exactly 3 terms: {token}")

    s_spec, p_spec, o_spec = [p.strip() for p in parts]

    # Nested TTs (not allowed by spec, but guard anyway)
    if any(s.startswith('<<(') for s in (s_spec, p_spec, o_spec)):
        return None, None, end

    tt_var = state.new_var()
    desc = TtDescriptor(var=tt_var, s_spec=s_spec, p_spec=p_spec, o_spec=o_spec)
    return tt_var, desc, end


def _rewrite_group_content_simplified(text: str, state: _RewriteState
                                       ) -> tuple[str, list[TtDescriptor | None]]:
    """Walk the WHERE body replacing <<( )>> with plain variables.

    Returns the rewritten text and a list of TtDescriptors (one per pattern).
    A None entry means that pattern could not be simplified; the caller should
    fall back to the full encoding rewriter.
    """
    result: list[str] = []
    descs: list[TtDescriptor | None] = []
    i = 0

    while i < len(text):
        if text.startswith("#", i):
            end = text.find("\n", i)
            if end == -1:
                result.append(text[i:])
                i = len(text)
            else:
                result.append(text[i:end + 1])
                i = end + 1
            continue

        if text.startswith('"""', i) or text.startswith("'''", i):
            literal, i = _consume_string(text, i, text[i:i + 3])
            result.append(literal)
            continue

        if text[i] in {'"', "'"}:
            literal, i = _consume_string(text, i, text[i])
            result.append(literal)
            continue

        if text[i] == '<' and not text.startswith("<<(", i):
            iri, i = _consume_iri(text, i)
            result.append(iri)
            continue

        if text.startswith("<<(", i):
            var, desc, i = _rewrite_tt_simplified(text, i, state)
            if desc is None:
                descs.append(None)
                result.append(var if var else text[i])
            else:
                descs.append(desc)
                result.append(var)
            continue

        if text[i] == '{':
            inner, i = _consume_balanced(text, i, '{', '}')
            rewritten, inner_descs = _rewrite_group_content_simplified(inner[1:-1], state)
            result.append('{')
            result.append(rewritten)
            result.append('}')
            descs.extend(inner_descs)
            continue

        result.append(text[i])
        i += 1

    return ''.join(result), descs


def rewrite_sparql12_simplified(query: str) -> tuple[str, list[TtDescriptor]] | None:
    """Attempt a simplified rewrite of SPARQL 1.2 TT patterns.

    Replaces each <<( s p o )>> with a plain variable ?__ttN (no encoding
    triple patterns are emitted). Returns (simplified_query, descriptors).

    Returns None if any TT pattern cannot be simplified (nested TT, complex
    component), signalling the caller to fall back to the full encoding rewriter.

    Only rewrites the main WHERE body; leaves SELECT/ASK/CONSTRUCT unchanged.
    Also applies the same non-TT rewrites as rewrite_sparql12_to_11 (annotation
    blocks, tilde reifier, isTripleTerm, accessor functions).
    """
    if '<<(' not in query:
        return query, []

    where_m = _re.search(r'\bWHERE\s*\{', query, _re.IGNORECASE)
    if not where_m:
        return None

    prefix = query[:where_m.end()]
    rest   = query[where_m.end():]

    # Find the matching closing brace for the main WHERE { }
    body_with_brace, after = rest, ''
    depth = 1
    i = 0
    while i < len(rest) and depth > 0:
        if rest[i] == '{':
            depth += 1
        elif rest[i] == '}':
            depth -= 1
        i += 1
    body = rest[:i - 1]
    after = rest[i - 1:]

    state = _RewriteState()
    rewritten_body, descs = _rewrite_group_content_simplified(body, state)

    if any(d is None or not d.can_resolve for d in descs):
        return None  # cannot simplify — fall back

    # Apply the same non-TT rewrites as rewrite_sparql12_to_11.
    full = prefix + rewritten_body + after

    needs_ann  = _re.search(r'<<[^(]|\{\|', full) is not None or '~' in full
    needs_func = _TRIPLE_FUNC_RE.search(full) is not None

    if _IS_TT_RE.search(full):
        full = _IS_TT_RE.sub(
            lambda m: f'STRSTARTS(STR({m.group(1)}), "{TT_NS_PREFIX}")', full
        )

    if needs_ann:
        full = _rewrite_annotation_forms(full, state)

    if needs_func:
        full = _rewrite_bind_accessors(full)
        if _TRIPLE_FUNC_RE.search(full):
            full = _rewrite_triple_functions(full, state)

    return full, [d for d in descs]


def inject_tt_vars_into_select(query: str, tt_vars: list[str]) -> str:
    """Add internal TT variables to the SELECT projection.

    Handles SELECT ?a ?b, SELECT DISTINCT ?a, and SELECT *.
    For SELECT * the variables are already projected; no change needed.
    """
    if not tt_vars:
        return query

    m = _re.search(r'\bSELECT\b\s*(?:DISTINCT\s+|REDUCED\s+)?\*', query, _re.IGNORECASE)
    if m:
        return query  # SELECT * — ?__ttN projected automatically

    where_m = _re.search(r'\bWHERE\b', query, _re.IGNORECASE)
    if not where_m:
        return query

    extra = ' '.join(tt_vars)
    pos = where_m.start()
    return query[:pos].rstrip() + ' ' + extra + ' ' + query[pos:]
    raise ValueError("Unterminated IRI")