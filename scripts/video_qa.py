#!/usr/bin/env python3
"""Default video-QA triage. Local/public/synthetic authorization lives in JOB.json.

No global vision switch. A zero exit is screening completion, never video acceptance.
Exit 3 means use local/visual fallback; exit 2 is an invalid job/error.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jevkit import video_qa,images


def run(path,out,local_only=False):
    path=Path(path).resolve(); out=Path(out)
    attempts=out.with_suffix('.attempts.jsonl')
    if out.exists() or attempts.exists():
        raise ValueError('Existing receipt/journal: do not replay the job automatically')
    if path.stat().st_size>8*1024*1024:
        raise ValueError('Job manifest too large')
    job=json.loads(path.read_text(encoding='utf-8'))
    if local_only: job['cloud_policy']='local_only'
    video_qa.validate(job)
    def reader(frame):
        p=(path.parent/frame['image']).resolve()
        if not p.is_relative_to(path.parent) or not p.is_file() or p.stat().st_size>images.MAX_FILE_BYTES:
            raise ValueError('Invalid local frame')
        return p.read_bytes()
    out.parent.mkdir(parents=True,exist_ok=True)
    def journal(frame):
        with attempts.open('a',encoding='utf-8') as h:
            h.write(json.dumps({'id':frame['id'],'attempted':True})+'\n')
            h.flush(); os.fsync(h.fileno())
    result=video_qa.screen(job,reader=reader,on_attempt=journal)
    result['job_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    result['implementation_sha256']=hashlib.sha256(Path(video_qa.__file__).read_bytes()).hexdigest()
    out.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('job',type=Path); p.add_argument('--out',type=Path,required=True)
    p.add_argument('--local-only',action='store_true')
    a=p.parse_args()
    try:
        r=run(a.job,a.out,a.local_only)
        print(json.dumps({k:v for k,v in r.items() if k!='frames'},indent=2))
        return 0 if r['screening_complete'] else 3
    except (ValueError,OSError) as e:
        print(json.dumps({'screening_complete':False,'final_acceptance':False,'error':str(e)}))
        return 2

if __name__=='__main__': raise SystemExit(main())
