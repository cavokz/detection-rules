# Copyright Elasticsearch B.V. and/or licensed to Elasticsearch B.V. under one
# or more contributor license agreements. Licensed under the Elastic License
# 2.0; you may not use this file except in compliance with the Elastic License
# 2.0.

"""Test emitter with rules."""

import os
import unittest
from pathlib import Path

from tests.utils import *
from detection_rules.rule_loader import RuleCollection
from detection_rules.events_emitter import emitter, ast_from_rule
from detection_rules import utils, jupyter


def _get_collection(var_name):
    var_value = os.getenv(var_name)
    rules_path = Path(var_value)
    if var_value.lower() in ("1", "true", "yes"):
        collection = RuleCollection.default()
    elif rules_path.exists() and rules_path.is_dir():
        collection = RuleCollection()
        collection.load_directory(rules_path)
    else:
        raise ValueError(f"path does not exist or is not a directory: {rules_path}")
    return collection


class TestRules(QueryTestCase, SeededTestCase, unittest.TestCase):
    maxDiff = None
    nb = jupyter.Notebook()
    nb.cells.append(jupyter.Markdown(
    """
        # Documents generation from detection rules

        This report captures the error reported while generating documents from detection rules. Here you
        can learn what rules are still problematic and for which no documents can be generated at the moment.

        Curious about the inner workings? Read [here](signals_generation.md).
    """))

    @classmethod
    def setUpClass(cls):
        super(TestRules, cls).setUpClass()

    def parse_from_collection(self, collection):
        asts = []
        rules = []
        errors = {}
        for rule in collection:
            try:
                asts.append(ast_from_rule(rule.contents.data))
                rules.append(rule)
            except Exception as e:
                errors.setdefault(str(e), []).append(rule)
                continue

        with self.nb.chapter("## Skipped rules") as cells:
            cells.append(None)
            for err in sorted(errors, key=lambda e: len(errors[e]), reverse=True):
                heading = [f"{len(errors[err])} rules:", ""]
                bullets = []
                for rule in sorted(errors[err], key=lambda r: r.contents.data.name):
                    path = rule.path.relative_to(utils.ROOT_DIR)
                    bullets.append(f"* [{rule.contents.data.name}](../../{path})")
                with self.nb.chapter(f"### {err}") as cells:
                    cells.append(jupyter.Markdown(heading + sorted(bullets)))

        return rules, asts

    def generate_docs(self, rules, asts):
        errors = {}
        for rule,ast in zip(rules, asts):
            try:
                _ = [list(branch) for branch in emitter.docs_from_ast(ast)]
            except Exception as e:
                errors.setdefault(str(e), []).append(rule)
                continue

        with self.nb.chapter("## Generation errors") as cells:
            cells.append(None)
            for err in sorted(errors, key=lambda e: len(errors[e]), reverse=True):
                heading = [f"{len(errors[err])} rules:"]
                bullets = []
                for rule in sorted(errors[err], key=lambda r: r.contents.data.name):
                    path = rule.path.relative_to(utils.ROOT_DIR)
                    bullets.append(f"* [{rule.contents.data.name}](../../{path})")
                with self.nb.chapter(f"### {err}") as cells:
                    cells.append(jupyter.Markdown(heading + sorted(bullets)))

    def test_rules_collection(self):
        collection = RuleCollection.default()
        rules, asts = self.parse_from_collection(collection)
        self.generate_docs(rules, asts)

    def test_unchanged(self):
        assertReportUnchanged(self, self.nb, "documents_from_rules.md")


@unittest.skipIf(os.getenv("TEST_SIGNALS_RULES", "0").lower() in ("0", "false", "no", ""), "Slow online test")
class TestSignalsRules(SignalsTestCase, OnlineTestCase, SeededTestCase, unittest.TestCase):
    maxDiff = None
    nb = jupyter.Notebook()
    nb.cells.append(jupyter.Markdown(
    """
        # Alerts generation from detection rules

        This report captures the detection rules signals generation coverage. Here you can
        learn what rules are supported and what not and why.

        Reasons for rules being not supported:
        * rule type is not EQL or query (e.g. ML, threshold)
        * query language is not EQL or Kuery (e.g. Lucene)
        * fields type mismatch (i.e. non-ECS field with incorrect type definition)
        * incorrect document generation

        Curious about the inner workings? Read [here](signals_generation.md).
    """))

    def parse_from_collection(self, collection):
        rules = []
        asts = []
        for i,rule in enumerate(collection):
            rule = rule.contents.data
            try:
                asts.append(ast_from_rule(rule))
            except:
                continue
            index_name = "{:s}-{:03d}".format(self.index_template, i)
            rules.append({
                "rule_id": rule.rule_id,
                "risk_score": rule.risk_score,
                "description": rule.description,
                "name": rule.name,
                "index": [index_name],
                "interval": "3s",
                "from": "now-5m",
                "severity": rule.severity,
                "type": rule.type,
                "query": rule.query,
                "language": rule.language,
                "enabled": True,
                ".test_private": {},  # private test data, not sent to Kibana
            })
        return rules, asts

    def test_rules(self):
        collection = _get_collection("TEST_SIGNALS_RULES")
        rules, asts = self.parse_from_collection(collection)
        pending = self.load_rules_and_docs(rules, asts)
        self.check_signals(rules, pending)
        assertReportUnchanged(self, self.nb, "alerts_from_rules.md")
