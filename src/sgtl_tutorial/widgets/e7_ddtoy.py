"""E7 · Double-difference toy: how errors of the data move absolute and relative positions.

A toy cluster of earthquakes on a small fault patch, 10 km deep, and a ring of stations around it. The explorer
never computes a travel time or a derivative itself; it takes them from your functions of M41:

- ``system(events_km, stations_km, obs, vp, vs) -> (G, d)``: your ``dd_system``. Called with every observed time set
  to 0, its d is minus the predicted differential times, which gives the error-free data; and the columns of one
  event hold the partial derivatives of that event's travel times;
- ``solve(G, d, damp) -> m``: your ``dd_solve``;
- ``relocate(events_km, stations_km, obs, vp, vs, damp, n_iter, system, solve) -> (positions, shifts, rms)``: your
  ``relocate``, called with your system and solver.

The errors you choose: a **pick error** (an independent random error of every P and S pick), a **station delay**
(one error per station, the same for every event, as from a velocity model that is wrong under that station) and,
for the differential times, either the pick errors (catalog times) or a small cross-correlation error.

- **Absolute positions**: for each event alone, one linearized least-squares step from its true position with its
  own travel-time errors (pick errors plus station delays) and the derivatives of your system: the move an absolute
  locator would make for such errors.
- **Relative positions**: your ``relocate`` from the absolute positions, on the differential times of every pair at
  every station (station delays cancel in them), with the centroid held fixed by your solver.

Credit: Minseong Seo (SGTL, Seoul National University). License: MIT.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional

import numpy as np

from ._common import Explorer, call_yours, func_name, status_html

VP, VS = 6.0, 3.47              # km/s of the toy medium
DEPTH_KM = 10.0
N_EVENTS = 6


def _shape_rms_m(xyz: np.ndarray, truth: np.ndarray) -> float:
    """RMS distance (m) between two sets of positions after removing each set's centroid."""
    diff = (xyz - xyz.mean(axis=0)) - (truth - truth.mean(axis=0))
    return 1000.0 * float(np.sqrt(np.mean(np.sum(diff ** 2, axis=1))))


