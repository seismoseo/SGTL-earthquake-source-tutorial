"""E12 · Radiation explorer: your P, SV and SH radiation patterns in map view, for the fault you set.

The explorer draws all downward rays from the source on a disk seen from above (the lower hemisphere of M50: the
center is a ray straight down, the rim a horizontal ray, north up). Every position and every value it colors comes
from the functions you give it:

- ``project(takeoff_deg, azimuth_deg) -> (x, y)``: your ``equal_area`` of M50 (task 4); it places the grid of rays
  and the stations on the disk.
- ``radiation(strike_deg, dip_deg, rake_deg, takeoff_deg, azimuth_deg) -> (rp, rsv, rsh)``: your function of M52
  (``radiation_pattern``), called once per redraw with two 2-D arrays of takeoff angles and azimuths.

Four panels: R^P, R^SV, R^SH and the size of the whole S motion, sqrt(R^SV^2 + R^SH^2). A thin black line marks
where your R^P changes sign. Controls: strike, dip and rake, and a text box of station directions written as
``label azimuth takeoff; ...`` (degrees). A station whose ray goes upward (takeoff above 90) has an open marker;
where it lands is up to your ``project`` (M50 puts it at the opposite direction). The status line lists your three
values at each station and the largest sizes on the disk. Without ``project`` the explorer draws the empty disk
only; without ``radiation``, the disk and the stations.

Credit: Minseong Seo (SGTL, Seoul National University). License: MIT.
"""
from __future__ import annotations

import math
from typing import Any, Callable, List, Optional, Sequence, Tuple

import numpy as np

from ._common import Explorer, call_yours, func_name, status_html

_TITLES = ("P", "SV", "SH", "S size")


def _yours(result: Any, shape: Tuple[int, ...]) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Your result as three float arrays of the grid's shape, or None when it is not that."""
    if not isinstance(result, tuple) or len(result) != 3:
        return None
    out = []
    for part in result:
        try:
            arr = np.asarray(part, dtype=float)
        except (TypeError, ValueError):
            return None
        if arr.shape != shape:
            return None
        out.append(arr)
    return out[0], out[1], out[2]


def parse_stations(text: str) -> Tuple[List[Tuple[str, float, float]], List[str]]:
    """``"A 30 120; B 200 45"`` -> ([(label, azimuth, takeoff), ...], [problems]). Labels may be left out."""
    found, problems = [], []
    for k, part in enumerate(p.strip() for p in str(text).replace("\n", ";").split(";")):
        if not part:
            continue
        bits = part.replace(",", " ").split()
        try:
            if len(bits) == 3:
                label, az, take = bits[0], float(bits[1]), float(bits[2])
            elif len(bits) == 2:
                label, az, take = f"S{k + 1}", float(bits[0]), float(bits[1])
            else:
                raise ValueError
        except ValueError:
            problems.append(f"could not read '{part}' (write: label azimuth takeoff)")
            continue
        if not (0.0 <= take <= 180.0 and math.isfinite(az)):
            problems.append(f"'{part}': the takeoff angle must lie between 0 and 180 degrees")
            continue
        found.append((label, az % 360.0, take))
    return found, problems


def _two_arrays(result: Any, shape: Tuple[int, ...]) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """Your project result as two finite float arrays of the given shape, or None."""
    try:
        x, y = result
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
    except (TypeError, ValueError):
        return None
    if x.size != int(np.prod(shape)) or y.size != x.size:
        return None
    x, y = x.reshape(shape), y.reshape(shape)
    if not (np.all(np.isfinite(x)) and np.all(np.isfinite(y))):
        return None
    return x, y


