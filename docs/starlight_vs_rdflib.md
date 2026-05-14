# StarlightGraph vs rdflib.Graph — Method Coverage Tracker

Summary of all public `rdflib.Graph` methods and status in `StarlightGraph`.

**Status key**

✅ Done — explicitly overridden; TripleTerm coercion/filtering is correct
🔗 Inherited — not overridden; delegates through our `triples()` override and works correctly
⚠️ Partial — works for common cases but has documented caveats
➖ Not relevant — no TripleTerm handling required; plain rdflib behaviour is correct

---

## Core Mutation

TripleTerm as used below can refer to either a plain 3-tuple `(s, p, o)` in object position, or a `TripleTerm` instance created as `TT = TripleTerm(s, p, o)`.

✅ `g.add(triple)` — Adds one triple. Allows triple term as an object.

✅ `g.remove(triple)` — Removes a triple. Allows triple term as an object.

🔗 `g.set(triple)` — Replaces all existing objects for the given subject+predicate with the new value. Allows triple term as an object.  

✅ `g.addN(quads)` — Adds multiple `(subject, predicate, object, graph)` quads in one call. Accepts TripleTerms in the object position.

---

## Core Traversal

TripleTerms can appear in the object position of a pattern. All traversal methods can return TripleTerms as first-class values.

✅ `g.triples((s, p, o))` — Yields all triples matching the pattern. Each position is a specific value or `None` (wildcard). Accepts a TripleTerm in the object position; returns TripleTerms as `TripleTerm` objects.

✅ `g.triples_choices((s, p, o))` — Like `g.triples()` but any position can be a list of values instead of a single value. Accepts TripleTerms in any object list entry.

🔗 `for (s, p, o) in g` — Iterates all triples in the graph. Delegates to `g.triples()`, so TripleTerms are returned correctly.

✅ `(s, p, o) in g` — Tests whether a specific triple is in the graph. Accepts a TripleTerm in the object position.

✅ `len(g)` — Returns the number of triples in the graph based on RDF 1.2 representation.

---

## Convenience Traversal

These are all rdflib wrappers over `g.triples()` and work correctly with TripleTerms without any override. Objects may be TripleTerms; TripleTerms are returned as `TripleTerm` objects.

🔗 `g.subjects(predicate, object)` — Yields subjects matching the given predicate and object.

🔗 `g.predicates(subject, object)` — Yields predicates matching the given subject and object.

🔗 `g.objects(subject, predicate)` — Yields objects for the given subject and predicate. May return TripleTerms.

🔗 `g.subject_objects(predicate)` — Yields `(subject, object)` pairs for the given predicate. May return TripleTerms as object.

🔗 `g.subject_predicates(object)` — Yields `(subject, predicate)` pairs for the given object.

🔗 `g.predicate_objects(subject)` — Yields `(predicate, object)` pairs for the given subject. May return TripleTerms as object.

🔗 `g.value(subject, predicate, object)` — Returns a single matching value, or `None`. Raises if multiple matches exist.

🔗 `g.all_nodes()` — Yields every subject and object node in the graph based on RDF 1.2 representation.  

---

## Namespace / Identifier

The following functions have no TripleTerm involvement.

➖ `g.bind(prefix, namespace)` — Registers a prefix/namespace pair.

➖ `g.namespaces()` — Yields all registered `(prefix, namespace)` pairs.

➖ `g.compute_qname(uri)` — Returns `(prefix, namespace, name)` for a URI.

➖ `g.qname(uri)` — Returns a qualified name string for a URI.

➖ `g.absolutize(uri)` — Resolves a relative URI against the graph's base.

➖ `g.n3(namespace_manager)` — Returns an N3-formatted string for the graph.

---

## Serialization / Parsing

All rdflib formats are supported. Six additional RDF 1.2 formats add TripleTerm support.

✅ `g.parse(...)` — Six additional RDF 1.2 formats supported: `turtle12`, `nt12`, `nq12`, `trig12`, `trix12`, `rdfxml12`.

✅ `g.serialize(...)` — All rdflib formats continue to work (e.g. ttl 1.1) but will expose internal encoding of triples. Six RDF 1.2 formats serialize TripleTerms correctly: `turtle12`, `longturtle12`, `nt12`, `nq12`, `trig12`, `trix12`.

✅ `g.print(...)` — Overridden to default to `turtle12`. Calling `g.print()` with no arguments produces clean RDF 1.2 output.

---

## SPARQL

SPARQL 1.2 syntax is fully supported. See [sparql12_design.md](sparql12_design.md) for full details.

✅ `g.query(...)` — Accepts SPARQL 1.2 queries including `<<( )>>` triple-term patterns, `{| |}` annotation blocks, `~?r` reifier binding, and `isTripleTerm()`. For the default rdf-1.1 backend, queries are rewritten to SPARQL 1.1 internally. For native backends (rdf-star, rdf-1.2), queries go directly to the endpoint via HTTP. CONSTRUCT can return RDF 1.2 graph.

✅ `g.update(...)` — Accepts SPARQL 1.2 UPDATE with triple-term patterns in WHERE, INSERT, and DELETE clauses. For the default rdf-1.1 backend, triple terms are encoded before writing. For native backends, the update goes directly to the endpoint via HTTP.

