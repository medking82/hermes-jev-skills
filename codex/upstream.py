"""Trusted control code for the fork's offline, exact-commit upstream integration."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess

FORK = "medking82/hermes-jev-skills"
UPSTREAM = "https://github.com/kerpopule/hermes-jev-skills.git"
WORKFLOW = "codex-upstream-sync.yml"
STOP_TITLE = "Jev Upstream Sync Stopped"


class StopUpdate(RuntimeError):
    pass


def git(repo, *args, check=True):
    # Disable local hooks; never introduce stored credentials into candidate jobs.
    result = subprocess.run(["git", "-c", "core.hooksPath=", *args], cwd=repo,
                            capture_output=True, text=True, encoding="utf-8", errors="replace",
                            timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if check and result.returncode:
        raise StopUpdate("git " + args[0] + " failed (exit " + str(result.returncode) + ")")
    return result.stdout.strip() if check else result


def commit(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise StopUpdate("invalid commit identity")
    return value


def controlled(path):
    """These changes need an explicit maintenance review, never automatic adoption."""
    return (path in {"AGENTS.md", ".gitattributes", ".gitmodules", "vendor/typesafe-ai/.gitattributes"}
            or path.startswith(("codex/", ".github/", "jevkit/codex"))
            or path.startswith("tests/test_codex"))


def controls(repo, revision):
    tree = git(repo, "ls-tree", "-r", "--full-tree", commit(revision))
    result = {}
    for line in tree.splitlines():
        entry, name = line.split("\t", 1)
        if controlled(name):
            result[name] = entry  # Mode, object type and content identity.
    return result


def require_ancestor(repo, old, new):
    if git(repo, "merge-base", "--is-ancestor", commit(old), commit(new), check=False).returncode:
        raise StopUpdate("history is not a fast-forward")


def require_controls(repo, base, candidate):
    if controls(repo, base) != controls(repo, candidate):
        raise StopUpdate("Codex, hook, authorization or automation controls changed; manual review required")


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def prepare(repo, output, *, validate_current=False, upstream=UPSTREAM, official_upstream=None):
    import official
    base = commit(git(repo, "rev-parse", "HEAD"))
    git(repo, "fetch", "--no-tags", upstream, "main")
    latest = commit(git(repo, "rev-parse", "FETCH_HEAD"))
    unchanged = git(repo, "merge-base", "--is-ancestor", latest, base, check=False).returncode == 0
    git(repo, "config", "user.name", "github-actions[bot]")
    git(repo, "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    if not unchanged:
        result = git(repo, "merge", "--no-edit", latest, check=False)
        if result.returncode:
            git(repo, "merge", "--abort", check=False)
            raise StopUpdate("upstream merge conflict; fork main was not changed")
    require_controls(repo, base, git(repo, "rev-parse", "HEAD"))
    reference = official.refresh(repo, upstream=official_upstream or official.URL)
    if reference["changed"]:
        git(repo, "add", "--", official.SNAPSHOT)
        git(repo, "commit", "-m", "Update Official TypeSafe Skill Reference")
    candidate = commit(git(repo, "rev-parse", "HEAD"))
    metadata = {"base": base, "candidate": candidate, "upstream": latest,
                "official": reference["commit"], "repository": FORK}
    if candidate == base and not validate_current:
        return dict(metadata, changed="false")
    require_controls(repo, base, candidate)
    require_ancestor(repo, base, candidate)
    require_ancestor(repo, latest, candidate)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    git(repo, "bundle", "create", str(output / "candidate.bundle"), "HEAD", official.REF)
    write_json(output / "candidate.json", metadata)
    return dict(metadata, changed="true")


def load_candidate(repo, artifact):
    import official
    data = json.loads((Path(artifact) / "candidate.json").read_text(encoding="utf-8"))
    base, candidate, latest = (commit(data[k]) for k in ("base", "candidate", "upstream"))
    if data.get("repository") != FORK or git(repo, "rev-parse", "HEAD") != base:
        raise StopUpdate("candidate base does not match the trusted workflow checkout")
    pinned = commit(data.get("official"))
    git(repo, "fetch", str(Path(artifact) / "candidate.bundle"), "HEAD:refs/jev-sync/candidate",
        official.REF + ":" + official.REF)
    if git(repo, "rev-parse", "refs/jev-sync/candidate") != candidate:
        raise StopUpdate("bundle does not match the tested commit")
    require_controls(repo, base, candidate)
    require_ancestor(repo, base, candidate)
    require_ancestor(repo, latest, candidate)
    info, files = official.at_revision(repo, candidate)
    if (info["commit"] != pinned or git(repo, "rev-parse", official.REF) != pinned
            or files != official.source(repo, pinned)):
        raise StopUpdate("candidate official reference does not match its source commit")
    return data


def publish(repo, artifact, output):
    data = load_candidate(repo, artifact)
    base, candidate = data["base"], data["candidate"]
    git(repo, "fetch", "--no-tags", "origin", "main")
    if git(repo, "rev-parse", "FETCH_HEAD") != base:
        raise StopUpdate("fork main advanced during tests; no push attempted")
    if candidate != base:
        # Ordinary fast-forward push, no force and no branch-protection bypass.
        git(repo, "push", "origin", candidate + ":refs/heads/main")
    result = dict(data, status="updated" if candidate != base else "unchanged",
                  run_id=os.environ.get("GITHUB_RUN_ID"), workflow=WORKFLOW)
    write_json(output, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["prepare", "verify", "publish"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--validate-current", action="store_true")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    try:
        if args.mode == "prepare":
            result = prepare(repo, args.output, validate_current=args.validate_current)
        elif args.mode == "verify":
            result = load_candidate(repo, args.artifact)
            git(repo, "checkout", "--detach", result["candidate"])
        else:
            result = publish(repo, args.artifact, args.output)
        if args.mode == "prepare" and os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
                for key in ("changed", "base", "candidate", "upstream"):
                    stream.write(key + "=" + result[key] + "\n")
        print(json.dumps(result))
        return 0
    except (OSError, ValueError, StopUpdate, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "stopped", "reason": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
