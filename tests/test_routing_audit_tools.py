"""Offline reports must distinguish request reuse and missing execution evidence."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


def load(name):
    path = Path(__file__).resolve().parents[1] / "scripts" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AuditTools(unittest.TestCase):
    @staticmethod
    def measurement_records():
        # Synthetic unit inputs deliberately exercise the measured-record schema.
        # These opaque evidence IDs are test doubles, not execution receipts.
        return [{"case_id": "a", "run_id": "1", "arm": arm, "data_kind": "measured",
                 "execution_verified": True, "execution_evidence_id": "test-execution-" + arm,
                 "cost_source": "provider_invoice", "cost_evidence_id": "test-invoice-" + arm,
                 "review_kind": "human", "reviewer_ids": ["test-reviewer"],
                 "review_evidence_id": "test-review-" + arm, "quality_score": quality,
                 "latency_ms": latency, "actual_cost_usd": cost}
                for arm, cost, quality, latency in (("baseline", 0.2, 2, 20), ("routed", 0.1, 3, 10))]

    def test_untrusted_event_kind_is_not_published(self):
        result = load("audit_routing")._summarize([
            json.dumps({"kind": "private-sentinel"}), json.dumps({"kind": {"bad": "shape"}})])
        self.assertEqual(result["events"], {"unknown": 2})
        self.assertNotIn("private-sentinel", json.dumps(result))

    def test_followups_do_not_inflate_turn_denominator(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            path.write_text("\n".join(json.dumps(r) for r in [
                {"kind": "route_effective", "first_request": True, "applied": True},
                {"kind": "route_effective", "first_request": False, "applied": True},
                {"kind": "route_effective", "first_request": True, "applied": False},
            ]) + "\nnot-json\n")
            result = load("audit_routing").summarize(path)
        self.assertEqual(result["request_application_rate"], 2 / 3)
        self.assertEqual(result["first_request_application_rate"], 1 / 2)
        self.assertEqual(result["malformed"], 1)

    def test_unverified_execution_cannot_produce_measured_difference(self):
        rows = [{"case_id": "a", "run_id": "1", "arm": arm,
                 "actual_cost_usd": 0.1, "latency_ms": 20} for arm in ("baseline", "routed")]
        result = load("compare_routing_eval").compare(rows)
        self.assertEqual(result["execution_verified_pairs"], 0)
        self.assertEqual(result["routed_minus_baseline"], {})

    def test_paired_measurements_and_duplicate_rejection(self):
        module = load("compare_routing_eval")
        rows = self.measurement_records()
        result = module.compare(rows)
        self.assertAlmostEqual(result["routed_minus_baseline"]["actual_cost_usd"]["mean"], -0.1)
        self.assertEqual(result["routed_minus_baseline"]["quality_score"]["mean"], 1)
        self.assertEqual(result["human_reviewed_pairs"], 1)
        self.assertEqual(result["excluded_pairs"], {})
        with self.assertRaises(ValueError):
            module.compare(rows + rows)

    def test_synthetic_pairs_never_enter_measured_differences(self):
        rows = [{"case_id": "fixture", "run_id": "1", "arm": arm,
                 "data_kind": "synthetic", "execution_verified": True,
                 "cost_source": "synthetic-fixture", "reviewer_ids": "synthetic-reviewer",
                 "quality_score": 4, "latency_ms": 10, "actual_cost_usd": cost}
                for arm, cost in (("baseline", 0.2), ("routed", 0.1))]
        result = load("compare_routing_eval").compare(rows)
        self.assertEqual(result["routed_minus_baseline"], {})
        self.assertEqual(result["excluded_pairs"], {"synthetic": 1})
        self.assertEqual(result["execution_verified_pairs"], 0)

    def test_mixed_or_unclassified_pairs_are_excluded(self):
        module = load("compare_routing_eval")
        for value in (None, "synthetic", "unknown", True, ["measured"]):
            with self.subTest(data_kind=value):
                rows = self.measurement_records()
                rows[1]["data_kind"] = value
                result = module.compare(rows)
                self.assertEqual(result["routed_minus_baseline"], {})
                self.assertEqual(result["excluded_pairs"], {"missing_or_mixed_provenance": 1})

    def test_unverified_or_unreferenced_execution_is_excluded(self):
        module = load("compare_routing_eval")
        for field, value in (("execution_verified", "true"), ("execution_verified", 1),
                             ("execution_evidence_id", " "), ("execution_evidence_id", [])):
            with self.subTest(field=field, value=value):
                rows = self.measurement_records()
                rows[1][field] = value
                result = module.compare(rows)
                self.assertEqual(result["routed_minus_baseline"], {})
                self.assertEqual(result["execution_verified_pairs"], 0)

    def test_cost_requires_recognized_source_and_evidence(self):
        module = load("compare_routing_eval")
        for field, value in (("cost_source", "synthetic-fixture"), ("cost_source", "estimated"),
                             ("cost_source", True), ("cost_source", ["provider_invoice"]),
                             ("cost_evidence_id", ""), ("cost_evidence_id", {})):
            with self.subTest(field=field, value=value):
                rows = self.measurement_records()
                rows[1][field] = value
                deltas = module.compare(rows)["routed_minus_baseline"]
                self.assertNotIn("actual_cost_usd", deltas)
                self.assertIn("latency_ms", deltas)

    def test_quality_requires_structured_human_review_evidence(self):
        module = load("compare_routing_eval")
        for field, value in (("reviewer_ids", "synthetic-reviewer"), ("reviewer_ids", {}),
                             ("reviewer_ids", [""]), ("reviewer_ids", ["a", " a "]),
                             ("reviewer_ids", [1]), ("review_kind", "automated"),
                             ("review_evidence_id", None)):
            with self.subTest(field=field, value=value):
                rows = self.measurement_records()
                rows[1][field] = value
                result = module.compare(rows)
                self.assertEqual(result["human_reviewed_pairs"], 0)
                self.assertNotIn("quality_score", result["routed_minus_baseline"])
                self.assertIn("latency_ms", result["routed_minus_baseline"])

    def test_synthetic_data_cannot_pollute_a_measured_pair(self):
        module = load("compare_routing_eval")
        rows = self.measurement_records()
        synthetic = [{**row, "case_id": "fixture", "data_kind": "synthetic",
                      "actual_cost_usd": 9999, "latency_ms": 9999} for row in rows]
        result = module.compare(rows + synthetic)
        self.assertEqual(result["routed_minus_baseline"], module.compare(rows)["routed_minus_baseline"])
        self.assertEqual(result["paired"], 2)
        self.assertEqual(result["excluded_pairs"], {"synthetic": 1})

    def test_replay_never_buys_missing_answers(self):
        module = load("replay_routing_eval")
        with self.assertRaises(ValueError):
            module.replay([{"case_id": "missing"}], {}, [])
        result = module.replay([{
            "case_id": "pinned", "category": "coding", "prompt": "Implement median",
            "current": "unknown:user-choice", "provider": "unknown", "pinned": True,
            "answers": {}}], {}, [])
        self.assertFalse(result[0]["routed"])
        self.assertEqual(result[0]["model"], "unknown:user-choice")
