"""Behavioral checks for routing, privacy, scope and host-independent failure paths."""
import io
import json
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from jevkit import client, codex


class CodexRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="codex-select-", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.catalog = [
            {"name": "design", "description": "Design and polish user interfaces", "path": str(root / "design/SKILL.md")},
            {"name": "drive:documents", "description": "Edit connected documents", "path": str(root / "docs/SKILL.md")},
        ]
        for row in self.catalog:
            path = Path(row["path"])
            path.parent.mkdir()
            path.write_text("---\nname: " + row["name"] + "\ndescription: " + row["description"] +
                            "\n---\n# Procedure\n" + row["description"], encoding="utf-8")
        self.calls = []

    def ask(self, state, questions, **kwargs):
        self.calls.append((state, questions, kwargs))
        if "gate::acts_on_user_system" in questions:
            answers = {"which": {"probabilities": {"design": .9, "drive:documents": .1}},
                       "gate::acts_on_user_system": {"noul": .9},
                       "gate::would_follow_documented_procedure": {"noul": .9},
                       "gate::prose_suffices": {"noul": .1},
                       "design_mode": {"choice": "mobile-native", "confidence": .8},
                       "workflow": {"choice": "none", "confidence": .8}}
        else:
            answers = {key: {"noul": .1 if key == "fits::drive:documents" else .9} for key in questions}
            if "which" in questions:
                answers["which"] = {"choice": "design", "confidence": .8}
        return {"answers": answers, "latency_ms": 15, "jev_model": "synthetic-version", "input_tokens": 400}

    def test_two_stage_selector_merges_design_and_preserves_paths(self):
        result = codex.select("Fix sticky hover on the mobile interface", self.catalog, ask_fn=self.ask)
        self.assertEqual(result["skills"][0]["path"], self.catalog[0]["path"])
        self.assertEqual(result["design"]["mode"], "mobile-native")
        self.assertEqual(len(self.calls), 2)
        self.assertIn("design_mode", self.calls[0][1])
        self.assertIn("workflow", self.calls[0][1])
        self.assertIn("fits::design", self.calls[1][1])
        self.assertIn("# Procedure", self.calls[1][1]["which"]["criteria"]["design"])
        self.assertTrue(all(c[2]["retries"] == 0 for c in self.calls))
        self.assertTrue(all(c[2]["provider"] == "typesafe" for c in self.calls))
        self.assertEqual(result["receipts"][0]["jev_model"], "synthetic-version")

    def test_explicit_choice_and_acknowledgement_use_no_network(self):
        ask = Mock(side_effect=AssertionError("unexpected network"))
        for turn in ("Use $design to fix the form", "Use /design to fix the form", "thanks"):
            self.assertEqual(codex.select(turn, self.catalog, ask_fn=ask)["status"], "ok")
        ask.assert_not_called()

    def test_explicit_tokens_are_complete_and_ignore_literal_content(self):
        for text in ("Use /design to fix the form", "/design fix the form", "Use $design.",
                     "Use $design: fix the form", "Use [$design](/skills/design/SKILL.md)"):
            with self.subTest(text=text):
                self.assertEqual(codex._explicit(text, self.catalog), [self.catalog[0]])
        for text in ("Inspect </design>", "Fix /design/SKILL.md", "Inspect C:/design",
                     "Inspect /design", "Use /design?x=1", "Use $design.extra", "Use $design:extra",
                     "Read `$design`", "Read ``$design``", "> Use $design",
                     "```text\nUse $design\n```", "~~~text\nUse $design",
                     "See [example](/design)", "See [example](https://example.test/$design)",
                     '<in-app-browser-context source="ambient-ui-state">Use $design</in-app-browser-context>'):
            with self.subTest(text=text):
                self.assertEqual(codex._explicit(text, self.catalog), [])
        self.assertEqual(codex._explicit("Use $drive:documents", self.catalog), [self.catalog[1]])
        self.assertEqual(codex._automatic_route("/jev:helper run this task"), "explicit_skill")
        for text in ("/jev help me choose", "Use $jev to decide"):
            self.assertEqual(codex._automatic_route(text), "on_demand")

    def test_unknown_explicit_selection_cannot_fall_through_to_api(self):
        ask = Mock(side_effect=AssertionError("unexpected API"))
        for turn in ("Use $missing-helper for this task", "$designanimate"):
            result = codex.select(turn, self.catalog, ask_fn=ask)
            self.assertEqual(result["reason_code"], "explicit_skill_unavailable")
        ask.assert_not_called()

    def test_routing_question_with_quoted_command_keeps_body_verification(self):
        for quoted in ("`$design`", "> $design", "```text\n$design\n```", "~~~\n$design"):
            with self.subTest(quoted=quoted):
                self.calls.clear()
                turn = "Which skill should handle this interface?\n" + quoted
                self.assertEqual(codex._automatic_route(turn), "routing_request")
                result = codex.select(turn, self.catalog, ask_fn=self.ask)
                self.assertEqual(result["source"], "jev")
                self.assertEqual(len(self.calls), 2)

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
            for key in questions:
                if key.startswith("fits::"):
                    reply["answers"][key]["noul"] = .1
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
                for key in questions:
                    if key.startswith("fits::"):
                        reply["answers"][key]["noul"] = .1
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
            if "gate::acts_on_user_system" in questions:
                return {"answers": {"which": {"probabilities": {"drive:documents": .9, "__no_match__": .1}},
                        **{key: {"noul": .9} for key in questions if key.startswith("gate::")}}, "latency_ms": 1}
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
        self.assertEqual(codex.design("Polish the form spacing", allowed=["emil-design-eng"], ask_fn=ask)["source"], "local")

    def test_settled_design_cases_make_no_calls_in_both_entrypoints(self):
        cases = [("Use animate mode.", "animate"), ("使用 mobile-native 模式。", "mobile-native"),
                 ("animation-performance", "animation-performance"),
                 ("Polish the form's spacing and button feedback.", "emil-design-eng"),
                 ("Adjust the button spacing", "emil-design-eng"),
                 ("调整表单间距和按钮反馈。", "emil-design-eng"),
                 ("优化组件的间距与对比度", "emil-design-eng")]
        ask = Mock(side_effect=AssertionError("unexpected network"))
        for turn, mode in cases:
            with self.subTest(turn=turn):
                result = codex.select(turn, self.catalog, ask_fn=ask)
                self.assertEqual(result["skills"], [self.catalog[0]])
                self.assertEqual(result["design"]["mode"], mode)
                self.assertEqual(result["requests"], 0)
                result = codex.design(turn, ask_fn=ask)
                self.assertEqual(result["mode"], mode)
                self.assertEqual(result["requests"], 0)
        ask.assert_not_called()

    def test_explicit_modes_authorize_only_the_named_mode(self):
        ask = Mock(side_effect=AssertionError("unexpected network"))
        for mode in codex.DESIGN_MODES:
            turn = "Use " + mode + " mode."
            self.assertEqual(codex.design(turn, ask_fn=ask)["mode"], mode)
            self.assertEqual(codex.select(turn, self.catalog, ask_fn=ask)["design"]["mode"], mode)
            self.assertEqual(codex.design(turn, allowed=[mode], ask_fn=ask)["mode"], mode)
            self.assertEqual(codex.select(turn, self.catalog, allowed_design_modes=[mode], ask_fn=ask)["design"]["mode"], mode)
        ask.assert_not_called()

    def test_unknown_mixed_conflicting_and_disallowed_cases_still_ask(self):
        turns = ["Improve the interface", "Use animate and mobile-native modes",
                 "Use animate mode, but do not use animate", "Do not use animate mode",
                 "Polish the form spacing and fix the backend", "调整表单间距并修复后端",
                 "调整表单间距和动画", "Use animate mode for an unknown mixed task",
                 "Compare prototype and break-ui", "Use invented-mode mode",
                 "Use `animate mode", "Use animate` mode"]
        for turn in turns:
            with self.subTest(turn=turn):
                ask = Mock(side_effect=client.JevError("offline"))
                self.assertEqual(codex.design(turn, ask_fn=ask)["reason_code"], "offline")
                self.assertEqual(codex.select(turn, self.catalog, ask_fn=ask)["reason_code"], "offline")
                self.assertEqual(ask.call_count, 2)
        # A caller-owned singleton is deterministic; skill selection still checks fit.
        for mode in ("animate", "break-ui"):
            ask = Mock(side_effect=client.JevError("offline"))
            turn = "Use " + mode + " mode."
            codex.design(turn, allowed=["emil-design-eng"], ask_fn=ask)
            codex.select(turn, self.catalog, allowed_design_modes=["emil-design-eng"], ask_fn=ask)
            self.assertEqual(ask.call_count, 1)
        ask = Mock(side_effect=AssertionError("unexpected network"))
        self.assertEqual(codex.design("Use animate and mobile-native modes", allowed=["emil-design-eng"], ask_fn=ask)["mode"], "emil-design-eng")
        ask.assert_not_called()

    def test_singleton_design_does_not_add_a_mode_question(self):
        def ask(state, questions, **kwargs):
            key = "mode" if "mode" in questions else "design_mode"
            if key in questions:
                self.fail("A singleton mode must be chosen in code")
            if key == "mode":
                return {"answers": {"mode": {"choice": "none", "confidence": .9}}}
            reply = self.ask(state, questions, **kwargs)
            reply["answers"]["design_mode"] = {"choice": "none", "confidence": .9}
            return reply
        result = codex.design("Improve the interface", allowed=["emil-design-eng"], ask_fn=ask)
        self.assertEqual(result["source"], "local")
        result = codex.select("Improve the interface", self.catalog, allowed_design_modes=["emil-design-eng"], ask_fn=ask)
        self.assertEqual(result["design"]["source"], "local")

    def test_local_design_requires_exact_catalog_row_and_preserves_explicit_skill(self):
        ask = Mock(side_effect=client.JevError("offline"))
        for rows in ([self.catalog[1]], [dict(self.catalog[0], name="plugin:design")]):
            self.assertEqual(codex.select("Adjust the button spacing", rows, ask_fn=ask)["reason_code"], "offline")
        self.assertEqual(ask.call_count, 2)
        ask = Mock(side_effect=AssertionError("unexpected network"))
        result = codex.select("Use $drive:documents; adjust the button spacing", self.catalog, ask_fn=ask)
        self.assertEqual(result["skills"], [self.catalog[1]])
        self.assertNotIn("design", result)
        result = codex.select("Use $design: Use animate mode.", self.catalog, ask_fn=ask)
        self.assertEqual(result["source"], "explicit")
        self.assertEqual(result["design"]["mode"], "animate")
        ask.assert_not_called()

    def test_off_switch_suppresses_decision_before_payload_processing(self):
        ask = Mock(side_effect=AssertionError("unexpected network"))
        with patch.dict(os.environ, {"JEV_CODEX_OFF": "1"}):
            self.assertEqual(codex.decision({}, ask_fn=ask)["reason_code"], "disabled_by_user")
        ask.assert_not_called()

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
                      "prompt": "Which design mode fits polishing this screen?", "cwd": str(self.home)}

    def test_ordinary_tasks_and_continuations_skip_before_catalog_or_selector(self):
        selector = Mock(side_effect=AssertionError("unexpected selector"))
        prompts = (
            "Implement the agreed fix and run the regression tests.",
            "Review the diff for correctness.",
            "Find the latest official documentation.",
            "Assess whether the application can work offline.",
            "继续按已经确定的方案完成实现和验证。",
            "看看这两个问题后来有没有修复。",
            "Document this example:\n```text\nWhich skill should I use?\n```",
            "Adjust the button spacing\n> Which skill should I use?",
            "Do not choose a workflow; continue the agreed implementation.",
            "不要替我选择 skill，继续执行。",
        )
        with patch.object(codex, "local_catalog", side_effect=AssertionError("unexpected catalog")):
            for prompt in prompts:
                with self.subTest(prompt=prompt):
                    self.assertEqual(codex.hook(dict(self.event, prompt=prompt), home=self.home, selector=selector), {})
                    receipt = json.loads((self.home / "jev/last-hook.json").read_text())
                    self.assertEqual(receipt["reason_code"], "automatic_scope_skipped")
                    self.assertEqual(receipt["ask_attempts"], 0)
                    self.assertEqual(receipt["receipts"], [])
                    self.assertFalse(receipt["trigger_eligible"])
                    self.assertIsInstance(receipt["duration_ms"], int)
                    self.assertNotIn(prompt, json.dumps(receipt))
        selector.assert_not_called()

    def test_routing_requests_are_admitted_without_task_history(self):
        selector = Mock(return_value={"status": "ok", "source": "jev", "skills": [],
                                      "ask_attempts": 2, "receipts": []})
        for index, prompt in enumerate((
            "Which skill should handle this request?",
            "Please choose a workflow for this task.",
            "Which design mode fits this interface problem?",
            "这个任务应该用哪个 skill？",
            "帮我选择适合这个任务的工作流。",
            "design mode 该选哪个？",
        )):
            codex.hook(dict(self.event, prompt=prompt, turn_id=str(index)), home=self.home, selector=selector)
            receipt = json.loads((self.home / "jev/last-hook.json").read_text())
            self.assertTrue(receipt["trigger_eligible"])
            self.assertEqual(receipt["trigger_reason"], "routing_request")
            self.assertEqual(receipt["automatic_trigger_policy"], "routing-requests-v1")
        self.assertEqual(selector.call_count, 6)

    def test_xml_and_paths_abstain_before_catalog_lookup(self):
        prompts = (
            '<in-app-browser-context source="ambient-ui-state">Current URL: https://example.test/api</in-app-browser-context>\nFix the agreed issue.',
            '<send_user_message_question_reply>Continue the fix.</send_user_message_question_reply>',
            '<heartbeat><instructions>Check C:/work/project.</instructions></heartbeat>',
            'Fix the /api and /data-entry routes, then inspect /lot.',
            'Review C:/work/project and C:/Program Files/Example.',
            'Inspect ./design and /design/SKILL.md.',
        )
        with patch.object(codex, "local_catalog", side_effect=AssertionError("unexpected catalog")):
            for prompt in prompts:
                with self.subTest(prompt=prompt):
                    self.assertEqual(codex.hook(dict(self.event, prompt=prompt), home=self.home), {})
                    receipt = json.loads((self.home / "jev/last-hook.json").read_text())
                    self.assertEqual(receipt["reason_code"], "automatic_scope_skipped")
                    self.assertEqual(receipt["ask_attempts"], 0)

    def test_explicit_only_local_skill_lookup_and_live_disablement(self):
        metadata = self.skill.parent / "agents/openai.yaml"
        metadata.parent.mkdir()
        metadata.write_text("policy:\n  allow_implicit_invocation: false\n", encoding="utf-8")
        self.assertEqual(codex.local_catalog(self.home, self.home), [])
        with patch.object(client, "ask", side_effect=AssertionError("unexpected API")):
            for prompt in ("Use $design to fix the form", "Use [$design](/skills/design/SKILL.md)"):
                result = codex.hook(dict(self.event, prompt=prompt), home=self.home)
                self.assertIn("Local routing suggests", result["hookSpecificOutput"]["additionalContext"])
                receipt = json.loads((self.home / "jev/last-hook.json").read_text())
                self.assertEqual(receipt["skills"], ["design"])
                self.assertEqual(receipt["ask_attempts"], 0)
            self.assertEqual(codex.hook(dict(self.event, prompt="Adjust the button spacing"), home=self.home), {})
            selector = Mock(return_value={"status": "ok", "source": "jev", "skills": []})
            codex.hook(self.event, home=self.home, selector=selector)
            self.assertEqual(selector.call_args.args[1], [])
            (self.home / "config.toml").write_text('[[skills.config]]\npath = ' + json.dumps(str(self.skill)) + '\nenabled = false\n')
            result = codex.hook(dict(self.event, prompt="Use $design to fix the form"), home=self.home)
            self.assertEqual(result, {})
            receipt = json.loads((self.home / "jev/last-hook.json").read_text())
            self.assertEqual(receipt["reason_code"], "explicit_skill_unavailable")
            self.assertFalse(receipt["cache_reused"])

    def test_on_demand_select_can_resolve_explicit_only_local_skill(self):
        metadata = self.skill.parent / "agents/openai.yaml"
        metadata.parent.mkdir()
        metadata.write_text("policy:\n  allow_implicit_invocation: false\n", encoding="utf-8")
        with patch.object(codex, "codex_home", return_value=self.home), \
                patch.object(client, "ask", side_effect=AssertionError("unexpected API")), \
                patch("sys.stdin", io.StringIO(json.dumps({"turn": "Use $design to fix the form"}))), \
                patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(codex.main(["select"]), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["source"], "explicit")
        self.assertEqual(result["skills"][0]["path"], str(self.skill))

    def test_explicit_only_lookup_respects_shared_and_trusted_project_scopes(self):
        project = self.home / "project"
        paths = (Path.home() / ".agents/skills/shared-explicit/SKILL.md",
                 project / ".agents/skills/project-explicit/SKILL.md")
        for path in paths:
            path.parent.mkdir(parents=True)
            path.write_text("---\nname: " + path.parent.name + "\ndescription: Explicit procedure\n---\n", encoding="utf-8")
            policy = path.parent / "agents/openai.yaml"
            policy.parent.mkdir()
            policy.write_text("policy:\n  allow_implicit_invocation: false\n", encoding="utf-8")
        names = {path.parent.name for path in paths}
        (self.home / "config.toml").write_text('[projects.' + json.dumps(str(project)) + ']\ntrust_level = "trusted"\n')
        self.assertFalse(names & {row["name"] for row in codex.local_catalog(self.home, project)})
        rows = codex.local_catalog(self.home, project, explicit=names)
        self.assertEqual(names & {row["name"] for row in rows}, names)
        (self.home / "config.toml").write_text("")
        rows = codex.local_catalog(self.home, project, explicit=names)
        self.assertNotIn("project-explicit", {row["name"] for row in rows})

    def test_local_explicit_and_settled_design_routes_still_use_no_api(self):
        with patch.object(client, "ask", side_effect=AssertionError("unexpected API")):
            for prompt in ("Use $design to fix the form", "Adjust the button spacing"):
                result = codex.hook(dict(self.event, prompt=prompt), home=self.home)
                self.assertIn("Local routing suggests", result["hookSpecificOutput"]["additionalContext"])
                receipt = json.loads((self.home / "jev/last-hook.json").read_text())
                self.assertEqual(receipt["ask_attempts"], 0)
            for prompt in ("Use $unknown-helper for the form", "/jev help me choose an approach"):
                self.assertEqual(codex.hook(dict(self.event, prompt=prompt), home=self.home), {})

    def test_narrow_hook_keeps_two_stage_body_verification(self):
        calls = []
        def ask(state, questions, **kwargs):
            calls.append(questions)
            if "gate::acts_on_user_system" in questions:
                answers = {"which": {"probabilities": {"design": .9, "__no_match__": .1}},
                           "gate::acts_on_user_system": {"noul": .9},
                           "gate::would_follow_documented_procedure": {"noul": .9},
                           "gate::prose_suffices": {"noul": .1},
                           "design_mode": {"choice": "animate", "confidence": .8}}
            else:
                answers = {"fits::design": {"noul": .9}}
            return {"answers": answers, "latency_ms": 4, "input_tokens": 20,
                    "usage": {"output_tokens": 3}, "jev_model": "synthetic"}
        self.skill.write_text("---\nname: design\ndescription: Polish interfaces\n---\nInspect the existing interface before editing.\n", encoding="utf-8")
        with patch.object(client, "ask", side_effect=ask):
            codex.hook(self.event, home=self.home)
        self.assertEqual(len(calls), 2)
        receipt = json.loads((self.home / "jev/last-hook.json").read_text())
        self.assertEqual(receipt["ask_attempts"], 2)
        self.assertEqual(receipt["verification"]["recipe"], "typesafe-skill-suggestion-v1")
        self.assertGreater(receipt["verification"]["evidence"][0]["body_chars"], 0)

    def test_duplicate_turn_reuses_result_but_changed_task_and_catalog_do_not(self):
        selector = Mock(return_value={"status": "ok", "source": "jev", "skills": [
            {"name": "design", "path": str(self.skill)}], "design": {"mode": "animate"}})
        first = codex.hook(self.event, home=self.home, selector=selector)
        self.assertIn("animate", first["hookSpecificOutput"]["additionalContext"])
        codex.hook(self.event, home=self.home, selector=selector)
        self.assertEqual(selector.call_count, 1)
        codex.hook(dict(self.event, prompt="Which design mode fits mobile scroll?"), home=self.home, selector=selector)
        self.assertEqual(selector.call_count, 2)
        self.skill.write_text("---\nname: design\ndescription: Changed scope\n---\n", encoding="utf-8")
        codex.hook(dict(self.event, prompt="Which design mode fits mobile scroll?"), home=self.home, selector=selector)
        self.assertEqual(selector.call_count, 3)
        codex.hook(dict(self.event, turn_id="turn-2"), home=self.home, selector=selector)
        self.assertEqual(selector.call_count, 4)

    def test_receipts_never_store_prompt_or_transcript(self):
        selector = Mock(return_value={"status": "ok", "source": "jev", "skills": []})
        codex.hook(self.event, home=self.home, selector=selector)
        saved = "".join(p.read_text(encoding="utf-8") for p in (self.home / "jev").rglob("*.json"))
        self.assertNotIn(self.event["prompt"], saved)

    def test_receipts_correlate_normal_gated_and_failed_events_without_prompt(self):
        selected = {"mode": "animate", "source": "local", "reason_code": "explicit_mode"}
        selector = Mock(return_value={"status": "ok", "source": "local", "skills": [
            {"name": "design", "path": str(self.skill)}], "design": selected})
        before = datetime.now(timezone.utc)
        context = codex.hook(self.event, home=self.home, selector=selector)
        receipt = json.loads((self.home / "jev/last-hook.json").read_text())
        self.assertIn("Local routing suggests", context["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(receipt["design"], selected)
        self.assertEqual(receipt["session_id"], self.event["session_id"])
        self.assertEqual(receipt["turn_id"], self.event["turn_id"])
        observed = datetime.fromisoformat(receipt["observed_at"])
        self.assertEqual(observed.utcoffset().total_seconds(), 0)
        self.assertLessEqual(before, observed)
        self.assertLessEqual(observed, datetime.now(timezone.utc))
        for prompt, marker in (("Native-only: fix the screen", "host_event"), ("thanks", "manual_smoke")):
            event = dict(self.event, prompt=prompt, turn_id="gated", _jev_invocation=marker)
            codex.hook(event, home=self.home, selector=selector)
            receipt = json.loads((self.home / "jev/last-hook.json").read_text())
            self.assertEqual(receipt["turn_id"], "gated")
            self.assertEqual(receipt["observation_source"], marker)
            self.assertNotIn(prompt, json.dumps(receipt))
        with patch("jevkit.codex.subprocess.run", side_effect=subprocess.TimeoutExpired("worker", .05)), patch("jevkit.codex.codex_home", return_value=self.home):
            codex._bounded_hook(self.event, deadline=.05)
        receipt = json.loads((self.home / "jev/last-hook.json").read_text())
        self.assertEqual(receipt["session_id"], self.event["session_id"])
        self.assertEqual(receipt["turn_id"], self.event["turn_id"])
        self.assertIn("observed_at", receipt)
        self.assertNotIn(self.event["prompt"], json.dumps(receipt))

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
