"""Bounded Codex skill and design routing; execution stays with the main agent."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid
from typing import Any, Dict, List, Optional

try:
    import tomllib
except ImportError:  # The adapter supports Python 3.11+; the upstream toolkit supports 3.9.
    tomllib = None

from . import client, codex_catalog, codex_skillpick, privacy, skillpick

VERSION = "0.2.0"
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


def user_skill_roots(home: Path) -> tuple:
    """Codex's runtime skills and the shared user skill scope are distinct."""
    return tuple(dict.fromkeys((home / "skills", Path.home() / ".agents" / "skills")))


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
        result.append({"name": name, "description": privacy.redact(description, codex_skillpick.DESCRIPTION_CHARS), "path": path})
    if len(result) > skillpick.MAX_SKILLS:
        raise ValueError("catalog exceeds the upstream selector limit")
    return result


def local_catalog(home: Path, cwd: Path) -> list:
    """Conservative local scopes, not an assertion about session plugin availability."""
    if tomllib is None:
        raise ValueError("Python 3.11 or newer is required")
    config_file = home / "config.toml"
    config = tomllib.loads(config_file.read_text(encoding="utf-8-sig")) if config_file.exists() else {}
    # Config also contains inactive/remote/retired paths. Canonicalizing all of
    # them probes unrelated filesystems and can stall an otherwise local turn.
    path_key = lambda value: os.path.normcase(os.path.abspath(value))
    disabled = {path_key(s["path"]) for s in config.get("skills", {}).get("config", [])
                if s.get("enabled") is False and isinstance(s.get("path"), str)}
    roots = list(user_skill_roots(home))
    # A hook cannot infer project trust from the prompt. Read project skills only
    # under a configured trusted project; do not walk arbitrary plugin caches.
    trusted = [Path(os.path.abspath(p)) for p, settings in config.get("projects", {}).items()
               if Path(p).is_absolute() and settings.get("trust_level") == "trusted"]
    cwd = Path(os.path.abspath(cwd))
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
            if path.is_symlink() or path_key(path) in disabled:
                continue
            metadata = path.parent / "agents" / "openai.yaml"
            if metadata.exists() and re.search(r"allow_implicit_invocation:\s*false\b", metadata.read_text(encoding="utf-8")):
                continue
            with path.open(encoding="utf-8-sig") as stream:
                fields = skillpick._front_matter(stream.read(8000))
            if fields.get("name") and fields.get("description"):
                rows.append({"name": fields["name"], "description": fields["description"], "path": str(path.absolute())})
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


def _settled_design(turn: str, allowed=None) -> Optional[dict]:
    """Recognize whole commands only; extra prose, negation or modes must use Jev.

    A literal mode command authorizes that mode, including opt-in modes, unless
    the caller restricts it. Polish accepts only component + visual-property lists.
    This intentionally leaves most natural-language requests to the main path.
    """
    text = re.sub(r"^(?:use\s+)?\$design(?![\w-])\s*[:：]?\s*", "", turn.strip(), flags=re.I)
    modes = _design_options(allowed)
    mode_ids = "|".join(re.escape(name) for name in DESIGN_MODES)
    command = re.fullmatch(
        r"(?:(?:use|choose|select)\s+|(?:使用|选择)\s*)?(?P<quote>`?)(?P<mode>" + mode_ids +
        r")(?P=quote)(?:\s+mode|\s*模式)?[.。]?", text, flags=re.I)
    if command:
        mode = command["mode"].lower()
        if allowed is None or mode in modes:
            return {"mode": mode, "source": "local", "reason_code": "explicit_mode"}
        return None
    component = r"(?:form|button|component|card|dialog)"
    aspect = r"(?:spacing|padding|alignment|contrast|focus styles|button feedback)"
    english = (r"(?:polish|adjust|improve|fix) (?:the )?" + component +
               r"(?:['’]s)? " + aspect + r"(?: (?:and|&) " + aspect + r")*[.]?")
    chinese_component = r"(?:表单|按钮|组件|卡片|对话框)"
    chinese_aspect = r"(?:间距|内边距|对齐|对比度|焦点样式|按钮反馈)"
    chinese = (r"(?:调整|优化|改善|润色)" + chinese_component + r"的?" + chinese_aspect +
               r"(?:(?:和|与|、)" + chinese_aspect + r")*[。]?")
    if re.fullmatch(english, text, flags=re.I) or re.fullmatch(chinese, text):
        return {"mode": "emil-design-eng", "source": "local", "reason_code": "component_polish"}
    return None


