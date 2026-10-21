"""Preview/apply the Codex-only consolidated Jev installation (Python 3.11+)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import shlex
import subprocess
import sys
import time
import tomllib

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from jevkit.codex import LEGACY_SKILLS, VERSION, user_skill_roots


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def package(repo: Path) -> dict[str, bytes]:
    """Build from upstream sources; only the umbrella keeps discovery metadata."""
    files = {}
    source = repo / "codex" / "skills" / "jev"
    for path in source.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts:
            if path.is_symlink():
                raise ValueError("symlink in the Codex skill source")
            files[path.relative_to(source).as_posix()] = path.read_bytes()
    upstream_names = sorted(p.name for p in (repo / "skills").glob("jev-*") if (p / "SKILL.md").is_file())
    for name in upstream_names:
        root = repo / "skills" / name
        if not (root / "SKILL.md").is_file():
            raise ValueError("upstream workflow missing: " + name)
        for path in root.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            if path.is_symlink():
                raise ValueError("symlink in upstream workflow")
            relative = path.relative_to(root).as_posix()
            content = path.read_bytes()
            if relative == "SKILL.md":
                text = content.decode("utf-8-sig")
                if text.startswith("---"):
                    text = text.split("---", 2)[2].lstrip()
                text = ("# Upstream Workflow Reference\n\n"
                        "Read the Codex umbrella's platform and authorization rules first. "
                        "Hermes switches and macOS helpers are not Codex capabilities.\n\n" + text)
                relative, content = "guide.md", text.encode("utf-8")
            elif path.name == "SKILL.md":
                continue  # No nested discovery entrypoints.
            files["references/upstream/" + name + "/" + relative] = content
    files["references/upstream/index.json"] = (json.dumps({"workflows": upstream_names}, indent=2) + "\n").encode()
    return files


def launcher(python: Path) -> bytes:
    # The existing workstation helper has no stdin parameter. Keep the event out of
    # argv and delete its private, short-lived file even when the adapter fails.
    escaped = str(python).replace("'", "''")
    return ("""$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$eventFile = $null
