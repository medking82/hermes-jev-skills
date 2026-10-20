"""Frozen one-attempt synthetic A/B collector. No retries, redirects or automatic promotion."""
from __future__ import annotations
import hashlib
import http.client
import json
import os
from pathlib import Path
import time
from decimal import Decimal
from urllib.parse import urlsplit
from . import client,images,ledger,usage,video_qa_ab as ab

RATE=Decimal(str(ledger.USD_PER_INPUT_TOKEN))
RESERVE_TOKENS=8_000_000
RESERVE=RESERVE_TOKENS*RATE
MAX_REQUESTS=48

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def write(path,data,exclusive=False):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    mode=os.O_WRONLY|os.O_CREAT|(os.O_EXCL if exclusive else os.O_TRUNC)
    fd=os.open(path,mode,0o600)
    with os.fdopen(fd,'w') as handle:
        handle.write(json.dumps(data,indent=2,sort_keys=True)+'\n');handle.flush();os.fsync(handle.fileno())

def pins():
    root=Path(__file__).resolve().parents[1]
    names=['jevkit/video_qa_ab_run.py','jevkit/video_qa_ab.py','jevkit/video_qa.py','jevkit/usage.py',
           'jevkit/client.py','jevkit/images.py','jevkit/ledger.py','tests/test_video_qa_ab_run.py','scripts/run_video_qa_ab.py']
    return {n:sha(root/n) for n in names}

def freeze(fixture,out,cap=1.0):
    fixture=Path(fixture).resolve();out=Path(out)
    cap=Decimal(str(cap))
    if not cap.is_finite() or not 0<cap<=1 or RESERVE>cap:raise ValueError('Unapproved/insufficient cap')
    manifest=json.loads((fixture/'manifest.json').read_text());labels=json.loads((fixture/'labels.json').read_text())
    protocol=json.loads((fixture/'protocol.json').read_text())
    if (manifest.get('synthetic') is not True or protocol['model']!=ab.MODEL or protocol['threshold']!=ab.THRESHOLD
        or protocol['manifest_sha256']!=ab.digest(manifest) or protocol['labels_sha256']!=ab.digest(labels)
        or protocol['arm_question_sha256']!={a:ab.digest(ab.questions(a)) for a in ('A','B')}):
        raise ValueError('Frozen synthetic protocol changed')
    rows=manifest['rows']
    if not rows or len(rows)*2>MAX_REQUESTS or len({r['id'] for r in rows})!=len(rows):raise ValueError('Invalid request plan')
    if set(labels)!={r['id'] for r in rows} or any(v not in ('clean','defect') for v in labels.values()):raise ValueError('Invalid labels')
    for row in rows:
        ab.parts(row,'frame')
        if row['split'] not in ('development','confirmation'):raise ValueError('Reserve/unplanned rows refused')
        path=(fixture/row['image']).resolve()
        if not path.is_relative_to(fixture) or sha(path)!=row['sha256']:raise ValueError('Frame source changed')
        _,w,h=images.inspect(path.read_bytes())
        if w>640 or h>360:raise ValueError('Outside conservative reservation geometry')
        images.asset(path)
    if any(sum(r['split']==p for r in rows)!=protocol['phase_counts'][p] for p in ('development','confirmation')):
        raise ValueError('Phase plan changed')
    out.mkdir(mode=0o700,parents=True,exist_ok=False)
    data=dict(schema='jev.question_ab_frozen_v1',cap_usd=str(cap),reservation_usd=str(RESERVE),
              model=ab.MODEL,threshold=ab.THRESHOLD,manifest_sha256=ab.digest(manifest),labels_sha256=ab.digest(labels),
              protocol_sha256=sha(fixture/'protocol.json'),source_files=pins(),max_requests=len(rows)*2,
              approval_scope='Steve approved $1 total for this synthetic A/B evaluation',
              price_basis='Configured TypeSafe input-token rate, not an invoice. Fixed provider; no max_price field supported by this native protocol.',
              bound_basis='8M input tokens reserved per sequential request; stop immediately on unknown usage, failed send or exceeded reservation')
    write(out/'freeze.json',data,True)
    return data

