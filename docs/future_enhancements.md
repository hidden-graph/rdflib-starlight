# Starlight Future Enhancements

---

## Keeping in step with RDF 1.2/SPARQL 1.2 as the spec finalizes

RDF 1.2 was at **Candidate Recommendation** (published 2026-04-07) as of this writing — not yet a final W3C Recommendation. Everything in this project (the gap analysis, the rewriter, the format modules) is checked against that CR-stage text. This project's own stated purpose (README: "intended to remain relevant until rdflib is updated to incorporate the final RDF 1.2 specification") means it has a deliberately limited lifespan, and needs periodic re-checking rather than a one-time gap analysis. Concrete steps for whoever picks this up as the spec progresses:

1. **Re-run the gap analysis at each W3C stage transition** (CR → PR → REC). CR-stage text can still change in response to implementation/horizontal-review feedback before Proposed Recommendation; re-diff `docs/rdf12_sparql12_gap_analysis.md` against the current editor's draft whenever the spec's status changes, not just once.
2. **Watch the CR exit criteria / implementation report.** The RDF-star Working Group's CR exit requires a set of independent conforming implementations. Whichever engines end up counted (Oxigraph and Fuseki are the two this project already tracks) are worth re-verifying starlight's rewriter against each time one of them ships a release claiming closer conformance — the live three-way comparison methodology used 2026-07-16 (see "Cross-backend behavior parity" below) is the reusable tool for that, not a one-off.
3. **Watch for a real JSON-LD RDF-1.2 companion spec.** If the JSON-LD Working Group ever publishes an RDF-1.2-aware revision with its own native representation for quoted/triple terms, replace `starlight/serializers/jsonld12.py` and `starlight/parsers/jsonld12.py`'s invented `rdf:TripleTerm` convention with the real one, and update the module's docstring and the callout in `docs/starlight_vs_rdflib.md` accordingly (see "Formats with no real spec target" in the gap analysis). TriX has no standards body actively developing it, so `trix12` is unlikely to ever gain a real target to converge on — its "starlight convention, not a spec" status is probably permanent, and the documentation callout is the whole fix rather than a placeholder for a future code change.
4. **Once rdflib ships native RDF 1.2 support** — re-evaluate this project's continued existence, per its own stated scope. At that point: (a) consider deprecating starlight's SPARQL 1.2→1.1 rewriter and in-memory triple-term encoding in favor of delegating straight to rdflib, and (b) check whether the `turtle12`/`nt12`/`nq12`/`trig12`/`rdfxml12` format modules can be dropped in favor of rdflib's own native parsers/serializers.
5. **Revisit `VERSION "1.2"` / `-1.2-basic` directive validation** (gap analysis §1/§2, low priority today because starlight rewrites RDF 1.2 syntax unconditionally regardless of the directive). Once the spec is final, check whether conforming tooling is expected to validate the directive's presence/value strictly rather than ignore it.

---

## Architectural review follow-ups (2026-07-16/17)

A full architectural review of the project (prompted by a direct request, not a spec gap) surfaced 9 findings, all addressed same day/next day:

**Correctness fixes:**
- **`tt_hash()` widened from 8 to 16 hex chars** (`starlight/model/encoding.py`) — an 8-char/32-bit content-address prefix has non-negligible birthday-bound collision risk above ~65,000 distinct triple terms in one process, a plausible count for this library's core use case (heavy reification). A collision would have silently merged two unrelated triple terms under the same internal URI. No migration story needed: the hash is recomputed fresh from content on every intern, never persisted as a stable external identifier.
- **`_rewrite_triple_functions` had the same WHERE-less bug** later fixed for ground `TRIPLE()` BINDs: it located its injection point via a bare `WHERE {` text search with no fallback, silently dropping `SUBJECT()`/`PREDICATE()`/`OBJECT()`'s binding triple on a WHERE-less query (`SELECT (SUBJECT(?tt) AS ?s) { }`) rather than raising or working. Fixed by extracting a shared `_find_group_pattern_start()` used by both call sites (`starlight/query/sparql12_to_11.py`).
- **`SUBJECT()`/`PREDICATE()`/`OBJECT()` applied directly to a `<<( )>>`/`TRIPLE(...)` literal** (as opposed to a bound variable) raised a `ParseException` — found via the property-based fuzz test below while designing its template set. `SUBJECT(<<( s p o )>>)` is an exact, lookup-free textual equivalence to `s` (unlike `SUBJECT(?tt)`, which needs a store lookup), so it's handled as an early desugaring pass, `_rewrite_triple_accessor_literals()`, that runs right after `TRIPLE(...)` is desugared to `<<( )>>` and before everything else — meaning it works identically inside a WHERE-clause block or bare in a SELECT projection, with none of the separate "inside vs. outside a block" injection logic the bound-variable form needs. See `tests/unit/test_sparql12_to_11.py` (rewriter-level) and `tests/unit/test_sparql12_query.py::TestQ22` (end-to-end).

