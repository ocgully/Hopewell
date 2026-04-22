"""Git post-commit hook installer.

On every commit, scans the commit message for node-id references
(`HW-0042` style) and `close <id>` or `fixes <id>` triggers. The hook
touches affected nodes and regenerates views. Deterministic + fast.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Optional


MARKER_BEGIN = "# --- hopewell hook (managed; do not edit this block) ---"
MARKER_END = "# --- /hopewell hook ---"

HOOK_BODY = r"""
# Hopewell post-commit: scan last commit for node refs; touch + re-render.
COMMIT_MSG=$(git log -1 --pretty=%B 2>/dev/null)
if [ -n "$COMMIT_MSG" ]; then
  if command -v hopewell >/dev/null 2>&1; then
    hopewell hook-on-commit --message "$COMMIT_MSG" --commit "$(git rev-parse HEAD)" --quiet || true
  elif command -v python >/dev/null 2>&1; then
    python -m hopewell hook-on-commit --message "$COMMIT_MSG" --commit "$(git rev-parse HEAD)" --quiet 2>/dev/null || true
  fi
fi
"""


def _git_dir(project_root: Path) -> Optional[Path]:
    candidate = project_root / ".git"
    if candidate.is_dir():
        return candidate
    if candidate.is_file():
        content = candidate.read_text(encoding="utf-8").strip()
        if content.startswith("gitdir:"):
            return Path(content.split(":", 1)[1].strip()).resolve()
    return None


def _hook_path(project_root: Path) -> Path:
    gd = _git_dir(project_root)
    if gd is None:
        raise RuntimeError("not inside a git working tree (no .git directory found)")
    hooks_dir = gd / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    return hooks_dir / "post-commit"


def install(project_root: Path) -> Path:
    hp = _hook_path(project_root)
    existing = hp.read_text(encoding="utf-8") if hp.is_file() else ""
    if MARKER_BEGIN in existing:
        start = existing.index(MARKER_BEGIN)
        end = existing.index(MARKER_END, start) + len(MARKER_END)
        existing = existing[:start] + existing[end:]

    if not existing.startswith("#!"):
        existing = "#!/usr/bin/env bash\n" + existing

    block = f"\n{MARKER_BEGIN}\n{HOOK_BODY}\n{MARKER_END}\n"
    hp.write_text(existing.rstrip() + "\n" + block, encoding="utf-8")
    try:
        hp.chmod(hp.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass
    return hp


def uninstall(project_root: Path) -> bool:
    hp = _hook_path(project_root)
    if not hp.is_file():
        return False
    text = hp.read_text(encoding="utf-8")
    if MARKER_BEGIN not in text:
        return False
    start = text.index(MARKER_BEGIN)
    end = text.index(MARKER_END, start) + len(MARKER_END)
    new = text[:start].rstrip() + "\n" + text[end:].lstrip()
    if new.strip() in ("", "#!/usr/bin/env bash"):
        hp.unlink()
    else:
        hp.write_text(new, encoding="utf-8")
    return True
