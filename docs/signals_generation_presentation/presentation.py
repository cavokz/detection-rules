# Copyright Elasticsearch B.V. and/or licensed to Elasticsearch B.V. under one
# or more contributor license agreements. Licensed under the Elastic License
# 2.0; you may not use this file except in compliance with the Elastic License
# 2.0.

"""Helper for the presentation."""

import os
import eql
import random

from IPython.display import display, HTML

presentation_dir = os.path.split(__file__)[0]
os.chdir(os.path.abspath(os.path.join(presentation_dir, "..", "..")))

from detection_rules.events_emitter import emitter
from detection_rules.ast_dag import draw_ast, Digraph

__all__ = (
    "emit",
    "draw",
    "draw_and_emit",
    "emit_and_draw",
)

random.seed("presentation")

def parse(query):
    with eql.parser.elasticsearch_syntax:
        return eql.parse_query(query)

def emit(query):
    try:
        return emitter.emit_docs(parse(query))
    except Exception as e:
        print(e)

def draw(query):
    try:
        return draw_ast(parse(query))
    except Exception as e:
        print(e)

def draw_and_emit(query):
    try:
        ast = parse(query)
        graph = draw_ast(ast)
        docs = emitter.emit_docs(ast)
        display(graph, docs)
    except Exception as e:
        print(e)

def emit_and_draw(query):
    try:
        ast = parse(query)
        graph = draw_ast(ast)
        docs = emitter.emit_docs(ast)
        display(docs, graph)
    except Exception as e:
        print(e)
