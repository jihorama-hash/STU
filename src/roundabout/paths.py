"""Project path resolution without machine-specific absolute paths."""

from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    override = os.environ.get("ROUNDABOUT_PROJECT_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def resolve_project_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (project_root() / path).resolve()


def display_project_path(value: str | Path) -> str:
    """Return a lexical project-relative path, or an absolute path if external.

    Unlike ``Path.resolve``, ``abspath`` normalizes ``..`` without following
    symlinks, so paths under a project symlink keep their project alias.
    """
    path = Path(value).expanduser()
    root = project_root()
    lexical_path = Path(os.path.abspath(path if path.is_absolute() else root / path))
    lexical_root = Path(os.path.abspath(root))
    try:
        return lexical_path.relative_to(lexical_root).as_posix()
    except ValueError:
        return str(lexical_path)
