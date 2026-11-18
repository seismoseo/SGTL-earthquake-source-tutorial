"""AST guard: find out whether a function uses a library that a task does not allow.

A task spec may list ``forbidden: [pyproj, obspy.geodetics, obspy.Trace.trigger]``. An entry matches the module,
class, function or method it names and everything inside it: ``pyproj`` matches ``pyproj`` and ``pyproj.Geod``.
An entry that names a function, class or method rather than a module (``numpy.polyfit``, ``obspy.Trace.trigger``)
also matches every attribute of that name that the code looks up on anything but a module: the guard cannot see
the type of a variable (``tr.trigger(...)`` on a Trace), and a namesake elsewhere does the same job
(``np.ma.polyfit``, ``DataArray.polyfit``).

The guard reads the function's source code (``inspect.getsource``), parses it into a syntax tree (AST = abstract
syntax tree), and collects

* imported module names (``import x.y`` -> ``x.y`` and ``x``; ``from x import y`` -> ``x``, ``x.y``),
* dotted attribute chains (``np.linalg.norm``), with names resolved through the imports in the function, the
  notebook's global variables (``np`` -> ``numpy``), local names that may hold a module, class or function
  (``p = np``, ``for m in (np, np.ma)``, ``mods[0]``, a parameter default ``lib=np``) and the objects a chain
  reaches (``np.lib.polynomial.polyfit`` is ``numpy.polyfit``; a module imported under another name, from a folder
  put on ``sys.path``, also gets the name its file has inside its package),
* plain names, resolved the same way (``from pyproj import Geod`` then ``Geod(...)``),
* functions, classes and modules held inside a global the function uses, up to six levels down (a
  ``functools.partial`` and its arguments, a dict, list, tuple or set, a numpy or pandas object array, the
  attributes of an object of the notebook's own classes): ``lib.f`` counts as used,
* module names given in quotes to ``__import__``, ``importlib.import_module``, ``importlib.util.find_spec``,
  ``pkgutil.resolve_name``, ``pydoc.locate`` and ``runpy.run_module``, and attribute names given in quotes to
  ``getattr``, ``hasattr``, ``setattr``, ``delattr``, ``operator.attrgetter`` and ``operator.methodcaller``.

The function's own name counts too (a library function handed in as the answer is caught by its name). Helper
functions and classes that the student defined in the same notebook (or in a Python file of the repository) and
that the function uses are read too, at any depth.

Names built at run time (category ``runtime-name``): a reader of the code can only judge names written out in it,
so the guard refuses a checked function (or a helper it reads) that

* gives one of the import functions above a module name that is not plain text in quotes;
* gives ``getattr``, ``hasattr``, ``setattr`` or ``delattr`` a name that is not plain text in quotes while the object
  is a module, or a class or function of a library (on data, such as a pandas row or a namedtuple, a variable name
  is fine); gives ``attrgetter`` or ``methodcaller`` such a name; or hands any of these functions on as a value;
* runs code given as text or builds functions from code (``eval``, ``exec``, ``compile``, IPython's ``run_cell``
  and magics, ``timeit``, ``doctest``, ``pdb``, ``types.FunctionType``, ``sympy.sympify``);
* looks names up in a namespace (``globals()``, ``locals()``, ``vars()``, ``__dict__``, ``__globals__``,
  ``__builtins__``, ``__getattribute__``, ``inspect.getmembers``, ``sys.modules``, a frame's ``f_globals``);
* changes where imports come from, or loads code from a file or from data (``sys.path``, ``importlib.machinery``,
  ``spec_from_file_location``, ``exec_module``, entry points, ``pickle``, ``marshal``, ``yaml.load``, ``ctypes``);
* or has no code the guard can read (made with ``exec`` or ``compile``, or typed at a plain Python prompt).

Names written out in quotes stay allowed unless a rule forbids what they name. What the guard cannot see is listed
in DESIGN.md section 4.1 (known gaps).

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
import collections
import collections.abc
import functools
import importlib.util
import inspect
import itertools
import linecache
import os
import re
import sys
import sysconfig
import textwrap
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

__all__ = ["GuardReport", "collect_names", "check_function", "matches", "SessionReport", "scan_sources",
           "scan_session", "install_cell_record", "watch_checkers"]

_MAX_DEPTH = 50  # helpers are read at any depth; the seen-set cuts cycles, this only stops pathological chains
_HELD_DEPTH = 6  # levels looked into a global (a dict of lists of functions is two levels)
_HELD_ITEMS = 100_000  # items of one container looked at (an isinstance test each)
_HELD_BUDGET = 2000  # containers and objects opened per global
_MAX_RUNTIME = 20
_CODE_TYPES = (types.ModuleType, types.FunctionType, types.BuiltinFunctionType, types.MethodType, type)
_PKG_DIR = Path(__file__).resolve().parent

# Functions that take a module name as text (first argument), functions that take an attribute name as text, and
# builtins whose result holds what went in (list(...), next(iter(...))): see _Reader.
_IMPORT_FUNCS = frozenset({"importlib.import_module", "importlib.__import__", "builtins.__import__",
                           "importlib.util.find_spec", "pkgutil.resolve_name", "pydoc.locate", "pydoc.resolve",
                           "runpy.run_module"})
_GETATTR_FUNCS = frozenset({"builtins.getattr", "builtins.hasattr", "builtins.setattr", "builtins.delattr",
                            "inspect.getattr_static"})
_GETTER_FUNCS = frozenset({"operator.attrgetter", "operator.methodcaller", "_operator.attrgetter",
                           "_operator.methodcaller"})
_NAME_FUNCS = _IMPORT_FUNCS | _GETATTR_FUNCS | _GETTER_FUNCS
_PASS_THROUGH = frozenset("builtins." + n for n in ("list", "tuple", "set", "frozenset", "dict", "iter", "next",
                                                    "reversed", "sorted", "min", "max", "zip", "enumerate",
                                                    "filter", "map")) | {"copy.copy", "copy.deepcopy"}

_WHY_UNREADABLE = "its code cannot be read (it was made with exec, eval or compile, or typed at a plain Python prompt)"
_WHY_MODULE = "the module name is not written out in quotes"
_WHY_ATTR = "the attribute name is not written out in quotes"
_WHY_VALUE = "handed on as a value, so the name it will look up is not in the code"
_WHY_TEXT = "runs code given as text"
_WHY_CODE = "builds a function from a code object"
_WHY_LOOKUP = "looks names up in a namespace while the code runs"
_WHY_LOAD = "changes where imports come from, or loads code from a file or from data"
_WHY_FRAME = "reads the names of other code from the call stack"
# Names (and everything inside them) refused in a checked function, matched only on names the guard resolved
# through imports and code objects (never on the text of a variable's name).
_RUNTIME_NAMES: Dict[str, str] = {
    **dict.fromkeys(("types.FunctionType", "types.LambdaType", "types.CodeType"), _WHY_CODE),
    **dict.fromkeys(("builtins.eval", "builtins.exec", "builtins.compile", "builtins.breakpoint", "timeit",
                     "doctest", "cProfile",
                     "profile", "pdb", "bdb", "code.InteractiveInterpreter", "code.InteractiveConsole",
                     "code.interact", "codeop", "sympy.sympify", "sympy.S", "sympy.parse_expr", "sympy.parsing",
                     "sympy.core.sympify", "sympy.lambdify", "sympy.utilities.lambdify", "mako",
                     "typing.get_type_hints", "typing.ForwardRef", "typing._eval_type", "inspect.get_annotations",
                     "string.Formatter"), _WHY_TEXT),
    **dict.fromkeys(("builtins.globals", "builtins.locals", "builtins.vars", "inspect.getmembers",
                     "inspect.getmembers_static", "sys.modules"), _WHY_LOOKUP),
    **dict.fromkeys(("sys.path", "sys.meta_path", "sys.path_hooks", "sys.path_importer_cache",
                     "importlib.machinery", "importlib._bootstrap", "importlib._bootstrap_external",
                     "importlib.util.module_from_spec", "importlib.util.spec_from_file_location",
                     "importlib.util.spec_from_loader", "importlib.util.LazyLoader", "importlib.metadata.entry_points",
                     "importlib_metadata.entry_points", "pkg_resources", "_frozen_importlib",
                     "_frozen_importlib_external", "_imp", "imp", "zipimport", "runpy.run_path", "pickle", "_pickle",
                     "marshal", "shelve", "dill", "cloudpickle", "pandas.read_pickle", "pandas.io.pickle",
                     "yaml.load", "yaml.load_all", "yaml.unsafe_load", "yaml.unsafe_load_all", "yaml.full_load",
                     "yaml.full_load_all", "yaml.Loader", "yaml.UnsafeLoader", "yaml.FullLoader", "logging.config",
                     "ctypes.CDLL", "ctypes.PyDLL", "ctypes.cdll", "ctypes.pydll", "ctypes.LibraryLoader",
                     "ctypes.pythonapi", "ctypes.util", "numpy.ctypeslib.load_library"), _WHY_LOAD),
    **dict.fromkeys(("sys._getframe", "sys._current_frames", "inspect.currentframe", "inspect.stack",
                     "inspect.trace", "inspect.getouterframes", "inspect.getinnerframes"), _WHY_FRAME),
}
# Attributes refused on any object.
_RUNTIME_ATTRS: Dict[str, str] = {
    **dict.fromkeys(("__dict__", "__globals__", "__builtins__", "__getattribute__", "__getattr__",
                     "__subclasses__"), _WHY_LOOKUP),
    **dict.fromkeys(("f_globals", "f_locals", "f_builtins", "f_back", "tb_frame", "gi_frame", "cr_frame",
                     "ag_frame"), _WHY_FRAME),
    **dict.fromkeys(("load_module", "exec_module", "create_module", "find_module", "find_loader"), _WHY_LOAD),
    **dict.fromkeys(("run_cell", "run_cell_magic", "run_line_magic", "runsource", "runcode", "run_code",
                     "safe_execfile", "safe_execfile_ipy", "safe_run_module", "run_ast_nodes", "ev", "ex"), _WHY_TEXT),
}


@dataclass
class GuardReport:
    """Result of :func:`check_function`."""

    ok: bool
    violations: List[str] = field(default_factory=list)  # forbidden entries that matched
    offending: List[str] = field(default_factory=list)  # resolved names (or code) that matched
    note: Optional[str] = None  # set when the guard was skipped
    runtime: List[str] = field(default_factory=list)  # code that builds a module or attribute name at run time

    @property
    def category(self) -> Optional[str]:
        """``runtime-name`` when names are built at run time, else ``forbidden-import`` when a rule matched."""
        if self.runtime:
            return "runtime-name"
        return "forbidden-import" if self.violations else None


def matches(name: str, forbidden: str) -> bool:
    """True when ``name`` is ``forbidden`` or lies inside it (``pyproj.Geod`` inside ``pyproj``)."""
    return name == forbidden or name.startswith(forbidden + ".")


def _strip_descriptor(obj: Any) -> Any:
    if isinstance(obj, (staticmethod, classmethod)):
        return obj.__func__
    return obj


def _unwrap(func: Any) -> Any:
    """The plain function behind a partial, a bound, static or class method, a decorator (``__wrapped__``),
    ``numpy.vectorize`` (``pyfunc``) or a numba dispatcher (``py_func``)."""
    for _ in range(20):
        if isinstance(func, functools.partial):
            func = func.func
            continue
        if isinstance(func, (types.MethodType, staticmethod, classmethod)):
            func = func.__func__
            continue
        try:
            inner = inspect.unwrap(func)
        except Exception:  # noqa: BLE001
            inner = func
        if inner is not func:
            func = inner
            continue
        if isinstance(func, (types.FunctionType, types.BuiltinFunctionType, type, types.ModuleType)):
            break
        nxt = None
        for attr in ("pyfunc", "py_func"):
            try:
                cand = inspect.getattr_static(func, attr)
            except Exception:  # noqa: BLE001
                continue
            if isinstance(cand, (types.FunctionType, functools.partial, types.MethodType)):
                nxt = cand
                break
        if nxt is None:
            break
        func = nxt
    return func


def _plain(obj: Any) -> Any:
    """The code object behind a global: :func:`_unwrap` for wrappers, the object itself otherwise."""
    if isinstance(obj, (types.ModuleType, type)):
        return obj
    try:
        return _unwrap(obj)
    except Exception:  # noqa: BLE001
        return obj


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


@functools.lru_cache(maxsize=1024)
def _package_path_name(filename: str) -> Optional[str]:
    """The dotted name a module file has inside its package (the folders above it that hold an __init__.py)."""
    try:
        p = Path(filename)
        stem = p.name.split(".")[0]
        parts = [] if stem == "__init__" else [stem]
        d = p.parent
        while (d / "__init__.py").is_file() and len(parts) < 40:
            parts.insert(0, d.name)
            d = d.parent
    except (OSError, ValueError):
        return None
    return ".".join(parts) or None


def _names_of(obj: Any) -> Set[str]:
    """Dotted names of an object: :func:`_object_name`, and for code of a module that was imported under another
    name (its folder put on ``sys.path``) the name its file has inside its package (``obspy.signal.trigger``)."""
    out: Set[str] = set()
    try:
        nm = _object_name(obj)
        modname = obj.__name__ if isinstance(obj, types.ModuleType) else getattr(obj, "__module__", None)
    except Exception:  # noqa: BLE001
        return out
    if not nm:
        return out
    out.add(nm)
    if isinstance(modname, str) and modname != "__main__" and matches(nm, modname):
        mod = sys.modules.get(modname)
        f = mod.__dict__.get("__file__") if isinstance(mod, types.ModuleType) else None
        real = _package_path_name(f) if isinstance(f, str) else None
        if real and real != modname:
            out.add(real + nm[len(modname):])
    return out


def _lookup(path: str) -> Tuple[bool, Any]:
    """``(True, object)`` when a dotted path leads, through modules already imported, to an object. It walks
    modules and classes only and reads attributes statically: it never imports and runs no code."""
    parts = path.split(".")
    for i in range(len(parts), 0, -1):
        obj = sys.modules.get(".".join(parts[:i]))
        if obj is None:
            continue
        for attr in parts[i:]:
            if not isinstance(obj, (types.ModuleType, type)):
                return False, None
            try:
                obj = _strip_descriptor(inspect.getattr_static(obj, attr))
            except Exception:  # noqa: BLE001
                return False, None
        return True, obj
    return False, None


def _module_file_names(name: str) -> Set[str]:
    """Other names of a module imported as ``name``: the name its file has inside its package (a folder of a
    package put on sys.path gives ``import trigger`` for obspy.signal.trigger). Never imports anything."""
    mod = sys.modules.get(name)
    if isinstance(mod, types.ModuleType):
        return _names_of(mod) - {name}
    if not name or "." in name:
        return set()
    try:
        spec = importlib.util.find_spec(name)  # a top-level name: nothing is imported to find it
    except Exception:  # noqa: BLE001
        return set()
    origin = getattr(spec, "origin", None)
    real = _package_path_name(origin) if isinstance(origin, str) and os.path.isfile(origin) else None
    return {real} if real and real != name else set()


@functools.lru_cache(maxsize=1)
def _library_roots() -> Tuple[str, ...]:
    roots: Set[str] = {str(_PKG_DIR)}
    for p in (sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix):
        if p:
            roots.add(os.path.realpath(p))
    try:
        paths = sysconfig.get_paths()
        for key in ("stdlib", "platstdlib", "purelib", "platlib"):
            if paths.get(key):
                roots.add(os.path.realpath(paths[key]))
    except Exception:  # noqa: BLE001
        pass
    try:
        import site

        for p in list(site.getsitepackages()) + [site.getusersitepackages()]:
            if p:
                roots.add(os.path.realpath(p))
    except Exception:  # noqa: BLE001
        pass
    return tuple(sorted(r.rstrip(os.sep) + os.sep for r in roots))


def _inside(path: Any, roots: Tuple[str, ...]) -> bool:
    try:
        return os.path.realpath(path).startswith(roots)
    except (TypeError, ValueError, OSError):
        return False


def _is_library_object(obj: Any) -> bool:
    """True for a function or class that an installed library, the standard library or this package defines, and
    that its module really holds under its qualified name (so a function made elsewhere cannot pose as one)."""
    try:
        modname = getattr(obj, "__module__", None)
        qual = getattr(obj, "__qualname__", None)
    except Exception:  # noqa: BLE001
        return False
    if not isinstance(modname, str) or not isinstance(qual, str) or modname == "__main__" or "<" in qual:
        return False
    mod = sys.modules.get(modname)
    if not isinstance(mod, types.ModuleType):
        return False
    f = mod.__dict__.get("__file__")
    if f is None:
        if modname not in sys.builtin_module_names:
            return False
    elif not _inside(f, _library_roots()):
        return False
    found, held = _lookup(modname + "." + qual)
    return found and (held is obj or _plain(held) is obj)


def _source_file(obj: Any) -> Optional[str]:
    code = getattr(obj, "__code__", None)
    if code is not None:
        return code.co_filename
    mod = sys.modules.get(getattr(obj, "__module__", None) or "")
    return mod.__dict__.get("__file__") if isinstance(mod, types.ModuleType) else None


def _class_functions(cls: type) -> List[Any]:
    """The functions a class body defines (methods, static and class methods, property accessors)."""
    out: List[Any] = []
    try:
        values = list(vars(cls).values())
    except TypeError:
        return out
    for v in values:
        if isinstance(v, property):
            out.extend(f for f in (v.fget, v.fset, v.fdel) if f is not None)
        elif isinstance(v, functools.cached_property):
            out.append(v.func)
        else:
            v = _strip_descriptor(v)
            if isinstance(v, (types.FunctionType, types.BuiltinFunctionType, functools.partial)):
                out.append(v)
    return out


def _held_items(obj: Any, own: Optional[Callable[[Any], bool]]) -> Iterable[Any]:
    """What a global holds one level down (see :func:`_held_code`)."""
    if isinstance(obj, (str, bytes, bytearray, int, float, complex, bool, range, type(None))):
        return ()
    if isinstance(obj, functools.partial):
        return [obj.func, *obj.args, *(obj.keywords or {}).values()]
    if isinstance(obj, (types.MethodType, staticmethod, classmethod)):
        return [obj.__func__]
    if isinstance(obj, property):
        return [obj.fget, obj.fset, obj.fdel]
    if type(obj).__name__ == "Field" and type(obj).__module__ == "dataclasses":
        return [obj.default, obj.default_factory]
    if isinstance(obj, _CODE_TYPES):
        return ()
    if isinstance(obj, dict):
        return itertools.islice(obj.values(), _HELD_ITEMS)
    if isinstance(obj, (list, tuple, set, frozenset, collections.deque)):
        return itertools.islice(obj, _HELD_ITEMS)
    np_ = sys.modules.get("numpy")
    if np_ is not None and isinstance(obj, np_.ndarray):
        return itertools.islice(obj.flat, _HELD_ITEMS) if obj.dtype == object else ()
    pd_ = sys.modules.get("pandas")
    if pd_ is not None and isinstance(obj, (pd_.Series, pd_.Index)):
        return itertools.islice(iter(obj.array), _HELD_ITEMS) if obj.dtype == object else ()
    if pd_ is not None and isinstance(obj, pd_.DataFrame):
        cols = [obj.iloc[:, i] for i in range(min(obj.shape[1], 50)) if obj.dtypes.iloc[i] == object]
        return itertools.chain.from_iterable(itertools.islice(iter(c.array), _HELD_ITEMS) for c in cols)
    if isinstance(obj, collections.abc.Mapping):
        return itertools.islice(obj.values(), _HELD_ITEMS)
    if isinstance(obj, types.SimpleNamespace) or (own is not None and own(type(obj))):
        return itertools.islice(object.__getattribute__(obj, "__dict__").values(), _HELD_ITEMS)
    return ()


def _held_code(obj: Any, own: Optional[Callable[[Any], bool]] = None) -> List[Any]:
    """Functions, classes and modules held inside a global, up to six levels down: a ``functools.partial`` and its
    arguments, a bound, static or class method, the values of a dict or mapping, the items of a list, tuple, set or
    numpy/pandas object array, the attributes of a SimpleNamespace or of an object of the notebook's own classes.
    Data are left out: a rule is about code that the function calls."""
    out: List[Any] = []
    stack: List[Tuple[Any, int]] = [(obj, 0)]
    opened: Set[int] = set()
    budget = _HELD_BUDGET
    while stack and budget > 0:
        cur, level = stack.pop()
        if id(cur) in opened:
            continue
        opened.add(id(cur))
        budget -= 1
        try:
            items = _held_items(cur, own)
            for item in items:
                if isinstance(item, (str, bytes, int, float, bool, type(None))):
                    continue
                item = _strip_descriptor(item)
                if isinstance(item, _CODE_TYPES):
                    out.append(item)
                elif isinstance(item, functools.partial):
                    out.append(_unwrap(item))
                    if level + 1 < _HELD_DEPTH and len(stack) < _HELD_BUDGET:
                        stack.append((item, level + 1))
                elif level + 1 < _HELD_DEPTH and len(stack) < _HELD_BUDGET:
                    stack.append((item, level + 1))
        except Exception:  # noqa: BLE001 - a strange container: what was found so far stays
            continue
    return out


_GENERATED_NAMES = frozenset({"__init__", "__repr__", "__eq__", "__ne__", "__lt__", "__le__", "__gt__", "__ge__",
                              "__hash__", "__setattr__", "__delattr__", "__getstate__", "__setstate__", "__new__",
                              "__replace__"})
_SUSPECT_CODE_NAMES = frozenset({"import_module", "__import__", "getattr", "hasattr", "eval", "exec", "compile",
                                 "globals", "vars", "locals", "modules", "attrgetter", "methodcaller", "find_spec",
                                 "resolve_name", "locate"}) | frozenset(_RUNTIME_ATTRS)


def _code_names(code: types.CodeType) -> Set[str]:
    out = set(code.co_names)
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            out |= _code_names(const)
    return out


def _generated_method(func: Any) -> bool:
    """True for a method that dataclasses or collections.namedtuple wrote with exec for a class, from its field
    names: it has no source, and its code may use nothing but builtins, the fields and the generators' helpers."""
    code = getattr(func, "__code__", None)
    if not isinstance(code, types.CodeType) or code.co_filename != "<string>" \
            or getattr(func, "__name__", None) not in _GENERATED_NAMES:
        return False
    made_by = (getattr(func, "__globals__", None) or {}).get("__name__", "")
    if not (code.co_qualname.startswith("__create_fn__.<locals>.")
            or (isinstance(made_by, str) and made_by.startswith("namedtuple_") and code.co_name == "<lambda>")):
        return False
    glb = getattr(func, "__globals__", None) or {}
    for name in _code_names(code):
        if "." in name or name in _SUSPECT_CODE_NAMES:
            return False
        held = glb.get(name, None) if name in glb else None
        if isinstance(held, types.ModuleType) or (name in glb and isinstance(_plain(held), _CODE_TYPES)
                                                   and not hasattr(builtins, name) and name != "_tuple_new"):
            return False
    return True


