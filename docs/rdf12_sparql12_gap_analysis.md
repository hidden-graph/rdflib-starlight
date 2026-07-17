# RDF 1.2 / SPARQL 1.2 Spec vs. Implementation — Gap Analysis

**Date of review:** 2026-07-16. Compared against the live W3C documents fetched on this date (not the archived copies this project was originally built against). Spec text moves under the WG; re-verify section numbers before citing them externally.

| Document | Status fetched | Date |
|---|---|---|
| RDF 1.2 Concepts and Abstract Syntax | Candidate Recommendation Snapshot | 2026-04-07 |
| RDF 1.2 Schema | Working Draft | 2026-03-28 |
| RDF 1.2 Turtle | Working Draft | 2026-06-12 |
| RDF 1.2 N-Triples | Working Draft | 2026-06-24 |
| RDF 1.2 XML Syntax | Working Draft | 2026-06-18 |
| SPARQL 1.2 Query | Working Draft | 2026-06-25 |
| SPARQL 1.2 Update | Working Draft | 2026-06-12 |

No RDF 1.2 companion spec exists yet for JSON-LD or TriX — see §5.

Existing project docs ([starlight_vs_rdflib.md](starlight_vs_rdflib.md), [sparql12_design.md](sparql12_design.md)) track coverage of rdflib's own API surface and document starlight's *intended* design. Neither compares against the W3C spec text directly — that's the gap this document fills. The README's scope note ("focuses on reification... base-direction not implemented") is accurate and consistent with what's found below; this doc adds the finer-grained syntax/function-level detail.

---

## 1. RDF 1.2 Concepts — data model

| Concept | Spec | Starlight | Verdict |
|---|---|---|---|
| Triple term, object-position-only | §3.1, §3.6 | `TripleTerm` in `starlight/model/triple.py`; `starlight_graph.py` rejects subject position | ✅ Match |
| No cycles; nesting allowed in object only | §3.1 | `tests/unit/test_starlight_graph.py::test_nested_tt_object_fully_resolves`; subject-nesting blocked | ✅ Match |
| `rdf:reifies`, reification does **not** entail the base triple | §1.5 | `sparql12_design.md` QF1/QF2 demonstrate exactly this distinction (formal `<<()>>` pattern vs. asserting `{| |}`/`~`) | ✅ Match |
| Content-addressing / term equality by structural equality | §3.6 | `tt_hash()` in `starlight/model/encoding.py`, SHA-256 over `(s,p,o)` string forms | ✅ Match (implementation detail, not spec-mandated, but produces spec-correct equality) |
| `rdf:dirLangString`, base direction (`ltr`/`rtl`), 4-component literal identity | §3.4 | **Fixed 2026-07-16.** `DirLangString` in `starlight/model/dirlangstring.py`; encoded as a `Literal` with an internal `dirlang:` datatype URI (no rdflib fork), decoded transparently at the `StarlightGraph` boundary. See `future_enhancements.md` for the full design writeup | ✅ Match |
| Language tag case-folding (`"chat"@fr` ≡ `"chat"@FR`) | §3.4.1 | Delegates to rdflib's `Literal` — rdflib 7.6 already lowercases language tags, so this falls out for free | ✅ Match (incidental) |
| Version/conformance levels ("1.2", "1.2-basic", "1.1") | §2, §2.1 | **Fixed 2026-07-17.** Starlight still parses/accepts RDF 1.2 syntax unconditionally regardless of any declared level (correct per spec — the directive is "merely a hint," a parser "is not required to reject features that are outside the announced version"), but now warns (`RDF12ConformanceWarning`, never a hard error, matching the spec's own "could signal them with a warning" language) when a document declares `"1.2-basic"` while actually containing a triple term or `dirLangString`, or declares an unrecognized label. See `starlight/model/conformance.py` | ✅ Match |

---

## 2. Concrete syntaxes — Turtle / N-Triples / N-Quads / TriG

| Feature | Spec grammar | Starlight | Verdict |
|---|---|---|---|
| `<<( s p o )>>` triple term, `ttSubject` = iri\|BlankNode (no literal, no nesting) | Turtle §[32-34] | `starlight/parsers/turtle_parser.py`, `syntax.py` | ✅ Match |
| `<< s p o >>` reified-triple shorthand (unasserted, auto blank-node reifier if `~` absent) | Turtle §[29] | Implemented, matches "not asserted" semantics | ✅ Match |
| `~ (iri\|BlankNode)?` reifier, attaches to plain `object` via `objectList ::= object annotation` — i.e. **not** only inside `<< >>` | Turtle §[13],[28],[35] | `s p o ~ :stmt1` bare form implemented and tested | ✅ Match |
| `{| predicateObjectList |}` annotation block, asserts base triple | Turtle §[36] | Implemented, asserts base triple | ✅ Match |
| `@version "1.2" .` / `VERSION "1.2"` directive | Turtle §[6],[9] | **Fixed 2026-07-17.** Both spellings' quoted label is now extracted (`syntax.py`'s `extract_fields()`) and checked for a conformance mismatch against a `"1.2-basic"` declaration (`starlight/model/conformance.py`, warning-only) — see the §1 conformance-levels row above for the full write-up | ✅ Match |
| N-Triples/N-Quads: `<<( )>>` only, no `~`/`{| |}` shorthand (correct per spec — these are line-oriented formats) | N-Triples WD | `starlight/parsers/ntriples12.py` matches — no shorthand support | ✅ Match |
| `"text"@lang--dir` lexical form | Turtle §[42] / N-Triples `LANG_DIR` | **Fixed 2026-07-16** in both `turtle_parser.py`/`turtle12.py` and `ntriples12.py` (parser + serializer), including non-ASCII text and TriG (which reuses the Turtle code path) | ✅ Match |

