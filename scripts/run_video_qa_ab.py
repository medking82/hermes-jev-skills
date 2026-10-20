#!/usr/bin/env python3
"""Owner-approved synthetic Jev A/B: freeze, collect once, or audit without network."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jevkit import video_qa_ab_run as run
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('action',choices=['freeze','run','audit']);p.add_argument('fixture',type=Path);p.add_argument('out',type=Path)
p.add_argument('--cap',type=float,default=1)
a=p.parse_args()
if a.action=='freeze':result=run.freeze(a.fixture,a.out,a.cap)
elif a.action=='run':result=run.run(a.fixture,a.out)
else:result=run.audit(a.fixture,a.out)
print(json.dumps(result,indent=2))
