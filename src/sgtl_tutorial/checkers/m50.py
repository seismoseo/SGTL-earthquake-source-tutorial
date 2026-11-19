"""Checkers for M50 · The focal sphere.

Where the truth comes from (DESIGN.md section 1, rule 1):

* M50-T1: independent libraries. Pyrocko's moment tensor of the same strike, dip and rake (north-east-down) must
  equal n d^T + d n^T from the student's two vectors; ObsPy's strike_dip turns the student's normal back into a
  strike and a dip, which must be the given plane's; the normal must point up (into the hanging wall).
* M50-T2: ObsPy's aux_plane (forbidden in the student's function), on made-up planes and on five fault types.
* M50-T3: ObsPy's mt2axes on Pyrocko's moment tensor turned into the up-south-east order that ObsPy reads.
* M50-T4: construction. Takeoff 0 is the centre and takeoff 90 the rim; the point of a ray lies at the ray's
  azimuth, clockwise from north; an upward ray lands where the opposite (downward) ray lands; and equal areas:
  of 200 000 random directions on the lower half of the sphere, the share with a takeoff angle up to i must equal
  the share of the circle's area inside the student's radius for i (r squared, the circle having radius 1).
* M50-T5: construction and an independent library. One layer: straight-line geometry. Two layers: Fermat's
  principle by brute force (the crossing point on the boundary with the least time; the takeoff is the angle of
  the leg from the source to it). The shipped models and a random model: ObsPy's TauP (forbidden in the student's
  function) on an Earth-flattened copy of the layers, as in M30.
* M50-T6: the student's polarity function on made-up rays first (directions drawn as vectors, the predicted
  polarity from Pyrocko's moment tensor, observed polarities with planted disagreements and question marks, so the
  fraction is known by construction); then the student's own files: polarities equal to the student's M20 pick
  file, distances and azimuths from ObsPy's gps2dist_azimuth, station coordinates from the course's station table,
  direct-wave takeoff angles and first arrivals from TauP, head-wave takeoffs at a critical angle of the model,
  predicted polarities from Pyrocko's moment tensor along SciPy's rotation of the downward vertical, and the
  fraction recomputed from the table; then the three runs of ObsPy's beachball (the production tool): the check
  draws ObsPy's beachball of the plane in each row itself, with the settings of the notebook's drawing cell, and
  compares the pixels of each PNG file with it; it recomputes the sha256 of each file and every count of the runs
  table from the files. No real-data value is printed.

Failure categories are keys of ``checks/specs/M50.yaml``; the engine prints their fixed messages.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import math
import numbers
import tempfile
import warnings
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import Outcome, outcome_from_cases

__all__ = ["check_T1", "check_T2", "check_T3", "check_T4", "check_T5", "check_T6"]

MAIN_EVENT = "2019009762"                 # the ML 3.9 Sangju earthquake of 21 July 2019 (KMA catalog)
# The two nodal planes of KIGAM's bulletin for that earthquake (report KEMS-2019-062, reference key
# kigam2021_bulletin2019): the INPUT mechanism of task 6, quoted in the notebook with its citation.
BULLETIN_PLANES = ((288.0, 89.0, 7.0), (198.0, 83.0, 179.0))
EARTH_KM = 6371.0
KM_PER_DEGREE = EARTH_KM * math.pi / 180.0
FLAT_POWER = 0.999
JOIN_KM = 200.0
SHAPE_TABLE_KEYS = ("agreement", "table", "png", "picks", "mechanism", "source", "model", "fraction")
TABLE_COLUMNS = ("station", "latitude", "longitude", "distance_km", "azimuth_deg", "wave", "takeoff_deg",
                 "polarity", "predicted")
RUNS_KEY = "obspy_runs"
RUNS_NAMES = ("unchanged 1", "unchanged 2", "changed")
RUNS_COLUMNS = ("run", "plane", "strike", "dip", "rake", "png", "sha256", "pixels", "pixels_changed",
                "strongly_changed", "grey_pixels")
RUNS_COUNTS = ("pixels", "pixels_changed", "strongly_changed", "grey_pixels")


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
    return isinstance(value, numbers.Real) and not isinstance(value, (bool, np.bool_)) and math.isfinite(value)


def _wrap(delta: Any) -> Any:
    """An angle difference in degrees moved into [-180, 180)."""
    return (np.asarray(delta, dtype=float) + 180.0) % 360.0 - 180.0


def _first(cats: Sequence[Optional[str]], priority: Sequence[str]) -> Optional[str]:
    present = {c for c in cats if c}
    return next((c for c in priority if c in present), None)


def _vote(cats: Sequence[Optional[str]], priority: Sequence[str]) -> Optional[str]:
    """The slip that most failing cases show (ties by priority); 'format' always first. A special plane (vertical,
    pure dip-slip) can look like another slip, so one case alone must not name the category."""
    found = [c for c in cats if c]
    if not found:
        return None
    if "format" in found:
        return "format"
    counts = {c: found.count(c) for c in set(found)}
    top = max(counts.values())
    return next(c for c in priority if counts.get(c) == top)


def _tensor(strike: float, dip: float, rake: float) -> np.ndarray:
    """Pyrocko's moment tensor (unit moment, north-east-down) of a double couple."""
    from pyrocko import moment_tensor as pmt

    return np.asarray(pmt.MomentTensor(strike=strike, dip=dip, rake=rake).m(), dtype=float)


def _use_order(m: np.ndarray) -> List[float]:
    """The six numbers ObsPy reads (up-south-east: rr, tt, pp, rt, rp, tp) from a north-east-down tensor."""
    return [m[2, 2], m[0, 0], m[1, 1], m[0, 2], -m[1, 2], -m[0, 1]]


def _planes(rng: np.random.Generator, number: int, dip_range=(5.0, 85.0)) -> List[Tuple[float, float, float]]:
    return [(float(rng.uniform(0.0, 360.0)), float(rng.uniform(*dip_range)), float(rng.uniform(-179.5, 179.5)))
            for _ in range(number)]


FAULT_TYPES = ((0.0, 90.0, 0.0), (0.0, 45.0, 90.0), (90.0, 30.0, -90.0), (210.0, 60.0, 180.0),
               (135.0, 75.0, 45.0))     # vertical left-lateral, thrust, normal, right-lateral, oblique


def _plane_text(case: Tuple[float, float, float]) -> Dict[str, float]:
    return {"strike": round(case[0], 3), "dip": round(case[1], 3), "rake": round(case[2], 3)}


# =========================================================================================== M50-T1
T1_PRIORITY = ("format", "not-unit", "coordinates", "radians", "strike-convention", "slip-sign", "swapped",
               "normal-down", "wrong-values")


def _t1_vectors(got: Any) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    if not isinstance(got, (tuple, list)) or len(got) != 2:
        return None
    out = []
    for part in got:
        if not isinstance(part, np.ndarray) or part.shape != (3,):
            return None
        try:
            vec = part.astype(float)
        except (TypeError, ValueError):
            return None
        if not np.all(np.isfinite(vec)):
            return None
        out.append(vec)
    return out[0], out[1]


