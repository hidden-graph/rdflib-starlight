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
from dataclasses import dataclass, field

RDF_SUBJECT     = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#subject>"
RDF_PREDICATE   = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#predicate>"
RDF_OBJECT      = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#object>"
RDF_REIFIES     = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies>"
TT_NS_PREFIX    = "https://github.com/hidden-graph/rdflib-starlight/ns/tt#"
DIRLANG_NS_PREFIX = "https://github.com/hidden-graph/rdflib-starlight/ns/dirlang#"

# SPARQL-callable function computing the same content-addressed tt:HASH URIRef
# that StarlightGraph._intern_tt() assigns on write. Used to BIND a triple-term
# variable that a CONSTRUCT template needs but that has no existing WHERE-clause
# match to bind it from (i.e. the template is minting a triple term that was
# never previously used as a value anywhere in the graph).
TT_HASH_FN = f"<{TT_NS_PREFIX}fn/hash>"


def _register_tt_hash_function() -> None:
    from rdflib import URIRef
    from rdflib.plugins.sparql.operators import register_custom_function

    from starlight.model.encoding import TT_NS, tt_hash, remember_tt_hash

    def _tt_hash_fn(s, p, o):
        uri = URIRef(TT_NS + tt_hash(str(s), str(p), str(o)))
        # s/p/o here are rdflib's own already-resolved terms (this function
        # runs at SPARQL *evaluation* time, after parsing/prefix-resolution,
        # not at this module's text-rewrite time) - remembering them lets
        # StarlightGraph._restore() reconstruct a proper TripleTerm for a
        # value that was computed but never written to any graph. See
        # starlight.model.encoding's _TT_HASH_MEMO docstring.
        remember_tt_hash(uri, s, p, o)
        return uri

    register_custom_function(URIRef(TT_HASH_FN[1:-1]), _tt_hash_fn, override=True)


# Deliberate import-time side effect: this mutates rdflib's *global*
# CUSTOM_EVALS/function registry the moment this module is imported, not on
# first use. override=True is intentional too - re-importing this module (or
# a reload) re-registers idempotently under the same TT_HASH_FN URI rather
# than raising on a duplicate registration, since it's always the same
# function. The tradeoff: nothing else in the process may register a
# different function at this exact URI and expect it to stick - acceptable
# here since TT_NS/DIRLANG_NS are starlight's own namespaces, not shared with
# any other library.
_register_tt_hash_function()

_TRIPLE_FUNC_RE = _re.compile(
    r'\b(SUBJECT|PREDICATE|OBJECT)\s*\(\s*([?$][A-Za-z_][A-Za-z0-9_]*)\s*\)',
    _re.IGNORECASE,
)

# SUBJECT/PREDICATE/OBJECT applied directly to a <<( )>> literal rather than
# a bound variable, e.g. SUBJECT(<<( :a :b :c )>>) - detected separately from
# _TRIPLE_FUNC_RE above (which only matches a bare-variable argument) and
# desugared by _rewrite_triple_accessor_literals(), which runs much earlier
# in the pipeline. Lookahead only, like _TRIPLE_CALL_RE - the actual call is
# consumed with _consume_balanced() since its content can itself contain
# nested parens/triple terms that a regex can't reliably bound.
_TRIPLE_ACCESSOR_LITERAL_RE = _re.compile(
    r'\b(SUBJECT|PREDICATE|OBJECT)\s*(?=\(\s*<<\()', _re.IGNORECASE,
)
_ACCESSOR_TO_INDEX = {'SUBJECT': 0, 'PREDICATE': 1, 'OBJECT': 2}
# isTRIPLE is the SPARQL 1.2 spec's own name (17.4.6); isTripleTerm is starlight's
# original, more descriptive spelling predating that section's stabilization. Both
# are accepted so a query copied verbatim from the spec or another RDF 1.2 tool
# works unchanged.
_IS_TT_RE = _re.compile(r'\bis(?:TripleTerm|Triple)\s*\(\s*([?$][A-Za-z_][A-Za-z0-9_]*)\s*\)', _re.IGNORECASE)

# TRIPLE(s, p, o) is the SPARQL 1.2 spec's function-call constructor for a triple
# term (17.4.6) - the spec treats it as equivalent to writing <<( s p o )>> as a
# term. Detected here only to decide whether the (costlier) rewrite pass below is
# needed; the actual conversion happens in _rewrite_triple_calls().
_TRIPLE_CALL_RE = _re.compile(r'\bTRIPLE\s*(?=\()', _re.IGNORECASE)