def select(turn: str, catalog: list, *, ask_fn=None, allowed_design_modes=None, request_gate=False) -> dict:
    """Follow official two-stage verification, merging speculative design routing."""
    gated = _gate(turn)
    if gated:
        return gated
    catalog = normalize_catalog(catalog)
    if not catalog:
        return fallback("catalog_unavailable")
    explicit = _explicit(turn, catalog)
    if explicit:
        result = {"status": "ok", "source": "explicit", "skills": explicit, "requests": 0}
        if len(explicit) == 1 and explicit[0]["name"] == "design":
            settled = _settled_design(turn, allowed_design_modes)
            if settled:
                result["design"] = settled
        return result
    design_skill = next((s for s in catalog if s["name"] == "design"), None)
    settled = _settled_design(turn, allowed_design_modes) if design_skill else None
    if settled:
        return {"status": "ok", "source": "local", "skills": [design_skill],
                "design": settled, "requests": 0}
    ask = ask_fn or client.ask
    receipts = []

    def bounded_ask(state, questions, **kwargs):
        kwargs.update(retries=0, provider=os.environ.get("JEV_PROVIDER", "typesafe"))
        receipt = {"outcome": "attempted"}
        receipts.append(receipt)
        reply = ask(state, questions, **kwargs)
        receipt.update({k: reply.get(k) for k in ("jev_model", "input_tokens", "latency_ms")})
        receipt["output_tokens"] = reply.get("usage", {}).get("output_tokens")
        receipt["outcome"] = "answered"
        return reply

    questions = codex_skillpick.stage_one_questions(catalog)
    questions["workflow"] = client.choice(
        "Which Jev workflow would materially help this request? Select none for settled work. "
        "This classifies a workflow; it grants no tool permission and performs no actions.", WORKFLOWS)
    questions["workflow_needed"] = client.noul(
        "This request materially benefits from one of the listed Jev workflows rather than ordinary direct work")
    modes = _design_options(allowed_design_modes)
    if any(s["name"] == "design" for s in catalog) and len(modes) > 1:
        questions["design_mode"] = client.choice(
            "Which listed design procedure best answers this request? Choose general component polish when no specialty is needed.", modes)
    try:
        reply = bounded_ask(codex_skillpick.build_state(turn), questions, timeout=1.4)
        result = codex_skillpick.verify(turn, catalog, reply, ask_fn=bounded_ask, request_gate=request_gate)
        # Resolve only against the original catalog, including plugin namespaces.
        by_name = {s["name"]: s for s in catalog}
        result["skills"] = [dict(by_name[s["name"]], match=s["match"])
                            for s in result.get("skills", []) if s["name"] in by_name]
        if any(s["name"] == "design" for s in result["skills"]):
            answer = reply["answers"].get("design_mode", {})
            result["design"] = ({"mode": next(iter(modes)), "source": "local"}
                                if len(modes) == 1 else _design_result(answer, modes))
        workflow = reply["answers"].get("workflow", {})
        if (workflow.get("choice") in WORKFLOWS and workflow.get("choice") != "none"
                and workflow.get("confidence", 0) >= .6
                and reply["answers"].get("workflow_needed", {}).get("noul", 0) >= .6):
            result["workflow"] = workflow["choice"]
        result.update(source="jev", ask_attempts=len(receipts), receipts=receipts)
        if result["status"] != "ok":
            result.setdefault("reason_code", "verification_unavailable")
        return result
    except client.JevError as error:
        return dict(fallback(error.code), ask_attempts=len(receipts), receipts=receipts)
    except (ValueError, KeyError, TypeError):
        return dict(fallback("invalid_response"), ask_attempts=len(receipts), receipts=receipts)


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
    settled = _settled_design(turn, allowed)
    if settled:
        return dict(settled, status="ok", requests=0)
    modes = _design_options(allowed)
    if len(modes) == 1:
        return {"status": "ok", "mode": next(iter(modes)), "source": "local", "requests": 0}
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
    if os.environ.get("JEV_CODEX_OFF") == "1":
        return fallback("disabled_by_user")
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


def guidance(*, home: Optional[Path] = None) -> dict:
    """Read the current installed official guide; no inference, cache or writes."""
    home = Path(os.path.abspath(home or codex_home()))

    def read(relative, limit):
        path = home / relative
        for parent in (path, *path.parents):
            if parent == home.parent:
                break
            info = parent.lstat()
            if parent.is_symlink() or getattr(info, "st_file_attributes", 0) & 1024:
                raise ValueError("linked guidance path")
        if path.stat().st_size > limit:
            raise ValueError("guidance exceeds its bound")
        return path.read_bytes()

    try:
        manifest = json.loads(read("jev/installation.json", 2 * 1024 * 1024))
        if manifest.get("source_dirty") or not re.fullmatch(r"[0-9a-f]{40}", manifest.get("source_commit", "")):
            raise ValueError("guidance is not an installed clean release")
        prefix = "skills/jev/references/official/typesafe-ai/"
        source_raw = read(prefix + "source.json", 64 * 1024)
        content = read(prefix + "guide.md", 260 * 1024)
        for name, data in (("source.json", source_raw), ("guide.md", content)):
            if manifest["files"].get(prefix + name) != hashlib.sha256(data).hexdigest():
                raise ValueError("guidance differs from installed ownership")
        source = json.loads(source_raw)
        identity = {key: source[key] for key in ("repository", "commit")}
        if (identity["repository"] != "typesafe-ai/skills" or source["directory"] != "skills/typesafe-ai"
                or not re.fullmatch(r"[0-9a-f]{40}", identity["commit"])
                or manifest.get("official_source") != identity):
            raise ValueError("guidance source differs from the installed release")
        return {"status": "ok", "source": "pinned_official", "official_source": identity,
                "path": str(home / prefix / "guide.md"),
                "sha256": hashlib.sha256(content).hexdigest(), "content": content.decode("utf-8")}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return fallback("official_guidance_unavailable")


