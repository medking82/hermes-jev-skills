"""Prove that installed official content reaches the caller, including later updates."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jevkit import codex


class OfficialGuidanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="codex-guidance-", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.reference = self.home / "skills/jev/references/official/typesafe-ai"
        self.reference.mkdir(parents=True)
        (self.home / "jev").mkdir()
        self.install("a" * 40, "# Official Guidance\nUse a no-match outcome when no candidate fits.\n")

    def install(self, commit, text):
        source = dict(repository="typesafe-ai/skills", directory="skills/typesafe-ai", commit=commit)
        (self.reference / "source.json").write_text(json.dumps(source), encoding="utf-8")
        (self.reference / "guide.md").write_text(text, encoding="utf-8")
        self.manifest = dict(source_commit="d" * 40, source_dirty=False,
                             official_source={key: source[key] for key in ("repository", "commit")},
                             files={p.relative_to(self.home).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                    for p in self.reference.iterdir()})
        self.save_manifest()

    def save_manifest(self):
        (self.home / "jev/installation.json").write_text(json.dumps(self.manifest), encoding="utf-8")

    def test_current_guidance_is_returned_without_inference_or_writes(self):
        before = {p.relative_to(self.home): p.read_bytes() for p in self.home.rglob("*") if p.is_file()}
        with patch("jevkit.codex.client.ask", side_effect=AssertionError("unexpected inference")):
            result = codex.guidance(home=self.home)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["content"], (self.reference / "guide.md").read_bytes().decode("utf-8"))
        self.assertEqual(result["official_source"]["commit"], "a" * 40)
        self.assertEqual(result["sha256"], hashlib.sha256(result["content"].encode()).hexdigest())
        self.assertEqual(before, {p.relative_to(self.home): p.read_bytes() for p in self.home.rglob("*") if p.is_file()})

    def test_same_path_returns_new_content_after_an_accepted_official_update(self):
        first = codex.guidance(home=self.home)
        self.install("b" * 40, "# Updated Guidance\nBatch independent questions over the same state.\n")
        second = codex.guidance(home=self.home)
        self.assertEqual(second["status"], "ok")
        self.assertEqual(first["path"], second["path"])
        self.assertEqual(second["official_source"]["commit"], "b" * 40)
        self.assertNotEqual(first["sha256"], second["sha256"])
        self.assertIn("Batch independent questions", second["content"])
        self.assertNotIn("no-match outcome", second["content"])

    def test_missing_or_modified_content_is_not_returned(self):
        guide = self.reference / "guide.md"
        guide.write_text("Unowned instructions", encoding="utf-8")
        result = codex.guidance(home=self.home)
        self.assertEqual(result["reason_code"], "official_guidance_unavailable")
        self.assertNotIn("content", result)
        guide.unlink()
        self.assertEqual(codex.guidance(home=self.home)["status"], "fail_open")

    def test_wrong_official_identity_and_dirty_release_fail_open(self):
        for field, value in (("official_source", dict(repository="other/skills", commit="a" * 40)),
                             ("source_dirty", True), ("source_commit", "not-a-commit")):
            with self.subTest(field=field):
                self.install("a" * 40, "# Guide\n")
                self.manifest[field] = value
                self.save_manifest()
                self.assertEqual(codex.guidance(home=self.home)["status"], "fail_open")

    def test_linked_guide_is_rejected_before_reading_its_target(self):
        guide = self.reference / "guide.md"
        guide.unlink()
        target = self.home / "private.txt"
        target.write_text("Must never be returned", encoding="utf-8")
        try:
            guide.symlink_to(target)
        except OSError:
            self.skipTest("This platform cannot create unprivileged symlinks")
        original = Path.read_bytes
        def guarded(path):
            if path == guide or path == target:
                raise AssertionError("linked content was read")
            return original(path)
        with patch.object(Path, "read_bytes", guarded):
            self.assertEqual(codex.guidance(home=self.home)["status"], "fail_open")

    def test_cli_delivers_content_without_stdin_or_a_provider_call(self):
        class NoInput:
            def read(self):
                raise AssertionError("guidance must not wait for stdin")
        output = io.StringIO()
        with patch.object(codex, "codex_home", return_value=self.home), patch("sys.stdin", NoInput()), \
                patch("jevkit.codex.client.ask", side_effect=AssertionError("unexpected inference")), \
                contextlib.redirect_stdout(output):
            self.assertEqual(codex.main(["guidance"]), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "ok")
        self.assertIn("no-match outcome", result["content"])


if __name__ == "__main__":
    unittest.main()