def _label(func: Any) -> str:
    name = getattr(func, "__qualname__", None) or getattr(func, "__name__", None)
    return name if isinstance(name, str) else type(func).__name__


def _find_node(source: str, code: types.CodeType, line: int, offset: int) -> Optional[List[ast.AST]]:
    """The syntax node(s) of a code object in ``source``: the def named like it whose first line (decorators
    included) is ``line``, or the lambdas that start on that line (``offset``: file line of source line 0)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    if code.co_name == "<lambda>":
        found = [n for n in ast.walk(tree) if isinstance(n, ast.Lambda) and n.lineno == line]
        if len(found) > 1:  # several lambdas on one line: the one around the code's first instruction
            spots = [(ln, col) for ln, eln, col, ecol in code.co_positions()  # empty spans: RESUME and the like
                     if None not in (ln, eln, col, ecol) and (eln, ecol) > (ln, col)]
            if spots:
                first = min(spots)
                inside = [n for n in found if (n.lineno + offset, n.col_offset) <= first
                          <= (n.end_lineno + offset, n.end_col_offset)]
                found = inside or found
        return found or None
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == code.co_name:
            if line in (n.lineno, min([n.lineno] + [d.lineno for d in n.decorator_list])):
                return [n]
    return None


def _function_tree(func: Any) -> ast.Module:
    """A module that holds only the function's own syntax node, read from its source. Raises OSError/TypeError
    when there is no source to read."""
    code = getattr(func, "__code__", None)
    if not isinstance(code, types.CodeType):
        raise TypeError("not a Python function")
    lines, start = inspect.getsourcelines(func)
    nodes = _find_node(textwrap.dedent("".join(lines)), code, code.co_firstlineno - start + 1, start - 1)
    if nodes is None or (code.co_name == "<lambda>" and len(nodes) > 1):
        whole = "".join(linecache.getlines(code.co_filename))  # a lambda inside a larger statement
        nodes = (_find_node(whole, code, code.co_firstlineno, 0) if whole else None) or nodes
    if not nodes:
        raise OSError("the function's own code was not found in its source")
    body = [ast.Expr(value=n) if isinstance(n, ast.Lambda) else n for n in nodes]
    return ast.Module(body=body, type_ignores=[])


def _runtime_reason(name: str) -> Optional[str]:
    for prefix, why in _RUNTIME_NAMES.items():
        if matches(name, prefix):
            return why
    return None


def _keyword(call: ast.Call, name: str) -> Optional[ast.AST]:
    return next((k.value for k in call.keywords if k.arg == name), None)


def _text_of(node: ast.AST) -> str:
    return _text(node, 60)


class _Uses:
    """What the code of a checked function and of the helpers it uses touches."""

    def __init__(self, repo: Optional[Path] = None) -> None:
        self.names: Set[str] = set()  # dotted names (modules, functions, classes, chains)
        self.attrs: Dict[str, Set[str]] = {}  # attribute name -> code that looks it up on something not a module
        self.runtime: List[str] = []  # code that builds names at run time
        self.repo = repo
        self.lookups: Dict[str, Tuple[bool, Any]] = {}

    def lookup(self, path: str) -> Tuple[bool, Any]:
        if path not in self.lookups:
            self.lookups[path] = _lookup(path)
        return self.lookups[path]

    def attr(self, name: str, text: str) -> None:
        self.attrs.setdefault(name, set()).add(text)

    def dynamic(self, text: str) -> None:
        if text not in self.runtime and len(self.runtime) < _MAX_RUNTIME:
            self.runtime.append(text)


def _own(obj: Any, home: Optional[str], repo: Optional[Path]) -> bool:
    """True for a function or class the student wrote: defined in the checked function's module, or in a Python
    file inside the student's repository (outside this package)."""
    if not isinstance(obj, (types.FunctionType, type)):
        return False
    if home is not None and getattr(obj, "__module__", None) == home:
        return True
    if repo is None:
        return False
    f = _source_file(obj)
    return (isinstance(f, str) and _inside(f, (str(Path(repo).resolve()) + os.sep,))
            and not _inside(f, (str(_PKG_DIR) + os.sep,)))


