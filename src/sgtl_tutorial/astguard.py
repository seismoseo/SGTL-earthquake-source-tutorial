"""AST guard: find out whether a function uses a library that a task does not allow.

A task spec may list ``forbidden: [pyproj, obspy.geodetics]``. An entry matches the module
itself and everything inside it: ``pyproj`` matches ``pyproj`` and ``pyproj.Geod``.

The guard reads the function's source code (``inspect.getsource``), parses it into a syntax
tree (AST = abstract syntax tree), and collects

* imported module names (``import x.y`` -> ``x.y`` and ``x``; ``from x import y`` -> ``x``, ``x.y``),
* dotted attribute chains (``np.linalg.norm``), with names resolved through the imports in the
  function and through the notebook's global variables (``np`` -> ``numpy``),
* plain names, resolved the same way (``from pyproj import Geod`` then ``Geod(...)``),
* functions, classes and modules held one level inside a global the function uses
  (``functools.partial(lib.f)``, ``{"f": lib.f}``, ``[lib.f]``): ``lib.f`` counts as used,
* string arguments of ``__import__("x")`` and ``importlib.import_module("x")``.

Helper functions that the student defined in the same notebook and that the function calls are
inspected too (up to three levels deep). When the source is not available (for example a
function typed into a plain Python prompt), the guard is skipped with a note.

Session guard (:func:`scan_session`, run by every check of every task kind): a checker computes its own
expected values, so a notebook that imports or calls the checkers' code (``sgtl_tutorial.checkers``) could hand
an answer over. The guard reads, without running anything,

* the code of every cell run in this IPython session (``history_manager.input_hist_parsed``, i.e. ``In``, plus
  a private record of every cell kept from the moment ``sgtl_tutorial`` was imported, so clearing ``In`` hides
  nothing), or, outside IPython, the source file of ``__main__``;
* Python files of the student's own (inside the tutorial repository) that the session imported or ran
  (``%run``, ``runpy.run_path``, ``open("x.py")``);
* the objects the session holds (variables, ``Out``, one level into lists, dicts, closures and defaults).

It counts: ``import sgtl_tutorial.checkers...``, ``from sgtl_tutorial import checkers``, ``<alias>.checkers``
where the alias is the package (``import sgtl_tutorial as s``, ``s2 = s``, ``importlib.import_module``,
``__import__``, ``sys.modules[...]``), strings that name the checkers (``getattr(st, "checkers")``,
``import_module("sgtl_tutorial.checkers.m04")``, also when glued together from constant pieces), the checkers'
own names (``check_T<n>``, ``_t<n>_<name>``, the engine's ``_resolve_checker``) when they are looked up (``a.b.name``,
``getattr``, ``vars(...)[...]``) on something that leads to the checkers' code (a student's own helper or method
with such a name is fine), code strings handed to ``exec``/``eval``/IPython magics, attempts to edit the record of
what ran, and any object defined in the checkers. A static scan cannot follow code that builds these names at run
time; that limit is documented in DESIGN.md section 4.

Run-time guard (:func:`watch_checkers`): an audit hook (``sys.addaudithook``), started when the package is imported
in an IPython kernel or else at the first check, marks the session when a checker module is imported or a checker
file is read by anything but the engine's own loader (the engine loads a checker privately: it never enters
``sys.modules``). It sees what code does, however the names were built. A mark stays until the kernel restarts.
"""
from __future__ import annotations

import ast
import builtins
import functools
import inspect
import itertools
import os
import re
import sys
import textwrap
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

__all__ = ["GuardReport", "collect_names", "check_function", "matches", "SessionReport", "scan_sources",
           "scan_session", "install_cell_record", "watch_checkers"]

_MAX_DEPTH = 3


@dataclass
class GuardReport:
    """Result of :func:`check_function`."""

    ok: bool
    violations: List[str] = field(default_factory=list)  # forbidden entries that matched
    offending: List[str] = field(default_factory=list)  # resolved names that matched
    note: Optional[str] = None  # set when the guard was skipped


def matches(name: str, forbidden: str) -> bool:
    """True when ``name`` is ``forbidden`` or lies inside it (``pyproj.Geod`` inside ``pyproj``)."""
    return name == forbidden or name.startswith(forbidden + ".")


def _unwrap(func: Any) -> Any:
    while isinstance(func, functools.partial):
        func = func.func
    try:
        func = inspect.unwrap(func)
    except Exception:
        pass
    if isinstance(func, (types.MethodType,)):
        func = func.__func__
    return func


def _source_tree(func: Any) -> ast.AST:
    src = textwrap.dedent(inspect.getsource(func))
    try:
        return ast.parse(src)
    except SyntaxError:
        # A lambda inside a larger expression: try the lines as an expression.
        return ast.parse("(" + src.strip().rstrip(",") + "\n)", mode="eval")


