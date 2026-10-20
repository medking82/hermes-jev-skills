import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from jevkit import ledger
from jevkit import usage

class UsageTests(unittest.TestCase):
    def test_unresolved_and_orphan_events_remain_unknown_not_free(self):
        identity='a'*32
        start=dict(ts=1,profile='test',feature='video_qa',attempt_id=identity,
                   usage_event='attempt',status='pending',source='jev')
        for rows in [[start],[dict(start,usage_event='result',status='ok',input_tokens=20,cost_usd=.01,list_usd=.01)],
                     [start,start,dict(start,usage_event='result',status='ok',input_tokens=20)]]:
            logical=ledger.logical_calls(rows)
            self.assertEqual(len(logical),1)
            self.assertEqual(logical[0]['status'],'unknown')
            report=ledger.summarize(logical,False)
            self.assertEqual(report['totals']['unresolved_attempts'],1)
            self.assertFalse(report['totals']['estimated_cost_complete'])
            self.assertIsNone(report['totals']['billed_cost_usd'])

    def test_window_filter_keeps_cross_boundary_attempt_pair(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'ledger'
            a=dict(ts=1,feature='video_qa',profile='test',usage_event='attempt',attempt_id='b'*32,status='pending')
            b=dict(a,ts=3,usage_event='result',status='ok',input_tokens=10,cost_usd=.01,list_usd=.01)
            p.write_text(json.dumps(a)+'\n'+json.dumps(b)+'\n')
            rows=ledger.read(p,since=2)
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]['status'],'ok')

    def test_exception_does_not_claim_zero_usage_or_retry(self):
        self.assertIsNotNone(usage)
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ',{'JEV_LEDGER_PATH':str(Path(tmp)/'calls'),'JEV_LEDGER':'on'}):
            with patch('jevkit.client.ask',side_effect=RuntimeError('do not log private exception text')) as ask:
                with self.assertRaises(RuntimeError):usage.ask('video_qa',{}, {'q':{}},retries=0)
            self.assertEqual(ask.call_count,1)
            row=ledger.read()[0]
            self.assertEqual(row['send_state'],'unknown')
            self.assertIsNone(row['cost_usd']);self.assertIsNone(row['input_tokens'])
            self.assertNotIn('private exception',ledger.path().read_text())

    def test_missing_usage_stays_unknown(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ',{'JEV_LEDGER_PATH':str(Path(tmp)/'calls'),'JEV_LEDGER':'on'}):
            with patch('jevkit.client.ask',return_value=dict(answers={},input_tokens=None,provider='typesafe',jev_model='jev-1.14.0')):
                usage.ask('video_qa',{}, {'q':{}},retries=0)
            r=ledger.summarize(ledger.read(),False)
            self.assertEqual(r['groups'][0]['usage_unknown'],1)
            self.assertFalse(r['totals']['estimated_cost_complete'])

    def test_retry_and_unknown_feature_rejected_without_request(self):
        with patch('jevkit.client.ask') as ask:
            for feature,retries in [('video_qa',1),('private unknown',0)]:
                with self.assertRaises(ValueError):usage.ask(feature,{}, {'q':{}},retries=retries)
            ask.assert_not_called()

    def test_write_ahead_failure_prevents_network(self):
        with patch('jevkit.ledger.enabled',return_value=True), patch('jevkit.ledger.append',side_effect=OSError('disk busy')), patch('jevkit.client.ask') as ask:
            with self.assertRaises(OSError):usage.ask('video_qa',{}, {'q':{}},retries=0)
            ask.assert_not_called()

    def test_shadow_potential_does_not_become_actual_savings(self):
        r=ledger.summarize([dict(feature='vision',shadow=True,status='ok',input_tokens=0,
                                cost_usd=0,list_usd=0,llm_avoided_est=999)],False)
        self.assertEqual(r['groups'][0]['actual_llm_avoided_tokens'],0)
        self.assertEqual(r['totals']['llm_avoided_est_tokens'],999)

    def test_retries_must_be_zero(self):
        with patch.object(usage.client,'ask') as call:
            with self.assertRaises(ValueError):
                usage.ask('video_qa',{},{},retries=1)
            call.assert_not_called()

    def test_terminal_write_failure_does_not_replay_paid_call(self):
        actual_open=ledger.os.open
        opens=[]
        def failing_open(*args,**kwargs):
            opens.append(1)
            if len(opens)>1:raise OSError('fixture terminal write failure')
            return actual_open(*args,**kwargs)
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ',{'JEV_LEDGER_PATH':str(Path(tmp)/'calls.jsonl'),'JEV_LEDGER':'on'}):
            with patch.object(ledger.os,'open',side_effect=failing_open), \
                 patch.object(usage.client,'ask',return_value={'input_tokens':10,'jev_model':'jev-1.14.0'}) as call:
                with self.assertRaises(OSError):
                    usage.ask('video_qa',{},{})
                call.assert_called_once()
            self.assertEqual(ledger.read()[0]['status'],'unknown')

    def test_summary_exposes_explicit_estimate_fields(self):
        result=ledger.summarize([{'feature':'fixture','shadow':True,'cost_usd':0.1,'llm_avoided_est':50}],by_day=False)
        self.assertEqual(result['totals']['actual_llm_avoided_tokens'],0)
        self.assertEqual(result['totals']['counterfactual_llm_avoided_est_tokens'],50)
        self.assertEqual(result['totals']['estimated_cost_usd'],0.1)
        self.assertIsNone(result['totals']['billed_cost_usd'])

    def test_unknown_spend_closes_the_daily_budget(self):
        import time,math
        row=dict(ts=time.time(),feature='video_qa',status='unknown',cost_usd=None)
        self.assertTrue(math.isinf(ledger.spent_today([row])))

    def test_attempt_precedes_call_and_summary_counts_once(self):
        self.assertIsNotNone(usage,'Missing standalone usage meter')
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ',{'JEV_LEDGER_PATH':str(Path(tmp)/'calls.jsonl'),'JEV_LEDGER':'on'}):
            def reply(*args,**kwargs):
                raw=[json.loads(x) for x in ledger.path().read_text().splitlines()]
                self.assertEqual(raw[0]['usage_event'],'attempt')
                self.assertNotIn('private heading',ledger.path().read_text())
                return dict(answers={},input_tokens=42,jev_model='jev-1.14.0',provider='typesafe',latency_ms=2)
            with patch('jevkit.client.ask',side_effect=reply):
                out=usage.ask('video_qa',{'private heading':'never log plaintext'},{'q':{'type':'noul','instructions':'Test?'}},retries=0)
            self.assertEqual(out['input_tokens'],42)
            rows=ledger.read(); self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['input_tokens'],42)
            total=ledger.summarize(rows,by_day=False)['totals']
            self.assertEqual(total['calls'],1)
            self.assertIsNone(total['billed_cost_usd'])
