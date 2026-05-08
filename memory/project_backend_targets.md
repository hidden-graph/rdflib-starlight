---
name: Backend store targets
description: Which RDF stores are planned as Phase 2 / Phase 3 backend targets
type: project
---

Target for RDF 1.2 native backend (Phase 3): **Oxigraph**

**Why:** Oxigraph is a Rust-based graph database with strong RDF 1.2 support and an active development trajectory.

**How to apply:** When designing the Case 2 (RDF 1.2 native) wire-format parsing layer and probe-and-dispatch logic, prototype against Oxigraph first. Two integration paths to evaluate:
- `pyoxigraph` directly (its own Python API, not rdflib-compatible)
- `rdflib-oxigraph` (wraps pyoxigraph as an rdflib Store plugin)

Need to determine whether `rdflib-oxigraph` exposes RDF 1.2 quoted-triple results through the rdflib Store interface or whether a direct `pyoxigraph` adapter is required.
