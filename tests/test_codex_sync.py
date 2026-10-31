"""Offline acceptance tests for the exact-commit update and fail-stop boundaries."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "codex"))
import upstream
import official


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
        self.official = self.root / "official"
        self.official.mkdir()
        upstream.git(self.official, "init", "-b", "main")
        upstream.git(self.official, "config", "user.name", "Synthetic Test")
        upstream.git(self.official, "config", "user.email", "test@example.invalid")
        upstream.git(self.official, "config", "commit.gpgsign", "false")
        self.write(self.official, "skills/typesafe-ai/SKILL.md",
                   "---\nname: typesafe-ai\nlicense: MIT\n---\n\n# Synthetic Reference\n")
        self.write(self.official, "skills/typesafe-ai/LICENSE",
                   "MIT License\n\nPermission is hereby granted for this synthetic fixture.\n")
        self.save(self.official)
        official.refresh(self.repo, upstream=str(self.official))
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

    def write(self, repo, name, text):
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def save(self, repo):
        upstream.git(repo, "add", ".")
        upstream.git(repo, "commit", "-m", "Synthetic fixture")

    def sync(self):
        return upstream.sync(self.repo, upstream=str(self.other), official_upstream=str(self.official))

    def head(self, repo):
        return upstream.git(repo, "rev-parse", "HEAD")


class UpstreamSyncTests(GitFixture):
    def test_unchanged_upstream_reports_no_change(self):
        result = self.sync()
        self.assertEqual(result["changed"], "false")
        self.assertEqual(self.head(self.repo), self.base)

    def test_upstream_change_is_merged_but_never_pushed(self):
        self.write(self.other, "engine.txt", "new upstream\n")
        self.save(self.other)
        result = self.sync()
        self.assertEqual(result["changed"], "true")
        self.assertEqual((self.repo / "engine.txt").read_text(), "new upstream\n")
        self.assertEqual(result["upstream"], self.head(self.other))
        # The workflow pushes; the helper itself never changes the remote.
        self.assertEqual(upstream.git(self.remote, "rev-parse", "main"), self.base)

    def test_fork_changes_are_kept_by_a_merge(self):
        self.write(self.repo, "fork.txt", "fork only\n")
        self.save(self.repo)
        self.write(self.other, "engine.txt", "new upstream\n")
        self.save(self.other)
        result = self.sync()
        self.assertEqual(result["changed"], "true")
        self.assertEqual((self.repo / "fork.txt").read_text(), "fork only\n")
        self.assertEqual((self.repo / "engine.txt").read_text(), "new upstream\n")

    def test_conflict_preserves_main_and_aborts_merge(self):
        self.write(self.repo, "engine.txt", "fork choice\n")
        self.save(self.repo)
        fork = self.head(self.repo)
        self.write(self.other, "engine.txt", "upstream choice\n")
        self.save(self.other)
        with self.assertRaisesRegex(upstream.StopUpdate, "conflict"):
            self.sync()
        self.assertEqual(self.head(self.repo), fork)
        self.assertFalse((self.repo / ".git/MERGE_HEAD").exists())

    def test_official_reference_change_is_committed(self):
        self.write(self.official, "skills/typesafe-ai/SKILL.md",
                   "---\nname: typesafe-ai\nlicense: MIT\n---\n\n# Updated Synthetic Reference\n")
        self.save(self.official)
        result = self.sync()
        self.assertEqual(result["changed"], "true")
        self.assertEqual(result["official"], self.head(self.official))
        self.assertEqual(official.checkout(self.repo)[0]["commit"], self.head(self.official))
        self.assertEqual(upstream.git(self.repo, "status", "--porcelain"), "")


@unittest.skipIf(sys.version_info < (3, 11), "Local Codex updater requires Python 3.11+")
class LocalUpdateTests(GitFixture):
    def setUp(self):
        super().setUp()
        import sync
        self.sync = sync
        for name in ("codex", "jevkit", "skills", "vendor"):
            shutil.copytree(ROOT / name, self.repo / name, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
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
        runner = self.root / "runtime"
        runner.mkdir()
        for name in sync.RUNNERS:
            source = ROOT / "codex" / name
            (runner / name).write_bytes(source.read_bytes() if source.is_file() else b"synthetic pinned launcher metadata\n")
        self.runner_patch = patch.object(sync, "__file__", str(runner / "sync.py"))
        self.runner_patch.start()
        self.addCleanup(self.runner_patch.stop)
        self.state = {"repo": str(self.repo), "home": str(self.home), "controls": upstream.controls(self.repo, self.base),
                      "runner_files": {n: sync.digest(runner / n) for n in sync.RUNNERS}}
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
        if endpoint.startswith("actions/workflows/" + upstream.TEST_WORKFLOW + "/runs?head_sha="):
            sha = endpoint.split("head_sha=", 1)[1].split("&", 1)[0]
            return {"workflow_runs": [dict(self.test_run, head_sha=sha)] if sha == self.head else []}
        self.fail("unexpected endpoint " + endpoint)

    test_run = {"id": 17, "status": "completed", "conclusion": "success",
                "path": ".github/workflows/test.yml", "html_url": "https://example.invalid/run/17"}

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

    def test_pending_github_tests_defer_without_applying(self):
        with patch.object(self, "test_run", dict(self.test_run, status="in_progress", conclusion=None)):
            with self.assertRaisesRegex(self.sync.DeferredUpdate, "still running"):
                self.run_update()
        self.assert_not_applied()
        self.assertEqual(self.calls, [])

    def test_failed_github_tests_defer_without_applying(self):
        with patch.object(self, "test_run", dict(self.test_run, conclusion="failure")):
            with self.assertRaisesRegex(self.sync.DeferredUpdate, "no passing GitHub tests"):
                self.run_update()
        self.assert_not_applied()
        self.assertEqual(self.calls, [])

    def test_passing_run_of_another_workflow_is_not_proof(self):
        with patch.object(self, "test_run", dict(self.test_run, path=".github/workflows/other.yml")):
            with self.assertRaises(self.sync.DeferredUpdate):
                self.run_update()
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