def verify(fixture,out):
    fixture=Path(fixture).resolve();out=Path(out)
    frozen=json.loads((out/'freeze.json').read_text())
    if frozen['source_files']!=pins():raise ValueError('Collector/source/test pins changed')
    m=json.loads((fixture/'manifest.json').read_text());l=json.loads((fixture/'labels.json').read_text())
    if ab.digest(m)!=frozen['manifest_sha256'] or ab.digest(l)!=frozen['labels_sha256'] or sha(fixture/'protocol.json')!=frozen['protocol_sha256']:
        raise ValueError('Corpus/protocol changed')
    for row in m['rows']:
        path=(fixture/row['image']).resolve()
        if not path.is_relative_to(fixture) or sha(path)!=row['sha256']:raise ValueError('Image changed')
    return frozen,m,l

def single_post(out,identity):
    def send(body,headers,timeout):
        data=json.loads(body)
        if data.get('model')!=ab.MODEL or len(body)>65536:raise ValueError('Unapproved payload')
        target=urlsplit(client.ENDPOINT)
        if target.scheme!='https' or target.hostname!='api.typesafe.ai' or target.port not in (None,443):raise ValueError('Unapproved endpoint')
        connection=http.client.HTTPSConnection('api.typesafe.ai',443,timeout=timeout)
        try:
            connection.request('POST',target.path,body=body,headers=headers)
            response=connection.getresponse();raw=response.read(client.MAX_RESPONSE_BYTES+1)
            if len(raw)>client.MAX_RESPONSE_BYTES:raise client.JevError('response_too_large')
            if response.status!=200:
                error=Path(out)/'errors'/(identity+'.json')
                write(error,{'status':response.status,'body_sha256':hashlib.sha256(raw).hexdigest(),'body':raw.decode('utf-8','replace')},True)
                raise client.JevError('auth_failed' if response.status in (401,403) else 'http_'+str(response.status))
            return raw
        finally:connection.close()
    return send