---

## Graph Algorithms

All graph algorithms operate on the visible RDF 1.2 graph; encoding triples are filtered automatically.

🔗 `g.connected()` — Uses `subjects()`.

⚠️ `g.isomorphic(other)` — Uses `graph_diff` which iterates both graphs via `triples()`; TT URIRefs are content-addressed (same content = same URI) so identical TripleTerms match correctly. BNodes *inside* a TripleTerm are included in the hash and will not isomorphize across separately parsed graphs.  

✅ `g.cbd(resource, ...)` — Returns a `StarlightGraph` containing all triples for the given resource. Raises `TypeError` if a plain `rdflib.Graph` is passed as `target_graph`.

➖ `g.transitiveClosure(func, arg)` — User-supplied function; no direct TripleTerm involvement.

➖ `g.transitive_objects(subject, predicate)` — Walks a chain following objects as subjects. A TripleTerm cannot be a subject.

➖ `g.transitive_subjects(predicate, object)` — Walks the chain in reverse, finding all subjects that eventually lead to the given object. A TripleTerm can be the starting object.  

---

## RDF Collections

🔗 `g.collection(identifier)` — Returns a `Collection` object for navigating an `rdf:first`/`rdf:rest` list. TripleTerms are valid list members and are returned correctly as `TripleTerm` objects.

🔗 `g.items(list)` — Iterates members of an RDF list. TripleTerms in the list are returned as `TripleTerm` objects.

---

## Store Lifecycle

These methods manage the underlying store connection and transactions. They have no TripleTerm involvement and are not overridden.

➖ `g.open(configuration, create)` — Opens the store (e.g. connects to a database).

➖ `g.close(commit_pending_transaction)` — Closes the store connection.

➖ `g.commit()` — Commits the current transaction.

➖ `g.rollback()` — Rolls back the current transaction.

➖ `g.destroy(configuration)` — Destroys the store (e.g. drops the database).

---

## Other rdflib Utilities

➖ `g.skolemize(...)` — Replaces blank nodes with stable URIs. No TripleTerm involvement.

➖ `g.de_skolemize(...)` — Reverses `skolemize()`. No TripleTerm involvement.

➖ `g.resource(identifier)` — Returns an `rdflib.Resource` view for navigating a node's properties. Not applicable to TripleTerms since they cannot be subjects — use `g.reifier_annotations(TT)` and `g.reified_triples()` instead.

➖ `g.toPython()` — No-op on graphs; no TripleTerm involvement.

---

## RDF 1.2 Additions (Starlight-only)

These methods exist only in `StarlightGraph` and have no rdflib equivalent.

✅ `g.add_reifier_annotation(predicate, obj, name=None)` — Creates a new annotation using named URIRef as subject if `name` given, BNode otherwise. The node becomes a reifier after `g.add_reification()` is called. Returns the subject node as reifier.

✅ `g.add_reification(reifier, triple_term)` — Adds `reifier rdf:reifies <<( s p o )>>`. Accepts a plain 3-tuple or `TripleTerm` for `triple_term`.

✅ `g.reifiers(TT=None, predicate=None, object=None)` — Yields reifier nodes. `TT` narrows by the TripleTerm being reified; `predicate`/`object` narrow by the reifier's own annotation properties. Any combination works.

✅ `g.reifications(s=None, p=None, o=None)` — Yields TripleTerms that have at least one reifier annotation, optionally filtered by the components `s`, `p`, `o` of the TripleTerm.

✅ `g.reifier_annotations(TT)` — Yields `(reifier, predicate, value)` annotation triples for all reifiers of the given TripleTerm. Excludes the `rdf:reifies` triple itself.

✅ `g.reified_triples(reifier)` — Yields the TripleTerms of the given reifier.  

✅ `g.triple_terms(subject=None, predicate=None, object=None)` — Yields all TripleTerms in the graph; any combination of `subject`, `predicate`, `object` filters the results.

✅ `g.has_triple_term(subject, predicate, object)` — Returns `True` if a TripleTerm with those exact components exists in the graph.

✅ `g.remove_reification(reifier)` — Removes the `rdf:reifies` triple for the given reifier.

✅ `g.from_rdflib(source_graph)` — Class method; imports a plain `rdflib.Graph` into a new `StarlightGraph`, encoding any existing reification triples and rebuilding the TripleTerm registry.

---

## Starlight Classes

New classes introduced by Starlight with no direct rdflib equivalent.

### starlight/model/triple.py

✅ `TripleTerm` — Represents an RDF 1.2 triple term `<<( s p o )>>` as a Python value. Two TripleTerms with the same components are equal regardless of how they were created. Accepts nested TripleTerms. A plain 3-tuple in object position is automatically treated as a TripleTerm. Implements `.n3()` so rdflib can format it as `<<( :bob :knows :carol )>>` wherever a node is expected.

### starlight/graph/starlight_graph.py

✅ `StarlightGraph` — Subclass of `rdflib.Graph`; the main public API for single-graph RDF 1.2. Stores TripleTerms as content-addressed `tt:HASH` URIRefs internally and hides the encoding from all callers. See method tracker above.

