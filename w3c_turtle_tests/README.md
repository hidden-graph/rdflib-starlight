# Instructions for the W3C Turtle Test Suite Integration

This folder contains the full set of W3C RDF 1.1 Turtle conformance tests, organized for use with the local parser test harness.

- All .ttl and .nt files are direct copies from the official W3C test suite.
- The manifest.csv file lists all tests, their types, and expected results.
- See the test runner script for how to execute and validate tests.

Test Types:
- TestTurtleEval: .ttl input, .nt expected output (parser output must match)
- TestTurtlePositiveSyntax: .ttl input, must parse successfully
- TestTurtleNegativeSyntax: .ttl input, must fail to parse
- TestTurtleNegativeEval: .ttl input, must fail to produce expected triples

For more details, see: https://w3c.github.io/rdf-tests/rdf/rdf11/rdf-turtle/index.html
