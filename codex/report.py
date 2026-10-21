"""Report allowlisted updater metadata through existing gh access. Never repairs state."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

from receipt_cloud import validate

TARGETS = {"jev": ("jev-sync", "Codex Jev Update", "medking82/hermes-jev-skills"),
           "native-review": ("native-review-sync", "Codex Native Review Update", "medking82/native-review")}
TASK_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$rows = @{}
foreach ($name in @('Codex Jev Update', 'Codex Native Review Update')) {
    try {
        $task = Get-ScheduledTask -TaskName $name -ErrorAction Stop
        $info = Get-ScheduledTaskInfo -InputObject $task -ErrorAction Stop
        $last = if ($info.LastRunTime.Year -gt 2000) { $info.LastRunTime.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') } else { $null }
        $state = if ([string]$task.State -eq 'Queued') { 'Running' } else { [string]$task.State }
        $rows[$name] = @{state=$state; last_run=$last; last_result=[long]$info.LastTaskResult}
    } catch {
        $state = if ($_.Exception.Message -match 'Access.*denied|Unauthorized|拒绝访问') { 'Denied' } elseif ($_.FullyQualifiedErrorId -match 'CmdletizationQuery_NotFound') { 'Missing' } else { 'Denied' }
        $rows[$name] = @{state=$state; last_run=$null; last_result=$null}
    }
}
$rows | ConvertTo-Json -Depth 4 -Compress
"""


def utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read(root, name):
    path = root / name
    for part in (path, *path.parents):
        if part.is_symlink() or (part.exists() and getattr(part.lstat(), "st_file_attributes", 0) & 1024):
            raise ValueError("Linked reporting paths require manual inspection")
    if not path.exists():
        return None
    if path.stat().st_size > 131072:
        raise ValueError("Oversized reporting metadata")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path, data):
    # Unique temporary files also keep peer task observations atomic.
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write((json.dumps(data, indent=2) + "\n").encode("utf-8"))
    os.replace(temporary, path)


def reason(value, status):
    """Never forward free-form exception text, filesystem paths or command output."""
    text = str(value or "").lower()
    for words, code in (
        (("launcher",), "launcher-failure"),
        (("permission", "access denied", "authentication", "forbidden"), "permissions"),
        (("conflict", "diverged", "not a fast-forward", "history is not"), "conflict"),
        (("offline-tests", "ci did not succeed", "latest ci", "github upstream run"), "ci-failure"),
        (("local tests", "offline tests", "check.py", "test failed", "tests failed"), "local-tests-failure"),
        (("controls", "pinned updater", "manual enrollment", "re-enrollment", "approved policy"), "pinned-controls"),
        (("local edits", "missing files", "clean main", "unclean", "source differs"), "local-edits"),
        (("stop notice", "open stop"), "upstream-stopped"),
        (("pending", "waiting for exact-commit"), "pending-ci"),
        (("temporarily unavailable", "timed out", "offline", "network"), "offline"),
    ):
        if any(word in text for word in words):
            return code
    return "unclassified-stop" if status == "stopped" else None


def receipt(raw, repository, fallback=None):
    if raw is None:
        return None
    status = raw.get("status")
    timestamp = raw.get("observed_at")
    # Older PowerShell launcher receipts contain fractional seconds.
    if isinstance(timestamp, str):
        timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    event = raw.get("event_id") or str(int(hashlib.sha256(str(timestamp).encode()).hexdigest()[:20], 16))
    commit = raw.get("commit") or fallback
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        commit = None
    url = raw.get("run_url")
    if not isinstance(url, str) or not re.fullmatch(r"https://github\.com/" + re.escape(repository) + r"/actions/runs/[0-9]+", url):
        url = None
    return dict(status=status, event_id=str(event), observed_at=timestamp, commit=commit,
                run_url=url, reason=reason(raw.get("reason"), status))


def collect(home, kind, task, now=None):
    folder, _, repository = TARGETS[kind]
    runtime = home / folder
    config = read(runtime, "reporting.json")
    if not config or set(config) != {"schema", "device"} or config["schema"] != 1:
        raise ValueError("Reporting requires reviewed enrollment")
    state = read(runtime, "state.json") or {}
    last = read(runtime, "last-run.json")
    updated = read(runtime, "last-update.json")
    fallback = (last or {}).get("commit") or (updated or {}).get("commit") or state.get("commit")
    report = dict(schema=1, device=config["device"], kind=kind, observed_at=now or utc(), task=task,
                  receipt=receipt(last, repository, fallback), last_update=receipt(updated, repository, fallback),
                  blocked=receipt(state.get("blocked"), repository, fallback),
                  launcher=receipt(read(runtime, "launcher-error.json"), repository, fallback), canary=False)
    validate(report, dict(schema=1, kind=kind, devices=[config["device"]], canary_devices=[]))
    return report


