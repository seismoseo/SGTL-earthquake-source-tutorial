"""Checkers for M53 · Moment-tensor inversion.

Where the truth comes from (DESIGN.md section 1, rule 1):

* M53-T1: construction and an independent library. Made-up kernels and tensors; the reference answer of each case
  comes from numpy.linalg.lstsq and numpy.linalg.pinv on the weighted rows (for the trace-free cases inside the
  null space of the trace, from scipy.linalg.null_space). Then many noise draws of one made-up network: the errors
  must scatter as the returned covariance says (mean chi-square, correlations).
* M53-T2: construction. Residuals of known size per row (every sample of a row has the same |residual|), so each
  norm's term is known without summing.
* M53-T3: construction and an independent library. Pulses moved by known whole samples (inside and outside the
  bound, a pulse that a wrap-around would bring back, symmetric ties), and random traces whose L2 answer comes from
  scipy.signal.correlate. The budget handed to the student's function is the check's own.
* M53-T4: construction and an independent library. Eigenvalues from chosen lune coordinates, eigenvectors from a
  double couple of pyrocko; its planes from pyrocko's both_strike_dip_rake.
* M53-T5: construction, then the student's own products. Made-up stations with chosen deviations from a chosen
  level; then the student's files: decisions recomputed with the student's function, planes with the student's
  tensor_summary and Kagan angles with the student's kagan_angle (both verified again first against pyrocko).
* M53-T6: construction, then the student's own products. Numbers placed on chosen sides of the rules' edges; then
  the student's MTUQ files: fingerprints, the norm of each run, the rerun, each best grid point, the trace budget,
  the spread and the Kagan angles recomputed with the student's functions, and the verdict with the student's
  function and the rules of criteria/M53.yaml.

No check prints a value of the Sangju data. Failure categories are keys of checks/specs/M53.yaml.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import math
import numbers
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import Outcome, outcome_from_cases

__all__ = ["check_T1", "check_T2", "check_T3", "check_T4", "check_T5", "check_T6"]

KIGAM_A = (288.0, 89.0, 7.0)                 # KIGAM (2021), KEMS-2019-062: plane A (strike, dip, rake)
EVENT_FOLDER = "20190721020418"              # the Sangju mainshock's UTC folder name
RUN_LABELS = ("first", "again", "changed")


# ------------------------------------------------------------------------------------------- helpers
def _call(func: Any, *args: Any, **kwargs: Any) -> Tuple[Any, Optional[BaseException]]:
    """Run the student's code. NotImplementedError passes through (the engine reports NOT STARTED)."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return func(*args, **kwargs), None
    except NotImplementedError:
        raise
    except Exception as exc:  # noqa: BLE001 - classified by the caller
        return None, exc


def _real(value: Any) -> bool:
    return isinstance(value, numbers.Real) and not isinstance(value, (bool, np.bool_)) and math.isfinite(value)


def _first(cats: Sequence[Optional[str]], priority: Sequence[str]) -> Optional[str]:
    present = {c for c in cats if c}
    return next((c for c in priority if c in present), None)


def _array(value: Any, shape: Tuple[int, ...]) -> Optional[np.ndarray]:
    try:
        arr = np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        return None
    return arr if arr.shape == shape else None


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _ang(a: float, b: float) -> float:
    return abs(((a - b + 180.0) % 360.0) - 180.0)


def _same_plane(a: Sequence[float], b: Sequence[float], tol: float) -> bool:
    return _ang(a[0], b[0]) <= tol and abs(a[1] - b[1]) <= tol and _ang(a[2], b[2]) <= tol


def _pyrocko_kagan(m1: Sequence[float], m2: Sequence[float]) -> float:
    from pyrocko import moment_tensor as pmt
    a = pmt.MomentTensor(strike=m1[0], dip=m1[1], rake=m1[2])
    b = pmt.MomentTensor(strike=m2[0], dip=m2[1], rake=m2[2])
    return float(pmt.kagan_angle(a, b))


def _kagan_ok(kagan: Any, rng: np.random.Generator, n: int = 6) -> bool:
    """The student's kagan_angle against pyrocko's on random double couples."""
    if not callable(kagan):
        return False
    for _ in range(n):
        m1 = (rng.uniform(0, 360), rng.uniform(5, 85), rng.uniform(-175, 175))
        m2 = (rng.uniform(0, 360), rng.uniform(5, 85), rng.uniform(-175, 175))
        got, err = _call(kagan, m1, m2)
        if err is not None or not _real(got) or abs(float(got) - _pyrocko_kagan(m1, m2)) > 0.05:
            return False
    return True


# =========================================================================================== M53-T1
T1_PRIORITY = ("format", "changed-input", "nan-gaps", "weights", "deviatoric", "covariance", "wrong-values",
               "statistics")


def _oracle_lsq(G: np.ndarray, d: np.ndarray, sigma: np.ndarray, deviatoric: bool,
                weight_power: float = 2.0) -> Tuple[np.ndarray, np.ndarray]:
    from scipy.linalg import null_space
    use = np.isfinite(d)
    w = 1.0 / sigma[use] ** (weight_power / 2.0)
    basis = null_space(np.array([[1.0, 1.0, 1.0, 0.0, 0.0, 0.0]])) if deviatoric else np.eye(6)
    rows = (G[use] @ basis) * w[:, None]
    p = np.linalg.lstsq(rows, d[use] * w, rcond=None)[0]
    cov = basis @ np.linalg.pinv(rows.T @ rows) @ basis.T
    return basis @ p, cov


def _t1_kernels(rng: np.random.Generator, n: int, blind: bool) -> np.ndarray:
    G = rng.normal(size=(n, 6)) * 10.0 ** rng.uniform(-17.0, -15.0)
    if blind:
        iso = np.array([1.0, 1.0, 1.0, 0.0, 0.0, 0.0]) / math.sqrt(3.0)
        G = G - np.outer(G @ iso, iso)
    return G


