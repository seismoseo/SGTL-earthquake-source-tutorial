"""Checkers for M52 · Synthetic seismograms.

Where the truth comes from (DESIGN.md section 1, rule 1):

* M52-T1: an independent library. pyrocko's ``MomentTensor(strike, dip, rake, scalar_moment)``: ``m()`` (north,
  east, down) and ``m_up_south_east()``. The student may not use pyrocko, MTUQ, obspy.imaging or PyFK.
* M52-T2: construction: magnitudes and moments drawn by the check, related by the formula of the module (the
  IASPEI form of Hanks and Kanamori's definition).
* M52-T3: an independent library. ObsPy's ``obspy.imaging.source.farfield`` (Aki and Richards eq. 4.29, far-field
  vectors) for pyrocko's tensor, read along the ray (P) and along the two S directions that the contract defines.
  ObsPy's S vector is (gamma gamma^T - I) M gamma, the negative of the S term of eq. 4.29 (it leaves out the minus
  sign in front, which a pattern plot does not need); the check negates it.
  Rays in the nodal planes and along the T and P axes come from the eigenvectors of that tensor (numpy.linalg.eigh),
  so the zeros and the +1/-1 hold by construction.
* M52-T4: the same two libraries: ObsPy's far-field P and S vectors of pyrocko's tensor, delayed by the travel times
  and scaled by 1 / (4 pi rho v^3 r), with the moment rate interpolated as the contract says.
* M52-T5: construction. The check's ``run`` stands in for PyFK: it reads a four-number double-couple source the
  way PyFK's SourceModel does and hands out samples of the same kind and unit as PyFK's calculate_sync, built from
  made-up Green's functions written as formulas. The truth is the made-up ground displacement in metres for the
  student's moment.
* M52-T6: construction, then the student's own products. Made-up records are exact shifted and scaled copies of
  made-up synthetics (continuous formulas sampled at 100 Hz), turned from R, T into N, E with ObsPy's rotate_rt_ne,
  with out-of-band disturbances and a burst outside the window; the check hands the student's function a
  correlation built on ObsPy's ``correlate``. On the Sangju data the check reruns the student's station_fit with the
  student's xcorr_lag (verified first on made-up shifts) on the student's records (response removed by ObsPy with
  the values written in the student's table) and the student's PyFK run, and compares with the student's table.
  The two R3 runs written into the table (the unchanged rerun and the run with one changed velocity model) are
  read back: their SHA-256 fingerprints are recomputed from the files, their requests compared with the first run's,
  and the second model's rows recomputed like the first. It prints no real-data value.

Failure categories are keys of ``checks/specs/M52.yaml``; the engine prints their fixed messages.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import math
import numbers
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import Outcome, outcome_from_cases

__all__ = ["check_T1", "check_T2", "check_T3", "check_T4", "check_T5", "check_T6"]

KMA_EVENT = "2019009762"                     # the ML 3.9 Sangju earthquake of 21 July 2019 (KMA catalog)
KIGAM_A = (288.0, 89.0, 7.0)                 # KIGAM (2021), KEMS-2019-062: plane A (strike, dip, rake)
KIGAM_B = (198.0, 83.0, 179.0)               # and plane B
KIGAM_MW_Q = 3.8                             # its moment magnitude
KIGAM_DEPTH_Q = 12.8                         # its depth (km)
DYNE_DECADES = 7.0                           # 1 N m = 1e7 dyne-cm


# ------------------------------------------------------------------------------------------- helpers
def _call(func: Any, *args: Any, **kwargs: Any) -> Tuple[Any, Optional[BaseException]]:
    """Run the student's code. NotImplementedError passes through (the engine reports NOT STARTED)."""
    try:
        return func(*args, **kwargs), None
    except NotImplementedError:
        raise
    except Exception as exc:  # noqa: BLE001 - classified by the caller
        return None, exc


def _real(value: Any) -> bool:
    return isinstance(value, numbers.Real) and not isinstance(value, (bool, np.bool_))


def _first(cats: Sequence[Optional[str]], priority: Sequence[str]) -> Optional[str]:
    present = {c for c in cats if c}
    return next((c for c in priority if c in present), None)


def _pyrocko_mt(strike: float, dip: float, rake: float, m0: float):
    from pyrocko import moment_tensor as pmt

    return pmt.MomentTensor(strike=float(strike), dip=float(dip), rake=float(rake), scalar_moment=float(m0))


def _ned(strike: float, dip: float, rake: float, m0: float) -> np.ndarray:
    return np.asarray(_pyrocko_mt(strike, dip, rake, m0).m(), dtype=float)


def _close(got: np.ndarray, want: np.ndarray, tol: float) -> bool:
    return bool(got.shape == want.shape and np.all(np.isfinite(got)) and np.all(np.abs(got - want) <= tol))


def _farfield(mt_ned: np.ndarray, gammas: np.ndarray, kind: str) -> np.ndarray:
    """ObsPy's far-field vectors for unit rays gammas (3, n), in the tensor's frame.

    P: gamma (gamma.M.gamma). S: (gamma gamma^T - I) M gamma, which is the far-field S term of Aki and Richards
    eq. 4.29 WITHOUT its leading minus sign (ObsPy draws patterns, where the sign does not matter); callers negate
    it to get the displacement direction."""
    from obspy.imaging.source import farfield

    six = [mt_ned[0, 0], mt_ned[1, 1], mt_ned[2, 2], mt_ned[0, 1], mt_ned[0, 2], mt_ned[1, 2]]
    return np.asarray(farfield(six, np.asarray(gammas, dtype=float), kind), dtype=float)


