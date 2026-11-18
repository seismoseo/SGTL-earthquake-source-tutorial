"""Checkers for M30 · Travel times in a layered crust.

Where the truth comes from (DESIGN.md section 1, rule 1):

* M30-T1: construction and an independent library. One-layer models: the straight-line formula of a homogeneous
  half-space. Two-layer models: Fermat's principle by brute force (the time through every crossing point on the
  boundary, then a bounded minimizer around the best one). The shipped models and a random four-layer model:
  ObsPy's TauP, which works on a sphere, run on an Earth-flattened copy of the flat model; the flattening makes its
  times those of the flat layers to well under a millisecond at the distances used (< 150 km). The student may not
  use obspy.taup or pyrocko in this task.
* M30-T2: Fermat's principle leg by leg (each down and up leg of the head wave minimized on its own with a bounded
  numerical minimizer, which gives the time and the sideways reach of the leg); crossover distances by bisection
  on the difference between that head-wave time and the direct-wave time of the half-space formula or of the
  two-layer brute force (every source of the cases lies in the first or second layer).
* M30-T3: construction (S-P times on exact lines through a known origin time and Vp/Vs) and numpy.polyfit as the
  oracle on noisy lines (polyfit and its relatives are forbidden in the student's function). On the student's own
  Sangju picks only loose physical bounds: Vp/Vs between the criteria's limits, and the origin time within the
  criteria's limit of the KMA origin time (public, data/catalogs). No real-data value is printed.
* M30-T4: construction: made-up models of one to three layers with the source in the top layer, observed times
  made from the check's own first arrival (the earliest of its straight-line direct wave and its leg-formula head
  waves, the two functions it hands to the student's function) plus residuals the check chose; the slopes from
  numpy.polyfit (forbidden in the student's function).
* M30-T5: the production tool itself. TauP on the shipped models, built from the same layers as the notebook's
  helper builds them (constant speeds, the Moho named, the deep Earth of ak135), compared with the student's
  wrapper at random distances and depths; two calls with the same input must give identical numbers.

Failure categories are keys of ``checks/specs/M30.yaml``; the engine prints their fixed messages.
"""
from __future__ import annotations

import contextlib
import functools
import io
import math
import numbers
import tempfile
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import Outcome, outcome_from_cases

__all__ = ["check_T1", "check_T2", "check_T3", "check_T4", "check_T5"]

MAIN_EVENT = "2019009762"                 # the ML 3.9 Sangju earthquake of 21 July 2019 (KMA catalog)
EARTH_KM = 6371.0
KM_PER_DEGREE = EARTH_KM * math.pi / 180.0
FLAT_POWER = 0.999                        # flattened speeds: v (r / R) ** FLAT_POWER (a tiny gradient for TauP)
JOIN_KM = 200.0                           # the half-space ends here; the deep Earth of ak135 follows
NINE_HOURS_S = 9 * 3600.0


# ------------------------------------------------------------------------------------------- helpers
def _call(func: Any, *args: Any, **kwargs: Any) -> Tuple[Any, Optional[BaseException]]:
    """Run the student's code. NotImplementedError passes through (the engine reports NOT STARTED)."""
    try:
        return func(*args, **kwargs), None
    except NotImplementedError:
        raise
    except Exception as exc:  # noqa: BLE001 - classified by the caller
        return None, exc


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


def _other(phase: str) -> str:
    return "S" if phase == "P" else "P"


def _real(value: Any) -> bool:
    return isinstance(value, numbers.Real) and not isinstance(value, (bool, np.bool_))


def _as_values(got: Any, scalar: bool, size: int) -> Optional[np.ndarray]:
    """The student's result as a float array, or None when its type or shape breaks the contract."""
    if scalar:
        return np.array([float(got)]) if _real(got) else None
    if not isinstance(got, np.ndarray) or got.shape != (size,):
        return None
    try:
        return got.astype(float)
    except (TypeError, ValueError):
        return None


def _first(cats: Sequence[Optional[str]], priority: Sequence[str]) -> Optional[str]:
    present = {c for c in cats if c}
    return next((c for c in priority if c in present), None)


def _fmt_x(x: Any) -> Any:
    arr = np.atleast_1d(np.asarray(x, dtype=float))
    return round(float(arr[0]), 4) if np.ndim(x) == 0 else f"{arr.size} distances from {arr.min():.4g} to " \
                                                            f"{arr.max():.4g} km"


# ----------------------------------------------------------------------------- TauP (independent library)
def _ak135_below(depth_km: float) -> List[str]:
    """Lines of ObsPy's ak135 model file below depth_km, with its core boundaries (the deep Earth TauP needs)."""
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


def _nd_lines(model: Any, flatten: bool) -> List[str]:
    """A TauP '.nd' model of the flat layers: constant speeds, or their Earth-flattened spherical twin."""
    tops = np.asarray(model["top_km"], dtype=float)
    vp = np.asarray(model["vp"], dtype=float)
    vs = np.asarray(model["vs"], dtype=float)
    ends = list(tops[1:]) + [JOIN_KM]
    lines = []
    for j, top in enumerate(tops):
        if j == len(tops) - 1 and j > 0:
            lines.append("mantle")
        for z in (top, ends[j]):
            if flatten:
                radius = EARTH_KM * math.exp(-z / EARTH_KM)
                scale = (radius / EARTH_KM) ** FLAT_POWER
                lines.append(f"{EARTH_KM - radius:.9f} {vp[j] * scale:.9f} {vs[j] * scale:.9f} 2.70")
            else:
                lines.append(f"{z:.6f} {vp[j]:.6f} {vs[j]:.6f} 2.70")
    deep = EARTH_KM * (1.0 - math.exp(-JOIN_KM / EARTH_KM)) if flatten else JOIN_KM
    return lines + _ak135_below(deep)