# RDF 1.2 base-direction functions (SPARQL 1.2 Query sec 17.4.2), rewritten by
# _rewrite_dirlang_and_strlangdir() below. Unlike SUBJECT/PREDICATE/OBJECT,
# none of these need WHERE-clause pattern injection - they rewrite to plain
# expression built-ins (DATATYPE/STR/STRSTARTS/... or, for STRLANGDIR, the
# registered constructor function below) evaluated against the internal
# dirlang: datatype-URI encoding (see starlight.model.dirlangstring).
#
# STRLANGDIR is a SPARQL-callable function (registered like TT_HASH_FN) rather
# than a pure STRDT/IRI/CONCAT/LCASE expression: a plain expression can't
# validate its direction argument at all - it would silently build a
# well-formed-looking but wrong Literal, with no diagnostic. Registering a
# real function lets it validate at construction time and raise SPARQLError
# for a bad direction like "sideways" - which rdflib's evaluator (evalExtend,
# for BIND/SELECT-projection expressions) specifically catches and treats as
# "leave the variable unbound for this solution", the same "type error in an
# expression" semantics a real SPARQL 1.2 engine uses (confirmed directly
# against live Fuseki 5.5.0 and Oxigraph 0.5.9 2026-07-16: an invalid
# direction there doesn't abort the query or drop the row, it just leaves
# that one binding's variable missing). A plain ValueError wouldn't get this
# treatment - rdflib's evalExtend only catches SPARQLError specifically, so
# anything else propagates and aborts the *entire* query, discarding every
# other row too - confirmed as a real, avoidable difference from native
# engines, not a defensible one, so this isn't a "fail fast" tradeoff being
# kept deliberately; it's just matching what a real engine already does.
DIRLANG_CONSTRUCT_FN = f"<{DIRLANG_NS_PREFIX}fn/construct>"

# A word boundary before "LANG"/"hasLANG" never matches inside
# "LANGDIR"/"hasLANGDIR"/"STRLANGDIR" (no \b between contiguous letters), so
# these five names are mutually exclusive regardless of scan order - the
# recursive descent below only needs the earliest match among them.
_DIRLANG_FUNC_RES = {
    name: _re.compile(rf'\b{name}\s*(?=\()', _re.IGNORECASE)
    for name in ('STRLANGDIR', 'hasLANGDIR', 'LANGDIR', 'hasLANG', 'LANG')
}


def _register_dirlang_construct_function() -> None:
    from rdflib import URIRef, Literal
    from rdflib.plugins.sparql.operators import register_custom_function
    from rdflib.plugins.sparql.sparql import SPARQLError

    from starlight.model.encoding import encode_dirlang_datatype

    def _dirlang_construct_fn(lex, lang, direction):
        lang_str = str(lang).lower()
        dir_str = str(direction).lower()
        if dir_str not in ('ltr', 'rtl'):
            # SPARQLError specifically (not ValueError): this is what
            # rdflib's evaluator recognizes as a SPARQL expression type
            # error and converts to "unbound", matching native engines -
            # see the module-level comment above DIRLANG_CONSTRUCT_FN.
            raise SPARQLError(f'STRLANGDIR: direction must be "ltr" or "rtl", got {dir_str!r}')
        return Literal(str(lex), datatype=encode_dirlang_datatype(lang_str, dir_str))

    register_custom_function(URIRef(DIRLANG_CONSTRUCT_FN[1:-1]), _dirlang_construct_fn, override=True)


# Same deliberate import-time global-registry mutation as
# _register_tt_hash_function() above, and the same reasoning applies.
_register_dirlang_construct_function()


def _rewrite_dirlang_literals(query: str) -> str:
    """Rewrite RDF 1.2 "text"@lang--dir literal syntax, wherever it appears,
    into a call to the registered dirlang: constructor function.

    A literal written directly in a query (as opposed to a value read from
    already-stored data via a bound variable, which already works correctly)
    is never rewritten anywhere else in this module: LANGDIR()/STRLANGDIR()/
    etc. only touch the *function calls* wrapping their arguments, not the
    lexical form of a literal argument itself. Left alone, "hi"@en--rtl is
    handed to rdflib's SPARQL 1.1 parser as-is, which has no notion of the
    --dir suffix and raises a ParseException on the "--" it doesn't expect.

    Runs early, before anything else, so every later pass only ever sees
    plain SPARQL 1.1-parseable text. Does not (and cannot) fix a "text"@lang--dir
    literal used directly as a graph-pattern term (e.g. `?s :p "hi"@en--rtl .`):
    SPARQL syntax doesn't allow a function call in a term position, so that
    position still needs a bound variable - already supported, just not via
    literal syntax typed directly into a pattern.
    """
    if '--' not in query:
        return query

    lang_dir_re = _re.compile(r'@([A-Za-z]+(?:-[A-Za-z0-9]+)*)--([A-Za-z]+)')
    result: list[str] = []
    i = 0
    n = len(query)
    while i < n:
        if query.startswith('#', i):
            comment_end = query.find('\n', i)
            if comment_end == -1:
                result.append(query[i:])
                break
            result.append(query[i:comment_end + 1])
            i = comment_end + 1
            continue

        if query.startswith('"""', i) or query.startswith("'''", i):
            token, j = _consume_string(query, i, query[i:i + 3])
        elif query[i] in ('"', "'"):
            token, j = _consume_string(query, i, query[i])
        else:
            result.append(query[i])
            i += 1
            continue

        m = lang_dir_re.match(query, j)
        if m:
            lang, direction = m.group(1), m.group(2)
            result.append(f'{DIRLANG_CONSTRUCT_FN}({token}, "{lang}", "{direction}")')
            i = m.end()
        else:
            result.append(token)
            i = j

    return ''.join(result)


def _dirlang_langdir(v: str) -> str:
    return (f'IF(STRSTARTS(STR(DATATYPE({v})), "{DIRLANG_NS_PREFIX}"), '
             f'STRAFTER(STR(DATATYPE({v})), "--"), "")')


