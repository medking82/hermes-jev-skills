"""Recorded score answers must round-trip without inference or weaker validation."""
import copy
import json
import unittest
from unittest.mock import patch

from jevkit import client, decide, policy


class RecordedScores(unittest.TestCase):
    def setUp(self):
        self.rules = policy.load('gate-ask')
        self.raw = {
            name: ({'type': 'score', 'score': 2.5,
                    'probabilities': {'2': 0.5, '3': 0.5}, 'confidence': 1.0}
                   if q['type'] == 'score' else {'type': 'noul', 'noul': 0.01})
            for name, q in self.rules['questions'].items()
        }
        self.checked = {
            name: client._check_answer(name, client.check_question(name, q), self.raw[name])
            for name, q in self.rules['questions'].items()
        }

    def test_validated_and_json_saved_scores_rescore_offline(self):
        original = copy.deepcopy(self.checked)
        values = policy.readings(self.rules['questions'], self.checked, policy.DEFAULT_BAND)
        expected = policy.apply(self.rules, values)['action']
        with patch.object(client, 'ask', side_effect=AssertionError('no inference')):
            for answers in [self.raw, self.checked, json.loads(json.dumps(self.checked))]:
                with self.subTest(answer_keys=list(answers['severity']['probabilities'])):
                    result = decide.rescore(self.rules, answers, jev_model='jev-1.14.0', mode='shadow')
                    self.assertEqual(result['action'], expected)
                    self.assertTrue(result['drift'])
        self.assertEqual(self.checked, original, 'caller data must not be mutated')

    def test_score_validation_stays_strict(self):
        bad_spreads = [
            {2: 0.5, '2': 0.5},  # representation collision must never lose a level
            {2: 0.1, 3: 0.1},
            {2: float('nan'), 3: 0.5},
            {2: -0.2, 3: 1.2},
            {2: 0.5, 9: 0.5},
            {True: 0.5, 3: 0.5},
        ]
        for spread in bad_spreads:
            with self.subTest(spread=spread):
                answers = copy.deepcopy(self.checked)
                answers['severity']['probabilities'] = spread
                with self.assertRaises(client.JevError):
                    decide.rescore(self.rules, answers, jev_model='jev-1.14.0', mode='shadow')

    def test_live_drift_still_uses_the_original_fallback(self):
        result = decide.rescore(self.rules, self.checked, jev_model='jev-1.14.0', mode='live')
        self.assertTrue(result['drift'])
        self.assertEqual(result['action'], self.rules['on_drift'])
        self.assertEqual(self.rules['tuned_on'], 'jev-1.13.0')

    def test_score_without_spread_stays_unreported(self):
        answers = copy.deepcopy(self.checked)
        answers['severity']['probabilities'] = {}
        result = decide.rescore(self.rules, answers, jev_model='jev-1.14.0', mode='shadow')
        self.assertEqual(result['answers']['severity']['p'], {})


if __name__ == '__main__':
    unittest.main()
