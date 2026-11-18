"""Check engine: predictions, checks, hints, rerolls and the progress table.

How a check runs (``st.check("M01-T1", func=great_circle_km)``):

1. The task must have a logged prediction (``st.predict``), else status NO PREDICTION.
2. The session guard (every task kind): when the notebook session imported or used the checkers' own code
   (``sgtl_tutorial.checkers``), the check FAILs with category ``checker-internals`` and no checker runs. Two
   parts: the static scan of the session's code and objects (``astguard.scan_session``) and the run-time guard,
   an audit hook that marks the session when a checker module is imported or a checker file is read by anything
   but this engine (``astguard.watch_checkers``).
3. A function target is screened by the AST guard against the spec's ``forbidden`` list (category
   ``forbidden-import``); a function that builds module or attribute names while it runs, or whose code cannot be
   read, FAILs with category ``runtime-name`` (``astguard.check_function``).
4. The checker ``check_T1(target, ctx)`` of ``sgtl_tutorial/checkers/m01.py`` runs and returns an
   :class:`Outcome`. The engine reads and compiles that file itself into a fresh namespace that never enters
   ``sys.modules`` and is emptied after the check. If anything inside raises NotImplementedError, status is
   NOT STARTED.
5. A short box is printed; one JSON line is appended to ``<repo>/work/.sgtl/progress.jsonl``.
6. With ``SGTL_STRICT=1`` (CI), anything but PASS raises AssertionError.

Only PASS and FAIL count as attempts. Real-data expected values are never printed. In ``checks/checks.json`` the
locked hints (levels 2 and 3) and the failure categories are stored zlib-compressed and base64-encoded (not secret,
just not readable at a glance); only ``hint`` (once the level is unlocked) and ``check`` (when a category fires)
decode them, and ``task_spec`` shows only what is unlocked.
"""
from __future__ import annotations

import base64
import builtins
import json
import os
import re
import textwrap
import zlib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import _paths, astguard
from .session import current, log_event, read_log, seed_for, user_name

__all__ = [
    "Outcome",
    "CheckContext",
    "CheckResult",
    "PASS",
    "FAIL",
    "NOT_STARTED",
    "NO_PREDICTION",
    "ERROR",
    "load_specs",
    "load_criteria",
    "task_spec",
    "predict",
    "check",
    "hint",
    "reroll",
    "progress",
]

PASS, FAIL, NOT_STARTED, NO_PREDICTION, ERROR = "PASS", "FAIL", "NOT STARTED", "NO PREDICTION", "ERROR"
TASK_RE = re.compile(r"^(M\d{2})-T(\d+)$")
_WIDTH = 92
_EMPTY_PREDICTIONS = {"", "...", "todo", "tbd", "write your prediction here", "your prediction here"}
_NOT_TOLERANCE = {"trials", "cases", "n_cases", "seed", "note", "notes", "frozen"}
DEFAULT_MESSAGES = {
    "forbidden-import": "This task asks you to write this step yourself, so the rule is: do not use {rules} here.",
    "checker-internals": "A check must judge your own work, so the rule is: do not import, call or copy the "
                         "checkers' own code (sgtl_tutorial.checkers) in your notebook.",
    "runtime-name": "The check reads your function's code to see which libraries it uses, so the rule is: write "
                    "each import and each name you take from a module out in full (import x, from x import y, x.y, "
                    "or getattr(x, \"y\") with the name in quotes) and define the function with def in a notebook "
                    "cell. Do not put such names together while the code runs (import_module or getattr with a "
                    "name made of pieces or kept in a variable), and do not use eval, exec, compile, globals(), "
                    "locals(), vars(), __dict__ or sys.modules.",
    "exception": "Your code stopped with an error: {error}",
}
_SHOW_FOUND = 3

try:  # from now on keep a private record of the cells this IPython session runs (see astguard.scan_session)
    astguard.install_cell_record()
except Exception:  # noqa: BLE001 - never block "import sgtl_tutorial"
    pass


# ----------------------------------------------------------------------------- data classes
@dataclass
class Outcome:
    """What a checker returns.

    ``details`` may hold ``real_data`` (True hides values), ``example`` = ``{"inputs", "got",
    "error"}`` for one failing synthetic case, and ``note`` (a sentence that is always shown).
    """

    passed: bool
    n_cases: int = 1
    n_failed: int = 0
    category: Optional[str] = None
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


