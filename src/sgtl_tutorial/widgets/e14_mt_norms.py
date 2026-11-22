"""E14 · Misfit-norm explorer: which station writes the answer of a moment-tensor grid search?

The explorer takes made-up elementary seismograms (the kernels of module M53, Part 0) and a made-up tensor, makes
noisy records from them once, and lets you turn the gain of one station up or down (a wrong number in its
response), switch the misfit norm (L2, L1, hybrid) and leave that station out. After every change it runs a
coarse grid search over strike, dip, rake and the scalar moments you give it, and shows each station's share of the
best fit's misfit, n_eff and the Kagan angle between the best mechanism and the made-up one. Every number that a task
of M53 or of an earlier module covers comes from the functions you hand in:

- ``misfit_budget(obs, syn, dt_s, norm) -> {"per_trace", "total", "share", "n_eff"}``: your task M53-T2; it scores
  every trial and gives the shares and n_eff of the best one.
- ``moment_tensor(strike, dip, rake, m0_nm, frame="USE")``: your task M52-T1; it builds the unit tensor of every
  grid point once, when the explorer starts.
- ``kagan_angle(mech1, mech2)``: your task M51-T3; it compares the best mechanism with the made-up one.

The explorer itself only adds and multiplies: records = kernels times the tensor plus noise, synthetics = kernels
times each trial tensor. It starts no thread and needs no display (the picture is a PNG of an Agg figure).

Credit: Minseong Seo (SGTL, Seoul National University). License: MIT.
"""
from __future__ import annotations

from typing import Any, Callable, List, Optional, Sequence, Tuple

import numpy as np

from ._common import Explorer, call_yours, func_name, status_html

NORMS = ("L2", "L1", "hybrid")


def grid_points(step_deg: float) -> List[Tuple[float, float, float]]:
    """(strike, dip, rake) of a regular grid: strike 0 to <360, dip step to 90, rake -180 to <180."""
    step = float(step_deg)
    if not 5.0 <= step <= 90.0:
        raise ValueError("step_deg must lie between 5 and 90 degrees")
    strikes = np.arange(0.0, 360.0 - 1e-9, step)
    dips = np.arange(step, 90.0 + 1e-9, step)
    rakes = np.arange(-180.0, 180.0 - 1e-9, step)
    return [(float(s), float(d), float(r)) for s in strikes for d in dips for r in rakes]


def _six(tensor: Any) -> Optional[np.ndarray]:
    """The six elements (11, 22, 33, 12, 13, 23) of a 3 x 3 result, or None when it is not that."""
    try:
        t = np.asarray(tensor, dtype=float)
    except (TypeError, ValueError):
        return None
    if t.shape != (3, 3) or not np.all(np.isfinite(t)):
        return None
    return np.array([t[0, 0], t[1, 1], t[2, 2], t[0, 1], t[0, 2], t[1, 2]])


def _budget(result: Any, n_rows: int) -> Optional[Tuple[float, np.ndarray]]:
    """(total, shares) of a misfit_budget result, or None when it is not usable."""
    if not isinstance(result, dict) or "total" not in result or "share" not in result:
        return None
    try:
        total = float(result["total"])
        share = np.asarray(result["share"], dtype=float)
    except (TypeError, ValueError):
        return None
    if share.shape != (n_rows,) or not np.isfinite(total):
        return None
    return total, share


