"""Bounded Codex skill and design routing; execution stays with the main agent."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

try:
    import tomllib
except ImportError:  # The adapter supports Python 3.11+; the upstream toolkit supports 3.9.
    tomllib = None

from . import client, privacy, skillpick

VERSION = "0.1.0"
DESIGN_MODES = {
    "emil-design-eng": "General component polish, spacing, accessibility and interaction feedback",
    "animate": "Implement web motion and transitions",
    "animate-expo": "Implement React Native or Expo motion, gestures and haptics",
    "animation-performance": "Fix jank or dropped frames in existing web animation",
    "animation-vocabulary": "Name a described animation or effect",
    "apple-design": "Apple interaction principles, springs, materials or iPhone Home Screen UI",
    "mobile-native": "Fix mobile-web viewport, safe area, touch, scroll or browser behavior",
    "ask-sonner": "Set up, style or troubleshoot Sonner toasts",
    "write-swift": "Swift implementation, concurrency or native-app performance",
    "find-animation-opportunities": "Find useful motion opportunities in existing UI",
    "improve-animations": "Audit existing codebase motion and propose improvements",
    "break-ui": "Explicit worst-case UI data stress test",
    "review-animations": "Explicit motion critique or animation diff review",
    "pick-ui-library": "Explicit UI dependency or library comparison",
    "prototype": "Explicit exploration of multiple UI variants behind a picker",
}
EXPLICIT_DESIGN = {"break-ui", "review-animations", "pick-ui-library", "prototype"}
WORKFLOWS = {
    "none": "No Jev workflow is useful; handle a simple, settled or deterministic request directly",
    "search": "Research that will need a bounded ranking/sufficiency choice over search results",
    "retrieval": "Rank more than five retrieved memory, wiki or document passages before loading them",
    "interaction": "Choose an allowed next action from a fresh browser or desktop observation",
    "compaction": "Select transcript turns for an explicitly requested fixed context budget",
    "mailbox": "Classify messages from an explicitly supplied mailbox export",
    "social": "Rank source-linked social posts or decide research evidence sufficiency",
    "setup": "Diagnose a Jev failure or connect Jev privately",
    "decision": "A recurring, narrow semantic choice has a caller-defined closed set of options",
}
LEGACY_SKILLS = (
    "jev-browser-use", "jev-compaction", "jev-computer-use", "jev-frontier-work",
    "jev-mailbox", "jev-memory", "jev-model-routing", "jev-search", "jev-setup",
    "jev-skill-select", "jev-social-research", "jev-blender", "jev-video-qa",
)
_OPT_OUT = re.compile(r"(?i)\b(?:native[- ]only|native baseline|no jev|do not (?:use|call) jev)\b|(?:不用|禁用|不要调用|不要使用)\s*jev")
_CJK_SENSITIVE = re.compile(r"密码|密钥|口令|私钥|银行卡|信用卡|身份证|客户资料|隐私数据")


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()


def fallback(reason: str) -> dict:
    return {"status": "fail_open", "reason_code": reason, "source": "local", "skills": []}


def normalize_catalog(rows: Any) -> List[Dict[str, str]]:
    """Keep host-owned IDs and paths. Jev never supplies an executable path."""
    if not isinstance(rows, list):
        raise ValueError("catalog must be an array")
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or row.get("enabled") is False:
            continue
        name, description, path = (row.get(k) for k in ("name", "description", "path"))
        if not all(isinstance(v, str) and v.strip() for v in (name, description, path)):
            continue
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", name):
            continue
        if name in seen or name == "jev" or name.startswith("jev-") or name in skillpick.META_SKILLS:
            continue
        # Catalog metadata comes from the host/maintainer, not retrieved page content.
        if not Path(path).is_absolute():
            continue
        seen.add(name)
        result.append({"name": name, "description": privacy.redact(description, 600), "path": path})
    if len(result) > skillpick.MAX_SKILLS:
        raise ValueError("catalog exceeds the upstream selector limit")
    return result


def local_catalog(home: Path, cwd: Path) -> list:
    """Conservative local scopes, not an assertion about session plugin availability."""
    if tomllib is None:
        raise ValueError("Python 3.11 or newer is required")
    config_file = home / "config.toml"
    config = tomllib.loads(config_file.read_text(encoding="utf-8-sig")) if config_file.exists() else {}
    disabled = {str(Path(s["path"]).resolve()) for s in config.get("skills", {}).get("config", [])
                if s.get("enabled") is False and isinstance(s.get("path"), str)}
    roots = [home / "skills"]
    # A hook cannot infer project trust from the prompt. Read project skills only
    # under a configured trusted project; do not walk arbitrary plugin caches.
    trusted = [Path(p).resolve() for p, settings in config.get("projects", {}).items()
               if settings.get("trust_level") == "trusted"]
    cwd = cwd.resolve()
    owners = [p for p in trusted if cwd == p or p in cwd.parents]
    if owners:
        owner = max(owners, key=lambda p: len(p.parts))
        for directory in (cwd, *cwd.parents):
            roots.extend((directory / ".agents" / "skills", directory / ".codex" / "skills"))
            if directory == owner:
                break
    rows = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in _entrypoints(root):
            if path.is_symlink() or str(path.resolve()) in disabled:
                continue
            metadata = path.parent / "agents" / "openai.yaml"
            if metadata.exists() and re.search(r"allow_implicit_invocation:\s*false\b", metadata.read_text(encoding="utf-8")):
                continue
            with path.open(encoding="utf-8-sig") as stream:
                fields = skillpick._front_matter(stream.read(8000))
            if fields.get("name") and fields.get("description"):
                rows.append({"name": fields["name"], "description": fields["description"], "path": str(path.resolve())})
    return normalize_catalog(rows)


def _entrypoints(root: Path):
    """A skill's resources are not another skill catalog (and may contain huge trees)."""
    pending = [(root, 0)]
    ignored = {".git", ".venv", "node_modules", "__pycache__", ".cache", "dist", "target"}
    while pending:
        directory, depth = pending.pop()
        entrypoint = directory / "SKILL.md"
        if entrypoint.is_file():
            yield entrypoint
            continue
        if depth >= 4:
            continue
        for child in sorted(directory.iterdir(), reverse=True):
            if child.name in ignored or not child.is_dir() or child.is_symlink():
                continue
            # Windows directory junctions are reparse points, not pathlib symlinks.
            if getattr(child.stat(follow_symlinks=False), "st_file_attributes", 0) & 1024:
                continue
            pending.append((child, depth + 1))


