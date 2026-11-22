"""Checkers for M00 · Start here.

Where the truth comes from (no task is solved here):

* T1 asks Python itself (getpass, pwd, pathlib) who and where the notebook runs, and compares that with the
  values the student copied from a terminal.
* T2 re-reads data/catalogs/kma_catalog.csv with the csv module, datetime and os.stat (the student uses shell
  commands). Real data: expected values are never printed.
* T3 reads the live limits of this kernel from threadpoolctl, os and resource. A wrong cpus_allowed that equals
  the session's thread cap (CORES in the parameters cell) gets its own category.
* T4 and T5 ask git about the student's own copy. They depend on a personal GitHub setup, so they pass with
  details {'skipped': 'solution run'} when SGTL_SOLUTION_RUN=1 (automatic solution runs).

Credit: Minseong Seo (SGTL, Seoul National University). License: MIT.
"""
from __future__ import annotations

import csv
import datetime as _dt
import getpass
import io
import numbers
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import Outcome, outcome_from_cases
from ..submit import github_slug

__all__ = ["check_T1", "check_T2", "check_T3", "check_T4", "check_T5"]

PUBLIC_SLUG = "seismoseo/SGTL-earthquake-source-tutorial"
CATALOG_PARTS = ("data", "catalogs", "kma_catalog.csv")
AI_LOG_PARTS = ("work", "ai_log", "M00.md")
TEMPLATE_PARTS = ("docs", "templates", "ai_log_template.md")
_GIB = 1024 ** 3


# ----------------------------------------------------------------------------------------------- helpers
def _value_of(target: Any) -> Any:
    """The student's function is called with no arguments; a plain value is accepted as it is."""
    return target() if callable(target) else target


def _is_int(x: Any) -> bool:
    return isinstance(x, numbers.Integral) and not isinstance(x, bool)


def _is_number(x: Any) -> bool:
    return isinstance(x, numbers.Real) and not isinstance(x, bool)


def _skip_solution_run() -> Optional[Outcome]:
    if os.environ.get("SGTL_SOLUTION_RUN", "") == "1":
        return Outcome(passed=True, n_cases=1, n_failed=0, category=None,
                       message="Skipped: this check depends on your own GitHub setup (automatic solution run).",
                       details={"skipped": "solution run"})
    return None


def _cases(results: List[Tuple[bool, str]], *, note: Optional[str] = None, example: Optional[dict] = None,
           real_data: bool = True) -> Outcome:
    """Outcome from (passed, category) pairs; the first failing pair names the category."""
    first = next((cat for good, cat in results if not good), None)
    return outcome_from_cases([good for good, _ in results], category=first, note=note, example=example,
                              real_data=real_data)


def _all_fail(n: int, category: str, note: Optional[str] = None) -> Outcome:
    return _cases([(False, category)] * n, note=note)


def _same_place(a: Any, b: Any) -> bool:
    """Do two paths name the same folder (symbolic links and bind mounts allowed)?"""
    try:
        return os.path.samefile(a, b)
    except OSError:
        try:
            return Path(a).resolve() == Path(b).resolve()
        except (OSError, RuntimeError, ValueError):
            return False


def _inside(child: Any, parent: Any) -> bool:
    try:
        c, p = Path(child).resolve(), Path(parent).resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    return c != p and p in c.parents


