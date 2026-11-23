"""PocketQuake helpers: check your clone, stage a dataset as a cluster, run stages, bootstrap, read results.

PocketQuake is the lab's earthquake-catalog toolchain (picking, location, relocation, focal mechanisms).
``bin/sgtl-install tools`` puts your own clone in ``~/sgtl/PocketQuake`` (version v1.16.1); its relocation
pipeline is the submodule ``external/korea-cluster-relocation``. These helpers only call PocketQuake's own
code; they never change how it computes anything. On the command line::

    sgtl pq check                                   is the clone at the pinned version, are the tools there?
    sgtl pq stage sangju2019 --slug sangju_me       register a fetched dataset as a cluster (dry run)
    sgtl pq run sangju_me --from stations --through dtct --cores 2          (dry run; add --apply)
    sgtl pq bootstrap sangju_me --branch dtcc --n 1000 --seed 0 --cores 2   (dry run; add --apply)

In a notebook (after a run)::

    st.pq.read_sum("sangju_me")          HYPOINVERSE locations (the .sum file of one velocity model)
    st.pq.read_reloc("sangju_me")        HypoDD relocations (hypoDD.reloc)
    st.pq.location_table("sangju_me")    relocations with their bootstrap 95 % errors, one row per event

A cluster is PocketQuake's name for one set of earthquakes processed together; its "slug" is the short
name you give it. Your staged clusters live only in your clone (they are never committed), and the
dataset folder stays read-only: PocketQuake writes its results under
``~/sgtl/PocketQuake/external/korea-cluster-relocation/pipeline/runs/<slug>/``.

Heavy runs follow the server rules: at most 4 cores (``taskset``), low priority (``nice -n 15``), a memory
cap per process (``prlimit``, 32 GB unless you choose another; hypoDD alone needs about 4.4 GB of address
space, so the cap is never below 6 GB), one heavy run per user at a time (a lock file in
``~/sgtl/.locks``), and no start while the server has less than 1.5 times the cap free. Every run is
logged, with the SHA-256 fingerprints of its products, in ``work/.sgtl/runs.jsonl`` of your repository.

Credit: Minseong Seo (SGTL, Seoul National University). License: MIT.
"""
from __future__ import annotations

import datetime as _dt
import getpass
import hashlib
import importlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
import shlex
from typing import Dict, List, Optional, Sequence, Tuple, Union

from . import _paths

__all__ = [
    "STAGES",
    "sgtl_home",
    "clone_dir",
    "pipeline_dir",
    "tools_env",
    "check",
    "stage",
    "run",
    "bootstrap",
    "read_sum",
    "read_reloc",
    "location_table",
]

# pipeline.core.pipeline.STAGES of PocketQuake v1.16.1, in order.
STAGES = ("stations", "waveforms", "picking", "hypoinverse", "ph2dt", "dtct", "rereference", "xcorr", "dtcc",
          "focal_mechanism", "report")
PICKER = "phasenet_plus"   # PhaseNet+ (EQNet): the picker that also gives first-motion polarities
MAX_CORES = 4
MIN_MEM_GB = 6.0           # hypoDD needs about 4.4 GB of address space
DEFAULT_MEM_GB = 32.0
MEM_FACTOR = 1.5           # refuse to start unless MemAvailable >= 1.5 x the cap
NICE_LEVEL = 15
REGION_PAD_DEG = 0.2       # map box: the events' extent plus this margin on every side
SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
REGION_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,39}$")
PROGRAMS = ("hyp1.40", "ph2dt", "hypoDD", "ncsn2pha")
# Products whose SHA-256 goes into work/.sgtl/runs.jsonl when a run creates or changes them (paths inside
# runs/<slug>/), plus one combined fingerprint of the pick files it wrote.
PRODUCT_GLOBS = ("station_table/used_stations_100km.csv", "1.HypoInv/PHS/*.phs", "1.HypoInv/*/*.sum",
                 "1.HypoInv/*/*.arc", "2.HypoDD/*/dt.ct", "2.HypoDD/*/dt.cc_0.7_combined*",
                 "2.HypoDD/*/hypoDD.reloc", "2.HypoDD/*/*/hypoDD.reloc", "2.HypoDD/*/bootstrap_errors.csv",
                 "3.FocalMech/*/mechanisms.csv")
_CLEAN_ENV = ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "LD_LIBRARY_PATH", "POCKETQUAKE_EQCYCLE_DIR",
              "GIT_DIR", "GIT_WORK_TREE")


# ----------------------------------------------------------------------------- where things are
def sgtl_home() -> Path:
    """``$SGTL_HOME`` (default ``~/sgtl``): where bin/sgtl-install put the environment, tools and clone."""
    env = os.environ.get("SGTL_HOME", "").strip()
    return Path(env).expanduser() if env else Path.home() / "sgtl"


def clone_dir() -> Path:
    """Your PocketQuake clone, ``~/sgtl/PocketQuake``."""
    return sgtl_home() / "PocketQuake"