def _scan(func: Any, depth: int, seen: Set[int], uses: _Uses) -> None:
    func = _unwrap(func)
    if not isinstance(func, (types.FunctionType, types.BuiltinFunctionType, type, types.ModuleType)) \
            and callable(func):  # an object with a __call__ of its own class: read that method
        try:
            call = _unwrap(inspect.getattr_static(type(func), "__call__"))
        except AttributeError:
            call = None
        if isinstance(call, types.FunctionType):
            func = call
    if id(func) in seen or depth > _MAX_DEPTH:
        return
    seen.add(id(func))
    if depth == 0:
        uses.names.update(_names_of(func))
    if isinstance(func, type):
        if not _is_library_object(func):
            for member in _class_functions(func):
                _scan(member, depth + 1, seen, uses)
        return
    if isinstance(func, (types.BuiltinFunctionType, types.ModuleType)) or _is_library_object(func):
        uses.names.update(_names_of(func))  # a library's own code: its name is what counts
        return
    if _generated_method(func):  # dataclass or namedtuple methods: no source; what their closures hold counts
        for cell in getattr(func, "__closure__", None) or ():
            try:
                value = cell.cell_contents
            except ValueError:
                continue
            for inner in [value] + _held_code(value):
                if isinstance(_plain(inner), _CODE_TYPES):
                    uses.names |= _names_of(_plain(inner))
        return
    try:
        tree = _function_tree(func)
    except (OSError, TypeError, SyntaxError, ValueError, AttributeError):
        uses.dynamic(f"{_label(func)}: {_WHY_UNREADABLE}")
        return
    try:
        _Reader(func, tree, depth, seen, uses).run()
    except Exception as exc:  # noqa: BLE001 - never let odd code switch the guard off
        uses.dynamic(f"{_label(func)}: the check could not read this code ({type(exc).__name__}); "
                     "please tell your mentor")