class MTNormExplorer(Explorer):
    """One loud (or quiet) station, three norms, and the shares of the best fit (see the module docstring).

    kernels     : (stations, 3, samples, 6) elementary seismograms, columns in USE order
    true_m6     : the made-up tensor (6 numbers, USE order, N m)
    mechanism   : its (strike, dip, rake), for the Kagan angle
    codes       : station names (one per station)
    dt_s        : sample interval (s)
    noise_sigma : standard deviation of the added Gaussian noise (record units)
    moments_nm  : trial scalar moments of the grid search (N m)
    step_deg    : grid step of strike, dip and rake (degrees)
    """

    def __init__(self, misfit_budget: Callable, moment_tensor: Callable, kagan_angle: Optional[Callable] = None, *,
                 kernels: Any, true_m6: Sequence[float], mechanism: Sequence[float], codes: Sequence[str],
                 dt_s: float, noise_sigma: float, moments_nm: Sequence[float], seed: int = 0,
                 step_deg: float = 30.0) -> None:
        if not callable(misfit_budget) or not callable(moment_tensor):
            raise TypeError("misfit_budget and moment_tensor must be your functions (tasks M53-T2 and M52-T1)")
        if kagan_angle is not None and not callable(kagan_angle):
            raise TypeError("kagan_angle must be your function of M51 (or None)")
        g = np.asarray(kernels, dtype=float)
        if g.ndim != 4 or g.shape[1] != 3 or g.shape[3] != 6:
            raise ValueError("kernels must have the shape (stations, 3, samples, 6)")
        if len(codes) != g.shape[0]:
            raise ValueError("give one station code per station of kernels")
        if len(mechanism) != 3 or len(true_m6) != 6:
            raise ValueError("mechanism is (strike, dip, rake) and true_m6 six numbers")
        moments = [float(m) for m in moments_nm]
        if not moments or any(not np.isfinite(m) or m <= 0 for m in moments):
            raise ValueError("moments_nm must hold positive scalar moments (N m)")
        super().__init__(10.0, 3.4)
        self.misfit_budget, self.moment_tensor, self.kagan_angle = misfit_budget, moment_tensor, kagan_angle
        self.kernels, self.codes, self.dt_s = g, [str(c) for c in codes], float(dt_s)
        self.mechanism = tuple(float(v) for v in mechanism)
        self.moments = moments
        clean = np.einsum("scnj,j->scn", g, np.asarray(true_m6, dtype=float))
        noise = np.random.default_rng(int(seed)).normal(0.0, float(noise_sigma), clean.shape)
        self.base_records = clean + noise
        self.grid = grid_points(step_deg)
        self.units, self.unit_problem = self._units()
        w = self._widgets
        style = {"description_width": "initial"}
        self.station_menu = w.Dropdown(options=self.codes, value=self.codes[min(3, len(self.codes) - 1)],
                                       description="Station", style=style, layout=w.Layout(width="200px"))
        self.gain_slider = w.FloatLogSlider(value=1.0, base=10.0, min=-1.0, max=1.5, step=0.05,
                                            description="Gain of that station", continuous_update=False,
                                            style=style, layout=w.Layout(width="360px"))
        self.norm_menu = w.Dropdown(options=list(NORMS), value="L2", description="Norm", style=style,
                                    layout=w.Layout(width="160px"))
        self.leave_out = w.Checkbox(value=False, description="Leave the station out", indent=False)
        for control in (self.station_menu, self.gain_slider, self.norm_menu, self.leave_out):
            control.observe(self._changed, names="value")
        self.box = w.VBox([w.HBox([self.station_menu, self.gain_slider, self.norm_menu, self.leave_out]),
                           self.image, self.status])
        self.redraw()

    def _units(self) -> Tuple[Optional[np.ndarray], Optional[str]]:
        """The unit tensor (USE, 1 N m) of every grid point from your moment_tensor, built once."""
        label = func_name(self.moment_tensor, "moment_tensor")
        rows = []
        for s, d, r in self.grid:
            result, problem = call_yours(self.moment_tensor, label, s, d, r, 1.0, "USE")
            if problem:
                return None, problem
            six = _six(result)
            if six is None:
                return None, f"your {label} did not return a 3 x 3 array of finite numbers"
            rows.append(six)
        return np.array(rows), None

    def records(self) -> np.ndarray:
        """The records with the chosen station's gain applied."""
        out = self.base_records.copy()
        out[self.codes.index(self.station_menu.value)] *= float(self.gain_slider.value)
        return out

    def _search(self, obs: np.ndarray, keep: List[int], norm: str) -> Tuple[Optional[dict], Optional[str]]:
        label = func_name(self.misfit_budget, "misfit_budget")
        rows = obs[keep].reshape(-1, obs.shape[-1])
        best = None
        for m0 in self.moments:
            trial = np.einsum("scnj,kj->kscn", self.kernels[keep], self.units * m0)
            trial = trial.reshape(len(self.units), -1, obs.shape[-1])
            for k in range(len(self.units)):
                result, problem = call_yours(self.misfit_budget, label, rows, trial[k], self.dt_s, norm)
                if problem:
                    return None, problem
                parsed = _budget(result, rows.shape[0])
                if parsed is None:
                    return None, f"your {label} did not return 'total' and one 'share' per trace"
                if best is None or parsed[0] < best["total"]:
                    best = {"total": parsed[0], "share": parsed[1], "mechanism": self.grid[k], "m0_nm": m0,
                            "synthetic": trial[k]}
        return best, None

    def _draw(self) -> None:
        fig = self.figure
        ax_share, ax_trace = fig.subplots(1, 2, gridspec_kw={"width_ratios": [1.2, 1.0]})
        loud = self.codes.index(self.station_menu.value)
        keep = [k for k in range(len(self.codes)) if not (self.leave_out.value and k == loud)]
        norm = str(self.norm_menu.value)
        obs = self.records()
        notes: List[str] = []
        self.state = {"station": self.station_menu.value, "gain": float(self.gain_slider.value), "norm": norm,
                      "kept": [self.codes[k] for k in keep], "best": None, "station_share": None, "n_eff": None,
                      "kagan": None}
        best = None
        if self.units is None:
            notes.append(self.unit_problem or "no unit tensors")
        else:
            best, problem = self._search(obs, keep, norm)
            if problem:
                notes.append(problem)
        if best is not None:
            per_station = best["share"].reshape(len(keep), 3).sum(axis=1)
            self.state.update(best=best["mechanism"], m0_nm=best["m0_nm"],
                              station_share=dict(zip(self.state["kept"], per_station.tolist())),
                              n_eff=float(1.0 / np.sum(best["share"] ** 2)) if np.sum(best["share"] ** 2) > 0
                              else float("nan"))
            colors = ["tab:red" if self.codes[k] == self.station_menu.value else "tab:gray" for k in keep]
            ax_share.bar(range(len(keep)), per_station, color=colors)
            ax_share.set_xticks(range(len(keep)))
            ax_share.set_xticklabels(self.state["kept"], rotation=60, fontsize=7)
            ax_share.set_ylabel("Share of the misfit")
            ax_share.set_ylim(0.0, 1.0)
            ax_share.set_title(f"{norm}: n_eff {self.state['n_eff']:.2f} of {best['share'].size} traces",
                               fontsize=9)
            show = keep.index(loud) if loud in keep else 0
            t = np.arange(obs.shape[-1]) * self.dt_s
            ax_trace.plot(t, obs[keep[show], 0], color="black", lw=0.8, label="record")
            syn = best["synthetic"].reshape(len(keep), 3, -1)[show, 0]
            ax_trace.plot(t, syn, color="red", lw=0.8, label="best synthetic")
            ax_trace.set_title(f"{self.codes[keep[show]]}, Z", fontsize=9)
            ax_trace.set_xlabel("Time (s)")
            ax_trace.set_yticks([])
            ax_trace.legend(loc="lower center", bbox_to_anchor=(0.5, 1.08), ncol=2, frameon=False, fontsize=8)
            if self.kagan_angle is not None:
                angle, problem = call_yours(self.kagan_angle, func_name(self.kagan_angle, "kagan_angle"),
                                            best["mechanism"], self.mechanism)
                if problem:
                    notes.append(problem)
                else:
                    try:
                        self.state["kagan"] = float(angle)
                    except (TypeError, ValueError):
                        notes.append("your kagan_angle did not return a number")
        lines = [f"Station {self.station_menu.value} x {float(self.gain_slider.value):.3g}"
                 f"{' (left out)' if self.leave_out.value else ''}; norm {norm}; grid of {len(self.grid)} "
                 f"mechanisms x {len(self.moments)} moments."]
        if best is not None:
            top = max(self.state["station_share"].items(), key=lambda kv: kv[1])
            lines.append(f"Best: strike {best['mechanism'][0]:g}, dip {best['mechanism'][1]:g}, rake "
                         f"{best['mechanism'][2]:g}, M0 {best['m0_nm']:.3g} N m; largest station share {top[0]} "
                         f"{top[1]:.3f}; n_eff {self.state['n_eff']:.2f}")
            if self.state["kagan"] is not None:
                lines.append(f"Kagan angle to the made-up mechanism {self.mechanism}: {self.state['kagan']:.1f} deg")
        self.status.value = status_html(lines + notes)


def mt_norm_explorer(misfit_budget: Callable, moment_tensor: Callable, kagan_angle: Optional[Callable] = None, *,
                     kernels: Any, true_m6: Sequence[float], mechanism: Sequence[float], codes: Sequence[str],
                     dt_s: float, noise_sigma: float, moments_nm: Sequence[float], seed: int = 0,
                     step_deg: float = 30.0) -> MTNormExplorer:
    """E14 explorer (see MTNormExplorer). Show it by making it the last line of a cell.

    Example (module M53, Part 2, with your own functions)::

        mt_norm_explorer(misfit_budget, moment_tensor, kagan_angle, kernels=TOY_G, true_m6=TOY_TRUE,
                         mechanism=TOY_MECHANISM, codes=TOY_CODES, dt_s=TOY_DT_S, noise_sigma=toy_sigma,
                         moments_nm=[magnitude_moment(mw=m) for m in TOY_MWS])
    """
    return MTNormExplorer(misfit_budget, moment_tensor, kagan_angle, kernels=kernels, true_m6=true_m6,
                          mechanism=mechanism, codes=codes, dt_s=dt_s, noise_sigma=noise_sigma,
                          moments_nm=moments_nm, seed=seed, step_deg=step_deg)
