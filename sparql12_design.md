# SPARQL 1.2 Query Design — Examples and Expected Behaviour

This document defines how `StarlightGraph.query()` should behave with SPARQL 1.2
triple-term syntax. It is a design agreement, not an implementation spec.

---

## Dataset Used in All Examples

```turtle
@prefix :    <http://example.org/> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

# Triple term in object position
:alice :says <<( :bob :knows :carol )>> .

# Named reifier with annotations
:stmt1 rdf:reifies <<( :bob :knows :carol )>> ;
       :confidence "0.9" ;
       :source :WikiData .

# Inline annotation — anonymous reifier
:bob :knows :carol {| :since "2020" ; :via :LinkedIn |} .

# Triple term as subject
<<( :bob :knows :carol )>> :verifiedBy :ResearchTeam .
```

---

## How the Rewriter Works

`StarlightGraph.query()` intercepts any query containing `<<( )>>` and rewrites it
to SPARQL 1.1 before passing it to rdflib's engine. Each triple term is replaced
with an auto-generated variable (`?__tt0`, `?__tt1`, ...) and three encoding
triples are injected into the same graph pattern block:

```sparql
# Input
?stmt rdf:reifies <<( :bob :knows :carol )>> .

# Rewritten
?stmt rdf:reifies ?__tt0 .
?__tt0 rdf:subject   :bob .
?__tt0 rdf:predicate :knows .
?__tt0 rdf:object    :carol .
```

Queries with no `<<( )>>` or annotation patterns are passed through unchanged.

**Annotation patterns** (`<< s p o >>`, `s p o {| ... |}`, `s p o ~?r`) are rewritten
differently — see the section below.

---

## Triple Terms vs Annotation Patterns

Two syntactically similar forms have distinct semantics.

**Triple term pattern** — parentheses: `<<( s p o )>>`

The triple is treated as a *resource* (a node). No claim that the underlying triple
is asserted in the graph. Used wherever an RDF node is expected.

**Annotation pattern** — no parentheses: `<< s p o >>`

Implies that the triple `(s, p, o)` is **asserted** in the graph. Expands to match
any reifier of that triple and query its properties.

The `{| pred obj |}` inline annotation and `~?r` reifier-name forms carry the same
asserted-triple semantics.

| Syntax | Triple asserted? | Typical use |
|--------|-----------------|-------------|
| `<<( s p o )>> :verifiedBy ?who` | No | Triple term as a subject node |
| `<< s p o >> :confidence ?c` | **Yes** | Query annotations on an asserted triple |
| `s p o {| ?pred ?val |}` | **Yes** | Inline annotation on an asserted triple |
| `s p o ~?r` | **Yes** | Bind the reifier of an asserted triple |
| `?stmt rdf:reifies <<( s p o )>>` | No | Find a named reifier |

**Rewrite for annotation patterns**

`<< ?s ?p ?o >> ?pred ?val .` rewrites to:

```sparql
?s ?p ?o .
?__r rdf:reifies <<( ?s ?p ?o )>> .
?__r ?pred ?val .
```

The anonymous reifier variable `?__r` is not exposed in results. Use `~?r` to name it.
Note that `?pred` will also bind to `rdf:reifies` (the reification triple itself);
add `FILTER(?pred != rdf:reifies)` to exclude it when querying only annotation properties.

---

## Result Binding Rules

Variables that appear **inside** a triple term pattern bind to plain RDF terms
(URIRef, Literal, BNode) — the components of the matched triple.

Variables that appear **outside** a triple term (i.e. bound to `?__ttN` internally)
are **not exposed** in SELECT results. `StarlightGraph.query()` post-processes
results to restore any `tt:HASH` URIRef bindings to `TripleTerm` objects — but
only for variables the caller explicitly selected.

---

## Query Examples

---

### Q1 — Triple term in object position (reification)

