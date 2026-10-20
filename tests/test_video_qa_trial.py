import importlib.util
import math
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('video_trial', Path(__file__).resolve().parents[1] / 'scripts/video_qa_trial.py')
assert SPEC and SPEC.loader
trial = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(trial)


class VideoTrialTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        directory=tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        meter=patch.dict('os.environ',{'JEV_LEDGER_PATH':str(Path(directory.name)/'ledger.jsonl'),'JEV_LEDGER':'on'})
        meter.start(); self.addCleanup(meter.stop)

    def test_code_failure_cannot_be_cleared(self):
        self.assertEqual(trial.route('clear', .99, True), 'review')

    def test_clear_requires_high_confidence(self):
        self.assertEqual(trial.route('clear', .899, False), 'review')
        self.assertEqual(trial.route('clear', .9, False), 'candidate_clear')

    def test_abstention_errors_and_unknown_review(self):
        for choice in ['flag', 'uncertain', 'made-up', None]:
            self.assertEqual(trial.route(choice, 1, False), 'review')
        for confidence in [float('nan'), float('inf'), -1, 2, True, None]:
            self.assertEqual(trial.route('clear', confidence, False), 'review')

    def test_metrics_report_misses_not_just_accuracy(self):
        rows=[dict(label='defect', code_flag=False, decision='candidate_clear'),
              dict(label='defect', code_flag=True, decision='review'),
              dict(label='clean', code_flag=False, decision='review'),
              dict(label='clean', code_flag=False, decision='candidate_clear')]
        out=trial.metrics(rows)
        self.assertEqual(out['missed_defects'],1)
        self.assertEqual(out['clean_frames_escalated'],1)
        self.assertEqual(out['defects'],2)
        self.assertEqual(out['candidate_clear'],2)

    def test_empty_metrics_are_not_perfect(self):
        out=trial.metrics([])
        self.assertIsNone(out['defect_recall'])

    def test_consent_before_any_asset_read(self):
        with self.assertRaises(ValueError):
            trial.validate_manifest(Path('/does-not-exist'), False)

    def test_synthetic_and_bounded_rows_required(self):
        for data in [dict(synthetic=False,rows=[]),dict(synthetic=True,rows=[]),
                     dict(synthetic=True,rows=[{}]*33)]:
            with self.assertRaises(ValueError): trial.validate_data(data)

    def fixture(self, root):
        import json,hashlib
        image=root/'frame.png'; image.write_bytes(b'original synthetic fixture')
        row=dict(id='f0',label='clean',code_flag=False,image='frame.png',
                 sha256=hashlib.sha256(image.read_bytes()).hexdigest())
        manifest=root/'manifest.json'
        manifest.write_text(json.dumps(dict(synthetic=True,rows=[row])))
        return manifest,row

    def test_path_escape_and_changed_hash_rejected(self):
        import json
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); manifest,row=self.fixture(root)
            row['image']='../outside.png'
            manifest.write_text(json.dumps(dict(synthetic=True,rows=[row])))
            with self.assertRaises(ValueError): trial.validate_manifest(manifest,True)
            manifest,row=self.fixture(root)
            (root/'frame.png').write_bytes(b'changed')
            with self.assertRaises(ValueError): trial.validate_manifest(manifest,True)

    def test_missing_usage_and_model_mismatch_cannot_clear(self):
        from unittest.mock import patch
        for change in [dict(input_tokens=None),dict(jev_model='other-version')]:
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp); manifest,_=self.fixture(root)
                response=dict(answers={'verdict':dict(choice='clear',confidence=1)},
                              input_tokens=10,jev_model=trial.MODEL)
                response.update(change)
                with patch.dict(trial.os.environ,{'TYPESAFE_BASE_URL':''}), \
                     patch.object(trial.images,'asset',return_value=('asset_ref',{})), \
                     patch.object(trial.client,'ask',return_value=response):
                    result=trial.run(manifest,root/'report.json',True)
                self.assertEqual(result['results'][0]['decision'],'review')
                self.assertNotEqual(result['results'][0]['status'],'ok')

    def test_network_error_and_replay_do_not_clear_or_resend(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); manifest,_=self.fixture(root)
            with patch.dict(trial.os.environ,{'TYPESAFE_BASE_URL':''}), \
                 patch.object(trial.images,'asset',return_value=('asset_ref',{})), \
                 patch.object(trial.client,'ask',side_effect=trial.client.JevError('timeout')) as ask:
                out=root/'report.json'; result=trial.run(manifest,out,True)
                self.assertEqual(result['results'][0]['decision'],'review')
                self.assertEqual(ask.call_count,1)
                self.assertTrue(out.with_suffix('.attempts.jsonl').is_file())
                with self.assertRaises(ValueError): trial.run(manifest,out,True)
                self.assertEqual(ask.call_count,1)

    def test_override_endpoint_refused_without_network(self):
        from unittest.mock import patch
        with patch.dict(trial.os.environ,{'TYPESAFE_BASE_URL':'https://example.invalid'}), \
             patch.object(trial.client,'ask') as ask:
            with self.assertRaises(ValueError): trial.run(Path('/missing'),Path('/unused'),True)
            ask.assert_not_called()

    def test_question_does_not_contain_labels_or_paths(self):
        state,questions=trial.request_parts('asset_ref')
        self.assertEqual(state,{'frame':'asset_ref'})
        self.assertEqual(set(questions),{'verdict'})
        self.assertNotIn('label',state)
        self.assertNotIn('defect_case',state)
        self.assertNotIn('defect_case',trial.QUESTION)
        self.assertNotIn('/Users/',trial.QUESTION)


if __name__=='__main__': unittest.main()
