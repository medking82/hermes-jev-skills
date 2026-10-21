import hashlib
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


@unittest.skipIf(sys.version_info < (3, 11), "Codex installer requires Python 3.11+")
class CodexInstallTests(unittest.TestCase):
    def setUp(self):
        self.repo = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location("codex_installer", self.repo / "codex/install.py")
        self.installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.installer)
        self.temp = tempfile.TemporaryDirectory(prefix="codex-install-", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        profile = patch.object(Path, "home", return_value=self.home / "profile")
        profile.start()
        self.addCleanup(profile.stop)
        self.shared = Path.home() / ".agents/skills"
        (self.home / "bin").mkdir()
        (self.home / "bin/invoke-hidden.ps1").write_text("# synthetic runner\n")
        self.old = self.home / "skills/jev-search"
        self.old.mkdir(parents=True)
        (self.old / "SKILL.md").write_text("old workflow\n")
        (self.home / "config.toml").write_text('model = "user-selected"\n')
        self.foreign = {"type": "command", "command": "existing-check", "timeout": 1}
        (self.home / "hooks.json").write_text(json.dumps({"hooks": {"UserPromptSubmit": [{"hooks": [self.foreign]}]}}))

    def run_install(self, apply):
        return self.installer.install(self.repo, self.home, Path(sys.executable), apply=apply)

    def test_preview_has_no_writes(self):
        before = {p.relative_to(self.home): p.read_bytes() for p in self.home.rglob("*") if p.is_file()}
        report = self.run_install(False)
        self.assertIn("jev-search", report["retire"])
        self.assertEqual(before, {p.relative_to(self.home): p.read_bytes() for p in self.home.rglob("*") if p.is_file()})

    def test_installs_one_entrypoint_preserves_config_hooks_and_archives_old_skill(self):
        report = self.run_install(True)
        self.assertEqual(report["status"], "installed")
        self.assertFalse(self.old.exists())
        self.assertEqual((Path(report["backup"]) / "retired/jev-search/SKILL.md").read_text(), "old workflow\n")
        self.assertEqual(len(list((self.home / "skills").rglob("SKILL.md"))), 1)
        reference = self.home / "skills/jev/references/official/typesafe-ai"
        self.assertTrue((reference / "guide.md").is_file())
        self.assertFalse((reference / "SKILL.md").exists())
        manifest = json.loads((self.home / "jev/installation.json").read_text())
        self.assertEqual(manifest["official_source"]["repository"], "typesafe-ai/skills")
        self.assertEqual(manifest["official_source"]["commit"], json.loads((reference / "source.json").read_text())["commit"])
        hooks = json.loads((self.home / "hooks.json").read_text())["hooks"]["UserPromptSubmit"]
        self.assertIn(self.foreign, [h for g in hooks for h in g["hooks"]])
        config = self.installer.tomllib.loads((self.home / "config.toml").read_text())
        self.assertEqual(config["model"], "user-selected")
        self.assertEqual(len(config["skills"]["config"]), 2 * len(self.installer.LEGACY_SKILLS))
        self.assertTrue(all(s["enabled"] is False for s in config["skills"]["config"]))
        self.assertTrue((self.home / "tools/hermes-jev-skills/jevkit/codex.py").exists())

    def test_second_install_does_not_duplicate_hook_or_disable_entries(self):
        self.run_install(True)
        self.run_install(True)
        hooks = json.loads((self.home / "hooks.json").read_text())["hooks"]["UserPromptSubmit"]
        self.assertEqual(sum(len(g["hooks"]) for g in hooks), 2)
        config = self.installer.tomllib.loads((self.home / "config.toml").read_text())
        self.assertEqual(len(config["skills"]["config"]), 2 * len(self.installer.LEGACY_SKILLS))

    def test_second_install_refreshes_accepted_official_references_without_invocation_changes(self):
        self.run_install(True)
        manifest_file = self.home / "jev/installation.json"
        before = json.loads(manifest_file.read_text())
        reference = self.home / "skills/jev/references/official/typesafe-ai"
        unchanged = {name: (self.home / name).read_bytes() for name in (
            "config.toml", "hooks.json", "skills/jev/SKILL.md", "skills/jev/agents/openai.yaml")}

        # Provenance acceptance is covered by test_codex_official; supply only the
        # next accepted reference package, without editing this checkout or Git.
        next_package = self.installer.official.reference_files(self.repo)
        source, source_files = self.installer.official.checkout(self.repo)
        next_commit = ("b" if source["commit"] != "b" * 40 else "c") * 40
        addition = b"\nAccepted official update: batch independent questions over the same state.\n"
        source_files["SKILL.md"] += addition
        next_source = self.installer.official.metadata(next_commit, source_files)
        next_package["guide.md"] = next_package["guide.md"].replace(
            source["commit"].encode(), next_commit.encode(), 1) + addition
        next_package["source.json"] = (json.dumps(next_source, indent=2) + "\n").encode("utf-8")
        with patch.object(self.installer.official, "reference_files", return_value=next_package):
            report = self.run_install(True)

        self.assertEqual(report["status"], "installed")
        after = json.loads(manifest_file.read_text())
        identity = {key: next_source[key] for key in ("repository", "commit")}
        self.assertEqual(after["official_source"], identity)
        self.assertEqual(report["official_source"], identity)
        self.assertNotEqual(after["official_source"], before["official_source"])
        self.assertEqual(json.loads((reference / "source.json").read_bytes()), next_source)
        for name in ("guide.md", "source.json"):
            with self.subTest(reference=name):
                target = reference / name
                relative = target.relative_to(self.home).as_posix()
                self.assertEqual(target.read_bytes(), next_package[name])
                self.assertEqual(after["files"][relative], hashlib.sha256(next_package[name]).hexdigest())
                self.assertNotEqual(after["files"][relative], before["files"][relative])
        for name, content in unchanged.items():
            with self.subTest(unchanged=name):
                self.assertEqual((self.home / name).read_bytes(), content)
        self.assertEqual(after["hook_handler"], before["hook_handler"])
        self.assertEqual([p.relative_to(self.home).as_posix()
                          for root in (self.home / "skills", self.shared)
                          for p in root.rglob("SKILL.md")], ["skills/jev/SKILL.md"])

    def test_local_runtime_drift_is_not_overwritten(self):
        self.run_install(True)
        skill = self.home / "skills/jev/SKILL.md"
        skill.write_text("local user edits\n")
        with self.assertRaisesRegex(ValueError, "local edits"):
            self.run_install(True)
        self.assertEqual(skill.read_text(), "local user edits\n")

    def test_future_standalone_entrypoint_is_archived_and_disabled(self):
        future = self.home / "skills/jev-future/SKILL.md"
        future.parent.mkdir()
        future.write_text("custom future entrypoint\n")
        report = self.run_install(True)
        self.assertIn("jev-future", report["retire"])
        self.assertFalse(future.exists())
        self.assertEqual((Path(report["backup"]) / "retired/jev-future/SKILL.md").read_text(), "custom future entrypoint\n")

    def test_shared_user_copies_are_retired_without_backup_collisions_or_other_skill_changes(self):
        for name in ("jev-search", "jev-future", "unrelated"):
            entry = self.shared / name / "SKILL.md"
            entry.parent.mkdir(parents=True)
            entry.write_text("shared " + name + "\n")
        report = self.run_install(False)
        self.assertTrue((self.shared / "jev-search/SKILL.md").exists())
        self.assertIn(str(self.shared / "jev-search"), report["retire_paths"])
        report = self.run_install(True)
        archive = Path(report["backup"]) / "retired"
        self.assertEqual((archive / "jev-search/SKILL.md").read_text(), "old workflow\n")
        self.assertEqual((archive / "agents/jev-search/SKILL.md").read_text(), "shared jev-search\n")
        self.assertEqual((archive / "agents/jev-future/SKILL.md").read_text(), "shared jev-future\n")
        self.assertFalse((self.shared / "jev-search").exists())
        self.assertFalse((self.shared / "jev-future").exists())
        self.assertEqual((self.shared / "unrelated/SKILL.md").read_text(), "shared unrelated\n")
        config = self.installer.tomllib.loads((self.home / "config.toml").read_text())
        disabled = {s["path"] for s in config["skills"]["config"] if s["enabled"] is False}
        self.assertIn((self.shared / "jev-search/SKILL.md").as_posix(), disabled)

    def test_second_scope_retirement_failure_restores_both_scopes(self):
        shared_old = self.shared / "jev-search/SKILL.md"
        shared_old.parent.mkdir(parents=True)
        shared_old.write_text("shared old\n")
        original = (self.home / "config.toml").read_bytes()
        replace = self.installer.os.replace
        calls = []
        def fail_once(source, destination):
            calls.append(source)
            if len(calls) == 2:
                raise OSError("second scope failure")
            return replace(source, destination)
        with patch.object(self.installer.os, "replace", side_effect=fail_once):
            with self.assertRaisesRegex(OSError, "second scope failure"):
                self.run_install(True)
        self.assertTrue(self.old.exists())
        self.assertEqual(shared_old.read_text(), "shared old\n")
        self.assertEqual((self.home / "config.toml").read_bytes(), original)
        self.assertFalse((self.home / "skills/jev/SKILL.md").exists())

    def test_failed_retirement_restores_runtime_and_config(self):
        original = (self.home / "config.toml").read_bytes()
        with patch.object(self.installer.os, "replace", side_effect=OSError("synthetic failure")):
            with self.assertRaises(OSError):
                self.run_install(True)
        self.assertTrue(self.old.exists())
        self.assertEqual((self.home / "config.toml").read_bytes(), original)
        self.assertFalse((self.home / "skills/jev/SKILL.md").exists())

    def test_packaged_references_retain_resources_without_nested_discovery(self):
        files = self.installer.package(self.repo)
        self.assertEqual([name for name in files if name.endswith("SKILL.md")], ["SKILL.md"])
        self.assertTrue(all("references/upstream/" + name + "/guide.md" in files for name in self.installer.LEGACY_SKILLS))

    @unittest.skipUnless(os.name == "nt", "Windows command-shell boundary")
    def test_windows_command_runs_through_cmd_and_powershell(self):
        # Only benign local fixtures run. No real agent, key or network transport.
        self.home = self.home / "synthetic profile with spaces"
        state = self.home / "jev"
        state.mkdir(parents=True)
        (self.home / "bin").mkdir()
        (state / "run-hook.ps1").write_bytes(self.installer.launcher(Path(sys.executable)))
        (self.home / "bin/invoke-hidden.ps1").write_text(
            "param($FilePath, [string[]]$ArgumentList, $WorkingDirectory)\n"
            "$eventValue = Get-Content -LiteralPath $ArgumentList[-1] -Raw | ConvertFrom-Json\n"
            "[Console]::Out.WriteLine((@{fixture='launcher-reached'; prompt=$eventValue.prompt} | ConvertTo-Json -Compress))\n",
            encoding="utf-8")
        command = self.installer.handler(self.home, Path(sys.executable))["commandWindows"]
        pwsh = self.installer.shutil.which("pwsh.exe")
        shadow = self.home / "benign shadow"
        shadow.mkdir()
        # Windows' own where.exe rejects pwsh arguments harmlessly. A bare-name
        # regression must not reach the real launcher. No foreign code is used.
        shutil.copyfile(Path(os.environ["SystemRoot"]) / "System32/where.exe", shadow / "pwsh.exe")
        env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATHEXT")
               if key in os.environ}
        env["PATH"] = str(shadow)
        invocations = [
            '"' + os.environ["COMSPEC"] + '" /d /s /c "' + command + '"',
            [pwsh, "-NoLogo", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", command],
        ]
        for invocation in invocations:
            run = subprocess.run(invocation, input='{"prompt":"synthetic 中文 boundary"}', capture_output=True,
                                 text=True, encoding="utf-8", errors="replace", timeout=10,
                                 cwd=shadow, env=env,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads(run.stdout), {"fixture": "launcher-reached", "prompt": "synthetic 中文 boundary"})
            self.assertEqual(list((state / "inbox").iterdir()), [])

    def test_windows_shell_paths_reject_unhandled_forms(self):
        for path in ("pwsh.exe", r"\\server\share\pwsh.exe", r"C:\bad%NAME%\pwsh.exe",
                     r"C:\bad$env\pwsh.exe", r"C:\bad`name\pwsh.exe", r'C:\bad"name\pwsh.exe',
                     "C:\\bad\nname\\pwsh.exe"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.installer.windows_shell_path(path)
        self.assertEqual(self.installer.windows_shell_path(r"C:\Program Files\PowerShell\7\pwsh.exe"),
                         'C:\\"Program Files\\PowerShell\\7\\pwsh.exe"')


if __name__ == "__main__":
    unittest.main()
