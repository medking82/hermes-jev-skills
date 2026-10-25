"""Plugin candidates from this turn's host-supplied catalog, never a cache scan."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

from . import skillpick

# Bound transcript I/O as well as the existing outer hook deadline. Old/oversized
# or unsupported host records fall back to local routing instead of guessing.
MAX_READ = 32 * 1024 * 1024
MAX_LINE = 512 * 1024


class CatalogUnavailable(ValueError):
    pass


def _path_key(path):
    return os.path.normcase(os.path.abspath(path))


def _plain(path, root):
    """Do not follow plugin/session symlinks or Windows junctions."""
    for part in (path, *path.parents):
        if part == root:
            return True
        if part.is_symlink() or getattr(part.stat(follow_symlinks=False), "st_file_attributes", 0) & 1024:
            return False
    return False


def _rollout(home, session):
    identity = uuid.UUID(session)
    if identity.version != 7:
        raise CatalogUnavailable("unsupported_session_id")
    created = datetime.fromtimestamp((identity.int >> 80) / 1000, timezone.utc)
    root = home / "sessions"
    matches = []
    # Codex uses UUIDv7 and date-partitioned rollouts. Include local-date offsets.
    for offset in (-1, 0, 1):
        folder = root / (created + timedelta(days=offset)).strftime("%Y/%m/%d")
        if folder.is_dir() and _plain(folder, root):
            matches.extend(p for p in folder.glob("rollout-*-" + str(identity) + ".jsonl") if _plain(p, root))
    if len(matches) != 1:
        raise CatalogUnavailable("session_rollout_unavailable")
    return matches[0]


def _frame(home, event):
    session, turn = event.get("session_id"), event.get("turn_id")
    if not isinstance(session, str) or not isinstance(turn, str) or not event.get("cwd"):
        raise CatalogUnavailable("session_identity_missing")
    uuid.UUID(turn)
    path = _rollout(home, session)
    with path.open("rb") as stream:
        header = json.loads(stream.readline(MAX_LINE))
        meta = header.get("payload", {})
        if (not isinstance(meta, dict) or header.get("type") != "session_meta"
                or meta.get("id") != session or meta.get("session_id", session) != session):
            raise CatalogUnavailable("session_identity_mismatch")
        size = stream.seek(0, 2)
        start = max(0, size - MAX_READ)
        stream.seek(start)
        data = stream.read(MAX_READ)
    lines = data.splitlines()
    if start:
        lines = lines[1:]
    # Only consume committed JSONL records, including during a live host append.
    if data and not data.endswith(b"\n"):
        lines = lines[:-1]
    context = None
    for raw in reversed(lines):
        if len(raw) > MAX_LINE or not (b"turn_context" in raw or b"<skills_instructions>" in raw):
            continue
        try:
            row = json.loads(raw)
        except (ValueError, UnicodeError):
            continue
        payload = row.get("payload", {})
        if not isinstance(payload, dict):
            continue
        if row.get("type") == "turn_context":
            if context is None:
                if payload.get("turn_id") != turn or _path_key(payload.get("cwd", "")) != _path_key(event["cwd"]):
                    raise CatalogUnavailable("active_turn_mismatch")
                context = row
        if context is None or row.get("type") != "response_item" or payload.get("role") != "developer":
            continue
        if row.get("timestamp", "") > context.get("timestamp", ""):
            continue
        for content in reversed(payload.get("content", [])):
            text = content.get("text", "") if isinstance(content, dict) else ""
            if (text.startswith("<skills_instructions>\n") and text.rstrip().endswith("</skills_instructions>")
                    and "### Skill roots\n" in text and "### Available skills\n" in text):
                return text, {"status": "verified", "source": "session_rollout",
                              "snapshot_at": row.get("timestamp"), "source_path": str(path),
                              "snapshot_sha256": hashlib.sha256(text.encode()).hexdigest()}
    raise CatalogUnavailable("current_session_catalog_unavailable")


def _plugin_rows(text, home, config, *, explicit=()):
    roots = dict(re.findall(r"(?m)^- `(r\d+)` = `([^`]+)`\s*$", text))
    section = text.split("### Available skills\n", 1)[1]
    disabled = {_path_key(s["path"]) for s in config.get("skills", {}).get("config", [])
                if isinstance(s.get("path"), str) and s.get("enabled") is False}
    cache = home / "plugins/cache"
    rows, seen = [], set()
    for line in section.splitlines():
        match = re.fullmatch(r"- ([A-Za-z0-9_.:-]{1,160}): (.+) \(file: (.+)\)", line)
        if not match:
            continue
        name, description, source = match.groups()
        prefix, _, rest = source.partition("/")
        path = Path(roots[prefix]) / rest if prefix in roots else Path(source)
        if not path.is_absolute() or not path.is_relative_to(cache):
            continue
        relative = path.relative_to(cache).parts
        if len(relative) != 6 or relative[3] != "skills" or relative[-1] != "SKILL.md":
            continue
        provider, package, version, _, directory, _ = relative
        if (name.split(":", 1)[0] != package or ":" not in name or ".." in path.parts
                or _path_key(path) in disabled or name in seen):
            continue
        if config.get("plugins", {}).get(package + "@" + provider, {}).get("enabled") is False:
            continue
        try:
            if not path.is_file() or not _plain(path, cache):
                continue
            policy = path.parent / "agents/openai.yaml"
            if policy.exists():
                if not _plain(policy, cache):
                    continue
                if (re.search(r"allow_implicit_invocation:\s*false\b", policy.read_text(encoding="utf-8"))
                        and name not in explicit):
                    continue
            with path.open(encoding="utf-8-sig") as stream:
                fields = skillpick._front_matter(stream.read(8000))
            if fields.get("name") != name.split(":", 1)[1]:
                continue
        except (OSError, ValueError, UnicodeError):
            continue
        seen.add(name)
        rows.append({"name": name, "description": description, "path": str(path)})
    return rows


def session_plugins(home: Path, event: dict, config: dict, *, explicit=()):
    """Return only host-listed, currently allowed plugins, plus prompt-free provenance."""
    try:
        text, evidence = _frame(home, event)
        rows = _plugin_rows(text, home, config, explicit=explicit)
        evidence.update(plugin_count=len(rows), plugin_skills=[r["name"] for r in rows])
        return rows, evidence
    except CatalogUnavailable as error:
        reason = str(error)
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        reason = "invalid_session_catalog"
    return [], {"status": "unavailable", "source": "session_rollout", "reason_code": reason, "plugin_count": 0}
