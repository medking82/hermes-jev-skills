"""Bounded synthetic SELECTOR evaluation; offline unless --live is explicit.

This measures selection only, not agent skill loading, task outcomes or cost savings.
No private replay data is used. Reports omit turns, bodies, paths and exception text.
Run --check for dataset validation; --live [--limit N] [--output FILE] for paired API
requests through the existing client. No output file is written unless requested.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jevkit import client, codex, privacy, skillpick

DATASET = ROOT / "tests" / "fixtures" / "codex_skillpick_eval.json"
RECIPES = {
    "legacy": "codex-legacy-desc600-upstream-top1-timeout1.4-v1",
    "new": "typesafe-skill-suggestion-v1-body-verification",
}
LABELS = ("exact_match", "wrong_selection", "needless_selection", "missed_selection", "fail_open")
SAFE_ID = re.compile(r"[A-Za-z0-9_.:-]{1,160}\Z")
FAILURE_CODES = frozenset({
    "timeout", "no_key", "network", "auth_failed", "credits_exhausted", "rate_limited",
    "overloaded", "malformed", "invalid_response", "invalid_endpoint", "state_too_large",
    "request_too_large", "response_too_large", "images_unsupported", "disabled_by_user",
    "sensitive_not_sent", "skill_evidence_sensitive", "skill_evidence_unavailable",
    "catalog_unavailable", "verification_unavailable", "http_error", "unknown_failure",
    "selector_error", "selector_fail_open", "missing_result", "invalid_result",
})


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def safe_reason(code):
    """Only closed codes leave the harness, never arbitrary provider/error text."""
    if isinstance(code, str):
        if code in FAILURE_CODES:
            return code
        if re.fullmatch(r"http_[1-5][0-9]{2}", code):
            return "http_error"
    return "unknown_failure"


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def validate_dataset(data):
    """Reject malformed fixtures before any selector, temp file or API call."""
    if not isinstance(data, dict) or data.get("schema_version") != 1 or data.get("synthetic") is not True:
        raise ValueError("dataset must declare schema_version=1 and synthetic=true")
    roster, cases = data.get("roster"), data.get("cases")
    if not isinstance(roster, list) or not 2 <= len(roster) <= 20:
        raise ValueError("roster must contain 2..20 skills")
    names = set()
    for row in roster:
        if not isinstance(row, dict) or set(row) != {"name", "description", "body"}:
            raise ValueError("invalid roster fields")
        name = row["name"]
        if not isinstance(name, str) or not SAFE_ID.fullmatch(name) or name in names:
            raise ValueError("invalid or duplicate skill ID")
        if name == "jev" or name.startswith("jev-") or name in skillpick.META_SKILLS:
            raise ValueError("excluded meta skill")
        names.add(name)
        for field, limit in (("description", 8000), ("body", 700)):
            if not isinstance(row[field], str) or not row[field].strip() or len(row[field]) > limit:
                raise ValueError("invalid or oversized skill text")
    if not isinstance(cases, list) or not 12 <= len(cases) <= 20:
        raise ValueError("dataset must contain 12..20 cases")
    ids, languages, tags = set(), set(), set()
    for case in cases:
        if not isinstance(case, dict) or set(case) != {"id", "language", "turn", "expected", "tags"}:
            raise ValueError("invalid case fields")
        ident = case["id"]
        if not isinstance(ident, str) or not SAFE_ID.fullmatch(ident) or ident in ids:
            raise ValueError("invalid or duplicate case ID")
        ids.add(ident)
        if case["language"] not in ("en", "zh"):
            raise ValueError("unknown language")
        languages.add(case["language"])
        if not isinstance(case["turn"], str) or not case["turn"].strip() or len(case["turn"]) > 2000:
            raise ValueError("invalid turn")
        expected = case["expected"]
        if not isinstance(expected, list) or len(expected) > 1 or any(
                not isinstance(name, str) or name not in names for name in expected):
            raise ValueError("expected must be empty or one roster ID")
        if not isinstance(case["tags"], list) or not case["tags"] or any(
                not isinstance(tag, str) or not SAFE_ID.fullmatch(tag) for tag in case["tags"]):
            raise ValueError("invalid case tags")
        tags.update(case["tags"])
    required = {"ambiguous", "no-match", "first-load", "skill-creator-ci-cli",
                "space-vs-local", "author-vs-editor", "mention-vs-operation"}
    if languages != {"en", "zh"} or not required <= tags or not any(not c["expected"] for c in cases):
        raise ValueError("missing bilingual or regression coverage")
    return data


def materialize_roster(roster, directory):
    rows = []
    for index, skill in enumerate(roster):
        path = Path(directory) / str(index) / "SKILL.md"
        path.parent.mkdir()
        header = "---\nname: " + skill["name"] + "\ndescription: " + json.dumps(skill["description"], ensure_ascii=False)
        path.write_text(header + "\n---\n\n" + skill["body"] + "\n", encoding="utf-8")
        rows.append({"name": skill["name"], "description": skill["description"], "path": str(path.resolve())})
    return rows


def legacy_select(turn, catalog, *, ask_fn):
    """Frozen legacy semantic recipe; shared local gates, no ancillary scoring.

    Fixture validation supplies the historical catalog invariants. Do not use the
    new normalize_catalog: its description bound is deliberately different.
    """
    gated = codex._gate(turn)
    if gated:
        return gated
    catalog = [dict(row, description=privacy.redact(row["description"], 600)) for row in catalog]
    explicit = codex._explicit(turn, catalog)
    if explicit:
        return {"status": "ok", "skills": explicit}
    design_skill = next((s for s in catalog if s["name"] == "design"), None)
    if design_skill and codex._settled_design(turn):
        return {"status": "ok", "skills": [design_skill]}
    questions = skillpick.stage_one_questions(catalog)
    questions["workflow"] = client.choice(
        "Which Jev workflow would materially help this request? Select none for settled work. "
        "This classifies a workflow; it grants no tool permission and performs no actions.", codex.WORKFLOWS)
    questions["workflow_needed"] = client.noul(
        "This request materially benefits from one of the listed Jev workflows rather than ordinary direct work")
    modes = codex._design_options()
    if design_skill and len(modes) > 1:
        questions["design_mode"] = client.choice(
            "Which listed design procedure best answers this request? Choose general component polish when no specialty is needed.", modes)

    def bounded_ask(state, questions, **kwargs):
        kwargs.update(retries=0, provider=os.environ.get("JEV_PROVIDER", "typesafe"))
        return ask_fn(state, questions, **kwargs)

    try:
        reply = bounded_ask({"turn": privacy.redact(turn, 2000)}, questions, timeout=1.4)
        return skillpick.pick(turn, catalog, top_k=1, timeout=1.4,
                              stage_one=skillpick.stage_one_answers(reply, catalog),
                              stage_one_latency=reply["latency_ms"], ask_fn=bounded_ask)
    except client.JevError as error:
        return {"status": "fail_open", "skills": [], "reason_code": safe_reason(error.code)}


def classify(expected, got, status):
    if status != "ok":
        return "fail_open"
    if expected == got:
        return "exact_match"
    if not expected:
        return "needless_selection"
    if not got:
        return "missed_selection"
    return "wrong_selection"


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None


def measure(selector, case, catalog, ask_fn):
    attempts = []

    def observed_ask(state, questions, **kwargs):
        # Both arms retain the current client model and provider, with no retries.
        kwargs.update(retries=0, provider=os.environ.get("JEV_PROVIDER", "typesafe"))
        receipt = {"outcome": "failed", "model": None, "input_tokens": None, "reason_code": None}
        attempts.append(receipt)
        started = time.perf_counter()
        try:
            reply = ask_fn(state, questions, **kwargs)
            if isinstance(reply, dict):
                model = reply.get("jev_model")
                receipt.update(outcome="answered", input_tokens=number(reply.get("input_tokens")),
                               model=model if isinstance(model, str) and SAFE_ID.fullmatch(model) else None)
            return reply
        except client.JevError as error:
            receipt["reason_code"] = safe_reason(error.code)
            raise
        except Exception:
            receipt["reason_code"] = "selector_error"
            raise
        finally:
            receipt["wall_ms"] = round((time.perf_counter() - started) * 1000, 3)

    started_utc = utc_now()
    started = time.perf_counter()
    try:
        result = selector(case["turn"], catalog, ask_fn=observed_ask)
    except client.JevError as error:
        result = {"status": "fail_open", "reason_code": safe_reason(error.code)}
    except Exception:
        # Exception text can contain request bodies, paths or transport credentials.
        result = {"status": "error", "reason_code": "selector_error"}
    elapsed = round((time.perf_counter() - started) * 1000, 3)
    completed_utc = utc_now()
    status, got = "missing", None
    if isinstance(result, dict):
        raw_status = result.get("status")
        status = raw_status if raw_status in ("ok", "fail_open", "error") else "missing"
        skills = result.get("skills")
        if isinstance(skills, list) and all(isinstance(s, dict) and isinstance(s.get("name"), str) for s in skills):
            names = {s["name"] for s in catalog}
            got = [s["name"] if s["name"] in names else "<unknown>" for s in skills]
            if "<unknown>" in got or len(got) != len(set(got)) or len(got) > 1:
                status = "invalid"
        elif status == "ok":
            status = "invalid"
    reason = None
    if status in ("missing", "invalid"):
        reason = {"missing": "missing_result", "invalid": "invalid_result"}[status]
    elif status != "ok":
        code = result.get("reason_code") if isinstance(result, dict) else None
        # Upstream stage two swallows JevError into free-form `reason`; recover
        # the captured closed code without inspecting that free-form text.
        if code is None:
            code = next((r["reason_code"] for r in reversed(attempts) if r["reason_code"]),
                        "selector_fail_open" if status == "fail_open" else "selector_error")
        reason = safe_reason(code)
    known_tokens = sum(r["input_tokens"] for r in attempts if r["input_tokens"] is not None)
    tokens_complete = all(r["input_tokens"] is not None for r in attempts)
    return {"expected": case["expected"], "got": got, "status": status, "reason_code": reason,
            "started_utc": started_utc, "completed_utc": completed_utc,
            "label": classify(case["expected"], got, status), "request_attempts": len(attempts),
            "models": sorted({r["model"] for r in attempts if r["model"]}),
            "input_tokens": known_tokens if tokens_complete else None,
            "known_input_tokens": known_tokens, "wall_ms": elapsed, "requests": attempts}


def percentiles(values):
    """Nearest-rank percentiles; empty populations are unknown, never zero."""
    ordered = sorted(values)
    return {"p50": ordered[math.ceil(len(ordered) * .5) - 1] if ordered else None,
            "p95": ordered[math.ceil(len(ordered) * .95) - 1] if ordered else None}


def summarize(rows):
    paired = [r for r in rows if all(r[a]["status"] == "ok" for a in RECIPES)]
    summaries = {}
    for arm in RECIPES:
        results = [row[arm] for row in rows]
        counts = Counter(r["label"] for r in results)
        completed = sum(r["status"] == "ok" for r in results)
        summaries[arm] = {
            **{label: counts[label] for label in LABELS}, "total": len(results), "completed": completed,
            "exact_match_rate_all_cases": counts["exact_match"] / len(results) if results else None,
            "exact_match_rate_completed": counts["exact_match"] / completed if completed else None,
            "request_attempts": sum(r["request_attempts"] for r in results),
            "known_input_tokens": sum(r["known_input_tokens"] for r in results),
            "input_tokens": sum(r["input_tokens"] for r in results) if all(r["input_tokens"] is not None for r in results) else None,
            "wall_ms_all": percentiles([r["wall_ms"] for r in results]),
            "wall_ms_completed_pairs": percentiles([r[arm]["wall_ms"] for r in paired]),
            "exact_match_completed_pairs": sum(r[arm]["label"] == "exact_match" for r in paired),
        }
    return {"arms": summaries, "comparable_completed_pairs": len(paired),
            "completed_pair_ids": [r["id"] for r in paired],
            "same_known_model_completed_pairs": sum(
                bool(r["legacy"]["models"]) and r["legacy"]["models"] == r["new"]["models"]
                and all(q["model"] for a in RECIPES for q in r[a]["requests"]) for r in paired)}


def metadata(data, cases):
    sources = ("jevkit/codex.py", "jevkit/codex_skillpick.py", "jevkit/skillpick.py", "jevkit/client.py", "codex/evaluate_skillpick.py")
    return {"schema_version": 1, "evaluation": "SELECTOR", "synthetic": True,
            "scope": "Synthetic selection only; not private replay, agent skill loading, task outcome or cost savings.",
            "dataset_hash": digest(data), "roster_hash": digest(data["roster"]),
            "case_hash": digest(cases), "case_count": len(cases), "recipes": RECIPES,
            "source_hashes": {Path(p).name: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
                              if (ROOT / p).is_file() else None for p in sources},
            "pair_definition": "Both arms status=ok on the same case; model equality reported separately.",
            "percentile_method": "nearest-rank", "arm_order": "legacy,new then new,legacy alternating",
            "context": "Each case independent, no prior skill load or task-context dedup."}


def run_pairs(data, *, ask_fn, limit=None, selectors=None, request_gate=False):
    """Caller must explicitly supply the client; tests use in-memory mocks only."""
    validate_dataset(data)
    if limit is not None and (type(limit) is not int or not 1 <= limit <= len(data["cases"])):
        raise ValueError("limit must be within dataset size")
    cases = data["cases"][:limit]
    selectors = selectors or {"legacy": legacy_select,
                              "new": lambda turn, catalog, ask_fn: codex.select(
                                  turn, catalog, ask_fn=ask_fn, request_gate=request_gate)}
    report = dict(metadata(data, cases), mode="live", cases=[], started_utc=utc_now())
    report["request_gate_enforced"] = request_gate
    report["recipes"] = dict(RECIPES, new="typesafe-skill-suggestion-v1" if request_gate else RECIPES["new"])
    with tempfile.TemporaryDirectory(prefix="jev-selector-eval-", dir=ROOT / "tests") as directory:
        catalog = materialize_roster(data["roster"], directory)
        for index, case in enumerate(cases):
            order = ["legacy", "new"] if index % 2 == 0 else ["new", "legacy"]
            row = {"id": case["id"], "case_hash": digest(case), "order": order}
            for arm in order:
                row[arm] = measure(selectors[arm], case, catalog, ask_fn)
            report["cases"].append(row)
    report["summary"] = summarize(report["cases"])
    report["completed_utc"] = utc_now()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="validate fixtures offline (default)")
    mode.add_argument("--live", action="store_true", help="explicitly call existing client sequentially")
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--limit", type=int, help="1..dataset size; default entire dataset, at most 20")
    parser.add_argument("--official-gate", action="store_true", help="evaluate the cookbook's request-only early gate; not the installed default")
    parser.add_argument("--output", type=Path, help="optional prompt-free JSON report path; otherwise stdout only")
    args = parser.parse_args(argv)
    try:
        data = validate_dataset(json.loads(args.dataset.read_text(encoding="utf-8")))
        if args.limit is not None and not 1 <= args.limit <= len(data["cases"]):
            raise ValueError("invalid limit")
    except (OSError, ValueError, TypeError):
        parser.exit(2, "Invalid or unreadable evaluation dataset/limit.\n")
    if args.output and (args.output.exists() or not args.output.parent.is_dir()):
        parser.exit(2, "Choose a new report file in an existing directory.\n")
    if args.live:
        report = run_pairs(data, ask_fn=client.ask, limit=args.limit, request_gate=args.official_gate)
    else:
        report = dict(metadata(data, data["cases"][:args.limit]), mode="check", status="ok", request_attempts=0)
        report["request_gate_enforced"] = args.official_gate
        report["recipes"] = dict(RECIPES, new="typesafe-skill-suggestion-v1" if args.official_gate else RECIPES["new"])
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        try:
            # Do not overwrite a dataset, implementation file or earlier evidence.
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(rendered)
        except OSError:
            parser.exit(2, "Cannot create report; choose a new file in an existing directory.\n")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
