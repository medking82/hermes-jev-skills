"""Pinned, fail-stop local Jev updater. No models, provider calls or trust writes."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

import official

from upstream import (FORK, WORKFLOW, STOP_TITLE, StopUpdate, commit, controls, git,
                      require_ancestor, write_json)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class DeferredUpdate(RuntimeError):
    """No update attempted; the next ordinary schedule may check connectivity again."""


def network_unavailable(stderr):
    text = stderr.decode("utf-8", errors="replace").lower() if isinstance(stderr, bytes) else stderr.lower()
    return any(marker in text for marker in ("could not resolve host", "couldn't resolve host", "dial tcp",
        "connection timed out", "connection refused", "network is unreachable", "i/o timeout",
        "tls handshake timeout", "could not connect to server", "failed to connect to github.com",
        "error connecting to api.github.com", "http 502", "http 503", "http 504"))


def execute(args, *, cwd=None, env=None, timeout=120, network=False):
    try:
        result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, timeout=timeout,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        if network:
            raise DeferredUpdate("GitHub request timed out; installed release retained") from None
        raise
    if result.returncode:
        if network and network_unavailable(result.stderr):
            raise DeferredUpdate("GitHub temporarily unavailable; installed release retained")
        # Never copy arbitrary command output, credentials or test logs into receipts.
        raise StopUpdate(Path(args[0]).name + " " + args[1] + " failed (exit " + str(result.returncode) + ")")
    return result.stdout


def api(endpoint, *, raw=False):
    output = execute(["gh", "api", "--hostname", "github.com", "repos/" + FORK + "/" + endpoint], network=True)
    return output if raw else json.loads(output)


def fetch_main(repo):
    try:
        result = git(repo, "fetch", "--no-tags", "origin", "main", check=False)
    except subprocess.TimeoutExpired:
        raise DeferredUpdate("GitHub fetch timed out; installed release retained") from None
    if result.returncode:
        if network_unavailable(result.stderr):
            raise DeferredUpdate("GitHub temporarily unavailable; installed release retained")
        raise StopUpdate("fork fetch failed; inspect origin access without bypassing permissions")


def safe_file(root, relative):
    target = root / relative
    if not target.is_relative_to(root) or ".." in Path(relative).parts or Path(relative).is_absolute():
        raise StopUpdate("unsafe owned path")
    for path in (target, *target.parents):
        if path == root.parent:
            break
        if path.is_symlink() or (path.exists() and getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0) & 1024):
            raise StopUpdate("linked owned path")
    return target


def installed(home):
    manifest = json.loads(safe_file(home, "jev/installation.json").read_text(encoding="utf-8"))
    if manifest.get("source_dirty") or not manifest.get("files"):
        raise StopUpdate("installed Jev is not an enrolled clean release")
    commit(manifest.get("source_commit"))
    for relative, expected in manifest["files"].items():
        if not (relative.startswith(("skills/jev/", "tools/hermes-jev-skills/")) or relative == "jev/run-hook.ps1"):
            raise StopUpdate("manifest contains a file outside Jev ownership")
        target = safe_file(home, relative)
        if not target.is_file() or digest(target) != expected:
            raise StopUpdate("installed Jev has missing files or local edits: " + relative)
    return manifest


def clean_main(repo):
    if git(repo, "symbolic-ref", "--short", "HEAD") != "main" or git(repo, "status", "--porcelain"):
        raise StopUpdate("local checkout must be clean main; user work is preserved")
    origin = git(repo, "remote", "get-url", "origin")
    if origin.rstrip("/").removesuffix(".git") not in {
            "https://github.com/" + FORK, "git@github.com:" + FORK, "ssh://git@github.com/" + FORK}:
        raise StopUpdate("origin is not the enrolled GitHub fork")
    return commit(git(repo, "rev-parse", "HEAD"))


def snapshots(home):
    return {name: digest(safe_file(home, name)) for name in ("config.toml", "hooks.json", "jev/installation.json")}


def load_installer(repo):
    spec = importlib.util.spec_from_file_location("jev_approved_installer", repo / "codex/install.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_preview(preview):
    if preview.get("retire_paths") or any(preview.get(k, True) for k in (
            "config_changed", "hooks_changed", "hook_definition_changed")):
        raise StopUpdate("update would change config, hook trust definition or retire skills; manual review required")


def server_state(get=api):
    workflow = get("actions/workflows/" + WORKFLOW)
    if workflow.get("state") != "active":
        raise StopUpdate("GitHub upstream schedule is not active")
    # Query the complete paginated open-issue set; do not depend on search indexing.
    for page in range(1, 101):
        issues = get("issues?state=open&per_page=100&page=" + str(page))
        if any(i.get("title") == STOP_TITLE and "pull_request" not in i for i in issues):
            raise StopUpdate("GitHub upstream integration has an open stop notice")
        if len(issues) < 100:
            break
    else:
        raise StopUpdate("open issue scan exceeded its bound")
    runs = get("actions/workflows/" + WORKFLOW + "/runs?branch=main&per_page=50")["workflow_runs"]
    applicable = [r for r in runs if r.get("head_branch") == "main" and r.get("event") in {"schedule", "workflow_dispatch"}]
    if applicable and applicable[0].get("conclusion") in {"failure", "cancelled", "timed_out", "action_required", "startup_failure"}:
        raise StopUpdate("latest GitHub upstream run did not succeed: " + applicable[0]["html_url"])
    return workflow, applicable


def publication_proof(candidate, workflow, runs, get=api):
    for run in runs:
        if (run.get("status") != "completed" or run.get("conclusion") != "success"
                or run.get("workflow_id") != workflow["id"]
                or run.get("path") != ".github/workflows/" + WORKFLOW):
            continue
        artifacts = get("actions/runs/" + str(run["id"]) + "/artifacts?per_page=100")["artifacts"]
        artifacts = [a for a in artifacts if a.get("name") == "jev-sync-result" and not a.get("expired")]
        if len(artifacts) != 1 or not 0 < artifacts[0]["size_in_bytes"] < 65536:
            continue
        raw = get("actions/artifacts/" + str(artifacts[0]["id"]) + "/zip", raw=True)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if archive.namelist() != ["result.json"] or archive.getinfo("result.json").file_size > 16384:
                raise StopUpdate("unexpected publication artifact")
            proof = json.loads(archive.read("result.json"))
        if (proof.get("candidate") == candidate and proof.get("repository") == FORK
                and proof.get("workflow") == WORKFLOW and str(proof.get("run_id")) == str(run["id"])
                and proof.get("base") == run.get("head_sha") and proof.get("status") in {"updated", "unchanged"}):
            commit(proof["base"])
            commit(proof["upstream"])
            return dict(proof, run_url=run["html_url"])
    raise StopUpdate("fork main has no successful exact-commit upstream publication proof; manual enrollment required")


def native_tests(stage, temporary):
    profile = Path(temporary) / "profile"
    profile.mkdir()
    env = dict(os.environ)
    for name in list(env):
        if any(word in name.upper() for word in ("TOKEN", "API_KEY", "SECRET", "PASSWORD")):
            env.pop(name)
    env.update(HOME=str(profile), USERPROFILE=str(profile), CODEX_HOME=str(profile / ".codex"),
               HERMES_HOME=str(profile / ".hermes"), XDG_CONFIG_HOME=str(profile / ".config"),
               PYTHONUTF8="1", JEV_RELEASE_DENYLIST=str(profile / "absent-denylist.txt"))
    execute([sys.executable, "-B", str(stage / "codex/check.py")], cwd=stage, env=env, timeout=1200)


def update(state, *, apply, get=api, test=native_tests):
    repo, home = Path(state["repo"]), Path(state["home"])
    if set(state["runner_files"]) != {"sync.py", "upstream.py", "official.py"}:
        raise StopUpdate("pinned updater inventory is incomplete; manual enrollment required")
    for name, expected in state["runner_files"].items():
        if digest(Path(__file__).parent / name) != expected:
            raise StopUpdate("pinned updater code changed; manual enrollment required")
    before = clean_main(repo)
    current = installed(home)
    if before != current["source_commit"]:
        raise StopUpdate("local source and installed Jev differ; manual reconciliation required")
    if controls(repo, before) != state["controls"]:
        raise StopUpdate("approved maintenance controls changed")
    saved = snapshots(home)
    workflow, runs = server_state(get)
    fetch_main(repo)
    candidate = commit(git(repo, "rev-parse", "FETCH_HEAD"))
    if before == candidate:
        return {"status": "unchanged", "commit": before}
    require_ancestor(repo, before, candidate)
    if controls(repo, candidate) != state["controls"]:
        raise StopUpdate("fork update changes approved controls; manual enrollment required")
    proof = publication_proof(candidate, workflow, runs, get)
    reference, _ = official.at_revision(repo, candidate)
    if proof.get("official") != reference["commit"]:
        raise StopUpdate("publication proof does not match the pinned official reference")
    require_ancestor(repo, proof["base"], candidate)
    require_ancestor(repo, proof["upstream"], candidate)
    cache = repo / ".cache/jev-sync"
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="candidate-", dir=cache) as temporary:
        stage = Path(temporary) / "source"
        git(repo, "clone", "--quiet", "--shared", "--no-checkout", "--no-hardlinks", str(repo), str(stage))
        git(stage, "checkout", "--detach", candidate)
        test(stage, temporary)
        if clean_main(repo) != before or snapshots(home) != saved:
            raise StopUpdate("source or runtime configuration changed during validation")
        # Import the approved installer, not arbitrary new control code.
        installer = load_installer(repo)
        preview = installer.install(stage, home, Path(sys.executable), apply=False)
        validate_preview(preview)
        if not apply:
            return {"status": "ready", "commit": candidate, "changed_files": preview["changed_files"],
                    "run_url": proof["run_url"], "warning": preview["warning"]}
        if clean_main(repo) != before or snapshots(home) != saved:
            raise StopUpdate("source or runtime configuration changed during validation")
        installed(home)  # Recheck every owned file immediately before mutation.
        fetch_main(repo)
        if git(repo, "rev-parse", "FETCH_HEAD") != candidate:
            raise StopUpdate("fork main moved during local tests")
        # A failed transactional installer leaves its backup and old runtime intact.
        # Source may already be advanced; stop for explicit reconciliation, never reset user work.
        git(repo, "merge", "--ff-only", candidate)
        report = installer.install(repo, home, Path(sys.executable), apply=True)
        final = installed(home)
        if final["source_commit"] != candidate or clean_main(repo) != candidate:
            raise StopUpdate("post-install provenance mismatch")
        if any(digest(safe_file(home, name)) != saved[name] for name in ("config.toml", "hooks.json")):
            raise StopUpdate("post-install configuration mismatch")
        return {"status": "updated", "commit": candidate, "previous_commit": before,
                "official_source": reference["commit"],
                "run_url": proof["run_url"], "backup": report["backup"], "owned_files": len(final["files"])}


@contextmanager
def lock(runtime):
    path = runtime / "run.lock"
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise StopUpdate("updater is already running, or its lock needs manual inspection") from None
    try:
        os.write(descriptor, str(os.getpid()).encode())
        os.close(descriptor)
        yield
    finally:
        path.unlink(missing_ok=True)


def enroll(repo, home, runtime):
    current = clean_main(repo)
    manifest = installed(home)
    if current != manifest["source_commit"]:
        raise StopUpdate("enrollment requires source and installed Jev at the same commit")
    if Path(__file__).parent.resolve() != runtime.resolve():
        raise StopUpdate("copy approved sync.py, upstream.py and official.py into the runtime before enrollment")
    official.checkout(repo)
    result = {"repo": str(repo.resolve()), "home": str(home.resolve()), "enrolled_commit": current,
              "controls": controls(repo, current), "blocked": None,
              "runner_files": {name: digest(runtime / name) for name in ("sync.py", "upstream.py", "official.py")}}
    write_json(runtime / "state.json", result)
    return {"status": "enrolled", "commit": current}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["enroll", "run", "resume"])
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--home", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    state = None
    try:
        with lock(runtime):
            if args.mode == "enroll":
                if not args.repo or not args.home:
                    raise StopUpdate("enrollment requires --repo and --home")
                result = enroll(args.repo, args.home, runtime)
            else:
                state = json.loads((runtime / "state.json").read_text(encoding="utf-8"))
                if state.get("blocked") and args.mode != "resume":
                    print(json.dumps(state["blocked"]))
                    return 2
                if args.mode == "resume":
                    # Explicit operator command only; never called by automation.
                    state["blocked"] = None
                    write_json(runtime / "state.json", state)
                    result = {"status": "resumed"}
                else:
                    result = update(state, apply=args.apply)
            result.update(event_id=str(time.time_ns()), observed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
            write_json(runtime / "last-run.json", result)
            if result["status"] == "updated":
                write_json(runtime / "last-update.json", result)
    except DeferredUpdate as error:
        result = {"status": "deferred", "reason": str(error), "event_id": str(time.time_ns()),
                  "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        write_json(runtime / "last-run.json", result)
    except (OSError, ValueError, KeyError, TypeError, StopUpdate, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        result = {"status": "stopped", "reason": str(error), "event_id": str(time.time_ns()),
                  "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        if state is not None:
            state["blocked"] = result
            write_json(runtime / "state.json", state)
        write_json(runtime / "last-run.json", result)
    print(json.dumps(result))
    return 2 if result["status"] == "stopped" else 0


if __name__ == "__main__":
    raise SystemExit(main())
