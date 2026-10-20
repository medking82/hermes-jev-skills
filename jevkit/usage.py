"""Hash-only write-ahead usage for authorized standalone helpers, never an action/consent gate."""
from __future__ import annotations
import hashlib
import json
import re
import time
import uuid
from . import client,ledger

FEATURES=frozenset(('video_qa','video_qa_trial','image_action','blender_advice','video_qa_ab'))

def _model(value):
    return value if isinstance(value,str) and re.fullmatch(r'(?:typesafe/)?jev[-A-Za-z0-9_.]{1,60}',value) else None

def ask(feature,state,questions,**kwargs):
    """One client invocation, no extra retries. Caller retains privacy, deadlines and consent.

    Write intent before invoking the client. A crash/timeout does not prove no send.
    Feature retries must be disabled so one invocation cannot hide multiple HTTP tries.
    Explicit JEV_LEDGER=off is honored. Never log state, assets, exception text or keys.
    """
    if feature not in FEATURES:
        raise ValueError('Unknown metered standalone feature')
    if kwargs.get('retries',0)!=0:
        raise ValueError('Metered standalone helpers require retries=0')
    kwargs['retries']=0
    enabled=ledger.enabled()
    identity=uuid.uuid4().hex
    base=dict(feature=feature,mode='live',source='jev',shadow=False,
              attempt_id=identity,n_questions=len(questions),
              question_sha256=hashlib.sha256(json.dumps(questions,sort_keys=True).encode()).hexdigest(),
              jev_model=_model(kwargs.get('model')),cost_basis='configured_list_estimate_not_invoice')
    if enabled:
        ledger.append({**base,'usage_event':'attempt','status':'pending','send_state':'unknown'},durable=True,strict=True)
    started=time.monotonic()
    try:
        out=client.ask(state,questions,**kwargs)
    except BaseException as exc:
        if enabled:
            ledger.append({**base,'usage_event':'result','status':'error','send_state':'unknown',
                           'input_tokens':None,'cost_usd':None,'list_usd':None,
                           'error':type(exc).__name__,'latency_ms':(time.monotonic()-started)*1000},durable=True)
        raise
    count=out.get('input_tokens')
    count=count if type(count) is int and count>=0 else None
    provider=out.get('provider')
    if provider not in ('typesafe','openrouter','venice','zen'): provider=None
    model=_model(out.get('jev_model'))
    estimate=ledger.cost(count,provider,model) if count is not None else {'cost_usd':None,'list_usd':None}
    if enabled:
        ledger.append({**base,**estimate,'usage_event':'result','status':'ok','send_state':'reply_received',
                       'provider':provider,'jev_model':model,'input_tokens':count,
                       'latency_ms':(time.monotonic()-started)*1000},durable=True,strict=True)
    return out
