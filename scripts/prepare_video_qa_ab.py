#!/usr/bin/env python3
"""Prepare an original frozen A/B fixture offline. This script has no inference runner."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jevkit import video_qa_ab as ab


def prepare(root,sans,serif):
    from PIL import Image,ImageDraw,ImageFont
    root=Path(root).resolve()
    if root.exists():raise ValueError('Refuse existing experiment directory')
    root.mkdir(parents=True,mode=0o700);(root/'frames').mkdir()
    rows=[];labels={};kinds={}
    for phase,seed,title in [('development',73109,'A clearer plan'),('confirmation',96231,'Work with intent')]:
        rng=random.Random(seed)
        cases=['clean']*6+['tiny','tiny','clipped','clipped','overlap','missing']
        rng.shuffle(cases)
        for number,kind in enumerate(cases):
            identity=('d' if phase=='development' else 'c')+str(number).zfill(2)
            dark=number%2==0;bg='#102c36' if dark else '#f3eadc';fg='#fbfaf4' if dark else '#142a32'
            button=['#f19b45','#c95062','#5ec9b4'][number%3]
            im=Image.new('RGB',(640,360),bg);draw=ImageDraw.Draw(im)
            x=36+rng.randrange(9);y=38+rng.randrange(7)
            for i in range(4):
                xx=50+i*135;draw.rounded_rectangle((xx,140,xx+100,215+rng.randrange(20)),8,fill=button)
            font=ImageFont.truetype(str(sans if number%2 else serif),6 if kind=='tiny' else 26)
            if kind=='clipped':x=610
            box=draw.textbbox((x,y),title,font=font)
            if kind=='clean' and not (0<=box[0]<box[2]<=640 and 0<=box[1]<box[3]<=360):
                raise ValueError('Clean fixture heading unexpectedly clipped')
            draw.text((x,y),title,font=font,fill=fg)
            if kind=='overlap':
                draw.rectangle((x+30,y+5,x+200,y+24),fill=button)
                draw.text((x+30,y+2),'OVERLAY',font=ImageFont.truetype(str(sans),24),fill=fg)
            if kind!='missing':
                draw.rounded_rectangle((36,270,166,322),10,fill=button)
                draw.text((64,282),'Next',font=ImageFont.truetype(str(sans),22),fill='#10212c')
            image=Path('frames')/(identity+'.png');im.save(root/image)
            rows.append(dict(id=identity,image=str(image),sha256=hashlib.sha256((root/image).read_bytes()).hexdigest(),
                             split=phase,requirements=dict(required_text=[title,'Next'],
                             required_elements=['a visible colored button labelled Next'],palette=[bg,button],
                             allow_blank=False,allow_overlap=False)))
            labels[identity]='clean' if kind=='clean' else 'defect';kinds[identity]=kind
    manifest=dict(schema='jev.video_qa_ab_fixture_v1',synthetic=True,rows=rows)
    protocol=dict(status='prepared_not_run',inference_calls=0,model=ab.MODEL,threshold=ab.THRESHOLD,
        manifest_sha256=ab.digest(manifest),labels_sha256=ab.digest(labels),
        arm_question_sha256={a:ab.digest(ab.questions(a)) for a in ('A','B')},
        seeds=dict(development=73109,confirmation=96231),phase_counts=dict(development=12,confirmation=12),
        runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        font_sha256=[hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in (sans,serif)],
        ordering='Development first. Confirmation remains untouched if development has unsafe clears or no usable coverage.',
        acceptance='No automatic promotion. Compare unsafe clears, clean coverage, all fallback/review time, metered tokens and unknown sends. Small synthetic results cannot certify general videos.',
        limitation='Renderer-injected labels, not independently adjudicated natural footage. No paid cap or live executor is implied.')
    for name,data in [('manifest.json',manifest),('labels.json',labels),('injected-cases.json',kinds),('protocol.json',protocol),
        ('approval-template.json',dict(approved=False,max_usd=None,max_requests=None,max_input_tokens=None,authorization_ref=None))]:
        (root/name).write_text(json.dumps(data,indent=2)+'\n')
    return protocol


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('out',type=Path)
    p.add_argument('--sans',type=Path,required=True);p.add_argument('--serif',type=Path,required=True)
    a=p.parse_args();print(json.dumps(prepare(a.out,a.sans,a.serif),indent=2))

if __name__=='__main__':main()
