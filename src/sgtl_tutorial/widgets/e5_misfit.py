"""E5 · Misfit explorer: the RMS of your own grid search in map view and in a depth section, and a Wadati inset.

The explorer computes no misfit and fits no line by itself. It hands the picks you keep to the functions you give
it and draws what they return:

- ``grid_search(obs, tt, xs, ys, zs) -> {"rms": array (nx, ny, nz), "t0": array (nx, ny, nz), "x_km", "y_km",
  "z_km", "t0_s", "rms_s"}``: your grid search of M31 (task 1). Every redraw calls it twice: on a map-view slice
  (all xs and ys at the depth you choose) and on a depth section (all xs, or all ys, along the line you choose, at
  every depth);
- ``wadati(tp_s, ts_s) -> (t0_s, vp_vs)``: your Wadati fit of M30 (optional): the straight line in the inset, which
  shows the S-P time of every station that has both picks against its P time.

The controls choose the depth of the map view, the direction (east-west or north-south) and position of the section
line, and stations to leave out (their picks are not handed to your functions). The status line reports the best
node of each slice as your function returned it, and the origin time your function chose there next to the origin
time of your Wadati line. Without ``grid_search`` you see the stations and the Wadati points only.

Credit: Minseong Seo (SGTL, Seoul National University). License: MIT.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ._common import Explorer, call_yours, func_name, status_html

COLUMNS = ("station", "phase", "x_km", "y_km", "t_s")
MIN_PICKS = 5


def _table(obs: Any) -> Any:
    """obs as a DataFrame with the columns of COLUMNS (a copy), or a ValueError that says what is missing."""
    import pandas as pd

    if not isinstance(obs, pd.DataFrame):
        raise ValueError("obs must be a pandas DataFrame with the columns " + ", ".join(COLUMNS))
    missing = [c for c in COLUMNS if c not in obs.columns]
    if missing:
        raise ValueError("obs needs the columns " + ", ".join(COLUMNS) + "; missing: " + ", ".join(missing))
    return obs.reset_index(drop=True).copy()


def _slice(result: Any, shape: Tuple[int, int, int]) -> Optional[Tuple[np.ndarray, np.ndarray, dict]]:
    """(rms cube, t0 cube, best) from your grid_search's dict, or None when it is not of the asked shape."""
    if not isinstance(result, dict):
        return None
    try:
        rms = np.asarray(result["rms"], dtype=float)
        t0 = np.asarray(result["t0"], dtype=float)
        best = {key: float(result[key]) for key in ("x_km", "y_km", "z_km", "t0_s", "rms_s")}
    except (KeyError, TypeError, ValueError):
        return None
    if rms.shape != shape or t0.shape != shape:
        return None
    return rms, t0, best


