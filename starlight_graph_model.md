# StarlightGraph — High-Level Model Design

## Purpose

`StarlightGraph` is the central abstraction in the starlight library. It **subclasses** `rdflib.Graph` with **RDF 1.2 semantics** — specifically triple terms and reification — as first-class Python objects, hiding the internal blank-node encoding that rdflib 1.1 requires.

```python
class StarlightGraph(rdflib.Graph): ...
```

The design principle is **extension, not replacement**: every method that exists on `rdflib.Graph` works identically on `StarlightGraph`. `isinstance(g, rdflib.Graph)` returns `True`. All unoverridden methods (namespace management, SPARQL, serialization, etc.) are inherited automatically.

---

## Inline TripleTerm Notation

The key convention throughout the entire API: **a Python 3-tuple in any node position is treated as a triple term.**

You never need to construct a `TripleTerm` object explicitly to use the API. Tuples are the natural inline notation:

```python
(EX.alice, EX.knows, EX.bob)   # ← this is a triple term wherever a node is expected
```

This applies uniformly to `add`, `remove`, `triples`, `subjects`, `objects`, and all other node-bearing methods.

---

## Core Types

### `TripleTerm`

Represents an RDF 1.2 triple term — a triple used as a resource (`<<( s p o )>>`).

```python
TripleTerm(subject, predicate, object)
```

- `subject` — URI, blank node, or another `TripleTerm`
- `predicate` — URI
- `object` — URI, blank node, literal, or another `TripleTerm`

**Key properties:**
- Value-typed: two `TripleTerm` instances with the same `(s, p, o)` are equal and have the same hash, regardless of how or when they were created.
- Immutable after construction.
- Nestable: subjects and objects may themselves be `TripleTerm` instances.
- A plain 3-tuple is automatically coerced to a `TripleTerm` wherever the API expects a node.

```python
t = TripleTerm(EX.alice, EX.knows, EX.bob)
t == TripleTerm(EX.alice, EX.knows, EX.bob)     # True
t == (EX.alice, EX.knows, EX.bob)               # True — tuple coercion
```

### `Statement`

Represents a reified triple — a named or anonymous resource that `rdf:reifies` a `TripleTerm`.

```python
Statement(reifier, triple_term)
```

- `reifier` — the URI or blank node that acts as the statement's identity
- `triple_term` — the `TripleTerm` (or tuple) being reified

A `Statement` is the bridge between an annotation and the triple it annotates.

```python
s = Statement(reifier=EX.stmt1, triple_term=(EX.s, EX.p, EX.o))
```

---

## StarlightGraph API

### Construction

Mirrors `rdflib.Graph`:

```python
g = StarlightGraph()
g = StarlightGraph(store='default', identifier=None)
g = StarlightGraph.from_rdflib(rdflib_graph)   # wrap an existing rdflib.Graph
```

### `add` — identical signature to rdflib, extended for triple terms

rdflib accepts either a single 3-tuple or three positional arguments:

```python
# rdflib-compatible: plain triple as a tuple
g.add((EX.s, EX.p, EX.o))

# rdflib-compatible: plain triple as positional args
g.add(EX.s, EX.p, EX.o)

# extended: triple term as subject, passed as a tuple in first position
g.add((EX.s, EX.p, EX.o), EX.q, EX.z)

# extended: triple term as object, passed as a tuple in third position
g.add(EX.s, EX.p, (EX.a, EX.b, EX.c))

# extended: triple term as both subject and object
g.add((EX.s, EX.p, EX.o), EX.q, (EX.a, EX.b, EX.c))

# rdflib-compatible: single-tuple form also works for triple-term triples
g.add(((EX.s, EX.p, EX.o), EX.q, EX.z))
```

The rule: if an argument in a node position (subject or object) is a 3-tuple, it is coerced to a `TripleTerm`. The predicate position is never a triple term.

### `remove` — same extension as `add`

```python
# remove a plain triple
g.remove((EX.s, EX.p, EX.o))

# remove a triple where the subject is a triple term
g.remove(((EX.s, EX.p, EX.o), EX.q, None))   # None = wildcard, rdflib convention
```

### `triples` — pattern matching, same as rdflib, extended for triple terms

rdflib's `triples` takes a `(subject, predicate, object)` tuple with `None` as wildcard. `StarlightGraph` extends this so triple terms can appear in patterns:

```python
# rdflib-compatible: find all triples with a given subject
g.triples((EX.s, None, None))

# extended: find all triples whose subject is a specific triple term
g.triples(((EX.s, EX.p, EX.o), None, None))

# extended: find all triples whose object is any triple term
# (None in the tuple position = wildcard over triple terms)
g.triples((None, EX.mentions, (None, None, None)))

# extended: find triples where subject is a triple term with a specific predicate inside it
g.triples(((None, EX.knows, None), EX.certainty, None))
```

Returns an iterator of `(subject, predicate, object)` tuples where any node that is a triple term is returned as a `TripleTerm` object (not a raw bnode).

### `subjects`, `predicates`, `objects` — same convention

```python
g.subjects(predicate=EX.p, object=EX.o)          # rdflib-compatible
g.objects(subject=(EX.s, EX.p, EX.o), predicate=EX.q)  # extended: triple term as subject
```

When a result is a triple term, it is returned as a `TripleTerm` object, not a bnode.

### `__contains__` — the `in` operator

```python
(EX.s, EX.p, EX.o) in g                            # rdflib-compatible
((EX.s, EX.p, EX.o), EX.q, EX.z) in g             # extended: triple term as subject
```

### `parse` — extended to support TTL 1.2

```python
g.parse("data.ttl")                      # rdflib-compatible: auto-detects format
g.parse("data.ttl", format="turtle12")   # extended: TTL 1.2 via StarlightTurtleParser
g.parse("data.nt",  format="ntriples12") # extended: N-Triples 1.2
```

