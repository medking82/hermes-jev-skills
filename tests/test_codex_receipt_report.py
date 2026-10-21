"""Reporting privacy and transport tests. No updater, network, auth or model calls."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "codex"))
spec = importlib.util.spec_from_file_location("receipt_report", ROOT / "codex/report.py")
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)
NOW = "2026-10-21T10:00:00Z"
SHA = "a" * 40


class ReportingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        # macOS exposes its temp directory through /var; fixtures use its real
        # path so the production linked-path guard stays strict and unchanged.
        self.home = Path(temporary.name).resolve()
        self.runtime = self.home / "native-review-sync"
        self.runtime.mkdir()
        report.write(self.runtime / "reporting.json", dict(schema=1, device="a" * 16))
        self.event = dict(status="stopped", reason="Local tests failed C:/private/token", event_id="123",
                          observed_at=NOW, commit=SHA, run_url="https://github.com/medking82/native-review/actions/runs/1234")
        report.write(self.runtime / "last-run.json", self.event)
        report.write(self.runtime / "state.json", dict(blocked=self.event, tools={"private": "never-upload"}))
        self.task = dict(state="Ready", last_run=NOW, last_result=2)

    def test_collect_uses_closed_schema_and_never_forwards_state_or_exception_text(self):
        value = report.collect(self.home, "native-review", self.task, NOW)
        self.assertEqual(value["receipt"]["reason"], "local-tests-failure")
        self.assertEqual(value["blocked"]["event_id"], "123")
        self.assertEqual(value["receipt"]["commit"], SHA)
        encoded = json.dumps(value)
        self.assertNotIn("private", encoded)
        self.assertNotIn("never-upload", encoded)
        self.assertNotIn("token", encoded)
        self.assertNotIn("tools", encoded)

    def test_foreign_url_and_invalid_commit_are_removed(self):
        value = report.receipt(dict(self.event, commit="private-value", run_url="https://example.com/secret"), "medking82/native-review")
        self.assertIsNone(value["commit"])
        self.assertIsNone(value["run_url"])

    def test_launcher_without_event_id_gets_stable_identity(self):
        launcher = dict(status="stopped", observed_at="2026-10-21T10:00:00.123+00:00", reason="launcher failed")
        a = report.receipt(launcher, "medking82/native-review")
        self.assertEqual(a, report.receipt(launcher, "medking82/native-review"))
        self.assertEqual(a["observed_at"], NOW)
        self.assertEqual(a["reason"], "launcher-failure")

    def test_only_expected_metadata_files_are_read(self):
        names = []
        original = report.read
        def read(root, name):
            names.append(name)
            return original(root, name)
        with patch.object(report, "read", side_effect=read):
            report.collect(self.home, "native-review", self.task, NOW)
        self.assertEqual(set(names), {"reporting.json", "state.json", "last-run.json", "last-update.json", "launcher-error.json"})

    def test_submit_uses_fixed_dispatch_endpoint_and_structured_payload(self):
        value = report.collect(self.home, "native-review", self.task, NOW)
        calls = []
        report.submit(value, "existing-gh", lambda args, **kw: calls.append((args, kw)))
        self.assertEqual(calls[0][0][-3:], ["repos/medking82/native-review/dispatches", "--input", "-"])
        self.assertEqual(json.loads(calls[0][1]["payload"])["client_payload"], value)

    def test_denied_submission_has_no_fallback(self):
        result = type("Result", (), {"returncode": 1, "stderr": "HTTP 403 private token detail", "stdout": ""})()
        with patch.object(report.subprocess, "run", return_value=result) as called:
            with self.assertRaisesRegex(PermissionError, "denied; no fallback"):
                report._run(["existing-gh", "api"])
        self.assertEqual(called.call_count, 1)

    def test_temporary_offline_is_not_a_test_failure(self):
        self.assertEqual(report.reason("GitHub temporarily unavailable", "deferred"), "offline")
        result = type("Result", (), {"returncode": 1, "stderr": "dial tcp unavailable", "stdout": ""})()
        with patch.object(report.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(ConnectionError, "no test result inferred"):
                report._run(["existing-gh", "api"])

    def test_normal_peer_is_not_submitted_but_disabled_peer_is(self):
        value = report.collect(self.home, "native-review", self.task, NOW)
        value["receipt"] = dict(value["receipt"], status="unchanged", reason=None)
        value["blocked"] = None
        self.assertFalse(report.unhealthy_peer(value))
        value["task"] = dict(self.task, state="Disabled")
        self.assertTrue(report.unhealthy_peer(value))

    def test_running_peer_and_five_minute_grace_do_not_raise_stale(self):
        value = report.collect(self.home, "native-review", self.task, NOW)
        value["receipt"] = None
        value["task"] = dict(self.task, state="Running")
        self.assertFalse(report.unhealthy_peer(value))
        value["task"] = self.task
        self.assertFalse(report.unhealthy_peer(value))


if __name__ == "__main__":
    unittest.main()
