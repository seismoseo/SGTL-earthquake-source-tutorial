"""AST guard: find out whether a function uses a library that a task does not allow.

A task spec may list ``forbidden: [pyproj, obspy.geodetics]``. An entry matches the module
itself and everything inside it: ``pyproj`` matches ``pyproj`` and ``pyproj.Geod``.

The guard reads the function's source code (``inspect.getsource``), parses it into a syntax
tree (AST = abstract syntax tree), and collects

* imported module names (``import x.y`` -> ``x.y`` and ``x``; ``from x import y`` -> ``x``, ``x.y``),
* dotted attribute chains (``np.linalg.norm``), with names resolved through the imports in the
  function and through the notebook's global variables (``np`` -> ``numpy``),
* plain names, resolved the same way (``from pyproj import Geod`` then ``Geod(...)``),
* string arguments of ``__import__("x")`` and ``importlib.import_module("x")``.

Helper functions that the student defined in the same notebook and that the function calls are
inspected too (up to three levels deep). When the source is not available (for example a
function typed into a plain Python prompt), the guard is skipped with a note.
"""
from __future__ import annotations

import ast
import builtins
import functools
import inspect
import textwrap
import types
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Set

__all__ = ["GuardReport", "collect_names", "check_function", "matches"]

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
            if (
                depth < _MAX_DEPTH
                and isinstance(obj, types.FunctionType)
                and getattr(obj, "__module__", None) == home_module
            ):
                helpers.append(obj)
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
