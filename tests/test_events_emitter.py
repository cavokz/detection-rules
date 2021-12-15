# Copyright Elasticsearch B.V. and/or licensed to Elasticsearch B.V. under one
# or more contributor license agreements. Licensed under the Elastic License
# 2.0; you may not use this file except in compliance with the Elastic License
# 2.0.

"""Test events emitter."""

import os
import sys
import time
import unittest
import random
import json
import eql

from detection_rules.rule_loader import RuleCollection
from detection_rules.events_emitter import emitter

verbose = sum(arg.count('v') for arg in sys.argv if arg.startswith("-") and not arg.startswith("--"))

eql_event_docs_mappings = {
    """process where process.name == "regsvr32.exe"
    """: {
        "properties": {
            "event": {"properties": {"category": {"type": "keyword"}}},
            "process": {"properties": {"name": {"type": "keyword"}}},
        },
    },

    """network where source.ip == "::1" or destination.ip == "::1"
    """: {
        "properties": {
            "event": {"properties": {"category": {"type": "keyword"}}},
            "destination": {"properties": {"ip": {"type": "ip"}}},
            "source": {"properties": {"ip": {"type": "ip"}}},
        },
    },

    """process where process.code_signature.exists == false and process.pid > 1024
    """: {
        "properties": {
            "event": {"properties": {"category": {"type": "keyword"}}},
            "process": {"properties": {"code_signature": {"properties": {"exists": {"type": "boolean"}}}, "pid": {"type": "long"}}},
        },
    },
}