For formats rdflib already handles, the call is passed through unchanged.

### `serialize` — extended to support TTL 1.2

```python
g.serialize(format="turtle")             # rdflib-compatible: TTL 1.1 (triple terms as bnodes)
g.serialize(format="turtle12")           # extended: TTL 1.2 with <<( )>> and {| |} syntax
g.serialize(format="ntriples12")         # extended: N-Triples 1.2
```

### `query` — extended for SPARQL-star

```python
# rdflib-compatible: standard SPARQL 1.1
g.query("SELECT ?s ?p ?o WHERE { ?s ?p ?o }")

# extended: SPARQL-star triple term patterns
g.query("SELECT ?r WHERE { ?r rdf:reifies <<( :s :p :o )>> }")
g.query("SELECT ?s ?o WHERE { <<?s :knows ?o>> :certainty ?c }")
```

SPARQL-star patterns are translated into equivalent queries over the internal bnode encoding before execution.

### RDF 1.2-specific methods (additions beyond rdflib)

These do not exist on `rdflib.Graph` and are the only net-new surface area:

```python
# add a reification: reifier rdf:reifies triple_term
g.add_statement(Statement(EX.stmt1, (EX.s, EX.p, EX.o)))

# find statements
g.statements(triple_term=(EX.s, EX.p, EX.o))  # all reifiers of this triple term
g.statements(reifier=EX.stmt1)                  # which triple term EX.stmt1 reifies

# wrap an rdflib.Graph produced by the parser
StarlightGraph.from_rdflib(rdflib_graph)
```

### Escape hatch

Since `StarlightGraph` IS a `rdflib.Graph` subclass, `g` itself can be used directly with any rdflib tooling that expects a `Graph`. There is no separate `g.rdflib_graph` property — `g` is the graph.

---

## Internal Representation

rdflib 1.1 has no native concept of a triple term. `StarlightGraph` encodes them using typed blank nodes and well-known predicates, completely hidden from callers.

### TripleTerm encoding

Each distinct `TripleTerm` is stored as one blank node with four triples:

```
_:si_N  rdf:type        sl:TripleTerm .
_:si_N  rdf:subject     <subject> .
_:si_N  rdf:predicate   <predicate> .
_:si_N  rdf:object      <object> .
```

`sl:` is the starlight internal namespace (`https://starlight.example/internal#`). These triples are never returned through the `StarlightGraph` API.

**Deduplication:** The graph maintains a registry mapping each canonical `(s, p, o)` tuple to its bnode. If the same triple term appears a second time, the existing bnode is reused. This preserves value-equality.

### Statement encoding

```
<reifier>  rdf:reifies  _:si_N .
```

The reifier may be a named URI (explicit `~ :id` syntax from TTL 1.2) or an auto-generated blank node.

### Triple encoding

Triples involving a triple term store the bnode in the node position:

```
_:si_N  <predicate>  <object> .   # triple term as subject
<subj>  <predicate>  _:si_N .    # triple term as object
```

---

## Bidirectional Translation

### Inbound (rdflib → StarlightGraph)

When wrapping an existing rdflib graph (e.g., from `StarlightTurtleParser`), the adapter scans for `sl:TripleTerm`-typed blank nodes, reconstructs `TripleTerm` objects from their `rdf:subject / rdf:predicate / rdf:object` triples, and populates the deduplication registry. From that point on all API calls are consistent.

### Outbound (StarlightGraph → rdflib)

When a tuple or `TripleTerm` appears in a node position:
1. Canonicalize to `(s, p, o)` — recursively if nested.
2. Check the registry — if a bnode already exists for this tuple, reuse it.
3. Otherwise allocate a new `_:si_N` bnode, write the four encoding triples, record the mapping.
4. Store the outer triple with the bnode in the node position.

---

## Relationship to Existing Components

```
TTL 1.2 text
    │
    ▼
StarlightTurtleParser          (starlight/parsers/ttl_parser.py)
    │  produces rdflib.Graph with _:si_N bnodes + sl:TripleTerm markers
    ▼
StarlightGraph.from_rdflib()   (starlight/graph/)
    │  reads existing bnodes into TripleTerm registry
    │  exposes extended rdflib API to callers
    ▼
  ┌──────────────────────────────────────┐
  │  Serializers        Query layer      │
  │  turtle12 /         SPARQL-star      │
  │  ntriples12         rewriting        │
  └──────────────────────────────────────┘
```

The parser remains unchanged and produces a plain `rdflib.Graph`. `StarlightGraph.from_rdflib()` wraps it. This keeps the parser decoupled from the graph model.

---

## Key Design Decisions

**Tuple = TripleTerm throughout.**
Using a Python 3-tuple as inline triple-term notation keeps the API natural and avoids forcing callers to construct `TripleTerm` objects. It also mirrors how rdflib itself uses 3-tuples as the unit of triple data.

**Extension, not replacement.**
`StarlightGraph` follows every rdflib.Graph convention. Existing rdflib code that does not use triple terms continues to work without change. New code that needs RDF 1.2 uses the same methods with tuples in node positions.

**Internal namespace is hidden.**
`sl:TripleTerm`, `_:si_N`, and the four encoding triples are never returned through the API. Callers see `TripleTerm` objects; the bnode encoding is an implementation detail.

**No separate triple store.**
rdflib remains the storage engine. `StarlightGraph` is a semantic lens over the same underlying rdflib store. Existing rdflib tooling works directly on `g` since `StarlightGraph` IS a `rdflib.Graph`.

**Parser → graph handoff is explicit.**
The parser produces a graph; the caller wraps it with `from_rdflib`. No implicit conversion. Both components remain independently testable.
