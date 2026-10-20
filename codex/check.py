"""Run the Codex checks without exposing the workstation's real agent homes."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true", help="Full upstream suite on its supported Unix platforms")
    args = parser.parse_args()
    if args.full and os.name == "nt":
        parser.error("The full upstream suite is Unix-specific; use the native Codex checks on Windows")
    repo = Path(__file__).resolve().parents[1]
    patterns = ["test_codex*.py", "test_turn.py", "test_skill_stage2_eval.py", "test_skill_suggestion_reachable.py"]
    commands = [[sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-p", p] for p in patterns]
    if args.full:
        commands = [[sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests"],
                    [sys.executable, "-B", "-m", "unittest", "discover", "-s", "router-dashboard/tests"]]
    commands.append([sys.executable, "-B", "scripts/check_release.py"])
    denylist = os.environ.get("JEV_RELEASE_DENYLIST", str(Path.home() / ".config/jev/release-denylist.txt"))
    with tempfile.TemporaryDirectory(prefix="codex-check-profile-", dir=repo / "tests") as temporary:
        profile = Path(temporary)
        env = dict(os.environ)
        env.update(HOME=str(profile), USERPROFILE=str(profile), CODEX_HOME=str(profile / ".codex"),
                   HERMES_HOME=str(profile / ".hermes"), XDG_CONFIG_HOME=str(profile / ".config"),
                   PYTHONUTF8="1", JEV_RELEASE_DENYLIST=denylist)
        for key in ("TYPESAFE_API_KEY", "OPENROUTER_API_KEY", "VENICE_API_KEY", "OPENCODE_API_KEY", "JEV_PROXY_API_KEY"):
            env.pop(key, None)
        for command in commands:
            result = subprocess.run(command, cwd=repo, env=env, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace",
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            print(result.stdout, end="", flush=True)
            print(result.stderr, end="", file=sys.stderr, flush=True)
            if result.returncode:
                return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