eql_event_docs_complete = {
    """any where true
    """: [
        {},
    ],

    """network where source.port > 512 and source.port < 1024
    """: [
        {"event": {"category": ["network"]}, "source": {"port": 859}},
    ],

    """network where source.port > 512 or source.port < 1024
    """: [
        {"event": {"category": ["network"]}, "source": {"port": 44068}},
        {"event": {"category": ["network"]}, "source": {"port": 609}},
    ],

    """network where source.port < 2000 and (source.port > 512 or source.port > 1024)
    """: [
        {"event": {"category": ["network"]}, "source": {"port": 630}},
        {"event": {"category": ["network"]}, "source": {"port": 1957}},
    ],

    """network where (source.port > 512 or source.port > 1024) and source.port < 2000
    """: [
        {"event": {"category": ["network"]}, "source": {"port": 1105}},
        {"event": {"category": ["network"]}, "source": {"port": 1448}},
    ],

    """network where (source.port > 1024 or source.port < 2000) and (source.port < 4000 or source.port > 512)
    """: [
        {"event": {"category": ["network"]}, "source": {"port": 2567}},
        {"event": {"category": ["network"]}, "source": {"port": 569}},
        {"event": {"category": ["network"]}, "source": {"port": 61845}},
        {"event": {"category": ["network"]}, "source": {"port": 1670}},
    ],

    """network where destination.port in (80, 443)
    """: [
        {"event": {"category": ["network"]}, "destination": {"port": 80}},
        {"event": {"category": ["network"]}, "destination": {"port": 443}},
    ],

    """network where destination.port not in (80, 443)
    """: [
        {"event": {"category": ["network"]}, "destination": {"port": 35106}},
    ],

    """network where destination.port == 22 and destination.port in (80, 443) or destination.port == 25
    """: [
        {"event": {"category": ["network"]}, "destination": {"port": 25}},
    ],

    """network where not destination.port in (80, 443)
    """: [
        {"event": {"category": ["network"]}, "destination": {"port": 58630}},
    ],

    """process where process.name == "regsvr32.exe"
    """: [
        {"event": {"category": ["process"]}, "process": {"name": "regsvr32.exe"}},
    ],

    """process where process.name != "regsvr32.exe"
    """: [
        {"event": {"category": ["process"]}, "process": {"name": "!regsvr32.exe"}},
    ],

    """process where process.pid != 0
    """: [
        {"event": {"category": ["process"]}, "process": {"pid": 1565416049}},
    ],

    """process where process.pid >= 0
    """: [
        {"event": {"category": ["process"]}, "process": {"pid": 2413373806}},
    ],

    """process where process.pid > 0
    """: [
        {"event": {"category": ["process"]}, "process": {"pid": 57239544}},
    ],

    """process where process.code_signature.exists == true
    """: [
        {"event": {"category": ["process"]}, "process": {"code_signature": {"exists": True}}},
    ],

    """process where process.code_signature.exists != true
    """: [
        {"event": {"category": ["process"]}, "process": {"code_signature": {"exists": False}}},
    ],

    """any where network.protocol == "some protocol"
    """: [
        {"network": {"protocol": "some protocol"}},
    ],

    """process where process.name == "regsvr32.exe" and process.parent.name == "cmd.exe"
    """: [
        {"event": {"category": ["process"]}, "process": {"name": "regsvr32.exe", "parent": {"name": "cmd.exe"}}},
    ],

    """process where process.name == "regsvr32.exe" or process.parent.name == "cmd.exe"
    """: [
        {"event": {"category": ["process"]}, "process": {"name": "regsvr32.exe"}},
        {"event": {"category": ["process"]}, "process": {"parent": {"name": "cmd.exe"}}},
    ],

    """process where process.name == "regsvr32.exe" or process.name == "cmd.exe" or process.name == "powershell.exe"
    """: [
        {"event": {"category": ["process"]}, "process": {"name": "regsvr32.exe"}},
        {"event": {"category": ["process"]}, "process": {"name": "cmd.exe"}},
        {"event": {"category": ["process"]}, "process": {"name": "powershell.exe"}},
    ],

    """process where process.name in ("regsvr32.exe", "cmd.exe", "powershell.exe")
    """: [
        {"event": {"category": ["process"]}, "process": {"name": "regsvr32.exe"}},
        {"event": {"category": ["process"]}, "process": {"name": "cmd.exe"}},
        {"event": {"category": ["process"]}, "process": {"name": "powershell.exe"}},
    ],

    """process where process.name in ("regsvr32.exe", "cmd.exe") or process.name == "powershell.exe"
    """: [
        {"event": {"category": ["process"]}, "process": {"name": "regsvr32.exe"}},
        {"event": {"category": ["process"]}, "process": {"name": "cmd.exe"}},
        {"event": {"category": ["process"]}, "process": {"name": "powershell.exe"}},
    ],

    """process where process.name : ("*.EXE", "*.DLL")
    """: [
        {"event": {"category": ["process"]}, "process": {"name": "4pp7h.exe"}},
        {"event": {"category": ["process"]}, "process": {"name": "0gwcwq8s9dic.dll"}},
    ],

    """process where event.type in ("start", "process_started") and process.args : "dump-keychain" and process.args : "-d"
    """: [
        {"event": {"category": ["process"], "type": ["start"]}, "process": {"args": ["dump-keychain", "-d"]}},
        {"event": {"category": ["process"], "type": ["process_started"]}, "process": {"args": ["dump-keychain", "-d"]}},
    ],
}

