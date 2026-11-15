"""Command line tool ``sgtl`` (also ``python -m sgtl_tutorial.cli``).

Subcommands:

* ``sgtl doctor``          check this environment; every line is PASS, WARN or FAIL
* ``sgtl new M01``         copy the module notebook into ``work/`` once (never overwrites)
* ``sgtl status``          your progress table
* ``sgtl diff M01``        has the module template changed since you copied it?
* ``sgtl setup-ai``        show which tutor-rule files would be copied to ``~/.claude/``
  (``--apply`` copies them; existing files are never overwritten)
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from . import __version__, _paths
from .session import _env_libgmt, _mem_available_gb, gmt_guard, mpl_guard, now_iso, release_version

MODULE_RE = re.compile(r"^M\d{2}$")
REQUIRED = ["numpy", "pandas", "matplotlib", "yaml", "threadpoolctl"]
COURSE = ["scipy", "pyproj", "obspy", "cartopy", "pygmt", "jupyterlab", "ipywidgets", "ipympl", "jupytext",
          "seisbench", "torch", "pyocto", "seismostats"]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rel(path: Path, repo: Path) -> str:
    try:
        return path.relative_to(repo).as_posix()
    except ValueError:
        return _paths.short_path(path)


# ----------------------------------------------------------------------------- doctor
def _line(status: str, name: str, detail: str = "") -> Tuple[str, str]:
    text = f"{status:<4}  {name}" + (f": {detail}" if detail else "")
    print(text)
    return status, text


def _gmt_version_of_env() -> Optional[str]:
    gmt = Path(sys.prefix) / "bin" / "gmt"
    if not gmt.exists():
        return None
    env = dict(os.environ)
    env.pop("LD_LIBRARY_PATH", None)
    try:
        out = subprocess.run([str(gmt), "--version"], capture_output=True, text=True, timeout=30, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def _pygmt_version() -> Tuple[Optional[str], Optional[str]]:
    """(GMT version that pygmt loads, error text)."""
    try:
        import pygmt  # noqa: F401
        from pygmt import clib

        ver = getattr(clib, "__gmt_version__", None)
        if not ver:
            with clib.Session() as lib:
                ver = lib.info.get("version")
        return (str(ver) if ver else None), None
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {str(exc).splitlines()[0][:160] if str(exc) else ''}"


def doctor() -> int:
    results: List[Tuple[str, str]] = []
    add = results.append
    gmt_guard()
    mpl_guard()
    py = sys.version_info
    add(_line("PASS" if (3, 10) <= py[:2] <= (3, 12) else "WARN", "Python",
              f"{platform.python_version()}" + ("" if (3, 10) <= py[:2] <= (3, 12) else " (course uses 3.10-3.12)")))
    repo = _paths.find_repo()
    add(_line("PASS" if repo else "FAIL", "Tutorial repository",
              f"found (sgtl-tutorial {__version__}, release {release_version(repo)})" if repo
              else "not found: run sgtl from inside your clone, or set SGTL_REPO"))
    missing = [m for m in REQUIRED if importlib.util.find_spec(m) is None]
    add(_line("FAIL" if missing else "PASS", "Required packages",
              ("missing: " + ", ".join(missing)) if missing else ", ".join(REQUIRED)))
    missing = [m for m in COURSE if importlib.util.find_spec(m) is None]
    add(_line("WARN" if missing else "PASS", "Course packages",
              ("missing: " + ", ".join(missing) + " (run: sgtl-install env)") if missing else "all present"))
    add(_line("WARN" if os.environ.get("LD_LIBRARY_PATH") else "PASS", "LD_LIBRARY_PATH",
              "is set; it can make Python load the wrong GMT or BLAS libraries. Unset it before starting "
              "Jupyter (unset LD_LIBRARY_PATH)" if os.environ.get("LD_LIBRARY_PATH") else "not set"))
    lib = _env_libgmt()
    if importlib.util.find_spec("pygmt") is None:
        add(_line("WARN", "GMT/PyGMT", "pygmt is not installed in this environment"))
    else:
        loaded, err = _pygmt_version()
        env_ver = _gmt_version_of_env() if lib is not None else None
        if err:
            add(_line("FAIL", "GMT/PyGMT", f"pygmt could not load GMT ({err})"))
        elif lib is None:
            add(_line("WARN", "GMT/PyGMT", f"pygmt loads GMT {loaded}, but this environment has no GMT of its own"))
        elif env_ver and loaded and env_ver != loaded:
            add(_line("FAIL", "GMT/PyGMT", f"pygmt loads GMT {loaded}, but this environment's GMT is {env_ver}. "
                      "Start Python from the course environment with GMT_LIBRARY_PATH unset or pointing to it"))
        else:
            add(_line("PASS", "GMT/PyGMT", f"pygmt loads GMT {loaded} (this environment's GMT: {env_ver or 'unknown'})"))
    thread_vars = ["OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"]
    bad = []
    for v in thread_vars:
        try:
            if not 1 <= int(os.environ.get(v, "")) <= 4:
                bad.append(v)
        except ValueError:
            bad.append(v)
    add(_line("WARN" if bad else "PASS", "Thread limits in this shell",
              (", ".join(bad) + " not set to 1-4 (notebooks set them in st.init; for scripts, export them = 1)")
              if bad else "set"))
    hp = os.environ.get("NUMPY_MADVISE_HUGEPAGE")
    add(_line("PASS" if hp == "0" else "WARN", "NUMPY_MADVISE_HUGEPAGE",
              "0" if hp == "0" else "not 0 (st.init sets it; for scripts, export NUMPY_MADVISE_HUGEPAGE=0)"))
    data = _paths.data_root()
    add(_line("PASS" if data.is_dir() else "WARN", "Data folder",
              f"{_paths.short_path(data)}" + ("" if data.is_dir() else " missing (run: sgtl-install data)")))
    try:
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from jupyter_client.kernelspec import find_kernel_specs

            has = "sgtl" in find_kernel_specs()
        add(_line("PASS" if has else "WARN", "Jupyter kernel 'sgtl'",
                  "installed" if has else "missing (run: sgtl-install env)"))
    except Exception:
        add(_line("WARN", "Jupyter kernel 'sgtl'", "jupyter_client not available"))
    if repo is not None and shutil.which("git"):
        try:
            hooks = subprocess.run(["git", "-C", str(repo), "config", "core.hooksPath"], capture_output=True,
                                   text=True, timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            hooks = ""
        add(_line("PASS" if hooks == ".githooks" else "WARN", "Git hooks",
                  "on" if hooks == ".githooks" else "off (run: git config core.hooksPath .githooks)"))
    try:
        free = shutil.disk_usage(Path.home()).free / 1024 ** 3
        add(_line("PASS" if free >= 5 else "WARN", "Free disk space in home", f"{free:.0f} GB"))
    except OSError:
        pass
    try:
        from .plot import _available_family

        fam = _available_family()
        add(_line("PASS" if fam == "Helvetica" else "WARN", "Plot font",
                  fam if fam == "Helvetica" else f"Helvetica not found; using {fam}"))
    except Exception:
        add(_line("WARN", "Plot font", "matplotlib not available"))
    mem = _mem_available_gb()
    try:
        ncpu = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        ncpu = os.cpu_count() or 1
    add(_line("PASS", "Server resources", f"{ncpu} CPUs usable" + (f", {mem:g} GB memory available" if mem else "")))
    n_fail = sum(1 for s, _ in results if s == "FAIL")
    n_warn = sum(1 for s, _ in results if s == "WARN")
    print(f"\n{n_fail} FAIL, {n_warn} WARN. " + ("Fix the FAIL lines first." if n_fail else "Ready."))
    return 1 if n_fail else 0


# ----------------------------------------------------------------------------- new / diff / status
def _template(repo: Path, mid: str) -> Optional[Path]:
    cands = sorted(repo.glob(f"modules/{mid}_*/{mid}_*.ipynb"))
    return cands[0] if cands else None


def new(mid: str) -> int:
    mid = mid.upper()
    if not MODULE_RE.match(mid):
        print("Module ids look like M01.")
        return 2
    repo = _paths.repo_root()
    tpl = _template(repo, mid)
    if tpl is None:
        print(f"No notebook for {mid} under modules/ (is this module released yet?).")
        return 1
    dest = repo / "work" / tpl.parent.name / tpl.name
    if dest.exists():
        print(f"{_rel(dest, repo)} already exists; sgtl never overwrites your work. "
              f"To see what changed in the template: sgtl diff {mid}")
        return 1
    sha = _sha256(tpl)
    nb = json.loads(tpl.read_text(encoding="utf-8"))
    meta = nb.setdefault("metadata", {}).setdefault("sgtl", {})
    meta.update({"template_sha": sha, "template_path": _rel(tpl, repo), "copied_at": now_iso(),
                 "release_at_copy": release_version(repo)})
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"created  {_rel(dest, repo)}  (copy of {_rel(tpl, repo)}, template sha256 {sha[:12]})")
    ai_tpl = repo / "docs" / "templates" / "ai_log_template.md"
    ai = repo / "work" / "ai_log" / f"{mid}.md"
    if ai_tpl.is_file() and not ai.exists():
        ai.parent.mkdir(parents=True, exist_ok=True)
        text = ai_tpl.read_text(encoding="utf-8").replace("{{module}}", mid).replace("{{date}}", now_iso()[:10])
        ai.write_text(text, encoding="utf-8")
        print(f"created  {_rel(ai, repo)}  (your AI-use log for {mid})")
    print(f"Next: open {_rel(dest, repo)} in JupyterLab (kernel 'SGTL').")
    return 0


def diff(mid: str) -> int:
    mid = mid.upper()
    repo = _paths.repo_root()
    tpl = _template(repo, mid)
    mine = sorted(repo.glob(f"work/{mid}_*/{mid}_*.ipynb"))
    if tpl is None or not mine:
        print(f"Nothing to compare: {'no template' if tpl is None else 'no copy in work/ (run: sgtl new ' + mid + ')'}.")
        return 1
    try:
        stored = json.loads(mine[0].read_text(encoding="utf-8")).get("metadata", {}).get("sgtl", {})
    except ValueError:
        print(f"{_rel(mine[0], repo)} is not valid notebook JSON.")
        return 1
    if stored.get("template_sha") == _sha256(tpl):
        print(f"The {mid} template is unchanged since you copied it (release {stored.get('release_at_copy', '?')}).")
        return 0
    print(f"The {mid} template changed since you copied it.")
    print(f"Compare:  nbdiff {_rel(tpl, repo)} {_rel(mine[0], repo)}")
    print(f"   or in a browser:  nbdiff-web {_rel(tpl, repo)} {_rel(mine[0], repo)}")
    print("Copy the cells you need by hand; sgtl never edits your work.")
    return 0


def status() -> int:
    from .checks import progress

    df = progress()
    if df.empty:
        print("No tasks found yet.")
        return 0
    import pandas as pd

    with pd.option_context("display.width", 140, "display.max_colwidth", 40, "display.max_rows", 500):
        print(df.drop(columns=["last_activity"]).to_string(index=False))
    return 0


def setup_ai(apply: bool = False) -> int:
    repo = _paths.repo_root()
    src = repo / ".claude"
    dest = Path.home() / ".claude"
    if not src.is_dir():
        print("This repository has no .claude folder; nothing to set up.")
        return 1
    for f in sorted(p for p in src.rglob("*") if p.is_file()):
        rel = f.relative_to(src)
        target = dest / rel
        if rel.name.startswith("settings") and rel.suffix == ".json":
            print(f"skip        .claude/{rel.as_posix()}  (settings files are never copied)")
        elif target.exists():
            print(f"keep        ~/.claude/{rel.as_posix()}  (already exists; not overwritten)")
        elif apply:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
            print(f"copied      .claude/{rel.as_posix()} -> ~/.claude/{rel.as_posix()}")
        else:
            print(f"would copy  .claude/{rel.as_posix()} -> ~/.claude/{rel.as_posix()}")
    if not apply:
        print("Dry run: nothing was copied. Run 'sgtl setup-ai --apply' to copy these files.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="sgtl", description="SGTL earthquake source tutorial helper.")
    parser.add_argument("--version", action="version", version=f"sgtl-tutorial {__version__}")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("doctor", help="check this environment (PASS/WARN/FAIL lines)")
    p = sub.add_parser("new", help="copy a module notebook into work/ (never overwrites)")
    p.add_argument("module", help="module id, e.g. M01")
    sub.add_parser("status", help="show your progress table")
    p = sub.add_parser("diff", help="has the module template changed since you copied it?")
    p.add_argument("module")
    p = sub.add_parser("setup-ai", help="copy tutor rules into ~/.claude/ (dry run unless --apply)")
    p.add_argument("--apply", action="store_true", help="really copy (existing files are kept)")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "doctor":
            return doctor()
        if args.cmd == "new":
            return new(args.module)
        if args.cmd == "status":
            return status()
        if args.cmd == "diff":
            return diff(args.module)
        if args.cmd == "setup-ai":
            return setup_ai(apply=args.apply)
    except RuntimeError as exc:  # e.g. repository not found
        print(f"sgtl: {exc}", file=sys.stderr)
        return 2
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