def pipeline_dir() -> Path:
    """The relocation pipeline inside the clone (the folder that holds ``pipeline/``)."""
    return clone_dir() / "external" / "korea-cluster-relocation"


def _runs_dir(slug: str) -> Path:
    return pipeline_dir() / "pipeline" / "runs" / slug


def tools_env() -> Dict[str, str]:
    """Source ``~/sgtl/tools/env.sh`` (written by bin/sgtl-install tools) and return its settings.

    Keys: SGTL_TOOLS, EQNET_DIR, SKHASH_DIR, POCKETQUAKE_DIR, POCKETQUAKE_PYTHON (when set) and
    TOOLS_PATH (the folders it puts in front of PATH). Empty when the file is missing or fails.
    """
    path = sgtl_home() / "tools" / "env.sh"
    if not path.is_file():
        return {}
    base = ["/usr/bin", "/bin"]
    try:
        out = subprocess.run(["bash", "--noprofile", "--norc", "-c", 'source "$1" >/dev/null 2>&1 && env -0',
                              "sgtl", str(path)], env={"PATH": ":".join(base), "HOME": str(Path.home())},
                             capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return {}
    if out.returncode != 0:
        return {}
    env = dict(item.split("=", 1) for item in out.stdout.decode("utf-8", "replace").split("\0") if "=" in item)
    result = {k: env[k] for k in ("SGTL_TOOLS", "EQNET_DIR", "SKHASH_DIR", "POCKETQUAKE_DIR", "POCKETQUAKE_PYTHON")
              if env.get(k)}
    result["TOOLS_PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep) if p and p not in base)
    return result


def _pins(repo: Path) -> Dict[str, str]:
    """PocketQuake's pinned tag and commits, read from install/components/tools.sh (one source of truth)."""
    text = (Path(repo) / "install" / "components" / "tools.sh").read_text(encoding="utf-8")
    out = {}
    for key, var in (("tag", "TOOLS_PQ_TAG"), ("commit", "TOOLS_PQ_COMMIT"), ("sub", "TOOLS_PQ_SUB"),
                     ("sub_commit", "TOOLS_PQ_SUB_COMMIT")):
        m = re.search(rf'^{var}="([^"]+)"', text, re.M)
        if not m:
            raise RuntimeError(f"install/components/tools.sh has no {var}; is this a complete copy of the tutorial?")
        out[key] = m.group(1)
    return out


def _git(path: Path, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        out = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, timeout=60, env=env)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def _pq_version(clone: Path) -> str:
    try:
        text = (clone / "pocketquake" / "__init__.py").read_text(encoding="utf-8")
    except OSError:
        return "?"
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)', text, re.M)
    return m.group(1) if m else "?"


def _cluster_names(config_text: str) -> List[str]:
    m = re.search(r"^CLUSTER_NAMES\s*=\s*\((.*?)\)\s*$", config_text, re.M | re.S)
    return re.findall(r"""["']([^"']+)["']""", m.group(1)) if m else []


def _line(results: List[str], status: str, name: str, detail: str) -> None:
    print(f"{status:<4}  {name}: {detail}")
    results.append(status)


# ----------------------------------------------------------------------------- sgtl pq check
def check() -> int:
    """``sgtl pq check``: PASS/WARN/FAIL lines for the clone, the submodule, env.sh, EQNet, SKHASH, programs."""
    repo = _paths.repo_root()
    pins = _pins(repo)
    results: List[str] = []
    clone = clone_dir()
    short = _paths.short_path(clone)
    if not (clone / "pocketquake" / "__init__.py").is_file():
        _line(results, "FAIL", "PocketQuake", f"no clone in {short}. Run: bin/sgtl-install tools --apply")
    else:
        head = _git(clone, "rev-parse", "HEAD")
        if head == pins["commit"]:
            _line(results, "PASS", "PocketQuake", f"{short} at {pins['tag']} ({head[:7]}), "
                  f"pocketquake {_pq_version(clone)}")
        else:
            _line(results, "FAIL", "PocketQuake", f"{short} is at {head[:7] or 'an unknown commit'}, not "
                  f"{pins['tag']} ({pins['commit'][:7]}). Run: bin/sgtl-install tools --apply")
        sub = clone / pins["sub"]
        sub_head = _git(sub, "rev-parse", "HEAD")
        if sub_head == pins["sub_commit"]:
            changed = [ln for ln in _git(sub, "status", "--porcelain").splitlines() if ln.strip()]
            note = f"; {len(changed)} local change(s), for example your staged clusters" if changed else ""
            _line(results, "PASS", "Relocation pipeline", f"{pins['sub']} at {sub_head[:7]}{note}")
        else:
            _line(results, "FAIL", "Relocation pipeline", f"{pins['sub']} is at {sub_head[:7] or 'nothing'}, not "
                  f"{pins['sub_commit'][:7]}. Run: git -C {short} submodule update --init")
    tools = tools_env()
    envsh = _paths.short_path(sgtl_home() / "tools" / "env.sh")
    if tools:
        _line(results, "PASS", "Tool settings", f"{envsh} (read by these helpers; notebooks need nothing else)")
    else:
        _line(results, "FAIL", "Tool settings", f"{envsh} is missing or fails. Run: bin/sgtl-install tools --apply")
    eq = tools.get("EQNET_DIR", "")
    weights = Path(eq) / "docs" / "model_phasenet_plus" / "model_99.pth" if eq else None
    if weights is not None and weights.is_file():
        _line(results, "PASS", "EQNET_DIR", f"{_paths.short_path(eq)} (PhaseNet+ weights present)")
    else:
        _line(results, "FAIL", "EQNET_DIR", (f"{_paths.short_path(eq)} has no PhaseNet+ weights" if eq else "not set")
              + ". Run: bin/sgtl-install tools --apply")
    sk = tools.get("SKHASH_DIR", "")
    if sk and (Path(sk) / "SKHASH.py").is_file():
        _line(results, "PASS", "SKHASH_DIR", _paths.short_path(sk))
    else:
        _line(results, "FAIL", "SKHASH_DIR", (f"{_paths.short_path(sk)} has no SKHASH.py" if sk else "not set")
              + ". Run: bin/sgtl-install tools --apply")
    tpath = tools.get("TOOLS_PATH", "")
    found = {p: shutil.which(p, path=tpath) if tpath else None for p in PROGRAMS}
    missing = [p for p, f in found.items() if not f]
    if missing:
        _line(results, "FAIL", "Programs", f"not found on the tools PATH: {', '.join(missing)}. "
              "Run: bin/sgtl-install tools --apply")
    else:
        where = sorted({_paths.short_path(Path(f).parent) for f in found.values() if f})
        _line(results, "PASS", "Programs", f"{', '.join(PROGRAMS)} in {', '.join(where)}")
    py = tools.get("POCKETQUAKE_PYTHON", "")
    if py and os.access(py, os.X_OK):
        _line(results, "PASS", "Python for PocketQuake", _paths.short_path(py))
    else:
        _line(results, "WARN", "Python for PocketQuake", f"POCKETQUAKE_PYTHON not usable; runs use "
              f"{_paths.short_path(sys.executable)}")
    n_fail, n_warn = results.count("FAIL"), results.count("WARN")
    print(f"\n{n_fail} FAIL, {n_warn} WARN. " + ("Fix the FAIL lines first." if n_fail else "PocketQuake is ready."))
    return 1 if n_fail else 0


# ----------------------------------------------------------------------------- sgtl pq stage
# Runs in a separate Python process (the clone is never imported into sgtl itself). Arguments: one JSON object.
# pocketquake.scaffold.scaffold() is not called: it would ask STP for the station list again and copy the
# catalog onto itself. sgtl data fetch already made the same folder layout, so staging only writes the
# cluster module and registers it (write_cluster_module + register_cluster).
_STAGE_RUNNER = r'''
import json, os, sys
a = json.loads(sys.argv[1])
sys.path.insert(0, a["pocketquake"])
from pocketquake import EQCYCLE_DIR
from pocketquake.scaffold import ClusterSpec, register_cluster, write_cluster_module
if os.path.realpath(EQCYCLE_DIR) != os.path.realpath(a["pipeline_dir"]):
    sys.exit("PocketQuake uses another relocation pipeline: " + EQCYCLE_DIR)
spec = ClusterSpec(name=a["slug"], region=a["region"], catalog_csv=a["catalog_csv"],
                   epicenter=tuple(a["epicenter"]), region_bounds=tuple(a["region_bounds"]),
                   src_dir_name=a["src_root"], networks=tuple(a["networks"]), wf_backend="stp")
if os.path.realpath(spec.src_root) != os.path.realpath(a["src_root"]):
    sys.exit("unexpected src_root " + spec.src_root)
module = write_cluster_module(spec)
names_changed, dirs_changed = register_cluster(spec)
sys.path.insert(0, EQCYCLE_DIR)
from pipeline import config
cfg = config.load_cluster(a["slug"])
print("SGTL-RESULT " + json.dumps({"module": module, "names_changed": names_changed, "dirs_changed": dirs_changed,
                                   "src_root": cfg.src_root, "wf_source": cfg.wf_source,
                                   "output_root": cfg.output_root}))
'''


def _region_bounds(lats: Sequence[float], lons: Sequence[float]) -> Tuple[float, float, float, float]:
    def lo(v: float) -> float:
        return math.floor(round((v - REGION_PAD_DEG) * 100, 6)) / 100

    def hi(v: float) -> float:
        return math.ceil(round((v + REGION_PAD_DEG) * 100, 6)) / 100

    return lo(min(lats)), hi(max(lats)), lo(min(lons)), hi(max(lons))


def _clean_env(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _CLEAN_ENV and not k.startswith("STP_")}
    env.update(OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1",
               NUMEXPR_MAX_THREADS="1", NUMBA_NUM_THREADS="1", NUMPY_MADVISE_HUGEPAGE="0", PYTHONNOUSERSITE="1",
               MPLBACKEND="Agg")
    env.update(extra or {})
    return env


def stage(dataset_name: str, slug: str, region: Optional[str] = None, apply: bool = False,
          *, manifest: Optional[Path] = None) -> int:
    """``sgtl pq stage DATASET --slug SLUG [--region NAME] [--apply]``."""
    from . import datafetch

    ds = datafetch.dataset(dataset_name, manifest=manifest)
    folder = datafetch.dataset_folder(dataset_name)
    if manifest is not None:
        datafetch._custom_request_record(ds, folder)
    manifest_flag = f" --manifest {shlex.quote(str(manifest))}" if manifest else ""
    region = region or (slug[:1].upper() + slug[1:])
    if not SLUG_RE.match(slug):
        print(f"The slug {slug!r} is not usable: 2-40 characters, lower-case letters, digits and _, starting "
              "with a letter (it becomes a Python module name).")
        return 2
    if not REGION_RE.match(region):
        print(f"The region {region!r} is not usable: letters, digits, _ and -, starting with a letter "
              "(PocketQuake uses it in file names).")
        return 2
    problems: List[str] = []
    pdir = pipeline_dir()
    config_py = pdir / "pipeline" / "config.py"
    module = pdir / "pipeline" / "clusters" / f"{slug}.py"
    if not (clone_dir() / "pocketquake" / "scaffold.py").is_file() or not config_py.is_file():
        problems.append(f"no PocketQuake clone in {_paths.short_path(clone_dir())}; run: bin/sgtl-install tools "
                        "--apply")
    elif module.exists() or slug in _cluster_names(config_py.read_text(encoding="utf-8")):
        problems.append(f"the slug {slug!r} is taken: PocketQuake already has a cluster with that name. "
                        "Choose another --slug (sgtl never overwrites a cluster).")
    catalog = folder / "event_catalog" / "event_catalog.csv"
    states = {e.folder: datafetch.event_state(folder, e) for e in ds.events}
    n_present = sum(1 for s in states.values() if s == "present")
    if not catalog.is_file() or n_present == 0:
        problems.append(f"dataset {dataset_name} is not fetched yet; run: sgtl data fetch {dataset_name}{manifest_flag} --apply")
    elif any(not (folder / "station_table" / f"{n}_station.csv").is_file() for n in ds.networks):
        problems.append(f"the station lists of {dataset_name} are missing; run: sgtl data fetch {dataset_name}{manifest_flag} --apply")
    src_root = str(folder.resolve())
    if any(c in src_root for c in "\"'\\\n"):
        problems.append(f"the data folder {_paths.short_path(src_root)} contains a quote or backslash, which a "
                        "cluster module cannot hold; set SGTL_DATA to a plainer folder")
    lats = [e.latitude for e in ds.events]
    lons = [e.longitude for e in ds.events]
    lat, lon = ds.center
    epicenter = (round(lat, 3), round(lon, 3))
    bounds = _region_bounds(lats, lons)
    print(f"Stage dataset {dataset_name} ({n_present} of {len(ds.events)} events fetched) as PocketQuake cluster "
          f"{slug!r}")
    print(f"  ClusterSpec(name={slug!r}, region={region!r}, wf_backend='stp', networks={tuple(ds.networks)},")
    print(f"              epicenter={epicenter}, region_bounds={bounds},")
    print(f"              src_root={_paths.short_path(src_root)!r})")
    print("Steps (they change only your clone; nothing is committed, the data folder stays read-only):")
    print(f"  write {_paths.short_path(module)}  (pocketquake.scaffold.write_cluster_module)")
    print(f"  add {slug!r} to CLUSTER_NAMES and the data folder to CLUSTER_SRC_DIRS in "
          f"{_paths.short_path(config_py)}  (pocketquake.scaffold.register_cluster)")
    print("  load the new cluster once with pipeline.config.load_cluster to check it")
    if n_present < len(ds.events):
        print(f"Note: {len(ds.events) - n_present} event(s) have no waveforms yet; PocketQuake will skip them.")
    if problems:
        print("Cannot stage:\n" + "\n".join(f"  - {p}" for p in problems))
        return 1
    if not apply:
        print(f"Dry run: nothing was changed. To do it:  sgtl pq stage {dataset_name}{manifest_flag} --slug {slug} --apply")
        return 0
    args = {"pocketquake": str(clone_dir()), "pipeline_dir": str(pdir), "slug": slug, "region": region,
            "catalog_csv": str(catalog), "epicenter": list(epicenter), "region_bounds": list(bounds),
            "src_root": src_root, "networks": list(ds.networks)}
    python = _python(tools_env())
    print(f"+ python: pocketquake.scaffold.write_cluster_module + register_cluster ({_paths.short_path(python)})")
    out = subprocess.run([python, "-I", "-c", _STAGE_RUNNER, json.dumps(args)], cwd=str(pdir), env=_clean_env(),
                         capture_output=True, text=True, timeout=600)
    result = None
    for ln in out.stdout.splitlines():
        if ln.startswith("SGTL-RESULT "):
            result = json.loads(ln[len("SGTL-RESULT "):])
        else:
            print("  | " + ln)
    if out.returncode != 0 or result is None:
        print("  | " + "\n  | ".join(out.stderr.strip().splitlines()[-15:]))
        print("Staging failed (see the lines above).")
        return 1
    ok = (Path(result["module"]).is_file() and os.path.realpath(result["src_root"]) == os.path.realpath(src_root)
          and result["wf_source"] == "stp_sac")
    print(f"wrote {_paths.short_path(result['module'])}; registered in config.py "
          f"(names {'added' if result['names_changed'] else 'already there'}, "
          f"data folder {'added' if result['dirs_changed'] else 'already there'})")
    print(f"check: load_cluster({slug!r}) reads waveforms from {_paths.short_path(result['src_root'])} "
          f"({result['wf_source']}); results will go to {_paths.short_path(result['output_root'])}")
    if not ok:
        print("The check did not give what was expected. Tell the mentor (friction issue).")
        return 1
    print(f"Next (a dry run first):  sgtl pq run {slug} --from stations --through dtct --cores 2 --mem-gb 8")
    return 0


# ----------------------------------------------------------------------------- heavy runs
def _python(tools: Dict[str, str]) -> str:
    py = tools.get("POCKETQUAKE_PYTHON", "")
    return py if py and os.access(py, os.X_OK) else sys.executable


def _run_env(tools: Dict[str, str], python: str) -> Dict[str, str]:
    path = [p for p in tools.get("TOOLS_PATH", "").split(os.pathsep) if p]
    path.append(str(Path(python).parent))
    path += [p for p in os.environ.get("PATH", "/usr/bin:/bin").split(os.pathsep) if p and p not in path]
    extra = {"PATH": os.pathsep.join(path)}
    for key in ("EQNET_DIR", "SKHASH_DIR"):
        if tools.get(key):
            extra[key] = tools[key]
    return _clean_env(extra)


def _cpu_times() -> Dict[int, Tuple[int, int]]:
    out = {}
    with open("/proc/stat", encoding="ascii") as fh:
        for ln in fh:
            m = re.match(r"^cpu(\d+)\s+(.*)$", ln)
            if m:
                v = [int(x) for x in m.group(2).split()]
                idle = v[3] + (v[4] if len(v) > 4 else 0)
                out[int(m.group(1))] = (sum(v[:8]) - idle, sum(v[:8]))
    return out


def _pick_cpus(n: int) -> List[int]:
    """The ``n`` least busy CPUs that this process may use (measured over 0.3 s from /proc/stat)."""
    try:
        allowed = sorted(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        allowed = list(range(os.cpu_count() or 1))
    try:
        a = _cpu_times()
        time.sleep(0.3)
        b = _cpu_times()
        load = {c: (b[c][0] - a[c][0]) / max(1, b[c][1] - a[c][1]) for c in allowed if c in a and c in b}
    except (OSError, ValueError, KeyError):
        load = {}
    return sorted(sorted(allowed, key=lambda c: (load.get(c, 1.0), c))[:n])


def _limit_cmd(cpus: Sequence[int], mem_gb: float) -> Tuple[List[str], Optional[object]]:
    """Command prefix for nice + taskset + prlimit; a Python fallback for any program that is missing."""
    mem_bytes = int(mem_gb * 1024 ** 3)
    prefix: List[str] = []
    todo = []
    if shutil.which("nice"):
        prefix += ["nice", "-n", str(NICE_LEVEL)]
    else:
        todo.append("nice")
    if shutil.which("taskset"):
        prefix += ["taskset", "-c", ",".join(str(c) for c in cpus)]
    else:
        todo.append("taskset")
    if shutil.which("prlimit"):
        prefix += ["prlimit", f"--as={mem_bytes}", "--"]
    else:
        todo.append("prlimit")
    if not todo:
        return prefix, None

    def preexec() -> None:  # pragma: no cover - runs in the child
        import resource

        if "nice" in todo:
            os.nice(NICE_LEVEL)
        if "taskset" in todo:
            os.sched_setaffinity(0, set(cpus))
        if "prlimit" in todo:
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))

    return prefix, preexec


