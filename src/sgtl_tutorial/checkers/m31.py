"""Checkers for M31 · Locating an earthquake.

Where the truth comes from (DESIGN.md section 1, rule 1):

* Two made-up travel-time models whose times are formulas: a homogeneous half-space (straight rays) and a crust
  whose speed grows linearly with depth (rays are circles; T = arccosh(1 + g^2 R^2 / (2 v0 v(z))) / g). Picks are
  made from them, so every hypocenter is known by construction; their exact derivatives come from complex-step
  differentiation of the same formulas (a different formula from the student's finite differences).
* M31-T1: construction (exact picks from a grid node: that node, RMS 0; noisy picks: at the true node the RMS and
  origin time are the standard deviation and mean of the noise the check drew) and SciPy's minimize_scalar over
  the origin time at random nodes (scipy is forbidden in the student's function).
* M31-T2: construction (exact picks: the true hypocenter), SciPy's least_squares on the same residuals (noisy
  picks), one step of the damped normal equations from numpy.linalg.lstsq on the augmented system [G; lambda I]
  with the exact Jacobian (one-step cases, also the depth rule), and the exact Jacobian at the student's answer.
* M31-T3: SciPy's curve_fit on the same linear problem (its covariance with absolute errors) for made-up
  Jacobians; then a Monte Carlo test with the student's own geiger (passed as locate=): the scatter of 300
  relocations against the student's standard errors.
* M31-T4: the student's own tool products (their picks and travel-time table, passed as obs= and tt=): the RMS
  recomputed, the origin time and the minimum tested with minimize_scalar; pyproj for the latitude and longitude;
  loose limits around the public KMA catalog location. No real-data value is printed or held here.
* M31-T5: construction and SciPy's least_squares with the depth held fixed.
* M31-T6: the check's own reading of the fixed columns of the student's lines (made-up picks), then the
  production tool itself: HYPOINVERSE (hyp1.40) locates a made-up earthquake in a half-space from the student's
  lines, and must find it where it was built.

Failure categories are keys of ``checks/specs/M31.yaml``; the engine prints their fixed messages.
"""
from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import Outcome, outcome_from_cases

__all__ = ["check_T1", "check_T2", "check_T3", "check_T4", "check_T5", "check_T6"]

MAIN_EVENT = "2019009762"                 # the ML 3.9 Sangju earthquake of 21 July 2019 (KMA catalog)
NINE_HOURS_S = 9 * 3600.0
H_COMPLEX = 1e-20                         # complex-step size: exact derivatives to rounding


# ------------------------------------------------------------------------------------------- helpers
def _call(func: Any, *args: Any, **kwargs: Any) -> Tuple[Any, Optional[BaseException]]:
    """Run the student's code. NotImplementedError passes through (the engine reports NOT STARTED)."""
    try:
        return func(*args, **kwargs), None
    except NotImplementedError:
        raise
    except Exception as exc:  # noqa: BLE001 - classified by the caller
        return None, exc


def _first(cats: Sequence[Optional[str]], priority: Sequence[str]) -> Optional[str]:
    found = [c for c in cats if c]
    for name in priority:
        if name in found:
            return name
    return found[0] if found else None


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


class _Model:
    """A made-up travel-time model with a formula: 'half' (half-space) or 'gradient' (v = v0 + g z)."""

    def __init__(self, kind: str, vp: float, ratio: float, g: float = 0.0) -> None:
        self.kind, self.vp, self.ratio, self.g = kind, float(vp), float(ratio), float(g)

    def time(self, x: Any, y: Any, z: Any, sx: np.ndarray, sy: np.ndarray, phase: np.ndarray) -> np.ndarray:
        """Travel times from a source at (x, y, z) to surface stations (sx, sy); complex inputs allowed."""
        r2 = (x - sx) ** 2 + (y - sy) ** 2 + z ** 2
        slow = np.where(np.asarray(phase) == "S", self.ratio, 1.0)
        if self.kind == "half":
            return np.sqrt(r2) / self.vp * slow
        vz = self.vp + self.g * z
        return np.arccosh(1.0 + self.g ** 2 * r2 / (2.0 * self.vp * vz)) / self.g * slow

    def tt(self, distance_km: Any, depth_km: Any, phase: Any) -> np.ndarray:
        """The function handed to the student: tt(distance_km, depth_km, phase) -> travel times (s)."""
        if phase not in ("P", "S"):
            raise ValueError(f"phase must be 'P' or 'S', got {phase!r}")
        d = np.asarray(distance_km, dtype=float)
        z = float(depth_km)
        return np.asarray(self.time(d, 0.0, z, 0.0, 0.0, np.full(d.shape, phase)), dtype=float)

    def tt_hypocentral(self, distance_km: Any, depth_km: Any, phase: Any) -> np.ndarray:
        """The slip of handing tt the hypocentral instead of the epicentral distance."""
        d = np.asarray(distance_km, dtype=float)
        return self.tt(np.sqrt(d * d + float(depth_km) ** 2), depth_km, phase)

    def jacobian(self, x: float, y: float, z: float, sx: np.ndarray, sy: np.ndarray,
                 phase: np.ndarray) -> np.ndarray:
        """Exact derivatives (complex step) of the travel times with respect to x, y, z; ones for t0."""
        G = np.ones((sx.size, 4))
        for col, (dx, dy, dz) in enumerate(((1, 0, 0), (0, 1, 0), (0, 0, 1))):
            h = 1j * H_COMPLEX
            G[:, col] = np.imag(self.time(x + dx * h, y + dy * h, z + dz * h, sx, sy, phase)) / H_COMPLEX
        return G


def _random_model(rng: np.random.Generator, kind: str) -> _Model:
    if kind == "half":
        return _Model("half", rng.uniform(5.6, 6.4), rng.uniform(1.68, 1.80))
    return _Model("gradient", rng.uniform(4.8, 5.6), rng.uniform(1.68, 1.80), rng.uniform(0.02, 0.06))


def _stations(rng: np.random.Generator, n: int, center: Tuple[float, float], r_min: float = 4.0,
              r_max: float = 40.0) -> Tuple[np.ndarray, np.ndarray]:
    """n made-up stations around center, spread in azimuth (one per sector, so no large gap)."""
    sectors = (np.arange(n) + rng.uniform(0.15, 0.85, n)) * 2.0 * np.pi / n
    radius = rng.uniform(r_min, r_max, n)
    return center[0] + radius * np.sin(sectors), center[1] + radius * np.cos(sectors)


def _obs_table(rng: np.random.Generator, model: _Model, sx: np.ndarray, sy: np.ndarray, truth: Sequence[float],
               sigma: float, s_count: int):
    """A pick table (station, phase, x_km, y_km, t_s, quality) in shuffled order with an odd index."""
    import pandas as pd

    names = [f"XQ.T{k:02d}" for k in range(sx.size)]
    with_s = set(rng.choice(sx.size, size=min(s_count, sx.size), replace=False).tolist())
    rows = []
    for k in range(sx.size):
        for phase in ("P", "S"):
            if phase == "S" and k not in with_s:
                continue
            rows.append((names[k], phase, float(sx[k]), float(sy[k])))
    sxa = np.array([r[2] for r in rows])
    sya = np.array([r[3] for r in rows])
    pha = np.array([r[1] for r in rows])
    x, y, z, t0 = (float(v) for v in truth)
    exact = t0 + np.real(model.time(x, y, z, sxa, sya, pha))
    noise = rng.normal(0.0, sigma, exact.size) if sigma > 0 else np.zeros(exact.size)
    table = pd.DataFrame({"station": [r[0] for r in rows], "phase": pha, "x_km": sxa, "y_km": sya,
                          "t_s": exact + noise, "quality": rng.integers(0, 4, exact.size)})
    order = rng.permutation(len(table))
    table = table.iloc[order]
    table.index = 2 * np.arange(len(table)) + 7
    return table, noise[order]


