# Copyright Elasticsearch B.V. and/or licensed to Elasticsearch B.V. under one
# or more contributor license agreements. Licensed under the Elastic License
# 2.0; you may not use this file except in compliance with the Elastic License
# 2.0.

"""Functions for generating event documents that would trigger a given rule."""

import time
import random
import contextlib
from functools import wraps
from itertools import chain
from typing import List

from .ecs import get_schema, get_max_version
from .rule import AnyRuleData
from .utils import deep_merge
from .constraints import Constraints

__all__ = (
    "emit_docs",
    "get_ast_stats",
)

default_custom_schema = {
    "file.Ext.windows.zone_identifier": {
        "type": "long",
    },
    "process.parent.Ext.real.pid": {
        "type": "long",
    },
}

def ast_from_eql_query(query):
    import eql
    with eql.parser.elasticsearch_syntax:
        return eql.parse_query(query)

def ast_from_kql_query(query):
    import kql
    return kql.to_eql(query)

def ast_from_query(query):
    exceptions = []
    try:
        return ast_from_eql_query(query)
    except Exception as e:
        exceptions.append(("EQL", e))
    try:
        return ast_from_kql_query(query)
    except Exception as e:
        exceptions.append(("KQL", e))
    def rank(e):
        line = getattr(e[1], "line", -1)
        column = getattr(e[1], "column", -1)
        return (line, column)
    lang,error = sorted(exceptions, key=rank)[-1]
    raise ValueError(f"{lang} query error: {error}")

def ast_from_rule(rule):
    if rule.type not in ("query", "eql"):
        raise NotImplementedError(f"Unsupported rule type: {rule.type}")
    elif rule.language == "eql":
        return rule.validator.ast
    elif rule.language == "kuery":
        return rule.validator.to_eql() # shortcut?
    else:
        raise NotImplementedError(f"Unsupported query language: {rule.language}")

def emit_field(field, value):
    for part in reversed(field.split(".")):
        value = {part: value}
    return value

def docs_from_branch(branch, schema, timestamp=True):
    for t,solution in enumerate(branch.resolve(schema)):
        doc = {}
        for field,value in solution:
            if value is not None:
                deep_merge(doc, emit_field(field, value))
        if timestamp:
            deep_merge(doc, emit_field("@timestamp", int(time.time() * 1000) + t))
        yield doc

def emit_mappings(fields, schema):
    mappings = {}
    for field in fields:
        try:
            field_type = schema[field]["type"]
        except KeyError:
            field_type = "keyword"
        value = {"type": field_type}
        for part in reversed(field.split(".")):
            value = {"properties": {part: value}}
        deep_merge(mappings, value)
    return mappings

class emitter:
    ecs_version = get_max_version()
    ecs_schema = get_schema(version=ecs_version)
    schema = deep_merge(default_custom_schema, ecs_schema)

    emitters = {}
    mappings_fields = set()

    def __init__(self, node_type):
        self.node_type = node_type
        self.successful = 0
        self.total = 0

    def __call__(self, func):
        if self.node_type in self.emitters:
            raise ValueError(f"Duplicate emitter for {self.node_type}: {func.__name__}")
        self.emitters[self.node_type] = self

        @wraps(func)
        def wrapper(*args, **kwargs):
            self.total += 1
            ret = func(*args, **kwargs)
            self.successful += 1
            return ret

        self.wrapper = wrapper
        return wrapper

    @classmethod
    def emit(cls, node, negate=False):
        return cls.emitters[type(node)].wrapper(node, negate)

    @classmethod
    def get_ast_stats(cls):
        return {k.__name__: (v.successful, v.total) for k,v in cls.emitters.items()}

    @classmethod
    def docs_from_branches(cls, branches, timestamp=True):
        if not branches:
            raise ValueError("Cannot trigger with any document")
        return (docs_from_branch(branch, cls.schema, timestamp) for branch in branches)

    @classmethod
    def docs_from_ast(cls, ast, timestamp=True):
        branches = cls.emit(ast)
        return cls.docs_from_branches(branches, timestamp)


class SourceEvents:
    def __init__(self, ecs_version=get_max_version(), custom_schema=None):
        ecs_schema = get_schema(version=ecs_version)
        if custom_schema is None:
            custom_schema = default_custom_schema
        self.schema = deep_merge(custom_schema, ecs_schema)
        self.ecs_version = ecs_version
        self.branches = {}

    def add_query(self, query):
        ast = ast_from_query(query)
        branches = emitter.emit(ast)
        if not branches:
            raise ValueError(f"Query without branches")
        self.branches[query] = branches

    def add_rule(self, rule):
        ast = ast_from_rule(rule)
        branches = emitter.emit(ast)
        if not branches:
            raise ValueError(f"Query without branches")
        self.branches[rule] = branches

    def emit_mappings(self):
        fields = set()
        for branches in self.branches.values():
            for branch in branches:
                fields |= set(branch.fields())
        return emit_mappings(fields, self.schema)

def emit_docs(rule: AnyRuleData) -> List[str]:
    ast = ast_from_rule(rule)
    return list(chain(*emitter.docs_from_ast(ast)))


def get_ast_stats():
    return emitter.get_ast_stats()


# circular dependency
import detection_rules.events_emitter_eql  # noqa: E402
