"""Portable entrypoint for the installed Codex Jev skill."""
import os
from pathlib import Path
import sys

home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
toolkit = Path(os.environ.get("JEV_TOOLKIT_ROOT", str(home / "tools" / "hermes-jev-skills")))
if not (toolkit / "jevkit" / "__init__.py").is_file():
    print('{"status":"fail_open","reason_code":"toolkit_missing"}')
    raise SystemExit(0)
sys.path.insert(0, str(toolkit))
if len(sys.argv) > 1 and sys.argv[1] in {"select", "design", "decision", "hook", "catalog", "status"}:
    from jevkit.codex import main
else:
    # Keep the complete upstream command surface without loading eleven skills.
    from jevkit.cli import main
raise SystemExit(main())