class MisfitExplorer(Explorer):
    """E5: map view and depth section of the RMS from your grid_search, with a Wadati inset.

    obs          : table with station, phase ("P"/"S"), x_km, y_km (station, km east and north) and t_s (s)
    tt           : the travel-time function handed to your grid_search, tt(distance_km, depth_km, phase)
    grid_search  : your function of M31 (task 1), or None
    wadati       : your wadati_fit of M30, or None
    marks        : {label: (x_km, y_km, z_km)} points to mark, for example a catalog hypocenter
    half_km      : the slices reach this far east, west, north and south of center (km)
    step_km      : node spacing of the slices (km)
    depths       : depths of the section and of the depth control (km); default 0.5, 1.5, ..., 29.5
    depth_km     : the depth of the map view to start with (the nearest of depths)
    center       : (x_km, y_km) of the middle of the slices
    """

    def __init__(self, obs: Any, tt: Callable, *, grid_search: Optional[Callable] = None,
                 wadati: Optional[Callable] = None, marks: Optional[Dict[str, Sequence[float]]] = None,
                 half_km: float = 20.0, step_km: float = 1.0, depths: Optional[Sequence[float]] = None,
                 depth_km: Optional[float] = None, center: Sequence[float] = (0.0, 0.0)) -> None:
        self.obs = _table(obs)
        if not callable(tt):
            raise TypeError("tt must be a travel-time function tt(distance_km, depth_km, phase)")
        for label, func in (("grid_search", grid_search), ("wadati", wadati)):
            if func is not None and not callable(func):
                raise TypeError(f"{label} must be one of your functions (or None)")
        if not (half_km > 0 and step_km > 0 and half_km / step_km <= 200):
            raise ValueError("half_km and step_km must be positive, with at most 200 steps per side")
        super().__init__(11.5, 4.6)
        self.tt, self.grid_search, self.wadati = tt, grid_search, wadati
        self.marks = {str(k): tuple(float(v) for v in xyz) for k, xyz in (marks or {}).items()}
        self.center = (float(center[0]), float(center[1]))
        offsets = np.arange(-float(half_km), float(half_km) + 0.5 * float(step_km), float(step_km))
        self.xs = self.center[0] + offsets
        self.ys = self.center[1] + offsets
        self.depths = np.asarray(np.arange(0.5, 30.01, 1.0) if depths is None else depths, dtype=float)
        if self.depths.ndim != 1 or self.depths.size < 2:
            raise ValueError("depths must be a 1-D sequence of at least two depths (km)")
        start = float(self.depths[len(self.depths) // 2] if depth_km is None else depth_km)
        nearest = float(min(self.depths, key=lambda z: abs(float(z) - start)))
        first = self.obs.groupby("station", sort=False)["t_s"].min().sort_values(kind="stable")
        self.station_order = [str(s) for s in first.index]          # earliest pick first: nearest stations first

        w = self._widgets
        style = {"description_width": "initial"}
        self.depth_slider = w.SelectionSlider(options=[(f"{z:g}", float(z)) for z in self.depths], value=nearest,
                                              description="Map depth (km)", continuous_update=False, style=style,
                                              layout=w.Layout(width="330px"))
        self.section_buttons = w.ToggleButtons(options=["East-west", "North-south"], value="East-west",
                                               description="Section", style=style)
        self.line_slider = w.FloatSlider(min=-float(half_km), max=float(half_km), step=float(step_km), value=0.0,
                                         description="Section line (km from center)", continuous_update=False,
                                         style=style, layout=w.Layout(width="380px"))
        self.leave_out = w.SelectMultiple(options=self.station_order, value=(), rows=min(8, len(self.station_order)),
                                          description="Leave out", style=style, layout=w.Layout(width="230px"))
        for control in (self.depth_slider, self.section_buttons, self.line_slider, self.leave_out):
            control.observe(self._changed, names="value")
        self.box = w.VBox([w.HBox([self.depth_slider, self.section_buttons]),
                           w.HBox([self.line_slider]),
                           w.HBox([self.leave_out, self.status]), self.image])
        self.redraw()

    # ----------------------------------------------------------------------------------------------- data
    def kept(self) -> Any:
        """The picks handed to your functions: obs without the stations left out (a copy)."""
        out = self.obs[~self.obs["station"].isin(list(self.leave_out.value))]
        return out.reset_index(drop=True).copy()

    def _section_axes(self) -> Tuple[str, float, np.ndarray, np.ndarray, np.ndarray]:
        """(direction, line position, xs, ys of the section call, positions along the section)."""
        line = float(self.line_slider.value)
        if self.section_buttons.value == "East-west":
            at = self.center[1] + line
            return "east-west", at, self.xs.copy(), np.array([at]), self.xs
        at = self.center[0] + line
        return "north-south", at, np.array([at]), self.ys.copy(), self.ys

    # -------------------------------------------------------------------------------------------------- draw
    def _draw(self) -> None:
        picks = self.kept()
        depth = float(self.depth_slider.value)
        direction, at, sec_xs, sec_ys, along = self._section_axes()
        notes: List[str] = []
        state: Dict[str, Any] = {"picks": len(picks), "left_out": list(self.leave_out.value), "depth_km": depth,
                                 "section": direction, "line_km": at, "map": None, "section_rms": None,
                                 "best_map": None, "best_section": None, "wadati": None}
        name = func_name(self.grid_search, "grid_search")
        if self.grid_search is None:
            notes.append("Pass grid_search=your grid search (task 1) to see the misfit.")
        elif len(picks) < MIN_PICKS:
            notes.append(f"Only {len(picks)} picks left: keep at least {MIN_PICKS} to locate.")
        else:
            result, problem = call_yours(self.grid_search, name, picks.copy(), self.tt, self.xs.copy(),
                                         self.ys.copy(), np.array([depth]))
            parts = None if problem else _slice(result, (self.xs.size, self.ys.size, 1))
            if problem or parts is None:
                notes.append((problem or f"your {name} did not return the dict of its Contract for the map view")
                             + ".")
            else:
                state["map"] = parts[0][:, :, 0]
                state["best_map"] = parts[2]
            result, problem = call_yours(self.grid_search, name, picks.copy(), self.tt, sec_xs, sec_ys,
                                         self.depths.copy())
            parts = None if problem else _slice(result, (sec_xs.size, sec_ys.size, self.depths.size))
            if problem or parts is None:
                notes.append((problem or f"your {name} did not return the dict of its Contract for the section")
                             + ".")
            else:
                state["section_rms"] = parts[0][:, 0, :] if direction == "east-west" else parts[0][0, :, :]
                state["best_section"] = parts[2]
        state["wadati"] = self._wadati_points(picks, notes)
        self.state = state
        self._draw_figure(picks, state, direction, at, along)
        self.status.value = status_html(self._status_lines(state, name) + notes)

    def _wadati_points(self, picks: Any, notes: List[str]) -> dict:
        both = picks.pivot_table(index="station", columns="phase", values="t_s", aggfunc="min")
        out: Dict[str, Any] = {"tp": np.array([]), "ts": np.array([]), "fit": None}
        if "P" in both.columns and "S" in both.columns:
            both = both.dropna(subset=["P", "S"])
            out["tp"], out["ts"] = both["P"].to_numpy(float), both["S"].to_numpy(float)
        if self.wadati is not None and out["tp"].size >= 2:
            label = func_name(self.wadati, "wadati")
            result, problem = call_yours(self.wadati, label, out["tp"].copy(), out["ts"].copy())
            fit = None
            if problem is None and isinstance(result, tuple) and len(result) == 2:
                try:
                    fit = (float(result[0]), float(result[1]))
                except (TypeError, ValueError):
                    fit = None
            if fit is None or not all(math.isfinite(v) for v in fit):
                notes.append((problem or f"your {label} did not return (t0_s, vp_vs)") + ".")
            else:
                out["fit"] = fit
        return out

    def _status_lines(self, state: dict, name: str) -> List[str]:
        lines = [f"{state['picks']} picks handed to your functions"
                 + (f" (left out: {', '.join(state['left_out'])})" if state["left_out"] else "") + "."]
        best = state["best_map"]
        if best is not None:
            lines.append(f"Map view at {state['depth_km']:g} km, best node of your {name}: east {best['x_km']:g}, "
                         f"north {best['y_km']:g} km, origin time {best['t0_s']:.3f} s, RMS {best['rms_s']:.3f} s.")
        best = state["best_section"]
        if best is not None:
            lines.append(f"Section ({state['section']}, line at {state['line_km']:g} km), best node: depth "
                         f"{best['z_km']:g} km, origin time {best['t0_s']:.3f} s, RMS {best['rms_s']:.3f} s.")
        fit = state["wadati"]["fit"] if state["wadati"] else None
        if fit is not None:
            lines.append(f"Your Wadati line: origin time {fit[0]:.3f} s, Vp/Vs {fit[1]:.3f}.")
        return lines

    def _draw_figure(self, picks: Any, state: dict, direction: str, at: float, along: np.ndarray) -> None:
        fig = self.figure
        ax_m, ax_s, ax_w = fig.subplots(1, 3, width_ratios=[1.0, 1.25, 0.75])
        left_out = set(self.leave_out.value)
        stations = self.obs.drop_duplicates("station")
        kept = ~stations["station"].isin(left_out).to_numpy()
        sx, sy = stations["x_km"].to_numpy(float), stations["y_km"].to_numpy(float)
        cmap = "viridis"
        levels = self._levels([g for g in (state["map"], state["section_rms"]) if g is not None])
        if state["map"] is not None:
            grid = state["map"]
            filled = ax_m.contourf(self.xs, self.ys, grid.T, levels=levels, cmap=cmap, extend="max")
            self.lines["map"] = filled
            best = state["best_map"]
            ax_m.plot(best["x_km"], best["y_km"], "o", color="tab:red", mec="w", ms=7, label="Best node")
        ax_m.plot(sx[kept], sy[kept], "^", color="w", mec="k", ms=7, label="Stations")
        if (~kept).any():
            ax_m.plot(sx[~kept], sy[~kept], "^", color="0.6", mec="0.4", ms=7, label="Left out")
        if direction == "east-west":
            ax_m.axhline(at, color="w", lw=1.0, ls="--")
        else:
            ax_m.axvline(at, color="w", lw=1.0, ls="--")
        for label, (mx, my, _) in self.marks.items():
            ax_m.plot(mx, my, "x", color="k", ms=9, mew=2.0, label=label)
        ax_m.set_xlim(self.xs[0], self.xs[-1])
        ax_m.set_ylim(self.ys[0], self.ys[-1])
        ax_m.set_aspect("equal")
        ax_m.set_xlabel("East (km)")
        ax_m.set_ylabel("North (km)")
        ax_m.set_title(f"(a) Map view at {state['depth_km']:g} km", fontsize=10, loc="left")

        if state["section_rms"] is not None:
            grid = state["section_rms"]
            filled = ax_s.contourf(along, self.depths, grid.T, levels=levels, cmap=cmap, extend="max")
            self.lines["section"] = filled
            fig.colorbar(filled, ax=ax_s, label="RMS residual (s)", format="%.2f")
            best = state["best_section"]
            ax_s.plot(best["x_km"] if direction == "east-west" else best["y_km"], best["z_km"], "o",
                      color="tab:red", mec="w", ms=7)
        for label, (mx, my, mz) in self.marks.items():
            ax_s.plot(mx if direction == "east-west" else my, mz, "x", color="k", ms=9, mew=2.0)
        ax_s.axhline(state["depth_km"], color="w", lw=0.8, ls=":")
        ax_s.set_xlim(along[0], along[-1])
        ax_s.set_ylim(self.depths[-1], 0.0)
        ax_s.set_xlabel("East (km)" if direction == "east-west" else "North (km)")
        ax_s.set_ylabel("Depth (km)")
        where = "north" if direction == "east-west" else "east"
        ax_s.set_title(f"(b) {direction.capitalize()} section at {at:g} km {where}", fontsize=10, loc="left")

        wad = state["wadati"]
        ax_w.plot(wad["tp"], wad["ts"] - wad["tp"], "o", color="tab:blue", ms=4, label="Stations with P and S")
        if wad["fit"] is not None and wad["tp"].size:
            t0, ratio = wad["fit"]
            line_x = np.array([min(t0, float(wad["tp"].min())), float(wad["tp"].max())])
            ax_w.plot(line_x, (ratio - 1.0) * (line_x - t0), color="k", lw=1.0, label="Your Wadati line")
        best = state["best_map"]
        if best is not None:
            ax_w.axvline(best["t0_s"], color="tab:red", lw=1.0, ls="--", label="Origin time, best node of (a)")
        ax_w.set_xlabel("P time (s)")
        ax_w.set_ylabel("S-P time (s)")
        ax_w.set_title("(c) Wadati", fontsize=10, loc="left")
        handles, labels = [], []
        for ax in (ax_m, ax_w):
            h, lab = ax.get_legend_handles_labels()
            handles += h
            labels += lab
        if handles:
            fig.legend(handles, labels, loc="outside upper center", ncol=min(len(handles), 6), frameon=False,
                       fontsize=8)
        if self.grid_search is None:
            ax_s.text(0.5, 0.5, "No misfit: pass your grid_search", transform=ax_s.transAxes, ha="center",
                      va="center", color="0.4")

    @staticmethod
    def _levels(grids: List[np.ndarray]) -> np.ndarray:
        """Shared color levels for the slices: from their smallest RMS (rounded down to 0.01 s) up by at most 1 s."""
        finite = np.concatenate([g[np.isfinite(g)].ravel() for g in grids]) if grids else np.array([])
        if finite.size == 0:
            return np.linspace(0.0, 1.0, 11)
        low = math.floor(float(finite.min()) * 100.0) / 100.0
        top = low + min(1.0, max(3.0 * (float(np.median(finite)) - low), 0.05))
        return np.linspace(low, top, 21)


def misfit_explorer(obs: Any, tt: Callable, *, grid_search: Optional[Callable] = None,
                    wadati: Optional[Callable] = None, marks: Optional[Dict[str, Sequence[float]]] = None,
                    half_km: float = 20.0, step_km: float = 1.0, depths: Optional[Sequence[float]] = None,
                    depth_km: Optional[float] = None, center: Sequence[float] = (0.0, 0.0)) -> MisfitExplorer:
    """E5 explorer (see MisfitExplorer). Show it by making it the last line of a cell.

    Example (module M31, with your own functions)::

        st.widgets.misfit_explorer(obs_main, tt_main, grid_search=grid_search, wadati=wadati_fit)
    """
    return MisfitExplorer(obs, tt, grid_search=grid_search, wadati=wadati, marks=marks, half_km=half_km,
                          step_km=step_km, depths=depths, depth_km=depth_km, center=center)
