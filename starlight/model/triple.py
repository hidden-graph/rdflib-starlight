"""
starlight.model.triple

Core RDF 1.2 types: TripleTerm and Statement.
"""


class TripleTerm:
    """An RDF 1.2 triple term — a triple used as a resource.

    Value-typed: two instances with the same (s, p, o) are equal and have the
    same hash. A plain Python 3-tuple is coerced to TripleTerm wherever the
    StarlightGraph API expects a node.
    """
    __slots__ = ('subject', 'predicate', 'object')

    def __init__(self, subject, predicate, obj):
        self.subject = subject
        self.predicate = predicate
        self.object = obj

    def _key(self):
        s = self.subject._key() if isinstance(self.subject, TripleTerm) else self.subject
        o = self.object._key()  if isinstance(self.object,  TripleTerm) else self.object
        return (s, self.predicate, o)

    def __eq__(self, other):
        if isinstance(other, TripleTerm):
            return self._key() == other._key()
        if isinstance(other, tuple) and len(other) == 3:
            return self._key() == TripleTerm(*other)._key()
        return NotImplemented

    def __hash__(self):
        return hash(self._key())

    def __iter__(self):
        yield self.subject
        yield self.predicate
        yield self.object

    def __repr__(self):
        return f'TripleTerm({self.subject!r}, {self.predicate!r}, {self.object!r})'


class Statement:
    """A reified triple — a resource that rdf:reifies a TripleTerm."""
    __slots__ = ('reifier', 'triple_term')

    def __init__(self, reifier, triple_term):
        self.reifier = reifier
        self.triple_term = (
            triple_term if isinstance(triple_term, TripleTerm)
            else TripleTerm(*triple_term)
        )

    def __eq__(self, other):
        return (
            isinstance(other, Statement)
            and self.reifier == other.reifier
            and self.triple_term == other.triple_term
        )

    def __hash__(self):
        return hash((self.reifier, self.triple_term))

    def __repr__(self):
        return f'Statement(reifier={self.reifier!r}, triple_term={self.triple_term!r})'