def _ray(takeoff_deg: np.ndarray, azimuth_deg: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The ray and the two S directions of the contract (north-east-down), each (3, n)."""
    i, f = np.radians(takeoff_deg), np.radians(azimuth_deg)
    gamma = np.array([np.sin(i) * np.cos(f), np.sin(i) * np.sin(f), np.cos(i)])
    e_sv = np.array([np.cos(i) * np.cos(f), np.cos(i) * np.sin(f), -np.sin(i)])
    e_sh = np.array([-np.sin(f), np.cos(f), np.zeros_like(f)])
    return gamma, e_sv, e_sh


def _angles_of(gamma: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    g = gamma / np.linalg.norm(gamma, axis=0)
    takeoff = np.degrees(np.arccos(np.clip(g[2], -1.0, 1.0)))
    azimuth = np.degrees(np.arctan2(g[1], g[0])) % 360.0
    return takeoff, azimuth


def _oracle_patterns(strike: float, dip: float, rake: float, takeoff: np.ndarray,
                     azimuth: np.ndarray) -> np.ndarray:
    """(3, n): R^P, R^SV, R^SH from ObsPy's far-field vectors of pyrocko's tensor (M0 = 1)."""
    mt = _ned(strike, dip, rake, 1.0)
    gamma, e_sv, e_sh = _ray(np.ravel(takeoff), np.ravel(azimuth))
    u_p = _farfield(mt, gamma, "P")
    u_s = -_farfield(mt, gamma, "S")                   # ObsPy's S vector has the opposite sign (see _farfield)
    return np.array([np.sum(gamma * u_p, axis=0), np.sum(e_sv * u_s, axis=0), np.sum(e_sh * u_s, axis=0)])


# =========================================================================================== M52-T1
T1_PRIORITY = ("format", "frame-name", "not-symmetric", "degrees", "scale", "sign", "frame", "wrong-values")


def _t1_cases(rng: np.random.Generator, n: int) -> List[dict]:
    fixed = [(30.0, 50.0, 70.0), (0.0, 90.0, 0.0), (0.0, 45.0, 90.0), (120.0, 0.0, 0.0), (300.0, 90.0, 180.0),
             (75.0, 30.0, -90.0), (210.0, 60.0, -150.0), (359.0, 89.0, 1.0)]
    cases = []
    for k in range(n):
        if k < len(fixed):
            s, d, r = fixed[k]
        else:
            s, d, r = rng.uniform(0.0, 360.0), rng.uniform(0.0, 90.0), rng.uniform(-180.0, 180.0)
        cases.append({"angles": (float(s), float(d), float(r)), "m0": float(10.0 ** rng.uniform(9.0, 20.0))})
    return cases


def _t1_judge(got: Any, want: np.ndarray, case: dict, frame: str, rel: float) -> Optional[str]:
    if not isinstance(got, np.ndarray) or got.shape != (3, 3):
        return "format"
    try:
        g = got.astype(float)
    except (TypeError, ValueError):
        return "format"
    if not np.all(np.isfinite(g)):
        return "format"
    m0 = case["m0"]
    tol = rel * m0
    if _close(g, want, tol):
        return None
    if not np.allclose(g, g.T, atol=tol):
        return "not-symmetric"
    s, d, r = case["angles"]
    radian_like = _ned(np.degrees(s), np.degrees(d), np.degrees(r), m0)
    if frame == "USE":
        radian_like = np.asarray(_pyrocko_mt(np.degrees(s), np.degrees(d), np.degrees(r), m0).m_up_south_east())
    if _close(g, radian_like, tol):
        return "degrees"
    scale = float(np.sum(g * want) / max(np.sum(want * want), 1e-300))
    if abs(scale - 1.0) > 1e-3 and _close(g, scale * want, tol * max(1.0, abs(scale))):
        return "scale"
    if _close(np.abs(g), np.abs(want), tol):
        return "sign"
    return "wrong-values"


def check_T1(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    rel = float(crit.get("rel_tol", 1e-6))
    cases = _t1_cases(ctx.rng, int(crit.get("trials", 40)))
    oks: List[bool] = []
    cats: List[Optional[str]] = []
    example = None
    ned_ok = []
    for case in cases:
        s, d, r = case["angles"]
        mt = _pyrocko_mt(s, d, r, case["m0"])
        for frame, want in (("NED", np.asarray(mt.m(), dtype=float)),
                            ("USE", np.asarray(mt.m_up_south_east(), dtype=float))):
            got, err = _call(target, s, d, r, case["m0"], frame=frame)
            cat = "format" if err is not None else _t1_judge(got, want, case, frame, rel)
            if frame == "NED":
                ned_ok.append(cat is None)
            oks.append(cat is None)
            cats.append(cat)
            if cat and example is None:
                example = {"inputs": {"strike_deg": round(s, 3), "dip_deg": round(d, 3), "rake_deg": round(r, 3),
                                      "m0_nm": f"{case['m0']:.4g}", "frame": frame},
                           "got": (f"{type(err).__name__}: {err}" if err is not None else
                                   np.round(np.asarray(got, dtype=float) / case["m0"], 4).tolist()
                                   if isinstance(got, np.ndarray) and got.shape == (3, 3) else repr(got)[:120]),
                           "error": "expected (in units of m0_nm) "
                                    f"{np.round(want / case['m0'], 4).tolist()}"}
    if all(ned_ok) and any(c and c != "format" for c in cats):
        cats = ["frame" if c and c != "format" else c for c in cats]
    _, bad_err = _call(target, 10.0, 20.0, 30.0, 1.0e12, frame="ENU")
    if bad_err is None or not isinstance(bad_err, ValueError):
        oks.append(False)
        cats.append("frame-name")
    category = _first(cats, T1_PRIORITY)
    return outcome_from_cases(oks, category=category, example=example)


# =========================================================================================== M52-T2
T2_PRIORITY = ("arguments", "format", "natural-log", "dyne-cm", "constant", "factor", "rounded", "wrong-values")


def _mw_of(m0: np.ndarray, constant: float = 9.1) -> np.ndarray:
    return (2.0 / 3.0) * (np.log10(m0) - constant)


def _t2_values(got: Any, scalar: bool, shape: Tuple[int, ...]) -> Optional[np.ndarray]:
    if scalar:
        return np.array([float(got)]) if _real(got) and math.isfinite(float(got)) else None
    if not isinstance(got, np.ndarray) or got.shape != shape:
        return None
    try:
        out = got.astype(float).ravel()
    except (TypeError, ValueError):
        return None
    return out if np.all(np.isfinite(out)) else None


def _t2_judge_mw(values: np.ndarray, m0: np.ndarray, tol: float) -> Optional[str]:
    truth = _mw_of(m0)
    if np.all(np.abs(values - truth) <= tol):
        return None
    near = lambda alt: bool(np.all(np.abs(values - alt) <= max(tol, 1e-6)))  # noqa: E731
    if near((2.0 / 3.0) * (np.log(m0) - 9.1)):
        return "natural-log"
    if near(truth + DYNE_DECADES * 2.0 / 3.0) or near(truth - DYNE_DECADES * 2.0 / 3.0):
        return "dyne-cm"
    if near(_mw_of(m0, 9.05)):
        return "constant"
    if near(1.5 * (np.log10(m0) - 9.1)):
        return "factor"
    if np.all(np.abs(values - truth) <= 0.051) and np.allclose(values, np.round(values, 2), atol=1e-12):
        return "rounded"
    return "wrong-values"


def _t2_judge_m0(values: np.ndarray, mw: np.ndarray, rel: float) -> Optional[str]:
    truth = 10.0 ** (1.5 * mw + 9.1)
    if np.all(np.abs(values - truth) <= rel * truth):
        return None
    near = lambda alt: bool(np.all(np.abs(values - alt) <= max(rel, 1e-6) * np.abs(alt)))  # noqa: E731
    if near(np.exp(1.5 * mw + 9.1)):
        return "natural-log"
    if near(truth * 10.0 ** DYNE_DECADES) or near(truth / 10.0 ** DYNE_DECADES):
        return "dyne-cm"
    if near(10.0 ** (1.5 * mw + 9.05)):
        return "constant"
    if near(10.0 ** ((2.0 / 3.0) * mw + 9.1)):
        return "factor"
    if np.all(np.abs(np.log10(np.abs(values) + 1e-300) - np.log10(truth)) <= 0.05):
        return "rounded"
    return "wrong-values"


def check_T2(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    n = int(crit.get("trials", 300))
    tol_mw = float(crit.get("abs_tol_mw", 1e-9))
    rel_m0 = float(crit.get("rel_tol_m0", 1e-9))
    rng = ctx.rng
    oks: List[bool] = []
    cats: List[Optional[str]] = []
    example = None
    for kwargs in ({"mw": 3.0, "m0_nm": 1.0e14}, {}):
        _, err = _call(target, **kwargs)
        good = isinstance(err, ValueError)
        oks.append(good)
        cats.append(None if good else "arguments")
    m0_all = 10.0 ** rng.uniform(6.0, 23.0, n)
    mw_all = rng.uniform(-2.0, 9.5, n)
    for direction, values_in in (("m0_nm", m0_all), ("mw", mw_all)):
        chunks = [(float(v), True, ()) for v in values_in[:20]]
        rest = values_in[20:]
        shapes = [(rest.size // 2,), (2, (rest.size - rest.size // 2) // 2)]
        start = 0
        for shape in shapes:
            size = int(np.prod(shape))
            chunks.append((rest[start:start + size].reshape(shape).copy(), False, shape))
            start += size
        for value, scalar, shape in chunks:
            got, err = _call(target, **{direction: value})
            if err is not None:
                vals = None
            else:
                vals = _t2_values(got, scalar, shape)
            if vals is None:
                cat = "format"
            elif direction == "m0_nm":
                cat = _t2_judge_mw(vals, np.ravel(value), tol_mw)
            else:
                cat = _t2_judge_m0(vals, np.ravel(value), rel_m0)
            oks.append(cat is None)
            cats.append(cat)
            if cat and example is None:
                show = float(np.ravel(value)[0])
                truth = _mw_of(np.array([show]))[0] if direction == "m0_nm" else 10.0 ** (1.5 * show + 9.1)
                example = {"inputs": {direction: f"{show:.6g}" + ("" if scalar else f" (first of an array {shape})")},
                           "got": (f"{type(err).__name__}: {err}" if err is not None else
                                   f"{float(np.ravel(got)[0]):.6g}" if vals is not None else repr(got)[:100]),
                           "error": f"expected {truth:.6g}"}
    return outcome_from_cases(oks, category=_first(cats, T2_PRIORITY), example=example)


# =========================================================================================== M52-T3
T3_PRIORITY = ("format", "degrees", "takeoff", "strike", "nodal", "swapped", "sv-sign", "sh-sign", "wrong-values")


def _t3_rays(rng: np.random.Generator, mech: Tuple[float, float, float], n: int) -> Tuple[np.ndarray, np.ndarray,
                                                                                           np.ndarray]:
    """Takeoff angles, azimuths and a kind per ray: 0 random, 1 in a nodal plane, 2 T axis, 3 P axis."""
    mt = _ned(*mech, 1.0)
    vals, vecs = np.linalg.eigh(mt)                    # ascending: P axis (-1), null axis (0), T axis (+1)
    p_ax, b_ax, t_ax = vecs[:, 0], vecs[:, 1], vecs[:, 2]
    rays, kinds = [], []
    for sign in (1.0, -1.0):
        normal = (t_ax + sign * p_ax) / math.sqrt(2.0)
        inside = np.cross(normal, b_ax)
        for angle in rng.uniform(0.0, 2.0 * math.pi, 3):
            rays.append(math.cos(angle) * b_ax + math.sin(angle) * inside)
            kinds.append(1)
    rays += [t_ax, -t_ax, p_ax]
    kinds += [2, 2, 3]
    while len(rays) < n:
        v = rng.normal(size=3)
        rays.append(v / np.linalg.norm(v))
        kinds.append(0)
    gam = np.array(rays).T
    takeoff, azimuth = _angles_of(gam)
    return takeoff, azimuth, np.array(kinds)


def _t3_tuple(got: Any, scalar: bool, shape: Tuple[int, ...]) -> Optional[np.ndarray]:
    if not isinstance(got, tuple) or len(got) != 3:
        return None
    rows = []
    for part in got:
        if scalar:
            if not _real(part):
                return None
            rows.append(np.array([float(part)]))
        else:
            if not isinstance(part, np.ndarray) or part.shape != shape:
                return None
            try:
                rows.append(part.astype(float).ravel())
            except (TypeError, ValueError):
                return None
    out = np.array(rows)
    return out if np.all(np.isfinite(out)) else None


def _t3_judge(vals: np.ndarray, mech: Tuple[float, float, float], take: np.ndarray, az: np.ndarray,
              kinds: np.ndarray, tol: float) -> Optional[str]:
    truth = _oracle_patterns(*mech, take, az)
    if np.all(np.abs(vals - truth) <= tol):
        return None
    near = lambda a, b: bool(np.all(np.abs(a - b) <= max(tol, 1e-6)))  # noqa: E731
    if near(vals, _oracle_patterns(*np.degrees(mech), np.degrees(take), np.degrees(az))):
        return "degrees"
    p_ok = near(vals[0], truth[0])
    if not p_ok:
        for alt_take in (180.0 - take, 90.0 - take, take - 90.0):
            if near(vals[0], _oracle_patterns(*mech, alt_take, az)[0]):
                return "takeoff"
        if near(vals[0], _oracle_patterns(0.0, mech[1], mech[2], take, az)[0]):
            return "strike"
        return "nodal" if np.any(kinds > 0) and not near(vals[0][kinds > 0], truth[0][kinds > 0]) else \
            "wrong-values"
    if near(vals[1], truth[2]) and near(vals[2], truth[1]):
        return "swapped"
    if near(vals[1], -truth[1]) and near(vals[2], truth[2]):
        return "sv-sign"
    if near(vals[2], -truth[2]) and near(vals[1], truth[1]):
        return "sh-sign"
    return "wrong-values"


def check_T3(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    n_faults = int(crit.get("trials", 30))
    n_rays = int(crit.get("rays_per_fault", 50))
    tol = float(crit.get("abs_tol", 1e-7))
    rng = ctx.rng
    fixed = [(0.0, 90.0, 0.0), (30.0, 50.0, 70.0), (0.0, 45.0, 90.0), (250.0, 20.0, -90.0)]
    oks: List[bool] = []
    cats: List[Optional[str]] = []
    example = None
    for k in range(n_faults):
        mech = fixed[k] if k < len(fixed) else (float(rng.uniform(0, 360)), float(rng.uniform(1, 89)),
                                                float(rng.uniform(-180, 180)))
        take, az, kinds = _t3_rays(rng, mech, n_rays)
        if k % 3 == 2:                                  # one ray at a time, as numbers
            for j in range(0, n_rays, 7):
                got, err = _call(target, *mech, float(take[j]), float(az[j]))
                vals = None if err is not None else _t3_tuple(got, True, ())
                cat = "format" if vals is None else _t3_judge(vals, mech, take[j:j + 1], az[j:j + 1],
                                                              kinds[j:j + 1], tol)
                oks.append(cat is None)
                cats.append(cat)
            continue
        shape = (n_rays,) if k % 3 == 0 else (5, n_rays // 5)
        size = int(np.prod(shape))
        t_in, a_in = take[:size].reshape(shape).copy(), az[:size].reshape(shape).copy()
        got, err = _call(target, *mech, t_in, a_in)
        vals = None if err is not None else _t3_tuple(got, False, shape)
        cat = "format" if vals is None else _t3_judge(vals, mech, take[:size], az[:size], kinds[:size], tol)
        oks.append(cat is None)
        cats.append(cat)
        if cat and example is None:
            truth = _oracle_patterns(*mech, take[:1], az[:1])[:, 0]
            example = {"inputs": {"strike, dip, rake": [round(v, 3) for v in mech],
                                  "takeoff_deg": round(float(take[0]), 3), "azimuth_deg": round(float(az[0]), 3)},
                       "got": (f"{type(err).__name__}: {err}" if err is not None else
                               np.round(vals[:, 0], 5).tolist() if vals is not None else repr(got)[:120]),
                       "error": f"expected (rp, rsv, rsh) = {np.round(truth, 5).tolist()} for the first ray"}
    return outcome_from_cases(oks, category=_first(cats, T3_PRIORITY), example=example)


# =========================================================================================== M52-T4
T4_PRIORITY = ("format", "changed-input", "units", "spreading", "speed-power", "missing-wave", "direction",
               "moment-not-rate", "timing", "wrong-values")


def _pulse(kind: str, duration: float, dt: float) -> np.ndarray:
    n = max(int(round(duration / dt)), 2) + 1
    x = np.linspace(0.0, 1.0, n)
    if kind == "hann":
        shape = np.sin(np.pi * x) ** 2
    elif kind == "triangle":
        shape = 1.0 - np.abs(2.0 * x - 1.0)
    else:
        shape = np.ones(n)
        shape[0] = shape[-1] = 0.0
    return shape / (shape.sum() * dt)


def _t4_cases(rng: np.random.Generator, n: int) -> List[dict]:
    cases = []
    for k in range(n):
        direction = rng.normal(size=3)
        if k == 0:
            direction = np.array([1.0, 1.0, 0.0])
        elif k == 1:
            direction = np.array([0.0, 0.0, 1.0])
        elif k == 2:
            direction = np.array([0.1, -0.2, -1.0])
        direction = direction / np.linalg.norm(direction)
        dist = float(10.0 ** rng.uniform(0.0, math.log10(200.0)))
        vp = float(rng.uniform(3.0, 8.0))
        vs = vp / float(rng.uniform(1.6, 2.0))
        stf_dt = float(rng.choice([0.005, 0.01, 0.02, 0.05]))
        duration = float(rng.uniform(0.2, 3.0))
        t_dt = float(rng.choice([0.005, 0.01, 0.02, 0.025]))
        t_end = dist / vs + duration + 2.0
        cases.append({"offset": direction * dist, "mech": (float(rng.uniform(0, 360)), float(rng.uniform(1, 89)),
                                                           float(rng.uniform(-180, 180))),
                      "m0": float(10.0 ** rng.uniform(10.0, 18.0)), "vp": vp, "vs": vs,
                      "rho": float(rng.uniform(2000.0, 3300.0)), "stf_dt": stf_dt,
                      "stf": _pulse(("hann", "triangle", "boxcar")[k % 3], duration, stf_dt),
                      "t": np.arange(-0.5, t_end, t_dt)})
    return cases


def _t4_parts(case: dict, stf: Optional[np.ndarray] = None, delays: Optional[Tuple[float, float]] = None):
    """P part and S part (each (3, n), m) of the far-field displacement, from ObsPy's vectors of pyrocko's tensor."""
    xyz = np.asarray(case["offset"], dtype=float) * 1000.0
    dist_m = math.sqrt(float(xyz @ xyz))
    gamma = (xyz / dist_m).reshape(3, 1)
    mt = _ned(*case["mech"], case["m0"])
    u_p = _farfield(mt, gamma, "P")[:, 0]
    u_s = -_farfield(mt, gamma, "S")[:, 0]
    alpha, beta = case["vp"] * 1000.0, case["vs"] * 1000.0
    pulse = case["stf"] if stf is None else stf
    pulse_t = np.arange(pulse.size) * case["stf_dt"]
    tp, ts = (dist_m / alpha, dist_m / beta) if delays is None else delays
    late_p = np.interp(case["t"] - tp, pulse_t, pulse, left=0.0, right=0.0)
    late_s = np.interp(case["t"] - ts, pulse_t, pulse, left=0.0, right=0.0)
    p_part = np.outer(u_p, late_p) / (4.0 * np.pi * case["rho"] * alpha ** 3 * dist_m)
    s_part = np.outer(u_s, late_s) / (4.0 * np.pi * case["rho"] * beta ** 3 * dist_m)
    return p_part, s_part, dist_m


def _fit_two(got: np.ndarray, a: np.ndarray, b: np.ndarray) -> Tuple[float, float, float]:
    """Least-squares got ~ x a + y b; returns (x, y, relative residual)."""
    cols = np.array([a.ravel(), b.ravel()]).T
    scale = np.abs(cols).max(axis=0)
    scale[scale == 0] = 1.0
    coef, *_ = np.linalg.lstsq(cols / scale, got.ravel(), rcond=None)
    coef = coef / scale
    resid = np.linalg.norm(got.ravel() - cols @ coef) / max(np.linalg.norm(got.ravel()), 1e-300)
    return float(coef[0]), float(coef[1]), float(resid)


def _t4_judge(got: Any, case: dict, rel: float) -> Optional[str]:
    n = case["t"].size
    if not isinstance(got, np.ndarray) or got.shape != (3, n):
        return "format"
    try:
        g = got.astype(float)
    except (TypeError, ValueError):
        return "format"
    if not np.all(np.isfinite(g)):
        return "format"
    p_part, s_part, r = _t4_parts(case)
    truth = p_part + s_part
    peak = np.abs(truth).max()
    if np.all(np.abs(g - truth) <= rel * peak + 1e-300):
        return None
    x, y, resid = _fit_two(g, p_part, s_part)
    if resid < 1e-3:
        def is_power(v: float, base: float) -> bool:
            if v <= 0:
                return False
            k = math.log(v) / math.log(base)
            return abs(k - round(k)) < 1e-3 and round(k) != 0
        if abs(x) < 1e-6 * max(abs(y), 1e-300) or abs(y) < 1e-6 * max(abs(x), 1e-300):
            return "missing-wave"
        if x < 0 or y < 0:
            return "direction"
        if abs(x / y - 1.0) < 1e-3:
            if is_power(x, 1000.0):
                return "units"
            if abs(x * r - 1.0) < 1e-3 or abs(x / r - 1.0) < 1e-3 or is_power(x, r / 1000.0):
                return "spreading"
            return "wrong-values"
        return "speed-power"
    step = np.cumsum(case["stf"]) * case["stf_dt"]
    p_m, s_m, _ = _t4_parts(case, stf=step)
    _, _, resid_m = _fit_two(g, p_m, s_m)
    if resid_m < 1e-2:
        return "moment-not-rate"
    down, swap = np.diag([1.0, 1.0, -1.0]), np.eye(3)[[1, 0, 2]]
    for flip in (down, swap, down @ swap):
        if np.all(np.abs(flip @ g - truth) <= max(rel, 1e-3) * peak):
            return "direction"
    for delays in ((0.0, 0.0), (r / (case["vs"] * 1000.0), r / (case["vp"] * 1000.0))):
        p_d, s_d, _ = _t4_parts(case, delays=delays)
        if _fit_two(g, p_d, s_d)[2] < 1e-2:
            return "timing"
    if np.abs(g).max() < 1e-6 * peak:
        return "missing-wave"
    return "wrong-values"


def check_T4(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    rel = float(crit.get("rel_tol", 1e-6))
    oks: List[bool] = []
    cats: List[Optional[str]] = []
    example = None
    for case in _t4_cases(ctx.rng, int(crit.get("trials", 20))):
        keep = (case["t"].copy(), case["offset"].copy(), case["stf"].copy())
        got, err = _call(target, case["t"], case["offset"], case["mech"], case["m0"], case["stf"], case["stf_dt"],
                         case["vp"], case["vs"], case["rho"])
        if err is not None:
            cat = "format"
        elif not (np.array_equal(keep[0], case["t"]) and np.array_equal(keep[1], case["offset"])
                  and np.array_equal(keep[2], case["stf"])):
            cat = "changed-input"
        else:
            cat = _t4_judge(got, case, rel)
        oks.append(cat is None)
        cats.append(cat)
        if cat and example is None:
            p_part, s_part, r = _t4_parts(case)
            truth = p_part + s_part
            j = int(np.argmax(np.abs(truth).max(axis=0)))
            example = {"inputs": {"offset_km": np.round(case["offset"], 3).tolist(),
                                  "mechanism": [round(v, 2) for v in case["mech"]], "m0_nm": f"{case['m0']:.4g}",
                                  "vp, vs, rho": [round(case["vp"], 3), round(case["vs"], 3), round(case["rho"], 1)],
                                  "pulse": f"{case['stf'].size} samples at {case['stf_dt']} s"},
                       "got": (f"{type(err).__name__}: {err}" if err is not None else
                               f"at t = {case['t'][j]:.3f} s: "
                               f"{np.round(np.asarray(got, dtype=float)[:, j], 12).tolist()}"
                               if isinstance(got, np.ndarray) and got.shape == truth.shape else repr(got)[:120]),
                       "error": f"expected {np.round(truth[:, j], 12).tolist()} m there"}
    return outcome_from_cases(oks, category=_first(cats, T4_PRIORITY), example=example)


# =========================================================================================== M52-T5
T5_PRIORITY = ("format", "not-finite", "source-angles", "moment-units", "magnitude", "rescaled-samples",
               "derivative", "time-step", "factor-100", "start", "wrong-values")


def _t5_shapes(rng: np.random.Generator, t: np.ndarray, n_rec: int) -> Tuple[np.ndarray, np.ndarray]:
    """Two made-up arrays of shape (3, n_rec, n): the goal shapes and the shapes the stand-in hands out."""
    goal = np.zeros((3, n_rec, t.size))
    fed = np.zeros_like(goal)
    span = t[-1] - t[0]
    dt = t[1] - t[0]
    for c in range(3):                                  # smooth shapes, many samples wide
        for k in range(n_rec):
            onset = t[0] + span * rng.uniform(0.1, 0.25)
            rise = dt * rng.uniform(60.0, 150.0)
            static = rng.uniform(-1.0, 1.0) * 1e-3
            x = np.clip((t - onset) / rise, 0.0, 1.0)
            goal[c, k] += static * (1.0 - np.cos(np.pi * x)) / 2.0
            fed[c, k] += np.where((t > onset) & (t < onset + rise),
                                  static * np.pi * np.sin(np.pi * x) / (2.0 * rise), 0.0)
            center = onset + rise + dt * rng.uniform(100.0, 250.0)
            width = dt * rng.uniform(60.0, 100.0)
            amp = rng.uniform(-1.0, 1.0) * 2e-3
            z = (t - center) / width
            goal[c, k] += amp * z * np.exp(-z * z)
            fed[c, k] += amp * (1.0 - 2.0 * z * z) * np.exp(-z * z) / width
    return goal, fed


class _FakePyFK:
    """Stand-in for PyFK's calculate_sync with a four-number double-couple source (made-up Green's functions)."""

    def __init__(self, goal: np.ndarray, fed: np.ndarray, dt: float, angles: Tuple[float, float, float],
                 one: bool) -> None:
        self.goal, self.fed, self.dt, self.angles, self.one = goal, fed, dt, angles, one
        self.calls: List[Any] = []

    def factor(self, angles: Sequence[float]) -> np.ndarray:
        s, d, r = np.radians(np.asarray(angles, dtype=float))
        return np.array([1.2 + math.cos(s) * math.sin(d), 0.8 + math.sin(r) ** 2, 1.0 + math.cos(d + r) ** 2])

    def __call__(self, source: Any) -> Tuple[np.ndarray, np.ndarray, np.ndarray, float]:
        self.calls.append(source)
        src = [float(v) for v in source]
        if len(src) != 4:
            raise ValueError("length of source_mechanism must be 1, 3, 4, 7 (a double couple of four numbers here)")
        with np.errstate(over="ignore", invalid="ignore"):
            m0 = np.power(10.0, 1.5 * src[0] + 16.1 - 20.0)
            parts = [self.fed[c] * m0 * self.factor(src[1:])[c] for c in range(3)]
        if self.one:
            parts = [p[0] for p in parts]
        return parts[0].copy(), parts[1].copy(), parts[2].copy(), self.dt


def _t5_judge(got: Any, fake: _FakePyFK, m0_nm: float, rel: float) -> Optional[str]:
    if len(fake.calls) != 1:
        return "format"
    try:
        src = [float(v) for v in fake.calls[0]]
    except (TypeError, ValueError):
        return "format"
    if len(src) != 4:
        return "format"
    shape = fake.goal.shape[1:] if not fake.one else fake.goal.shape[2:]
    if not isinstance(got, tuple) or len(got) != 3:
        return "format"
    try:
        g = np.array([np.asarray(part, dtype=float) for part in got])
    except (TypeError, ValueError):
        return "format"
    if g.shape[1:] != tuple(shape):
        return "format"
    if not np.all(np.isfinite(g)):
        return "not-finite"
    if not np.allclose(src[1:], fake.angles, atol=1e-9):
        return "source-angles"
    mw = (2.0 / 3.0) * (math.log10(m0_nm) - 9.1)
    if abs(src[0] - mw) > 1e-6:
        if min(abs(src[0] - mw - 14.0 / 3.0), abs(src[0] - mw + 14.0 / 3.0)) < 1e-6:
            return "moment-units"
        return "magnitude"
    factor = fake.factor(fake.angles)
    pyfk_m0 = m0_nm * 1e7 * 1e-20
    scale = factor.reshape((3,) + (1,) * (g.ndim - 1)) * pyfk_m0
    goal = fake.goal if not fake.one else fake.goal[:, 0]
    fed = fake.fed if not fake.one else fake.fed[:, 0]
    truth = goal * scale / 100.0
    peak = np.abs(truth).max()
    if np.all(np.abs(g - truth) <= rel * peak):
        return None

    def prop(alt: np.ndarray) -> Optional[float]:
        c = float(np.sum(g * alt) / max(np.sum(alt * alt), 1e-300))
        resid = np.linalg.norm(g - c * alt) / max(np.linalg.norm(g), 1e-300)
        return c if resid < 0.05 else None

    if prop(fed * scale) is not None:
        return "rescaled-samples"
    steeper = np.gradient(fed * scale, fake.dt, axis=-1)
    if prop(steeper) is not None:
        return "derivative"
    c = prop(truth)
    if c is not None:
        for bad, cat in ((100.0, "factor-100"), (1.0 / fake.dt, "time-step"), (fake.dt, "time-step"),
                         (1e7, "moment-units"), (1e-7, "moment-units")):
            if abs(c / bad - 1.0) < 0.05:
                return cat
    if np.any(np.abs(g[..., 0]) > rel * peak):
        return "start"
    return "wrong-values"


def check_T5(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    rel = float(crit.get("rel_tol", 0.02))
    rng = ctx.rng
    oks: List[bool] = []
    cats: List[Optional[str]] = []
    example = None
    for k in range(int(crit.get("trials", 12))):
        one = k < 8
        n_rec = 1 if one else int(rng.integers(2, 5))
        dt = float(rng.uniform(0.01, 0.1))
        t = np.arange(int(rng.integers(1000, 1600))) * dt
        goal, fed = _t5_shapes(rng, t, n_rec)
        angles = (float(rng.uniform(0, 360)), float(rng.uniform(5, 90)), float(rng.uniform(-180, 180)))
        m0_nm = float(10.0 ** rng.uniform(10.0, 19.0))
        fake = _FakePyFK(goal, fed, dt, angles, one)
        got, err = _call(target, m0_nm, *angles, fake)
        cat = "format" if err is not None else _t5_judge(got, fake, m0_nm, rel)
        oks.append(cat is None)
        cats.append(cat)
        if cat and example is None:
            example = {"inputs": {"m0_nm": f"{m0_nm:.4g}", "strike, dip, rake": [round(a, 2) for a in angles],
                                  "receivers": n_rec, "dt_s": round(dt, 4)},
                       "got": (f"{type(err).__name__}: {err}" if err is not None else
                               f"run was called with {fake.calls[0] if fake.calls else 'nothing'}"),
                       "error": "see the category below"}
    return outcome_from_cases(oks, category=_first(cats, T5_PRIORITY), example=example)


# =========================================================================================== M52-T6
T6_PRIORITY = ("format", "changed-input", "xcorr-use", "units", "filter", "window", "back-azimuth", "rotation",
               "lag-sign", "time-axis", "wrong-values")


def _ricker(t: np.ndarray, center: float, peak_hz: float) -> np.ndarray:
    arg = (np.pi * peak_hz * (t - center)) ** 2
    return (1.0 - 2.0 * arg) * np.exp(-arg)


class _Spy:
    """The check's correlation (ObsPy's correlate, whole samples), with the contract of M41-T2; records calls."""

    def __init__(self) -> None:
        self.calls: List[Tuple[np.ndarray, np.ndarray]] = []

    def __call__(self, a: Any, b: Any, dt_s: float, max_lag_s: float):
        from obspy.signal.cross_correlation import correlate

        a = np.asarray(a, dtype=float)
        b = np.asarray(b, dtype=float)
        self.calls.append((a.copy(), b.copy()))
        k = int(round(max_lag_s / dt_s))
        cc = np.asarray(correlate(a, b, k, demean=True, normalize="naive", method="direct"), dtype=float)
        cc = cc[::-1]                                   # ObsPy's sign is the other way round: b later -> positive
        lags = np.arange(-k, k + 1) * dt_s
        j = int(np.argmax(cc))
        return float(lags[j]), float(cc[j]), lags, cc


def _t6_case(rng: np.random.Generator, k: int) -> dict:
    from obspy import Stream, Trace, UTCDateTime
    from obspy.signal.rotate import rotate_rt_ne

    dt = float(rng.choice([0.02, 0.025]))
    n = int(round(60.0 / dt))
    b_s = float(rng.uniform(4.0, 7.0))                           # more than max_lag + the largest shift
    t_syn = b_s + dt * np.arange(n)
    window = (b_s + 8.0 + 0.5 * dt, b_s + 44.0 + 0.5 * dt)     # half a sample off the grid: no ties
    lag = float(rng.uniform(-1.2, 1.2))
    factors = {c: float(rng.uniform(0.2, 5.0)) for c in "zrt"}
    waves = {c: [(float(rng.uniform(window[0] + 4.0, window[1] - 6.0)), float(rng.uniform(0.6, 1.2)),
                  float(rng.uniform(-1.0, 1.0)) * 10.0 ** rng.uniform(-6, -3)) for _ in range(3)] for c in "zrt"}

    def model(c: str, t: np.ndarray) -> np.ndarray:            # the synthetic as a formula, in run's unit
        return sum(a * _ricker(t, center, f) for center, f, a in waves[c])

    syn = {c: model(c, t_syn) for c in "zrt"}
    syn.update(b_s=b_s, dt_s=dt)
    origin = UTCDateTime(2031, 4, 5, 6, 7, 8) + float(rng.uniform(0.0, 3600.0))
    rate = 100.0
    start = -30.0 + float(rng.uniform(0.0, 0.01))
    t_rec = start + np.arange(int(round((b_s + 75.0 - start) * rate))) / rate
    rec = {c: factors[c] * model(c, t_rec - lag) / 100.0 for c in "zrt"}
    edge = np.clip(np.minimum(t_rec - t_rec[0], t_rec[-1] - t_rec) / 10.0, 0.0, 1.0)
    for c in "zrt":                                             # out-of-band disturbances and a late burst
        peak = np.abs(rec[c]).max()
        rec[c] = rec[c] + edge * peak * (3.0 * np.sin(2 * np.pi * 0.07 * t_rec + rng.uniform(0, 6))
                                         + 1.0 * np.sin(2 * np.pi * 12.0 * t_rec + rng.uniform(0, 6)))
        rec[c] = rec[c] + 3.0 * peak * _ricker(t_rec, window[1] + 6.0, 1.0)
    baz = float(rng.uniform(30.0, 150.0) + rng.choice([0.0, 180.0]))   # not within 30 degrees of 0 or 180, where
                                                                         # R and T are N and E up to their signs
    north, east = rotate_rt_ne(rec["r"], rec["t"], baz)
    stream = Stream()
    for chan, data in (("HHZ", rec["z"]), ("HHN", north), ("HHE", east)):
        tr = Trace(data=np.asarray(data, dtype=float))
        tr.stats.network, tr.stats.station, tr.stats.channel = "XX", f"SY{k:02d}", chan
        tr.stats.sampling_rate = rate
        tr.stats.starttime = origin + start
        stream += tr
    order = [stream[i] for i in rng.permutation(3)]
    return {"stream": Stream(order), "syn": syn, "origin": origin, "baz": baz, "lag": lag, "factors": factors,
            "window": window, "band": (float(rng.uniform(0.3, 0.45)), float(rng.uniform(2.0, 2.8))), "max_lag": 2.0}


def _table(got: Any) -> Optional[Any]:
    import pandas as pd

    if not isinstance(got, pd.DataFrame) or not {"cc", "lag_s", "amp_ratio"} <= set(got.columns):
        return None
    if sorted(str(i) for i in got.index) != ["R", "T", "Z"]:
        return None
    try:
        out = got.loc[["Z", "R", "T"], ["cc", "lag_s", "amp_ratio"]].astype(float)
    except (KeyError, TypeError, ValueError):
        return None
    return out if np.all(np.isfinite(out.to_numpy())) else None


def _t6_judge(got: Any, spy: _Spy, case: dict, crit: dict, changed: bool) -> Optional[str]:
    if changed:
        return "changed-input"
    table = _table(got)
    if table is None:
        return "format"
    dt = case["syn"]["dt_s"]
    if len(spy.calls) != 3 or any(a.size != b.size or a.size < 10 for a, b in spy.calls):
        return "xcorr-use"
    ratio_tol = float(crit.get("ratio_rel_tol", 0.03))
    lag_tol = float(crit.get("lag_tol_s", 0.02)) + dt
    cc_min = float(crit.get("cc_min", 0.97))
    want = np.array([case["factors"][c] for c in "zrt"])
    ratio = table["amp_ratio"].to_numpy()
    lags = table["lag_s"].to_numpy()
    ccs = table["cc"].to_numpy()
    good_ratio = np.abs(ratio / want - 1.0) <= ratio_tol
    good_lag = np.abs(lags - case["lag"]) <= lag_tol
    good_cc = ccs >= cc_min
    if np.all(good_ratio & good_lag & good_cc):
        return None
    if np.any(np.abs(ratio / (want * 100.0) - 1.0) <= ratio_tol) or np.any(np.abs(ratio * 100.0 / want - 1.0)
                                                                              <= ratio_tol):
        return "units"
    expected = spy.calls[0][0].size
    window_n = int(np.sum((case["syn"]["b_s"] + dt * np.arange(case["syn"]["z"].size) >= case["window"][0])
                          & (case["syn"]["b_s"] + dt * np.arange(case["syn"]["z"].size) <= case["window"][1])))
    if expected != window_n:
        return "window"
    rec_out = max(_outband(b, dt, case["band"]) for _, b in spy.calls)
    if rec_out > 0.05:                                 # the record still holds what the band-pass removes
        return "filter"
    if np.all(good_lag) and np.all(ccs >= 0.9) and not np.all(good_ratio):
        return "filter"                                # right shapes and times, sizes off: filtered unalike
    times = case["syn"]["b_s"] + dt * np.arange(case["syn"]["z"].size)
    raw = case["syn"]["z"]
    here = (times >= case["window"][0]) & (times <= case["window"][1])
    there = (times - case["syn"]["b_s"] >= case["window"][0]) & (times - case["syn"]["b_s"] <= case["window"][1])
    a_z = spy.calls[0][0]
    if a_z.size == int(there.sum()) and _corr(a_z, raw[there]) > _corr(a_z, raw[here]) + 0.2:
        return "time-axis"
    if np.all(np.abs(lags + case["lag"]) <= lag_tol) and np.all(good_ratio):
        return "lag-sign"
    z_ok = bool(good_ratio[0] and good_lag[0] and good_cc[0])
    if z_ok:
        if np.all(good_ratio[1:]) and np.all(ccs[1:] < cc_min):
            return "back-azimuth"
        return "rotation"
    return "wrong-values"


def _outband(x: np.ndarray, dt: float, band: Tuple[float, float]) -> float:
    """Fraction of the power of x outside [low / 1.5, high * 1.5] (a diagnostic of a missing band-pass)."""
    x = np.asarray(x, dtype=float) - np.mean(x)
    power = np.abs(np.fft.rfft(x * np.hanning(x.size))) ** 2
    freqs = np.fft.rfftfreq(x.size, dt)
    total = power.sum()
    if total <= 0:
        return 0.0
    return float(power[(freqs < band[0] / 1.5) | (freqs > band[1] * 1.5)].sum() / total)


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=float) - np.mean(a)
    b = np.asarray(b, dtype=float) - np.mean(b)
    den = math.sqrt(float(np.dot(a, a) * np.dot(b, b)))
    return abs(float(np.dot(a, b))) / den if den > 0 else 0.0


def _snapshot(stream: Any) -> List[Tuple[str, str, float, np.ndarray]]:
    return [(tr.id, str(tr.stats.starttime), float(tr.stats.delta), tr.data.copy()) for tr in stream]


def _same(stream: Any, snap: List[Tuple[str, str, float, np.ndarray]]) -> bool:
    now = _snapshot(stream)
    return len(now) == len(snap) and all(a[0] == b[0] and a[1] == b[1] and a[2] == b[2] and
                                         a[3].shape == b[3].shape and np.array_equal(a[3], b[3])
                                         for a, b in zip(now, snap))


def _xcorr_ok(xcorr: Any, rng: np.random.Generator, trials: int) -> bool:
    """The student's xcorr_lag on made-up shifts (positive when b is later): within one sample."""
    dt = 0.01
    t = np.arange(-1.5, 1.5, dt)
    for _ in range(trials):
        shift = float(rng.uniform(-0.25, 0.25))
        a = _ricker(t, 0.0, 4.0)
        b = 0.7 * _ricker(t, shift, 4.0)
        got, err = _call(xcorr, a, b, dt, 0.4)
        if err is not None or not isinstance(got, tuple) or len(got) < 2 or not _real(got[0]):
            return False
        if abs(float(got[0]) - shift) > dt or not (0.9 <= float(got[1]) <= 1.0 + 1e-9):
            return False
    return True


