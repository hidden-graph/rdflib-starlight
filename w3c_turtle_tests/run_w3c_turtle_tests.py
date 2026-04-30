
import os
import csv


# Ensure starlight is importable

import sys
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(TEST_DIR, "..")))
from starlight.parsers.ttl_parser import StarlightTurtleParser

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(TEST_DIR, "manifest.csv")
OUTPUT_FILE = os.path.join(TEST_DIR, "w3c_test_output.txt")
SEPARATOR = "\n---\n"

def run_test(test, output_handle):
    print("[DEBUG] Entered run_test")
    try:
        test_name, test_type, ttl_file, nt_file, *_ = test
        print(f"[DEBUG] test_name={test_name}, ttl_file={ttl_file}")
        ttl_path = os.path.join(TEST_DIR, ttl_file) if ttl_file else None
        if not ttl_path:
            print(f"Skipping test {test_name}: missing .ttl file reference.")
            return True
        # Write test name
        output_handle.write(f"TEST: {test_name}\n")
        print(f"[DEBUG] Wrote test name: {test_name}")
        # Write input
        with open(ttl_path, "r") as inf:
            input_data = inf.read()
        output_handle.write("INPUT:\n")
        output_handle.write(input_data)
        if not input_data.endswith("\n"):
            output_handle.write("\n")
        print(f"[DEBUG] Wrote input for: {test_name}")
        # Parse and write output
        output_handle.write("OUTPUT:\n")
        try:
            parser = StarlightTurtleParser()
            graph = parser.parse(input_data)
            # Serialize output as TriG and remove the graph name
            trig_str = graph.serialize(format="trig")
            lines = trig_str.splitlines()
            prefix_lines = [line for line in lines if line.strip().startswith("@prefix")]
            # Find the first '{' and last '}'
            try:
                start_idx = next(i for i, line in enumerate(lines) if '{' in line)
                end_idx = len(lines) - 1 - next(i for i, line in enumerate(reversed(lines)) if '}' in line)
                content_lines = lines[start_idx+1:end_idx]
            except StopIteration:
                content_lines = []
            for line in content_lines:
                output_handle.write(line + "\n")
            output_handle.write("\n")
            output_handle.write(SEPARATOR)
            print(f"[DEBUG] Wrote output for: {test_name} (PASS)")
            return True
        except Exception as parse_exc:
            output_handle.write(f"[ERROR] Exception in parser: {parse_exc}\n")
            output_handle.write(SEPARATOR)
            print(f"[DEBUG] Wrote output for: {test_name} (FAIL)")
            return False
    except Exception as e:
        print(f"[ERROR] Exception in run_test: {e}")
        output_handle.write(f"[ERROR] Exception in run_test: {e}\n")
        output_handle.write(SEPARATOR)
        return False

def main():
    print(f"[DEBUG] Opening manifest: {MANIFEST}")
    print(f"[DEBUG] About to open output file: {OUTPUT_FILE}")
    try:
        with open(MANIFEST, newline="") as mf, open(OUTPUT_FILE, "w") as outf:
            print(f"[DEBUG] Output file opened: {OUTPUT_FILE}")
            reader = csv.reader(mf)
            next(reader)  # skip header
            for row in reader:
                if row and not row[0].startswith("#"):
                    print(f"[DEBUG] Running test: {row[0]}")
                    result = run_test(row, outf)
                    print(f"[DEBUG] Finished test: {row[0]}")
                    if not result:
                        print(f"[DEBUG] Stopping on failure at test: {row[0]}")
                        break
    except Exception as e:
        print(f"[ERROR] Exception opening/writing output file: {e}")
    print(f"[DEBUG] Done main()")

if __name__ == "__main__":
    print("[DEBUG] Entering __main__ block")
    main()
