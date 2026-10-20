#!/usr/bin/env python3
"""Create an original synthetic 18-frame test video, decode it and freeze labels.

Optional test dependencies: Pillow, numpy, a working FFmpeg. No network or installs.
This is a diagnostic fixture, not a film-production renderer or a quality benchmark.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import random
import subprocess
import time


def build(root,ffmpeg,font_path):
    from PIL import Image,ImageDraw,ImageFont
    import numpy as np
    root=Path(root).resolve()
    root.mkdir(parents=True,exist_ok=False)
    source=root/'source'; frames=root/'frames'; source.mkdir(); frames.mkdir()
    cases=['clean']*6+['blank','missing','clipped','overlap','red','tiny']*2
    random.Random(20261019).shuffle(cases)
    label_font=ImageFont.truetype(font_path,34)
    button_font=ImageFont.truetype(font_path,24)
    caption=ImageFont.truetype(font_path,15)
    for i,case in enumerate(cases):
        bg=(15+i%3,27+i%4,44+i%5)
        im=Image.new('RGB',(640,360),bg); d=ImageDraw.Draw(im)
        if case!='blank':
            d.rounded_rectangle((30,30,610,330),radius=24,outline='#345273',width=2)
            d.text((48,43),'ILLUSTRATIVE WORKFLOW TEST',font=caption,fill='#9bb7d2')
            x=490 if case=='clipped' else 48+i%3*4
            f=ImageFont.truetype(font_path,6) if case=='tiny' else label_font
            d.text((x,95),'A clear next step',font=f,fill='#f8fbff')
            d.text((48,166),'Learn an idea. Try it. Build something.',font=caption,fill='#b6cbe0')
            if case=='overlap':
                d.text((110,106),'BUILD NOW',font=label_font,fill='#f8fbff')
            if case!='missing':
                d.rounded_rectangle((236,232,404,288),radius=12,fill='#f52836' if case=='red' else '#fc9943')
                d.text((292,245),'Start',font=button_font,fill='#101b2c')
            for j in range(3):
                d.ellipse((506+j*20,252,512+j*20,258),fill='#64d9bd')
        im.save(source/f'{i:03}.png')
    def command(args):
        subprocess.run([ffmpeg,'-nostdin','-v','error','-y']+args,check=True,timeout=60)
    command(['-framerate','2','-start_number','0','-i',str(source/'%03d.png'),
             '-c:v','libx264','-crf','16','-pix_fmt','yuv420p','-color_primaries','bt709',
             '-color_trc','bt709','-colorspace','bt709','-movflags','+faststart',str(root/'trial.mp4')])
    command(['-i',str(root/'trial.mp4'),'-fps_mode','passthrough','-start_number','0',str(frames/'%03d.png')])
    files=sorted(frames.glob('*.png')); assert len(files)==len(cases)==18
    code_started=time.monotonic(); rows=[]
    sheet=Image.new('RGB',(1280,1080))
    for i,(p,case) in enumerate(zip(files,cases)):
        im=Image.open(p).convert('RGB'); a=np.asarray(im).astype(float)
        blank=float(np.std(a.mean(axis=2)))<4
        red=float(((a[:,:,0]>180)&(a[:,:,1]<90)&(a[:,:,2]<100)).mean())>.01
        rows.append(dict(id=f'f{i:02}',image=str(p.relative_to(root)),
                         label='clean' if case=='clean' else 'defect',defect_case=case,
                         code_flag=blank or red,code_reasons=[x for x,b in [('blank',blank),('red_palette',red)] if b],
                         sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
        thumb=im.resize((320,180)); sheet.paste(thumb,((i%4)*320,(i//4)*216))
        d=ImageDraw.Draw(sheet); d.text(((i%4)*320+8,(i//4)*216+182),f'f{i:02} / {case}',font=caption,fill='white')
    sheet.save(root/'labelled-contact-sheet.png')
    manifest=dict(synthetic=True,generator='video_qa_fixture.py v1',rows=rows,
                  fixture_video_sha256=hashlib.sha256((root/'trial.mp4').read_bytes()).hexdigest(),
                  code_measurement_seconds=round(time.monotonic()-code_started,6),
                  frame_rate='2',frames=18,intentional_still_frames=True,
                  limits='Labels and names stay local. Per-frame semantic test; no temporal quality claim.')
    (root/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(dict(frames=len(rows),code_flags=sum(r['code_flag'] for r in rows),manifest=str(root/'manifest.json'))))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('out',type=Path); p.add_argument('--ffmpeg',required=True)
    p.add_argument('--font',required=True,help='A locally licensed TrueType/OpenType font; no fonts downloaded')
    a=p.parse_args(); build(a.out,a.ffmpeg,a.font)


if __name__=='__main__': main()