**Query**
```sparql
PREFIX :   <http://example.org/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT ?stmt WHERE {
  ?stmt rdf:reifies <<( :bob :knows :carol )>> .
}
```

**Expected results**

?stmt
:stmt1
_:rr_0  (the anonymous reifier from the {| |} annotation)

**Notes**
Both the named reifier `:stmt1` and the anonymous blank-node reifier from
`{| :since "2020" ... |}` reify the same triple term.

---

### Q2 — Triple term as subject

**Query**
```sparql
PREFIX :   <http://example.org/>

SELECT ?who WHERE {
  <<( :bob :knows :carol )>> :verifiedBy ?who .
}
```

**Expected results**

?who
:ResearchTeam

---

### Q3 — Triple term in object position (non-reification)

**Query**
```sparql
PREFIX :   <http://example.org/>

SELECT ?who WHERE {
  ?who :says <<( :bob :knows :carol )>> .
}
```

**Expected results**

?who
:alice

---

### Q4 — Variable triple term components

**Query**
```sparql
PREFIX :   <http://example.org/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT ?stmt ?s ?p ?o WHERE {
  ?stmt rdf:reifies <<( ?s ?p ?o )>> .
}
```

**Expected results**

?stmt    ?s     ?p       ?o
:stmt1   :bob   :knows   :carol
_:rr_0   :bob   :knows   :carol

**Notes**
`?s`, `?p`, `?o` bind to the components of the matched triple term.
Both reifiers point to the same triple term so both rows have identical ?s/?p/?o.

---

### Q5 — OPTIONAL annotations on a reifier

**Query**
```sparql
PREFIX :   <http://example.org/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT ?stmt ?conf ?source WHERE {
  ?stmt rdf:reifies <<( :bob :knows :carol )>> .
  OPTIONAL { ?stmt :confidence ?conf . }
  OPTIONAL { ?stmt :source ?source . }
}
```

**Expected results**

?stmt    ?conf   ?source
:stmt1   "0.9"   :WikiData
_:rr_0   —       —

**Notes**
The anonymous reifier has no `:confidence` or `:source` so those columns are
unbound (NULL) for its row. OPTIONAL scope must remain local to its `{ }` block.

---

### Q6 — Triple term selected as a variable

**Query**
```sparql
PREFIX :   <http://example.org/>

SELECT ?who ?tt WHERE {
  ?who :says ?tt .
}
```

**Expected results**

?who     ?tt
:alice   <<( :bob :knows :carol )>>

**Notes**
`?tt` binds to the raw `tt:HASH` URIRef in the underlying store.
`StarlightGraph.query()` must restore this to a `TripleTerm` object and
serialize it using the graph's namespace manager so prefixed names are used.
This is a post-processing step, not part of the rewriter.

---

### Q7 — SUBJECT / PREDICATE / OBJECT functions

SPARQL 1.2 defines built-in functions for extracting components from a triple
term binding.

**Query**
```sparql
PREFIX :   <http://example.org/>

SELECT ?who (SUBJECT(?tt) AS ?knower) (PREDICATE(?tt) AS ?rel) (OBJECT(?tt) AS ?known) WHERE {
  ?who :says ?tt .
}
```

**Expected results**

?who     ?knower   ?rel      ?known
:alice   :bob      :knows    :carol

**Notes**
`SUBJECT()`, `PREDICATE()`, `OBJECT()` operate on bound triple term variables.
They rewrite to `rdf:subject`/`rdf:predicate`/`rdf:object` triple patterns injected
into the WHERE clause, consistent with how `<<( )>>` patterns are handled.

---

### Q8 — Annotation patterns

Annotation patterns query properties of reifiers of asserted triples. All three
syntactic forms rewrite to the same `rdf:reifies` + component pattern.

**Query — all annotations on any asserted triple (`<< >>` form)**
```sparql
PREFIX :   <http://example.org/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT ?s ?p ?o ?pred ?val WHERE {
  << ?s ?p ?o >> ?pred ?val .
  FILTER(?pred != rdf:reifies)
}
```

