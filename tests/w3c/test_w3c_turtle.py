"""
W3C Turtle 1.2 conformance tests.

Parametrized over w3c_turtle_tests/manifest.csv. For each test case:
  1. Parse the .ttl input with StarlightTurtleParser.
  2. Build the expected graph from the .nt file using parse_nt12(), which
     expands the RDF 1.2 <<( )>> triple-term notation into the same
     starlight internal blank-node encoding the parser produces.
  3. Assert graph isomorphism (handles blank-node renaming automatically).
"""

import csv
import pathlib
import pytest
from rdflib import Graph, URIRef, BNode, Literal
from rdflib.namespace import RDF
from rdflib.compare import isomorphic

RDF_REIFIES = URIRef('http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies')

from starlight.parsers.turtle_parser import StarlightTurtleParser, SL_NS
from starlight.parsers.lexer import next_token

W3C_DIR  = pathlib.Path(__file__).parent.parent.parent / 'w3c_turtle_tests'
MANIFEST = W3C_DIR / 'manifest.csv'

SL_TRIPLE_TERM = URIRef(SL_NS + 'TripleTerm')
SL_REIFICATION = URIRef(SL_NS + 'Reification')


# ---------------------------------------------------------------------------
# NT 1.2 reader — converts expected .nt files into the starlight encoding
# ---------------------------------------------------------------------------

def parse_nt12(text):
    """Parse N-Triples 1.2 text into an rdflib.Graph using the starlight
    internal encoding for <<( s p o )>> triple terms.

    Blank-node labels within a single file are de-duplicated: the same label
    always maps to the same BNode instance, so the resulting graph is suitable
    for isomorphism comparison with the parser's output.
    """
    g = Graph()
    bnode_map = {}
    tt_cache  = {}

    def get_bnode(label):
        if label not in bnode_map:
            bnode_map[label] = BNode()
        return bnode_map[label]

    def resolve_token(tok):
        tok = tok.strip()
        if tok.startswith('<') and tok.endswith('>'):
            return URIRef(tok[1:-1])
        if tok.startswith('_:'):
            return get_bnode(tok[2:])
        if tok.startswith(('"', "'")):
            if '^^' in tok:
                lit, dtype = tok.rsplit('^^', 1)
                return Literal(lit.strip('"').strip("'"),
                               datatype=URIRef(dtype.strip().strip('<>')))
            if tok.count('@') > 0 and not tok.endswith(('"', "'")):
                at = tok.rfind('@')
                return Literal(tok[1:at-1], lang=tok[at+1:])
            return Literal(tok.strip('"').strip("'"))
        return Literal(tok)

    def expand_triple_term(tok):
        """Expand <<( s p o )>> into a starlight TripleTerm bnode. Handles nesting."""
        inner = tok[3:-3].strip()
        s_tok, rest  = next_token(inner)
        p_tok, rest2 = next_token(rest)
        o_tok, _     = next_token(rest2)
        s = resolve_token(s_tok)
        p = resolve_token(p_tok)
        o = expand_triple_term(o_tok) if o_tok.startswith('<<(') else resolve_token(o_tok)
        key = (s, p, o)
        if key in tt_cache:
            return tt_cache[key]
        bn = BNode()
        g.add((bn, RDF.type,      SL_TRIPLE_TERM))
        g.add((bn, RDF.subject,   s))
        g.add((bn, RDF.predicate, p))
        g.add((bn, RDF.object,    o))
        tt_cache[key] = bn
        return bn

    reification_subjects = set()

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.endswith('.'):
            line = line[:-1].rstrip()

        tokens = []
        rest = line.strip()
        while rest:
            tok, rest = next_token(rest)
            if tok:
                tokens.append(tok)
            else:
                break

        # Typed literals tokenize as "value" + "^^" + "<dtype>" — merge back
        if len(tokens) > 3:
            tokens = [tokens[0], tokens[1], ''.join(tokens[2:])]

        if len(tokens) != 3:
            continue

        s_tok, p_tok, o_tok = tokens
        s = resolve_token(s_tok)
        p = resolve_token(p_tok)
        o = expand_triple_term(o_tok) if o_tok.startswith('<<(') else resolve_token(o_tok)

        g.add((s, p, o))

        if p == RDF_REIFIES:
            reification_subjects.add(s)

    for subj in reification_subjects:
        g.add((subj, RDF.type, SL_REIFICATION))

    return g


# ---------------------------------------------------------------------------
# Test parametrization
# ---------------------------------------------------------------------------

def _load_manifest():
    cases = []
    with open(MANIFEST, newline='') as f:
        for row in csv.DictReader(f):
            name     = row['test_name']
            ttl_file = W3C_DIR / row['ttl_file']
            nt_file  = W3C_DIR / row['nt_file']
            if ttl_file.exists() and nt_file.exists():
                cases.append(pytest.param(name, ttl_file, nt_file, id=name))
    return cases


@pytest.mark.parametrize('name,ttl_file,nt_file', _load_manifest())
def test_w3c_turtle(name, ttl_file, nt_file, parser):
    result   = parser.parse(ttl_file.read_text())
    expected = parse_nt12(nt_file.read_text())
    assert isomorphic(result, expected), (
        f"\n{name}: graph mismatch"
        f"\n\nPARSED ({len(result)} triples):\n"
        + '\n'.join(f'  {s!r} {p!r} {o!r}' for s, p, o in sorted(result, key=str))
        + f"\n\nEXPECTED ({len(expected)} triples):\n"
        + '\n'.join(f'  {s!r} {p!r} {o!r}' for s, p, o in sorted(expected, key=str))
    )
