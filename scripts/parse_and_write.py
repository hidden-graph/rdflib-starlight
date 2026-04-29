"""
Script to parse samples/simple.ttl using StarlightTurtleParser and write the triples to samples/output.ttl in Turtle format.
"""
import os


from starlight.parsers.ttl_parser import StarlightTurtleParser



# Use test.ttl as input and output to test_output.ttl
sample_path = os.path.join(os.path.dirname(__file__), '../samples/ttl 1.2.ttl')
output_path = os.path.join(os.path.dirname(__file__), '../samples/test_output.ttl')
json_output_path = os.path.join(os.path.dirname(__file__), '../samples/test.json')

TTL_1_2 = True  # set to False when parsing standard Turtle 1.1 files

with open(sample_path, 'r') as f:
    ttl_data = f.read()


# Parse with starlight
starlight_parser = StarlightTurtleParser()
starlight_graph = starlight_parser.parse(ttl_data, json_debug_path=json_output_path)


# Compare triples against rdflib (skip for TTL 1.2 — rdflib does not support that syntax)
from rdflib import Graph
if TTL_1_2:
    print("NOTE: Skipping rdflib comparison (TTL_1_2 = True).")
else:
    rdflib_graph = Graph()
    rdflib_graph.parse(data=ttl_data, format="turtle")
    starlight_triples = set((str(s), str(p), str(o)) for s, p, o in starlight_graph.triples((None, None, None)))
    rdflib_triples = set((str(s), str(p), str(o)) for s, p, o in rdflib_graph.triples((None, None, None)))
    if starlight_triples == rdflib_triples:
        print("SUCCESS: Starlight and rdflib graphs are equivalent.")
    else:
        print("ERROR: Graphs differ!")
        print("Starlight only:", starlight_triples - rdflib_triples)
        print("rdflib only:", rdflib_triples - starlight_triples)

# Write output using rdflib
starlight_graph.serialize(destination=output_path, format="turtle")
print(f"Wrote output to {output_path}")