def _resolve(path_text: str, fit_json: Path) -> Path:
    path = Path(path_text)
    if path.is_absolute() or path.exists():
        return path
    for base in (fit_json.parent, fit_json.parent.parent):
        if (base / path).exists():
            return base / path
    return path


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _r3_runs(info: dict, fit_json: Path, main: Any, names: List[str]) -> Tuple[Optional[str], Any, List[dict]]:
    """The two R3 runs of the table: (category or None, the changed-model run, its rows)."""
    from .. import data as _data
    from .. import pyfk_runner as _fk

    try:
        rerun, changed = dict(info["rerun"]), dict(info["changed"])
        again = _fk.load(_resolve(str(rerun["fk_dir"]), fit_json))
        other = _fk.load(_resolve(str(changed["fk_dir"]), fit_json))
        want_layers = np.array(_fk.model_layers(_data.velocity_model(str(changed["model"]))), dtype=float)
        other_rows = [dict(r) for r in changed["rows"]]
        shas = [str(info["fk_sha256"]), str(rerun["fk_sha256"]), str(changed["fk_sha256"])]
    except Exception:  # noqa: BLE001 - missing, unreadable or unknown: the R3 part of the table is incomplete
        return "r3-runs", None, []
    folders = {run.path.resolve() for run in (main, again, other)}
    if len(folders) != 3:
        return "r3-runs", None, []
    if shas != [_file_sha256(run.path / "result.npz") for run in (main, again, other)]:
        return "r3-runs", None, []
    req_main, req_again = main.meta.get("request", {}), again.meta.get("request", {})
    req_other = other.meta.get("request", {})
    if req_again != req_main:
        return "r3-runs", None, []
    if any(req_other.get(key) != req_main.get(key) for key in set(req_main) | set(req_other) if key != "layers"):
        return "r3-runs", None, []
    try:
        got_layers = np.array(req_other.get("layers", []), dtype=float)
        main_layers = np.array(req_main.get("layers", []), dtype=float)
    except (TypeError, ValueError):
        return "r3-runs", None, []
    if got_layers.shape != want_layers.shape or not np.allclose(got_layers, want_layers, atol=1e-9):
        return "r3-runs", None, []
    if got_layers.shape == main_layers.shape and np.allclose(got_layers, main_layers, atol=1e-9):
        return "r3-runs", None, []
    have = {(str(r.get("station")), str(r.get("component"))) for r in other_rows}
    if any((name, comp) not in have for name in names for comp in "ZRT"):
        return "r3-runs", None, []
    return None, other, other_rows