try {
    $codexRoot = Split-Path -Parent $PSScriptRoot
    $hidden = Join-Path $codexRoot 'bin/invoke-hidden.ps1'
    $adapter = Join-Path $codexRoot 'skills/jev/scripts/jev.py'
    $inbox = Join-Path $PSScriptRoot 'inbox'
    [IO.Directory]::CreateDirectory($inbox) | Out-Null
    $jevEventText = [Console]::In.ReadToEnd()
    if ($jevEventText -match '(?i)api[_ -]?key|password|bearer\\s|token\\s*[:=]|密码|密钥|口令|私钥') {
        [Console]::Out.WriteLine('{}')
        exit 0
    }
    $eventFile = Join-Path $inbox ([guid]::NewGuid().ToString('N') + '.json')
    [IO.File]::WriteAllText($eventFile, $jevEventText, [Text.UTF8Encoding]::new($false))
    & $hidden -FilePath '""" + escaped + """' -ArgumentList @('-B', $adapter, 'hook', '--event-file', $eventFile) -WorkingDirectory $PSScriptRoot
} catch {
    [Console]::Out.WriteLine('{}')
} finally {
    if ($eventFile -and (Test-Path -LiteralPath $eventFile)) {
        Remove-Item -LiteralPath $eventFile -Force
    }
}
exit 0
""").encode("utf-8")


def windows_shell_path(value: str) -> str:
    """A literal drive-rooted path usable as a command in both cmd and PowerShell.

    Keeping the drive/root outside quotes makes PowerShell invoke the path rather
    than evaluate a quoted string. Reject unsupported expansion/control syntax;
    never fall back to a basename, PATH lookup or an unquoted path.
    """
    path = PureWindowsPath(value)
    if (not path.is_absolute() or not re.fullmatch(r"[A-Za-z]:", path.drive)
            or any(char in value for char in '\"`$%!&|<>^\r\n\x00')):
        raise ValueError("Windows hook paths require a literal absolute drive path")
    return path.anchor + '"' + str(path)[len(path.anchor):] + '"'


def handler(home: Path, python: Path) -> dict:
    command = shlex.join([str(python), "-B", str(home / "skills/jev/scripts/jev.py"), "hook"])
    result = {"type": "command", "command": command, "timeout": 6,
              "statusMessage": "Selecting A Skill With Jev", "additionalContextLimit": 1800}
    if os.name == "nt":
        pwsh = shutil.which("pwsh.exe")
        if not pwsh or not (home / "bin/invoke-hidden.ps1").is_file():
            raise ValueError("PowerShell 7 and the workstation hidden runner are required")
        script = str(home / "jev/run-hook.ps1")
        windows_shell_path(script)  # Apply the same no-expansion path validation.
        result["commandWindows"] = (windows_shell_path(str(Path(pwsh).resolve(strict=True))) +
            ' -NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -File "' + script + '"')
    return result


def install(repo: Path, home: Path, python: Path, *, apply=False) -> dict:
    home, repo = home.resolve(), repo.resolve()
    if not home.is_dir():
        raise ValueError("Codex home must already exist")
    state = home / "jev"
    manifest_file = state / "installation.json"
    prior = json.loads(manifest_file.read_text(encoding="utf-8")) if manifest_file.exists() else {}
    skill_root = home / "skills/jev"
    toolkit_root = home / "tools/hermes-jev-skills"
    payload = {skill_root / name: content for name, content in package(repo).items()}
    for path in (repo / "jevkit").rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts:
            if path.is_symlink():
                raise ValueError("symlink in toolkit source")
            payload[toolkit_root / path.relative_to(repo)] = path.read_bytes()
    if os.name == "nt":
        payload[state / "run-hook.ps1"] = launcher(python)
    # Source provenance is metadata, never a claim that a dirty checkout is a release.
    git_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True,
                              text=True, creationflags=git_flags, timeout=10)
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True,
                           text=True, creationflags=git_flags, timeout=10)
    source_commit = revision.stdout.strip() if revision.returncode == 0 else None
    payload[toolkit_root / "INSTALL-COMMIT.txt"] = ((source_commit or "unknown source archive") + "\n").encode()
    # Unknown installed edits stay intact. A first enrollment takes a recoverable
    # snapshot; subsequent updates verify the exact previously owned files.
    for relative, digest in prior.get("files", {}).items():
        target = home / relative
        if target.exists() and sha(target.read_bytes()) != digest:
            raise ValueError("installed Jev file has local edits: " + relative)
    for target in payload:
        if not target.is_relative_to(home):
            raise ValueError("installation target escapes Codex home")
        for ancestor in (target, *target.parents):
            if ancestor == home.parent:
                break
            if ancestor.is_symlink():
                raise ValueError("linked installation target")
    hook_file = home / "hooks.json"
    hooks = json.loads(hook_file.read_text(encoding="utf-8")) if hook_file.exists() else {"hooks": {}}
    new_handler = handler(home, python)
    groups = hooks.setdefault("hooks", {}).setdefault("UserPromptSubmit", [])
    old_handler = prior.get("hook_handler")
    if old_handler:
        for group in groups:
            group["hooks"] = [h for h in group.get("hooks", []) if h != old_handler]
        groups[:] = [g for g in groups if g.get("hooks")]
    if not any(new_handler in g.get("hooks", []) for g in groups):
        groups.append({"hooks": [new_handler]})
    payload[hook_file] = (json.dumps(hooks, indent=2) + "\n").encode("utf-8")
    config_file = home / "config.toml"
    config_text = config_file.read_text(encoding="utf-8-sig") if config_file.exists() else ""
    config = tomllib.loads(config_text)
    path_key = lambda value: os.path.normcase(os.path.abspath(value))
    configured = {path_key(s["path"]) for s in config.get("skills", {}).get("config", [])
                  if s.get("enabled") is False and "path" in s}
    roots = user_skill_roots(home)
    retired_names = sorted(set(LEGACY_SKILLS) | {
        p.name for p in (repo / "skills").glob("jev-*") if (p / "SKILL.md").is_file()
    } | {p.name for root in roots for p in root.glob("jev-*") if p.is_dir()})
    for root in roots:
        for name in retired_names:
            old = root / name / "SKILL.md"
            if path_key(old) not in configured:
                config_text += '\n[[skills.config]]\npath = ' + json.dumps(old.as_posix()) + '\nenabled = false\n'
                configured.add(path_key(old))
    tomllib.loads(config_text)
    payload[config_file] = config_text.encode("utf-8")
    retired = [root / name for root in roots for name in retired_names if (root / name).exists()]
    for path in retired:
        # Refuse linked folders/junctions before moving an entire skill directory.
        if any(p.is_symlink() or getattr(p.stat(follow_symlinks=False), "st_file_attributes", 0) & 1024
               for p in (path, path.parent, path.parent.parent)) or path.resolve().parent != path.parent.resolve():
            raise ValueError("unsafe retirement target")
    report = {"status": "preview", "skill": str(skill_root), "toolkit": str(toolkit_root),
              "retire": sorted({p.name for p in retired}), "retire_paths": [str(p) for p in retired],
              "hook_event": "UserPromptSubmit",
              "warning": "Review and trust the new hook in Codex /hooks; host activation is not yet verified.",
              "config_changed": not config_file.exists() or config_file.read_bytes() != payload[config_file],
              "hooks_changed": not hook_file.exists() or hook_file.read_bytes() != payload[hook_file],
              "hook_definition_changed": old_handler != new_handler,
              "changed_files": sum(not p.exists() or p.read_bytes() != b for p, b in payload.items())}
    if not apply:
        return report
    backup = state / "backups" / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + str(time.time_ns()))
    old_files = {p: p.read_bytes() if p.exists() else None for p in payload}
    obsolete = [home / relative for relative in prior.get("files", {}) if home / relative not in payload]
    for path in obsolete:
        if not path.resolve().is_relative_to(home):
            raise ValueError("obsolete file escapes Codex home")
        old_files[path] = path.read_bytes() if path.exists() else None
    old_files[manifest_file] = manifest_file.read_bytes() if manifest_file.exists() else None
    moved = []
    try:
        backup.mkdir(parents=True)
        for path, content in old_files.items():
            if content is not None:
                dest = backup / "files" / path.relative_to(home)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(content)
        for path, content in payload.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            if old_files[path] != content:
                path.write_bytes(content)
        for path in obsolete:
            path.unlink(missing_ok=True)
        for path in retired:
            relative = Path(path.name) if path.parent == home / "skills" else Path("agents") / path.name
            dest = backup / "retired" / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(str(path), str(dest))
            moved.append((path, dest))
        owned = {p.relative_to(home).as_posix(): sha(b) for p, b in payload.items()
                 if p not in (hook_file, config_file)}
        manifest = {"adapter_version": VERSION, "files": owned, "hook_handler": new_handler,
                    "backup": str(backup), "retired": retired_names,
                    "retired_paths": [str(p) for p in retired],
                    "source_commit": source_commit, "source_dirty": bool(dirty.stdout.strip())}
        manifest_file.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    except Exception:
        for original, dest in reversed(moved):
            os.replace(str(dest), str(original))
        for path, content in old_files.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(content)
        raise
    report.update(status="installed", backup=str(backup))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--home", type=Path, default=Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))))
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    args = parser.parse_args()
    try:
        print(json.dumps(install(REPO, args.home, args.python, apply=args.apply), indent=2))
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({"status": "error", "error": str(error)}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
