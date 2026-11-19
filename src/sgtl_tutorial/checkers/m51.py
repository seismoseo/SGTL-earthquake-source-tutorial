"""Checkers for M51 · Mechanisms from first motions.

Where the truth comes from (DESIGN.md section 1, rule 1):

* M51-T1: construction and an independent library. Made-up mechanisms and rays; the polarity a mechanism predicts
  is the sign of the ray projected on Pyrocko's moment tensor (pyrocko.moment_tensor, north-east-down axes), a
  different formula from the fault normal and slip vector of the task. Observed polarities are those signs with a
  few flipped, so the misfit is known by construction.
* M51-T2: construction. Made-up stations around a made-up mechanism, a few polarities flipped. The check hands the
  student's grid search its own misfit function (the moment tensor of Aki & Richards' table, checked against
  Pyrocko), records every mechanism it is asked about, and compares the answer with those records; then the best
  mechanisms of all cases must lie near the made-up truth (Pyrocko's Kagan angle, median over the cases).
* M51-T3: an independent library: pyrocko.moment_tensor.kagan_angle (forbidden in the student's function), on
  random pairs, on one mechanism written with either of its nodal planes, and on nearby pairs.
* M51-T4: construction. Groups of mechanisms made by small known rotations of well separated mechanisms (their
  Kagan angles from Pyrocko), misfits chosen so that the expected families follow from the construction; one
  chain of three mechanisms along one rotation axis. The check hands in its own Kagan function (Pyrocko).
* M51-T5: construction for the reader function (made-up SKHASH tables with known takeoff angles), then the
  student's own run: the SHA-256 of the copied mechanism file against work/.sgtl/runs.jsonl, the student's own
  functions rerun on the student's own SKHASH table (after a short re-test on made-up cases), the reported Kagan
  angles against Pyrocko's for the reported mechanisms, and a loose agreement with the student's own SKHASH
  mechanisms of the best-recorded events (criteria/M51.yaml).
* M51-T6: construction for the table function (made-up S/P ratios and picks), then the student's own runs: three
  copied folders, their fingerprints in the run log, the control files and inputs that show exactly one change,
  and the reported Kagan angles between the first and the changed run against Pyrocko's.

No real-data value is computed or printed here. Failure categories are keys of ``checks/specs/M51.yaml``.
"""
from __future__ import annotations

import hashlib
import json
import math
import numbers
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import Outcome, outcome_from_cases

__all__ = ["check_T1", "check_T2", "check_T3", "check_T4", "check_T5", "check_T6"]

HEX64 = re.compile(r"[0-9a-f]{64}")
FM_KEY = "mechanisms.csv"                  # the product key that sgtl logs for the mechanism stage ends with this
KIGAM = (288.0, 89.0, 7.0)                 # KIGAM 2019 bulletin, KEMS-2019-062 (one of its two planes), as printed


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


def _real(value: Any) -> bool:
    return isinstance(value, numbers.Real) and not isinstance(value, (bool, np.bool_)) and math.isfinite(float(value))


def _frame(got: Any) -> bool:
    try:
        import pandas as pd
    except ImportError:  # pragma: no cover - the course environment has pandas
        return False
    return isinstance(got, pd.DataFrame)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _pmt() -> Any:
    from pyrocko import moment_tensor
    return moment_tensor


def _kagan_oracle(a: Sequence[float], b: Sequence[float]) -> float:
    mt = _pmt()
    one = mt.MomentTensor(strike=float(a[0]), dip=float(a[1]), rake=float(a[2]))
    two = mt.MomentTensor(strike=float(b[0]), dip=float(b[1]), rake=float(b[2]))
    return float(mt.kagan_angle(one, two))


def _unit_rays(az_deg: np.ndarray, inc_deg: np.ndarray) -> np.ndarray:
    """Rays (N, 3) in north-east-down axes; inc from the downward vertical."""
    a, t = np.radians(az_deg), np.radians(inc_deg)
    return np.column_stack([np.cos(a) * np.sin(t), np.sin(a) * np.sin(t), np.cos(t)])


def _tensor_pyrocko(m: Sequence[float]) -> np.ndarray:
    mt = _pmt()
    return np.asarray(mt.MomentTensor(strike=float(m[0]), dip=float(m[1]), rake=float(m[2])).m(), dtype=float)


def _tensors_table(s_deg: np.ndarray, d_deg: np.ndarray, r_deg: np.ndarray) -> np.ndarray:
    """(M, 3, 3) moment tensors of unit double couples from Aki & Richards' table (north, east, down)."""
    f, dl, lm = np.radians(s_deg), np.radians(d_deg), np.radians(r_deg)
    sd, cd, s2d, c2d = np.sin(dl), np.cos(dl), np.sin(2 * dl), np.cos(2 * dl)
    sr, cr, sf, cf, s2f, c2f = np.sin(lm), np.cos(lm), np.sin(f), np.cos(f), np.sin(2 * f), np.cos(2 * f)
    out = np.empty(f.shape + (3, 3))
    out[..., 0, 0] = -(sd * cr * s2f + s2d * sr * sf ** 2)
    out[..., 1, 1] = sd * cr * s2f - s2d * sr * cf ** 2
    out[..., 2, 2] = s2d * sr
    out[..., 0, 1] = out[..., 1, 0] = sd * cr * c2f + 0.5 * s2d * sr * s2f
    out[..., 0, 2] = out[..., 2, 0] = -(cd * cr * cf + c2d * sr * sf)
    out[..., 1, 2] = out[..., 2, 1] = -(cd * cr * sf - c2d * sr * cf)
    return out


def _radiated(tensors: np.ndarray, rays: np.ndarray) -> np.ndarray:
    """Ray-projected moment tensor, (M, N): its sign is the polarity of P along each ray."""
    return np.einsum("ni,mij,nj->mn", rays, tensors, rays)