def _rows_agree(mine: List[dict], table: Any, tol: float) -> Optional[str]:
    """None when every row of the student's table equals the recomputed table; else a category."""
    for r in mine:
        comp = str(r.get("component"))
        for col in ("cc", "lag_s", "amp_ratio"):
            try:
                value = float(r[col])
                again = float(table.loc[comp, col])
            except (KeyError, TypeError, ValueError):
                return "table"
            if not math.isfinite(value) or abs(value - again) > tol * max(1.0, abs(again)):
                return "recomputed"
        if not (-1.0 - 1e-9 <= float(r["cc"]) <= 1.0 + 1e-9 and float(r["amp_ratio"]) > 0):
            return "table"
    return None


def _real_table(target: Any, ctx: Any, crit: dict) -> Tuple[Optional[str], int]:
    """(category or None, number of real rows checked). Prints nothing of the data."""
    from obspy import UTCDateTime, read, read_inventory
    from obspy.geodetics import gps2dist_azimuth

    from .. import data as _data
    from .. import pyfk_runner as _fk

    fit_json = ctx.get("fit_json")
    xcorr = ctx.get("xcorr")
    if fit_json is None or xcorr is None or not callable(xcorr):
        return "no-table", 0
    fit_json = Path(fit_json)
    try:
        info = json.loads(fit_json.read_text(encoding="utf-8"))
        rows, stations = list(info["rows"]), list(info["stations"])
        origin = UTCDateTime(str(info["origin"]))
        lat, lon = (float(v) for v in info["epicenter"])
        pre_filt = tuple(float(v) for v in info["pre_filt_hz"])
        band = tuple(float(v) for v in info["band_hz"])
        taper, max_lag = float(info["taper"]), float(info["max_lag_s"])
        folder = (Path(ctx.data_root) / str(info["dataset"]) / "stp_download" / "SAC" / str(info["event_folder"])
                  / str(info.get("band", "HH")))
    except (OSError, ValueError, KeyError, TypeError):
        return "table", 0
    names = [str(s.get("station")) for s in stations]
    if len(set(names)) != len(names) or len(names) < int(crit.get("min_stations", 4)):
        return "table", 0
    have = {(str(r.get("station")), str(r.get("component"))) for r in rows}
    if any((name, comp) not in have for name in names for comp in "ZRT"):
        return "table", 0
    cat = _data.kma_catalog()
    event = cat.loc[cat["event_id"] == KMA_EVENT]
    if event.empty or abs(UTCDateTime(event.iloc[0]["origin_utc"].isoformat()) - origin) > 1e-3 or \
            abs(float(event.iloc[0]["latitude"]) - lat) > 1e-6 or abs(float(event.iloc[0]["longitude"]) - lon) > 1e-6:
        return "table", 0
    try:
        run = _fk.load(_resolve(str(info["fk_dir"]), fit_json))
    except (OSError, ValueError, KeyError):
        return "fk-run", 0
    req = run.meta.get("request", {})
    layers = _fk.model_layers(_data.velocity_model("kim1983"))
    src = [float(v) for v in req.get("source", [])]
    try:
        req_layers = np.array(req.get("layers", []), dtype=float)
    except (TypeError, ValueError):
        return "fk-run", 0
    if (len(src) != 4 or abs(src[0] - KIGAM_MW_Q) > 1e-9 or
            not any(np.allclose(src[1:], plane, atol=1e-9) for plane in (KIGAM_A, KIGAM_B)) or
            req.get("src_type") != "dc" or abs(float(req.get("source_depth_km", -1)) - KIGAM_DEPTH_Q) > 1e-9 or
            req_layers.shape != np.array(layers).shape or not np.allclose(req_layers, layers, atol=1e-9) or
            len(run) != len(names)):
        return "fk-run", 0
    r3_cat, other, other_rows = _r3_runs(info, fit_json, run, names)
    if r3_cat:
        return r3_cat, 0
    if not _xcorr_ok(xcorr, ctx.rng, int(crit.get("xcorr_trials", 4))):
        return "xcorr", 0
    tol = float(crit.get("recompute_tol", 1e-6))
    checked = 0
    for k, name in enumerate(names):
        files = sorted(folder.glob(f"*.{name}.{info.get('band', 'HH')}?.sac"))
        xml = Path(ctx.data_root) / "metadata" / "stationxml" / f"{name}.xml"
        if len(files) != 3 or not xml.is_file():
            return "no-data", checked
        try:
            with warnings.catch_warnings(), contextlib.redirect_stdout(io.StringIO()):
                warnings.simplefilter("ignore")
                stream = read(str(folder / f"*.{name}.{info.get('band', 'HH')}?.sac"))
                stream.detrend("demean").taper(max_percentage=taper, type="hann")
                stream.remove_response(inventory=read_inventory(str(xml)), output="VEL", pre_filt=pre_filt,
                                       water_level=None)
        except Exception:  # noqa: BLE001 - unreadable data
            return "no-data", checked
        sac = stream[0].stats.sac
        dist_m, az, baz = gps2dist_azimuth(lat, lon, float(sac.stla), float(sac.stlo))
        if (abs(dist_m / 1000.0 - float(run.distances_km[k])) > float(crit.get("distance_tol_km", 0.5)) or
                abs(((az - float(run.azimuths_deg[k]) + 180.0) % 360.0) - 180.0) > float(crit.get("azimuth_tol_deg",
                                                                                                   1.0))):
            return "fk-run", checked
        baz_used = float(stations[k].get("back_azimuth_deg", baz))
        if abs(((baz_used - baz + 180.0) % 360.0) - 180.0) > float(crit.get("azimuth_tol_deg", 1.0)):
            return "table", checked
        for result, table_rows in ((run, rows), (other, other_rows)):
            syn = {"z": result.z[k].copy(), "r": result.r[k].copy(), "t": result.t[k].copy(),
                   "b_s": float(result.b_s[k]), "dt_s": result.dt_s}
            mine = [r for r in table_rows if str(r.get("station")) == name]
            try:
                window = tuple(float(v) for v in mine[0].get("window_s", (np.nan, np.nan)))
            except (TypeError, ValueError):
                return "table", checked
            span = (float(result.b_s[k]), float(result.b_s[k]) + result.dt_s * (result.z.shape[1] - 1))
            if len(window) != 2 or not (span[0] <= window[0] < window[1] <= span[1]):
                return "table", checked
            with warnings.catch_warnings(), contextlib.redirect_stdout(io.StringIO()):
                warnings.simplefilter("ignore")
                got, err = _call(target, stream.copy(), syn, origin, baz_used, band, window, max_lag, xcorr)
            table = None if err is not None else _table(got)
            if table is None:
                return "recomputed", checked
            bad = _rows_agree(mine, table, tol)
            if bad:
                return bad, checked
            checked += len(mine)
    return None, checked