def _same_tensor(n: np.ndarray, d: np.ndarray, m: np.ndarray, tol: float) -> bool:
    return bool(np.max(np.abs(np.outer(n, d) + np.outer(d, n) - m)) <= tol)


def _t1_judge(case: Tuple[float, float, float], n: np.ndarray, d: np.ndarray, tol: float) -> Optional[str]:
    from obspy.imaging.beachball import strike_dip

    strike, dip, rake = case
    if abs(np.linalg.norm(n) - 1.0) > tol or abs(np.linalg.norm(d) - 1.0) > tol:
        return "not-unit"
    truth = _tensor(strike, dip, rake)
    if _same_tensor(n, d, truth, tol):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            got_strike, got_dip = strike_dip(float(n[0]), float(n[1]), float(-n[2]))
        steep = dip > 89.9
        strike_off = abs(_wrap(got_strike - strike))
        if abs(got_dip - dip) > 1e-4 or (strike_off > 1e-4 and not (steep and abs(strike_off - 180.0) < 1e-4)):
            return "swapped"
        if n[2] > 1e-9:
            return "normal-down"
        return None
    for frame in (lambda v: np.array([v[1], v[0], -v[2]]),        # east-north-up
                  lambda v: np.array([-v[1], v[2], -v[0]])):      # up-south-east
        if _same_tensor(frame(n), frame(d), truth, tol):
            return "coordinates"
    if _same_tensor(n, d, _tensor(math.degrees(strike), math.degrees(dip), math.degrees(rake)), tol):
        return "radians"
    if any(_same_tensor(n, d, _tensor(strike + turn, dip, rake), tol) for turn in (90.0, -90.0, 180.0)):
        return "strike-convention"
    if _same_tensor(n, d, -truth, tol) or _same_tensor(n, d, _tensor(strike, dip, -rake), tol):
        return "slip-sign"
    return "wrong-values"


