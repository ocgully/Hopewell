"""Project-root and `.hopewell/` discovery."""
from __future__ import annotations

from pathlib import Path
from typing import Optional


MARKER = ".hopewell"


def find_project_root(start: Optional[Path] = None) -> Optional[Path]:
    """Walk upward from `start` (or cwd) until a `.hopewell/` dir is found.

    Returns None if not inside an initialised project.
    """
    cur = (start or Path.cwd()).resolve()
    for candidate in (cur, *cur.parents):
        if (candidate / MARKER).is_dir():
            return candidate
    return None


def require_project_root(start: Optional[Path] = None) -> Path:
    root = find_project_root(start)
    if root is None:
        raise FileNotFoundError(
            f"not inside a Hopewell project — no `{MARKER}/` directory found "
            f"walking up from {(start or Path.cwd()).resolve()}. Run `hopewell init` first."
        )
    return root


def hw_dir(project_root: Path) -> Path:
    return project_root / MARKER


def ensure_hw_dir(project_root: Path) -> Path:
    d = hw_dir(project_root)
    d.mkdir(parents=True, exist_ok=True)
    (d / "nodes").mkdir(exist_ok=True)
    (d / "views").mkdir(exist_ok=True)
    (d / "orchestrator").mkdir(exist_ok=True)
    (d / "orchestrator" / "runs").mkdir(exist_ok=True)
    return d