class _Spy:
    """The check's own misfit function (T1's contract) that records every mechanism it is asked about."""

    def __init__(self) -> None:
        self.asked: List[np.ndarray] = []
        self.values: List[np.ndarray] = []

    def __call__(self, strike: Any, dip: Any, rake: Any, azimuth: Any, takeoff: Any, polarity: Any,
                 weight: Any) -> Tuple[Any, np.ndarray]:
        scalar_input = np.ndim(strike) == 0
        s, d, r = (np.atleast_1d(np.asarray(x, dtype=float)).ravel() for x in (strike, dip, rake))
        rays = _unit_rays(np.asarray(azimuth, dtype=float), np.asarray(takeoff, dtype=float))
        signs = np.sign(_radiated(_tensors_table(s, d, r), rays)).astype(int)
        w = np.asarray(weight, dtype=float)
        miss = (signs != np.asarray(polarity, dtype=float)[None, :]).astype(float) @ w / float(w.sum())
        self.asked.append(np.column_stack([s, d, r]))
        self.values.append(miss)
        return (float(miss[0]), signs[0]) if scalar_input else (miss, signs)


def _contract_grid(step: float) -> np.ndarray:
    """The grid of the T2 contract, in its order (strike outermost, rake innermost)."""
    n_s, n_d, n_r = int(round(360.0 / step)), int(round(90.0 / step)), int(round(360.0 / step))
    rows = [(i * step, (j + 1) * step, -180.0 + (k + 1) * step)
            for i in range(n_s) for j in range(n_d) for k in range(n_r)]
    return np.asarray(rows, dtype=float)


def _keys(rows: np.ndarray) -> List[Tuple[float, float, float]]:
    return [tuple(round(float(v), 6) for v in row) for row in np.asarray(rows, dtype=float).reshape(-1, 3)]


def _made_up_mech(rng: np.random.Generator, min_dip: float = 10.0) -> Tuple[float, float, float]:
    return (float(rng.uniform(0.0, 360.0)), float(rng.uniform(min_dip, 89.0)), float(rng.uniform(-179.0, 179.0)))


def _made_up_rays(rng: np.random.Generator, m: Sequence[float], n: int, lo: float, hi: float,
                  clear: float = 0.05) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """n rays (azimuth, inc) at least ``clear`` (relative amplitude) away from the nodal planes, and their signs."""
    tensor = _tensor_pyrocko(m)
    az, inc, sg = [], [], []
    while len(az) < n:
        a, t = float(rng.uniform(0.0, 360.0)), float(rng.uniform(lo, hi))
        value = float(_radiated(tensor[None], _unit_rays(np.array([a]), np.array([t])))[0, 0])
        if abs(value) >= clear:
            az.append(a)
            inc.append(t)
            sg.append(1 if value > 0 else -1)
    return np.array(az), np.array(inc), np.array(sg, dtype=int)


def _logged(log: Path, slug: str) -> List[dict]:
    out = []
    try:
        text = log.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("cluster") == slug and rec.get("returncode") == 0:
            out.append(rec)
    return out


def _mechanism_writes(ctx: Any, slug: str) -> Dict[str, int]:
    """fingerprint -> number of successful logged runs of the cluster that wrote it as its mechanism file."""
    writes: Dict[str, int] = {}
    for rec in _logged(Path(ctx.repo) / "work" / ".sgtl" / "runs.jsonl", slug):
        if rec.get("command") != "pq run":
            continue
        for key, sha in (rec.get("products") or {}).items():
            if str(key).startswith("3.FocalMech/") and str(key).endswith(FM_KEY):
                writes[str(sha)] = writes.get(str(sha), 0) + 1
    return writes


# ------------------------------------------------------------------------------------------- M51-T1
T1_PRIORITY = ("format", "changed-input", "shape", "sign", "takeoff-convention", "azimuth-convention", "unweighted",
               "count", "wrong-values")


def _t1_cases(rng: np.random.Generator, crit: dict) -> List[dict]:
    cases = []
    for k in range(int(crit.get("trials", 16))):
        many = k % 3 == 2
        mechs = [_made_up_mech(rng, 5.0) for _ in range(int(rng.integers(3, 7)) if many else 1)]
        n = int(rng.integers(16, 41))
        while True:                                               # at least 12 rays clear of every nodal plane
            az, inc, _ = _made_up_rays(rng, mechs[0], n, 0.0, 180.0, clear=0.0)
            rays = _unit_rays(az, inc)
            amps = np.stack([_radiated(_tensor_pyrocko(m)[None], rays)[0] for m in mechs])
            size = np.abs(amps).max(axis=1, keepdims=True)
            keep = (np.abs(amps) >= 0.05 * size).all(axis=0)
            if keep.sum() >= 12:
                break
        az, inc, amps = az[keep], inc[keep], amps[:, keep]
        signs = np.sign(amps).astype(int)
        pol = signs[0].copy()
        flip = rng.random(pol.size) < rng.uniform(0.0, 0.3)
        pol[flip] *= -1
        w = np.ones(pol.size) if k % 4 == 0 else rng.uniform(0.1, 1.0, pol.size)
        cases.append({"mechs": mechs, "many": many, "az": az, "inc": inc, "pol": pol, "w": w, "signs": signs})
    return cases


def _t1_alt(case: dict, az: np.ndarray, inc: np.ndarray) -> np.ndarray:
    rays = _unit_rays(az, inc)
    return np.sign(np.stack([_radiated(_tensor_pyrocko(m)[None], rays)[0] for m in case["mechs"]])).astype(int)


def _t1_judge(case: dict, got: Any, err: Optional[BaseException], crit: dict) -> Optional[str]:
    if err is not None or not isinstance(got, tuple) or len(got) != 2:
        return "format"
    n, m = case["pol"].size, len(case["mechs"])
    try:
        pred = np.asarray(got[1], dtype=float)
        miss = np.asarray(got[0], dtype=float)
    except (TypeError, ValueError):
        return "format"
    if case["many"]:
        if pred.shape != (m, n) or miss.shape != (m,):
            return "shape"
    else:
        if pred.shape != (n,) or miss.ndim != 0:
            return "shape"
        pred, miss = pred[None, :], miss.reshape(1)
    if not np.all(np.isfinite(pred)) or not np.all(np.isfinite(miss)):
        return "format"
    signs = case["signs"]
    w, pol = case["w"], case["pol"]
    tol = float(crit.get("misfit_tol", 1e-9))
    if not np.array_equal(pred, signs):
        if np.array_equal(pred, -signs):
            return "sign"
        for inc in (180.0 - case["inc"], 90.0 - case["inc"]):
            if np.array_equal(pred, _t1_alt(case, case["az"], inc)):
                return "takeoff-convention"
        for az in (90.0 - case["az"], case["az"] + 180.0, -case["az"]):
            if np.array_equal(pred, _t1_alt(case, az, case["inc"])):
                return "azimuth-convention"
        return "wrong-values"
    wrong = (signs != pol[None, :]).astype(float)
    expected = wrong @ w / w.sum()
    if np.allclose(miss, expected, rtol=0.0, atol=tol):
        return None
    if np.allclose(miss, wrong.mean(axis=1), rtol=0.0, atol=tol):
        return "unweighted"
    if np.allclose(miss, wrong @ w, rtol=0.0, atol=tol) or np.allclose(miss, 100.0 * expected, atol=tol):
        return "count"
    return "wrong-values"


