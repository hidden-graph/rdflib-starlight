# Starlight Future Enhancements

---

## Fuseki RDF 1.2 Native Syntax

Jena 5.4+ introduced experimental RDF 1.2 support. If a future Fuseki release accepts the final `<<( s p o )>>` syntax natively, no code changes are needed — developers simply switch the backend flag:

```python
# Current: Fuseki rdf-star draft syntax << s p o >>
g = StarlightGraph(backend='rdf-star', query_url=..., update_url=...)

# Future: Fuseki with native RDF 1.2 <<( s p o )>> syntax
g = StarlightGraph(backend='rdf-1.2', query_url=..., update_url=...)
```

Verify against a running Fuseki instance when a stable RDF 1.2 release is available.

---

## rdflib 8 Compatibility

rdflib 8.0.0a0 (pre-release) was tested; Revisit when a stable release arrives.
