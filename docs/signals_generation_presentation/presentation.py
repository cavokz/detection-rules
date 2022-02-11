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
)

random.seed("presentation")

def emit(query, timestamp=False, draw=False):
    try:
        with eql.parser.elasticsearch_syntax:
            ast = eql.parse_query(query)
        branches = emitter.branches_from_ast(ast)
        docs = emitter.docs_from_branches(branches, timestamp)
    except Exception as e:
        print(e)
    if draw:
        display(draw_ast(ast), docs)
    else:
        display(docs)

def draw(query):
    try:
        return draw_ast(parse(query))
    except Exception as e:
        print(e)
