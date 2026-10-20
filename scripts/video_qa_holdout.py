#!/usr/bin/env python3
"""Generate and optionally screen a fresh, multi-layout synthetic frame holdout.

Build with --ffmpeg and --sans/--serif font files. Run later with --run.
Only synthetic assets and ground truth are generated. Never use private footage here.
Optional generation dependencies: Pillow/numpy and a working FFmpeg.
"""
import argparse
import hashlib
import json
from pathlib import Path
import random
import re
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jevkit import video_qa

STYLES=[
 dict(name='studio',heading='Build with AI',button='Explore',bg='#102037',fg='#f8fbff',color='#28b4ad',font='sans',risk='routine'),
 dict(name='paper',heading='A better workflow',button='Continue',bg='#f8f1e7',fg='#182031',color='#d54255',font='serif',risk='routine'),
 dict(name='chart',heading='Weekly progress',button='View detail',bg='#f3f6fb',fg='#102544',color='#2f74c8',font='sans',risk='high'),
 dict(name='split',heading='Ideas into action',button='Try a demo',bg='#efe9fb',fg='#291e49',color='#8957cc',font='serif',risk='routine')]


def build(root,ffmpeg,sans,serif):
    from PIL import Image,ImageDraw,ImageFont
    import numpy as np
    root=Path(root)
    if root.exists(): raise ValueError('Use a fresh holdout directory')
    (root/'source').mkdir(parents=True); (root/'frames').mkdir()
    fonts={'sans':sans,'serif':serif}; labels=[]; groups=[]; source=[]
    rng=random.Random(481510)
    for style in STYLES:
        kinds=['clean']*4+['clipped','overlap','missing','tiny']; rng.shuffle(kinds)
        ids=[]
        for kind in kinds:
            i=len(labels); ids.append(i); im=Image.new('RGB',(800,450),style['bg']); d=ImageDraw.Draw(im)
            heading=ImageFont.truetype(fonts[style['font']],6 if kind=='tiny' else 36)
            body=ImageFont.truetype(sans,21); button_font=ImageFont.truetype(sans,24)
            x=54 if kind!='clipped' else 720
            if style['name']=='chart':
                for n,h in enumerate([35,70,48,92]):
                    d.rectangle((490+n*50,335-h,520+n*50,335),fill=style['color'])
            elif style['name']=='split':
                d.ellipse((500,160,740,400),fill='#d9c7f7')
            else:
                d.rounded_rectangle((28,28,772,422),radius=18,outline='#8290a5',width=2)
            d.text((x,68),style['heading'],font=heading,fill=style['fg'])
            d.text((54,160),'A practical idea, made visible.',font=body,fill=style['fg'])
            if kind=='overlap':
                d.text((85,80),'LAYER COLLISION',font=ImageFont.truetype(sans,40),fill=style['fg'])
            if kind!='missing':
                d.rounded_rectangle((54,270,300,336),radius=12,fill=style['color'])
                d.text((72,286),style['button'],font=button_font,fill='#ffffff')
            # Tiny deterministic decor differentiates clean frames without labels.
            d.ellipse((730-i%5*3,40,742-i%5*3,52),fill=style['color'])
            im.save(root/'source'/f'{i:03}.png'); source.append(im)
            labels.append(dict(id=f'h{i:02}',kind=kind,label='clean' if kind=='clean' else 'defect',style=style['name']))
        groups.append(dict(style=style,indices=ids))
    i=len(labels); im=Image.new('RGB',(800,450),'#142336'); im.save(root/'source'/f'{i:03}.png')
    labels.append(dict(id=f'h{i:02}',kind='intentional_blank',label='clean',style='blank')); source.append(im)
    cmd=[ffmpeg,'-v','error','-nostdin','-y','-framerate','2','-i',str(root/'source/%03d.png'),
         '-c:v','libx264','-pix_fmt','yuv420p','-crf','18','-colorspace','bt709',
         '-color_primaries','bt709','-color_trc','bt709',str(root/'holdout.mp4')]
    subprocess.run(cmd,check=True,timeout=90,capture_output=True)
    decoded=subprocess.run([ffmpeg,'-hide_banner','-nostdin','-i',str(root/'holdout.mp4'),'-vf','showinfo',
         '-fps_mode','passthrough','-start_number','0',str(root/'frames/%03d.png')],check=True,timeout=60,capture_output=True)
    log=decoded.stderr.decode(errors='replace')
    times=[float(v) for v in re.findall(r'Parsed_showinfo[^\n]* n:\s*\d+ pts:\s*-?\d+ pts_time:([-+\d.eE]+)',log)]
    assert len(times)==len(labels) and all(abs(t-n/2)<1e-6 for n,t in enumerate(times))
    assert 'Duration: 00:00:16.50' in log
    media_sha=hashlib.sha256((root/'holdout.mp4').read_bytes()).hexdigest()
    def frame(n,scene):
        p=root/'frames'/f'{n:03}.png'
        with Image.open(p) as image: assert image.size==(800,450)
        return dict(id=labels[n]['id'],image=f'frames/{n:03}.png',sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
                    local='pass',scene=scene,transition=False)
    jobs=[]
    for group in groups:
        s=group['style']; name=s['name']+'.json'; jobs.append(name)
        job=dict(schema='jev.video_qa_v1',cloud_policy='authorized_synthetic',review_risk=s['risk'],
          source_sha256=media_sha,local_checks={k:('not_applicable' if k=='audio' else 'pass') for k in video_qa.LOCAL_CHECKS},
          requirements=dict(required_text=[s['heading'],s['button']],required_elements=['a button labelled '+s['button']],
                            palette=[s['color'],s['bg']],allow_blank=False,allow_overlap=False),
          frames=[frame(n,s['name']) for n in group['indices']])
        (root/name).write_text(json.dumps(job,indent=2)+'\n')
    blank=dict(schema='jev.video_qa_v1',cloud_policy='authorized_synthetic',review_risk='routine',source_sha256=media_sha,
          local_checks={k:('not_applicable' if k=='audio' else 'pass') for k in video_qa.LOCAL_CHECKS},
          requirements=dict(required_text=[],required_elements=[],palette=['#142336'],allow_blank=True,allow_overlap=False),
          frames=[frame(len(labels)-1,'blank')])
    (root/'blank.json').write_text(json.dumps(blank,indent=2)+'\n'); jobs.append('blank.json')
    (root/'truth.json').write_text(json.dumps(dict(rows=labels,jobs=jobs,source_sha256=media_sha,
                                                frames=len(times),duration=16.5,fps=2),indent=2)+'\n')
    # Labels appear only on this local inspection sheet, never on uploaded frames.
    sheet=Image.new('RGB',(1280,9*204),'#202020'); draw=ImageDraw.Draw(sheet); font=ImageFont.truetype(sans,15)
    for n,label in enumerate(labels):
        with Image.open(root/'frames'/f'{n:03}.png') as image: sheet.paste(image.resize((320,180)),((n%4)*320,(n//4)*204))
        draw.text(((n%4)*320+5,(n//4)*204+183),label['id']+' '+label['style']+' '+label['kind'],font=font,fill='white')
    sheet.save(root/'labelled-sheet.png')
    print(json.dumps({'built':len(labels),'jobs':len(jobs),'source_sha256':media_sha}))


def run(root):
    from scripts.video_qa import run as screen_job
    root=Path(root); truth=json.loads((root/'truth.json').read_text())
    reports=[]
    for job in truth['jobs']:
        reports.append(screen_job(root/job,root/(Path(job).stem+'-receipt.json')))
    rows=[r for report in reports for r in report['frames']]; byid={r['id']:r for r in rows}
    defects=[r for r in truth['rows'] if r['label']=='defect']; clean=[r for r in truth['rows'] if r['label']=='clean']
    result=dict(frames=len(rows),defects=len(defects),clean=len(clean),
        raw_clear_misses=[r['id'] for r in defects if byid[r['id']].get('choice')=='clear'],
        candidate_clear_misses=[r['id'] for r in defects if byid[r['id']]['decision']=='candidate_clear'],
        routed_or_audited_misses=[r['id'] for r in defects if byid[r['id']]['decision']=='candidate_clear' and not byid[r['id']]['audit_required']],
        clean_flagged=[r['id'] for r in clean if byid[r['id']].get('choice')=='flag'],
        clean_referred=[r['id'] for r in clean if byid[r['id']]['decision']=='review'],
        model_calls=sum(r['model_calls'] for r in reports),input_tokens=sum(r['input_tokens'] for r in reports),
        wall_seconds=round(sum(r['wall_seconds'] for r in reports),3),
        estimated_list_usd=(sum(r['estimated_list_usd'] for r in reports)
                            if all(type(r['estimated_list_usd']) in (int,float) for r in reports) else None),
        audit_frames=sum(len(r['audit_ids']) for r in reports),
        limits=['Synthetic single-frame holdout, not a temporal or general-quality benchmark',
                'Flags and audits are routing, not completed review','No frontier time/cost comparison'])
    (root/'holdout-results.json').write_text(json.dumps(result,indent=2)+'\n'); print(json.dumps(result,indent=2))


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('out',type=Path)
    p.add_argument('--run',action='store_true'); p.add_argument('--ffmpeg'); p.add_argument('--sans'); p.add_argument('--serif')
    a=p.parse_args()
    if a.run: run(a.out)
    else:
        if not all((a.ffmpeg,a.sans,a.serif)): p.error('Build requires --ffmpeg --sans --serif')
        build(a.out,a.ffmpeg,a.sans,a.serif)
if __name__=='__main__': main()
