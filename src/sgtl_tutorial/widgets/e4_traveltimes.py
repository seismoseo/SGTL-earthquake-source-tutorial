"""E4 · Travel-time explorer: change a layered crust and the source depth, and watch your own travel-time curves.

The explorer computes no travel time by itself. It hands the layered model to the functions you give it and
draws what they return:

- ``direct(x_km, depth_km, model, phase) -> times``: your direct-wave function of M30 (``direct_time``);
- ``head(x_km, depth_km, model, phase, interface) -> (times, critical_km, crossover_km)``: your head-wave function
  of M30 (``head_wave``), called once for every boundary below the source (``interface`` = its row number).

The controls change the model that your functions receive: pick a layer, then move its thickness, P speed and S
speed; move the source depth; switch between P and S; show reduced time (time minus distance / reduction speed,
which tilts the curves so that small differences show). Every model handed to your functions is a fresh copy, a
pandas DataFrame with the columns ``top_km``, ``vp`` and ``vs`` (like ``st.data.velocity_model``). Without
functions you see the model only. The shaded band beyond ``locate_km`` (100 km) marks distances at which this
course does not use arrivals to locate earthquakes.

Credit: Minseong Seo (SGTL, Seoul National University). License: MIT.
"""
from __future__ import annotations

import math
from typing import Any, Callable, List, Optional, Tuple

import numpy as np

from ._common import Explorer, call_yours, func_name, status_html

REDUCTION_KM_S = {"P": 8.0, "S": 4.6}
LAYER_COLORS = ("tab:green", "tab:purple", "tab:brown", "tab:pink", "tab:olive", "tab:cyan")


