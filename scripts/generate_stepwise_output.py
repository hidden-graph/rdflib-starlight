import os
import sys
import csv
from pathlib import Path

# Import the parser
sys.path.insert(0, str(Path(__file__).parent.parent))
from starlight.parsers.ttl_parser import StarlightTurtleParser

def clean_nt(nt_text):
    nt_text = nt_text.replace('_:anon', '_:')
    nt_text = nt_text.replace('http://example/', ':')
    nt_text = nt_text.replace('http://www.w3.org/1999/02/22-rdf-syntax-ns#', 'rdf:')
    return nt_text

def main():
    manifest_path = Path('w3c_turtle_tests/manifest.csv')
    out_path = Path('w3c_turtle_tests/w3c_test_output.txt')
    parser = StarlightTurtleParser()
    with open(manifest_path, newline='') as csvfile, open(out_path, 'w') as outfile:
        outfile.write('# W3C Turtle 1.2 Stepwise Test Output\n')
        outfile.write('# This file is regenerated step by step for each test in the manifest.\n\n')
        reader = csv.DictReader(csvfile)
        for i, row in enumerate(reader):
            test = row['test_name']
            ttl_file = Path('w3c_turtle_tests') / row['ttl_file']
            nt_file = Path('w3c_turtle_tests') / row['nt_file']
            ttl_text = ttl_file.read_text(errors='replace')
            try:
                g = parser.parse(ttl_text)
                parser_output = clean_nt(g.serialize(format='nt'))
            except Exception as e:
                parser_output = f'[parser error: {e}]'
            if nt_file.exists():
                nt_text = nt_file.read_text(errors='replace')
                cleaned_nt = clean_nt(nt_text)
            else:
                cleaned_nt = '[NT file missing]'
            outfile.write(f'TEST: {test}\n')
            outfile.write('INPUT:\n')
            outfile.write(ttl_text.strip() + '\n\n')
            outfile.write('OUTPUT:\n')
            outfile.write(parser_output.strip() + '\n\n')
            outfile.write('NT:\n')
            outfile.write(cleaned_nt.strip() + '\n\n')

if __name__ == '__main__':
    main()
