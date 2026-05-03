# StarlightGraph vs rdflib.Graph — Method Coverage Tracker

Tracks every public `rdflib.Graph` method against its status in `StarlightGraph`.

**Status key**

✅ Done — explicitly overridden; TripleTerm coercion/filtering is correct
🔗 Inherited — not overridden; delegates through our `triples()` override and works correctly
⚠️ Partial — works for common cases but has documented caveats
🔲 Not started — known gap; TripleTerm handling is missing or incorrect
➖ Not needed — no TripleTerm handling required; plain rdflib behaviour is correct

---

## Core Mutation
Triples may contain triples statements {(c b c)} in the subject or object position of the triple.

✅ `add(triple)` — Coerces tuple/TripleTerm in subject and object positions; also accepts positional `(s, p, o)` form.

✅ `remove(triple)` — Coerces subject/object before delegating to store.

🔗 `set(triple)` — Calls our `remove()` + `add()`, so coercion flows through correctly.

✅ `addN(quads)` — Overridden; coerces TripleTerms in subject/object positions before writing to the store.

---

## Core Traversal
Patterns may contain triple statements as part of the pattern.
✅ `triples(pattern)` — Coerces TripleTerm patterns; filters internal encoding triples (`tt:` subject + `rdf:subject/predicate/object`); restores TT URIRefs to TripleTerm objects in results.

✅ `triples_choices(triple)` — Overridden; coerces TripleTerm patterns (lists or singles), filters encoding triples, restores TripleTerm objects in results.

🔗 `__iter__` — rdflib implements as `self.triples((None, None, None))` — our override fires correctly.

✅ `__contains__(triple)` — Coerces subject/object before membership test.

✅ `__len__` — Counts only visible (non-encoding) triples via `self.triples()`.

---

## Convenience Traversal

All of these are implemented in rdflib as thin wrappers over `self.triples()`, so they inherit correct TripleTerm support without needing overrides.

Subjects and objects may be triple terms and subjects() and objects() may return triple terms.

🔗 `subjects(predicate, object)` — Iterates `self.triples()`; returns TripleTerm objects where applicable; encoding triples filtered.

🔗 `predicates(subject, object)` — Predicates cannot be TripleTerms in RDF 1.2; encoding predicates are filtered by `triples()`.

🔗 `objects(subject, predicate)` — Returns TripleTerm objects in object positions via `triples()` restoration.

🔗 `subject_objects(predicate)` — Both positions restored via `triples()`.

🔗 `subject_predicates(object)` — Subject position restored via `triples()`.

🔗 `predicate_objects(subject)` — Object position restored via `triples()`.

🔗 `value(subject, predicate, object)` — Delegates to `objects()` / `subjects()`; returns TripleTerm correctly.

🔗 `all_nodes()` — Built as `chain(subjects(), objects())`; both of those work; encoding nodes excluded.

---

## Namespace / Identifier

➖ `bind(prefix, namespace)` — No TripleTerm involvement.

➖ `namespaces()` — No TripleTerm involvement.

➖ `compute_qname(uri)` — URI string utility.

➖ `qname(uri)` — URI string utility.

➖ `absolutize(uri)` — URI resolution utility.

➖ `n3(namespace_manager)` — Returns the graph's own identifier as N3, not triple content.

---

## Serialization / Parsing

Allows for the parsing from 1.2 formats and the serialization into 1.2 formats. 

⚠️ `parse(...)` — `format='turtle12'` routes to `StarlightTurtleParser` + `_skolemize_encoding`; all other formats delegate to rdflib with no TripleTerm support (TripleTerms will not be recognized or registered).

⚠️ `serialize(...)` — `format='turtle12'` routes to `serialize_turtle12()`; all other formats serialize the raw store (encoding triples visible, TT URIRefs as `tt:HASH` instead of `<<( )>>`).

⚠️ `print(format, out)` — Calls `self.serialize()`; Turtle 1.2 output works cleanly; all other formats expose internal encoding.

---

## SPARQL

Allow SPARQL queries to consume and return triple statements.

