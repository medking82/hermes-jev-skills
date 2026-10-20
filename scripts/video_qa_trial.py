#!/usr/bin/env python3
"""Opt-in synthetic video-frame Jev experiment, NOT a production QA gate.

Labels remain local. Pictures explicitly leave the machine for TypeSafe only.
Needs an already-reviewed, synthetic fixture manifest; no arbitrary footage.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jevkit import client, images, ledger, usage

THRESHOLD=.9
MODEL='jev-1.14.0'
QUESTION=("Inspect the image `frame` as a motion-graphics quality-control frame. "
          "The required main heading is 'A clear next step' and the required button label is 'Start'. "
          "Both must be present, easily readable, fully inside the image, and not obscured by any other text or shape. "
          "The button must be orange, not red; the normal background is dark navy. "
          "Flag an empty image, missing required heading or button, clipped/overlapping text, "
          "unreadably tiny text, or a wrong red button. Ignore decorative dots and normal margins. "
          "Choose clear only when all these requirements visibly hold; choose uncertain when not sure.")


def request_parts(ref):
    return {'frame':ref}, {'verdict':client.choice(QUESTION,{
        'clear':'All specified visible checks pass.',
        'flag':'At least one specified visible check fails.',
        'uncertain':'Insufficient evidence; refer for visual review.'})}


def route(choice, confidence, code_flag):
    if (code_flag is False and choice=='clear' and isinstance(confidence,(int,float))
            and not isinstance(confidence,bool) and math.isfinite(confidence)
            and THRESHOLD<=confidence<=1):
        return 'candidate_clear'
    return 'review'


def metrics(rows):
    defects=[r for r in rows if r['label']=='defect']; clean=[r for r in rows if r['label']=='clean']
    misses=sum(r['decision']=='candidate_clear' for r in defects)
    return dict(frames=len(rows),defects=len(defects),clean=len(clean),missed_defects=misses,
                defect_recall=(len(defects)-misses)/len(defects) if defects else None,
                clean_frames_escalated=sum(r['decision']=='review' for r in clean),
                candidate_clear=sum(r['decision']=='candidate_clear' for r in rows),
                review_queue=sum(r['decision']=='review' for r in rows))


def validate_data(data):
    if (not isinstance(data,dict) or data.get('synthetic') is not True
            or not isinstance(data.get('rows'),list) or not 1<=len(data['rows'])<=32):
        raise ValueError('Requires 1..32 explicitly synthetic fixture rows')
    seen=set()
    for row in data['rows']:
        if (not isinstance(row,dict) or not isinstance(row.get('id'),str) or row['id'] in seen or row.get('label') not in ('clean','defect')
                or type(row.get('code_flag')) is not bool or not isinstance(row.get('image'),str)
                or not isinstance(row.get('sha256'),str) or len(row['sha256'])!=64):
            raise ValueError('Invalid or duplicate fixture row')
        seen.add(row['id'])
    return data


def validate_manifest(path, consent):
    if consent is not True:
        raise ValueError('Explicit synthetic-image upload consent is required before reading assets')
    path=Path(path).resolve()
    data=validate_data(json.loads(path.read_text()))
    for row in data['rows']:
        image=(path.parent/row['image']).resolve()
        if not image.is_relative_to(path.parent):
            raise ValueError('Fixture asset escapes its reviewed root')
        if hashlib.sha256(image.read_bytes()).hexdigest()!=row['sha256']:
            raise ValueError('Fixture image changed after labelling')
        images.asset(image)  # Validate every image before making ANY call.
    return data


def run(manifest, output, consent=False, timeout_s=120) -> dict:
    if os.environ.get('TYPESAFE_BASE_URL','').strip().rstrip('/') not in ('','https://api.typesafe.ai'):
        raise ValueError('This trial is restricted to the official TypeSafe endpoint')
    path=Path(manifest).resolve(); data=validate_manifest(path,consent)
    output=Path(output); progress=output.with_suffix('.rows.jsonl')
    attempts_path=output.with_suffix('.attempts.jsonl')
    if output.exists() or progress.exists() or attempts_path.exists():
        raise ValueError('Refuse to overwrite an earlier trial; use a fresh output name')
    output.parent.mkdir(parents=True,exist_ok=True)
    started=time.monotonic(); results=[]; tokens=0; errors=0; attempts=0
    for row in data['rows']:
        result: dict=dict(id=row['id'],label=row['label'],code_flag=row['code_flag'],decision='review')
        remaining=timeout_s-(time.monotonic()-started)
        if remaining<=.5 or tokens>=100000 or errors>=3:
            result['status']='budget_exhausted'
        else:
            asset=(path.parent/row['image']).read_bytes()
            if hashlib.sha256(asset).hexdigest()!=row['sha256']:
                raise ValueError('Fixture image changed before send')
            ref,picture=images.asset(asset)
            with attempts_path.open('a',encoding='utf-8') as handle:
                handle.write(json.dumps({'id':row['id'],'attempted':True})+'\n')
                handle.flush(); os.fsync(handle.fileno())
            t=time.monotonic(); attempts+=1
            try:
                state,questions=request_parts(ref)
                out=usage.ask('video_qa_trial',state,questions,
                    assets={ref:picture},provider='typesafe',model=MODEL,
                    timeout=min(10,remaining),retries=0)
                verdict=out['answers']['verdict']; count=out.get('input_tokens')
                result.update(status='ok',choice=verdict['choice'],confidence=verdict['confidence'],
                              input_tokens=count,jev_model=out.get('jev_model'))
                if count is None:
                    errors=3; result['status']='usage_unavailable'
                else: tokens+=count
                if out.get('jev_model')==MODEL:
                    if result['status']=='ok':
                        result['decision']=route(verdict['choice'],verdict['confidence'],row['code_flag'])
                else:
                    result['status']='model_mismatch'; errors+=1
            except (client.JevError,images.ImageError) as error:
                result.update(status='error',error=error.code); errors+=1
            result['wall_ms']=round((time.monotonic()-t)*1000,3)
        results.append(result)
        with progress.open('a',encoding='utf-8') as handle:
            handle.write(json.dumps(result)+'\n')
    code=[dict(r,decision='review' if r['code_flag'] else 'candidate_clear') for r in results]
    selective=[dict(r,decision='review' if r['code_flag'] or i%6==0 else 'candidate_clear')
               for i,r in enumerate(results)]
    latencies=[r['wall_ms'] for r in results if 'wall_ms' in r]
    report=dict(schema='jev.synthetic_video_trial_v1',model=MODEL,threshold=THRESHOLD,
                runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                manifest_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                question_sha256=hashlib.sha256(QUESTION.encode()).hexdigest(),
                total_wall_seconds=round(time.monotonic()-started,3),attempted_calls=attempts,
                successful_calls=sum(r['status']=='ok' for r in results),input_tokens=tokens,
                latency_median_ms=statistics.median(latencies) if latencies else None,
                estimated_list_usd=round(tokens*ledger.USD_PER_INPUT_TOKEN,8),
                estimate_basis='Repository configured input-token list rate, not an invoice or live-price guarantee',
                code_only=metrics(code),code_plus_every_sixth_frame_review_queue=metrics(selective),
                hybrid=metrics(results),results=results,
                limits=['Synthetic still-frame set only, not temporal or artistic QA',
                        'Candidate clear is advisory, not delivery authorization',
                        'Review-queue coverage assumes an eventual reviewer catches queued defects',
                        'No frontier cost, time savings or production accuracy measured'])
    output.write_text(json.dumps(report,indent=2)+'\n')
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('manifest',type=Path); p.add_argument('--out',type=Path,required=True)
    p.add_argument('--allow-synthetic-upload',action='store_true')
    a=p.parse_args(argv)
    try: report=run(a.manifest,a.out,a.allow_synthetic_upload)
    except (OSError,ValueError) as error:
        print(json.dumps(dict(error=str(error),production_gate=False))); return 2
    print(json.dumps({k:v for k,v in report.items() if k!='results'},indent=2))
    return 0 if report['successful_calls']==len(report['results']) else 1


if __name__=='__main__': raise SystemExit(main())