def _arrays(obs: Any) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    return (obs["x_km"].to_numpy(float), obs["y_km"].to_numpy(float), obs["phase"].to_numpy(str),
            obs["t_s"].to_numpy(float))


def _same_table(a: Any, b: Any) -> bool:
    return list(a.columns) == list(b.columns) and list(a.index) == list(b.index) and a.equals(b)


def _best_t0(rho: np.ndarray) -> Tuple[float, float]:
    """(t0, RMS) that minimize sum (rho - t0)^2, found numerically (SciPy's minimize_scalar)."""
    from scipy.optimize import minimize_scalar

    lo, hi = float(rho.min()) - 1.0, float(rho.max()) + 1.0
    found = minimize_scalar(lambda t: float(np.sum((rho - t) ** 2)), bracket=(lo, hi), method="brent",
                            options={"xtol": 1e-13, "maxiter": 500})
    t0 = float(found.x)
    return t0, float(np.sqrt(np.mean((rho - t0) ** 2)))


def _rho(model_tt: Callable, obs_arrays: Tuple[np.ndarray, ...], x: float, y: float, z: float) -> np.ndarray:
    """Observed minus predicted travel time (origin time 0) at one trial point, with a tt function."""
    sx, sy, ph, t = obs_arrays
    dist = np.sqrt((x - sx) ** 2 + (y - sy) ** 2)
    pred = np.empty(t.size)
    for phase in ("P", "S"):
        use = ph == phase
        if use.any():
            pred[use] = np.asarray(model_tt(dist[use], z, phase), dtype=float)
    return t - pred


# =========================================================================================== M31-T1
T1_PRIORITY = ("format", "changed-input", "axis-order", "phase", "hypocentral", "origin-time", "median", "not-rms",
               "best-node", "wrong-values")
T1_KEYS = ("rms", "t0", "x_km", "y_km", "z_km", "t0_s", "rms_s")


def _t1_cases(rng: np.random.Generator, crit: dict) -> List[dict]:
    cases = []
    trials = int(crit.get("trials", 6))
    for i in range(trials):
        model = _random_model(rng, "half" if i % 2 == 0 else "gradient")
        step = float(rng.choice([1.0, 1.5]))
        xs = float(rng.integers(-3, 4)) + (np.arange(17) - 8) * step
        ys = float(rng.integers(-3, 4)) + (np.arange(13) - 6) * step
        zs = 1.0 + 2.0 * np.arange(9)
        node = (int(rng.integers(3, 14)), int(rng.integers(3, 10)), int(rng.integers(1, 8)))
        t0 = float(rng.uniform(-2.0, 2.0))
        truth = (xs[node[0]], ys[node[1]], zs[node[2]], t0)
        n_sta = int(rng.integers(6, 13))
        sx, sy = _stations(rng, n_sta, (truth[0], truth[1]), 3.0, 35.0)
        sigma = 0.0 if i < trials // 2 else float(crit.get("noise_s", 0.05))
        obs, noise = _obs_table(rng, model, sx, sy, truth, sigma, int(rng.integers(3, n_sta + 1)))
        probes = [(int(rng.integers(0, 17)), int(rng.integers(0, 13)), int(rng.integers(0, 9)))
                  for _ in range(int(crit.get("random_nodes", 15)))]
        cases.append({"model": model, "xs": xs, "ys": ys, "zs": zs, "node": node, "truth": truth, "obs": obs,
                      "noise": noise, "sigma": sigma, "probes": probes})
    return cases


def _t1_alternatives(case: dict, arrays: Tuple[np.ndarray, ...], i: int, j: int, k: int) -> Dict[str, float]:
    """RMS values at node (i, j, k) under the usual slips."""
    model = case["model"]
    x, y, z = case["xs"][i], case["ys"][j], case["zs"][k]
    rho = _rho(model.tt, arrays, x, y, z)
    out = {"origin-time": float(np.sqrt(np.mean(rho ** 2))),
           "median": float(np.sqrt(np.mean((rho - np.median(rho)) ** 2))),
           "not-rms": float(np.sum((rho - rho.mean()) ** 2))}
    out["not-rms-2"] = float(np.sqrt(np.sum((rho - rho.mean()) ** 2)))
    out["not-rms-3"] = float(np.mean((rho - rho.mean()) ** 2))
    out["not-rms-4"] = float(np.mean(np.abs(rho - rho.mean())))
    rho_h = _rho(model.tt_hypocentral, arrays, x, y, z)
    out["hypocentral"] = float(np.std(rho_h))
    sx, sy, ph, t = arrays
    rho_p = _rho(model.tt, (sx, sy, np.full(ph.shape, "P"), t), x, y, z)
    out["phase"] = float(np.std(rho_p))
    return out


def _t1_judge(case: dict, got: Any, tol: float) -> Tuple[bool, Optional[str], Optional[str]]:
    """(passed, category, what went wrong in words)."""
    nx, ny, nz = case["xs"].size, case["ys"].size, case["zs"].size
    if not isinstance(got, dict) or any(key not in got for key in T1_KEYS):
        return False, "format", "not a dict with the keys of the Contract"
    try:
        rms = np.asarray(got["rms"], dtype=float)
        t0c = np.asarray(got["t0"], dtype=float)
    except (TypeError, ValueError):
        return False, "format", "rms or t0 is not an array of numbers"
    if rms.shape == (ny, nx, nz) or t0c.shape == (ny, nx, nz):
        return False, "axis-order", f"arrays of shape {rms.shape}, expected {(nx, ny, nz)}"
    if rms.shape != (nx, ny, nz) or t0c.shape != (nx, ny, nz):
        return False, "format", f"arrays of shape {rms.shape} and {t0c.shape}, expected {(nx, ny, nz)}"
    scalars = [_finite(got[key]) for key in ("x_km", "y_km", "z_km", "t0_s", "rms_s")]
    if any(v is None for v in scalars) or not np.isfinite(rms).all():
        return False, "format", "a value is not a finite number"
    arrays = _arrays(case["obs"])
    model = case["model"]
    checks = [case["node"]] + list(case["probes"])
    for idx, (i, j, k) in enumerate(checks):
        rho = _rho(model.tt, arrays, case["xs"][i], case["ys"][j], case["zs"][k])
        if idx == 0:                                  # the true node: what the noise was built to give
            exp_t0 = case["truth"][3] + float(np.mean(case["noise"]))
            exp_rms = float(np.std(case["noise"]))
        else:
            exp_t0, exp_rms = _best_t0(rho)
        if abs(rms[i, j, k] - exp_rms) > tol or abs(t0c[i, j, k] - exp_t0) > max(tol, 1e-6):
            alts = _t1_alternatives(case, arrays, i, j, k)
            for name in ("phase", "hypocentral", "origin-time", "median", "not-rms", "not-rms-2", "not-rms-3",
                         "not-rms-4"):
                if abs(rms[i, j, k] - alts[name]) <= 1e-6:
                    cat = "not-rms" if name.startswith("not-rms") else name
                    return False, cat, f"at node {(i, j, k)}"
            return False, "wrong-values", f"at node {(i, j, k)}: RMS {rms[i, j, k]:.6f} s, origin time " \
                                          f"{t0c[i, j, k]:.6f} s; expected {exp_rms:.6f} s and {exp_t0:.6f} s"
    # the best node: the minimum of the student's own cube
    x_b, y_b, z_b, t0_b, rms_b = scalars
    low = float(rms.min())
    at = [(int(a), int(b), int(c)) for a, b, c in zip(*np.nonzero(rms <= low + 1e-12))]
    ok_node = any(abs(case["xs"][a] - x_b) < 1e-9 and abs(case["ys"][b] - y_b) < 1e-9
                  and abs(case["zs"][c] - z_b) < 1e-9 and abs(t0c[a, b, c] - t0_b) < 1e-9 for a, b, c in at)
    if not ok_node or abs(rms_b - low) > 1e-9:
        return False, "best-node", "x_km, y_km, z_km, t0_s and rms_s are not the node of your smallest RMS"
    if case["sigma"] == 0.0:
        i, j, k = case["node"]
        if (case["xs"][i], case["ys"][j], case["zs"][k]) != (x_b, y_b, z_b):
            return False, "best-node", "with exact picks the best node must be the true node"
    return True, None, None


