"""``sgtl oral [MXX]``: pick three of your own task cells for the weekly oral check.

Plain words: the command reads ``work/.sgtl/progress.jsonl``, keeps the tasks whose check has passed, finds
their code cells (tagged ``task-code``) in your work notebooks and picks three at random. The random choice is
seeded by the date, your login, the module and a word your mentor says at the meeting (``--salt WORD``, or
``SGTL_ORAL_SALT`` in the shell that runs the command). The word is required: without it the command picks
nothing, so nobody can see the cells before the meeting. Each cell is printed with line numbers and two
questions: what one of its lines does, and what would change if one detail were different. The choice is
appended to ``work/.sgtl/oral.jsonl`` with the date and a SHA-256 fingerprint of the word (never the word
itself). The command only reads your notebooks; it never runs them.

Copyright (c) 2026 Minseong Seo (SGTL, Seoul National University). MIT License.
"""
from __future__ import annotations

import ast
import datetime as _dt
import hashlib
import json
import os
import random
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import _paths
from .session import now_iso, read_log, release_version, user_name

__all__ = ["oral", "pick_cells", "line_question", "change_question"]

TASK_TITLE = re.compile(r"^###\s+(M\d\d-T\d+)\b", re.M)
MODULE_RE = re.compile(r"^M\d{2}$")
STUB = re.compile(r"raise\s+NotImplementedError\b")
N_PICKS = 3
SALT_ENV = "SGTL_ORAL_SALT"
MIN_SALT = 6  # characters: short enough to say, too many to try them all in advance
_OPS = {ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=", ast.Eq: "==", ast.NotEq: "!="}
_SWAP = {"<": "<=", "<=": "<", ">": ">=", ">=": ">", "==": "!=", "!=": "=="}


def _source(cell: Dict[str, Any]) -> str:
    src = cell.get("source", "")
    return "".join(src) if isinstance(src, list) else str(src)


def passed_tasks(events: List[Dict[str, Any]], module: Optional[str] = None) -> List[str]:
    done = {e.get("task") for e in events if e.get("event") == "check" and e.get("status") == "PASS"
            and isinstance(e.get("task"), str)}
    return sorted(t for t in done if module is None or t.startswith(module + "-"))


def task_code_cells(nb: Dict[str, Any]) -> List[Tuple[str, int, str, str]]:
    """(task id, cell index, cell id, source) of every ``task-code`` cell, in notebook order."""
    out, task = [], None
    for i, cell in enumerate(nb.get("cells", [])):
        tags = (cell.get("metadata") or {}).get("tags") or []
        src = _source(cell)
        if cell.get("cell_type") == "markdown" and "task" in tags:
            m = TASK_TITLE.search(src)
            task = m.group(1) if m else task
        elif cell.get("cell_type") == "code" and "task-code" in tags and task:
            out.append((task, i, str(cell.get("id", "")), src))
    return out


def _parse(src: str) -> Optional[ast.AST]:
    # Lines starting with % or ! (IPython magics and shell commands) are not Python; blank them first.
    text = "\n".join("" if ln.lstrip().startswith(("%", "!")) else ln for ln in src.split("\n"))
    try:
        return ast.parse(text)
    except SyntaxError:
        return None


def candidate_lines(src: str) -> List[int]:
    """Line numbers (1-based) of statements worth explaining: not comments, docstrings, imports or stubs.

    ``def`` and ``class`` lines count only when the cell has no other statement.
    """
    lines = src.split("\n")
    tree = _parse(src)
    found = set()
    if tree is not None:
        heads = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.stmt):
                continue
            if isinstance(node, (ast.Import, ast.ImportFrom, ast.Pass, ast.Global, ast.Nonlocal)):
                continue
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                continue  # a docstring or a lone value
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                heads.add(node.lineno)
                continue
            found.add(node.lineno)
        found = found or heads
    else:
        found = {n for n, ln in enumerate(lines, 1) if ln.strip() and not ln.strip().startswith("#")}
    keep = []
    for n in sorted(found):
        text = lines[n - 1].strip() if n - 1 < len(lines) else ""
        if text and not text.startswith("#") and not STUB.search(text) and len(text) >= 6:
            keep.append(n)
    return keep


def has_own_code(src: str) -> bool:
    """False for a cell that still holds the 'write your code here' stub (such a task cannot have passed)."""
    return not STUB.search(src) and bool(candidate_lines(src))


def line_question(src: str, rng: random.Random) -> Tuple[int, str]:
    lines = src.split("\n")
    n = rng.choice(candidate_lines(src))
    text = lines[n - 1].strip()
    if len(text) > 100:
        text = text[:97] + "..."
    return n, f"What does line {n} do, and why is it needed?   `{text}`"


def _number(value: Any) -> Optional[str]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value == 0:
        return "1"
    if value == 1:
        return "2"
    return f"{value * 2:g}"


