"""Notebook session: shared-server manners, house style, per-user seeds, and the progress log.

``st.init("M01")`` runs once at the top of every notebook. It

1. pins GMT and matplotlib to this environment and to writable folders (before pygmt or
   matplotlib is imported),
2. caps threads (environment variables + threadpoolctl; torch only if it is already loaded),
3. sets a soft memory cap (Linux only; an existing limit is never raised above its hard limit),
4. applies the house plotting style, and
5. prints a short report (no secrets, no host names).
"""
from __future__ import annotations

import datetime as _dt
import getpass
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import _paths

__all__ = [
    "Session",
    "init",
    "current",
    "server_rules",
    "gmt_guard",
    "mpl_guard",
    "seed_for",
    "user_name",
    "log_event",
    "read_log",
    "now_iso",
    "release_version",
]

THREAD_VARS = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)
_GB = 1024 ** 3


# ----------------------------------------------------------------------------- small helpers
def now_iso() -> str:
    """Local time with its UTC offset, e.g. ``2026-11-16T14:03:12+09:00``."""
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def user_name() -> str:
    """Login name (``SGTL_USER`` overrides it, e.g. in tests)."""
    env = os.environ.get("SGTL_USER", "").strip()
    if env:
        return env
    try:
        return getpass.getuser()
    except Exception:
        return os.environ.get("USER") or os.environ.get("LOGNAME") or "student"


def seed_for(user: str, task: str, reroll: int = 0) -> int:
    """Seed for synthetic cases: the first 4 bytes of sha256("user:task:reroll") as an integer."""
    digest = hashlib.sha256(f"{user}:{task}:{int(reroll)}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big")


def release_version(repo: Optional[Path] = None) -> str:
    """Release of this checkout (``.sgtl/release.json``), else the package version."""
    from . import __version__

    repo = repo or _paths.find_repo()
    if repo is not None:
        rel = Path(repo) / ".sgtl" / "release.json"
        try:
            v = json.loads(rel.read_text(encoding="utf-8")).get("version")
            if v:
                return str(v)
        except (OSError, ValueError, AttributeError):
            pass
    return __version__


def _writable_dir(path: Path) -> bool:
    """True when we can create ``path`` (if needed) and write a file inside it."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path, prefix=".sgtl-probe-"):
            pass
        return True
    except OSError:
        return False


def _private_tmp(name: str) -> Path:
    uid = os.getuid() if hasattr(os, "getuid") else 0
    p = Path(tempfile.gettempdir()) / f"sgtl-{uid}" / name
    p.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p.parent, 0o700)
    except OSError:
        pass
    return p


# ----------------------------------------------------------------------------- guards
def _env_libgmt() -> Optional[Path]:
    prefix = Path(sys.prefix)
    for cand in (prefix / "lib" / "libgmt.so", prefix / "lib" / "libgmt.dylib",
                 prefix / "Library" / "bin" / "gmt.dll"):
        if cand.exists():
            return cand
    return None


def gmt_guard() -> Dict[str, str]:
    """Make pygmt load THIS environment's GMT and write its session files somewhere writable.

    Must run before ``import pygmt``. Returns the environment variables it set.
    """
    changed: Dict[str, str] = {}
    lib = _env_libgmt()
    if lib is not None and not os.environ.get("GMT_LIBRARY_PATH"):
        os.environ["GMT_LIBRARY_PATH"] = changed["GMT_LIBRARY_PATH"] = str(lib.parent)
    bindir = str(Path(sys.prefix) / ("Library/bin" if os.name == "nt" else "bin"))
    path_parts = os.environ.get("PATH", "").split(os.pathsep)
    if Path(bindir).is_dir() and bindir not in path_parts:
        os.environ["PATH"] = changed["PATH"] = os.pathsep.join([bindir] + [p for p in path_parts if p])
    if not os.environ.get("GMT_SESSIONDIR") or not os.environ.get("GMT_USERDIR"):
        if not _writable_dir(Path.home() / ".gmt"):
            for var, sub in (("GMT_SESSIONDIR", "gmt_sessions"), ("GMT_USERDIR", "gmt_user")):
                if not os.environ.get(var):
                    os.environ[var] = changed[var] = str(_private_tmp(sub))
    return changed


def mpl_guard() -> Dict[str, str]:
    """Point MPLCONFIGDIR to a writable folder when ~/.config/matplotlib is not writable.

    Must run before ``import matplotlib``.
    """
    changed: Dict[str, str] = {}
    if not os.environ.get("MPLCONFIGDIR"):
        default = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "matplotlib"
        if not _writable_dir(default):
            os.environ["MPLCONFIGDIR"] = changed["MPLCONFIGDIR"] = str(_private_tmp("mpl"))
    return changed


def _set_thread_env(cores: int) -> None:
    for var in THREAD_VARS:
        cur = os.environ.get(var, "").strip()
        try:
            too_many = int(cur) > cores or int(cur) < 1
        except ValueError:
            too_many = True  # unset or unreadable
        if too_many:
            os.environ[var] = str(cores)
    os.environ.setdefault("NUMPY_MADVISE_HUGEPAGE", "0")


def _numpy_hugepage(set_to: Optional[bool] = None) -> Optional[bool]:
    """Read (and optionally set) numpy's huge-page madvise switch. None when unknown."""
    try:
        import numpy as np

        mod = getattr(getattr(np, "_core", None), "multiarray", None) or np.core.multiarray
        fn = getattr(mod, "_set_madvise_hugepage", None)
        if fn is None:
            return None
        prev = bool(fn(False))
        fn(prev if set_to is None else bool(set_to))
        return prev if set_to is None else bool(set_to)
    except Exception:
        return None