eql_sequence_docs_complete = {
    """sequence
        [process where process.name : "cmd.exe"]
        [process where process.parent.name : "cmd.exe"]
    """: [
        {"event": {"category": ["process"]}, "process": {"name": "cmd.exe"}},
        {"event": {"category": ["process"]}, "process": {"parent": {"name": "cmd.exe"}}},
    ],

    """sequence by user.id
        [process where process.name : "cmd.exe"]
        [process where process.parent.name : "cmd.exe"]
    """: [
        {"event": {"category": ["process"]}, "process": {"name": "cmd.exe"}, "user": {"id": "xgG"}},
        {"event": {"category": ["process"]}, "process": {"parent": {"name": "cmd.exe"}}, "user": {"id": "xgG"}},
    ],

    """sequence
        [process where process.name : "cmd.exe"] by user.id
        [process where process.parent.name : "cmd.exe"] by user.name
    """: [
        {"event": {"category": ["process"]}, "process": {"name": "cmd.exe"}, "user": {"id": "Eev"}},
        {"event": {"category": ["process"]}, "process": {"parent": {"name": "cmd.exe"}}, "user": {"name": "Eev"}},
    ],

    """sequence
        [process where process.name : "cmd.exe"]
        [process where process.parent.name : "cmd.exe" or process.name : "powershell.exe"]
    """: [
        {"event": {"category": ["process"]}, "process": {"name": "cmd.exe"}},
        {"event": {"category": ["process"]}, "process": {"parent": {"name": "cmd.exe"}}},
        {"event": {"category": ["process"]}, "process": {"name": "cmd.exe"}},
        {"event": {"category": ["process"]}, "process": {"name": "powershell.exe"}},
    ],

    """sequence by user.id
        [process where process.name : "cmd.exe"]
        [process where process.parent.name : "cmd.exe" or process.name : "powershell.exe"]
    """: [
        {"event": {"category": ["process"]}, "process": {"name": "cmd.exe"}, "user": {"id": "GuM"}},
        {"event": {"category": ["process"]}, "process": {"parent": {"name": "cmd.exe"}}, "user": {"id": "GuM"}},
        {"event": {"category": ["process"]}, "process": {"name": "cmd.exe"}, "user": {"id": "etd"}},
        {"event": {"category": ["process"]}, "process": {"name": "powershell.exe"}, "user": {"id": "etd"}},
    ],

    """sequence
        [process where process.name in ("cmd.exe", "powershell.exe")] by process.name
        [process where process.name in ("cmd.exe", "powershell.exe")] by process.parent.name
    """: [
        {"event": {"category": ["process"]}, "process": {"name": "cmd.exe"}},
        {"event": {"category": ["process"]}, "process": {"name": "cmd.exe", "parent": {"name": "cmd.exe"}}},
        {"event": {"category": ["process"]}, "process": {"name": "cmd.exe"}},
        {"event": {"category": ["process"]}, "process": {"name": "powershell.exe", "parent": {"name": "cmd.exe"}}},
        {"event": {"category": ["process"]}, "process": {"name": "powershell.exe"}},
        {"event": {"category": ["process"]}, "process": {"name": "cmd.exe", "parent": {"name": "powershell.exe"}}},
        {"event": {"category": ["process"]}, "process": {"name": "powershell.exe"}},
        {"event": {"category": ["process"]}, "process": {"name": "powershell.exe", "parent": {"name": "powershell.exe"}}},
    ],

    """sequence by user.id
        [process where process.name in ("cmd.exe", "powershell.exe")] by process.name
        [process where process.name in ("cmd.exe", "powershell.exe")] by process.parent.name
    """: [
        {"event": {"category": ["process"]}, "process": {"name": "cmd.exe"}, "user": {"id": "Tkx"}},
        {"event": {"category": ["process"]}, "process": {"name": "cmd.exe", "parent": {"name": "cmd.exe"}}, "user": {"id": "Tkx"}},
        {"event": {"category": ["process"]}, "process": {"name": "cmd.exe"}, "user": {"id": "REt"}},
        {"event": {"category": ["process"]}, "process": {"name": "powershell.exe", "parent": {"name": "cmd.exe"}}, "user": {"id": "REt"}},
        {"event": {"category": ["process"]}, "process": {"name": "powershell.exe"}, "user": {"id": "dLh"}},
        {"event": {"category": ["process"]}, "process": {"name": "cmd.exe", "parent": {"name": "powershell.exe"}}, "user": {"id": "dLh"}},
        {"event": {"category": ["process"]}, "process": {"name": "powershell.exe"}, "user": {"id": "Bvu"}},
        {"event": {"category": ["process"]}, "process": {"name": "powershell.exe", "parent": {"name": "powershell.exe"}}, "user": {"id": "Bvu"}},
    ],
}

