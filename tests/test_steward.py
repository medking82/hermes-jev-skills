from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from jevkit import steward

class StewardTests(unittest.TestCase):
    def test_fleet_usage_aggregates_metadata_without_private_labels(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'logs').mkdir()
            rows=[dict(ts=100,feature='private-client-fixture-name',status='ok',cost_usd=0.1,input_tokens=2,shadow=True,action='private-fixture-action'),
                  dict(ts=101,feature='video_qa',status='pending',usage_event='attempt',attempt_id='f'*32)]
            (root/'logs/jev-ledger.jsonl').write_text('\n'.join(json.dumps(r) for r in rows))
            result=steward.usage_totals([root],since=0)
            self.assertEqual(result['totals']['calls'],2)
            self.assertFalse(result['totals']['estimated_cost_complete'])
            self.assertNotIn('private-client-fixture-name',str(result))
            self.assertNotIn('private-fixture-action',str(result))
            self.assertEqual(result['totals']['unresolved_attempts'],1)
            self.assertEqual(result['totals']['unknown_cost_rows'],1)

    def test_refresh_gates_never_execute_installer(self):
        cases=('dirty','ci','tests','no_auto','dry')
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as folder:
                root=Path(folder);run=Mock()
                p=dict(checkout_at_main=True,checkout_dirty=case=='dirty',installed_matches_checkout=False,matches_main=False)
                if case=='no_auto':(root/'NO_AUTO_INSTALL').write_text('fixture')
                with patch('jevkit.provenance.check_install',return_value=p):
                    state=steward.install_state('a'*40,{'status':'failure' if case=='ci' else 'success'},
                        {'status':'red' if case=='tests' else 'green'},repo=root,home=root,switches=root,
                        git=Mock(),run=run,dry=case=='dry')
                run.assert_not_called();self.assertFalse(state['main_match'])
                self.assertIn('action',state)

    def test_verified_refresh_uses_enable_none_and_rechecks(self):
        p=dict(checkout_at_main=True,checkout_dirty=False,installed_matches_checkout=False,matches_main=False)
        done={**p,'installed_matches_checkout':True,'matches_main':True}
        with tempfile.TemporaryDirectory() as folder, patch('jevkit.provenance.check_install',side_effect=[p,done]) as inspect:
            run=Mock(return_value=(0,'',''))
            state=steward.install_state('a'*40,{'status':'success'},{'status':'green'},repo=folder,home=folder,switches=folder,git=Mock(),run=run)
            self.assertEqual(inspect.call_count,2);run.assert_called_once()
            self.assertEqual(run.call_args.args[0],['/usr/bin/python3','install.py','--enable','none'])
            self.assertTrue(state['main_match']);self.assertTrue(state['switches_unchanged'])

    def test_provenance_failure_cannot_install(self):
        with tempfile.TemporaryDirectory() as folder, patch('jevkit.provenance.check_install',side_effect=ValueError('fixture invalid identity')):
            run=Mock()
            state=steward.install_state('a'*40,{'status':'success'},{'status':'green'},repo=folder,home=folder,switches=folder,git=Mock(),run=run)
            run.assert_not_called();self.assertFalse(state['main_match'])

    def test_matching_feature_checkout_cannot_claim_main_or_install(self):
        self.assertIsNotNone(steward,'Missing checked stewardship adapter')
        p=dict(checkout_at_main=False,checkout_dirty=False,installed_matches_checkout=True,
               matches_main=False,checkout_sha='f'*40,main_sha='a'*40)
        run=Mock(); git=Mock()
        with tempfile.TemporaryDirectory() as folder, patch('jevkit.provenance.check_install',return_value=p):
            state=steward.install_state('a'*40,{'status':'success'},{'status':'green'},
                repo=Path(folder),home=Path(folder),switches=Path(folder),git=git,run=run)
        run.assert_not_called()
        self.assertFalse(state['main_match'])
        self.assertTrue(state['in_sync'])
        self.assertNotIn('matches main',steward.describe_install(state))