def _dirlang_has_langdir(v: str) -> str:
    return f'STRSTARTS(STR(DATATYPE({v})), "{DIRLANG_NS_PREFIX}")'


def _dirlang_lang(v: str) -> str:
    return (f'IF(STRSTARTS(STR(DATATYPE({v})), "{DIRLANG_NS_PREFIX}"), '
             f'STRBEFORE(STRAFTER(STR(DATATYPE({v})), "{DIRLANG_NS_PREFIX}"), "--"), '
             f'LANG({v}))')


def _dirlang_has_lang(v: str) -> str:
    return f'(STRSTARTS(STR(DATATYPE({v})), "{DIRLANG_NS_PREFIX}") || (LANG({v}) != ""))'


_DIRLANG_UNARY_TEMPLATES = {
    'LANGDIR':     _dirlang_langdir,
    'hasLANGDIR':  _dirlang_has_langdir,
    'LANG':        _dirlang_lang,
    'hasLANG':     _dirlang_has_lang,
}


def _rewrite_dirlang_and_strlangdir(query: str) -> str:
    """Rewrite LANGDIR/hasLANGDIR/LANG/hasLANG/STRLANGDIR (SPARQL 1.2 Query
    sec 17.4.2) against the internal dirlang: datatype-URI encoding.

    Recursive descent (like _rewrite_triple_calls): each call's argument(s)
    are rewritten first, so nesting - e.g. ``LANGDIR(STRLANGDIR(...))`` or
    ``hasLANGDIR(IF(..., ?x, ?y))`` - resolves correctly, unlike a plain regex
    substitution which can only match a single bare variable argument.

    LANG()/hasLANG() are rewritten unconditionally whenever present (even in a
    query that never touches a dirLangString) - the rewritten form is a strict
    generalization: its IF-condition is simply false and it falls back to
    plain LANG(v)/"has an ordinary language tag" for every other literal.
    """
    result: list[str] = []
    i = 0
    while True:
        best_match = None
        best_name = None
        for name, pat in _DIRLANG_FUNC_RES.items():
            m = pat.search(query, i)
            if m is not None and (best_match is None or m.start() < best_match.start()):
                best_match = m
                best_name = name
        if best_match is None:
            result.append(query[i:])
            break

        result.append(query[i:best_match.start()])
        call_span, end = _consume_balanced(query, best_match.end(), '(', ')')
        inner = call_span[1:-1]

        if best_name == 'STRLANGDIR':
            args = _split_top_level_args(inner)
            if len(args) != 3:
                raise ValueError(f"STRLANGDIR() requires exactly 3 arguments: {query[best_match.start():end]}")
            lex, lang, direction = (_rewrite_dirlang_and_strlangdir(a) for a in args)
            result.append(f'{DIRLANG_CONSTRUCT_FN}({lex}, {lang}, {direction})')
        else:
            arg = _rewrite_dirlang_and_strlangdir(inner.strip())
            result.append(_DIRLANG_UNARY_TEMPLATES[best_name](arg))

        i = end
    return ''.join(result)

_FUNC_TO_PRED = {
    'SUBJECT':   RDF_SUBJECT,
    'PREDICATE': RDF_PREDICATE,
    'OBJECT':    RDF_OBJECT,
}

# BIND(SUBJECT(?tt) AS ?s)  →  ?tt <rdf:subject> ?s  (in-place, no outer injection)
# $tt/$s are equally valid SPARQL variable syntax (the sigils are interchangeable)
# and are the convention SHACL-SPARQL constraints use for $this/$value.
_BIND_ACCESSOR_RE = _re.compile(
    r'\bBIND\s*\(\s*(SUBJECT|PREDICATE|OBJECT)\s*\(\s*([?$][A-Za-z_]\w*)\s*\)\s+AS\s+([?$][A-Za-z_]\w*)\s*\)',
    _re.IGNORECASE,
)

# A SPARQL term: variable, full IRI, prefixed name, default-prefix name,
# quoted literal (simple), blank node, or rdf:type shorthand 'a'.
_T = (
    r'(?:'
    r'[?$][A-Za-z_]\w*'                                      # variable
    r'|<[^>]+>'                                              # full IRI
    r'|"[^"\\]*(?:\\.[^"\\]*)*"'                             # double-quoted literal
    r"|'[^'\\]*(?:\\.[^'\\]*)*'"                             # single-quoted literal
    r'|[A-Za-z_]\w*:[A-Za-z_]\w*'                           # prefixed name  prefix:local
    r'|:[A-Za-z_]\w*'                                        # default-prefix name  :local
    r'|_:[A-Za-z_]\w*'                                       # blank node
    r'|\ba\b'                                                # rdf:type shorthand
    r'|[+-]?(?:\d+\.?\d*|\d*\.\d+)(?:[eE][+-]?\d+)?'       # numeric literal
    r')'
)

# << s p o ~ reifier >> pred obj  — annotation subject with explicit reifier
_ANN_SUBJECT_TILDE_RE = _re.compile(
    rf'<<\s+({_T})\s+({_T})\s+({_T})\s+~\s+({_T})\s*>>\s+({_T})\s+({_T})',
)

# << s p o >> pred obj  — annotation subject pattern (anonymous reifier)
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
    rf'({_T})\s+({_T})\s+({_T})\s+~\s+([?$][A-Za-z_]\w*)',
)