eql_exceptions = {
    """any where false
    """:
        "Cannot trigger with any document",

    """process where process.pid == 0
    """:
        "Unsolvable constraints: process.pid (out of boundary, 1 <= 0 <= 4294967295)",

    """process where process.pid <= 0
    """:
        "Unsolvable constraints: process.pid (empty solution space, 1 <= x <= 0)",

    """process where process.pid < 0
    """:
        "Unsolvable constraints: process.pid (empty solution space, 1 <= x <= -1)",

    """any where network.protocol == "http" and network.protocol == "https"
    """:
        "Unsolvable constraints ==: network.protocol ('https' != 'http')",

    """network where destination.port == 22 and destination.port in (80, 443)
    """:
        "Cannot trigger with any document",

    """sequence by process.name
        [process where process.name : "cmd.exe"]
        [process where process.name : "powershell.exe"]
    """:
        "Unsolvable constraints ==: process.name ('cmd.exe' != 'powershell.exe')",

    """sequence
        [process where process.name : "cmd.exe"] by process.name
        [process where process.parent.name : "powershell.exe"] by process.parent.name
    """:
        "Unsolvable constraints ==: process.parent.name ('cmd.exe' != 'powershell.exe')",
}


class TestCaseSeed:
    """Make Emitter repeat the same random choices."""

    def setUp(self):
        self.random_state = random.getstate()

    def tearDown(self):
        random.setstate(self.random_state)

    def subTest(self, query):
        fuzziness = emitter.fuzziness()
        completeness = emitter.completeness()
        random.seed(f"{query} {completeness} {fuzziness}")
        return super(TestCaseSeed, self).subTest(query, completeness=completeness, fuzziness=fuzziness)


class TestEmitter(TestCaseSeed, unittest.TestCase):
    maxDiff = None

    def test_mappings(self):
        with eql.parser.elasticsearch_syntax, emitter.fuzziness(0), emitter.completeness(1):
            for query, mappings in eql_event_docs_mappings.items():
                with self.subTest(query):
                    emitter.reset_mappings()
                    _ = emitter.emit_docs(emitter.emit(eql.parse_query(query)))
                    self.assertEqual(mappings, emitter.emit_mappings())

    def test_eql_exceptions(self):
        with eql.parser.elasticsearch_syntax, emitter.fuzziness(0):
            for query, msg in eql_exceptions.items():
                with self.subTest(query):
                    with self.assertRaises(ValueError, msg=msg):
                        self.assertEqual(None, emitter.emit_docs(emitter.emit(eql.parse_query(query))))

    def test_eql_events_complete(self):
        with eql.parser.elasticsearch_syntax, emitter.fuzziness(0), emitter.completeness(1):
            for query, docs in eql_event_docs_complete.items():
                with self.subTest(query):
                    self.assertEqual(docs, emitter.emit_docs(emitter.emit(eql.parse_query(query))))

    def test_eql_sequence_complete(self):
        with eql.parser.elasticsearch_syntax, emitter.fuzziness(0), emitter.completeness(1):
            for query, docs in eql_sequence_docs_complete.items():
                with self.subTest(query):
                    self.assertEqual(docs, emitter.emit_docs(emitter.emit(eql.parse_query(query))))

