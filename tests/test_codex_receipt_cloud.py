"""Receiver-only offline checks. No updater imports, subprocesses, or network."""

import base64
import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = "codex" if (ROOT / "codex" / "receipt_cloud.py").exists() else "maintenance"
SPEC = importlib.util.spec_from_file_location("tested_receipt_cloud", ROOT / DIRECTORY / "receipt_cloud.py")
cloud = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cloud)
KIND = "jev" if DIRECTORY == "codex" else "native-review"
REPO = cloud.REPOSITORIES[KIND]
DEVICE = "0123456789abcdef"
CANARY = "fedcba9876543210"
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
WORKFLOW = "https://github.com/" + REPO + "/actions/runs/900"


def policy():
    return {"schema": 1, "kind": KIND, "devices": [DEVICE, CANARY], "canary_devices": [CANARY]}


def event(status="unchanged", identity="100", when=NOW, reason=None):
    return {"status": status, "event_id": identity, "observed_at": cloud.utc(when),
            "commit": "a" * 40, "run_url": "https://github.com/" + REPO + "/actions/runs/123",
            "reason": reason}


def report(receipt=None, now=NOW):
    return {"schema": 1, "device": DEVICE, "kind": KIND, "observed_at": cloud.utc(now),
            "task": {"state": "Ready", "last_run": cloud.utc(now), "last_result": 0},
            "receipt": receipt, "last_update": None, "blocked": None, "launcher": None,
            "canary": False}


class FakeAPI:
    """SHA compare-and-swap fake, including errors after durable side effects."""
    def __init__(self):
        self.branch = False
        self.states = {}
        self.created = []
        self.existing = []
        self.writes = 0
        self.fail_write = None
        self.fail_issue = False
        self.lost_issue_response = False
        self.scans = 0
        self.loaded = []

    def ensure_branch(self, create):
        if create:
            self.branch = True
        return self.branch

    def load_state(self, device):
        self.loaded.append(device)
        return copy.deepcopy(self.states.get(device, (None, None)))

    def save_state(self, device, state, sha):
        self.writes += 1
        if self.writes == self.fail_write:
            raise cloud.CloudError("Synthetic write failure")
        expected = self.states.get(device, (None, None))[1]
        if sha != expected:
            raise cloud.CloudError("Synthetic SHA conflict")
        next_sha = str(self.writes)
        self.states[device] = (copy.deepcopy(state), next_sha)
        return next_sha

    def issues(self):
        self.scans += 1
        return iter(copy.deepcopy(self.existing + self.created))

    def create_issue(self, payload):
        if self.fail_issue:
            raise cloud.CloudError("Synthetic notification failure")
        self.created.append(dict(payload, state="open"))
        if self.lost_issue_response:
            raise cloud.CloudError("Synthetic lost response")


