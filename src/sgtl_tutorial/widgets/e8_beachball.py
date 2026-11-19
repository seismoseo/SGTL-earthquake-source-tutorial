"""E8 · Beachball explorer: turn strike, dip and rake, and watch your own predicted polarities and misfit.

The explorer computes no projection, no polarity and no misfit by itself. It hands everything to the functions you
give it:

- ``project(takeoff_deg, azimuth_deg) -> (x, y)``: your ``equal_area`` of M50 (task 4); it places every station and
  every point of the shading on the net.
- ``misfit(strike, dip, rake, azimuth, takeoff, polarity, weight) -> (misfit, predicted)``: your polarity misfit of
  M51 (task 1). Every redraw calls it twice: once on the stations (your misfit and the stations whose observed
  polarity differs from your prediction) and once on a grid of directions that covers the lower half of the focal
  sphere (the shading: your predicted compressions are dark).

The picture is the lower-hemisphere net of M50: north is up, a ray leaving the source straight down sits in the
middle, a horizontal ray on the rim; where a ray that leaves upward is drawn is up to your ``project``.
Compressions (up) are filled circles, dilatations (down) open circles; stations your function gets wrong are ringed
in red. Without ``project`` you see the rim of the net and the status line only; without ``misfit``, the stations
only.

The controls are sliders for strike, dip and rake, and a menu of mechanisms to jump to (``marks``, for example the
mechanism of a program or of a bulletin).

Credit: Minseong Seo (SGTL, Seoul National University). License: MIT.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ._common import Explorer, call_yours, func_name, status_html

GRID_TAKEOFFS = 61     # shading grid: takeoff 0-90 degrees (every 1.5 degrees) ...
GRID_AZIMUTHS = 181    # ... times azimuth 0-360 (every 2 degrees): the lower half of the focal sphere
NONE_MARK = "(keep the sliders)"


def _directions() -> Tuple[np.ndarray, np.ndarray]:
    """(takeoff, azimuth) in degrees on a regular grid over the lower half sphere, as 2-D arrays."""
    return np.meshgrid(np.linspace(0.0, 90.0, GRID_TAKEOFFS), np.linspace(0.0, 360.0, GRID_AZIMUTHS), indexing="ij")


def _two_arrays(result: Any, size: int) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """Your project result as two finite float arrays of the given length, or None."""
    try:
        x, y = result
        x = np.asarray(x, dtype=float).ravel()
        y = np.asarray(y, dtype=float).ravel()
    except (TypeError, ValueError):
        return None
    if x.size != size or y.size != size or not (np.all(np.isfinite(x)) and np.all(np.isfinite(y))):
        return None
    return x, y


def _vector(value: Any, n: int, name: str) -> np.ndarray:
    out = np.asarray(value, dtype=float).ravel()
    if out.size != n:
        raise ValueError(f"{name} must have one value per station ({n}), not {out.size}")
    if not np.all(np.isfinite(out)):
        raise ValueError(f"{name} must hold finite numbers")
    return out


class BeachballExplorer(Explorer):
    """E8: a beachball under strike, dip and rake sliders, shaded by your own predicted polarities.

    azimuth, takeoff : station azimuths (degrees clockwise from north) and takeoff angles (degrees from the
                       downward vertical), one per station
    polarity         : observed polarities, +1 (up) or -1 (down)
    weight           : weights (default 1 for every station)
    project          : your equal_area of M50 (task 4): (takeoff_deg, azimuth_deg) -> (x, y), or None
    misfit           : your polarity_misfit of M51 (task 1), or None
    start            : the strike, dip and rake to begin with (degrees)
    marks            : {label: (strike, dip, rake)} mechanisms to jump to (shown in a menu)
    stations         : station names, one per station (shown in the status line for mismatches)
    """

    def __init__(self, azimuth: Any, takeoff: Any, polarity: Any, weight: Any = None, *,
                 project: Optional[Callable] = None, misfit: Optional[Callable] = None,
                 start: Sequence[float] = (0.0, 45.0, 90.0),
                 marks: Optional[Dict[str, Sequence[float]]] = None,
                 stations: Optional[Sequence[str]] = None) -> None:
        az = np.asarray(azimuth, dtype=float).ravel()
        n = az.size
        if n == 0:
            raise ValueError("give at least one station")
        self.azimuth = _vector(az, n, "azimuth")
        self.takeoff = _vector(takeoff, n, "takeoff")
        self.polarity = _vector(polarity, n, "polarity")
        if not np.all(np.isin(self.polarity, (-1.0, 1.0))):
            raise ValueError("polarity must be +1 (up) or -1 (down) for every station")
        self.weight = np.ones(n) if weight is None else _vector(weight, n, "weight")
        for label, func in (("project", project), ("misfit", misfit)):
            if func is not None and not callable(func):
                raise TypeError(f"{label} must be one of your functions (or None)")
        self.project, self.misfit = project, misfit
        self.names = [str(s) for s in stations] if stations is not None else [f"station {i + 1}" for i in range(n)]
        if len(self.names) != n:
            raise ValueError(f"stations must name every station ({n})")
        self.marks = {str(k): tuple(float(v) for v in m) for k, m in (marks or {}).items()}
        if any(len(m) != 3 for m in self.marks.values()):
            raise ValueError("every mark must be (strike, dip, rake)")
        super().__init__(5.2, 5.4)
        self.grid = _directions()

        w = self._widgets
        style = {"description_width": "initial"}
        s0, d0, r0 = (float(v) for v in start)
        self.strike_slider = w.FloatSlider(min=0.0, max=360.0, step=1.0, value=s0 % 360.0, description="Strike (deg)",
                                           continuous_update=False, style=style, layout=w.Layout(width="330px"))
        self.dip_slider = w.FloatSlider(min=0.0, max=90.0, step=1.0, value=min(max(d0, 0.0), 90.0),
                                        description="Dip (deg)", continuous_update=False, style=style,
                                        layout=w.Layout(width="330px"))
        self.rake_slider = w.FloatSlider(min=-180.0, max=180.0, step=1.0, value=min(max(r0, -180.0), 180.0),
                                         description="Rake (deg)", continuous_update=False, style=style,
                                         layout=w.Layout(width="330px"))
        self.jump = w.Dropdown(options=[NONE_MARK] + list(self.marks), value=NONE_MARK, description="Jump to",
                               style=style, layout=w.Layout(width="330px"))
        for control in (self.strike_slider, self.dip_slider, self.rake_slider):
            control.observe(self._changed, names="value")
        self.jump.observe(self._jumped, names="value")
        self.box = w.VBox([w.HBox([w.VBox([self.strike_slider, self.dip_slider, self.rake_slider, self.jump]),
                                   self.status]), self.image])
        self.redraw()

    # ------------------------------------------------------------------------------------------ controls
    def mechanism(self) -> Tuple[float, float, float]:
        return float(self.strike_slider.value), float(self.dip_slider.value), float(self.rake_slider.value)

    def set_mechanism(self, strike: float, dip: float, rake: float) -> None:
        """Move the three sliders at once (one redraw)."""
        with self.hold():
            self.strike_slider.value = float(strike) % 360.0
            self.dip_slider.value = min(max(float(dip), 0.0), 90.0)
            self.rake_slider.value = min(max(float(rake), -180.0), 180.0)
        self.redraw()

    def _jumped(self, change: Any) -> None:
        label = change.get("new") if isinstance(change, dict) else self.jump.value
        if label in self.marks:
            self.set_mechanism(*self.marks[label])

    # ---------------------------------------------------------------------------------------------- draw
    def _ask(self, azimuth: np.ndarray, takeoff: np.ndarray, polarity: np.ndarray, weight: np.ndarray,
             name: str) -> Tuple[Optional[float], Optional[np.ndarray], Optional[str]]:
        s, d, r = self.mechanism()
        result, problem = call_yours(self.misfit, name, s, d, r, azimuth.copy(), takeoff.copy(), polarity.copy(),
                                     weight.copy())
        if problem:
            return None, None, problem
        try:
            value = float(np.asarray(result[0], dtype=float))
            predicted = np.asarray(result[1], dtype=float).ravel()
        except (TypeError, ValueError, IndexError):
            return None, None, f"your {name} did not return (misfit, predicted)"
        if predicted.size != azimuth.size or not math.isfinite(value):
            return None, None, f"your {name} did not return one predicted polarity per point"
        return value, predicted, None

    def _place(self, takeoff: np.ndarray, azimuth: np.ndarray) -> Tuple[Optional[tuple], Optional[str]]:
        name = func_name(self.project, "equal_area")
        result, problem = call_yours(self.project, name, takeoff.copy(), azimuth.copy())
        if problem:
            return None, problem
        xy = _two_arrays(result, takeoff.size)
        if xy is None:
            return None, f"your {name} did not return two arrays (x, y) of finite numbers, one per ray"
        return xy, None

    def _draw(self) -> None:
        name = func_name(self.misfit, "polarity_misfit")
        notes: List[str] = []
        state: Dict[str, Any] = {"mechanism": self.mechanism(), "misfit": None, "mismatched": [], "shaded": False,
                                 "placed": False}
        shade = grid_xy = station_xy = None
        wrong = np.zeros(self.polarity.size, dtype=bool)
        if self.project is None:
            notes.append("Pass project=your equal_area (M50, task 4) to place the stations on the net.")
        else:
            station_xy, problem = self._place(self.takeoff, self.azimuth)
            if problem:
                notes.append(problem + ".")
            else:
                flat = (self.grid[0].ravel(), self.grid[1].ravel())
                grid_xy, problem = self._place(*flat)
                if problem:
                    notes.append(problem + " (shading).")
                    grid_xy = None
                else:
                    grid_xy = (grid_xy[0].reshape(self.grid[0].shape), grid_xy[1].reshape(self.grid[0].shape))
            state["placed"] = station_xy is not None
        if self.misfit is None:
            notes.append("Pass misfit=your polarity_misfit (task 1) to see the shading and the misfit.")
        else:
            value, predicted, problem = self._ask(self.azimuth, self.takeoff, self.polarity, self.weight, name)
            if problem:
                notes.append(problem + ".")
            else:
                state["misfit"] = value
                wrong = predicted != self.polarity
                state["mismatched"] = [self.names[i] for i in np.flatnonzero(wrong)]
            if grid_xy is not None:
                ginc, gaz = self.grid[0].ravel(), self.grid[1].ravel()
                ones = np.ones(gaz.size)
                _, shade, problem = self._ask(gaz, ginc, ones, ones, name)
                if problem:
                    notes.append(problem + " (shading).")
                    shade = None
                state["shaded"] = shade is not None
        self.state = state
        self._picture(station_xy, grid_xy, shade, wrong)
        lines = [f"Mechanism: strike {state['mechanism'][0]:g}, dip {state['mechanism'][1]:g}, "
                 f"rake {state['mechanism'][2]:g} deg; {self.polarity.size} stations."]
        if state["misfit"] is not None:
            lines.append(f"Your {name}: misfit {state['misfit']:.3f}, {len(state['mismatched'])} stations "
                         "differ from your prediction"
                         + (": " + ", ".join(state["mismatched"][:8]) + (" ..." if len(state["mismatched"]) > 8 else "")
                            if state["mismatched"] else "") + ".")
        self.status.value = status_html(lines + notes)

    def _picture(self, station_xy: Optional[tuple], grid_xy: Optional[tuple], shade: Optional[np.ndarray],
                 wrong: np.ndarray) -> None:
        fig = self.figure
        ax = fig.subplots(1, 1)
        t = np.linspace(0.0, 2.0 * math.pi, 361)
        if shade is not None and grid_xy is not None:
            sign = np.where(shade.reshape(grid_xy[0].shape) > 0, 1.0, -1.0)
            ax.contourf(grid_xy[0], grid_xy[1], sign, levels=[-2.0, 0.0, 2.0], colors=["white", "0.62"], zorder=1)
            self.lines["shade"] = int(np.count_nonzero(shade > 0))
        ax.plot(np.cos(t), np.sin(t), color="k", lw=1.2, zorder=3)
        if station_xy is not None:
            x, y = station_xy
            up = self.polarity > 0
            ax.scatter(x[up], y[up], s=46, color="k", edgecolors="w", linewidths=0.6, zorder=4,
                       label="Up (compression)")
            ax.scatter(x[~up], y[~up], s=46, facecolors="w", edgecolors="k", linewidths=1.0, zorder=4,
                       label="Down (dilatation)")
            if wrong.any():
                ax.scatter(x[wrong], y[wrong], s=150, facecolors="none", edgecolors="tab:red", linewidths=1.6,
                           zorder=5, label="Differs from your prediction")
            fig.legend(loc="outside lower center", ncol=3, frameon=False, fontsize=8)
        ax.text(0.0, 1.06, "N", ha="center", va="bottom", fontsize=10)
        ax.set_xlim(-1.15, 1.15)
        ax.set_ylim(-1.15, 1.2)
        ax.set_aspect("equal")
        ax.axis("off")
        s, d, r = self.mechanism()
        ax.set_title(f"Strike {s:g}, dip {d:g}, rake {r:g}", fontsize=10)


def beachball_explorer(azimuth: Any, takeoff: Any, polarity: Any, weight: Any = None, *,
                       project: Optional[Callable] = None, misfit: Optional[Callable] = None,
                 start: Sequence[float] = (0.0, 45.0, 90.0),
                       marks: Optional[Dict[str, Sequence[float]]] = None,
                       stations: Optional[Sequence[str]] = None) -> BeachballExplorer:
    """E8 explorer (see BeachballExplorer). Show it by making it the last line of a cell.

    Example (module M51, with your own function)::

        st.widgets.beachball_explorer(rays["azimuth"], rays["takeoff"], rays["polarity"], rays["weight"],
                                      project=equal_area, misfit=polarity_misfit,
                                      marks={"A program": (120.0, 60.0, 45.0)})
    """
    return BeachballExplorer(azimuth, takeoff, polarity, weight, project=project, misfit=misfit, start=start,
                             marks=marks, stations=stations)