def _dotted(node: ast.AST) -> Optional[List[str]]:
    parts: List[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return parts[::-1]
    return None


def _object_name(obj: Any) -> Optional[str]:
    """Dotted origin of an object: a module's name, or ``<module>.<qualname>`` of a function/class."""
    if isinstance(obj, types.ModuleType):
        return obj.__name__
    mod = getattr(obj, "__module__", None)
    qual = getattr(obj, "__qualname__", None) or getattr(obj, "__name__", None)
    if isinstance(mod, str) and isinstance(qual, str):
        return f"{mod}.{qual}"
    if isinstance(mod, str):
        return mod
    return None


_HELD_ITEMS = 200
_CODE_TYPES = (types.ModuleType, types.FunctionType, types.BuiltinFunctionType, types.MethodType, type)


def _held_callables(obj: Any) -> List[Any]:
    """Functions, classes and modules one level inside a global: what a ``functools.partial`` wraps (and its bound
    arguments), the values of a dict, the items of a list, tuple or set, the function of a (static/class) method.
    Data objects are left out: a forbidden rule is about code that the function calls."""
    out: List[Any] = []
    try:
        if isinstance(obj, functools.partial):
            while isinstance(obj, functools.partial):
                out.extend(list(obj.args) + list((obj.keywords or {}).values()))
                obj = obj.func
            out.append(obj)
        elif isinstance(obj, (types.MethodType, staticmethod, classmethod)):
            out.append(obj.__func__)
        elif isinstance(obj, dict):
            out.extend(itertools.islice(obj.values(), _HELD_ITEMS))
        elif isinstance(obj, (list, tuple, set, frozenset)):
            out.extend(itertools.islice(obj, _HELD_ITEMS))
    except Exception:  # noqa: BLE001
        return []
    out = [_unwrap(o) if isinstance(o, functools.partial) else o for o in out]
    return [o for o in out if isinstance(o, _CODE_TYPES)]


def _scan(func: Any, depth: int, seen: Set[int], out: Set[str]) -> None:
    func = _unwrap(func)
    if id(func) in seen:
        return
    seen.add(id(func))
    tree = _source_tree(func)  # may raise OSError/TypeError: handled by the caller
    glb: Dict[str, Any] = dict(getattr(func, "__globals__", {}) or {})
    # Closure variables (nonlocal names) behave like globals for our purpose.
    code = getattr(func, "__code__", None)
    closure = getattr(func, "__closure__", None)
    if code is not None and closure:
        for name, cell in zip(code.co_freevars, closure):
            try:
                glb[name] = cell.cell_contents
            except ValueError:
                pass
    aliases: Dict[str, str] = {}  # local name -> dotted module path, from imports in the source
    helpers: List[Any] = []
    home_module = getattr(func, "__module__", None)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.add(a.name)
                parts = a.name.split(".")
                out.update(".".join(parts[: i + 1]) for i in range(len(parts)))
                if a.asname:
                    aliases[a.asname] = a.name
                else:
                    aliases[parts[0]] = parts[0]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            out.add(node.module)
            for a in node.names:
                full = f"{node.module}.{a.name}"
                out.add(full)
                aliases[a.asname or a.name] = full
        elif isinstance(node, ast.Call):
            fn = _dotted(node.func)
            if fn and fn[-1] in ("__import__", "import_module") and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    out.add(arg.value)

    # Names bound inside the function (parameters, assignments, nested defs) shadow globals.
    local_names: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            a = node.args
            for arg in list(getattr(a, "posonlyargs", [])) + a.args + a.kwonlyargs:
                local_names.add(arg.arg)
            for arg in (a.vararg, a.kwarg):
                if arg is not None:
                    local_names.add(arg.arg)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            local_names.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            local_names.add(node.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            local_names.add(node.name)
    top = tree.body[0] if isinstance(tree, ast.Module) and tree.body else None
    if isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef)):
        local_names.discard(top.name)  # the function's own name is global (recursion)

    def resolve(first: str) -> Optional[str]:
        if first in aliases:
            return aliases[first]
        if first in local_names:
            return None
        if first in glb:
            obj = glb[first]
            for inner in [obj] + _held_callables(obj):
                if inner is not obj:  # e.g. functools.partial(lib.func) or {"f": lib.func}: lib.func is used
                    nm = _object_name(inner)
                    if nm:
                        out.add(nm)
                if (
                    depth < _MAX_DEPTH
                    and isinstance(inner, types.FunctionType)
                    and getattr(inner, "__module__", None) == home_module
                ):
                    helpers.append(inner)
            return _object_name(obj)
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            parts = _dotted(node)
            if not parts:
                continue
            base = resolve(parts[0])
            if base:
                out.add(".".join([base] + parts[1:]))
            elif parts[0] not in local_names:
                out.add(".".join(parts))
            if parts[0] in glb and parts[0] not in local_names and parts[0] not in aliases:
                obj = glb[parts[0]]
                for attr in parts[1:]:
                    if not isinstance(obj, (types.ModuleType, type)):
                        break
                    try:
                        obj = getattr(obj, attr)
                    except Exception:
                        break
                    nm = _object_name(obj)
                    if nm:
                        out.add(nm)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if hasattr(builtins, node.id) and node.id not in aliases and node.id not in glb:
                continue
            resolved = resolve(node.id)
            if resolved:
                out.add(resolved)
            elif node.id not in local_names:
                out.add(node.id)

    for helper in helpers:
        try:
            _scan(helper, depth + 1, seen, out)
        except (OSError, TypeError, SyntaxError):
            continue


def collect_names(func: Callable) -> Set[str]:
    """All module names, dotted chains and plain names that ``func`` uses (see module docstring).

    Raises OSError/TypeError when the source code is not available.
    """
    out: Set[str] = set()
    _scan(func, 0, set(), out)
    return out


def check_function(func: Callable, forbidden: Iterable[str]) -> GuardReport:
    """Check ``func`` against the ``forbidden`` list of a task spec."""
    forbidden = [f.strip() for f in (forbidden or []) if f and str(f).strip()]
    if not forbidden:
        return GuardReport(ok=True)
    try:
        names = collect_names(func)
    except (OSError, TypeError, SyntaxError, IndentationError):
        return GuardReport(
            ok=True,
            note="Library-use check skipped: the source code of this function is not available.",
        )
    violations, offending = [], []
    for rule in forbidden:
        hits = sorted(n for n in names if matches(n, rule))
        if hits:
            violations.append(rule)
            offending.extend(hits)
    return GuardReport(ok=not violations, violations=violations, offending=sorted(set(offending)))