class TestCaseOnline:
    index_template = "detection-rules-ut"

    @classmethod
    def setUpClass(cls):
        from elasticsearch import Elasticsearch
        from elasticsearch.client import IndicesClient
        from detection_rules.kibana import Kibana

        es_url = os.getenv("TEST_ELASTICSEARCH_URL", "http://elastic:changeit@localhost:29650")
        cls.es = Elasticsearch(es_url)
        kbn_url = os.getenv("TEST_KIBANA_URL", "http://elastic:changeit@localhost:65290")
        cls.kbn = Kibana(kbn_url)

        if not cls.es.ping():
            raise unittest.SkipTest(f"Could not reach Elasticsearch: {es_url}")
        if not cls.kbn.ping():
            raise unittest.SkipTest(f"Could not reach Kibana: {kbn_url}")

        cls.es_indices = IndicesClient(cls.es)
        cls.kbn.create_siem_index()

    @classmethod
    def tearDownClass(cls):
        cls.es.close()
        del(cls.es)
        del(cls.kbn)
        del(cls.es_indices)

    def setUp(self):
        super(TestCaseOnline, self).setUp()

        self.kbn.delete_detection_engine_rules()

        if self.es_indices.exists_index_template(self.index_template):
            self.es_indices.delete_index_template(self.index_template)

        self.es_indices.delete(f"{self.index_template}-*")
        self.es.delete_by_query(".siem-signals-default-000001", body={"query": {"match_all": {}}})