@dataclass
class _RewriteState:
    next_var_index: int = 0
    _content_cache: dict = field(default_factory=dict, init=False, repr=False)
    generated_vars: set  = field(default_factory=set,  init=False, repr=False)
    pending_binds: list  = field(default_factory=list, init=False, repr=False)
    in_construct_template: bool = field(default=False, init=False, repr=False)
    # BINDs for fully-ground (variable-free) TRIPLE()/<<( )>> values used as a
    # plain expression, not a graph-pattern term - see _rewrite_triple_term.
    # Unlike pending_binds (CONSTRUCT-template minting, relocated to the
    # *end* of the WHERE clause since it depends on that clause's own
    # bindings), these have no dependency on anything else in the query, so
    # they're hoisted to the very *start* of the WHERE clause instead: that's
    # the only placement that's guaranteed to precede every possible use of
    # the variable, including the containing statement itself (e.g.
    # `?stmt rdf:reifies TRIPLE(:a,:b,:c)` needs its BIND before that same
    # triple pattern, not after it).
    pending_ground_binds: list = field(default_factory=list, init=False, repr=False)

    def new_var(self) -> str:
        var_name = f"__tt{self.next_var_index}"
        self.next_var_index += 1
        self.generated_vars.add(var_name)
        return f"?{var_name}"

    def var_for_content(self, content_key: str) -> str:
        if content_key not in self._content_cache:
            self._content_cache[content_key] = self.new_var()
        return self._content_cache[content_key]


_CONSTRUCT_RE = _re.compile(r'\bCONSTRUCT\s*(?=\{)', _re.IGNORECASE)
_WHERE_RE = _re.compile(r'\bWHERE\s*(?=\{)', _re.IGNORECASE)


def _try_split_construct_where(query: str):
    """Split ``... CONSTRUCT { template } WHERE { where } ...`` into
    ``(prologue, template_inner, where_inner, epilogue)``.

    Returns ``None`` for any other query form (SELECT/ASK/DESCRIBE, or a
    CONSTRUCT form this simple two-block split doesn't recognize) so callers
    can fall back to the single-pass rewrite unchanged.
    """
    m = _CONSTRUCT_RE.search(query)
    if not m:
        return None

    try:
        brace_start = query.index('{', m.end())
        template_span, after_template = _consume_balanced(query, brace_start, '{', '}')

        wm = _WHERE_RE.search(query, after_template)
        if not wm or query[after_template:wm.start()].strip():
            return None

        where_brace_start = query.index('{', wm.end())
        where_span, after_where = _consume_balanced(query, where_brace_start, '{', '}')
    except ValueError:
        return None

    prologue = query[:m.start()]
    epilogue = query[after_where:]
    return prologue, template_span[1:-1], where_span[1:-1], epilogue


def _find_group_pattern_start(query: str) -> int | None:
    """Index just after the outermost group graph pattern's opening brace.

    Prefers an explicit ``WHERE {``. Falls back to the first ``{`` in the
    query when the WHERE keyword is absent - it's optional in SPARQL for
    SELECT/ASK/DESCRIBE (e.g. plain ``ASK { ... }``), and neither the
    prologue (BASE/PREFIX) nor a SELECT variable list/dataset clause can
    contain a brace, so the first one is always the group graph pattern's.
    Returns None only if the query has no ``{`` at all.

    Shared by every pass that needs to inject content at the very start of
    the WHERE clause: _inject_ground_binds_into_where (ground TRIPLE()/
    <<( )>> BINDs) and _rewrite_triple_functions (SUBJECT/PREDICATE/OBJECT
    binding triples for a SELECT-projection call). Both used to search for
    literal "WHERE {" text with no fallback, silently dropping their
    injected content on a WHERE-less query - fixed once here rather than
    per call site.
    """
    where_m = _re.search(r'\bWHERE\s*\{', query, _re.IGNORECASE)
    if where_m:
        return where_m.end()
    brace_m = _re.search(r'\{', query)
    return brace_m.end() if brace_m else None


def _inject_ground_binds_into_where(query: str, state: "_RewriteState") -> str:
    """Insert state.pending_ground_binds right after the WHERE clause's own
    opening brace, so they precede everything else in the query - see
    _RewriteState.pending_ground_binds. Used for the SELECT/ASK/DESCRIBE
    path; _rewrite_construct_query handles the CONSTRUCT path itself, since
    it already assembles the WHERE clause text directly.
    """
    if not state.pending_ground_binds:
        return query
    insert_pos = _find_group_pattern_start(query)
    if insert_pos is None:
        state.pending_ground_binds.clear()
        return query
    prefix = "\n  " + "\n  ".join(state.pending_ground_binds) + "\n  "
    state.pending_ground_binds.clear()
    return query[:insert_pos] + prefix + query[insert_pos:]