def _taup_model(model: Any, flatten: bool = True):
    from obspy.taup import TauPyModel
    from obspy.taup.taup_create import build_taup_model

    with tempfile.TemporaryDirectory(prefix="sgtl-m30-") as tmp:
        source = Path(tmp) / "layers.nd"
        source.write_text("\n".join(_nd_lines(model, flatten)) + "\n")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
                warnings.catch_warnings():
            warnings.simplefilter("ignore")
            build_taup_model(str(source), output_folder=tmp, verbose=False)
            return TauPyModel(model=str(Path(tmp) / "layers.npz"))


def _taup_time(taup: Any, x_km: float, depth_km: float, name: str, flatten: bool = True) -> float:
    """Earliest TauP time of phase `name` (or of every phase when name is None); NaN when there is none."""
    depth = EARTH_KM * (1.0 - math.exp(-depth_km / EARTH_KM)) if flatten else depth_km
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        arrivals = taup.get_travel_times(source_depth_in_km=depth, distance_in_degree=x_km / KM_PER_DEGREE,
                                         phase_list=[name] if name else ["ttall"])
    times = [a.time for a in arrivals if name is None or a.name == name]
    return float(min(times)) if times else float("nan")


def _taup_times(taup: Any, xs: np.ndarray, depth_km: float, name: Optional[str], flatten: bool = True):
    return np.array([_taup_time(taup, float(x), depth_km, name, flatten) for x in np.atleast_1d(xs)])


# ---------------------------------------------------------------------- Fermat's principle by brute force
def _bounded_min(f: Any, lo: float, hi: float, points: int = 2001) -> Tuple[float, float]:
    """(smallest value, where) of a smooth function of one variable on [lo, hi]: a grid, then Brent's method."""
    from scipy.optimize import minimize_scalar

    grid = np.linspace(lo, hi, points)
    values = np.asarray(f(grid), dtype=float)       # f takes an array (numpy arithmetic) or one number
    k = int(np.nanargmin(values))
    a, b = grid[max(k - 1, 0)], grid[min(k + 1, points - 1)]
    if b <= a:
        return float(values[k]), float(grid[k])
    best = minimize_scalar(f, bounds=(a, b), method="bounded", options={"xatol": 1e-12})
    if best.fun < values[k]:
        return float(best.fun), float(best.x)
    return float(values[k]), float(grid[k])


def _two_layer_time(x: float, depth: float, z1: float, v1: float, v2: float) -> float:
    """Least time from depth (below the boundary z1) to the surface point at distance x, over every crossing."""
    below = depth - z1
    if x <= 0.0:
        return z1 / v1 + below / v2
    value, _ = _bounded_min(lambda a: np.hypot(a, below) / v2 + np.hypot(x - a, z1) / v1, 0.0, x, 4001)
    return value


def _direct_brute(x: float, depth: float, model: Any, phase: str) -> float:
    """Direct-wave time when the source lies in the first or second layer (formula, or Fermat by brute force)."""
    tops, speed = _speeds(model, phase)
    if depth <= tops[1]:
        return float(math.hypot(x, depth) / speed[0])
    if len(tops) > 2 and depth > tops[2]:
        raise ValueError("the brute-force direct time handles sources in the first two layers only")
    return _two_layer_time(x, depth, float(tops[1]), float(speed[0]), float(speed[1]))


def _head_legs(model: Any, depth: float, phase: str, n: int) -> Optional[Tuple[float, float, float]]:
    """(speed along the boundary, time delay, critical distance) of the head wave along the top of layer n.

    Each leg (down from the source, up to the surface) is a straight segment in one layer; its share of the time,
    hypot(s, d) / v - s / v_n for a sideways reach s, is minimized numerically and on its own.
    None when the wave cannot exist (source not above the boundary, or a layer above it as fast or faster)."""
    tops, speed = _speeds(model, phase)
    if n <= 0 or depth >= tops[n] or speed[:n].max() >= speed[n]:
        return None
    vn = float(speed[n])
    delay = reach = 0.0
    for j in range(n):
        bottom = float(tops[j + 1])
        for d in (bottom - float(tops[j]), max(0.0, bottom - max(float(tops[j]), depth))):
            if d <= 0.0:
                continue
            v = float(speed[j])
            value, s = _bounded_min(lambda a, d=d, v=v: np.hypot(a, d) / v - a / vn, 0.0, 400.0 * d)
            delay += value
            reach += s
    return vn, delay, reach


# =========================================================================================== M30-T1
T1_PRIORITY = ("format", "changed-input", "zero-distance", "phase", "straight-ray", "source-depth",
               "fastest-layer", "not-converged", "wrong-values")


def _straight_ray(x: np.ndarray, depth: float, model: Any, phase: str) -> np.ndarray:
    """A straight line from the source to the station, each layer crossed in proportion to its thickness."""
    tops, speed = _speeds(model, phase)
    ends = np.concatenate([tops[1:], [np.inf]])
    share = np.clip(np.minimum(ends, depth) - tops, 0.0, None)
    return np.hypot(x, depth) / depth * float(np.sum(share / speed))


