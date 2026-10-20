import hashlib
import unittest
from unittest.mock import Mock
from jevkit import video_qa as v

DATA=b'synthetic png bytes'
SHA=hashlib.sha256(DATA).hexdigest()

class VideoQATests(unittest.TestCase):
    def job(self,n=1) -> dict:
        return dict(schema='jev.video_qa_v1',cloud_policy='authorized_synthetic',review_risk='routine',
          source_sha256='a'*64,local_checks={k:'pass' for k in v.LOCAL_CHECKS},
          requirements=dict(required_text=['Different words'],required_elements=['blue button'],palette=['#224488'],
                            allow_blank=False,allow_overlap=False),
          frames=[dict(id=f'f{i}',image=f'f{i}.png',sha256=SHA,local='pass',scene='one',transition=False) for i in range(n)])
    def reply(self,choice='clear',confidence=.99,model=None):
        return dict(answers={'verdict':dict(choice=choice,confidence=confidence)},input_tokens=100,jev_model=model or v.MODEL)
    def run_job(self,j,reply=None,**kw):
        asker=Mock(return_value=reply or self.reply()); reader=Mock(return_value=DATA)
        report=v.screen(j,reader=reader,asker=asker,assetter=lambda b:('picture',{}),**kw)
        return report,reader,asker
    def test_private_and_unknown_never_read_or_send(self):
        for policy in ['local_only','unknown']:
            j=self.job(); j['cloud_policy']=policy
            r,read,ask=self.run_job(j)
            read.assert_not_called(); ask.assert_not_called()
            self.assertEqual(r['review_ids'],['f0'])
    def test_accounting_failure_stops_spending_and_requests_full_review(self):
        asker=Mock(side_effect=OSError('fixture ledger unavailable'))
        report=v.screen(self.job(3),reader=lambda f:DATA,asker=asker,assetter=lambda b:('picture',{}))
        asker.assert_called_once();self.assertTrue(report['requires_full_visual_review'])
        self.assertEqual(report['frames'][0]['reason'],'usage_unavailable')
        self.assertIsNone(report['estimated_list_usd'])

    def test_missing_policy_is_local_only(self):
        j=self.job(); del j['cloud_policy']; r,read,ask=self.run_job(j)
        read.assert_not_called(); ask.assert_not_called()
    def test_unknown_or_failed_local_checks_never_send(self):
        for status in ['unknown','fail']:
            j=self.job(); j['local_checks']['decode']=status
            r,read,ask=self.run_job(j); read.assert_not_called(); ask.assert_not_called()
    def test_local_frame_failure_cannot_be_cleared(self):
        j=self.job(); j['frames'][0]['local']='fail'
        r,read,ask=self.run_job(j); ask.assert_not_called()
        self.assertEqual(r['review_ids'],['f0'])
    def test_general_requirements_and_image_only_leave(self):
        r,read,ask=self.run_job(self.job()); state=ask.call_args.args[0]
        self.assertEqual(state['requirements']['required_text'],['Different words'])
        self.assertEqual(set(state),{'frame','requirements'})
        self.assertNotIn('source_sha256',state)
        self.assertEqual(r['audit_ids'],['f0'])
        self.assertFalse(r['final_acceptance'])
    def test_hash_mismatch_never_sends(self):
        j=self.job(); j['frames'][0]['sha256']='b'*64
        r,read,ask=self.run_job(j); ask.assert_not_called()
        self.assertEqual(r['frames'][0]['reason'],'image_changed')
    def test_exact_duplicates_cached_but_still_audited(self):
        r,read,ask=self.run_job(self.job(12)); self.assertEqual(ask.call_count,1)
        self.assertEqual(r['model_calls'],1)
        self.assertTrue({'f0','f9','f11'}.issubset(set(r['audit_ids'])))
    def test_each_scene_transition_and_unknown_risk_audited(self):
        j=self.job(4); j['frames'][1]['scene']='two'; j['frames'][2]['transition']=True
        r,_,_=self.run_job(j); self.assertEqual(r['audit_ids'],['f0','f1','f2','f3'])
        j=self.job(4); j['review_risk']='unknown'
        r,_,_=self.run_job(j); self.assertEqual(len(r['audit_ids']),4)
    def test_uncertain_low_invalid_or_wrong_model_review(self):
        for response in [self.reply('uncertain'),self.reply('clear',.89),self.reply('other'),
                         self.reply('clear',float('nan')),self.reply(model='other')]:
            r,_,_=self.run_job(self.job(),response)
            self.assertEqual(r['review_ids'],['f0'])
    def test_missing_usage_and_error_fail_to_review(self):
        response=self.reply(); response['input_tokens']=None
        r,_,_=self.run_job(self.job(),response); self.assertEqual(r['review_ids'],['f0'])
        ask=Mock(side_effect=v.client.JevError('timeout'))
        r=v.screen(self.job(),reader=lambda f:DATA,asker=ask,assetter=lambda b:('p',{}))
        self.assertEqual(r['review_ids'],['f0'])
    def test_budget_defers_instead_of_passing(self):
        r,_,ask=self.run_job(self.job(),max_calls=0)
        ask.assert_not_called(); self.assertEqual(r['review_ids'],['f0'])
        self.assertFalse(r['screening_complete'])
    def test_unknown_fields_and_invalid_values_rejected(self):
        j=self.job(); j['hidden']='send'
        with self.assertRaises(ValueError): v.validate(j)
        for key,value in [('review_risk','unbounded'),('frames',[]),('source_sha256','wrong')]:
            j=self.job(); j[key]=value
            with self.assertRaises(ValueError): v.validate(j)
    def test_cost_estimate_uses_actual_list_field(self):
        r,_,_=self.run_job(self.job())
        self.assertEqual(r['estimated_list_usd'],v.ledger.cost(100,'typesafe',v.MODEL)['list_usd'])

    def test_no_coverage_stops_after_eight_calls(self):
        j=self.job(12)
        for i,frame in enumerate(j['frames']):
            frame['sha256']=hashlib.sha256(str(i).encode()).hexdigest()
        ask=Mock(return_value=self.reply('flag'))
        r=v.screen(j,reader=lambda f:f['id'][1:].encode(),asker=ask,assetter=lambda b:('p',{}))
        self.assertEqual(ask.call_count,8)
        self.assertTrue(r['requires_full_visual_review'])
        self.assertEqual(r['frames'][-1]['reason'],'low_coverage_fallback')
        self.assertEqual(len(r['review_ids']),12)

    def test_invalid_budgets_and_mutating_caller_do_not_change_policy(self):
        for budget in [dict(max_calls=True),dict(timeout_s=float('nan')),dict(timeout_s=True)]:
            with self.assertRaises(ValueError): self.run_job(self.job(),**budget)
        j=self.job()
        def reader(f):
            j['requirements']['required_text']=['changed after validation']
            return DATA
        ask=Mock(return_value=self.reply())
        v.screen(j,reader=reader,asker=ask,assetter=lambda b:('p',{}))
        self.assertEqual(ask.call_args.args[0]['requirements']['required_text'],['Different words'])

    def test_private_cli_needs_no_pixels_and_refuses_replay(self):
        import tempfile,json,subprocess,sys
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); j=self.job(); j['cloud_policy']='local_only'
            p=root/'job.json'; p.write_text(json.dumps(j)); out=root/'receipt.json'
            cmd=[sys.executable,str(Path(__file__).resolve().parents[1]/'scripts/video_qa.py'),str(p),'--out',str(out)]
            result=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(result.returncode,3)
            receipt=json.loads(out.read_text())
            self.assertEqual(receipt['model_calls'],0)
            self.assertEqual(receipt['review_ids'],['f0'])
            self.assertEqual(subprocess.run(cmd,capture_output=True).returncode,2)

    def test_sensitive_requirements_not_sent(self):
        j=self.job(); j['requirements']['required_text']=['person@example.com']
        r,read,ask=self.run_job(j); read.assert_not_called(); ask.assert_not_called()
        self.assertEqual(r['review_ids'],['f0'])

if __name__=='__main__': unittest.main()