class RadiationExplorer(Explorer):
    """E12: your radiation patterns on the lower hemisphere for the mechanism under the sliders.

    radiation : your function radiation(strike, dip, rake, takeoff_deg, azimuth_deg) -> (rp, rsv, rsh), or None
    project   : your equal_area of M50 (task 4): (takeoff_deg, azimuth_deg) -> (x, y), or None
    mechanism : (strike, dip, rake) in degrees to start with
    stations  : station directions to start with: a list of (label, azimuth_deg, takeoff_deg), or the text form
    n_takeoff, n_azimuth : grid size (rays from 0 to 90 degrees takeoff, all azimuths)
    """

    def __init__(self, *, radiation: Optional[Callable] = None, project: Optional[Callable] = None,
                 mechanism: Sequence[float] = (0.0, 90.0, 0.0), stations: Any = None, n_takeoff: int = 46,
                 n_azimuth: int = 121) -> None:
        if radiation is not None and not callable(radiation):
            raise TypeError("radiation must be your function radiation_pattern (or None)")
        if project is not None and not callable(project):
            raise TypeError("project must be your function equal_area of M50 (or None)")
        if len(mechanism) != 3:
            raise ValueError("mechanism must be (strike, dip, rake) in degrees")
        if not (n_takeoff >= 4 and n_azimuth >= 8):
            raise ValueError("the grid needs at least 4 takeoff angles and 8 azimuths")
        super().__init__(10.5, 3.6)
        self.radiation, self.project = radiation, project
        take = np.linspace(0.0, 90.0, int(n_takeoff))
        azim = np.linspace(0.0, 360.0, int(n_azimuth))
        self.take_grid, self.az_grid = np.meshgrid(take, azim)
        if stations is None:
            text = ""
        elif isinstance(stations, str):
            text = stations
        else:
            text = "; ".join(f"{label} {float(az):g} {float(tk):g}" for label, az, tk in stations)
        w = self._widgets
        style = {"description_width": "initial"}
        strike, dip, rake = (float(v) for v in mechanism)
        self.strike_slider = w.FloatSlider(min=0.0, max=360.0, step=1.0, value=strike % 360.0,
                                           description="Strike (deg)", continuous_update=False, style=style,
                                           layout=w.Layout(width="300px"))
        self.dip_slider = w.FloatSlider(min=0.0, max=90.0, step=1.0, value=min(max(dip, 0.0), 90.0),
                                        description="Dip (deg)", continuous_update=False, style=style,
                                        layout=w.Layout(width="260px"))
        self.rake_slider = w.FloatSlider(min=-180.0, max=180.0, step=1.0, value=min(max(rake, -180.0), 180.0),
                                         description="Rake (deg)", continuous_update=False, style=style,
                                         layout=w.Layout(width="300px"))
        self.stations_text = w.Text(value=text, description="Stations (label azimuth takeoff; ...)",
                                    continuous_update=False, style=style, layout=w.Layout(width="640px"))
        for control in (self.strike_slider, self.dip_slider, self.rake_slider, self.stations_text):
            control.observe(self._changed, names="value")
        self.box = w.VBox([w.HBox([self.strike_slider, self.dip_slider, self.rake_slider]), self.stations_text,
                           self.image, self.status])
        self.redraw()

    def mechanism(self) -> Tuple[float, float, float]:
        return float(self.strike_slider.value), float(self.dip_slider.value), float(self.rake_slider.value)

    def _place(self, takeoff: np.ndarray, azimuth: np.ndarray) -> Tuple[Optional[tuple], Optional[str]]:
        name = func_name(self.project, "equal_area")
        result, problem = call_yours(self.project, name, takeoff.copy(), azimuth.copy())
        if problem:
            return None, problem
        xy = _two_arrays(result, takeoff.shape)
        if xy is None:
            return None, f"your {name} did not return two arrays (x, y) of finite numbers, one per ray"
        return xy, None

    def _draw(self) -> None:
        mech = self.mechanism()
        stations, problems = parse_stations(self.stations_text.value)
        notes = list(problems)
        found = grid_xy = station_xy = None
        if self.project is None:
            notes.append("Pass project=your equal_area (M50, task 4) to place the rays on the disk.")
        else:
            grid_xy, error = self._place(self.take_grid, self.az_grid)
            if error:
                notes.append(error)
            elif stations:
                station_xy, error = self._place(np.array([tk for _, _, tk in stations], dtype=float),
                                                np.array([az for _, az, _ in stations], dtype=float))
                if error:
                    notes.append(error)
        if self.radiation is not None:
            label = func_name(self.radiation, "radiation_pattern")
            result, error = call_yours(self.radiation, label, *mech, self.take_grid.copy(), self.az_grid.copy())
            if error:
                notes.append(error)
            else:
                found = _yours(result, self.take_grid.shape)
                if found is None:
                    notes.append(f"your {label} did not return three arrays of the grid's shape "
                                 f"{self.take_grid.shape} (rp, rsv, rsh)")
        else:
            notes.append("Pass radiation=your radiation_pattern to see the patterns.")
        fig = self.figure
        axes = fig.subplots(1, 4)
        self.state = {"mechanism": mech, "stations": stations, "patterns": None, "at_stations": [],
                      "placed": grid_xy is not None}
        values = None
        if found is not None:
            rp, rsv, rsh = found
            values = (rp, rsv, rsh, np.hypot(rsv, rsh))
            self.state["patterns"] = values
        circle = np.linspace(0.0, 2.0 * math.pi, 361)
        for k, ax in enumerate(axes):
            if values is not None and grid_xy is not None:
                mesh = ax.pcolormesh(grid_xy[0], grid_xy[1], values[k], cmap="RdBu_r" if k < 3 else "Greys",
                                     vmin=-1.0 if k < 3 else 0.0, vmax=1.0, shading="gouraud")
                self.lines[_TITLES[k]] = mesh
                if np.nanmin(values[0]) < 0.0 < np.nanmax(values[0]):
                    ax.contour(grid_xy[0], grid_xy[1], values[0], levels=[0.0], colors="k", linewidths=0.6)
                ax.set_title(f"{_TITLES[k]}: largest |R| {np.nanmax(np.abs(values[k])):.2f}", fontsize=9)
            else:
                ax.set_title(_TITLES[k], fontsize=9)
            ax.plot(np.cos(circle), np.sin(circle), color="k", lw=0.8)
            ax.text(0.0, 1.06, "N", ha="center", va="bottom", fontsize=8)
            for j, (label, az, take) in enumerate(stations if station_xy is not None else []):
                x, y = float(station_xy[0][j]), float(station_xy[1][j])
                ax.plot(x, y, marker="^", ms=6, mec="k", mfc="none" if take > 90.0 else "gold", ls="none")
                if k == 0:
                    ax.text(x + 0.04, y + 0.04, label, fontsize=7)
            ax.set_xlim(-1.12, 1.12)
            ax.set_ylim(-1.12, 1.18)
            ax.set_aspect("equal")
            ax.set_axis_off()
        lines = [f"Mechanism: strike {mech[0]:g}, dip {mech[1]:g}, rake {mech[2]:g} degrees; lower hemisphere "
                 "on your net, north up. Open markers: upward rays."]
        if values is not None:
            lines.append("Largest sizes on the disk: " + ", ".join(
                f"|R^{name}| {np.nanmax(np.abs(v)):.3f}" for name, v in zip(("P", "SV", "SH"), values[:3])))
            for label, az, take in stations:
                result, error = call_yours(self.radiation, "radiation_pattern", *mech, float(take), float(az))
                one = None
                if not error and isinstance(result, tuple) and len(result) == 3:
                    try:
                        one = [float(np.asarray(v, dtype=float).reshape(())) for v in result]
                    except (TypeError, ValueError):
                        one = None
                if one is None:
                    lines.append(f"{label}: your function gave no three numbers for one ray")
                    continue
                rp1, rsv1, rsh1 = (float(v) for v in one)
                self.state["at_stations"].append((label, rp1, rsv1, rsh1))
                lines.append(f"{label} (azimuth {az:g}, takeoff {take:g}): R^P {rp1:+.3f}, R^SV {rsv1:+.3f}, "
                             f"R^SH {rsh1:+.3f}")
        self.status.value = status_html(lines + notes)


def radiation_explorer(*, radiation: Optional[Callable] = None, project: Optional[Callable] = None,
                       mechanism: Sequence[float] = (0.0, 90.0, 0.0), stations: Any = None, n_takeoff: int = 46,
                       n_azimuth: int = 121) -> RadiationExplorer:
    """E12 explorer (see RadiationExplorer). Show it by making it the last line of a cell.

    Example (module M52, with your own function)::

        radiation_explorer(radiation=radiation_pattern, project=equal_area, mechanism=(10.0, 60.0, -30.0),
                           stations="A 45 100")
    """
    return RadiationExplorer(radiation=radiation, project=project, mechanism=mechanism, stations=stations,
                             n_takeoff=n_takeoff, n_azimuth=n_azimuth)
