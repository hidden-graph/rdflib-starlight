import json

from rdflib import Graph, URIRef, BNode, Literal, Namespace
from rdflib.namespace import RDF, RDFS, XSD
import re
from rdflib.compare import isomorphic


# Load complex.json
with open('complex.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# Write pretty-printed JSON for user review
with open('complex_pretty.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
print("Wrote pretty-printed JSON to complex_pretty.json")

g = Graph()

# Collect prefixes and base
prefix_map = {}
base_uri = None
bnode_map = {}

# First pass: collect prefixes and base
for entry in data:
    if entry.get('type') == 'prefix':
        prefix_map[entry['prefix']] = entry['iri']
        g.bind(entry['prefix'], entry['iri'])
    elif entry.get('type') == 'base':
        base_uri = entry['iri']

# Helper to resolve IRIs and prefixed names
def resolve_iri(val):
    val = val.strip()
    if val.startswith('<') and val.endswith('>'):
        return URIRef(val[1:-1])
    elif ':' in val and not val.startswith('http'):
        pref, local = val.split(':', 1)
        if pref in prefix_map:
            return URIRef(prefix_map[pref] + local)
        # fallback to rdflib namespaces
        if pref == 'rdf':
            return getattr(RDF, local)
        if pref == 'rdfs':
            return getattr(RDFS, local)
        if pref == 'xsd':
            return getattr(XSD, local)
        return URIRef(val)
    elif val.startswith('_:'):
        # Use a consistent BNode for each label
        if val not in bnode_map:
            bnode_map[val] = BNode(val[2:])
        return bnode_map[val]
    elif val.startswith('_b'):
        # For expanded blank nodes
        if val not in bnode_map:
            bnode_map[val] = BNode(val)
        return bnode_map[val]
    elif base_uri:
        return URIRef(base_uri + val)
    else:
        return URIRef(val)

# Helper to parse literals (with datatype/lang)
def parse_literal(val):
    val = val.strip()
    # Language tag
    m = re.match(r'^"(.*)"@(\w[\w-]*)$', val)
    if m:
        return Literal(m.group(1), lang=m.group(2))
    # Datatype
    m = re.match(r'^"(.*)"\^\^(.+)$', val)
    if m:
        dt = m.group(2)
        if dt.startswith('<') and dt.endswith('>'):
            dt_uri = URIRef(dt[1:-1])
        else:
            dt_uri = resolve_iri(dt)
        return Literal(m.group(1), datatype=dt_uri)
    # Quoted string
    if val.startswith('"') and val.endswith('"'):
        return Literal(val[1:-1])
    # Boolean
    if val == 'true':
        return Literal(True, datatype=XSD.boolean)
    if val == 'false':
        return Literal(False, datatype=XSD.boolean)
    # Integer
    if re.match(r'^-?\d+$', val):
        return Literal(int(val), datatype=XSD.integer)
    # Decimal/float
    if re.match(r'^-?\d*\.\d+(e[+-]?\d+)?$', val, re.I):
        return Literal(float(val), datatype=XSD.decimal)
    # Fallback
    return Literal(val)

# Second pass: add triples
for entry in data:
    if entry.get('type') != 'triple':
        continue
    for triple in entry['triple_set']:
        s = triple['subject']
        p = triple['predicate']
        o = triple['object']
        # Subject
        s_node = resolve_iri(s)
        # Predicate
        if p.startswith('rdf:'):
            p_node = getattr(RDF, p.split(':',1)[1])
        else:
            p_node = resolve_iri(p)
        # Object
        if isinstance(o, str):
            if o.startswith('_:') or o.startswith('_b'):
                o_node = resolve_iri(o)
            elif o == 'rdf:nil':
                o_node = RDF.nil
            elif o.startswith('<') and o.endswith('>'):
                o_node = resolve_iri(o)
            elif o.startswith('"'):
                o_node = parse_literal(o)
            elif ':' in o:
                o_node = resolve_iri(o)
            else:
                o_node = parse_literal(o)
        else:
            o_node = o
        g.add((s_node, p_node, o_node))

# Serialize and print triple count
g.serialize(destination='complex_output.ttl', format='turtle')
print(f"Wrote complex_output.ttl with {len(list(g.triples((None,None,None))))} triples.")

# Optional: compare with rdflib parse of the original Turtle file
from rdflib import Graph as RDFGraph
rdflib_graph = RDFGraph()
with open('samples/complex.ttl', 'r', encoding='utf-8') as f:
    ttl_data = f.read()
rdflib_graph.parse(data=ttl_data, format='turtle')

if isomorphic(g, rdflib_graph):
    print("SUCCESS: JSON-based and rdflib graphs are isomorphic (semantically equivalent, ignoring blank node IDs).")
else:
    print("ERROR: Graphs are not isomorphic (not semantically equivalent).")