**Expected results**

?s      ?p       ?o       ?pred         ?val
:bob    :knows   :carol   :since        "2020"
:bob    :knows   :carol   :via          :LinkedIn
:bob    :knows   :carol   :confidence   "0.9"
:bob    :knows   :carol   :source       :WikiData

**Notes**
All four rows come from two reifiers of `<<( :bob :knows :carol )>>`: the anonymous
`_:rr_0` (carrying `:since`/`:via`) and `:stmt1` (carrying `:confidence`/`:source`).
Without the `FILTER`, a row with `?pred = rdf:reifies` would also appear for each
reifier.

---

**Query — inline annotation form (`{| |}`) targeting a specific predicate**
```sparql
PREFIX :   <http://example.org/>

SELECT ?since WHERE {
  :bob :knows :carol {| :since ?since |} .
}
```

**Expected results**

?since
"2020"

---

**Query — bind the reifier explicitly (`~?r` form)**
```sparql
PREFIX :   <http://example.org/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT ?r ?pred ?val WHERE {
  :bob :knows :carol ~?r .
  ?r ?pred ?val .
  FILTER(?pred != rdf:reifies)
}
```

**Expected results**

?r       ?pred         ?val
:stmt1   :confidence   "0.9"
:stmt1   :source       :WikiData
_:rr_0   :since        "2020"
_:rr_0   :via          :LinkedIn

**Notes**
`~?r` binds the reifier node directly, allowing further pattern matching on its
properties without the implicit `?__r` variable. Equivalent to:
```sparql
?r rdf:reifies <<( :bob :knows :carol )>> .
:bob :knows :carol .
?r ?pred ?val .
```

---

### Q9 — Nested triple term

A nested triple term is a triple whose subject or object is itself a triple
term. This query finds reifiers of a triple whose subject is another triple.

**Additional data for this example**
```turtle
@prefix :    <http://example.org/> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

# :carol claims that the fact ":alice :believes <<( :bob :knows :dave )>>"
# has been verified.
:verifStmt rdf:reifies <<( <<( :bob :knows :dave )>> :believedBy :alice )>> .
:verifStmt :verifiedBy :ResearchTeam .
```

**Query**
```sparql
PREFIX :   <http://example.org/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT ?stmt ?innerS ?innerP ?innerO ?outerP ?outerO WHERE {
  ?stmt rdf:reifies <<( <<( ?innerS ?innerP ?innerO )>> ?outerP ?outerO )>> .
}
```

**Expected results**

?stmt        ?innerS   ?innerP   ?innerO   ?outerP        ?outerO
:verifStmt   :bob      :knows    :dave     :believedBy    :alice

**Notes**
The rewriter produces two `?__ttN` variables — `?__tt0` for the inner triple
term, `?__tt1` for the outer — and injects encoding triples for both:

```sparql
?stmt rdf:reifies ?__tt1 .
?__tt1 rdf:subject   ?__tt0 .
?__tt1 rdf:predicate :believedBy .
?__tt1 rdf:object    :alice .
?__tt0 rdf:subject   :bob .
?__tt0 rdf:predicate :knows .
?__tt0 rdf:object    :dave .
```

The inner `?__tt0` appears as the value of `rdf:subject` in the outer encoding.

---

### Q10 — All reification statements with their triple terms

Returns every reifier alongside the triple it reifies — both the reifier node
and the triple term are returned as bound variables.

**Query**
```sparql
PREFIX :   <http://example.org/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

SELECT ?stmt ?tt WHERE {
  ?stmt rdf:reifies ?tt .
}
```

**Expected results**

?stmt      ?tt
:stmt1     <<( :bob :knows :carol )>>
_:rr_0     <<( :bob :knows :carol )>>

