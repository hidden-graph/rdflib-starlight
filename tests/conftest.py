"""
Shared fixtures for the starlight test suite.
"""

import pathlib
import pytest
from starlight.parsers.turtle_parser import StarlightTurtleParser

FIXTURES_DIR = pathlib.Path(__file__).parent / 'fixtures'


@pytest.fixture
def parser():
    return StarlightTurtleParser()


@pytest.fixture
def fixture_ttl():
    """Return a callable: fixture_ttl(name) reads tests/fixtures/<name>."""
    def _read(name):
        return (FIXTURES_DIR / name).read_text()
    return _read


@pytest.fixture
def parse(parser):
    """Return a callable: parse(data) → rdflib.Graph."""
    return parser.parse
