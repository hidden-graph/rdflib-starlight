"""
starlight.graph.adapter

Adapter to bridge between starlight model triples/statements and RDFLib Graph.
"""

from typing import Any, Iterable
#from rdflib import Graph as RDFLibGraph  # Uncomment when integrating with RDFLib
#from rdflib.term import Node as RDFLibNode
from starlight.model.triple import Triple, Statement

class GraphAdapter:
    """Bridges starlight model <-> RDFLib.Graph."""
    def __init__(self, rdflib_graph: Any):
        self.rdflib_graph = rdflib_graph

    def add_triple(self, triple: Triple):
        # Convert Triple to RDFLib triple and add to graph
        s, p, o = triple.as_tuple()
        # self.rdflib_graph.add((s, p, o))
        pass  # TODO: implement conversion and add

    def add_statement(self, statement: Statement):
        # Add named/reified statement to RDFLib graph
        # TODO: implement mapping for RDF-star or reification
        pass

    def triples(self) -> Iterable[Triple]:
        # Yield starlight Triples from RDFLib graph
        # for s, p, o in self.rdflib_graph.triples((None, None, None)):
        #     yield Triple(s, p, o)
        pass

    def statements(self) -> Iterable[Statement]:
        # Yield starlight Statements (named/reified) from RDFLib graph
        pass