def check_T1(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    tol = float(crit.get("rms_tol_s", 1e-6))
    oks: List[bool] = []
    cats: List[Optional[str]] = []
    example = None
    for case in _t1_cases(ctx.rng, crit):
        obs = case["obs"].copy(deep=True)
        got, err = _call(target, obs, case["model"].tt, case["xs"].copy(), case["ys"].copy(), case["zs"].copy())
        if err is not None:
            raise err
        if not _same_table(obs, case["obs"]):
            ok, cat, why = False, "changed-input", "the obs table was changed"
        else:
            ok, cat, why = _t1_judge(case, got, tol)
        oks.append(ok)
        cats.append(cat)
        if cat and example is None:
            example = {"inputs": {"model": ("half-space" if case["model"].kind == "half" else "speed growing with "
                                            "depth"), "stations": int(case["obs"]["station"].nunique()),
                                  "picks": len(case["obs"]), "pick errors (s)": case["sigma"],
                                  "grid": f"{case['xs'].size} x {case['ys'].size} x {case['zs'].size}",
                                  "true node": [round(float(v), 3) for v in case["truth"][:3]],
                                  "true origin time (s)": round(case["truth"][3], 4)},
                       "got": None, "error": why}
    category = _first(cats, T1_PRIORITY)
    return outcome_from_cases(np.array(oks), category=category, example=example)


# =========================================================================================== M31-T2
T2_PRIORITY = ("format", "changed-input", "airquake", "origin-time", "derivative-sign", "hypocentral", "jacobian",
               "damping", "not-converged", "wrong-values")
T2_KEYS = ("x_km", "y_km", "z_km", "t0_s", "rms_s", "residual_s", "G", "n_iter", "converged")


def _lsq_oracle(model_tt: Callable, arrays: Tuple[np.ndarray, ...], start: Sequence[float],
                fixed_z: Optional[float] = None) -> np.ndarray:
    """SciPy's least_squares on the same residuals (depth >= 0; or with the depth held at fixed_z)."""
    from scipy.optimize import least_squares

    if fixed_z is None:
        def resid(m):
            return _rho(model_tt, arrays, m[0], m[1], m[2]) - m[3]
        lower = [-np.inf, -np.inf, 0.0, -np.inf]
        fit = least_squares(resid, np.asarray(start, dtype=float), bounds=(lower, np.inf), method="trf",
                            xtol=1e-14, ftol=1e-14, gtol=1e-14, max_nfev=2000)
        return fit.x

    def resid3(m):
        return _rho(model_tt, arrays, m[0], m[1], fixed_z) - m[2]
    fit = least_squares(resid3, np.asarray(start, dtype=float), method="lm", xtol=1e-14, ftol=1e-14, gtol=1e-14,
                        max_nfev=4000)
    return fit.x


def _t2_cases(rng: np.random.Generator, crit: dict) -> List[dict]:
    cases = []
    sigma = float(crit.get("noise_s", 0.05))
    specs = [("exact", "half", 6.0), ("exact", "gradient", 6.0), ("far", "half", 12.0), ("noisy", "half", 6.0),
             ("noisy", "gradient", 6.0), ("one-step", "half", 3.0), ("one-step", "gradient", 3.0),
             ("air", "gradient", 1.0)]
    for kind, model_kind, offset in specs:
        model = _random_model(rng, model_kind)
        center = (float(rng.uniform(-5, 5)), float(rng.uniform(-5, 5)))
        if kind == "air":                          # picks from a source 1 km above the ground
            truth = (center[0], center[1], -1.0, float(rng.uniform(-1, 1)))
        else:
            truth = (center[0], center[1], float(rng.uniform(4.0, 18.0)), float(rng.uniform(-1, 1)))
        n_sta = int(rng.integers(8, 13))
        sx, sy = _stations(rng, n_sta, center, 3.0, 40.0)
        noisy = kind == "noisy"
        obs, _ = _obs_table(rng, model, sx, sy, truth, sigma if noisy else 0.0, int(rng.integers(4, n_sta + 1)))
        angle = rng.uniform(0, 2 * np.pi)
        if kind == "far":
            start = (truth[0] + offset * math.sin(angle), truth[1] + offset * math.cos(angle), 1.0, 0.0)
        elif kind == "air":
            start = (truth[0] + 0.3, truth[1] - 0.2, 0.4, truth[3] + 0.05)
        else:
            start = (truth[0] + offset * math.sin(angle), truth[1] + offset * math.cos(angle),
                     max(1.0, truth[2] + float(rng.uniform(-4.0, 4.0))), truth[3] + float(rng.uniform(-0.6, 0.6)))
        case = {"kind": kind, "model": model, "truth": truth, "obs": obs, "start": start}
        if kind in ("one-step", "air"):
            damping = float(crit.get("damping", 0.3)) if kind == "one-step" else 0.0
            case["kwargs"] = {"damping": damping, "max_iter": 1}
            case["expected"] = _t2_one_step(case, damping)
            free = _t2_one_step(case, damping, rule=False)
            if kind == "air" and free[2] >= 0.0:       # the step must want to leave the ground
                case["start"] = (start[0], start[1], 0.15, start[3])
                case["expected"] = _t2_one_step(case, damping)
            if kind == "one-step" and free[2] < 0.0:   # a plain damped step that stays below the surface
                case["start"] = (start[0], start[1], case["truth"][2], start[3])
                case["expected"] = _t2_one_step(case, damping)
        else:
            case["kwargs"] = {}
        cases.append(case)
    return cases


def _t2_one_step(case: dict, damping: float, rule: bool = True) -> np.ndarray:
    """One damped Gauss-Newton step from the start with the exact Jacobian (lstsq on [G; lambda I])."""
    sx, sy, ph, t = _arrays(case["obs"])
    x, y, z, t0 = case["start"]
    G = case["model"].jacobian(x, y, z, sx, sy, ph)
    r = t - t0 - np.real(case["model"].time(x, y, z, sx, sy, ph))
    A = np.vstack([G, damping * np.eye(4)])
    b = np.concatenate([r, np.zeros(4)])
    step = np.linalg.lstsq(A, b, rcond=None)[0]
    new = np.array([x, y, z, t0]) + step
    if rule and z + step[2] < 0.0:
        new[2] = 0.5 * z
    return new


def _t2_parts(got: Any, n: int) -> Optional[dict]:
    if not isinstance(got, dict) or any(key not in got for key in T2_KEYS):
        return None
    out = {}
    for key in ("x_km", "y_km", "z_km", "t0_s", "rms_s"):
        value = _finite(got[key])
        if value is None:
            return None
        out[key] = value
    try:
        out["residual_s"] = np.asarray(got["residual_s"], dtype=float).ravel()
        out["G"] = np.asarray(got["G"], dtype=float)
        out["n_iter"] = int(got["n_iter"])
    except (TypeError, ValueError):
        return None
    if out["residual_s"].size != n or out["G"].ndim != 2 or out["G"].shape[0] != n:
        return None
    if not isinstance(got["converged"], (bool, np.bool_)):
        return None
    out["converged"] = bool(got["converged"])
    out["m"] = np.array([out["x_km"], out["y_km"], out["z_km"], out["t0_s"]])
    return out


def _close(m: np.ndarray, ref: np.ndarray, tol_km: float, tol_s: float) -> bool:
    return bool(np.all(np.abs(m[:3] - ref[:3]) <= tol_km) and abs(m[3] - ref[3]) <= tol_s)


def _t2_judge(case: dict, got: Any, crit: dict) -> Tuple[bool, Optional[str], Optional[str]]:
    obs = case["obs"]
    n = len(obs)
    parts = _t2_parts(got, n)
    if parts is None:
        return False, "format", "not a dict with the keys and shapes of the Contract"
    if parts["G"].shape != (n, 4):
        return False, "jacobian", f"G has shape {parts['G'].shape}, expected {(n, 4)}"
    m = parts["m"]
    if m[2] < 0.0:
        return False, "airquake", f"final depth {m[2]:.3f} km"
    arrays = _arrays(obs)
    model = case["model"]
    tol_km, tol_s = float(crit.get("tol_km", 0.005)), float(crit.get("tol_s", 0.0005))
    start = np.asarray(case["start"], dtype=float)
    if case["kind"] in ("one-step", "air"):
        expected = case["expected"]
        if _close(m, expected, 1e-3, 1e-4):
            return True, None, None
        free = _t2_one_step(case, case["kwargs"]["damping"], rule=False)
        if free[2] < 0.0 and (m[2] <= 0.0 or abs(m[2] - free[2]) < 1e-3):
            return False, "airquake", f"after one step the depth is {m[2]:.4f} km, expected {expected[2]:.4f} km"
        here_G = model.jacobian(m[0], m[1], m[2], arrays[0], arrays[1], arrays[2])
        if parts["G"].shape == (n, 4) and np.max(np.abs(parts["G"][:, :2] + here_G[:, :2])) < 5e-3:
            return False, "derivative-sign", "the x and y columns of G have the wrong sign"
        if abs(m[3] - start[3]) < 1e-12:
            return False, "origin-time", "the origin time did not move"
        if case["kind"] == "one-step":
            plain = _t2_one_step(case, 0.0)
            single = _t2_one_step(case, math.sqrt(case["kwargs"]["damping"]))
            if _close(m, plain, 1e-3, 1e-4) or _close(m, single, 1e-3, 1e-4):
                return False, "damping", "the first step does not use (G^T G + damping^2 I)"
        return False, "wrong-values", f"after one step {np.round(m, 4).tolist()}, expected " \
                                      f"{np.round(expected, 4).tolist()}"
    truth = np.asarray(case["truth"], dtype=float)
    ref = truth if case["kind"] in ("exact", "far") else _lsq_oracle(model.tt, arrays, start)
    # residuals and Jacobian at the student's final hypocenter
    exact_G = model.jacobian(m[0], m[1], m[2], arrays[0], arrays[1], arrays[2])
    resid = arrays[3] - m[3] - np.real(model.time(m[0], m[1], m[2], arrays[0], arrays[1], arrays[2]))
    if _close(m, ref, tol_km, tol_s):
        if not np.allclose(parts["G"][:, 3], 1.0, atol=1e-12):
            return False, "jacobian", "the last column of G is not all ones"
        if np.max(np.abs(parts["G"] - exact_G)) > float(crit.get("jacobian_tol", 2e-4)):
            return False, "jacobian", "G differs from the derivatives at your final hypocenter"
        if np.max(np.abs(parts["residual_s"] - resid)) > 1e-6:
            return False, "wrong-values", "residual_s are not observed - t0 - T at your final hypocenter (row order)"
        if abs(parts["rms_s"] - float(np.sqrt(np.mean(resid ** 2)))) > 1e-6:
            return False, "wrong-values", "rms_s is not the RMS of your final residuals"
        if not parts["converged"] or parts["n_iter"] < 1:
            return False, "not-converged", "converged is False although the answer is right"
        return True, None, None
    # wrong answer: which slip?
    if abs(m[3] - start[3]) < 1e-12 and abs(ref[3] - start[3]) > 1e-3:
        return False, "origin-time", "the origin time never moved"
    G_here = parts["G"]
    if G_here.shape == (n, 4) and np.max(np.abs(G_here[:, :2] + exact_G[:, :2])) < 5e-3 and \
            np.max(np.abs(exact_G[:, :2])) > 1e-3:
        return False, "derivative-sign", "the x and y columns of G have the wrong sign"
    alt = _lsq_oracle(model.tt_hypocentral, arrays, start)
    if _close(m, alt, 0.05, 0.01):
        return False, "hypocentral", "your location fits tt called with hypocentral distances"
    start_G = model.jacobian(start[0], start[1], start[2], arrays[0], arrays[1], arrays[2])
    if np.max(np.abs(G_here - start_G)) < 5e-4 < np.max(np.abs(exact_G - start_G)):
        return False, "jacobian", "G is the Jacobian at the start, not at your final hypocenter"
    if _close(m, ref, 0.5, 0.05) or not parts["converged"]:
        return False, "not-converged", f"ended at {np.round(m, 4).tolist()} after {parts['n_iter']} steps"
    return False, "wrong-values", f"ended at {np.round(m, 4).tolist()}, expected {np.round(ref, 4).tolist()}"


def check_T2(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    oks: List[bool] = []
    cats: List[Optional[str]] = []
    example = None
    for case in _t2_cases(ctx.rng, crit):
        obs = case["obs"].copy(deep=True)
        got, err = _call(target, obs, case["model"].tt, tuple(case["start"]), **case["kwargs"])
        if err is not None:
            raise err
        if not _same_table(obs, case["obs"]):
            ok, cat, why = False, "changed-input", "the obs table was changed"
        else:
            ok, cat, why = _t2_judge(case, got, crit)
        oks.append(ok)
        cats.append(cat)
        if cat and example is None:
            example = {"inputs": {"case": case["kind"], "model": ("half-space" if case["model"].kind == "half"
                                                                  else "speed growing with depth"),
                                  "picks": len(case["obs"]), "start": [round(float(v), 3) for v in case["start"]],
                                  "keywords": case["kwargs"] or "defaults",
                                  "true hypocenter and origin time": [round(float(v), 3) for v in case["truth"]]},
                       "got": None, "error": why}
    category = _first(cats, T2_PRIORITY)
    return outcome_from_cases(np.array(oks), category=category, example=example)


# =========================================================================================== M31-T3
T3_PRIORITY = ("format", "no-sigma", "sigma-not-squared", "fixed-origin", "variance", "corr", "wrong-values",
               "no-locator", "locator", "monte-carlo")


def _t3_oracle(G: np.ndarray, sigma: float, rng: np.random.Generator) -> np.ndarray:
    """Covariance of the linear least-squares fit y = G m with absolute pick errors sigma (SciPy's curve_fit)."""
    from scipy.optimize import curve_fit

    def line(X, a, b, c, d):
        return X @ np.array([a, b, c, d])

    def slope(X, *p):
        return X

    y = G @ rng.normal(0.0, 1.0, 4) + rng.normal(0.0, sigma, G.shape[0])
    _, pcov = curve_fit(line, G, y, p0=np.zeros(4), sigma=np.full(G.shape[0], sigma), absolute_sigma=True,
                        jac=slope)
    return np.asarray(pcov, dtype=float)


def _t3_parts(got: Any) -> Optional[Tuple[np.ndarray, np.ndarray, float]]:
    if not isinstance(got, dict) or any(key not in got for key in ("cov", "se", "corr_zt")):
        return None
    try:
        cov = np.asarray(got["cov"], dtype=float)
        se = np.asarray(got["se"], dtype=float).ravel()
    except (TypeError, ValueError):
        return None
    corr = _finite(got["corr_zt"])
    if corr is None or se.size != 4 or not np.isfinite(se).all():
        return None
    return cov, se, corr


def _t3_linear(target: Any, rng: np.random.Generator, crit: dict) -> Tuple[List[bool], List[Optional[str]],
                                                                             Optional[dict]]:
    oks, cats, example = [], [], None
    rel = float(crit.get("rel_tol", 1e-6))
    for _ in range(int(crit.get("trials", 8))):
        n = int(rng.integers(6, 21))
        G = np.column_stack([rng.uniform(-0.2, 0.2, n), rng.uniform(-0.2, 0.2, n), rng.uniform(0.0, 0.15, n),
                             np.ones(n)])
        sigma = float(rng.uniform(0.02, 0.3))
        truth = _t3_oracle(G, sigma, rng)
        got, err = _call(target, G.copy(), sigma)
        if err is not None:
            raise err
        parts = _t3_parts(got)
        cat, why = None, None
        if parts is None:
            cat, why = "format", "not a dict with cov (4 x 4), se (4 numbers) and corr_zt (a number)"
        else:
            cov, se, corr = parts
            se_true = np.sqrt(np.diag(truth))
            corr_true = truth[2, 3] / (se_true[2] * se_true[3])

            def near(a, b):
                a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
                return a.shape == b.shape and bool(np.all(np.abs(a - b) <= rel * np.abs(b) + 1e-14))
            space = sigma ** 2 * np.linalg.inv(G[:, :3].T @ G[:, :3])
            if cov.shape != (4, 4):
                if cov.shape == (3, 3) and near(cov, space):
                    cat, why = "fixed-origin", "a 3 x 3 covariance of x, y, z alone"
                else:
                    cat, why = "format", f"cov has shape {cov.shape}"
            elif not near(cov, truth):
                if near(cov, truth / sigma ** 2):
                    cat = "no-sigma"
                elif near(cov, truth / sigma):
                    cat = "sigma-not-squared"
                elif near(cov[:3, :3], space):
                    cat = "fixed-origin"
                else:
                    cat = "wrong-values"
                why = "cov differs from sigma^2 (G^T G)^-1"
            elif not near(se, se_true):
                if near(se, np.diag(truth)):
                    cat = "variance"
                elif near(se[:3], np.sqrt(np.diag(space))):
                    cat = "fixed-origin"
                else:
                    cat = "wrong-values"
                why = "se differs from the square roots of the diagonal of cov"
            elif abs(corr - corr_true) > 1e-6:
                cat, why = "corr", f"corr_zt {corr:.6f}, expected {corr_true:.6f}"
        oks.append(cat is None)
        cats.append(cat)
        if cat and example is None:
            example = {"inputs": {"G": f"{n} x 4 (made up)", "sigma_s": round(sigma, 4)}, "got": None,
                       "error": why}
    return oks, cats, example


def check_T3(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    rng = ctx.rng
    oks, cats, example = _t3_linear(target, rng, crit)
    if not all(oks):
        return outcome_from_cases(np.array(oks), category=_first(cats, T3_PRIORITY), example=example)
    locate = ctx.get("locate") if hasattr(ctx, "get") else None
    if not callable(locate):
        return outcome_from_cases(np.array(oks + [False]), category="no-locator")
    # Monte Carlo with the student's own locator
    sigma = float(crit.get("mc_sigma_s", 0.05))
    model = _Model("half", 6.0, 1.73)
    truth = (1.5, -2.0, float(rng.uniform(5.0, 10.0)), 0.4)
    sx, sy = _stations(rng, 12, (truth[0], truth[1]), 4.0, 40.0)
    obs, _ = _obs_table(rng, model, sx, sy, truth, 0.0, 8)
    t_exact = obs["t_s"].to_numpy(float).copy()
    first, err = _call(locate, obs.copy(deep=True), model.tt, (truth[0] + 0.4, truth[1] - 0.3, truth[2] + 0.5,
                                                                truth[3] + 0.05))
    parts = _t2_parts(first, len(obs)) if err is None else None
    if parts is None or not _close(parts["m"], np.asarray(truth), 0.01, 0.001) or parts["G"].shape != (len(obs), 4):
        return outcome_from_cases(np.array(oks + [False]), category="locator",
                                  note="The Monte Carlo part needs your geiger (locate=geiger) to find a made-up "
                                       "earthquake from exact picks.")
    predicted, err = _call(target, parts["G"].copy(), sigma)
    pred = _t3_parts(predicted) if err is None else None
    if pred is None:
        return outcome_from_cases(np.array(oks + [False]), category="format")
    cloud = []
    for _ in range(int(crit.get("mc_draws", 300))):
        noisy = obs.copy(deep=True)
        noisy["t_s"] = t_exact + rng.normal(0.0, sigma, t_exact.size)
        fit, err = _call(locate, noisy, model.tt, tuple(truth))
        fit_parts = _t2_parts(fit, len(obs)) if err is None else None
        if fit_parts is None:
            return outcome_from_cases(np.array(oks + [False]), category="locator")
        cloud.append(fit_parts["m"])
    cloud = np.array(cloud)
    scatter = cloud.std(axis=0)
    corr = float(np.corrcoef(cloud[:, 2], cloud[:, 3])[0, 1])
    ratio_ok = bool(np.all(np.abs(scatter / pred[1] - 1.0) <= float(crit.get("mc_rel_tol", 0.2))))
    corr_ok = abs(corr - pred[2]) <= float(crit.get("mc_corr_tol", 0.15))
    passed = ratio_ok and corr_ok
    example = None if passed else {
        "inputs": {"made-up earthquake": [round(v, 3) for v in truth], "pick errors (s)": sigma,
                   "relocations": len(cloud)},
        "got": {"your standard errors": np.round(pred[1], 4).tolist(), "your correlation": round(pred[2], 3)},
        "error": f"the relocations scatter by {np.round(scatter, 4).tolist()} with correlation {corr:.3f}"}
    return outcome_from_cases(np.array(oks + [passed]), category="monte-carlo", example=example)


# =========================================================================================== M31-T4
T4_KEYS = ("x_km", "y_km", "depth_km", "t0_s", "latitude", "longitude", "origin_utc", "rms_s", "se", "n_picks")


def _kma_event(event_id: str) -> Tuple[float, float, float, Any]:
    from obspy import UTCDateTime

    from .. import data as _data

    cat = _data.kma_catalog()
    row = cat.loc[cat["event_id"] == event_id].iloc[0]
    return (float(row["latitude"]), float(row["longitude"]), float(row["depth_km"]),
            UTCDateTime(row["origin_utc"].isoformat()))


def check_T4(target: Any, ctx: Any) -> Outcome:
    from obspy import UTCDateTime
    from pyproj import Proj

    crit = ctx.criteria

    def fail(category: str, n: int = 1) -> Outcome:
        return Outcome(passed=False, n_cases=n, n_failed=1, category=category, message="",
                       details={"real_data": True})

    ans = target
    if not isinstance(ans, dict) or any(key not in ans for key in T4_KEYS):
        return fail("format")
    nums = {key: _finite(ans[key]) for key in T4_KEYS if key not in ("origin_utc", "se")}
    try:
        se = np.asarray(ans["se"], dtype=float).ravel()
        origin = UTCDateTime(str(ans["origin_utc"]))
    except Exception:  # noqa: BLE001 - anything unreadable is a format problem
        return fail("format")
    if any(v is None for v in nums.values()) or se.size != 4:
        return fail("format")
    lat0, lon0, _depth0, origin0 = _kma_event(MAIN_EVENT)
    offset = origin - (origin0 + nums["t0_s"])
    if abs(abs(offset) - NINE_HOURS_S) <= 2.0:
        return fail("time-zone")
    if abs(offset) > float(crit.get("origin_tol_s", 0.002)):
        return fail("origin-utc")
    frame = Proj(proj="aeqd", lat_0=lat0, lon_0=lon0, datum="WGS84")
    east, north = frame(nums["longitude"], nums["latitude"])
    if math.hypot(east / 1000.0 - nums["x_km"], north / 1000.0 - nums["y_km"]) > float(crit.get("frame_tol_km",
                                                                                                 0.05)):
        return fail("projection")
    if (math.hypot(nums["x_km"], nums["y_km"]) > float(crit.get("epicenter_km", 10.0))
            or not float(crit.get("depth_min_km", 2.0)) <= nums["depth_km"] <= float(crit.get("depth_max_km", 30.0))
            or abs(nums["t0_s"]) > float(crit.get("origin_window_s", 3.0))):
        return fail("far-from-kma")
    if not (np.all(np.isfinite(se)) and np.all(se > 0) and np.all(se[:3] <= float(crit.get("se_max_km", 10.0)))
            and se[3] <= float(crit.get("se_max_s", 2.0))):
        return fail("errors")
    obs = ctx.get("obs") if hasattr(ctx, "get") else None
    tt = ctx.get("tt") if hasattr(ctx, "get") else None
    if obs is None or not callable(tt):
        return fail("no-picks")
    try:
        arrays = _arrays(obs)
    except Exception:  # noqa: BLE001
        return fail("no-picks")
    if int(nums["n_picks"]) != arrays[3].size:
        return fail("picks-count")
    rho = _rho(tt, arrays, nums["x_km"], nums["y_km"], nums["depth_km"])
    rms_here = float(np.sqrt(np.mean((rho - nums["t0_s"]) ** 2)))
    if not math.isfinite(rms_here) or abs(rms_here - nums["rms_s"]) > float(crit.get("rms_tol_s", 1e-4)):
        return fail("rms")
    best_t0, _ = _best_t0(rho)
    if abs(best_t0 - nums["t0_s"]) > float(crit.get("best_t0_tol_s", 0.003)):
        return fail("not-minimum")
    step = float(crit.get("probe_km", 0.25))
    slack = float(crit.get("probe_slack_s", 5e-4))
    for dx, dy, dz in ((step, 0, 0), (-step, 0, 0), (0, step, 0), (0, -step, 0), (0, 0, step), (0, 0, -step)):
        depth = nums["depth_km"] + dz
        if depth < 0.0:
            continue
        _, rms_probe = _best_t0(_rho(tt, arrays, nums["x_km"] + dx, nums["y_km"] + dy, depth))
        if rms_probe < nums["rms_s"] - slack:
            return fail("not-minimum")
    return Outcome(passed=True, n_cases=1, n_failed=0, category=None, message="", details={"real_data": True})


# =========================================================================================== M31-T5
T5_PRIORITY = ("format", "changed-input", "depth-moved", "origin-fixed", "not-converged", "wrong-values")
T5_COLUMNS = ("depth_km", "x_km", "y_km", "t0_s", "rms_s")


def _t5_cases(rng: np.random.Generator, crit: dict) -> List[dict]:
    cases = []
    for kind, model_kind in (("exact", "half"), ("exact", "gradient"), ("noisy", "half"), ("noisy", "gradient")):
        model = _random_model(rng, model_kind)
        center = (float(rng.uniform(-4, 4)), float(rng.uniform(-4, 4)))
        truth = (center[0], center[1], float(np.round(rng.uniform(4.0, 14.0), 2)), float(rng.uniform(-1, 1)))
        n_sta = int(rng.integers(8, 13))
        sx, sy = _stations(rng, n_sta, center, 3.0, 40.0)
        sigma = 0.0 if kind == "exact" else float(crit.get("noise_s", 0.05))
        obs, _ = _obs_table(rng, model, sx, sy, truth, sigma, int(rng.integers(4, n_sta + 1)))
        depths = np.round(truth[2] + np.arange(-6.0, 6.01, 1.5) + (0.0 if kind == "exact" else 0.4), 3)
        depths = depths[depths >= 0.5]
        start = (truth[0] + 1.5, truth[1] - 1.0, truth[3] + 0.4)
        cases.append({"kind": kind, "model": model, "truth": truth, "obs": obs, "depths": depths, "start": start})
    return cases


def _t5_judge(case: dict, got: Any, crit: dict) -> Tuple[bool, Optional[str], Optional[str]]:
    import pandas as pd

    depths = case["depths"]
    if not isinstance(got, pd.DataFrame) or any(c not in got.columns for c in T5_COLUMNS) or len(got) != depths.size:
        return False, "format", "not a DataFrame with depth_km, x_km, y_km, t0_s, rms_s and one row per depth"
    try:
        table = {c: got[c].to_numpy(float) for c in T5_COLUMNS}
    except (TypeError, ValueError):
        return False, "format", "a column holds something that is not a number"
    if not all(np.isfinite(v).all() for v in table.values()):
        return False, "format", "a value is not a finite number"
    if np.max(np.abs(table["depth_km"] - depths)) > 1e-9:
        return False, "depth-moved", "depth_km is not the list of depths given, in its order"
    arrays = _arrays(case["obs"])
    model = case["model"]
    truth = case["truth"]
    mine = np.column_stack([table["x_km"], table["y_km"], table["t0_s"]])
    # SciPy's least_squares at each fixed depth, started from the student's own row: a row must be a converged
    # minimum at its depth (far from the true depth the misfit may hold more than one; any of them is accepted)
    near = np.hypot(mine[:, 0] - truth[0], mine[:, 1] - truth[1]) < 15.0
    ref = np.array([_lsq_oracle(model.tt, arrays, (row if ok else (truth[0], truth[1], truth[3])),
                                fixed_z=float(z)) for row, ok, z in zip(mine, near, depths)])
    ref_rms = np.array([float(np.sqrt(np.mean((_rho(model.tt, arrays, r[0], r[1], z) - r[2]) ** 2)))
                        for r, z in zip(ref, depths)])
    tol_km, tol_s = float(crit.get("tol_km", 0.003)), float(crit.get("tol_s", 0.0005))
    ok_rows = (np.all(np.abs(mine[:, :2] - ref[:, :2]) <= tol_km, axis=1) & (np.abs(mine[:, 2] - ref[:, 2]) <= tol_s)
               & (np.abs(table["rms_s"] - ref_rms) <= float(crit.get("rms_tol_s", 1e-5))))
    if case["kind"] == "exact":
        k = int(np.argmin(np.abs(depths - truth[2])))
        ok_rows[k] &= table["rms_s"][k] <= 1e-4
    if ok_rows.all():
        return True, None, None
    if np.allclose(table["t0_s"], case["start"][2], atol=1e-12):
        return False, "origin-fixed", "t0_s never moved from the start"
    spread_mine = np.ptp(mine, axis=0).max()
    spread_ref = np.ptp(ref, axis=0).max()
    if spread_mine < 1e-3 < spread_ref or np.ptp(table["rms_s"]) < 1e-7 < np.ptp(ref_rms):
        return False, "depth-moved", "every depth gives the same answer: the depth was not held fixed"
    bad = int(np.flatnonzero(~ok_rows)[0])
    if np.all(np.abs(mine - ref) <= np.array([0.2, 0.2, 0.05])):
        return False, "not-converged", f"at {depths[bad]:g} km: {np.round(mine[bad], 4).tolist()}, expected " \
                                       f"{np.round(ref[bad], 4).tolist()}"
    return False, "wrong-values", f"at {depths[bad]:g} km: {np.round(mine[bad], 4).tolist()} and RMS " \
                                  f"{table['rms_s'][bad]:.5f} s, expected {np.round(ref[bad], 4).tolist()} and " \
                                  f"{ref_rms[bad]:.5f} s"


def check_T5(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    oks: List[bool] = []
    cats: List[Optional[str]] = []
    example = None
    for case in _t5_cases(ctx.rng, crit):
        obs = case["obs"].copy(deep=True)
        got, err = _call(target, obs, case["model"].tt, case["depths"].copy(), tuple(case["start"]))
        if err is not None:
            raise err
        if not _same_table(obs, case["obs"]):
            ok, cat, why = False, "changed-input", "the obs table was changed"
        else:
            ok, cat, why = _t5_judge(case, got, crit)
        oks.append(ok)
        cats.append(cat)
        if cat and example is None:
            example = {"inputs": {"case": case["kind"], "model": ("half-space" if case["model"].kind == "half"
                                                                  else "speed growing with depth"),
                                  "picks": len(case["obs"]), "depths (km)": case["depths"].round(3).tolist(),
                                  "start": [round(float(v), 3) for v in case["start"]],
                                  "true hypocenter and origin time": [round(float(v), 3) for v in case["truth"]]},
                       "got": None, "error": why}
    return outcome_from_cases(np.array(oks), category=_first(cats, T5_PRIORITY), example=example)


# =========================================================================================== M31-T6
T6_PRIORITY = ("format", "station-columns", "s-columns", "p-columns", "seconds", "time-zone", "rounding", "weight",
               "wrong-values", "no-hypoinverse", "hypoinverse")
_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"


def _t6_picks(rng: np.random.Generator, n_sta: int, start: Any, edges: bool):
    """Made-up picks: invented station and network codes, an invented date, times on second/minute edges."""
    import pandas as pd

    rows = []
    nets = ["Q" + _LETTERS[int(rng.integers(0, len(_LETTERS)))] for _ in range(2)]
    for k in range(n_sta):
        size = int(rng.integers(2, 6))
        code = "".join(_LETTERS[int(rng.integers(0, len(_LETTERS)))] for _ in range(size - 1)) + str(k % 10)
        net = nets[k % 2]
        tp = start + float(rng.uniform(1.0, 40.0))
        for phase in ("P", "S"):
            if (phase == "S" and k % 4 == 1) or (phase == "P" and k % 5 == 3):
                continue
            when = tp if phase == "P" else tp + float(rng.uniform(0.5, 20.0))
            rows.append({"station": f"{net}.{code}", "phase": phase,
                         "channel": ("HHZ" if phase == "P" else str(rng.choice(["HHN", "HHE", "ELN"]))),
                         "time": when, "weight": int(rng.integers(0, 5))})
    if edges:   # the edge of a minute and of a second, and a time just after a full second
        base = start + 600.0 - (start.timestamp % 60.0)
        for k, sec in enumerate((59.996, 9.9951, 0.004, 59.9949)):
            phase = "P" if k % 2 == 0 else "S"
            rows.append({"station": f"{nets[0]}.E{k}", "phase": phase, "channel": "HHZ" if phase == "P" else "HHE",
                         "time": base + 60.0 * k + sec, "weight": k % 5})
    table = pd.DataFrame(rows)
    table = table.iloc[rng.permutation(len(table))]
    table["comment"] = "made up"
    table.index = 3 * np.arange(len(table)) + 11
    return table


def _t6_read(line: Any, phase: str) -> Tuple[Optional[dict], Optional[str]]:
    """The fields of one phase line, read back from the fixed columns of the Contract (None, category) if bad."""
    from obspy import UTCDateTime

    if not isinstance(line, str) or "\n" in line:
        return None, "format"
    pad = line.ljust(60)
    fields = {"station": pad[0:5].strip(), "network": pad[5:7].strip(), "channel": pad[9:12].strip()}
    if pad[7:9].strip() or pad[12].strip() or pad[5:7] != pad[5:7].strip().ljust(2):
        return fields, "station-columns"
    if phase == "P":
        if pad[13:15] != "IP":
            return fields, ("s-columns" if pad[46:48] == "ES" else "p-columns")
        weight, minute, sec_text, rest = pad[16], pad[17:29], pad[29:34], pad[34:]
        blanks = pad[15]
    else:
        if pad[46:48] != "ES":
            return fields, "s-columns"
        if pad[13:17].strip() or pad[29:41].strip():
            return fields, "s-columns"
        weight, minute, sec_text, rest = pad[49], pad[17:29], pad[41:46], pad[50:]
        blanks = pad[48]
    if blanks.strip() or rest.strip():
        return fields, ("p-columns" if phase == "P" else "s-columns")
    if not (minute.isdigit() and len(minute) == 12):
        return fields, "p-columns" if phase == "P" else "s-columns"
    if "." in sec_text or not sec_text.strip().isdigit() or sec_text != sec_text.strip().rjust(5):
        return fields, "seconds"
    if not weight.isdigit():
        return fields, "weight"
    try:
        start = UTCDateTime(f"{minute[0:4]}-{minute[4:6]}-{minute[6:8]}T{minute[8:10]}:{minute[10:12]}:00")
    except Exception:  # noqa: BLE001
        return fields, "p-columns" if phase == "P" else "s-columns"
    fields.update({"weight": int(weight), "time": start + int(sec_text) / 100.0})
    return fields, None


def _t6_judge_lines(picks: Any, got: Any) -> Tuple[bool, Optional[str], Optional[str]]:
    if not isinstance(got, (list, tuple)) or len(got) != len(picks) or not all(isinstance(s, str) for s in got):
        return False, "format", "not a list of strings, one per pick"
    for line, row in zip(got, picks.itertuples(index=False)):
        given = tuple(reversed(str(row.station).split(".", 1))) + (row.channel,)
        fields, cat = _t6_read(line, row.phase)
        if cat is None and (fields["station"], fields["network"], fields["channel"]) != given:
            cat = "station-columns"
        if cat:
            return False, cat, f"line {line!r} for {row.phase} at {row.station}"
        error = float(fields["time"] - row.time)
        if abs(abs(error) - NINE_HOURS_S) < 1.0:
            return False, "time-zone", f"line {line!r}: 9 hours off"
        if abs(error) > 0.005 + 1e-6:
            category = "rounding" if abs(error) <= 0.0100001 else "seconds" if abs(error) > 1.0 else "wrong-values"
            return False, category, f"line {line!r} reads {fields['time']} for a pick at {row.time}"
        if fields["weight"] != int(row.weight):
            return False, "weight", f"line {line!r}: weight {fields['weight']}, expected {int(row.weight)}"
    return True, None, None


def _hypoinverse() -> Optional[str]:
    home = os.environ.get("SGTL_HOME", "").strip()
    places = [str(Path(home).expanduser() / "tools" / "bin")] if home else []
    places.append(str(Path.home() / "sgtl" / "tools" / "bin"))
    places.append(os.environ.get("PATH", ""))
    return shutil.which("hyp1.40", path=os.pathsep.join(p for p in places if p))


def _degmin(value: float) -> Tuple[int, float]:
    whole = int(abs(value))
    return whole, (abs(value) - whole) * 60.0


def _t6_locate(program: str, lines: List[str], stations: Dict[str, Tuple[float, float]], header_time: Any,
               center: Tuple[float, float]) -> Optional[dict]:
    """Run HYPOINVERSE on the student's lines (one-layer half-space model); the first summary line as a dict."""
    import pandas as pd
    from obspy import UTCDateTime

    with tempfile.TemporaryDirectory(prefix="sgtl-m31-hyp-") as tmp:
        room = Path(tmp)
        with open(room / "sta.hyp", "w") as out:
            for name, (lat, lon) in sorted(stations.items()):
                net, code = name.split(".")
                la, la_m = _degmin(lat)
                lo, lo_m = _degmin(lon)
                out.write(f"{code:<5} {net:<2}  HHZ  {la:2d} {la_m:7.4f}N{lo:3d} {lo_m:7.4f}E   0\n")
        (room / "p.crh").write_text("check P\n 6.00 0.00\n")
        (room / "s.crh").write_text("check S\n 3.47 0.00\n")
        la, la_m = _degmin(center[0])
        lo, lo_m = _degmin(center[1])
        head = header_time.strftime("%Y%m%d%H%M%S") + "00" + f"{la:2d}N{int(la_m * 100):4d}{lo:3d}E{int(lo_m * 100):4d}"
        (room / "ev.phs").write_text("\n".join([head, *lines, " " * 66 + "1"]) + "\n")
        commands = ("CON 25 0.01 0.0001\nMIN 4\nZTR 8 F\nDIS 4 300 1 3\nRMS 4 9 9 9\nERF T\nTOP F\nH71 4 1 3\n"
                    "LET 5 2 0 0 0\nSTA 'sta.hyp'\nCRH 1 'p.crh'\nCRH 2 's.crh'\nSAL 1 2\nPHS 'ev.phs'\nFIL\n"
                    "PRT 'ev.prt'\nSUM 'ev.sum'\nARC 'ev.arc'\nLOC\nSTO\n")
        try:
            subprocess.run([program], input=commands, cwd=room, capture_output=True, text=True, timeout=120)
            table = pd.read_csv(room / "ev.sum", skipinitialspace=True)
        except Exception:  # noqa: BLE001 - no summary: HYPOINVERSE could not read the lines
            return None
    if table.empty:
        return None
    table.columns = [str(c).strip() for c in table.columns]
    row = table.iloc[0]
    minute = str(row[table.columns[0]]).strip().replace("/", "-").replace(" ", "T")
    return {"lat": float(row["LAT"]), "lon": float(row["LON"]), "depth": float(row["DEPTH"]),
            "time": UTCDateTime(minute + ":00") + float(row["SEC"])}


def check_T6(target: Any, ctx: Any) -> Outcome:
    from obspy import UTCDateTime
    from pyproj import Geod

    crit = ctx.criteria
    rng = ctx.rng
    oks: List[bool] = []
    cats: List[Optional[str]] = []
    example = None
    for k in range(int(crit.get("trials", 3))):
        start = UTCDateTime(int(rng.integers(2031, 2037)), int(rng.integers(1, 13)), int(rng.integers(1, 29)),
                            int(rng.integers(0, 24)), int(rng.integers(0, 60)), float(rng.uniform(0, 59)))
        picks = _t6_picks(rng, int(rng.integers(4, 9)), start, edges=(k == 0))
        given = picks.copy(deep=True)
        got, err = _call(target, given)
        if err is not None:
            raise err
        if not _same_table(given, picks):
            ok, cat, why = False, "format", "the picks table was changed"
        else:
            ok, cat, why = _t6_judge_lines(picks, got)
        oks.append(ok)
        cats.append(cat)
        if cat and example is None:
            example = {"inputs": {"picks": len(picks), "first pick": f"{picks.iloc[0]['station']} "
                                  f"{picks.iloc[0]['phase']} {picks.iloc[0]['channel']} {picks.iloc[0]['time']} "
                                  f"weight {picks.iloc[0]['weight']}"}, "got": None, "error": why}
    if not all(oks):
        return outcome_from_cases(np.array(oks), category=_first(cats, T6_PRIORITY), example=example)
    program = _hypoinverse()
    if program is None:
        return outcome_from_cases(np.array(oks + [False]), category="no-hypoinverse")
    # a made-up earthquake in a half-space, located by HYPOINVERSE from the student's lines
    import pandas as pd

    geod = Geod(ellps="WGS84")
    center = (float(rng.uniform(15.0, 45.0)), float(rng.uniform(100.0, 150.0)))
    sx, sy = _stations(rng, 10, (0.0, 0.0), 5.0, 45.0)
    truth = (float(rng.uniform(-5, 5)), float(rng.uniform(-5, 5)), float(rng.uniform(4.0, 16.0)))
    origin = UTCDateTime(int(rng.integers(2031, 2037)), int(rng.integers(1, 13)), int(rng.integers(1, 29)),
                         int(rng.integers(0, 24)), int(rng.integers(0, 60)), float(rng.uniform(0, 59)))
    stations, rows = {}, []
    for j in range(sx.size):
        name = f"QZ.M{j:02d}"
        lon, lat, _ = geod.fwd(center[1], center[0], math.degrees(math.atan2(sx[j], sy[j])),
                               1000.0 * math.hypot(sx[j], sy[j]))
        stations[name] = (lat, lon)
        dist = math.sqrt((sx[j] - truth[0]) ** 2 + (sy[j] - truth[1]) ** 2 + truth[2] ** 2)
        rows.append({"station": name, "phase": "P", "channel": "HHZ", "time": origin + dist / 6.0, "weight": 0})
        if j % 3 != 2:
            rows.append({"station": name, "phase": "S", "channel": "HHN", "time": origin + dist / 3.47,
                         "weight": 0})
    picks = pd.DataFrame(rows)
    got, err = _call(target, picks.copy(deep=True))
    if err is not None:
        raise err
    lon_t, lat_t, _ = geod.fwd(center[1], center[0], math.degrees(math.atan2(truth[0], truth[1])),
                               1000.0 * math.hypot(truth[0], truth[1]))
    found = _t6_locate(program, list(got), stations, origin - 2.0, center)
    passed = False
    why = "HYPOINVERSE wrote no location from your lines"
    if found is not None:
        _, _, miss_m = geod.inv(lon_t, lat_t, found["lon"], found["lat"])
        miss_z = abs(found["depth"] - truth[2])
        miss_t = abs(found["time"] - origin)
        passed = (miss_m / 1000.0 <= float(crit.get("hyp_epi_km", 0.15)) and miss_z <= float(crit.get("hyp_depth_km",
                                                                                                      0.3))
                  and miss_t <= float(crit.get("hyp_time_s", 0.03)))
        why = (f"HYPOINVERSE put the made-up earthquake {miss_m / 1000.0:.3f} km from its epicenter, "
               f"{miss_z:.3f} km off in depth and {miss_t:.3f} s off in origin time")
    example = None if passed else {"inputs": {"stations": len(stations), "picks": len(picks),
                                              "model": "half-space, 6.00 and 3.47 km/s"}, "got": None, "error": why}
    return outcome_from_cases(np.array(oks + [passed]), category="hypoinverse", example=example)
