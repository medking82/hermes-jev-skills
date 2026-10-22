"""Offline checks for scoring, gold isolation, and bypass accounting."""
import unittest
from unittest.mock import patch
import benchmark as b


class BenchmarkChecks(unittest.TestCase):
    def test_gold_and_rationale_never_enter_model_packet(self):
        case = {"id": "secret-label", "suite": "jev", "request": "What is 2 + 2?",
                "expected": ["none"], "rationale": "GOLD_MARKER_NOT_MODEL_INPUT"}
        packet = b.contract(case)
        self.assertNotIn("expected", packet)
        self.assertNotIn("rationale", packet)
        self.assertNotIn("GOLD_MARKER", str(packet))

    def test_explicit_matt_choice_bypasses_transport(self):
        with patch.object(b.client, "ask", side_effect=AssertionError("Must not call API")):
            value = b.advisor({"suite": "matt", "request": "Use diagnosing-bugs.",
                               "workflow": "diagnosing-bugs"})
        self.assertEqual(value["calls"], [])
        self.assertEqual(value["advice"]["suggested_choices"], ["diagnosing-bugs"])

    def test_native_opt_out_bypasses_transport_and_keeps_all(self):
        with patch.object(b.client, "ask", side_effect=AssertionError("Must not call API")):
            value = b.advisor({"suite": "native", "request": "Review this change.", "enabled": False})
        self.assertEqual(value["calls"], [])
        self.assertEqual(value["advice"]["suggested_choices"], ["all"])

    def test_native_review_not_in_implicit_catalog(self):
        self.assertNotIn("native-review", [r["name"] for r in b.entry_catalog("Review the diff")])
        self.assertIn("native-review", [r["name"] for r in b.entry_catalog("Use native-review")])

    def test_missing_usage_not_silently_zero(self):
        rows = [{"A": {"llm": {"usage": {"input_tokens": 10}}}}, {"A": {"llm": {}}}]
        self.assertEqual(b.usage_total(rows, "A", "input_tokens"), {"total": 10, "known": 1, "missing": 1})

    def test_quantile_interpolation_and_empty(self):
        self.assertEqual(b.quantile([2, 4], .5), 3)
        self.assertIsNone(b.quantile([], .5))


if __name__ == "__main__":
    unittest.main()