class CheckContext(dict):
    """Information for a checker. Read it as ``ctx["rng"]`` or ``ctx.rng``.

    Keys: rng, seed, reroll, criteria, strict, session, task, module, spec, user, repo, data_root,
    plus any extra keyword arguments given to ``st.check``.
    """

    def __getattr__(self, key: str) -> Any:
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc


@dataclass
class CheckResult:
    """Returned by ``st.check``; ``bool(result)`` is True only for PASS."""

    task: str
    status: str
    outcome: Optional[Outcome] = None
    seed: Optional[int] = None
    reroll: int = 0
    attempt: Optional[int] = None
    text: str = ""
    _shown: bool = field(default=False, repr=False)

    @property
    def passed(self) -> bool:
        return self.status == PASS

    @property
    def category(self) -> Optional[str]:
        return self.outcome.category if self.outcome else None

    def __bool__(self) -> bool:
        return self.passed

    def __str__(self) -> str:
        return self.text

    def __repr__(self) -> str:
        return f"CheckResult({self.task}: {self.status})"

    def _ipython_display_(self) -> None:  # the box was already printed by st.check
        if self._shown:
            self._shown = False
            return
        print(self.text)


# ----------------------------------------------------------------------------- spec loading
_CACHE: Dict[Any, Dict[str, dict]] = {}


def _yaml_load(path: Path) -> Any:
    import yaml

    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    with open(path, encoding="utf-8") as fh:
        return yaml.load(fh, Loader=loader) or {}


def _signature(kind: str, files: List[Path]) -> Tuple:
    return (kind,) + tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in files)


_ENCODED = "zb64:"  # prefix of a text stored zlib-compressed and base64-encoded (see tools/compile_checks.py)


def _encode(text: str) -> str:
    return _ENCODED + base64.b64encode(zlib.compress(text.encode("utf-8"), 9)).decode("ascii")


def _decode(value: Any) -> str:
    if isinstance(value, str) and value.startswith(_ENCODED):
        return zlib.decompress(base64.b64decode(value[len(_ENCODED):])).decode("utf-8")
    return "" if value is None else str(value)


def _normalize_spec(task: str, spec: Optional[dict], module: Optional[str]) -> dict:
    """A loaded spec keeps the locked hints (levels 2 and 3) and the failure categories encoded, whatever the
    source (checks.json stores them encoded; the instructor's YAML is encoded here)."""
    spec = dict(spec or {})
    spec.setdefault("module", module or task.split("-")[0])
    hints: Dict[int, str] = {}
    for k, v in (spec.get("hints") or {}).items():
        level = int(k)
        if level <= 1:
            hints[level] = _decode(v)
        else:
            hints[level] = v if isinstance(v, str) and v.startswith(_ENCODED) else _encode(_decode(v))
    spec["hints"] = hints
    cats = spec.get("categories") or {}
    if isinstance(cats, dict):
        cats = _encode(json.dumps({str(k): str(v) for k, v in cats.items()}, sort_keys=True)) if cats else ""
    spec["categories"] = cats if isinstance(cats, str) else ""
    spec["forbidden"] = [str(f) for f in (spec.get("forbidden") or [])]
    return spec


def _categories(spec: dict) -> Dict[str, str]:
    raw = spec.get("categories")
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    try:
        data = json.loads(_decode(raw)) if raw else {}
    except (ValueError, zlib.error):
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def _category_text(spec: dict, category: Optional[str]) -> Optional[str]:
    """The fixed message of one failure category (decoded only when that category fires)."""
    return _categories(spec).get(category) if category else None


def _hint_text(spec: dict, level: int) -> str:
    try:
        return _decode(spec.get("hints", {}).get(level))
    except (ValueError, zlib.error):
        return ""


