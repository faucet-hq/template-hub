"""Tests for the recorded-exchange replay harness (scripts/replay.py).

    python3 -m unittest discover -s scripts
"""

import json
import os
import sys
import tempfile
import unittest
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))

import replay  # noqa: E402


class KeepLatestRecords(unittest.TestCase):
    def test_an_empty_later_run_keeps_the_previous_output(self):
        with tempfile.TemporaryDirectory() as d:
            produced, kept = os.path.join(d, "out"), os.path.join(d, "kept")
            os.makedirs(produced)
            write = lambda s, rows: open(os.path.join(produced, f"{s}.jsonl"), "w").write("".join(json.dumps(r) + "\n" for r in rows))
            write("a", [{"id": 1}])
            write("b", [])
            replay.keep_latest_records(produced, kept)
            write("a", [])
            write("b", [{"id": 2}])
            replay.keep_latest_records(produced, kept)
            self.assertEqual(replay.read_jsonl(os.path.join(kept, "a.jsonl")), [{"id": 1}])
            self.assertEqual(replay.read_jsonl(os.path.join(kept, "b.jsonl")), [{"id": 2}])
            write("a", [{"id": 3}])
            replay.keep_latest_records(produced, kept)
            self.assertEqual(replay.read_jsonl(os.path.join(kept, "a.jsonl")), [{"id": 3}])


class Subset(unittest.TestCase):
    def test_objects_match_by_key_and_arrays_element_wise(self):
        self.assertTrue(replay.subset({"a": 1}, {"a": 1, "b": 2}))
        self.assertTrue(replay.subset({"a": {"b": [1, {"c": 2}]}}, {"a": {"b": [1, {"c": 2, "d": 3}]}, "e": 0}))
        self.assertFalse(replay.subset({"a": 1}, {"a": 2}))
        self.assertFalse(replay.subset({"a": 1}, {}))
        self.assertFalse(replay.subset([1, 2], [1]))
        self.assertFalse(replay.subset({"a": 1}, [1]))


class Subst(unittest.TestCase):
    def test_replaces_the_placeholder_everywhere(self):
        got = replay.subst({"next": "{replay}/p2", "l": ["{replay}"], "n": 3}, "http://h:1")
        self.assertEqual(got, {"next": "http://h:1/p2", "l": ["http://h:1"], "n": 3})


class Matches(unittest.TestCase):
    def m(self, spec, method="GET", path="/x", query=None, headers=None, body=None, form=None):
        return replay.matches(spec, method, path, query or {}, headers or {}, body, form)

    def test_method_path_and_query(self):
        spec = {"path": "/x", "query": {"limit": "100"}}
        self.assertTrue(self.m(spec, query={"limit": ["100"], "other": ["1"]}))
        self.assertFalse(self.m(spec, query={"limit": ["50"]}))
        self.assertFalse(self.m(spec, method="POST", query={"limit": ["100"]}))
        self.assertFalse(self.m(spec, path="/y", query={"limit": ["100"]}))

    def test_a_repeated_query_key_never_matches_a_single_value(self):
        self.assertFalse(self.m({"path": "/x", "query": {"since": "a"}}, query={"since": ["a", "a"]}))

    def test_absent_keys(self):
        spec = {"path": "/x", "absent": ["cursor"]}
        self.assertTrue(self.m(spec))
        self.assertFalse(self.m(spec, query={"cursor": ["c"]}))

    def test_headers_are_case_insensitive_by_name(self):
        spec = {"path": "/x", "headers": {"Authorization": "Bearer t"}}
        self.assertTrue(self.m(spec, headers={"authorization": "Bearer t"}))
        self.assertFalse(self.m(spec, headers={"authorization": "Bearer u"}))

    def test_json_body_subset_regex_and_form(self):
        self.assertTrue(self.m({"method": "POST", "path": "/x", "body": {"q": "a"}}, method="POST", body={"q": "a", "p": 1}))
        self.assertFalse(self.m({"method": "POST", "path": "/x", "body": {"q": "a"}}, method="POST", body=None))
        rx = {"method": "POST", "path": "/x", "body_regex": {"q": r"SELECT .* WHERE t > \d+"}}
        self.assertTrue(self.m(rx, method="POST", body={"q": "SELECT a FROM b WHERE t > 5"}))
        self.assertFalse(self.m(rx, method="POST", body={"q": "SELECT a FROM b"}))
        self.assertFalse(self.m(rx, method="POST", body={"q": 5}))
        form = {"method": "POST", "path": "/t", "form": {"grant_type": "refresh_token"}}
        self.assertTrue(self.m(form, method="POST", path="/t", form={"grant_type": ["refresh_token"]}))
        self.assertFalse(self.m(form, method="POST", path="/t", form={"grant_type": ["client_credentials"]}))
        self.assertFalse(self.m(form, method="POST", path="/t"))

    def test_specificity_counts_every_constraint(self):
        self.assertEqual(replay.specificity({"path": "/x"}), 0)
        self.assertEqual(
            replay.specificity({"query": {"a": 1, "b": 2}, "absent": ["c"], "headers": {"h": 1}, "body": {"q": 1, "p": 2}, "body_regex": {"r": "."}, "form": {"f": 1}}),
            8,
        )