**Notes**
`?tt` binds to a `tt:HASH` URIRef in the store; `query()` post-processing restores
it to a `TripleTerm` object. Both rows share the same triple term value since
`:stmt1` and `_:rr_0` both reify the same triple.

---

### Q11 — ASK with triple term

**Query**
```sparql
PREFIX :   <http://example.org/>

ASK {
  <<( :bob :knows :carol )>> :verifiedBy :ResearchTeam .
}
```

**Expected result**
`true`

---

### Q12 — CONSTRUCT producing a plain graph

**Query**
```sparql
PREFIX :   <http://example.org/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

CONSTRUCT {
  ?stmt :hasConfidence ?conf .
} WHERE {
  ?stmt rdf:reifies <<( :bob :knows :carol )>> .
  ?stmt :confidence ?conf .
}
```

**Expected result graph**
```turtle
:stmt1 :hasConfidence "0.9" .
```

---

### Q13 — `isTripleTerm` and assertion check

`isTripleTerm(?x)` returns `true` when `?x` is a triple term value. It rewrites to
`FILTER(STRSTARTS(STR(?x), "http://starlight.org/tt/"))` against the internal
`tt:HASH` encoding. `SUBJECT()`, `PREDICATE()`, `OBJECT()` extract components of a
bound triple term without needing a `<<( )>>` pattern in WHERE.

**Query**
```sparql
PREFIX :   <http://example.org/>

SELECT DISTINCT ?tt ?s ?p ?o (EXISTS { ?s ?p ?o } AS ?asserted) WHERE {
  { ?sub ?pred ?tt } UNION { ?tt ?pred ?obj }
  FILTER(isTripleTerm(?tt))
  BIND(SUBJECT(?tt) AS ?s)
  BIND(PREDICATE(?tt) AS ?p)
  BIND(OBJECT(?tt) AS ?o)
}
```

**Expected results**

?tt                          ?s     ?p       ?o       ?asserted
<<( :bob :knows :carol )>>   :bob   :knows   :carol   true

**Notes**
The UNION covers triple terms in both subject and object positions; `DISTINCT`
collapses duplicates. `EXISTS { ?s ?p ?o }` is `true` here because `:bob :knows
:carol` is asserted via the `{| |}` annotation. A triple term that appears only as
an object of `:says` or `rdf:reifies`, with the base triple never directly asserted,
would return `false`.

---

## Design Decisions

Agreed and closed — not open for further debate.

- **TripleTerm restoration**: `query()` always restores `tt:HASH` URIRefs to
  `TripleTerm` objects in SELECT results. Callers never see internal `tt:` URIRefs.

- **CONSTRUCT output**: always a `StarlightGraph`, regardless of whether the
  template contains triple terms.

- **`isTripleTerm` implementation**: rewrite to
  `FILTER(STRSTARTS(STR(?x), "http://starlight.org/tt/"))` — consistent with the
  rewriter approach, no rdflib extension registration needed.

- **`SUBJECT`/`PREDICATE`/`OBJECT` implementation**: rewrite to inject
  `rdf:subject`/`rdf:predicate`/`rdf:object` triple patterns into the WHERE clause.

---

## Open Implementation Notes

1. **Prefixed name serialization in TripleTerm results (Q6, Q7, Q10)**
   `TripleTerm.__str__()` currently emits full URIs (`<http://...>`). Results must
   use prefixed names (`:bob`) consistent with the rest of the graph. `query()` must
   pass the graph's namespace manager to `TripleTerm` serialization at result time.

2. **Annotation pattern rewriter pass (Q8)**
   `<< s p o >>`, `{| |}`, and `~?r` forms require a pre-pass that runs before the
   `<<( )>>` rewriter. The injected reifier variable `?__r` must be scoped to the
   same `{ }` block as the base triple. OPTIONAL and UNION interaction must be
   tested against Q8 examples.

3. **SPARQL UPDATE — deferred**
   INSERT/DELETE with triple-term patterns is not addressed here.
