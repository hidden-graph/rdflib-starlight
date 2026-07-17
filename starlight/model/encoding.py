"""
starlight.model.encoding

Shared constants and hash function for the starlight internal graph encoding.

Triple terms    → content-addressed URIRefs under TT_NS (same content = same URI)
Anon reifiers   → sequential URIRefs under RR_NS (each {| |} block is distinct)
DirLangString   → a Literal whose datatype URI under DIRLANG_NS packs the real
                  language tag and base direction (see decode_dirlang_datatype)
"""

import hashlib

from rdflib import URIRef

TT_NS      = 'https://github.com/hidden-graph/rdflib-starlight/ns/tt#'       # triple-term content-addressed URIs
RR_NS      = 'https://github.com/hidden-graph/rdflib-starlight/ns/rr#'       # anonymous reifier URIs
DIRLANG_NS = 'https://github.com/hidden-graph/rdflib-starlight/ns/dirlang#'  # dirLangString datatype encoding


def tt_hash(s_str: str, p_str: str, o_str: str) -> str:
    """Return an 8-hex-char content-addressed ID for a triple term.

    Inputs are the canonical string representations of the resolved nodes
    (full URIs, bnode IDs, or literal N3 strings).  Nested triple terms
    contribute their full TT_NS URI as the s/o string, so nesting is
    reflected in the hash.
    """
    return hashlib.sha256(
        f'{s_str}\x00{p_str}\x00{o_str}'.encode()
    ).hexdigest()[:8]


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
_TT_HASH_MEMO: dict = {}


def remember_tt_hash(uri: URIRef, s, p, o) -> None:
    """Record that *uri* is the content-addressed hash of triple term (s, p, o)."""
    _TT_HASH_MEMO[uri] = (s, p, o)


def lookup_tt_hash(uri: URIRef):
    """Return the (s, p, o) remembered for *uri* via remember_tt_hash(), or None."""
    return _TT_HASH_MEMO.get(uri)


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