class Recorder(unittest.TestCase):
    def setUp(self):
        self.rec = replay.Recorder([
            {"match": {"path": "/items"}, "response": {"body": {"page": 1, "next": "{replay}/items?cursor=2"}}},
            {"match": {"path": "/items", "query": {"cursor": "2"}}, "response": {"status": 200, "headers": {"X-Next": "{replay}/done"}, "text": "a,b\n1,2\n"}},
            {"match": {"path": "/never"}, "response": {"status": 204}},
        ])
        self.rec.base = "http://h:1"

    def test_the_most_specific_exchange_wins_and_placeholders_resolve(self):
        status, headers, payload = self.rec.answer("GET", "/items", {}, b"")
        self.assertEqual((status, json.loads(payload)), (200, {"page": 1, "next": "http://h:1/items?cursor=2"}))
        status, headers, payload = self.rec.answer("GET", "/items?cursor=2", {}, b"")
        self.assertEqual(payload, b"a,b\n1,2\n")
        self.assertEqual(headers["X-Next"], "http://h:1/done")
        self.assertEqual(self.rec.hits, [1, 1, 0])

    def test_an_unmatched_request_is_recorded_and_answered_599(self):
        status, _, _ = self.rec.answer("POST", "/items", {}, b'{"q": 1}')
        self.assertEqual(status, 599)
        self.assertEqual(len(self.rec.unmatched), 1)
        self.assertIn("POST /items", self.rec.unmatched[0])

    def test_form_bodies_are_parsed(self):
        rec = replay.Recorder([{"match": {"method": "POST", "path": "/t", "form": {"grant_type": "refresh_token"}}, "response": {"body": {"access_token": "x"}}}])
        status, _, _ = rec.answer("POST", "/t", {}, b"grant_type=refresh_token&refresh_token=r")
        self.assertEqual(status, 200)

    def test_an_empty_response_has_no_payload(self):
        status, _, payload = self.rec.answer("GET", "/never", {}, b"")
        self.assertEqual((status, payload), (204, b""))


class Server(unittest.TestCase):
    def test_serves_recorded_exchanges_over_http(self):
        rec = replay.Recorder([{"match": {"path": "/ping", "headers": {"authorization": "Bearer t"}}, "response": {"body": {"pong": "{replay}"}}}])
        server = replay.serve(rec)
        try:
            req = urllib.request.Request(rec.base + "/ping", headers={"Authorization": "Bearer t"})
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(json.loads(resp.read()), {"pong": rec.base})
        finally:
            server.shutdown()


class Files(unittest.TestCase):
    def test_jsonl_helpers(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.jsonl")
            with open(p, "w") as f:
                f.write('{"b": 2, "a": 1}\n\n{"a": 0}\n')
            open(os.path.join(d, "notes.txt"), "w").close()
            self.assertEqual(replay.read_jsonl(p), [{"b": 2, "a": 1}, {"a": 0}])
            self.assertEqual(replay.read_jsonl(os.path.join(d, "missing.jsonl")), [])
            self.assertEqual(replay.jsonl_stems(d), {"s"})
            self.assertEqual(replay.jsonl_stems(os.path.join(d, "nope")), set())
        self.assertEqual(replay.canonical([{"b": 1, "a": 2}, {"a": 1}]), ['{"a": 1}', '{"a": 2, "b": 1}'])

    def test_discover_finds_every_replay_case(self):
        found = replay.discover()
        self.assertTrue(all(tid.count("/") == 1 for tid in found))
        for tid in found:
            self.assertTrue(os.path.isfile(os.path.join(replay.TESTS, *tid.split("/"), "replay.yaml")))


if __name__ == "__main__":
    unittest.main()
