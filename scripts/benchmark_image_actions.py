#!/usr/bin/env python3
"""Opt-in synthetic native benchmark. Images go to TypeSafe only when this script is run.
No global vision switch is enabled. Only local fixture controls can be acted on.
"""
from __future__ import annotations
import argparse, hashlib, importlib.util, json, os, pathlib, statistics, subprocess, sys, time

ROOT=pathlib.Path(__file__).resolve().parents[1]
BUNDLE='ai.jev.synthetic-image-demo'
FLOOR=.65

def unwrap(reply):
 r=reply.get('result',{})
 if r.get('isError') or reply.get('error'): raise RuntimeError('Native tool refused: '+str(reply.get('error') or r)[:300])
 if isinstance(r.get('structuredContent'),dict):return r['structuredContent']
 for part in r.get('content',[]):
  if part.get('type')=='text':
   try:return json.loads(part['text'])
   except (ValueError,KeyError):pass
 return r

def safe_pick(pick, confidence, table):
 if not __import__('math').isfinite(confidence) or pick not in table or pick in ('reobserve','abstain') or confidence<FLOOR:return None
 return table[pick]

def summarize(rows):
 report={}
 for route in ('elements','image'):
  group=[r for r in rows if r['route']==route and r['task']!='visual']
  durations=sorted(r['decision_ms'] for r in group)
  report[route]={'decisions':len(group),'verified':sum(r['verified'] for r in group),
   'fallbacks':sum(r.get('fallback_used',False) for r in group),
   'median_with_fallback_ms':round(statistics.median(r.get('hybrid_decision_ms',r['decision_ms']) for r in group),1),
   'median_decision_ms':round(statistics.median(durations),1),'p95_decision_ms':round(durations[max(0,__import__('math').ceil(len(durations)*.95)-1)],1),
   'models':sorted(set(r['model'] for r in group))}
 return report

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=pathlib.Path,required=True);p.add_argument('--rounds',type=int,default=3);a=p.parse_args()
 assert 1<=a.rounds<=5
 out=a.output.resolve();out.mkdir(parents=True,exist_ok=True);os.chmod(out,0o700)
 # Exercise the actually installed Hermes modules, not an uninstalled source import.
 installed=pathlib.Path.home()/'.hermes/plugins/hermes-jev'
 sys.path.insert(0,str(installed));from jevkit import choose,client,images,switches,usage
 assert pathlib.Path(images.__file__).is_relative_to(installed)
 assert (ROOT/'jevkit/images.py').read_bytes()==pathlib.Path(images.__file__).read_bytes()
 os.environ['TYPESAFE_MODEL']='jev-1.14.0'  # scoped to this benchmark process only
 assert switches.mode('vision_cloud')=='off','Keep global screenshot forwarding off for this scoped test'
 sys.path.insert(0,str(ROOT/'skills/jev-computer-use/scripts'));import coagent_cu as cu;import jev_gui_agent as gui
 from PIL import Image
 assert cu.call_tool('computer_status',{}).get('ready')
 app=out/'JevImageDemo.app';(app/'Contents/MacOS').mkdir(parents=True,exist_ok=True)
 import plistlib
 (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':BUNDLE,'CFBundleName':'JevImageDemo','CFBundleExecutable':'JevImageDemo','CFBundlePackageType':'APPL','NSHighResolutionCapable':True}))
 binary=app/'Contents/MacOS/JevImageDemo';subprocess.run(['swiftc',str(ROOT/'tests/fixtures/JevImageDemo.swift'),'-o',str(binary)],check=True,timeout=90)
 proc=subprocess.Popen([str(binary),str(out)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 driver=None;recording=False;rows=[];video_bounds=None;started=None
 def state():return json.loads((out/'state.json').read_text())
 def banner(line):(out/'control.json').write_text(json.dumps({'line':line}))
 try:
  driver=gui.Driver(gui._find_driver())
  matches=[]
  for attempt in range(40):
   windows=unwrap(driver.tool('list_windows',{'pid':proc.pid})).get('windows',[])
   matches=[w for w in windows if w.get('title')=='Jev Image Demo Lab' and w.get('is_on_screen')]
   if matches:break
   time.sleep(.15)
  assert matches,'Owned fixture window unavailable'
  window=matches[0];wid=window['window_id'];video_bounds=window['bounds']
  active=cu.call_tool('computer_act',{'kind':'activate','bundle':BUNDLE})
  assert active.get('ok'),active
  def observe():
   o=cu.call_tool('computer_observe',{'bundle':BUNDLE})
   assert o.get('ok') and o.get('frontmost') and not o.get('blockers'),o
   return o
  def screenshot(name):
   raw=out/(name+'-native.png');answer=unwrap(driver.tool('get_window_state',{'pid':proc.pid,'window_id':wid,'include_accessibility_tree':False,'screenshot_out_file':str(raw)}))
   assert raw.exists(),str(answer)[:300]
   final=out/(name+'.png')
   with Image.open(raw) as im:
    im.thumbnail((1280,1280));im.convert('RGB').save(final)
   return final
  def step(route,roundno,task,goal,actions,expected):
   banner(route.upper()+'  |  choosing a safe action...');time.sleep(.12)
   o=observe();elems=o['elements'];table=dict(actions)
   options={key:val['description'] for key,val in table.items()}
   options.update(reobserve='Observe again without acting.',abstain='Stop: evidence insufficient.')
   candidates=[{'id':k,'description':v} for k,v in options.items()]
   image=screenshot(f'{roundno}-{route}-{task}') if route=='image' else None
   if route=='image':
    ref,pic=images.asset(image);payload={'goal':goal,'screen':ref}
    question=client.choice('Choose one prevalidated action ID using the visible screen and goal. Do not infer hidden state.',options)
    t=time.perf_counter();answer=usage.ask('image_action',payload,{'next_action':question},assets={ref:pic},model='jev-1.14.0',provider='typesafe',timeout=10,retries=0);ms=(time.perf_counter()-t)*1000
    verdict=answer['answers']['next_action'];pick=verdict['choice'];confidence=verdict['confidence'];model=answer.get('jev_model','unknown')
   else:
    request={'schema':choose.REQUEST_SCHEMA,'goal':goal,'observation_id':o['obs'],'regions':[{'id':e['id'],'role':e['role'],'label':e['label'],'interactive':not e.get('info',False)} for e in elems if e.get('label')][:100],'history':[],'candidates':candidates}
    t=time.perf_counter();answer=choose.choose(request,timeout=10,usage_feature='image_action');ms=(time.perf_counter()-t)*1000;pick=answer['selected_id'];confidence=answer['confidence'];model='jev-1.14.0'
   image_pick,image_confidence=pick,confidence
   fallback_ms=0.0;fallback_used=False
   if route=='image' and safe_pick(pick,confidence,table) is None and task!='visual':
    # Preserve the image confidence floor. Labels are an explicitly measured fallback.
    current=observe()
    request={'schema':choose.REQUEST_SCHEMA,'goal':goal,'observation_id':current['obs'],'regions':[{'id':e['id'],'role':e['role'],'label':e['label'],'interactive':not e.get('info',False)} for e in current['elements'] if e.get('label')][:100],'history':[],'candidates':candidates}
    t=time.perf_counter();fallback=choose.choose(request,timeout=10,usage_feature='image_action');fallback_ms=(time.perf_counter()-t)*1000
    pick=fallback['selected_id'];confidence=fallback['confidence'];fallback_used=True
   selected=safe_pick(pick,confidence,table);verified=False
   if selected is not None:
    # Reobserve after inference. Dispatch only the chosen prevalidated label/action.
    fresh=observe();matches=[e for e in fresh['elements'] if e.get('label')==selected['target']]
    assert len(matches)==1,'Ambiguous or vanished target'
    act={'kind':selected['kind'],'obs':fresh['obs'],'el':matches[0]['id'],'bundle':BUNDLE}
    if 'text' in selected:act.update(text=selected['text'],replace=True)
    result=cu.call_tool('computer_act',act)
    assert result.get('status') not in ('needs_approval','blocked','denied'),result
    end=time.monotonic()+3
    while time.monotonic()<end:
     if expected(state()):verified=True;break
     time.sleep(.05)
   elapsed=ms+fallback_ms
   banner(f'{route.upper()}  |  decision {elapsed:.0f} ms'+(' incl. labels fallback' if fallback_used else '')+'  |  '+('VERIFIED' if verified else 'ABSTAIN / UNVERIFIED'))
   row={'route':route,'round':roundno,'task':task,'decision_ms':round(ms,2),'choice':pick,'confidence':confidence,'model':model,'verified':verified,'image_choice':image_pick if route=='image' else None,'image_confidence':image_confidence if route=='image' else None,'fallback_used':fallback_used,'fallback_ms':round(fallback_ms,2),'hybrid_decision_ms':round(elapsed,2)}
   rows.append(row);(out/'rows.json').write_text(json.dumps(rows,indent=2));print(json.dumps(row),flush=True)
   return row
  for roundno in range(a.rounds):
   if roundno==a.rounds-1:
    rs=unwrap(driver.tool('get_recording_state',{}));assert not rs.get('enabled'),'Another owner is recording'
    rec=unwrap(driver.tool('start_recording',{'output_dir':str(out/'private-recording'),'record_video':True}));recording=True;started=time.monotonic();time.sleep(.5)
   for route in (('elements','image') if roundno%2==0 else ('image','elements')):
    (out/'control.json').write_text(json.dumps({'line':f'{route.upper()} | fresh fixture {roundno}','reset':'fresh-fixture'}))
    end=time.monotonic()+3
    while time.monotonic()<end and (state()['selected']!='None' or state()['note']!=''):
     time.sleep(.1)
    time.sleep(.2)
    assert state()['selected']=='None' and state()['note']=='' and state()['preview'] is False
    step(route,roundno,'workspace','Select the Rocket workspace.',[
     ('orbit',{'description':'Click Orbit workspace','target':'Orbit','kind':'click'}),('garden',{'description':'Click Garden workspace','target':'Garden','kind':'click'}),('rocket',{'description':'Click Rocket workspace','target':'Rocket','kind':'click'})],lambda s:s['selected']=='Rocket')
    step(route,roundno,'type','Type LAUNCH READY into the Mission note field.',[
     ('note',{'description':'Type the supplied exact text into Mission note','target':'Mission note','kind':'type','text':'LAUNCH READY'}),('orbit',{'description':'Click Orbit workspace','target':'Orbit','kind':'click'})],lambda s:s['note']=='LAUNCH READY')
    step(route,roundno,'preview','Click Preview to check the prepared Rocket mission.',[
     ('preview',{'description':'Click Preview','target':'Preview','kind':'click'}),('orbit',{'description':'Click Orbit workspace','target':'Orbit','kind':'click'})],lambda s:s['preview'] is True)
  # Only pixels carry the colour evidence. A separate capability test, not a speed comparison.
  visual=step('image',a.rounds,'visual','Choose the TEAL visual tile. The buttons are marked A, B and C.',[(k,{'description':'Click visual tile '+k,'target':k,'kind':'click'}) for k in ['A','B','C']],lambda s:s['visual']=='B')
  time.sleep(1.2);final=screenshot('final-fixture')
  report={'schema':'jev.synthetic_native_image_comparison_v1','syntheticOnly':True,'installedHermesModules':True,'globalCloudSwitch':'off','summary':summarize(rows),'visualTealTileVerified':visual['verified'],'timingScope':'Wall-clock Jev decision call only; excludes observation, screenshot preparation and input execution. Same pinned model for both routes.','rounds':a.rounds,'recordingBounds':video_bounds,'recordedSeconds':round(time.monotonic()-started,2),'rows':rows}
  (out/'benchmark.json').write_text(json.dumps(report,indent=2))
  assert all(r['verified'] for r in rows),'An action was not independently verified; failed receipt retained'
  print(json.dumps({'summary':report['summary'],'visualVerified':visual['verified']}))
 finally:
  try:
   if driver and recording:
    stop=unwrap(driver.tool('stop_recording',{}));(out/'recording-stop.json').write_text(json.dumps(stop,indent=2))
  finally:
   if driver:driver.stop()
   proc.terminate()
   try:proc.wait(timeout=3)
   except subprocess.TimeoutExpired:proc.kill();proc.wait()
   (out/'cleanup.json').write_text(json.dumps({'fixtureStopped':proc.poll() is not None,'recordingStopRequested':recording}))
 return 0
if __name__=='__main__':raise SystemExit(main())
