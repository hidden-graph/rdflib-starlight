"""
tests.test_ttl_parser

Test that starlight's Turtle parser produces the same triples as rdflib's parser.
"""

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../starlight')))

#from rdflib import Graph as RDFLibGraph
from starlight.parsers.ttl_parser import StarlightTurtleParser
#from starlight.model.triple import Triple

def test_ttl_equivalence():
    sample_path = os.path.join(os.path.dirname(__file__), '../samples/simple.ttl')
    with open(sample_path, 'r') as f:
        ttl_data = f.read()

    starlight_parser = StarlightTurtleParser()
    starlight_triples = starlight_parser.parse(ttl_data)

    from rdflib import Graph as RDFLibGraph
    g = RDFLibGraph()
    g.parse(data=ttl_data, format="turtle")
    rdflib_triples = set((s, p, o) for s, p, o in g.triples((None, None, None)))

    starlight_set = set(t.as_tuple() for t in starlight_triples)
    assert starlight_set == rdflib_triples, f"Mismatch: {starlight_set} != {rdflib_triples}"
    print("Starlight and rdflib triples are equivalent.")

if __name__ == "__main__":
    test_ttl_equivalence()
