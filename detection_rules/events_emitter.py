# Copyright Elasticsearch B.V. and/or licensed to Elasticsearch B.V. under one
# or more contributor license agreements. Licensed under the Elastic License
# 2.0; you may not use this file except in compliance with the Elastic License
# 2.0.

"""Functions for generating event documents that would trigger a given rule."""

import time
import random
import contextlib
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

custom_schema = {
    "file.Ext.windows.zone_identifier": {
        "type": "long",
    },
    "process.parent.Ext.real.pid": {
        "type": "long",
    },
}

class emitter:
    ecs_version = get_max_version()
    ecs_schema = get_schema(version=ecs_version)
    schema = deep_merge(custom_schema, ecs_schema)

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

        def wrapper(*args, **kwargs):
            self.total += 1
            ret = func(*args, **kwargs)
            self.successful += 1
            return ret

        self.wrapper = wrapper
        return wrapper

    @classmethod
    def add_mappings_field(cls, field):
        cls.mappings_fields.add(field)

    @classmethod
    def reset_mappings(cls):
        cls.mappings_fields = set()

    @classmethod
    def branches_from_ast(cls, node, negate=False):
        return cls.emitters[type(node)].wrapper(node, negate)

    @classmethod
    def get_ast_stats(cls):
        return {k.__name__: (v.successful, v.total) for k,v in cls.emitters.items()}

    @classmethod
    def emit_mappings(cls):
        mappings = {}
        for field in cls.mappings_fields:
            try:
                field_type = cls.schema[field]["type"]
            except KeyError:
                field_type = "keyword"
            value = {"type": field_type}
            for part in reversed(field.split(".")):
                value = {"properties": {part: value}}
            deep_merge(mappings, value)
        return mappings

    @classmethod
    def ast_from_rule(cls, rule):
        if rule.type not in ("query", "eql"):
            raise NotImplementedError(f"Unsupported rule type: {rule.type}")
        elif rule.language == "eql":
            return rule.validator.ast
        elif rule.language == "kuery":
            return rule.validator.to_eql() # shortcut?
        else:
            raise NotImplementedError(f"Unsupported query language: {rule.language}")

    @classmethod
    def emit_field(cls, field, value):
        cls.add_mappings_field(field)
        for part in reversed(field.split(".")):
            value = {part: value}
        return value

    @classmethod
    def docs_from_branch(cls, branch, timestamp=True):
        docs = []
        for t,constraints in enumerate(branch):
            doc = {}
            for field,value in constraints.resolve(cls.schema):
                if value is not None:
                    deep_merge(doc, cls.emit_field(field, value))
            if timestamp:
                deep_merge(doc, cls.emit_field("@timestamp", int(time.time() * 1000) + t))
            docs.append(doc)
        return docs

    @classmethod
    def docs_from_branches(cls, branches, timestamp=True):
        if not branches:
            raise ValueError("Cannot trigger with any document")
        return [cls.docs_from_branch(branch, timestamp) for branch in branches]

    @classmethod
    def docs_from_ast(cls, ast, timestamp=True):
        branches = cls.branches_from_ast(ast)
        return cls.docs_from_branches(branches, timestamp)


def emit_docs(rule: AnyRuleData) -> List[str]:
    ast = emitter.ast_from_rule(rule)
    return list(chain(*emitter.docs_from_ast(ast)))


def get_ast_stats():
    return emitter.get_ast_stats()


# circular dependency
import detection_rules.events_emitter_eql  # noqa: E402
