"""Checkers for M41 · Relative relocation.

Where the truth comes from (DESIGN.md section 1, rule 1):

* M41-T1: construction. Made-up picks of made-up events at made-up stations (some picks missing, rows shuffled);
  the expected differential times come from the made-up travel times, pair by pair, by plain loops.
* M41-T2: construction and an independent library. Made-up wavelets (Ricker and Gabor shapes, smooth noise bursts)
  and copies shifted by known fractions of a sample, with offsets, scaling and noise; ObsPy's correlate (naive
  normalization, direct method) gives the correlation values and xcorr_max the peak; numpy.polyfit through the
  three samples around the peak gives the vertex (a different formula). The student may use none of these.
* M41-T3: construction and a different formula. Made-up clusters and stations; the partial derivatives come from
  central finite differences of the straight-line travel time, and the observed differential times from positions
  moved by a known small step, so that G times that step reproduces d to second order.
* M41-T4: construction and a different method. The constrained damped least-squares solution through an orthonormal
  basis of the null space of the four mean-shift rows (scipy.linalg.null_space) and numpy.linalg.lstsq; exact data
  of a known change with zero mean shift must give that change back.
* M41-T5: construction. Exact differential times of made-up clusters from known positions and origin-time shifts;
  the start positions differ from the truth by changes with zero mean, so the iterations must land on the truth.
  The check hands its own finite-difference system and null-space solver to the student's function.
* M41-T6: construction for the function (made-up run logs and product files in a temporary folder), then the
  student's own run products: the check recomputes the SHA-256 of every copy named in the report, requires the
  reported fingerprints to be those of the files, compares them with the log work/.sgtl/runs.jsonl that sgtl
  writes for every run (two identical relocation copies need two logged runs that wrote them), and reads the
  provenance line that PocketQuake writes at the top of bootstrap_errors.csv. The report holds no verdict of its
  own: whether the rerun was identical is judged from the files.

No real-data value is computed or printed here. Failure categories are keys of ``checks/specs/M41.yaml``.
"""
from __future__ import annotations

import hashlib
import json
import math
import numbers
import os
import re
import tempfile
from itertools import combinations
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import Outcome, outcome_from_cases

__all__ = ["check_T1", "check_T2", "check_T3", "check_T4", "check_T5", "check_T6"]

FD_STEP_KM = 1.0e-4          # central differences of the straight-line time (truncation error ~1e-9 s/km)


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
    present = {c for c in cats if c}
    return next((c for c in priority if c in present), next(iter(sorted(present)), None))


def _is_frame(got: Any) -> bool:
    try:
        import pandas as pd
    except ImportError:  # pragma: no cover - the course environment has pandas
        return False
    return isinstance(got, pd.DataFrame)


def _real(value: Any) -> bool:
    return isinstance(value, numbers.Real) and not isinstance(value, (bool, np.bool_)) and math.isfinite(float(value))


def _array(value: Any, shape: Tuple[int, ...]) -> Optional[np.ndarray]:
    """A finite float array of exactly this shape, or None."""
    if not isinstance(value, np.ndarray) or value.shape != shape:
        return None
    try:
        out = value.astype(float)
    except (TypeError, ValueError):
        return None
    return out if np.isfinite(out).all() else None


def _close(a: Any, b: Any, tol: float) -> bool:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    return a.shape == b.shape and bool(np.all(np.abs(a - b) <= tol))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------- shared oracles of tasks 3, 4 and 5
def _times(points: np.ndarray, stations: np.ndarray, rows_sta: np.ndarray, speed: np.ndarray) -> np.ndarray:
    return np.linalg.norm(points - stations[rows_sta], axis=1) / speed


def _fd_system(events_km: Any, stations_km: Any, obs: Any, vp: float, vs: float) -> Tuple[np.ndarray, np.ndarray]:
    """G and d of a homogeneous medium: derivatives by central finite differences of the straight-line time."""
    ev = np.array(events_km, dtype=float)
    sta = np.array(stations_km, dtype=float)
    e1 = np.asarray(obs["ev1"], dtype=int)
    e2 = np.asarray(obs["ev2"], dtype=int)
    k = np.asarray(obs["sta"], dtype=int)
    speed = np.where(np.asarray(obs["phase"]) == "P", float(vp), float(vs))
    m = len(e1)
    out = np.zeros((m, 4 * len(ev)))
    rows = np.arange(m)
    for which, sign in ((e1, 1.0), (e2, -1.0)):
        for c in range(3):
            step = np.zeros(3)
            step[c] = FD_STEP_KM
            ahead = _times(ev[which] + step, sta, k, speed)
            behind = _times(ev[which] - step, sta, k, speed)
            np.add.at(out, (rows, 4 * which + c), sign * (ahead - behind) / (2.0 * FD_STEP_KM))
        np.add.at(out, (rows, 4 * which + 3), sign)
    resid = np.asarray(obs["dt_s"], dtype=float) - (_times(ev[e1], sta, k, speed) - _times(ev[e2], sta, k, speed))
    return out, resid