**Overall: the Turtle/N-Triples/N-Quads/TriG layer is the strongest part of the implementation** — every syntactic form covered in this table has a matching, tested code path.

---

## 3. RDF/XML 1.2 — concrete deviation

The real spec (RDF 1.2 XML Syntax WD, 2026-06-18) represents a triple term with the existing RDF/XML `rdf:parseType="Triple"` mechanism on a property element wrapping a normal `rdf:Description`:

```xml
<ex:prop rdf:parseType="Triple">
  <rdf:Description rdf:about="http://example.org/stuff/1.0/s">
    <ex:p rdf:resource="http://example.org/stuff/1.0/o" />
  </rdf:Description>
</ex:prop>
```

and reification via new `rdf:annotation`/`rdf:annotationNodeID` **attributes** on the property element itself (distinct from the legacy `rdf:ID`-based `rdf:Statement` reification).

**Fixed 2026-07-16.** `starlight/serializers/rdfxml12.py` now emits real `rdf:parseType="Triple"` (recursively, for nested triple terms) instead of the invented `<rdf:TripleTerm>` element; reification is the ordinary `rdf:reifies` predicate with a triple-term-valued object (the same "formal pattern" canonical everywhere else in this codebase), not a special element either. `starlight/parsers/rdfxml12.py` was rewritten to preprocess the raw XML tree (via `xml.etree.ElementTree`) for `rdf:parseType="Triple"` **and** the `rdf:annotation`/`rdf:annotationNodeID` shorthand attributes before delegating the rest of the document to rdflib's real (RDF 1.1) `'xml'` parser unchanged — this was necessary, not optional: empirically, rdflib's parser silently mishandles both constructs today (`parseType="Triple"` degrades to an `rdf:XMLLiteral`; `rdf:annotation` gets misread as an ordinary property attribute and the element's own text content is silently dropped). The parser now also accepts `rdf:annotation`/`rdf:annotationNodeID` for reading documents from other RDF 1.2 tools, even though this serializer never emits them. Verified directly against the spec's own sec 2.19/2.20 XML examples (`tests/unit/test_rdf12_formats.py::TestRDFXML12SpecInterop`).

Scope limits of the rewrite (documented in the parser's own docstring): only node elements directly under `<rdf:RDF>` and their direct property children are inspected for the two RDF 1.2 attributes (matches what the serializer emits); a property carrying `rdf:annotation`/`rdf:annotationNodeID` must resolve to `rdf:resource`, `rdf:nodeID`, a single nested node element, or plain literal content — combining either attribute with `rdf:parseType="Resource"`/`"Collection"` raises `NotImplementedError` rather than being silently mishandled; only a single document-level `xml:base` is honored (no per-element override) for the parts resolved manually. Nested `rdf:parseType="Triple"` (a triple term whose own object is another triple term) is supported as a reasonable extrapolation beyond the spec's single-level example, since nothing in the grammar forbids it and RDF 1.2's abstract model permits nesting generally.

---

## 4. SPARQL 1.2 Query — functions and syntax

| Spec item | Starlight | Verdict |
|---|---|---|
| `SUBJECT(tt)` / `PREDICATE(tt)` / `OBJECT(tt)`, arity 1 | `sparql12_to_11.py` `_FUNC_TO_PRED`, exact name match | ✅ Match |
| `TRIPLE(s, p, o)` — constructor **function**, independent of `<<( )>>` literal syntax | **Fixed.** `_rewrite_triple_calls()` in `sparql12_to_11.py` desugars `TRIPLE(s, p, o)` to `<<( s p o )>>` (recursively, so nested `TRIPLE(...)` and `<<( )>>` arguments both work) before any other pass runs, so it inherits matching, nesting, and CONSTRUCT-template minting for free | ✅ Match |
| `isTRIPLE(term)` — spec's exact function name | **Fixed.** `_IS_TT_RE` now matches `is(?:TripleTerm|Triple)(...)`, so both spellings are accepted | ✅ Match |
| `<<( s p o )>>` valid directly in `BIND(...)`, same as Turtle | Spec's own example: `BIND( <<( ?s ?p ?o )>> AS ?tt )` | Matches starlight's approach exactly | ✅ Match |
| Reification/annotation shorthand (`~`, `{| |}`, `<< >>`) valid in WHERE-clause graph patterns | Not fully confirmed from the fetched WD text (grammar section was truncated in the fetch), but is consistent with the worked examples in the spec and with prior RDF-star/SPARQL-star drafts | starlight implements and tests this (`sparql12_design.md` Phase 1) | ✅ Likely match — recommend re-verifying against the published grammar once it stabilizes, but no evidence of a discrepancy |
| `LANGDIR`, `hasLANGDIR`, `STRLANGDIR` — direction-aware literal functions; `LANG`/`hasLANG` upgraded for dirLangString | **Fixed 2026-07-16, arbitrary-nesting fix 2026-07-16.** `LANGDIR`/`hasLANGDIR`/`LANG`/`hasLANG` rewrite to plain SPARQL 1.1 built-ins (`DATATYPE`/`STR`/`STRSTARTS`/`STRAFTER`/`STRBEFORE`/`IF`); `STRLANGDIR` rewrites to a registered constructor function (validates its direction argument immediately, unlike a pure expression) against the internal `dirlang:` datatype URI. `_rewrite_dirlang_and_strlangdir()` is recursive-descent (mirrors `_rewrite_triple_calls`), so nested calls like `LANGDIR(STRLANGDIR(...))` resolve correctly — no longer limited to a bare-variable argument | ✅ Match |
| `VERSION "1.2"` query prologue directive | Not handled by `sparql12_to_11.py` | **Fixed 2026-07-17 — this was actually a real bug, not just a validation gap.** The directive wasn't merely unvalidated, it was never even *stripped*: `VERSION "1.2"\nSELECT ...` (the spec's own example form) raised a `ParseException` on the in-memory backend, since rdflib's SPARQL 1.1 parser has no notion of the directive at all. Now stripped by `_strip_version_directive()` before any further rewriting, with the same warning-only conformance check as the Turtle side | ✅ Match |

**Update 2026-07-16: fixed.** `TRIPLE()` and `isTRIPLE()` were the two spec-mandated tokens most likely to appear in a query copy-pasted from spec examples or another RDF 1.2 tool. Both are now aliased in `starlight/query/sparql12_to_11.py` (`isTRIPLE` → same rewrite as `isTripleTerm`; `TRIPLE(s,p,o)` → desugared to `<<( s p o )>>` up front, so it reuses the existing rewrite path unchanged). Covered by `tests/unit/test_sparql12_to_11.py` (rewriter-level) and `tests/unit/test_sparql12_query.py::TestQ18`/`TestQ19` (end to end).

---

## 5. SPARQL 1.2 Update

| Spec rule | Starlight | Verdict |
|---|---|---|
| `INSERT DATA`/`DELETE DATA` require ground triple terms (no variables; `DELETE DATA` additionally forbids blank nodes) | `starlight_graph.py:107-118` explicitly rejects triple terms in subject position and (per comment) nested/non-ground forms in `INSERT DATA` blocks | ✅ Match |
| Reifying a triple in `INSERT DATA` does not auto-assert the base triple | Consistent with the Query-side non-entailment behavior already verified in §1 | ✅ Match |
| `INSERT`/`DELETE ... WHERE` pattern forms allow variables, mirroring Query | `starlight_graph.py:857` `update()`, plus the CONSTRUCT-style `BIND`-splicing added in the working-tree diff for minting new triple terms | ✅ Match |

No gaps found here beyond what's already covered by the Query-side function gaps in §4 (an Update `WHERE` clause using `TRIPLE()`/`isTRIPLE()` inherits the same problem).

---

## 6. Formats with no real spec target: JSON-LD "1.2", TriX "1.2"

The RDF 1.2 Schema document's own list of companion specs is: Turtle, N-Triples, N-Quads, TriG, XML Syntax. **There is no W3C JSON-LD 1.2 or TriX 1.2 document** — the JSON-LD Working Group has not published an RDF-1.2-aware revision, and TriX was never an RDF 1.1 W3C spec either (it's a long-standing HP Labs/Jena convention).

