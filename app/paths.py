from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    """
    True when running from a frozen executable (e.g. PyInstaller).
    """
    return bool(getattr(sys, "frozen", False))


def _bundle_dir() -> Path | None:
    """
    When frozen (PyInstaller), sys._MEIPASS points to the extraction/bundle directory.
    For onedir builds, this is commonly the `_internal/` directory.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        try:
            return Path(meipass).resolve()
        except Exception:
            return Path(meipass)
    return None


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
    # Prefer `static/` next to the executable (best for editable assets in onedir).
    p = project_root_path / "static"
    if p.exists():
        return p

    # Common PyInstaller onedir layout: dist/AppName/_internal/static
    p2 = project_root_path / "_internal" / "static"
    if p2.exists():
        return p2

    # Fallback: PyInstaller bundle/extraction directory.
    b = _bundle_dir()
    if b is not None:
        p3 = b / "static"
        if p3.exists():
            return p3

    return p