def _rewrite_construct_query(query: str, state: "_RewriteState") -> str:
    """Rewrite a ``CONSTRUCT { template } WHERE { where }`` query.

    The WHERE clause is rewritten first so that any triple-term content
    already resolvable by matching existing data registers its variable
    before the template is processed. The template is then rewritten with
    ``state.in_construct_template`` set, so any triple-term content that
    appears *only* in the template (never matched in WHERE) gets a computed
    BIND — collected into ``state.pending_binds`` — instead of relying on a
    pre-existing match. Collected BINDs are spliced into the WHERE clause
    (since a CONSTRUCT template cannot itself contain a BIND), appended
    *after* the WHERE clause's own patterns rather than before them: a BIND's
    component variables (e.g. ``?z`` bound only via ordinary WHERE matching,
    not a constant) must already be bound by the time the BIND evaluates, or
    SPARQL silently drops that binding instead of erroring.

    ``state.pending_ground_binds`` (fully-ground TRIPLE()/<<( )>> values used
    as a plain expression - see _rewrite_triple_term) go the *opposite* way:
    prepended *before* the WHERE clause's own content, since they have no
    dependency on it and must be available to everything, including the
    WHERE clause's own patterns.
    """
    split = _try_split_construct_where(query)
    if split is None:
        return _inject_ground_binds_into_where(_rewrite_group_content(query, state), state)

    prologue, template_inner, where_inner, epilogue = split
    rewritten_where = _rewrite_group_content(where_inner, state, handle_funcs=True)
    state.in_construct_template = True
    rewritten_template = _rewrite_group_content(template_inner, state, handle_funcs=True)
    state.in_construct_template = False

    ground_prefix = ""
    if state.pending_ground_binds:
        ground_prefix = "\n  " + "\n  ".join(state.pending_ground_binds) + "\n  "
        state.pending_ground_binds.clear()

    bind_suffix = ""
    if state.pending_binds:
        bind_suffix = "\n  " + "\n  ".join(state.pending_binds) + "\n  "

    return f"{prologue}CONSTRUCT {{{rewritten_template}}} WHERE {{{ground_prefix}{rewritten_where}{bind_suffix}}}{epilogue}"


def _rewrite_triple_calls(query: str) -> str:
    """Rewrite ``TRIPLE(s, p, o)`` constructor calls to ``<<( s p o )>>``.

    Runs before every other pass so the rest of the pipeline only ever has to
    handle one spelling of a triple term - matching, nesting, and CONSTRUCT-
    template minting (``_rewrite_triple_term``) all apply unchanged to the
    result. Arguments are recursively converted first so a nested ``TRIPLE(...)``
    call (or a literal ``<<( )>>`` argument) is fully desugared before being
    wrapped, since the whitespace-splitting in ``_split_top_level_terms``
    treats an unconverted ``TRIPLE(a, b, c)`` argument as one opaque token
    rather than something to recurse into.
    """
    result: list[str] = []
    i = 0
    while True:
        m = _TRIPLE_CALL_RE.search(query, i)
        if not m:
            result.append(query[i:])
            break
        result.append(query[i:m.start()])
        call_span, end = _consume_balanced(query, m.end(), '(', ')')
        args = _split_top_level_args(call_span[1:-1])
        if len(args) != 3:
            raise ValueError(f"TRIPLE() requires exactly 3 arguments: {query[m.start():end]}")
        rewritten_args = [_rewrite_triple_calls(a) for a in args]
        result.append("<<( " + " ".join(rewritten_args) + " )>>")
        i = end
    return ''.join(result)


def _rewrite_triple_accessor_literals(query: str) -> str:
    """Desugar SUBJECT/PREDICATE/OBJECT(<<( s p o )>>) - the accessor applied
    directly to a triple-term literal - to the relevant component (s, p, or
    o) directly.

    This is an exact, pass-order-independent textual equivalence, unlike
    SUBJECT(?tt): a bound-variable argument needs a store lookup (an injected
    ?tt rdf:subject ?fresh binding pattern - see _rewrite_triple_functions /
    _rewrite_group_content's inline handling), but a literal <<( s p o )>>
    argument already spells out all three components right there in the
    query text, so there is nothing to look up - SUBJECT(<<( s p o )>>) means
    exactly s. Runs right after _rewrite_triple_calls (so a TRIPLE(...)-
    spelled argument has already become <<( )>> uniformly) and before every
    other pass, so a component that is itself a nested <<( )>>/TRIPLE(...)
    is left as plain text at this call's former position for the normal
    downstream passes to rewrite - the same as if it had been written
    directly there to begin with. Also means this works identically whether
    the call sits inside a WHERE-clause block or bare in a SELECT projection,
    with no separate "outside any block yet" injection logic needed at all
    (contrast the bare-variable case's _rewrite_triple_functions).

    Found missing via property-based fuzz testing 2026-07-17 - the bare-
    variable-only _TRIPLE_FUNC_RE regex silently failed to match this form,
    reaching rdflib's SPARQL 1.1 parser as literal, unparseable text.
    """
    result: list[str] = []
    i = 0
    while True:
        m = _TRIPLE_ACCESSOR_LITERAL_RE.search(query, i)
        if not m:
            result.append(query[i:])
            break
        result.append(query[i:m.start()])
        paren_start = query.index('(', m.end())
        call_span, end = _consume_balanced(query, paren_start, '(', ')')
        inner = call_span[1:-1].strip()
        tt_token, tt_end = _consume_triple_term(inner, 0)
        if tt_end != len(inner):
            raise ValueError(
                f"{m.group(1).upper()}() applied to a triple-term literal takes exactly "
                f"one <<( )>> argument: {query[m.start():end]}"
            )
        parts = _split_top_level_terms(tt_token[3:-3].strip())
        if len(parts) != 3:
            raise ValueError(f"Triple term must contain exactly 3 terms: {tt_token}")
        idx = _ACCESSOR_TO_INDEX[m.group(1).upper()]
        result.append(_rewrite_triple_accessor_literals(parts[idx]))
        i = end
    return ''.join(result)