def load_specs(repo: Optional[Path] = None) -> Dict[str, dict]:
    """Task specs: ``checks/specs/*.yaml`` when present (instructor), else ``checks/checks.json``."""
    repo = Path(repo or _paths.repo_root())
    spec_dir = repo / "checks" / "specs"
    files = sorted(spec_dir.glob("*.yaml")) if spec_dir.is_dir() else []
    if files:
        key = _signature("yaml", files)
        if key not in _CACHE:
            tasks: Dict[str, dict] = {}
            for f in files:
                data = _yaml_load(f)
                module = data.get("module")
                for tid, spec in (data.get("tasks") or {}).items():
                    tasks[str(tid)] = _normalize_spec(str(tid), spec, module)
            _CACHE[key] = tasks
        return _CACHE[key]
    cj = repo / "checks" / "checks.json"
    if not cj.is_file():
        return {}
    key = _signature("json", [cj])
    if key not in _CACHE:
        data = json.loads(cj.read_text(encoding="utf-8"))
        _CACHE[key] = {str(t): _normalize_spec(str(t), s, None) for t, s in (data.get("tasks") or {}).items()}
    return _CACHE[key]


def load_criteria(repo: Optional[Path] = None) -> Dict[str, dict]:
    """Frozen pass criteria from ``criteria/*.yaml``: ``{task_id: {...}}``."""
    repo = Path(repo or _paths.repo_root())
    files = sorted((repo / "criteria").glob("*.yaml")) if (repo / "criteria").is_dir() else []
    key = _signature("criteria", files)
    if key not in _CACHE:
        out: Dict[str, dict] = {}
        for f in files:
            for tid, crit in ((_yaml_load(f).get("tasks")) or {}).items():
                out[str(tid)] = dict(crit or {})
        _CACHE[key] = out
    return _CACHE[key]


def _spec(task_id: str, repo: Optional[Path] = None) -> dict:
    """The engine's spec of one task (raises KeyError with a plain message when unknown)."""
    if not TASK_RE.match(task_id or ""):
        raise KeyError(f"{task_id!r} is not a task id; task ids look like 'M01-T1'.")
    specs = load_specs(repo)
    if task_id not in specs:
        same = sorted(t for t in specs if t.startswith(task_id.split("-")[0] + "-"))
        raise KeyError(f"Unknown task {task_id!r}. Tasks of this module: {', '.join(same) or 'none found'}. "
                       "If your copy of the tutorial is old, update it (see docs).")
    return specs[task_id]


def task_spec(task_id: str, repo: Optional[Path] = None) -> dict:
    """The spec of one task as you may see it: the hints unlocked so far (level 1 always, level 2 after one failed
    check, level 3 after two) and the failure categories your checks of this task have reported."""
    repo = Path(repo or _paths.repo_root())
    spec = _spec(task_id, repo)
    out = {k: v for k, v in spec.items() if k not in ("hints", "categories")}
    unlocked = _unlocked_hint(task_id, repo)
    out["hints"] = {lvl: _hint_text(spec, lvl) for lvl in sorted(spec["hints"]) if lvl <= unlocked}
    fired = {str(e.get("category")) for e in _events(task_id, "check", repo) if e.get("category")}
    cats = _categories(spec)
    out["categories"] = {k: cats[k] for k in sorted(fired) if k in cats}
    return out


# ----------------------------------------------------------------------------- log queries
def _events(task: str, event: str, repo: Path, user: Optional[str] = None) -> List[dict]:
    return [e for e in read_log(repo) if e.get("task") == task and e.get("event") == event
            and (user is None or e.get("user") == user)]


def _has_prediction(task: str, repo: Path) -> bool:
    return any(e.get("status") == "ok" and str(e.get("text") or "").strip() for e in _events(task, "predict", repo))


def _n_fail(task: str, repo: Path) -> int:
    return sum(1 for e in _events(task, "check", repo) if e.get("status") == FAIL)


def _n_attempts(task: str, repo: Path) -> int:
    return sum(1 for e in _events(task, "check", repo) if e.get("status") in (PASS, FAIL))


def _reroll_index(task: str, repo: Path, user: str) -> int:
    return len(_events(task, "reroll", repo, user))


def _unlocked_hint(task: str, repo: Path) -> int:
    """Highest hint level open now: 1 always, 2 after one failed check, 3 after two."""
    return 1 + min(_n_fail(task, repo), 2)


def _max_hint_shown(task: str, repo: Path) -> int:
    levels = [int(e.get("level") or 0) for e in _events(task, "hint", repo) if e.get("status") == "shown"]
    return max(levels, default=0)