def command(args, *, payload=None):
    """Use current gh authentication without reading it, and keep errors prompt-free."""
    if os.name == "nt":
        # gh --input - needs stdin, while the workstation hidden runner takes a
        # file. Only sanitized dispatch JSON is spooled; never credentials.
        hidden = Path(os.environ.get("USERPROFILE", "")) / ".codex/bin/invoke-hidden.ps1"
        pwsh = shutil.which("pwsh.exe")
        if not hidden.is_file() or not pwsh:
            raise PermissionError("Existing hidden runner is required")
        def quote(value):
            return "'" + str(value).replace("'", "''") + "'"
        temporary = None
        try:
            if payload is not None:
                with tempfile.NamedTemporaryFile(prefix="receipt-dispatch-", suffix=".json", delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(payload.encode("utf-8"))
                if args[-2:] != ["--input", "-"]:
                    raise ValueError("Unexpected receipt transport input")
                args = [*args[:-1], str(temporary)]
            script = ("& " + quote(hidden) + " -FilePath " + quote(args[0])
                      + " -ArgumentList @(" + ",".join(map(quote, args[1:])) + ")")
            return _run([pwsh, "-NoProfile", "-NonInteractive", "-Command", script])
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
    return _run(args, payload)


def _run(args, payload=None):
    result = subprocess.run(args, input=payload, capture_output=True, text=True, encoding="utf-8",
                            timeout=90, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        error = result.stderr.lower()
        if any(word in error for word in ("http 401", "http 403", "authentication", "permission", "access denied")):
            raise PermissionError("GitHub receipt reporting denied; no fallback attempted")
        raise ConnectionError("GitHub receipt submission unavailable; no test result inferred")
    return result.stdout


def submit(report, gh, call=command):
    repository = TARGETS[report["kind"]][2]
    body = json.dumps(dict(event_type="codex-updater-receipt", client_payload=report))
    call([gh, "api", "--hostname", "github.com", "--method", "POST", "repos/" + repository + "/dispatches", "--input", "-"], payload=body)


def unhealthy_peer(value):
    task, current, blocked = value["task"], value["receipt"], value["blocked"]
    if task["state"] in {"Disabled", "Missing", "Denied"} or value["launcher"]:
        return True
    if task["state"] == "Running":
        return False
    if current and current["status"] == "stopped":
        return True  # Sticky receipt replay is harmless; cloud deduplicates its identity.
    if not task["last_run"]:
        return False
    last = datetime.fromisoformat(task["last_run"].replace("Z", "+00:00"))
    now = datetime.fromisoformat(value["observed_at"].replace("Z", "+00:00"))
    if (now - last).total_seconds() <= 300:
        return False
    if task["last_result"] == 2 and blocked and current and blocked["event_id"] == current["event_id"]:
        return False
    return not current or current["status"] == "enrolled" or datetime.fromisoformat(current["observed_at"].replace("Z", "+00:00")) < last


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--kind", choices=TARGETS, required=True)
    args = parser.parse_args(argv)
    own = args.home / TARGETS[args.kind][0]
    try:
        pwsh, gh = shutil.which("pwsh.exe"), shutil.which("gh.exe")
        if not pwsh or not gh:
            raise PermissionError("Existing PowerShell and GitHub CLI are required")
        tasks = json.loads(command([pwsh, "-NoProfile", "-NonInteractive", "-Command", TASK_SCRIPT]))
        for kind, (folder, task_name, _) in TARGETS.items():
            runtime = args.home / folder
            if kind != args.kind and not (runtime / "reporting.json").is_file():
                continue
            report = collect(args.home, kind, tasks[task_name])
            if kind != args.kind and not unhealthy_peer(report):
                continue
            submit(report, gh)
            write(runtime / "last-report.json", dict(status="submitted", observed_at=report["observed_at"],
                  device=report["device"], receipt_event_id=(report["receipt"] or {}).get("event_id")))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        status = "denied" if isinstance(error, PermissionError) else "deferred"
        write(own / "last-report.json", dict(status=status, observed_at=utc(), reason="permissions" if status == "denied" else "reporting-unavailable"))
        print("Receipt reporting " + status + "; updater state retained", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
