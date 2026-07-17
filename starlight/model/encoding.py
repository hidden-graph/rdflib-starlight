"""
starlight.model.encoding

Shared constants and hash function for the starlight internal graph encoding.

Triple terms    → content-addressed URIRefs under TT_NS (same content = same URI)
Anon reifiers   → sequential URIRefs under RR_NS (each {| |} block is distinct)
DirLangString   → a Literal whose datatype URI under DIRLANG_NS packs the real
                  language tag and base direction (see decode_dirlang_datatype)
"""

import hashlib
from collections import OrderedDict

from rdflib import URIRef
from rdflib.namespace import RDF

TT_NS      = 'https://github.com/hidden-graph/rdflib-starlight/ns/tt#'       # triple-term content-addressed URIs
RR_NS      = 'https://github.com/hidden-graph/rdflib-starlight/ns/rr#'       # anonymous reifier URIs
DIRLANG_NS = 'https://github.com/hidden-graph/rdflib-starlight/ns/dirlang#'  # dirLangString datatype encoding

# Predicates used in the internal TripleTerm URIRef encoding - shared by
# StarlightGraph and StarlightDataset's _is_encoding_triple() checks and by
# restore_select_bindings() below.
ENCODING_PREDS = frozenset({RDF.subject, RDF.predicate, RDF.object})


def tt_hash(s_str: str, p_str: str, o_str: str) -> str:
    """Return a 16-hex-char content-addressed ID for a triple term.

    Inputs are the canonical string representations of the resolved nodes
    (full URIs, bnode IDs, or literal N3 strings).  Nested triple terms
    contribute their full TT_NS URI as the s/o string, so nesting is
    reflected in the hash.

    16 hex chars = 64 bits, keeping birthday-bound collision risk negligible
    even for graphs with heavy reification (an 8-char/32-bit prefix becomes
    non-negligible around ~65,000 distinct triple terms in one process - a
    plausible count for this library's primary use case). Safe to change
    without a migration story: the hash is recomputed fresh from content on
    every intern, never persisted as a stable external identifier - every
    RDF 1.2 serializer emits <<( )>> syntax, never a raw tt:HASH URI.
    """
    return hashlib.sha256(
        f'{s_str}\x00{p_str}\x00{o_str}'.encode()
    ).hexdigest()[:16]


# Process-wide memo: tt:HASH URIRef -> (s, p, o) components, populated by the
# registered TT_HASH_FN SPARQL function (starlight.query.sparql12_to_11)
# whenever it computes a hash for a fully-ground TRIPLE()/<<( )>> value used
# as a plain expression (SELECT projection, BIND, FILTER) rather than a
# graph-pattern term - a value that, like a literal IRI, is constructed on
# the spot and never needs to have been written to any graph. Since it was
# never written, no StarlightGraph's own _tt_nodes registry has it, so
# StarlightGraph._restore() falls back to this memo to still reconstruct a
# proper TripleTerm instead of leaking the raw internal URIRef to the caller.
#
# Sharing this across every graph and query in the process is correct, not a
# leak: tt_hash is a pure, deterministic function of (s, p, o), so what a
# given hash "means" doesn't depend on which graph is asking - the same
# (s, p, o) always hashes to the same URI everywhere, and a graph that has
# never seen that URI still means the same thing by it as one that has.
#
# Bounded LRU rather than a plain dict, though: correctness of *what a hash
# means* doesn't bound how much memory remembering every hash ever computed
# costs. A long-running process issuing many distinct ground TRIPLE()/
# <<( )>> queries would otherwise grow this dict forever. Capped size with
# oldest-first eviction trades "a very old, likely-no-longer-relevant ground
# value might need re-computing/re-remembering via TT_HASH_FN if looked up
# again" for bounded memory - re-computation is just re-running the pure
# hash function, so eviction has no correctness cost, only a cache-miss cost.
_TT_HASH_MEMO_MAXSIZE = 100_000
_TT_HASH_MEMO: OrderedDict = OrderedDict()


def remember_tt_hash(uri: URIRef, s, p, o) -> None:
    """Record that *uri* is the content-addressed hash of triple term (s, p, o)."""
    _TT_HASH_MEMO[uri] = (s, p, o)
    _TT_HASH_MEMO.move_to_end(uri)
    if len(_TT_HASH_MEMO) > _TT_HASH_MEMO_MAXSIZE:
        _TT_HASH_MEMO.popitem(last=False)


def lookup_tt_hash(uri: URIRef):
    """Return the (s, p, o) remembered for *uri* via remember_tt_hash(), or None."""
    value = _TT_HASH_MEMO.get(uri)
    if value is not None:
        _TT_HASH_MEMO.move_to_end(uri)
    return value


def encode_dirlang_datatype(language: str, direction: str) -> URIRef:
    """Return the internal datatype URIRef encoding (language, direction).

    rdflib.Literal(text, lang="en--rtl") raises ValueError - rdflib's langtag
    validator (_is_valid_langtag) has no notion of the RDF 1.2 "--dir" suffix
    and rejects it outright. Validation only fires for the lang= keyword, not
    datatype=, so packing (language, direction) into a synthetic datatype URI
    sidesteps the check entirely while staying self-describing: the URI's
    local name is exactly the real "lang--dir" lexical suffix (RDF 1.2
    Concepts sec 3.4), so decoding is a plain string split, no lookup table.
    """
    return URIRef(f'{DIRLANG_NS}{language}--{direction}')


def decode_dirlang_datatype(datatype) -> tuple[str, str] | None:
    """Return (language, direction) if datatype is a starlight dirlang encoding.

    Returns None for any other datatype (including plain rdf:langString, which
    never reaches here since it's represented via Literal's native lang=).
    """
    s = str(datatype)
    if not s.startswith(DIRLANG_NS):
        return None
    suffix = s[len(DIRLANG_NS):]
    language, sep, direction = suffix.rpartition('--')
    if not sep:
        return None
    return language, direction


def restore_select_bindings(r, restore_fn) -> None:
    """Post-process a SPARQL SELECT rdflib.query.Result in place: drop rows
    that are purely internal encoding infrastructure, and restore any
    tt:HASH URIRef/dirlang: Literal in the surviving rows to its public
    TripleTerm/DirLangString form via restore_fn.

    Shared by StarlightGraph.query() (restore_fn=self._restore, which looks
    up a single graph's own registry) and StarlightDataset.query()
    (restore_fn=self._restore_any, which searches every cached graph's
    registry) - the row-filtering and restoration shape is identical between
    the two; only how a tt:HASH URIRef gets resolved back to a TripleTerm
    differs, which is exactly what restore_fn parameterizes.

    A row is dropped when it contains both a TT_NS-prefixed URIRef and one of
    the rdf:subject/predicate/object encoding predicates as *values* - such a
    row exists only because a query pattern incidentally matched the raw
    encoding triples (e.g. an unconstrained ``?s ?p ?o``), not because the
    user asked about them.
    """
    r.bindings = [
        {var: restore_fn(row.get(var)) if row.get(var) is not None else None
         for var in r.vars}
        for row in r.bindings
        if not (any(isinstance(v, URIRef) and str(v).startswith(TT_NS)
                    for v in row.values())
                and ENCODING_PREDS.intersection(row.values()))
    ]