# ----------------------------------------------------------------------------- rendering
def _fmt(value: Any, limit: int = 240) -> str:
    try:
        import numpy as np

        if isinstance(value, np.ndarray):
            s = np.array2string(value, precision=6, threshold=12, separator=", ")
            return s if len(s) <= limit else s[: limit - 3] + "..."
        if isinstance(value, np.generic):
            value = value.item()
    except ImportError:
        pass
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, dict):
        return ", ".join(f"{k}={_fmt(v, 60)}" for k, v in value.items())[:limit]
    if isinstance(value, (list, tuple)):
        s = "[" + ", ".join(_fmt(v, 40) for v in value) + "]"
        return s if len(s) <= limit else s[: limit - 3] + "..."
    s = repr(value) if not isinstance(value, str) else value
    return s if len(s) <= limit else s[: limit - 3] + "..."


def _box(title: str, lines: List[str]) -> str:
    out = ["+-- " + title]
    for line in lines:
        for raw in str(line).split("\n"):
            indent = len(raw) - len(raw.lstrip(" "))
            wrapped = textwrap.wrap(raw, width=_WIDTH - 2, subsequent_indent=" " * (indent + 2),
                                    break_long_words=False, break_on_hyphens=False) or [""]
            out.extend("| " + w for w in wrapped)
    out.append("+" + "-" * (_WIDTH - 1))
    return "\n".join(out)


def _tolerance_text(criteria: dict) -> str:
    items = [f"{k}={_fmt(v, 40)}" for k, v in criteria.items() if k not in _NOT_TOLERANCE]
    return ", ".join(items)


def _title(task: str, spec: dict) -> str:
    bits = [task, spec.get("title") or ""]
    if spec.get("tier"):
        bits.append(str(spec["tier"]))
    return " · ".join(b for b in bits if b)


# ----------------------------------------------------------------------------- public API
def _strict() -> bool:
    return os.environ.get("SGTL_STRICT", "") == "1"


def _is_empty_prediction(text: str) -> bool:
    return text.strip().strip(".!").strip().lower() in _EMPTY_PREDICTIONS


def predict(task_id: str, text: str) -> None:
    """Log your prediction for a task (what you expect, before you code). Required before st.check."""
    repo = _paths.repo_root()
    spec = _spec(task_id, repo)
    clean = (text or "").strip()
    if _is_empty_prediction(clean):
        print(_box(_title(task_id, spec), [
            "Your prediction is still empty, so nothing was saved.",
            "Write 1-3 sentences inside the quotes: what do you expect the result to be, and why?",
        ]))
        return None
    rec = log_event("predict", task_id, status="ok", text=clean, repo=repo)
    print(f"Prediction for {task_id} saved at {rec['ts'].replace('T', ' ')} ({len(clean)} characters). "
          "Now write your code and run the check.")
    return None


def _student_frames(exc: BaseException, target: Any) -> bool:
    """True when the error passed through code the student wrote (same module as the target)."""
    mod = getattr(astguard._unwrap(target), "__module__", None) if callable(target) else None
    if not mod or mod.startswith("sgtl_tutorial"):
        return False
    tb = exc.__traceback__
    while tb is not None:
        if tb.tb_frame.f_globals.get("__name__") == mod:
            return True
        tb = tb.tb_next
    return False


def _checkers_dir() -> Path:
    return Path(__file__).resolve().parent / "checkers"


def _checker_path(module_id: str) -> Path:
    """The checker file of a module: ``"m04"`` -> ``<package>/checkers/m04.py``."""
    return _checkers_dir() / f"{module_id}.py"


def _resolve_checker(task: str, namespace: Dict[str, Any]) -> Callable:
    """Load the task's checker privately: read its file, compile it and run it in ``namespace`` (a fresh dict from
    ``check``), so the module never enters ``sys.modules``. The run-time guard allows this read only when ``check``
    itself calls this function; read from anywhere else, a checker file marks the session.

    Checker modules may import the package (``from .. import synth``) and the checkers' package helpers
    (``from . import Outcome``), not each other. The code is compiled under a name in angle brackets, so warnings
    and tracebacks never reopen the file."""
    m = TASK_RE.match(task)
    assert m is not None
    module_id = m.group(1).lower()
    path = Path(_checker_path(module_id))
    with open(path, "rb") as fh:
        source = fh.read()
    namespace.update({"__name__": f"{astguard.CHECKERS}.{module_id}", "__package__": astguard.CHECKERS,
                      "__builtins__": builtins, "__loader__": None, "__spec__": None})
    exec(compile(source, f"<sgtl checker {path.name}>", "exec", dont_inherit=True), namespace)
    return namespace[f"check_T{m.group(2)}"]