# ============================================================================= session guard
PACKAGE = "sgtl_tutorial"
CHECKERS = PACKAGE + ".checkers"
# Names the checkers use: the entry points check_T<n>, the per-task helpers _t<n>_<name>, and the engine function
# that loads a checker. A student may use such a name for an own helper, so ``<owner>.<name>`` counts only when the
# owner leads to the checkers' code (see _names_checker_code); imports from the package count as they are.
_INTERNAL_NAME = re.compile(r"^(?:check_T\d+|_t\d+_\w+|_resolve_checker)$")
_ENGINE_LOADER = (PACKAGE + ".checks", "_resolve_checker")
_PKG_ROOT = "<package>"  # first item of an owner chain that starts at an expression giving the package
_ATTR_READERS = {"getattr", "hasattr", "getattr_static"}
_CHECKERS_TEXT = re.compile(r"sgtl_tutorial\s*[./\\]\s*checkers\b")
_PARTS = re.compile(r"[./\\]")
_RECORD_ATTR = "_sgtl_cell_record"
_TAMPER_ATTRS = {"history_manager", "input_hist_parsed", "input_hist_raw", _RECORD_ATTR}
_CODE_RUNNERS = {"exec", "eval", "compile", "run_cell", "run_cell_magic", "run_line_magic", "runsource",
                 "run_code", "system", "getoutput"}
_FILE_RUNNERS = {"run_path", "open"}
_NS_SKIP = re.compile(r"^(?:In|_ih|_i+|_i\d+|_dh|exit|quit|get_ipython|__builtins__|__builtin__)$")
_SAFE_FORMAT = re.compile(r"(?:[^{}]|\{\{|\}\}|\{\w*\})*\Z")
_WIDE_PERCENT = re.compile(r"%[-#0 +]*\d{4,}")
_FOLD_MAX_LEN = 4000
_FOLD_MAX_DEPTH = 30
_NESTED_CODE_DEPTH = 3
_CONTAINER_ITEMS = 200
_FILE_MAX_BYTES = 2_000_000
_CACHE_MAX = 4096
_MISSING = object()


@dataclass
class SessionReport:
    """Result of :func:`scan_session`: ``found`` lists where the checkers' code was used (no values)."""

    ok: bool
    found: List[str] = field(default_factory=list)
    note: Optional[str] = None


@dataclass
class _Facts:
    hits: List[Tuple[int, str]] = field(default_factory=list)  # (line, code text)
    aliases: Set[str] = field(default_factory=set)  # names bound to the sgtl_tutorial package
    bound: List[Tuple[str, str]] = field(default_factory=list)  # (name, "sgtl_tutorial.x.y") from import statements
    links: List[Tuple[str, str]] = field(default_factory=list)  # (name, other name) from "name = other"
    bases: List[Tuple[Tuple[str, ...], int, str]] = field(default_factory=list)  # "<a.b>.checkers": resolve later
    # "<a.b>.check_T4", getattr(a.b, "_t4_x"), vars(a.b)["_t4_x"]: (owner chain or None, name, line, code text)
    named: List[Tuple[Optional[Tuple[str, ...]], str, int, str]] = field(default_factory=list)
    runs: List[str] = field(default_factory=list)  # files the code runs or reads (%run, run_path, open)


_FACTS: Dict[str, _Facts] = {}
_FILE_FACTS: Dict[Tuple[str, int, int], _Facts] = {}
_TRANSFORMED: Dict[str, str] = {}


def _in_checkers(name: str) -> bool:
    return name == CHECKERS or name.startswith(CHECKERS + ".")


def _in_package(name: str) -> bool:
    return name == PACKAGE or name.startswith(PACKAGE + ".")


def _suspicious(text: str) -> bool:
    """True for a string that names the checkers' module (a module path or a file path). A string that is one of
    their function names (``"_t4_x"``) counts only where it is looked up on an owner (see ``_scan_tree``)."""
    if _CHECKERS_TEXT.search(text):
        return True
    return any(part.strip() == "checkers" for part in _PARTS.split(text))


def _internal(value: Any) -> Optional[str]:
    """The name, when ``value`` is a string spelling one of the checkers' names (check_T4, _t4_x, ...)."""
    if isinstance(value, str) and _INTERNAL_NAME.match(value.strip()):
        return value.strip()
    return None


def _text(node: ast.AST, limit: int = 70) -> str:
    try:
        s = " ".join(ast.unparse(node).split())
    except Exception:  # noqa: BLE001
        s = type(node).__name__
    return s if len(s) <= limit else s[: limit - 3] + "..."


def _short(value: Any) -> Any:
    return value if not isinstance(value, str) or len(value) <= _FOLD_MAX_LEN else None


