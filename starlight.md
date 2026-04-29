# starlight (rdflib-starlight) — Architecture & Implementation Guide

## Overview

starlight is a semantic extension layer over RDFLib that adds first-class support for:

- RDF-star (`<< s p o >>`)
- RDF 1.1 reification
- Named statement patterns (`~ :stmt1`)
- SPARQL-star parsing and rewriting

It is NOT a replacement for RDFLib. It is a translation + interpretation layer.

---

## Core Design Principles

### 1. Separation of concerns

| Layer | Responsibility |
|------|----------------|
| parsers | Convert RDF text → RDFLib graph + starlight model |
| model | Define RDF-star semantics (pure, no RDFLib dependency) |
| graph | Bridge RDFLib Graph ↔ starlight model |
| query | SPARQL-star parsing, rewriting, execution |
| serializers | Convert graph → RDF-star or RDF 1.1 reification |

---

### 2. Lossless semantics

The system must never lose information:
- RDF-star structures are preserved
- Reification mappings are reversible
- Named statements (`~`) retain identity binding

---

### 3. RDFLib remains the execution engine

All storage and SPARQL execution ultimately uses RDFLib.Graph.

---

# Package Structure

starlight/
    parsers/
    serializers/
    query/
    model/
    graph/

---

# Modules

## parsers
parse(data: str) -> Graph

## model
Triple, QuotedTriple, Statement, bind_statement()

## graph
add(), get_triples(), bind_reifier(), resolve_statement()

## query
parse(), rewrite(), execute()

## serializers
serialize(), to_turtle_star(), to_reification()

---

# Data Flow

INPUT → parsers → model → graph → query → serializers → OUTPUT
