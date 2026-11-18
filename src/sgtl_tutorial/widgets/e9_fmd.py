"""E9 · Frequency-magnitude distribution explorer: move Mc and the bin width, and watch your own functions.

The explorer counts nothing and estimates nothing by itself. It hands the magnitudes to the functions you give
it and draws what they return:

- ``fmd(mags, dm) -> (centers, n_noncum, n_cum)``: your counting function of M04 (per bin, and at or above);
- ``b_estimator(mags, mc, dm) -> b``: your b-value function of M05 (for example ``b_utsu``);
- ``sigma_estimator(used_mags, b) -> sigma``: its uncertainty (for example ``shi_bolt``); it receives the
  magnitudes at or above Mc only, by the rule of the M05 contract (m >= Mc - dm/2);
- ``mc_estimator(mags, dm) -> mc``: your completeness function of M05 (for example ``mc_maxc``), drawn as a
  dashed line; the button moves the Mc slider there.

Without ``fmd`` you see the magnitudes themselves, in the order given; without the estimators, no line and no b.
The Gutenberg-Richter line goes on the "at or above" panel only: N(>=m) = N_used * 10**(-b * (m - Mc)) for
m >= Mc, where N_used is the number of magnitudes at or above Mc and b is what your ``b_estimator`` returned.

Credit: Minseong Seo (SGTL, Seoul National University). License: MIT.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Optional, Sequence

import numpy as np

from ._common import Explorer, call_yours, func_name, status_html

MAGNITUDE_LABEL = r"Local magnitude, $\mathit{M}_{\mathrm{L}}$"


def _tidy(value: float) -> float:
    """A grid value without float noise in its last digits (0.30000000000000004 -> 0.3)."""
    return float(round(float(value), 10))


def _choices(values: Sequence[float]) -> list:
    return [(f"{v:.10g}", v) for v in values]


def _nearest(values: Sequence[float], target: float) -> float:
    return min(values, key=lambda v: abs(v - target))


def _finite_number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _three_arrays(result: Any) -> Optional[tuple]:
    """Your fmd result as three float arrays of one length, or None when it is not that."""
    try:
        parts = [np.asarray(part, dtype=float).ravel() for part in result]
    except (TypeError, ValueError):
        return None
    if len(parts) != 3 or parts[0].size == 0 or len({part.size for part in parts}) != 1:
        return None
    return tuple(parts)


class FMDExplorer(Explorer):
    """E9: the frequency-magnitude distribution for the Mc and bin width you choose, drawn from your functions.

    mags            : 1-D array-like of magnitudes (NaN values are left out)
    fmd             : your function fmd(mags, dm) -> (centers, n_noncum, n_cum), or None
    b_estimator     : your function b(mags, mc, dm) -> b-value, or None
    sigma_estimator : your function sigma(used_mags, b) -> uncertainty of b, or None
    mc_estimator    : your function mc(mags, dm) -> completeness magnitude, or None
    dm              : the bin width to start with (the step in which the magnitudes were reported)
    dm_options      : the bin widths the slider offers (default: dm times 0.5, 1, 2, 3 and 5)
    mc              : the Mc to start with (default: your mc_estimator's value, else the smallest bin)
    xlabel          : the label of the magnitude axis
    """

    def __init__(self, mags: Any, *, fmd: Optional[Callable] = None, b_estimator: Optional[Callable] = None,
                 sigma_estimator: Optional[Callable] = None, mc_estimator: Optional[Callable] = None,
                 dm: float = 0.1, dm_options: Optional[Sequence[float]] = None, mc: Optional[float] = None,
                 xlabel: Optional[str] = None) -> None:
        values = np.ravel(np.asarray(mags, dtype=np.float64))
        values = values[np.isfinite(values)]
        if values.size == 0:
            raise ValueError("fmd_explorer needs at least one magnitude that is not NaN")
        width = _finite_number(dm)
        if width is None or width <= 0:
            raise ValueError("dm, the bin width, must be a positive number")
        for label, func in (("fmd", fmd), ("b_estimator", b_estimator), ("sigma_estimator", sigma_estimator),
                            ("mc_estimator", mc_estimator)):
            if func is not None and not callable(func):
                raise TypeError(f"{label} must be one of your functions (or None)")
        super().__init__(9.0, 3.9)
        self.values = values
        self.fmd, self.b_estimator = fmd, b_estimator
        self.sigma_estimator, self.mc_estimator = sigma_estimator, mc_estimator
        self.xlabel = xlabel or MAGNITUDE_LABEL
        self._mc_cache: dict = {}

        dm = _tidy(dm)
        widths = sorted({_tidy(w) for w in (dm_options or [dm * k for k in (0.5, 1, 2, 3, 5)]) if w > 0} | {dm})
        grid = self._grid(dm)
        if mc is not None and _finite_number(mc) is not None:
            start = _nearest(grid, float(mc))
        else:
            estimate, _ = self._mc_estimate(dm)
            start = _nearest(grid, estimate) if estimate is not None else grid[0]

        w = self._widgets
        style = {"description_width": "initial"}
        self.mc_slider = w.SelectionSlider(options=_choices(grid), value=start, description="Mc",
                                           continuous_update=False, style=style,
                                           layout=w.Layout(width="330px"))
        self.dm_slider = w.SelectionSlider(options=_choices(widths), value=dm, description="Bin width",
                                           continuous_update=False, style=style,
                                           layout=w.Layout(width="260px"))
        self.mc_button = w.Button(description="Mc from your function", disabled=mc_estimator is None,
                                  tooltip="Move the Mc slider to what your mc_estimator returns",
                                  layout=w.Layout(width="190px"))
        self.mc_slider.observe(self._changed, names="value")
        self.dm_slider.observe(self._new_width, names="value")
        self.mc_button.on_click(self._use_estimate)
        self.box = w.VBox([w.HBox([self.mc_slider, self.dm_slider, self.mc_button]), self.image, self.status])
        self.redraw()

    # ---------------------------------------------------------------------------------------------- controls
    def _grid(self, dm: float) -> list:
        """Slider values for Mc: multiples of dm from the smallest to the largest magnitude."""
        first = math.floor(self.values.min() / dm + 1e-6)
        last = math.ceil(self.values.max() / dm - 1e-6)
        return [_tidy(k * dm) for k in range(first, last + 1)]

    def _mc_estimate(self, dm: float) -> tuple:
        """(your mc_estimator's value, None) or (None, message); one call per bin width."""
        if self.mc_estimator is None:
            return None, None
        if dm not in self._mc_cache:
            name = func_name(self.mc_estimator, "mc_estimator")
            result, problem = call_yours(self.mc_estimator, name, self.values.copy(), dm)
            value = _finite_number(result) if problem is None else None
            if problem is None and value is None:
                problem = f"your {name} did not return one finite number"
            self._mc_cache[dm] = (value, problem)
        return self._mc_cache[dm]

    def _new_width(self, change: Any) -> None:
        dm = change["new"]
        grid = self._grid(dm)
        target = _nearest(grid, self.mc_slider.value)
        with self.hold():
            self.mc_slider.options = _choices(grid)
            self.mc_slider.value = target
        self.redraw()

    def _use_estimate(self, _button: Any = None) -> None:
        estimate, _ = self._mc_estimate(self.dm_slider.value)
        if estimate is None:
            self.redraw()
            return
        target = _nearest([v for _, v in self.mc_slider.options], estimate)
        if target == self.mc_slider.value:
            self.redraw()
        else:
            self.mc_slider.value = target           # the slider's observer redraws

    # -------------------------------------------------------------------------------------------------- draw
    def _draw(self) -> None:
        dm, mc = self.dm_slider.value, self.mc_slider.value
        values = self.values
        used = values >= mc - dm / 2.0               # "at or above Mc", as the M05 contract defines it
        n_used = int(np.count_nonzero(used))
        notes = []

        b = sigma = None
        b_name = func_name(self.b_estimator, "b_estimator")
        if self.b_estimator is not None and n_used < 2:
            notes.append("Fewer than two magnitudes at or above Mc: no b-value.")
        elif self.b_estimator is not None:
            result, problem = call_yours(self.b_estimator, b_name, values.copy(), mc, dm)
            b = _finite_number(result) if problem is None else None
            if problem is None and (b is None or b <= 0):
                problem, b = f"your {b_name} did not return one positive finite number", None
            if problem:
                notes.append(problem + ".")
        s_name = func_name(self.sigma_estimator, "sigma_estimator")
        if b is not None and self.sigma_estimator is not None:
            result, problem = call_yours(self.sigma_estimator, s_name, values[used].copy(), b)
            sigma = _finite_number(result) if problem is None else None
            if problem is None and sigma is None:
                problem = f"your {s_name} did not return one finite number"
            if problem:
                notes.append(problem + ".")
        mc_guess, problem = self._mc_estimate(dm)
        if problem:
            notes.append(problem + ".")

        counts = None
        if self.fmd is not None:
            name = func_name(self.fmd, "fmd")
            result, problem = call_yours(self.fmd, name, values.copy(), dm)
            counts = _three_arrays(result) if problem is None else None
            if problem is None and counts is None:
                problem = f"your {name} did not return three arrays of the same length"
            if problem:
                notes.append(problem + "; showing the magnitudes instead.")
        else:
            notes.append("Pass fmd=your fmd function of M04 to draw the frequency-magnitude distribution.")
        if self.b_estimator is None:
            notes.append("Pass b_estimator=your b-value function to draw the Gutenberg-Richter line.")

        if counts is None:
            self._draw_magnitudes(used, mc, mc_guess)
        else:
            self._draw_counts(counts, dm, mc, n_used, b, sigma, mc_guess)

        self.state = {"mc": mc, "dm": dm, "n_used": n_used, "n_total": int(values.size), "b": b,
                      "sigma": sigma, "mc_estimate": mc_guess}
        summary = (f"Mc {mc:g}, bin width {dm:g}: {n_used:,} of {values.size:,} magnitudes at or above Mc "
                   f"(m >= Mc - bin width/2; these are the ones a b-value uses).")
        yours = []
        if b is not None:
            yours.append(f"your {b_name}: b = {b:.2f}")
        if sigma is not None:
            yours.append(f"your {s_name}: ± {sigma:.2f}")
        if mc_guess is not None:
            yours.append(f"your {func_name(self.mc_estimator, 'mc_estimator')}: Mc = {mc_guess:g} (dashed line)")
        mine = "; ".join(yours)
        self.status.value = status_html([summary, mine[:1].upper() + mine[1:], *notes])

    def _draw_counts(self, counts: tuple, dm: float, mc: float, n_used: int, b: Optional[float],
                     sigma: Optional[float], mc_guess: Optional[float]) -> None:
        centers, n_bin, n_up = counts
        fig = self.figure
        fig.set_size_inches(9.0, 3.9)
        ax_bin, ax_cum = fig.subplots(1, 2, sharex=True)
        left = min(float(centers.min()), float(self.values.min())) - dm
        right = max(float(centers.max()), float(self.values.max())) + dm
        handles = []
        for ax in (ax_bin, ax_cum):
            ax.axvspan(left, mc - dm / 2.0, color="0.9", lw=0, zorder=0)
            mc_line = ax.axvline(x=mc, c="tab:red", lw=1.2, label="Mc (slider)")
            guess_line = None
            if mc_guess is not None:
                guess_line = ax.axvline(mc_guess, color="tab:green", ls="--", lw=1.2, label="Your Mc function")
            ax.set_yscale("log")
            ax.set_xlim(left, right)
            ax.set_xlabel(self.xlabel)
        handles += [mc_line] + ([guess_line] if guess_line is not None else [])
        shown_bin = n_bin.copy()
        shown_bin[n_bin <= 0] = np.nan              # empty bins have no place on a log axis
        shown_cum = n_up.copy()
        shown_cum[n_up <= 0] = np.nan
        self.lines["per_bin"], = ax_bin.plot(centers, shown_bin, "o", ms=3.5, color="tab:blue", label="Per bin")
        self.lines["at_or_above"], = ax_cum.plot(centers, shown_cum, "s", ms=3.5, mfc="none", color="0.25",
                                                 label="At or above")
        handles = [self.lines["per_bin"], self.lines["at_or_above"]] + handles
        if b is not None:
            m_line = np.linspace(mc, max(float(centers.max()), mc), 40)
            self.lines["gr"], = ax_cum.plot(m_line, n_used * 10.0 ** (-b * (m_line - mc)), color="tab:orange",
                                            lw=1.6, label="Gutenberg-Richter line, your b")
            handles.append(self.lines["gr"])
        top = np.nanmax(np.concatenate([shown_bin, shown_cum, [1.0]]))
        for ax in (ax_bin, ax_cum):
            ax.set_ylim(0.5, 2.0 * top)
        ax_bin.set_ylabel("Number of events")
        ax_bin.set_title("Per bin", fontsize=10)
        ax_cum.set_title("At or above", fontsize=10)
        text = f"N = {n_used:,} at or above Mc"
        if b is not None:
            text += f"\nyour b = {b:.2f}" + (f" ± {sigma:.2f}" if sigma is not None else "")
        ax_cum.text(0.97, 0.96, text, transform=ax_cum.transAxes, ha="right", va="top", fontsize=9)
        fig.legend(handles=handles, loc="outside upper center", ncol=min(len(handles), 5), frameon=False,
                   fontsize=9)

    def _draw_magnitudes(self, used: np.ndarray, mc: float, mc_guess: Optional[float]) -> None:
        fig = self.figure
        fig.set_size_inches(6.5, 3.9)
        ax = fig.subplots()
        number = np.arange(1, self.values.size + 1)
        ax.plot(number[~used], self.values[~used], ".", ms=2.5, color="0.65", label="Below Mc")
        self.lines["used"], = ax.plot(number[used], self.values[used], ".", ms=2.5, color="tab:blue",
                                      label="At or above Mc")
        ax.axhline(mc, color="tab:red", lw=1.2, label="Mc (slider)")
        if mc_guess is not None:
            ax.axhline(mc_guess, color="tab:green", ls="--", lw=1.2, label="Your Mc function")
        ax.set_xlabel("Event number, in the order given")
        ax.set_ylabel(self.xlabel)
        ax.set_title("Magnitudes", fontsize=10)
        fig.legend(loc="outside upper center", ncol=4, frameon=False, fontsize=9, markerscale=3)


def fmd_explorer(mags: Any, *, fmd: Optional[Callable] = None, b_estimator: Optional[Callable] = None,
                 sigma_estimator: Optional[Callable] = None, mc_estimator: Optional[Callable] = None,
                 dm: float = 0.1, dm_options: Optional[Sequence[float]] = None, mc: Optional[float] = None,
                 xlabel: Optional[str] = None) -> FMDExplorer:
    """E9 explorer (see FMDExplorer). Show it by making it the last line of a cell.

    Example (module M05, with your own functions)::

        st.widgets.fmd_explorer(mags, fmd=fmd, b_estimator=b_utsu, sigma_estimator=shi_bolt,
                                mc_estimator=mc_maxc, dm=0.1)
    """
    return FMDExplorer(mags, fmd=fmd, b_estimator=b_estimator, sigma_estimator=sigma_estimator,
                       mc_estimator=mc_estimator, dm=dm, dm_options=dm_options, mc=mc, xlabel=xlabel)