class ValidationTests(unittest.TestCase):
    def test_strict_valid_detached_report_and_old_event_identity(self):
        value = report(event("stopped", when=NOW - timedelta(days=500), reason="conflict"))
        value["blocked"] = copy.deepcopy(value["receipt"])
        clean = cloud.validate(value, policy())
        self.assertEqual(clean, value)
        clean["task"]["state"] = "Missing"
        self.assertEqual(value["task"]["state"], "Ready")

    def test_exact_keys_types_identity_and_timestamp_rejection(self):
        cases = []
        for key, value in [("extra", "C:\\private"), ("schema", True), ("schema", 2),
                           ("device", "0123456789abcdeF"), ("device", "0" * 16),
                           ("kind", "other"), ("canary", 1), ("canary", True),
                           ("observed_at", "2026-02-30T12:00:00Z"),
                           ("observed_at", "2026-10-21T12:00:00+00:00")]:
            value_report = report()
            value_report[key] = value
            cases.append(value_report)
        for task in [{"state": "Ready", "last_run": None},
                     {"state": "Ready", "last_run": None, "last_result": True},
                     {"state": "Unknown", "last_run": None, "last_result": 0}]:
            value_report = report()
            value_report["task"] = task
            cases.append(value_report)
        missing = report()
        del missing["launcher"]
        cases.append(missing)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                cloud.validate(value, policy())

    def test_reason_url_path_commit_and_event_rejection(self):
        for key, value in [("reason", "C:\\Users\\private\\token"),
                           ("reason", "arbitrary failure text"), ("reason", []),
                           ("run_url", WORKFLOW + "?token=secret"),
                           ("run_url", "https://github.com/other/repo/actions/runs/1"),
                           ("run_url", WORKFLOW + "/../2"), ("run_url", "file:///C:/private"),
                           ("commit", "A" * 40), ("commit", "a" * 39),
                           ("event_id", "1\n"), ("event_id", "1" * 25),
                           ("event_id", "../1"), ("event_id", 1), ("status", "success"),
                           ("observed_at", "2026-10-21T12:00:00Z\n"),
                           ("path", "C:\\private")]:
            value_report = report(event())
            value_report["receipt"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                cloud.validate(value_report, policy())

    def test_last_update_and_blocked_have_fixed_status(self):
        for name, status in [("last_update", "unchanged"), ("blocked", "updated")]:
            value = report()
            value[name] = event(status)
            with self.assertRaises(ValueError):
                cloud.validate(value, policy())

    def test_policy_and_canary_isolation(self):
        value = report()
        value["device"] = CANARY
        with self.assertRaises(ValueError):
            cloud.validate(value, policy())
        value["canary"] = True
        cloud.validate(value, policy())
        for invalid in [dict(policy(), schema=True), dict(policy(), devices=[]),
                        dict(policy(), devices=[DEVICE, DEVICE]),
                        dict(policy(), canary_devices=["f" * 16]),
                        dict(policy(), extra="path")]:
            with self.assertRaises(ValueError):
                cloud.validate_policy(invalid)
        other = dict(policy(), kind="native-review" if KIND == "jev" else "jev")
        with self.assertRaises(ValueError):
            cloud.validate(value, other)

    def test_cli_input_duplicate_keys_and_size_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_text('{"schema":1,"schema":2}', encoding="utf-8")
            with self.assertRaises(ValueError):
                cloud.load_json(path, 100)
            path.write_text(" " * 101, encoding="utf-8")
            with self.assertRaises(ValueError):
                cloud.load_json(path, 100)


class DecisionTests(unittest.TestCase):
    def test_unchanged_ready_enrolled_do_not_claim_success(self):
        for status in ("unchanged", "ready", "enrolled", "deferred"):
            self.assertEqual(cloud.decide(report(event(status)), NOW), [])

    def test_updated_once_and_historical_import_is_explicit(self):
        api = FakeAPI()
        value = report(event("updated"))
        value["last_update"] = copy.deepcopy(value["receipt"])
        self.assertEqual(cloud.receive(api, value, policy(), NOW, WORKFLOW), 1)
        self.assertEqual(cloud.receive(api, value, policy(), NOW, WORKFLOW), 0)
        self.assertIn("[Updater Updated] aaaaaaaaaaaa", api.created[0]["title"])
        old = report(event("stopped", "200", reason="ci-failure"))
        old["last_update"] = event("updated", "50", NOW - timedelta(days=1))
        planned = cloud.decide(old, NOW)
        history = next(item for item in planned if item["key"] == "event:updated:50")
        rendered = cloud.issue(old, history, WORKFLOW)
        self.assertIn("[Updater Receipt Imported]", rendered["title"])
        self.assertIn("does not indicate current task success", rendered["body"])
        cloud.receive(api, old, policy(), NOW, WORKFLOW)
        cloud.receive(api, old, policy(), NOW, WORKFLOW)
        self.assertEqual(len(api.created), 3)

    def test_sticky_stop_matching_exit_two_excludes_stale(self):
        value = report(event("stopped", when=NOW - timedelta(days=1), reason="conflict"))
        value["blocked"] = copy.deepcopy(value["receipt"])
        value["task"] = {"state": "Ready", "last_run": cloud.utc(NOW - timedelta(minutes=10)), "last_result": 2}
        self.assertEqual([item["category"] for item in cloud.decide(value, NOW)], ["stopped"])
        api = FakeAPI()
        cloud.receive(api, value, policy(), NOW, WORKFLOW)
        value["observed_at"] = cloud.utc(NOW + timedelta(hours=1))
        cloud.receive(api, value, policy(), NOW + timedelta(hours=1), WORKFLOW)
        self.assertEqual(len(api.created), 1)

    def test_old_current_updated_receipt_is_imported_history(self):
        value = report(event("updated", when=NOW - timedelta(days=1)))
        item, = cloud.decide(value, NOW)
        self.assertEqual(item["category"], "receipt-imported")
        rendered = cloud.issue(value, item, WORKFLOW)
        self.assertIn("[Updater Receipt Imported]", rendered["title"])
        self.assertNotIn("unclassified-stop", rendered["body"])
        # A later watchdog must preserve the original fresh event classification.
        fresh = report(event("updated"))
        self.assertEqual(cloud.decide(fresh, NOW + timedelta(hours=6))[0]["category"], "updated")

    def test_stale_enrolled_exit_zero_and_five_minute_boundary(self):
        value = report(event("enrolled", when=NOW - timedelta(days=1)))
        value["task"]["last_run"] = cloud.utc(NOW - timedelta(minutes=5))
        self.assertEqual(cloud.decide(value, NOW), [])
        value["task"]["last_run"] = cloud.utc(NOW - timedelta(minutes=5, seconds=1))
        self.assertEqual([item["category"] for item in cloud.decide(value, NOW)], ["stale"])
        self.assertEqual(cloud.decide(value, NOW)[0]["reason"], "stale-receipt")
        value["receipt"] = None
        self.assertEqual(cloud.decide(value, NOW)[0]["category"], "stale")

    def test_running_and_matching_receipt_are_not_stale(self):
        value = report(event("enrolled", when=NOW - timedelta(days=1)))
        value["task"]["state"] = "Running"
        value["task"]["last_run"] = cloud.utc(NOW - timedelta(hours=1))
        self.assertEqual(cloud.decide(value, NOW), [])
        value["task"]["state"] = "Ready"
        value["receipt"] = event("unchanged", when=NOW - timedelta(minutes=30))
        self.assertEqual(cloud.decide(value, NOW), [])

    def test_enrolled_timestamp_equal_to_last_run_is_stale_after_five_minutes(self):
        when = NOW - timedelta(minutes=5, seconds=1)
        value = report(event("enrolled", when=when))
        value["task"]["last_run"] = cloud.utc(when)
        self.assertEqual([item["category"] for item in cloud.decide(value, NOW)], ["stale"])
        value["receipt"]["observed_at"] = cloud.utc(NOW)
        self.assertEqual([item["category"] for item in cloud.decide(value, NOW)], ["stale"])
        value["task"]["state"] = "Running"
        self.assertEqual(cloud.decide(value, NOW), [])

    def test_disabled_missing_denied_stable_semantic_keys(self):
        for state in ("Disabled", "Missing", "Denied"):
            api = FakeAPI()
            value = report()
            value["task"]["state"] = state
            cloud.receive(api, value, policy(), NOW, WORKFLOW)
            value["observed_at"] = cloud.utc(NOW + timedelta(hours=1))
            value["task"]["last_run"] = cloud.utc(NOW + timedelta(hours=1))
            cloud.receive(api, value, policy(), NOW + timedelta(hours=1), WORKFLOW)
            self.assertEqual(len(api.created), 1)
            self.assertIn("[Updater Task " + state + "]", api.created[0]["title"])

    def test_launcher_failure_has_safe_context_and_no_ready_alert(self):
        value = report(event())
        value["launcher"] = event("ready", "200")
        self.assertEqual(cloud.decide(value, NOW), [])
        value["launcher"] = event("stopped", "201", reason="launcher-failure")
        item, = cloud.decide(value, NOW)
        self.assertEqual(item["category"], "launcher")
        rendered = cloud.issue(value, item, WORKFLOW)
        self.assertIn(value["launcher"]["commit"], rendered["body"])
        self.assertIn(value["launcher"]["run_url"], rendered["body"])
        self.assertIn(WORKFLOW, rendered["body"])

    def test_new_disabled_incident_after_successful_run_is_not_silenced(self):
        api = FakeAPI()
        value = report(event())
        value["task"]["state"] = "Disabled"
        cloud.receive(api, value, policy(), NOW, WORKFLOW)
        recovered = report(event(identity="101", when=NOW + timedelta(hours=1)), now=NOW + timedelta(hours=1))
        cloud.receive(api, recovered, policy(), NOW + timedelta(hours=1), WORKFLOW)
        recovered["task"]["state"] = "Disabled"
        cloud.receive(api, recovered, policy(), NOW + timedelta(hours=1), WORKFLOW)
        self.assertEqual(len(api.created), 2)


class PersistenceTests(unittest.TestCase):
    def test_closed_issue_marker_is_authoritative_without_edit_or_reopen(self):
        api = FakeAPI()
        value = report(event("stopped", reason="conflict"))
        item, = cloud.decide(value, NOW)
        api.existing.append(dict(cloud.issue(value, item, WORKFLOW), state="closed"))
        self.assertEqual(cloud.receive(api, value, policy(), NOW, WORKFLOW), 0)
        self.assertEqual(api.created, [])
        self.assertEqual(api.states[DEVICE][0]["seen_event_ids"], ["event:stopped:100"])

    def test_retry_after_final_state_write_failure_does_not_repeat_issue(self):
        api = FakeAPI()
        api.fail_write = 2
        value = report(event("updated"))
        with self.assertRaises(cloud.CloudError):
            cloud.receive(api, value, policy(), NOW, WORKFLOW)
        self.assertEqual(len(api.created), 1)
        self.assertEqual(api.states[DEVICE][0]["seen_event_ids"], [])
        api.created[0]["state"] = "closed"
        self.assertEqual(cloud.receive(api, value, policy(), NOW, WORKFLOW), 0)
        self.assertEqual(len(api.created), 1)

    def test_failed_initial_state_write_cannot_create_untracked_issue(self):
        api = FakeAPI()
        api.fail_write = 1
        with self.assertRaises(cloud.CloudError):
            cloud.receive(api, report(event("stopped")), policy(), NOW, WORKFLOW)
        self.assertEqual(api.created, [])

    def test_watchdog_retries_failed_notification_from_saved_report(self):
        api = FakeAPI()
        api.fail_issue = True
        with self.assertRaises(cloud.CloudError):
            cloud.receive(api, report(event("updated")), policy(), NOW, WORKFLOW)
        self.assertIn(DEVICE, api.states)
        api.fail_issue = False
        counts = cloud.watchdog(api, policy(), NOW + timedelta(minutes=1), WORKFLOW)
        self.assertEqual(counts, {"production": 1, "canary": 0})
        self.assertEqual(len(api.created), 1)

    def test_lost_issue_response_is_recovered_by_marker_scan(self):
        api = FakeAPI()
        api.lost_issue_response = True
        value = report(event("stopped"))
        with self.assertRaises(cloud.CloudError):
            cloud.receive(api, value, policy(), NOW, WORKFLOW)
        api.lost_issue_response = False
        self.assertEqual(cloud.receive(api, value, policy(), NOW, WORKFLOW), 0)
        self.assertEqual(len(api.created), 1)

    def test_fresh_report_old_sticky_events_and_out_of_order_replay(self):
        api = FakeAPI()
        initial = report(event("stopped", "1", NOW - timedelta(days=10), "conflict"))
        cloud.receive(api, initial, policy(), NOW, WORKFLOW)
        newer = report(event("unchanged", "2", NOW + timedelta(minutes=2)), NOW + timedelta(minutes=2))
        cloud.receive(api, newer, policy(), NOW + timedelta(minutes=2), WORKFLOW)
        before = copy.deepcopy(api.states[DEVICE])
        self.assertEqual(cloud.receive(api, initial, policy(), NOW + timedelta(minutes=3), WORKFLOW), 0)
        self.assertEqual(api.states[DEVICE], before)
        fresh = report(event("unchanged", "3", NOW + timedelta(hours=1)), NOW + timedelta(hours=1))
        cloud.receive(api, fresh, policy(), NOW + timedelta(hours=1), WORKFLOW)
        self.assertEqual(api.states[DEVICE][0]["received_at"], cloud.utc(NOW + timedelta(hours=1)))

    def test_freshness_enforced_only_on_report_not_old_event(self):
        for delta in (timedelta(minutes=-15, seconds=-1), timedelta(minutes=5, seconds=1)):
            api = FakeAPI()
            with self.assertRaises(ValueError):
                cloud.receive(api, report(now=NOW + delta), policy(), NOW, WORKFLOW)
            self.assertFalse(api.branch)
        value = report(event("stopped", when=NOW - timedelta(days=100)))
        cloud.receive(FakeAPI(), value, policy(), NOW, WORKFLOW)
        value["receipt"]["observed_at"] = cloud.utc(NOW + timedelta(minutes=6))
        with self.assertRaises(ValueError):
            cloud.receive(FakeAPI(), value, policy(), NOW, WORKFLOW)

    def test_last_receipt_and_update_survive_null_reports(self):
        api = FakeAPI()
        value = report(event("updated"))
        value["last_update"] = copy.deepcopy(value["receipt"])
        cloud.receive(api, value, policy(), NOW, WORKFLOW)
        cloud.receive(api, report(now=NOW + timedelta(minutes=1)), policy(), NOW + timedelta(minutes=1), WORKFLOW)
        saved = api.states[DEVICE][0]
        self.assertEqual(saved["last_receipt"], value["receipt"])
        self.assertEqual(saved["last_update"], value["last_update"])

    def test_current_updated_receipt_is_saved_without_duplicate_last_update_field(self):
        api = FakeAPI()
        value = report(event("updated"))
        cloud.receive(api, value, policy(), NOW, WORKFLOW)
        self.assertEqual(api.states[DEVICE][0]["last_update"], value["receipt"])

    def test_seen_history_eviction_still_uses_durable_marker(self):
        api = FakeAPI()
        value = report(event("updated"))
        cloud.receive(api, value, policy(), NOW, WORKFLOW)
        state, sha = api.states[DEVICE]
        state["seen_event_ids"] = ["event:updated:" + str(number) for number in range(1000, 1000 + cloud.MAX_SEEN)]
        api.states[DEVICE] = (state, sha)
        self.assertEqual(cloud.receive(api, value, policy(), NOW, WORKFLOW), 0)
        self.assertEqual(len(api.created), 1)
        self.assertEqual(len(api.states[DEVICE][0]["seen_event_ids"]), cloud.MAX_SEEN)


class WatchdogTests(unittest.TestCase):
    def test_schedule_does_not_create_branch_or_never_enrolled_failure(self):
        api = FakeAPI()
        self.assertEqual(cloud.watchdog(api, policy(), NOW, WORKFLOW), {"production": 0, "canary": 0})
        self.assertFalse(api.branch)
        api.branch = True
        cloud.watchdog(api, policy(), NOW, WORKFLOW)
        self.assertEqual(api.created, [])
        self.assertNotIn(CANARY, api.loaded)

    def test_outage_boundary_once_closed_dedup_and_new_contact_identity(self):
        api = FakeAPI()
        cloud.receive(api, report(event()), policy(), NOW, WORKFLOW)
        self.assertEqual(cloud.watchdog(api, policy(), NOW + timedelta(hours=3), WORKFLOW)["production"], 0)
        later = NOW + timedelta(hours=3, seconds=1)
        self.assertEqual(cloud.watchdog(api, policy(), later, WORKFLOW)["production"], 1)
        self.assertIn("[Updater Reporting Unavailable]", api.created[0]["title"])
        self.assertIn("No CI or local test conclusion", api.created[0]["body"])
        api.created[0]["state"] = "closed"
        self.assertEqual(cloud.watchdog(api, policy(), later + timedelta(days=1), WORKFLOW)["production"], 0)
        resumed = report(event(when=later), now=later)
        cloud.receive(api, resumed, policy(), later, WORKFLOW)
        cloud.watchdog(api, policy(), later + timedelta(hours=4), WORKFLOW)
        self.assertEqual(len(api.created), 2)

    def test_known_offline_deferral_suppresses_outage_not_real_stop(self):
        api = FakeAPI()
        value = report(event("deferred", reason="offline"))
        cloud.receive(api, value, policy(), NOW, WORKFLOW)
        self.assertEqual(cloud.watchdog(api, policy(), NOW + timedelta(days=3), WORKFLOW)["production"], 0)
        self.assertEqual(api.created, [])
        value["blocked"] = event("stopped", "200", reason="local-tests-failure")
        cloud.receive(api, value, policy(), NOW, WORKFLOW)
        self.assertEqual(len(api.created), 1)
        pending = report(event("deferred", reason="pending-ci"))
        cloud.receive(api, pending, policy(), NOW, WORKFLOW)
        self.assertEqual(cloud.watchdog(api, policy(), NOW + timedelta(hours=4), WORKFLOW)["production"], 1)

    def test_canary_alert_is_separate_and_watchdog_skips_canaries(self):
        api = FakeAPI()
        normal = report(event("updated"))
        cloud.receive(api, normal, policy(), NOW, WORKFLOW)
        canary = copy.deepcopy(normal)
        canary.update(device=CANARY, canary=True)
        cloud.receive(api, canary, policy(), NOW, WORKFLOW)
        self.assertEqual(len(api.created), 2)
        self.assertIn("[LIVE CANARY]", api.created[1]["title"])
        self.assertIn("not production", api.created[1]["body"])
        item, = cloud.decide(normal, NOW)
        self.assertNotEqual(cloud.marker(normal, item["key"]), cloud.marker(canary, item["key"]))
        api.loaded.clear()
        counts = cloud.watchdog(api, policy(), NOW + timedelta(days=1), WORKFLOW)
        self.assertEqual(counts, {"production": 1, "canary": 0})
        self.assertEqual(api.loaded, [DEVICE])


class TransportAndWorkflowTests(unittest.TestCase):
    def test_all_state_pagination_including_closed_marker_on_last_page(self):
        api = cloud.GitHubAPI(REPO)
        with patch.object(api, "request", side_effect=[[
                {"body": "unrelated", "state": "closed"} for _ in range(100)],
                [{"body": "last page", "state": "closed"}]]) as request:
            result = list(api.issues())
        self.assertEqual(len(result), 101)
        self.assertEqual(request.call_args_list[0].args[1], "issues?state=all&per_page=100&page=1")
        self.assertEqual(request.call_args_list[1].args[1], "issues?state=all&per_page=100&page=2")

    def test_contents_optimistic_sha_and_explicit_branch_creation_only(self):
        api = cloud.GitHubAPI(REPO)
        with patch.object(api, "request", side_effect=[None]) as request:
            self.assertFalse(api.ensure_branch(create=False))
            self.assertEqual(request.call_count, 1)
        with patch.object(api, "request", side_effect=[None, {"object": {"sha": "b" * 40}}, {}]) as request:
            self.assertTrue(api.ensure_branch(create=True))
            self.assertEqual(request.call_args_list[2].args[2], {"ref": "refs/heads/updater-receipts", "sha": "b" * 40})
        with patch.object(api, "request", return_value={"content": {"sha": "new-sha"}}) as request:
            self.assertEqual(api.save_state(DEVICE, {"safe": True}, "old-sha"), "new-sha")
            payload = request.call_args.args[2]
            self.assertEqual(payload["sha"], "old-sha")
            self.assertEqual(payload["branch"], "updater-receipts")
            self.assertEqual(json.loads(base64.b64decode(payload["content"])), {"safe": True})

    def test_gh_errors_sanitized_and_payload_only_passed_as_stdin(self):
        api = cloud.GitHubAPI(REPO)
        failed = subprocess.CompletedProcess([], 1, "HTTP/2.0 403 Forbidden\n\nsecret body", "secret token")
        with patch.object(cloud.subprocess, "run", return_value=failed) as run:
            with self.assertRaises(cloud.CloudError) as raised:
                api.request("POST", "issues", {"body": "safe"})
            self.assertNotIn("secret", str(raised.exception))
            self.assertEqual(json.loads(run.call_args.kwargs["input"]), {"body": "safe"})
            self.assertNotIn("safe", run.call_args.args[0])
            self.assertEqual(run.call_args.kwargs["timeout"], 60)
        ok = subprocess.CompletedProcess([], 0, 'HTTP/2.0 200 OK\nContent-Type: application/json\n\n{"ok":true}', "")
        with patch.object(cloud.subprocess, "run", return_value=ok):
            self.assertEqual(api.request("GET", "issues"), {"ok": True})
        with patch.object(cloud.subprocess, "run", side_effect=subprocess.TimeoutExpired("gh", 60)):
            with self.assertRaises(cloud.CloudError):
                api.request("GET", "issues")

    def test_owner_assignment_only_422_falls_back(self):
        api = cloud.GitHubAPI(REPO)
        with patch.object(api, "request", side_effect=[None, {}]) as request:
            api.create_issue({"title": "safe", "body": "safe"})
            self.assertEqual(request.call_args_list[0].args[2]["assignees"], ["medking82"])
            self.assertNotIn("assignees", request.call_args_list[1].args[2])
        with patch.object(api, "request", side_effect=cloud.CloudError("API failure")) as request:
            with self.assertRaises(cloud.CloudError):
                api.create_issue({"title": "safe", "body": "safe"})
            self.assertEqual(request.call_count, 1)

    def test_workflow_uses_only_trusted_code_and_six_hour_watchdog(self):
        workflow = (ROOT / ".github" / "workflows" / "updater-receipts.yml").read_text(encoding="utf-8")
        for expected in ["'17 */6 * * *'", "cancel-in-progress: false", "group: updater-receipts",
                         "contents: write", "issues: write", "github.actor == github.repository_owner",
                         "github.event.sender.login == github.repository_owner", "ref: main",
                         "persist-credentials: false", "GH_TOKEN: ${{ github.token }}",
                         "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683",
                         "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
                         "python -B " + DIRECTORY + "/receipt_cloud.py"]:
            self.assertIn(expected, workflow)
        self.assertNotIn("client_payload", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertNotIn("pip install", workflow)

    def test_main_rejects_actor_before_api_and_uses_exact_client_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            event_path = Path(directory) / "event.json"
            policy_path = Path(directory) / "policy.json"
            policy_path.write_text(json.dumps(policy()), encoding="utf-8")
            payload = {"repository": {"full_name": REPO, "owner": {"login": "medking82"}},
                       "sender": {"login": "other"}, "action": "codex-updater-receipt",
                       "client_payload": report(event("updated"))}
            event_path.write_text(json.dumps(payload), encoding="utf-8")
            environment = {"GITHUB_REPOSITORY": REPO, "GITHUB_REF": "refs/heads/main",
                           "GITHUB_RUN_ID": "900", "GITHUB_ACTOR": "medking82",
                           "GITHUB_EVENT_NAME": "repository_dispatch"}
            argv = ["--event", str(event_path), "--policy", str(policy_path)]
            with patch.dict(os.environ, environment, clear=True), patch.object(cloud, "GitHubAPI") as api:
                with patch("sys.stderr", new=io.StringIO()):
                    self.assertEqual(cloud.main(argv), 1)
                api.assert_not_called()
            payload["sender"]["login"] = "medking82"
            event_path.write_text(json.dumps(payload), encoding="utf-8")
            with patch.dict(os.environ, environment, clear=True), patch.object(cloud, "receive", return_value=1) as receive:
                with patch("sys.stdout", new=io.StringIO()):
                    self.assertEqual(cloud.main(argv), 0)
                self.assertEqual(receive.call_args.args[1], payload["client_payload"])


if __name__ == "__main__":
    unittest.main()