class TestSignals(TestCaseOnline, TestCaseSeed, unittest.TestCase):
    maxDiff = None

    def parse_from_queries(self, queries):
        rules = []
        asts = []
        for i,query in enumerate(queries):
            index_name = "{:s}-{:03d}".format(self.index_template, i)
            rules.append({
                "rule_id": "test_{:03d}".format(i),
                "risk_score": 17,
                "description": "Test rule {:03d}".format(i),
                "name": "Rule {:03d}".format(i),
                "index": [index_name],
                "interval": "3s",
                "from": "now-5m",
                "severity": "low",
                "type": "eql",
                "query": query,
                "language": "eql",
                "enabled": True,
            })
            asts.append(eql.parse_query(query))
        return rules, asts

    def parse_from_collection(self, collection):
        rules = []
        asts = []
        for i,rule in enumerate(collection):
            rule = rule.contents.data
            if rule.type == "eql":
                asts.append(rule.validator.ast)
            elif rule.type == "query" and rule.language == "kuery":
                asts.append(rule.validator.to_eql())
            else:
                if verbose > 3:
                    sys.stderr.write(f"rule was skipped: type={rule.type}\n")
                    sys.stderr.flush()
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
            })
        return rules, asts

    def generate_docs_and_mappings(self, rules, asts):
        emitter.reset_mappings()

        bulk = []
        for rule, ast in zip(rules, asts):
            with self.subTest(rule["query"]):
                try:
                    for doc in emitter.docs_from_ast(ast):
                        bulk.append(json.dumps({"index": {"_index": rule["index"][0]}}))
                        bulk.append(json.dumps(doc))
                except Exception as e:
                    if verbose > 2:
                        sys.stderr.write(f"{str(e)}\n")
                        sys.stderr.flush()
                    continue
        return (bulk, emitter.emit_mappings())

    def load_rules_and_docs(self, rules, asts, batch_size=100):
        docs, mappings = self.generate_docs_and_mappings(rules, asts)

        template = {
            "index_patterns": [f"{self.index_template}-*"],
            "template": {"mappings": mappings},
        }
        self.es_indices.put_index_template(self.index_template, body=template)

        pos = 0
        while docs[pos:pos+batch_size]:
            ret = self.es.bulk("\n".join(docs[pos:pos+batch_size]))
            for item in ret["items"]:
                if item["index"]["status"] != 201:
                    if verbose > 1:
                        sys.stderr.write(f"{str(item['index'])}\n")
                        sys.stderr.flush()
            pos += batch_size

        pending = self.kbn.create_detection_engine_rules(rules)
        for rule, rule_id in zip(rules, pending):
            rule["id"] = rule_id
        return pending

    def wait_for_rules(self, pending, timeout=300, sleep=5):
        start = time.time()
        successful = {}
        failed = {}
        while (time.time() - start) < timeout:
            self.check_rules(pending, successful, failed)
            if verbose:
                sys.stderr.write(f"{len(pending)} ")
                sys.stderr.flush()
            if pending:
                time.sleep(sleep)
            else:
                break
        return successful, failed

    def check_rules(self, pending, successful, failed):
        statuses = self.kbn.find_detection_engine_rules_statuses(pending)
        for rule_id, rule_status in statuses.items():
            current_status = rule_status["current_status"]
            if current_status["last_success_at"]:
                del(pending[rule_id])
                successful[rule_id] = rule_status
            elif current_status["last_failure_at"]:
                del(pending[rule_id])
                failed[rule_id] = rule_status

    def get_rule_by_id(self, rules, rule_id):
        for rule in rules:
            if rule['id'] == rule_id:
                return rule

    def check_docs(self, rule):
        try:
            ret = self.es.search(index=",".join(rule["index"]), body={"query": {"match_all": {}}})
        except Exception as e:
            if verbose > 1:
                sys.stderr.write(f"{str(e)}\n")
                sys.stderr.flush()
            return []
        return [hit["_source"] for hit in ret["hits"]["hits"]]

    def debug_rules(self, rules, rule_ids):
        lines = []
        for rule_id in sorted(rule_ids):
            rule = self.get_rule_by_id(rules, rule_id)
            docs = self.check_docs(rule)
            lines.append("")
            lines.append("{:s}: {:s}".format(rule_id, rule["name"]))
            lines.append(rule["query"].strip())
            lines.extend(json.dumps(doc, sort_keys=True) for doc in docs)
        return lines

    def get_signals_per_rule(self):
        body = {
            "size": 0,
            "query": {
                "bool": {
                    "must_not": [
                        { "exists": { "field": "signal.rule.building_block_type" }},
                    ]
                }
            },
            "aggs": {
                "signals_per_rule": {
                    "terms": {
                        "field": "signal.rule.id",
                        "size": 10000,
                    }
                }
            }
        }
        ret = self.kbn.search_detection_engine_signals(body)
        return {bucket["key"]: bucket["doc_count"] for bucket in ret["aggregations"]["signals_per_rule"]["buckets"]}

    def assert_signals(self, rules, pending):
        successful, failed = self.wait_for_rules(pending)
        signals = self.get_signals_per_rule()
        self.assertEqual([], sorted(set(signals) - set(successful)),
            msg="\n\n ** Unsuccessful rules with signals **" +
                "\n".join(self.debug_rules(rules, set(signals) - set(successful))))
        self.assertEqual([], sorted(set(successful) - set(signals)),
            msg="\n\n** Rules with too few signals **\n" +
                "\n".join(self.debug_rules(rules, set(successful) - set(signals))))
        self.assertEqual([], sorted((rule_id, status["current_status"]["last_failure_message"]) for rule_id,status in failed.items()),
            msg="\n\n** Failed rules **\n" +
                "\n".join(self.debug_rules(rules, failed)))
        self.assertEqual([], sorted((rule_id, doc_count) for rule_id,doc_count in signals.items() if doc_count > 1),
            msg="\n\n** Rules with too many signals **\n" +
                "\n".join(self.debug_rules(rules, (rule_id for rule_id,doc_count in signals.items() if doc_count > 1))))

    @unittest.skipIf(os.getenv("TEST_SIGNALS_QUERIES", "0").lower() not in ("1", "true"), "Slow online test")
    def test_queries(self):
        queries = tuple(eql_event_docs_complete) + tuple(eql_sequence_docs_complete)
        with eql.parser.elasticsearch_syntax:
            rules, asts = self.parse_from_queries(queries)
        with emitter.fuzziness(0), emitter.completeness(0):
            pending = self.load_rules_and_docs(rules, asts)
        self.assert_signals(rules, pending)

    @unittest.skipIf(os.getenv("TEST_SIGNALS_COLLECTION", "0").lower() not in ("1", "true"), "Slow online test")
    def test_rules_collection(self):
        collection = RuleCollection.default()
        with eql.parser.elasticsearch_syntax:
            rules, asts = self.parse_from_collection(collection)
        with emitter.fuzziness(0), emitter.completeness(0):
            pending = self.load_rules_and_docs(rules, asts)
        self.assert_signals(rules, pending)