def _mean_rows(n_par: int) -> np.ndarray:
    rows = np.zeros((4, n_par))
    for e in range(n_par // 4):
        rows[:, 4 * e:4 * e + 4] = np.eye(4)
    return rows


def _ns_solve(G: Any, d: Any, damp: float) -> np.ndarray:
    """Constrained damped least squares through an orthonormal basis of the null space of the mean-shift rows."""
    from scipy.linalg import null_space

    design = np.array(G, dtype=float)
    data = np.array(d, dtype=float)
    basis = null_space(_mean_rows(design.shape[1]))
    stacked = np.vstack([design @ basis, float(damp) * np.eye(basis.shape[1])])
    padded = np.concatenate([data, np.zeros(basis.shape[1])])
    return basis @ np.linalg.lstsq(stacked, padded, rcond=None)[0]


def _geometry(rng: np.random.Generator, n_ev: int, n_sta: int, spread_km: float = 0.6,
              radius: Tuple[float, float] = (4.0, 70.0)) -> Tuple[np.ndarray, np.ndarray]:
    center = np.array([rng.uniform(-3, 3), rng.uniform(-3, 3), rng.uniform(6.0, 18.0)])
    events = center + rng.normal(0.0, spread_km, (n_ev, 3))
    az = rng.uniform(0.0, 2 * np.pi, n_sta)
    dist = rng.uniform(*radius, n_sta)
    elev = np.where(rng.random(n_sta) < 0.3, 0.0, -rng.uniform(0.0, 0.8, n_sta))   # z down: above sea level < 0
    stations = np.column_stack([center[0] + dist * np.sin(az), center[1] + dist * np.cos(az), elev])
    return events, stations


def _obs_table(rng: np.random.Generator, n_ev: int, n_sta: int, n_obs: int, index_offset: bool = True):
    import pandas as pd

    rows = []
    while len(rows) < n_obs:
        i, j = (int(v) for v in rng.choice(n_ev, 2, replace=False))
        rows.append({"ev1": i, "ev2": j, "sta": int(rng.integers(0, n_sta)),
                     "phase": "P" if rng.random() < 0.55 else "S"})
    table = pd.DataFrame(rows)
    if index_offset:
        table.index = rng.permutation(np.arange(100, 100 + n_obs))
    return table


def _exact_dt(events: np.ndarray, stations: np.ndarray, obs: Any, vp: float, vs: float,
              shifts: np.ndarray) -> np.ndarray:
    """Differential travel times (t_ev1 - t0_ev1) - (t_ev2 - t0_ev2) for events at `events` whose origin times are
    later than their catalog times by `shifts` (s)."""
    e1 = np.asarray(obs["ev1"], dtype=int)
    e2 = np.asarray(obs["ev2"], dtype=int)
    k = np.asarray(obs["sta"], dtype=int)
    speed = np.where(np.asarray(obs["phase"]) == "P", vp, vs)
    return (_times(events[e1], stations, k, speed) + shifts[e1]) - (_times(events[e2], stations, k, speed)
                                                                    + shifts[e2])


# ===================================================================== M41-T1 catalog differential times
T1_COLUMNS = ("ev1", "ev2", "station", "phase", "dt_s")
T1_PRIORITY = ("format", "changed-input", "pair-order", "nan-rows", "duplicates", "min-obs", "rows", "no-origin",
               "sign", "wrong-values", "order")


def _t1_case(rng: np.random.Generator, number: int) -> dict:
    import pandas as pd

    n_ev = int(rng.integers(3, 7))
    n_sta = int(rng.integers(3, 8))
    names = [f"ev{int(v):03d}" for v in rng.choice(np.arange(10, 400), n_ev, replace=False)]
    stations = [f"XX.S{int(v):02d}" for v in rng.choice(np.arange(1, 60), n_sta, replace=False)]
    origins = {e: float(np.round(rng.uniform(0.0, 5.0e5), 3)) for e in names}
    keep_p = 0.55 if number % 3 == 0 else 0.8
    tt: Dict[str, Dict[Tuple[str, str], float]] = {}
    rows = []
    for e in names:
        tt[e] = {}
        for s in stations:
            tp = float(rng.uniform(1.0, 15.0))
            for ph, t in (("P", tp), ("S", tp * float(rng.uniform(1.68, 1.80)))):
                if rng.random() < keep_p:
                    tt[e][(s, ph)] = t
                    rows.append({"event_id": e, "station": s, "phase": ph, "time_s": origins[e] + t,
                                 "weight": float(np.round(rng.uniform(0.1, 1.0), 2)),
                                 "channel": "HHZ" if ph == "P" else "HHN"})
    picks = pd.DataFrame(rows).sample(frac=1.0, random_state=int(rng.integers(0, 2 ** 31)))
    picks.index = rng.permutation(np.arange(500, 500 + len(picks)))
    counts = {}
    for a, b in combinations(sorted(names), 2):
        counts[(a, b)] = sorted(set(tt[a]) & set(tt[b]))
    positive = sorted({len(v) for v in counts.values() if v})
    min_obs = 1 if (number % 4 == 0 or not positive) else positive[len(positive) // 2]

    def keys_for(limit: int) -> set:
        return {(a, b, s, ph) for (a, b), common in counts.items() if len(common) >= max(limit, 1)
                for (s, ph) in common}

    expected = sorted(keys_for(min_obs))
    values = {(a, b, s, ph): tt[a][(s, ph)] - tt[b][(s, ph)] for (a, b, s, ph) in expected}
    arrivals = {(a, b, s, ph): (origins[a] + tt[a][(s, ph)]) - (origins[b] + tt[b][(s, ph)])
                for (a, b, s, ph) in expected}
    return {"picks": picks, "origins": origins, "min_obs": min_obs, "expected": expected, "values": values,
            "arrivals": arrivals, "near": [keys_for(min_obs - 1), keys_for(min_obs + 1), keys_for(1)]}


def _t1_judge(got: Any, case: dict, tol: float) -> Optional[str]:
    if not _is_frame(got) or any(c not in got.columns for c in T1_COLUMNS):
        return "format"
    try:
        e1 = [str(v) for v in got["ev1"]]
        e2 = [str(v) for v in got["ev2"]]
        sta = [str(v) for v in got["station"]]
        ph = [str(v) for v in got["phase"]]
        dt = np.asarray(got["dt_s"], dtype=float)
    except (TypeError, ValueError):
        return "format"
    if any(a >= b for a, b in zip(e1, e2)):
        return "pair-order"
    if np.isnan(dt).any():
        return "nan-rows"
    keys = list(zip(e1, e2, sta, ph))
    if len(set(keys)) != len(keys):
        return "duplicates"
    expected = set(case["expected"])
    if set(keys) != expected:
        return "min-obs" if set(keys) in case["near"] else "rows"
    want = np.array([case["values"][k] for k in keys])
    if not _close(dt, want, tol):
        if _close(dt, -want, tol):
            return "sign"
        if _close(dt, [case["arrivals"][k] for k in keys], 1e-6):
            return "no-origin"
        return "wrong-values"
    if keys != case["expected"] or list(got.index) != list(range(len(got))):
        return "order"
    return None


def check_T1(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    tol = float(crit.get("tol_s", 1e-9))
    rng = ctx.rng
    oks, cats, example = [], [], None
    for k in range(int(crit.get("trials", 12))):
        case = _t1_case(rng, k)
        picks_before = case["picks"].copy(deep=True)
        origins_before = dict(case["origins"])
        got, err = _call(target, case["picks"], case["origins"], case["min_obs"])
        if err is not None:
            raise err
        cat = _t1_judge(got, case, tol)
        if cat is None and (not case["picks"].equals(picks_before) or case["origins"] != origins_before):
            cat = "changed-input"
        oks.append(cat is None)
        if cat:
            cats.append(cat)
            if example is None:
                example = {"inputs": {"events": sorted(case["origins"]), "picks": len(case["picks"]),
                                      "min_obs": case["min_obs"]},
                           "got": (f"{len(got)} rows" if _is_frame(got) else type(got).__name__),
                           "error": f"expected {len(case['expected'])} rows"}
    return outcome_from_cases(np.array(oks), category=_first(cats, T1_PRIORITY), example=example)


# ===================================================================== M41-T2 cross-correlation lag
T2_PRIORITY = ("format", "changed-input", "window", "sign", "no-demean", "not-normalized", "abs-max", "peak-value",
               "edge", "no-refinement", "vertex", "wrong-values")


def _shape(kind: str, t: np.ndarray, f: float, rng_noise: Optional[np.ndarray] = None) -> np.ndarray:
    if kind == "ricker":
        a = (np.pi * f * t) ** 2
        return (1.0 - 2.0 * a) * np.exp(-a)
    if kind == "gabor":
        return np.exp(-(f * t / 1.3) ** 2) * np.cos(2.0 * np.pi * f * t + 0.4)
    # a smooth burst: a sum of Gabor atoms with fixed random phases and frequencies (passed in rng_noise)
    out = np.zeros_like(t)
    for amp, ff, ph in rng_noise:
        out += amp * np.exp(-(f * t / 1.6) ** 2) * np.cos(2.0 * np.pi * ff * t + ph)
    return out


def _t2_case(rng: np.random.Generator, number: int) -> dict:
    dt = float(rng.choice([0.01, 0.005, 0.02]))
    f = float(rng.uniform(0.03, 0.12)) / dt           # 8 to 33 samples per period
    kmax = int(rng.integers(8, 31))
    dur = 4.0 / f
    n = int(2 * kmax + dur / dt + 30)
    t = (np.arange(n) - (n - 1) / 2.0) * dt
    kind = ("ricker", "gabor", "burst")[number % 3]
    atoms = np.column_stack([rng.uniform(0.5, 1.0, 3), f * rng.uniform(0.7, 1.3, 3), rng.uniform(0, 2 * np.pi, 3)])
    variant = number % 6
    if variant == 0:                                  # the true shift lies outside the search window
        tau = float(np.sign(rng.uniform(-1, 1)) * (kmax + rng.uniform(3.2, 6.0)))
    else:
        tau = float(rng.uniform(-0.6, 0.6) * kmax)
    amp_a, amp_b = float(rng.uniform(0.5, 3.0)), float(rng.uniform(0.2, 4.0))
    dc_a, dc_b = float(rng.uniform(-2, 2)), float(rng.uniform(-2, 2))
    a = amp_a * _shape(kind, t, f, atoms) + dc_a
    sign = -1.0 if variant == 3 else 1.0
    b = sign * amp_b * _shape(kind, t - tau * dt, f, atoms) + dc_b
    noisy = variant == 4
    if noisy:
        a = a + rng.normal(0.0, 0.15 * amp_a, n)
        b = b + rng.normal(0.0, 0.15 * amp_b, n)
    max_lag_s = kmax * dt * (1.0 + float(rng.uniform(-1e-12, 1e-12)))
    from obspy.signal.cross_correlation import correlate, xcorr_max

    native = np.asarray(correlate(a, b, kmax, demean=True, normalize="naive", method="direct"), dtype=float)
    cc = native[::-1].copy()                          # contract: positive lag = b later than a
    shift, _value = xcorr_max(native, abs_max=False)
    k_peak = int(round(-float(shift))) + kmax          # index into cc
    if 0 < k_peak < 2 * kmax:
        p = np.polyfit([-1.0, 0.0, 1.0], cc[k_peak - 1:k_peak + 2], 2)
        lag = (k_peak - kmax - p[1] / (2.0 * p[0])) * dt
    else:
        lag = (k_peak - kmax) * dt
    plain = []                                        # the same sums without removing the means
    scale = math.sqrt(float(np.sum(a * a) * np.sum(b * b)))
    for k in range(-kmax, kmax + 1):
        plain.append(float(np.dot(a[:n - k], b[k:]) if k >= 0 else np.dot(a[-k:], b[:n + k])) / scale)
    return {"a": a, "b": b, "dt": dt, "max_lag_s": max_lag_s, "kmax": kmax, "cc": cc, "lag": lag,
            "peak": float(cc[k_peak]), "k_peak": k_peak, "tau_s": tau * dt, "clean": variant in (1, 2, 5),
            "edge": k_peak in (0, 2 * kmax), "plain": np.array(plain), "kind": kind, "n": n}


def _t2_judge(got: Any, case: dict, crit: dict) -> Optional[str]:
    kmax, dt = case["kmax"], case["dt"]
    if not isinstance(got, tuple) or len(got) != 4 or not _real(got[0]) or not _real(got[1]):
        return "format"
    lags = got[2] if isinstance(got[2], np.ndarray) else None
    cc = got[3] if isinstance(got[3], np.ndarray) else None
    if lags is None or cc is None or lags.ndim != 1 or cc.ndim != 1 or lags.shape != cc.shape:
        return "format"
    if lags.size != 2 * kmax + 1 or not _close(lags, np.arange(-kmax, kmax + 1) * dt, 1e-9 * max(1.0, kmax * dt)):
        return "window"
    cc = cc.astype(float)
    tol_cc = float(crit.get("cc_tol", 1e-9))
    if not _close(cc, case["cc"], tol_cc):
        if _close(cc, case["cc"][::-1], tol_cc):
            return "sign"
        if _close(cc, case["plain"], 1e-6):
            return "no-demean"
        ratio = cc / np.where(np.abs(case["cc"]) > 1e-6, case["cc"], np.nan)
        finite = ratio[np.isfinite(ratio)]
        if finite.size and np.allclose(finite, np.median(finite), rtol=1e-6) and abs(np.median(finite) - 1) > 1e-3:
            return "not-normalized"
        return "wrong-values"
    lag, peak = float(got[0]), float(got[1])
    k_abs = int(np.argmax(np.abs(case["cc"])))
    if abs(peak - case["peak"]) > tol_cc:
        if k_abs != case["k_peak"] and abs(abs(peak) - abs(case["cc"][k_abs])) <= 1e-6:
            return "abs-max"
        return "peak-value"
    tol_lag = float(crit.get("lag_tol_s", 1e-9))
    if abs(lag - case["lag"]) > tol_lag:
        if case["edge"]:
            return "edge"
        whole = (case["k_peak"] - kmax) * dt
        if abs(lag - (2.0 * whole - case["lag"])) <= max(tol_lag, 1e-9):
            return "vertex"                           # the parabola's correction applied the wrong way
        if abs(lag + case["lag"]) <= max(tol_lag, 1e-9):
            return "sign"
        if abs(lag - whole) <= 1e-9:
            return "no-refinement"
        return "vertex"
    if case["clean"] and abs(lag - case["tau_s"]) > float(crit.get("truth_tol_samples", 0.1)) * dt:
        return "wrong-values"
    return None


def check_T2(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    rng = ctx.rng
    oks, cats, example = [], [], None
    for k in range(int(crit.get("trials", 24))):
        case = _t2_case(rng, k)
        a0, b0 = case["a"].copy(), case["b"].copy()
        got, err = _call(target, case["a"], case["b"], case["dt"], case["max_lag_s"])
        if err is not None:
            raise err
        cat = _t2_judge(got, case, crit)
        if cat is None and not (np.array_equal(case["a"], a0) and np.array_equal(case["b"], b0)):
            cat = "changed-input"
        oks.append(cat is None)
        if cat:
            cats.append(cat)
            if example is None:
                shown = (round(float(got[0]), 6), round(float(got[1]), 6)) \
                    if isinstance(got, tuple) and len(got) == 4 and _real(got[0]) and _real(got[1]) \
                    else type(got).__name__
                example = {"inputs": {"wavelet": case["kind"], "samples": case["n"], "dt_s": case["dt"],
                                      "max_lag_s": round(case["max_lag_s"], 6),
                                      "b is a copy of a shifted by (s)": round(case["tau_s"], 6)},
                           "got": {"(lag_s, cc_peak)": shown},
                           "error": "the lag or the correlation values do not match"}
    return outcome_from_cases(np.array(oks), category=_first(cats, T2_PRIORITY), example=example)


# ===================================================================== M41-T3 the double-difference system
T3_PRIORITY = ("format", "changed-input", "units", "phase", "column-order", "pair-sign", "derivative-sign",
               "depth-sign", "origin-column", "residual-sign", "wrong-values")


def _t3_case(rng: np.random.Generator, number: int) -> dict:
    n_ev = int(rng.integers(3, 8))
    n_sta = int(rng.integers(4, 12))
    events, stations = _geometry(rng, n_ev, n_sta)
    vp = float(rng.uniform(5.5, 6.5))
    vs = vp / float(rng.uniform(1.68, 1.80))
    obs = _obs_table(rng, n_ev, n_sta, int(rng.integers(15, 40)))
    step = np.column_stack([rng.normal(0.0, 0.05, (n_ev, 3)), rng.normal(0.0, 0.01, n_ev)])
    obs["dt_s"] = _exact_dt(events + step[:, :3], stations, obs, vp, vs, step[:, 3])
    G, d = _fd_system(events, stations, obs, vp, vs)
    # the second-order Taylor remainder of a straight-line time is at most |step|^2 / (v R) per event: a bound
    k = np.asarray(obs["sta"], dtype=int)
    speed = np.where(np.asarray(obs["phase"]) == "P", vp, vs)
    bound = np.zeros(len(obs))
    for col in ("ev1", "ev2"):
        e = np.asarray(obs[col], dtype=int)
        near = np.linalg.norm(events[e] - stations[k], axis=1) - np.linalg.norm(step[e, :3], axis=1)
        bound += np.sum(step[e, :3] ** 2, axis=1) / (speed * near)
    return {"events": events, "stations": stations, "obs": obs, "vp": vp, "vs": vs, "G": G, "d": d,
            "step": step.ravel(), "bound": 2.0 * bound + 1e-9}


def _t3_variants(case: dict) -> Dict[str, Tuple[np.ndarray, np.ndarray]]:
    """The usual slips, built from the case's own G and d (so a student's matrix can be named)."""
    G, d = case["G"], case["d"]
    n_ev = G.shape[1] // 4
    pos = np.zeros(G.shape[1], dtype=bool)
    pos[[4 * e + c for e in range(n_ev) for c in range(3)]] = True
    depth = np.zeros(G.shape[1], dtype=bool)
    depth[[4 * e + 2 for e in range(n_ev)]] = True
    origin = ~pos
    out = {}
    g = G.copy()
    g[:, pos] *= -1.0
    out["derivative-sign"] = (g, d)
    g = G.copy()
    g[:, depth] *= -1.0
    out["depth-sign"] = (g, d)
    out["residual-sign"] = (G, -d)
    g = G.copy()
    g[:, pos] /= 1000.0
    out["units"] = (g, d)
    g = G.copy()
    g[:, pos] *= 1000.0
    out["units-km"] = (g, d)
    g = G.copy()
    g[:, origin] = 0.0
    out["origin-column"] = (g, d)
    g = G.copy()
    g[:, origin] *= -1.0
    out["origin-sign"] = (g, d)
    e2 = np.asarray(case["obs"]["ev2"], dtype=int)
    g = G.copy()
    for r, j in enumerate(e2):
        g[r, 4 * j:4 * j + 4] *= -1.0
    out["pair-sign"] = (g, d)
    g = np.zeros_like(G)                                    # per event: origin time first, then x, y, z
    for e in range(n_ev):
        g[:, 4 * e] = G[:, 4 * e + 3]
        g[:, 4 * e + 1:4 * e + 4] = G[:, 4 * e:4 * e + 3]
    out["column-order"] = (g, d)
    g = np.zeros_like(G)                                    # all x columns, then all y, all z, all t0
    for e in range(n_ev):
        for c in range(4):
            g[:, c * n_ev + e] = G[:, 4 * e + c]
    out["column-order-blocks"] = (g, d)
    return out


def _t3_judge(got: Any, case: dict, crit: dict) -> Optional[str]:
    G, d = case["G"], case["d"]
    if not isinstance(got, tuple) or len(got) != 2:
        return "format"
    g_got = _array(got[0], G.shape)
    d_got = _array(got[1], d.shape)
    if g_got is None or d_got is None:
        return "format"
    tol_g = float(crit.get("deriv_tol", 1e-6))
    tol_d = float(crit.get("d_tol_s", 1e-9))
    if _close(g_got, G, tol_g) and _close(d_got, d, tol_d):
        return None
    for name, (gv, dv) in _t3_variants(case).items():
        if _close(g_got, gv, tol_g) and _close(d_got, dv, tol_d):
            return {"units-km": "units", "origin-sign": "origin-column",
                    "column-order-blocks": "column-order"}.get(name, name)
    # P and S speeds swapped (or vp for every row): compare the system of a medium with other speeds
    for vp, vs in ((case["vs"], case["vp"]), (case["vp"], case["vp"]), (case["vs"], case["vs"])):
        gv, dv = _fd_system(case["events"], case["stations"], case["obs"], vp, vs)
        if _close(g_got, gv, tol_g) or _close(d_got, dv, tol_d):
            return "phase"
    if _close(g_got, G, tol_g):
        return "residual-sign" if _close(d_got, -d, tol_d) else "wrong-values"
    return "wrong-values"


def check_T3(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    rng = ctx.rng
    oks, cats, example = [], [], None
    for k in range(int(crit.get("trials", 10))):
        case = _t3_case(rng, k)
        before = (case["events"].copy(), case["stations"].copy(), case["obs"].copy(deep=True))
        got, err = _call(target, case["events"], case["stations"], case["obs"], case["vp"], case["vs"])
        if err is not None:
            raise err
        cat = _t3_judge(got, case, crit)
        if cat is None and not (np.array_equal(before[0], case["events"]) and
                                np.array_equal(before[1], case["stations"]) and before[2].equals(case["obs"])):
            cat = "changed-input"
        if cat is None:   # truth by construction: G times the known step reproduces d to second order
            g_got, d_got = np.asarray(got[0], dtype=float), np.asarray(got[1], dtype=float)
            if np.any(np.abs(g_got @ case["step"] - d_got) > case["bound"]):
                cat = "wrong-values"
        oks.append(cat is None)
        if cat:
            cats.append(cat)
            if example is None:
                example = {"inputs": {"events": len(case["events"]), "stations": len(case["stations"]),
                                      "observations": len(case["obs"]), "vp": round(case["vp"], 4),
                                      "vs": round(case["vs"], 4)},
                           "got": (f"G {getattr(got[0], 'shape', '?')}, d {getattr(got[1], 'shape', '?')}"
                                   if isinstance(got, tuple) and len(got) == 2 else type(got).__name__),
                           "error": f"expected G of shape {case['G'].shape} and d of shape {case['d'].shape}"}
    return outcome_from_cases(np.array(oks), category=_first(cats, T3_PRIORITY), example=example)


# ===================================================================== M41-T4 damped solve, zero mean shift
T4_PRIORITY = ("format", "changed-input", "no-constraint", "weak-constraint", "no-damping", "damp-squared",
               "wrong-values")


def _t4_case(rng: np.random.Generator, number: int) -> dict:
    n_ev = int(rng.integers(3, 7))
    n_sta = int(rng.integers(6, 12))
    events, stations = _geometry(rng, n_ev, n_sta)
    vp = float(rng.uniform(5.6, 6.4))
    vs = vp / 1.73
    obs = _obs_table(rng, n_ev, n_sta, int(rng.integers(8 * n_ev, 12 * n_ev)), index_offset=False)
    obs["dt_s"] = 0.0
    G, _ = _fd_system(events, stations, obs, vp, vs)
    kind = number % 5
    truth = np.column_stack([rng.normal(0.0, 0.08, (n_ev, 3)), rng.normal(0.0, 0.01, n_ev)])
    if kind != 4:
        truth = truth - truth.mean(axis=0)            # a change with zero mean shift
    truth = truth.ravel()
    d = G @ truth
    if kind in (1, 2, 3):
        d = d + rng.normal(0.0, 0.004, d.size)
    damp = {0: 1.0e-6, 1: 0.0, 2: 0.05, 3: 0.5, 4: 0.01}[kind]
    want = _ns_solve(G, d, damp)
    return {"G": G, "d": d, "damp": damp, "want": want, "truth": truth, "kind": kind}


def _t4_judge(got: Any, case: dict, crit: dict) -> Optional[str]:
    want = case["want"]
    m = _array(got, want.shape)
    if m is None:
        return "format"
    scale = max(1e-3, float(np.max(np.abs(want))))
    tol = float(crit.get("rel_tol", 1e-6)) * scale + 1e-12
    means = m.reshape(-1, 4).mean(axis=0)
    G, d, damp = case["G"], case["d"], case["damp"]
    if np.max(np.abs(means)) > tol:
        free = np.linalg.lstsq(np.vstack([G, damp * np.eye(G.shape[1])]),
                               np.concatenate([d, np.zeros(G.shape[1])]), rcond=None)[0]
        if _close(m, free, 1e-4 * scale):
            return "no-constraint"
        return "weak-constraint"
    if _close(m, want, tol):
        if case["kind"] == 0 and not _close(m, case["truth"], 1e-4 * max(1e-3, np.max(np.abs(case["truth"])))):
            return "wrong-values"
        return None
    if damp > 0:                                      # name the nearest of the usual slips, if one is near
        slips = [("no-damping", 0.0), ("damp-squared", damp * damp), ("damp-squared", math.sqrt(damp))]
        gaps = [(float(np.max(np.abs(m - _ns_solve(G, d, other)))), name) for name, other in slips]
        gap, name = min(gaps)
        if gap <= 1e-4 * scale:
            return name
    return "wrong-values"


def check_T4(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    rng = ctx.rng
    oks, cats, example = [], [], None
    for k in range(int(crit.get("trials", 10))):
        case = _t4_case(rng, k)
        g0, d0 = case["G"].copy(), case["d"].copy()
        got, err = _call(target, case["G"], case["d"], case["damp"])
        if err is not None:
            raise err
        cat = _t4_judge(got, case, crit)
        if cat is None and not (np.array_equal(g0, case["G"]) and np.array_equal(d0, case["d"])):
            cat = "changed-input"
        oks.append(cat is None)
        if cat:
            cats.append(cat)
            if example is None:
                m = np.asarray(got, dtype=float) if isinstance(got, np.ndarray) else None
                example = {"inputs": {"G": list(case["G"].shape), "damp": case["damp"]},
                           "got": ("mean shift (x, y, z, t0) of your answer: "
                                   + str(np.round(m.reshape(-1, 4).mean(axis=0), 6).tolist())
                                   if m is not None and m.size % 4 == 0 else type(got).__name__),
                           "error": "not the damped least-squares solution with zero mean shift"}
    return outcome_from_cases(np.array(oks), category=_first(cats, T4_PRIORITY), example=example)


# ===================================================================== M41-T5 iterate to convergence
T5_PRIORITY = ("format", "changed-input", "own-functions", "sign", "origin-shift", "not-converged", "weights",
               "rms", "wrong-values")


class _Counted:
    """The check's own system or solver, counting how often the student's function calls it."""

    def __init__(self, func: Any) -> None:
        self.func = func
        self.calls = 0

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        return self.func(*args, **kwargs)


def _t5_case(rng: np.random.Generator, number: int) -> dict:
    n_ev = int(rng.integers(4, 8))
    n_sta = int(rng.integers(7, 13))
    truth, stations = _geometry(rng, n_ev, n_sta, spread_km=0.8, radius=(5.0, 60.0))
    vp = float(rng.uniform(5.6, 6.4))
    vs = vp / float(rng.uniform(1.70, 1.78))
    obs = _obs_table(rng, n_ev, n_sta, int(rng.integers(10 * n_ev, 14 * n_ev)))
    shifts = rng.normal(0.0, 0.05, n_ev)
    shifts -= shifts.mean()
    obs["dt_s"] = _exact_dt(truth, stations, obs, vp, vs, shifts)
    weighted = number % 3 == 2
    if weighted:
        w = np.round(rng.uniform(0.2, 1.0, len(obs)), 3)
        bad = rng.random(len(obs)) < 0.2
        w[bad] = 0.0
        obs.loc[obs.index[bad], "dt_s"] += rng.choice([-1.0, 1.0], int(bad.sum())) * rng.uniform(0.2, 0.6,
                                                                                                    int(bad.sum()))
        obs["weight"] = w
    move = rng.normal(0.0, float(rng.uniform(0.1, 0.35)), (n_ev, 3))
    start = truth - (move - move.mean(axis=0))
    n_iter = int(rng.integers(6, 9))
    damp = float(rng.choice([0.0, 1e-4, 1e-3]))
    w_all = obs["weight"].to_numpy(float) if weighted else np.ones(len(obs))
    _, d0 = _fd_system(start, stations, obs, vp, vs)
    rms0 = float(np.sqrt(np.mean((w_all * d0) ** 2)))
    return {"start": start, "stations": stations, "obs": obs, "vp": vp, "vs": vs, "damp": damp,
            "n_iter": n_iter, "truth": truth, "shifts": shifts, "weighted": weighted, "rms0": rms0}


def _t5_judge(got: Any, case: dict, calls: Tuple[int, int], crit: dict) -> Optional[str]:
    n_ev = len(case["truth"])
    if not isinstance(got, tuple) or len(got) != 3:
        return "format"
    pos = _array(got[0], (n_ev, 3))
    shift = _array(got[1], (n_ev,))
    try:
        rms = np.asarray(got[2], dtype=float).ravel()
    except (TypeError, ValueError):
        rms = None
    if pos is None or shift is None or rms is None or rms.size != case["n_iter"] + 1 or not np.isfinite(rms).all():
        return "format"
    if min(calls) < case["n_iter"]:
        return "own-functions"
    tol_km = float(crit.get("pos_tol_km", 1e-5))
    tol_s = float(crit.get("shift_tol_s", 1e-6))
    err_now = float(np.max(np.abs(pos - case["truth"])))
    err_start = float(np.max(np.abs(case["start"] - case["truth"])))
    if err_now > tol_km or float(np.max(np.abs(shift - case["shifts"]))) > tol_s:
        if case["weighted"]:
            return "weights"                          # rows of weight 0 hold wrong times on purpose
        if err_now > err_start:
            return "sign"
        big = np.abs(case["shifts"]) > 0.2 * np.max(np.abs(case["shifts"]))
        if float(np.median(shift[big] / case["shifts"][big])) >= 1.5:
            return "origin-shift"                     # each round added the same origin-time change again
        if rms[-1] < rms[0] and err_now < err_start:
            return "not-converged"
        return "wrong-values"
    if abs(rms[0] - case["rms0"]) > 1e-9 + 1e-6 * case["rms0"] or rms[-1] > float(crit.get("rms_tol_s", 1e-7)):
        return "rms"
    return None


def check_T5(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    rng = ctx.rng
    oks, cats, example = [], [], None
    for k in range(int(crit.get("trials", 6))):
        case = _t5_case(rng, k)
        system, solve = _Counted(_fd_system), _Counted(_ns_solve)
        before = (case["start"].copy(), case["obs"].copy(deep=True))
        got, err = _call(target, case["start"], case["stations"], case["obs"], case["vp"], case["vs"],
                         case["damp"], case["n_iter"], system, solve)
        if err is not None:
            raise err
        cat = _t5_judge(got, case, (system.calls, solve.calls), crit)
        if cat is None and not (np.array_equal(before[0], case["start"]) and before[1].equals(case["obs"])):
            cat = "changed-input"
        oks.append(cat is None)
        if cat:
            cats.append(cat)
            if example is None:
                err_km = (float(np.max(np.abs(np.asarray(got[0], dtype=float) - case["truth"])))
                          if isinstance(got, tuple) and len(got) == 3 and _array(got[0], case["truth"].shape)
                          is not None else None)
                example = {"inputs": {"events": len(case["truth"]), "observations": len(case["obs"]),
                                      "weights": case["weighted"], "n_iter": case["n_iter"], "damp": case["damp"],
                                      "calls of system and solve": [system.calls, solve.calls]},
                           "got": ("largest distance from the true positions: "
                                   f"{err_km:.6f} km" if err_km is not None else type(got).__name__),
                           "error": "the iterations did not land on the positions the data were made from"}
    return outcome_from_cases(np.array(oks), category=_first(cats, T5_PRIORITY), example=example)


# ===================================================================== M41-T6 which run wrote this file?
T6_KEYS = {"who_wrote", "slug", "first", "rerun", "boot", "boot_changed"}
HEX64 = re.compile(r"[0-9a-f]{64}")
T6_PRIORITY = ("format", "bad-line", "cluster", "latest-run", "name-only", "fingerprint", "earliest",
               "wrong-record")
RELOC_KEY = "02.dt.cc/hypoDD.reloc"
DTCC_DIR = "02.dt.cc/"
BOOT_KEY = "02.dt.cc/bootstrap_errors.csv"


def _ts(minutes: int) -> str:
    base = 1_700_000_000 + 60 * minutes
    import datetime as _dt

    return _dt.datetime.fromtimestamp(base, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _t6_scenario(rng: np.random.Generator, root: Path, number: int) -> dict:
    kind = number % 8
    slug = "toy_" + "".join(rng.choice(list("abcdefghijk"), 4))
    other = slug + "_b"
    folder = root / f"case{number}"
    product = f"2.HypoDD/{RELOC_KEY}"
    path = folder / "runs" / slug / product
    path.parent.mkdir(parents=True, exist_ok=True)
    texts = [f"   {200000 + i}  36.{int(rng.integers(1e5, 9e5))}  128.{int(rng.integers(1e5, 9e5))}\n" * 3
             for i in range(3)]
    sha = [hashlib.sha256(t.encode()).hexdigest() for t in texts]
    t0 = int(rng.integers(0, 100000))

    def rec(minute: int, cluster: str, products: Optional[dict], rc: int = 0, through: str = "dtcc") -> dict:
        out = {"ts": _ts(t0 + minute), "end": _ts(t0 + minute + 1), "user": "intern", "command": "pq run",
               "cluster": cluster, "stage_from": through, "through": through, "returncode": rc,
               "log": f"runs/{cluster}/sgtl_logs/{minute}.log"}
        if products is not None:
            out["products"] = products
        return out

    lines: List[str] = []
    records: List[dict] = []
    content = texts[0]
    expected: Optional[int] = 0                      # index into records, or None
    if kind == 0:                                    # the newest run wrote the file
        records = [rec(0, slug, {product: sha[0]}), rec(5, slug, {product: sha[1]})]
        content, expected = texts[1], 1
    elif kind == 1:                                  # an unchanged rerun wrote the same bytes again
        records = [rec(0, slug, {product: sha[0]}), rec(5, slug, {product: sha[0]})]
        expected = 1
    elif kind == 2:                                  # a later run failed and wrote nothing
        records = [rec(0, slug, {product: sha[0]}), rec(5, slug, {}, rc=1)]
    elif kind == 3:                                  # a later run wrote other products only
        records = [rec(0, slug, {product: sha[0]}), rec(5, slug, {"2.HypoDD/01.dt.ct/hypoDD.reloc": sha[2]},
                                                       through="dtct")]
    elif kind == 4:                                  # the file was restored from an old copy
        records = [rec(0, slug, {product: sha[0]}), rec(5, slug, {product: sha[1]})]
    elif kind == 5:                                  # the file was edited after the last run
        records = [rec(0, slug, {product: sha[0]})]
        content, expected = texts[0] + "edited by hand\n", None
    elif kind == 6:                                  # another cluster wrote identical bytes later
        records = [rec(0, slug, {product: sha[0]}), rec(5, other, {product: sha[0]})]
    else:                                            # a broken line and a record without products
        records = [rec(0, slug, {product: sha[0]}), rec(5, slug, None, rc=1)]
    for r in records:
        lines.append(json.dumps(r))
    if kind == 7:
        lines.insert(1, '{"ts": "' + _ts(t0 + 3) + '", "cluster": "' + slug + '", "prod')
        lines.insert(1, "")
    path.write_text(content, encoding="utf-8")
    log = folder / "work" / ".sgtl" / "runs.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"path": path, "log": log, "slug": slug, "records": records, "kind": kind,
            "expected": None if expected is None else records[expected]}


def _t6_judge(got: Any, err: Optional[BaseException], case: dict) -> Optional[str]:
    if err is not None:
        return "bad-line" if case["kind"] == 7 else "format"
    if got is not None and not isinstance(got, dict):
        return "format"
    if got == case["expected"]:
        return None
    records = case["records"]
    if case["kind"] == 5:
        return "fingerprint"
    if got is None:
        return "wrong-record"
    if case["kind"] == 6 and got == records[1]:
        return "cluster"
    if case["kind"] == 4 and got == records[1]:
        return "name-only"
    if case["kind"] == 1 and got == records[0]:
        return "earliest"
    if case["kind"] in (2, 3, 7) and got == records[-1]:
        return "latest-run"
    return "wrong-record"


def _logged(log: Path, slug: str) -> List[dict]:
    out = []
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("cluster") == slug and rec.get("returncode") == 0:
            out.append(rec)
    return out


def _header(path: Path) -> Dict[str, str]:
    try:
        with open(path, encoding="utf-8") as fh:
            first = fh.readline()
    except (OSError, UnicodeDecodeError):
        return {}
    if not first.startswith("# bootstrap_errors"):
        return {}
    return dict(re.findall(r"(\w+)=(\S+)", first))


def _t6_prints(value: Any) -> Optional[Dict[Path, str]]:
    """{copy path: reported fingerprint} of a report entry 'first' or 'rerun', or None when it is malformed."""
    if not isinstance(value, dict) or not value:
        return None
    out: Dict[Path, str] = {}
    for key, sha in value.items():
        if not isinstance(key, (str, os.PathLike)) or not isinstance(sha, str) or not HEX64.fullmatch(sha.lower()):
            return None
        out[Path(key).expanduser()] = sha.lower()
    return out


def _t6_artifacts(target: dict, ctx: Any) -> Tuple[int, Optional[str]]:
    passed = 0
    sets = {key: _t6_prints(target[key]) for key in ("first", "rerun")}
    if any(v is None for v in sets.values()):
        return passed, "format"
    files = {}
    for key in ("boot", "boot_changed"):
        value = target[key]
        if not isinstance(value, (str, os.PathLike)):
            return passed, "format"
        files[key] = Path(value).expanduser()
    every = [p for v in sets.values() for p in v] + list(files.values())
    if not all(p.is_file() for p in every):
        return passed, "copies"
    passed += 1
    actual = {p: _sha256(p) for p in every}
    if any(actual[p] != sha for v in sets.values() for p, sha in v.items()):
        return passed, "fingerprint-claim"         # the report names fingerprints the files do not have
    passed += 1
    slug = target["slug"]
    log = Path(ctx.repo) / "work" / ".sgtl" / "runs.jsonl"
    if not isinstance(slug, str) or not log.is_file():
        return passed, "runs-missing"
    records = _logged(log, slug)
    writes: Dict[str, int] = {}                       # fingerprint -> number of dt.cc runs that wrote it
    relocs = set()                                    # fingerprints logged for the dt.cc relocation itself
    for r in records:
        if r.get("command") == "pq run":
            for k, v in (r.get("products") or {}).items():
                if DTCC_DIR in str(k):
                    writes[v] = writes.get(v, 0) + 1
                if str(k).endswith(RELOC_KEY):
                    relocs.add(v)
    boots = {}
    for r in records:
        if r.get("command") == "pq bootstrap" and r.get("branch") == "dtcc":
            for k, v in (r.get("products") or {}).items():
                if str(k).endswith(BOOT_KEY):
                    boots[v] = (r.get("n"), r.get("seed"))
    if len(relocs) < 1 or len(boots) < 1:
        return passed, "runs-missing"
    passed += 1
    if any(actual[p] not in writes for v in sets.values() for p in v) or \
            actual[files["boot"]] not in boots or actual[files["boot_changed"]] not in boots:
        return passed, "not-run-products"
    reloc_of = {}
    for key, v in sets.items():
        hits = [actual[p] for p in v if actual[p] in relocs]
        if not hits:
            return passed, "no-relocation"
        reloc_of[key] = hits[0]
    passed += 1
    first_paths = {p.resolve() for p in sets["first"]}
    if first_paths & {p.resolve() for p in sets["rerun"]}:
        return passed, "no-rerun"                     # one copy named for both runs
    if reloc_of["first"] == reloc_of["rerun"] and writes[reloc_of["first"]] < 2:
        return passed, "no-rerun"                     # the same bytes twice, but only one run wrote them
    passed += 1
    heads = {key: _header(files[key]) for key in ("boot", "boot_changed")}
    for key, head in heads.items():
        try:
            n_seed = (int(head["n"]), int(head["seed"]))
        except (KeyError, ValueError):
            return passed, "bootstrap-header"
        if head.get("branch") != "dtcc" or tuple(boots[actual[files[key]]]) != n_seed:
            return passed, "bootstrap-header"
    passed += 1
    n_a, seed_a = int(heads["boot"]["n"]), int(heads["boot"]["seed"])
    n_b, seed_b = int(heads["boot_changed"]["n"]), int(heads["boot_changed"]["seed"])
    if n_a != n_b or seed_a == seed_b:
        return passed, "one-change"
    if abs(seed_a - seed_b) < n_a:
        return passed, "overlapping-seeds"
    passed += 1
    return passed, None


def check_T6(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    if not isinstance(target, dict) or set(target) != T6_KEYS or not callable(target.get("who_wrote")) or \
            _t6_prints(target.get("first")) is None or _t6_prints(target.get("rerun")) is None:
        return Outcome(passed=False, n_cases=1, n_failed=1, category="format", message="", details={})
    rng = ctx.rng
    oks, cats, example = [], [], None
    with tempfile.TemporaryDirectory(prefix="sgtl-m41-t6-") as tmp:
        for k in range(max(8, int(crit.get("trials", 8)))):
            case = _t6_scenario(rng, Path(tmp), k)
            try:
                got, err = target["who_wrote"](str(case["path"]), str(case["log"]), case["slug"]), None
            except NotImplementedError:
                raise
            except Exception as exc:  # noqa: BLE001 - classified below
                got, err = None, exc
            cat = _t6_judge(got, err, case)
            oks.append(cat is None)
            if cat:
                cats.append(cat)
                if example is None:
                    example = {"inputs": {"log lines": len(case["log"].read_text().splitlines()),
                                          "cluster": case["slug"], "scenario": case["kind"]},
                               "got": (got.get("ts") if isinstance(got, dict) else
                                       (type(err).__name__ if err is not None else repr(got))),
                               "error": "expected " + ("None" if case["expected"] is None else
                                                       f"the record that started at {case['expected']['ts']}")}
    category = _first(cats, T6_PRIORITY)
    if category is not None:
        return outcome_from_cases(np.array(oks), category=category, example=example)
    passed, cat = _t6_artifacts(target, ctx)
    steps = 7
    ok = np.array(oks + [True] * passed + [False] * (steps - passed if cat else 0), dtype=bool)
    note = ("The check recomputed the SHA-256 fingerprints of your copied files, compared them with the ones in your "
            "report and with the ones sgtl logged for your runs in work/.sgtl/runs.jsonl, and read the first line of "
            "your two bootstrap tables; it never prints a location or an error value.")
    return outcome_from_cases(ok, category=cat, real_data=True, note=note)