def _fold(node: ast.AST, depth: int = 0) -> Any:
    """The value of an expression built only from constants (str, int, tuples), else None. Never runs code."""
    if depth > _FOLD_MAX_DEPTH:
        return None
    d = depth + 1
    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, bool):
            return None
        if isinstance(v, int):
            return v if abs(v) < 10 ** 6 else None
        return _short(v) if isinstance(v, str) else None
    if isinstance(node, (ast.Tuple, ast.List)):
        if len(node.elts) > 64:
            return None
        vals = tuple(_fold(e, d) for e in node.elts)
        return None if any(v is None for v in vals) else vals
    if isinstance(node, ast.JoinedStr):
        out = []
        for part in node.values:
            if isinstance(part, ast.FormattedValue):
                if part.format_spec is not None or part.conversion not in (-1, 115):
                    return None
                part = part.value
            v = _fold(part, d)
            if not isinstance(v, (str, int)):
                return None
            out.append(str(v))
        return _short("".join(out))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _fold(node.operand, d)
        return (-v if isinstance(node.op, ast.USub) else v) if isinstance(v, int) else None
    try:
        if isinstance(node, ast.BinOp):
            a, b = _fold(node.left, d), _fold(node.right, d)
            if a is None or b is None:
                return None
            if isinstance(node.op, ast.Add) and isinstance(a, str) and isinstance(b, str):
                return _short(a + b)
            if isinstance(node.op, ast.Mult):
                s, n = (a, b) if isinstance(a, str) else (b, a)
                if isinstance(s, str) and isinstance(n, int) and 0 <= n <= 64:
                    return _short(s * n)
            if isinstance(node.op, ast.Mod) and isinstance(a, str) and not _WIDE_PERCENT.search(a):
                return _short(a % b)
            return None
        if isinstance(node, ast.Subscript):
            base = _fold(node.value, d)
            if not isinstance(base, (str, tuple)):
                return None
            sl = node.slice
            if isinstance(sl, ast.Slice):
                nodes = (sl.lower, sl.upper, sl.step)
                parts = [None if p is None else _fold(p, d) for p in nodes]
                if any(n is not None and not isinstance(p, int) for n, p in zip(nodes, parts)) or parts[2] == 0:
                    return None
                return base[slice(*parts)]
            idx = _fold(sl, d)
            return base[idx] if isinstance(idx, int) else None
        if isinstance(node, ast.Call):
            args = [_fold(a, d) for a in node.args]
            if any(a is None for a in args):
                return None
            func = node.func
            if isinstance(func, ast.Name) and len(args) == 1 and not node.keywords:
                a = args[0]
                if func.id == "str" and isinstance(a, str):
                    return a
                if func.id == "chr" and isinstance(a, int) and 0 <= a < 0x110000:
                    return chr(a)
                if func.id == "reversed" and isinstance(a, (str, tuple)):
                    return a[::-1]
                if func.id in ("tuple", "list") and isinstance(a, (str, tuple)):
                    return tuple(a)
                return None
            if not isinstance(func, ast.Attribute):
                return None
            obj = _fold(func.value, d)
            if not isinstance(obj, str):
                return None
            name = func.attr
            if name == "join" and len(args) == 1 and isinstance(args[0], (str, tuple)) \
                    and all(isinstance(x, str) for x in args[0]):
                return _short(obj.join(args[0]))
            if name == "format" and _SAFE_FORMAT.match(obj):
                kw = {k.arg: _fold(k.value, d) for k in node.keywords if k.arg}
                if len(kw) != len(node.keywords) or any(v is None for v in kw.values()):
                    return None
                return _short(obj.format(*args, **kw))
            if node.keywords:
                return None
            if name == "replace" and 2 <= len(args) <= 3 and all(isinstance(a, str) for a in args[:2]):
                if len(obj) * max(1, len(args[1])) > 10 ** 6:
                    return None
                return _short(obj.replace(*args))
            if name in ("upper", "lower", "casefold", "title", "capitalize", "swapcase", "strip", "lstrip",
                        "rstrip") and not args:
                return getattr(obj, name)()
            if name in ("strip", "lstrip", "rstrip", "removeprefix", "removesuffix") and len(args) == 1 \
                    and isinstance(args[0], str):
                return getattr(obj, name)(args[0])
    except (TypeError, ValueError, IndexError, KeyError, OverflowError, AttributeError):
        return None
    return None


def _package_expr(node: ast.AST) -> bool:
    """True for an expression that gives the sgtl_tutorial package (import_module, __import__, sys.modules)."""
    if isinstance(node, ast.Call) and node.args:
        fn = _dotted(node.func) or ([node.func.attr] if isinstance(node.func, ast.Attribute) else None)
        name = _fold(node.args[0])
        if not fn or not isinstance(name, str):
            return False
        if fn[-1] == "import_module":
            return name == PACKAGE
        if fn[-1] == "__import__":
            fromlist = len(node.args) >= 4 or any(k.arg == "fromlist" for k in node.keywords)
            return _in_package(name) and not fromlist
        return False
    if isinstance(node, ast.Subscript):
        return _fold(node.slice) == PACKAGE
    return False


def _owner_chain(node: ast.AST) -> Optional[Tuple[str, ...]]:
    """``a.b.c`` as ("a", "b", "c"); ``__import__("sgtl_tutorial").b`` as (_PKG_ROOT, "b"); else None."""
    chain = _dotted(node)
    if chain is not None:
        return tuple(chain)
    rest: List[str] = []
    while isinstance(node, ast.Attribute):
        rest.append(node.attr)
        node = node.value
    return (_PKG_ROOT,) + tuple(reversed(rest)) if _package_expr(node) else None


def _bind(target: ast.AST, value: ast.AST, facts: _Facts) -> None:
    if isinstance(target, ast.Name):
        if isinstance(value, ast.Name):
            facts.links.append((target.id, value.id))
        elif _package_expr(value):
            facts.aliases.add(target.id)
    elif isinstance(target, (ast.Tuple, ast.List)) and isinstance(value, (ast.Tuple, ast.List)) \
            and len(target.elts) == len(value.elts):
        for t, v in zip(target.elts, value.elts):
            _bind(t, v, facts)


