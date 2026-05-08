"""
starlight.model.triple

Core RDF 1.2 types: TripleTerm.
"""


class TripleTerm:
    """An RDF 1.2 triple term — a triple used as a resource.

    Value-typed: two instances with the same (s, p, o) are equal and have the
    same hash. A plain Python 3-tuple is coerced to TripleTerm wherever the
    StarlightGraph API expects a node.

    _namespace_manager is set by StarlightGraph._restore() when returning a
    TripleTerm from a query result so that __str__ can emit prefixed names.
    It is excluded from equality and hashing.
    """
    __slots__ = ('subject', 'predicate', 'object', '_namespace_manager')

    # Slots that may only be written once (during __init__)
    _IMMUTABLE = frozenset({'subject', 'predicate', 'object'})

    def __init__(self, subject, predicate, obj):
        if isinstance(subject, TripleTerm):
            raise ValueError(
                "RDF 1.2: the subject of a triple term must be an IRI or blank node, "
                "not a triple term. Triple terms are only permitted in object position."
            )
        self.subject = subject
        self.predicate = predicate
        self.object = obj
        self._namespace_manager = None

    def __setattr__(self, name, value):
        if name in TripleTerm._IMMUTABLE:
            try:
                object.__getattribute__(self, name)
            except AttributeError:
                object.__setattr__(self, name, value)
                return
            raise AttributeError(f"TripleTerm is immutable; cannot reassign '{name}'")
        object.__setattr__(self, name, value)

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

    def n3(self, namespace_manager=None):
        nm = namespace_manager if namespace_manager is not None else self._namespace_manager
        return f'<<( {self.subject.n3(nm)} {self.predicate.n3(nm)} {self.object.n3(nm)} )>>'

    def __str__(self):
        return self.n3()

    def __repr__(self):
        return f'TripleTerm({self.subject!r}, {self.predicate!r}, {self.object!r})'