def _split_top_level_args(text: str) -> list[str]:
    """Split a ``TRIPLE(...)`` argument list on top-level commas.

    Mirrors ``_split_top_level_terms`` (which splits on whitespace for
    ``<<( )>>`` content) but splits on ``,`` instead, since function-call
    arguments are comma-separated. Strings, IRIs, and nested ``<<( )>>``
    triple terms are treated as atomic; parens/brackets are depth-tracked so
    a comma inside a nested call or list isn't mistaken for an argument
    separator.
    """
    parts: list[str] = []
    current: list[str] = []
    i = 0
    depth = 0

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

        if text[i] in '([':
            depth += 1
        elif text[i] in ')]':
            depth -= 1

        if text[i] == ',' and depth == 0:
            parts.append(''.join(current).strip())
            current.clear()
            i += 1
            continue

        current.append(text[i])
        i += 1

    if current:
        parts.append(''.join(current).strip())
    return [part for part in parts if part]


def _rewrite_sparql12_to_11_tracked(query: str) -> tuple[str, frozenset]:
    """Internal rewriter that also returns the set of generated variable names.

    Returns ``(rewritten_query, generated_tt_vars)`` where ``generated_tt_vars``
    is a ``frozenset[str]`` of rdflib ``Variable`` name strings (without ``?``)
    that were generated by this call, e.g. ``frozenset({'__tt0', '__tt1'})``.
    Callers that only need the string should use ``rewrite_sparql12_to_11``.
    """
    query = _rewrite_dirlang_literals(query)

    if _TRIPLE_CALL_RE.search(query):
        query = _rewrite_triple_calls(query)

    if _TRIPLE_ACCESSOR_LITERAL_RE.search(query):
        # Must run after _rewrite_triple_calls (so a TRIPLE(...)-spelled
        # argument is already <<( )>> by now) and before needs_tt/needs_func
        # are computed below, so those flags reflect what's actually left in
        # the query rather than a SUBJECT(<<( )>>) call this pass already
        # resolved away.
        query = _rewrite_triple_accessor_literals(query)

    if 'LANG' in query.upper():
        query = _rewrite_dirlang_and_strlangdir(query)

    needs_tt   = "<<(" in query
    needs_ann  = _re.search(r'<<[^(]|\{\|', query) is not None or '~' in query
    needs_func = _TRIPLE_FUNC_RE.search(query) is not None
    needs_istt = _IS_TT_RE.search(query) is not None

    if not (needs_tt or needs_ann or needs_func or needs_istt):
        return query, frozenset()

    state = _RewriteState()

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
        query = _rewrite_construct_query(query, state)

    # After inline handling, any remaining SUBJECT/PREDICATE/OBJECT calls live
    # outside {…} blocks (SELECT projections, HAVING, ORDER BY).  Inject their
    # binding triples at the WHERE level — correct for those clause positions.
    if needs_func and _TRIPLE_FUNC_RE.search(query):
        query = _rewrite_triple_functions(query, state)

    if _IS_TT_RE.search(query):
        # Runs last, after <<( )>>/TRIPLE(...) have already been reduced to
        # plain variables by the passes above - isTRIPLE's argument must be a
        # bare variable for this regex to match (isTRIPLE(?x)), and a nested
        # triple-term expression like isTRIPLE(TRIPLE(...)) only becomes that
        # shape once the inner call has been desugared and its component
        # triples correctly placed inside the WHERE clause. Running this
        # earlier would either miss the nested case entirely or - worse -
        # leave a literal "isTRIPLE(...)" in the output after the inner
        # <<( )>> is separately rewritten to a variable, which the SPARQL 1.1
        # engine doesn't recognize as a function at all.
        #
        # Deliberately re-searching here rather than trusting the
        # early-computed needs_istt: that flag reflects the *pre-rewrite*
        # text, where a nested-expression argument doesn't match this regex
        # yet, so it can be False here even when this block needs to run -
        # needs_istt still matters for the early bail-out check above (a
        # query where isTRIPLE(?x) - bare variable - is the *only* SPARQL 1.2
        # construct present).
        #
        # STRSTARTS alone is sufficient and correct: every TT_NS-prefixed
        # URIRef is created exclusively by _intern_tt() (or its addN/parser
        # equivalents), which always writes the rdf:subject/predicate/object
        # encoding triples in the same call before returning the URI - so
        # there is no state where such a URI exists without them. Every other
        # TT_NS membership check in this codebase (_is_encoding_triple,
        # _restore, _build_registry_from_store) already relies on the prefix
        # alone with no separate existence check, so this matches established
        # invariants, not a new assumption.
        #
        # This used to also wrap an `EXISTS { ?x rdf:subject [] } &&` guard,
        # which is unnecessary per the above - and actively wrong to keep: it
        # hits a genuine rdflib limitation (confirmed independently of this
        # codebase, with a bare rdflib.Graph()) where `EXISTS {...} && ...`
        # raises deep inside the evaluator ("What do I do with this
        # CompValue?") when used in a `(expr AS ?var)` position (SELECT
        # projection or BIND), while the identical expression works fine
        # inside FILTER(...). Every prior isTripleTerm()/isTRIPLE() test only
        # ever used it inside FILTER, so this was never triggered before.
        query = _IS_TT_RE.sub(
            lambda m: f'STRSTARTS(STR({m.group(1)}), "{TT_NS_PREFIX}")',
            query,
        )

    return query, frozenset(state.generated_vars)