```python
from starlight.graph.starlight_graph import StarlightGraph
from starlight.model.triple import TripleTerm
from rdflib import URIRef, Literal

g = StarlightGraph()                    # in-memory, default rdf-1.1 backend
g = StarlightGraph(backend='rdf-1.2')  # native RDF 1.2 endpoint
```

### starlight/graph/starlight_dataset.py

✅ `StarlightDataset` — Subclass of `rdflib.Dataset`; a multi-graph container where every named graph is a `StarlightGraph`. Each named graph has its own independent TripleTerm registry — triple terms in graph A are not visible from graph B.

- `ds.get_context(uri)` — returns the named graph as a `StarlightGraph` with its registry populated.

- `ds.quads((s, p, o))` — yields `(subject, predicate, object, graph)` across all named graphs, filtered by the optional `(s, p, o)` pattern (each position `None` matches anything). Encoding triples are hidden; TripleTerms are returned as `TripleTerm` objects. The fourth element is the `StarlightGraph` the triple belongs to.

- `ds.contexts()` — yields each named graph as a `StarlightGraph`.

- `ds.parse(format='trig12')` — loads a TriG 1.2 document, each named graph into its own `StarlightGraph`.

- `ds.serialize(format='trig12')` — emits a TriG 1.2 document with `GRAPH <uri> { ... }` blocks.


### starlight/parsers/turtle_parser.py

✅ `StarlightTurtleParser` — Parses Turtle 1.2 text (including `<<( )>>`, `{| |}`, and `~ reifier` syntax) into an rdflib Graph with BNode-based triple-term encoding. Called by `StarlightGraph.parse(format='turtle12')`.

➖ `_Expander` — Internal helper class used by the parser to resolve prefixes and base URIs during parsing. Not part of the public API.

### starlight/parsers/ntriples12.py

✅ `parse_ntriples12(text)` — Parses N-Triples 1.2 text line-by-line; returns a list of `(s, p, o)` triples where subjects/objects may be `TripleTerm` instances. Handles full IRIs, blank nodes, plain/typed/language-tagged literals, and `<<( )>>` triple terms (including nested). Called by `StarlightGraph.parse(format='nt12')`.

✅ `parse_nquads12(text)` — Parses N-Quads 1.2 text; returns a list of `(s, p, o, g)` quads. Called by `StarlightGraph.parse(format='nq12')`; the graph component `g` is discarded when merging into a single-graph `StarlightGraph`.

### starlight/parsers/trig12.py

✅ `parse_trig12(text)` — Parses TriG 1.2 text by splitting the document into prefix declarations and named-graph content blocks, parsing each block as Turtle 1.2 via `StarlightTurtleParser`, and merging all resulting triples. Called by `StarlightGraph.parse(format='trig12')`.

### starlight/serializers/ntriples12.py

✅ `serialize_ntriples12(g)` — Serializes a `StarlightGraph` to N-Triples 1.2 text (one triple per line, full IRIs, `<<( )>>` for triple terms). Called by `StarlightGraph.serialize(format='nt12')`.

✅ `serialize_nquads12(g, graph_uri=None)` — Serializes to N-Quads 1.2 text (N-Triples + graph name from `g.identifier`). Called by `StarlightGraph.serialize(format='nq12')`.

### starlight/serializers/trig12.py

✅ `serialize_trig12(g)` — Serializes to TriG 1.2 text. Named-graph identifiers (URIRef) produce a `GRAPH <uri> { ... }` block around Turtle 1.2 content; BNode identifiers produce plain Turtle 1.2 (default-graph convention). Called by `StarlightGraph.serialize(format='trig12')`.

### starlight/query/sparql12_to_11.py

✅ `rewrite_sparql12_to_11(query)` — Public entry point. Rewrites SPARQL 1.2 syntax to SPARQL 1.1: triple-term patterns `<<( )>>`, annotation subjects `<< >>`, inline annotation blocks `{| |}`, reifier binding `~?r`, `SUBJECT()`/`PREDICATE()`/`OBJECT()` function calls, and `isTripleTerm()` filter. Passes plain queries through unchanged.

➖ `_RewriteState` — Internal counter for generating unique `?__ttN` variable names across a single rewrite pass. Not part of the public API.

---

## Starlight Internal Functions

Module-level functions that are part of the internal encoding but not public API.

### starlight/model/encoding.py

✅ `tt_hash(s, p, o)` — Produces an 8-hex-char SHA-256 content address for a triple term. Same inputs always produce the same hash, so identical triple terms map to the same internal `tt:HASH` URIRef.

---

## Summary

✅ Done — 35 (13 rdflib.Graph methods overridden; 10 RDF 1.2 additions; 12 Starlight classes/functions)
🔗 Inherited (works) — 13
⚠️ Partial / caveats — 1 (see below)
➖ Not relevant — 20


### Known caveat

- **`isomorphic`** — TripleTerms with BNodes inside them are content-addressed and will not isomorphize across separately parsed graphs (expected RDF 1.2 semantics, but worth noting).
