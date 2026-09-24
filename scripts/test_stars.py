"""Tests for scripts/stars.py and the trust merge in scripts/index.py (#685).

    python3 -m unittest discover -s scripts
"""

import datetime as dt
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))

import index  # noqa: E402
import stars  # noqa: E402

NOW = dt.datetime(2026, 9, 24, tzinfo=dt.timezone.utc)
OLD = "2020-01-01T00:00:00Z"

INDEX = {
    "sources": [
        {"id": "faucet-hq/example-csv", "name": "example-csv", "owner": "faucet-hq", "file": "source-templates/faucet-hq/example-csv.yaml",
         "description": "Two CSV files", "stable": 1,
         "versions": [{"version": 1, "commit": "a", "date": "2026-09-01T10:00:00+00:00"},
                      {"version": 2, "commit": "b", "date": "2026-09-10T10:00:00+00:00"}]},
        {"id": "octo/netsuite", "name": "netsuite", "owner": "octo"},
    ],
    "sinks": [{"id": "faucet-hq/jsonl", "name": "jsonl", "owner": "faucet-hq"}],
    "matrix": [
        {"source": "faucet-hq/example-csv", "sink": "faucet-hq/jsonl", "compatible": True},
        {"source": "octo/netsuite", "sink": "faucet-hq/jsonl", "compatible": False},
    ],
}

SNAPSHOT = {
    "discussions": {
        "faucet-hq/example-csv": {"url": "https://github.com/x/discussions/1", "upvotes": 3},
        "octo/netsuite": {"url": "https://github.com/x/discussions/2", "upvotes": 0},
    },
    "open_issues": {"faucet-hq/example-csv": 2},
    "accounts": {"faucet-hq": "2024-09-24T00:00:00Z", "octo": OLD},
}


class Pure(unittest.TestCase):
    def test_marker_survives_edits_and_ignores_unmarked(self):
        self.assertEqual(stars.marker_id("hi\n<!-- faucet-template: acme/hr -->"), "acme/hr")
        self.assertEqual(stars.marker_id("<!--faucet-template:x-->"), "x")
        self.assertIsNone(stars.marker_id("no marker"))
        self.assertIsNone(stars.marker_id(None))

    def test_stars_are_the_discussions_upvotes(self):
        self.assertEqual(stars.stars_from({"upvotes": 4}), 4)
        self.assertEqual(stars.stars_from({"upvotes": 0}), 0)
        self.assertEqual(stars.stars_from({"upvotes": None}), 0)
        self.assertEqual(stars.stars_from({}), 0)

    def test_labels_respect_githubs_length_limit(self):
        self.assertEqual(stars.label_for("acme/hr"), "template:acme/hr")
        self.assertIsNone(stars.label_for("a" * 39 + "/" + "b" * 20))
        self.assertIsNone(stars.namespace("bare"))
        self.assertEqual(stars.namespace("acme/hr"), "acme")

    def test_discussion_body_carries_the_marker(self):
        body = stars.discussion_body(INDEX["sources"][0], "source")
        self.assertEqual(stars.marker_id(body), "faucet-hq/example-csv")
        self.assertIn("Upvote", body)
        self.assertNotIn("👍", body)
        self.assertIn("template:faucet-hq/example-csv", body)
        self.assertIn("a sink template", stars.discussion_body({"id": "a/b"}, "sink"))

    def test_collect_builds_stars_json(self):
        out = stars.collect(INDEX, SNAPSHOT, NOW)
        t = out["templates"]
        self.assertEqual(set(out), {"templates"})
        self.assertEqual(t["faucet-hq/example-csv"],
                         {"stars": 3, "star_url": "https://github.com/x/discussions/1",
                          "open_issues": 2, "publisher_account_age_days": 730})
        self.assertEqual(t["octo/netsuite"]["stars"], 0)
        self.assertNotIn("stars", t["faucet-hq/jsonl"])  # no discussion yet
        self.assertEqual(t["faucet-hq/jsonl"]["publisher_account_age_days"], 730)


class TrustMerge(unittest.TestCase):
    def test_apply_trust_combines_history_matrix_and_stars(self):
        idx = json.loads(json.dumps(INDEX))
        s = stars.collect(INDEX, SNAPSHOT, NOW)
        index.apply_trust(idx, s)
        csv = idx["sources"][0]["trust"]
        self.assertEqual(csv["stars"], 3)
        self.assertEqual(csv["updated"], "2026-09-10")
        self.assertEqual(csv["stable_since"], "2026-09-01")
        self.assertEqual(csv["compatible_sinks"], 1)
        self.assertEqual(csv["open_issues"], 2)
        self.assertEqual(csv["publisher"], {"templates": 2, "account_age_days": 730})
        ns = idx["sources"][1]["trust"]
        self.assertEqual(ns["compatible_sinks"], 0)
        self.assertNotIn("updated", ns)
        self.assertNotIn("compatible_sinks", idx["sinks"][0]["trust"])

    def test_no_stars_file_still_yields_history_signals_and_drops_empty_blocks(self):
        idx = {"sources": [], "sinks": [{"id": "bare", "name": "bare", "trust": {"stale": 1}}], "matrix": []}
        index.apply_trust(idx, {})
        self.assertNotIn("trust", idx["sinks"][0])
        self.assertEqual(index.load_stars("/definitely/missing.json"), {})
        self.assertIsNone(index._day(None))


class EndToEnd(unittest.TestCase):
    def test_fixture_run_writes_stars_json(self):
        with tempfile.TemporaryDirectory() as d:
            ip, fp, op = (os.path.join(d, n) for n in ("index.json", "snap.json", "stars.json"))
            json.dump(INDEX, open(ip, "w"))
            json.dump(SNAPSHOT, open(fp, "w"))
            res = stars.main(["--fixture", fp, "--index", ip, "--out", op, "--now", "2026-09-24T00:00:00Z"])
            self.assertTrue(os.path.isfile(op))
            self.assertEqual(json.load(open(op)), res)
            self.assertIn("faucet-hq/example-csv", res["templates"])


if __name__ == "__main__":
    unittest.main()
