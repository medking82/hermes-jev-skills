"""Official recipe regressions: evidence, abstention, bounded calls and audit history."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from jevkit import client, codex, codex_skillpick as picker


class OfficialSkillRecipeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="codex-evidence-", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.catalog = [self.make_skill("author", "Work with presentations", "Create a new deck from a brief."),
                        self.make_skill("editor", "Work with presentations", "Edit an existing deck; do not create one.")]
        self.calls = []

    def make_skill(self, name, description, body):
        path = self.root / name / "SKILL.md"
        path.parent.mkdir()
        path.write_text("---\nname: " + name + "\ndescription: " + description + "\n---\n" + body, encoding="utf-8")
        return {"name": name, "description": description, "path": str(path)}

    def ask(self, state, questions, **kwargs):
        self.calls.append((state, questions, kwargs))
        if "gate::acts_on_user_system" in questions:
            names = list(questions["which"]["criteria"])
            answers = {"which": {"probabilities": {name: 1 / len(names) for name in names}},
                       "gate::acts_on_user_system": {"noul": .8},
                       "gate::would_follow_documented_procedure": {"noul": .8},
                       "gate::prose_suffices": {"noul": .2}}
        else:
            answers = {key: {"noul": .7} for key in questions if key.startswith("fits::")}
            if "which" in questions:
                # The original descriptions are indistinguishable: this decision
                # requires the actual instructions to reach the request boundary.
                criteria = questions["which"]["criteria"]
                chosen = next((name for name, text in criteria.items() if "Create a new deck" in text), next(iter(criteria)))
                answers["which"] = {"choice": chosen, "confidence": .9}
        return {"answers": answers, "latency_ms": 5, "input_tokens": 200,
                "jev_model": "synthetic", "usage": {"output_tokens": 10}}

    def test_full_source_description_and_body_resolve_similar_candidates(self):
        long_description = "Presentation editing. " * 35 + "Existing decks only."
        path = Path(self.catalog[1]["path"])
        path.write_text("---\nname: editor\ndescription: " + long_description +
                        "\n---\nEdit an existing deck; do not create one.", encoding="utf-8")
        result = codex.select("Create a new deck from this brief", self.catalog[::-1], ask_fn=self.ask)
        self.assertEqual(result["skills"][0]["name"], "author")
        criteria = self.calls[1][1]["which"]["criteria"]
        self.assertIn(long_description, criteria["editor"])
        self.assertIn("Create a new deck from a brief.", criteria["author"])
        self.assertNotIn("---", criteria["author"])
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(result["receipts"][1]["output_tokens"], 10)

    def test_gate_orients_prose_and_stops_before_reading_candidates(self):
        def ask(*args, **kwargs):
            reply = self.ask(*args, **kwargs)
            for key, value in (("acts_on_user_system", .1), ("would_follow_documented_procedure", .1), ("prose_suffices", .9)):
                reply["answers"]["gate::" + key]["noul"] = value
            return reply
        with patch.object(picker, "evidence", side_effect=AssertionError("gate must stop here")):
            result = codex.select("Explain what a monad means", self.catalog, ask_fn=ask, request_gate=True)
        self.assertEqual(result["verification"]["outcome"], "gate_no_match")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["ask_attempts"], 1)

    def test_default_verifies_body_despite_low_request_only_gate(self):
        def ask(state, questions, **kwargs):
            reply = self.ask(state, questions, **kwargs)
            if "gate::acts_on_user_system" in questions:
                reply["answers"]["gate::acts_on_user_system"]["noul"] = .05
                reply["answers"]["gate::would_follow_documented_procedure"]["noul"] = .32
                reply["answers"]["gate::prose_suffices"]["noul"] = .59
            return reply
        result = codex.select("Create a new deck", self.catalog, ask_fn=ask)
        self.assertEqual(result["skills"][0]["name"], "author")
        self.assertEqual(result["ask_attempts"], 2)
        self.assertFalse(result["verification"]["request_gate_enforced"])

    def test_only_three_candidates_are_opened(self):
        third = self.make_skill("third", "Another procedure", "A bounded procedure.")
        missing = {"name": "fourth", "description": "Unrelated", "path": str(self.root / "missing/SKILL.md")}
        result = codex.select("Create a new presentation", self.catalog + [third, missing], ask_fn=self.ask)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["verification"]["evidence"]), 3)

    def test_excerpt_is_bounded_and_redacted_without_sending_paths(self):
        path = Path(self.catalog[0]["path"])
        path.write_text("Contact writer@example.test. " + "x" * 1200 + " END_MARKER", encoding="utf-8")
        codex.select("Create a new deck", self.catalog, ask_fn=self.ask)
        wire = json.dumps([(state, questions) for state, questions, _ in self.calls])
        self.assertNotIn("writer@example.test", wire)
        self.assertNotIn("END_MARKER", wire)
        self.assertNotIn(str(self.root), wire)
        text, metadata = picker.evidence(self.catalog[0])
        self.assertLessEqual(len(text["body"]), 700)
        self.assertEqual(metadata["body_chars"], len(text["body"]))

    def test_missing_or_sensitive_evidence_abstains_without_second_request(self):
        for mode in ("missing", "sensitive"):
            with self.subTest(mode=mode):
                path = Path(self.catalog[0]["path"])
                if mode == "missing":
                    path.unlink()
                else:
                    path.write_text("password: synthetic-fixture", encoding="utf-8")
                self.calls.clear()
                result = codex.select("Create a new deck", self.catalog, ask_fn=self.ask)
                self.assertEqual(result["status"], "fail_open")
                self.assertEqual(result["skills"], [])
                self.assertEqual(len(self.calls), 1)

    def test_chinese_sensitive_evidence_is_withheld(self):
        Path(self.catalog[0]["path"]).write_text("密码：synthetic-fixture", encoding="utf-8")
        result = codex.select("Create a new deck", self.catalog, ask_fn=self.ask)
        self.assertEqual(result["reason_code"], "skill_evidence_sensitive")
        self.assertEqual(len(self.calls), 1)

    def test_credential_documentation_is_withheld_without_losing_safe_procedure(self):
        Path(self.catalog[0]["path"]).write_text(
            "Create a new deck from a brief.\nRead API_KEY from the user's environment.\n"
            "Render and verify the resulting slides.\n密码：synthetic-fixture", encoding="utf-8")
        result = codex.select("Create a new deck", self.catalog, ask_fn=self.ask)
        self.assertEqual(result["status"], "ok")
        wire = json.dumps([(state, questions) for state, questions, _ in self.calls])
        self.assertNotIn("API_KEY", wire)
        self.assertNotIn("synthetic-fixture", wire)
        self.assertIn("Render and verify", wire)
        self.assertEqual(result["verification"]["evidence"][0]["redacted_lines"], 2)

    def test_singleton_no_match_option_cannot_replace_a_real_skill(self):
        rows = [dict(self.catalog[0], name="__no_match__")]
        result = codex.select("Create a new deck", rows, ask_fn=self.ask)
        self.assertEqual(result["skills"][0]["name"], "__no_match__")
        self.assertEqual(len(self.calls[0][1]["which"]["criteria"]), 2)

    def test_choice_and_fit_have_distinct_roles_as_in_official_recipe(self):
        def ask(state, questions, **kwargs):
            reply = self.ask(state, questions, **kwargs)
            if "fits::author" in questions:
                reply["answers"]["fits::author"]["noul"] = .35
                reply["answers"]["fits::editor"]["noul"] = .8
            return reply
        result = codex.select("Create a new deck", self.catalog, ask_fn=ask)
        self.assertEqual(result["skills"][0]["name"], "author")
        self.assertEqual(result["skills"][0]["match"], .35)

    def test_all_fits_low_is_no_match_not_a_failed_call(self):
        def ask(state, questions, **kwargs):
            reply = self.ask(state, questions, **kwargs)
            for key in questions:
                if key.startswith("fits::"):
                    reply["answers"][key]["noul"] = .1
            return reply
        result = codex.select("Post to a service not covered by this catalog", self.catalog, ask_fn=ask)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["verification"]["outcome"], "fit_no_match")
        self.assertEqual(result["skills"], [])

    def test_missing_or_invalid_answers_fail_open(self):
        for answer in ({}, {"gate::acts_on_user_system": {"noul": float("nan")}}):
            result = codex.select("Create a new deck", self.catalog, ask_fn=Mock(return_value={"answers": answer}))
            self.assertEqual(result["reason_code"], "invalid_response")

    def test_second_call_timeout_does_not_return_a_suggestion(self):
        def ask(state, questions, **kwargs):
            if any(k.startswith("fits::") for k in questions):
                raise client.JevError("timeout")
            return self.ask(state, questions, **kwargs)
        result = codex.select("Create a new deck", self.catalog, ask_fn=ask)
        self.assertEqual(result["status"], "fail_open")
        self.assertEqual(result["ask_attempts"], 2)

    def test_linked_entrypoint_is_not_read(self):
        real_lstat = Path.lstat
        def lstat(path):
            if path == Path(self.catalog[0]["path"]):
                return Mock(st_mode=0o100644, st_file_attributes=1024)
            return real_lstat(path)
        with patch.object(Path, "lstat", lstat):
            result = codex.select("Create a new deck", self.catalog, ask_fn=self.ask)
        self.assertEqual(result["reason_code"], "skill_evidence_unavailable")
        self.assertEqual(len(self.calls), 1)

    def test_hook_ledger_preserves_observations_and_counts_duplicate_calls_once(self):
        home = self.root / "home"
        event = {"hook_event_name": "UserPromptSubmit", "session_id": "synthetic-session", "turn_id": "one",
                 "prompt": "Which skill should create a new deck?", "cwd": str(self.root), "_jev_invocation": "manual_smoke"}
        selector = Mock(side_effect=lambda turn, catalog: codex.select(turn, catalog, ask_fn=self.ask))
        with patch.object(codex, "local_catalog", return_value=self.catalog), \
                patch.object(codex.codex_catalog, "session_plugins", return_value=([], {})):
            codex.hook(event, home=home, selector=selector)
            codex.hook(event, home=home, selector=selector)
            self.assertEqual(selector.call_count, 1)
            # Body-only change invalidates this same-turn cache without adding a
            # cross-turn history/loaded-skill policy.
            path = Path(self.catalog[0]["path"])
            path.write_text(path.read_text(encoding="utf-8") + " New constraint.", encoding="utf-8")
            codex.hook(event, home=home, selector=selector)
        rows = [json.loads(p.read_text(encoding="utf-8")) for p in (home / "jev/observations").glob("*/*.json")]
        self.assertEqual(len(rows), 3)
        self.assertEqual(selector.call_count, 2)
        self.assertEqual(sum(r["ask_attempts"] for r in rows), 4)
        self.assertEqual(sum(r["cache_reused"] for r in rows), 1)
        self.assertEqual(len({r["observation_id"] for r in rows}), 3)
        raw = json.dumps(rows)
        self.assertNotIn(event["prompt"], raw)
        self.assertNotIn("Create a new deck from a brief.", raw)
        self.assertTrue(all(r["observation_source"] == "manual_smoke" for r in rows))

    def test_hook_no_match_is_advisory_but_failure_is_silent(self):
        event = {"hook_event_name": "UserPromptSubmit", "prompt": "Which skill should explain monads?", "cwd": str(self.root)}
        with patch.object(codex, "local_catalog", return_value=self.catalog), \
                patch.object(codex.codex_catalog, "session_plugins", return_value=([], {})):
            selector = Mock(return_value={"status": "ok", "source": "jev", "skills": [],
                                         "verification": {"outcome": "gate_no_match"}})
            result = codex.hook(event, home=self.root, selector=selector)
            self.assertIn("mandatory skill instructions", result["hookSpecificOutput"]["additionalContext"])
            selector.return_value = codex.fallback("timeout")
            self.assertEqual(codex.hook(event, home=self.root, selector=selector), {})


if __name__ == "__main__":
    unittest.main()