def _scan_tree(tree: ast.AST, facts: _Facts, depth: int = 0, line: Optional[int] = None) -> None:
    """Collect what one piece of code does with the checkers. ``line`` pins nested code to its outer line."""
    for node in ast.walk(tree):
        at = line if line is not None else int(getattr(node, "lineno", 0) or 0)
        if isinstance(node, ast.Import):
            for a in node.names:
                if _in_checkers(a.name):
                    facts.hits.append((at, "import " + a.name))
                elif _in_package(a.name):
                    if a.asname is None:
                        facts.aliases.add(PACKAGE)
                    elif a.name == PACKAGE:
                        facts.aliases.add(a.asname)
                    else:
                        facts.bound.append((a.asname, a.name))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level == 0 and _in_checkers(mod):
                facts.hits.append((at, f"from {mod} import ..."))
            elif node.level == 0 and _in_package(mod):
                for a in node.names:
                    if (mod == PACKAGE and a.name == "checkers") or _INTERNAL_NAME.match(a.name):
                        facts.hits.append((at, f"from {mod} import {a.name}"))
                    elif a.name != "*":
                        facts.bound.append((a.asname or a.name, f"{mod}.{a.name}"))
        elif isinstance(node, ast.Attribute):
            if node.attr == "checkers":
                chain = _dotted(node.value)
                if chain is None:
                    facts.hits.append((at, _text(node)))
                else:
                    facts.bases.append((tuple(chain), at, _text(node)))
            elif _INTERNAL_NAME.match(node.attr):
                facts.named.append((_owner_chain(node.value), node.attr, at, _text(node)))
            elif node.attr in _TAMPER_ATTRS:
                facts.hits.append((at, _text(node) + " (edits the record of what ran)"))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _suspicious(node.value):
                facts.hits.append((at, _text(node)))
        if isinstance(node, (ast.BinOp, ast.JoinedStr, ast.Subscript, ast.Call)):
            value = _fold(node)
            if isinstance(value, str) and _suspicious(value):
                facts.hits.append((at, _text(node)))
        if isinstance(node, ast.Subscript):  # vars(owner)["_t4_x"], owner.__dict__["_t4_x"]
            name, base = _internal(_fold(node.slice)), node.value
            owner = None
            if isinstance(base, ast.Call) and _dotted(base.func) == ["vars"] and len(base.args) == 1:
                owner = base.args[0]
            elif isinstance(base, ast.Attribute) and base.attr == "__dict__":
                owner = base.value
            if name and owner is not None:
                facts.named.append((_owner_chain(owner), name, at, _text(node)))
        if isinstance(node, ast.Assign):
            for t in node.targets:
                _bind(t, node.value, facts)
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
            _bind(node.target, node.value, facts)
        if isinstance(node, ast.Call):
            fn = _dotted(node.func) or ([node.func.attr] if isinstance(node.func, ast.Attribute) else None)
            if not fn:
                continue
            values = [_fold(a) for a in node.args] + [_fold(k.value) for k in node.keywords]
            if fn[-1] in _ATTR_READERS and len(node.args) >= 2 and _internal(values[1]):
                facts.named.append((_owner_chain(node.args[0]), _internal(values[1]), at, _text(node)))
            if fn[-1] == "run_line_magic" and len(values) >= 2 and values[0] in ("run", "load") \
                    and isinstance(values[1], str):
                words = [w for w in values[1].split() if not w.startswith("-")]
                facts.runs.extend(words[:1])
            elif fn[-1] in _FILE_RUNNERS and values and isinstance(values[0], str) and values[0].endswith(".py"):
                facts.runs.append(values[0])
            if fn[-1] in _CODE_RUNNERS and depth < _NESTED_CODE_DEPTH:
                for v in values:
                    if not isinstance(v, str):
                        continue
                    try:
                        sub = ast.parse(v)
                    except (SyntaxError, ValueError, RecursionError, MemoryError):
                        continue
                    _scan_tree(sub, facts, depth + 1, at)


def _facts_for(source: str) -> Optional[_Facts]:
    """Facts of one piece of code (cached by its text); None when it does not parse (then it never ran)."""
    facts = _FACTS.get(source)
    if facts is None:
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            return None
        facts = _Facts()
        _scan_tree(tree, facts)
        if len(_FACTS) >= _CACHE_MAX:
            _FACTS.clear()
        _FACTS[source] = facts
    return facts


def _file_facts(path: Path) -> Optional[_Facts]:
    try:
        st_ = path.stat()
        if not path.is_file() or st_.st_size > _FILE_MAX_BYTES:
            return None
        key = (str(path), st_.st_mtime_ns, st_.st_size)
        if key not in _FILE_FACTS:
            if len(_FILE_FACTS) >= _CACHE_MAX:
                _FILE_FACTS.clear()
            _FILE_FACTS[key] = _facts_for(path.read_text(encoding="utf-8", errors="replace")) or _Facts()
        return _FILE_FACTS[key]
    except OSError:
        return None


def _reaches_package(chain: Tuple[str, ...], aliases: Set[str], ns: Mapping[str, Any], pkg: Any) -> bool:
    """Does the dotted name in front of ``.checkers`` stand for the sgtl_tutorial package? Unknown counts as yes."""
    head, rest = chain[0], chain[1:]
    if head in ns:
        obj = ns[head]
    elif head in aliases:
        obj = pkg
    else:
        return True  # a name the session does not hold (a local variable, a deleted name): count it
    if not rest and head in aliases:
        return True
    for attr in rest:
        if obj is None or not isinstance(obj, (types.ModuleType, type)):
            return True  # following it would run code: count it
        obj = inspect.getattr_static(obj, attr, _MISSING)
        if obj is _MISSING:
            return True
    return pkg is not None and obj is pkg


def _walk_static(obj: Any, attrs: Iterable[str]) -> Any:
    """Follow ``obj.a.b`` without running code; stops early (returning that object) at anything from the checkers.
    _MISSING when an attribute is not there."""
    for attr in attrs:
        if obj is _MISSING or _from_checkers(obj):
            return obj
        obj = inspect.getattr_static(obj, attr, _MISSING)
    return obj


