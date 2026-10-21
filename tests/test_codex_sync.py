"""Offline acceptance tests for the exact-commit update and fail-stop boundaries."""
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "codex"))
import upstream


class GitFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="codex-sync-", dir=ROOT / "tests")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / "fork"
        self.repo.mkdir()
        upstream.git(self.repo, "init", "-b", "main")
        upstream.git(self.repo, "config", "user.name", "Synthetic Test")
        upstream.git(self.repo, "config", "user.email", "test@example.invalid")
        upstream.git(self.repo, "config", "commit.gpgsign", "false")
        self.write(self.repo, "engine.txt", "base\n")
        self.save(self.repo)
        self.base = upstream.git(self.repo, "rev-parse", "HEAD")
        self.remote = self.root / "remote.git"
        upstream.git(self.root, "clone", "--bare", str(self.repo), str(self.remote))
        self.other = self.root / "upstream"
        upstream.git(self.root, "clone", str(self.repo), str(self.other))
        upstream.git(self.other, "config", "user.name", "Synthetic Test")
        upstream.git(self.other, "config", "user.email", "test@example.invalid")
        upstream.git(self.other, "config", "commit.gpgsign", "false")
        upstream.git(self.repo, "remote", "add", "origin", str(self.remote))
        self.artifact = self.root / "artifact"

    def write(self, repo, name, text):
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def save(self, repo):
        upstream.git(repo, "add", ".")
        upstream.git(repo, "commit", "-m", "Synthetic fixture")

    def candidate(self):
        self.write(self.other, "engine.txt", "new upstream\n")
        self.save(self.other)
        return upstream.prepare(self.repo, self.artifact, upstream=str(self.other))


class UpstreamIntegrationTests(GitFixture):
    def test_unchanged_skips_publication(self):
        result = upstream.prepare(self.repo, self.artifact, upstream=str(self.other))
        self.assertEqual(result["changed"], "false")
        self.assertFalse(self.artifact.exists())

    def test_validated_bundle_publishes_exact_candidate(self):
        data = self.candidate()
        upstream.git(self.repo, "checkout", "--detach", self.base)
        result = upstream.publish(self.repo, self.artifact, self.root / "result.json")
        self.assertEqual(result["candidate"], data["candidate"])
        self.assertEqual(upstream.git(self.remote, "rev-parse", "main"), data["candidate"])

    def test_conflict_preserves_main_and_aborts_merge(self):
        self.write(self.repo, "engine.txt", "fork choice\n")
        self.save(self.repo)
        fork = upstream.git(self.repo, "rev-parse", "HEAD")
        self.write(self.other, "engine.txt", "upstream choice\n")
        self.save(self.other)
        with self.assertRaisesRegex(upstream.StopUpdate, "conflict"):
            upstream.prepare(self.repo, self.artifact, upstream=str(self.other))
        self.assertEqual(upstream.git(self.repo, "rev-parse", "HEAD"), fork)
        self.assertFalse((self.repo / ".git/MERGE_HEAD").exists())
        self.assertEqual(upstream.git(self.remote, "rev-parse", "main"), self.base)

    def test_control_change_requires_manual_review(self):
        self.write(self.other, "codex/authorization.py", "# changed control\n")
        self.save(self.other)
        with self.assertRaisesRegex(upstream.StopUpdate, "manual review"):
            upstream.prepare(self.repo, self.artifact, upstream=str(self.other))
        self.assertEqual(upstream.git(self.remote, "rev-parse", "main"), self.base)

    def test_moved_main_is_not_overwritten(self):
        self.candidate()
        upstream.git(self.repo, "checkout", "--detach", self.base)
        self.write(self.repo, "user.txt", "concurrent change\n")
        self.save(self.repo)
        raced = upstream.git(self.repo, "rev-parse", "HEAD")
        upstream.git(self.repo, "push", "origin", raced + ":main")
        upstream.git(self.repo, "checkout", "--detach", self.base)
        with self.assertRaisesRegex(upstream.StopUpdate, "advanced"):
            upstream.publish(self.repo, self.artifact, self.root / "result.json")
        self.assertEqual(upstream.git(self.remote, "rev-parse", "main"), raced)

    def test_bundle_identity_mismatch_cannot_publish(self):
        self.candidate()
        data = json.loads((self.artifact / "candidate.json").read_text())
        data["candidate"] = self.base
        upstream.write_json(self.artifact / "candidate.json", data)
        upstream.git(self.repo, "checkout", "--detach", self.base)
        with self.assertRaisesRegex(upstream.StopUpdate, "tested commit"):
            upstream.publish(self.repo, self.artifact, self.root / "result.json")
        self.assertEqual(upstream.git(self.remote, "rev-parse", "main"), self.base)

    def test_validate_current_exercises_pipeline_without_pushing_change(self):
        data = upstream.prepare(self.repo, self.artifact, validate_current=True, upstream=str(self.other))
        self.assertEqual(data["candidate"], self.base)
        result = upstream.publish(self.repo, self.artifact, self.root / "result.json")
        self.assertEqual(result["status"], "unchanged")