def _shareable(outcome: Optional[Outcome]) -> Optional[Outcome]:
    """The Outcome handed back to the notebook. For real-data cases it keeps only what the box may show (the
    inputs and the student's own value): an error size or an expected value there would give the answer away."""
    details = outcome.details if outcome is not None else None
    if not isinstance(details, dict) or not details.get("real_data"):
        return outcome
    keep = {k: details[k] for k in ("real_data", "note", "found") if k in details}
    example = details.get("example")
    if isinstance(example, dict):
        keep["example"] = {k: example[k] for k in ("inputs", "got") if k in example}
    return replace(outcome, details=keep)


def _as_outcome(value: Any) -> Outcome:
    if isinstance(value, Outcome):
        return value
    if isinstance(value, bool):
        return Outcome(passed=value, n_cases=1, n_failed=0 if value else 1)
    if isinstance(value, dict):
        return Outcome(**value)
    raise TypeError(f"checker returned {type(value).__name__}, expected Outcome")


def check(task_id: str, answer: Any = None, *, func: Optional[Callable] = None, **ctx: Any) -> CheckResult:
    """Check your function (``func=``) or your answer (``answer=``) for a task and print the result."""
    sess = current()
    repo = _paths.repo_root()
    spec = _spec(task_id, repo)
    criteria = dict(load_criteria(repo).get(task_id, {}))
    strict = _strict()
    user = user_name()
    reroll_n = _reroll_index(task_id, repo, user)
    seed = seed_for(user, task_id, reroll_n)
    title = _title(task_id, spec)
    seed_txt = f"seed {seed} (reroll {reroll_n})"

    if func is None and spec.get("target") == "func" and callable(answer):
        func, answer = answer, None
    if answer is Ellipsis:
        answer = None
    target = func if func is not None else answer

    def finish(status: str, lines: List[str], outcome: Optional[Outcome] = None,
               counted: bool = False) -> CheckResult:
        attempt = _n_attempts(task_id, repo) + 1 if counted else None
        cat = outcome.category if outcome is not None and status != PASS else None
        if counted:
            lines = lines + [f"Attempt {attempt} · logged"]
        text = _box(title, lines)
        log_event("check", task_id, status=status, attempt=attempt, seed=seed, category=cat, repo=repo,
                  reroll=reroll_n)
        res = CheckResult(task=task_id, status=status, outcome=_shareable(outcome), seed=seed, reroll=reroll_n,
                          attempt=attempt, text=text, _shown=True)
        print(text)
        if strict and status != PASS:
            raise AssertionError(f"{task_id}: {status}\n{text}")
        return res

    # 1. prediction gate
    if not _has_prediction(task_id, repo) and not (strict and os.environ.get("SGTL_SOLUTION_RUN") == "1"):
        return finish(NO_PREDICTION, [
            "NO PREDICTION · write down what you expect before checking (nothing was counted).",
            f'Next step: in the prediction cell above, write your expectation inside the quotes of '
            f'st.predict("{task_id}", """ ... """) and run that cell, then run this check again.',
        ])

    # 2. something to check?
    if target is None and spec.get("target") in ("func", "answer"):
        what = "your function: st.check(..., func=your_function)" if spec.get("target") == "func" \
            else "your answer: st.check(..., answer=your_answer)"
        return finish(NOT_STARTED, [
            "NOT STARTED · there is nothing to check yet (nothing was counted).",
            f"Next step: finish the task, then pass {what}.",
        ])

    # 3. session guard (every task kind): the checkers' own code must not have been used in this session
    notes: List[str] = []
    marks = astguard.watch_checkers(*_ENGINE_CODES, _checkers_dir())
    if marks is None:
        return finish(ERROR, [
            "ERROR · the session guard could not start, so nothing was checked (nothing was counted).",
            "Next step: restart the kernel (Kernel > Restart Kernel), run your cells again from the top, then run "
            "this check again. If this happens again, tell your mentor.",
        ])
    session_rep = astguard.scan_session(repo)
    if session_rep.note:
        if strict:
            raise AssertionError(f"{task_id}: session guard failed: {session_rep.note}")
        notes.append("Note: " + session_rep.note)
    found = list(session_rep.found) + list(marks)
    if found:
        msg = _category_text(spec, "checker-internals") or DEFAULT_MESSAGES["checker-internals"]
        shown = found[:_SHOW_FOUND]
        more = len(found) - len(shown)
        out = Outcome(passed=False, n_cases=0, n_failed=0, category="checker-internals", message=msg,
                      details={"found": found})
        return finish(FAIL, notes + [
            f"FAIL · rule broken: the checkers' own code was used · {seed_txt}",
            f"Problem (checker-internals): {msg}",
            "Found in your session: " + "; ".join(shown) + (f" (and {more} more)" if more else ""),
            "Next step: delete that code, restart the kernel (Kernel > Restart Kernel), run your cells again "
            "from the top, then run this check again.",
        ], out, counted=True)

    # 4. AST guard
    if callable(target) and spec.get("forbidden"):
        rep = astguard.check_function(target, spec["forbidden"], repo=repo)
        if rep.note:
            notes.append("Note: " + rep.note)
        if not rep.ok:
            rule_msg = _category_text(spec, "forbidden-import") or DEFAULT_MESSAGES["forbidden-import"]
            rule_msg = rule_msg.replace("{rules}", ", ".join(rep.violations))
            if rep.runtime:  # names built while the code runs: the guard cannot judge them, so they come first
                msg = _category_text(spec, "runtime-name") or DEFAULT_MESSAGES["runtime-name"]
                shown, more = rep.runtime[:_SHOW_FOUND], len(rep.runtime) - _SHOW_FOUND
                out = Outcome(passed=False, n_cases=0, n_failed=0, category="runtime-name", message=msg,
                              details={"found": list(rep.runtime), "rules": rep.offending})
                return finish(FAIL, [
                    f"FAIL · names built while the code runs · {seed_txt}",
                    f"Problem (runtime-name): {msg}",
                    "Found in your code: " + "; ".join(shown) + (f" (and {more} more)" if more > 0 else ""),
                ] + ([f"Also (forbidden-import): {rule_msg} Found: {', '.join(rep.offending)}"]
                     if rep.violations else []) + [
                    "Next step: write those names out in full in the code (or leave the step out), then run this "
                    f'check again. Stuck? st.hint("{task_id}", 1)',
                ], out, counted=True)
            out = Outcome(passed=False, n_cases=0, n_failed=0, category="forbidden-import", message=rule_msg,
                          details={"found": rep.offending})
            return finish(FAIL, [
                f"FAIL · library rule broken · {seed_txt}",
                f"Problem (forbidden-import): {rule_msg}",
                f"Found in your code: {', '.join(rep.offending)}",
                f'Next step: rewrite the function without it. Stuck? st.hint("{task_id}", 1)',
            ], out, counted=True)

    # 5. run the checker
    from .synth import rng_for

    context = CheckContext(rng=rng_for(user, task_id, reroll_n), seed=seed, reroll=reroll_n, criteria=criteria,
                           strict=strict, session=sess, task=task_id, module=spec.get("module"), spec=spec,
                           user=user, repo=repo, data_root=_paths.data_root())
    for k, v in ctx.items():
        if k in context:
            raise TypeError(f"st.check: the keyword {k!r} is reserved; use another name.")
        context[k] = v
    namespace: Dict[str, Any] = {}  # the checker's module namespace: private, emptied when the check ends
    try:
        try:  # called from here only: the run-time guard allows the read for check() itself, nobody else
            checker = _resolve_checker(task_id, namespace)
        except (OSError, KeyError, ImportError) as exc:
            why = (f"the checker needs a package that is missing ({exc})" if isinstance(exc, ImportError)
                   else "there is no checker for this task in your copy of the tutorial")
            return finish(ERROR, [f"ERROR · {why} (nothing was counted).", "Next step: run 'sgtl doctor' in a "
                                  "terminal; if that does not help, tell your mentor."])
        except Exception as exc:  # noqa: BLE001 - a broken checker file
            return finish(ERROR, [f"ERROR · the checker for this task could not start ({type(exc).__name__}); "
                                  "nothing was counted.", "Next step: tell your mentor."])
        return _run_checker(task_id, checker, target, context, finish, notes, seed_txt, criteria, repo, spec)
    finally:
        namespace.clear()


