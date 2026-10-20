"""What every policy decision cost and how long it took: one JSONL row per call, and a report.

The article's claim is economic — stop waking the most expensive brain for every small
decision — so the claim needs a meter. Each row holds numbers, ids and hashes only: never the
state, never a command, never a question's text.

Row fields: ``ts``, ``profile``, ``feature``, ``mode``, ``policy`` (name@version#sha),
``jev_model``, ``provider``, ``n_questions``, ``input_tokens``, ``cost_usd`` (legacy rate estimate, not an invoice),
``list_usd`` (what the same tokens cost at list price, so a free tier still shows its size),
``latency_ms``, ``status`` (ok / error / skipped / code), ``source`` (code / jev / fallback),
``error``, ``action``, ``fallback_used``,
``shadow``, ``drift``, ``queue_dropped`` and ``llm_avoided_est`` — an *estimate*, labelled
as one, of the frontier-model tokens a caller said this decision replaces.

``JEV_LEDGER=off`` turns writing off; ``JEV_LEDGER_PATH`` moves the file.
"""
from __future__ import annotations

import json
import math
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

# TypeSafe list price (Models page, read 2026-09-26): $0.042 per million input tokens,
# output free. The same figure mailbox.py and triage.py already use for their estimates.
USD_PER_INPUT_TOKEN = 0.042 / 1_000_000
FREE_MODELS = ("jev-1.13-free",)
FIELDS = ("ts", "profile", "feature", "mode", "policy", "jev_model", "provider", "n_questions",
          "input_tokens", "cost_usd", "list_usd", "latency_ms", "status", "error", "action",
          "fallback_used", "shadow", "drift", "queue_dropped", "llm_avoided_est", "source", "usage_event", "attempt_id", "send_state",
          "question_sha256", "cost_basis")


def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")


def profile() -> str:
    home = hermes_home()
    return home.name if home.parent.name == "profiles" else "default"


def path() -> Path:
    override = os.environ.get("JEV_LEDGER_PATH", "").strip()
    return Path(override).expanduser() if override else hermes_home() / "logs" / "jev-ledger.jsonl"


def enabled() -> bool:
    return os.environ.get("JEV_LEDGER", "").strip().lower() not in ("off", "0", "false", "no")


def cost(input_tokens: Optional[int], provider: Optional[str] = None,
         jev_model: Optional[str] = None) -> Dict[str, float]:
    """Configured-rate estimates, not verified billing; preserve legacy field names."""
    tokens = int(input_tokens or 0)
    listed = round(tokens * USD_PER_INPUT_TOKEN, 8)
    free = (jev_model or "") in FREE_MODELS or (provider == "zen" and (jev_model or "").endswith("-free"))
    return {"cost_usd": 0.0 if free else listed, "list_usd": listed}


def append(row: Mapping[str, Any], *, durable: bool = False, strict: bool = False) -> None:
    """Create 0600 rows; best-effort by default, strict durable write-ahead when requested."""
    if not enabled():
        return
    entry = {"ts": round(time.time(), 3), "profile": profile()}
    entry.update({key: row[key] for key in FIELDS if key in row and key not in ("ts",)})
    try:
        target = path()
        target.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, separators=(",", ":"), default=str) + "\n")
            if durable:
                handle.flush()
                os.fsync(handle.fileno())
    except OSError:
        if strict:
            raise


def logical_calls(rows):
    """Collapse write-ahead/terminal events; unresolved or contradictory calls stay unknown."""
    plain=[]; events={}
    for row in rows:
        if row.get('usage_event') not in ('attempt','result'):
            plain.append(row); continue
        identity=row.get('attempt_id')
        key=(row.get('profile'),identity)
        events.setdefault(key,[]).append(row)
    for items in events.values():
        starts=[r for r in items if r.get('usage_event')=='attempt']
        ends=[r for r in items if r.get('usage_event')=='result']
        if len(starts)==1 and len(ends)==1 and starts[0].get('feature')==ends[0].get('feature') and starts[0].get('question_sha256')==ends[0].get('question_sha256'):
            row={**starts[0],**ends[0]}
        else:
            row={**items[0], 'status':'unknown','send_state':'unknown','input_tokens':None,
                 'cost_usd':None,'list_usd':None,'error':'unresolved_attempt'}
        row['usage_event']='call'; plain.append(row)
    return plain


def read(source: Optional[Path] = None, since: Optional[float] = None, *, strict: bool = False) -> List[Dict[str, Any]]:
    target = source or path()
    rows: List[Dict[str, Any]] = []
    try:
        with open(target, encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    if strict:raise ValueError("Malformed usage ledger row") from None
                    continue
                if isinstance(row, dict):
                    rows.append(row)
                elif strict:raise ValueError("Non-object usage ledger row")
    except OSError:
        if strict:raise
        return []
    out=[]
    for row in logical_calls(rows):
        try:
            stamp=float(row.get('ts') or 0)
            if math.isfinite(stamp) and (since is None or stamp>=since): out.append(row)
        except (TypeError,ValueError):
            continue
    return out


def _percentile(values: List[float], q: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(math.ceil(q * len(ordered))) - 1))
    return ordered[index]


