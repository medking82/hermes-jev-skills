import unittest
import report


class AnalysisChecks(unittest.TestCase):
    def test_ceiling_accuracy_has_nontrivial_uncertainty(self):
        low, high = report.wilson(40, 40)
        self.assertAlmostEqual(high, 1)
        self.assertGreater(low, .90)
        self.assertLess(low, .92)

    def test_no_discordance_is_not_evidence_of_superiority(self):
        self.assertEqual(report.mcnemar(0, 0), 1)
        self.assertAlmostEqual(report.mcnemar(0, 6), .03125)
        self.assertEqual(report.mcnemar(4, 4), 1)

    def test_constant_paired_difference_interval(self):
        self.assertEqual(report.paired_interval([12, 12, 12]), [12, 12])


if __name__ == "__main__":
    unittest.main()