def _run_checker(task_id: str, checker: Callable, target: Any, context: "CheckContext", finish: Callable,
                 notes: List[str], seed_txt: str, criteria: dict, repo: Path, spec: dict) -> "CheckResult":
    """Steps 5 and 6 of :func:`check`: run the loaded checker on the target and report.

    Whatever is raised from here (strict mode's AssertionError, an interrupt) is raised outside the ``except``
    blocks, so it carries no traceback into the checker's frames and their local values."""
    failure: Optional[Tuple[str, str]] = None
    escaped: Optional[BaseException] = None
    try:
        outcome = _as_outcome(checker(target, context))
    except NotImplementedError:
        failure = ("not-started", "")
    except Exception as exc:  # noqa: BLE001 - shown to the student in plain words
        failure = ("student" if _student_frames(exc, target) else "checker", f"{type(exc).__name__}: {exc}")
    except KeyboardInterrupt:
        escaped = KeyboardInterrupt("the check was interrupted")
    except SystemExit as exc:
        escaped = SystemExit(exc.code)
    if escaped is not None:
        raise escaped
    if failure is not None:
        kind, err = failure
        if kind == "not-started":
            return finish(NOT_STARTED, notes + [
                "NOT STARTED · your function still raises NotImplementedError (nothing was counted).",
                'Next step: replace the line "raise NotImplementedError(...)" with your code, '
                "then run this check again.",
            ])
        if kind == "student":
            msg = DEFAULT_MESSAGES["exception"].replace("{error}", _fmt(err, 300))
            out = Outcome(passed=False, n_cases=1, n_failed=1, category="exception", message=msg)
            return finish(FAIL, notes + [
                f"FAIL · your code raised an error · {seed_txt}",
                f"Problem (exception): {msg}",
                f'Next step: run your function by hand on a simple input to see the error. '
                f'Stuck? st.hint("{task_id}", 1)',
            ], out, counted=True)
        return finish(ERROR, notes + [
            f"ERROR · the checker could not use your result ({_fmt(err, 200)}). Nothing was counted.",
            "Next step: check that your function returns what the Contract asks for (type, shape, units). "
            "If it does, tell your mentor.",
        ])

    # 6. report
    n = int(outcome.n_cases or 0)
    n_pass = max(0, n - int(outcome.n_failed or 0))
    tol = _tolerance_text(criteria)
    head = [("PASS" if outcome.passed else "FAIL")]
    if n:
        head.append(f"{n_pass}/{n} cases passed")
    if tol:
        head.append(f"tolerance {tol}")
    head.append(seed_txt)
    lines = notes + [" · ".join(head)]
    details = outcome.details or {}
    real = bool(details.get("real_data"))
    if outcome.passed:
        if outcome.message:
            lines.append(outcome.message)
        if details.get("note"):
            lines.append(str(details["note"]))
        lines.append("Next step: answer the Explain prompt below (3-5 sentences), then go on.")
        return finish(PASS, lines, outcome, counted=True)

    cat = outcome.category or "wrong"
    msg = _category_text(spec, cat) or outcome.message or "Some cases are outside the tolerance."
    lines.append(f"Problem ({cat}): {msg}")
    example = details.get("example") or {k: details[k] for k in ("inputs", "got", "error") if k in details}
    if example and not real:
        bits = []
        if "inputs" in example:
            bits.append(f"inputs {_fmt(example['inputs'])}")
        if "got" in example:
            bits.append(f"your value {_fmt(example['got'])}")
        if "error" in example:
            bits.append(f"error {_fmt(example['error'])}")
        lines.append("Example case: " + " -> ".join(bits[:2]) + (f" ({bits[2]})" if len(bits) > 2 else ""))
    elif example and real:
        if "inputs" in example:
            lines.append(f"Example case: {_fmt(example['inputs'])}" +
                         (f" -> your value {_fmt(example['got'])}" if "got" in example else ""))
    if details.get("note"):
        lines.append(str(details["note"]))
    n_fail_after = _n_fail(task_id, repo) + 1
    unlocked = 1 + min(n_fail_after, 2)
    level = min(unlocked, _max_hint_shown(task_id, repo) + 1)
    lines.append(f'Next step: fix your code and run this check again. Stuck? st.hint("{task_id}", {level})')
    return finish(FAIL, lines, outcome, counted=True)


