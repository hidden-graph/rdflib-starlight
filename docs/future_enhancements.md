# Starlight Future Enhancements

*Last reviewed: 2026-07-17*

---

## Deferred / open follow-ups

- **`starlight/query/sparql12_to_11.py` complexity.** Still the single most complex module in the codebase — a ~1,100-line hand-rolled, multi-pass text scanner implementing the SPARQL 1.2→1.1 rewrite pipeline. A 2026-07-17 duplication review deliberately left it untouched: restructuring a working, fuzz-tested, heavily-exercised piece of logic purely for complexity's sake carries real regression risk without a clearly corresponding benefit. Worth a dedicated look later — e.g. splitting `_rewrite_sparql12_to_11_tracked` into named per-concern passes with clearer sequencing/dependency documentation — without risking the correctness properties the fuzz suite and cross-backend parity tests currently protect.

- **rdflib 8 compatibility.** Currently built on and tested against rdflib 7.6.0 (`pyproject.toml` requires `rdflib>=7.0`). rdflib 8.0.0a0 (pre-release) was tested too; revisit compatibility when a stable rdflib 8 release ships.

- **RDF serialization of SPARQL queries.** A genuine new feature, not a gap - needs design (representation, integration point) before starting.

- **More examples.** Only two exist today; no example covers `StarlightDataset` (multi-graph). Decide what's worth adding.

---

## Keeping in step with RDF 1.2/SPARQL 1.2 as the spec finalizes

RDF 1.2 was at **Candidate Recommendation** (published 2026-04-07) as of this writing — not yet a final W3C Recommendation. Everything in this project (the gap analysis, the rewriter, the format modules) is checked against that CR-stage text. This project's own stated purpose (README: "intended to remain relevant until rdflib is updated to incorporate the final RDF 1.2 specification") means it has a deliberately limited lifespan, and needs periodic re-checking rather than a one-time gap analysis. Concrete steps for whoever picks this up as the spec progresses:

1. **Re-run the gap analysis at each W3C stage transition** (CR → PR → REC). CR-stage text can still change in response to implementation/horizontal-review feedback before Proposed Recommendation; re-diff `docs/rdf12_sparql12_gap_analysis.md` against the current editor's draft whenever the spec's status changes, not just once. `docs/spec_snapshots/refresh_snapshots.py` automates the "what actually changed" half of that: it re-fetches all seven tracked documents and overwrites the saved snapshots, so `git diff docs/spec_snapshots/` shows exactly what moved since the last review instead of requiring a full re-read.
2. **Watch the CR exit criteria / implementation report.** The RDF-star Working Group's CR exit requires a set of independent conforming implementations. Whichever engines end up counted (Oxigraph and Fuseki are the two this project already tracks) are worth re-verifying starlight's rewriter against each time one of them ships a release claiming closer conformance — a live three-way comparison against the in-memory backend (see `tests/integration/test_cross_backend_parity.py`) is the reusable tool for that, not a one-off.
3. **Watch for a real JSON-LD RDF-1.2 companion spec.** If the JSON-LD Working Group ever publishes an RDF-1.2-aware revision with its own native representation for quoted/triple terms, replace `starlight/serializers/jsonld12.py` and `starlight/parsers/jsonld12.py`'s invented `rdf:TripleTerm` convention with the real one, and update the module's docstring and the callout in `docs/starlight_vs_rdflib.md` accordingly (see "Formats with no real spec target" in the gap analysis). TriX has no standards body actively developing it, so `trix12` is unlikely to ever gain a real target to converge on — its "starlight convention, not a spec" status is probably permanent, and the documentation callout is the whole fix rather than a placeholder for a future code change.
4. **Once rdflib ships native RDF 1.2 support** — re-evaluate this project's continued existence, per its own stated scope. At that point: (a) consider deprecating starlight's SPARQL 1.2→1.1 rewriter and in-memory triple-term encoding in favor of delegating straight to rdflib, and (b) check whether the `turtle12`/`nt12`/`nq12`/`trig12`/`rdfxml12` format modules can be dropped in favor of rdflib's own native parsers/serializers.
