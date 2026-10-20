import tempfile,types,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from jevkit import steward

class BridgeTests(unittest.TestCase):
    def module(self,home):
        def summary(day,repo,ci,tests,inst,tri,use,agent_needed,reasons,paused=False):
            return 'Paused' if paused else '- **Fleet copy:** matches main.\n'
        return types.SimpleNamespace(ROOT_HOME=home,REPO=home/'repo',SWITCHES=home/'switches',git=Mock(),run=Mock(),
               install_state=Mock(),usage=Mock(return_value={}),summary=summary,main=Mock(side_effect=AssertionError('main must not execute')))
    def test_bridge_is_idempotent_reports_unknowns_and_never_calls_main(self):
        with tempfile.TemporaryDirectory() as folder:
            m=self.module(Path(folder));steward.wire_existing(m);usage=m.usage;steward.wire_existing(m)
            self.assertIs(m.usage,usage)
            with patch.object(steward,'usage_totals',return_value={'totals':{'calls':2,'estimated_cost_usd':None,'unknown_cost_rows':1},'unavailable_files':0}):
                use=m.usage(24)
            text=m.summary('day',{},{},{},{},{},use,False,[])
            self.assertNotIn('matches main.',text);self.assertIn('unverified source/install',text)
            self.assertIn('unavailable/partial',text);self.assertIn('not invoice',text);self.assertIn('not realized savings',text)
            m.main.assert_not_called()
    def test_bridge_dry_install_delegates_and_paused_report_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            m=self.module(Path(folder));steward.wire_existing(m)
            with patch.object(steward,'install_state',return_value={'action':'would refresh'}) as install:
                m.install_state('sha',{}, {},dry=True)
                self.assertTrue(install.call_args.kwargs['dry'])
            self.assertEqual(m.summary('day',{},{},{},{},{},{},False,[],paused=True),'Paused')
            m.run.assert_not_called();m.main.assert_not_called()