def _layer_table(model: Any) -> Tuple[List[float], List[float], List[float], str]:
    """(tops, vp, vs, name) from a shipped model name or a table with top_km, vp and vs."""
    name = ""
    if isinstance(model, str):
        from .. import data as _data

        name = model
        model = _data.velocity_model(model)
    try:
        tops = [float(v) for v in model["top_km"]]
        vp = [float(v) for v in model["vp"]]
        vs = [float(v) for v in model["vs"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("model must be a shipped model name (for example 'kim1983') or a table with the "
                         "columns top_km, vp and vs") from exc
    if not tops or tops[0] != 0.0 or any(b <= a for a, b in zip(tops, tops[1:])):
        raise ValueError("model: top_km must start at 0 and increase from row to row")
    if not all(math.isfinite(v) and v > 0 for v in vp + vs):
        raise ValueError("model: every speed must be a positive number")
    return tops, vp, vs, name or str(getattr(model, "attrs", {}).get("name", "") or "your model")


def _times(result: Any, size: int) -> Optional[np.ndarray]:
    """Your times as a float array of the given size, or None when they are not that."""
    try:
        values = np.asarray(result, dtype=float).ravel()
    except (TypeError, ValueError):
        return None
    return values if values.size == size else None


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


class TravelTimeExplorer(Explorer):
    """E4: travel-time curves of your direct-wave and head-wave functions for a layered model you can change.

    model     : a shipped model name ('kim1983', 'kim2011') or a table with top_km, vp and vs
    direct    : your function direct(x_km, depth_km, model, phase) -> times, or None
    head      : your function head(x_km, depth_km, model, phase, interface) -> (times, critical_km,
                crossover_km), or None
    depth_km  : the source depth to start with
    phase     : 'P' or 'S'
    x_max_km  : the largest epicentral distance drawn
    n_points  : the number of distances at which your functions are called
    locate_km : the distance beyond which the band is shaded (arrivals not used to locate)
    """

    def __init__(self, model: Any = "kim1983", *, direct: Optional[Callable] = None,
                 head: Optional[Callable] = None, depth_km: float = 14.0, phase: str = "P",
                 x_max_km: float = 200.0, n_points: int = 81, locate_km: float = 100.0) -> None:
        tops, vp, vs, name = _layer_table(model)
        for label, func in (("direct", direct), ("head", head)):
            if func is not None and not callable(func):
                raise TypeError(f"{label} must be one of your functions (or None)")
        if phase not in ("P", "S"):
            raise ValueError("phase must be 'P' or 'S'")
        if not (x_max_km > 0 and int(n_points) >= 2):
            raise ValueError("x_max_km must be positive and n_points at least 2")
        super().__init__(10.5, 4.3)
        self.direct, self.head = direct, head
        self.name = name
        self._start = (list(tops), list(vp), list(vs))
        self.thick = [b - a for a, b in zip(tops, tops[1:])]
        self.vp, self.vs = list(vp), list(vs)
        self.x = np.linspace(0.0, float(x_max_km), int(n_points))
        self.locate_km = float(locate_km)

        w = self._widgets
        style = {"description_width": "initial"}
        self.layer_menu = w.Dropdown(options=self._layer_options(), value=0, description="Layer", style=style,
                                     layout=w.Layout(width="250px"))
        self.thick_slider = w.FloatSlider(min=0.5, max=40.0, step=0.5, description="Thickness (km)",
                                          continuous_update=False, style=style, layout=w.Layout(width="300px"))
        self.vp_slider = w.FloatSlider(min=2.0, max=9.5, step=0.01, description="Vp (km/s)",
                                       continuous_update=False, style=style, layout=w.Layout(width="300px"))
        self.vs_slider = w.FloatSlider(min=1.0, max=5.5, step=0.01, description="Vs (km/s)",
                                       continuous_update=False, style=style, layout=w.Layout(width="300px"))
        self.depth_slider = w.FloatSlider(min=0.5, max=60.0, step=0.5, value=float(depth_km),
                                          description="Source depth (km)", continuous_update=False, style=style,
                                          layout=w.Layout(width="330px"))
        self.phase_buttons = w.ToggleButtons(options=["P", "S"], value=phase, description="Phase", style=style)
        self.reduced_box = w.Checkbox(value=False, description="Reduced time", indent=False)
        self.reset_button = w.Button(description="Reset model", tooltip="Back to the model you started with")
        self._show_layer(0)
        self.layer_menu.observe(self._new_layer, names="value")
        for slider in (self.thick_slider, self.vp_slider, self.vs_slider):
            slider.observe(self._new_value, names="value")
        for control in (self.depth_slider, self.phase_buttons, self.reduced_box):
            control.observe(self._changed, names="value")
        self.reset_button.on_click(self._reset)
        self.box = w.VBox([w.HBox([self.layer_menu, self.thick_slider, self.reset_button]),
                           w.HBox([self.vp_slider, self.vs_slider]),
                           w.HBox([self.depth_slider, self.phase_buttons, self.reduced_box]),
                           self.image, self.status])
        self.redraw()

    # ---------------------------------------------------------------------------------------------- model
    def tops(self) -> List[float]:
        """Depths of the layer tops (km) of the current model."""
        out = [0.0]
        for h in self.thick:
            out.append(out[-1] + h)
        return out

    def model(self):
        """The current model as a new table (top_km, vp, vs), the one your functions receive."""
        import pandas as pd

        table = pd.DataFrame({"top_km": self.tops(), "vp": list(self.vp), "vs": list(self.vs)})
        table.attrs["name"] = self.name
        return table

    def _layer_options(self) -> list:
        tops = self.tops()
        rows = []
        for j, top in enumerate(tops):
            if j < len(tops) - 1:
                rows.append((f"Layer {j + 1}: {top:g}-{tops[j + 1]:g} km", j))
            else:
                rows.append((f"Half-space: from {top:g} km", j))
        return rows

    def _show_layer(self, j: int) -> None:
        with self.hold():
            last = j == len(self.vp) - 1
            self.thick_slider.disabled = last
            if not last:
                self.thick_slider.value = self.thick[j]
            self.vp_slider.value = self.vp[j]
            self.vs_slider.value = self.vs[j]

    def _new_layer(self, change: Any) -> None:
        self._show_layer(int(change["new"]))
        self.redraw()

    def _new_value(self, _change: Any = None) -> None:
        if self._held:
            return
        j = int(self.layer_menu.value)
        if j < len(self.thick):
            self.thick[j] = float(self.thick_slider.value)
        self.vp[j], self.vs[j] = float(self.vp_slider.value), float(self.vs_slider.value)
        with self.hold():
            self.layer_menu.options = self._layer_options()
            self.layer_menu.value = j
        self.redraw()

    def _reset(self, _button: Any = None) -> None:
        tops, vp, vs = self._start
        self.thick = [b - a for a, b in zip(tops, tops[1:])]
        self.vp, self.vs = list(vp), list(vs)
        with self.hold():
            self.layer_menu.options = self._layer_options()
            self.layer_menu.value = 0
        self._show_layer(0)
        self.redraw()

    # -------------------------------------------------------------------------------------------------- draw
    def _draw(self) -> None:
        depth, phase = float(self.depth_slider.value), self.phase_buttons.value
        reduced = bool(self.reduced_box.value)
        tops = self.tops()
        x = self.x
        notes: List[str] = []
        curves: List[Tuple[str, np.ndarray, Any]] = []        # (label, times, color)
        marks: List[Tuple[str, Optional[float], Optional[float], Any]] = []

        if self.direct is not None:
            name = func_name(self.direct, "direct")
            result, problem = call_yours(self.direct, name, x.copy(), depth, self.model(), phase)
            times = _times(result, x.size) if problem is None else None
            if problem is None and times is None:
                problem = f"your {name} did not return one time per distance"
            if problem:
                notes.append(problem + ".")
            else:
                curves.append((f"Direct {phase} (your {name})", times, "tab:blue"))
        else:
            notes.append("Pass direct=your direct-wave function to draw the direct wave.")

        below = [n for n, top in enumerate(tops) if n > 0 and top > depth]
        if self.head is not None:
            name = func_name(self.head, "head")
            for k, n in enumerate(below):
                result, problem = call_yours(self.head, name, x.copy(), depth, self.model(), phase, n)
                parts = None
                if problem is None:
                    if isinstance(result, tuple) and len(result) == 3:
                        times = _times(result[0], x.size)
                        parts = None if times is None else (times, _finite(result[1]), _finite(result[2]))
                    if parts is None:
                        problem = f"your {name} did not return (times, critical distance, crossover distance)"
                if problem:
                    notes.append(f"Boundary at {tops[n]:g} km: {problem}.")
                    continue
                times, crit, cross = parts
                color = LAYER_COLORS[k % len(LAYER_COLORS)]
                label = f"Head wave along {tops[n]:g} km"
                if np.isfinite(times).any():
                    curves.append((label, times, color))
                marks.append((label, crit, cross, color))
        elif below:
            notes.append("Pass head=your head-wave function to draw the head waves.")

        self._draw_figure(tops, depth, phase, reduced, curves, marks)
        first = self._first_at(curves)
        self.state = {"model": self.model(), "depth_km": depth, "phase": phase, "reduced": reduced,
                      "curves": {label: times for label, times, _ in curves},
                      "critical_km": {label: c for label, c, _, _ in marks},
                      "crossover_km": {label: c for label, _, c, _ in marks}, "first_at_locate_km": first}
        lines = [f"Source at {depth:g} km, phase {phase}; boundaries at "
                 + (", ".join(f"{t:g}" for t in tops[1:]) or "none") + " km."]
        for label, crit, cross, _ in marks:
            if crit is None:
                lines.append(f"{label}: your function finds no head wave here.")
            else:
                lines.append(f"{label}: critical distance {crit:.1f} km, crossover "
                             + (f"{cross:.1f} km" if cross is not None else "none") + " (your numbers).")
        if first:
            lines.append(f"Earliest of your curves at {self.locate_km:g} km: {first}.")
        self.status.value = status_html(lines + notes)

    def _first_at(self, curves: list) -> Optional[str]:
        """The label of the curve with the smallest time at the grid distance nearest to locate_km."""
        if not curves:
            return None
        k = int(np.abs(self.x - self.locate_km).argmin())
        best = None
        for label, times, _ in curves:
            if np.isfinite(times[k]) and (best is None or times[k] < best[1]):
                best = (label, float(times[k]))
        return None if best is None else best[0]

    def _draw_figure(self, tops: List[float], depth: float, phase: str, reduced: bool, curves: list,
                     marks: list) -> None:
        fig = self.figure
        ax_m, ax_t = fig.subplots(1, 2, width_ratios=[1, 2.6])
        bottom = max(tops[-1] + 15.0, depth + 10.0)
        edges = tops + [bottom]
        for speeds, color, label in ((self.vp, "tab:blue", "Vp"), (self.vs, "tab:red", "Vs")):
            xs_, ys_ = [], []
            for j, v in enumerate(speeds):
                xs_ += [v, v]
                ys_ += [edges[j], edges[j + 1]]
            ax_m.plot(xs_, ys_, color=color, lw=1.6, label=label)
        chosen = int(self.layer_menu.value)
        ax_m.axhspan(edges[chosen], edges[chosen + 1], color="0.9", zorder=0)
        for top in tops[1:]:
            ax_m.axhline(top, color="0.6", lw=0.6, ls=":")
        ax_m.plot([min(self.vs) - 0.3], [depth], marker="*", ms=12, color="gold", mec="k", ls="none",
                  label="Source")
        ax_m.set_ylim(bottom, 0.0)
        ax_m.set_xlim(min(self.vs) - 0.6, max(self.vp) + 0.6)
        ax_m.set_xlabel("Speed (km/s)")
        ax_m.set_ylabel("Depth (km)")
        ax_m.set_title("Model", fontsize=10)
        ax_m.legend(loc="lower left", fontsize=8, frameon=False)

        red = REDUCTION_KM_S[phase] if reduced else None
        x = self.x
        handles = []
        for label, times, color in curves:
            shown = times - x / red if red else times
            line, = ax_t.plot(x, shown, color=color, lw=1.6, label=label)
            self.lines[label] = line
            handles.append(line)
        for label, crit, cross, color in marks:
            if crit is not None:
                ax_t.axvline(crit, color=color, lw=0.8, ls=":")
            if cross is not None:
                ax_t.axvline(cross, color=color, lw=1.2, ls="--")
        ax_t.axvspan(self.locate_km, x[-1], color="0.92", lw=0, zorder=0)
        ax_t.text(0.99, 0.03, f"beyond {self.locate_km:g} km: not used to locate", transform=ax_t.transAxes,
                  ha="right", va="bottom", fontsize=8, color="0.35")
        ax_t.set_xlim(0.0, x[-1])
        ax_t.set_xlabel("Epicentral distance (km)")
        ax_t.set_ylabel(f"Time - distance / {red:g} km/s (s)" if red else "Travel time (s)")
        ax_t.set_title(f"{phase} travel times (dotted: critical, dashed: crossover distance)", fontsize=10)
        if not curves:
            ax_t.text(0.5, 0.5, "No curves: pass your functions", transform=ax_t.transAxes, ha="center",
                      va="center", color="0.4")
        if handles:
            fig.legend(handles=handles, loc="outside upper center", ncol=min(len(handles), 4), frameon=False,
                       fontsize=9)


def traveltime_explorer(model: Any = "kim1983", *, direct: Optional[Callable] = None,
                        head: Optional[Callable] = None, depth_km: float = 14.0, phase: str = "P",
                        x_max_km: float = 200.0, n_points: int = 81,
                        locate_km: float = 100.0) -> TravelTimeExplorer:
    """E4 explorer (see TravelTimeExplorer). Show it by making it the last line of a cell.

    Example (module M30, with your own functions)::

        st.widgets.traveltime_explorer("kim1983", direct=direct_time, head=head_wave, depth_km=14.0)
    """
    return TravelTimeExplorer(model, direct=direct, head=head, depth_km=depth_km, phase=phase,
                              x_max_km=x_max_km, n_points=n_points, locate_km=locate_km)