✅ `query(query_object, ...)` — Overridden. Rewrites SPARQL 1.2 syntax to SPARQL 1.1 before execution; runs the rewritten query against a plain `Graph` view of the store so encoding triples are visible; post-processes SELECT bindings to restore `tt:HASH` URIRefs to `TripleTerm` objects (including prefixed-name serialization via the graph's namespace manager); wraps CONSTRUCT output in a `StarlightGraph`. Supported forms: `<<( )>>` triple-term patterns, `<< >>` annotation subjects, `{| |}` inline annotation blocks, `~?r` reifier binding, `SUBJECT()`/`PREDICATE()`/`OBJECT()` functions, `isTripleTerm()` filter.

✅ `update(update_object, ...)` — Overridden. Three paths: (1) WHERE clauses — `<<( )>>` rewritten to encoding patterns; (2) INSERT/DELETE DATA — ground triple terms parsed via Turtle 1.2 and added/removed directly; (3) INSERT/DELETE templates — `<<( )>>` in subject **or** object position handled via post-processing SELECT against the same WHERE clause; bindings resolved via Python API. Registry rebuilt after every update.

---

## Graph Algorithms

Update graph algorithms to operate with triple statements,

🔗 `connected()` — Uses `subjects()` which is correct; encoding triples filtered so only visible graph structure is considered.

⚠️ `isomorphic(other)` — Uses `graph_diff` which iterates both graphs via `triples()`; TT URIRefs are content-addressed (same content = same URI) so identical TripleTerms match correctly. BNodes *inside* a TripleTerm are included in the hash and will not isomorphize across separately parsed graphs — correct RDF 1.2 semantics but may surprise callers.

⚠️ `cbd(resource, ...)` — Calls `self.predicate_objects()` (correct), but copies results into `target_graph` via `target_graph.add()`. If `target_graph` is a plain `rdflib.Graph`, TripleTerms in object position cannot be stored. Works correctly when `target_graph` is also a `StarlightGraph`.

➖ `transitiveClosure(func, arg)` — User-supplied function; no direct TripleTerm involvement.

➖ `transitive_objects(subject, predicate)` — Calls `self.objects()` which is inherited correctly; a TripleTerm as a hop in the chain is an unusual edge case.

➖ `transitive_subjects(predicate, object)` — Same as above.

---

## RDF Collections

🔲 `collection(identifier)` — `rdf:first` / `rdf:rest` lists; TripleTerms should be valid list members (a collection of statements) but are not currently handled.

🔲 `items(list)` — Generator over list members; will return raw `tt:HASH` URIRefs instead of TripleTerm objects when a list contains triple terms.

---

## Store Lifecycle

➖ `open(configuration, create)`

➖ `close(commit_pending_transaction)`

➖ `commit()`

➖ `rollback()`

➖ `destroy(configuration)`

---

## Other rdflib Utilities

➖ `skolemize(...)` — rdflib BNode → URI skolemization; unrelated to TT encoding.

➖ `de_skolemize(...)`

🔲 `resource(identifier)` — Returns an `rdflib.Resource` view; identifier is not coerced to `tt:HASH`, so passing a TripleTerm to navigate annotations will not work.

➖ `toPython()` — No-op on Graph; unrelated.

---

## RDF 1.2 Additions (Starlight-only)

These methods exist only in `StarlightGraph` and have no rdflib equivalent.

✅ `add_reifier(predicate, obj, name=None)` — Creates a reifier node (named URIRef if `name` given, fresh BNode otherwise), asserts `(reifier, predicate, obj)` into the graph, and returns the reifier for use with `add_reification()`. `.

✅ `add_reification(reifier, triple_term)` — Adds a reification as `reifier rdf:reifies tt:HASH`; accepts a plain 3-tuple or TripleTerm for `triple_term`.

✅ `reifications(TT=None, predicate=None, object=None)` — Yields reifier nodes matching the combined filters: `TT` narrows by the triple term being reified; `predicate`/`object` narrow by properties of the reifier itself. Any combination works — e.g. `reifications(TT=t, predicate=EX.reported, object=EX.NYTimes)` returns reifiers that reify `t` AND were reported by NYTimes.

✅ `reified_triples(reifier)` — Yields the TripleTerms reified by the given reifier node. Pair with `reifications()` to answer "what did NYTimes report?" or "what does this reifier claim?".

✅ `triple_terms(subject=None, predicate=None, object=None)` — Yields all TripleTerms registered in the graph; any combination of subject, predicate, object filters the results. Use `next(g.triple_terms(s, p, o), None)` for a single lookup by components.

✅ `has_triple_term(subject, predicate, object)` — Returns True if a TripleTerm with those exact components exists in the graph; pure registry lookup, no store query.

✅ `reifiers(TT)` — Shorthand for `reifications(TT=TT)`; yields all reifier nodes that claim a specific triple term.

✅ `remove_reification(reifier)` — Removes the `rdf:reifies` triple(s) for the given reifier node.

✅ `from_rdflib(source_graph)` — Class method; runs `_skolemize_encoding`, copies triples, rebuilds TT registry.

---

## Starlight Classes

New classes introduced by Starlight with no direct rdflib equivalent.

### starlight/model/triple.py

✅ `TripleTerm` — Represents an RDF 1.2 triple term `<<( s p o )>>` as a Python value type. Value-equality and hashing based on content; accepts nested TripleTerms. Coerced from plain 3-tuples wherever the StarlightGraph API accepts a node. Implements `n3(namespace_manager=None)` for rdflib term interface compatibility.

### starlight/graph/starlight_graph.py

✅ `StarlightGraph` — Subclass of `rdflib.Graph`; the main public API. Stores TripleTerms as content-addressed `tt:HASH` URIRefs internally and hides the encoding from all callers. See method tracker above.


### starlight/parsers/turtle_parser.py

✅ `StarlightTurtleParser` — Parses Turtle 1.2 text (including `<<( )>>`, `{| |}`, and `~ reifier` syntax) into an rdflib Graph with BNode-based triple-term encoding. Called by `StarlightGraph.parse(format='turtle12')`.

➖ `_Expander` — Internal helper class used by the parser to resolve prefixes and base URIs during parsing. Not part of the public API.

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

✅ Done — 11
🔗 Inherited (works) — 14
⚠️ Partial / caveats — 5
🔲 Not started (gap) — 2
➖ Not needed — 16


### Known caveats

- **`serialize` non-turtle12 formats** — internal `tt:HASH` URIRefs and encoding triples (`rdf:subject/predicate/object`) are visible; intended for debugging but may surprise callers expecting clean RDF 1.1.
- **`cbd`** — only safe when `target_graph` is a `StarlightGraph`; TripleTerms in object positions cannot be stored in a plain `rdflib.Graph`.
- **`isomorphic`** — TripleTerms with BNodes inside them are content-addressed and will not isomorphize across separately parsed graphs (expected RDF 1.2 semantics, but worth noting).
