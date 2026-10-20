import copy
import unittest
from jevkit import video_qa_ab as ab

class ABTests(unittest.TestCase):
    def fixture(self) -> tuple[dict,dict,dict]:
        row=dict(id='d0',image='frame.png',sha256='0'*64,split='development',requirements={})
        manifest=dict(schema='jev.video_qa_ab_fixture_v1',synthetic=True,rows=[row])
        labels={'d0':'clean'}
        receipt=dict(manifest_sha256=ab.digest(manifest),labels_sha256=ab.digest(labels),model=ab.MODEL,
                     threshold=ab.THRESHOLD,phase='development',records=[])
        for arm in ('A','B'):
            receipt['records'].append(dict(id='d0',arm=arm,status='ok',input_tokens=10,
                question_sha256=ab.digest(ab.questions(arm)),returned_model=ab.MODEL,
                frame_sha256=row['sha256'],requirements_sha256=ab.digest(row['requirements']),
                answers={q:dict(choice='clear',confidence=.9) for q in ab.questions(arm)}))
        return manifest,labels,receipt

    def test_question_shapes_are_fixed_and_do_not_send_labels(self):
        m,l,r=self.fixture()
        self.assertEqual(len(ab.questions('A')),1);self.assertEqual(len(ab.questions('B')),4)
        self.assertEqual(set(ab.parts(m['rows'][0],'asset')),{'frame','requirements'})
        for arm in ('A','B'):
            self.assertTrue(all(q['type']=='choice' for q in ab.questions(arm).values()))
        self.assertFalse(ab.score(m,l,r)['auto_promote'])

    def test_missing_duplicate_or_mutated_outcomes_are_refused(self):
        for change in ['missing','duplicate','question','model','usage','source']:
            m,l,r=self.fixture()
            if change=='missing':r['records'].pop()
            elif change=='duplicate':r['records'].append(r['records'][0])
            elif change=='question':r['records'][0]['question_sha256']='0'*64
            elif change=='model':r['model']='other'
            elif change=='usage':r['records'][0]['input_tokens']=None
            elif change=='source':r['manifest_sha256']='0'*64
            with self.subTest(change=change),self.assertRaises(ValueError):ab.score(m,l,r)

    def test_per_row_model_and_source_bindings_are_required(self):
        for field in ('returned_model','frame_sha256','requirements_sha256'):
            m,l,r=self.fixture();r['records'][0][field]='wrong'
            with self.subTest(field=field),self.assertRaises(ValueError):ab.score(m,l,r)

    def test_confirmation_requires_recorded_development_qualification(self):
        m,l,r=self.fixture();m['rows'][0]['split']='confirmation';r['phase']='confirmation'
        r['manifest_sha256']=ab.digest(m)
        with self.assertRaises(ValueError):ab.score(m,l,r)
        r['development_passed']=True
        self.assertFalse(ab.score(m,l,r)['auto_promote'])

    def test_non_object_answer_is_refused(self):
        m,l,r=self.fixture();r['records'][0]['answers']['verdict']=None
        with self.assertRaises(ValueError):ab.score(m,l,r)

    def test_unknown_truth_is_not_clean(self):
        m,l,r=self.fixture();l['d0']='unknown';r['labels_sha256']=ab.digest(l)
        with self.assertRaises(ValueError):ab.score(m,l,r)

    def test_any_low_confidence_or_unknown_check_preserves_review(self):
        values={q:dict(choice='clear',confidence=.99) for q in ab.questions('B')}
        for change in [dict(choice='clear',confidence=.89),dict(choice='uncertain',confidence=1)]:
            v=copy.deepcopy(values);v['presence']=change
            self.assertFalse(ab.clear(v,'B'))
        values['presence']['confidence']=float('nan')
        with self.assertRaises(ValueError):ab.clear(values,'B')
