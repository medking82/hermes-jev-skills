"""Offline evaluation contracts: mocks prove scoring/plumbing, not API accuracy."""
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("codex_skillpick_eval", ROOT / "codex" / "evaluate_skillpick.py")
evaluation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluation)


class SelectorEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(evaluation.DATASET.read_text(encoding="utf-8"))
        self.env = patch.dict(os.environ, {"JEV_CODEX_OFF": "0", "JEV_PROVIDER": "typesafe"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def temporary(self):
        temporary = tempfile.TemporaryDirectory(prefix="skillpick-eval-test-", dir=ROOT / "tests")
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name)

    def mock_ask(self, state, questions, **kwargs):
        answers = {}
        for key, question in questions.items():
            if key.startswith("pick:"):
                answers[key] = {"probabilities": {name: .9 if name == "S0" else .01 for name in question["criteria"]}}
            elif key == "which":
                options = list(question["criteria"])
                answers[key] = {"choice": options[0], "confidence": .9,
                                "probabilities": {name: .9 if i == 0 else .01 for i, name in enumerate(options)}}
            elif key == "workflow":
                answers[key] = {"choice": "none", "confidence": .9}
            elif key == "design_mode":
                answers[key] = {"choice": "emil-design-eng", "confidence": .9}
            else:
                answers[key] = {"noul": .01 if key in ("workflow_needed", "gate::prose_suffices") else .9}
        return {"answers": answers, "latency_ms": 2, "jev_model": "synthetic-model-v1", "input_tokens": 42}

    def test_default_and_check_never_call_client_or_create_temp_roster(self):
        with patch.object(evaluation.client, "ask", side_effect=AssertionError("network")) as ask, \
                patch.object(evaluation, "materialize_roster", side_effect=AssertionError("write")):
            for args in ([], ["--check"]):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(evaluation.main(args), 0)
                report = json.loads(output.getvalue())
                self.assertEqual(report["request_attempts"], 0)
                self.assertEqual(report["evaluation"], "SELECTOR")
                self.assertEqual(report["mode"], "check")
            ask.assert_not_called()

    def test_fixture_is_bounded_bilingual_and_hashes_are_deterministic(self):
        evaluation.validate_dataset(self.data)
        self.assertEqual(len(self.data["cases"]), 16)
        self.assertEqual({c["language"] for c in self.data["cases"]}, {"en", "zh"})
        first = evaluation.metadata(self.data, self.data["cases"])
        second = evaluation.metadata(copy.deepcopy(self.data), self.data["cases"])
        self.assertEqual(first, second)
        mutated = copy.deepcopy(self.data)
        mutated["roster"][0]["body"] += " Revised."
        self.assertNotEqual(first["roster_hash"], evaluation.digest(mutated["roster"]))
        self.assertNotEqual(first["case_hash"], evaluation.digest(self.data["cases"][:1]))

    def test_invalid_fixtures_fail_before_any_call(self):
        bad_cases = []
        duplicate = copy.deepcopy(self.data)
        duplicate["cases"][1]["id"] = duplicate["cases"][0]["id"]
        bad_cases.append(duplicate)
        oversized = copy.deepcopy(self.data)
        oversized["roster"][0]["body"] = "x" * 701
        bad_cases.append(oversized)
        unknown = copy.deepcopy(self.data)
        unknown["cases"][0]["expected"] = ["missing"]
        bad_cases.append(unknown)
        private = copy.deepcopy(self.data)
        private["synthetic"] = False
        bad_cases.append(private)
        ask = Mock(side_effect=AssertionError("network"))
        for data in bad_cases:
            with self.assertRaises(ValueError):
                evaluation.run_pairs(data, ask_fn=ask)
        for limit in (0, -1, 21, True):
            with self.assertRaises(ValueError):
                evaluation.run_pairs(self.data, ask_fn=ask, limit=limit)
        ask.assert_not_called()

    def test_every_fixture_body_is_readable_as_bounded_verification_evidence(self):
        from jevkit import codex_skillpick
        catalog = evaluation.materialize_roster(self.data["roster"], self.temporary())
        for skill, source in zip(catalog, self.data["roster"]):
            text, receipt = codex_skillpick.evidence(skill)
            self.assertIn(source["body"], text["body"])
            self.assertLessEqual(receipt["body_chars"], 700)
            self.assertEqual(len(receipt["evidence_sha256"]), 64)
        self.assertTrue(any(len(s["description"]) > 600 for s in self.data["roster"]))
        self.assertTrue(all(not evaluation.privacy.is_sensitive(c["turn"]) for c in self.data["cases"]))

    def test_all_selection_labels_and_failure_precedence(self):
        examples = [([], [], "ok", "exact_match"), (["a"], ["a"], "ok", "exact_match"),
                    (["a"], ["b"], "ok", "wrong_selection"),
                    ([], ["a"], "ok", "needless_selection"),
                    (["a"], [], "ok", "missed_selection"),
                    ([], [], "fail_open", "fail_open"), ([], None, "missing", "fail_open")]
        for expected, got, status, label in examples:
            self.assertEqual(evaluation.classify(expected, got, status), label)

    def test_failed_missing_and_malformed_results_are_not_correct_empty_answers(self):
        case = self.data["cases"][0]
        for result in (None, {}, {"status": "ok"}, {"status": "ok", "skills": None},
                       {"status": "fail_open", "skills": []}, {"skills": []},
                       {"status": "ok", "skills": [{"name": "unknown"}]}):
            measured = evaluation.measure(lambda *a, **k: result, case, [], Mock())
            self.assertEqual(measured["label"], "fail_open")
        measured = evaluation.measure(Mock(side_effect=RuntimeError("secret prompt path")), case, [], Mock())
        self.assertEqual(measured["status"], "error")
        self.assertNotIn("secret", json.dumps(measured))

    def test_failed_attempt_is_counted_tokens_unknown_and_errors_are_redacted(self):
        def selector(turn, catalog, *, ask_fn):
            return ask_fn({"turn": turn}, {})
        result = evaluation.measure(selector, self.data["cases"][0], [],
                                    Mock(side_effect=evaluation.client.JevError("timeout", "private body")))
        self.assertEqual(result["request_attempts"], 1)
        self.assertIsNone(result["input_tokens"])
        self.assertEqual(result["known_input_tokens"], 0)
        self.assertEqual(result["requests"][0]["outcome"], "failed")
        self.assertEqual(result["reason_code"], "timeout")
        self.assertNotIn("private body", json.dumps(result))

    def test_reason_codes_are_closed_and_preserve_transport_and_privacy_failures(self):
        case = self.data["cases"][0]
        for code in ("no_key", "timeout", "sensitive_not_sent", "skill_evidence_sensitive",
                     "skill_evidence_unavailable", "disabled_by_user"):
            result = evaluation.measure(
                lambda *a, **k: {"status": "fail_open", "reason_code": code}, case, [], Mock())
            self.assertEqual(result["reason_code"], code)
            self.assertEqual(result["label"], "fail_open")
        for code in ("private prompt/path", "no_key: private text", {"private": "body"}):
            result = evaluation.measure(
                lambda *a, **k: {"status": "fail_open", "reason_code": code}, case, [], Mock())
            self.assertEqual(result["reason_code"], "unknown_failure")
            self.assertNotIn("private", json.dumps(result))
        self.assertEqual(evaluation.safe_reason("http_503"), "http_error")

    def test_both_arms_preserve_stage_one_and_swallowed_stage_two_error_codes(self):
        for code in ("no_key", "timeout"):
            for phase in (1, 2):
                def ask(state, questions, **kwargs):
                    first_stage = "workflow" in questions
                    if first_stage == (phase == 1):
                        raise evaluation.client.JevError(code, "private exception detail")
                    return self.mock_ask(state, questions, **kwargs)
                report = evaluation.run_pairs(self.data, ask_fn=ask, limit=1)
                for arm in evaluation.RECIPES:
                    result = report["cases"][0][arm]
                    self.assertEqual(result["reason_code"], code)
                    self.assertEqual(result["request_attempts"], phase)
                    self.assertEqual(result["label"], "fail_open")
                self.assertNotIn("private exception detail", json.dumps(report))

    def test_run_and_each_arm_have_utc_start_and_completion_timestamps(self):
        report = evaluation.run_pairs(self.data, ask_fn=self.mock_ask, limit=1)
        records = [report] + [report["cases"][0][arm] for arm in evaluation.RECIPES]
        for record in records:
            for field in ("started_utc", "completed_utc"):
                self.assertTrue(record[field].endswith("Z"))
                parsed = evaluation.datetime.fromisoformat(record[field].replace("Z", "+00:00"))
                self.assertEqual(parsed.tzinfo, evaluation.timezone.utc)
            self.assertLessEqual(record["started_utc"], record["completed_utc"])
        for arm in evaluation.RECIPES:
            self.assertIsNone(report["cases"][0][arm]["reason_code"])

    def test_sequential_pair_order_and_temporary_files_are_cleaned(self):
        calls, paths = [], []
        def selector(arm):
            def run(turn, catalog, *, ask_fn):
                calls.append((arm, turn))
                for row in catalog:
                    path = Path(row["path"])
                    self.assertTrue(path.is_absolute() and path.is_file())
                    self.assertTrue(path.is_relative_to(ROOT / "tests"))
                    self.assertIn("---\nname:", path.read_text(encoding="utf-8"))
                    paths.append(path)
                return {"status": "ok", "skills": []}
            return run
        report = evaluation.run_pairs(self.data, ask_fn=Mock(), limit=2,
                                       selectors={a: selector(a) for a in evaluation.RECIPES})
        self.assertEqual([a for a, t in calls], ["legacy", "new", "new", "legacy"])
        self.assertEqual(calls[0][1], calls[1][1])
        self.assertEqual(calls[2][1], calls[3][1])
        self.assertTrue(all(not p.exists() for p in paths))
        self.assertEqual(report["summary"]["comparable_completed_pairs"], 2)
        self.assertEqual(report["summary"]["same_known_model_completed_pairs"], 0)

    def test_both_real_selectors_use_mock_only_and_preserve_provider_model_retry_policy(self):
        ask = Mock(side_effect=self.mock_ask)
        with patch.object(evaluation.client, "ask", side_effect=AssertionError("live call")), \
                patch.dict(os.environ, {"JEV_PROVIDER": "custom-fixture"}):
            report = evaluation.run_pairs(self.data, ask_fn=ask, limit=1)
        self.assertEqual(ask.call_count, 4)
        for call in ask.call_args_list:
            self.assertEqual(call.kwargs["retries"], 0)
            self.assertEqual(call.kwargs["provider"], "custom-fixture")
            self.assertEqual(call.kwargs["timeout"], 1.4)
            self.assertNotIn("model", call.kwargs)
        for arm in evaluation.RECIPES:
            result = report["cases"][0][arm]
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["request_attempts"], 2)
            self.assertEqual(result["input_tokens"], 84)
            self.assertEqual(result["models"], ["synthetic-model-v1"])
        serialized = json.dumps(report, ensure_ascii=False)
        for skill in self.data["roster"]:
            self.assertNotIn(skill["description"], serialized)
            self.assertNotIn(skill["body"], serialized)
        self.assertNotIn(self.data["cases"][0]["turn"], serialized)
        self.assertNotIn(str(ROOT), serialized)

    def test_legacy_description_bound_and_new_body_evidence(self):
        data = copy.deepcopy(self.data)
        data["roster"][0]["description"] = "A reusable procedure. " * 35 + "End marker."
        ask = Mock(side_effect=self.mock_ask)
        report = evaluation.run_pairs(data, ask_fn=ask, limit=1)
        legacy_stage2 = ask.call_args_list[1].args[0]
        historical = evaluation.privacy.redact(data["roster"][0]["description"], 600)[:600]
        self.assertEqual(legacy_stage2["skills"]["S0"], "skill-creator: " + historical)
        new_stage2 = ask.call_args_list[3].args[1]
        self.assertIn("End marker.", new_stage2["fits::skill-creator"]["instructions"])
        self.assertIn(data["roster"][0]["body"], new_stage2["which"]["criteria"]["skill-creator"])
        self.assertEqual(report["recipes"]["new"], "typesafe-skill-suggestion-v1-body-verification")
        self.assertFalse(report["request_gate_enforced"])

    def test_summary_excludes_failed_pairs_and_reports_denominators(self):
        case = self.data["cases"][0]
        good = evaluation.measure(lambda *a, **k: {"status": "ok", "skills": []}, case, [], Mock())
        fail = evaluation.measure(lambda *a, **k: {"status": "fail_open", "skills": []}, case, [], Mock())
        rows = [{"id": "a", "legacy": dict(good, wall_ms=10), "new": dict(good, wall_ms=20)},
                {"id": "b", "legacy": dict(good, wall_ms=100), "new": dict(fail, wall_ms=200)}]
        summary = evaluation.summarize(rows)
        self.assertEqual(summary["comparable_completed_pairs"], 1)
        self.assertEqual(summary["completed_pair_ids"], ["a"])
        new = summary["arms"]["new"]
        self.assertEqual(new["exact_match"], 1)
        self.assertEqual(new["fail_open"], 1)
        self.assertEqual(new["exact_match_rate_all_cases"], .5)
        self.assertEqual(new["exact_match_rate_completed"], 1)
        self.assertEqual(new["wall_ms_all"], {"p50": 20, "p95": 200})
        self.assertEqual(new["wall_ms_completed_pairs"], {"p50": 20, "p95": 20})
        self.assertEqual(evaluation.percentiles([]), {"p50": None, "p95": None})

    def test_missing_body_fails_new_arm_without_scoring_no_match_as_correct(self):
        def missing_body(turn, catalog, *, ask_fn):
            path = Path(catalog[0]["path"])
            self.assertTrue(path.is_relative_to(ROOT / "tests"))
            path.unlink()
            return evaluation.codex.select(turn, catalog, ask_fn=ask_fn)
        report = evaluation.run_pairs(self.data, ask_fn=self.mock_ask, limit=1,
                                       selectors={"legacy": evaluation.legacy_select, "new": missing_body})
        result = report["cases"][0]["new"]
        self.assertEqual(result["status"], "fail_open")
        self.assertEqual(result["reason_code"], "skill_evidence_unavailable")
        self.assertEqual(result["got"], [])
        self.assertEqual(result["label"], "fail_open")
        self.assertEqual(result["request_attempts"], 1)
        self.assertEqual(report["summary"]["comparable_completed_pairs"], 0)

    def test_cli_requires_live_and_explicit_output_and_refuses_overwrite(self):
        output_path = self.temporary() / "report.json"
        with patch.object(evaluation.client, "ask", side_effect=AssertionError("live call")) as ask:
            self.assertEqual(evaluation.main(["--check", "--output", str(output_path)]), 0)
            report = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(report["mode"], "check")
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                evaluation.main(["--live", "--output", str(output_path)])
            ask.assert_not_called()
        with patch.object(evaluation.client, "ask", side_effect=self.mock_ask) as ask, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(evaluation.main(["--live", "--limit", "1"]), 0)
        self.assertEqual(ask.call_count, 4)
        self.assertEqual(json.loads(output.getvalue())["case_count"], 1)


if __name__ == "__main__":
    unittest.main()