class _HeavyLock:
    """One heavy run per user: an exclusive lock on ``~/sgtl/.locks/heavy-run.lock`` (fcntl.flock)."""

    def __init__(self) -> None:
        self.path = sgtl_home() / ".locks" / "heavy-run.lock"
        self.fd: Optional[int] = None

    def acquire(self, create: bool = True) -> bool:
        """Take the lock (``create=False``: only test it, creating nothing; a missing file means free)."""
        import fcntl

        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        elif not self.path.exists():
            return True
        fd = os.open(str(self.path), os.O_RDWR | (os.O_CREAT if create else 0), 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        self.fd = fd
        return True

    def holder(self) -> str:
        try:
            info = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        except (OSError, ValueError):
            return "another run"
        return (f"'{info.get('command', '?')} {info.get('cluster', '?')}' (process {info.get('pid', '?')}, "
                f"started {info.get('started', '?')})")

    def note(self, info: dict) -> None:
        assert self.fd is not None
        os.ftruncate(self.fd, 0)
        os.lseek(self.fd, 0, os.SEEK_SET)
        os.write(self.fd, (json.dumps(info) + "\n").encode())

    def release(self) -> None:
        import fcntl

        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _snapshot(out_root: Path) -> Dict[str, Tuple[int, int]]:
    """(modification time in ns, size) of every product file and pick file, by path inside ``runs/<slug>/``."""
    files = [p for pattern in PRODUCT_GLOBS for p in out_root.glob(pattern)] + list(out_root.glob("picks/*.csv"))
    out = {}
    for p in files:
        try:
            st = p.stat()
        except OSError:
            continue
        if p.is_file():
            out[p.relative_to(out_root).as_posix()] = (st.st_mtime_ns, st.st_size)
    return out


def _products(out_root: Path, before: Dict[str, Tuple[int, int]]) -> Dict[str, str]:
    """SHA-256 of the products that the run created or changed (compared with the snapshot ``before``).

    All changed pick files share one entry: the SHA-256 of their sorted "<sha256>  <name>" lines.
    """
    after = _snapshot(out_root)
    changed = sorted(rel for rel, sig in after.items() if before.get(rel) != sig)
    found = {rel: _sha256(out_root / rel) for rel in changed if not rel.startswith("picks/")}
    picks = [rel for rel in changed if rel.startswith("picks/")]
    if picks:
        joined = "".join(f"{_sha256(out_root / rel)}  {rel[len('picks/'):]}\n" for rel in picks)
        found[f"picks/*.csv ({len(picks)} files)"] = hashlib.sha256(joined.encode()).hexdigest()
    return found


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _heavy(kind: str, slug: str, py_args: List[str], *, cores: int, mem_gb: float, apply: bool,
           needs: Sequence[str], details: dict, describe: str) -> int:
    """Shared by run and bootstrap: checks, limits, lock, the run itself, and the log line."""
    from .session import _mem_available_gb, release_version

    repo = _paths.repo_root()
    problems: List[str] = []
    if not 1 <= cores <= MAX_CORES:
        problems.append(f"--cores must be 1 to {MAX_CORES} on the shared server (you gave {cores})")
    if mem_gb < MIN_MEM_GB:
        problems.append(f"--mem-gb must be at least {MIN_MEM_GB:g}: hypoDD alone needs about 4.4 GB of address space")
    module = pipeline_dir() / "pipeline" / "clusters" / f"{slug}.py"
    if not module.is_file():
        problems.append(f"PocketQuake has no cluster {slug!r}; stage one first: sgtl pq stage <dataset> --slug {slug}")
    tools = tools_env()
    if not tools:
        problems.append("~/sgtl/tools/env.sh is missing; run: bin/sgtl-install tools --apply")
    if "eqnet" in needs:
        eq = tools.get("EQNET_DIR", "")
        if not (eq and (Path(eq) / "docs" / "model_phasenet_plus" / "model_99.pth").is_file()):
            problems.append("the PhaseNet+ weights (EQNET_DIR) are missing; run: bin/sgtl-install tools --apply")
    if "skhash" in needs and not (tools.get("SKHASH_DIR") and (Path(tools["SKHASH_DIR"]) / "SKHASH.py").is_file()):
        problems.append("SKHASH (SKHASH_DIR) is missing; run: bin/sgtl-install tools --apply")
    avail = _mem_available_gb()
    if avail is not None and avail < MEM_FACTOR * mem_gb:
        problems.append(f"the server has {avail:g} GB of memory free, less than {MEM_FACTOR:g} x the {mem_gb:g} GB "
                        "cap; try later, or a smaller --mem-gb (not below 6)")
    lock = _HeavyLock()
    if lock.acquire(create=apply):
        if not apply:
            lock.release()
    else:
        problems.append(f"another heavy run of yours is going: {lock.holder()}. One heavy run at a time; "
                        "wait for it to finish")
    python = _python(tools)
    cpus = _pick_cpus(max(1, min(cores, MAX_CORES)))
    prefix, preexec = _limit_cmd(cpus, mem_gb)
    cmd = prefix + [python] + py_args
    out_root = _runs_dir(slug)
    print(describe)
    print(f"  cores: {cores} (CPUs {','.join(map(str, cpus))}, the least busy now), priority: nice {NICE_LEVEL}, "
          f"memory cap: {mem_gb:g} GB per process" + (f" (server has {avail:g} GB free)" if avail is not None else ""))
    print(f"  in {_paths.short_path(pipeline_dir())} with EQNET_DIR, SKHASH_DIR and the tools folder on PATH "
          f"(from {_paths.short_path(sgtl_home() / 'tools' / 'env.sh')})")
    print(f"  results: {_paths.short_path(out_root)}")
    shown = [a if len(a) < 120 else "<code>" for a in cmd]
    print("  command: " + " ".join(shown))
    if problems:
        lock.release()
        print("Cannot start:\n" + "\n".join(f"  - {p}" for p in problems))
        return 1
    if not apply:
        print("Dry run: nothing was started. To do it, add --apply (run it inside tmux if it may take long).")
        return 0

    started, t0 = _now(), time.time()
    before = _snapshot(out_root)
    lock.note({"pid": os.getpid(), "command": f"pq {kind}", "cluster": slug, "started": started})
    log_dir = out_root / "sgtl_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{started.replace(':', '').replace('-', '')}_{kind}.log"
    rc = 1
    try:
        with open(log_path, "w", encoding="utf-8") as log:
            log.write("command: " + " ".join(shown) + "\n")
            assert lock.fd is not None
            proc = subprocess.Popen(cmd, cwd=str(pipeline_dir()), env=_run_env(tools, python), text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, errors="replace", bufsize=1,
                                    pass_fds=(lock.fd,), preexec_fn=preexec)  # noqa: PLW1509
            try:
                assert proc.stdout is not None
                for ln in proc.stdout:
                    sys.stdout.write(ln)
                    sys.stdout.flush()
                    log.write(ln)
                rc = proc.wait()
            except KeyboardInterrupt:
                proc.wait()
                rc = 130
                print("Stopped (Ctrl-C).")
    finally:
        seconds = time.time() - t0
        record = {"ts": started, "end": _now(), "user": getpass.getuser(), "command": f"pq {kind}", "cluster": slug,
                  **details, "cores": cores, "cpus": ",".join(map(str, cpus)), "mem_gb": mem_gb, "returncode": rc,
                  "seconds": round(seconds, 1), "pocketquake": _git(clone_dir(), "rev-parse", "HEAD")[:12],
                  "pipeline": _git(pipeline_dir(), "rev-parse", "HEAD")[:12], "release": release_version(repo),
                  "log": _paths.short_path(log_path), "products": _products(out_root, before)}
        runs = Path(repo) / "work" / ".sgtl" / "runs.jsonl"
        runs.parent.mkdir(parents=True, exist_ok=True)
        with open(runs, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        lock.release()
    took = f"{seconds:.0f} s" if seconds < 120 else f"{seconds / 60:.1f} min"
    print(f"{'Finished' if rc == 0 else f'Stopped with exit code {rc}'} after {took}; "
          f"{len(record['products'])} product fingerprint(s) logged in work/.sgtl/runs.jsonl "
          f"(full output: {_paths.short_path(log_path)})")
    return 0 if rc == 0 else 1


def run(slug: str, stage_from: str, through: str, cores: int = 1, mem_gb: float = DEFAULT_MEM_GB,
        apply: bool = False) -> int:
    """``sgtl pq run SLUG --from STAGE --through STAGE [--cores N] [--mem-gb G] [--apply]``."""
    for name in (stage_from, through):
        if name not in STAGES:
            print(f"Unknown stage {name!r}. Stages, in order: {' '.join(STAGES)}")
            return 2
    i, j = STAGES.index(stage_from), STAGES.index(through)
    if i > j:
        print(f"--from {stage_from} comes after --through {through}; stages run in this order: {' '.join(STAGES)}")
        return 2
    chosen = STAGES[i:j + 1]
    needs = (["eqnet"] if "picking" in chosen else []) + (["skhash"] if "focal_mechanism" in chosen else [])
    py_args = ["-m", "pipeline.cli.run_pipeline", "--cluster", slug, "--picker", PICKER, "--stage-from", stage_from,
               "--through", through, "--cores", str(cores)]
    return _heavy("run", slug, py_args, cores=cores, mem_gb=mem_gb, apply=apply, needs=needs,
                  details={"stage_from": stage_from, "through": through, "picker": PICKER},
                  describe=f"PocketQuake run of cluster {slug!r}: stages {' -> '.join(chosen)} (picker {PICKER})")


_BOOTSTRAP_RUNNER = r'''
import json, sys, time
a = json.loads(sys.argv[1])
from pipeline import config
from pipeline.core import hypodd
cfg = config.load_cluster(a["cluster"])
t0 = time.time()
df = hypodd.bootstrap_relocation(cfg, branch=a["branch"], n=a["n"], seed=a["seed"], cores=a["cores"])
print("bootstrap_relocation: %d events, %.0f s" % (len(df), time.time() - t0))
'''


def bootstrap(slug: str, branch: str = "dtcc", n: int = 1000, seed: int = 0, cores: int = 1,
              mem_gb: float = DEFAULT_MEM_GB, apply: bool = False) -> int:
    """``sgtl pq bootstrap SLUG --branch dtcc --n 1000 --seed 0 --cores N [--apply]``.

    Calls ``pipeline.core.hypodd.bootstrap_relocation(cfg, branch, n, seed, cores)``: HypoDD is run ``n``
    times on resampled differential times, and the spread of each event gives its 95 % error.
    """
    if branch not in ("dtcc", "dtct"):
        print("--branch must be dtcc (cross-correlation times) or dtct (catalog times).")
        return 2
    if not 10 <= n <= 100000:
        print("--n must be between 10 and 100000.")
        return 2
    sub = "02.dt.cc" if branch == "dtcc" else "01.dt.ct"
    reloc = _runs_dir(slug) / "2.HypoDD" / sub / "hypoDD.reloc"
    if not reloc.is_file():
        print(f"There is no {branch} relocation yet ({_paths.short_path(reloc)}). Run that stage first: "
              f"sgtl pq run {slug} --from <stage> --through {branch} --apply")
        return 1
    args = json.dumps({"cluster": slug, "branch": branch, "n": n, "seed": seed, "cores": cores})
    return _heavy("bootstrap", slug, ["-c", _BOOTSTRAP_RUNNER, args], cores=cores, mem_gb=mem_gb, apply=apply,
                  needs=[], details={"branch": branch, "n": n, "seed": seed},
                  describe=f"Bootstrap of cluster {slug!r}, {branch} branch: {n} HypoDD runs on resampled data, "
                           f"seed {seed} (pipeline.core.hypodd.bootstrap_relocation)")


# ----------------------------------------------------------------------------- readers for notebooks
def _pipeline_config():
    """Import ``pipeline.config`` from your clone (EQNET_DIR and SKHASH_DIR set first, from tools/env.sh)."""
    tools = tools_env()
    for key in ("EQNET_DIR", "SKHASH_DIR"):
        if not os.environ.get(key) and tools.get(key):
            os.environ[key] = tools[key]
    pdir = pipeline_dir()
    if not (pdir / "pipeline" / "config.py").is_file():
        raise FileNotFoundError(f"No PocketQuake relocation pipeline in {_paths.short_path(pdir)}. "
                                "Run: bin/sgtl-install tools --apply")
    if str(pdir) not in sys.path:
        sys.path.insert(0, str(pdir))
    config = importlib.import_module("pipeline.config")
    where = Path(config.__file__).resolve()
    if pdir.resolve() not in where.parents:
        raise RuntimeError(f"Another 'pipeline' package is already loaded ({_paths.short_path(where)}). "
                           "Restart the kernel and call st.pq functions before importing it.")
    return config


def _as_path(target: Union[str, os.PathLike]) -> Optional[Path]:
    text = os.fspath(target)
    if isinstance(target, os.PathLike) or os.sep in text or text.endswith((".sum", ".reloc")):
        return Path(text).expanduser()
    return None


def read_sum(cluster_or_path: Union[str, os.PathLike], velmodel: str = "kim1983"):
    """HYPOINVERSE locations of a run, as a DataFrame (``pipeline.core.sumio.read_sum``).

    Give a cluster slug (reads ``runs/<slug>/1.HypoInv/<velmodel>/<Region>.sum``) or a path to a .sum file.
    Columns: id, time (UTC), lat, lon, depth, num, gap, rms, erh, erz, qual. ``df.attrs["source"]`` is the file.
    """
    config = _pipeline_config()
    sumio = importlib.import_module("pipeline.core.sumio")
    path = _as_path(cluster_or_path) or Path(config.sum_file(config.load_cluster(str(cluster_or_path)), velmodel))
    df = sumio.read_sum(str(path))
    df.attrs["source"] = _paths.short_path(path)
    return df


def read_reloc(cluster_or_path: Union[str, os.PathLike], branch: str = "dtcc"):
    """HypoDD relocations of a run, as a DataFrame (``pipeline.core.sumio.read_reloc``).

    Give a cluster slug and ``branch`` ("dtcc": cross-correlation times, "dtct": catalog times), or a path to a
    hypoDD.reloc file. ``df.attrs["source"]`` is the file.
    """
    config = _pipeline_config()
    sumio = importlib.import_module("pipeline.core.sumio")
    path = _as_path(cluster_or_path)
    if path is None:
        if branch not in ("dtcc", "dtct"):
            raise ValueError("branch must be 'dtcc' or 'dtct'")
        cfg = config.load_cluster(str(cluster_or_path))
        path = Path(config.dtcc_dir(cfg) if branch == "dtcc" else config.dtct_dir(cfg)) / "hypoDD.reloc"
    df = sumio.read_reloc(str(path))
    df.attrs["source"] = _paths.short_path(path)
    return df


def location_table(cluster: str, branch: Optional[str] = None, save: bool = False):
    """Relocations with their bootstrap 95 % errors, one row per event (``pipeline.viz.location_table``).

    ``branch`` None reads the dt.cc relocation (the dt.ct one when there is none). ``save=True`` also writes
    ``final_locations.csv`` next to the relocation, as PocketQuake does by default.
    """
    import matplotlib as mpl

    config = _pipeline_config()
    with mpl.rc_context():  # pipeline.viz changes matplotlib settings when it is imported; keep yours
        viz = importlib.import_module("pipeline.viz")
    return viz.location_table(config.load_cluster(cluster), branch=branch, save=save)
