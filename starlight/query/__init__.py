"""Query utilities for translating RDF 1.2/SPARQL-star syntax.

This package is intentionally separate from ``starlight.graph`` so query
translation can be developed and tested without changing ``StarlightGraph``.
"""

from .sparql12_to_11 import rewrite_sparql12_to_11
from .sparql_api import parseQuery, prepareQuery, parseUpdate, prepareUpdate, processUpdate

__all__ = [
    "rewrite_sparql12_to_11",
    "parseQuery",
    "prepareQuery",
    "parseUpdate",
    "prepareUpdate",
    "processUpdate",
]