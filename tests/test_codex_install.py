import importlib.util
import json
import os
from pathlib import Path
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
        hooks = json.loads((self.home / "hooks.json").read_text())["hooks"]["UserPromptSubmit"]
        self.assertIn(self.foreign, [h for g in hooks for h in g["hooks"]])
        config = self.installer.tomllib.loads((self.home / "config.toml").read_text())
        self.assertEqual(config["model"], "user-selected")
        self.assertEqual(len(config["skills"]["config"]), len(self.installer.LEGACY_SKILLS))
        self.assertTrue(all(s["enabled"] is False for s in config["skills"]["config"]))
        self.assertTrue((self.home / "tools/hermes-jev-skills/jevkit/codex.py").exists())

    def test_second_install_does_not_duplicate_hook_or_disable_entries(self):
        self.run_install(True)
        self.run_install(True)
        hooks = json.loads((self.home / "hooks.json").read_text())["hooks"]["UserPromptSubmit"]
        self.assertEqual(sum(len(g["hooks"]) for g in hooks), 2)
        config = self.installer.tomllib.loads((self.home / "config.toml").read_text())
        self.assertEqual(len(config["skills"]["config"]), len(self.installer.LEGACY_SKILLS))

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


if __name__ == "__main__":
    unittest.main()
