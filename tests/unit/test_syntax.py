"""
Unit tests for starlight.parsers.syntax.

Covers coerce_object, classify_statement, split_statements,
extract_fields, and expand_triple_set.
"""

import pytest
from starlight.parsers.syntax import (
    coerce_object,
    classify_statement,
    split_statements,
    extract_fields,
    expand_triple_set,
)


class TestCoerceObject:
    def test_true(self):      assert coerce_object('true') is True
    def test_false(self):     assert coerce_object('false') is False
    def test_integer(self):   assert coerce_object('42') == 42
    def test_negative(self):  assert coerce_object('-5') == -5
    def test_positive(self):  assert coerce_object('+3') == 3
    def test_float(self):     assert coerce_object('3.14') == 3.14
    def test_float_exp(self): assert coerce_object('1.5e2') == 150.0
    def test_string(self):    assert coerce_object(':foo') == ':foo'
    def test_whitespace(self):assert coerce_object('  42  ') == 42


class TestClassifyStatement:
    def test_at_prefix_lower(self):
        assert classify_statement('@prefix ex: <http://x/>') == 'prefix'

    def test_bare_prefix_upper(self):
        assert classify_statement('PREFIX ex: <http://x/>') == 'prefix'

    def test_at_base(self):
        assert classify_statement('@base <http://x/>') == 'base'

    def test_bare_base_upper(self):
        assert classify_statement('BASE <http://x/>') == 'base'

    def test_triple(self):
        assert classify_statement(':s :p :o .') == 'triple'

    def test_triple_with_iri_subject(self):
        assert classify_statement('<http://x/s> :p :o .') == 'triple'


class TestSplitStatements:
    def test_single_prefix(self):
        stmts = split_statements('@prefix ex: <http://example.org/>')
        assert len(stmts) == 1
        assert classify_statement(stmts[0]) == 'prefix'

    def test_two_triples(self):
        data = ':s :p :o .\n:a :b :c .\n'
        stmts = split_statements(data)
        assert len(stmts) == 2

    def test_prefix_then_triple(self):
        data = '@prefix ex: <http://example.org/>\nex:s ex:p ex:o .\n'
        stmts = split_statements(data)
        assert len(stmts) == 2
        assert classify_statement(stmts[0]) == 'prefix'
        assert classify_statement(stmts[1]) == 'triple'

    def test_multiline_triple(self):
        data = ':s\n    :p\n    :o .\n'
        stmts = split_statements(data)
        assert len(stmts) == 1
        assert classify_statement(stmts[0]) == 'triple'

    def test_annotation_statement(self):
        data = 'PREFIX : <http://example/>\n:s :p :o {| :ann :val |} .\n'
        stmts = split_statements(data)
        assert len(stmts) == 2

    def test_period_inside_string_not_split(self):
        data = ':s :p "hello.world" .\n'
        stmts = split_statements(data)
        assert len(stmts) == 1


class TestExtractFields:
    def test_prefix_at(self):
        fields = extract_fields('@prefix ex: <http://example.org/>', 'prefix')
        assert fields['prefix'] == 'ex'
        assert fields['iri'] == 'http://example.org/'

    def test_prefix_bare(self):
        fields = extract_fields('PREFIX ex: <http://example.org/>', 'prefix')
        assert fields['prefix'] == 'ex'

    def test_prefix_empty_local(self):
        fields = extract_fields('@prefix : <http://example.org/>', 'prefix')
        assert fields['prefix'] == ''

    def test_base(self):
        fields = extract_fields('@base <http://example.org/>', 'base')
        assert fields['iri'] == 'http://example.org/'

    def test_simple_triple(self):
        fields = extract_fields(':s :p :o .', 'triple', [0])
        ts = fields['triple_set']
        assert len(ts) == 1
        assert ts[0]['subject'] == ':s'
        assert ts[0]['predicate'] == ':p'
        assert ts[0]['object'] == ':o'

    def test_multiple_predicates(self):
        fields = extract_fields(':s :p :o ; :q :z .', 'triple', [0])
        ts = fields['triple_set']
        assert len(ts) == 2
        predicates = {t['predicate'] for t in ts}
        assert ':p' in predicates
        assert ':q' in predicates

    def test_multiple_objects(self):
        fields = extract_fields(':s :p :o , :o2 .', 'triple', [0])
        ts = fields['triple_set']
        assert len(ts) == 2
        objects = {t['object'] for t in ts}
        assert ':o' in objects
        assert ':o2' in objects

    def test_rdf_type_abbreviation(self):
        fields = extract_fields(':s a :Thing .', 'triple', [0])
        ts = fields['triple_set']
        assert ts[0]['predicate'] == 'a'

    def test_annotation_recorded(self):
        fields = extract_fields(':s :p :o {| :ann :val |} .', 'triple', [0])
        ts = fields['triple_set']
        assert ts[0].get('annotations') is not None

    def test_blank_node_subject_expanded(self):
        counter = [0]
        fields = extract_fields('[] :p :o .', 'triple', counter)
        ts = fields['triple_set']
        assert ts[0]['subject'].startswith('_:sl_')


class TestExpandTripleSet:
    def test_plain_triple_unchanged(self):
        ts = [{'subject': ':s', 'predicate': ':p', 'object': ':o'}]
        result = expand_triple_set(ts, [0])
        assert result == ts

    def test_blank_node_object_expands(self):
        ts = [{'subject': ':s', 'predicate': ':p', 'object': '[ :q :z ]'}]
        result = expand_triple_set(ts, [0])
        assert len(result) > 1
        assert result[0]['object'].startswith('_:sl_')

    def test_blank_node_inner_triple_present(self):
        ts = [{'subject': ':s', 'predicate': ':p', 'object': '[ :q :z ]'}]
        result = expand_triple_set(ts, [0])
        bnode = result[0]['object']
        inner = [t for t in result if t['subject'] == bnode]
        assert len(inner) == 1
        assert inner[0]['predicate'] == ':q'

    def test_empty_collection_becomes_nil(self):
        ts = [{'subject': ':s', 'predicate': ':p', 'object': '()'}]
        result = expand_triple_set(ts, [0])
        assert len(result) == 1
        assert result[0]['object'] == 'rdf:nil'

    def test_single_element_collection(self):
        ts = [{'subject': ':s', 'predicate': ':p', 'object': '( :a )'}]
        result = expand_triple_set(ts, [0])
        predicates = {t['predicate'] for t in result}
        assert 'rdf:first' in predicates
        assert 'rdf:rest' in predicates
        rest_triples = [t for t in result if t['predicate'] == 'rdf:rest']
        assert rest_triples[-1]['object'] == 'rdf:nil'

    def test_two_element_collection(self):
        ts = [{'subject': ':s', 'predicate': ':p', 'object': '( :a :b )'}]
        result = expand_triple_set(ts, [0])
        first_triples = [t for t in result if t['predicate'] == 'rdf:first']
        assert len(first_triples) == 2

    def test_nested_blank_in_collection(self):
        ts = [{'subject': ':s', 'predicate': ':p', 'object': '( [ :q :z ] )'}]
        result = expand_triple_set(ts, [0])
        predicates = {t['predicate'] for t in result}
        assert 'rdf:first' in predicates
        assert ':q' in predicates
