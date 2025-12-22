from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    """
    True when running from a frozen executable (e.g. PyInstaller).
    """
    return bool(getattr(sys, "frozen", False))


def project_root() -> Path:
    """
    Return the persistent root directory used for config/pid/custom files.

    - dev: current working directory
    - frozen: directory containing the executable (stable for double-click / shortcuts)
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def static_dir(project_root_path: Path) -> Path:
    """
    Return directory that contains `static/` files.

    For the onedir distribution we want `static/` next to the executable, so this
    is simply `${project_root}/static`.
    """
    return project_root_path / "static"


