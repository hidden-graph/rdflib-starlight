"""Per-graph/dataset SPARQL query preparation cache.

``StarlightGraph.query()`` and ``StarlightDataset.query()`` both rewrite
SPARQL 1.2 triple-term syntax to SPARQL 1.1 (``rewrite_sparql12_to_11``) and
then hand the resulting text to rdflib, which parses it into a fresh SPARQL
algebra tree on every call. Callers that evaluate the same query text
repeatedly against an unmutated graph with only ``initBindings`` differing -
the exact shape of pySHACL's own SHACL-AF rule/constraint evaluation, which
calls ``.query()`` once per focus node per rule per iteration - redo that
rewrite+parse work every single time even though its result never changes
between those calls.

``prepare_query_cached`` caches the rewritten-and-parsed
``rdflib.plugins.sparql.sparql.Query`` object, keyed on the query text plus
the *effective* namespace mapping and base IRI - both of which rdflib's own
``prepareQuery`` bakes into the parsed query at parse time, so they're part
of what makes two calls equivalent, not just the query text. Passing an
already-prepared ``Query`` object instead of a string to ``Graph.query()``
is a first-class, documented rdflib capability (``Store.query()``'s own
type signature is ``Union[Query, str]``, and
``SPARQLProcessor.query()`` branches on exactly this), not a workaround -
so this is safe for any spec-compliant store, not just the default
in-memory one.
"""

from __future__ import annotations

from typing import Any, Mapping

from rdflib.plugins.sparql import prepareQuery
from rdflib.plugins.sparql.sparql import Query

from starlight.query.sparql12_to_11 import rewrite_sparql12_to_11


def prepare_query_cached(
    cache: dict[tuple[str, tuple, str | None], Query],
    query_text: str,
    effective_ns: Mapping[str, Any] | None,
    base: str | None,
) -> Query:
    """Return a prepared SPARQL ``Query`` for ``query_text``, reusing a
    previous preparation from ``cache`` if the same
    (query text, effective namespaces, base) was seen before.

    ``effective_ns`` must already be the namespace mapping that will
    actually be used - the caller's explicit ``initNs``, or its own bound
    namespaces if none was given - not ``None`` standing in for "resolve
    it later"; a cache keyed before that resolution would miss real
    differences (or worse, reuse a stale mapping) if a graph's bound
    namespaces change between calls with the same query text.
    """
    ns_key = tuple(sorted((str(k), str(v)) for k, v in effective_ns.items())) if effective_ns else ()
    cache_key = (query_text, ns_key, base)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    rewritten = rewrite_sparql12_to_11(query_text)
    prepared = prepareQuery(rewritten, initNs=dict(effective_ns) if effective_ns else {}, base=base)
    cache[cache_key] = prepared
    return prepared