def _t1_cases(rng: np.random.Generator, crit: dict) -> List[dict]:
    cases: List[dict] = []
    # one layer: the formula of a homogeneous half-space
    for i in range(int(crit.get("half_space_cases", 6))):
        vp = rng.uniform(4.5, 8.0)
        model = _frame([0.0], [vp], [vp / rng.uniform(1.6, 1.9)])
        phase = "P" if i % 2 == 0 else "S"
        depth = rng.uniform(1.0, 30.0)
        x: Any = float(rng.uniform(0.0, 150.0)) if i < 2 else np.concatenate([[0.0], rng.uniform(0.0, 150.0, 7)])
        cases.append({"model": model, "depth": depth, "x": x, "phase": phase, "kind": "half-space",
                      "truth": lambda xs, ph, m=model, d=depth: np.hypot(xs, d) / _speeds(m, ph)[1][0]})
    # two layers, brute force: source below the boundary (one case with a slower lower layer), source above it
    # the slower lower layer: v2 / v1 below 7/8 and a thin cover, so that the far ray (148 km) needs p within a few
    # parts in a thousand of 1 / v1, and any p between 1 / v1 and 1 / v2 would make sin(i) > 1 in the top layer
    specs = [("below", False), ("below", False), ("below", True), ("above", False)]
    for i, (where, slower) in enumerate(specs):
        z1 = rng.uniform(3.0, 8.0) if slower else rng.uniform(3.0, 15.0)
        v1 = rng.uniform(5.0, 6.2)
        v2 = v1 * (rng.uniform(0.80, 0.87) if slower else rng.uniform(1.05, 1.25))
        ratio = rng.uniform(1.65, 1.85)
        model = _frame([0.0, z1], [v1, v2], [v1 / ratio, v2 / ratio])
        if where == "above":
            depth = z1 * rng.uniform(0.3, 0.9)
        else:
            depth = z1 + (rng.uniform(1.0, 6.0) if slower else rng.uniform(1.0, 15.0))
        phase = "P" if i % 2 == 0 else "S"
        xs = np.concatenate([[0.0], np.sort(rng.uniform(1.0, 150.0, 5)), [148.0]])   # one far, near-grazing ray

        def truth(xv, ph, model=model, depth=depth, z1=z1):
            tops, speed = _speeds(model, ph)
            if depth <= z1:
                return np.hypot(xv, depth) / speed[0]
            return np.array([_two_layer_time(float(a), depth, z1, float(speed[0]), float(speed[1]))
                             for a in np.atleast_1d(xv)])
        cases.append({"model": model, "depth": depth, "x": xs, "phase": phase, "kind": f"two-layer-{where}",
                      "slower": slower, "truth": truth, "bottom": z1 if where == "above" else None})
    # the shipped models and a random four-layer model: TauP on the flattened layers
    rand_tops = np.concatenate([[0.0], np.add.accumulate(rng.uniform(2.0, 11.0, 3))])
    rand_vp = np.sort(rng.uniform(5.2, 7.9, 4))
    rand = _frame(rand_tops, rand_vp, rand_vp / rng.uniform(1.65, 1.85))
    for name, model, depths in (("kim1983", _shipped("kim1983"), (14.0, rng.uniform(16.0, 30.0))),
                                ("kim2011", _shipped("kim2011"), (14.0, rng.uniform(21.0, 30.0))),
                                ("random", rand, (rng.uniform(rand_tops[2], rand_tops[3]) + 0.5,))):
        taup = _taup_model(model)
        for j, depth in enumerate(depths):
            phase = "P" if j % 2 == 0 else "S"
            xs = np.sort(np.concatenate([[0.3, 100.0], rng.uniform(1.0, 145.0, 6)]))

            def truth(xv, ph, taup=taup, depth=depth):
                return _taup_times(taup, np.atleast_1d(xv), depth, "p" if ph == "P" else "s")
            cases.append({"model": model, "depth": float(depth), "x": xs, "phase": phase, "kind": f"taup-{name}",
                          "truth": truth})
    return cases


def _t1_judge(case: dict, got: Any, tol: float) -> Tuple[np.ndarray, Optional[str], Optional[np.ndarray]]:
    x, scalar = case["x"], np.ndim(case["x"]) == 0
    xs = np.atleast_1d(np.asarray(x, dtype=float))
    values = _as_values(got, scalar, xs.size)
    if values is None:
        return np.zeros(xs.size, dtype=bool), "format", None
    truth = np.asarray(case["truth"](xs, case["phase"]), dtype=float)
    err = np.abs(values - truth)
    ok = (np.isfinite(values) & (err <= tol)) | np.isnan(truth)     # no oracle value there: not judged
    if ok.all():
        return ok, None, truth
    bad = ~ok
    def near(alt: np.ndarray) -> bool:
        return bool(np.all(np.isfinite(values[bad]) & (np.abs(values[bad] - alt[bad]) <= tol)))
    if np.all(xs[bad] == 0.0):
        return ok, "zero-distance", truth
    other = np.asarray(case["truth"](xs, _other(case["phase"])), dtype=float)
    if near(other):
        return ok, "phase", truth
    if case["kind"] != "half-space" and xs.size > 1 and near(_straight_ray(xs, case["depth"], case["model"],
                                                                            case["phase"])):
        return ok, "straight-ray", truth
    if case.get("bottom") is not None:
        speed = _speeds(case["model"], case["phase"])[1][0]
        if near(np.hypot(xs, case["bottom"]) / speed):
            return ok, "source-depth", truth
    if np.all(np.isfinite(values[bad]) & (err[bad] <= 0.01 * truth[bad] + 0.02)):
        return ok, "not-converged", truth
    if case.get("slower"):
        return ok, "fastest-layer", truth
    return ok, "wrong-values", truth


