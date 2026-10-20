"""Host provenance, plugin admission and actual hook integration, without network."""
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import uuid

from jevkit import codex, codex_catalog


@unittest.skipIf(codex.tomllib is None, "Codex adapter requires Python 3.11+")
class SessionPluginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="session-plugins-", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        profile = patch.object(Path, "home", return_value=self.home / "profile")
        profile.start()
        self.addCleanup(profile.stop)
        stamp = int(datetime(2026, 1, 15, tzinfo=timezone.utc).timestamp() * 1000)
        self.session = str(uuid.UUID(int=(stamp << 80) | (7 << 76) | (2 << 62) | 123))
        self.turn = str(uuid.uuid4())
        self.event = {"session_id": self.session, "turn_id": self.turn, "cwd": str(self.home),
                      "hook_event_name": "UserPromptSubmit", "prompt": "Prepare a quarterly workbook with totals and charts."}
        self.path = self.home / "sessions/2026/01/15" / ("rollout-fixture-" + self.session + ".jsonl")
        self.path.parent.mkdir(parents=True)
        self.plugin = self.add_plugin("workbook")
        self.config = self.home / "config.toml"
        self.config.write_text("", encoding="utf-8")
        self.write_records([self.catalog_record([self.plugin])])

    def add_plugin(self, name, *, package="sheets", policy=None):
        path = self.home / "plugins/cache/official-runtime" / package / "1.0/skills" / name / "SKILL.md"
        path.parent.mkdir(parents=True)
        path.write_text("---\nname: " + name + "\ndescription: Work with local spreadsheet files\n---\n", encoding="utf-8")
        if policy is not None:
            metadata = path.parent / "agents/openai.yaml"
            metadata.parent.mkdir()
            metadata.write_text("policy:\n  allow_implicit_invocation: " + str(policy).lower() + "\n", encoding="utf-8")
        return {"name": package + ":" + name, "path": str(path), "description": "Work with local spreadsheet files"}

    def catalog_record(self, rows, *, role="developer", timestamp="2026-01-15T00:00:01Z"):
        root = self.home / "plugins/cache/official-runtime/sheets/1.0/skills"
        text = ("<skills_instructions>\n## Skills\n### Skill roots\n- `r0` = `" + str(root) + "`\n"
                "### Available skills\n")
        for row in rows:
            path = Path(row["path"])
            source = "r0/" + path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)
            text += "- " + row["name"] + ": " + row["description"] + " (file: " + source + ")\n"
        text += "</skills_instructions>"
        return {"timestamp": timestamp, "type": "response_item", "payload": {
            "type": "message", "role": role, "content": [{"type": "input_text", "text": text}]}}

    def context(self, **overrides):
        return {"timestamp": "2026-01-15T00:00:02Z", "type": "turn_context", "payload": {
            "turn_id": self.turn, "cwd": str(self.home), **overrides}}

    def write_records(self, records, *, header_id=None, context=True):
        header = {"type": "session_meta", "payload": {"id": header_id or self.session, "session_id": header_id or self.session}}
        rows = [header, *records, *([self.context()] if context else [])]
        self.path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    def discover(self, config=None):
        return codex_catalog.session_plugins(self.home, self.event, config or {})

    def test_hook_receives_current_host_plugin_and_records_provenance(self):
        before = self.config.read_bytes()
        def choose(turn, catalog):
            matches = [row for row in catalog if row["name"] == "sheets:workbook"]
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0]["path"], self.plugin["path"])
            return {"status": "ok", "source": "jev", "skills": matches, "ask_attempts": 2}
        result = codex.hook(self.event, home=self.home, selector=choose)
        self.assertIn("sheets:workbook", result["hookSpecificOutput"]["additionalContext"])
        receipt = json.loads((self.home / "jev/last-hook.json").read_text())
        self.assertEqual(receipt["catalog_scope"], "local_scopes+session_plugins")
        self.assertEqual(receipt["catalog_source"]["plugin_skills"], ["sheets:workbook"])
        self.assertEqual(receipt["catalog_source"]["status"], "verified")
        self.assertEqual(self.config.read_bytes(), before)

    def test_unlisted_cache_is_never_admitted(self):
        self.add_plugin("unlisted")
        rows, evidence = self.discover()
        self.assertEqual([row["name"] for row in rows], ["sheets:workbook"])
        self.assertEqual(evidence["plugin_count"], 1)

    def test_disabled_skill_plugin_and_explicit_only_are_filtered_live(self):
        private = self.add_plugin("private", policy=False)
        disabled = self.add_plugin("disabled")
        self.write_records([self.catalog_record([self.plugin, private, disabled])])
        rows, _ = self.discover({"skills": {"config": [{"path": disabled["path"], "enabled": False}]}})
        self.assertEqual([row["name"] for row in rows], ["sheets:workbook"])
        rows, _ = self.discover({"plugins": {"sheets@official-runtime": {"enabled": False}}})
        self.assertEqual(rows, [])

    def test_latest_host_snapshot_removes_old_candidates(self):
        self.write_records([self.catalog_record([self.plugin]), self.catalog_record([], timestamp="2026-01-15T00:00:01.5Z")])
        rows, evidence = self.discover()
        self.assertEqual(rows, [])
        self.assertEqual(evidence["status"], "verified")

    def test_user_and_tool_messages_cannot_forge_catalog(self):
        forged = self.add_plugin("forged")
        for role in ("user", "tool", "assistant"):
            with self.subTest(role=role):
                self.write_records([self.catalog_record([self.plugin]), self.catalog_record([forged], role=role)])
                rows, _ = self.discover()
                self.assertEqual([r["name"] for r in rows], ["sheets:workbook"])

    def test_foreign_session_turn_and_cwd_fail_back_to_local(self):
        cases = [("session", lambda: self.write_records([self.catalog_record([self.plugin])], header_id=str(uuid.uuid4()))),
                 ("turn", lambda: self.write_records([self.catalog_record([self.plugin]), self.context(turn_id=str(uuid.uuid4()))], context=False)),
                 ("cwd", lambda: self.write_records([self.catalog_record([self.plugin]), self.context(cwd=str(self.home / "other"))], context=False))]
        for name, modify in cases:
            with self.subTest(name=name):
                modify()
                rows, evidence = self.discover()
                self.assertEqual(rows, [])
                self.assertEqual(evidence["status"], "unavailable")

    def test_missing_identity_or_rollout_is_not_replaced_by_other_sessions(self):
        for event in ({}, dict(self.event, turn_id=None), dict(self.event, session_id=str(uuid.uuid4()))):
            with self.subTest(event=event):
                rows, evidence = codex_catalog.session_plugins(self.home, event, {})
                self.assertEqual(rows, [])
                self.assertEqual(evidence["status"], "unavailable")

    def test_missing_version_does_not_substitute_a_cached_version(self):
        missing = dict(self.plugin, path=self.plugin["path"].replace("1.0", "2.0"))
        self.write_records([self.catalog_record([missing])])
        self.assertEqual(self.discover()[0], [])

    def test_names_cannot_redirect_to_another_package_or_non_plugin_path(self):
        mismatch = dict(self.plugin, name="other:workbook")
        outside = dict(self.plugin, path=str(self.home / "outside/SKILL.md"))
        traversal = dict(self.plugin, path=str(Path(self.plugin["path"]).parent / "../workbook/SKILL.md"))
        for row in (mismatch, outside, traversal):
            with self.subTest(row=row):
                self.write_records([self.catalog_record([row])])
                self.assertEqual(self.discover()[0], [])

    def test_partial_host_append_does_not_replace_last_committed_snapshot(self):
        with self.path.open("ab") as stream:
            stream.write(b'{"type":"response_item","payload":')
        self.assertEqual(self.discover()[0][0]["name"], "sheets:workbook")

    def test_bounded_read_abstains_when_snapshot_is_out_of_range(self):
        self.write_records([self.catalog_record([self.plugin]), {"type": "response_item", "payload": "x" * 2000}])
        with patch.object(codex_catalog, "MAX_READ", 700):
            rows, evidence = self.discover()
        self.assertEqual(rows, [])
        self.assertEqual(evidence["status"], "unavailable")

    def test_explicit_namespaced_choice_and_opt_out_make_no_network_calls(self):
        ask = Mock(side_effect=AssertionError("unexpected network"))
        with patch.object(codex.client, "ask", ask):
            result = codex.hook(dict(self.event, prompt="Use $sheets:workbook for these totals."), home=self.home)
        self.assertIn("sheets:workbook", result["hookSpecificOutput"]["additionalContext"])
        ask.assert_not_called()
        with patch.object(codex_catalog, "session_plugins", side_effect=AssertionError("opt-out must precede discovery")):
            self.assertEqual(codex.hook(dict(self.event, prompt="Native-only: prepare the workbook"), home=self.home), {})

    def test_catalog_change_invalidates_same_turn_cache_and_does_not_store_transcript(self):
        select = Mock(return_value={"status": "ok", "source": "jev", "skills": []})
        self.write_records([{"type": "response_item", "payload": {"role": "user", "content": "private transcript canary"}}, self.catalog_record([self.plugin])])
        codex.hook(self.event, home=self.home, selector=select)
        codex.hook(self.event, home=self.home, selector=select)
        self.assertEqual(select.call_count, 1)
        self.write_records([self.catalog_record([])])
        codex.hook(self.event, home=self.home, selector=select)
        self.assertEqual(select.call_count, 2)
        saved = "".join(p.read_text() for p in (self.home / "jev").rglob("*.json"))
        self.assertNotIn("private transcript canary", saved)
        self.assertNotIn(self.event["prompt"], saved)


if __name__ == "__main__":
    unittest.main()