def run(fixture,out,ask=None):
    fixture=Path(fixture).resolve();out=Path(out)
    frozen,manifest,labels=verify(fixture,out)
    if (out/'receipt.json').exists() or list((out/'attempts').glob('*.json')):raise ValueError('Refuse resend/resume under this approval')
    if os.environ.get('TYPESAFE_BASE_URL','').strip().rstrip('/') not in ('','https://api.typesafe.ai'):raise ValueError('Endpoint override refused')
    cap=Decimal(frozen['cap_usd']);known=Decimal(0);upper=Decimal(0);all_records=[];phases=[];stop=None
    rehearsal=ask is not None;invoke=ask or usage.ask
    receipt={}
    started=time.monotonic()
    for phase in ('development','confirmation'):
        phase_records=[]
        for index,row in enumerate(r for r in manifest['rows'] if r['split']==phase):
            for arm in (('A','B') if index%2==0 else ('B','A')):
                if known+RESERVE>cap:stop='cap_reservation';break
                identity=hashlib.sha256((row['id']+':'+arm).encode()).hexdigest()[:24]
                attempt=out/'attempts'/(identity+'.json')
                write(attempt,dict(id=row['id'],arm=arm,reservation_usd=str(RESERVE),status='attempted'),True)
                before=known;upper=known+RESERVE
                record=dict(id=row['id'],arm=arm,frame_sha256=row['sha256'],requirements_sha256=ab.digest(row['requirements']),
                            question_sha256=ab.digest(ab.questions(arm)),status='unknown_failure',reservation_usd=str(RESERVE))
                t=time.monotonic()
                try:
                    ref,picture=images.asset((fixture/row['image']).read_bytes())
                    reply=invoke('video_qa_ab',ab.parts(row,ref),ab.questions(arm),assets={ref:picture},
                                 provider='typesafe',model=ab.MODEL,timeout=10,retries=0,transport=single_post(out,identity))
                    count=reply.get('input_tokens')
                    if type(count) is not int or not 0<=count<=RESERVE_TOKENS:raise ValueError('Unknown/out-of-reservation usage')
                    record.update(input_tokens=count,returned_model=reply.get('jev_model'))
                    if reply.get('jev_model')!=ab.MODEL:raise ValueError('Model substitution')
                    known+=count*RATE;upper=known
                    ab.clear(reply['answers'],arm)
                    record.update(status='ok',returned_model=reply['jev_model'],input_tokens=count,answers=reply['answers'])
                except Exception as exc:
                    upper=before+RESERVE
                    record['error']=getattr(exc,'code',type(exc).__name__);stop='failed_or_unknown_attempt'
                record['wall_ms']=round((time.monotonic()-t)*1000,3)
                all_records.append(record);phase_records.append(record)
                write(out/'results'/(identity+'.json'),record,True)
                receipt=dict(schema='jev.question_ab_run_v1',collection_mode='offline_rehearsal' if rehearsal else 'live',
                    model=ab.MODEL,threshold=ab.THRESHOLD,cap_usd=str(cap),known_rate_estimate_usd=str(known),
                    conservative_bound_usd=str(upper),billing_verified=False,records=all_records,phases=phases,stop_reason=stop,
                    elapsed_s=round(time.monotonic()-started,3),auto_promote=False)
                write(out/'receipt.json',receipt)
                if stop:break
            if stop:break
        if stop:break
        phase_receipt=dict(manifest_sha256=ab.digest(manifest),labels_sha256=ab.digest(labels),model=ab.MODEL,
                           threshold=ab.THRESHOLD,phase=phase,records=phase_records,development_passed=phase=='confirmation')
        scored:dict=ab.score(manifest,labels,phase_receipt);phases.append(scored)
        if phase=='development' and (scored['arms']['B']['unsafe_clears'] or not scored['arms']['B']['clean_clears']):
            stop='development_did_not_qualify';break
    receipt.update(phases=phases,stop_reason=stop,elapsed_s=round(time.monotonic()-started,3))
    write(out/'receipt.json',receipt)
    return receipt


def audit(fixture,out):
    frozen,manifest,labels=verify(fixture,out)
    out=Path(out);attempts={p.stem:json.loads(p.read_text()) for p in (out/'attempts').glob('*.json')}
    results={p.stem:json.loads(p.read_text()) for p in (out/'results').glob('*.json')}
    if not set(results)<=set(attempts):raise ValueError('Result without attempt')
    allowed={(r['id'],a) for r in manifest['rows'] for a in ('A','B')}
    known=Decimal(0);upper=Decimal(0);unknown=0
    for identity,a in attempts.items():
        if (a['id'],a['arm']) not in allowed or Decimal(a['reservation_usd'])!=RESERVE:raise ValueError('Invalid attempt reservation')
        r=results.get(identity,{})
        count=r.get('input_tokens')
        valid=type(count) is int and 0<=count<=RESERVE_TOKENS and r.get('returned_model')==ab.MODEL
        if valid:known+=count*RATE
        if r.get('status')=='ok' and valid:upper+=count*RATE
        else:unknown+=1;upper+=RESERVE
    if upper>Decimal(frozen['cap_usd']):raise ValueError('Conservative bound exceeds approval')
    return dict(attempts=len(attempts),successful=len(attempts)-unknown,unknown_failures=unknown,
                planned=frozen['max_requests'],not_attempted=frozen['max_requests']-len(attempts),
                known_rate_estimate_usd=str(known),conservative_bound_usd=str(upper),billing_verified=False,
                freeze_sha256=sha(out/'freeze.json'),receipt_sha256=sha(out/'receipt.json') if (out/'receipt.json').exists() else None)
