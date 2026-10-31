"""Plain fork sync: merge Hermes upstream and refresh the pinned official TypeSafe reference."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess

FORK = "medking82/hermes-jev-skills"
UPSTREAM = "https://github.com/kerpopule/hermes-jev-skills.git"
WORKFLOW = "fork-sync-upstream.yml"
TEST_WORKFLOW = "test.yml"


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


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def sync(repo, *, upstream=UPSTREAM, official_upstream=None):
    """Merge Hermes upstream and refresh the official reference in the checkout; never push.

    The workflow pushes the result and starts `test.yml` for it. The local updater installs
    only a commit whose GitHub tests and local tests both pass.
    """
    import official
    base = commit(git(repo, "rev-parse", "HEAD"))
    git(repo, "fetch", "--no-tags", upstream, "main")
    latest = commit(git(repo, "rev-parse", "FETCH_HEAD"))
    if git(repo, "merge-base", "--is-ancestor", latest, base, check=False).returncode:
        result = git(repo, "merge", "--no-edit", latest, check=False)
        if result.returncode:
            git(repo, "merge", "--abort", check=False)
            raise StopUpdate("upstream merge conflict; fork main was not changed")
    reference = official.refresh(repo, upstream=official_upstream or official.URL)
    if reference["changed"]:
        git(repo, "add", "--", official.SNAPSHOT)
        git(repo, "commit", "-m", "Update Official TypeSafe Skill Reference")
    head = commit(git(repo, "rev-parse", "HEAD"))
    return {"base": base, "head": head, "upstream": latest, "official": reference["commit"],
            "changed": "true" if head != base else "false"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["sync"])
    parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    try:
        result = sync(repo)
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
                stream.write("changed=" + result["changed"] + "\n")
        print(json.dumps(result))
        return 0
    except (OSError, ValueError, StopUpdate, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "stopped", "reason": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
