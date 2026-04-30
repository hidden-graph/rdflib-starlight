
# W3C Turtle Test Suite Download Script (manifest.ttl version)
# Downloads all .ttl and .nt files referenced in manifest.ttl from the official W3C RDF 1.1 Turtle test suite.
# Run this script from the project root.

import os
import requests
import re

BASE_URL = "https://w3c.github.io/rdf-tests/rdf/rdf12/rdf-turtle/eval/"
MANIFEST_URL = BASE_URL + "manifest.ttl"
DEST_DIR = "w3c_turtle_tests"
MANIFEST_FILE = os.path.join(DEST_DIR, "manifest.csv")

def download_file(url, dest):
    if os.path.exists(dest):
        return
    r = requests.get(url)
    if r.status_code == 200:
        with open(dest, "wb") as f:
            f.write(r.content)
        print(f"Downloaded {url}")
    else:
        print(f"Failed to download {url}")

def main():
    os.makedirs(DEST_DIR, exist_ok=True)
    print(f"Fetching manifest from {MANIFEST_URL} ...")
    r = requests.get(MANIFEST_URL)
    manifest = r.text
    # Parse manifest line by line (state machine)
    tests = []
    current = {}
    for line in manifest.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        # Start of a test entry (trs:... rdf:type ...)
        m = re.match(r'trs:([\w\-]+)\s+rdf:type\s+([^ ;]+)\s*;', line)
        if m:
            if current:
                tests.append((current.get('name'), current.get('type'), current.get('ttl'), current.get('nt')))
            current = {'name': m.group(1), 'type': m.group(2), 'ttl': None, 'nt': None}
            continue
        # mf:action (ttl file)
        m = re.match(r'mf:action\s+<([^>]+\.ttl)>\s*;', line)
        if m and current:
            current['ttl'] = m.group(1)
            continue
        # mf:result (nt file)
        m = re.match(r'mf:result\s+<([^>]+\.nt)>\s*;', line)
        if m and current:
            current['nt'] = m.group(1)
            continue
    # Add last test
    if current:
        tests.append((current.get('name'), current.get('type'), current.get('ttl'), current.get('nt')))
    tests = [t for t in tests if t[2] or t[3]]  # Only keep tests with files
    print(f"Discovered {len(tests)} tests in manifest.")
    # Write manifest
    with open(MANIFEST_FILE, "w") as mf:
        mf.write("test_name,test_type,ttl_file,nt_file\n")
        for test_name, test_type, ttl_file, nt_file in tests:
            mf.write(f"{test_name},{test_type},{ttl_file or ''},{nt_file or ''}\n")
    # Download files
    for test_name, test_type, ttl_file, nt_file in tests:
        print(f"Test: {test_name} | Type: {test_type} | TTL: {ttl_file} | NT: {nt_file}")
        if ttl_file:
            print(f"  Downloading TTL: {ttl_file}")
            download_file(BASE_URL + ttl_file, os.path.join(DEST_DIR, ttl_file))
        if nt_file:
            print(f"  Downloading NT: {nt_file}")
            download_file(BASE_URL + nt_file, os.path.join(DEST_DIR, nt_file))

if __name__ == "__main__":
    main()