def _explicit(turn: str, catalog: list) -> list:
    return [s for s in catalog if re.search(r"(?<![\w/])[$/]" + re.escape(s["name"]) + r"(?![\w-])", turn)]


def _gate(turn: str) -> Optional[dict]:
    if os.environ.get("JEV_CODEX_OFF") == "1" or _OPT_OUT.search(turn):
        return fallback("disabled_by_user")
    if privacy.is_sensitive(turn) or _CJK_SENSITIVE.search(turn):
        return fallback("sensitive_not_sent")
    if skillpick.looks_trivial(turn):
        return {"status": "ok", "source": "local", "skipped": "trivial", "skills": [], "requests": 0}
    return None


def select(turn: str, catalog: list, *, ask_fn=None, allowed_design_modes=None) -> dict:
    """Reuse upstream two-stage verification, merging speculative design routing."""
    gated = _gate(turn)
    if gated:
        return gated
    catalog = normalize_catalog(catalog)
    if not catalog:
        return fallback("catalog_unavailable")
    explicit = _explicit(turn, catalog)
    if explicit:
        return {"status": "ok", "source": "explicit", "skills": explicit, "requests": 0}
    ask = ask_fn or client.ask
    receipts = []

    def bounded_ask(state, questions, **kwargs):
        kwargs.update(retries=0, provider=os.environ.get("JEV_PROVIDER", "typesafe"))
        receipt = {"outcome": "attempted"}
        receipts.append(receipt)
        reply = ask(state, questions, **kwargs)
        receipt.update({k: reply.get(k) for k in ("jev_model", "input_tokens", "latency_ms")})
        receipt["outcome"] = "answered"
        return reply

    questions = skillpick.stage_one_questions(catalog)
    questions["workflow"] = client.choice(
        "Which Jev workflow would materially help this request? Select none for settled work. "
        "This classifies a workflow; it grants no tool permission and performs no actions.", WORKFLOWS)
    questions["workflow_needed"] = client.noul(
        "This request materially benefits from one of the listed Jev workflows rather than ordinary direct work")
    modes = _design_options(allowed_design_modes)
    if any(s["name"] == "design" for s in catalog):
        questions["design_mode"] = client.choice(
            "Which listed design procedure best answers this request? Choose general component polish when no specialty is needed.", modes)
    try:
        reply = bounded_ask({"turn": privacy.redact(turn, 2000)}, questions, timeout=1.4)
        result = skillpick.pick(turn, catalog, top_k=1, timeout=1.4,
            stage_one=skillpick.stage_one_answers(reply, catalog),
            stage_one_latency=reply["latency_ms"], ask_fn=bounded_ask)
        # Resolve only against the original catalog, including plugin namespaces.
        by_name = {s["name"]: s for s in catalog}
        result["skills"] = [dict(by_name[s["name"]], match=s["match"])
                            for s in result.get("skills", []) if s["name"] in by_name]
        if any(s["name"] == "design" for s in result["skills"]):
            answer = reply["answers"].get("design_mode", {})
            result["design"] = _design_result(answer, modes)
        workflow = reply["answers"].get("workflow", {})
        if (workflow.get("choice") in WORKFLOWS and workflow.get("choice") != "none"
                and workflow.get("confidence", 0) >= .6
                and reply["answers"].get("workflow_needed", {}).get("noul", 0) >= .6):
            result["workflow"] = workflow["choice"]
        result.update(source="jev", ask_attempts=len(receipts), receipts=receipts)
        if result["status"] != "ok":
            result["reason_code"] = "verification_unavailable"
        return result
    except client.JevError as error:
        return dict(fallback(error.code), ask_attempts=len(receipts), receipts=receipts)