def check_T1(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    tol = float(crit.get("tol", 1e-6))
    cases = list(FAULT_TYPES) + _planes(ctx.rng, int(crit.get("random_cases", 40)))
    oks, cats, examples = [], [], {}
    for case in cases:
        got, err = _call(target, *case)
        if err is not None:
            raise err
        vectors = _t1_vectors(got)
        cat = "format" if vectors is None else _t1_judge(case, vectors[0], vectors[1], tol)
        oks.append(cat is None)
        cats.append(cat)
        if cat and cat not in examples:
            examples[cat] = {"inputs": _plane_text(case),
                       "got": "wrong type or shape" if vectors is None else
                       {"normal": np.round(vectors[0], 4).tolist(), "slip": np.round(vectors[1], 4).tolist()},
                       "error": "these vectors do not describe this plane and slip (see the problem above)"}
    category = _vote(cats, T1_PRIORITY)
    return outcome_from_cases(np.array(oks), category=category, example=examples.get(category))


# =========================================================================================== M50-T2
T2_PRIORITY = ("format", "degrees", "same-plane", "upward-normal", "range", "strike-direction", "rake-sign",
               "wrong-values")


def _t2_cases(rng: np.random.Generator, number: int) -> List[Tuple[Tuple[float, float, float], Tuple]]:
    from obspy.imaging.beachball import aux_plane

    out = [((0.0, 45.0, 90.0), aux_plane(0.0, 45.0, 90.0)), ((90.0, 30.0, -90.0), aux_plane(90.0, 30.0, -90.0)),
           ((135.0, 75.0, 45.0), aux_plane(135.0, 75.0, 45.0)), ((0.0, 90.0, 0.0), aux_plane(0.0, 90.0, 0.0))]
    while len(out) < number + 4:
        case = _planes(rng, 1)[0]
        other = aux_plane(*case)
        if 3.0 < other[1] < 87.0 and 2.0 < abs(other[2]) < 178.0:
            out.append((case, other))
    return out


def _t2_same(got: Sequence[float], want: Sequence[float], tol: float) -> bool:
    s, d, r = (float(v) for v in got)
    S, D, R = (float(v) for v in want)
    if abs(_wrap(s - S)) <= tol and abs(d - D) <= tol and abs(_wrap(r - R)) <= tol:
        return True
    # a vertical plane has two names: (strike, 90, rake) and (strike + 180, 90, -rake)
    return D > 90.0 - tol and abs(_wrap(s - S - 180.0)) <= tol and abs(d - D) <= tol and abs(_wrap(r + R)) <= tol


def _t2_judge(case, truth, got: Any, tol: float) -> Optional[str]:
    if not isinstance(got, (tuple, list)) or len(got) != 3 or not all(_real(v) for v in got):
        return "format"
    s, d, r = (float(v) for v in got)
    S, D, R = (float(v) for v in truth)
    in_range = 0.0 <= s <= 360.0 and 0.0 <= d <= 90.0 + 1e-9 and -180.0 < r <= 180.0
    if _t2_same((s, d, r), truth, tol):
        return None if in_range else "range"
    if _t2_same(np.degrees([s, d, r]), truth, tol):
        return "degrees"
    if _t2_same((s, d, r), case, tol):
        return "same-plane"
    if d > 90.0 or _t2_same((s, d, r), (S + 180.0, 180.0 - D, -R), tol):
        return "upward-normal"
    if abs(_wrap(s - S - 180.0)) <= tol and abs(d - D) <= tol:
        return "strike-direction"
    if abs(_wrap(s - S)) <= tol and abs(d - D) <= tol and (abs(_wrap(r + R)) <= tol or
                                                          abs(_wrap(r - (180.0 - R))) <= tol):
        return "rake-sign"
    return "wrong-values"


def check_T2(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    tol = float(crit.get("tol_deg", 0.01))
    oks, cats, examples = [], [], {}
    for case, truth in _t2_cases(ctx.rng, int(crit.get("random_cases", 40))):
        got, err = _call(target, *case)
        if err is not None:
            raise err
        cat = _t2_judge(case, truth, got, tol)
        oks.append(cat is None)
        cats.append(cat)
        if cat and cat not in examples:
            examples[cat] = {"inputs": _plane_text(case), "got": got if cat != "format" else repr(got)[:120],
                       "error": "expected (strike, dip, rake) = " +
                                str(tuple(round(float(v), 3) for v in truth))}
    category = _vote(cats, T2_PRIORITY)
    return outcome_from_cases(np.array(oks), category=category, example=examples.get(category))


# =========================================================================================== M50-T3
T3_PRIORITY = ("format", "degrees", "swapped", "upper-hemisphere", "trend-convention", "plunge-convention",
               "wrong-values")


def _t3_truth(case: Tuple[float, float, float]) -> Dict[str, Tuple[float, float]]:
    from obspy.imaging.beachball import MomentTensor, mt2axes

    t_axis, _, p_axis = mt2axes(MomentTensor(_use_order(_tensor(*case)), 0))
    return {"P": (float(p_axis.strike) % 360.0, float(p_axis.dip)),
            "T": (float(t_axis.strike) % 360.0, float(t_axis.dip))}


def _t3_axis_ok(got: Tuple[float, float], want: Tuple[float, float], tol: float, flat: float) -> bool:
    trend, plunge = got
    if abs(plunge - want[1]) > tol:
        return False
    if want[1] > 90.0 - flat:
        return True                                   # a vertical axis has no trend
    off = abs(_wrap(trend - want[0]))
    return off <= tol or (want[1] < flat and abs(off - 180.0) <= tol)


def _t3_pairs(got: Any) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
    if not isinstance(got, (tuple, list)) or len(got) != 2:
        return None
    pairs = []
    for part in got:
        if not isinstance(part, (tuple, list)) or len(part) != 2 or not all(_real(v) for v in part):
            return None
        pairs.append((float(part[0]), float(part[1])))
    return pairs[0], pairs[1]


def _t3_judge(truth: dict, pairs, tol: float, flat: float) -> Optional[str]:
    p_got, t_got = pairs
    if any(not (0.0 <= a[0] <= 360.0) or not (-1e-6 <= a[1] <= 90.0 + 1e-6) for a in (p_got, t_got)):
        if any(a[1] < -1e-6 for a in (p_got, t_got)):
            if all(_t3_axis_ok(((a[0] + 180.0) % 360.0, -a[1]), w, tol, flat)
                   for a, w in ((p_got, truth["P"]), (t_got, truth["T"]))):
                return "upper-hemisphere"
        if all(_t3_axis_ok(tuple(np.degrees(a)), w, tol, flat) for a, w in ((p_got, truth["P"]),
                                                                            (t_got, truth["T"]))):
            return "degrees"
        if all(_t3_axis_ok((a[0] % 360.0, a[1]), w, tol, flat) for a, w in ((p_got, truth["P"]),
                                                                            (t_got, truth["T"]))):
            return "format"
    if _t3_axis_ok(p_got, truth["P"], tol, flat) and _t3_axis_ok(t_got, truth["T"], tol, flat):
        return None
    if _t3_axis_ok(p_got, truth["T"], tol, flat) and _t3_axis_ok(t_got, truth["P"], tol, flat):
        return "swapped"
    if all(_t3_axis_ok(tuple(np.degrees(a)), w, tol, flat) for a, w in ((p_got, truth["P"]),
                                                                        (t_got, truth["T"]))):
        return "degrees"
    if all(_t3_axis_ok(((90.0 - a[0]) % 360.0, a[1]), w, tol, flat) for a, w in ((p_got, truth["P"]),
                                                                                 (t_got, truth["T"]))):
        return "trend-convention"
    if all(_t3_axis_ok((a[0], 90.0 - a[1]), w, tol, flat) for a, w in ((p_got, truth["P"]), (t_got, truth["T"]))):
        return "plunge-convention"
    return "wrong-values"


def check_T3(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    tol = float(crit.get("tol_deg", 0.01))
    flat = float(crit.get("flat_plunge_deg", 0.5))
    oks, cats, examples = [], [], {}
    for case in list(FAULT_TYPES) + _planes(ctx.rng, int(crit.get("random_cases", 40))):
        truth = _t3_truth(case)
        got, err = _call(target, *case)
        if err is not None:
            raise err
        pairs = _t3_pairs(got)
        cat = "format" if pairs is None else _t3_judge(truth, pairs, tol, flat)
        oks.append(cat is None)
        cats.append(cat)
        if cat and cat not in examples:
            examples[cat] = {"inputs": _plane_text(case), "got": repr(got)[:160],
                       "error": "expected P (trend, plunge) = " + str(tuple(round(v, 3) for v in truth["P"])) +
                                ", T = " + str(tuple(round(v, 3) for v in truth["T"]))}
    category = _vote(cats, T3_PRIORITY)
    return outcome_from_cases(np.array(oks), category=category, example=examples.get(category))


# =========================================================================================== M50-T4
T4_PRIORITY = ("format", "center", "rim", "azimuth", "upgoing", "equal-angle", "not-equal-area")
T4_AREA_TAKEOFFS = (10.0, 25.0, 40.0, 55.0, 70.0, 85.0)


def _t4_xy(got: Any, scalar: bool, size: int) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    if not isinstance(got, (tuple, list)) or len(got) != 2:
        return None
    out = []
    for part in got:
        if scalar:
            if not _real(part):
                return None
            out.append(np.array([float(part)]))
        else:
            if not isinstance(part, np.ndarray) or part.shape != (size,):
                return None
            try:
                out.append(part.astype(float))
            except (TypeError, ValueError):
                return None
    return out[0], out[1]


def _t4_run(target: Any, takeoff: Any, azimuth: Any) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    scalar = np.ndim(takeoff) == 0
    got, err = _call(target, takeoff if scalar else np.array(takeoff, dtype=float),
                     azimuth if scalar else np.array(azimuth, dtype=float))
    if err is not None:
        raise err
    xy = _t4_xy(got, scalar, 1 if scalar else int(np.size(takeoff)))
    return (None, None) if xy is None else xy


def check_T4(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    rng = ctx.rng
    tol = float(crit.get("tol", 1e-9))
    n_rays = int(crit.get("random_rays", 200))
    results: List[Tuple[bool, Optional[str]]] = []
    example = None

    def note(ok: bool, cat: Optional[str], inputs: dict, got: Any, error: str) -> None:
        nonlocal example
        results.append((ok, None if ok else cat))
        if not ok and example is None:
            example = {"inputs": inputs, "got": got, "error": error}

    # format: one number in, two floats out; an array in, two arrays of its length out
    az0 = float(rng.uniform(0.0, 360.0))
    x, y = _t4_run(target, 0.0, az0)
    if x is None:
        note(False, "format", {"takeoff_deg": 0.0, "azimuth_deg": round(az0, 3)}, "not two floats",
             "one number in gives two floats (x, y)")
        return outcome_from_cases([ok for ok, _ in results], category="format", example=example)
    note(math.hypot(x[0], y[0]) <= 1e-9, "center", {"takeoff_deg": 0.0, "azimuth_deg": round(az0, 3)},
         [float(x[0]), float(y[0])], "a ray straight down lands in the centre, (0, 0)")
    down_i = rng.uniform(0.5, 89.5, n_rays)
    down_az = rng.uniform(0.0, 360.0, n_rays)
    xd, yd = _t4_run(target, down_i, down_az)
    if xd is None:
        note(False, "format", {"takeoff_deg": f"{n_rays} values", "azimuth_deg": f"{n_rays} values"},
             "not two arrays", "an array in gives two arrays of its length")
        return outcome_from_cases([ok for ok, _ in results], category="format", example=example)
    rim_az = rng.uniform(0.0, 360.0, 6)
    xr, yr = _t4_run(target, np.full(6, 90.0), rim_az)
    if xr is None:
        note(False, "format", {"takeoff_deg": "6 values of 90"}, "not two arrays", "")
    else:
        r = np.hypot(xr, yr)
        note(bool(np.all(np.abs(r - 1.0) <= 1e-6)), "rim", {"takeoff_deg": 90.0, "azimuth_deg": round(rim_az[0], 3)},
             round(float(r[0]), 6), "a horizontal ray lands on the rim, at distance 1 from the centre")
    rd = np.hypot(xd, yd)
    seen = np.degrees(np.arctan2(xd, yd))
    off = np.abs(_wrap(seen - down_az))
    good = (rd > 1e-6) & (off <= 1e-6)
    k = int(np.argmin(good)) if not good.all() else 0
    note(bool(good.all()), "azimuth", {"takeoff_deg": round(float(down_i[k]), 3),
                                       "azimuth_deg": round(float(down_az[k]), 3)},
         [round(float(xd[k]), 5), round(float(yd[k]), 5)],
         "the point must lie in the direction of the azimuth, clockwise from north (x east, y north)")
    up_i = rng.uniform(90.5, 179.5, n_rays)
    up_az = rng.uniform(0.0, 360.0, n_rays)
    xu, yu = _t4_run(target, up_i, up_az)
    xo, yo = _t4_run(target, 180.0 - up_i, (up_az + 180.0) % 360.0)
    if xu is None or xo is None:
        note(False, "format", {"takeoff_deg": f"{n_rays} values above 90"}, "not two arrays", "")
    else:
        same = (np.abs(xu - xo) <= 1e-9) & (np.abs(yu - yo) <= 1e-9) & (np.hypot(xu, yu) <= 1.0 + 1e-9)
        k = int(np.argmin(same)) if not same.all() else 0
        note(bool(same.all()), "upgoing", {"takeoff_deg": round(float(up_i[k]), 3),
                                           "azimuth_deg": round(float(up_az[k]), 3)},
             [round(float(xu[k]), 5), round(float(yu[k]), 5)],
             "an upward ray lands where the opposite downward ray lands")
    # equal areas: the share of random directions with a takeoff up to i equals r(i) squared
    n_dir = int(crit.get("area_directions", 200000))
    vec = rng.standard_normal((n_dir, 3))
    down = np.abs(vec[:, 2]) / np.linalg.norm(vec, axis=1)
    takeoffs = np.degrees(np.arccos(np.clip(down, -1.0, 1.0)))
    test = np.array(T4_AREA_TAKEOFFS)
    share = np.array([np.mean(takeoffs <= i) for i in test])
    xa, ya = _t4_run(target, test, np.zeros(test.size))
    if xa is None:
        note(False, "format", {"takeoff_deg": test.tolist()}, "not two arrays", "")
    else:
        r2 = xa ** 2 + ya ** 2
        area_tol = float(crit.get("area_tol", 0.006))
        bad = np.abs(r2 - share) > area_tol
        stereo = np.tan(np.radians(test) / 2.0)
        cat = "equal-angle" if np.allclose(np.sqrt(r2), stereo, atol=1e-6) else "not-equal-area"
        k = int(np.argmax(bad)) if bad.any() else 0
        note(not bad.any(), cat, {"takeoff_deg": float(test[k]), "azimuth_deg": 0.0},
             {"r": round(float(np.sqrt(r2[k])), 5), "area share inside r (r squared)": round(float(r2[k]), 5)},
             f"{share[k]:.4f} of {n_dir} random directions on the lower half of the sphere have a takeoff up to "
             f"{test[k]:g} degrees, so that share of the circle's area must lie inside r")
    oks = [ok for ok, _ in results]
    category = _first([c for _, c in results], T4_PRIORITY)
    return outcome_from_cases(oks, category=category, example=example)


# =========================================================================================== M50-T5
T5_PRIORITY = ("format", "changed-input", "degrees", "upward-vertical", "zero-distance", "phase", "straight-ray",
               "top-layer-speed", "not-converged", "wrong-values")


def _frame(tops: Sequence[float], vp: Sequence[float], vs: Sequence[float]):
    import pandas as pd

    return pd.DataFrame({"top_km": np.asarray(tops, dtype=float), "vp": np.asarray(vp, dtype=float),
                         "vs": np.asarray(vs, dtype=float)})


def _shipped(name: str):
    from .. import data as _data

    table = _data.velocity_model(name)
    return _frame(table["top_km"], table["vp"], table["vs"])


def _speeds(model: Any, phase: str) -> Tuple[np.ndarray, np.ndarray]:
    return (np.asarray(model["top_km"], dtype=float),
            np.asarray(model["vp" if phase == "P" else "vs"], dtype=float))


def _source_speed(model: Any, depth: float, phase: str) -> float:
    tops, speed = _speeds(model, phase)
    return float(speed[np.nonzero(tops <= depth)[0][-1]])


def _ak135_below(depth_km: float) -> List[str]:
    import obspy.taup

    path = Path(obspy.taup.__file__).parent / "data" / "ak135f_no_mud.nd"
    out = []
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) == 1 and parts[0] in ("outer-core", "inner-core"):
            out.append(parts[0])
        elif len(parts) >= 4 and float(parts[0]) > depth_km:
            out.append(" ".join(parts[:4]))
    return out


def _nd_lines(model: Any) -> List[str]:
    """A TauP '.nd' model: the Earth-flattened spherical twin of the flat layers (as in the checks of M30)."""
    tops = np.asarray(model["top_km"], dtype=float)
    vp = np.asarray(model["vp"], dtype=float)
    vs = np.asarray(model["vs"], dtype=float)
    ends = list(tops[1:]) + [JOIN_KM]
    lines = []
    for j, top in enumerate(tops):
        if j == len(tops) - 1 and j > 0:
            lines.append("mantle")
        for z in (top, ends[j]):
            radius = EARTH_KM * math.exp(-z / EARTH_KM)
            scale = (radius / EARTH_KM) ** FLAT_POWER
            lines.append(f"{EARTH_KM - radius:.9f} {vp[j] * scale:.9f} {vs[j] * scale:.9f} 2.70")
    deep = EARTH_KM * (1.0 - math.exp(-JOIN_KM / EARTH_KM))
    return lines + _ak135_below(deep)


def _taup_model(model: Any):
    from obspy.taup import TauPyModel
    from obspy.taup.taup_create import build_taup_model

    with tempfile.TemporaryDirectory(prefix="sgtl-m50-") as tmp:
        source = Path(tmp) / "layers.nd"
        source.write_text("\n".join(_nd_lines(model)) + "\n")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
                warnings.catch_warnings():
            warnings.simplefilter("ignore")
            build_taup_model(str(source), output_folder=tmp, verbose=False)
            return TauPyModel(model=str(Path(tmp) / "layers.npz"))


def _taup_arrivals(taup: Any, x_km: float, depth_km: float, phases: List[str]):
    depth = EARTH_KM * (1.0 - math.exp(-depth_km / EARTH_KM))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return taup.get_travel_times(source_depth_in_km=depth, distance_in_degree=max(x_km, 1e-4) / KM_PER_DEGREE,
                                     phase_list=phases)


def _taup_takeoff(taup: Any, x_km: float, depth_km: float, name: str) -> float:
    arrivals = [a for a in _taup_arrivals(taup, x_km, depth_km, [name]) if a.name == name]
    return float(arrivals[0].takeoff_angle) if arrivals else float("nan")


def _fermat_two_layer(x: float, depth: float, z1: float, v1: float, v2: float) -> float:
    """Takeoff (degrees from down) of the quickest path from a source in the lower layer to a surface station."""
    from scipy.optimize import minimize_scalar

    if x <= 0.0:
        return 180.0

    def time(c: float) -> float:
        return math.hypot(c, depth - z1) / v2 + math.hypot(x - c, z1) / v1

    grid = np.linspace(0.0, x, 4001)
    best = int(np.argmin([time(c) for c in grid]))
    lo, hi = grid[max(best - 1, 0)], grid[min(best + 1, grid.size - 1)]
    res = minimize_scalar(time, bounds=(lo, hi), method="bounded", options={"xatol": 1e-11, "maxiter": 500})
    return 180.0 - math.degrees(math.atan2(float(res.x), depth - z1))


def _t5_cases(rng: np.random.Generator) -> List[dict]:
    cases: List[dict] = []
    for i in range(4):
        vp = rng.uniform(4.5, 8.0)
        model = _frame([0.0], [vp], [vp / rng.uniform(1.6, 1.9)])
        depth = float(rng.uniform(1.0, 30.0))
        x: Any = float(rng.uniform(0.5, 150.0)) if i < 2 else np.concatenate([[0.0], rng.uniform(0.0, 150.0, 7)])
        cases.append({"model": model, "depth": depth, "x": x, "phase": "P" if i % 2 == 0 else "S",
                      "kind": "half-space", "tol": "formula",
                      "truth": lambda xs, ph, d=depth: 180.0 - np.degrees(np.arctan2(xs, d))})
    for i, slower in enumerate((False, False, True)):
        z1 = rng.uniform(3.0, 8.0) if slower else rng.uniform(3.0, 15.0)
        v1 = rng.uniform(5.0, 6.2)
        v2 = v1 * (rng.uniform(0.80, 0.87) if slower else rng.uniform(1.05, 1.25))
        ratio = rng.uniform(1.65, 1.85)
        model = _frame([0.0, z1], [v1, v2], [v1 / ratio, v2 / ratio])
        depth = float(z1 + (rng.uniform(1.0, 6.0) if slower else rng.uniform(1.0, 15.0)))
        xs = np.concatenate([[0.0], np.sort(rng.uniform(1.0, 140.0, 6))])

        def truth(xv, ph, model=model, depth=depth, z1=z1):
            _, speed = _speeds(model, ph)
            return np.array([_fermat_two_layer(float(a), depth, z1, float(speed[0]), float(speed[1]))
                             for a in np.atleast_1d(xv)])
        cases.append({"model": model, "depth": depth, "x": xs, "phase": "P" if i % 2 == 0 else "S",
                      "kind": "two-layer", "tol": "formula", "truth": truth, "slower": slower})
    rand_tops = np.concatenate([[0.0], np.add.accumulate(rng.uniform(2.0, 11.0, 3))])
    rand_vp = np.sort(rng.uniform(5.2, 7.9, 4))
    rand = _frame(rand_tops, rand_vp, rand_vp / rng.uniform(1.65, 1.85))
    for name, model, depth, phase in (("kim1983", _shipped("kim1983"), float(rng.uniform(16.0, 30.0)), "P"),
                                      ("kim2011", _shipped("kim2011"), 14.0, "S"),
                                      ("random", rand, float(rng.uniform(rand_tops[2], rand_tops[3]) + 0.5), "P")):
        taup = _taup_model(model)
        xs = np.sort(np.concatenate([[0.3, 100.0], rng.uniform(1.0, 140.0, 5)]))

        def truth(xv, ph, taup=taup, depth=depth):
            return np.array([_taup_takeoff(taup, float(a), depth, "p" if ph == "P" else "s")
                             for a in np.atleast_1d(xv)])
        cases.append({"model": model, "depth": depth, "x": xs, "phase": phase, "kind": f"taup-{name}",
                      "tol": "taup", "truth": truth})
    return cases


def _t5_values(got: Any, scalar: bool, size: int) -> Optional[np.ndarray]:
    if scalar:
        return np.array([float(got)]) if _real(got) else None
    if not isinstance(got, np.ndarray) or got.shape != (size,):
        return None
    try:
        return got.astype(float)
    except (TypeError, ValueError):
        return None


def _t5_judge(case: dict, got: Any, tol: float) -> Tuple[np.ndarray, Optional[str], Optional[np.ndarray]]:
    x, scalar = case["x"], np.ndim(case["x"]) == 0
    xs = np.atleast_1d(np.asarray(x, dtype=float))
    values = _t5_values(got, scalar, xs.size)
    if values is None:
        return np.zeros(xs.size, dtype=bool), "format", None
    truth = np.asarray(case["truth"](xs, case["phase"]), dtype=float)
    ok = (np.isfinite(values) & (np.abs(values - truth) <= tol)) | np.isnan(truth)
    if ok.all():
        return ok, None, truth
    bad = ~ok

    def near(alt: np.ndarray, size: float = tol) -> bool:
        alt = np.asarray(alt, dtype=float)
        return bool(np.all(np.isfinite(values[bad]) & (np.abs(values[bad] - alt[bad]) <= size)))
    if near(np.radians(truth), 1e-3):
        return ok, "degrees", truth
    if near(180.0 - truth):
        return ok, "upward-vertical", truth
    if np.all(xs[bad] == 0.0):
        return ok, "zero-distance", truth
    other = np.asarray(case["truth"](xs, "S" if case["phase"] == "P" else "P"), dtype=float)
    if near(other):
        return ok, "phase", truth
    if case["kind"] != "half-space" and near(180.0 - np.degrees(np.arctan2(xs, case["depth"]))):
        return ok, "straight-ray", truth
    _, speed = _speeds(case["model"], case["phase"])
    v_src = _source_speed(case["model"], case["depth"], case["phase"])
    slowness = np.sin(np.radians(truth)) / v_src
    top = np.clip(slowness * speed[0], -1.0, 1.0)
    if case["kind"] != "half-space" and near(180.0 - np.degrees(np.arcsin(top))):
        return ok, "top-layer-speed", truth
    if np.all(np.isfinite(values[bad]) & (np.abs(values[bad] - truth[bad]) <= 1.0)):
        return ok, "not-converged", truth
    return ok, "wrong-values", truth


def check_T5(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    tols = {"formula": float(crit.get("tol_formula_deg", 0.01)), "taup": float(crit.get("tol_taup_deg", 0.1))}
    oks: List[np.ndarray] = []
    cats: List[Optional[str]] = []
    example = None
    for case in _t5_cases(ctx.rng):
        model = case["model"]
        before = model.copy(deep=True)
        got, err = _call(target, case["x"] if np.ndim(case["x"]) == 0 else case["x"].copy(), case["depth"],
                         model, case["phase"])
        if err is not None:
            raise err
        if not (list(model.columns) == list(before.columns) and model.equals(before)):
            oks.append(np.zeros(1, dtype=bool))
            cats.append("changed-input")
            continue
        ok, cat, truth = _t5_judge(case, got, tols[case["tol"]])
        oks.append(ok)
        cats.append(cat)
        if cat and example is None:
            rows = [f"top {t:g} km: vp {p:.3f}, vs {s:.3f}" for t, p, s in
                    zip(model["top_km"], model["vp"], model["vs"])]
            xs = np.atleast_1d(np.asarray(case["x"], dtype=float))
            example = {"inputs": {"x_km": round(float(xs[0]), 4) if np.ndim(case["x"]) == 0 else
                                  f"{xs.size} distances from {xs.min():.4g} to {xs.max():.4g} km",
                                  "depth_km": round(case["depth"], 3), "model": "; ".join(rows),
                                  "phase": case["phase"]},
                       "got": repr(got)[:120] if truth is None else
                       np.round(np.atleast_1d(np.asarray(got, dtype=float))[~ok][:3], 4).tolist(),
                       "error": ("wrong type or shape" if truth is None else
                                 f"expected {np.round(truth[~ok][:3], 4).tolist()} degrees at "
                                 f"{np.round(xs[~ok][:3], 3).tolist()} km")}
    category = _first(cats, T5_PRIORITY)
    all_ok = np.concatenate(oks)
    if category and all_ok.all():
        all_ok = np.append(all_ok, False)
    return outcome_from_cases(all_ok, category=category, example=example)


# =========================================================================================== M50-T6
T6_FUNC_PRIORITY = ("format", "reversed", "azimuth-convention", "takeoff-convention", "wrong-values",
                    "question-marks", "fraction-function")


def _amplitudes(m: np.ndarray, rays: np.ndarray) -> np.ndarray:
    """Radial P amplitude gamma^T M gamma along unit rays (rows of rays, north-east-down)."""
    return np.einsum("ij,jk,ik->i", rays, m, rays)


def _rays_from_angles(takeoff_deg: np.ndarray, azimuth_deg: np.ndarray) -> np.ndarray:
    """Unit rays from takeoff and azimuth: SciPy's rotation of the downward vertical, first about east (by the
    takeoff), then about down (by the azimuth). An independent route from the one the task asks for."""
    from scipy.spatial.transform import Rotation

    angles = np.column_stack([np.asarray(takeoff_deg, dtype=float), np.asarray(azimuth_deg, dtype=float)])
    return Rotation.from_euler("yz", angles, degrees=True).apply(np.array([0.0, 0.0, 1.0]))


def _t6_tables(rng: np.random.Generator, number: int, margin: float) -> List[dict]:
    """Made-up rays and polarities. Rays are drawn as vectors; the takeoff and azimuth are read from them."""
    tables = []
    for k in range(number):
        plane = _planes(rng, 1, (10.0, 90.0))[0]
        m = _tensor(*plane)
        size = int(rng.integers(8, 21))
        rays: List[np.ndarray] = []
        while len(rays) < size:
            v = rng.standard_normal(3)
            v /= np.linalg.norm(v)
            if abs(_amplitudes(m, v[None, :])[0]) >= margin and abs(v[2]) < 0.985:
                rays.append(v)
        ray = np.array(rays)
        takeoff = np.degrees(np.arccos(np.clip(ray[:, 2], -1.0, 1.0)))
        azimuth = np.degrees(np.arctan2(ray[:, 1], ray[:, 0])) % 360.0
        truth = np.where(_amplitudes(m, ray) > 0.0, "U", "D")
        observed = truth.copy()
        flips = rng.choice(size, size=int(rng.integers(0, max(1, size // 3))), replace=False)
        observed[flips] = np.where(observed[flips] == "U", "D", "U")
        unknown = rng.choice(size, size=int(rng.integers(1, 4)), replace=False) if k % 3 else np.array([], int)
        observed = observed.astype(object)
        observed[unknown] = "?"
        if k == number - 1:
            observed[:] = "?"                       # a table without one clear first motion
        known = observed != "?"
        agree = int(np.sum(observed[known] == truth[known]))
        fraction = agree / int(known.sum()) if known.any() else float("nan")
        h = np.hypot(ray[:, 0], ray[:, 1])
        alt_az = ray[:, [1, 0, 2]]                                        # north and east swapped
        alt_up = np.column_stack([ray[:, 0] * ray[:, 2] / h, ray[:, 1] * ray[:, 2] / h, h])   # from horizontal
        tables.append({"plane": plane, "takeoff": takeoff, "azimuth": azimuth, "observed": list(observed),
                       "truth": truth, "fraction": fraction, "known": int(known.sum()), "agree": agree,
                       "size": size, "alt_az": np.where(_amplitudes(m, alt_az) > 0.0, "U", "D"),
                       "alt_up": np.where(_amplitudes(m, alt_up) > 0.0, "U", "D")})
    return tables


def _t6_function(func: Callable, ctx: Any) -> Optional[Outcome]:
    """The polarity function on made-up rays: None when it passes, else the failing Outcome."""
    crit = ctx.criteria
    tables = _t6_tables(ctx.rng, int(crit.get("tables", 10)), float(crit.get("nodal_margin", 0.05)))
    oks, cats, example = [], [], None
    for tab in tables:
        got, err = _call(func, tab["takeoff"].copy(), tab["azimuth"].copy(), list(tab["observed"]),
                         *tab["plane"])
        if err is not None:
            raise err
        cat = None
        if not isinstance(got, (tuple, list)) or len(got) != 2 or not isinstance(got[0], np.ndarray) or \
                got[0].shape != (tab["size"],) or not isinstance(got[1], numbers.Real) or \
                isinstance(got[1], (bool, np.bool_)):
            cat = "format"
        else:
            predicted = np.asarray(got[0]).astype(str)
            fraction = float(got[1])
            if not set(predicted.tolist()) <= {"U", "D"}:
                cat = "format"
            elif not np.array_equal(predicted, tab["truth"]):
                opposite = np.where(tab["truth"] == "U", "D", "U")
                cat = ("reversed" if np.array_equal(predicted, opposite) else
                       "azimuth-convention" if np.array_equal(predicted, tab["alt_az"]) else
                       "takeoff-convention" if np.array_equal(predicted, tab["alt_up"]) else "wrong-values")
            elif tab["known"] == 0:
                cat = None if math.isnan(fraction) else "question-marks"
            elif not abs(fraction - tab["fraction"]) <= 1e-9:
                cat = "question-marks" if abs(fraction - tab["agree"] / tab["size"]) <= 1e-9 else \
                    "fraction-function"
        oks.append(cat is None)
        cats.append(cat)
        if cat and example is None:
            example = {"inputs": {"strike, dip, rake": [round(v, 3) for v in tab["plane"]],
                                  "takeoff_deg": np.round(tab["takeoff"][:3], 3).tolist(),
                                  "azimuth_deg": np.round(tab["azimuth"][:3], 3).tolist(),
                                  "polarity": tab["observed"][:3], "rays": tab["size"]},
                       "got": repr(got)[:160],
                       "error": f"expected the first three predictions {tab['truth'][:3].tolist()} and the fraction "
                                f"{tab['agree']} of {tab['known']} clear first motions"}
    if all(oks):
        return None
    return outcome_from_cases(np.array(oks), category=_first(cats, T6_FUNC_PRIORITY), example=example)


def _t6_guard(func: Any, ctx: Any) -> Optional[Outcome]:
    from .. import astguard

    rules = list((ctx.spec or {}).get("forbidden") or [])
    if not rules:
        return None
    rep = astguard.check_function(func, rules)
    if rep.ok:
        return None
    msg = ("This task asks you to write this step yourself, so the rule is: do not use "
           f"{', '.join(rep.violations)} here (found in {getattr(func, '__name__', 'your function')}).")
    return Outcome(False, 0, 0, "forbidden-import", msg, details={"found": rep.offending})


def _fail(category: str, note: Optional[str] = None) -> Outcome:
    return outcome_from_cases([False], category=category, real_data=True, note=note)


def _t6_shape(answer: Any) -> bool:
    if not isinstance(answer, dict) or not set(SHAPE_TABLE_KEYS) <= set(answer) <= set(SHAPE_TABLE_KEYS) | \
            {RUNS_KEY} or not callable(answer["agreement"]):
        return False
    if not all(isinstance(answer[k], (str, Path)) for k in ("table", "png", "picks")):
        return False
    mech = answer["mechanism"]
    if not isinstance(mech, (tuple, list)) or len(mech) != 3 or not all(_real(v) for v in mech):
        return False
    src = answer["source"]
    if not isinstance(src, dict) or not all(_real(src.get(k)) for k in ("latitude", "longitude", "depth_km")):
        return False
    return isinstance(answer["model"], str) and answer["model"] in ("kim1983", "kim2011") and \
        _real(answer["fraction"])


def _t6_station_table() -> Dict[str, Tuple[float, float]]:
    import pandas as pd

    from .. import data as _data

    path = _data.repo_path("data", "stations", "stations.csv")
    if not Path(path).is_file():
        return {}
    table = pd.read_csv(path)
    return {f"{n}.{s}": (float(a), float(b)) for n, s, a, b in
            zip(table["network"], table["station"], table["latitude"], table["longitude"])}


def _t6_files(answer: dict, ctx: Any) -> Outcome:
    import pandas as pd
    from obspy.geodetics import gps2dist_azimuth

    from .. import data as _data

    crit = ctx.criteria
    plane = tuple(float(v) for v in answer["mechanism"])
    if not any(abs(_wrap(plane[0] - p[0])) <= 0.5 and abs(plane[1] - p[1]) <= 0.5 and
               abs(_wrap(plane[2] - p[2])) <= 0.5 for p in BULLETIN_PLANES):
        return _fail("mechanism")
    try:
        table = pd.read_csv(answer["table"], dtype={"station": str, "polarity": str, "predicted": str,
                                                   "wave": str})
    except Exception:  # noqa: BLE001 - any unreadable file is the same problem
        return _fail("table")
    if any(c not in table.columns for c in TABLE_COLUMNS) or table["station"].duplicated().any() or \
            len(table) < int(crit.get("min_polarities", 5)):
        return _fail("table")
    try:
        numbers_ = table[["latitude", "longitude", "distance_km", "azimuth_deg", "takeoff_deg"]].astype(float)
    except (TypeError, ValueError):
        return _fail("table")
    if not np.all(np.isfinite(numbers_.to_numpy())):
        return _fail("table")
    polarity = table["polarity"].fillna("").str.strip()
    predicted = table["predicted"].fillna("").str.strip()
    wave = table["wave"].fillna("").str.strip()
    if not set(polarity) <= {"U", "D"} or not set(predicted) <= {"U", "D"} or not set(wave) <= {"direct", "head"}:
        return _fail("table")
    try:
        picks = pd.read_csv(answer["picks"], dtype={"station": str, "phase": str, "polarity": str})
        p_rows = picks[picks["phase"].astype(str).str.strip() == "P"].drop_duplicates("station")
        theirs = dict(zip(p_rows["station"].astype(str).str.strip(), p_rows["polarity"].fillna("?").str.strip()))
    except Exception:  # noqa: BLE001
        return _fail("table", "The pick file under 'picks' could not be read as a pick table of module M20.")
    clear = {s for s, p in theirs.items() if p in ("U", "D")}
    names = table["station"].str.strip().tolist()
    if any(theirs.get(s) != p for s, p in zip(names, polarity)):
        return _fail("not-your-polarities")
    if set(names) != clear:
        return _fail("missing-stations")
    catalog = _data.kma_catalog()
    row = catalog.loc[catalog["event_id"] == MAIN_EVENT].iloc[0]
    src = answer["source"]
    lat0, lon0, depth = float(src["latitude"]), float(src["longitude"]), float(src["depth_km"])
    window = float(crit.get("epicenter_window_deg", 0.2))
    if abs(lat0 - float(row["latitude"])) > window or abs(lon0 - float(row["longitude"])) > window or \
            not 0.5 <= depth <= 40.0:
        return _fail("source")
    stations = _t6_station_table()
    tol_sta = float(crit.get("station_tol_deg", 0.02))
    for name, lat, lon in zip(names, numbers_["latitude"], numbers_["longitude"]):
        if name in stations and (abs(stations[name][0] - lat) > tol_sta or abs(stations[name][1] - lon) > tol_sta):
            return _fail("station-coordinates")
    dist_tol, az_tol = float(crit.get("distance_tol_km", 0.1)), float(crit.get("azimuth_tol_deg", 0.2))
    for lat, lon, dist, az in zip(numbers_["latitude"], numbers_["longitude"], numbers_["distance_km"],
                                  numbers_["azimuth_deg"]):
        metres, forward, back = gps2dist_azimuth(lat0, lon0, float(lat), float(lon))
        if abs(metres / 1000.0 - dist) > dist_tol:
            return _fail("distance")
        if abs(_wrap(az - forward)) > az_tol:
            return _fail("back-azimuth" if abs(_wrap(az - back)) <= az_tol else "azimuth")
    takeoff = numbers_["takeoff_deg"].to_numpy()
    distance = numbers_["distance_km"].to_numpy()
    direct = (wave == "direct").to_numpy()
    if np.any(direct & (takeoff <= 90.0)) or np.any(~direct & (takeoff >= 90.0)):
        return _fail("takeoff-direction")
    if direct.any() and (~direct).any() and distance[direct].max() > distance[~direct].min():
        return _fail("wave-order")
    model = _shipped(answer["model"])
    tops, speed = _speeds(model, "P")
    v_src = _source_speed(model, depth, "P")
    critical = [math.degrees(math.asin(v_src / v)) for t, v in zip(tops, speed) if t > depth and v > v_src]
    tol_take = float(crit.get("takeoff_tol_deg", 0.2))
    margin_s = float(crit.get("first_arrival_margin_s", 0.05))
    taup = _taup_model(model)
    for is_direct, x, angle in zip(direct, distance, takeoff):
        arrivals = _taup_arrivals(taup, float(x), depth, ["p", "P"])
        direct_arr = [a for a in arrivals if a.name == "p"]
        t_direct = min((a.time for a in direct_arr), default=float("nan"))
        t_below = min((a.time for a in arrivals if a.name == "P"), default=float("inf"))   # rays from below
        if math.isfinite(t_direct) and ((is_direct and t_below < t_direct - margin_s) or
                                        (not is_direct and t_direct < t_below - margin_s)):
            return _fail("first-arrival")
        if is_direct:
            want = float(direct_arr[0].takeoff_angle) if direct_arr else float("nan")
            if math.isfinite(want) and abs(angle - want) > tol_take:
                return _fail("takeoff")
        elif not any(abs(angle - c) <= tol_take for c in critical):
            return _fail("takeoff")
    m = _tensor(*plane)
    amp = _amplitudes(m, _rays_from_angles(takeoff, numbers_["azimuth_deg"].to_numpy()))
    clear_amp = np.abs(amp) >= float(crit.get("nodal_margin", 0.05))
    oracle = np.where(amp > 0.0, "U", "D")
    if np.any(clear_amp & (oracle != predicted.to_numpy())):
        return _fail("predicted")
    recomputed = float(np.mean(polarity.to_numpy() == predicted.to_numpy()))
    if abs(float(answer["fraction"]) - recomputed) > 1e-9:
        return _fail("fraction")
    png = Path(answer["png"])
    if not png.is_file() or png.stat().st_size < int(crit.get("figure_min_bytes", 5000)) or \
            png.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
        return _fail("figure")
    category = _t6_runs(answer.get(RUNS_KEY))
    if category is not None:
        return _fail(category)
    return outcome_from_cases(np.ones(len(names) + 3 + len(RUNS_NAMES), dtype=bool), real_data=True)


def _obspy_pixels(plane: Sequence[float]) -> Optional[np.ndarray]:
    """ObsPy's beachball of one plane, drawn as the notebook's drawing cell draws it (Matplotlib's default
    settings), as RGBA bytes of its PNG."""
    import matplotlib.style
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from obspy.imaging.beachball import beach

    buffer = io.BytesIO()
    with matplotlib.style.context("default"):
        fig = Figure(figsize=(3.0, 3.0), dpi=100)
        FigureCanvasAgg(fig)
        ax = fig.add_axes([0.0, 0.0, 1.0, 1.0])
        ax.add_collection(beach(list(plane), xy=(0.0, 0.0), width=2.0, linewidth=1.0, facecolor="0.55"))
        ax.set_xlim(-1.05, 1.05)
        ax.set_ylim(-1.05, 1.05)
        ax.set_aspect("equal")
        ax.axis("off")
        fig.savefig(buffer, format="png", dpi=100)
    return _png_pixels(buffer.getvalue())


def _png_pixels(data: bytes) -> Optional[np.ndarray]:
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as image:
            return np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
    except Exception:  # noqa: BLE001 - an unreadable picture is the same problem
        return None


def _t6_runs(path: Any) -> Optional[str]:
    """The table of the three ObsPy runs: None when it holds, else the failing category."""
    import pandas as pd

    if not isinstance(path, (str, Path)) or not Path(path).is_file():
        return "obspy-runs"
    try:
        runs = pd.read_csv(path, dtype={"run": str, "plane": str, "png": str, "sha256": str})
    except Exception:  # noqa: BLE001
        return "obspy-runs"
    if any(c not in runs.columns for c in RUNS_COLUMNS) or \
            runs["run"].fillna("").str.strip().tolist() != list(RUNS_NAMES):
        return "obspy-runs"
    try:
        angles = runs[["strike", "dip", "rake"]].astype(float).to_numpy()
        counts = runs[list(RUNS_COUNTS)].astype(float).to_numpy()
    except (TypeError, ValueError):
        return "obspy-runs"
    files = [Path(str(p).strip()) for p in runs["png"].fillna("")]
    if not np.all(np.isfinite(angles)) or not np.all(np.isfinite(counts)) or \
            not all(f.is_file() and f.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" for f in files):
        return "obspy-runs"

    def bulletin(plane: np.ndarray) -> Optional[int]:
        return next((k for k, p in enumerate(BULLETIN_PLANES) if abs(_wrap(plane[0] - p[0])) <= 0.5 and
                     abs(plane[1] - p[1]) <= 0.5 and abs(_wrap(plane[2] - p[2])) <= 0.5), None)

    which = [bulletin(a) for a in angles]
    if which[0] is None or which[1] != which[0] or which[2] is None or which[2] == which[0]:
        return "obspy-planes"
    if any(hashlib.sha256(f.read_bytes()).hexdigest() != str(h).strip().lower()
           for f, h in zip(files, runs["sha256"].fillna(""))):
        return "obspy-sha256"
    pixels = [_png_pixels(f.read_bytes()) for f in files]
    if any(p is None for p in pixels):
        return "obspy-runs"
    for got, k in zip(pixels, which):
        want = _obspy_pixels(BULLETIN_PLANES[k])
        if want is None or got.shape != want.shape or not np.array_equal(got, want):
            return "obspy-pixels"
    for got, row in zip(pixels, counts):
        gap = np.abs(pixels[0].astype(int) - got.astype(int)).max(axis=2)
        grey = np.all(np.abs(got[..., :3].astype(int) - 140) <= 3, axis=2)
        mine = (gap.size, int((gap > 0).sum()), int((gap > 64).sum()), int(grey.sum()))
        if any(int(round(v)) != m for v, m in zip(row, mine)):
            return "obspy-pixels"
    return None


def check_T6(target: Any, ctx: Any) -> Outcome:
    if not _t6_shape(target):
        return outcome_from_cases([False], category="format")
    guard = _t6_guard(target["agreement"], ctx)
    if guard is not None:
        return guard
    failed = _t6_function(target["agreement"], ctx)
    if failed is not None:
        return failed
    return _t6_files(target, ctx)