class _Reader:
    """Reads one function's syntax tree against its globals (see the module docstring)."""

    def __init__(self, func: Any, tree: ast.Module, depth: int, seen: Set[int], uses: _Uses) -> None:
        self.func, self.tree, self.depth, self.seen, self.uses = func, tree, depth, seen, uses
        glb: Dict[str, Any] = dict(getattr(func, "__globals__", {}) or {})
        code = getattr(func, "__code__", None)
        closure = getattr(func, "__closure__", None)
        if code is not None and closure:  # closure variables behave like globals for our purpose
            for name, cell in zip(code.co_freevars, closure):
                try:
                    glb[name] = cell.cell_contents
                except ValueError:
                    pass
        self.glb = glb
        self.home = getattr(func, "__module__", None)
        self.label = _label(func)
        self.imports: Dict[str, Set[str]] = {}  # local name -> dotted paths, from import statements
        self.local: Set[str] = set()  # names bound inside the function (they shadow globals)
        self.alias: Dict[str, Set[str]] = {}  # local name -> modules, classes, functions it may hold
        self.helpers: List[Any] = []
        self.called: Set[int] = set()
        self.reported: Set[int] = set()  # name nodes whose run-time finding was given with their call
        self.held: Dict[int, List[Any]] = {}

    # ------------------------------------------------------------------------------------------------ helpers
    def own(self, obj: Any) -> bool:
        return _own(obj, self.home, self.uses.repo)

    def add_helper(self, obj: Any) -> None:
        if isinstance(obj, types.FunctionType):
            if self.own(obj):
                self.helpers.append(obj)
        elif isinstance(obj, type):
            if self.own(obj):
                self.helpers.extend(_class_functions(obj))
        elif not isinstance(obj, _CODE_TYPES) and self.own(type(obj)):  # an object of the notebook's own class
            self.helpers.extend(_class_functions(type(obj)))

    def hold(self, obj: Any) -> List[Any]:
        """Record what a global holds: the notebook's own code in it is read as a helper, the names of the
        functions, classes and modules inside it count as used. Returns that code."""
        if id(obj) in self.held:
            return self.held[id(obj)]
        inner_code = [_plain(inner) for inner in _held_code(obj, self.own)]
        self.held[id(obj)] = inner_code
        self.add_helper(_plain(obj))
        for inner in inner_code:
            for n in _names_of(inner):
                self.code_name(n, f"{self.label} uses an object that holds {n}")
            self.add_helper(inner)
        return inner_code

    def object_paths(self, obj: Any) -> Set[str]:
        """Names of a global when it is code, and of the code it holds (a list of modules)."""
        out: Set[str] = set()
        base = _plain(obj)
        if isinstance(base, _CODE_TYPES):
            out |= _names_of(base)
        for inner in self.hold(obj):
            out |= _names_of(inner)
        return out

    def code_name(self, path: str, text: str) -> Optional[str]:
        """Record a name reached through an import or a code object; refuse the run-time machinery (returns why)."""
        names = {path}
        parts = path.split(".")
        for i in range(len(parts), 0, -1):  # a module reached through another one: importlib.sys.modules
            found, obj = self.uses.lookup(".".join(parts[:i]))
            if found and (i == len(parts) or isinstance(obj, _CODE_TYPES)):
                names |= {".".join([n] + parts[i:]) for n in _names_of(obj)}
        self.uses.names |= names
        for n in sorted(names):
            why = _runtime_reason(n)
            if why:
                self.uses.dynamic(f"{text}: {why}")
                return why
        return None

    def all_modules(self, paths: Set[str]) -> bool:
        return bool(paths) and all(isinstance(self.uses.lookup(p)[1], types.ModuleType) for p in paths)

    # ------------------------------------------------------------------------------------------------ names
    def name_paths(self, name: str) -> Tuple[Set[str], str]:
        """``(paths, kind)`` of a plain name; kind is 'code' (an import, or a module, class or function), 'data'
        (a global that holds data), 'local' (a local variable or parameter), 'builtin' or 'unknown'."""
        if name in self.imports:
            return set(self.imports[name]), "code"
        if name in self.local:
            paths = self.alias.get(name)
            return (set(paths), "code") if paths else (set(), "local")
        if name in self.glb:
            obj = self.glb[name]
            self.hold(obj)
            base = _plain(obj)
            if isinstance(base, _CODE_TYPES):
                return _names_of(base), "code"
            return _names_of(obj), "data"
        if hasattr(builtins, name):
            return {"builtins." + name}, "builtin"
        return {name}, "unknown"

    def chain_paths(self, node: ast.AST) -> Tuple[Set[str], str]:
        if isinstance(node, ast.Name):
            return self.name_paths(node.id)
        if isinstance(node, ast.Attribute):
            base, kind = self.chain_paths(node.value)
            if kind == "local":
                return set(), "local"
            if kind == "data" and not base:
                parts = _dotted(node)
                return ({".".join(parts)} if parts else set()), "data"
            return {b + "." + node.attr for b in base}, kind
        paths = self.may(node)
        return (paths, "code") if paths else (set(), "local")

    def func_names(self, node: ast.AST) -> Set[str]:
        paths, kind = self.chain_paths(node)
        return paths if kind in ("code", "builtin") else set()

    def may(self, node: ast.AST, depth: int = 0) -> Set[str]:
        """Dotted names of the modules, classes and functions an expression may give or hold (an over-estimate)."""
        if depth > 12 or node is None:
            return set()
        d = depth + 1
        if isinstance(node, ast.Name):
            if node.id in self.imports:
                return set(self.imports[node.id])
            if node.id in self.local:
                return set(self.alias.get(node.id, ()))
            if node.id in self.glb:
                return self.object_paths(self.glb[node.id])
            return {"builtins." + node.id} if hasattr(builtins, node.id) else set()
        if isinstance(node, ast.Attribute):
            return {b + "." + node.attr for b in self.may(node.value, d)}
        if isinstance(node, (ast.Subscript, ast.Starred, ast.NamedExpr, ast.Await)):
            return self.may(node.value, d)
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            return set().union(*(self.may(e, d) for e in node.elts))
        if isinstance(node, ast.Dict):
            return set().union(*(self.may(v, d) for v in node.values))
        if isinstance(node, ast.IfExp):
            return self.may(node.body, d) | self.may(node.orelse, d)
        if isinstance(node, ast.BoolOp):
            return set().union(*(self.may(v, d) for v in node.values))
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            return self.may(node.elt, d)
        if isinstance(node, ast.DictComp):
            return self.may(node.value, d)
        if isinstance(node, ast.Call):
            fn = self.func_names(node.func) if isinstance(node.func, (ast.Name, ast.Attribute)) \
                else self.may(node.func, d)
            out: Set[str] = set()
            if fn & _IMPORT_FUNCS:
                out |= self.import_target(node, fn)
            elif fn & _GETATTR_FUNCS and len(node.args) >= 2:
                name = node.args[1].value if isinstance(node.args[1], ast.Constant) else _fold(node.args[1])
                if isinstance(name, str):
                    out |= {b + "." + name for b in self.may(node.args[0], d)}
            elif fn & _PASS_THROUGH:
                for a in node.args:
                    out |= self.may(a, d)
                for k in node.keywords:
                    out |= self.may(k.value, d)
            elif isinstance(node.func, ast.Lambda):
                out |= self.may(node.func.body, d)
            return out
        return set()

    def import_target(self, node: ast.Call, fn: Set[str]) -> Set[str]:
        """The module an import call with a name in quotes gives (``__import__("a.b")`` gives ``a``)."""
        arg = node.args[0] if node.args else _keyword(node, "name")
        name = arg.value if isinstance(arg, ast.Constant) and isinstance(arg.value, str) else None
        if not name or name.startswith("."):
            return set()
        name = name.replace(":", ".").strip()
        if fn & {"builtins.__import__", "importlib.__import__"}:
            fromlist = len(node.args) >= 4 or _keyword(node, "fromlist") is not None
            return {name if fromlist else name.split(".")[0]}
        return {name}

    # ------------------------------------------------------------------------------------------------ passes
    def run(self) -> None:
        nodes = list(ast.walk(self.tree))
        self.read_imports(nodes)
        self.read_locals(nodes)
        self.read_bindings(nodes)
        self.called = {id(n.func) for n in nodes if isinstance(n, ast.Call)}
        self.read_owner()
        for node in nodes:
            if isinstance(node, ast.Attribute):
                self.visit_attribute(node)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                self.visit_name(node)
            if isinstance(node, ast.Call):
                self.visit_call(node)
        for helper in self.helpers:
            _scan(helper, self.depth + 1, self.seen, self.uses)

    def read_imports(self, nodes: List[ast.AST]) -> None:
        for node in nodes:
            if isinstance(node, ast.Import):
                for a in node.names:
                    parts = a.name.split(".")
                    for i in range(len(parts)):
                        self.code_name(".".join(parts[: i + 1]), "import " + a.name)
                    self.uses.names |= _module_file_names(a.name)
                    key, target = (a.asname, a.name) if a.asname else (parts[0], parts[0])
                    self.imports.setdefault(key, set()).add(target)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                self.code_name(node.module, "from " + node.module + " import ...")
                self.uses.names |= _module_file_names(node.module)
                for a in node.names:
                    if a.name == "*":
                        continue
                    full, text = f"{node.module}.{a.name}", f"from {node.module} import {a.name}"
                    self.code_name(full, text)
                    self.imports.setdefault(a.asname or a.name, set()).add(full)
                    if not self.all_modules({full}):
                        self.uses.attr(a.name, text)

    def read_locals(self, nodes: List[ast.AST]) -> None:
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                a = node.args
                for arg in list(a.posonlyargs) + a.args + a.kwonlyargs:
                    self.local.add(arg.arg)
                for arg in (a.vararg, a.kwarg):
                    if arg is not None:
                        self.local.add(arg.arg)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.local.add(node.name)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                self.local.add(node.id)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                self.local.add(node.name)
        top = self.tree.body[0] if self.tree.body else None
        if isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self.local.discard(top.name)  # the function's own name is global (recursion)
        code = getattr(self.func, "__code__", None)
        if code is not None:  # parameter defaults as they really are (lib=np, g=make_helper())
            params = list(code.co_varnames[: code.co_argcount])
            defaults = getattr(self.func, "__defaults__", None) or ()
            pairs = list(zip(params[len(params) - len(defaults):], defaults))
            pairs += list((getattr(self.func, "__kwdefaults__", None) or {}).items())
            for name, value in pairs:
                paths = self.object_paths(value)
                if paths:
                    self.alias.setdefault(name, set()).update(paths)

    def read_bindings(self, nodes: List[ast.AST]) -> None:
        """Local names that may hold a module, class or function: ``p = np``, ``a, b = np, sp``, ``for m in (np,
        np.ma)``, ``with ... as m``, a parameter default (flow-insensitive: every binding counts)."""
        pairs: List[Tuple[str, ast.AST]] = []

        def pair(target: ast.AST, value: ast.AST) -> None:
            if isinstance(target, ast.Name):
                pairs.append((target.id, value))
            elif isinstance(target, ast.Starred):
                pair(target.value, value)
            elif isinstance(target, (ast.Tuple, ast.List)):
                vals = value.elts if isinstance(value, (ast.Tuple, ast.List)) else None
                if vals is not None and len(vals) == len(target.elts) \
                        and not any(isinstance(e, ast.Starred) for e in list(target.elts) + list(vals)):
                    for t, v in zip(target.elts, vals):
                        pair(t, v)
                else:
                    for t in target.elts:
                        pair(t, value)

        for node in nodes:
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    pair(t, node.value)
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.NamedExpr)) and node.value is not None:
                pair(node.target, node.value)
            elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
                pair(node.target, node.iter)  # what a container may hold, its items may be
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    if item.optional_vars is not None:
                        pair(item.optional_vars, item.context_expr)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                a = node.args
                pos = list(a.posonlyargs) + list(a.args)
                pairs.extend((arg.arg, d) for arg, d in zip(pos[len(pos) - len(a.defaults):], a.defaults))
                pairs.extend((arg.arg, d) for arg, d in zip(a.kwonlyargs, a.kw_defaults) if d is not None)
        for _ in range(10):
            changed = False
            for name, value in pairs:
                if name not in self.local:
                    continue
                new = self.may(value) - self.alias.get(name, set())
                if new:
                    self.alias.setdefault(name, set()).update(new)
                    changed = True
            if not changed:
                break

    def read_owner(self) -> None:
        """A method of the notebook's own class: the other methods of that class are helpers (self.helper())."""
        qual = getattr(self.func, "__qualname__", "") or ""
        if "." not in qual or "<" in qual:
            return
        owner: Any = self.glb.get(qual.split(".")[0], None)
        for part in qual.split(".")[1:-1]:
            owner = getattr(owner, part, None) if isinstance(owner, type) else None
        if isinstance(owner, type) and self.own(owner):
            self.helpers.extend(_class_functions(owner))

    # ------------------------------------------------------------------------------------------------ visits
    def visit_name(self, node: ast.Name) -> None:
        if node.id == "__builtins__":
            self.uses.dynamic(f"__builtins__: {_WHY_LOOKUP}")
            return
        paths, kind = self.name_paths(node.id)
        if kind == "local":
            return
        if kind in ("code", "builtin"):
            text = "" if id(node) in self.reported else node.id
            for p in paths:
                if text:
                    self.code_name(p, text)
                else:
                    self.uses.names.add(p)
            if paths & _NAME_FUNCS and id(node) not in self.called:
                self.uses.dynamic(f"{node.id}: {_WHY_VALUE}")
        else:
            self.uses.names |= paths  # data and names not defined yet: as written

    def visit_attribute(self, node: ast.Attribute) -> None:
        text = _text_of(node)
        if node.attr in _RUNTIME_ATTRS:
            self.uses.dynamic(f"{text}: {_RUNTIME_ATTRS[node.attr]}")
        paths, kind = self.chain_paths(node)
        if kind in ("code", "builtin"):
            for p in paths:
                if id(node) in self.reported:
                    self.uses.names.add(p)
                else:
                    self.code_name(p, text)
            if paths & _NAME_FUNCS and id(node) not in self.called:
                self.uses.dynamic(f"{text}: {_WHY_VALUE}")
            if not self.all_modules(paths):
                self.uses.attr(node.attr, text)
        else:
            self.uses.names |= paths
            self.uses.attr(node.attr, text)

    def visit_call(self, node: ast.Call) -> None:
        fn = self.func_names(node.func) if isinstance(node.func, (ast.Name, ast.Attribute)) else self.may(node.func)
        last = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
        text = _text_of(node)
        if isinstance(node.func, (ast.Name, ast.Attribute)):  # eval("..."), pickle.loads(...): shown with the call
            for n in sorted(fn):
                if self.code_name(n, text):
                    self.reported.add(id(node.func))
                    break
        if fn & _IMPORT_FUNCS or last in ("import_module", "__import__"):
            self.import_call(node, fn, text)
        elif fn & _GETATTR_FUNCS:
            self.getattr_call(node, text)
        elif fn & _GETTER_FUNCS:
            self.getter_names(node, fn, text, record=True)
        if isinstance(node.func, ast.Call) and node.args:  # attrgetter("x")(obj), methodcaller("x")(obj)
            inner = node.func
            inner_fn = self.func_names(inner.func) if isinstance(inner.func, (ast.Name, ast.Attribute)) else set()
            if inner_fn & _GETTER_FUNCS:
                base, kind = self.chain_paths(node.args[0])
                if kind in ("code", "builtin"):
                    for name in self.getter_names(inner, inner_fn, text, record=False):
                        for b in base:
                            self.code_name(f"{b}.{name}", text)

    def import_call(self, node: ast.Call, fn: Set[str], text: str) -> None:
        arg = node.args[0] if node.args else _keyword(node, "name")
        if arg is None:
            return
        literal = arg.value if isinstance(arg, ast.Constant) and isinstance(arg.value, str) else None
        name = literal if literal is not None else _fold(arg)
        if literal is None:
            self.uses.dynamic(f"{text}: {_WHY_MODULE}")
        if not isinstance(name, str):
            return
        name = name.strip()
        if fn & {"pkgutil.resolve_name"}:
            name = name.replace(":", ".")
        if name.startswith("."):
            pkg = node.args[1] if len(node.args) > 1 else _keyword(node, "package")
            try:
                assert isinstance(pkg, ast.Constant) and isinstance(pkg.value, str)
                name = importlib.util.resolve_name(name, pkg.value)
            except (AssertionError, ImportError, ValueError):
                self.uses.dynamic(f"{text}: {_WHY_MODULE}")
                return
        parts = [p for p in name.split(".") if p]
        for i in range(len(parts)):
            self.code_name(".".join(parts[: i + 1]), text)
        self.uses.names |= _module_file_names(".".join(parts))

    def getattr_call(self, node: ast.Call, text: str) -> None:
        if len(node.args) < 2:
            return
        obj, nm = node.args[0], node.args[1]
        base, kind = self.chain_paths(obj)
        code_obj = self.is_code(obj, base, kind)
        literal = nm.value if isinstance(nm, ast.Constant) and isinstance(nm.value, str) else None
        name = literal if literal is not None else _fold(nm)
        if isinstance(name, str):
            if name in _RUNTIME_ATTRS:
                self.uses.dynamic(f"{text}: {_RUNTIME_ATTRS[name]}")
            full = {f"{b}.{name}" for b in base} if kind in ("code", "builtin") else set()
            for p in full:
                self.code_name(p, text)
            if not self.all_modules(full):
                self.uses.attr(name, text)
        if literal is None and code_obj:
            self.uses.dynamic(f"{text}: {_WHY_ATTR}")

    def getter_names(self, node: ast.Call, fn: Set[str], text: str, record: bool) -> List[str]:
        caller = any(n.endswith("methodcaller") for n in fn)
        out: List[str] = []
        for a in (node.args[:1] if caller else node.args):
            literal = a.value if isinstance(a, ast.Constant) and isinstance(a.value, str) else None
            name = literal if literal is not None else _fold(a)
            if record and literal is None:
                self.uses.dynamic(f"{text}: {_WHY_ATTR}")
            if not isinstance(name, str):
                continue
            parts = [part.strip() for part in name.split(".") if part.strip()]
            if parts:
                out.append(".".join(parts))
            for part in parts if record else ():
                self.uses.attr(part, text)
                if part in _RUNTIME_ATTRS:
                    self.uses.dynamic(f"{text}: {_RUNTIME_ATTRS[part]}")
        return out

    def global_object(self, node: ast.AST) -> Any:
        """The object behind a global name or a chain of one (modules and classes walked statically)."""
        if isinstance(node, ast.Name):
            if node.id in self.local or node.id in self.imports or node.id not in self.glb:
                return _MISSING
            return _plain(self.glb[node.id])
        if isinstance(node, ast.Attribute):
            base = self.global_object(node.value)
            if base is _MISSING or not isinstance(base, (types.ModuleType, type)):
                return _MISSING
            try:
                return _strip_descriptor(inspect.getattr_static(base, node.attr))
            except Exception:  # noqa: BLE001
                return _MISSING
        return _MISSING

    def is_code(self, node: ast.AST, base: Set[str], kind: str) -> bool:
        """True when an expression gives a module, or a class or function of a library (the student's own classes
        and functions, and data, are not code here)."""
        if kind not in ("code", "builtin"):
            return False
        objs: List[Any] = []
        for p in base:
            found, obj = self.uses.lookup(p)
            if not found:
                obj = self.global_object(node)
                if obj is _MISSING:
                    return True  # an import the guard cannot reach yet: it came from code, so count it
            objs.append(obj)
        if not objs:
            return True
        return any(isinstance(o, types.ModuleType)
                   or (isinstance(o, (type, types.FunctionType, types.BuiltinFunctionType, types.MethodType))
                       and not self.own(o)) for o in objs)