class DDToy(Explorer):
    """E7: true, absolute and relative positions of a toy cluster under errors you choose.

    system, solve, relocate : your dd_system, dd_solve and relocate of M41 (None: only the true cluster is shown)
    n_stations : number of stations to start with (3-12)
    pick_ms    : pick error to start with (standard deviation, ms)
    delay_ms   : station delay to start with (standard deviation, ms)
    cc_ms      : error of a cross-correlation differential time (standard deviation, ms)
    n_iter     : rounds of your relocate
    seed       : seed of the first error draw
    """

    def __init__(self, *, system: Optional[Callable] = None, solve: Optional[Callable] = None,
                 relocate: Optional[Callable] = None, n_stations: int = 6, pick_ms: float = 30.0,
                 delay_ms: float = 80.0, cc_ms: float = 1.0, n_iter: int = 4, seed: int = 7) -> None:
        for label, func in (("system", system), ("solve", solve), ("relocate", relocate)):
            if func is not None and not callable(func):
                raise TypeError(f"{label} must be one of your functions (or None)")
        if not 3 <= int(n_stations) <= 12:
            raise ValueError("n_stations must be 3 to 12")
        super().__init__(11.0, 4.4)
        self.system, self.solve, self.relocate = system, solve, relocate
        self.seed = int(seed)
        self.cc_ms = float(cc_ms)
        self.n_iter = int(n_iter)
        layout = np.random.default_rng(4100)
        along = np.linspace(-0.45, 0.45, N_EVENTS) + layout.normal(0.0, 0.05, N_EVENTS)
        down = layout.uniform(-0.35, 0.35, N_EVENTS)
        strike = math.radians(35.0)                       # a vertical patch striking N35E
        self.truth = np.column_stack([along * math.sin(strike), along * math.cos(strike), DEPTH_KM + down])
        w = self._widgets
        style = {"description_width": "initial"}
        self.stations_slider = w.IntSlider(min=3, max=12, step=1, value=int(n_stations), description="Stations",
                                           continuous_update=False, style=style, layout=w.Layout(width="260px"))
        self.pick_slider = w.FloatSlider(min=0.0, max=100.0, step=1.0, value=float(pick_ms),
                                         description="Pick error (ms)", continuous_update=False, style=style,
                                         layout=w.Layout(width="300px"))
        self.delay_slider = w.FloatSlider(min=0.0, max=200.0, step=5.0, value=float(delay_ms),
                                          description="Station delay (ms)", continuous_update=False, style=style,
                                          layout=w.Layout(width="300px"))
        self.data_buttons = w.ToggleButtons(options=["Catalog times", "Cross-correlation times"],
                                            value="Catalog times", description="Differential times", style=style)
        self.error_button = w.Button(description="New errors", tooltip="Draw new random errors")
        for control in (self.stations_slider, self.pick_slider, self.delay_slider, self.data_buttons):
            control.observe(self._changed, names="value")
        self.error_button.on_click(self._new_errors)
        self.box = w.VBox([w.HBox([self.stations_slider, self.pick_slider, self.delay_slider]),
                           w.HBox([self.data_buttons, self.error_button]), self.image, self.status])
        self.redraw()

    def _new_errors(self, _button: Any = None) -> None:
        self.seed += 1
        self.redraw()

    def stations(self) -> np.ndarray:
        """The station positions (km; x east, y north, z down) for the current number of stations."""
        n = int(self.stations_slider.value)
        az = np.radians(20.0 + 360.0 * np.arange(n) / n)
        dist = 12.0 + 18.0 * ((np.arange(n) * 7) % n) / max(n - 1, 1)
        return np.column_stack([dist * np.sin(az), dist * np.cos(az), np.zeros(n)])

    def _table(self, pairs: List[tuple], n_sta: int):
        import pandas as pd

        rows = [{"ev1": i, "ev2": j, "sta": k, "phase": ph, "dt_s": 0.0}
                for (i, j) in pairs for k in range(n_sta) for ph in ("P", "S")]
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------------------------------------ draw
    def _draw(self) -> None:
        stations = self.stations()
        n_sta = len(stations)
        rng = np.random.default_rng(self.seed)
        pick = rng.normal(0.0, float(self.pick_slider.value) / 1000.0, (N_EVENTS, n_sta, 2))
        delay = rng.normal(0.0, float(self.delay_slider.value) / 1000.0, (n_sta, 2))
        errors = pick + delay[None, :, :]                 # error of each travel time: event, station, P/S
        notes: List[str] = []
        absolute = relative = None
        if None in (self.system, self.solve, self.relocate):
            notes.append("Pass system=your dd_system, solve=your dd_solve and relocate=your relocate to see the "
                         "absolute and relative positions.")
        else:
            absolute, relative, problem = self._positions(stations, errors, rng)
            if problem:
                notes.append(problem + ".")
        self._draw_figure(stations, absolute, relative)
        self.state = {"truth_km": self.truth, "stations_km": stations, "absolute_km": absolute,
                      "relative_km": relative}
        lines = [f"{N_EVENTS} events on a 1-km patch at {DEPTH_KM:g} km; {n_sta} stations at 12-30 km; pick error "
                 f"{self.pick_slider.value:g} ms, station delay {self.delay_slider.value:g} ms; differential times: "
                 f"{self.data_buttons.value.lower()}."]
        if absolute is not None:
            for label, xyz in (("absolute", absolute), ("relative (yours)", relative)):
                if xyz is None:
                    continue
                centroid = 1000.0 * np.linalg.norm(xyz.mean(axis=0) - self.truth.mean(axis=0))
                shape = _shape_rms_m(xyz, self.truth)
                self.state[f"{label.split()[0]}_centroid_m"] = centroid
                self.state[f"{label.split()[0]}_shape_m"] = shape
                lines.append(f"{label}: centroid {centroid:.0f} m from the true centroid; shape error {shape:.0f} m "
                             "(RMS after removing each centroid).")
        self.status.value = status_html(lines + notes)

    def _positions(self, stations: np.ndarray, errors: np.ndarray, rng: np.random.Generator):
        """(absolute positions, relative positions, problem text) from your three functions."""
        n_sta = len(stations)
        phase_col = {"P": 0, "S": 1}
        # absolute: one event against a far reference event; its own columns are the derivatives of its times
        far = np.vstack([self.truth, [[200.0, 200.0, DEPTH_KM]]])
        absolute = self.truth.copy()
        name = func_name(self.system, "system")
        for i in range(N_EVENTS):
            table = self._table([(i, N_EVENTS)], n_sta)
            result, problem = call_yours(self.system, name, far.copy(), stations.copy(), table, VP, VS)
            if problem is not None:
                return None, None, problem
            try:
                rows = np.asarray(result[0], dtype=float)[:, 4 * i:4 * i + 4]
            except (TypeError, ValueError, IndexError):
                return None, None, f"your {name} did not return (G, d)"
            e = np.array([errors[i, k, phase_col[ph]] for k, ph in zip(table["sta"], table["phase"])])
            step = np.linalg.lstsq(rows, e, rcond=None)[0]
            absolute[i] = self.truth[i] + step[:3]
        # relative: error-free differential times from your system, plus the chosen errors
        pairs = [(i, j) for i in range(N_EVENTS) for j in range(i + 1, N_EVENTS)]
        table = self._table(pairs, n_sta)
        result, problem = call_yours(self.system, name, self.truth.copy(), stations.copy(), table, VP, VS)
        if problem is not None:
            return absolute, None, problem
        exact = -np.asarray(result[1], dtype=float)
        if self.data_buttons.value == "Catalog times":
            noise = np.array([errors[i, k, phase_col[ph]] - errors[j, k, phase_col[ph]]
                              for i, j, k, ph in zip(table["ev1"], table["ev2"], table["sta"], table["phase"])])
        else:
            noise = rng.normal(0.0, self.cc_ms / 1000.0, len(table))
        observed = table.assign(dt_s=exact + noise)
        rname = func_name(self.relocate, "relocate")
        result, problem = call_yours(self.relocate, rname, absolute.copy(), stations.copy(), observed, VP, VS, 0.0,
                                     self.n_iter, self.system, self.solve)
        if problem is not None:
            return absolute, None, problem
        try:
            relative = np.asarray(result[0], dtype=float).reshape(N_EVENTS, 3)
        except (TypeError, ValueError, IndexError):
            return absolute, None, f"your {rname} did not return (positions, shifts, rms)"
        return absolute, relative, None

    def _draw_figure(self, stations: np.ndarray, absolute: Optional[np.ndarray],
                     relative: Optional[np.ndarray]) -> None:
        fig = self.figure
        ax_s, ax_m, ax_d = fig.subplots(1, 3, width_ratios=[0.55, 1.0, 1.25])
        ax_s.plot(stations[:, 0], stations[:, 1], "v", color="tab:green", ms=6, ls="none")
        ax_s.plot([0.0], [0.0], "*", color="k", ms=9, ls="none")
        ax_s.set_aspect("equal", adjustable="datalim")
        ax_s.set_xlabel("East (km)")
        ax_s.set_ylabel("North (km)")
        ax_s.set_title("Stations and cluster", fontsize=10)
        sets: Dict[str, tuple] = {"True": (self.truth, "o", "k"), "Absolute": (absolute, "s", "0.55"),
                                  "Relative (yours)": (relative, "^", "tab:blue")}
        center = self.truth.mean(axis=0)
        for label, (xyz, marker, color) in sets.items():
            if xyz is None:
                continue
            m = 1000.0 * (xyz - center)
            line, = ax_m.plot(m[:, 0], m[:, 1], marker, color=color, ms=7, mfc="none" if label != "True" else color,
                              ls="none", label=label)
            ax_d.plot(m[:, 0], m[:, 2], marker, color=color, ms=7, mfc="none" if label != "True" else color,
                      ls="none")
            self.lines[label] = line
        ax_m.set_aspect("equal", adjustable="datalim")
        ax_m.set_xlabel("East of the true centroid (m)")
        ax_m.set_ylabel("North of the true centroid (m)")
        ax_m.set_title("Map view", fontsize=10)
        ax_d.invert_yaxis()
        ax_d.set_xlabel("East of the true centroid (m)")
        ax_d.set_ylabel("Below the true centroid (m)")
        ax_d.set_title("Depth section, looking north", fontsize=10)
        handles, labels = ax_m.get_legend_handles_labels()
        if handles:
            fig.legend(handles, labels, loc="outside upper center", ncol=3, frameon=False, fontsize=9)


def dd_toy(*, system: Optional[Callable] = None, solve: Optional[Callable] = None,
           relocate: Optional[Callable] = None, n_stations: int = 6, pick_ms: float = 30.0, delay_ms: float = 80.0,
           cc_ms: float = 1.0, n_iter: int = 4, seed: int = 7) -> DDToy:
    """E7 explorer (see DDToy). Show it by making it the last line of a cell.

    Example (module M41, with your own functions)::

        st.widgets.dd_toy(system=dd_system, solve=dd_solve, relocate=relocate)
    """
    return DDToy(system=system, solve=solve, relocate=relocate, n_stations=n_stations, pick_ms=pick_ms,
                 delay_ms=delay_ms, cc_ms=cc_ms, n_iter=n_iter, seed=seed)
