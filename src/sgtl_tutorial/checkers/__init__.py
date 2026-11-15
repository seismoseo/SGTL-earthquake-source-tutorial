"""Per-module checkers: ``sgtl_tutorial.checkers.mXX.check_Tn(target, ctx) -> Outcome``.

Contract for checker authors (see DESIGN.md section 4):

* ``target`` is the student's function (``st.check(..., func=f)``) or answer (``answer=x``);
  ``None`` for artifact/manual kinds.
* ``ctx`` (a dict that also allows ``ctx.rng`` style access) carries ``rng`` (numpy Generator
  seeded from sha256("user:task:reroll")), ``seed``, ``reroll``, ``criteria`` (this task's dict
  from ``criteria/MXX.yaml``), ``strict``, ``session``, ``task``, ``module``, ``spec``, ``user``,
  ``repo``, ``data_root`` and any extra keywords given to ``st.check``.
* Return :class:`Outcome` ``(passed, n_cases, n_failed, category, message, details)``.
  ``category`` must be a key of the spec's ``categories`` (its fixed message is printed).
  ``details`` may contain ``example={"inputs": ..., "got": ..., "error": ...}`` for ONE failing
  synthetic case, ``note`` (a sentence always shown) and ``real_data=True`` for real-data cases
  (then the error size is hidden). Never put a real-data expected value in ``message`` or ``note``.
* Do not catch NotImplementedError: the engine turns it into NOT STARTED.
* Truth comes only from construction (``sgtl_tutorial.synth``), an independent library (oracle),
  a different formula, or the student's own tool products. Never write the solution out here.
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np

from ..checks import CheckContext, Outcome

__all__ = ["Outcome", "CheckContext", "within_tol", "outcome_from_cases"]


def within_tol(got: Any, expected: Any, *, rel_tol: float = 0.0, abs_tol: float = 0.0) -> np.ndarray:
    """Element-wise ``|got - expected| <= max(abs_tol, rel_tol * |expected|)``; NaN counts as wrong."""
    g = np.asarray(got, dtype=float)
    e = np.asarray(expected, dtype=float)
    ok = np.abs(g - e) <= np.maximum(abs_tol, rel_tol * np.abs(e))
    return np.asarray(ok & np.isfinite(g), dtype=bool)


def outcome_from_cases(ok: Any, *, category: Optional[str] = None, message: str = "",
                       example: Optional[dict] = None, real_data: bool = False,
                       note: Optional[str] = None) -> Outcome:
    """Build an Outcome from a boolean array of passed cases (``category`` is used only on failure)."""
    ok = np.asarray(ok, dtype=bool).ravel()
    n_failed = int((~ok).sum())
    details: dict = {"real_data": bool(real_data)}
    if example is not None and n_failed:
        details["example"] = example
    if note:
        details["note"] = note
    return Outcome(passed=n_failed == 0, n_cases=int(ok.size), n_failed=n_failed,
                   category=None if n_failed == 0 else category, message=message, details=details)
