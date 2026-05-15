"""Starlight — RDF 1.2 / RDF-star graph library built on rdflib.

Re-exports the most commonly needed rdflib primitives so downstream code can
import everything from ``starlight`` rather than mixing ``starlight.*`` and
``rdflib.*`` imports.
"""

# Core rdflib term types
from rdflib import BNode, Literal, URIRef, Variable

# Namespace utilities
from rdflib import Namespace
from rdflib.namespace import RDF, RDFS, XSD

# Graph / dataset base classes (aliased so consumers can stay on starlight.*)
from rdflib import Graph, Dataset
from rdflib.collection import Collection

# Starlight-specific additions
from starlight.model.triple import TripleTerm
from starlight.graph.starlight_graph import StarlightGraph
from starlight.graph.starlight_dataset import StarlightDataset

__all__ = [
    # rdflib primitives
    "BNode",
    "Literal",
    "URIRef",
    "Variable",
    # namespaces
    "Namespace",
    "RDF",
    "RDFS",
    "XSD",
    # graph types
    "Graph",
    "Dataset",
    "Collection",
    # starlight additions
    "TripleTerm",
    "StarlightGraph",
    "StarlightDataset",
]