def check_T6(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    rng = ctx.rng
    oks: List[bool] = []
    cats: List[Optional[str]] = []
    example = None
    for k in range(int(crit.get("trials", 10))):
        case = _t6_case(rng, k)
        snap = _snapshot(case["stream"])
        syn_keep = {c: case["syn"][c].copy() for c in "zrt"}
        spy = _Spy()
        with warnings.catch_warnings(), contextlib.redirect_stdout(io.StringIO()):
            warnings.simplefilter("ignore")
            got, err = _call(target, case["stream"], case["syn"], case["origin"], case["baz"], case["band"],
                             case["window"], case["max_lag"], spy)
        changed = not _same(case["stream"], snap) or any(not np.array_equal(syn_keep[c], case["syn"][c])
                                                         for c in "zrt")
        cat = "format" if err is not None else _t6_judge(got, spy, case, crit, changed)
        oks.append(cat is None)
        cats.append(cat)
        if cat and example is None:
            table = None if err is not None else _table(got)
            example = {"inputs": {"made-up station": f"SY{k:02d}", "back_azimuth_deg": round(case["baz"], 2),
                                  "band_hz": [round(v, 3) for v in case["band"]],
                                  "window_s": [round(v, 3) for v in case["window"]], "dt_s": case["syn"]["dt_s"]},
                       "got": (f"{type(err).__name__}: {err}" if err is not None else
                               table.round(4).to_dict(orient="index") if table is not None else repr(got)[:150]),
                       "error": f"expected lag {case['lag']:.3f} s on every component, amp_ratio "
                                f"{ {c.upper(): round(v, 4) for c, v in case['factors'].items()} }, cc near 1"}
    category = _first(cats, T6_PRIORITY)
    if category:
        return outcome_from_cases(oks, category=category, example=example)
    real_cat, n_real = _real_table(target, ctx, crit)
    note = (f"{len(oks)} made-up stations, then {n_real} rows of your Sangju tables (both velocity models) "
            "recomputed with your function and your xcorr_lag on your own records and PyFK runs, and the "
            "fingerprints of your three R3 runs (no value is shown)")
    if real_cat:
        return outcome_from_cases(oks + [False], category=real_cat, real_data=True, note=note)
    return outcome_from_cases(oks + [True] * max(n_real, 1), real_data=True, note=note)
