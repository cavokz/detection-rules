# Copyright Elasticsearch B.V. and/or licensed to Elasticsearch B.V. under one
# or more contributor license agreements. Licensed under the Elastic License
# 2.0; you may not use this file except in compliance with the Elastic License
# 2.0.

"""Functions for generating event documents that would trigger a given rule."""

import sys
from typing import List
import eql

# https://stackoverflow.com/questions/7204805/how-to-merge-dictionaries-of-dictionaries/7205107#7205107
def merge_dicts(a, b, path=None):
    "merges b into a"
    if path is None:
        path = []
    for key in b:
        if key in a:
            if isinstance(a[key], dict) and isinstance(b[key], dict):
                merge_dicts(a[key], b[key], path + [str(key)])
            else:
                a[key] = b[key]
        else:
            a[key] = b[key]
    return a

def emit_events(node: eql.ast.BaseNode) -> List[str]:
    try:
        return emitters[type(node)](node)
    except KeyError:
        sys.stderr.write(f"##############################\n")
        sys.stderr.write(f"{node}\n")
        sys.stderr.write(f"{type(node)}\n")
        sys.stderr.write(f"{dir(node)}\n")
        sys.exit(1)

def emit_Field(node: eql.ast.Field, value):
    for part in reversed([node.base] + node.path):
        value = { part: value }
    return value

def emit_Or(node: eql.ast.And):
    doc = {}
    if type(node.terms) != list:
        raise NotImplementedError(f"Unsupported terms type: {type(node.terms)}")
    for term in node.terms:
        term_docs = emit_events(term)
        if len(term_docs) > 1:
            raise NotImplementedError("Unsuported multi-event term")
        doc.update(term_docs[0])
    return [doc]

def emit_And(node: eql.ast.And):
    doc = {}
    if type(node.terms) != list:
        raise NotImplementedError(f"Unsupported terms type: {type(node.terms)}")
    for term in node.terms:
        term_docs = emit_events(term)
        if len(term_docs) > 1:
            raise NotImplementedError("Unsuported multi-event term")
        merge_dicts(doc, term_docs[0])
    return [doc]

def emit_Comparison(node: eql.ast.Comparison):
    ops = {
        eql.ast.String: {
            "==": lambda s: s,    "!=": lambda s: "!" + s,
        },
        eql.ast.Number: {
            "==": lambda n: n,    "!=": lambda n: n + 1,
            ">=": lambda n: n,    "<=": lambda n: n,
             ">": lambda n: n + 1, "<": lambda n: n - 1,
        },
        eql.ast.Boolean: {
            "==": lambda b: b,    "!=": lambda b: not b,
        }
    }

    if type(node.left) != eql.ast.Field:
        raise NotImplementedError(f"Unsupported LHS type: {type(node.left)}")
    if type(node.right) not in (eql.ast.String, eql.ast.Number, eql.ast.Boolean):
        raise NotImplementedError(f"Unsupported RHS type: {type(node.left)}")

    value = ops[type(node.right)][node.comparator](node.right.value)
    doc = emit_Field(node.left, value)
    return [doc]

def emit_EventQuery(node: eql.ast.EventQuery):
    if type(node.event_type) != str:
        raise NotImplementedError(f"Unsupported event_type type: {type(node.event_type)}")
    docs = emit_events(node.query)
    if node.event_type != "any":
        for doc in docs:
            doc.update({"event": { "category": node.event_type }})
    return docs

def emit_PipedQuery(node: eql.ast.PipedQuery):
    if node.pipes:
        raise NotImplementedError("Pipes are unsupported")
    return emit_events(node.first)

emitters = {
    eql.ast.Or: emit_Or,
    eql.ast.And: emit_And,
    eql.ast.Comparison: emit_Comparison,
    eql.ast.EventQuery: emit_EventQuery,
    eql.ast.PipedQuery: emit_PipedQuery,
}

def _emit_events_query(query: str) -> List[str]:
    """
    >>> _emit_events_query('process where process.name == "regsvr32.exe"')
    '[{"event": {"category": "process"}, "process": {"name": "regsvr32.exe"}}]'
    >>> _emit_events_query('process where process.name != "regsvr32.exe"')
    '[{"event": {"category": "process"}, "process": {"name": "!regsvr32.exe"}}]'
    >>> _emit_events_query('process where process.pid == 0')
    '[{"event": {"category": "process"}, "process": {"pid": 0}}]'
    >>> _emit_events_query('process where process.pid != 0')
    '[{"event": {"category": "process"}, "process": {"pid": 1}}]'
    >>> _emit_events_query('process where process.pid >= 0')
    '[{"event": {"category": "process"}, "process": {"pid": 0}}]'
    >>> _emit_events_query('process where process.pid <= 0')
    '[{"event": {"category": "process"}, "process": {"pid": 0}}]'
    >>> _emit_events_query('process where process.pid > 0')
    '[{"event": {"category": "process"}, "process": {"pid": 1}}]'
    >>> _emit_events_query('process where process.pid < 0')
    '[{"event": {"category": "process"}, "process": {"pid": -1}}]'
    >>> _emit_events_query('process where process.code_signature.exists == true')
    '[{"event": {"category": "process"}, "process": {"code_signature": {"exists": true}}}]'
    >>> _emit_events_query('process where process.code_signature.exists != true')
    '[{"event": {"category": "process"}, "process": {"code_signature": {"exists": false}}}]'
    >>> _emit_events_query('any where network.protocol == "some protocol"')
    '[{"network": {"protocol": "some protocol"}}]'
    >>> _emit_events_query('process where process.name == "regsvr32.exe" and process.parent.name == "cmd.exe"')
    '[{"event": {"category": "process"}, "process": {"name": "regsvr32.exe", "parent": {"name": "cmd.exe"}}}]'
    >>> _emit_events_query('process where process.name == "regsvr32.exe" or process.parent.name == "cmd.exe"')
    '[{"event": {"category": "process"}, "process": {"parent": {"name": "cmd.exe"}}}]'

    """
    import json

    with eql.parser.elasticsearch_syntax, eql.parser.ignore_missing_functions:
        return json.dumps(emit_events(eql.parse_query(query)), sort_keys=True)

if __name__ == "__main__":
    import doctest
    doctest.testmod()