def change_question(src: str, rng: random.Random) -> str:
    """A 'what would change if ...' question about one concrete detail of the cell."""
    tree = _parse(src)
    options: List[str] = []
    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and _number(node.value) is not None:
                options.append(f"What would change if the number `{node.value!r}` in line {node.lineno} were "
                               f"{_number(node.value)} instead?")
            elif isinstance(node, ast.Compare):
                for op in node.ops:
                    sym = _OPS.get(type(op))
                    if sym:
                        options.append(f"What would change if `{sym}` in line {node.lineno} were `{_SWAP[sym]}`?")
            elif isinstance(node, ast.keyword) and node.arg and getattr(node, "lineno", None):
                options.append(f"What would change if the argument `{node.arg}=` in line {node.lineno} were "
                               "left out, so that the function uses its default?")
            elif isinstance(node, ast.Slice) and getattr(node, "lineno", None):
                options.append(f"What would change if the slice in line {node.lineno} started one element later?")
    if not options:
        return ("What would change in the result of this cell if its input had only one element, "
                "or none at all?")
    return rng.choice(sorted(set(options)))


def oral_seed(date: str, user: str, module: Optional[str], salt: str) -> int:
    key = f"sgtl-oral|{date}|{user}|{module or 'all'}|{salt}"
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:12], 16)


def salt_fingerprint(salt: str) -> str:
    """What the log keeps of the mentor's word: a SHA-256 fingerprint, so the word itself is never stored."""
    return hashlib.sha256(f"sgtl-oral-salt|{salt}".encode("utf-8")).hexdigest()


def pick_cells(repo: Path, module: Optional[str], seed: int, n: int = N_PICKS) -> List[Dict[str, Any]]:
    """Up to ``n`` task cells of passed tasks (different tasks first), each with two questions."""
    passed = set(passed_tasks(read_log(repo), module))
    pattern = f"work/{module}_*/{module}_*.ipynb" if module else "work/M[0-9][0-9]_*/M[0-9][0-9]_*.ipynb"
    cells: Dict[str, List[Tuple[str, int, str, str]]] = {}
    for path in sorted(repo.glob(pattern)):
        try:
            nb = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for task, idx, cid, src in task_code_cells(nb):
            if task in passed and has_own_code(src):
                cells.setdefault(task, []).append((path.relative_to(repo).as_posix(), idx, cid, src))
    rng = random.Random(seed)
    tasks = sorted(cells)
    chosen = rng.sample(tasks, min(n, len(tasks)))
    picks = [(t, rng.choice(cells[t])) for t in chosen]
    rest = [(t, c) for t in tasks for c in cells[t] if (t, c) not in picks]
    while len(picks) < n and rest:
        picks.append(rest.pop(rng.randrange(len(rest))))
    out = []
    for task, (nb_rel, idx, cid, src) in picks:
        line_no, q1 = line_question(src, rng)
        out.append({"task": task, "notebook": nb_rel, "cell": idx, "cell_id": cid, "line": line_no,
                    "code_sha256": hashlib.sha256(src.encode("utf-8")).hexdigest(), "source": src,
                    "questions": [q1, change_question(src, rng)]})
    return out


def oral(module: Optional[str] = None, *, date: Optional[str] = None, salt: Optional[str] = None,
         n: int = N_PICKS) -> int:
    if module:
        module = module.upper()
        if not MODULE_RE.match(module):
            print("Module ids look like M04.")
            return 2
    if date is not None and not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        print("Write the date as YYYY-MM-DD.")
        return 2
    salt = (salt if salt is not None else os.environ.get(SALT_ENV, "")).strip()
    if len(salt) < MIN_SALT:
        print(f"sgtl oral needs the word your mentor says at the meeting (at least {MIN_SALT} characters): "
              f"bin/sgtl oral {module or ''}{' ' if module else ''}--salt WORD, or {SALT_ENV}=WORD in the "
              "mentor's shell. Without it nothing is picked, so the cells cannot be known before the meeting.")
        return 2
    repo = _paths.repo_root()
    date = date or _dt.date.today().isoformat()
    user = user_name()
    seed = oral_seed(date, user, module, salt)
    picks = pick_cells(repo, module, seed, n)
    where = f"module {module}" if module else "all modules"
    if not picks:
        print(f"No task of {where} has a passed check with your own code yet; the oral check uses cells of "
              "tasks whose check has passed (st.progress() shows them).")
        return 1
    try:
        from .checks import load_specs

        specs = load_specs(repo)
    except Exception:  # titles are a convenience only
        specs = {}
    print(f"Weekly oral check, {date}, {where}: {len(picks)} cell(s) from tasks you passed (seed {seed}).")
    print("Explain each cell without notes: what each line does, why it is there, what would change.\n")
    for k, p in enumerate(picks, 1):
        title = (specs.get(p["task"]) or {}).get("title", "")
        print(f"{k}. {p['task']}{' · ' + title if title else ''}   ({p['notebook']}, cell {p['cell']})")
        body = p["source"].rstrip("\n").split("\n")
        width = len(str(len(body)))
        for i, ln in enumerate(body, 1):
            print(f"   {i:>{width}} | {ln}")
        print(f"   Q1. {p['questions'][0]}")
        print(f"   Q2. {p['questions'][1]}\n")
    rec = {"ts": now_iso(), "date": date, "user": user, "module": module, "seed": seed,
           "salt_sha256": salt_fingerprint(salt),
           "release": release_version(repo),
           "picks": [{k: v for k, v in p.items() if k != "source"} for p in picks]}
    log = Path(repo) / "work" / ".sgtl" / "oral.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("The choice is logged in work/.sgtl/oral.jsonl; commit it with your work.")
    return 0
