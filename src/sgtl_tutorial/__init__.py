"""Helper package for the SGTL earthquake source tutorial.

Typical notebook use::

    import sgtl_tutorial as st
    S = st.init("M01")                       # thread/memory caps, house style, short report
    st.predict("M01-T1", \"\"\"I expect ...\"\"\")    # write what you expect first
    st.check("M01-T1", func=my_function)     # PASS/FAIL box, logged to work/.sgtl/progress.jsonl
    st.hint("M01-T1", 1)                     # hints 2 and 3 unlock after failed checks

Submodules ``st.data``, ``st.plot``, ``st.synth`` and ``st.glossary`` load on first use, so
``st.init`` can set thread limits and library paths before numpy, matplotlib or pygmt start.

Credit: Minseong Seo (SGTL, Seoul National University). License: MIT.
"""
from __future__ import annotations

import importlib
from typing import Any

__version__ = "1.3.0"

from .checks import CheckContext, CheckResult, Outcome, check, hint, predict, progress, reroll  # noqa: E402
from .session import Session, init, server_rules  # noqa: E402

_LAZY = {"data", "plot", "synth", "glossary", "astguard", "checkers", "widgets", "cli", "datafetch", "pq", "seiscomp"}

__all__ = [
    "__version__",
    "init",
    "predict",
    "check",
    "hint",
    "progress",
    "reroll",
    "server_rules",
    "Session",
    "Outcome",
    "CheckResult",
    "CheckContext",
    "data",
    "plot",
    "synth",
    "glossary",
]


def __getattr__(name: str) -> Any:
    if name in _LAZY:
        mod = importlib.import_module(f"{__name__}.{name}")
        globals()[name] = mod
        return mod
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(globals()) | _LAZY)