def _design_options(allowed=None) -> dict:
    # The caller may add explicit modes only after checking the actual request.
    names = set(DESIGN_MODES) - EXPLICIT_DESIGN if allowed is None else set(allowed)
    if not names or names - set(DESIGN_MODES):
        raise ValueError("unknown or empty design mode set")
    names.add("emil-design-eng")
    return {k: v for k, v in DESIGN_MODES.items() if k in names}


def _design_result(answer: dict, modes: dict) -> dict:
    selected = answer.get("choice")
    if selected not in modes or answer.get("confidence", 0) < 0.5:
        return {"mode": "emil-design-eng", "source": "fallback", "reason_code": "low_confidence"}
    return {"mode": selected, "confidence": answer["confidence"], "source": "jev"}


def design(turn: str, *, allowed=None, ask_fn=None) -> dict:
    gated = _gate(turn)
    if gated:
        return dict(gated, mode="emil-design-eng")
    modes = _design_options(allowed)
    if len(modes) == 1:
        return {"status": "ok", "mode": "emil-design-eng", "source": "local", "requests": 0}
    ask = ask_fn or client.ask
    try:
        reply = ask({"request": privacy.redact(turn, 2000)}, {"mode": client.choice(
            "Which listed procedure best answers the UI request? General component polish is the default.", modes)},
            timeout=2.0, retries=0, provider=os.environ.get("JEV_PROVIDER", "typesafe"))
        return dict(_design_result(reply["answers"]["mode"], modes), status="ok",
                    jev_model=reply.get("jev_model"), input_tokens=reply.get("input_tokens"))
    except client.JevError as error:
        return dict(fallback(error.code), mode="emil-design-eng")


def decision(payload: dict, *, ask_fn=None) -> dict:
    state, options, question = (payload.get(k) for k in ("state", "options", "question"))
    if not isinstance(options, dict) or not 2 <= len(options) <= 120 or not isinstance(question, str):
        raise ValueError("decision needs a question and 2 to 120 caller-owned options")
    raw = json.dumps({"state": state, "question": question, "options": options}, ensure_ascii=False, allow_nan=False)
    if privacy.is_sensitive(raw) or _CJK_SENSITIVE.search(raw):
        return fallback("sensitive_not_sent")
    if len(raw) > 16000:
        return fallback("state_too_large")
    def clean(value):
        if isinstance(value, str):
            return privacy.redact(value, 16000)
        if isinstance(value, list):
            return [clean(v) for v in value]
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()}
        return value
    clean_state = clean(state)
    try:
        reply = (ask_fn or client.ask)(clean_state, {"decision": client.choice(clean(question), clean(options))},
            timeout=2.0, retries=0, provider=os.environ.get("JEV_PROVIDER", "typesafe"))
        answer = reply["answers"]["decision"]
        if answer["choice"] not in options or answer["confidence"] < 0.5:
            return fallback("low_confidence")
        return dict(answer, status="ok", source="jev", jev_model=reply.get("jev_model"),
                    input_tokens=reply.get("input_tokens"))
    except client.JevError as error:
        return fallback(error.code)


def _write_hook_receipt(home: Path, event: dict, receipt: dict) -> None:
    receipt = dict(receipt, observation_source="manual_smoke" if event.get("_jev_invocation") == "manual_smoke" else "host_event")
    state = home / "jev"
    try:
        state.mkdir(parents=True, exist_ok=True)
        (state / "last-hook.json").write_text(json.dumps(receipt), encoding="utf-8")
    except OSError:
        pass