def _names_checker_code(chain: Optional[Tuple[str, ...]], name: str, aliases: Set[str],
                        bound: Mapping[str, Set[str]], ns: Mapping[str, Any], pkg: Any) -> bool:
    """Does ``<chain>.<name>`` (a name such as check_T4, _t4_x or _resolve_checker) reach the checkers' code?

    The owner is followed through the session's objects without running code (``inspect.getattr_static``); a name
    the session no longer holds is followed from what an import bound to it (``bound``: ``from sgtl_tutorial import
    checks as c``) or from the package for its aliases. An owner that cannot be found (``self``, a local variable)
    counts as NO, and so does a name that leads to the student's own code: a student's own helper may carry such
    a name. Code that reached the checkers' module itself was counted where it did so.
    """
    if not chain:
        return False
    head, rest = chain[0], chain[1:] + (name,)
    try:
        if head == _PKG_ROOT:
            starts = [pkg]
        elif head in ns:
            starts = [ns[head]]
        else:
            starts = ([pkg] if head in aliases else []) + [_walk_static(pkg, path.split(".")[1:])
                                                            for path in sorted(bound.get(head, ()))]
        for start in starts:
            if start is None or start is _MISSING:
                continue
            obj = _walk_static(start, rest)
            if isinstance(obj, (staticmethod, classmethod)):
                obj = obj.__func__
            if obj is _MISSING:
                continue
            if _from_checkers(obj) or (isinstance(obj, types.FunctionType)
                                       and (obj.__module__, obj.__name__) == _ENGINE_LOADER):
                return True
    except Exception:  # noqa: BLE001 - an object that cannot be inspected statically: not counted
        return False
    return False


def _from_checkers(obj: Any) -> Optional[str]:
    """The checkers module an object comes from, or None."""
    for _ in range(5):
        if isinstance(obj, functools.partial):
            obj = obj.func
        elif isinstance(obj, types.MethodType):
            obj = obj.__func__
        else:
            break
    try:
        if isinstance(obj, types.ModuleType):
            name = obj.__dict__.get("__name__")
        elif isinstance(obj, (types.FunctionType, types.BuiltinFunctionType, type)):
            name = obj.__dict__.get("__module__") if isinstance(obj, type) else getattr(obj, "__module__", None)
        else:
            name = getattr(type(obj), "__module__", None)
    except Exception:  # noqa: BLE001
        return None
    return name if isinstance(name, str) and _in_checkers(name) else None


def _inner_objects(obj: Any) -> Iterable[Any]:
    """One level inside: items of lists, tuples, sets and dicts; closure cells and defaults of functions."""
    try:
        if isinstance(obj, dict):
            return list(itertools.islice(obj.values(), _CONTAINER_ITEMS))
        if isinstance(obj, (list, tuple, set, frozenset)):
            return list(itertools.islice(obj, _CONTAINER_ITEMS))
        if isinstance(obj, types.FunctionType):
            out: List[Any] = list(obj.__defaults__ or ()) + list((obj.__kwdefaults__ or {}).values())
            for cell in obj.__closure__ or ():
                try:
                    out.append(cell.cell_contents)
                except ValueError:
                    pass
            return out
    except Exception:  # noqa: BLE001
        pass
    return []


def _namespace_hits(ns: Mapping[str, Any]) -> List[str]:
    found = []
    for key, value in list(ns.items()):
        if not isinstance(key, str) or _NS_SKIP.match(key):
            continue
        where = _from_checkers(value)
        if where is None:
            where = next((w for w in map(_from_checkers, _inner_objects(value)) if w), None)
        if where:
            found.append(f"the name {key!r} holds an object from {where}")
    return found


def _own_files(ns: Mapping[str, Any], runs: Iterable[str],
               repo: Optional[Path]) -> List[Tuple[Path, Mapping[str, Any]]]:
    """The student's own Python files (inside the repository, outside this package) the session uses, each with
    the names its code sees: the module's globals when the session imported it, else the session's own names
    (``%run`` runs a file among them)."""
    if repo is None:
        return []
    pkg_dir = Path(__file__).resolve().parent
    names: List[Tuple[str, Mapping[str, Any]]] = [(r, ns) for r in runs if isinstance(r, str)]
    for value in list(ns.values()):
        try:
            if isinstance(value, types.ModuleType):
                f, scope = value.__dict__.get("__file__"), value.__dict__
            elif isinstance(value, types.FunctionType):
                f, scope = value.__code__.co_filename, value.__globals__
            elif isinstance(value, type) and value.__dict__.get("__module__") not in (None, "__main__"):
                mod = sys.modules.get(value.__dict__.get("__module__"))
                f, scope = getattr(mod, "__file__", None), getattr(mod, "__dict__", ns)
            else:
                f, scope = None, ns
        except Exception:  # noqa: BLE001
            f, scope = None, ns
        if isinstance(f, str) and f.endswith(".py"):
            names.append((f, scope if isinstance(scope, Mapping) else ns))
    out: List[Tuple[Path, Mapping[str, Any]]] = []
    for name, scope in names:
        try:
            p = Path(name).expanduser()
            p = (p if p.is_absolute() else Path.cwd() / p).resolve()
        except (OSError, ValueError, RuntimeError):
            continue
        if repo in p.parents and pkg_dir != p.parent and pkg_dir not in p.parents \
                and all(p != q for q, _ in out):
            out.append((p, scope))
    return out