def rewrite_sparql12_to_11(query: str) -> str:
    """Rewrite SPARQL 1.2 triple-term syntax to SPARQL 1.1.

    Handles:
    - ``<<( s p o )>>`` triple-term patterns in WHERE clauses
    - ``<< s p o >> pred obj`` annotation subject patterns (anonymous reifier)
    - ``<< s p o ~ reifier >> pred obj`` annotation subject with explicit reifier
    - ``s p o {| ap av ; ... |}`` inline annotation blocks
    - ``s p o ~?r`` reifier-binding shorthand
    - ``SUBJECT(?tt)``, ``PREDICATE(?tt)``, ``OBJECT(?tt)`` function calls
    - ``isTripleTerm(?x)`` filter function, and its spec-name alias ``isTRIPLE(?x)``
    - ``TRIPLE(s, p, o)`` constructor function - the spec's function-call form of
      ``<<( s p o )>>``; desugared to it before any other rewriting runs
    - ``LANGDIR(?x)``, ``hasLANGDIR(?x)``, ``STRLANGDIR(lex, lang, dir)`` - RDF 1.2
      base-direction functions (SPARQL 1.2 Query sec 17.4.2), evaluated against
      the internal dirlang: datatype-URI encoding of a DirLangString
    - ``LANG(?x)`` and ``hasLANG(?x)`` are upgraded so both also recognize a
      DirLangString the same way they already handle a plain rdf:langString

    Queries with none of these forms are returned unchanged.
    """
    return _rewrite_sparql12_to_11_tracked(query)[0]


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
    # Pass 1: << s p o ~ reifier >> pred obj  — explicit reifier in subject
    # Must run before _TILDE_RE so the bare `s p o ~?r` pattern doesn't consume
    # the tilde that belongs inside << >>.
    def _ann_subject_tilde(m: _re.Match) -> str:
        s, p, o = m.group(1), m.group(2), m.group(3)
        reifier, pred, obj = m.group(4), m.group(5), m.group(6)
        tt_var = state.new_var()
        parts = [f"{tt_var} {RDF_SUBJECT} {s}",
                 f"{tt_var} {RDF_PREDICATE} {p}",
                 f"{tt_var} {RDF_OBJECT} {o}",
                 f"{reifier} {RDF_REIFIES} {tt_var}",
                 f"{reifier} {pred} {obj}"]
        return " .\n  ".join(parts)

    query = _ANN_SUBJECT_TILDE_RE.sub(_ann_subject_tilde, query)

    # Pass 2: << s p o >> pred obj  — anonymous reifier in subject
    # No base-triple assertion. Component patterns still go before reification.
    def _ann_subject(m: _re.Match) -> str:
        s, p, o = m.group(1), m.group(2), m.group(3)
        pred, obj = m.group(4), m.group(5)
        r_var = state.new_var()
        tt_var = state.new_var()
        parts = [f"{tt_var} {RDF_SUBJECT} {s}",
                 f"{tt_var} {RDF_PREDICATE} {p}",
                 f"{tt_var} {RDF_OBJECT} {o}",
                 f"{r_var} {RDF_REIFIES} {tt_var}",
                 f"{r_var} {pred} {obj}"]
        return " .\n  ".join(parts)

    query = _ANN_SUBJECT_RE.sub(_ann_subject, query)

    # Pass 3: s p o ~?r
    # Component patterns first (bind ?__tt via the selective rdf:subject index),
    # then find reifiers, then validate the base-triple assertion last.
    # Putting s p o last avoids a full triple-scan when s/p/o are variables.
    # Runs after << >> forms are consumed so ~ inside << >> isn't matched here.
    def _tilde(m: _re.Match) -> str:
        s, p, o, r = m.group(1), m.group(2), m.group(3), m.group(4)
        tt_var = state.new_var()
        return (f"{tt_var} {RDF_SUBJECT} {s} .\n  "
                f"{tt_var} {RDF_PREDICATE} {p} .\n  "
                f"{tt_var} {RDF_OBJECT} {o} .\n  "
                f"{r} {RDF_REIFIES} {tt_var} .\n  "
                f"{s} {p} {o}")

    query = _TILDE_RE.sub(_tilde, query)

    # Pass 4: s p o {| ap av ; ... |}
    # Same strategy: triple term components → reification → annotation properties
    # → assertion check last. Any <<( )>> in annotation values are left for Phase 2.
    def _ann_block(m: _re.Match) -> str:
        s, p, o = m.group(1), m.group(2), m.group(3)
        pairs = [pair.strip() for pair in m.group(4).split(';') if pair.strip()]
        r_var = state.new_var()
        tt_var = state.new_var()
        parts = [f"{tt_var} {RDF_SUBJECT} {s}",
                 f"{tt_var} {RDF_PREDICATE} {p}",
                 f"{tt_var} {RDF_OBJECT} {o}",
                 f"{r_var} {RDF_REIFIES} {tt_var}"]
        parts.extend(f"{r_var} {pair}" for pair in pairs)
        parts.append(f"{s} {p} {o}")
        return " .\n  ".join(parts)

    query = _ANN_BLOCK_RE.sub(_ann_block, query)

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
        insert_pos = _find_group_pattern_start(result)
        if insert_pos is not None:
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
            replacement, patterns, i, _is_ground = _rewrite_triple_term(text, i, state)
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
            inner_content = inner[1:-1]
            if pending_patterns:
                # A <<( )>> (or a TRIPLE(...) desugared to one) appeared before
                # any {} block at all - e.g. in a bare SELECT projection with
                # no BIND, ahead of the WHERE clause. There is nowhere upstream
                # of this point to put its matching pattern (SPARQL has no
                # constraint syntax outside a graph pattern block), so it must
                # go inside the first block encountered, which for a
                # SELECT/ASK/DESCRIBE query is the WHERE clause itself.
                # Leaving it to fall through to the end-of-string flush below
                # would land it after the query's closing brace - invalid syntax.
                inner_content = _emit_pending_patterns(pending_patterns) + inner_content
                pending_patterns.clear()
            rewritten = _rewrite_group_content(inner_content, state, handle_funcs=True)
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


