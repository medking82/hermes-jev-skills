"""Offline contract tests for the Blender decision boundary. No real API or Blender."""
import json
import unittest
from unittest.mock import patch

from jevkit import blender


def state(**updates):
    value = {'schema': 'jev.blender_state_v1', 'revision': 1, 'geometry': 'pass',
             'materials': 'pass', 'framing': 'pass', 'lighting': 'pass',
             'preview': 'pass', 'export': 'pass', 'issue': 'none',
             'export_requested': True, 'private': False, 'symptoms': [], 'stagnation': 0,
             'estimated_probe_ms': 0}
    value.update(updates)
    return value


def answer(request, **kwargs):
    return {'selected_id': 'inspect_lighting', 'confidence': .9,
            'observation_id': request['observation_id']}


class BlenderPolicyTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        directory=tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        meter=patch.dict('os.environ',{'JEV_LEDGER_PATH':str(Path(directory.name)/'ledger.jsonl'),'JEV_LEDGER':'on'})
        meter.start(); self.addCleanup(meter.stop)

    def test_completion_is_local_verification_not_a_model_verdict(self):
        with patch('jevkit.blender.choose', side_effect=AssertionError('must not call')):
            self.assertEqual(blender.select(state())['action'], 'verify_artifacts')

    def test_red_geometry_stops_before_any_preview_or_inference(self):
        with patch('jevkit.blender.choose', side_effect=AssertionError('must not call')):
            self.assertEqual(blender.select(state(geometry='fail'))['action'], 'planner_repair')

    def test_unknown_geometry_is_measured_before_visual_work(self):
        self.assertEqual(blender.select(state(geometry='unknown'))['action'], 'inspect_geometry')

    def test_missing_preview_and_export_are_not_complete(self):
        self.assertEqual(blender.select(state(preview='unknown'))['action'], 'render_preview')
        self.assertEqual(blender.select(state(export='unknown'))['action'], 'inspect_export')

    def test_no_export_requested_does_not_require_one(self):
        self.assertEqual(blender.select(state(export='unknown', export_requested=False))['action'], 'verify_artifacts')

    def test_private_or_cheap_ambiguous_work_remains_local(self):
        for overrides in ({'private': True, 'estimated_probe_ms': 5000}, {'estimated_probe_ms': 10}):
            with self.subTest(overrides=overrides), patch('jevkit.blender.choose', side_effect=AssertionError('must not call')):
                result = blender.select(state(issue='unclear', **overrides))
                self.assertFalse(result['jev_called'])
                self.assertEqual(result['action'], 'planner_inspect')

    def test_accounting_failure_preserves_local_planner(self):
        with patch('jevkit.choose.usage.ask',side_effect=OSError('fixture ledger unavailable')) as ask:
            result=blender.select(state(issue='unclear',estimated_probe_ms=5000))
        ask.assert_called_once();self.assertEqual(result['action'],'planner_inspect')

    def test_live_request_contains_only_fixed_vocabulary_no_scene_content(self):
        captured = []
        def chooser(request, **kwargs):
            captured.append(request)
            return answer(request)
        with patch('jevkit.blender.choose', side_effect=chooser):
            result = blender.select(state(issue='unclear', estimated_probe_ms=5000))
        self.assertEqual(result['action'], 'inspect_lighting')
        self.assertTrue(result['jev_called'])
        self.assertNotIn('5000', json.dumps(captured[0]))
        self.assertNotIn('revision', json.dumps(captured[0]))
        self.assertIn('reobserve', [x['id'] for x in captured[0]['candidates']])

    def test_invalid_or_unusable_choices_do_not_dispatch(self):
        for selected, confidence, stale in [('arbitrary_code', .99, False), ('verify_artifacts', .99, False),
                                            ('inspect_lighting', .2, False), ('inspect_lighting', True, False),
                                            ('inspect_lighting', float('nan'), False), ('inspect_lighting', .99, True),
                                            ('reobserve', 1., False), ('abstain', 1., False)]:
            with self.subTest(selected=selected, confidence=confidence, stale=stale):
                def chooser(request, **kwargs):
                    return {'selected_id': selected, 'confidence': confidence,
                            'observation_id': 'stale' if stale else request['observation_id']}
                with patch('jevkit.blender.choose', side_effect=chooser):
                    self.assertEqual(blender.select(state(issue='unclear', estimated_probe_ms=5000))['action'], 'planner_inspect')

    def test_unavailable_jev_preserves_local_planner(self):
        with patch('jevkit.blender.choose', side_effect=RuntimeError('transport failed')):
            result = blender.select(state(issue='unclear', estimated_probe_ms=5000))
        self.assertEqual(result['action'], 'planner_inspect')
        self.assertTrue(result['jev_called'])

    def test_unknown_fields_or_free_text_are_refused_before_inference(self):
        for changes in ({'code': 'print(1)'}, {'scene_name': 'private title'}, {'issue': 'custom prose'},
                        {'revision': True}, {'geometry': True}, {'private': 0}, {'estimated_probe_ms': -1},
                        {'stagnation': 2.0}):
            with self.subTest(changes=changes), patch('jevkit.blender.choose', side_effect=AssertionError('must not call')):
                with self.assertRaises(ValueError):
                    blender.select(state(**changes))

    def test_stagnation_never_adds_more_model_calls(self):
        with patch('jevkit.blender.choose', side_effect=AssertionError('must not call')):
            self.assertEqual(blender.select(state(issue='unclear', stagnation=2, estimated_probe_ms=5000))['action'], 'planner_inspect')

    def test_model_never_receives_permission_to_mutate_or_finish(self):
        req = blender.build_request(state(issue='unclear', estimated_probe_ms=5000))
        ids = {x['id'] for x in req['candidates']}
        self.assertEqual(ids, {'inspect_geometry', 'inspect_materials', 'inspect_framing', 'inspect_lighting', 'reobserve', 'abstain'})

    def test_cli_accepts_closed_state_and_refuses_unknown_content(self):
        import subprocess
        import sys
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        for payload, exit_code in [(state(), 0), ({'code': 'DO_NOT_ECHO_PRIVATE_TEXT'}, 2)]:
            result = subprocess.run([sys.executable, '-m', 'jevkit', 'blender-next'],
                                    cwd=root, input=json.dumps(payload), text=True, capture_output=True)
            self.assertEqual(result.returncode, exit_code, result.stderr)
            self.assertNotIn('DO_NOT_ECHO_PRIVATE_TEXT', result.stdout + result.stderr)
            if exit_code == 0:
                self.assertEqual(json.loads(result.stdout)['action'], 'verify_artifacts')

    def test_symptoms_are_fixed_vocabulary_not_a_text_escape(self):
        for value in ['render_dark', ['render_dark', 'render_dark'], ['send private scene'], [False]]:
            with self.subTest(value=value), patch('jevkit.blender.choose') as pick:
                with self.assertRaises(ValueError):
                    blender.select(state(symptoms=value, issue='unclear', estimated_probe_ms=5000))
                pick.assert_not_called()
        req = blender.build_request(state(symptoms=['faceted_surface'], issue='unclear', estimated_probe_ms=5000))
        self.assertIn('faceted surface',json.dumps(req))

    def test_timeout_cap_is_preserved(self):
        with patch('jevkit.blender.choose', side_effect=answer) as pick:
            blender.select(state(issue='unclear', estimated_probe_ms=5000), timeout=20)
        self.assertLessEqual(pick.call_args.kwargs['timeout'], 1.0)


if __name__ == '__main__':
    unittest.main()
