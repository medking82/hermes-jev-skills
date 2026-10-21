"""Prove that installed official content reaches the caller, including later updates."""
import base64
import contextlib
import hashlib
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

from jevkit import codex


class OfficialGuidanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="codex-guidance-", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.reference = self.home / "skills/jev/references/official/typesafe-ai"
        self.reference.mkdir(parents=True)
        (self.home / "jev").mkdir()
        self.guide_text = ("# Official Guidance\r\nUse a no-match outcome when no candidate fits.\n"
                           "\u4e2d\u6587 \u201c\u6307\u5357\u201d caf\u00e9 na\u00efve \U0001f680\r\n"
                           "LF: r\u00e9sum\u00e9 \U0001f600\n")
        self.install("a" * 40, self.guide_text)

    def install(self, commit, text):
        source = dict(repository="typesafe-ai/skills", directory="skills/typesafe-ai", commit=commit)
        (self.reference / "source.json").write_text(json.dumps(source), encoding="utf-8")
        (self.reference / "guide.md").write_bytes(text.encode("utf-8"))
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
        output_bytes = io.BytesIO()
        output = io.TextIOWrapper(output_bytes, encoding="cp437", errors="replace", newline="\r\n")
        self.addCleanup(output.close)
        with patch.object(codex, "codex_home", return_value=self.home), patch("sys.stdin", NoInput()), \
                patch("jevkit.codex.client.ask", side_effect=AssertionError("unexpected inference")), \
                contextlib.redirect_stdout(output):
            self.assertEqual(codex.main(["guidance"]), 0)
        output.flush()
        received = output_bytes.getvalue()
        result = json.loads(received.decode("utf-8", errors="strict"))
        self.assertEqual(result["status"], "ok")
        self.assertIn("no-match outcome", result["content"])
        self.assertEqual(output.encoding, "utf-8")
        self.assertEqual(output.errors, "strict")
        self.assertEqual(received, (json.dumps(result, ensure_ascii=False) + "\n").encode("utf-8"))
        self.assertEqual(result["content"], self.guide_text)
        self.assertEqual(result["content"].encode("utf-8"), (self.reference / "guide.md").read_bytes())
        self.assertEqual(result["sha256"], hashlib.sha256(self.guide_text.encode("utf-8")).hexdigest())

    @unittest.skipUnless(sys.platform == "win32", "Windows hidden runner requires Windows")
    def test_hidden_runner_preserves_utf8_streams_and_nonzero_exit_from_legacy_parent(self):
        pwsh = shutil.which("pwsh.exe")
        if not pwsh:
            self.skipTest("PowerShell 7 (pwsh.exe) is not installed")
        helper = Path(__file__).resolve().parents[1] / "codex/invoke-hidden.ps1"
        stdout_text = self.guide_text + "No Final Newline: \u5b8c\u6210 \U0001f600"
        stderr_text = "\u9519\u8bef \u201d r\u00e9sum\u00e9 \U0001f6a8\nCRLF: \u4e2d\u6587\r\nEnd"
        # ASCII source keeps the host's argv encoding out of the Unicode fixture.
        child_source = (
            "import ctypes, os, sys\n"
            "assert not ctypes.windll.kernel32.GetConsoleWindow(), 'unexpected console window'\n"
            "assert os.environ['PYTHONUTF8'] == '1'\n"
            "assert os.environ['PYTHONIOENCODING'] == 'utf-8:strict'\n"
            "assert sys.flags.utf8_mode == 1\n"
            "assert sys.stdout.encoding == sys.stderr.encoding == 'utf-8'\n"
            "assert sys.stdout.errors == 'strict'\n"
            # Preserve mixed line endings without overriding the inherited encoding.
            "sys.stdout.reconfigure(newline='\\n')\n"
            "sys.stderr.reconfigure(newline='\\n')\n"
            f"sys.stdout.write({ascii(stdout_text)})\n"
            "sys.stdout.flush()\n"
            f"sys.stderr.write({ascii(stderr_text)})\n"
            "sys.stderr.flush()\n"
            "raise SystemExit(23)\n"
        )

        def ps_quote(value):
            return "'" + str(value).replace("'", "''") + "'"

        command = (
            "$ErrorActionPreference = 'Stop'\n"
            "$legacy = [Text.Encoding]::GetEncoding(437)\n"
            "[Console]::InputEncoding = $legacy\n"
            "[Console]::OutputEncoding = $legacy\n"
            "$OutputEncoding = $legacy\n"
            "if ([Console]::OutputEncoding.CodePage -ne 437) { throw 'CP437 setup failed' }\n"
            f"& {ps_quote(helper)} -FilePath {ps_quote(sys.executable)} "
            f"-ArgumentList @('-B', '-c', {ps_quote(child_source)}) "
            f"-WorkingDirectory {ps_quote(self.home)}\n"
            "exit $LASTEXITCODE\n"
        )
        encoded_command = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
        environment = dict(os.environ, PYTHONUTF8="0", PYTHONIOENCODING="cp437:replace")
        received = subprocess.run(
            [pwsh, "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded_command],
            cwd=self.home, env=environment, stdin=subprocess.DEVNULL, capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW, timeout=30,
        )
        self.assertEqual(received.returncode, 23, received.stderr.decode("utf-8", errors="backslashreplace"))
        for stream, actual, text in (("stdout", received.stdout, stdout_text),
                                     ("stderr", received.stderr, stderr_text)):
            with self.subTest(stream=stream):
                expected = text.encode("utf-8")
                self.assertEqual(actual, expected)
                self.assertEqual(actual.decode("utf-8", errors="strict"), text)
                self.assertEqual(hashlib.sha256(actual).hexdigest(), hashlib.sha256(expected).hexdigest())


if __name__ == "__main__":
    unittest.main()