@dataclass(frozen=True)
class _Rule:
    text: str
    forms: Tuple[str, ...]  # the entry and the names of what it names (obspy.Trace.trigger: obspy.core.trace...)
    member: Optional[str]  # last name of an entry that names a function, class or method (not a module)


def _rule(text: str) -> _Rule:
    forms = {text}
    member = None
    parts = text.split(".")
    found, obj = _lookup(text)
    if found:
        forms |= _names_of(obj)
        if len(parts) > 1 and not isinstance(obj, types.ModuleType):
            member = parts[-1]
    elif len(parts) > 2 and any(p[:1].isupper() for p in parts[1:-1]):
        member = parts[-1]  # a method of a class whose library is not imported yet: obspy.Trace.trigger
    return _Rule(text, tuple(sorted(forms)), member)


def _collect(func: Any, repo: Optional[Path] = None) -> _Uses:
    uses = _Uses(repo)
    seen: Set[int] = set()
    home = getattr(_unwrap(func), "__module__", None)
    for inner in _held_code(func):  # what a partial handed in as the answer binds: partial(f, helper=lib.g)
        inner = _plain(inner)
        uses.names |= _names_of(inner)
        if _own(inner, home, repo):
            _scan(inner, 1, seen, uses)
    _scan(func, 0, seen, uses)
    return uses


def collect_names(func: Callable) -> Set[str]:
    """All module names, dotted chains and plain names that ``func`` uses (see module docstring)."""
    return set(_collect(func).names)


def check_function(func: Callable, forbidden: Iterable[str], repo: Optional[Path] = None) -> GuardReport:
    """Check ``func`` against the ``forbidden`` list of a task spec (``repo``: the student's repository, whose
    Python files count as the student's own helpers)."""
    forbidden = [str(f).strip() for f in (forbidden or []) if f and str(f).strip()]
    if not forbidden:
        return GuardReport(ok=True)
    uses = _collect(func, repo)
    violations: List[str] = []
    offending: Set[str] = set()
    for text in forbidden:
        rule = _rule(text)
        hits = {n for n in uses.names if any(matches(n, form) for form in rule.forms)}
        if rule.member:
            hits |= uses.attrs.get(rule.member, set())
        if hits:
            violations.append(text)
            offending |= hits
    return GuardReport(ok=not violations and not uses.runtime, violations=violations, offending=sorted(offending),
                       runtime=list(uses.runtime))


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
