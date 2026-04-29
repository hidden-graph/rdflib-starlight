"""
starlight.model.triple

Defines core RDF-star triple and statement classes, independent of RDFLib.
"""

from typing import Any, Tuple

class Triple:
    """Represents an RDF triple or RDF-star triple (subject, predicate, object)."""
    def __init__(self, subject: Any, predicate: Any, object: Any):
        self.subject = subject
        self.predicate = predicate
        self.object = object

    def as_tuple(self) -> Tuple[Any, Any, Any]:
        return (self.subject, self.predicate, self.object)

    def __eq__(self, other):
        return (
            isinstance(other, Triple) and
            self.subject == other.subject and
            self.predicate == other.predicate and
            self.object == other.object
        )

    def __hash__(self):
        return hash((self.subject, self.predicate, self.object))

    def __repr__(self):
        return f"Triple({self.subject!r}, {self.predicate!r}, {self.object!r})"

class Statement:
    """Represents a named or reified statement (for RDF-star or reification)."""
    def __init__(self, triple: Triple, name: Any = None):
        self.triple = triple
        self.name = name  # Optional identifier for named statement

    def __eq__(self, other):
        return (
            isinstance(other, Statement) and
            self.triple == other.triple and
            self.name == other.name
        )

    def __hash__(self):
        return hash((self.triple, self.name))

    def __repr__(self):
        return f"Statement({self.triple!r}, name={self.name!r})"
