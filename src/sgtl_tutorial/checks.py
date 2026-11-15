"""Check engine: predictions, checks, hints, rerolls and the progress table.

How a check runs (``st.check("M01-T1", func=great_circle_km)``):

1. The task must have a logged prediction (``st.predict``), else status NO PREDICTION.
2. A function target is screened by the AST guard against the spec's ``forbidden`` list.
3. The checker ``sgtl_tutorial.checkers.m01.check_T1(target, ctx)`` runs and returns an
   :class:`Outcome`. If anything inside raises NotImplementedError, status is NOT STARTED.
4. A short box is printed; one JSON line is appended to ``<repo>/work/.sgtl/progress.jsonl``.
5. With ``SGTL_STRICT=1`` (CI), anything but PASS raises AssertionError.

Only PASS and FAIL count as attempts. Real-data expected values are never printed.
"""
from __future__ import annotations

import importlib
import json
import os
import re
import textwrap
from dataclasses import dataclass, field
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
    "exception": "Your code stopped with an error: {error}",
}


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


def _normalize_spec(task: str, spec: Optional[dict], module: Optional[str]) -> dict:
    spec = dict(spec or {})
    spec.setdefault("module", module or task.split("-")[0])
    spec["hints"] = {int(k): str(v) for k, v in (spec.get("hints") or {}).items()}
    spec["categories"] = {str(k): str(v) for k, v in (spec.get("categories") or {}).items()}
    spec["forbidden"] = [str(f) for f in (spec.get("forbidden") or [])]
    return spec


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


def task_spec(task_id: str, repo: Optional[Path] = None) -> dict:
    """The spec of one task (raises KeyError with a plain message when unknown)."""
    if not TASK_RE.match(task_id or ""):
        raise KeyError(f"{task_id!r} is not a task id; task ids look like 'M01-T1'.")
    specs = load_specs(repo)
    if task_id not in specs:
        same = sorted(t for t in specs if t.startswith(task_id.split("-")[0] + "-"))
        raise KeyError(f"Unknown task {task_id!r}. Tasks of this module: {', '.join(same) or 'none found'}. "
                       "If your copy of the tutorial is old, update it (see docs).")
    return specs[task_id]


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
    spec = task_spec(task_id, repo)
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


def _resolve_checker(task: str, spec: dict) -> Callable:
    m = TASK_RE.match(task)
    assert m is not None
    modname = f"sgtl_tutorial.checkers.{m.group(1).lower()}"
    mod = importlib.import_module(modname)
    return getattr(mod, f"check_T{m.group(2)}")


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
    spec = task_spec(task_id, repo)
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
        res = CheckResult(task=task_id, status=status, outcome=outcome, seed=seed, reroll=reroll_n,
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

    # 3. AST guard
    notes: List[str] = []
    if callable(target) and spec.get("forbidden"):
        rep = astguard.check_function(target, spec["forbidden"])
        if rep.note:
            notes.append("Note: " + rep.note)
        if not rep.ok:
            msg = spec["categories"].get("forbidden-import") or DEFAULT_MESSAGES["forbidden-import"]
            msg = msg.replace("{rules}", ", ".join(rep.violations))
            out = Outcome(passed=False, n_cases=0, n_failed=0, category="forbidden-import", message=msg,
                          details={"found": rep.offending})
            return finish(FAIL, [
                f"FAIL · library rule broken · {seed_txt}",
                f"Problem (forbidden-import): {msg}",
                f"Found in your code: {', '.join(rep.offending)}",
                f'Next step: rewrite the function without it. Stuck? st.hint("{task_id}", 1)',
            ], out, counted=True)

    # 4. run the checker
    from .synth import rng_for

    context = CheckContext(rng=rng_for(user, task_id, reroll_n), seed=seed, reroll=reroll_n, criteria=criteria,
                           strict=strict, session=sess, task=task_id, module=spec.get("module"), spec=spec,
                           user=user, repo=repo, data_root=_paths.data_root())
    for k, v in ctx.items():
        if k in context:
            raise TypeError(f"st.check: the keyword {k!r} is reserved; use another name.")
        context[k] = v
    try:
        checker = _resolve_checker(task_id, spec)
    except (ImportError, AttributeError) as exc:
        missing = isinstance(exc, ModuleNotFoundError) and str(getattr(exc, "name", "")).startswith(
            "sgtl_tutorial.checkers")
        why = ("there is no checker for this task in your copy of the tutorial" if missing or
               isinstance(exc, AttributeError) else f"the checker needs a package that is missing ({exc})")
        return finish(ERROR, [f"ERROR · {why} (nothing was counted).",
                              "Next step: run 'sgtl doctor' in a terminal; if that does not help, tell your mentor."])
    try:
        outcome = _as_outcome(checker(target, context))
    except NotImplementedError:
        return finish(NOT_STARTED, notes + [
            "NOT STARTED · your function still raises NotImplementedError (nothing was counted).",
            'Next step: replace the line "raise NotImplementedError(...)" with your code, '
            "then run this check again.",
        ])
    except Exception as exc:  # noqa: BLE001 - shown to the student in plain words
        err = f"{type(exc).__name__}: {exc}"
        if _student_frames(exc, target):
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

    # 5. report
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
    msg = spec["categories"].get(cat) or outcome.message or "Some cases are outside the tolerance."
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
    spec = task_spec(task_id, repo)
    level = int(level)
    if level not in (1, 2, 3):
        raise ValueError("Hint levels are 1, 2 and 3.")
    n_fail = _n_fail(task_id, repo)
    unlocked = 1 + min(n_fail, 2)
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
    text = spec["hints"].get(level)
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
    task_spec(task_id, repo)
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
