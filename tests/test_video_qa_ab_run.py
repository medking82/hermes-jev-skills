import json,struct,zlib,tempfile
from pathlib import Path
import unittest
from unittest.mock import patch,Mock
from jevkit import video_qa_ab as ab,video_qa_ab_run as run,client

def png():
    def chunk(name,data):return struct.pack('>I',len(data))+name+data+struct.pack('>I',zlib.crc32(name+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',640,360,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+b'\x20\x30\x40'*640)*360))+chunk(b'IEND',b'')

class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.fixture=self.root/'fixture';self.fixture.mkdir();self.out=self.root/'run'
        image=png();(self.fixture/'frame.png').write_bytes(image)
        rows=[dict(id=p,image='frame.png',sha256=run.sha(self.fixture/'frame.png'),split=p,requirements={}) for p in ('development','confirmation')]
        manifest=dict(schema='jev.video_qa_ab_fixture_v1',synthetic=True,rows=rows);labels={p:'clean' for p in ('development','confirmation')}
        protocol=dict(model=ab.MODEL,threshold=ab.THRESHOLD,manifest_sha256=ab.digest(manifest),labels_sha256=ab.digest(labels),
                      arm_question_sha256={a:ab.digest(ab.questions(a)) for a in ('A','B')},phase_counts={'development':1,'confirmation':1})
        for name,obj in [('manifest',manifest),('labels',labels),('protocol',protocol)]:
            (self.fixture/(name+'.json')).write_text(json.dumps(obj))
    def fake(self,feature,state,questions,**kwargs):
        self.assertEqual(kwargs['retries'],0);self.assertEqual(kwargs['provider'],'typesafe')
        return dict(jev_model=ab.MODEL,input_tokens=100,answers={q:dict(choice='clear',confidence=1) for q in questions})
    def test_arm_order_is_counterbalanced_before_outcomes(self):
        manifest=json.loads((self.fixture/'manifest.json').read_text())
        manifest['rows']=[dict(r,id=r['id']+str(i)) for r in manifest['rows'] for i in range(2)]
        labels={r['id']:'clean' for r in manifest['rows']}
        protocol=json.loads((self.fixture/'protocol.json').read_text())
        protocol.update(manifest_sha256=ab.digest(manifest),labels_sha256=ab.digest(labels),phase_counts={'development':2,'confirmation':2})
        for name,obj in [('manifest',manifest),('labels',labels),('protocol',protocol)]:
            (self.fixture/(name+'.json')).write_text(json.dumps(obj))
        run.freeze(self.fixture,self.out);order=[]
        def invoke(feature,state,questions,**kwargs):
            order.append('A' if questions==ab.questions('A') else 'B')
            return self.fake(feature,state,questions,**kwargs)
        run.run(self.fixture,self.out,ask=invoke)
        self.assertEqual(order,['A','B','B','A','A','B','B','A'])

    def test_full_rehearsal_and_replay_refusal(self):
        run.freeze(self.fixture,self.out)
        result=run.run(self.fixture,self.out,ask=self.fake)
        self.assertEqual(len(result['records']),4);self.assertEqual(len(result['phases']),2)
        before=run.sha(self.out/'receipt.json')
        with self.assertRaises(ValueError):run.run(self.fixture,self.out,ask=Mock(side_effect=AssertionError('resend')))
        with patch('http.client.HTTPSConnection',side_effect=AssertionError('audit network')):audit=run.audit(self.fixture,self.out)
        self.assertEqual(audit['attempts'],4);self.assertEqual(before,run.sha(self.out/'receipt.json'))
    def test_unknown_send_stops_and_is_reserved_not_free(self):
        run.freeze(self.fixture,self.out)
        ask=Mock(side_effect=client.JevError('network'))
        result=run.run(self.fixture,self.out,ask=ask);ask.assert_called_once()
        self.assertEqual(result['stop_reason'],'failed_or_unknown_attempt')
        self.assertGreater(float(result['conservative_bound_usd']),0)
    def test_cap_and_source_changes_refuse_before_calls(self):
        with self.assertRaises(ValueError):run.freeze(self.fixture,self.out,.001)
        run.freeze(self.fixture,self.out)
        (self.fixture/'frame.png').write_bytes(b'changed')
        ask=Mock()
        with self.assertRaises(ValueError):run.run(self.fixture,self.out,ask=ask)
        ask.assert_not_called()
    def test_substituted_model_stops(self):
        run.freeze(self.fixture,self.out)
        def wrong(*args,**kwargs):return dict(jev_model='wrong',input_tokens=1,answers={})
        result=run.run(self.fixture,self.out,ask=wrong)
        self.assertEqual(len(result['records']),1);self.assertEqual(result['stop_reason'],'failed_or_unknown_attempt')
    def test_standard_client_retries_zero_is_one_http_attempt(self):
        connection=Mock();connection.request.side_effect=OSError('offline fixture closed socket')
        with patch.object(client._POOL,'borrow',return_value=connection) as borrow,patch.object(client._POOL,'drop'):
            with self.assertRaises(client.JevError):
                client.ask({}, {'q':client.choice('Fixture?',{'yes':'yes','no':'no'})},
                           api_key='offline-fixture-not-a-real-key',provider='typesafe',retries=0)
        self.assertEqual(borrow.call_count,1)

    def test_single_post_redirect_is_never_followed_and_error_saved(self):
        connection=Mock();response=Mock(status=302);response.read.return_value=b'{"error":"fixture redirect"}'
        connection.getresponse.return_value=response
        with patch('http.client.HTTPSConnection',return_value=connection):
            with self.assertRaises(client.JevError):run.single_post(self.out,'fixture')(json.dumps({'model':ab.MODEL}).encode(),{},1)
        connection.request.assert_called_once();connection.close.assert_called_once()
        self.assertTrue((self.out/'errors/fixture.json').exists())
    def test_http_body_model_gate_precedes_open(self):
        with patch('http.client.HTTPSConnection') as open:
            with self.assertRaises(ValueError):run.single_post(self.out,'fixture')(b'{"model":"wrong"}',{},1)
            open.assert_not_called()
    def test_actual_client_synthetic_transport_rehearsal(self):
        run.freeze(self.fixture,self.out)
        class Connection:
            def __init__(self,*args,**kwargs):pass
            def request(self,method,path,body,headers):
                self.payload=json.loads(body)
                if method!='POST' or self.payload['model']!=ab.MODEL:raise AssertionError('wire')
            def getresponse(self):
                q=self.payload['questions'];obj=dict(model=ab.MODEL,usage={'input_tokens':100},answers={
                    key:dict(type='choice',choice='clear',confidence=1,probabilities={'clear':1,'flag':0,'uncertain':0}) for key in q})
                response=Mock(status=200);response.read.return_value=json.dumps(obj).encode();return response
            def close(self):pass
        def invoke(feature,state,questions,**kwargs):return client.ask(state,questions,api_key='offline-fixture-not-a-real-key',**kwargs)
        with patch('http.client.HTTPSConnection',Connection):result=run.run(self.fixture,self.out,ask=invoke)
        self.assertEqual(len(result['records']),4)