def _apply_memory_cap(mem_gb: Optional[float]) -> Optional[float]:
    """Soft RLIMIT_DATA = mem_gb when currently unlimited. Returns the soft limit in GB (None = none)."""
    try:
        import resource
    except ImportError:
        return None
    if not sys.platform.startswith("linux"):
        return None
    soft, hard = resource.getrlimit(resource.RLIMIT_DATA)
    if mem_gb and soft == resource.RLIM_INFINITY:
        new_soft = int(float(mem_gb) * _GB)
        if hard != resource.RLIM_INFINITY:
            new_soft = min(new_soft, hard)
        try:
            resource.setrlimit(resource.RLIMIT_DATA, (new_soft, hard))
            soft = new_soft
        except (ValueError, OSError):
            pass
    return None if soft == resource.RLIM_INFINITY else round(soft / _GB, 2)


def _rlimit_gb(name: str) -> Optional[float]:
    try:
        import resource

        soft, _hard = resource.getrlimit(getattr(resource, name))
    except Exception:
        return None
    return None if soft == resource.RLIM_INFINITY else round(soft / _GB, 2)


def _mem_available_gb() -> Optional[float]:
    try:
        with open("/proc/meminfo", encoding="ascii") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return round(int(line.split()[1]) * 1024 / _GB, 1)
    except (OSError, ValueError, IndexError):
        pass
    return None


def _cpus_allowed() -> int:
    try:
        return len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return os.cpu_count() or 1


def _env_int(var: str) -> Optional[int]:
    try:
        return int(os.environ[var])
    except (KeyError, ValueError):
        return None


def server_rules() -> Dict[str, Any]:
    """Live thread, memory and CPU state of this Python process (used in M00).

    Memory limits are in GB; ``None`` means "no limit set" (or "not available on this system").
    """
    pools: List[Dict[str, Any]] = []
    try:
        from threadpoolctl import threadpool_info

        for info in threadpool_info():
            pools.append({
                "library": info.get("internal_api"),
                "user_api": info.get("user_api"),
                "prefix": info.get("prefix"),
                "num_threads": info.get("num_threads"),
            })
    except Exception:
        pass
    try:
        load1 = round(os.getloadavg()[0], 2)
    except (AttributeError, OSError):
        load1 = None
    return {
        "omp_threads": _env_int("OMP_NUM_THREADS"),
        "openblas_threads": _env_int("OPENBLAS_NUM_THREADS"),
        "mkl_threads": _env_int("MKL_NUM_THREADS"),
        "numexpr_threads": _env_int("NUMEXPR_NUM_THREADS"),
        "threadpools": pools,
        "numpy_madvise_hugepage": os.environ.get("NUMPY_MADVISE_HUGEPAGE"),
        "numpy_hugepage_active": _numpy_hugepage(),
        "rlimit_data_gb": _rlimit_gb("RLIMIT_DATA"),
        "rlimit_as_gb": _rlimit_gb("RLIMIT_AS"),
        "cpus_allowed": _cpus_allowed(),
        "cpus_total": os.cpu_count(),
        "load_avg_1min": load1,
        "mem_available_gb": _mem_available_gb(),
    }