def hint(task_id: str, level: int = 1) -> None:
    """Show a hint. Level 1 is always available; level 2 after 1 failed check; level 3 after 2."""
    repo = _paths.repo_root()
    spec = _spec(task_id, repo)
    level = int(level)
    if level not in (1, 2, 3):
        raise ValueError("Hint levels are 1, 2 and 3.")
    n_fail = _n_fail(task_id, repo)
    unlocked = _unlocked_hint(task_id, repo)
    title = f"Hint {level} of 3 · {_title(task_id, spec)}"
    if level > unlocked:
        log_event("hint", task_id, status="locked", repo=repo, level=level)
        need = level - 1
        print(_box(title, [
            f"Locked: hint {level} unlocks after {need} failed check{'s' if need > 1 else ''} "
            f"(you have {n_fail}).",
            f'Try st.hint("{task_id}", {unlocked}) first, or run the check with your best attempt.',
        ]))
        return None
    text = _hint_text(spec, level)  # a locked hint is never decoded
    if not text:
        log_event("hint", task_id, status="missing", repo=repo, level=level)
        print(_box(title, ["There is no hint at this level for this task. Ask your mentor."]))
        return None
    log_event("hint", task_id, status="shown", repo=repo, level=level)
    print(_box(title, [text.rstrip()]))
    return None


