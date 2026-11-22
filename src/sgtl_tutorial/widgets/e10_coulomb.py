"""E10 · Coulomb explorer: your stress change around a slipping rectangle, resolved on receivers you choose.

The explorer draws a map at one depth around a source fault. Every value it colors comes from the two functions
you give it; it computes no stress and resolves nothing itself:

- ``stress(fault, points_km, lame1_pa, mu_pa) -> (n, 3, 3)``: your ``okada_stress`` of M54 (task 3), called with
  the source under the sliders (your source dict with its rake and slip replaced) and a grid of points (east,
  north, depth in km) centred on the source;
- ``resolve(stress_enu_pa, strike, dip, rake, friction, skempton) -> (shear_kpa, normal_kpa, coulomb_kpa)``: your
  ``coulomb_change`` of M54 (task 1), called with that stress and the receiver, friction and Skempton coefficient
  under the sliders.

Three panels: your shear, normal and Coulomb changes (kPa), with one color limit for all three (values beyond it
are drawn at the limit). A black line marks the source's strike through its centre. The stress is asked again only
when the source's rake, its slip or the map depth changes; moving a receiver or friction slider only resolves
again. The status line gives the largest and smallest values and the share of grid cells above zero, all from
your functions. Without ``stress`` the explorer draws the empty map; without ``resolve``, it says what is missing.

Credit: Minseong Seo (SGTL, Seoul National University). License: MIT.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

import numpy as np

from ._common import Explorer, call_yours, func_name, status_html

_PANELS = ("Shear", "Normal", "Coulomb")
_NEEDED = ("strike", "dip", "rake", "length_km", "width_km", "east_km", "north_km", "depth_km", "slip_m")


def _tensors(result: Any, n: int) -> Optional[np.ndarray]:
    """Your stress as an (n, 3, 3) float array, or None when it is not that shape."""
    try:
        arr = np.asarray(result, dtype=float)
    except (TypeError, ValueError):
        return None
    return arr if arr.shape == (n, 3, 3) else None


def _triple(result: Any, n: int) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Your (shear, normal, coulomb) as three float arrays of length n, or None."""
    if not isinstance(result, tuple) or len(result) != 3:
        return None
    parts = []
    for part in result:
        try:
            arr = np.asarray(part, dtype=float).reshape(-1)
        except (TypeError, ValueError):
            return None
        if arr.size != n:
            return None
        parts.append(arr)
    return parts[0], parts[1], parts[2]