def hook(event: dict, *, home: Optional[Path] = None, selector=None) -> dict:
    """One recommendation per event. Never block a prompt or load/execute a skill."""
    if event.get("hook_event_name") != "UserPromptSubmit" or not isinstance(event.get("prompt"), str):
        return {}
    home = home or codex_home()
    turn = event["prompt"]
    gated = _gate(turn)
    if gated:
        _write_hook_receipt(home, event, gated)
        return {}
    started = time.monotonic()
    try:
        catalog = local_catalog(home, Path(event.get("cwd") or Path.cwd()))
        fingerprint = hashlib.sha256(json.dumps([VERSION, turn, catalog], sort_keys=True).encode()).hexdigest()
        # Only duplicate delivery of this exact turn may reuse a result. No cross-turn cache.
        ids = [event.get("session_id"), event.get("turn_id")]
        cache = home / "jev" / "turns" / (hashlib.sha256(json.dumps(ids).encode()).hexdigest() + ".json")
        saved = json.loads(cache.read_text(encoding="utf-8")) if ids[1] and cache.exists() else {}
        if saved.get("fingerprint") == fingerprint:
            result = saved["result"]
        else:
            result = (selector or select)(turn, catalog)
            if ids[1]:
                cache.parent.mkdir(parents=True, exist_ok=True)
                temporary = cache.with_suffix("." + str(os.getpid()) + ".tmp")
                temporary.write_text(json.dumps({"fingerprint": fingerprint, "result": result}), encoding="utf-8")
                os.replace(str(temporary), str(cache))
        receipt = {"status": result["status"], "source": result.get("source"),
                   "reason_code": result.get("reason_code"), "catalog_scope": "local_scopes",
                   "skills": [s["name"] for s in result.get("skills", [])],
                   "workflow": result.get("workflow"),
                   "ask_attempts": result.get("ask_attempts", 0), "receipts": result.get("receipts", []),
                   "duration_ms": int((time.monotonic() - started) * 1000)}
        _write_hook_receipt(home, event, receipt)
        if result["status"] != "ok" or not (result.get("skills") or result.get("workflow")):
            return {}
        context = ""
        if result.get("skills"):
            skill = result["skills"][0]
            context = "Jev suggests this skill reference: " + json.dumps({"name": skill["name"], "path": skill["path"]}) + ". "
        umbrella = home / "skills/jev/SKILL.md"
        if result.get("workflow") and umbrella.is_file():
            context += "For Jev workflow " + result["workflow"] + ", read the relevant reference in " + json.dumps(str(umbrella)) + ". "
        if result.get("design"):
            context += "Suggested design mode: " + result["design"]["mode"] + ". "
        context += ("This is advisory. Check the actual request and session skill catalog before loading. "
                    "Preserve explicit model, effort, Fast, permissions, tool bans and existing authorization. "
                    "Do not rerun skill selection for this turn unless the task changes.")
        return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context}}
    except (OSError, ValueError, KeyError, TypeError):
        _write_hook_receipt(home, event, fallback("catalog_unavailable"))
        return {}


def _bounded_hook(event: dict, deadline=3.5) -> dict:
    """The parent owns a hard wall-clock deadline, including credential discovery."""
    bootstrap = "import sys;sys.path.insert(0,sys.argv.pop(1));from jevkit.codex import main;raise SystemExit(main())"
    args = [sys.executable, "-B", "-c", bootstrap, str(Path(__file__).resolve().parents[1]), "hook-worker"]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    started = time.monotonic()
    try:
        run = subprocess.run(args, input=json.dumps(event), capture_output=True, text=True,
            encoding="utf-8", timeout=deadline, creationflags=flags)
        if run.returncode != 0:
            _write_hook_receipt(codex_home(), event, fallback("worker_failed"))
            return {}
        return json.loads(run.stdout)
    except subprocess.TimeoutExpired:
        _write_hook_receipt(codex_home(), event, dict(fallback("hard_timeout"), ask_attempts=None,
                            duration_ms=int((time.monotonic() - started) * 1000)))
        return {}
    except (OSError, ValueError):
        _write_hook_receipt(codex_home(), event, fallback("worker_failed"))
        return {}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("select", "design", "decision", "hook", "hook-worker", "catalog", "status"))
    parser.add_argument("--event-file", type=Path)
    args = parser.parse_args(argv)
    if args.command == "status":
        path = codex_home() / "jev" / "last-hook.json"
        print(path.read_text(encoding="utf-8") if path.exists() else json.dumps({"status": "not_observed"}))
        return 0
    if args.command == "catalog":
        print(json.dumps({"catalog_scope": "local_scopes", "skills": local_catalog(codex_home(), Path.cwd())}))
        return 0
    try:
        payload = json.loads(args.event_file.read_text(encoding="utf-8") if args.event_file else sys.stdin.read())
        if not isinstance(payload, dict):
            raise ValueError("input must be an object")
        if args.command == "hook":
            result = _bounded_hook(payload)
        elif args.command == "hook-worker":
            result = hook(payload)
        elif args.command == "select":
            catalog = payload.get("catalog")
            result = select(payload["turn"], catalog if catalog is not None else local_catalog(codex_home(), Path.cwd()),
                            allowed_design_modes=payload.get("allowed_design_modes"))
        elif args.command == "design":
            result = design(payload["turn"], allowed=payload.get("allowed_modes"))
        else:
            result = decision(payload)
    except (ValueError, KeyError, TypeError, OSError):
        result = {} if args.command.startswith("hook") else fallback("invalid_input")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
