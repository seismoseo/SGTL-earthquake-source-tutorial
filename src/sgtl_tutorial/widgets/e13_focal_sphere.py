"""E13 · Focal-sphere fitter: turn strike, dip and rake, and watch your own quadrants move over your first motions.

The explorer computes no projection, no polarity and no axis by itself. It hands the angles to the functions you
give it and draws what they return:

- ``project(takeoff_deg, azimuth_deg) -> (x, y)``: your ``equal_area`` of M50 (task 4); it places every point;
- ``agreement(takeoff_deg, azimuth_deg, polarity, strike, dip, rake) -> (predicted, fraction)``: your
  ``polarity_agreement`` (task 6); its predictions on a dense set of directions shade the quadrants where it
  predicts compression (U), so the edges of the grey areas are the nodal planes, and its fraction for your first
  motions goes into the status line;
- ``axes(strike, dip, rake) -> ((p_trend, p_plunge), (t_trend, t_plunge))``: your ``pt_axes`` (task 3); it marks
  P and T (a point at takeoff 90 - plunge in the direction of the trend);
- ``aux_plane(strike, dip, rake) -> (strike2, dip2, rake2)``: your ``auxiliary_plane`` (task 2); the status line
  names the other plane.

Without ``project`` you see the rim of the net only; without ``agreement`` no shading and no fraction. A
``reference`` plane (for example a bulletin's) is drawn as a dashed edge, again from your ``agreement``.

Credit: Minseong Seo (SGTL, Seoul National University). License: MIT.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Optional, Sequence, Tuple

import numpy as np

from ._common import Explorer, call_yours, func_name, status_html

GRID_TAKEOFFS = 121                     # shading grid: takeoff 0-90 degrees (every 0.75 degree) ...
GRID_AZIMUTHS = 361                     # ... times azimuth 0-360 (every degree): the lower half of the sphere


def _directions() -> Tuple[np.ndarray, np.ndarray]:
    """(takeoff, azimuth) in degrees on a regular grid over the lower half sphere, as 2-D arrays."""
    return np.meshgrid(np.linspace(0.0, 90.0, GRID_TAKEOFFS), np.linspace(0.0, 360.0, GRID_AZIMUTHS), indexing="ij")


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _two_arrays(result: Any, size: int) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """Your project result as two float arrays of the given length, or None."""
    try:
        x, y = result
        x = np.asarray(x, dtype=float).ravel()
        y = np.asarray(y, dtype=float).ravel()
    except (TypeError, ValueError):
        return None
    if x.size != size or y.size != size:
        return None
    return x, y


def _labels(result: Any, size: int) -> Tuple[Optional[np.ndarray], Optional[float]]:
    """Your agreement result as (an array of 'U'/'D' strings, the fraction or None), or (None, None)."""
    try:
        predicted, fraction = result
        labels = np.asarray(predicted).astype(str).ravel()
    except (TypeError, ValueError):
        return None, None
    if labels.size != size or not set(labels.tolist()) <= {"U", "D"}:
        return None, None
    return labels, _finite(fraction)


def _first_motions(table: Any) -> dict:
    """takeoff, azimuth, polarity (and station names when given) from a DataFrame or a dict of columns."""
    if table is None:
        return {"takeoff": np.zeros(0), "azimuth": np.zeros(0), "polarity": np.zeros(0, dtype=str), "names": []}
    try:
        takeoff = np.asarray(table["takeoff_deg"], dtype=float).ravel()
        azimuth = np.asarray(table["azimuth_deg"], dtype=float).ravel()
        polarity = np.asarray([str(p).strip() for p in table["polarity"]])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("first_motions needs the columns takeoff_deg, azimuth_deg and polarity") from exc
    if not (takeoff.size == azimuth.size == polarity.size):
        raise ValueError("takeoff_deg, azimuth_deg and polarity must have the same length")
    try:
        names = [str(s).split(".")[-1] for s in table["station"]]
    except (KeyError, TypeError):
        names = []
    return {"takeoff": takeoff, "azimuth": azimuth, "polarity": polarity,
            "names": names if len(names) == takeoff.size else []}


class FocalSphereFitter(Explorer):
    """E13: a focal sphere for the strike, dip and rake you choose, drawn only from your functions.

    first_motions : DataFrame (or dict of columns) with takeoff_deg, azimuth_deg, polarity (U, D or ?) and,
                    optionally, station; or None
    project       : your function equal_area(takeoff_deg, azimuth_deg) -> (x, y), or None
    agreement     : your function polarity_agreement(takeoff, azimuth, polarity, strike, dip, rake)
                    -> (predicted, fraction), or None
    axes          : your function pt_axes(strike, dip, rake) -> ((p_trend, p_plunge), (t_trend, t_plunge)), or None
    aux_plane     : your function auxiliary_plane(strike, dip, rake) -> (strike2, dip2, rake2), or None
    strike, dip, rake : the plane to start with (degrees)
    reference     : a plane (strike, dip, rake) drawn as a dashed edge, or None
    """

    def __init__(self, first_motions: Any = None, *, project: Optional[Callable] = None,
                 agreement: Optional[Callable] = None, axes: Optional[Callable] = None,
                 aux_plane: Optional[Callable] = None, strike: float = 0.0, dip: float = 60.0, rake: float = 0.0,
                 reference: Optional[Sequence[float]] = None) -> None:
        for label, func in (("project", project), ("agreement", agreement), ("axes", axes),
                            ("aux_plane", aux_plane)):
            if func is not None and not callable(func):
                raise TypeError(f"{label} must be one of your functions (or None)")
        start = [_finite(v) for v in (strike, dip, rake)]
        if any(v is None for v in start):
            raise ValueError("strike, dip and rake must be finite numbers")
        if reference is not None:
            ref = [_finite(v) for v in reference]
            if len(ref) != 3 or any(v is None for v in ref):
                raise ValueError("reference must be a plane (strike, dip, rake) of three finite numbers")
            reference = tuple(ref)
        super().__init__(5.6, 5.4)
        self.motions = _first_motions(first_motions)
        self.project, self.agreement, self.axes, self.aux_plane = project, agreement, axes, aux_plane
        self.reference = reference
        self.grid = _directions()

        w = self._widgets
        style = {"description_width": "initial"}
        self.strike_slider = w.FloatSlider(value=float(start[0]) % 360.0, min=0.0, max=359.0, step=1.0,
                                           description="Strike", continuous_update=False, style=style,
                                           layout=w.Layout(width="320px"))
        self.dip_slider = w.FloatSlider(value=min(max(float(start[1]), 0.0), 90.0), min=0.0, max=90.0, step=1.0,
                                        description="Dip", continuous_update=False, style=style,
                                        layout=w.Layout(width="320px"))
        self.rake_slider = w.FloatSlider(value=min(max(float(start[2]), -180.0), 180.0), min=-180.0, max=180.0,
                                         step=1.0, description="Rake", continuous_update=False, style=style,
                                         layout=w.Layout(width="320px"))
        for slider in (self.strike_slider, self.dip_slider, self.rake_slider):
            slider.observe(self._changed, names="value")
        self.box = w.VBox([w.HBox([self.strike_slider, self.dip_slider]), w.HBox([self.rake_slider]), self.image,
                           self.status])
        self.redraw()

    # -------------------------------------------------------------------------------------------------- draw
    def _plane(self) -> Tuple[float, float, float]:
        return float(self.strike_slider.value), float(self.dip_slider.value), float(self.rake_slider.value)

    def _predict(self, takeoff: np.ndarray, azimuth: np.ndarray, polarity: Sequence[str],
                 plane: Sequence[float]) -> Tuple[Optional[np.ndarray], Optional[float], Optional[str]]:
        name = func_name(self.agreement, "agreement")
        result, problem = call_yours(self.agreement, name, takeoff.copy(), azimuth.copy(), list(polarity),
                                     *plane)
        if problem:
            return None, None, problem
        labels, fraction = _labels(result, takeoff.size)
        if labels is None:
            return None, None, f"your {name} did not return (an array of 'U'/'D', a fraction)"
        return labels, fraction, None

    def _place(self, takeoff: np.ndarray, azimuth: np.ndarray) -> Tuple[Optional[tuple], Optional[str]]:
        name = func_name(self.project, "project")
        result, problem = call_yours(self.project, name, takeoff.copy(), azimuth.copy())
        if problem:
            return None, problem
        xy = _two_arrays(result, takeoff.size)
        if xy is None:
            return None, f"your {name} did not return two arrays (x, y) of the input's length"
        return xy, None

    def _draw(self) -> None:
        from matplotlib.patches import Circle

        plane = self._plane()
        fig = self.figure
        ax = fig.subplots()
        notes = []
        self.lines["rim"] = ax.add_patch(Circle((0.0, 0.0), 1.0, fill=False, edgecolor="k", lw=1.2))
        ax.text(0.0, 1.04, "N", ha="center", va="bottom", fontsize=9)
        state = {"plane": plane, "fraction": None, "other_plane": None, "p_axis": None, "t_axis": None}

        grid_xy = None
        shape = self.grid[0].shape
        flat = (self.grid[0].ravel(), self.grid[1].ravel())
        if self.project is None:
            notes.append("Pass project=your equal_area (task 4) to place the points.")
        else:
            grid_xy, problem = self._place(*flat)
            if problem:
                notes.append(problem + ".")
            else:
                grid_xy = (grid_xy[0].reshape(shape), grid_xy[1].reshape(shape))
        if self.agreement is None:
            notes.append("Pass agreement=your polarity_agreement (task 6) to shade the quadrants.")
        elif grid_xy is not None:
            labels, _, problem = self._predict(*flat, ["?"] * flat[0].size, plane)
            if problem:
                notes.append(problem + ".")
            else:
                sign = np.where(labels == "U", 1.0, -1.0).reshape(shape)
                ax.contourf(*grid_xy, sign, levels=[-2.0, 0.0, 2.0], colors=["white", "0.72"])
                ax.contour(*grid_xy, sign, levels=[0.0], colors="k", linewidths=1.0)
            if self.reference is not None:
                labels, _, problem = self._predict(*flat, ["?"] * flat[0].size, self.reference)
                if labels is not None:
                    ax.contour(*grid_xy, np.where(labels == "U", 1.0, -1.0).reshape(shape), levels=[0.0],
                               colors="tab:orange", linewidths=1.2, linestyles="dashed")

        m = self.motions
        if m["takeoff"].size and self.project is not None:
            xy, problem = self._place(m["takeoff"], m["azimuth"])
            if problem:
                notes.append(problem + ".")
            else:
                ups, downs = m["polarity"] == "U", m["polarity"] == "D"
                self.lines["up"], = ax.plot(xy[0][ups], xy[1][ups], "o", ms=8, mfc="k", mec="k",
                                            label="U (compression)")
                self.lines["down"], = ax.plot(xy[0][downs], xy[1][downs], "o", ms=8, mfc="white", mec="k",
                                              mew=1.5, label="D (dilatation)")
                for sx, sy, name in zip(xy[0], xy[1], m["names"]):
                    ax.text(sx + 0.04, sy + 0.04, name, fontsize=7)
            if self.agreement is not None:
                _, fraction, problem = self._predict(m["takeoff"], m["azimuth"], m["polarity"], plane)
                if problem:
                    notes.append(problem + ".")
                state["fraction"] = fraction

        if self.axes is not None and self.project is not None:
            name = func_name(self.axes, "axes")
            result, problem = call_yours(self.axes, name, *plane)
            try:
                (p_tr, p_pl), (t_tr, t_pl) = result
                pairs = [(float(p_tr), float(p_pl)), (float(t_tr), float(t_pl))]
            except (TypeError, ValueError):
                pairs = None
                problem = problem or f"your {name} did not return ((p_trend, p_plunge), (t_trend, t_plunge))"
            if problem:
                notes.append(problem + ".")
            else:
                xy, problem = self._place(np.array([90.0 - pairs[0][1], 90.0 - pairs[1][1]]),
                                          np.array([pairs[0][0], pairs[1][0]]))
                if problem:
                    notes.append(problem + ".")
                else:
                    ax.text(xy[0][0], xy[1][0], "P", ha="center", va="center", fontsize=12, fontweight="bold",
                            color="tab:red")
                    ax.text(xy[0][1], xy[1][1], "T", ha="center", va="center", fontsize=12, fontweight="bold",
                            color="tab:blue")
                    state["p_axis"], state["t_axis"] = pairs
        if self.aux_plane is not None:
            name = func_name(self.aux_plane, "aux_plane")
            result, problem = call_yours(self.aux_plane, name, *plane)
            try:
                other = tuple(float(v) for v in result)
                if len(other) != 3:
                    raise ValueError
            except (TypeError, ValueError):
                other = None
                problem = problem or f"your {name} did not return (strike2, dip2, rake2)"
            if problem:
                notes.append(problem + ".")
            state["other_plane"] = other

        ax.set_aspect("equal")
        ax.set_xlim(-1.15, 1.15)
        ax.set_ylim(-1.15, 1.15)
        ax.axis("off")
        ax.set_title(f"Strike {plane[0]:g}, dip {plane[1]:g}, rake {plane[2]:g}", fontsize=10)
        if "up" in self.lines:
            fig.legend(loc="outside lower center", ncol=2, frameon=False, fontsize=9)
        self.state = state

        lines = [f"Plane: strike {plane[0]:g}, dip {plane[1]:g}, rake {plane[2]:g}."]
        if state["other_plane"] is not None:
            s2, d2, r2 = state["other_plane"]
            lines.append(f"Your {func_name(self.aux_plane, 'aux_plane')}: the other plane is strike {s2:.1f}, "
                         f"dip {d2:.1f}, rake {r2:.1f}.")
        clear = int(np.isin(m["polarity"], ["U", "D"]).sum())
        if state["fraction"] is not None:
            lines.append(f"Your {func_name(self.agreement, 'agreement')}: fraction {state['fraction']:.3f} of the "
                         f"{clear} clear first motions agree.")
        if self.reference is not None and self.agreement is not None:
            lines.append("Dashed orange: the nodal planes of the reference plane " +
                         ", ".join(f"{v:g}" for v in self.reference) + ".")
        self.status.value = status_html(lines + notes)


def focal_sphere_fitter(first_motions: Any = None, *, project: Optional[Callable] = None,
                     agreement: Optional[Callable] = None, axes: Optional[Callable] = None,
                     aux_plane: Optional[Callable] = None, strike: float = 0.0, dip: float = 60.0,
                     rake: float = 0.0, reference: Optional[Sequence[float]] = None) -> FocalSphereFitter:
    """E13 explorer (see FocalSphereFitter). Show it by making it the last line of a cell.

    Example (module M50, with your own functions)::

        st.widgets.focal_sphere_fitter(table, project=equal_area, agreement=polarity_agreement, axes=pt_axes,
                                       aux_plane=auxiliary_plane, strike=120, dip=70, rake=-20)
    """
    return FocalSphereFitter(first_motions, project=project, agreement=agreement, axes=axes, aux_plane=aux_plane,
                           strike=strike, dip=dip, rake=rake, reference=reference)
