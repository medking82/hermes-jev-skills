"""Pin TypeSafe's official skill as bounded, non-discoverable reference data."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from upstream import StopUpdate, commit, git, require_ancestor

REPOSITORY = "typesafe-ai/skills"
URL = "https://github.com/" + REPOSITORY + ".git"
DIRECTORY = "skills/typesafe-ai"
SNAPSHOT = "vendor/typesafe-ai"
REF = "refs/jev-sync/official"
ATTRIBUTES = b"* -text\n"
MAX_FILE = 256 * 1024
MAX_TOTAL = 1024 * 1024
MAX_FILES = 32


def allowed(name):
    if name in {"SKILL.md", "LICENSE"}:
        return True
    return (name.startswith("references/") and name.endswith(".md")
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", name) is not None
            and all(part not in {"", ".", ".."} and not part.endswith(".")
                    and part.upper().split(".")[0] not in {"CON", "PRN", "AUX", "NUL", *["COM" + str(i) for i in range(1, 10)], *["LPT" + str(i) for i in range(1, 10)]}
                    for part in name.split("/"))
            and name.rsplit("/", 1)[-1].lower() != "skill.md")


def validate_files(files):
    if not {"SKILL.md", "LICENSE"}.issubset(files) or len(files) > MAX_FILES:
        raise StopUpdate("official skill files are missing or exceed the reference limit")
    if len({name.casefold() for name in files}) != len(files):
        raise StopUpdate("case-colliding official reference paths")
    total = 0
    for name, content in files.items():
        if not allowed(name) or len(content) > MAX_FILE or b"\0" in content:
            raise StopUpdate("official skill added unsupported content; manual review required")
        content.decode("utf-8")
        total += len(content)
    if total > MAX_TOTAL:
        raise StopUpdate("official reference package exceeds the size limit")
    text = files["SKILL.md"].decode("utf-8")
    if (not text.startswith("---\n") or len(text.split("---", 2)) != 3
            or not re.search(r"(?m)^name: typesafe-ai\s*$", text.split("---", 2)[1])
            or not re.search(r"(?m)^license: MIT\s*$", text.split("---", 2)[1])):
        raise StopUpdate("official skill identity or license changed; manual review required")
    if not files["LICENSE"].startswith(b"MIT License") or b"Permission is hereby granted" not in files["LICENSE"]:
        raise StopUpdate("official license changed; manual review required")


def git_files(repo, revision, prefix, *, snapshot=False):
    """Read immutable blobs, refusing links, executables and unsupported file names."""
    revision = commit(revision)
    result = git(repo, "ls-tree", "-r", "-l", "-z", revision, "--", prefix + "/", check=False)
    if result.returncode:
        raise StopUpdate("cannot inspect official reference tree")
    files = {}
    entries = result.stdout.split("\0")
    if len(entries) > MAX_FILES + 3:
        raise StopUpdate("official reference tree exceeds the file limit")
    total = 0
    for entry in entries:
        if not entry:
            continue
        header, path = entry.split("\t", 1)
        mode, kind, blob, size = header.split()
        name = path[len(prefix) + 1:]
        meta = snapshot and name in {"source.json", ".gitattributes"}
        if mode != "100644" or kind != "blob" or (not meta and not allowed(name)):
            raise StopUpdate("official reference contains executable, linked or unsupported files")
        if not size.isdecimal() or int(size) > MAX_FILE:
            raise StopUpdate("official reference file exceeds the size limit")
        total += int(size)
        if total > MAX_TOTAL:
            raise StopUpdate("official reference package exceeds the size limit")
        process = subprocess.run(["git", "cat-file", "blob", blob], cwd=repo, capture_output=True,
                                 timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if process.returncode or len(process.stdout) != int(size):
            raise StopUpdate("official reference blob could not be read")
        files[name] = process.stdout
    return files


def source(repo, revision):
    files = git_files(repo, revision, DIRECTORY)
    validate_files(files)
    return files


def metadata(revision, files):
    return {"repository": REPOSITORY, "directory": DIRECTORY, "commit": commit(revision),
            "files": {name: hashlib.sha256(content).hexdigest() for name, content in sorted(files.items())}}


def validate_snapshot(files):
    files = dict(files)
    if files.pop(".gitattributes", None) != ATTRIBUTES:
        raise StopUpdate("official snapshot byte-preservation policy changed")
    raw = files.pop("source.json", None)
    if raw is None:
        raise StopUpdate("official reference provenance is missing")
    info = json.loads(raw)
    if not isinstance(info, dict):
        raise StopUpdate("official reference provenance must be an object")
    validate_files(files)
    if info != metadata(info.get("commit"), files):
        raise StopUpdate("official reference provenance or file hashes do not match")
    return info, files


def checkout(repo):
    root = Path(repo) / SNAPSHOT
    if not root.is_dir() or any(path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 1024
                              for path in (root, root.parent)):
        raise StopUpdate("official reference snapshot is missing or linked")
    files = {}
    for path in root.rglob("*"):
        if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 1024:
            raise StopUpdate("linked official snapshot path")
        if path.is_file():
            if path.stat().st_size > MAX_FILE or len(files) >= MAX_FILES + 2:
                raise StopUpdate("official snapshot exceeds its bounds")
            files[path.relative_to(root).as_posix()] = path.read_bytes()
    return validate_snapshot(files)


def at_revision(repo, revision):
    return validate_snapshot(git_files(repo, revision, SNAPSHOT, snapshot=True))


def refresh(repo, *, upstream=URL):
    """Update only an intact snapshot; never install or execute downloaded content."""
    root = Path(repo) / SNAPSHOT
    prior, old_files = checkout(repo) if root.exists() else (None, {})
    git(repo, "fetch", "--no-tags", upstream, "main:" + REF)
    revision = commit(git(repo, "rev-parse", REF))
    if prior:
        require_ancestor(repo, prior["commit"], revision)
    files = source(repo, revision)
    info = metadata(revision, files)
    if info == prior:
        return dict(info, changed=False)
    root.mkdir(parents=True, exist_ok=True)
    # Existing files were fully verified before touching this owned subtree.
    (root / ".gitattributes").write_bytes(ATTRIBUTES)
    for name, content in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    for name in old_files.keys() - files.keys():
        (root / name).unlink()
    # Metadata is also byte-stable when Windows and GitHub runners alternate.
    (root / "source.json").write_bytes((json.dumps(info, indent=2) + "\n").encode("utf-8"))
    return dict(info, changed=True)


def verify_live(repo, *, upstream=URL):
    """Verify the pinned snapshot against actual upstream Git objects, without changing it."""
    info, files = checkout(repo)
    git(repo, "fetch", "--no-tags", upstream, info["commit"])
    if source(repo, info["commit"]) != files:
        raise StopUpdate("snapshot differs from its official upstream commit")
    return info


def reference_files(repo):
    info, files = checkout(repo)
    body = files.pop("SKILL.md").decode("utf-8").split("---", 2)[2].lstrip()
    header = ("# Official TypeSafe Skill Reference\n\n"
              "Source: `typesafe-ai/skills`, `skills/typesafe-ai`, commit `" + info["commit"] + "`.\n"
              "This reference is subordinate to the Jev umbrella's scope and authorization rules. "
              "It enables no new provider, model, retry loop, hook, worker or tool permission.\n\n")
    files["guide.md"] = (header + body).encode("utf-8")
    files["source.json"] = (json.dumps(info, indent=2) + "\n").encode("utf-8")
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["refresh", "verify"])
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    try:
        info = refresh(repo) if args.mode == "refresh" else (verify_live(repo) if args.live else checkout(repo)[0])
        print(json.dumps(info))
        return 0
    except (OSError, ValueError, TypeError, StopUpdate, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "stopped", "reason": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
