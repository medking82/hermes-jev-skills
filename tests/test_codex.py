"""Behavioral checks for routing, privacy, scope and host-independent failure paths."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from jevkit import client, codex


class CodexRoutingTests(unittest.TestCase):
    def setUp(self):
        self.catalog = [
            {"name": "design", "description": "Design and polish user interfaces", "path": str(Path("design/SKILL.md").resolve())},
            {"name": "drive:documents", "description": "Edit connected documents", "path": str(Path("docs/SKILL.md").resolve())},
        ]
        self.calls = []

    def ask(self, state, questions, **kwargs):
        self.calls.append((state, questions, kwargs))
        if "pick:0" in questions:
            answers = {"pick:0": {"probabilities": {"S0": .9, "S1": .05, "none": .05}},
                       "design_mode": {"choice": "mobile-native", "confidence": .8},
                       "workflow": {"choice": "none", "confidence": .8}}
        else:
            answers = {key: {"noul": .1 if key == "s1" else .9} for key in questions}
        return {"answers": answers, "latency_ms": 15, "jev_model": "synthetic-version", "input_tokens": 400}

    def test_two_stage_selector_merges_design_and_preserves_paths(self):
        result = codex.select("Fix sticky hover on the mobile interface", self.catalog, ask_fn=self.ask)
        self.assertEqual(result["skills"][0]["path"], self.catalog[0]["path"])
        self.assertEqual(result["design"]["mode"], "mobile-native")
        self.assertEqual(len(self.calls), 2)
        self.assertIn("design_mode", self.calls[0][1])
        self.assertIn("workflow", self.calls[0][1])
        self.assertIn("needs_skill", self.calls[1][1])
        self.assertTrue(all(c[2]["retries"] == 0 for c in self.calls))
        self.assertTrue(all(c[2]["provider"] == "typesafe" for c in self.calls))
        self.assertEqual(result["receipts"][0]["jev_model"], "synthetic-version")

    def test_explicit_choice_and_acknowledgement_use_no_network(self):
        ask = Mock(side_effect=AssertionError("unexpected network"))
        for turn in ("Use $design to fix the form", "Use /design to fix the form", "thanks"):
            self.assertEqual(codex.select(turn, self.catalog, ask_fn=ask)["status"], "ok")
        ask.assert_not_called()

    def test_sensitive_and_user_opt_out_use_no_network(self):
        ask = Mock(side_effect=AssertionError("unexpected network"))
        for turn in ("My password is a synthetic fixture", "Native-only: fix the screen", "不要使用 Jev，修改界面", "这是一条包含密码的合成测试请求"):
            self.assertEqual(codex.select(turn, self.catalog, ask_fn=ask)["status"], "fail_open")
        ask.assert_not_called()

    def test_substantive_chinese_is_not_treated_as_trivial(self):
        result = codex.select("修复手机网页的滚动和安全区域", self.catalog, ask_fn=self.ask)
        self.assertEqual(result["source"], "jev")
        self.assertEqual(len(self.calls), 2)

    def test_no_key_and_transport_failure_return_to_main_model(self):
        for code in ("no_key", "timeout", "malformed", "invalid_response", "http_429"):
            result = codex.select("Polish the interface", self.catalog,
                                  ask_fn=Mock(side_effect=client.JevError(code)))
            self.assertEqual(result["status"], "fail_open")
            self.assertEqual(result["skills"], [])
            self.assertEqual(result["reason_code"], code)

    def test_stage_two_can_reject_all(self):
        def ask(state, questions, **kwargs):
            reply = self.ask(state, questions, **kwargs)
            if "needs_skill" in questions:
                reply["answers"]["needs_skill"]["noul"] = .1
            return reply
        result = codex.select("Polish the interface", self.catalog, ask_fn=ask)
        self.assertEqual(result["skills"], [])
        self.assertNotIn("design", result)

    def test_useful_workflow_can_be_recommended_without_another_specialist(self):
        def ask(state, questions, **kwargs):
            reply = self.ask(state, questions, **kwargs)
            if "workflow" in questions:
                reply["answers"]["workflow"] = {"choice": "search", "confidence": .8}
                reply["answers"]["workflow_needed"] = {"noul": .9}
            else:
                reply["answers"]["needs_skill"]["noul"] = .1
            return reply
        result = codex.select("Research primary sources and rank the evidence", self.catalog, ask_fn=ask)
        self.assertEqual(result["skills"], [])
        self.assertEqual(result["workflow"], "search")
        self.assertEqual(len(self.calls), 2)

    def test_workflow_choice_without_applicability_does_not_add_a_phase(self):
        def ask(state, questions, **kwargs):
            reply = self.ask(state, questions, **kwargs)
            if "workflow" in questions:
                reply["answers"].update(workflow={"choice": "search", "confidence": .99}, workflow_needed={"noul": .1})
            return reply
        result = codex.select("Fix a known one-line typo", self.catalog, ask_fn=ask)
        self.assertNotIn("workflow", result)

    def test_namespaced_host_id_is_retained(self):
        rows = [self.catalog[1]]
        def ask(state, questions, **kwargs):
            if "pick:0" in questions:
                return {"answers": {"pick:0": {"probabilities": {"S0": .9, "none": .1}}}, "latency_ms": 1}
            return {"answers": {k: {"noul": .9} for k in questions}, "latency_ms": 1}
        self.assertEqual(codex.select("Edit a connected document", rows, ask_fn=ask)["skills"][0]["name"], "drive:documents")

    def test_selector_and_retired_skills_do_not_route_to_themselves(self):
        rows = [dict(self.catalog[0], name="jev"), dict(self.catalog[0], name="jev-search")]
        self.assertEqual(codex.normalize_catalog(rows), [])

    def test_design_explicit_only_modes_are_excluded_by_default(self):
        def ask(state, questions, **kwargs):
            self.assertFalse(set(questions["mode"]["criteria"]) & codex.EXPLICIT_DESIGN)
            return {"answers": {"mode": {"choice": "mobile-native", "confidence": .8}}}
        self.assertEqual(codex.design("Fix mobile scroll", ask_fn=ask)["mode"], "mobile-native")

    def test_design_low_confidence_and_unknown_choice_use_existing_default(self):
        for choice, confidence in (("animate", .1), ("invented-mode", .99)):
            reply = {"answers": {"mode": {"choice": choice, "confidence": confidence}}}
            self.assertEqual(codex.design("Improve the interface", ask_fn=Mock(return_value=reply))["mode"], "emil-design-eng")

    def test_design_single_candidate_is_deterministic(self):
        ask = Mock(side_effect=AssertionError("unexpected network"))
        self.assertEqual(codex.design("Polish the form", allowed=["emil-design-eng"], ask_fn=ask)["source"], "local")

    def test_design_explicit_scope_is_caller_owned(self):
        def ask(state, questions, **kwargs):
            self.assertEqual(set(questions["mode"]["criteria"]), {"break-ui", "emil-design-eng"})
            return {"answers": {"mode": {"choice": "break-ui", "confidence": .8}}}
        self.assertEqual(codex.design("Stress test with worst-case data", allowed=["break-ui"], ask_fn=ask)["mode"], "break-ui")

    def test_decision_redacts_contacts_without_serialization_damage(self):
        def ask(state, questions, **kwargs):
            self.assertNotIn("person@example.test", json.dumps(state))
            self.assertIn('quoted "text"', state["context"])
            return {"answers": {"decision": {"choice": "a", "confidence": .8}}}
        result = codex.decision({"state": {"context": 'quoted "text" person@example.test'},
                                 "question": "Which tone best fits?", "options": {"a": "Neutral", "b": "Formal"}}, ask_fn=ask)
        self.assertEqual(result["choice"], "a")


@unittest.skipIf(codex.tomllib is None, "Codex adapter requires Python 3.11+")
class CodexHookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="codex-routing-", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        profile = patch.object(Path, "home", return_value=self.home / "profile")
        profile.start()
        self.addCleanup(profile.stop)
        self.skill = self.home / "skills/design/SKILL.md"
        self.skill.parent.mkdir(parents=True)
        self.skill.write_text("---\nname: design\ndescription: Polish interfaces\n---\n", encoding="utf-8")
        self.event = {"hook_event_name": "UserPromptSubmit", "session_id": "synthetic-session", "turn_id": "turn-1",
                      "prompt": "Polish the screen", "cwd": str(self.home)}

    def test_duplicate_turn_reuses_result_but_changed_task_and_catalog_do_not(self):
        selector = Mock(return_value={"status": "ok", "source": "jev", "skills": [
            {"name": "design", "path": str(self.skill)}], "design": {"mode": "animate"}})
        first = codex.hook(self.event, home=self.home, selector=selector)
        self.assertIn("animate", first["hookSpecificOutput"]["additionalContext"])
        codex.hook(self.event, home=self.home, selector=selector)
        self.assertEqual(selector.call_count, 1)
        codex.hook(dict(self.event, prompt="Fix mobile scroll"), home=self.home, selector=selector)
        self.assertEqual(selector.call_count, 2)
        self.skill.write_text("---\nname: design\ndescription: Changed scope\n---\n", encoding="utf-8")
        codex.hook(dict(self.event, prompt="Fix mobile scroll"), home=self.home, selector=selector)
        self.assertEqual(selector.call_count, 3)
        codex.hook(dict(self.event, turn_id="turn-2"), home=self.home, selector=selector)
        self.assertEqual(selector.call_count, 4)

    def test_receipts_never_store_prompt_or_transcript(self):
        selector = Mock(return_value={"status": "ok", "source": "jev", "skills": []})
        codex.hook(self.event, home=self.home, selector=selector)
        saved = "".join(p.read_text(encoding="utf-8") for p in (self.home / "jev").rglob("*.json"))
        self.assertNotIn(self.event["prompt"], saved)

    def test_hook_failure_never_blocks_the_prompt(self):
        selector = Mock(return_value=codex.fallback("timeout"))
        self.assertEqual(codex.hook(self.event, home=self.home, selector=selector), {})

    def test_disabled_paths_and_explicit_only_metadata_are_respected(self):
        (self.home / "config.toml").write_text('[[skills.config]]\npath = ' + json.dumps(str(self.skill)) + '\nenabled = false\n')
        self.assertEqual(codex.local_catalog(self.home, self.home), [])
        (self.home / "config.toml").write_text("")
        metadata = self.skill.parent / "agents/openai.yaml"
        metadata.parent.mkdir()
        metadata.write_text("policy:\n  allow_implicit_invocation: false\n")
        self.assertEqual(codex.local_catalog(self.home, self.home), [])

    def test_untrusted_project_skills_and_plugin_caches_are_not_inventoried(self):
        project_skill = self.home / "project/.agents/skills/private/SKILL.md"
        project_skill.parent.mkdir(parents=True)
        project_skill.write_text("---\nname: project-private\ndescription: Project work\n---\n")
        names = {s["name"] for s in codex.local_catalog(self.home, project_skill.parent)}
        self.assertNotIn("project-private", names)

    def test_nested_resources_are_not_discovered_as_independent_skills(self):
        nested = self.skill.parent / "references/example/SKILL.md"
        nested.parent.mkdir(parents=True)
        nested.write_text("---\nname: embedded-example\ndescription: Not an installed skill\n---\n")
        names = {s["name"] for s in codex.local_catalog(self.home, self.home)}
        self.assertEqual(names, {"design"})

    def test_system_scope_is_discovered_without_traversing_dependency_trees(self):
        for relative, name in ((".system/system-test", "system-test"), ("node_modules/dependency", "dependency")):
            entry = self.home / "skills" / relative / "SKILL.md"
            entry.parent.mkdir(parents=True)
            entry.write_text("---\nname: " + name + "\ndescription: Synthetic catalog entry\n---\n")
        names = {s["name"] for s in codex.local_catalog(self.home, self.home)}
        self.assertIn("system-test", names)
        self.assertNotIn("dependency", names)

    def test_unrelated_config_paths_are_not_probed(self):
        unrelated = self.home / "unavailable-project"
        (self.home / "config.toml").write_text('[projects.' + json.dumps(str(unrelated)) + ']\ntrust_level = "trusted"\n')
        original = Path.resolve
        def guarded(path, *args, **kwargs):
            if "unavailable-project" in str(path):
                raise AssertionError("unrelated filesystem was probed")
            return original(path, *args, **kwargs)
        with patch.object(Path, "resolve", guarded):
            self.assertEqual(len(codex.local_catalog(self.home, self.home)), 1)

    def test_explicitly_trusted_project_scope_is_included(self):
        project = self.home / "project"
        entry = project / ".agents/skills/project-helper/SKILL.md"
        entry.parent.mkdir(parents=True)
        entry.write_text("---\nname: project-helper\ndescription: Work on this project\n---\n")
        (self.home / "config.toml").write_text('[projects.' + json.dumps(str(project)) + ']\ntrust_level = "trusted"\n')
        names = {s["name"] for s in codex.local_catalog(self.home, project)}
        self.assertIn("project-helper", names)

    def test_shared_user_scope_is_discovered_and_disabled_paths_are_honored(self):
        entry = Path.home() / ".agents/skills/shared-helper/SKILL.md"
        entry.parent.mkdir(parents=True)
        entry.write_text("---\nname: shared-helper\ndescription: Shared user work\n---\n")
        rows = codex.local_catalog(self.home, self.home)
        self.assertIn(str(entry), {s["path"] for s in rows})
        (self.home / "config.toml").write_text('[[skills.config]]\npath = ' + json.dumps(str(entry)) + '\nenabled = false\n')
        self.assertNotIn("shared-helper", {s["name"] for s in codex.local_catalog(self.home, self.home)})

    def test_hard_deadline_returns_empty_context(self):
        with patch("jevkit.codex.subprocess.run", side_effect=subprocess.TimeoutExpired("worker", .05)), patch("jevkit.codex.codex_home", return_value=self.home):
            self.assertEqual(codex._bounded_hook(self.event, deadline=.05), {})
        receipt = json.loads((self.home / "jev/last-hook.json").read_text())
        self.assertEqual(receipt["reason_code"], "hard_timeout")
        self.assertIsNone(receipt["ask_attempts"])

    def test_worker_bootstrap_is_cwd_independent_and_windowless(self):
        with patch("jevkit.codex.subprocess.run", return_value=Mock(returncode=0, stdout="{}")) as run:
            codex._bounded_hook(self.event)
        args, kwargs = run.call_args
        self.assertIn(str(Path(codex.__file__).resolve().parents[1]), args[0])
        self.assertIn("creationflags", kwargs)
        self.assertNotIn(self.event["prompt"], " ".join(args[0]))


if __name__ == "__main__":
    unittest.main()