def reroll(task_id: str) -> None:
    """Draw new practice cases for a synthetic check (new seed; logged)."""
    repo = _paths.repo_root()
    _spec(task_id, repo)
    user = user_name()
    n = _reroll_index(task_id, repo, user) + 1
    seed = seed_for(user, task_id, n)
    log_event("reroll", task_id, status="ok", seed=seed, repo=repo, reroll=n)
    print(f"New practice cases for {task_id}: seed {seed} (reroll {n}). Run the check cell again.")
    return None


def _task_order(task: str) -> Tuple[str, int]:
    m = TASK_RE.match(task)
    return (m.group(1), int(m.group(2))) if m else (task, 0)


def progress(module: Optional[str] = None):
    """Table of tasks: prediction, attempts, best status, hints seen, last activity."""
    import pandas as pd

    repo = _paths.repo_root()
    specs = load_specs(repo)
    events = read_log(repo)
    tasks = set(specs) | {e.get("task") for e in events if isinstance(e.get("task"), str)}
    if module:
        tasks = {t for t in tasks if t.startswith(module + "-")}
    rows = []
    for t in sorted(tasks, key=_task_order):
        evs = [e for e in events if e.get("task") == t]
        checks = [e for e in evs if e.get("event") == "check"]
        statuses = [e.get("status") for e in checks]
        if PASS in statuses:
            status = PASS
        elif statuses:
            status = statuses[-1]
        else:
            status = "not checked"
        spec = specs.get(t, {})
        rows.append({
            "module": _task_order(t)[0],
            "task": t,
            "title": spec.get("title", ""),
            "tier": spec.get("tier", ""),
            "predicted": any(e.get("event") == "predict" and e.get("status") == "ok" for e in evs),
            "attempts": sum(1 for s in statuses if s in (PASS, FAIL)),
            "failed": sum(1 for s in statuses if s == FAIL),
            "status": status,
            "hints_seen": max([int(e.get("level") or 0) for e in evs
                               if e.get("event") == "hint" and e.get("status") == "shown"], default=0),
            "last_activity": max([str(e.get("ts")) for e in evs], default=""),
        })
    cols = ["module", "task", "title", "tier", "predicted", "attempts", "failed", "status", "hints_seen",
            "last_activity"]
    return pd.DataFrame(rows, columns=cols)


# ----------------------------------------------------------------------------- run-time guard
# check() and the loader it calls are the only readers of a checker file the run-time guard allows
# (astguard.watch_checkers). In an IPython kernel the guard starts here, at "import sgtl_tutorial"; anywhere else at
# the first check.
_ENGINE_CODES = (check.__code__, _resolve_checker.__code__)
try:
    if astguard._ipython_shell() is not None:
        astguard.watch_checkers(*_ENGINE_CODES, _checkers_dir())
except Exception:  # noqa: BLE001 - never block "import sgtl_tutorial"
    pass
