"""
starlight.model.encoding

Shared constants and hash function for the starlight internal graph encoding.

Triple terms  → content-addressed URIRefs under TT_NS (same content = same URI)
Anon reifiers → sequential URIRefs under RR_NS (each {| |} block is distinct)
"""

import hashlib

TT_NS = 'https://github.com/hidden-graph/rdflib-starlight/ns/tt#'   # triple-term content-addressed URIs
RR_NS = 'https://github.com/hidden-graph/rdflib-starlight/ns/rr#'   # anonymous reifier URIs


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