def scan_sources(units: Sequence[Tuple[str, str]], namespace: Optional[Mapping[str, Any]] = None,
                 repo: Optional[Path] = None) -> SessionReport:
    """Session guard on given code (``[(label, source), ...]``) and objects (``{name: value}``).

    ``repo`` is the tutorial repository: the student's own ``.py`` files inside it that the code runs or the
    namespace imports are read too. Returns ``SessionReport(ok, found)``; ``found`` names places, never values.
    """
    ns: Mapping[str, Any] = namespace if namespace is not None else {}
    parsed: List[Tuple[str, _Facts, Mapping[str, Any]]] = []  # (label, facts, the names that code sees)
    for label, source in units:
        if isinstance(source, str) and source.strip():
            facts = _facts_for(source)
            if facts is not None:
                parsed.append((label, facts, ns))
    runs = [r for _, f, _ in parsed for r in f.runs]
    root = repo.resolve() if repo is not None else None
    for path, scope in _own_files(ns, runs, root):
        facts = _file_facts(path)
        if facts is not None:
            try:
                label = path.relative_to(root).as_posix() if root is not None else path.name
            except ValueError:
                label = path.name
            parsed.append((label, facts, scope))
    pkg = sys.modules.get(PACKAGE)
    aliases: Set[str] = set().union(*(f.aliases for _, f, _ in parsed)) if parsed else set()
    if pkg is not None:
        aliases |= {k for k, v in list(ns.items()) if v is pkg and isinstance(k, str)}
    bound: Dict[str, Set[str]] = {}
    for _, f, _ in parsed:
        for name, path in f.bound:
            bound.setdefault(name, set()).add(path)
    links = [link for _, f, _ in parsed for link in f.links]
    grew = True
    while grew:
        grew = False
        for a, b in links:
            if b in aliases and a not in aliases:
                aliases.add(a)
                grew = True
            if not bound.get(b, set()) <= bound.get(a, set()):
                bound.setdefault(a, set()).update(bound[b])
                grew = True
    found: List[str] = []
    seen: Set[Tuple[str, int]] = set()
    for label, facts, scope in parsed:
        items = list(facts.hits) + [(at, text) for chain, name, at, text in facts.named
                                    if _names_checker_code(chain, name, aliases, bound, scope, pkg)]
        items += [(at, text) for chain, at, text in facts.bases if _reaches_package(chain, aliases, scope, pkg)]
        for at, text in sorted(items, key=lambda item: item[0]):
            if (label, at) not in seen:
                seen.add((label, at))
                found.append(f"{label}, line {at}: {text}" if at else f"{label}: {text}")
    found.extend(_namespace_hits(ns))
    return SessionReport(ok=not found, found=found)


def _ipython_shell() -> Any:
    mod = sys.modules.get("IPython")
    if mod is None:
        return None
    try:
        return mod.get_ipython()
    except Exception:  # noqa: BLE001
        return None


def install_cell_record() -> bool:
    """Keep a private copy of every cell this IPython session runs from now on (for :func:`scan_session`)."""
    ip = _ipython_shell()
    if ip is None:
        return False
    if isinstance(getattr(ip, _RECORD_ATTR, None), list):
        return True
    record: List[List[Any]] = []  # [cell number or None, raw cell]; the code is kept BEFORE the cell runs
    texts: Set[str] = set()
    pending: List[List[Any]] = []

    def _sgtl_record_cell(info: Any = None) -> None:
        try:
            pending.clear()
            raw = getattr(info, "raw_cell", None)
            if isinstance(raw, str) and raw.strip() and raw not in texts:
                texts.add(raw)
                record.append([None, raw])
                pending.append(record[-1])
        except Exception:  # noqa: BLE001 - never disturb the student's cell
            pass

    def _sgtl_number_cell(result: Any = None) -> None:  # the cell's number is known for sure only afterwards
        try:
            n = getattr(result, "execution_count", None)
            if pending and isinstance(n, int):
                pending[0][0] = n
            pending.clear()
        except Exception:  # noqa: BLE001
            pass

    try:
        ip.events.register("pre_run_cell", _sgtl_record_cell)
        ip.events.register("post_run_cell", _sgtl_number_cell)
        setattr(ip, _RECORD_ATTR, record)
    except Exception:  # noqa: BLE001
        return False
    return True


def _python_of_cell(ip: Any, raw: str) -> str:
    """A recorded cell as IPython runs it (magics turned into Python calls)."""
    if raw not in _TRANSFORMED:
        try:
            text = ip.transform_cell(raw)
        except Exception:  # noqa: BLE001
            text = raw
        if len(_TRANSFORMED) >= _CACHE_MAX:
            _TRANSFORMED.clear()
        _TRANSFORMED[raw] = text if isinstance(text, str) else raw
    return _TRANSFORMED[raw]


def scan_session(repo: Optional[Path] = None) -> SessionReport:
    """Session guard on the running session: IPython cells (or the ``__main__`` file) and the user namespace."""
    try:
        if repo is None:
            from . import _paths

            repo = _paths.find_repo()
        ip = _ipython_shell()
        units: List[Tuple[str, str]] = []
        if ip is not None:
            install_cell_record()
            seen: Set[str] = set()
            history = getattr(getattr(ip, "history_manager", None), "input_hist_parsed", None) or []
            for i, src in enumerate(list(history)):
                if isinstance(src, str) and src not in seen:
                    seen.add(src)
                    units.append((f"cell [{i}]", src))
            for entry in list(getattr(ip, _RECORD_ATTR, None) or []):
                count, raw = (entry[0], entry[1]) if isinstance(entry, (list, tuple)) and len(entry) == 2 \
                    else (None, entry)
                if not isinstance(raw, str):
                    continue
                src = _python_of_cell(ip, raw)
                if src not in seen:
                    seen.add(src)
                    units.append((f"cell [{count}]" if isinstance(count, int) else "an earlier cell", src))
            namespace = getattr(ip, "user_ns", None) or {}
        else:
            main = sys.modules.get("__main__")
            namespace = dict(vars(main)) if main is not None else {}
            path = getattr(main, "__file__", None)
            if isinstance(path, str) and os.path.isfile(path) and os.path.getsize(path) <= _FILE_MAX_BYTES:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    units.append((os.path.basename(path), fh.read()))
        return scan_sources(units, namespace, repo)
    except Exception as exc:  # noqa: BLE001 - a guard failure must not stop the student's work
        return SessionReport(ok=True, note=f"the notebook-history check could not run ({type(exc).__name__}); "
                                           "tell your mentor.")