def _write_hook_receipt(home: Path, event: dict, receipt: dict) -> None:
    receipt = dict(receipt, adapter_version=VERSION, observation_id=uuid.uuid4().hex,
                   observation_source="manual_smoke" if event.get("_jev_invocation") == "manual_smoke" else "host_event",
                   session_id=event.get("session_id") if isinstance(event.get("session_id"), str) else None,
                   turn_id=event.get("turn_id") if isinstance(event.get("turn_id"), str) else None,
                   observed_at=datetime.now(timezone.utc).isoformat())
    state = home / "jev"
    try:
        state.mkdir(parents=True, exist_ok=True)
        (state / "last-hook.json").write_text(json.dumps(receipt), encoding="utf-8")
    except OSError:
        pass
    # Immutable files avoid competing hooks rewriting one another's ledger. The
    # old last-hook/cache files remain compatibility views, never audit history.
    try:
        directory = state / "observations" / receipt["observed_at"][:10]
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / (receipt["observation_id"] + ".json")
        temporary = target.with_suffix(".tmp")
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(receipt, stream)
        temporary.rename(target)
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
        config_file = home / "config.toml"
        config = tomllib.loads(config_file.read_text(encoding="utf-8-sig")) if config_file.exists() else {}
        plugins, catalog_source = codex_catalog.session_plugins(home, event, config)
        catalog = normalize_catalog(catalog + plugins)
        fingerprint = hashlib.sha256(json.dumps([VERSION, turn, catalog], sort_keys=True).encode()).hexdigest()
        # Only duplicate delivery of this exact turn may reuse a result. No cross-turn cache.
        ids = [event.get("session_id"), event.get("turn_id")]
        cache = home / "jev" / "turns" / (hashlib.sha256(json.dumps(ids).encode()).hexdigest() + ".json")
        saved = json.loads(cache.read_text(encoding="utf-8")) if ids[1] and cache.exists() else {}
        reused = saved.get("fingerprint") == fingerprint and codex_skillpick.evidence_unchanged(saved.get("result", {}), catalog)
        if reused:
            result = saved["result"]
        else:
            result = (selector or select)(turn, catalog)
            if ids[1]:
                cache.parent.mkdir(parents=True, exist_ok=True)
                temporary = cache.with_suffix("." + str(os.getpid()) + ".tmp")
                temporary.write_text(json.dumps({"fingerprint": fingerprint, "result": result}), encoding="utf-8")
                os.replace(str(temporary), str(cache))
        receipt = {"status": result["status"], "source": result.get("source"),
                   "reason_code": result.get("reason_code"),
                   "fingerprint": fingerprint, "cache_reused": reused,
                   "verification": result.get("verification"),
                   "catalog_scope": "local_scopes+session_plugins" if plugins else "local_scopes",
                   "catalog_source": catalog_source,
                   "skills": [s["name"] for s in result.get("skills", [])],
                   "workflow": result.get("workflow"),
                   "design": result.get("design"),
                   "ask_attempts": 0 if reused else result.get("ask_attempts", 0),
                   "receipts": [] if reused else result.get("receipts", []),
                   "duration_ms": int((time.monotonic() - started) * 1000)}
        _write_hook_receipt(home, event, receipt)
        no_match = (result.get("source") == "jev" and
                    result.get("verification", {}).get("outcome") in ("gate_no_match", "fit_no_match"))
        if result["status"] != "ok" or not (result.get("skills") or result.get("workflow") or no_match):
            return {}
        context = ""
        if result.get("skills"):
            skill = result["skills"][0]
            prefix = "Jev suggests" if result.get("source") == "jev" else "Local routing suggests"
            context = prefix + " this skill reference: " + json.dumps({"name": skill["name"], "path": skill["path"]}) + ". "
        elif no_match:
            context = "Jev found no applicable skill in the catalog for this request. Explicit choices and mandatory skill instructions still apply. "
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
    parser.add_argument("command", choices=("select", "design", "decision", "guidance", "hook", "hook-worker", "catalog", "status"))
    parser.add_argument("--event-file", type=Path)
    args = parser.parse_args(argv)
    if args.command == "status":
        path = codex_home() / "jev" / "last-hook.json"
        print(path.read_text(encoding="utf-8") if path.exists() else json.dumps({"status": "not_observed"}))
        return 0
    if args.command == "catalog":
        print(json.dumps({"catalog_scope": "local_scopes", "skills": local_catalog(codex_home(), Path.cwd())}))
        return 0
    if args.command == "guidance":
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="strict", newline="\n")
        print(json.dumps(guidance(), ensure_ascii=False))
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