def check_T1(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    oks, cats, example = [], [], None
    for case in _t1_cases(ctx.rng, crit):
        args = [np.array(v) for v in zip(*case["mechs"])] if case["many"] else list(case["mechs"][0])
        copies = [case["az"].copy(), case["inc"].copy(), case["pol"].copy(), case["w"].copy()]
        got, err = _call(target, *args, *copies)
        cat = _t1_judge(case, got, err, crit)
        if cat is None and not all(np.array_equal(a, b) for a, b in
                                   zip(copies, (case["az"], case["inc"], case["pol"], case["w"]))):
            cat = "changed-input"
        oks.append(cat is None)
        if cat:
            cats.append(cat)
            if example is None:
                shown = case["mechs"][0]
                example = {"inputs": {"mechanisms": len(case["mechs"]), "first (strike, dip, rake)":
                                      tuple(round(v, 1) for v in shown), "stations": int(case["pol"].size),
                                      "first ray (azimuth, takeoff)": (round(float(case["az"][0]), 1),
                                                                       round(float(case["inc"][0]), 1))},
                           "got": (type(err).__name__ if err is not None else
                                   (f"misfit {got[0]!r}" if isinstance(got, tuple) and got else repr(got))[:120]),
                           "error": "see the category"}
    category = _first(cats, T1_PRIORITY)
    return outcome_from_cases(np.array(oks), category=category, example=example)


# ------------------------------------------------------------------------------------------- M51-T2
T2_PRIORITY = ("format", "grid", "not-best", "ties", "tolerance", "accepted-misfit", "order", "far-from-truth")


def _t2_cases(rng: np.random.Generator, crit: dict) -> List[dict]:
    cases = []
    steps = [float(s) for s in crit.get("steps", [10.0, 15.0, 18.0, 30.0])]
    tols = [float(t) for t in crit.get("tols", [0.0, 0.05, 0.1])]
    for k in range(int(crit.get("trials", 12))):
        truth = _made_up_mech(rng, 10.0)
        n = int(rng.integers(30, 61))
        az, inc, pol = _made_up_rays(rng, truth, n, 20.0, 160.0, clear=0.02)
        n_flip = int(round(rng.uniform(0.0, 0.1) * n))
        pol[rng.choice(n, n_flip, replace=False)] *= -1
        w = rng.uniform(0.3, 1.0, n) if k % 3 else np.ones(n)
        cases.append({"truth": truth, "az": az, "inc": inc, "pol": pol, "w": w,
                      "step": steps[k % len(steps)] if k < len(steps) else 10.0, "tol": tols[k % len(tols)]})
    return cases


def _t2_parts(got: Any) -> Optional[Tuple[Tuple[float, float, float], float, np.ndarray, np.ndarray]]:
    if not isinstance(got, tuple) or len(got) != 4:
        return None
    try:
        best = tuple(float(v) for v in got[0])
        acc = np.asarray(got[2], dtype=float)
        acc_m = np.asarray(got[3], dtype=float)
    except (TypeError, ValueError):
        return None
    if len(best) != 3 or not _real(got[1]) or acc.ndim != 2 or acc.shape[1:] != (3,) or acc_m.shape != acc.shape[:1]:
        return None
    if not (np.all(np.isfinite(acc)) and np.all(np.isfinite(acc_m)) and all(math.isfinite(v) for v in best)):
        return None
    return best, float(got[1]), acc, acc_m


def _t2_judge(case: dict, spy: _Spy, got: Any, err: Optional[BaseException], crit: dict) -> Optional[str]:
    parts = None if err is not None else _t2_parts(got)
    if parts is None:
        return "format"
    best, best_m, acc, acc_m = parts
    if not spy.asked:
        return "grid"
    asked = np.vstack(spy.asked)
    values = np.concatenate(spy.values)
    grid = _contract_grid(case["step"])
    seen: Dict[Tuple[float, float, float], float] = {}
    for key, value in zip(_keys(asked), values):
        seen.setdefault(key, float(value))
    grid_keys = _keys(grid)
    if set(grid_keys) != set(seen):
        return "grid"
    tol = float(crit.get("misfit_tol", 1e-9))
    ordered = np.array([seen[k] for k in grid_keys])
    low = float(ordered.min())
    best_key = _keys(np.array([best]))[0]
    if best_key not in seen or abs(seen[best_key] - low) > tol or abs(best_m - low) > tol:
        return "not-best"
    if best_key != grid_keys[int(np.argmin(ordered))]:
        return "ties"
    edge = low + case["tol"]
    must = {grid_keys[i] for i in np.flatnonzero((ordered <= edge - tol) | (ordered <= low))}   # inside, ties
    may = {grid_keys[i] for i in np.flatnonzero(ordered <= edge + tol)}       # inside, or on its edge
    acc_keys = _keys(acc)
    if not (must <= set(acc_keys) <= may) or len(set(acc_keys)) != len(acc_keys):
        return "tolerance"
    if not np.allclose(acc_m, [seen[k] for k in acc_keys], rtol=0.0, atol=tol):
        return "accepted-misfit"
    rank = {k: i for i, k in enumerate(grid_keys)}
    if acc_keys != sorted(acc_keys, key=lambda k: (seen[k], rank[k])):
        return "order"
    return None


def check_T2(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    oks, cats, example, angles = [], [], None, []
    for case in _t2_cases(ctx.rng, crit):
        spy = _Spy()
        copies = [case["az"].copy(), case["inc"].copy(), case["pol"].copy(), case["w"].copy()]
        got, err = _call(target, *copies, case["step"], case["tol"], spy)
        cat = _t2_judge(case, spy, got, err, crit)
        if cat is None and not all(np.array_equal(a, b) for a, b in
                                   zip(copies, (case["az"], case["inc"], case["pol"], case["w"]))):
            cat = "format"
        if cat is None:
            angles.append(_kagan_oracle(_t2_parts(got)[0], case["truth"]))
        oks.append(cat is None)
        if cat:
            cats.append(cat)
            if example is None:
                example = {"inputs": {"stations": int(case["pol"].size), "step_deg": case["step"],
                                      "tol": case["tol"], "mechanisms your function asked the misfit about":
                                      int(sum(len(a) for a in spy.asked))},
                           "got": (type(err).__name__ if err is not None else
                                   (f"best {tuple(round(float(v), 3) for v in got[0])}"
                                    if isinstance(got, tuple) and got and isinstance(got[0], (tuple, list, np.ndarray))
                                    else repr(got)[:100])),
                           "error": "see the category"}
    category = _first(cats, T2_PRIORITY)
    if category is not None:
        return outcome_from_cases(np.array(oks), category=category, example=example)
    median = float(np.median(angles))
    limit = float(crit.get("kagan_median_max_deg", 20.0))
    note = (f"Median Kagan angle between your best mechanisms and the made-up truths: {median:.1f} deg "
            f"(at most {limit:g} deg passes).")
    if median > limit:
        return outcome_from_cases(np.array(oks + [False]), category="far-from-truth", note=note)
    return outcome_from_cases(np.array(oks + [True]), note=note)


# ------------------------------------------------------------------------------------------- M51-T3
T3_PRIORITY = ("format", "radians", "no-symmetry", "nodal-plane", "asymmetric", "wrong-values")


def _t3_pairs(rng: np.random.Generator, crit: dict) -> List[Tuple[Tuple[float, ...], Tuple[float, ...], str]]:
    mt = _pmt()
    pairs = []
    for k in range(int(crit.get("trials", 30))):
        a = _made_up_mech(rng, 1.0)
        kind = ("random", "other-plane", "near", "same")[k % 4] if k < 24 else "random"
        if kind == "random":
            b = _made_up_mech(rng, 1.0)
        elif kind == "other-plane":
            planes = mt.MomentTensor(strike=a[0], dip=a[1], rake=a[2]).both_strike_dip_rake()
            b = max(planes, key=lambda p: abs(p[0] - a[0]) + abs(p[1] - a[1]) + abs(p[2] - a[2]))
        elif kind == "near":
            b = (a[0] + float(rng.uniform(-6, 6)), min(89.9, a[1] + float(rng.uniform(-4, 4))),
                 a[2] + float(rng.uniform(-6, 6)))
        else:
            b = a
        pairs.append((tuple(float(v) for v in a), tuple(float(v) for v in b), kind))
    return pairs


def check_T3(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    tol = float(crit.get("tol_deg", 1e-3))
    oks, cats, example = [], [], None
    for a, b, kind in _t3_pairs(ctx.rng, crit):
        want = _kagan_oracle(a, b)
        got, err = _call(target, a, b)
        cat = None
        if err is not None or not _real(got):
            cat = "format"
        else:
            value = float(got)
            if abs(value - want) > tol:
                if want > 1.0 and abs(value - math.radians(want)) <= 1e-4:
                    cat = "radians"
                elif value > 120.0 + tol:
                    cat = "no-symmetry"
                elif kind == "other-plane":
                    cat = "nodal-plane"
                else:
                    cat = "wrong-values"
            else:
                back, err2 = _call(target, b, a)
                if err2 is not None or not _real(back) or abs(float(back) - want) > tol:
                    cat = "asymmetric"
        oks.append(cat is None)
        if cat:
            cats.append(cat)
            if example is None:
                example = {"inputs": {"mech1": tuple(round(v, 2) for v in a), "mech2": tuple(round(v, 2) for v in b)},
                           "got": (type(err).__name__ if err is not None else repr(got)[:60]),
                           "error": (f"{abs(float(got) - want):.3g} deg" if err is None and _real(got)
                                     else "not a number")}
    return outcome_from_cases(np.array(oks), category=_first(cats, T3_PRIORITY), example=example)


# ------------------------------------------------------------------------------------------- M51-T4
T4_PRIORITY = ("format", "changed-input", "center", "ties", "chain", "counts", "share", "order", "wrong-values")
T4_COLUMNS = ["strike", "dip", "rake", "misfit", "n", "share"]


def _rotate(m: Sequence[float], axis: np.ndarray, angle_deg: float) -> Tuple[float, float, float]:
    """The mechanism m turned by angle_deg about axis (north-east-down), as strike, dip, rake (Pyrocko)."""
    mt = _pmt()
    u = np.asarray(axis, dtype=float) / np.linalg.norm(axis)
    t = math.radians(angle_deg)
    k = np.array([[0.0, -u[2], u[1]], [u[2], 0.0, -u[0]], [-u[1], u[0], 0.0]])
    rot = np.eye(3) + math.sin(t) * k + (1.0 - math.cos(t)) * (k @ k)
    tensor = rot @ _tensor_pyrocko(m) @ rot.T
    plane = mt.MomentTensor(m=mt.symmat6(tensor[0, 0], tensor[1, 1], tensor[2, 2], tensor[0, 1], tensor[0, 2],
                                         tensor[1, 2])).both_strike_dip_rake()[0]
    return tuple(float(v) for v in plane)


def _t4_case(rng: np.random.Generator, k: int) -> dict:
    """Separated groups (or the chain) with misfits; the families follow from the construction.

    Groups: members are turned at most 0.45 max_angle from their group's first mechanism, and the first mechanisms
    of two groups are at least 2.4 max_angle apart, so every member lies within max_angle of any member of its own
    group and farther than max_angle from every member of another group. A family's center is its group's member
    of lowest misfit (the first in the input among equals). Chain: 0, 0.7 and 1.4 max_angle about one axis.
    """
    chain, tie = k % 4 == 3, k % 4 == 1
    groups: List[List[Tuple[float, float, float]]] = []
    levels: List[List[float]] = []
    if chain:
        angle = float(rng.choice([20.0, 30.0, 40.0]))
        while True:
            core = _made_up_mech(rng, 20.0)
            axis = rng.normal(size=3)
            two, three = _rotate(core, axis, 0.7 * angle), _rotate(core, axis, 1.4 * angle)
            if abs(_kagan_oracle(core, two) - 0.7 * angle) < 0.01 and \
                    abs(_kagan_oracle(core, three) - 1.4 * angle) < 0.01:
                break
        groups, levels = [[core, two], [three]], [[0.05, 0.08], [0.11]]
    else:
        angle = float(rng.choice([15.0, 20.0, 25.0, 30.0]))
        n_groups = int(rng.integers(2, 4))
        cores: List[Tuple[float, float, float]] = []
        while len(cores) < n_groups:
            cand = _made_up_mech(rng, 15.0)
            if all(_kagan_oracle(cand, c) >= 2.4 * angle for c in cores):
                cores.append(cand)
        base = sorted(float(v) for v in rng.uniform(0.0, 0.2, n_groups))
        for g, core in enumerate(cores):
            size = int(rng.integers(3 if tie else 2, 7))
            members = [core]
            while len(members) < size:
                cand = _rotate(core, rng.normal(size=3), float(rng.uniform(0.1, 0.45)) * angle)
                if _kagan_oracle(core, cand) <= 0.45 * angle + 1e-6:
                    members.append(cand)
            lv = [base[g]] + [base[g] + float(v) for v in rng.uniform(0.01, 0.3, size - 1)]
            if tie and g == 0:
                lv[2] = base[g]                      # a tie with the group's first mechanism
            groups.append(members)
            levels.append(lv)
    flat = [(m, lv, g) for g, (ms, ls) in enumerate(zip(groups, levels)) for m, lv in zip(ms, ls)]
    order = rng.permutation(len(flat))
    mechs = np.array([flat[i][0] for i in order])
    miss = np.array([flat[i][1] for i in order])
    group_of = np.array([flat[i][2] for i in order])
    families = []
    for g in range(len(groups)):
        idx = np.flatnonzero(group_of == g)
        low = miss[idx].min()
        center = int(idx[np.flatnonzero(miss[idx] == low)[0]])
        families.append({"center": center, "members": [int(i) for i in idx]})
    families.sort(key=lambda f: (miss[f["center"]], f["center"]))
    return {"mechs": mechs, "misfit": miss, "angle": angle, "families": families, "chain": chain, "tie": tie}


def _t4_judge(case: dict, got: Any, err: Optional[BaseException]) -> Optional[str]:
    if err is not None or not _frame(got) or list(got.columns)[:6] != T4_COLUMNS:
        return "format"
    try:
        table = got[T4_COLUMNS].to_numpy(dtype=float)
    except (TypeError, ValueError):
        return "format"
    if not np.all(np.isfinite(table)):
        return "format"
    fams = case["families"]
    mechs, miss = case["mechs"], case["misfit"]
    total = len(mechs)
    want_centers = [_keys(mechs[f["center"]][None])[0] for f in fams]
    got_centers = _keys(table[:, :3])
    if sorted(got_centers) != sorted(want_centers):
        if case["chain"] and len(table) == 1:
            return "chain"
        lows = {_keys(mechs[i][None])[0] for i in range(total) if miss[i] <= miss.min() + 1e-12}
        if case["tie"] and any(c in lows for c in got_centers):
            return "ties"
        return "center"
    if got_centers != want_centers:
        return "order"
    sizes = [len(f["members"]) for f in fams]
    if not np.allclose(table[:, 4], sizes):
        return "counts"
    if not np.allclose(table[:, 5], np.array(sizes) / total, rtol=0.0, atol=1e-9):
        return "share"
    if not np.allclose(table[:, 3], [miss[f["center"]] for f in fams], rtol=0.0, atol=1e-9):
        return "wrong-values"
    return None


def check_T4(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    rng = ctx.rng
    oks, cats, example = [], [], None
    for k in range(int(crit.get("trials", 12))):
        case = _t4_case(rng, k)
        mechs, miss = case["mechs"].copy(), case["misfit"].copy()
        got, err = _call(target, mechs, miss, _kagan_oracle, case["angle"])
        cat = _t4_judge(case, got, err)
        if cat is None and not (np.array_equal(mechs, case["mechs"]) and np.array_equal(miss, case["misfit"])):
            cat = "changed-input"
        oks.append(cat is None)
        if cat:
            cats.append(cat)
            if example is None:
                example = {"inputs": {"mechanisms": len(case["mechs"]), "max_angle": case["angle"],
                                      "kind": "chain" if case["chain"] else ("tie" if case["tie"] else "groups")},
                           "got": (type(err).__name__ if err is not None else
                                   (f"{len(got)} families" if _frame(got) else repr(got)[:80])),
                           "error": f"expected {len(case['families'])} families"}
    return outcome_from_cases(np.array(oks), category=_first(cats, T4_PRIORITY), example=example)


# ------------------------------------------------------------------------------------------- M51-T5
T5_KEYS = {"skhash_polarities", "polarity_misfit", "grid_search", "kagan", "slug", "folder", "mechanisms_sha256",
           "step_deg", "tol", "min_weight", "best", "kagan_skhash", "kagan_kigam"}
T5_FUNC_PRIORITY = ("format", "changed-input", "weight-gate", "station-name", "order", "takeoff-convention",
                    "polarity-weight", "wrong-values")
T5_OUT = ["event_id", "station", "azimuth", "takeoff", "polarity", "weight"]


def _t5_table(rng: np.random.Generator, k: int) -> Tuple[Any, Any, float]:
    """A made-up SKHASH polarity table and the expected reading of it."""
    import pandas as pd

    min_w = float(rng.choice([0.2, 0.3, 0.4]))
    rows, want = [], []
    for e in rng.choice(np.arange(700000, 700050), size=int(rng.integers(1, 4)), replace=False):
        for j in range(int(rng.integers(4, 12))):
            net, sta = ("XX", "YY")[j % 2], f"Q{rng.integers(10, 99)}{chr(65 + j)}"
            inc = float(rng.uniform(5.0, 175.0))
            az = float(rng.uniform(0.0, 360.0))
            p = float(rng.choice([-1, 1]) * rng.choice([rng.uniform(0.05, min_w - 0.01), min_w,
                                                         rng.uniform(min_w + 0.01, 1.0)]))
            rows.append({"event_id": int(e), "sta_code": f"{net}.{sta}.--.HHZ", "p_polarity": round(p, 3),
                         "sr_dist_km": float(rng.uniform(5, 100)), "takeoff": round(180.0 - inc, 1),
                         "azimuth": round(az, 1), "source": "trad_p", "sp_ratio": np.nan})
            if abs(round(p, 3)) >= min_w:
                want.append({"event_id": int(e), "station": f"{net}.{sta}", "azimuth": round(az, 1),
                             "takeoff": 180.0 - round(180.0 - inc, 1), "polarity": 1 if p > 0 else -1,
                             "weight": abs(round(p, 3))})
            if rng.random() < 0.5:                  # SKHASH's S/P rows carry no polarity
                rows.append({"event_id": int(e), "sta_code": f"{net}.{sta}.--.HHZ", "p_polarity": np.nan,
                             "sr_dist_km": float(rng.uniform(5, 100)), "takeoff": round(180.0 - inc, 1),
                             "azimuth": round(az, 1), "source": "trad_sp", "sp_ratio": float(rng.uniform(0.5, 3))})
    table = pd.DataFrame(rows).sample(frac=1.0, random_state=int(rng.integers(1 << 30)))
    table.index = rng.permutation(len(table)) + 50
    expected = pd.DataFrame(want, columns=T5_OUT).sort_values(["event_id", "station"], ignore_index=True)
    return table, expected, min_w


def _t5_judge_table(table: Any, expected: Any, min_w: float, got: Any, err: Optional[BaseException]) -> Optional[str]:
    if err is not None or not _frame(got) or not set(T5_OUT) <= set(got.columns):
        return "format"
    if len(got) != len(expected):
        return "weight-gate"
    g = got[T5_OUT].reset_index(drop=True)
    key_got = list(zip(g["event_id"].astype(int), g["station"].astype(str)))
    key_want = list(zip(expected["event_id"], expected["station"]))
    if sorted(key_got) != sorted(key_want):
        if any("--" in s or s.count(".") != 1 for _, s in key_got):
            return "station-name"
        return "weight-gate"
    if key_got != key_want:
        return "order"
    try:
        inc = g["takeoff"].to_numpy(dtype=float)
        az = g["azimuth"].to_numpy(dtype=float)
        pol = g["polarity"].to_numpy(dtype=float)
        w = g["weight"].to_numpy(dtype=float)
    except (TypeError, ValueError):
        return "format"
    if not np.allclose(az, expected["azimuth"], atol=1e-9):
        return "wrong-values"
    if not np.allclose(inc, expected["takeoff"], atol=1e-9):
        return "takeoff-convention"
    if not (np.array_equal(pol, expected["polarity"].to_numpy(float)) and np.allclose(w, expected["weight"])):
        return "polarity-weight"
    return None


def _t5_functions_still(target: dict, rng: np.random.Generator) -> bool:
    """A short re-test of the reported misfit, Kagan and grid-search functions on made-up cases."""
    for _ in range(3):
        m = _made_up_mech(rng, 10.0)
        az, inc, sg = _made_up_rays(rng, m, 20, 10.0, 170.0)
        got, err = _call(target["polarity_misfit"], m[0], m[1], m[2], az, inc, sg, np.ones(sg.size))
        if err is not None or not isinstance(got, tuple) or len(got) != 2:
            return False
        try:
            if not np.array_equal(np.asarray(got[1], dtype=float), sg) or abs(float(got[0])) > 1e-9:
                return False
        except (TypeError, ValueError):
            return False
        a, b = _made_up_mech(rng, 1.0), _made_up_mech(rng, 1.0)
        got, err = _call(target["kagan"], a, b)
        if err is not None or not _real(got) or abs(float(got) - _kagan_oracle(a, b)) > 1e-3:
            return False
    spy = _Spy()
    m = _made_up_mech(rng, 10.0)
    az, inc, sg = _made_up_rays(rng, m, 40, 20.0, 160.0)
    got, err = _call(target["grid_search"], az, inc, sg, np.ones(sg.size), 30.0, 0.05, spy)
    return err is None and _t2_judge({"step": 30.0, "tol": 0.05}, spy, got, None, {}) is None


def _t5_artifacts(target: dict, ctx: Any, crit: dict) -> Tuple[int, Optional[str]]:
    import pandas as pd

    passed = 0
    folder = Path(str(target["folder"])).expanduser()
    files = {name: folder / name for name in ("mechanisms.csv", "control_file.txt", "OUT/out_polinfo.csv")}
    if not all(p.is_file() for p in files.values()):
        return passed, "copies"
    sha = str(target["mechanisms_sha256"]).lower()
    if not HEX64.fullmatch(sha) or _sha256(files["mechanisms.csv"]) != sha:
        return passed, "fingerprint-claim"
    passed += 1
    if not isinstance(target["slug"], str):
        return passed, "runs-missing"
    writes = _mechanism_writes(ctx, target["slug"])
    if not writes:
        return passed, "runs-missing"
    if sha not in writes:
        return passed, "not-run-product"
    passed += 1
    control = files["control_file.txt"].read_text(encoding="utf-8", errors="replace")
    found = re.search(r"\$min_polarity_weight\s*\n\s*(\S+)", control)
    step, tol, min_w = target["step_deg"], target["tol"], target["min_weight"]
    if not (found and _real(min_w) and abs(float(found.group(1)) - float(min_w)) < 1e-9):
        return passed, "settings"
    if not (_real(step) and 1.0 <= float(step) <= float(crit.get("max_step_deg", 10.0))
            and abs(90.0 / float(step) - round(90.0 / float(step))) < 1e-9 and _real(tol) and 0.0 <= float(tol) <= 0.3):
        return passed, "settings"
    passed += 1
    mech = pd.read_csv(files["mechanisms.csv"], dtype={"event_id": str})
    polinfo = pd.read_csv(files["OUT/out_polinfo.csv"])
    got, err = _call(target["skhash_polarities"], polinfo.copy(), float(min_w))
    if err is not None or not _frame(got):
        return passed, "not-reproduced"
    best, kag = target["best"], target["kagan_skhash"]
    if not (isinstance(best, dict) and isinstance(kag, dict)):
        return passed, "format"
    best = {str(k): v for k, v in best.items()}
    kag = {str(k): v for k, v in kag.items()}
    names = dict(zip(mech["cuspid"].astype(int), mech["event_id"].astype(str)))
    used = sorted(int(e) for e in set(got["event_id"]) if int(e) in names)
    if not used or set(best) != {names[e] for e in used} or set(kag) != set(best):
        return passed, "events"
    for e in used:
        rows = got[got["event_id"].astype(int) == e]
        arrays = [rows[c].to_numpy(dtype=float) for c in ("azimuth", "takeoff", "polarity", "weight")]
        result, err = _call(target["grid_search"], *arrays, float(step), float(tol), target["polarity_misfit"])
        parts = None if err is not None else _t2_parts(result)
        try:
            mine = tuple(float(v) for v in best[names[e]])
        except (TypeError, ValueError):
            return passed, "format"
        if parts is None or len(mine) != 3:
            return passed, "not-reproduced"
        at_mine, err = _call(target["polarity_misfit"], mine[0], mine[1], mine[2], *arrays)
        if err is not None or not isinstance(at_mine, tuple) or not _real(at_mine[0]) or \
                abs(float(at_mine[0]) - parts[1]) > 1e-9:
            return passed, "not-reproduced"
    passed += 1
    mainshock = mech.loc[mech["magnitude"].astype(float).idxmax(), "event_id"] if "magnitude" in mech else None
    for e in used:
        row = mech[mech["event_id"].astype(str) == names[e]].iloc[0]
        want = _kagan_oracle(best[names[e]], (row["strike"], row["dip"], row["rake"]))
        if not _real(kag[names[e]]) or abs(float(kag[names[e]]) - want) > 0.05:
            return passed, "kagan-values"
    if mainshock not in best or not _real(target["kagan_kigam"]) or \
            abs(float(target["kagan_kigam"]) - _kagan_oracle(best[mainshock], KIGAM)) > 0.05:
        return passed, "kagan-values"
    passed += 1
    limit = float(crit.get("skhash_agree_deg", 30.0))
    min_pol = int(crit.get("skhash_agree_min_pol", 50))
    for e in used:
        row = mech[mech["event_id"].astype(str) == names[e]].iloc[0]
        if str(row["quality"]) == "A" and int(row["num_p_pol"]) >= min_pol and \
                _kagan_oracle(best[names[e]], (row["strike"], row["dip"], row["rake"])) > limit:
            return passed, "far-from-skhash"
    passed += 1
    return passed, None


def check_T5(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    funcs = ("skhash_polarities", "polarity_misfit", "grid_search", "kagan")
    if not isinstance(target, dict) or set(target) != T5_KEYS or not all(callable(target.get(f)) for f in funcs):
        return Outcome(passed=False, n_cases=1, n_failed=1, category="format", message="", details={})
    rng = ctx.rng
    oks, cats, example = [], [], None
    for k in range(int(crit.get("trials", 8))):
        table, expected, min_w = _t5_table(rng, k)
        before = table.copy()
        got, err = _call(target["skhash_polarities"], table, min_w)
        cat = _t5_judge_table(table, expected, min_w, got, err)
        if cat is None and not table.equals(before):
            cat = "changed-input"
        oks.append(cat is None)
        if cat:
            cats.append(cat)
            if example is None:
                example = {"inputs": {"rows": len(table), "polarity rows": int((table["source"] == "trad_p").sum()),
                                      "min_weight": min_w},
                           "got": (type(err).__name__ if err is not None else
                                   (f"{len(got)} rows" if _frame(got) else repr(got)[:80])),
                           "error": f"expected {len(expected)} rows"}
    category = _first(cats, T5_FUNC_PRIORITY)
    if category is not None:
        return outcome_from_cases(np.array(oks), category=category, example=example)
    if not _t5_functions_still(target, rng):
        return outcome_from_cases(np.array(oks + [False]), category="functions")
    oks.append(True)
    passed, cat = _t5_artifacts(target, ctx, crit)
    steps = 6
    ok = np.array(oks + [True] * passed + [False] * (steps - passed if cat else 0), dtype=bool)
    note = ("The check recomputed the SHA-256 of your copied mechanism file, looked it up in work/.sgtl/runs.jsonl, "
            "reran your own functions on your own SKHASH polarity table and recomputed your Kagan angles with an "
            "independent library; it never prints a mechanism or an angle of the real data.")
    return outcome_from_cases(ok, category=cat, real_data=True, note=note)


# ------------------------------------------------------------------------------------------- M51-T6
T6_KEYS = {"sp_table", "slug", "first", "rerun", "polarities_only", "mechanisms_sha256", "kagan_without_sp"}
T6_FUNC_PRIORITY = ("format", "changed-input", "rows", "sp-sign", "first-pick", "order", "wrong-values")
T6_OUT = ["event_id", "network", "station", "sp_ratio", "sp_time_s"]


def _t6_tables(rng: np.random.Generator) -> Tuple[Any, Any, Any]:
    import pandas as pd

    t0 = pd.Timestamp("2001-02-03T04:05:00", tz="UTC") + pd.Timedelta(seconds=float(rng.uniform(0, 3000)))
    amp, picks, want = [], [], []
    for e in range(int(rng.integers(1, 4))):
        ev = int(800000 + 7 * e + rng.integers(0, 5))
        for j in range(int(rng.integers(3, 9))):
            net, sta = ("XX", "YY")[j % 2], f"R{j}{chr(70 + e)}"
            ratio = round(float(rng.uniform(0.3, 6.0)), 5)
            amp.append({"event_id": ev, "network": net, "station": sta, "location": "--", "channel": "HHZ",
                        "sp_ratio": ratio})
            tp = t0 + pd.Timedelta(seconds=float(rng.uniform(1, 20)))
            sp = float(rng.uniform(0.8, 14.0))
            have = rng.random()
            if have > 0.15:
                picks.append({"event_id": ev, "network": net, "station": sta, "phase": "P", "time": tp})
                if rng.random() < 0.3:      # a later, second P pick at the same station
                    picks.append({"event_id": ev, "network": net, "station": sta, "phase": "P",
                                  "time": tp + pd.Timedelta(seconds=float(rng.uniform(0.5, 4)))})
                picks.append({"event_id": ev, "network": net, "station": sta, "phase": "S",
                              "time": tp + pd.Timedelta(seconds=sp)})
            want.append({"event_id": ev, "network": net, "station": sta, "sp_ratio": ratio,
                         "sp_time_s": sp if have > 0.15 else np.nan})
    amp_df = pd.DataFrame(amp).sample(frac=1.0, random_state=int(rng.integers(1 << 30)))
    picks_df = pd.DataFrame(picks).sample(frac=1.0, random_state=int(rng.integers(1 << 30)))
    picks_df.index = rng.permutation(len(picks_df)) + 10
    expected = pd.DataFrame(want, columns=T6_OUT).sort_values(["event_id", "network", "station"], ignore_index=True)
    return amp_df, picks_df, expected


def _t6_judge_table(expected: Any, got: Any, err: Optional[BaseException]) -> Optional[str]:
    if err is not None or not _frame(got) or not set(T6_OUT) <= set(got.columns):
        return "format"
    if len(got) != len(expected):
        return "rows"
    g = got[T6_OUT].reset_index(drop=True)
    keys_got = list(zip(g["event_id"].astype(int), g["network"].astype(str), g["station"].astype(str)))
    keys_want = list(zip(expected["event_id"], expected["network"], expected["station"]))
    if sorted(keys_got) != sorted(keys_want):
        return "rows"
    if keys_got != keys_want:
        return "order"
    try:
        sp = g["sp_time_s"].to_numpy(dtype=float)
        ratio = g["sp_ratio"].to_numpy(dtype=float)
    except (TypeError, ValueError):
        return "format"
    if not np.allclose(ratio, expected["sp_ratio"].to_numpy(float), rtol=0, atol=0):
        return "wrong-values"
    want = expected["sp_time_s"].to_numpy(float)
    if not np.array_equal(np.isnan(sp), np.isnan(want)):
        return "rows"
    have = ~np.isnan(want)
    if np.allclose(sp[have], -want[have], atol=1e-6) and have.any():
        return "sp-sign"
    if not np.allclose(sp[have], want[have], atol=1e-6):
        return "first-pick"
    return None


def _t6_artifacts(target: dict, ctx: Any) -> Tuple[int, Optional[str]]:
    import pandas as pd

    passed = 0
    names = ("first", "rerun", "polarities_only")
    folders = {}
    for name in names:
        if not isinstance(target[name], (str, os.PathLike)):
            return passed, "format"
        folders[name] = Path(target[name]).expanduser()
    shas = target["mechanisms_sha256"]
    if not isinstance(shas, dict) or set(shas) != set(names):
        return passed, "format"
    need = ("mechanisms.csv", "control_file.txt", "IN/pol.csv", "IN/eq_catalog.csv", "IN/stations.csv")
    if not all((folders[n] / f).is_file() for n in names for f in need) or \
            not (folders["first"] / "IN/amp.csv").is_file():
        return passed, "copies"
    passed += 1
    actual = {n: _sha256(folders[n] / "mechanisms.csv") for n in names}
    if any(str(shas[n]).lower() != actual[n] for n in names):
        return passed, "fingerprint-claim"
    passed += 1
    writes = _mechanism_writes(ctx, str(target["slug"])) if isinstance(target["slug"], str) else {}
    if not writes:
        return passed, "runs-missing"
    if any(actual[n] not in writes for n in names):
        return passed, "not-run-product"
    if len({folders[n].resolve() for n in names}) < 3:
        return passed, "no-rerun"
    if actual["first"] == actual["rerun"] and writes[actual["first"]] < 2:
        return passed, "no-rerun"
    passed += 1
    ctl = {n: (folders[n] / "control_file.txt").read_text(encoding="utf-8", errors="replace") for n in names}
    if "$ampfile" not in ctl["first"] or "$ampfile" not in ctl["rerun"] or "$ampfile" in ctl["polarities_only"]:
        return passed, "one-change"
    for f in ("IN/pol.csv", "IN/eq_catalog.csv", "IN/stations.csv"):
        if len({_sha256(folders[n] / f) for n in names}) != 1:
            return passed, "one-change"
    other = pd.read_csv(folders["polarities_only"] / "mechanisms.csv")
    if "num_sp_ratios" not in other or (other["num_sp_ratios"].fillna(0).astype(float) != 0).any():
        return passed, "one-change"
    passed += 1
    kag = target["kagan_without_sp"]
    if not isinstance(kag, dict):
        return passed, "format"
    kag = {str(k): v for k, v in kag.items()}
    mech = {n: pd.read_csv(folders[n] / "mechanisms.csv", dtype={"event_id": str}).drop_duplicates("event_id")
            for n in ("first", "polarities_only")}
    if not all({"event_id", "strike", "dip", "rake"} <= set(m.columns) for m in mech.values()):
        return passed, "copies"
    rows = {n: m.set_index("event_id") for n, m in mech.items()}
    both = [e for e in rows["first"].index if e in rows["polarities_only"].index]
    if not both or set(kag) != set(both):
        return passed, "events"
    for e in both:
        a, b = (tuple(float(v) for v in rows[n].loc[e, ["strike", "dip", "rake"]])
                for n in ("first", "polarities_only"))
        if not _real(kag[e]) or abs(float(kag[e]) - _kagan_oracle(a, b)) > 0.05:
            return passed, "kagan-values"
    passed += 1
    return passed, None


def check_T6(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    if not isinstance(target, dict) or set(target) != T6_KEYS or not callable(target.get("sp_table")):
        return Outcome(passed=False, n_cases=1, n_failed=1, category="format", message="", details={})
    rng = ctx.rng
    oks, cats, example = [], [], None
    for _ in range(int(crit.get("trials", 8))):
        amp, picks, expected = _t6_tables(rng)
        a0, p0 = amp.copy(), picks.copy()
        got, err = _call(target["sp_table"], amp, picks)
        cat = _t6_judge_table(expected, got, err)
        if cat is None and not (amp.equals(a0) and picks.equals(p0)):
            cat = "changed-input"
        oks.append(cat is None)
        if cat:
            cats.append(cat)
            if example is None:
                example = {"inputs": {"S/P rows": len(amp), "picks": len(picks)},
                           "got": (type(err).__name__ if err is not None else
                                   (f"{len(got)} rows" if _frame(got) else repr(got)[:80])),
                           "error": f"expected {len(expected)} rows"}
    category = _first(cats, T6_FUNC_PRIORITY)
    if category is not None:
        return outcome_from_cases(np.array(oks), category=category, example=example)
    passed, cat = _t6_artifacts(target, ctx)
    steps = 5
    ok = np.array(oks + [True] * passed + [False] * (steps - passed if cat else 0), dtype=bool)
    note = ("The check recomputed the SHA-256 of your three copied mechanism files, looked them up in "
            "work/.sgtl/runs.jsonl, compared the control files and inputs of the three runs and recomputed your "
            "Kagan angles between the first and the polarities-only run with an independent library; it never "
            "prints an angle or a mechanism of the real data.")
    return outcome_from_cases(ok, category=cat, real_data=True, note=note)
