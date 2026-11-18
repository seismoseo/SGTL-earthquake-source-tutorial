"""Interactive explorers: optional sliders over a figure, for building intuition (not checked).

- E1 ``filter_bench(trace, spectrum=..., inventory=...)`` (module M10): band-pass corners, filter order,
  zero-phase or causal, counts or ground velocity; the record and its amplitude spectrum before and after.
- E9 ``fmd_explorer(mags, fmd=..., b_estimator=..., mc_estimator=...)`` (module M05): the frequency-magnitude
  distribution for the Mc and bin width you choose, with the Gutenberg-Richter line of your b-value.

An explorer never does a task for you: whatever a task asks you to write (counting magnitudes, a b-value, Mc,
an amplitude spectrum) comes from the function you pass in, and without it the explorer shows the data only.
Each redraw renders a static PNG with Matplotlib (ipywidgets 8, no ipympl), works without a display, and starts
no threads or processes, so it stays within the thread caps of ``st.init``. Make the explorer the last line of a
cell to show it; ``explorer.figure.savefig(...)`` keeps the current picture.

Credit: Minseong Seo (SGTL, Seoul National University). License: MIT.
"""
from __future__ import annotations

import importlib
from typing import Any

_WHERE = {"filter_bench": "e1_filter", "FilterBench": "e1_filter",
          "fmd_explorer": "e9_fmd", "FMDExplorer": "e9_fmd"}

__all__ = sorted(_WHERE)


def __getattr__(name: str) -> Any:
    if name in _WHERE:
        value = getattr(importlib.import_module(f"{__name__}.{_WHERE[name]}"), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list:
    return sorted(set(globals()) | set(_WHERE))
