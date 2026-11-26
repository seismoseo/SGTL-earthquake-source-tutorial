"""Command line tool ``sgtl`` (also ``python -m sgtl_tutorial.cli``).

Subcommands:

* ``sgtl doctor``          check this environment; every line is PASS, WARN or FAIL
* ``sgtl new M01``         copy the module notebook into ``work/`` once (never overwrites)
* ``sgtl new project``     copy the research-project templates into ``project/`` (never overwrites; module M60)
* ``sgtl status``          your progress table
* ``sgtl diff M01``        has the module template changed since you copied it?
* ``sgtl setup-ai``        show which tutor-rule files would be copied to ``~/.claude/``
  (``--apply`` copies them; existing files are never overwritten)
* ``sgtl data list``       the STP waveform datasets, their sizes, and what you already have
* ``sgtl data fetch NAME`` the download plan (``--apply`` downloads with your STP account)
* ``sgtl data verify NAME`` file counts, damaged files and SHA-256 fingerprints of a dataset
* ``sgtl pq check``        is your PocketQuake clone at the pinned version, are its tools there?
* ``sgtl pq stage DATASET --slug NAME``  register a fetched dataset as a PocketQuake cluster
* ``sgtl pq run NAME --from STAGE --through STAGE``  run PocketQuake stages (``--apply`` to start)
* ``sgtl pq bootstrap NAME``  relocation errors by resampling (``--apply`` to start)
* ``sgtl submit M04``      the plan for submitting a module (``--apply`` runs core tasks in notebook order;
  ``--include-optional`` adds stretch/research tasks), commits the record on a new branch of your private
  copy and opens a pull request for the mentor;
  it pushes only to a repository GitHub reports as private)
* ``sgtl oral [M04] --salt WORD``  three of your passed task cells, picked by date and the word your mentor
  says at the meeting (required), with two questions each
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


# A notebook loads numpy, PyTorch and PyGMT into one process. With mixed math libraries (MKL and its OpenMP
# instead of the pinned OpenBLAS with GNU OpenMP, see environment.yml) such a process dies inside GMT ("double free
# or corruption") the first time fig.plot gets x= and y= arrays. Doctor repeats those steps in a separate process,
# so that a crash becomes a FAIL line instead of killing doctor. Each finished step prints "SGTL-STEP <name>".
_STACK_TEST = r'''
import os, sys, tempfile
def step(name):
    print("SGTL-STEP " + name, flush=True)
import numpy as np
a = np.random.default_rng(0).standard_normal((300, 300))
assert np.isfinite(a @ a.T).all()
step("numpy")
try:
    import torch
except ImportError:
    step("torch-missing")
else:
    torch.set_num_threads(1)
    assert bool(torch.isfinite(torch.randn(64, 64) @ torch.randn(64, 64)).all())
    assert np.isfinite(a @ a).all()
    step("torch")
try:
    import pygmt
except ImportError:
    step("pygmt-missing")
else:
    fig = pygmt.Figure()
    fig.basemap(region=[0, 10, 0, 10], projection="X4c", frame=True)
    fig.plot(x=np.array([1.0, 5.0, 9.0]), y=np.array([2.0, 8.0, 3.0]), pen="1p")
    step("pygmt")
    with tempfile.TemporaryDirectory() as d:
        fig.savefig(os.path.join(d, "doctor.png"))
    step("pygmt-save")
step("done")
'''
_STACK_STEPS = [("numpy", "a numpy matrix product"), ("torch", "a PyTorch matrix product"),
                ("pygmt", "PyGMT fig.plot(x=..., y=...)"), ("pygmt-save", "saving the PyGMT figure")]
_STACK_FIX = ("This happens when the environment mixes math libraries (MKL and its OpenMP instead of the pinned "
              "OpenBLAS with GNU OpenMP). Fix: rebuild the course environment with its pinned libraries "
              "(bin/sgtl-install env --apply --rebuild), then run sgtl doctor again")


def _stack_check(timeout: float = 300.0) -> Tuple[str, str]:
    """(status, detail) of numpy + PyTorch + PyGMT in one separate process; never raises."""
    import signal

    env = dict(os.environ)
    env.pop("LD_LIBRARY_PATH", None)  # as in the course kernel (a set LD_LIBRARY_PATH has its own WARN line)
    env.update(OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1", NUMEXPR_MAX_THREADS="1",
               NUMPY_MADVISE_HUGEPAGE="0", MPLBACKEND="Agg")
    try:
        p = subprocess.run([sys.executable, "-I", "-c", _STACK_TEST], capture_output=True, text=True,
                           errors="replace", timeout=timeout, env=env, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        p = None
    except OSError as exc:
        return "WARN", f"could not start the test process ({exc})"
    else:
        out = p.stdout or ""
    done = [ln.split()[1] for ln in out.splitlines() if ln.startswith("SGTL-STEP ") and len(ln.split()) > 1]
    names = {d.replace("-missing", "") for d in done}
    if p is not None and p.returncode == 0 and "done" in done:
        parts = ["a numpy matrix product"]
        if "torch" in done:
            parts.append("a PyTorch matrix product")
        if "pygmt-save" in done:
            parts.append("PyGMT fig.plot(x=, y=) and savefig")
        detail = ", ".join(parts) + " ran together in one process"
        skipped = [n for n in ("torch", "pygmt") if f"{n}-missing" in done]
        if skipped:
            return "WARN", detail + f"; {' and '.join(skipped)} not installed, so not tested"
        return "PASS", detail
    stage = next((label for key, label in _STACK_STEPS if key not in names), "the end of the test")
    if p is None:
        return "FAIL", f"the test process hung during {stage} (no result in {timeout:.0f} s). {_STACK_FIX}"
    if p.returncode < 0:
        try:
            how = f"crashed ({signal.Signals(-p.returncode).name})"
        except ValueError:
            how = f"crashed (signal {-p.returncode})"
    else:
        how = f"stopped with exit code {p.returncode}"
    last = next((ln.strip() for ln in reversed((p.stderr or "").splitlines()) if ln.strip()), "")
    hint = f" (last message: {last[:160]})" if last else ""
    return "FAIL", f"the test process {how} during {stage}{hint}. {_STACK_FIX}"


SEISBENCH_FILES = ("phasenet/stead.json.v2", "phasenet/stead.pt.v2", "phasenet/original.json.v2",
                   "phasenet/original.pt.v2")


def _seisbench_weights(repo: Optional[Path]) -> Tuple[str, str]:
    """The PhaseNet weights of ``bin/sgtl-install seisbench`` (module M21), checked against install/checksums.txt."""
    env = os.environ.get("SEISBENCH_CACHE_ROOT", "").strip()
    home = os.environ.get("SGTL_HOME", "").strip()
    root = Path(env).expanduser() if env else (Path(home).expanduser() if home else Path.home() / "sgtl") / "seisbench"
    pins = {}
    sums = repo / "install" / "checksums.txt" if repo is not None else None
    if sums is not None and sums.is_file():
        for row in sums.read_text(encoding="utf-8").splitlines():
            parts = row.split()
            if len(parts) >= 2 and parts[0] in SEISBENCH_FILES:
                pins[parts[0]] = parts[1]
    folder = root / "models" / "v3"
    fix = "run: bin/sgtl-install seisbench --apply; needed in M21"
    missing = [n for n in SEISBENCH_FILES if not (folder / n).is_file()]
    if missing:
        return "WARN", f"not found in {_paths.short_path(folder / 'phasenet')} ({fix})"
    changed = [n for n in SEISBENCH_FILES if n in pins and _sha256(folder / n) != pins[n]]
    if changed:
        return "WARN", (f"{', '.join(Path(n).name for n in changed)} in {_paths.short_path(folder / 'phasenet')} "
                        f"differ from install/checksums.txt ({fix})")
    where = _paths.short_path(root) + ("" if env else " (notebooks find them; in a shell, source "
                                                      f"{_paths.short_path(root.parent / 'tools' / 'env.sh')})")
    checked = "checksums match" if len(pins) == len(SEISBENCH_FILES) else "checksums not compared"
    return "PASS", f"stead and original, version 2, in {where}; {checked}"


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
    try:
        status, detail = _stack_check()
    except Exception as exc:  # noqa: BLE001 - doctor always finishes
        status, detail = "WARN", f"the test could not run ({type(exc).__name__})"
    add(_line(status, "numpy + PyTorch + PyGMT in one process", detail))
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
        status, detail = _seisbench_weights(repo)
    except OSError as exc:
        status, detail = "WARN", f"could not be read ({type(exc).__name__})"
    add(_line(status, "SeisBench PhaseNet weights", detail))
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
    for folder in ("docs/notebooks", "modules"):  # keep older private copies usable after an update
        cands = sorted(repo.glob(f"{folder}/{mid}_*/{mid}_*.ipynb"))
        if cands:
            return cands[0]
    return None


PROJECT_TEMPLATES = ("templates", "project")     # in the repository; copied once into project/ (module M60)


def new_project() -> int:
    """``sgtl new project``: copy the project templates into ``project/``; a file that exists is never touched."""
    repo = _paths.repo_root()
    src = _paths.course_path(*PROJECT_TEMPLATES, repo=repo)
    files = sorted(p for p in src.rglob("*") if p.is_file()) if src.is_dir() else []
    if not files:
        print("No project templates under docs/templates/project/ (is this release older than module M60?).")
        return 1
    dest = repo / "project"
    record_path = dest / ".sgtl" / "templates.json"
    try:
        record = json.loads(record_path.read_text(encoding="utf-8")) if record_path.is_file() else {}
    except ValueError:
        record = {}
    created = 0
    for tpl in files:
        rel = tpl.relative_to(src).as_posix()
        out = dest / rel
        if out.exists():
            print(f"kept     {_rel(out, repo)}  (exists; sgtl never overwrites your project files)")
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        text = tpl.read_text(encoding="utf-8").replace("{{date}}", now_iso()[:10])
        out.write_text(text, encoding="utf-8")
        record[rel] = {"template_sha": _sha256(tpl), "copied_sha": _sha256(out), "copied_at": now_iso(),
                       "release_at_copy": release_version(repo)}
        created += 1
        print(f"created  {_rel(out, repo)}  (copy of {_rel(tpl, repo)})")
    if created:
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Next: read {_rel(dest / 'README.md', repo)}, then write your plan in "
              f"{_rel(dest / 'ANALYSIS_PLAN.md', repo)} (module M60, task 6).")
    else:
        print("Nothing to copy: every template file is already in project/.")
    return 0 if created else 1


def new(mid: str) -> int:
    if mid.strip().lower() == "project":
        return new_project()
    mid = mid.upper()
    if not MODULE_RE.match(mid):
        print("Module ids look like M01 (or: sgtl new project).")
        return 2
    repo = _paths.repo_root()
    tpl = _template(repo, mid)
    if tpl is None:
        print(f"No notebook for {mid} under docs/notebooks/ (is this module released yet?).")
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
    from .notebooks import relocate_links

    relocate_links(nb, "../../")
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


# ----------------------------------------------------------------------------- data / pq
def _add_data_parser(sub) -> argparse.ArgumentParser:
    p = sub.add_parser("data", help="STP waveform datasets: list, fetch (dry run unless --apply), verify",
                       description="Waveform datasets from STP (data/manifests/stp_datasets.yaml). Files go to "
                                   "~/sgtl/data/<dataset>/ (or $SGTL_DATA/<dataset>/). Your STP account is read from "
                                   "~/.sgtl/credentials.env and the STP program from ~/.sgtl/stp-client.pl.")
    ds = p.add_subparsers(dest="data_cmd")
    listing = ds.add_parser("list", help="every dataset, its size, and what you already have")
    listing.add_argument("--manifest", type=Path, help="private frozen research request YAML instead of teaching datasets")
    q = ds.add_parser("fetch", help="the download plan of a dataset; --apply downloads it",
                      description="Without --apply: print the plan (stations, STP requests, size) and change nothing. "
                                  "With --apply: download the events you do not have yet, through PocketQuake.")
    q.add_argument("name", help="dataset name, e.g. sangju2019 (see: sgtl data list)")
    q.add_argument("--apply", action="store_true", help="really download (without it: only the plan)")
    q.add_argument("--large", action="store_true", help="confirm fetching a large dataset (several GB)")
    q.add_argument("--manifest", type=Path, help="private frozen research request YAML instead of teaching datasets")
    q = ds.add_parser("verify", help="check a downloaded dataset (counts, damaged files, fingerprints)")
    q.add_argument("name", help="dataset name")
    q.add_argument("--write", action="store_true",
                   help="record the SHA-256 fingerprints of the files you have now in MANIFEST.sha256")
    q.add_argument("--manifest", type=Path, help="the same private request YAML used to fetch this research dataset")
    return p


def _add_pq_parser(sub) -> argparse.ArgumentParser:
    p = sub.add_parser("pq", help="PocketQuake: check, stage, run, bootstrap (dry run unless --apply)",
                       description="Helpers for your PocketQuake clone in ~/sgtl/PocketQuake. Heavy runs use at most "
                                   "4 cores, nice 15, a memory cap, and one run per user at a time.")
    ps = p.add_subparsers(dest="pq_cmd")
    ps.add_parser("check", help="is the clone at the pinned version, and are its tools in place?")
    q = ps.add_parser("stage", help="register a fetched dataset as a PocketQuake cluster (dry run unless --apply)")
    q.add_argument("dataset", help="a fetched dataset, e.g. sangju2019")
    q.add_argument("--slug", required=True, help="your name for the cluster: lower-case letters, digits, _")
    q.add_argument("--region", help="name used in PocketQuake's file names (default: the slug, capitalized)")
    q.add_argument("--manifest", type=Path, help="private frozen request YAML used to fetch the dataset")
    q.add_argument("--apply", action="store_true", help="really write the cluster into your clone")
    stages = " ".join(_pq_stages())
    q = ps.add_parser("run", help="run PocketQuake stages of a cluster (dry run unless --apply)",
                      description=f"Stages, in order: {stages}. Picks come from PhaseNet+.")
    q.add_argument("slug", help="a staged cluster")
    q.add_argument("--from", dest="stage_from", required=True, metavar="STAGE", help="first stage")
    q.add_argument("--through", required=True, metavar="STAGE", help="last stage")
    q.add_argument("--cores", type=int, default=1, help="CPU cores, 1 to 4 (default 1)")
    q.add_argument("--mem-gb", type=float, default=32.0, help="memory cap per process in GB (default 32, at least 6)")
    q.add_argument("--apply", action="store_true", help="really start the run")
    q = ps.add_parser("bootstrap", help="relocation errors by resampling (dry run unless --apply)")
    q.add_argument("slug", help="a staged cluster with a finished relocation")
    q.add_argument("--branch", choices=["dtcc", "dtct"], default="dtcc", help="which relocation (default dtcc)")
    q.add_argument("--n", type=int, default=1000, help="number of resampled HypoDD runs (default 1000)")
    q.add_argument("--seed", type=int, default=0, help="random seed (default 0)")
    q.add_argument("--cores", type=int, default=1, help="CPU cores, 1 to 4 (default 1)")
    q.add_argument("--mem-gb", type=float, default=32.0, help="memory cap per process in GB (default 32, at least 6)")
    q.add_argument("--apply", action="store_true", help="really start the bootstrap")
    return p


def _pq_stages() -> Tuple[str, ...]:
    from .pq import STAGES

    return STAGES


def _data_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from . import datafetch

    if args.data_cmd == "list":
        return datafetch.list_datasets(manifest=args.manifest)
    if args.data_cmd == "fetch":
        return datafetch.fetch(args.name, apply=args.apply, large=args.large, manifest=args.manifest)
    if args.data_cmd == "verify":
        return datafetch.verify(args.name, write=args.write, manifest=args.manifest)
    parser.print_help()
    return 0


def _pq_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from . import pq

    if args.pq_cmd == "check":
        return pq.check()
    if args.pq_cmd == "stage":
        return pq.stage(args.dataset, args.slug, region=args.region, apply=args.apply, manifest=args.manifest)
    if args.pq_cmd == "run":
        return pq.run(args.slug, args.stage_from, args.through, cores=args.cores, mem_gb=args.mem_gb,
                      apply=args.apply)
    if args.pq_cmd == "bootstrap":
        return pq.bootstrap(args.slug, branch=args.branch, n=args.n, seed=args.seed, cores=args.cores,
                            mem_gb=args.mem_gb, apply=args.apply)
    parser.print_help()
    return 0


def _add_gui_parser(sub):
    p = sub.add_parser("gui", help="SeisComP offline waveform viewer and event picker (dry run unless --apply)")
    actions = p.add_subparsers(dest="gui_cmd")
    actions.add_parser("doctor", help="check native SeisComP tools and the current X11 display")
    q = actions.add_parser("demo", help="prepare a synthetic rehearsal without STP records")
    q.add_argument("--out", type=Path, default=Path("work/seiscomp/demo"))
    q.add_argument("--apply", action="store_true")
    q = actions.add_parser("prepare", help="prepare local copies of your SAC records and station metadata")
    q.add_argument("dataset", nargs="?", default="sangju2019")
    q.add_argument("--event", default="20190721020418", help="UTC event folder YYYYMMDDHHMMSS")
    q.add_argument("--band", default="HH")
    q.add_argument("--out", type=Path, required=True, help="new session directory under work/")
    q.add_argument("--waveforms", type=Path, help="project mode: folder of one event's original SAC files")
    q.add_argument("--stationxml", type=Path, help="folder of NET.STA.xml metadata files")
    q.add_argument("--origin", help="project mode: context origin, explicit UTC Z suffix")
    q.add_argument("--latitude", type=float)
    q.add_argument("--longitude", type=float)
    q.add_argument("--depth-km", type=float)
    q.add_argument("--apply", action="store_true")
    q = actions.add_parser("open", help="open a prepared offline session, close its window to return")
    q.add_argument("session", type=Path)
    q.add_argument("--app", choices=["waveforms", "event"], default="waveforms")
    q.add_argument("--apply", action="store_true")
    q = actions.add_parser("import-picks", help="validate your saved SCML picks and export the M20 CSV format")
    q.add_argument("session", type=Path)
    q.add_argument("--xml", type=Path, required=True)
    q.add_argument("--origin-id", help="reviewed origin ID; required when XML contains several revisions")
    q.add_argument("--out", type=Path, required=True, help="new CSV file; never overwrites an existing file")
    q.add_argument("--apply", action="store_true")
    return p


def _gui_command(args, parser):
    from . import seiscomp
    if args.gui_cmd == "doctor":
        return seiscomp.doctor()
    if args.gui_cmd == "demo":
        return seiscomp.demo(out=args.out, apply=args.apply)
    if args.gui_cmd == "prepare":
        return seiscomp.prepare(args.dataset, event=args.event, band=args.band, out=args.out, apply=args.apply,
                                waveforms=args.waveforms, stationxml=args.stationxml, origin=args.origin,
                                latitude=args.latitude, longitude=args.longitude, depth_km=args.depth_km)
    if args.gui_cmd == "open":
        return seiscomp.launch(args.session, app=args.app, apply=args.apply)
    if args.gui_cmd == "import-picks":
        return seiscomp.import_picks(args.session, xml=args.xml, out=args.out, origin_id=args.origin_id, apply=args.apply)
    parser.print_help()
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="sgtl", description="SGTL earthquake source tutorial helper.")
    parser.add_argument("--version", action="version", version=f"sgtl-tutorial {__version__}")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("doctor", help="check this environment (PASS/WARN/FAIL lines)")
    p = sub.add_parser("new", help="copy a module notebook into work/, or the project templates into project/ "
                                   "(never overwrites)")
    p.add_argument("module", help="module id, e.g. M01, or the word project")
    sub.add_parser("status", help="show your progress table")
    p = sub.add_parser("diff", help="has the module template changed since you copied it?")
    p.add_argument("module")
    p = sub.add_parser("setup-ai", help="copy tutor rules into ~/.claude/ (dry run unless --apply)")
    p.add_argument("--apply", action="store_true", help="really copy (existing files are kept)")
    p = sub.add_parser("submit", help="run your work notebook of a module and send it for review "
                                      "(dry run unless --apply)")
    p.add_argument("module", help="module id, e.g. M04")
    p.add_argument("--apply", action="store_true", help="really run, commit on a new branch, push, open the PR")
    p.add_argument("--timeout", type=float, default=120, metavar="MIN", help="stop the run after MIN minutes "
                   "(default 120)")
    p.add_argument("--base", default="main", help="branch the pull request goes into (default main)")
    p.add_argument("--kernel", help="Jupyter kernel to run with (default: the notebook's own, 'sgtl')")
    p.add_argument("--no-pr", action="store_true", help="push the branch but do not open a pull request")
    p.add_argument("--include-optional", action="store_true", help="also run stretch and research task blocks "
                   "(default: core tasks only)")
    p = sub.add_parser("oral", help="pick three of your passed task cells for the weekly oral check")
    p.add_argument("module", nargs="?", help="module id, e.g. M04 (default: all modules)")
    p.add_argument("--date", help="the date that seeds the choice, YYYY-MM-DD (default: today)")
    p.add_argument("--salt", metavar="WORD", help="required: a new word the mentor says at the meeting (at least "
                   "6 characters; or SGTL_ORAL_SALT in the mentor's shell); only its fingerprint is logged")
    data_parser = _add_data_parser(sub)
    pq_parser = _add_pq_parser(sub)
    gui_parser = _add_gui_parser(sub)
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
        if args.cmd == "submit":
            from .submit import submit

            return submit(args.module, apply=args.apply, timeout_min=args.timeout, base=args.base,
                          kernel=args.kernel, no_pr=args.no_pr, include_optional=args.include_optional)
        if args.cmd == "oral":
            from .oral import oral

            return oral(args.module, date=args.date, salt=args.salt)
        if args.cmd == "data":
            return _data_command(args, data_parser)
        if args.cmd == "pq":
            return _pq_command(args, pq_parser)
        if args.cmd == "gui":
            return _gui_command(args, gui_parser)
    except (RuntimeError, ValueError, OSError) as exc:  # e.g. repository or request manifest not found
        print(f"sgtl: {exc}", file=sys.stderr)
        return 2
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