@unittest.skipIf(sys.version_info < (3, 11), "Local Codex updater requires Python 3.11+")
class LocalUpdateTests(GitFixture):
    def setUp(self):
        super().setUp()
        import sync
        self.sync = sync
        for name in ("codex", "jevkit", "skills"):
            shutil.copytree(ROOT / name, self.repo / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copyfile(ROOT / ".gitignore", self.repo / ".gitignore")
        self.save(self.repo)
        self.base = upstream.git(self.repo, "rev-parse", "HEAD")
        upstream.git(self.repo, "push", "origin", "main")
        self.home = self.root / "home"
        (self.home / "bin").mkdir(parents=True)
        self.write(self.home, "bin/invoke-hidden.ps1", "# synthetic\n")
        self.write(self.home, "config.toml", 'model = "user-selected"\n')
        self.profile = patch.object(Path, "home", return_value=self.root / "profile")
        self.profile.start()
        self.addCleanup(self.profile.stop)
        sync.load_installer(self.repo).install(self.repo, self.home, Path(sys.executable), apply=True)
        self.config = (self.home / "config.toml").read_bytes()
        self.hooks = (self.home / "hooks.json").read_bytes()
        self.state = {"repo": str(self.repo), "home": str(self.home), "controls": upstream.controls(self.repo, self.base),
                      "runner_files": {n: sync.digest(ROOT / "codex" / n) for n in ("sync.py", "upstream.py")}}
        # A trusted candidate changes toolkit code without touching adapter controls.
        self.write(self.repo, "jevkit/update_fixture.py", "# new upstream feature\n")
        self.save(self.repo)
        self.head = upstream.git(self.repo, "rev-parse", "HEAD")
        upstream.git(self.repo, "push", "origin", "main")
        upstream.git(self.repo, "reset", "--keep", self.base)  # Fixture-owned commit only.
        upstream.git(self.repo, "remote", "set-url", "origin", "https://github.com/" + upstream.FORK + ".git")
        real_git = upstream.git
        def local_git(repo, *args, **kwargs):
            if args[:3] == ("fetch", "--no-tags", "origin"):
                args = (*args[:2], str(self.remote), *args[3:])
            return real_git(repo, *args, **kwargs)
        self.git_patch = patch.object(sync, "git", side_effect=local_git)
        self.git_patch.start()
        self.addCleanup(self.git_patch.stop)
        self.calls = []

    def get(self, endpoint, **kwargs):
        if endpoint == "actions/workflows/" + upstream.WORKFLOW:
            return {"id": 99, "state": "active"}
        if endpoint.startswith("issues?"):
            return []
        if "/runs?" in endpoint:
            return {"workflow_runs": [{"id": 17, "workflow_id": 99, "head_branch": "main", "event": "schedule",
                    "status": "completed", "conclusion": "success", "head_sha": self.base,
                    "path": ".github/workflows/" + upstream.WORKFLOW, "html_url": "https://example.invalid/run/17"}]}
        if endpoint.endswith("/artifacts?per_page=100"):
            return {"artifacts": [{"id": 25, "name": "jev-sync-result", "size_in_bytes": 600, "expired": False}]}
        if endpoint == "actions/artifacts/25/zip":
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, "w") as archive:
                archive.writestr("result.json", json.dumps({"repository": upstream.FORK, "workflow": upstream.WORKFLOW,
                    "candidate": self.head, "base": self.base, "upstream": self.head, "run_id": "17", "status": "updated"}))
            return stream.getvalue()
        self.fail("unexpected endpoint " + endpoint)

    def run_update(self, **kwargs):
        return self.sync.update(self.state, apply=True, get=self.get,
                                test=lambda stage, temporary: self.calls.append(str(stage)), **kwargs)

    def assert_not_applied(self):
        self.assertEqual(upstream.git(self.repo, "rev-parse", "HEAD"), self.base)
        self.assertEqual(self.sync.installed(self.home)["source_commit"], self.base)
        self.assertEqual((self.home / "config.toml").read_bytes(), self.config)
        self.assertEqual((self.home / "hooks.json").read_bytes(), self.hooks)

    def test_proven_tested_commit_updates_source_and_runtime_without_config_changes(self):
        result = self.run_update()
        self.assertEqual(result["status"], "updated")
        self.assertEqual(upstream.git(self.repo, "rev-parse", "HEAD"), self.head)
        self.assertEqual(self.sync.installed(self.home)["source_commit"], self.head)
        self.assertEqual((self.home / "config.toml").read_bytes(), self.config)
        self.assertEqual((self.home / "hooks.json").read_bytes(), self.hooks)
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(Path(result["backup"]).is_dir())

    def test_failed_native_tests_do_not_update_source_or_runtime(self):
        def failed(stage, temporary):
            raise upstream.StopUpdate("synthetic tests failed")
        with self.assertRaisesRegex(upstream.StopUpdate, "tests failed"):
            self.sync.update(self.state, apply=True, get=self.get, test=failed)
        self.assert_not_applied()

    def test_owned_file_edits_are_preserved_before_network(self):
        owned = self.home / "skills/jev/SKILL.md"
        owned.write_text("user edits\n")
        with self.assertRaisesRegex(upstream.StopUpdate, "local edits"):
            self.run_update()
        self.assertEqual(owned.read_text(), "user edits\n")
        self.assertEqual(self.calls, [])

    def test_missing_owned_file_is_not_silently_recreated(self):
        (self.home / "skills/jev/SKILL.md").unlink()
        with self.assertRaisesRegex(upstream.StopUpdate, "missing files"):
            self.run_update()
        self.assertEqual(self.calls, [])

    def test_uncommitted_source_is_preserved(self):
        self.write(self.repo, "engine.txt", "user edits\n")
        with self.assertRaisesRegex(upstream.StopUpdate, "clean main"):
            self.run_update()
        self.assertEqual((self.repo / "engine.txt").read_text(), "user edits\n")
        self.assertEqual(self.calls, [])

    def test_disabled_schedule_stops_without_applying(self):
        original = self.get
        def disabled(endpoint, **kwargs):
            return {"id": 99, "state": "disabled_manually"} if endpoint.endswith(upstream.WORKFLOW) else original(endpoint, **kwargs)
        with self.assertRaisesRegex(upstream.StopUpdate, "not active"):
            self.sync.update(self.state, apply=True, get=disabled)
        self.assert_not_applied()

    def test_open_stop_notice_stops_without_applying(self):
        original = self.get
        def stopped(endpoint, **kwargs):
            return [{"title": upstream.STOP_TITLE}] if endpoint.startswith("issues?") else original(endpoint, **kwargs)
        with self.assertRaisesRegex(upstream.StopUpdate, "stop notice"):
            self.sync.update(self.state, apply=True, get=stopped)
        self.assert_not_applied()

    def test_unproven_main_cannot_install(self):
        original = self.get
        def no_proof(endpoint, **kwargs):
            return {"artifacts": []} if endpoint.endswith("/artifacts?per_page=100") else original(endpoint, **kwargs)
        with self.assertRaisesRegex(upstream.StopUpdate, "no successful exact-commit"):
            self.sync.update(self.state, apply=True, get=no_proof)
        self.assert_not_applied()

    def test_config_change_during_tests_stops_without_overwriting_user(self):
        def change(stage, temporary):
            with (self.home / "config.toml").open("a") as stream:
                stream.write('fast = true\n')
        with self.assertRaisesRegex(upstream.StopUpdate, "changed during validation"):
            self.sync.update(self.state, apply=True, get=self.get, test=change)
        self.assertEqual(upstream.git(self.repo, "rev-parse", "HEAD"), self.base)
        self.assertIn("fast = true", (self.home / "config.toml").read_text())

    def test_preview_refuses_new_hook_or_config_or_retirement(self):
        good = {"retire_paths": [], "config_changed": False, "hooks_changed": False, "hook_definition_changed": False}
        self.sync.validate_preview(good)
        for key in ("config_changed", "hooks_changed", "hook_definition_changed", "retire_paths"):
            with self.subTest(key=key), self.assertRaises(upstream.StopUpdate):
                self.sync.validate_preview(dict(good, **{key: ["old"] if key == "retire_paths" else True}))

    def test_sticky_stop_does_not_retry_or_change_receipt(self):
        runtime = self.root / "runner"
        runtime.mkdir()
        stopped = {"status": "stopped", "reason": "tests failed", "event_id": "one"}
        upstream.write_json(runtime / "state.json", {"blocked": stopped})
        with patch.object(sys, "argv", ["sync.py", "run", "--runtime", str(runtime), "--apply"]), patch.object(self.sync, "update") as update:
            self.assertEqual(self.sync.main(), 2)
        update.assert_not_called()
        self.assertEqual(json.loads((runtime / "state.json").read_text())["blocked"], stopped)

    def test_cli_failure_records_a_persistent_stop(self):
        runtime = self.root / "runner"
        runtime.mkdir()
        upstream.write_json(runtime / "state.json", self.state)
        with patch.object(sys, "argv", ["sync.py", "run", "--runtime", str(runtime), "--apply"]), patch.object(self.sync, "update", side_effect=upstream.StopUpdate("synthetic tests failed")):
            self.assertEqual(self.sync.main(), 2)
        state = json.loads((runtime / "state.json").read_text())
        receipt = json.loads((runtime / "last-run.json").read_text())
        self.assertEqual(state["blocked"], receipt)
        self.assertEqual(receipt["status"], "stopped")
        self.assert_not_applied()

    def test_offline_check_defers_without_latching_or_applying(self):
        runtime = self.root / "runner"
        runtime.mkdir()
        upstream.write_json(runtime / "state.json", dict(self.state, blocked=None))
        with patch.object(sys, "argv", ["sync.py", "run", "--runtime", str(runtime), "--apply"]), patch.object(self.sync, "update", side_effect=self.sync.DeferredUpdate("temporarily offline")):
            self.assertEqual(self.sync.main(), 0)
        self.assertIsNone(json.loads((runtime / "state.json").read_text())["blocked"])
        self.assertEqual(json.loads((runtime / "last-run.json").read_text())["status"], "deferred")
        self.assert_not_applied()

    def test_transport_outage_defers_but_permission_denial_stops_without_fallback(self):
        for message, expected in ((b"error connecting to api.github.com", self.sync.DeferredUpdate),
                                  (b"HTTP 403: Resource not accessible", upstream.StopUpdate)):
            result = subprocess.CompletedProcess(["gh"], 1, stdout=b"", stderr=message)
            with self.subTest(message=message), patch.object(self.sync.subprocess, "run", return_value=result) as run:
                with self.assertRaises(expected):
                    self.sync.api("actions/workflows/" + upstream.WORKFLOW)
                self.assertEqual(run.call_count, 1)
        with patch.object(self.sync.subprocess, "run", side_effect=subprocess.TimeoutExpired("gh", 120)):
            with self.assertRaises(self.sync.DeferredUpdate):
                self.sync.api("actions/workflows/" + upstream.WORKFLOW)