`starlight/serializers/jsonld12.py` is honest about this in its own docstring — it states the output is "valid JSON-LD 1.1" using an ad hoc `rdf:TripleTerm` node convention starlight defined itself, round-trippable only through starlight's own parser. `trix12.py` is the same kind of invention (a `<tripleTerm>` element added to the pre-existing, non-W3C TriX convention). Both were extended for `dirLangString` the same way: an internal `dirlang:` datatype URI (`@type` in JSON-LD, `datatype=` on TriX's `<typedLiteral>`) rather than JSON-LD 1.1's native `@direction` keyword — rdflib's JSON-LD codec (RDF 1.1) has no concept of `@direction` and would silently drop it on parse, so using `@type` instead keeps it round-trippable through rdflib's real, unmodified JSON-LD parser.

**Verdict: not a bug, but a naming/expectation risk.** Calling these formats `jsonld12`/`trix12` alongside genuinely spec-backed `turtle12`/`nt12`/`nq12`/`trig12`/`rdfxml12` (even with rdfxml12's own deviation from §3) implies a level of external conformance that doesn't exist for these two — there is currently no external tool a user could round-trip either through. Worth a one-line callout in the README/docs distinguishing "spec-target formats" from "starlight-defined conventions," so users don't file a bug against, say, a real JSON-LD processor for rejecting starlight's `rdf:TripleTerm` convention.

---

## Summary — ranked by priority

1. ~~**`TRIPLE(s,p,o)` constructor and `isTRIPLE()` naming** (§4)~~ — **done, see update above.**
2. ~~**`rdf:dirLangString` and its SPARQL functions** (§1, §2, §4)~~ — **done 2026-07-16, fully verified against live backends.** Data model (`DirLangString`), all six formats (Turtle/N-Triples/N-Quads/TriG/RDF-XML/TriX/JSON-LD 1.2), and `LANGDIR`/`hasLANGDIR`/`STRLANGDIR`/upgraded `LANG`/`hasLANG` all implemented and tested (`tests/unit/test_dirlangstring.py`). Nested/arbitrary-expression function arguments and query-time `STRLANGDIR` direction validation were both closed out as follow-ups the same day. The native-backend JSON-results direction key was an unverified `"direction"` guess as of the last update to this doc — **now confirmed and corrected to `"its:dir"`**, tested directly against live Fuseki 5.5.0 and Oxigraph 0.5.9 (both agree independently); see `future_enhancements.md`'s "Fuseki RDF 1.2 Native Syntax" section for the full write-up, including a newly-discovered regression in `backend='rdf-star'` mode against modern Fuseki (backend since removed entirely). A follow-up systematic three-way comparison against both live backends (`future_enhancements.md`'s "Cross-backend behavior parity" section) then found and fixed three more real bugs this same table didn't catch: `TRIPLE()`/`isTRIPLE()` used bare in a SELECT projection produced invalid SPARQL, and a `"text"@lang--dir` literal written directly in a query (not via a bound variable) wasn't rewritten at all. `STRLANGDIR`'s invalid-direction handling was also changed to match native soft-failure semantics (unbound variable, not a query-aborting exception). The remaining matching-vs-constructing `TRIPLE()` semantics difference was itself resolved 2026-07-16 (documented there, not here): a *ground* `TRIPLE()`/`<<( )>>` value now always constructs, with no side effect on the graph, while a triple term with any variable component keeps requiring an actual match — mirroring how an IRI not present in the graph is still a valid, constructible term.
3. ~~**RDF/XML 1.2 deviation on TripleTerm** (§3)~~ — **done 2026-07-16.** Serializer switched to real `rdf:parseType="Triple"` (recursive, for nesting) and the formal `rdf:reifies` pattern; parser rewritten to preprocess `rdf:parseType="Triple"` and `rdf:annotation`/`rdf:annotationNodeID` at the XML-tree level before delegating to rdflib, which was necessary (not optional — rdflib's own parser was confirmed to silently mishandle both constructs). Verified against the spec's own sec 2.19/2.20 examples.
4. ~~**Documentation callout for jsonld12/trix12** (§6)~~ — **done 2026-07-16.** Added to `README.md` and `docs/starlight_vs_rdflib.md`'s Serialization/Parsing section: `jsonld12`/`trix12` have no W3C spec target (unlike the other six RDF 1.2 formats) and round-trip only through starlight's own parser/serializer.
5. ~~**Version-directive validation, conformance levels** (§1, §2)~~ — **done 2026-07-17.** Re-checked against the live spec text and found a real bug hiding behind the "low priority" label: a SPARQL 1.2 query with a leading `VERSION "1.2"` directive — the spec's own example syntax — previously raised `ParseException` outright on the in-memory backend. Fixed (directive is now stripped before rewriting), and a new `RDF12ConformanceWarning` (warning-only, per the spec's explicit "merely a hint" language — never a hard error) fires when a document/query declares `"1.2-basic"` while still using a triple term or `dirLangString`, or declares an unrecognized label. See `starlight/model/conformance.py` and `docs/future_enhancements.md`.
6. **New: keeping in step with the spec as it moves from Candidate Recommendation to a final Recommendation** — this project's whole reason to exist is temporary by its own README's admission. See `docs/future_enhancements.md`'s "Keeping in step with RDF 1.2/SPARQL 1.2 as the spec finalizes" for the concrete re-check steps (re-run this gap analysis at each spec-stage transition, watch for a real JSON-LD RDF-1.2 companion spec, re-evaluate this project's continued existence once rdflib ships native support).