# ----------------------------------------------------------------------------- progress log
def read_log(repo: Optional[Path] = None) -> List[Dict[str, Any]]:
    """All events in ``<repo>/work/.sgtl/progress.jsonl`` (broken lines are skipped)."""
    path = _paths.progress_path(repo)
    events: List[Dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if isinstance(ev, dict):
                    events.append(ev)
    except OSError:
        pass
    return events


def log_event(event: str, task: str, *, status: Optional[str] = None, attempt: Optional[int] = None,
              seed: Optional[int] = None, category: Optional[str] = None, text: Optional[str] = None,
              repo: Optional[Path] = None, **extra: Any) -> Dict[str, Any]:
    """Append one JSON line to the progress log and return the record."""
    repo = repo or _paths.repo_root()
    rec: Dict[str, Any] = {
        "ts": now_iso(),
        "user": user_name(),
        "module": task.split("-")[0] if task else None,
        "task": task,
        "event": event,
        "status": status,
        "attempt": attempt,
        "seed": seed,
        "category": category,
        "release": release_version(repo),
    }
    if text is not None:
        rec["text"] = text
    rec.update(extra)
    path = _paths.progress_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


# ----------------------------------------------------------------------------- session
@dataclass
class Session:
    """What ``st.init`` set up. Kept alive so the thread limits stay in force."""

    module: Optional[str]
    cores: int = 1
    mem_gb: Optional[float] = 16
    user: str = field(default_factory=user_name)
    repo: Optional[Path] = None
    release: str = ""
    started: str = field(default_factory=now_iso)
    mem_cap_gb: Optional[float] = None
    env_changes: Dict[str, str] = field(default_factory=dict)
    report: str = ""
    _limiter: Any = field(default=None, repr=False)

    @property
    def strict(self) -> bool:
        return os.environ.get("SGTL_STRICT", "") == "1"

    def seed(self, task: str, reroll: int = 0) -> int:
        return seed_for(self.user, task, reroll)

    def rng(self, task: str, reroll: int = 0):
        from .synth import rng_for

        return rng_for(self.user, task, reroll)


_CURRENT: Optional[Session] = None


def current() -> Session:
    """The session from ``st.init``; a quiet default one when init was not called."""
    global _CURRENT
    if _CURRENT is None:
        repo = _paths.find_repo()
        _CURRENT = Session(module=None, repo=repo, release=release_version(repo))
    return _CURRENT


def _git_short(repo: Optional[Path]) -> Optional[str]:
    if repo is None or not (Path(repo) / ".git").exists():
        return None
    try:
        out = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def init(module_id: str, *, cores: int = 1, mem_gb: Optional[float] = 16, quiet: bool = False) -> Session:
    """Set up this notebook: thread and memory caps, house style, seeds; print a short report.

    Parameters
    ----------
    module_id : the module, e.g. ``"M01"``.
    cores : how many CPU cores this notebook may use (1 for normal work, at most 4 for heavy runs).
    mem_gb : soft memory cap in GB (Linux). ``None`` or 0 leaves memory limits alone.
    """
    global _CURRENT
    cores = max(1, int(cores))
    changes: Dict[str, str] = {}
    changes.update(gmt_guard())
    changes.update(mpl_guard())
    _set_thread_env(cores)

    limiter = None
    try:
        from threadpoolctl import threadpool_limits

        limiter = threadpool_limits(limits=cores)
    except Exception:
        pass
    if "torch" in sys.modules:
        try:
            sys.modules["torch"].set_num_threads(cores)
        except Exception:
            pass
    _numpy_hugepage(False)
    cap = _apply_memory_cap(mem_gb)

    style_note = ""
    try:
        from . import plot

        style_note = plot.use_house_style(quiet=True)
    except Exception as exc:  # matplotlib missing or broken: keep going
        style_note = f"house style not applied ({type(exc).__name__})"

    repo = _paths.find_repo()
    sess = Session(module=module_id, cores=cores, mem_gb=mem_gb, repo=repo,
                   release=release_version(repo), mem_cap_gb=cap, env_changes=changes,
                   _limiter=limiter)
    _CURRENT = sess

    from . import __version__

    commit = _git_short(repo)
    data = _paths.data_root()
    mem_now = _mem_available_gb()
    lines = [
        f"SGTL tutorial · module {module_id} · sgtl-tutorial {__version__} (release {sess.release})",
        f"Python {platform.python_version()} · user {sess.user}"
        + (f" · repository commit {commit}" if commit else (" · repository found" if repo else
                                                           " · repository NOT found (set SGTL_REPO)")),
        f"Threads: {cores} per library (OpenMP, OpenBLAS, MKL, NumExpr) · CPUs this process may use: "
        f"{_cpus_allowed()} of {os.cpu_count()}",
        "Memory cap: " + (f"{cap:g} GB (soft limit)" if cap else "none set")
        + (f" · available on the server now: {mem_now:g} GB" if mem_now is not None else ""),
        f"Data folder: {_paths.short_path(data)}" + ("" if data.exists() else " (not created yet)"),
        "Practice cases: seeded per user and task (st.reroll(task) gives new ones)",
        f"Plot style: {style_note}",
    ]
    lib = _env_libgmt()
    gmt_path = os.environ.get("GMT_LIBRARY_PATH", "")
    if lib is not None and gmt_path and Path(gmt_path).resolve() != lib.parent.resolve():
        lines.append("Warning: GMT_LIBRARY_PATH points to a GMT outside this environment; maps may break. "
                     "Run 'sgtl doctor' in a terminal.")
    elif lib is not None:
        lines.append("GMT: pinned to this environment's GMT library")
    if os.environ.get("LD_LIBRARY_PATH"):
        lines.append("Warning: LD_LIBRARY_PATH is set; it can make Python load the wrong libraries. "
                     "Start Jupyter from a shell without it.")
    sess.report = "\n".join(lines[:10])
    if not quiet:
        print(sess.report)
    return sess