def check_T1(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    tol = float(crit.get("tol_s", 0.005))
    cases = _t1_cases(ctx.rng, crit)
    oks: List[np.ndarray] = []
    cats: List[Optional[str]] = []
    example = None
    for case in cases:
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
        ok, cat, truth = _t1_judge(case, got, tol)
        oks.append(ok)
        cats.append(cat)
        if cat and example is None:
            rows = [f"top {t:g} km: vp {p:.3f}, vs {s:.3f}" for t, p, s in
                    zip(model["top_km"], model["vp"], model["vs"])]
            example = {"inputs": {"x_km": _fmt_x(case["x"]), "depth_km": round(case["depth"], 3),
                                  "model": "; ".join(rows), "phase": case["phase"]},
                       "got": got if np.ndim(case["x"]) == 0 or truth is None else
                       np.round(np.asarray(got, dtype=float)[~ok][:3], 4).tolist(),
                       "error": ("wrong type or shape" if truth is None else
                                 f"expected {np.round(truth[~ok][:3], 4).tolist()} s at "
                                 f"{np.round(np.atleast_1d(case['x'])[~ok][:3], 3).tolist()} km")}
    category = _first(cats, T1_PRIORITY)
    all_ok = np.concatenate(oks)
    if category and all_ok.all():
        all_ok = np.append(all_ok, False)
    return outcome_from_cases(all_ok, category=category, example=example)


# =========================================================================================== M30-T2
T2_PRIORITY = ("format", "no-head-wave", "phase", "surface-source", "no-nan", "head-time", "critical",
               "crossover", "wrong-values")


def _t2_cases(rng: np.random.Generator) -> List[dict]:
    k83, k11 = _shipped("kim1983"), _shipped("kim2011")
    rand_tops = [0.0, rng.uniform(4.0, 12.0)]
    rand_tops.append(rand_tops[1] + rng.uniform(8.0, 20.0))
    rand_vp = np.sort(rng.uniform(5.3, 7.9, 3))
    ratio = rng.uniform(1.68, 1.82)
    rand = _frame(rand_tops, rand_vp, rand_vp / ratio)
    fast = _frame([0.0, 12.0, 28.0], [6.0, 7.2, 6.8], np.array([6.0, 7.2, 6.8]) / 1.73)
    return [
        {"model": k83, "depth": 14.0, "phase": "P", "n": -1, "name": "kim1983"},
        {"model": k83, "depth": 14.0, "phase": "S", "n": 1, "name": "kim1983"},
        {"model": k11, "depth": rng.uniform(2.0, 6.5), "phase": "P", "n": 1, "name": "kim2011"},
        {"model": k11, "depth": 14.0, "phase": "S", "n": -1, "name": "kim2011"},
        {"model": k11, "depth": 14.0, "phase": "P", "n": 1, "name": "kim2011"},          # source below it
        {"model": rand, "depth": rng.uniform(1.0, rand_tops[1] - 0.5), "phase": "S", "n": 2, "name": "random"},
        {"model": rand, "depth": rng.uniform(rand_tops[1] + 0.5, rand_tops[2] - 0.5), "phase": "P", "n": -1,
         "name": "random"},
        {"model": fast, "depth": 8.0, "phase": "P", "n": -1, "name": "fast-middle"},     # a faster layer above
    ]


def _t2_truth(case: dict, xs: np.ndarray, phase: Optional[str] = None, depth: Optional[float] = None,
              crossover: bool = True) -> Optional[dict]:
    phase = phase or case["phase"]
    depth = case["depth"] if depth is None else depth
    n = case["n"] % len(case["model"])
    legs = _head_legs(case["model"], depth, phase, n)
    if legs is None:
        return None
    vn, delay, reach = legs
    times = np.where(xs >= reach, xs / vn + delay, np.nan)
    out = {"t": times, "crit": reach, "cross": float("nan"), "vn": vn, "delay": delay}
    if crossover:
        def gap(x: float) -> float:
            return _direct_brute(x, depth, case["model"], phase) - (x / vn + delay)
        lo, hi = reach, reach + 50.0
        while gap(hi) < 0.0 and hi < 5000.0:
            lo, hi = hi, 2.0 * hi
        for _ in range(45):
            mid = 0.5 * (lo + hi)
            lo, hi = (mid, hi) if gap(mid) < 0.0 else (lo, mid)
        out["cross"] = 0.5 * (lo + hi)
    return out


def _t2_parts(got: Any, scalar: bool, size: int) -> Optional[Tuple[np.ndarray, float, float]]:
    if not isinstance(got, tuple) or len(got) != 3:
        return None
    times = got[0]
    if scalar:
        if not (_real(times) or (isinstance(times, float))):
            return None
        values = np.array([float(times)])
    else:
        values = _as_values(times, False, size)
        if values is None:
            return None
    if not (_real(got[1]) and _real(got[2])):
        return None
    return values, float(got[1]), float(got[2])


def _t2_judge(case: dict, xs: np.ndarray, values: np.ndarray, x_crit: float, x_cross: float, truth: dict,
              crit: dict) -> Optional[str]:
    tol = float(crit.get("tol_s", 0.005))
    away = np.abs(xs - truth["crit"]) > 0.05           # the grid point next to the critical distance is left out
    live, mine = np.isfinite(truth["t"]), np.isfinite(values)
    both = live & mine & away

    def matches(other: Optional[dict]) -> bool:
        return other is not None and bool(both.any()) and \
            bool(np.all(np.abs(values[both] - other["t"][both]) <= tol))

    if (live & away).any() and not matches(truth):
        if matches(_t2_truth(case, xs, phase=_other(case["phase"]), crossover=False)):
            return "phase"
        if matches(_t2_truth(case, xs, depth=1e-9, crossover=False)):
            return "surface-source"
        return "head-time"
    if abs(x_crit - truth["crit"]) > float(crit.get("critical_tol_km", 0.02)):
        return "critical"
    if (mine & ~live & away).any():
        return "no-nan"
    if (live & ~mine & away).any():
        return "head-time"
    cross_ok = abs(x_cross - truth["cross"]) <= float(crit.get("crossover_rel_tol", 0.01)) * truth["cross"] + \
        float(crit.get("crossover_abs_tol_km", 0.1))
    return None if cross_ok else "crossover"


def check_T2(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    rng = ctx.rng
    cases = _t2_cases(rng)
    grid = np.linspace(0.0, 300.0, 61)
    oks: List[bool] = []
    cats: List[Optional[str]] = []
    example = None
    for i, case in enumerate(cases):
        scalar = i == 1
        xs = np.array([rng.uniform(80.0, 140.0)]) if scalar else grid
        x_arg: Any = float(xs[0]) if scalar else xs.copy()
        got, err = _call(target, x_arg, case["depth"], case["model"], case["phase"], case["n"])
        if err is not None:
            raise err
        parts = _t2_parts(got, scalar, xs.size)
        truth = _t2_truth(case, xs)
        cat: Optional[str] = None
        if parts is None:
            cat = "format"
        else:
            values, x_crit, x_cross = parts
            if truth is None:
                if np.isfinite(values).any() or np.isfinite(x_crit) or np.isfinite(x_cross):
                    cat = "no-head-wave"
            else:
                cat = _t2_judge(case, xs, values, x_crit, x_cross, truth, crit)
        oks.append(cat is None)
        cats.append(cat)
        if cat and example is None:
            example = {"inputs": {"x_km": _fmt_x(x_arg), "depth_km": round(case["depth"], 3),
                                  "model": case["name"] if case["name"] != "random" else
                                  "; ".join(f"top {t:g} km: vp {p:.3f}, vs {s:.3f}" for t, p, s in
                                            zip(case["model"]["top_km"], case["model"]["vp"],
                                                case["model"]["vs"])),
                                  "phase": case["phase"], "interface": case["n"]},
                       "got": got if scalar or parts is None else
                       {"critical distance (km)": round(parts[1], 4), "crossover distance (km)": round(parts[2], 4)},
                       "error": ("no head wave exists here" if truth is None else
                                 f"critical distance {truth['crit']:.3f} km, crossover {truth['cross']:.2f} km")}
    category = _first(cats, T2_PRIORITY)
    return outcome_from_cases(np.array(oks), category=category, example=example)


# =========================================================================================== M30-T3
T3_PRIORITY = ("format", "ratio-minus-one", "inverse-ratio", "origin-sign", "through-origin", "swapped-axes",
               "wrong-values")


def _t3_cases(rng: np.random.Generator, crit: dict) -> List[dict]:
    cases = []
    for i in range(int(crit.get("trials", 12))):
        n = int(rng.integers(5, 16))
        ratio = rng.uniform(1.6, 1.9)
        vp = rng.uniform(5.5, 6.8)
        t0 = rng.uniform(5.0, 60.0)                      # seconds after the reference moment
        dist = rng.uniform(8.0, 120.0, n)
        tp = t0 + dist / vp
        ts = t0 + dist * ratio / vp
        noisy = i >= int(crit.get("trials", 12)) // 2
        if noisy:
            tp = tp + rng.normal(0.0, rng.uniform(0.03, 0.15), n)
            ts = ts + rng.normal(0.0, rng.uniform(0.05, 0.3), n)
            slope, cut = np.polyfit(tp, ts - tp, 1)       # the oracle: a library least-squares line
            truth = (-cut / slope, 1.0 + slope)
        else:
            truth = (t0, ratio)
        order = rng.permutation(n)
        cases.append({"tp": tp[order], "ts": ts[order], "truth": truth, "noisy": noisy, "as_list": i == 1})
    return cases


def _t3_alternatives(tp: np.ndarray, ts: np.ndarray, truth: Tuple[float, float]) -> Dict[str, Tuple[float, float]]:
    sp = ts - tp
    alt = {"ratio-minus-one": (truth[0], truth[1] - 1.0), "inverse-ratio": (truth[0], 1.0 / truth[1]),
           "origin-sign": (-truth[0], truth[1])}
    slope0 = float(np.sum(tp * sp) / np.sum(tp * tp))
    alt["through-origin"] = (0.0, 1.0 + slope0)
    back, cut = np.polyfit(sp, tp, 1)                     # P time against S-P time, then turned around
    alt["swapped-axes"] = (cut, 1.0 + 1.0 / back)
    return alt


def _t3_pairs(picks: Any, origin) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """P and S times (s after origin) at the stations that have both, from the student's pick table."""
    from obspy import UTCDateTime

    try:
        names = [str(s).strip() for s in picks["station"]]
        phases = [str(p).strip().upper()[:1] for p in picks["phase"]]
        when = [float(UTCDateTime(t.strip() if isinstance(t, str) else t) - origin) for t in picks["time"]]
    except Exception:  # noqa: BLE001 - any unusable table is 'no-picks'
        return None
    first: Dict[Tuple[str, str], float] = {}
    for name, phase, t in zip(names, phases, when):
        if phase in ("P", "S") and math.isfinite(t):
            key = (name, phase)
            first[key] = min(t, first.get(key, math.inf))
    both = sorted(n for n, ph in first if ph == "P" and (n, "S") in first)
    if not both:
        return None
    return np.array([first[(n, "P")] for n in both]), np.array([first[(n, "S")] for n in both])


def _event_origin(event_id: str):
    from obspy import UTCDateTime

    from .. import data as _data

    cat = _data.kma_catalog()
    rows = cat.loc[cat["event_id"] == str(event_id)]
    return None if rows.empty else UTCDateTime(rows.iloc[0]["origin_utc"].isoformat())


def check_T3(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    t_tol, r_tol = float(crit.get("origin_tol_s", 1e-6)), float(crit.get("ratio_tol", 1e-6))
    oks: List[bool] = []
    cats: List[Optional[str]] = []
    example = None
    for case in _t3_cases(ctx.rng, crit):
        tp, ts = case["tp"], case["ts"]
        args = (tp.tolist(), ts.tolist()) if case["as_list"] else (tp.copy(), ts.copy())
        got, err = _call(target, *args)
        if err is not None:
            raise err
        cat = None
        if not (isinstance(got, tuple) and len(got) == 2 and all(_real(g) for g in got)
                and all(math.isfinite(float(g)) for g in got)):
            cat = "format"
        else:
            t0, ratio = float(got[0]), float(got[1])
            good = lambda pair: abs(t0 - pair[0]) <= t_tol * max(1.0, abs(pair[0])) and \
                abs(ratio - pair[1]) <= r_tol * abs(pair[1])
            if not good(case["truth"]):
                alts = _t3_alternatives(tp, ts, case["truth"])
                cat = next((name for name in T3_PRIORITY[1:-1] if name in alts and good(alts[name])),
                           "wrong-values")
        oks.append(cat is None)
        cats.append(cat)
        if cat and example is None:
            example = {"inputs": {"tp_s": np.round(tp, 4).tolist(), "ts_s": np.round(ts, 4).tolist()},
                       "got": got, "error": f"expected t0 = {case['truth'][0]:.6f} s, vp_vs = "
                                            f"{case['truth'][1]:.6f}"}
    category = _first(cats, T3_PRIORITY)
    if category:
        return outcome_from_cases(np.array(oks), category=category, example=example)

    # the student's own picks of the Sangju mainshock: loose physical bounds only, nothing printed
    n_synth = len(oks)
    picks = ctx.get("picks")
    origin = _event_origin(str(ctx.get("event") or MAIN_EVENT))
    pairs = None if picks is None or origin is None else _t3_pairs(picks, origin)
    min_n = int(crit.get("min_stations", 5))
    if pairs is None or pairs[0].size < min_n:
        return Outcome(passed=False, n_cases=n_synth + 1, n_failed=1, category="no-picks",
                       details={"real_data": True})
    got, err = _call(target, pairs[0].copy(), pairs[1].copy())
    if err is not None:
        raise err
    t0, ratio = float(got[0]), float(got[1])
    low, high = (float(v) for v in crit.get("vp_vs_range", (1.60, 1.95)))
    cat = None
    if abs(abs(t0) - NINE_HOURS_S) <= 600.0:
        cat = "time-zone"
    elif not (low <= ratio <= high) or abs(t0) > float(crit.get("origin_window_s", 2.0)):
        cat = "implausible"
    note = (f"Your own Sangju picks: {pairs[0].size} stations with both P and S; your Vp/Vs and origin time are "
            "within the physical bounds of the criteria file (the values are not printed).") if cat is None else None
    return Outcome(passed=cat is None, n_cases=n_synth + 1, n_failed=0 if cat is None else 1, category=cat,
                   details={"real_data": True, **({"note": note} if note else {})})


# =========================================================================================== M30-T4
# "boundaries" ranks above "direct-only": with a fast middle layer, the Moho alone gives the direct wave alone
T4_PRIORITY = ("format", "changed-input", "own-function", "nan-head", "boundaries", "direct-only", "phase", "sign",
               "order", "no-shift", "per-phase-shift", "shift", "slope", "wrong-values")


@functools.lru_cache(maxsize=512)
def _t4_legs(tops: Tuple[float, ...], speed: Tuple[float, ...], depth: float,
             n: int) -> Optional[Tuple[float, float, float]]:
    return _head_legs(_frame(tops, speed, speed), depth, "P", n)


def _t4_head_parts(model: Any, depth: float, phase: str, n: int) -> Optional[Tuple[float, float, float]]:
    """(speed along the top of layer n, time delay, critical distance) from Fermat's principle leg by leg
    (_head_legs, kept for each model, depth and boundary); None when no head wave runs there."""
    tops, speed = _speeds(model, phase)
    if not 0 < n < len(tops):
        return None
    return _t4_legs(tuple(float(t) for t in tops), tuple(float(v) for v in speed), float(depth), int(n))


def _t4_direct_times(x: np.ndarray, depth: float, model: Any, phase: str) -> np.ndarray:
    """Direct wave of a source in the top layer: the straight line at the speed of that layer."""
    _, speed = _speeds(model, phase)
    return np.hypot(x, depth) / float(speed[0])


def _t4_head_times(x: np.ndarray, depth: float, model: Any, phase: str, n: int) -> np.ndarray:
    parts = _t4_head_parts(model, depth, phase, n)
    if parts is None:
        return np.full(x.shape, np.nan)
    v_n, delay, x_crit = parts
    return np.where(x >= x_crit, x / v_n + delay, np.nan)           # the head wave exists from x_crit on


def _t4_first(x: np.ndarray, depth: float, model: Any, phase: str,
              boundaries: Optional[Sequence[int]] = None) -> np.ndarray:
    """The model's first arrival (or, with some boundaries left out, a usual slip): the earliest wave, NaN-free."""
    times = _t4_direct_times(x, depth, model, phase)
    for n in (range(1, len(model)) if boundaries is None else boundaries):
        times = np.fmin(times, _t4_head_times(x, depth, model, phase, n))
    return times


def _t4_distances(rng: np.random.Generator, depth: float, model: Any, phase: str, count: int) -> np.ndarray:
    """count distances (2-220 km): two inside the range of every wave that comes first somewhere, the rest anywhere."""
    if count < 2:
        return rng.uniform(2.0, 220.0, count)
    grid = np.linspace(2.0, 220.0, 1091)
    waves = [_t4_direct_times(grid, depth, model, phase)]
    waves += [_t4_head_times(grid, depth, model, phase, n) for n in range(1, len(model))]
    best = np.argmin(np.where(np.isfinite(waves), waves, np.inf), axis=0)
    chosen: List[float] = []
    for wave in np.unique(best):
        chosen += list(rng.choice(grid[best == wave], 2) + rng.uniform(-0.05, 0.05, 2))
    chosen = chosen[:count]
    return np.concatenate([chosen, rng.uniform(2.0, 220.0, count - len(chosen))])


def _t4_funcs(calls: list):
    """The check's own direct-wave and head-wave functions (called like direct_time and head_wave), recording calls."""
    def direct(x_km, depth_km, model, phase="P"):
        calls.append(("direct", float(depth_km), float(np.asarray(model["vp"], dtype=float)[0]), len(model)))
        values = _t4_direct_times(np.asarray(x_km, dtype=float), float(depth_km), model, phase)
        return float(values) if np.ndim(x_km) == 0 else values

    def head(x_km, depth_km, model, phase="P", interface=-1):
        calls.append(("head", float(depth_km), float(np.asarray(model["vp"], dtype=float)[0]), len(model)))
        n = int(interface) % len(model)
        parts = _t4_head_parts(model, float(depth_km), phase, n)
        times = _t4_head_times(np.asarray(x_km, dtype=float), float(depth_km), model, phase, n)
        if parts is None:
            x_crit = x_cross = float("nan")
        else:
            v_n, delay, x_crit = parts                                     # crossover with the direct wave
            lo, hi = x_crit, x_crit + 4000.0
            for _ in range(80):
                mid = 0.5 * (lo + hi)
                ahead = _t4_direct_times(np.array(mid), float(depth_km), model, phase) < mid / v_n + delay
                lo, hi = (mid, hi) if ahead else (lo, mid)
            x_cross = 0.5 * (lo + hi)
        return (float(times) if np.ndim(x_km) == 0 else times), x_crit, x_cross
    return direct, head


def _t4_model(rng: np.random.Generator, number: int):
    """A made-up model of one to three rows; the source always lies in the top layer."""
    vp1 = rng.uniform(5.5, 6.2)
    ratio = rng.uniform(1.65, 1.85, 3)
    if number == 0:
        tops, vp = [0.0], [vp1]
    elif number == 3:                       # a fast middle layer: no head wave along the half-space below it
        h1 = rng.uniform(8.0, 15.0)
        tops, vp = [0.0, h1, h1 + rng.uniform(10.0, 20.0)], [vp1, rng.uniform(7.4, 7.8), rng.uniform(6.6, 7.0)]
    elif number == 2:
        tops, vp = [0.0, rng.uniform(8.0, 15.0)], [vp1, vp1 + rng.uniform(0.4, 0.9)]
    else:
        h1 = rng.uniform(8.0, 15.0)
        tops = [0.0, h1, h1 + rng.uniform(12.0, 22.0)]
        vp = [vp1, vp1 + rng.uniform(0.4, 0.8), rng.uniform(7.7, 8.1)]
    vp = np.asarray(vp)
    return _frame(tops, vp, vp / ratio[:len(vp)]), rng.uniform(0.25, 0.85) * (tops[1] if len(tops) > 1 else 12.0)


def _t4_case(rng: np.random.Generator, number: int) -> dict:
    import pandas as pd

    model, depth = _t4_model(rng, number)
    n_p = int(rng.integers(8, 14))
    n_s = 1 if number == 2 else int(rng.integers(6, 12))
    phase = np.array(["P"] * n_p + ["S"] * n_s)
    dist = np.concatenate([_t4_distances(rng, depth, model, "P", n_p), _t4_distances(rng, depth, model, "S", n_s)])
    offset = rng.uniform(-1.0, 1.0)
    trend = {"P": rng.uniform(-0.01, 0.01), "S": rng.uniform(-0.02, 0.02)}
    extra = {"P": rng.uniform(-0.3, 0.3), "S": rng.uniform(-0.6, 0.6)}
    resid = np.array([offset + extra[p] + trend[p] * d for p, d in zip(phase, dist)])
    resid = resid + rng.normal(0.0, 0.1, phase.size)
    first = np.array([_t4_first(np.array([d]), depth, model, p)[0] for p, d in zip(phase, dist)])
    order = rng.permutation(phase.size)
    obs = pd.DataFrame({"station": [f"ST{k:02d}" for k in range(phase.size)], "phase": phase[order],
                        "epi_km": dist[order], "tt_s": (first + resid)[order], "note": "made up"},
                       index=rng.choice(1000, phase.size, replace=False))
    resid = resid[order]
    truth = {"residual_s": resid, "shift_s": float(resid.mean()),
             "rms_s": float(np.sqrt(np.mean((resid - resid.mean()) ** 2)))}
    for ph in ("P", "S"):
        rows = obs["phase"].to_numpy() == ph
        truth["slope_" + ph] = float(np.polyfit(obs["epi_km"].to_numpy()[rows], resid[rows], 1)[0]) \
            if rows.sum() >= 2 else float("nan")
    return {"obs": obs, "depth": depth, "model": model, "truth": truth}


def _t4_variant(case: dict, **kw: Any) -> np.ndarray:
    """Residuals that a usual slip gives (observed minus the variant's prediction), in the row order of obs."""
    obs, model, depth = case["obs"], case["model"], case["depth"]
    as_phase = kw.pop("as_phase", None)
    dist = np.asarray(obs["epi_km"], dtype=float)
    pred = np.array([_t4_first(np.array([d]), depth, model, as_phase or p, **kw)[0]
                     for p, d in zip(obs["phase"], dist)])
    return np.asarray(obs["tt_s"], dtype=float) - pred


def _t4_judge(got: Any, case: dict, calls: list, crit: dict) -> Optional[str]:
    truth, obs, model = case["truth"], case["obs"], case["model"]
    keys = ("residual_s", "shift_s", "rms_s", "slope_P", "slope_S")
    if not isinstance(got, dict) or any(k not in got for k in keys):
        return "format"
    res = got["residual_s"]
    if not isinstance(res, np.ndarray) or res.shape != (len(obs),) or \
            not all(_real(got[k]) or (isinstance(got[k], float)) for k in keys[1:]):
        return "format"
    try:
        res = res.astype(float)
    except (TypeError, ValueError):
        return "format"
    tol = float(crit.get("tol_s", 1e-9))
    slope_tol = float(crit.get("slope_rel_tol", 1e-6))
    vp = float(model["vp"].iloc[0])
    if not any(c[0] == "direct" for c in calls) or \
            any(c[2] != vp or c[3] != len(model) or abs(c[1] - case["depth"]) > 1e-12 for c in calls):
        return "own-function"
    want = truth["residual_s"]
    kinds = np.asarray(obs["phase"])

    def near(alt: np.ndarray) -> bool:
        return bool(np.allclose(res, alt, rtol=0.0, atol=tol)) and not np.allclose(alt, want, rtol=0.0, atol=tol)

    if not np.allclose(res, want, rtol=0.0, atol=tol):
        if np.isnan(res).any():
            return "nan-head"
        if near(_t4_variant(case, boundaries=())):
            return "direct-only"
        if len(model) > 2 and (near(_t4_variant(case, boundaries=(len(model) - 1,)))
                               or near(_t4_variant(case, boundaries=(1,)))):
            return "boundaries"
        as_p = _t4_variant(case, as_phase="P")
        if np.allclose(res[kinds == "S"], as_p[kinds == "S"], atol=tol) and \
                not np.allclose(as_p[kinds == "S"], want[kinds == "S"], atol=tol):
            return "phase"
        if np.allclose(res, -want, atol=tol):
            return "sign"
        if np.allclose(np.sort(res), np.sort(want), atol=tol):
            return "order"
        return "wrong-values"
    if len(model) > 1 and not any(c[0] == "head" for c in calls):
        return "own-function"                   # right values without the head-wave function it was given
    shift, rms = float(got["shift_s"]), float(got["rms_s"])
    if abs(rms - truth["rms_s"]) > tol:
        if abs(rms - float(np.sqrt(np.mean(want ** 2)))) <= tol:
            return "no-shift"
        own = want.copy()
        for kind in ("P", "S"):
            own[kinds == kind] -= want[kinds == kind].mean()
        if abs(rms - float(np.sqrt(np.mean(own ** 2)))) <= tol:
            return "per-phase-shift"
        return "wrong-values"
    if abs(shift - truth["shift_s"]) > tol:
        return "shift"
    for ph in ("P", "S"):
        a, b = float(got["slope_" + ph]), truth["slope_" + ph]
        if math.isnan(b):
            if not math.isnan(a):
                return "slope"
        elif not (abs(a - b) <= slope_tol * abs(b) + 1e-12):
            return "slope"
    return None


def check_T4(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    oks: List[bool] = []
    cats: List[Optional[str]] = []
    example = None
    for number in range(int(crit.get("trials", 6))):
        case = _t4_case(ctx.rng, number)
        calls: list = []
        obs, model = case["obs"], case["model"]
        before, model_before = obs.copy(deep=True), model.copy(deep=True)
        direct, head = _t4_funcs(calls)
        got, err = _call(target, obs, case["depth"], model, direct, head)
        if err is not None:
            raise err
        unchanged = list(obs.columns) == list(before.columns) and obs.equals(before) and model.equals(model_before)
        cat = "changed-input" if not unchanged else _t4_judge(got, case, calls, crit)
        oks.append(cat is None)
        cats.append(cat)
        if cat and example is None:
            layers = ", ".join(f"{t:.1f} km: vp {v:.2f}" for t, v in zip(model["top_km"], model["vp"]))
            example = {"inputs": {"obs rows": len(obs), "P rows": int((obs["phase"] == "P").sum()),
                                  "S rows": int((obs["phase"] == "S").sum()), "depth_km": round(case["depth"], 3),
                                  "model (top and vp of each row)": layers},
                       "got": {k: (np.round(v, 4).tolist()[:4] if isinstance(v, np.ndarray) else v)
                               for k, v in got.items()} if isinstance(got, dict) else got,
                       "error": f"expected shift {case['truth']['shift_s']:.4f} s, rms {case['truth']['rms_s']:.4f}"
                                f" s, slope_P {case['truth']['slope_P']:.6f} s/km"}
    return outcome_from_cases(np.array(oks), category=_first(cats, T4_PRIORITY), example=example)


# =========================================================================================== M30-T5
T5_PRIORITY = ("format", "not-deterministic", "degrees", "phase-name", "model", "first-arrival", "wrong-values")


def check_T5(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    tol = float(crit.get("tol_s", 0.002))
    rng = ctx.rng
    shipped = {name: _shipped(name) for name in ("kim1983", "kim2011")}
    taups = {name: _taup_model(model, flatten=False) for name, model in shipped.items()}
    runs = [("kim1983", 14.0, np.array([3.0, 12.0, 30.0, 55.0, 80.0, 100.0, 125.0, 150.0])),
            ("kim2011", float(rng.uniform(5.0, 25.0)), np.sort(rng.uniform(2.0, 150.0, 6))),
            ("kim1983", float(rng.uniform(16.0, 30.0)), np.sort(rng.uniform(2.0, 95.0, 5)))]
    oks: List[bool] = []
    cats: List[Optional[str]] = []
    example = None
    for k, (name, depth, xs) in enumerate(runs):
        got, err = _call(target, name, depth, xs.copy())
        if err is not None:
            raise err
        cat = None
        if not (isinstance(got, tuple) and len(got) == 2 and
                all(_as_values(g, False, xs.size) is not None for g in got)):
            cat = "format"
        else:
            tp, ts = (np.asarray(g, dtype=float) for g in got)
            if k == 0:
                again, err = _call(target, name, depth, xs.copy())
                if err is not None:
                    raise err
                if not (isinstance(again, tuple) and len(again) == 2 and
                        all(np.array_equal(np.asarray(a, dtype=float), b, equal_nan=True)
                            for a, b in zip(again, (tp, ts)))):
                    cat = "not-deterministic"
            if cat is None:
                want_p = _taup_times(taups[name], xs, depth, "p", flatten=False)
                want_s = _taup_times(taups[name], xs, depth, "s", flatten=False)
                good = _agree(tp, want_p, tol) and _agree(ts, want_s, tol)
                if not good:
                    if _same(tp, _taup_times(taups[name], xs * KM_PER_DEGREE, depth, "p", flatten=False), tol):
                        cat = "degrees"
                    elif not (np.isfinite(tp).all() and np.isfinite(ts).all()):
                        cat = "phase-name"
                    elif _same(tp, _taup_times(_builtin("iasp91"), xs, depth, "p", flatten=False), tol):
                        cat = "model"
                    elif _same(tp, _taup_times(taups[name], xs, depth, None, flatten=False), tol):
                        cat = "first-arrival"
                    else:
                        cat = "wrong-values"
        oks.append(cat is None)
        cats.append(cat)
        if cat and example is None:
            example = {"inputs": {"model_name": name, "depth_km": round(depth, 3),
                                  "x_km": np.round(xs, 3).tolist()},
                       "got": got if cat == "format" else [np.round(np.asarray(g, float), 4).tolist() for g in got],
                       "error": "see the category"}
    return outcome_from_cases(np.array(oks), category=_first(cats, T5_PRIORITY), example=example)


def _agree(a: np.ndarray, b: np.ndarray, tol: float) -> bool:
    """NaN in the same places and equal within tol elsewhere (TauP finds no direct wave beyond some distance
    for a shallow source under a slower layer: the sphere bends the layers away from the ray)."""
    fa, fb = np.isfinite(a), np.isfinite(b)
    return bool(np.array_equal(fa, fb) and np.all(np.abs(a[fa] - b[fb]) <= tol))


def _same(a: np.ndarray, b: np.ndarray, tol: float) -> bool:
    """Equal within tol where both are numbers, NaN in the same places (one place may differ: a ray that just
    reaches), and at least one number in common."""
    fa, fb = np.isfinite(a), np.isfinite(b)
    both = fa & fb
    return bool(both.any() and np.count_nonzero(fa != fb) <= 1 and np.all(np.abs(a[both] - b[both]) <= tol))


def _builtin(name: str):
    from obspy.taup import TauPyModel

    return TauPyModel(model=name)