**Hardening:**
- **`_TT_HASH_MEMO`** (the process-wide memo backing ground-`TRIPLE()` restoration, see the "Cross-backend behavior parity" section's `TRIPLE()` write-up below) **is now a bounded LRU `OrderedDict`** (cap 100,000) instead of an unbounded plain `dict`, so a long-running process issuing many distinct ground `TRIPLE()` queries no longer leaks memory forever. Eviction has no correctness cost — a re-lookup after eviction just re-runs the pure hash function.
- **Duplicated SELECT-result restore/filter logic** between `StarlightGraph.query()` and `StarlightDataset.query()` (identical row-filtering list comprehension, differing only in `self._restore` vs `self._restore_any`) factored into a shared `restore_select_bindings()` in `starlight/model/encoding.py`, alongside a shared `ENCODING_PREDS` constant.
- **Import-time SPARQL function registration** (`_register_tt_hash_function()`/`_register_dirlang_construct_function()`, which mutate rdflib's global function registry as a side effect of importing `sparql12_to_11.py`) is now documented as deliberate rather than left as an unexplained action-at-a-distance.

**Testing infrastructure:**
- **Property-based fuzz testing** (`tests/unit/test_sparql12_to_11_fuzz.py`, using Hypothesis) checks one cheap, purely syntactic property across a combinatorial grid the example-based tests don't enumerate — query form × explicit/omitted `WHERE` × ground/variable/nested triple-term components × block placement — asserting only that `rewrite_sparql12_to_11()`'s output always parses as valid SPARQL 1.1. This immediately found the `SUBJECT()`-on-literal gap above while its template set was being designed.
- **The manual three-way comparison script used 2026-07-16 promoted to a standing, checked-in integration test**, `tests/integration/test_cross_backend_parity.py` (13 scenarios, ported directly from the scratchpad script, parametrized and compared against the in-memory backend independently per native backend so a partial environment still provides value). Verified live against Fuseki 5.5.0 and Oxigraph. One scenario (`isTripleTerm()`, starlight's own pre-spec-stabilization alias) had to be excluded from the parity set — confirmed live that real SPARQL 1.2 engines correctly reject it as a parse error, since it's not real SPARQL syntax, only something the in-memory rewriter's `_IS_TT_RE` understands; `isTRIPLE()` (the real spec name, also in the scenario set) already covers the same functionality and does match everywhere.
- **CI (`tool.pytest.ini_options`/`.github/workflows/test.yml`) was actually broken by the Hypothesis addition** until caught by re-running a clean-venv simulation of CI's exact install command: CI installed `pytest` directly rather than the new `test` extras group, so `hypothesis` was never installed and the whole suite failed to collect. Fixed (`pip install -e ".[sqlalchemy,test]"`); also discovered and fixed a second, pre-existing and unrelated CI issue while verifying this: the `integration` pytest marker declared in `pyproject.toml` was never actually applied to any test, so `pytest -m "not integration"` was a silent no-op — the integration tests were only ever excluded by their own `skipif` checks failing to find a local server, not by the marker filter. Added `pytestmark = pytest.mark.integration` to all three integration test modules.

**The Turtle 1.2 parser (`starlight/parsers/{turtle_parser,lexer,syntax}.py`) now raises on malformed input, matching rdflib's own Turtle parser.** Previously it was silently permissive: `:s :p totally!bogus$$token .` parsed with no error at all, producing `Literal('totally!bogus$$token')` — a stray unquoted, colonless token isn't valid Turtle in any position, but `_to_node()`'s fallback chain bottomed out at `return Literal(val)` for anything unrecognized, and several places in `lexer.py`/`syntax.py` treated "never found the closing delimiter" (unterminated string, unclosed `[`/`(`/`<<( )>>`/IRI) as "the rest of the document is one token" instead of an error. Confirmed directly against rdflib that this is a real gap, not an inherent property of hand-written Turtle parsers: `rdflib.plugins.parsers.notation3.BadSyntax` (a `SyntaxError` subclass reporting a line number and a `^`-pointer into the source) fires on the exact same input (though rdflib's own parser isn't spotless either - two tested cases, unterminated string and a missing trailing `.`, leaked a bare `AssertionError`/`IndexError` instead of `BadSyntax`, so the bar adopted here was "clear, typed exception with a line number for the common structural failures," not exhaustive grammar conformance).

Fixed with a new `TurtleSyntaxError(SyntaxError)` (`starlight/parsers/errors.py`, re-exported from `starlight` and `starlight.parsers`), styled after `BadSyntax` in spirit (line number + caret-pointer context) without depending on rdflib's internal parser state. Every silent fallback identified above now raises it instead: `lexer.next_token()`'s unclosed-delimiter branches, `turtle_parser._to_node()`'s unrecognized-term fallback, `turtle_parser._split_literal()`'s unterminated-quote fallback, and a new end-of-document check in `syntax.py` for a document that ends mid-string or with an unclosed bracket. Line numbers are threaded through the whole pipeline back to the original source (not the blank/comment-stripped text the parser actually scans) via a `line_map` in `StarlightTurtleParser.parse()`, at statement-start granularity (not byte-exact - matches newlines being stripped out of buffered multi-line statement text, an already-existing property of this scanner, not a new limitation introduced here). `trig12.py` needed no changes - it delegates to `StarlightTurtleParser` per `GRAPH` block, so it inherited the strictness automatically; verified live. `split_statements()`'s existing public signature was kept unchanged (still returns bare strings) specifically to avoid touching its own existing test suite; the new line-tracking is exposed via a new `split_statements_with_lines()` instead. Two off-by-one bugs in the new offset-tracking were caught and fixed via the new tests themselves before landing (a trailing-newline timing bug, and a separate one from blank lines between statements not being fully consumed) - both are exactly the kind of thing "run the full suite, don't just eyeball it" verification is for.

Verified with a full test-suite run after each change (zero regressions among ~600 pre-existing tests, confirming no currently-passing test relied on the old permissive behavior) plus 24 new tests: `tests/unit/test_lexer.py::TestNextTokenUnterminated`, `tests/unit/test_syntax.py::TestSplitStatementsWithLines`, and the new end-to-end `tests/unit/test_turtle_parser_errors.py`.

---

## VERSION directive: real bug fix + conformance warnings (2026-07-17)

Gap-analysis item "Version-directive validation, conformance levels" was filed as low priority with no known blocked use case — re-checking it against the live spec text (RDF 1.2 Concepts sec 2.1, RDF 1.2 Turtle's VERSION grammar, SPARQL 1.2 Query sec 4.3) turned up a real bug hiding behind that label, not just a missing nice-to-have.

**Confirmed from the spec**: three version labels exist — `"1.2"` (full), `"1.2-basic"` (RDF 1.2 syntax but *excludes* triple terms and `dirLangString`), `"1.1"` (legacy, discouraged in a VERSION directive since it'd needlessly break RDF 1.1 parsers). The directive is explicitly only a hint: "parsers are not required to reject features that are outside the announced version (but could signal them with a warning)"; the SPARQL side says processors "may treat unrecognized labels as an error or as a warning." Neither is mandatory.

**The real bug**: `VERSION "1.2"\nSELECT * WHERE { ?s ?p ?o }` — the spec's own example form — raised `pyparsing.ParseException` outright on the in-memory backend. `sparql12_to_11.py` never stripped the directive before handing the query to rdflib's SPARQL 1.1 parser, which has no notion of it at all. Fixed with `_strip_version_directive()`, run first in the rewrite pipeline, before any other pass. This one fix covers both `StarlightGraph.query()` and `.update()` (both funnel through the same rewriter); the native `rdf-1.2` backend was never affected since it passes queries straight through to a real endpoint that already understands `VERSION` natively.

**The conformance-checking half** (declaring `"1.2-basic"` while actually using a triple term or `dirLangString` anyway) is warning-only by design — `RDF12ConformanceWarning` (`starlight/model/conformance.py`), never a hard error, matching the spec's own permissive framing and this project's established posture of accepting RDF 1.2 syntax unconditionally. (This is a different category from the Turtle-parser strictness work above: that was about *malformed* syntax that should never parse to anything; this is about self-inconsistent-but-otherwise-valid documents/queries, where turning a stale VERSION line into a hard failure would do more harm than good.) One shared `check_version_conformance()` function is called from both sides so the warning wording isn't duplicated:

- **SPARQL side**: called right after `needs_tt`/`needs_ann` are computed in `_rewrite_sparql12_to_11_tracked`, using those existing flags plus a `'--' in query` check (captured *before* `_rewrite_dirlang_literals` runs, since that pass rewrites away the `--` in a literal `"text"@lang--dir`) as the "uses a triple term / dirLangString" signals.
- **Turtle side**: the version label was previously recognized-but-discarded (`turtle_parser.py`: `if typ == 'version': pass`) — `syntax.py`'s `extract_fields()` now actually extracts it (both the dotted `@version "1.2" .` and bare `VERSION "1.2"` spellings), and `turtle_parser.py` staples it onto the returned `Graph` as `g._declared_version` (an attribute, not a signature change, to avoid touching the half-dozen existing call sites of `StarlightTurtleParser().parse()`). `StarlightGraph.parse()` reads it back after `_build_registry_from_store()` and checks it against `self._tt_nodes`/a `DirLangString` scan. `trig12.py` is passthrough-only for now (no separate per-named-graph check) — it already tolerated the directive fine, just discarded it, same as before.

Verified: the exact spec-example query now executes end-to-end via a live `StarlightGraph().query(...)` call (previously raised); full suite run clean (zero regressions, 618 passing including 15 new tests: `tests/unit/test_syntax.py`'s version-extraction cases and the new `tests/unit/test_conformance.py`).

**Two follow-up gaps found the same day by asking "is this consistent with our two native-backend comparables?" and actually checking, rather than assuming yes:**

1. **`"1.1"` was missing from the mismatch check.** The initial version only special-cased `"1.2-basic"` for the "excludes triple terms/dirLangString" warning — but `"1.1"` (plain RDF 1.1 syntax/semantics) excludes those features at least as strictly, not more permissively. `check_version_conformance()` now treats `"1.2-basic"` and `"1.1"` identically for this check.
2. **The native (`rdf-1.2`) backend never ran the conformance check at all.** `StarlightGraph.query()`/`.update()` return early for `self._is_native` — straight into `_native_query()`/`http_update()` — before `rewrite_sparql12_to_11()` (and therefore the conformance check inside it) is ever reached. Confirmed live against Fuseki 5.5.0 and Oxigraph: both execute a `VERSION "1.2-basic"` query containing a `<<( )>>` pattern completely normally (HTTP 200, no error, no warning anywhere in the response) — so without a fix, a `backend='rdf-1.2'` graph would silently never emit `RDF12ConformanceWarning` for the exact query the default in-memory backend does warn on. Added `_check_native_version_conformance()` (`starlight_graph.py`) to both native branches — it only replicates the *warning*, deliberately not the stripping, since the real endpoint needs to see the directive itself (and already understands it correctly, confirmed by the same live test). Covered by `tests/unit/test_conformance.py::TestNativeBackendVersionConformance` (tests the check function directly — it's pure Python with no network dependency, the HTTP call happens after it).

Re-verified full suite clean at 684 passing (including live integration tests, run this time with Fuseki/Oxigraph containers up).

---

## TriX: adopted Jena's real convention instead of starlight's own invention (2026-07-17)

Prompted by a direct question — "how does our format support compare to our two 1.2-native backends, are we over-supporting?" — checked live against Fuseki 5.5.0 and Oxigraph rather than assuming. Read/write matrix (Graph Store Protocol both directions):

| Format | Fuseki | Oxigraph |
|---|---|---|
| Turtle/N-Triples/N-Quads/TriG/RDF-XML | read+write | read+write |
| JSON-LD (plain) | read+write | read+write |
| JSON-LD with a triple term | **write fails (HTTP 500)** | **write fails ("not supported yet")** |
| TriX (plain and with a triple term) | **read+write, fully working** | **not supported at all (HTTP 415/406)** |

Two things fell out of this:

1. **JSON-LD**: starlight is ahead of, not behind, both real backends — neither will serialize a triple term to JSON-LD at all. Left as-is; genuinely speculative (no real spec, no real implementation to compare against) but not contradicted by anything either.
2. **TriX turned out to be the interesting one.** The gap analysis (§6) had assumed "no external tool to round-trip through" for TriX, same as JSON-LD — that assumption was wrong, not just unverified. Apache Jena has a real, working TriX writer/reader, and it does support RDF 1.2 triple terms. Starlight's own invented TriX convention — `<TriX>` (capital) root element, a distinct `<tripleTerm>` tag — was incompatible with Jena's actual output in *both* respects, confirmed the direct way: feeding Fuseki's live TriX output into `starlight.parsers.trix12.parse_trix12()` raised `ValueError: Expected <TriX> root element, got '{...}trix'`.

**Fixed**: `starlight/serializers/trix12.py` now emits Jena's exact convention — lowercase `<trix>` root, and a triple term as a `<triple>` nested in a term position (reusing the same element used for an ordinary asserted statement; TriX disambiguates by structural position, not tag name, and Jena has no separate "triple term" tag at all). `starlight/parsers/trix12.py` accepts this new form and still accepts the old `<TriX>`/`<tripleTerm>` spelling for backward compatibility with anything already serialized by the prior version, though nothing writes that form anymore. Re-verified live, both directions: Fuseki accepts starlight's new TriX output completely unmodified (HTTP 201), and starlight correctly parses Fuseki's real TriX output byte-for-byte — `tests/unit/test_rdf12_formats.py::TestTriX12ParseJenaConvention::test_parses_real_fuseki_output_verbatim` embeds the literal captured bytes from a live Fuseki 5.5.0 response, not a hand-written guess at what its output looks like.

Two existing tests asserted the old `<tripleTerm>` tag directly (`TestTriX12Serialize`/`TestTriX12Dataset`) and were updated to check for the new nested-`<triple>` count instead. Full suite: 687 passing, zero regressions.

---

## VERSION-directive support extended to every text-directive format (2026-07-17)

Prompted by a direct follow-up question — "does our VERSION support extend to other formats?" — rather than assuming the Turtle/SPARQL fix above covered everything, checked each format against its own spec text (or confirmed the spec doesn't apply). Result, spec mechanism vs. implementation:

| Format | Spec mechanism | Implemented? |
|---|---|---|
| SPARQL query/update | `VERSION "label"` prologue | ✅ (prior fix) |
| Turtle/longturtle | `@version "label" .` / `VERSION "label"` | ✅ (prior fix) |
| N-Triples/N-Quads | `VERSION "label"` (confirmed via spec fetch — bare form, same grammar as SPARQL's) | ❌ → **fixed today** |
| TriG | inherits Turtle's directive, but document-scoped, not per-`GRAPH`-block | ❌ → **fixed today** |
| RDF/XML | `rdf:version` attribute on a node element (confirmed via spec fetch) — structurally different, not a text directive at all | ❌ **still open**, deliberately deferred (different shape, doesn't fit the pattern below) |
| JSON-LD, TriX | no real RDF 1.2 spec exists for either | N/A, correctly out of scope |

**N-Triples/N-Quads**: `ntriples12.py`'s line parser already had `stripped.upper().startswith('VERSION')` — but only to skip the line like a comment, never extracting the label. New `extract_version_directive(text)` does a lightweight separate scan of just the first non-blank/comment line, keeping `parse_ntriples12()`/`parse_nquads12()`'s existing `list[tuple]` return signature untouched (same "don't change a tested public signature" approach used for `split_statements()` during the Turtle-parser strictness work). `StarlightGraph.parse()` calls it alongside the existing parse call.

**TriG**: worse than N-Triples — completely silent, not just partially. The document-level directive isn't per-`GRAPH`-block, but `trig12.py`'s parser works by splitting into blocks and running each one through `StarlightTurtleParser` separately; whichever block happens to contain the leading `VERSION` line captures it *internally* on its own throwaway parse result, but neither `parse_trig12()` nor `parse_trig12_named()` ever propagated that attribute out — confirmed live that a `VERSION "1.2-basic"` + triple-term TriG document produced zero warnings before the fix. New `extract_version_directive(text)` in `trig12.py` scans the raw document once via `syntax.split_statements()`/`classify_statement()` (reusing the already-tested Turtle statement splitter rather than duplicating its grammar) and checks whether the *first* statement is a version directive — matching the grammar's requirement that VERSION, if present, comes first. Wired into both `StarlightGraph.parse(format='trig12')` and `StarlightDataset.parse(format='trig12')` (added a new `_check_document_version_conformance()` helper on `StarlightDataset` since the directive covers the whole document, so the check runs against the union of every resulting named graph, not each one independently); `StarlightDataset.parse(format='nq12')` got the same treatment as a byproduct since it shares the pattern.

**RDF/XML deliberately left open**: its version mechanism is an `rdf:version` XML attribute on a node element, not a prologue-style text directive — a fundamentally different detection shape that doesn't fit `extract_version_directive()`'s pattern, so it wasn't bundled in. Tracked in the gap analysis as its own open item.

9 new tests added to `tests/unit/test_conformance.py` (`TestNTriplesNQuadsVersionDirective`, `TestTrigVersionDirective`; 26 total in that file now). Full suite: 636 passing, zero regressions, re-verified in a clean-venv CI simulation.

---

## Fuseki RDF 1.2 Native Syntax

**Status: confirmed 2026-07-16, against a live Fuseki 5.5.0 (`secoresearch/fuseki:latest` Docker image) and Oxigraph 0.5.9 (`ghcr.io/oxigraph/oxigraph:latest`).** This is the thing the note below (kept for history) said to check once a stable release was available — it now is, and it works with zero code changes:

```python
# Fuseki 5.5+: speaks the final RDF 1.2 <<( s p o )>> syntax natively.
# "type":"triple" comes back correctly in SPARQL JSON results.
g = StarlightGraph(backend='rdf-1.2', query_url=..., update_url=...)
```

**`backend='rdf-star'` was removed 2026-07-16** (the older Jena draft `<< s p o >>`
bracket syntax, pre-dating the final RDF 1.2 spec). Confirmed directly via raw
HTTP that it's now broken for triple-term round-tripping against Fuseki 5.5.0:
a value matched via `<< s p o >>` comes back in SPARQL JSON results as a plain
`"type":"bnode"` instead of `"type":"triple"` — Fuseki appears to have retired
JSON-result materialization for the old bracket form now that the final
`<<( )>>` syntax is natively supported. Concretely:

```sparql
# Insert via the OLD draft syntax:
INSERT DATA { << <http://example.org/alice> <http://example.org/knows> <http://example.org/bob> >>
               <http://example.org/via> <http://example.org/x> . }

# Query it back:
SELECT ?tt WHERE { ?tt <http://example.org/via> <http://example.org/x> }
# => {"tt": {"type": "bnode", "value": "b0"}}     -- no longer "type":"triple"
```

Plain triples, wildcard matching, and `__contains__` under the old `rdf-star`
mode were all still fine — only the specific case of a triple term coming back
as a *value* in results was affected. But with `backend='rdf-1.2'` fully
confirmed working (see above) and strictly superior, there was no reason to
keep the older, now partially-broken mode around: `VALID_BACKENDS` is now just
`{'rdf-1.1', 'rdf-1.2'}`, `starlight/backends/native.py`'s `rewrite_12_to_backend()`
and its Jena-draft-bracket-conversion logic were deleted outright (nothing left
to rewrite - the sole remaining native backend speaks SPARQL 1.2 directly), and
`sparql_term()` lost its now-single-valued `backend` parameter. The two
regression tests that had briefly lived in
`tests/integration/test_fuseki_backend.py::TestFusekiNativeRdfStar` as `xfail`
were removed along with the class; `TestFusekiNativeRdf12` (below) is the
replacement.

Also confirmed working natively on **both** Fuseki 5.5.0 and Oxigraph 0.5.9,
via `backend='rdf-1.2'`, with zero rewriting needed (the endpoint receives the
SPARQL 1.2 query unchanged — see `starlight/backends/native.py`):
- `TRIPLE(s, p, o)` and `isTRIPLE(...)` (both engines agree on `"type":"triple"`
  in JSON results for `TRIPLE()`, and on boolean results for `isTRIPLE()`)
- `LANGDIR`, `hasLANGDIR`, `STRLANGDIR`, and dirLangString-aware `LANG`/`hasLANG`
- A `DirLangString` written via `sparql_term()`'s real `"text"@lang--dir"` form,
  read back correctly including through `CONSTRUCT` (which routes through the
  Turtle 1.2 parser)

**Also confirmed and fixed as a result of this testing**: the SPARQL 1.2 JSON
Results key for a dirLangString's base direction is **`"its:dir"`** (both
Fuseki and Oxigraph agree independently) — mirroring the `its:dir` attribute
RDF/XML 1.2 also uses. An earlier version of `_parse_json_term` in
`starlight/backends/native.py` guessed `"direction"`, which was wrong; this is
now fixed and verified, not a guess. See `tests/unit/test_dirlangstring.py::TestNativeBackend`
and `tests/integration/test_fuseki_backend.py::TestFusekiRdf12SparqlFunctions`/
`test_oxigraph_backend.py::TestOxigraphRdf12SparqlFunctions`.

*Original note, kept for history: "Jena 5.4+ introduced experimental RDF 1.2
support. If a future Fuseki release accepts the final `<<( s p o )>>` syntax
natively, no code changes are needed — developers simply switch the backend
flag. Verify against a running Fuseki instance when a stable RDF 1.2 release is
available." — done.*

---

## Cross-backend behavior parity (in-memory vs Oxigraph vs Fuseki)

**Status: systematically tested 2026-07-16** with a live three-way comparison script (13 scenarios run identically against the default in-memory rdf-1.1 backend, `backend='rdf-1.2'` against Oxigraph 0.5.9, and `backend='rdf-1.2'` against Fuseki 5.5.0). 8/13 matched immediately; the other 5 turned out to be 3 real bugs (fixed same day, isolated to the in-memory backend's SPARQL 1.2→1.1 rewriter) and 2 legitimate, deliberate architectural differences.

**Bugs found and fixed** (all in `starlight/query/sparql12_to_11.py`):

1. **`TRIPLE(s,p,o)` (or a bare `<<( s p o )>>`) used directly in a SELECT projection with no `BIND`** — e.g. `SELECT (TRIPLE(<a>,<b>,<c>) AS ?t) WHERE {}`. `_rewrite_group_content`'s pending-pattern flushing assumed a `<<( )>>` would always be followed by a `.` or `}` in the *same* scope shortly after; when it appears before the WHERE clause's own `{`, the scan recurses into that block as an opaque unit and never flushes the pending patterns there, so they fell through to the end-of-string handler and got appended *after* the query's closing brace — syntactically invalid SPARQL, a `ParseException`. Fixed by injecting any patterns still pending when the first `{}` block is encountered as a prefix to that block's own content (the same one `_rewrite_triple_functions` already does for `SUBJECT`/`PREDICATE`/`OBJECT` in this position, just via a different mechanism).
2. **`isTRIPLE(TRIPLE(...))` / `isTripleTerm(TRIPLE(...))`** — a nested-expression argument, not a bare variable. `_IS_TT_RE`'s regex only ever matched `isTRIPLE(?x)`; run at its original point in the pipeline (before `<<( )>>` had been reduced to a variable), it silently failed to match the nested form, leaving literal `isTRIPLE(...)` text in the output for the *later* pass to walk straight past — the SPARQL 1.1 engine doesn't know that function name. Fixed by moving the substitution to run last, after every other pass has had a chance to reduce a nested `TRIPLE(...)`/`<<( )>>` argument down to a plain variable, and re-checking the regex fresh at that point rather than trusting the early (pre-rewrite) detection flag.
3. **A `"text"@lang--dir` literal written directly in a query** (as opposed to a variable bound from already-stored data, which worked already) — e.g. `LANGDIR("hi"@en--rtl)`. Nothing rewrote the *lexical form* itself, only the function-call wrappers around it, so it reached rdflib's SPARQL 1.1 parser unchanged and failed on the `--` it doesn't understand. Fixed with a new early pass, `_rewrite_dirlang_literals()`, that finds every such literal (any quote style) anywhere in the query text and rewrites it to a call to the same registered `dirlang:` constructor function `STRLANGDIR()` already uses.

Fixing bug 2 also surfaced a **pre-existing, independent rdflib limitation**, unrelated to this codebase: `EXISTS {...} && ...` raises an internal exception (`"What do I do with this CompValue?"`) when used inside a `(expr AS ?var)` position (`SELECT` projection or `BIND`), while the identical expression works fine inside `FILTER(...)`. Reproduced with a bare `rdflib.Graph()`, no StarlightGraph involved. Every prior `isTripleTerm()`/`isTRIPLE()` test happened to only ever use it inside `FILTER`, so this had never been triggered before. Worked around (not just avoided) by dropping the `EXISTS` half of the check entirely: `STRSTARTS(STR(?x), TT_NS_PREFIX)` alone is sufficient and correct, since every `TT_NS`-prefixed URIRef is created exclusively by `_intern_tt()`, which always writes its `rdf:subject`/`predicate`/`object` encoding triples in the same call — there's no state where the prefix matches without them. This also matches every *other* `TT_NS` membership check already in this codebase (`_is_encoding_triple`, `_restore()`, `_build_registry_from_store()`), none of which do a separate existence check either.

**`STRLANGDIR("x","en","sideways")` (invalid direction) — resolved 2026-07-16: changed to match native soft-failure semantics.** Originally raised a hard Python `ValueError` on the in-memory backend while producing a silently unbound variable on native backends (standard SPARQL "type error in expression → unbound" semantics) — confirmed as a real, concrete difference via a live multi-row example: a query selecting three rows where only the middle one has a bad direction returns all three rows on Oxigraph/Fuseki (the bad row just has that one variable missing) but raised and returned *zero* rows on the in-memory backend, discarding the two good ones along with the bad one. `_dirlang_construct_fn` now raises `rdflib.plugins.sparql.sparql.SPARQLError` instead of `ValueError` - rdflib's `evalExtend` (which handles `BIND`/`SELECT`-projection evaluation) specifically catches `SPARQLError` and converts it to "leave the variable unbound for this solution"; a plain `ValueError` isn't caught and propagates as a hard crash of the whole query. This was a deliberate choice to prioritize resilience (one bad value degrades gracefully) over the "fail fast with a clear diagnostic" behavior the original design favored - a real tradeoff, decided in favor of matching real engines rather than an oversight. See `tests/unit/test_dirlangstring.py::TestSparqlFunctions::test_strlangdir_invalid_direction_does_not_abort_other_rows` for the multi-row regression test.

**`TRIPLE(a,b,c)`/`<<( a b c )>>` used as a value with all components ground — resolved 2026-07-16: now constructs, matching native "always constructible" semantics.** Previously, on the in-memory backend, a *ground* (variable-free) triple term used as a value (SELECT projection, `BIND`) had *matching* semantics, not *constructing* semantics: if `(a,b,c)` had never been registered anywhere in the graph, the query returned zero rows instead of the value. Native backends have no registry at all — a triple term is just a value, always constructible, exactly like an IRI that isn't in the graph is still a valid term to ask about. Explicit design direction for the fix: *"we certainly dont want a query asking about a triple that does not exist to cause that triple to exist. but we should be able to handle such a query similar to how a query would act about an IRI that did not exist."* Two things had to both be true simultaneously, which is why this wasn't just "always register on construction": (1) constructing the value must have **zero side effects** — it must not write anything to the graph or its registry, and (2) *graph-pattern matching* on a ground triple term (e.g. a reverse `rdf:reifies` lookup, or `<<( ?s ?p ?o )>>` enumeration) must still require the term to actually exist, unchanged from before.

The fix, in `starlight/query/sparql12_to_11.py`'s `_rewrite_triple_term()`: a fully-ground `<<( s p o )>>` (recursively, including nested ground triple terms) is now rewritten to `BIND(<tt#fn/hash>(s, p, o) AS ?__ttN)` — a pure, content-addressed hash computation with no graph read or write — instead of the old `?__ttN rdf:subject s . ?__ttN rdf:predicate p . ?__ttN rdf:object o .` matching pattern. A triple term with *any* variable component keeps the old matching-pattern behavior unchanged, since that's a lookup/enumeration, not a value construction. The registered `TT_HASH_FN` SPARQL function (which already existed, for `CONSTRUCT`-template minting) now also calls a new `remember_tt_hash()` (in `starlight/model/encoding.py`) as a side effect at *query-evaluation* time (after rdflib has resolved prefixes) — populating a process-wide, deterministic memo so `StarlightGraph._restore()` can still reconstruct a proper `TripleTerm` object for a hash that was computed but never written to any graph's own `_tt_nodes` registry. Ground `BIND`s are hoisted to the very start of the `WHERE` clause (a new `state.pending_ground_binds`, distinct from the existing template-minting `state.pending_binds` which goes at the *end* — see the docstring on `_rewrite_construct_query` for why the two need opposite placement) so they precede any statement that consumes the resulting variable in the same textual position, e.g. `?stmt rdf:reifies <<( :a :b :c )>> .`.

Fixing this surfaced two more real, independent bugs during triage, both also fixed same day:
- `starlight/query/sparql_api.py`'s `_restore_sparql12_in_tree()` (used by `parseQuery`/`parseUpdate` to reconstruct `TripleTerm` nodes in the parse tree) only recognized the old rdf:subject/predicate/object matching-triple encoding shape, not the new `BIND(tt_hash(...) AS ?__ttN)` shape — so ground triple terms silently stopped round-tripping through the parse-tree API. Fixed by also detecting `Bind` nodes whose expression is a call to the registered hash function (unwrapping rdflib's no-op `ConditionalOrExpression → ... → MultiplicativeExpression` single-child wrapper ladder to reach the actual `Function` CompValue).
- `_inject_ground_binds_into_where()` located the injection point by searching for the literal `WHERE {` text — but the `WHERE` keyword is optional in SPARQL for `SELECT`/`ASK`/`DESCRIBE` (e.g. plain `ASK { ... }`), so any ground triple term inside such a query silently failed to get its `BIND` injected at all, leaving `?__ttN` completely unbound and matching everything — e.g. `ASK { GRAPH <g> { ?stmt rdf:reifies <<( :nobody :knows :nobody )>> . } }` incorrectly returned `true` on a graph containing *any* `rdf:reifies` triple, not just one involving `:nobody`. Fixed by falling back to the first top-level `{` in the query text when no explicit `WHERE` keyword is found (safe: neither the prologue nor a `SELECT` variable list/dataset clause can contain a `{`).

Regression tests: `tests/unit/test_sparql12_to_11.py` (rewriter-level, including the pre-existing `TestParseQueryTripleTermSubject`/`Object`/`NestedTripleTerm`/`OptionalBlock` classes in `test_sparql12_parse.py` which exercise the parse-tree reconstruction), `tests/unit/test_sparql12_query.py::TestQ21` (end-to-end: zero side effects on construction, matching still requires registration, nested ground terms, mixed ground/variable unaffected, `isTRIPLE()` on an unregistered value, `CONSTRUCT`-template minting unaffected), `tests/unit/test_dataset_query.py::TestAsk::test_ask_false_when_no_match` (the `ASK`-without-`WHERE` regression).

---

## rdflib 8 Compatibility

rdflib 8.0.0a0 (pre-release) was tested; Revisit when a stable release arrives.

---

## `rdf:dirLangString` (RDF 1.2 base-direction-tagged literals)

**Status: implemented (2026-07-16).** `"text"@lang--dir` (e.g. `"مرحبا"@ar--rtl`) is
supported end to end. This surfaced from the starShacl side while closing SHACL
1.2 Core's changelog (Issue 737, referenced by `sh:uniqueLang`) — see starShacl's
`docs/shacl12-gap-matrix.md` (`rdf:dirLangString` row) for the discovery context;
`sh:uniqueLang` itself is still direction-unaware and is the actual follow-up
this unblocks on the starShacl side.

**Encoding**: `starlight/model/dirlangstring.py`'s `DirLangString(value, language,
direction)` is the public value type — analogous to `TripleTerm`, immutable,
value-typed (`__eq__`/`__hash__` by `(value, language, direction)`), language tag
case-folded per RDF 1.2 Concepts sec 3.4.1. Internally it's a plain
`rdflib.Literal` whose `datatype=` URI packs `(language, direction)` — e.g.
`https://github.com/hidden-graph/rdflib-starlight/ns/dirlang#en--rtl` — since
`Literal(text, lang="en--rtl")` raises (rdflib's langtag validator has no notion
of `--dir`) but validation never fires for `datatype=`. Unlike `TripleTerm`,
this needs **no registry**: the encoding is a pure function of the value itself
(no side-table of rdf:subject/predicate/object triples), so decoding happens
lazily wherever `StarlightGraph._restore()` already runs — no analogue of
`_build_registry_from_store()` was needed.

**Where it's wired in**:
- `starlight/graph/starlight_graph.py` — `_coerce_tt`/`_coerce_tt_read` encode on
  write, `_restore()` decodes on read; `_needs_encoding()` (renamed from
  `_is_tt_like` at two call sites) recognizes it for `triples_choices()`,
  `initBindings`, and nesting inside a `TripleTerm`'s object. Subject position is
  rejected the same way a `TripleTerm` is.
- Parsers/serializers: Turtle 1.2, N-Triples 1.2, N-Quads 1.2 (and TriG 1.2,
  which reuses the Turtle parser/serializer per named graph) support the real
  `"text"@lang--dir` lexical form natively. RDF/XML 1.2 and TriX 1.2 use their
  existing `rdf:datatype`/`typedLiteral[datatype=]` mechanisms with the internal
  dirlang: URI (no langtag validation on that path either). JSON-LD 1.2 uses
  `{"@value": ..., "@type": "<dirlang-uri>"}` rather than JSON-LD 1.1's native
  `@direction` keyword, since rdflib's JSON-LD codec (RDF 1.1) has no concept of
  `@direction` and would silently drop it — `@type` round-trips through
  rdflib's real parser unchanged.
- SPARQL: `starlight/query/sparql12_to_11.py` adds `LANGDIR(?x)`, `hasLANGDIR(?x)`,
  and `STRLANGDIR(lex, lang, dir)` (SPARQL 1.2 Query sec 17.4.2), and upgrades
  `LANG(?x)`/adds `hasLANG(?x)` so both also recognize a dirLangString the way
  they already handle a plain `rdf:langString`. `LANGDIR`/`hasLANGDIR`/`LANG`/
  `hasLANG` rewrite to plain SPARQL 1.1 expression built-ins (`DATATYPE`/`STR`/
  `STRSTARTS`/`STRAFTER`/`STRBEFORE`/`IF`). `STRLANGDIR` rewrites to a registered
  custom function (`DIRLANG_CONSTRUCT_FN`, same pattern as `TT_HASH_FN`) rather
  than a pure expression, so a malformed direction argument raises immediately
  at query time instead of silently building a bad value. `_rewrite_dirlang_and_strlangdir()`
  is a recursive-descent rewriter (like `_rewrite_triple_calls`) — every argument
  is rewritten before being spliced into its enclosing call, so arbitrary nesting
  (`LANGDIR(STRLANGDIR(...))`, `hasLANGDIR(IF(..., ?x, ?y))`) resolves correctly,
  not just a bare variable.

**Known limitations, not addressed**:
- RDF 1.2's "1.2-basic" (no dirLangString/no triple terms) conformance level
  isn't modeled — starlight has no opt-out mode. Low priority, no known use case
  blocked.

~~Native backends: the exact SPARQL 1.2 JSON Results key for dirLangString's
base direction was unverified~~ — **resolved 2026-07-16**, see the "Fuseki RDF
1.2 Native Syntax" section above: confirmed as `"its:dir"` against live Fuseki
5.5.0 and Oxigraph 0.5.9, and `starlight/backends/native.py` was corrected from
the earlier `"direction"` guess.

Tests: `tests/unit/test_dirlangstring.py`.
