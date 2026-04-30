def copy_graph_with_prefixes(g):
    """Return a new rdflib.Graph with all triples and namespace bindings from g."""
    g2 = g.__class__()
    # Copy namespace bindings
    for prefix, ns in g.namespaces():
        g2.bind(prefix, ns)
    # Copy triples
    for t in g:
        g2.add(t)
    return g2
"""
Script to demonstrate round-trip parsing of Turtle 1.2 syntax:
- Reads each example file in samples/ttl12_examples/
- Parses with StarlightTurtleParser
- Serializes to Turtle 1.1 (rdflib-compatible)
- Writes grouped output to samples/ttl_1.2_output.txt
"""
from pathlib import Path
from starlight.parsers.ttl_parser import StarlightTurtleParser
import rdflib

example_dir = Path('samples/ttl12_examples')
output_path = Path('samples/ttl_1.2_output.txt')
example_files = sorted(example_dir.glob('ex*.ttl'))

parser = StarlightTurtleParser()

with open(output_path, 'w') as out:
    out.write('# Turtle 1.2 round-trip demonstration output\n\n')
    import re
    from rdflib import Graph, Namespace, BNode
    SL = Namespace("http://starlight.org/ns#")
    RDF = Namespace("http://www.w3.org/1999/02/22-rdf-syntax-ns#")

    def tripleterm_to_ttl12(text):
        # Robustly match [ a sl:TripleTerm ; ... ] blocks with any property order/whitespace
        def tripleterm_block_repl(match):
            block = match.group(0)
            # Extract subject, predicate, object
            subj = pred = obj = None
            # Remove brackets and split by semicolon
            inner = block[1:-1]
            for part in inner.split(';'):
                part = part.strip()
                if part.startswith('a sl:TripleTerm'):
                    continue
                if part.startswith('rdf:subject'):
                    subj = part[len('rdf:subject'):].strip()
                elif part.startswith('rdf:predicate'):
                    pred = part[len('rdf:predicate'):].strip()
                elif part.startswith('rdf:object'):
                    obj = part[len('rdf:object'):].strip()
            # If all found, return <<s p o>>
            if subj and pred and obj:
                return f"<<{subj} {pred} {obj}>>"
            return block

        # Regex to match [ a sl:TripleTerm ; ... ] blocks (non-greedy)
        pattern = re.compile(r"\[\s*a\s+sl:TripleTerm\s*;(.|\n)*?\]", re.DOTALL)
        return pattern.sub(tripleterm_block_repl, text)

    for i, ex_file in enumerate(example_files, 1):
        ttl12_text = ex_file.read_text(errors='replace').strip()
        out.write(f'# Example {i}\n')
        out.write('INPUT:\n')
        out.write(ttl12_text + '\n\n')
        try:
            g = parser.parse(ttl12_text)
            ttl11_output = g.serialize(format='turtle').strip()

            # --- New TTL 1.2 output logic ---
            g2 = copy_graph_with_prefixes(g)

            tripleterm_map = {}
            to_remove = set()
            # Helper to get prefixed name
            def to_prefixed(val, ns_manager):
                if isinstance(val, rdflib.term.URIRef):
                    return ns_manager.normalizeUri(val)
                elif isinstance(val, rdflib.term.Literal):
                    return str(val)
                elif isinstance(val, rdflib.term.BNode):
                    return str(val)
                else:
                    return str(val)

            ns_manager = g2.namespace_manager
            # Step 2: Find all triple term nodes (blank or named)
            for s, p, o in g2.triples((None, RDF.type, SL.TripleTerm)):
                subj = s
                pred = g2.value(subj, RDF.predicate)
                obj = g2.value(subj, RDF.object)
                subj2 = g2.value(subj, RDF.subject)
                # Use the exact identifier as it appears in Turtle output
                if isinstance(subj, rdflib.term.BNode):
                    subj_key = str(subj)
                    # Ensure it starts with '_:'
                    if not subj_key.startswith('_:'):
                        subj_key = f'_:{subj_key}'
                else:
                    subj_key = ns_manager.normalizeUri(subj)
                if subj2 and pred and obj:
                    tripleterm_map[subj_key] = f"<<{to_prefixed(subj2, ns_manager)} {to_prefixed(pred, ns_manager)} {to_prefixed(obj, ns_manager)}>>"
                for p2, o2 in g2.predicate_objects(subj):
                    to_remove.add((subj, p2, o2))
            # Step 3: Remove all triple term statements
            for t in to_remove:
                g2.remove(t)
            # Step 4: Remove all 'a sl:Reification' statements
            to_remove2 = set()
            for s, p, o in g2.triples((None, RDF.type, SL.Reification)):
                to_remove2.add((s, p, o))
            for t in to_remove2:
                g2.remove(t)
            # Step 5: Serialize and replace blank node IDs
            ttl12_output = g2.serialize(format='turtle').strip()
            # Helper: convert IRI to prefixed name if possible
            def iri_to_prefixed(iri, nsmap):
                iri = str(iri)
                for prefix, ns in nsmap.items():
                    if iri.startswith(ns):
                        return f"{prefix}:{iri[len(ns):]}"
                return iri

            # Build namespace map from graph
            nsmap = {str(p): str(ns) for p, ns in g2.namespaces()}
            # Try to replace all occurrences, including inside brackets
            import re
            print('DEBUG: tripleterm_map:', tripleterm_map)
            print('DEBUG: TTL 1.2 output before replacement:\n', ttl12_output[:500])
            for bnode, qt in tripleterm_map.items():
                # Replace as object: rdf:reifies _:si_2 [with trailing . ; , or whitespace]
                ttl12_output = re.sub(rf'(rdf:reifies\s+){re.escape(bnode)}(\s*[.;,\]])', rf'\1{qt}\2', ttl12_output)
                # Replace as object in []: rdf:reifies [ ]
                ttl12_output = re.sub(r'(rdf:reifies\s+)\[\s*\]', r'\1'+qt, ttl12_output)
                # Replace as subject (rare): ^_:si_2 ...
                ttl12_output = re.sub(rf'^{re.escape(bnode)}(\s)', rf'{qt}\1', ttl12_output, flags=re.MULTILINE)
            # Replace IRIs with prefixed names
            for prefix, ns in nsmap.items():
                if prefix == '': continue
                ttl12_output = ttl12_output.replace(ns, f'{prefix}:')
        except Exception as e:
            ttl11_output = f'[parser error: {e}]'
            ttl12_output = ttl11_output
        out.write('TTL 1.1 OUTPUT:\n')
        out.write(ttl11_output + '\n\n')
        out.write('TTL 1.2 OUTPUT (round-tripped):\n')
        out.write(ttl12_output + '\n\n')

        # --- True round-trip test: parse 1.2 output, serialize to 1.1 ---
        try:
            g_rt = parser.parse(ttl12_output)
            ttl11_rt_output = g_rt.serialize(format='turtle').strip()
        except Exception as e:
            ttl11_rt_output = f'[parser error: {e}]'
        out.write('TTL 1.1 OUTPUT (from 1.2 round-trip):\n')
        out.write(ttl11_rt_output + '\n\n')