def _rewrite_triple_term(
    text: str, start: int, state: _RewriteState
) -> tuple[str, list[str], int, bool]:
    """Rewrite one <<( s p o )>> occurrence. Returns (tt_var, patterns, end,
    is_ground) where is_ground is True iff s, p, and o are all variable-free
    (recursively, for a nested triple term) - see the "elif all_ground"
    branch below for what that unlocks.
    """
    token, end = _consume_triple_term(text, start)
    inner = token[3:-3].strip()
    parts = _split_top_level_terms(inner)
    if len(parts) != 3:
        raise ValueError(f"Triple term must contain exactly 3 terms: {token}")

    subject_token, subject_patterns, subject_ground = _rewrite_term(parts[0], state)
    predicate_token, predicate_patterns, predicate_ground = _rewrite_term(parts[1], state)
    object_token, object_patterns, object_ground = _rewrite_term(parts[2], state)
    all_ground = subject_ground and predicate_ground and object_ground

    content_key = f"{subject_token} {predicate_token} {object_token}"
    is_new = content_key not in state._content_cache
    tt_var = state.var_for_content(content_key)

    patterns = []
    patterns.extend(subject_patterns)
    patterns.extend(predicate_patterns)
    patterns.extend(object_patterns)

    if state.in_construct_template:
        if is_new:
            # No WHERE-clause occurrence of this triple term exists to bind
            # tt_var from — mint it deterministically instead of requiring it
            # to already be registered in the graph. Collected separately
            # since a CONSTRUCT template cannot itself contain a BIND; the
            # caller relocates these into the WHERE clause.
            state.pending_binds.append(
                f"BIND({TT_HASH_FN}({subject_token}, {predicate_token}, {object_token}) AS {tt_var})"
            )
        # The constructed *output* graph needs its own encoding triples for
        # this value regardless of is_new (harmless if repeated - CONSTRUCT
        # naturally deduplicates identical output triples).
        patterns.append(f"{tt_var} {RDF_SUBJECT} {subject_token} .")
        patterns.append(f"{tt_var} {RDF_PREDICATE} {predicate_token} .")
        patterns.append(f"{tt_var} {RDF_OBJECT} {object_token} .")
    elif all_ground:
        # Fully ground (no variables anywhere, recursively): this is a value,
        # like a literal IRI, not a lookup - it must always construct
        # successfully regardless of whether it was ever written to the
        # graph, and must never have the side effect of writing anything (a
        # read-only SELECT/ASK/FILTER must stay read-only). Routed to
        # state.pending_ground_binds (hoisted to the top of the WHERE clause
        # by the caller) rather than appended to `patterns` here: unlike the
        # rdf:subject/predicate/object matching patterns in the branches
        # below - which are order-independent, just another triple pattern
        # joined into the same basic graph pattern - a BIND is evaluated in
        # sequence and must textually precede anything that reads tt_var,
        # which this function's local "defer to the next '.' or '}'"
        # placement can't guarantee: e.g. for
        # `?stmt rdf:reifies TRIPLE(:a,:b,:c)`, tt_var is read by the very
        # statement being rewritten, immediately at this position.
        if is_new:
            state.pending_ground_binds.append(
                f"BIND({TT_HASH_FN}({subject_token}, {predicate_token}, {object_token}) AS {tt_var}) ."
            )
    else:
        patterns.append(f"{tt_var} {RDF_SUBJECT} {subject_token} .")
        patterns.append(f"{tt_var} {RDF_PREDICATE} {predicate_token} .")
        patterns.append(f"{tt_var} {RDF_OBJECT} {object_token} .")

    return tt_var, patterns, end, all_ground


def _rewrite_term(term: str, state: _RewriteState) -> tuple[str, list[str], bool]:
    stripped = term.strip()
    if stripped.startswith("<<("):
        replacement, patterns, _, is_ground = _rewrite_triple_term(stripped, 0, state)
        return replacement, patterns, is_ground
    is_ground = not (stripped.startswith('?') or stripped.startswith('$'))
    return stripped, [], is_ground


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