# ============================================================================= run-time guard (audit hook)
# The static scan reads code; it cannot follow names built at run time (rot13, a helper file outside the
# repository, a search of sys.modules). The run-time guard watches what actually happens instead: an audit hook
# (sys.addaudithook) sees every module import and every file opened in the process. The engine loads a checker
# privately (``checks._resolve_checker``: read, compiled and run in a fresh namespace that never enters
# sys.modules), so any other import of a checker module, or any other read of a checker file, comes from the
# session and marks it. A mark cannot be taken back: every later check refuses (category checker-internals).
# The checkers' package file (``checkers/__init__.py``: shared helpers, no task code) is not watched, so code
# completion that touches ``st.checkers`` marks nothing. Copying a checker's text in a terminal, or code that
# walks up the stack from inside a running check, is outside what this guard sees.
AUDIT_QUERY = "sgtl_tutorial.guard.query"
AUDIT_MARK = "sgtl_tutorial.guard.mark"
_AUDIT_EVENTS = frozenset({"open", "import", AUDIT_QUERY, AUDIT_MARK})
_MAX_MARKS = 20


def _package_init(name: str) -> bool:
    return name.split(".", 1)[0] == "__init__"


def _checker_files(folder: str) -> frozenset:
    """``(device, inode)`` of every file of the checkers except the package's ``__init__`` (source and compiled),
    so a file is recognised under any path or link name it is opened by."""
    out = set()
    for sub in (folder, os.path.join(folder, "__pycache__")):
        try:
            with os.scandir(sub) as entries:
                for entry in entries:
                    if not _package_init(entry.name) and entry.is_file():
                        info = entry.stat()
                        out.add((info.st_dev, info.st_ino))
        except OSError:
            continue
    return frozenset(out)


def _make_audit_hook(check_code: types.CodeType, loader_code: types.CodeType, folder: str) -> Callable:
    """The hook. Its marks live only in this closure: nothing in the package refers to them, and the engine reads
    them with the query event (each hook appends ``(marks, check_code, loader_code)`` to the list it is given)."""
    marks: List[str] = []
    state = {"files": _checker_files(folder)}
    getframe, stat, prefix = sys._getframe, os.stat, CHECKERS + "."

    def add(text: str) -> None:
        if text not in marks and len(marks) < _MAX_MARKS:
            marks.append(text)

    def _sgtl_audit_hook(event: str, args: tuple) -> None:
        if event not in _AUDIT_EVENTS:
            return
        try:
            if event == "open":
                path = args[0]
                if isinstance(path, int):
                    return
                try:
                    info = stat(path)
                except (OSError, TypeError, ValueError):
                    return
                if (info.st_dev, info.st_ino) not in state["files"]:
                    return
                try:  # allowed: the engine's loader, called by check() itself
                    caller = getframe(1)
                    engine = caller.f_code is loader_code and caller.f_back is not None \
                        and caller.f_back.f_code is check_code
                except ValueError:
                    engine = False
                if not engine:
                    add(f"a checker file was read ({os.path.basename(os.fsdecode(os.fspath(path)))})")
            elif event == "import":
                if isinstance(args[0], str) and args[0].startswith(prefix):
                    add(f"a checker module was imported ({args[0]})")
            elif event == AUDIT_MARK:
                if isinstance(args[0], str):
                    add(args[0])
            elif isinstance(args[0], list):
                state["files"] = _checker_files(folder)  # files added since (a new compiled file, ...)
                args[0].append((tuple(marks), check_code, loader_code))
        except Exception:  # noqa: BLE001 - a hook must never disturb the student's code
            pass

    return _sgtl_audit_hook


def _loaded_checker_modules(folder: str) -> List[str]:
    """Checker modules present in ``sys.modules`` (the engine never leaves one there)."""
    roots = {os.path.join(p, "") for p in (folder, os.path.realpath(folder))}
    found = []
    for name, mod in list(sys.modules.items()):
        if not isinstance(name, str) or not isinstance(mod, types.ModuleType):
            continue
        path = mod.__dict__.get("__file__")
        inside = isinstance(path, str) and any(path.startswith(r) for r in roots) \
            and not _package_init(os.path.basename(path))
        if name.startswith(CHECKERS + ".") or inside:
            found.append(name)
    return found


def _query_hooks() -> List[Tuple[Tuple[str, ...], Any, Any]]:
    reply: List[Any] = []
    try:
        sys.audit(AUDIT_QUERY, reply)
    except Exception:  # noqa: BLE001 - another hook refused the event: no answer
        return []
    return [r for r in reply if isinstance(r, tuple) and len(r) == 3 and isinstance(r[0], tuple)]


def watch_checkers(check_code: types.CodeType, loader_code: types.CodeType, folder: Any) -> Optional[List[str]]:
    """Run-time guard: make sure an audit hook watches the checkers in ``folder`` for this engine (``check_code``
    and ``loader_code`` are the code of ``checks.check`` and ``checks._resolve_checker``, the only reader allowed),
    then return what every such hook saw in this process (plain sentences, never values). A checker module left in
    ``sys.modules`` (imported before the hook started) is marked too. Returns ``None`` when no hook answers."""
    folder = os.fspath(folder)
    replies = _query_hooks()
    if not any(r[1] is check_code and r[2] is loader_code for r in replies):
        try:
            sys.addaudithook(_make_audit_hook(check_code, loader_code, folder))
        except Exception:  # noqa: BLE001
            pass
    for name in _loaded_checker_modules(folder):
        try:
            sys.audit(AUDIT_MARK, f"a checker module was loaded in this session ({name})")
        except Exception:  # noqa: BLE001
            pass
    replies = _query_hooks()
    if not any(r[1] is check_code and r[2] is loader_code for r in replies):
        return None
    marks: List[str] = []
    for r in replies:
        marks.extend(m for m in r[0] if isinstance(m, str) and m not in marks)
    return marks
