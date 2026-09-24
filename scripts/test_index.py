"""Tests for version deprecation in scripts/index.py (#691).

    python3 -m unittest discover -s scripts
"""

import os
import sys
import unittest

import yaml

sys.path.insert(0, os.path.dirname(__file__))

import index  # noqa: E402

TID = "acme/netsuite"


def versions(n):
    return [{"version": i, "commit": f"c{i}", "date": f"2026-09-0{i}T00:00:00+00:00", "pr": None} for i in range(1, n + 1)]


class Parse(unittest.TestCase):
    def test_sidecar_without_deprecated(self):
        self.assertEqual(index.deprecations_from({}), ({}, []))
        self.assertEqual(index.deprecations_from({"stable": 3, "launch": False}), ({}, []))

    def test_yaml_int_and_str_keys_normalise_to_int(self):
        side = yaml.safe_load('stable: 4\ndeprecated:\n  2: "drops the invoices stream; use v3+"\n  "1": superseded\n')
        self.assertEqual(index.deprecations_from(side),
                         ({2: "drops the invoices stream; use v3+", 1: "superseded"}, []))

    def test_empty_reason_is_empty_string(self):
        self.assertEqual(index.deprecations_from({"deprecated": {3: None, 4: "  "}}), ({3: "", 4: ""}, []))

    def test_bad_keys_are_reported(self):
        got, bad = index.deprecations_from({"deprecated": {"v2": "x", 0: "x", -1: "x", True: "x", 5: "ok"}})
        self.assertEqual(got, {5: "ok"})
        self.assertEqual(bad, ["v2", 0, -1, True])

    def test_non_map_is_a_bad_key(self):
        self.assertEqual(index.deprecations_from({"deprecated": [1, 2]}), ({}, [[1, 2]]))


class Mark(unittest.TestCase):
    def test_marks_versions_and_lists_live_ones(self):
        vs = versions(4)
        live = index.mark_deprecated(vs, {2: "use v3+", 1: ""})
        self.assertEqual(live, [3, 4])
        self.assertEqual(vs[1]["deprecated"], True)
        self.assertEqual(vs[1]["reason"], "use v3+")
        self.assertEqual(vs[0]["deprecated"], True)
        self.assertNotIn("reason", vs[0])
        self.assertNotIn("deprecated", vs[2])

    def test_nothing_deprecated_means_every_version_is_live(self):
        vs = versions(3)
        self.assertEqual(index.mark_deprecated(vs, {}), [1, 2, 3])
        self.assertTrue(all("deprecated" not in v for v in vs))

    def test_remarking_clears_stale_flags(self):
        vs = versions(2)
        index.mark_deprecated(vs, {1: "old"})
        self.assertEqual(index.mark_deprecated(vs, {}), [1, 2])
        self.assertNotIn("reason", vs[0])


class Gate(unittest.TestCase):
    def test_valid_sidecar_passes(self):
        self.assertEqual(index.sidecar_errors(TID, versions(4), 4, {1: "superseded", 2: "use v3+"}, []), [])

    def test_deprecating_stable_is_refused(self):
        errs = index.sidecar_errors(TID, versions(4), 4, {4: "broken"}, [])
        self.assertEqual(len(errs), 1)
        self.assertIn(TID, errs[0])
        self.assertIn("v4", errs[0])
        self.assertIn("stable", errs[0])

    def test_computed_stable_landing_on_a_deprecated_version_is_refused(self):
        vs = versions(3)
        stable = index.stable_for(vs, {"launch": False})
        self.assertEqual(stable, 2)
        errs = index.sidecar_errors(TID, vs, stable, {2: "x"}, [])
        self.assertTrue(any("stable" in e and "v2" in e for e in errs))

    def test_nonexistent_version_is_refused(self):
        errs = index.sidecar_errors(TID, versions(2), 2, {7: "x"}, [])
        self.assertEqual(len(errs), 1)
        self.assertIn(TID, errs[0])
        self.assertIn("v7", errs[0])
        self.assertIn("does not exist", errs[0])

    def test_bad_key_is_refused(self):
        errs = index.sidecar_errors(TID, versions(2), 2, {}, ["v1"])
        self.assertEqual(len(errs), 1)
        self.assertIn(TID, errs[0])
        self.assertIn("'v1'", errs[0])


if __name__ == "__main__":
    unittest.main()