class CoulombExplorer(Explorer):
    """E10: your shear, normal and Coulomb stress changes in map view, for the receiver under the sliders.

    resolve   : your coulomb_change(stress_enu_pa, strike, dip, rake, friction, skempton), or None
    stress    : your okada_stress(fault, points_km, lame1_pa, mu_pa), or None
    source    : the source fault, a dict with strike, dip, rake, length_km, width_km, east_km, north_km, depth_km
                and slip_m (the Contract of task 3)
    receiver  : (strike, dip, rake) of the receivers to start with (degrees)
    friction, skempton : starting values of the two sliders
    lame1_pa, mu_pa    : the elastic constants handed to your stress function
    half_width_km      : the map reaches this far east, west, north and south of the source centre
    n_grid    : points per side of the map
    """

    def __init__(self, *, resolve: Optional[Callable] = None, stress: Optional[Callable] = None,
                 source: Optional[Dict[str, float]] = None, receiver: Sequence[float] = (0.0, 90.0, 180.0),
                 friction: float = 0.4, skempton: float = 0.0, lame1_pa: float = 30e9, mu_pa: float = 30e9,
                 half_width_km: float = 25.0, n_grid: int = 40) -> None:
        if resolve is not None and not callable(resolve):
            raise TypeError("resolve must be your function coulomb_change (or None)")
        if stress is not None and not callable(stress):
            raise TypeError("stress must be your function okada_stress (or None)")
        if len(receiver) != 3:
            raise ValueError("receiver must be (strike, dip, rake) in degrees")
        if source is None:
            source = {"strike": 0.0, "dip": 90.0, "rake": 180.0, "length_km": 10.0, "width_km": 8.0,
                      "east_km": 0.0, "north_km": 0.0, "depth_km": 8.0, "slip_m": 1.0}
        missing = [key for key in _NEEDED if key not in source]
        if missing:
            raise ValueError(f"source lacks {', '.join(missing)} (see the Contract of task 3)")
        if not (n_grid >= 6 and half_width_km > 0.0):
            raise ValueError("the map needs at least 6 points per side and a positive half width")
        super().__init__(11.0, 3.9)
        self.resolve, self.stress = resolve, stress
        self.source = {key: float(source[key]) for key in _NEEDED}
        self.lame1_pa, self.mu_pa = float(lame1_pa), float(mu_pa)
        side = np.linspace(-float(half_width_km), float(half_width_km), int(n_grid))
        self.east_grid, self.north_grid = np.meshgrid(side + self.source["east_km"], side + self.source["north_km"])
        self._cache_key: Any = None
        self._cache: Tuple[Optional[np.ndarray], Optional[str]] = (None, None)
        self.stress_calls = 0
        w = self._widgets
        style = {"description_width": "initial"}

        def slider(low: float, high: float, step: float, value: float, text: str, width: str = "250px") -> Any:
            return w.FloatSlider(min=low, max=high, step=step, value=min(max(float(value), low), high),
                                 description=text, continuous_update=False, style=style, layout=w.Layout(width=width))

        strike, dip, rake = (float(v) for v in receiver)
        self.strike_slider = slider(0.0, 360.0, 1.0, strike % 360.0, "Receiver strike (deg)", "300px")
        self.dip_slider = slider(0.0, 90.0, 1.0, dip, "Receiver dip (deg)", "280px")
        self.rake_slider = slider(-180.0, 180.0, 1.0, rake, "Receiver rake (deg)", "300px")
        self.friction_slider = slider(0.0, 1.0, 0.05, friction, "Friction")
        self.skempton_slider = slider(0.0, 1.0, 0.05, skempton, "Skempton B")
        self.source_rake_slider = slider(-180.0, 180.0, 1.0, self.source["rake"], "Source rake (deg)", "300px")
        self.slip_slider = w.FloatLogSlider(value=min(max(self.source["slip_m"], 1e-4), 10.0), base=10, min=-4,
                                            max=1, step=0.05, description="Source slip (m)",
                                            continuous_update=False, style=style, layout=w.Layout(width="280px"))
        self.depth_slider = slider(0.5, 40.0, 0.5, self.source["depth_km"], "Map depth (km)", "280px")
        self.limit_slider = w.FloatLogSlider(value=100.0, base=10, min=-2, max=3, step=0.1,
                                             description="Color limit (kPa)", continuous_update=False, style=style,
                                             layout=w.Layout(width="280px"))
        controls = (self.strike_slider, self.dip_slider, self.rake_slider, self.friction_slider,
                    self.skempton_slider, self.source_rake_slider, self.slip_slider, self.depth_slider,
                    self.limit_slider)
        for control in controls:
            control.observe(self._changed, names="value")
        self.box = w.VBox([w.HBox([self.strike_slider, self.dip_slider, self.rake_slider]),
                           w.HBox([self.friction_slider, self.skempton_slider, self.limit_slider]),
                           w.HBox([self.source_rake_slider, self.slip_slider, self.depth_slider]),
                           self.image, self.status])
        self.redraw()

    def receiver(self) -> Tuple[float, float, float]:
        return float(self.strike_slider.value), float(self.dip_slider.value), float(self.rake_slider.value)

    def current_source(self) -> Dict[str, float]:
        out = dict(self.source)
        out["rake"] = float(self.source_rake_slider.value)
        out["slip_m"] = float(self.slip_slider.value)
        return out

    def points(self) -> np.ndarray:
        depth = float(self.depth_slider.value)
        return np.column_stack([self.east_grid.ravel(), self.north_grid.ravel(),
                                np.full(self.east_grid.size, depth)])

    def _stress(self) -> Tuple[Optional[np.ndarray], Optional[str]]:
        """Your stress on the grid, asked again only when the source or the map depth changed."""
        fault = self.current_source()
        key = (fault["rake"], fault["slip_m"], float(self.depth_slider.value))
        if key == self._cache_key:
            return self._cache
        pts = self.points()
        label = func_name(self.stress, "okada_stress")
        result, problem = call_yours(self.stress, label, dict(fault), pts.copy(), self.lame1_pa, self.mu_pa)
        self.stress_calls += 1
        if problem:
            found: Tuple[Optional[np.ndarray], Optional[str]] = (None, problem)
        else:
            tensors = _tensors(result, len(pts))
            found = (tensors, None) if tensors is not None else (
                None, f"your {label} did not return an array of shape ({len(pts)}, 3, 3), one tensor per point")
        self._cache_key, self._cache = key, found
        return found

    def _draw(self) -> None:
        rec = self.receiver()
        friction, skempton = float(self.friction_slider.value), float(self.skempton_slider.value)
        limit = float(self.limit_slider.value)
        fault = self.current_source()
        notes = []
        values = None
        if self.stress is None:
            notes.append("Pass stress=your okada_stress (task 3) to compute the stress on the map.")
        else:
            tensors, problem = self._stress()
            if problem:
                notes.append(problem)
            elif self.resolve is None:
                notes.append("Pass resolve=your coulomb_change (task 1) to resolve the stress on the receivers.")
            else:
                label = func_name(self.resolve, "coulomb_change")
                result, problem = call_yours(self.resolve, label, tensors.copy(), *rec, friction, skempton)
                if problem:
                    notes.append(problem)
                else:
                    values = _triple(result, tensors.shape[0])
                    if values is None:
                        notes.append(f"your {label} did not return three arrays of length {tensors.shape[0]} "
                                     "(shear, normal, coulomb) for a stack of tensors")
        self.state = {"receiver": rec, "friction": friction, "skempton": skempton, "source": fault,
                      "depth_km": float(self.depth_slider.value), "values": None, "positive_share": None}
        axes = self.figure.subplots(1, 3, sharex=True, sharey=True)
        phi = math.radians(fault["strike"])
        half = 0.5 * fault["length_km"]
        trace_e = fault["east_km"] + np.array([-half, half]) * math.sin(phi)
        trace_n = fault["north_km"] + np.array([-half, half]) * math.cos(phi)
        mesh = None
        if values is not None:
            self.state["values"] = values
        for k, ax in enumerate(axes):
            if values is not None:
                grid = np.ma.masked_invalid(values[k].reshape(self.east_grid.shape))
                mesh = ax.pcolormesh(self.east_grid, self.north_grid, np.ma.clip(grid, -limit, limit),
                                     cmap="RdBu_r", vmin=-limit, vmax=limit, shading="auto")
                self.lines[_PANELS[k]] = mesh
            ax.plot(trace_e, trace_n, color="k", lw=2.0)
            ax.set_title(f"{_PANELS[k]} change (kPa)", fontsize=9)
            ax.set_xlabel("East (km)", fontsize=8)
            ax.set_aspect("equal")
            ax.tick_params(labelsize=7)
        axes[0].set_ylabel("North (km)", fontsize=8)
        if mesh is not None:
            self.figure.colorbar(mesh, ax=list(axes), shrink=0.8, label=f"kPa (limit {limit:g})")
        lines = [f"Receiver: strike {rec[0]:g}, dip {rec[1]:g}, rake {rec[2]:g} degrees; friction {friction:g}, "
                 f"Skempton {skempton:g}. Source: rake {fault['rake']:g} degrees, slip {fault['slip_m']:.4g} m; "
                 f"map at {self.state['depth_km']:g} km depth."]
        if values is not None:
            coulomb = values[2]
            finite = np.isfinite(coulomb)
            if finite.any():
                share = float(np.mean(coulomb[finite] > 0.0))
                self.state["positive_share"] = share
                lines.append("Your values on the map: " + ", ".join(
                    f"{name.lower()} {np.nanmin(v):.3g} to {np.nanmax(v):.3g} kPa"
                    for name, v in zip(_PANELS, values) if np.isfinite(v).any())
                    + f"; Coulomb above zero in {100.0 * share:.1f} % of the cells.")
            if not finite.all():
                lines.append(f"{int((~finite).sum())} cells without a finite value are left blank.")
        self.status.value = status_html(lines + notes)


def coulomb_explorer(*, resolve: Optional[Callable] = None, stress: Optional[Callable] = None,
                     source: Optional[Dict[str, float]] = None, receiver: Sequence[float] = (0.0, 90.0, 180.0),
                     friction: float = 0.4, skempton: float = 0.0, lame1_pa: float = 30e9, mu_pa: float = 30e9,
                     half_width_km: float = 25.0, n_grid: int = 40) -> CoulombExplorer:
    """E10 explorer (see CoulombExplorer). Show it by making it the last line of a cell.

    Example (module M54, with your own functions)::

        coulomb_explorer(resolve=coulomb_change, stress=okada_stress, source=TOY, receiver=(0.0, 90.0, 180.0))
    """
    return CoulombExplorer(resolve=resolve, stress=stress, source=source, receiver=receiver, friction=friction,
                           skempton=skempton, lame1_pa=lame1_pa, mu_pa=mu_pa, half_width_km=half_width_km,
                           n_grid=n_grid)