def summarize(rows: Iterable[Mapping[str, Any]], by_day: bool = True) -> Dict[str, Any]:
    """Per feature (and per day): calls, latency percentiles, error rate, dollars, drift, LLM avoided."""
    groups: Dict[Any, List[Mapping[str, Any]]] = defaultdict(list)
    for row in logical_calls(rows):
        day = time.strftime("%Y-%m-%d", time.localtime(float(row.get("ts") or 0))) if by_day else "all"
        groups[(str(row.get("feature") or "?"), day)].append(row)
    out = []
    for (feature, day), items in sorted(groups.items()):
        sent = [r for r in items if r.get("status") in ("ok", "error")]
        latencies = [float(r["latency_ms"]) for r in sent if isinstance(r.get("latency_ms"), (int, float))]
        errors = sum(1 for r in sent if r.get("status") == "error")
        out.append({
            "feature": feature, "day": day, "calls": len(items), "sent": len(sent),
            "unresolved_attempts": sum(r.get('status')=='unknown' for r in items),
            "usage_unknown": sum(r.get('input_tokens') is None for r in items),
            "estimated_cost_complete": all(r.get('cost_usd') is not None for r in items),
            "billed_cost_usd": None,
            "actual_llm_avoided_tokens": 0 if all(r.get('shadow') for r in items) else None,
            "skipped": sum(1 for r in items if r.get("status") == "skipped"),
            "decided_by_code": sum(1 for r in items if r.get("status") == "code"),
            "shadow": sum(1 for r in items if r.get("shadow")),
            "p50_ms": _percentile(latencies, 0.50), "p90_ms": _percentile(latencies, 0.90),
            "p99_ms": _percentile(latencies, 0.99),
            "error_rate": round(errors / len(sent), 4) if sent else None,
            "cost_usd": round(sum(float(r.get("cost_usd") or 0) for r in items), 6),
            "list_usd": round(sum(float(r.get("list_usd") or 0) for r in items), 6),
            "input_tokens": sum(int(r.get("input_tokens") or 0) for r in items),
            "drift": sum(1 for r in items if r.get("drift")),
            "fallback_used": sum(1 for r in items if r.get("fallback_used")),
            "queue_dropped": max([int(r.get("queue_dropped") or 0) for r in items] or [0]),
            "llm_avoided_est_tokens": sum(int(r.get("llm_avoided_est") or 0) for r in items),
            "counterfactual_llm_avoided_est_tokens": sum(int(r.get("llm_avoided_est") or 0) for r in items),
            "estimated_cost_usd": round(sum(float(r.get("cost_usd") or 0) for r in items), 6) if all(r.get("cost_usd") is not None for r in items) else None,
            "actions": dict(sorted(_count(r.get("action") for r in items).items())),
        })
    totals: Dict[str, Any] = {"calls": sum(g["calls"] for g in out), "cost_usd": round(sum(g["cost_usd"] for g in out), 6),
              "list_usd": round(sum(g["list_usd"] for g in out), 6),
              "llm_avoided_est_tokens": sum(g["llm_avoided_est_tokens"] for g in out)}
    totals.update(billed_cost_usd=None,
                  estimated_cost_usd=totals["cost_usd"] if all(g["estimated_cost_complete"] for g in out) else None,
                  counterfactual_llm_avoided_est_tokens=totals["llm_avoided_est_tokens"],
                  actual_llm_avoided_tokens=0 if out and all(g["actual_llm_avoided_tokens"] == 0 for g in out) else None,
                  unresolved_attempts=sum(g['unresolved_attempts'] for g in out),
                  estimated_cost_complete=all(g['estimated_cost_complete'] for g in out))
    return {"groups": out, "totals": totals,
            "note": "Legacy cost_usd/list_usd are configured-rate estimates, not invoices. Unknown usage is not zero cost. llm_avoided_est_tokens is caller-supplied potential saving; shadow does not avoid the original call."}


def _count(values: Iterable[Any]) -> Dict[str, int]:
    counts: Dict[str, int] = defaultdict(int)
    for value in values:
        counts[str(value)] += 1
    return counts


def spent_today(rows: Optional[Iterable[Mapping[str, Any]]] = None) -> float:
    start = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
    try:
        source = rows if rows is not None else read(since=start,strict=True)
    except FileNotFoundError:
        return 0.0
    except (OSError,ValueError):
        return math.inf
    total=0.0
    for row in logical_calls(source):
        try:
            if float(row.get("ts") or 0)<start:continue
            unknown=row.get("status") in ("unknown","pending") or (row.get("status") in ("ok","error") and row.get("cost_usd") is None)
            if unknown:return math.inf
            value=float(row.get("cost_usd") or 0)
            if not math.isfinite(value) or value<0:return math.inf
            total+=value
        except (TypeError,ValueError):
            return math.inf
    return round(total,8)
