"""Find the tutorial repository and the data folder.

Rules (plain words):

* The repository is the folder that holds ``pyproject.toml`` with ``name = "sgtl-tutorial"``.
  Set ``SGTL_REPO`` to point at it directly; otherwise the package looks upward from the
  current folder, then upward from where the package itself lives.
* The data root (large downloaded files, outside the repository) is ``SGTL_DATA`` when set,
  else ``~/sgtl/data``.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable, Optional

PROJECT_NAME = "sgtl-tutorial"

__all__ = [
    "PROJECT_NAME",
    "find_repo",
    "repo_root",
    "course_path",
    "data_root",
    "progress_path",
    "short_path",
]


def course_path(*parts: str, repo: Optional[Path] = None) -> Path:
    """Find a course asset in the student layout, with the instructor/older release path as fallback."""
    root = Path(repo) if repo is not None else repo_root()
    relative = Path(*parts)
    name = relative.as_posix()
    for previous, current in (
        ("checks", ".sgtl/checks"),
        ("criteria", ".sgtl/criteria"),
        ("glossary", "docs/resources/glossary"),
        ("references", "docs/resources/references"),
        ("templates/project", "docs/templates/project"),
    ):
        if name == previous or name.startswith(previous + "/"):
            mapped = root / (current + name[len(previous):])
            if mapped.exists():
                return mapped
            break
    legacy = root / relative
    if not legacy.exists() and (name == "templates/project" or name.startswith("templates/project/")):
        overlay = root / "student_overlay" / relative
        if overlay.exists():
            return overlay
    return legacy


def _project_name(pyproject: Path) -> Optional[str]:
    """Return ``[project].name`` from a pyproject.toml file, or None."""
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return None
    try:  # Python 3.11+
        import tomllib  # type: ignore[import-not-found]

        return tomllib.loads(text).get("project", {}).get("name")
    except ModuleNotFoundError:
        pass
    except Exception:
        return None
    # Python 3.10 without tomli: read the [project] table by hand.
    section = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line.strip("[] ").strip()
            continue
        if section == "project":
            m = re.match(r"""name\s*=\s*["']([^"']+)["']""", line)
            if m:
                return m.group(1)
    return None


def _is_repo(path: Path) -> bool:
    return (path / "pyproject.toml").is_file() and _project_name(path / "pyproject.toml") == PROJECT_NAME


def _walk_up(start: Path) -> Iterable[Path]:
    start = start.resolve()
    yield start
    yield from start.parents


def find_repo() -> Optional[Path]:
    """Return the tutorial repository folder, or None when it cannot be found."""
    env = os.environ.get("SGTL_REPO", "").strip()
    if env:
        p = Path(env).expanduser()
        if p.is_dir():
            return p.resolve()
    starts = []
    try:
        starts.append(Path.cwd())
    except OSError:  # cwd deleted
        pass
    starts.append(Path(__file__).resolve().parent)
    for start in starts:
        for cand in _walk_up(start):
            if _is_repo(cand):
                return cand
    return None


def repo_root(required: bool = True) -> Optional[Path]:
    """Like :func:`find_repo`, but raise a plain-language error when ``required``."""
    repo = find_repo()
    if repo is None and required:
        raise RuntimeError(
            "Could not find the tutorial repository (a folder whose pyproject.toml says "
            f'name = "{PROJECT_NAME}"). Open the notebook from inside your clone, or set '
            "the environment variable SGTL_REPO to the clone's folder."
        )
    return repo


def data_root() -> Path:
    """Folder for large data files: ``$SGTL_DATA`` or ``~/sgtl/data``."""
    env = os.environ.get("SGTL_DATA", "").strip()
    return Path(env).expanduser() if env else Path.home() / "sgtl" / "data"


def progress_path(repo: Optional[Path] = None) -> Path:
    """The progress log ``<repo>/work/.sgtl/progress.jsonl``."""
    repo = repo or repo_root()
    return Path(repo) / "work" / ".sgtl" / "progress.jsonl"


def short_path(path: os.PathLike | str) -> str:
    """Show a path with the home folder written as ``~`` (keeps printed output free of user paths)."""
    p = str(path)
    home = str(Path.home())
    if home and home != "/" and (p == home or p.startswith(home + os.sep)):
        return "~" + p[len(home):]
    return p