def _t1_cases(rng: np.random.Generator, n: int) -> List[dict]:
    cases = []
    for k in range(n):
        rows = int(rng.integers(30, 240))
        blind = k % 5 == 4
        dev = blind or k % 3 == 1
        G = _t1_kernels(rng, rows, blind)
        m = rng.normal(size=6) * 10.0 ** rng.uniform(12.0, 16.0)
        clean = G @ m
        scale = float(np.std(clean))
        if k % 2:
            sigma = scale * rng.uniform(0.02, 0.2, rows)
        else:
            sigma = np.full(rows, scale * rng.uniform(0.02, 0.2))
        d = clean + rng.normal(size=rows) * sigma
        if k % 4 in (1, 2):
            gaps = rng.choice(rows, size=max(1, rows // 6), replace=False)
            d[gaps] = np.nan
        cases.append({"G": G, "d": d, "sigma": sigma if k % 2 else float(sigma[0]), "sigma_arr": sigma,
                      "dev": dev, "blind": blind})
    return cases


def _t1_unpack(got: Any) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    if not isinstance(got, tuple) or len(got) != 2:
        return None
    m, cov = _array(got[0], (6,)), _array(got[1], (6, 6))
    if m is None or cov is None:
        return None
    return m, cov


def _t1_judge(got: Any, case: dict, rel: float) -> Optional[str]:
    pair = _t1_unpack(got)
    if pair is None:
        return "format"
    m, cov = pair
    want_m, want_cov = _oracle_lsq(case["G"], case["d"], case["sigma_arr"], case["dev"])
    tol_m = rel * float(np.max(np.abs(want_m)))
    tol_c = rel * float(np.max(np.abs(want_cov)))
    if not np.all(np.isfinite(m)):
        return "nan-gaps" if np.isnan(case["d"]).any() else "format"
    m_ok = np.allclose(m, want_m, rtol=0.0, atol=tol_m)
    if m_ok:
        if np.all(np.isfinite(cov)) and np.allclose(cov, want_cov, rtol=0.0, atol=tol_c):
            return None
        return "covariance"
    if np.isnan(case["d"]).any():
        filled = np.nan_to_num(case["d"])
        for dev in {case["dev"], False}:
            try:
                alt, _ = _oracle_lsq(case["G"], filled, case["sigma_arr"], dev)
            except Exception:  # noqa: BLE001
                continue
            if np.allclose(m, alt, rtol=0.0, atol=10 * tol_m):
                return "nan-gaps"
    for power in (0.0, 1.0, 4.0):
        try:
            alt, _ = _oracle_lsq(case["G"], case["d"], case["sigma_arr"], case["dev"], weight_power=power)
        except Exception:  # noqa: BLE001
            continue
        if np.allclose(m, alt, rtol=0.0, atol=10 * tol_m) and not np.allclose(alt, want_m, rtol=0.0, atol=tol_m):
            return "weights"
    if case["dev"]:
        if abs(float(np.sum(m[:3]))) > tol_m:
            return "deviatoric"
        if not case["blind"]:
            free, _ = _oracle_lsq(case["G"], case["d"], case["sigma_arr"], False)
            free[:3] -= free[:3].sum() / 3.0
            if np.allclose(m, free, rtol=0.0, atol=10 * tol_m):
                return "deviatoric"
    return "wrong-values"


def _t1_statistics(target: Any, rng: np.random.Generator, crit: dict) -> Optional[str]:
    """Many noise draws of one made-up network: chi-square and correlations of the errors."""
    rows = 240
    G = _t1_kernels(rng, rows, False)
    m_true = rng.normal(size=6) * 1e14
    clean = G @ m_true
    sigma = float(np.std(clean)) * rng.uniform(0.05, 0.2, rows)
    errs, chi = [], []
    want_cov = np.linalg.pinv((G / sigma[:, None]).T @ (G / sigma[:, None]))
    inv_cov = np.linalg.pinv(want_cov)
    for _ in range(int(crit.get("draws", 300))):
        got, err = _call(target, G, clean + rng.normal(size=rows) * sigma, sigma)
        pair = None if err is not None else _t1_unpack(got)
        if pair is None:
            return "format"
        e = pair[0] - m_true
        errs.append(e)
        chi.append(float(e @ inv_cov @ e))
    errs = np.array(errs)
    if abs(float(np.mean(chi)) - 6.0) > float(crit.get("chi2_tol", 1.0)):
        return "statistics"
    emp = np.corrcoef(errs.T)
    sd = np.sqrt(np.diag(want_cov))
    model = want_cov / np.outer(sd, sd)
    if np.max(np.abs(emp - model)) > float(crit.get("corr_tol", 0.2)):
        return "statistics"
    return None


def check_T1(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    rel = float(crit.get("rel_tol", 1e-6))
    oks: List[bool] = []
    cats: List[Optional[str]] = []
    example = None
    for case in _t1_cases(ctx.rng, int(crit.get("trials", 30))):
        keep = (case["G"].copy(), case["d"].copy(), np.array(case["sigma"], dtype=float).copy())
        got, err = _call(target, case["G"], case["d"], case["sigma"], deviatoric=case["dev"])
        cat = "format" if err is not None else _t1_judge(got, case, rel)
        if cat is None and not (np.array_equal(keep[0], case["G"]) and np.array_equal(keep[1], case["d"], equal_nan=True)
                                and np.array_equal(keep[2], np.array(case["sigma"], dtype=float))):
            cat = "changed-input"
        oks.append(cat is None)
        cats.append(cat)
        if cat and example is None:
            example = {"inputs": {"rows": int(case["G"].shape[0]), "gaps": int(np.isnan(case["d"]).sum()),
                                  "sigma": "array" if np.ndim(case["sigma"]) else "number",
                                  "deviatoric": case["dev"], "kernels_blind_to_volume": case["blind"]},
                       "got": f"{type(err).__name__}: {err}" if err is not None else "see the category",
                       "error": "compared with numpy's lstsq on the weighted rows"}
    if all(oks):
        cat = _t1_statistics(target, ctx.rng, crit)
        oks.append(cat is None)
        cats.append(cat)
    return outcome_from_cases(oks, category=_first(cats, T1_PRIORITY), example=example)


# =========================================================================================== M53-T2
T2_PRIORITY = ("format", "norm-name", "changed-input", "dt", "l2", "l1", "hybrid", "shares", "n_eff",
               "wrong-values")


def _t2_case(rng: np.random.Generator) -> dict:
    n_tr = int(rng.integers(1, 9))
    n_s = int(rng.integers(20, 300))
    dt = float(rng.choice([0.01, 0.05, 0.1, 0.2, 0.5, 1.0]))
    size = rng.uniform(0.1, 3.0, n_tr) * 10.0 ** rng.uniform(-8, 0)
    syn = rng.normal(size=(n_tr, n_s)) * size[:, None] * 3.0         # same order as the residuals: no cancellation
    signs = rng.choice([-1.0, 1.0], size=(n_tr, n_s))
    return {"syn": syn, "obs": syn + size[:, None] * signs, "dt": dt, "size": size, "n": n_s}


def _t2_truth(case: dict, norm: str) -> np.ndarray:
    size, n, dt = case["size"], case["n"], case["dt"]
    if norm == "L2":
        return dt * n * size ** 2
    if norm == "L1":
        return dt * n * size
    return dt * math.sqrt(n) * size


def _t2_judge(got: Any, case: dict, norm: str, rel: float) -> Optional[str]:
    if not isinstance(got, dict) or not {"per_trace", "total", "share", "n_eff"} <= set(got):
        return "format"
    n_tr = case["syn"].shape[0]
    terms, shares = _array(got["per_trace"], (n_tr,)), _array(got["share"], (n_tr,))
    if terms is None or shares is None or not _real(got["total"]) or not _real(got["n_eff"]):
        return "format"
    want = _t2_truth(case, norm)
    if not np.allclose(terms, want, rtol=rel, atol=0.0):
        size, n, dt = case["size"], case["n"], case["dt"]
        for alt in ((want / dt), (want * dt)):
            if np.allclose(terms, alt, rtol=rel, atol=0.0):
                return "dt"
        if norm == "hybrid" and np.allclose(terms, np.sqrt(dt * n) * size, rtol=rel, atol=0.0):
            return "dt"
        if norm == "hybrid" and np.allclose(terms, dt * n * size ** 2, rtol=rel, atol=0.0):
            return "hybrid"
        return {"L2": "l2", "L1": "l1", "hybrid": "hybrid"}[norm]
    total = float(np.sum(want))
    if abs(float(got["total"]) - total) > rel * total:
        return "wrong-values"
    if not np.allclose(shares, want / total, rtol=rel, atol=1e-12):
        return "shares"
    if abs(float(got["n_eff"]) - 1.0 / float(np.sum((want / total) ** 2))) > rel * n_tr:
        return "n_eff"
    return None


def check_T2(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    rel = float(crit.get("rel_tol", 1e-9))
    oks: List[bool] = []
    cats: List[Optional[str]] = []
    example = None
    for k in range(int(crit.get("trials", 40))):
        case = _t2_case(ctx.rng)
        norm = ("L2", "L1", "hybrid")[k % 3]
        keep = (case["obs"].copy(), case["syn"].copy())
        got, err = _call(target, case["obs"], case["syn"], case["dt"], norm)
        cat = "format" if err is not None else _t2_judge(got, case, norm, rel)
        if cat is None and not (np.array_equal(keep[0], case["obs"]) and np.array_equal(keep[1], case["syn"])):
            cat = "changed-input"
        oks.append(cat is None)
        cats.append(cat)
        if cat and example is None:
            example = {"inputs": {"traces": case["syn"].shape[0], "samples": case["n"], "dt_s": case["dt"],
                                  "norm": norm, "|residual| per trace": np.round(case["size"], 12).tolist()},
                       "got": (f"{type(err).__name__}: {err}" if err is not None else
                               np.round(np.asarray(got.get("per_trace", []), dtype=float), 12).tolist()
                               if isinstance(got, dict) else repr(got)[:120]),
                       "error": f"expected per_trace {np.round(_t2_truth(case, norm), 12).tolist()}"}
    case = _t2_case(ctx.rng)
    _, bad = _call(target, case["obs"], case["syn"], case["dt"], "L3")
    oks.append(isinstance(bad, ValueError))
    cats.append(None if isinstance(bad, ValueError) else "norm-name")
    return outcome_from_cases(oks, category=_first(cats, T2_PRIORITY), example=example)


# =========================================================================================== M53-T3
T3_PRIORITY = ("format", "changed-input", "norm", "budget", "wrap-around", "sign", "bound", "ties",
               "wrong-values")


class _Budget:
    """The check's own budget: the three norms of Part 2, and a record of the norms it was asked for."""

    def __init__(self) -> None:
        self.norms: List[Any] = []

    def __call__(self, obs: Any, syn: Any, dt_s: float, norm: str = "L2") -> Dict[str, Any]:
        self.norms.append(norm)
        gap = np.atleast_2d(np.subtract(obs, syn, dtype=float))
        lengths = {"L2": (2, 2), "L1": (1, 1), "hybrid": (2, 1)}
        if norm not in lengths:
            raise ValueError("norm")
        order, power = lengths[norm]
        terms = np.linalg.norm(gap, ord=order, axis=-1) ** power * dt_s
        terms = np.atleast_1d(terms)
        total = float(np.sum(terms))
        share = terms / total if total > 0 else np.zeros_like(terms)
        return {"per_trace": terms, "total": total, "share": share,
                "n_eff": float(1.0 / np.sum(share ** 2)) if total > 0 else float("nan")}


def _pulse(n: int, center: float, width: float) -> np.ndarray:
    t = np.arange(n, dtype=float)
    return np.exp(-0.5 * ((t - center) / width) ** 2)


def _later(x: np.ndarray, k: int) -> np.ndarray:
    out = np.zeros_like(x)
    if k >= 0:
        out[k:] = x[:x.size - k]
    else:
        out[:x.size + k] = x[-k:]
    return out


def _t3_cases(rng: np.random.Generator, n_random: int) -> List[dict]:
    cases = []
    norms = ("L2", "L1", "hybrid")
    for j in range(9):                                    # exact copies inside the bound
        n, dt = int(rng.integers(120, 300)), float(rng.choice([0.01, 0.05, 0.1]))
        reach = int(rng.integers(4, 20))
        k0 = int(rng.integers(-reach, reach + 1))
        syn = _pulse(n, n / 2 + rng.uniform(-10, 10), rng.uniform(2, 6)) * rng.uniform(0.5, 3)
        cases.append({"obs": _later(syn, k0), "syn": syn, "dt": dt, "max": reach * dt + 0.3 * dt,
                      "norm": norms[j % 3], "want": k0 * dt, "kind": "inside"})
    for j in range(6):                                    # beyond the bound: the edge
        n, dt = 300, 0.1
        reach = int(rng.integers(3, 10))
        sign = 1 if j % 2 else -1
        k0 = sign * (reach + int(rng.integers(3, 15)))
        syn = _pulse(n, 150 + rng.uniform(-5, 5), rng.uniform(3, 6))
        cases.append({"obs": _later(syn, k0), "syn": syn, "dt": dt, "max": reach * dt, "norm": norms[j % 3],
                      "want": sign * reach * dt, "kind": "outside"})
    for j in range(3):                                    # a pulse at the end that a wrap-around brings back
        n, dt, reach = 200, 0.1, 12
        obs = _pulse(n, 4.0, 1.5)
        syn = _pulse(n, n - 6.0, 1.5)
        cases.append({"obs": obs, "syn": syn, "dt": dt, "max": reach * dt, "norm": norms[j % 3],
                      "want": reach * dt, "kind": "wrap"})
    tri = np.array([1.0, 2.0, 3.0, 2.0, 1.0])
    for j in range(3):                                    # ties: two equal triangles (exact sums), an empty synthetic
        n, dt, k0 = 240, 0.05, int(rng.integers(5, 15))
        obs, syn = np.zeros(n), np.zeros(n)
        obs[118:123] = tri
        syn[118 - k0:123 - k0] += tri
        syn[118 + k0:123 + k0] += tri
        cases.append({"obs": obs, "syn": syn, "dt": dt, "max": (k0 + 5) * dt, "norm": norms[j % 3],
                      "want": -k0 * dt, "kind": "tie"})
    cases.append({"obs": _pulse(100, 50.0, 3.0), "syn": np.zeros(100), "dt": 0.1, "max": 1.0, "norm": "L2",
                  "want": 0.0, "kind": "tie"})
    for j in range(n_random):                             # random traces, L2: SciPy's correlation as the reference
        n, dt = int(rng.integers(60, 200)), 0.02
        obs, syn = rng.normal(size=n), rng.normal(size=n)
        reach = int(rng.integers(3, 25))
        cases.append({"obs": obs, "syn": syn, "dt": dt, "max": reach * dt + 0.4 * dt, "norm": "L2",
                      "want": None, "kind": "random"})
    return cases


def _t3_reference(case: dict) -> float:
    from scipy.signal import correlate
    obs, syn, dt = case["obs"], case["syn"], case["dt"]
    n = obs.size
    reach = int(np.floor(case["max"] / dt + 1e-9))
    cross = correlate(obs, syn, mode="full")
    cum = np.concatenate([[0.0], np.cumsum(syn ** 2)])
    best = None
    for k in range(-reach, reach + 1):
        inside = cum[n - k] if k >= 0 else cum[n] - cum[-k]
        value = float(np.sum(obs ** 2) + inside - 2.0 * cross[n - 1 + k])
        if best is None or value < best[1] - 1e-12:
            best = (k, value)
    return best[0] * dt


def _t3_judge(got: Any, case: dict, spy: _Budget, tol: float) -> Optional[str]:
    if not isinstance(got, tuple) or len(got) != 2 or not _real(got[0]) or not _real(got[1]):
        return "format"
    shift, value = float(got[0]), float(got[1])
    if not spy.norms:
        return "budget"
    if any(n != case["norm"] for n in spy.norms):
        return "norm"
    k = int(round(shift / case["dt"]))
    if abs(k * case["dt"] - shift) > 1e-9 or abs(shift) > case["max"] + 1e-9:
        return "bound"

    def total(moved: np.ndarray) -> float:
        return _Budget()(case["obs"][None, :], moved[None, :], case["dt"], case["norm"])["total"]

    def near(a: float, b: float) -> bool:
        return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))

    if not near(total(_later(case["syn"], k)), value):
        if near(total(np.roll(case["syn"], k)), value):
            return "wrap-around"
        if near(total(_later(case["syn"], -k)), value):
            return "sign"
        return "budget"
    want = case["want"] if case["want"] is not None else _t3_reference(case)
    if abs(shift - want) <= tol * case["dt"]:
        return None
    reach = int(np.floor(case["max"] / case["dt"] + 1e-9))
    if abs(abs(want) - reach * case["dt"]) <= 1e-9 and abs(abs(shift) - (reach - 1) * case["dt"]) <= 1e-9:
        return "bound"
    if case["kind"] == "tie":
        return "ties"
    if abs(shift + want) <= tol * case["dt"] and want != 0:
        return "sign"
    if case["kind"] == "outside":
        return "bound"
    return "wrong-values"


def check_T3(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    tol = float(crit.get("shift_tol_samples", 0.01))
    oks: List[bool] = []
    cats: List[Optional[str]] = []
    example = None
    for case in _t3_cases(ctx.rng, int(crit.get("random_trials", 12))):
        spy = _Budget()
        keep = (case["obs"].copy(), case["syn"].copy())
        got, err = _call(target, case["obs"], case["syn"], case["dt"], case["max"], spy, norm=case["norm"])
        cat = "format" if err is not None else _t3_judge(got, case, spy, tol)
        if cat is None and not (np.array_equal(keep[0], case["obs"]) and np.array_equal(keep[1], case["syn"])):
            cat = "changed-input"
        oks.append(cat is None)
        cats.append(cat)
        if cat and example is None and case["kind"] != "random":
            example = {"inputs": {"kind": case["kind"], "samples": int(case["obs"].size), "dt_s": case["dt"],
                                  "max_shift_s": round(case["max"], 4), "norm": case["norm"]},
                       "got": f"{type(err).__name__}: {err}" if err is not None else repr(got)[:120],
                       "error": f"expected shift_s {case['want']:.4g}"}
    return outcome_from_cases(oks, category=_first(cats, T3_PRIORITY), example=example)


# =========================================================================================== M53-T4
T4_PRIORITY = ("format", "changed-input", "eigenvalues", "eigen-order", "m0", "lune", "ranges", "frame", "planes")


def _t4_case(rng: np.random.Generator, k: int) -> dict:
    from pyrocko import moment_tensor as pmt
    kinds = ("dc", "clvd", "free")
    kind = kinds[k % 3]
    gamma = 0.0 if kind == "dc" else (rng.choice([-1.0, 1.0]) * rng.uniform(5, 29) if kind == "clvd"
                                      else rng.uniform(-29, 29))
    delta = 0.0 if kind != "free" else rng.uniform(-70, 70)
    rho = 10.0 ** rng.uniform(10, 19)
    g, d = math.radians(gamma), math.radians(delta)
    e_iso = np.ones(3) / math.sqrt(3.0)
    e_dc = np.array([1.0, 0.0, -1.0]) / math.sqrt(2.0)
    e_clvd = np.array([-1.0, 2.0, -1.0]) / math.sqrt(6.0)
    lam = rho * (math.sin(d) * e_iso + math.cos(d) * (math.cos(g) * e_dc + math.sin(g) * e_clvd))
    strike, dip, rake = rng.uniform(0, 360), rng.uniform(12, 85), rng.uniform(-175, 175)
    dc = pmt.MomentTensor(strike=strike, dip=dip, rake=rake)
    vals, vecs = np.linalg.eigh(np.asarray(dc.m_up_south_east(), dtype=float))
    vecs = vecs[:, np.argsort(vals)[::-1]]
    tensor = vecs @ np.diag(lam) @ vecs.T
    m6 = np.array([tensor[0, 0], tensor[1, 1], tensor[2, 2], tensor[0, 1], tensor[0, 2], tensor[1, 2]])
    return {"m6": m6, "lam": lam, "rho": rho, "gamma": gamma, "delta": delta,
            "planes": [tuple(float(v) for v in p) for p in dc.both_strike_dip_rake()], "vecs": vecs}


def _t4_judge(got: Any, case: dict, rel: float, tol_deg: float) -> Optional[str]:
    if not isinstance(got, dict) or not {"eigenvalues", "m0_nm", "gamma_deg", "delta_deg", "planes"} <= set(got):
        return "format"
    eig = _array(got["eigenvalues"], (3,))
    planes = got["planes"]
    if eig is None or not _real(got["m0_nm"]) or not _real(got["gamma_deg"]) or not _real(got["delta_deg"]):
        return "format"
    try:
        planes = [tuple(float(v) for v in p) for p in planes]
    except (TypeError, ValueError):
        return "format"
    if len(planes) != 2 or any(len(p) != 3 or not all(math.isfinite(v) for v in p) for p in planes):
        return "format"
    scale = case["rho"]
    if not np.allclose(eig, case["lam"], rtol=0.0, atol=rel * scale):
        same = np.allclose(np.sort(eig), np.sort(case["lam"]), rtol=0.0, atol=rel * scale)
        return "eigen-order" if same else "eigenvalues"
    if abs(float(got["m0_nm"]) - case["rho"] / math.sqrt(2.0)) > rel * scale:
        return "m0"
    if abs(float(got["gamma_deg"]) - case["gamma"]) > tol_deg or abs(float(got["delta_deg"]) - case["delta"]) > tol_deg:
        return "lune"
    for s, d, r in planes:
        if not (0.0 <= s < 360.0 + 1e-9 and -1e-9 <= d <= 90.0 + 1e-9 and -180.0 < r <= 180.0 + 1e-9):
            return "ranges"
    if all(any(_same_plane(p, q, tol_deg) for q in planes) for p in case["planes"]):
        return None
    return "frame" if _planes_as_ned(case, planes, tol_deg) else "planes"


def _planes_as_ned(case: dict, planes: List[Tuple[float, float, float]], tol: float) -> bool:
    """True when the planes are those of the up-south-east eigenvectors read as north-east-down."""
    from pyrocko import moment_tensor as pmt
    vecs = case["vecs"]
    dc = vecs @ np.diag([1.0, 0.0, -1.0]) @ vecs.T
    try:
        wrong = pmt.MomentTensor(m=dc).both_strike_dip_rake()
    except Exception:  # noqa: BLE001
        return False
    return all(any(_same_plane(p, q, tol) for q in planes) for p in wrong)


def check_T4(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    rel = float(crit.get("rel_tol", 1e-6))
    tol_deg = float(crit.get("abs_tol_deg", 0.01))
    oks: List[bool] = []
    cats: List[Optional[str]] = []
    example = None
    for k in range(int(crit.get("trials", 60))):
        case = _t4_case(ctx.rng, k)
        keep = case["m6"].copy()
        got, err = _call(target, case["m6"])
        cat = "format" if err is not None else _t4_judge(got, case, rel, tol_deg)
        if cat is None and not np.array_equal(keep, case["m6"]):
            cat = "changed-input"
        oks.append(cat is None)
        cats.append(cat)
        if cat and example is None:
            example = {"inputs": {"m6 (N m)": np.round(case["m6"], 6).tolist()},
                       "got": (f"{type(err).__name__}: {err}" if err is not None else
                               {key: (np.round(np.asarray(v, dtype=float), 4).tolist() if key != "planes" else v)
                                for key, v in got.items()} if isinstance(got, dict) else repr(got)[:160]),
                       "error": (f"expected gamma {case['gamma']:.4f}, delta {case['delta']:.4f}, m0 "
                                 f"{case['rho'] / math.sqrt(2.0):.6g}, planes "
                                 f"{[tuple(round(v, 3) for v in p) for p in case['planes']]}")}
    return outcome_from_cases(oks, category=_first(cats, T4_PRIORITY), example=example)


def _summary_ok(summary: Any, rng: np.random.Generator, n: int = 8) -> bool:
    """The student's tensor_summary again, on made-up tensors (planes only)."""
    if not callable(summary):
        return False
    for k in range(n):
        case = _t4_case(rng, k)
        got, err = _call(summary, case["m6"])
        if err is not None or _t4_judge(got, case, 1e-6, 0.01) is not None:
            return False
    return True


# =========================================================================================== M53-T5
T5_PRIORITY = ("format", "changed-input", "unusable", "log", "distance", "mean", "keep", "wrong-values")
T5_REAL = ("no-report", "report", "amplitudes", "summary-func", "kagan-func", "lsq-file", "lsq-depth",
           "lsq-planes", "kagan", "n-eff", "stale")


def _t5_case(rng: np.random.Generator, k: int) -> dict:
    n = int(rng.integers(5, 14)) | 1                      # an odd number of usable stations: the median is one
    level = rng.uniform(-6.0, -2.0)
    dev = rng.normal(0.0, 0.2, n)
    dev -= np.median(dev)
    outliers = rng.choice(n, size=1 + k % 2, replace=False)
    dev[outliers] = rng.choice([-1.0, 1.0], size=outliers.size) * rng.uniform(0.7, 1.6, outliers.size)
    dev -= np.median(dev)
    dist = rng.uniform(8.0, 150.0, n)
    peak = 10.0 ** (level - np.median(dev) + dev) / dist
    want_dev = np.log10(peak * dist) - np.median(np.log10(peak * dist))
    bad = []
    if k % 3 == 2:                                       # unusable entries: NaN, zero, negative
        for value in (np.nan, 0.0, -1e-6)[: 1 + k % 3]:
            peak = np.append(peak, value)
            dist = np.append(dist, rng.uniform(8.0, 150.0))
            want_dev = np.append(want_dev, np.nan)
            bad.append(peak.size - 1)
    max_dev = float(rng.uniform(0.4, 0.8))
    keep = np.isfinite(want_dev) & (np.abs(np.nan_to_num(want_dev, nan=np.inf)) <= max_dev)
    usable = np.isfinite(want_dev)
    return {"peak": peak, "dist": dist, "max": max_dev, "dev": want_dev, "keep": keep,
            "level": float(np.median(np.log10(peak[usable] * dist[usable]))), "bad": bad}


def _t5_judge(got: Any, case: dict, tol: float) -> Optional[str]:
    n = case["peak"].size
    if not isinstance(got, dict) or not {"deviation", "keep", "level"} <= set(got):
        return "format"
    dev = _array(got["deviation"], (n,))
    try:
        keep = np.asarray(got["keep"], dtype=bool)
    except (TypeError, ValueError):
        return "format"
    if dev is None or keep.shape != (n,) or not _real(got["level"]):
        return "format"
    usable = np.isfinite(case["dev"])
    if not np.all(np.isnan(dev[~usable])) or np.any(keep[~usable]) or not np.all(np.isfinite(dev[usable])):
        return "unusable"
    if np.allclose(dev[usable], case["dev"][usable], atol=tol) and abs(float(got["level"]) - case["level"]) <= tol:
        return None if np.array_equal(keep, case["keep"]) else "keep"
    logs = np.log10(case["peak"][usable] * case["dist"][usable])
    if np.allclose(dev[usable], case["dev"][usable] * np.log(10.0), atol=1e-6):
        return "log"
    if np.allclose(dev[usable], logs - np.mean(logs), atol=tol):
        return "mean"
    for alt in (np.log10(case["peak"][usable]), np.log10(case["peak"][usable] / case["dist"][usable]),
                np.log10(case["peak"][usable] * case["dist"][usable] ** 2)):
        if np.allclose(dev[usable], alt - np.median(alt), atol=tol):
            return "distance"
    return "wrong-values"


def _t5_real(target: Any, ctx: Any, crit: dict) -> Optional[str]:
    """None when the student's Sangju files agree with the report; else a category. Prints nothing of the data."""
    import pandas as pd
    report = ctx.get("report")
    if report is None:
        return "no-report"
    keys = {"rejected", "max_dev", "amplitudes_sha256", "lsq_sha256", "lsq_depth_km", "lsq_planes",
            "kagan_lsq_kigam", "n_eff_lsq"}
    if not isinstance(report, dict) or not keys <= set(report):
        return "report"
    paths = [ctx.get(name) for name in ("amplitudes", "lsq", "lsq_traces")]
    if any(p is None or not Path(p).is_file() for p in paths):
        return "report"
    amp_path, lsq_path, tr_path = (Path(p) for p in paths)
    if _sha(amp_path) != str(report["amplitudes_sha256"]) or _sha(lsq_path) != str(report["lsq_sha256"]):
        return "stale"
    try:
        amps = pd.read_csv(amp_path)
        peak, dist = amps["peak_m"].to_numpy(dtype=float), amps["distance_km"].to_numpy(dtype=float)
        names = amps["station"].astype(str).tolist()
        max_dev = float(report["max_dev"])
    except (KeyError, ValueError, TypeError):
        return "report"
    if len(names) < int(crit.get("min_stations", 4)) or not (0.2 <= max_dev <= 1.5):
        return "amplitudes"
    got, err = _call(target, peak, dist, max_dev)
    if err is not None or not isinstance(got, dict):
        return "amplitudes"
    rejected = sorted(n for n, k in zip(names, np.asarray(got["keep"], dtype=bool)) if not k)
    try:
        if sorted(str(s) for s in report["rejected"]) != rejected:
            return "amplitudes"
    except TypeError:
        return "report"
    if not _summary_ok(ctx.get("summary"), ctx.rng):
        return "summary-func"
    kagan = ctx.get("kagan")
    if not _kagan_ok(kagan, ctx.rng):
        return "kagan-func"
    try:
        lsq = pd.read_csv(lsq_path)
        traces = pd.read_csv(tr_path)
        m6 = lsq.loc[lsq["misfit"].idxmin(), ["mrr", "mtt", "mpp", "mrt", "mrp", "mtp"]].to_numpy(dtype=float)
        depth = float(lsq.loc[lsq["misfit"].idxmin(), "depth_km"])
        terms = traces["term"].to_numpy(dtype=float)
        stations_used = {".".join(str(t).split(".")[:2]) for t in traces["trace"]}
    except (KeyError, ValueError, TypeError):
        return "lsq-file"
    if len(lsq) < 2 or terms.size < 3 or not np.all(np.isfinite(terms)) or np.any(terms < 0):
        return "lsq-file"
    if stations_used & set(rejected) or not stations_used <= set(names):
        return "lsq-file"
    if not _real(report["lsq_depth_km"]) or abs(float(report["lsq_depth_km"]) - depth) > 1e-9:
        return "lsq-depth"
    summary, _ = _call(ctx.get("summary"), m6)
    try:
        mine = [tuple(float(v) for v in p) for p in report["lsq_planes"]]
        again = [tuple(float(v) for v in p) for p in summary["planes"]]
    except (TypeError, ValueError, KeyError):
        return "lsq-planes"
    tol_deg = float(crit.get("recompute_tol_deg", 0.01))
    if len(mine) != 2 or not all(any(_same_plane(p, q, tol_deg) for q in again) for p in mine):
        return "lsq-planes"
    angle, err = _call(kagan, mine[0], KIGAM_A)
    if err is not None or not _real(report["kagan_lsq_kigam"]) or \
            abs(float(report["kagan_lsq_kigam"]) - float(angle)) > tol_deg:
        return "kagan"
    shares = terms / terms.sum()
    if not _real(report["n_eff_lsq"]) or abs(float(report["n_eff_lsq"]) - 1.0 / float(np.sum(shares ** 2))) > 1e-6:
        return "n-eff"
    return None


def check_T5(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    tol = float(crit.get("abs_tol", 1e-9))
    oks: List[bool] = []
    cats: List[Optional[str]] = []
    example = None
    for k in range(int(crit.get("trials", 30))):
        case = _t5_case(ctx.rng, k)
        keep = (case["peak"].copy(), case["dist"].copy())
        got, err = _call(target, case["peak"], case["dist"], case["max"])
        cat = "format" if err is not None else _t5_judge(got, case, tol)
        if cat is None and not (np.array_equal(keep[0], case["peak"], equal_nan=True)
                                and np.array_equal(keep[1], case["dist"])):
            cat = "changed-input"
        oks.append(cat is None)
        cats.append(cat)
        if cat and example is None:
            example = {"inputs": {"peak_m": np.round(case["peak"], 12).tolist(),
                                  "distance_km": np.round(case["dist"], 3).tolist(), "max_dev": round(case["max"], 4)},
                       "got": f"{type(err).__name__}: {err}" if err is not None else "see the category",
                       "error": f"expected deviation {np.round(case['dev'], 4).tolist()}"}
    if not all(oks):
        return outcome_from_cases(oks, category=_first(cats, T5_PRIORITY), example=example)
    with contextlib.redirect_stdout(io.StringIO()):
        real = _t5_real(target, ctx, crit)
    oks.append(real is None)
    return outcome_from_cases(oks, category=real, real_data=True)


# =========================================================================================== M53-T6
T6_PRIORITY = ("format", "changed-input", "rules-ignored", "boundary", "not-resolved", "provisional", "reasons",
               "wrong-values")
T6_REAL = ("no-report", "report", "stale", "norm", "rerun", "changed-run", "best", "traces", "kagan-func",
           "summary-func", "spread", "kagan", "verdict")
NOT_RESOLVED = ("min_stations", "min_n_eff", "max_share")
GOOD = ("good_n_eff", "good_share", "max_spread_deg", "max_kagan_lsq_deg")


def _t6_rules(rng: np.random.Generator, course: dict, vary: bool) -> dict:
    if not vary:
        return dict(course)
    rules = {"min_stations": int(rng.integers(3, 8)), "min_n_eff": float(rng.uniform(1.5, 4.0)),
             "max_share": float(rng.uniform(0.4, 0.7))}
    rules["good_n_eff"] = rules["min_n_eff"] + float(rng.uniform(1.0, 5.0))
    rules["good_share"] = rules["max_share"] - float(rng.uniform(0.05, 0.3))
    rules["max_spread_deg"] = float(rng.uniform(15.0, 45.0))
    rules["max_kagan_lsq_deg"] = float(rng.uniform(15.0, 45.0))
    return rules


def _t6_case(rng: np.random.Generator, rules: dict, edge: bool) -> dict:
    """Numbers on chosen sides of the rules; the verdict and reasons follow from the choice."""
    target = rng.choice(["not resolved", "provisional", "resolved"])
    fail: List[str] = []
    if target == "not resolved":
        while not fail:
            fail = [k for k in NOT_RESOLVED if rng.random() < 0.5]
    elif target == "provisional":
        while not fail:
            fail = [k for k in GOOD if rng.random() < 0.5]

    def side(low: float, high: float, at: float, bad: bool, upper_is_bad: bool, closed_ok: bool) -> float:
        if edge and not bad and closed_ok:
            return at
        if bad == upper_is_bad:
            return float(rng.uniform(at + 1e-6 * max(1.0, abs(at)), high))
        return float(rng.uniform(low, at - 1e-6 * max(1.0, abs(at))))

    n_st = int(rng.integers(1, rules["min_stations"])) if "min_stations" in fail else \
        int(rules["min_stations"]) if edge else int(rng.integers(rules["min_stations"] + 1, rules["min_stations"] + 10))
    if "min_n_eff" in fail:
        n_eff = float(rng.uniform(1.0, rules["min_n_eff"] - 1e-6))
    elif target == "not resolved":
        n_eff = float(rng.uniform(rules["min_n_eff"], rules["good_n_eff"] + 5))
    elif "good_n_eff" in fail:
        n_eff = rules["min_n_eff"] if edge else float(rng.uniform(rules["min_n_eff"], rules["good_n_eff"] - 1e-6))
    else:
        n_eff = rules["good_n_eff"] if edge else float(rng.uniform(rules["good_n_eff"], rules["good_n_eff"] + 10))
    if "max_share" in fail:
        share = float(rng.uniform(rules["max_share"] + 1e-6, 1.0))
    elif target == "not resolved":
        share = float(rng.uniform(0.05, rules["max_share"]))
    elif "good_share" in fail:
        share = rules["max_share"] if edge else float(rng.uniform(rules["good_share"] + 1e-6, rules["max_share"]))
    else:
        share = rules["good_share"] if edge else float(rng.uniform(0.02, rules["good_share"]))
    spread = side(0.0, 120.0, rules["max_spread_deg"], "max_spread_deg" in fail, True, True)
    kag = side(0.0, 120.0, rules["max_kagan_lsq_deg"], "max_kagan_lsq_deg" in fail, True, True)
    if target != "provisional" and target != "not resolved":
        spread = rules["max_spread_deg"] if edge else float(rng.uniform(0.0, rules["max_spread_deg"]))
        kag = rules["max_kagan_lsq_deg"] if edge else float(rng.uniform(0.0, rules["max_kagan_lsq_deg"]))
    order = NOT_RESOLVED if target == "not resolved" else GOOD
    return {"args": (n_st, n_eff, share, spread, kag), "rules": rules, "verdict": str(target),
            "reasons": [k for k in order if k in fail], "edge": edge}


def _t6_unpack(got: Any) -> Optional[Tuple[str, List[str]]]:
    if not isinstance(got, tuple) or len(got) != 2 or not isinstance(got[0], str):
        return None
    try:
        reasons = [str(r) for r in got[1]]
    except TypeError:
        return None
    return got[0], reasons


def _t6_synthetic(target: Any, ctx: Any, crit: dict) -> Tuple[List[bool], List[Optional[str]], Optional[dict]]:
    course = dict(crit["rules"])
    oks, cats, example = [], [], None
    varied, edges = [], []
    for k in range(int(crit.get("trials", 200))):
        vary = k % 2 == 1
        rules = _t6_rules(ctx.rng, course, vary)
        case = _t6_case(ctx.rng, rules, edge=k % 7 == 3)
        keep = dict(rules)
        got, err = _call(target, *case["args"], rules)
        pair = None if err is not None else _t6_unpack(got)
        if pair is None:
            cat = "format"
        elif rules != keep:
            cat = "changed-input"
        elif pair[0] != case["verdict"]:
            cat = "not-resolved" if "not resolved" in (pair[0], case["verdict"]) else "provisional"
        elif pair[1] != case["reasons"]:
            cat = "reasons"
        else:
            cat = None
        varied.append(vary)
        edges.append(case["edge"])
        oks.append(cat is None)
        cats.append(cat)
        if cat and example is None:
            example = {"inputs": dict(zip(("n_stations", "n_eff", "largest_share", "spread_deg", "kagan_lsq_deg"),
                                          [round(float(v), 6) for v in case["args"]]), rules=rules),
                       "got": f"{type(err).__name__}: {err}" if err is not None else repr(got)[:160],
                       "error": f"expected {(case['verdict'], case['reasons'])}"}
    bad = [not ok for ok in oks]
    plain = {"format", "changed-input"}
    if any(bad) and not any(c in plain for c in cats):
        if not any(b and not v for b, v in zip(bad, varied)):
            cats = ["rules-ignored" if c else c for c in cats]
        elif not any(b and not e for b, e in zip(bad, edges)):
            cats = ["boundary" if c else c for c in cats]
    return oks, cats, example


def _t6_norms(report: dict, folder: Path) -> Optional[str]:
    """The norm of each run: named in its folder's norm.txt and in the report, one that MTUQ computes as named."""
    as_named = ("L2", "hybrid")
    try:
        said = {label: str(report["norms"][label]) for label in RUN_LABELS}
        found = {label: (folder / f"M53_mtuq_{label}" / "norm.txt").read_text(encoding="utf-8").strip()
                 for label in RUN_LABELS}
    except (KeyError, TypeError, OSError, UnicodeDecodeError):
        return "report"
    if said != found:
        return "stale"
    if any(name not in as_named for name in said.values()):
        return "norm"
    if said["again"] != said["first"]:
        return "rerun"
    if said["changed"] == said["first"]:
        return "changed-run"
    return None


def _t6_real(target: Any, ctx: Any, crit: dict) -> Optional[str]:
    import pandas as pd
    report = ctx.get("report")
    if report is None:
        return "no-report"
    keys = {"runs", "norms", "grid_sha256", "best", "n_stations", "n_eff", "largest_share", "spread_deg",
            "kagan_kigam", "kagan_skhash", "kagan_lsq", "verdict", "reasons"}
    if not isinstance(report, dict) or not keys <= set(report) or not isinstance(report["runs"], dict):
        return "report"
    folder = ctx.get("results")
    if folder is None or not Path(folder).is_dir():
        return "report"
    folder = Path(folder)
    files = {label: folder / f"M53_mtuq_{label}" / "misfit.npy" for label in RUN_LABELS}
    grid_file = folder / "M53_mtuq_grid.npz"
    if any(not p.is_file() for p in files.values()) or not grid_file.is_file():
        return "report"
    try:
        if any(_sha(files[label]) != str(report["runs"][label]) for label in RUN_LABELS) or \
                _sha(grid_file) != str(report["grid_sha256"]):
            return "stale"
    except KeyError:
        return "report"
    named = _t6_norms(report, folder)
    if named is not None:
        return named
    values = {label: np.load(files[label], allow_pickle=False) for label in RUN_LABELS}
    axes = np.load(grid_file, allow_pickle=False)
    try:
        lengths = tuple(axes[name].size for name in ("mw", "strike", "rake", "dip", "depth_km"))
    except KeyError:
        return "report"
    if any(v.shape != lengths or not np.all(np.isfinite(v)) for v in values.values()):
        return "report"
    if not np.array_equal(values["first"], values["again"]):
        return "rerun"
    if np.array_equal(values["first"], values["changed"]):
        return "changed-run"

    def best(v: np.ndarray) -> List[float]:
        i, j, k, l, d = np.unravel_index(np.argmin(v), v.shape)
        return [float(axes["depth_km"][d]), float(axes["mw"][i]), float(axes["strike"][j]), float(axes["dip"][l]),
                float(axes["rake"][k])]

    try:
        for label in ("first", "changed"):
            mine = [float(x) for x in report["best"][label]]
            want = best(values[label])
            if len(mine) != 5 or any(abs(a - b) > 0.006 for a, b in zip(mine, want)):
                return "best"
    except (KeyError, TypeError, ValueError):
        return "report"
    try:
        traces = pd.read_csv(folder / "M53_mtuq_first" / "traces.csv")
        terms = traces["your_term"].to_numpy(dtype=float)
        mtuq_terms = traces["mtuq_misfit"].to_numpy(dtype=float)
        n_st = int(traces["station"].nunique())
    except (OSError, KeyError, ValueError):
        return "traces"
    if terms.size < 3 or not np.all(np.isfinite(terms)) or not np.allclose(terms, mtuq_terms, rtol=1e-6, atol=0.0):
        return "traces"
    shares = terms / terms.sum()
    rules = dict(crit["rules"])
    tol = float(crit.get("recompute_tol", 1e-6))
    for key, value in (("n_stations", n_st), ("n_eff", 1.0 / float(np.sum(shares ** 2))),
                       ("largest_share", float(shares.max()))):
        if not _real(report[key]) or abs(float(report[key]) - value) > tol * max(1.0, abs(value)):
            return "traces"
    kagan = ctx.get("kagan")
    if not _kagan_ok(kagan, ctx.rng):
        return "kagan-func"
    if not _summary_ok(ctx.get("summary"), ctx.rng):
        return "summary-func"
    best_first = best(values["first"])
    mech = tuple(best_first[2:])
    accepted = np.argwhere(values["first"] <= (1.0 + float(crit.get("accept_tol", 0.02))) * values["first"].min())
    angles = []
    for _, j, k, l, _ in accepted:
        angle, err = _call(kagan, mech, (float(axes["strike"][j]), float(axes["dip"][l]), float(axes["rake"][k])))
        if err is not None or not _real(angle):
            return "kagan-func"
        angles.append(float(angle))
    tol_deg = float(crit.get("recompute_tol_deg", 0.01))
    if not _real(report["spread_deg"]) or abs(float(report["spread_deg"]) - max(angles)) > tol_deg:
        return "spread"
    skhash = ctx.get("skhash")
    lsq = ctx.get("lsq")
    try:
        sk = pd.read_csv(skhash, dtype={"event_id": str})
        row = sk.loc[sk["event_id"] == EVENT_FOLDER].iloc[0]
        sk_mech = (float(row["strike"]), float(row["dip"]), float(row["rake"]))
        table = pd.read_csv(lsq)
        m6 = table.loc[table["misfit"].idxmin(), ["mrr", "mtt", "mpp", "mrt", "mrp", "mtp"]].to_numpy(dtype=float)
    except (OSError, KeyError, ValueError, IndexError, TypeError):
        return "report"
    summary, err = _call(ctx.get("summary"), m6)
    if err is not None:
        return "summary-func"
    for key, other in (("kagan_kigam", KIGAM_A), ("kagan_skhash", sk_mech),
                       ("kagan_lsq", tuple(float(v) for v in summary["planes"][0]))):
        angle, err = _call(kagan, mech, other)
        if err is not None or not _real(report[key]) or abs(float(report[key]) - float(angle)) > tol_deg:
            return "kagan"
    got, err = _call(target, n_st, 1.0 / float(np.sum(shares ** 2)), float(shares.max()), max(angles),
                     float(report["kagan_lsq"]), rules)
    pair = None if err is not None else _t6_unpack(got)
    if pair is None or report["verdict"] != pair[0] or [str(r) for r in report["reasons"]] != pair[1]:
        return "verdict"
    return None


def check_T6(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    oks, cats, example = _t6_synthetic(target, ctx, crit)
    if not all(oks):
        return outcome_from_cases(oks, category=_first(cats, T6_PRIORITY), example=example)
    with contextlib.redirect_stdout(io.StringIO()):
        real = _t6_real(target, ctx, crit)
    oks.append(real is None)
    return outcome_from_cases(oks, category=real, real_data=True)