def _git(repo: Path, *args: str, timeout: float = 20) -> Optional[str]:
    """stdout of ``git -C repo args`` (stripped), or None when git fails or is missing."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_TERMINAL_PROMPT="0", LC_ALL="C")
    try:
        done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                              timeout=timeout, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def _own_repo(repo: Path) -> bool:
    top = _git(repo, "rev-parse", "--show-toplevel")
    return bool(top) and _same_place(top, repo)


def _github_slug(url: str) -> Optional[str]:
    """'owner/name' (lower case) for a GitHub address in any form git accepts, else None (the parser of submit)."""
    slug = github_slug(str(url or ""))
    return slug.lower() if slug else None


def _is_public(url: Optional[str]) -> bool:
    return bool(url) and _github_slug(url) == PUBLIC_SLUG.lower()


# ------------------------------------------------------------------------------------- T1 who am I here
_T1_KEYS = ("user", "home", "repo")
_SHELL_SHORTCUTS = {"whoami", "pwd", "echo", "cd"}


def _not_output(text: str) -> bool:
    s = text.strip()
    return s.lower() in _SHELL_SHORTCUTS or s.startswith("~") or "$" in s


def _login_names() -> set:
    names = set()
    try:
        names.add(getpass.getuser())
    except Exception:
        pass
    try:
        import pwd

        names.add(pwd.getpwuid(os.geteuid()).pw_name)
    except Exception:
        pass
    return {n for n in names if n}


def _home_folders() -> List[str]:
    homes = [str(Path.home())]
    try:
        import pwd

        homes.append(pwd.getpwuid(os.getuid()).pw_dir)
    except Exception:
        pass
    return homes


def check_T1(target, ctx):
    me = _value_of(target)
    if not isinstance(me, dict):
        return _all_fail(3, "type")
    if set(me) != set(_T1_KEYS):
        return _all_fail(3, "keys")
    results, wrong, example = [], [], None
    for key in _T1_KEYS:
        value = me[key]
        if not isinstance(value, str):
            ok, cat = False, "type"
        elif _not_output(value):
            ok, cat = False, "not-output"
        elif key == "user":
            ok, cat = value.strip() in _login_names(), "user"
        elif key == "home":
            ok, cat = any(_same_place(value.strip(), h) for h in _home_folders()), "home"
        else:
            repo = Path(ctx["repo"])
            ok = _same_place(value.strip(), repo)
            cat = "subfolder" if not ok and _inside(value.strip(), repo) else "repo"
        results.append((ok, cat))
        if not ok:
            wrong.append(key)
            example = example or {"inputs": f"key '{key}'", "got": value}
    note = f"Keys that do not match yet: {', '.join(wrong)}." if wrong else None
    return _cases(results, note=note, example=example)


# --------------------------------------------------------------------------------- T2 shell scavenger hunt
_T2_KEYS = ("n_lines", "columns", "n_events_2016", "max_ml", "n_ml_ge_5", "size_kb")


def _utc(text: str) -> _dt.datetime:
    t = _dt.datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=_dt.timezone.utc)


def _catalog_facts(path: Path) -> Dict[str, Any]:
    """Facts about the catalog file, read with Python (an independent route from the shell)."""
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    table = list(csv.reader(io.StringIO(text)))
    header = [name.strip() for name in table[0]]
    rows = [r for r in table[1:] if any(cell.strip() for cell in r)]
    where = {name: i for i, name in enumerate(header)}
    t_utc = [_utc(r[where["origin_utc"]]) for r in rows]
    mags = [float(r[where["ml"]]) for r in rows if r[where["ml"]].strip()]
    shift = _dt.timedelta(hours=9)
    info = path.stat()
    blocks = getattr(info, "st_blocks", None)
    return {
        "n_lines": raw.count(b"\n"),
        "columns": header,
        "n_2016": sum(t.year == 2016 for t in t_utc),
        "n_2016_anywhere": sum("2016" in line for line in text.splitlines()),
        "n_2016_event_id": sum(r[where["event_id"]].strip().startswith("2016") for r in rows),
        "n_2016_kst": sum((t + shift).year == 2016 for t in t_utc),
        "max_ml": max(mags),
        "n_ge_5": sum(m >= 5.0 for m in mags),
        "n_gt_5": sum(m > 5.0 for m in mags),
        "bytes": info.st_size,
        "kib_apparent": info.st_size / 1024.0,
        "kib_disk": None if blocks is None else blocks * 512 / 1024.0,
    }


def _size_category(got: float, facts: Dict[str, Any], tol: float) -> Tuple[bool, str]:
    sizes = [facts["kib_apparent"]] + ([facts["kib_disk"]] if facts["kib_disk"] is not None else [])
    if any(abs(got - s) <= tol for s in sizes):
        return True, "size"
    b = facts["bytes"]
    other_units = [(b, 0.01 * b), (b / 1000.0, tol), (b / 1024.0 ** 2, 0.01), (b / 1e6, 0.01)]
    if any(abs(got - v) <= t for v, t in other_units):
        return False, "size-units"
    return False, "size"


def check_T2(target, ctx):
    answers = _value_of(target)
    if not isinstance(answers, dict):
        return _all_fail(len(_T2_KEYS), "type")
    if set(answers) != set(_T2_KEYS):
        return _all_fail(len(_T2_KEYS), "keys")
    facts = _catalog_facts(Path(ctx["repo"]).joinpath(*CATALOG_PARTS))
    tol = float((ctx.get("criteria") or {}).get("size_abs_tol_kb", 1.0))
    results, wrong, example = [], [], None
    for key in _T2_KEYS:
        got = answers[key]
        if key == "columns":
            if not isinstance(got, (list, tuple)) or not all(isinstance(c, str) for c in got):
                ok, cat = False, "type"
            else:
                ok, cat = [c.strip() for c in got] == facts["columns"], "columns"
        elif key == "max_ml":
            if not _is_number(got):
                ok, cat = False, "type"
            else:
                ok, cat = abs(float(got) - facts["max_ml"]) <= 1e-6, "max-ml"
        elif key == "size_kb":
            ok, cat = (False, "type") if not _is_number(got) else _size_category(float(got), facts, tol)
        elif not _is_int(got):
            ok, cat = False, "type"
        elif key == "n_lines":
            ok = got == facts["n_lines"]
            cat = "header" if got == facts["n_lines"] - 1 else "lines"
        elif key == "n_events_2016":
            ok, cat = got == facts["n_2016"], "year-count"
            for alt_key, alt_cat in (("n_2016_anywhere", "anywhere"), ("n_2016_event_id", "event-id"),
                                     ("n_2016_kst", "kst")):
                if not ok and got == facts[alt_key]:
                    cat = alt_cat
                    break
        else:  # n_ml_ge_5
            ok = got == facts["n_ge_5"]
            cat = "threshold" if not ok and got == facts["n_gt_5"] else "ml-count"
        results.append((ok, cat))
        if not ok:
            wrong.append(key)
            example = example or {"inputs": f"key '{key}'", "got": got}
    note = f"Keys that do not match the file yet: {', '.join(wrong)}." if wrong else None
    return _cases(results, note=note, example=example, real_data=True)


# --------------------------------------------------------------------------------- T3 the server rules
_T3_KEYS = ("blas_threads", "cpus_allowed", "mem_cap_gb")


def _live_limits() -> Tuple[set, int, Optional[float]]:
    """(thread counts of the BLAS pools, CPUs this process may use, soft data-memory limit in GB or None)."""
    blas: set = set()
    try:
        from threadpoolctl import threadpool_info

        blas = {int(p["num_threads"]) for p in threadpool_info()
                if p.get("user_api") == "blas" and p.get("num_threads") is not None}
    except Exception:
        blas = set()
    if not blas:
        for var in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS"):
            try:
                blas = {int(os.environ[var])}
                break
            except (KeyError, ValueError):
                continue
    try:
        cpus = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        cpus = os.cpu_count() or 1
    try:
        import resource

        soft, _hard = resource.getrlimit(resource.RLIMIT_DATA)
        mem = None if soft == resource.RLIM_INFINITY else soft / _GIB
    except Exception:
        mem = None
    return blas, cpus, mem


def _thread_cap(ctx) -> Optional[int]:
    """The thread cap st.init set from CORES (the session's cores), else OMP_NUM_THREADS, else None."""
    cores = getattr(ctx.get("session"), "cores", None)
    if _is_int(cores):
        return int(cores)
    try:
        return int(os.environ["OMP_NUM_THREADS"])
    except (KeyError, ValueError):
        return None


def _cpus_category(got: Any, cpus: int, ctx) -> Tuple[bool, str]:
    if not _is_int(got):
        return False, "type"
    if int(got) == cpus:
        return True, "cpus"
    cap = _thread_cap(ctx)
    return False, "thread-cap" if cap is not None and int(got) == cap else "cpus"


def _mem_category(got: Any, live: Optional[float], crit: dict) -> Tuple[bool, str]:
    if got is not None and not _is_number(got):
        return False, "type"
    if live is None:
        if got is None:
            return True, "mem-cap"
        return False, "units" if float(got) > 1e5 else "mem-cap"
    if got is None:
        return False, "mem-cap"
    g = float(got)
    tol = max(float(crit.get("mem_abs_tol_gb", 0.01)), float(crit.get("mem_rel_tol", 0.01)) * live)
    if abs(g - live) <= tol:
        return True, "mem-cap"
    in_other_units = (live * _GIB, live * 1024.0, live * _GIB / 1e9, live * _GIB / 1e6)
    if g > 1e5 or any(abs(g - v) <= 0.01 * v for v in in_other_units):
        return False, "units"
    return False, "mem-cap"


def check_T3(target, ctx):
    reading = _value_of(target)
    if not isinstance(reading, dict):
        return _all_fail(3, "type")
    if set(reading) != set(_T3_KEYS):
        return _all_fail(3, "keys")
    blas, cpus, mem = _live_limits()
    crit = ctx.get("criteria") or {}
    results = []
    got = reading["blas_threads"]
    results.append((False, "type") if not _is_int(got) else (int(got) in blas, "threads"))
    results.append(_cpus_category(reading["cpus_allowed"], cpus, ctx))
    results.append(_mem_category(reading["mem_cap_gb"], mem, crit))
    wrong = [k for k, (ok, _c) in zip(_T3_KEYS, results) if not ok]
    note = f"Keys that do not match this kernel yet: {', '.join(wrong)}." if wrong else None
    return _cases(results, note=note, real_data=True)


# ------------------------------------------------------------------------------------- T4 private copy
def check_T4(target, ctx):
    skipped = _skip_solution_run()
    if skipped is not None:
        return skipped
    remotes = _value_of(target)
    n = 6
    if not isinstance(remotes, dict) or not all(isinstance(v, str) for v in remotes.values()):
        return _all_fail(n, "type")
    if set(remotes) != {"origin", "upstream"}:
        return _all_fail(n, "keys")
    repo = Path(ctx["repo"])
    if not _own_repo(repo):
        return _all_fail(n, "not-a-repo")
    results = [(True, "not-a-repo")]
    up = _git(repo, "remote", "get-url", "upstream")
    results.append((False, "no-upstream") if not up else (_is_public(up), "upstream-url"))
    origin = _git(repo, "remote", "get-url", "origin")
    results.append((False, "no-origin") if not origin else (not _is_public(origin), "origin-is-public"))
    push = _git(repo, "remote", "get-url", "--push", "upstream") if up else None
    results.append((bool(up) and not _is_public(push or "") and (push or "") != up, "upstream-push"))
    hooks = (_git(repo, "config", "--get", "core.hooksPath") or "").strip()
    hooks_ok = hooks.rstrip("/") in (".githooks", "./.githooks") or (
        bool(hooks) and _same_place(Path(hooks) if Path(hooks).is_absolute() else repo / hooks,
                                    repo / ".githooks"))
    results.append((hooks_ok, "hooks"))

    def same(mine: str, actual: Optional[str]) -> bool:
        if not actual:
            return False
        mine, actual = mine.strip(), actual.strip()
        return mine == actual or (_github_slug(mine) is not None and _github_slug(mine) == _github_slug(actual))

    results.append((same(remotes["origin"], origin) and same(remotes["upstream"], up), "mismatch"))
    return _cases(results)


# --------------------------------------------------------------------------- T5 AI log and first commit
_LOG_FIELDS = ("what i asked", "what the ai answered", "what i used", "did the help touch", "what i learned")
_FIELD_LINE = re.compile(r"^[-*+]\s*\*\*(?P<label>.+?)\*\*(?P<rest>.*)$")
_ENTRY_HEAD = re.compile(r"^#{2,6}\s*\d{4}-\d{2}-\d{2}\b(?P<rest>.*)$")
_WORD = re.compile(r"[^\W_]+(?:['’-][^\W_]+)*")


def _squash(text: str) -> str:
    return " ".join(text.split())


def _field_key(label: str) -> Optional[str]:
    norm = _squash(re.sub(r"[^\w\s,]", " ", label.lower()))
    return next((k for k in _LOG_FIELDS if norm.startswith(k)), None)


def _template_parts(template: str) -> Tuple[set, Dict[str, str]]:
    """Template lines (to ignore) and, per field, the template's text after the bold label (to strip)."""
    lines, rests = set(), {}
    for raw in template.splitlines():
        s = raw.strip()
        if s:
            lines.add(_squash(s))
        m = _FIELD_LINE.match(s)
        if m and _field_key(m.group("label")):
            rests[_field_key(m.group("label"))] = m.group("rest").strip()
    return lines, rests


def _log_report(text: str, template: str) -> Tuple[bool, List[str], int]:
    """(has a dated M00 entry, fields still empty, words written by the student)."""
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    template = re.sub(r"<!--.*?-->", " ", template, flags=re.S)
    t_lines, t_rests = _template_parts(template)
    has_entry, filled, own, current = False, {}, 0, None
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue
        head = _ENTRY_HEAD.match(s)
        if head:
            has_entry = has_entry or bool(re.search(r"\bM00-T\d+\b", head.group("rest")))
            current = None
            continue
        if s.startswith("#"):
            current = None
            continue
        field = _FIELD_LINE.match(s)
        if _squash(s) in t_lines:  # an untouched template line
            current = _field_key(field.group("label")) if field else None
            continue
        if s.lower().startswith("no ai help used in this module"):
            continue
        if field:
            current = _field_key(field.group("label"))
            rest = field.group("rest").strip()
            fill = t_rests.get(current or "", "")
            if fill and rest.startswith(fill):
                rest = rest[len(fill):]
            words = len(_WORD.findall(rest))
        else:
            words = len(_WORD.findall(s))
        if current:
            filled[current] = filled.get(current, 0) + words
        own += words
    missing = [k for k in _LOG_FIELDS if not filled.get(k)]
    return has_entry, missing, own


def check_T5(target, ctx):
    skipped = _skip_solution_run()
    if skipped is not None:
        return skipped
    commit = _value_of(target)
    n = 10
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-fA-F]{7,40}", commit.strip()):
        return _all_fail(n, "type")
    commit = commit.strip()
    repo = Path(ctx["repo"])
    log_path = repo.joinpath(*AI_LOG_PARTS)
    if not log_path.is_file():
        return _all_fail(n, "no-log")
    try:
        template = repo.joinpath(*TEMPLATE_PARTS).read_text(encoding="utf-8")
    except OSError:
        template = ""
    has_entry, missing, own = _log_report(log_path.read_text(encoding="utf-8", errors="replace"), template)
    min_words = int((ctx.get("criteria") or {}).get("min_words", 40))
    note = f"Your log has {own} words of your own (not counting the template text)."
    results = [(True, "no-log"), (has_entry, "log-entry"), (not missing, "log-sections"),
               (own >= min_words, "log-unfilled")]
    if not all(ok for ok, _c in results):
        return _cases(results + [(False, "not-a-repo")] * (n - len(results)), note=note)
    if not _own_repo(repo):
        return _cases(results + [(False, "not-a-repo")] * (n - len(results)), note=note)
    results.append((True, "not-a-repo"))
    rel = "/".join(AI_LOG_PARTS)
    sha = _git(repo, "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}")
    known = bool(sha) and _git(repo, "merge-base", "--is-ancestor", sha, "HEAD") is not None
    results.append((known, "unknown-commit"))
    results.append((known and _git(repo, "cat-file", "-e", f"{sha}:{rel}") is not None, "log-not-in-commit"))
    status = _git(repo, "status", "--porcelain", "--", rel)
    results.append((status == "", "uncommitted"))
    tracking = _git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}") or ""
    results.append((tracking.startswith("origin/"), "no-tracking"))
    ahead = _git(repo, "rev-list", "--count", "@{u}..HEAD") if tracking else None
    results.append((ahead is not None and ahead.isdigit() and int(ahead) == 0, "not-pushed"))
    return _cases(results, note=note)
