"""
starlight.model.triple

Core RDF 1.2 types: TripleTerm.
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

    def __str__(self):
        s = str(self.subject)   if isinstance(self.subject, TripleTerm) else self.subject.n3()
        p = self.predicate.n3()
        o = str(self.object)    if isinstance(self.object,  TripleTerm) else self.object.n3()
        return f'<<( {s} {p} {o} )>>'

    def __repr__(self):
        return f'TripleTerm({self.subject!r}, {self.predicate!r}, {self.object!r})'


