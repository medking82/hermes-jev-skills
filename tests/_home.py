"""A throwaway home folder that every platform agrees is the home folder.

POSIX reads HOME. Windows ignores it: Path.home() and expanduser read USERPROFILE, then
HOMEDRIVE + HOMEPATH. A test that set HOME alone sent a Windows run of the installer tests into
the real profile, where it installed the skills, the lane agents and the CLAUDE.md block for real.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict


def home_env(home) -> Dict[str, str]:
    """Every variable the platform reads to find the home folder, pointed at ``home``."""
    drive, rest = os.path.splitdrive(str(home))
    return {"HOME": str(home), "USERPROFILE": str(home), "HOMEDRIVE": drive, "HOMEPATH": rest}


def assert_home_is(home) -> None:
    """Refuse to go on unless both ways code finds home land on ``home``."""
    want = Path(home).resolve()
    for found in (Path.home(), Path(os.path.expanduser("~"))):
        if found.resolve() != want:
            raise AssertionError(f"home resolves to {found}, not the throwaway {want}; "
                                 "going on would write to the real home")
