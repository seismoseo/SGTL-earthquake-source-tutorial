"""Checkers for M05 · Statistical seismology: b-value, completeness, aftershock decay.

Where the truth comes from (DESIGN.md section 1, rule 1):

* M05-T1: theory. Rounded Gutenberg-Richter magnitudes sit on bins mc + k*dm whose index k follows a
  geometric distribution, P(k) = (1 - q) q**k with q = 10**(-b*dm). Large samples are tested against it
  (a z-test on the mean index and a chi-square test on the bin counts; thresholds in criteria/M05.yaml).
  The function gets a numpy Generator that notes whole-number draws (geometric, integers, choice, ...): the task
  asks for continuous magnitudes rounded as a catalog rounds them, so drawing bin indices directly fails. That
  Generator withholds its bit generator and state (no plain Generator can be rebuilt from it), and the spec
  forbids numpy.random inside the function.
* M05-T2, T3, T4: an independent library, SeismoStats 1.0.1 (Mirwald et al. 2026): UtsuBValueEstimator and
  shi_bolt_confidence, estimate_mc_maxc, BPositiveBValueEstimator. The practice catalogs draw the bin index
  k directly from the geometric distribution (numpy's ``geometric``), a different route from the task's.
  The library sees clean bin values; the student's function may get the same values with one-ulp noise.
* M05-T5: a different formula. The rate integral is done by numerical quadrature in log time; the fit is
  judged on event times drawn by inverse CDF from known (K, c, p): the student's estimate must fit at least
  as well as the true parameters, and p must lie within a tolerance frozen from a Monte-Carlo study.
* M05-T6, T7: the student's own products. Their function runs on one made-up catalog (known answers) and on
  the shipped KMA catalog; its numbers are checked for consistency with SeismoStats run on the events the
  function itself returned, and for broad physical ranges. Real-data values are never printed. T6 also reads
  back the rate panel: its points must be the check's own counts per bin of the fitted events divided by the
  bin widths (bins inferred from the plotted centers), and a line must be the student's fitted rate. The
  Gyeongju choices (mc, dmc, t_start, t_end) must be given to st.check; no Mc is stored anywhere: mc must lie on
  the bin grid with at least mc_min_events events at or above it, and those magnitudes must pass SeismoStats'
  Kolmogorov-Smirnov test of a Gutenberg-Richter law with the student's own b.

Failure categories are keys of ``checks/specs/M05.yaml``; the engine prints their fixed messages.
"""
from __future__ import annotations

import math
import warnings
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .. import astguard
from . import Outcome, outcome_from_cases, within_tol

__all__ = ["check_T1", "check_T2", "check_T3", "check_T4", "check_T5", "check_T6", "check_T7"]

LN10 = math.log(10.0)
DAY_S = 86400.0


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


def _number(value: Any) -> Optional[float]:
    """A finite float from a plain number or a size-1 array, else None."""
    try:
        arr = np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        return None
    if arr.size != 1:
        return None
    out = float(arr.reshape(-1)[0])
    return out if math.isfinite(out) else None


def _close(a: Optional[float], b: float, rel: float, absolute: float = 0.0) -> bool:
    return a is not None and abs(a - b) <= max(absolute, rel * abs(b))


def _grid(levels: np.ndarray, dm: float) -> np.ndarray:
    """Clean float values of bin levels (integers times dm), written the way a catalog file would."""
    return np.round(np.asarray(levels, dtype=float) * dm, 10)


def _geometric_levels(rng: np.random.Generator, n: int, b: float, dm: float) -> np.ndarray:
    """Bin indices 0, 1, 2, ... of Gutenberg-Richter magnitudes with slope b (P(k) = (1-q) q**k)."""
    q = 10.0 ** (-b * dm)
    return rng.geometric(1.0 - q, int(n)).astype(np.int64) - 1


def _ulp_noise(rng: np.random.Generator, values: np.ndarray, share: float) -> np.ndarray:
    """Move a share of the values one floating-point step up or down (as arithmetic on floats does)."""
    out = np.array(values, dtype=float)
    pick = rng.random(out.size) < share
    down = rng.random(out.size) < 0.5
    out[pick & down] = np.nextafter(out[pick & down], -np.inf)
    out[pick & ~down] = np.nextafter(out[pick & ~down], np.inf)
    return out


def _ss_utsu(mags: np.ndarray, mc: float, dm: float) -> float:
    from seismostats.analysis import UtsuBValueEstimator
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return float(UtsuBValueEstimator().calculate(np.asarray(mags, dtype=float), mc=mc, delta_m=dm))


def _ss_classic(mags: np.ndarray, mc: float, dm: float) -> float:
    from seismostats.analysis import ClassicBValueEstimator
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return float(ClassicBValueEstimator().calculate(np.asarray(mags, dtype=float), mc=mc, delta_m=dm))


def _ss_shi_bolt(mags: np.ndarray, b: float) -> float:
    from seismostats.analysis import shi_bolt_confidence
    return float(shi_bolt_confidence(np.asarray(mags, dtype=float), b=b))


def _ss_maxc(mags: np.ndarray, dm: float, correction: float) -> float:
    from seismostats.analysis import estimate_mc_maxc
    return float(estimate_mc_maxc(np.asarray(mags, dtype=float), fmd_bin=dm, correction_factor=correction)[0])


def _ss_bpositive(mags: np.ndarray, dm: float, dmc: float) -> float:
    from seismostats.analysis import BPositiveBValueEstimator
    arr = np.asarray(mags, dtype=float)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return float(BPositiveBValueEstimator().calculate(arr, mc=float(arr.min()), delta_m=dm, dmc=dmc))


def _guard(func: Any, ctx: Any) -> Optional[Outcome]:
    """Apply the task's library rule to a second function given to st.check (the engine screens only one)."""
    rules = list((ctx.spec or {}).get("forbidden") or [])
    if func is None or not rules:
        return None
    rep = astguard.check_function(func, rules)
    if rep.ok:
        return None
    msg = ("This task asks you to write this step yourself, so the rule is: do not use "
           f"{', '.join(rep.violations)} here (found in {getattr(func, '__name__', 'your function')}).")
    return Outcome(False, 0, 0, "forbidden-import", msg, details={"found": rep.offending})


# ------------------------------------------------------------------------- M05-T1 simulate magnitudes
WHOLE_NUMBER_DRAWS = ("geometric", "integers", "choice", "binomial", "negative_binomial", "poisson",
                      "hypergeometric", "multivariate_hypergeometric", "multinomial", "logseries", "zipf")


def _withheld(self: Any, *args: Any) -> Any:
    raise AttributeError("The rng of this check gives random numbers only: draw them from rng itself "
                         "(rng.random, rng.exponential, ...), not from another generator made from it.")


class _DrawLog(np.random.Generator):
    """The Generator of np.random.default_rng(seed) (same numbers), noting draws of whole numbers.

    It does not hand out its bit generator, its state or children, so no plain Generator can be rebuilt from it
    to draw whole numbers unnoticed (the spec's forbidden list refuses numpy.random inside the function too).
    """

    def __init__(self, seed: int) -> None:
        super().__init__(np.random.PCG64(seed))
        self.whole_number_draws: List[str] = []

    bit_generator = property(_withheld)
    _bit_generator = property(_withheld)
    __reduce__ = _withheld
    __getstate__ = _withheld
    spawn = _withheld

    def __repr__(self) -> str:
        return "Generator(PCG64)"

    __str__ = __repr__


def _noting(name: str) -> Callable:
    def draw(self: _DrawLog, *args: Any, **kwargs: Any) -> Any:
        self.whole_number_draws.append(name)
        return getattr(np.random.Generator, name)(self, *args, **kwargs)

    draw.__name__ = name
    return draw


for _name in WHOLE_NUMBER_DRAWS:
    setattr(_DrawLog, _name, _noting(_name))


def _t1_cases(rng: np.random.Generator, k: int) -> List[Tuple[float, float, float]]:
    """(b, mc, dm) with mc a whole number of bins; always some dm other than 0.1."""
    menu = [(0.1, (0, 31)), (0.1, (5, 26)), (0.2, (0, 16)), (0.05, (10, 61)), (0.01, (100, 301)),
            (0.1, (-5, 5))]
    out = []
    for j in range(max(int(k), 4)):
        dm, (lo, hi) = menu[j % len(menu)]
        b = float(np.round(rng.uniform(0.6, 1.5), 3))
        out.append((b, float(np.round(dm * rng.integers(lo, hi), 10)), dm))
    return out


def _chi2_pvalue(levels: np.ndarray, q: float) -> Tuple[float, int]:
    """Chi-square test of bin counts against P(k) = (1 - q) q**k (tail merged where few are expected)."""
    from scipy.stats import chi2

    n = levels.size
    expect = []
    k = 0
    while True:
        e = n * (1.0 - q) * q ** k
        if e < 5.0 or k > 5000:
            break
        expect.append(e)
        k += 1
    k_top = len(expect)
    observed = np.bincount(np.minimum(levels, k_top), minlength=k_top + 1)[: k_top + 1].astype(float)
    expected = np.append(np.asarray(expect), n * q ** k_top)
    stat = float(((observed - expected) ** 2 / expected).sum())
    return float(chi2.sf(stat, k_top)), k_top


def check_T1(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    n = int(crit.get("n", 200000))
    z_max = float(crit.get("z_max", 5.0))
    p_min = float(crit.get("chi2_p_min", 1.0e-6))
    cases = _t1_cases(ctx.rng, int(crit.get("trials", 6)))
    ok: List[bool] = []

    def fail(category: str, b: float, mc: float, dm: float, got: Any, note: Optional[str] = None) -> Outcome:
        return outcome_from_cases(ok + [False], category=category, note=note, example={
            "inputs": {"n": n, "b": b, "mc": mc, "dm": dm, "rng": "np.random.default_rng(seed)"}, "got": got})

    for b, mc, dm in cases:
        seed = int(ctx.rng.integers(0, 2 ** 31 - 1))
        log = _DrawLog(seed)
        got, err = _call(target, n, b, mc, dm, log)
        if err is not None:
            raise err
        if log.whole_number_draws:
            return fail("whole-bins", b, mc, dm, f"rng.{log.whole_number_draws[0]}(...) was called")
        try:
            mags = np.asarray(got, dtype=float)
        except (TypeError, ValueError):
            return fail("shape", b, mc, dm, f"{type(got).__name__}")
        if mags.shape != (n,) or not np.all(np.isfinite(mags)):
            return fail("shape", b, mc, dm, f"{type(got).__name__} of shape {np.shape(got)}")
        if mags.min() < mc - 1e-6:
            return fail("below-mc", b, mc, dm, f"smallest value {mags.min():.4f}")
        steps = (mags - mc) / dm
        levels = np.rint(steps)
        if np.max(np.abs(steps - levels)) > 1e-6:
            return fail("unbinned", b, mc, dm, f"values such as {mags[np.argmax(np.abs(steps - levels))]:.6f}")
        levels = levels.astype(np.int64)
        used = np.unique(levels)
        if used.size > 3 and np.gcd.reduce(used[used > 0]) > 1:
            return fail("unbinned", b, mc, dm, f"only every {np.gcd.reduce(used[used > 0])}th bin is used")
        q = 10.0 ** (-b * dm)
        mean_k = float(levels.mean())
        z = (mean_k - q / (1.0 - q)) / (math.sqrt(q) / (1.0 - q) / math.sqrt(n))
        pval, _ = _chi2_pvalue(levels, q)
        if abs(z) > z_max or pval < p_min:
            q_hat = mean_k / (1.0 + mean_k)
            b_hat = -math.log10(q_hat) / dm if 0.0 < q_hat < 1.0 else float("nan")
            share0 = float((levels == 0).mean())
            if math.isfinite(b_hat) and (abs(b_hat / (b / LN10) - 1.0) < 0.05 or abs(b_hat / (b * LN10) - 1.0) < 0.05):
                category = "beta-for-b"
            elif abs(share0 - (1.0 - math.sqrt(q))) < 5.0 * math.sqrt(share0 * (1 - share0) / n) + 1e-4:
                category = "half-bin"
            else:
                category = "wrong-distribution"
            return fail(category, b, mc, dm, f"b estimated from your sample {b_hat:.3f} (asked for b = {b})")
        again, err = _call(target, n, b, mc, dm, _DrawLog(seed))
        other, err2 = _call(target, n, b, mc, dm, _DrawLog(seed + 1))
        if err is not None or err2 is not None or not np.array_equal(np.asarray(again, dtype=float), mags) \
                or np.array_equal(np.asarray(other, dtype=float), mags):
            return fail("rng", b, mc, dm, "different values for the same seed, or the same values for another seed")
        ok.append(True)
    return outcome_from_cases(ok)


# --------------------------------------------------------------------------- M05-T2 b-value and sigma
def _t2_case(rng: np.random.Generator, j: int) -> Dict[str, Any]:
    dm = (0.1, 0.1, 0.1, 0.2, 0.05, 0.1, 0.01, 0.1)[j % 8]
    b = float(rng.uniform(0.6, 1.5))
    mc_level = int(rng.integers(int(round(0.5 / dm)), int(round(3.0 / dm)) + 1))
    n_full = int(10 ** rng.uniform(1.6, 3.4))
    levels = mc_level + _geometric_levels(rng, n_full, b, dm)
    if j % 4 != 3:   # an incomplete part below mc (every fourth catalog has none)
        depth = int(rng.integers(1, max(2, int(round(0.6 / dm))) + 1))
        below = mc_level - 1 - _geometric_levels(rng, int(n_full * rng.uniform(0.2, 1.0)), 2.0, dm) % depth
        levels = np.concatenate([levels, below])
    levels = rng.permutation(levels)
    clean = _grid(levels, dm)
    noisy = _ulp_noise(rng, clean, 0.5) if j % 2 == 0 else clean.copy()
    return {"dm": dm, "mc": float(np.round(mc_level * dm, 10)), "clean": clean, "given": noisy, "b_true": b}


def check_T2(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    rel = float(crit.get("rel_tol", 1e-6))
    sigma_rel = float(crit.get("sigma_rel_tol", 0.002))
    sigma_func = ctx.get("shi_bolt")
    if sigma_func is not None:
        blocked = _guard(sigma_func, ctx)
        if blocked is not None:
            return blocked
    trials = int(crit.get("trials", 40))
    ok: List[bool] = []
    for j in range(trials):
        case = _t2_case(ctx.rng, j)
        dm, mc, given, clean = case["dm"], case["mc"], case["given"], case["clean"]
        expected = _ss_utsu(clean, mc, dm)
        got, err = _call(target, given.copy(), mc, dm)
        if err is not None:
            raise err
        value = _number(got)
        if not _close(value, expected, rel):
            kept = clean[clean >= mc - dm / 2]
            naive = given[given >= mc]
            alternatives = [
                ("natural-log", expected * LN10),
                ("no-dm-correction", 1.0 / (LN10 * (kept.mean() - mc))),
                ("exact-binned", _ss_classic(clean, mc, dm)),
                ("mc-filter", 1.0 / (LN10 * (given.mean() - mc + dm / 2))),
                ("mc-filter", 1.0 / (LN10 * (naive.mean() - mc + dm / 2)) if naive.size else float("nan")),
                ("mc-filter", 1.0 / (LN10 * (given[given > mc + dm / 2].mean() - mc + dm / 2))
                 if np.any(given > mc + dm / 2) else float("nan")),
            ]
            category = next((cat for cat, alt in alternatives if _close(value, alt, 1e-6)), "wrong-values")
            return outcome_from_cases(ok + [False], category=category, example={
                "inputs": f"{given.size} magnitudes ({int((clean < mc - dm / 2).sum())} below mc), mc = {mc}, "
                          f"dm = {dm}", "got": got if value is None else round(value, 6),
                "error": None if value is None else f"{value - expected:+.6f}"})
        ok.append(True)
    if sigma_func is None:
        return Outcome(False, trials + 1, 1, "missing-sigma")
    sigma_ok: List[bool] = []
    for j in range(int(crit.get("sigma_trials", 20))):
        case = _t2_case(ctx.rng, j)
        dm, mc, clean = case["dm"], case["mc"], case["clean"]
        used = clean[clean >= mc - dm / 2][: int(ctx.rng.integers(20, 120))]
        if used.size < 20:
            continue
        b = _ss_utsu(used, mc, dm)
        expected = _ss_shi_bolt(used, b)
        got, err = _call(sigma_func, used.copy(), b)
        if err is not None:
            raise err
        value = _number(got)
        sigma_ok.append(_close(value, expected, sigma_rel))
        if not sigma_ok[-1]:
            rule = b / math.sqrt(used.size)
            category = "rule-of-thumb" if _close(value, rule, 1e-3) else "shi-bolt"
            return outcome_from_cases(ok + sigma_ok, category=category, example={
                "inputs": f"{used.size} magnitudes at or above mc = {mc}, b = {b:.4f}",
                "got": got if value is None else round(value, 6),
                "error": None if value is None else f"{value - expected:+.6f}"})
    return outcome_from_cases(ok + sigma_ok)


# ----------------------------------------------------------------------------- M05-T3 maximum curvature
def _t3_case(rng: np.random.Generator, j: int) -> Dict[str, Any]:
    dm = (0.1, 0.1, 0.2, 0.1, 0.05, 0.1)[j % 6]
    corr = None if j % 3 == 0 else float((0.2, 0.0, 0.3, 0.1, 0.5)[j % 5])
    if j % 10 == 7:   # a tie for the largest count, built by hand
        top = int(rng.integers(5, 40))
        counts = np.array([2, top - 3, top, top, top - 4, 3, 1])
        start = int(rng.integers(0, int(round(2.0 / dm))))
        levels = np.repeat(start + np.arange(counts.size), counts)
    else:
        from scipy.stats import norm

        b = float(rng.uniform(0.7, 1.3))
        centre, width = float(rng.uniform(0.8, 2.0)), float(rng.uniform(0.1, 0.4))
        want = int(10 ** rng.uniform(2.3, 3.5))   # detected events
        levels = np.zeros(0, dtype=np.int64)
        while levels.size < want:
            draw = _geometric_levels(rng, 4 * want, b, dm)
            seen = rng.random(draw.size) < norm.cdf((draw * dm - centre) / width)
            levels = np.concatenate([levels, draw[seen]])
        levels = levels[:want]
    clean = _grid(rng.permutation(levels), dm)
    return {"dm": dm, "corr": corr, "clean": clean, "given": _ulp_noise(rng, clean, 0.3)}


def check_T3(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    tol = float(crit.get("abs_tol", 1e-6))
    trials = int(crit.get("trials", 30))
    ok: List[bool] = []
    for j in range(trials):
        case = _t3_case(ctx.rng, j)
        dm, corr, clean, given = case["dm"], case["corr"], case["clean"], case["given"]
        used_corr = 0.2 if corr is None else corr
        expected = _ss_maxc(clean, dm, used_corr)
        if corr is None:
            got, err = _call(target, given.copy(), dm)
        else:
            got, err = _call(target, given.copy(), dm, correction=corr)
        if err is not None:
            raise err
        value = _number(got)
        if not _close(value, expected, 0.0, tol):
            shifts = [("no-correction", -used_corr), ("left-edge", -dm / 2), ("right-edge", dm / 2),
                      ("correction-argument", 0.2 - used_corr)]
            category = "wrong-values"
            if value is not None:
                lv, counts = np.unique(np.rint(clean / dm).astype(np.int64), return_counts=True)
                tied = lv[counts == counts.max()]
                if tied.size > 1 and any(abs(value - (t * dm + used_corr)) <= tol for t in tied[1:]):
                    category = "ties"
                else:
                    for cat, shift in shifts:
                        if shift != 0.0 and abs(value - (expected + shift)) <= tol:
                            category = cat
                            break
            call = "mc_maxc(mags, dm)" if corr is None else f"mc_maxc(mags, dm, correction={corr})"
            return outcome_from_cases(ok + [False], category=category, example={
                "inputs": f"{call} with {given.size} magnitudes from {given.min():.2f} to {given.max():.2f}, "
                          f"dm = {dm}", "got": got if value is None else round(value, 6),
                "error": None if value is None else f"{value - expected:+.4f}"})
        ok.append(True)
    return outcome_from_cases(ok)


# ------------------------------------------------------------------------------------ M05-T4 b-positive
def _t4_case(rng: np.random.Generator, j: int) -> Dict[str, Any]:
    dm = (0.1, 0.1, 0.1, 0.2, 0.05)[j % 5]
    dmc = (None, None, 1, 2, 3)[j % 5]
    b = float(rng.uniform(0.7, 1.4))
    n = int(10 ** rng.uniform(2.5, 3.5))
    base = int(rng.integers(0, int(round(1.5 / dm)) + 1))
    levels = base + _geometric_levels(rng, n, b, dm)
    # transient incompleteness: right after a large event the small ones are often missed
    keep = np.ones(n, dtype=bool)
    lift = 0.0
    for i in range(n):
        lift *= 0.8
        if levels[i] * dm - base * dm < lift and rng.random() < 0.7:
            keep[i] = False
            continue
        lift = max(lift, levels[i] * dm - base * dm - 1.0)
    levels = levels[keep]
    clean = _grid(levels, dm)
    return {"dm": dm, "dmc": None if dmc is None else float(np.round(dmc * dm, 10)), "clean": clean,
            "given": _ulp_noise(rng, clean, 0.5) if j % 2 == 0 else clean.copy()}


def _tm_formula(values: np.ndarray, threshold: float, dm: float) -> float:
    """Exact binned estimator of Tinti and Mulargia (1987), used to name a wrong turn."""
    gap = values.mean() - threshold
    return math.log(1.0 + dm / gap) / (dm * LN10) if gap > 0 else float("nan")


def check_T4(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    rel = float(crit.get("rel_tol", 1e-6))
    trials = int(crit.get("trials", 30))
    ok: List[bool] = []
    for j in range(trials):
        case = _t4_case(ctx.rng, j)
        dm, dmc, clean, given = case["dm"], case["dmc"], case["clean"], case["given"]
        dmc_used = dm if dmc is None else dmc
        expected = _ss_bpositive(clean, dm, dmc_used)
        if dmc is None:
            got, err = _call(target, given.copy(), dm)
        else:
            got, err = _call(target, given.copy(), dm, dmc=dmc)
        if err is not None:
            raise err
        value = _number(got)
        if not _close(value, expected, rel):
            d = np.round(np.diff(clean) / dm) * dm
            ups = d[d >= dmc_used - dm / 2]
            raw = np.diff(given)
            alternatives = [
                ("order", _ss_bpositive(np.sort(clean), dm, dmc_used)),
                ("all-differences", _tm_formula(np.abs(d)[np.abs(d) >= dmc_used - dm / 2], dmc_used, dm)),
                ("threshold", _tm_formula(raw[raw >= dmc_used], dmc_used, dm)),
                ("threshold", _tm_formula(raw[raw > dmc_used], dmc_used, dm)),
                ("threshold", _tm_formula(d[d > 0], dmc_used, dm)),
                ("threshold", _tm_formula(d[d >= dm - dm / 2], dmc_used, dm)),
                ("threshold", _tm_formula(ups, dm, dm)),
                ("binning", 1.0 / (LN10 * (ups.mean() - dmc_used + dm / 2))),
                ("binning", 1.0 / (LN10 * (ups.mean() - dmc_used))),
            ]
            category = "wrong-values"
            for cat, alt in alternatives:
                if math.isfinite(alt) and _close(value, alt, 1e-6):
                    category = cat
                    break
            call = "b_positive(mags, dm)" if dmc is None else f"b_positive(mags, dm, dmc={dmc})"
            return outcome_from_cases(ok + [False], category=category, example={
                "inputs": f"{call} with {given.size} magnitudes in time order, dm = {dm}",
                "got": got if value is None else round(value, 6),
                "error": None if value is None else f"{value - expected:+.6f}"})
        ok.append(True)
    return outcome_from_cases(ok)


# ------------------------------------------------------------------------------- M05-T5 Omori-Utsu fit
def _rate_integral(K: float, c: float, p: float, t0: float, t1: float) -> float:
    """Integral of K / (t + c)**p from t0 to t1, by quadrature in u = ln(t + c) (a different formula)."""
    from scipy.integrate import quad

    lo, hi = math.log(t0 + c), math.log(t1 + c)
    val, _ = quad(lambda u: math.exp((1 - p) * u) * K, lo, hi, epsabs=0.0, epsrel=1e-12, limit=200)
    return float(val)


def _nll_ref(K: float, c: float, p: float, times: np.ndarray, t0: float, t1: float) -> float:
    log_terms = math.log(K) * times.size - p * float(np.sum(np.log(times + c)))
    return _rate_integral(K, c, p, t0, t1) - log_terms


def _omori_times(rng: np.random.Generator, K: float, c: float, p: float, t0: float, t1: float) -> np.ndarray:
    """Event times of a Poisson process with rate K/(t+c)**p on [t0, t1], by inverse CDF of the density."""
    count = int(rng.poisson(_rate_integral(K, c, p, t0, t1)))
    u = rng.random(count)
    if p == 1.0:
        return np.sort((t0 + c) * np.power((t1 + c) / (t0 + c), u) - c)
    e = 1.0 - p
    edge0, edge1 = math.pow(t0 + c, e), math.pow(t1 + c, e)
    return np.sort(np.clip(np.power(edge0 + (edge1 - edge0) * u, 1.0 / e) - c, t0, t1))


def _t5_nll_case(rng: np.random.Generator, j: int) -> Tuple[Tuple[float, float, float], np.ndarray, float, float]:
    K = float(10 ** rng.uniform(0.0, 2.7))
    c = float(10 ** rng.uniform(-3.0, 0.0))
    if j % 5 == 0:
        p = 1.0
    else:
        p = float(rng.uniform(0.6, 1.6))
        if abs(p - 1.0) < 0.01:
            p += 0.02
    t0 = 0.0 if j % 3 == 0 else float(rng.uniform(0.0, 1.0))
    t1 = float(rng.uniform(10.0, 500.0))
    times = np.sort(t0 + (t1 - t0) * rng.random(int(rng.integers(5, 400))) ** 3)
    return (K, c, p), times, t0, t1


def _t5_fit_case(rng: np.random.Generator, j: int) -> Tuple[Tuple[float, float, float], float, float]:
    c = float(10 ** rng.uniform(math.log10(0.005), math.log10(0.2)))
    p = 1.0 if j % 4 == 0 else float(rng.uniform(0.8, 1.4))
    t0 = 0.0 if j % 2 == 0 else float(rng.uniform(0.01, 0.2))
    t1 = float(rng.uniform(100.0, 400.0))
    K = float(rng.uniform(800.0, 3000.0)) / _rate_integral(1.0, c, p, t0, t1)
    return (K, c, p), t0, t1


def check_T5(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    rel, absolute = float(crit.get("rel_tol", 1e-6)), float(crit.get("abs_tol", 1e-6))
    trials = int(crit.get("trials", 30))
    fit = ctx.get("fit")
    if fit is not None:
        blocked = _guard(fit, ctx)
        if blocked is not None:
            return blocked
    ok: List[bool] = []
    bad: Optional[Dict[str, Any]] = None
    p1_bad = other_bad = 0
    for j in range(trials):
        (K, c, p), times, t0, t1 = _t5_nll_case(ctx.rng, j)
        expected = _nll_ref(K, c, p, times, t0, t1)
        params = (K, c, p) if j % 2 else np.array([K, c, p])
        got, err = _call(target, params, times.copy(), t0, t1)
        value = _number(got) if err is None else None
        good = _close(value, expected, rel, absolute)
        ok.append(good)
        if good:
            continue
        if p == 1.0:
            p1_bad += 1
        else:
            other_bad += 1
        if bad is None or (bad["p"] == 1.0 and p != 1.0):
            bad = {"K": K, "c": c, "p": p, "times": times, "t0": t0, "t1": t1, "value": value, "err": err,
                   "expected": expected}
    if bad is not None:
        if other_bad == 0 and p1_bad > 0:
            category = "p-equals-1"
        elif bad["err"] is not None:
            raise bad["err"]
        else:
            category = _t5_category(bad)
        example = {"inputs": {"params": (round(bad["K"], 4), round(bad["c"], 5), round(bad["p"], 4)),
                              "t": f"{bad['times'].size} times from {bad['times'].min():.4f} to "
                                   f"{bad['times'].max():.2f} days", "t_start": round(bad["t0"], 5),
                              "t_end": round(bad["t1"], 3)},
                   "got": "an error" if bad["err"] is not None else bad["value"],
                   "error": None if bad["value"] is None else f"{bad['value'] - bad['expected']:+.6g}"}
        return outcome_from_cases(ok, category=category, example=example)
    if fit is None:
        return Outcome(False, trials + 1, 1, "missing-fit")
    return _t5_fit(fit, ctx, ok)


def _t5_category(bad: Dict[str, Any]) -> str:
    K, c, p, times, t0, t1, value = (bad[k] for k in ("K", "c", "p", "times", "t0", "t1", "value"))
    if value is None:
        return "wrong-values"
    area = _rate_integral(K, c, p, t0, t1)
    full = bad["expected"]
    checks = [
        ("sign", -full),
        ("integral", full - area),
        ("integral", full - area + _rate_integral(K, c, p, 0.0, t1)),
        ("integral", full - 2 * area),
        ("log-rate", full + math.log(K) * times.size),
    ]
    for factor in (24.0, 1440.0, DAY_S):   # times turned into hours, minutes or seconds inside the function
        checks.append(("units", _nll_ref(K, c, p, times * factor, t0 * factor, t1 * factor)))
        checks.append(("units", _nll_ref(K, c * factor, p, times * factor, t0 * factor, t1 * factor)))
    if K < 50.0:   # K and c read as natural logarithms
        checks.append(("units", _nll_ref(math.exp(K), math.exp(c), p, times, t0, t1)))
    for cat, alt in checks:
        if math.isfinite(alt) and _close(value, alt, 1e-6, 1e-6):
            return cat
    return "wrong-values"


def _t5_fit(fit: Callable, ctx: Any, ok: List[bool]) -> Outcome:
    crit = ctx.criteria
    p_tol = float(crit.get("p_tol", 0.15))
    slack = float(crit.get("nll_slack", 0.05))
    fit_ok: List[bool] = []
    for j in range(int(crit.get("fit_trials", 4))):
        (K, c, p), t0, t1 = _t5_fit_case(ctx.rng, j)
        times = _omori_times(ctx.rng, K, c, p, t0, t1)
        got, err = _call(fit, times.copy(), t0, t1)
        if err is not None:
            raise err
        inputs = (f"{times.size} event times drawn from K = {K:.4g} per day, c = {c:.4g} days, p = {p:.4f}, "
                  f"t_start = {t0:.4g}, t_end = {t1:.4g}")
        try:
            vals = [float(v) for v in got]
        except (TypeError, ValueError):
            vals = []
        if len(vals) != 3 or not all(math.isfinite(v) for v in vals) or vals[0] <= 0 or vals[1] <= 0:
            return outcome_from_cases(ok + fit_ok + [False], category="fit-output",
                                      example={"inputs": inputs, "got": got})
        k_hat, c_hat, p_hat = vals
        best = _nll_ref(k_hat, c_hat, p_hat, times, t0, t1)
        truth = _nll_ref(K, c, p, times, t0, t1)
        if best > truth + slack:
            category = "not-converged"
            for factor in (24.0, 1440.0, DAY_S):
                back = _nll_ref(k_hat * factor ** (1.0 - p_hat), c_hat / factor, p_hat, times, t0, t1)
                if back <= truth + slack:
                    category = "units"
            return outcome_from_cases(ok + fit_ok + [False], category=category, example={
                "inputs": inputs, "got": (round(k_hat, 4), round(c_hat, 6), round(p_hat, 4)),
                "error": f"negative log-likelihood {best - truth:+.4f} above that of the true parameters"})
        if abs(p_hat - p) > p_tol:
            return outcome_from_cases(ok + fit_ok + [False], category="fit", example={
                "inputs": inputs, "got": (round(k_hat, 4), round(c_hat, 6), round(p_hat, 4)),
                "error": f"p off by {p_hat - p:+.4f}"})
        fit_ok.append(True)
    return outcome_from_cases(ok + fit_ok)


# ----------------------------------------------------------------- shared by M05-T6 and M05-T7 (artifacts)
def _figure_problem(fig: Any, *, min_axes: int, min_series: int = 1, need_log: bool = False) -> Optional[str]:
    from matplotlib.figure import Figure

    if not isinstance(fig, Figure):
        return f"a {type(fig).__name__}, not a matplotlib Figure"

    def series(ax: Any) -> int:
        return len(ax.lines) + len(ax.collections) + len(ax.containers) + len(ax.images) + \
            (1 if ax.patches and not ax.containers else 0)

    drawn = [ax for ax in fig.get_axes() if series(ax) > 0]
    if len(drawn) < min_axes:
        return f"{len(drawn)} panel(s) with data; {min_axes} are needed"
    if sum(series(ax) for ax in drawn) < min_series:
        return f"fewer than {min_series} sets of data are drawn"
    if need_log and not any("log" in (ax.get_yscale(), ax.get_xscale()) for ax in drawn):
        return "no panel uses a logarithmic axis"
    return None


def _xy_series(ax: Any) -> List[Tuple[np.ndarray, np.ndarray]]:
    """(x, y) of every line and scatter set drawn on one panel, as float arrays (masked values as NaN)."""
    from matplotlib.collections import PathCollection

    out = []
    for artist in list(ax.lines) + [col for col in ax.collections if isinstance(col, PathCollection)]:
        try:
            if isinstance(artist, PathCollection):
                xy = np.ma.filled(np.ma.asarray(artist.get_offsets(), dtype=float), np.nan).reshape(-1, 2)
                x, y = xy[:, 0], xy[:, 1]
            else:
                x = np.ma.filled(np.ma.asarray(artist.get_xdata(), dtype=float), np.nan).reshape(-1)
                y = np.ma.filled(np.ma.asarray(artist.get_ydata(), dtype=float), np.nan).reshape(-1)
        except (TypeError, ValueError):
            continue
        if x.shape == y.shape:
            out.append((x, y))
    return out


def _binned_rate_match(x: np.ndarray, y: np.ndarray, times: np.ndarray, slack: float, coverage: float) -> bool:
    """True when the points (x, y) are the counts of ``times`` in bins evenly spaced in log time divided by the
    bin widths, drawn at the bin centers (geometric or arithmetic); empty bins may be left out. The bins are
    inferred from the spacing of the plotted centers, so any number of bins is accepted."""
    keep = np.isfinite(x) & (x > 0) & np.isfinite(y)
    x, y = x[keep], y[keep]
    if x.size < 4 or times.size == 0:
        return False
    order = np.argsort(x)
    x, y = x[order], y[order]
    gaps = np.diff(np.log10(x))
    if np.any(gaps <= 1e-9):
        return False
    t = np.sort(times)
    for parts in (1, 2, 3):                    # empty bins left out: the smallest gap may span 2 or 3 bins
        step = float(gaps.min()) / parts
        multiples = gaps / step
        if np.max(np.abs(multiples - np.rint(multiples))) > 1e-3:
            continue
        ratio = 10.0 ** step
        for left in (x / math.sqrt(ratio), 2.0 * x / (1.0 + ratio)):
            right = left * ratio
            counts = np.searchsorted(t, right, side="right") - np.searchsorted(t, left, side="left")
            if counts.sum() < coverage * t.size:
                continue
            if np.all(np.abs(y * (right - left) - counts) <= slack + 1e-6 * counts):
                return True
    return False


def _fit_curve_match(x: np.ndarray, y: np.ndarray, K: float, c: float, p: float, rel: float) -> bool:
    keep = np.isfinite(x) & (x > 0) & np.isfinite(y) & (y > 0)
    if keep.sum() < 2:
        return False
    model = K / np.power(x[keep] + c, p)
    return bool(np.all(np.abs(y[keep] - model) <= rel * model))


def _rate_panel_problem(fig: Any, times: np.ndarray, K: float, c: float, p: float, crit: dict) -> Optional[str]:
    """Read back the rate panel: observed points against the check's own binned rate, and the fitted line."""
    slack = float(crit.get("rate_slack_events", 1.0))
    coverage = float(crit.get("rate_coverage", 0.9))
    rel = float(crit.get("fit_rel_tol", 1.0e-3))
    panels = [ax for ax in fig.get_axes() if ax.get_xscale() == "log" and ax.get_yscale() == "log"]
    if not panels:
        return "no panel has both axes logarithmic"
    found = (False, False)
    for ax in panels:
        series = _xy_series(ax)
        rates = any(_binned_rate_match(x, y, times, slack, coverage) for x, y in series)
        line = any(_fit_curve_match(x, y, K, c, p, rel) for x, y in series)
        if rates and line:
            return None
        found = (found[0] or rates, found[1] or line)
    if found[0]:
        return "the rate panel has the binned rates but no line of your fitted K/(t + c)^p"
    return ("no set of points on a log-log panel equals the counts per bin of the fitted events divided by the "
            "bin widths (bins evenly spaced in log time)")


def _close_new_figures(before: set) -> None:
    import matplotlib.pyplot as plt

    for num in set(plt.get_fignums()) - before:
        plt.close(num)


def _event_ids(df: Any) -> Optional[set]:
    if not isinstance(df, pd.DataFrame) or "event_id" not in df or "origin_utc" not in df or "ml" not in df:
        return None
    return set(df["event_id"].astype(str))


# ------------------------------------------------------------------------------- M05-T6 Gyeongju 2016
T6_KEYS = ("events", "mc_maxc", "mc", "b", "sigma_b", "b_positive", "K", "c", "p", "t_start", "t_end", "figure")
T6_ARGS = ("mc", "dmc", "t_start", "t_end")   # the student's choices for gyeongju2016, always given to st.check


def _synthetic_sequence(rng: np.random.Generator) -> Tuple[pd.DataFrame, Dict[str, float]]:
    """A made-up sequence: foreshocks, an ML 5.5 mainshock, Omori-decaying GR aftershocks complete above 1.0."""
    from ..synth import KST

    dm, m_low = 0.1, 1.0
    b = float(rng.uniform(0.8, 1.2))
    c = float(10 ** rng.uniform(-2.0, -1.0))
    p = float(rng.uniform(0.9, 1.3))
    span = 400.0
    K = float(rng.uniform(5000.0, 9000.0)) / _rate_integral(1.0, c, p, 0.0, span)
    after_days = _omori_times(rng, K, c, p, 0.0, span)
    after_days = after_days[after_days > 1e-4]
    n_fore = int(rng.integers(5, 20))
    fore_days = -np.sort(rng.uniform(0.01, 10.0, n_fore))[::-1]
    days = np.concatenate([fore_days, [0.0], after_days])
    levels = int(round(m_low / dm)) + _geometric_levels(rng, days.size, b, dm)
    levels = np.minimum(levels, int(round(4.9 / dm)))
    levels[n_fore] = int(round(5.5 / dm))
    t_main = pd.Timestamp("2021-03-01T00:00:00Z") + pd.Timedelta(seconds=float(rng.uniform(0, 86400 * 300)))
    origin = t_main + pd.to_timedelta(np.round(days * DAY_S, 3), unit="s")
    n = days.size
    df = pd.DataFrame({
        "event_id": [f"SYN{i:06d}" for i in range(1, n + 1)],
        "origin_utc": pd.Series(origin, dtype="datetime64[ns, UTC]"),
        "latitude": np.round(36.0 + rng.normal(0.0, 0.02, n), 4),
        "longitude": np.round(128.5 + rng.normal(0.0, 0.02, n), 4),
        "depth_km": np.round(rng.uniform(8.0, 15.0, n), 1),
        "ml": _grid(levels, dm),
    })
    df.insert(2, "origin_kst", df["origin_utc"].dt.tz_convert(KST))
    df = df.sort_values("origin_utc", kind="mergesort").reset_index(drop=True)
    df.attrs["source"] = "synthetic sequence (M05-T6 check); not real earthquakes"
    return df, {"b": b, "c": c, "p": p, "K": K}


def _gr_law_holds(mags: np.ndarray, mc: float, dm: float, b: float, crit: dict, rng: np.random.Generator) -> bool:
    """SeismoStats' Kolmogorov-Smirnov test of a Gutenberg-Richter law at and above mc with the student's own b
    (Clauset et al. 2009; Mizrahi et al. 2021): True when the law cannot be rejected at the ks_p_min level.
    Its simulated catalogs draw from numpy's global generator, seeded here from the check's rng and restored."""
    from seismostats.analysis.estimate_mc import ks_test_gr

    state = np.random.get_state()
    try:
        np.random.seed(int(rng.integers(0, 2 ** 31 - 1)))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            p_value = float(ks_test_gr(np.asarray(mags, dtype=float), mc=mc, delta_m=dm, b_value=b,
                                       n=int(crit.get("ks_sims", 2000)))[0])
    finally:
        np.random.set_state(state)
    return p_value >= float(crit.get("ks_p_min", 0.1))


def _t6_review(res: Any, seq: pd.DataFrame, args: Dict[str, float], crit: dict, *, real: bool,
               truth: Optional[Dict[str, float]] = None,
               rng: Optional[np.random.Generator] = None) -> Optional[Tuple[str, str]]:
    """First problem found, as (category, short description without real-data values), or None."""
    dm, mc, dmc, t0, t1 = (args[k] for k in ("dm", "mc", "dmc", "t_start", "t_end"))
    if not isinstance(res, dict) or any(k not in res for k in T6_KEYS):
        missing = [k for k in T6_KEYS if not isinstance(res, dict) or k not in res]
        return "keys", f"missing keys: {', '.join(missing)}"
    ids = _event_ids(res["events"])
    main_time = seq.loc[seq["ml"].idxmax(), "origin_utc"]
    want = set(seq.loc[seq["origin_utc"] > main_time, "event_id"].astype(str))
    if ids is None or ids != want:
        return "selection", "the events are not exactly the events after the mainshock"
    numbers = {k: _number(res[k]) for k in T6_KEYS if k not in ("events", "figure")}
    if any(v is None for v in numbers.values()):
        return "keys", "every value except events and figure must be one finite number"
    ev = res["events"].sort_values("origin_utc", kind="mergesort")
    mags = ev["ml"].to_numpy(dtype=float)
    if not _close(numbers["mc_maxc"], _ss_maxc(mags, dm, 0.2), 0.0, 1e-6):
        return "mc-maxc", "mc_maxc differs from the maximum-curvature Mc (+0.2) of the events"
    if abs(numbers["mc"] - mc) > 1e-9:
        return "keys", "the value under 'mc' is not the mc given to the function"
    used = mags[mags >= mc - dm / 2]
    if real and (abs(mc / dm - round(mc / dm)) > 1e-6 or used.size < int(crit.get("mc_min_events", 50))):
        return "mc-choice", "mc is not a whole number of bins, or too few events are left at or above it"
    if used.size < 20:
        return "mc-choice", "fewer than 20 events at or above mc"
    b_ref = [_ss_utsu(used, mc, dm), _ss_classic(used, mc, dm)]
    if not any(_close(numbers["b"], ref, 0.01) for ref in b_ref):
        return "b-consistency", "b does not match the events at or above mc"
    if real and not _gr_law_holds(used, mc, dm, numbers["b"], crit, rng if rng is not None else
                                  np.random.default_rng(0)):
        return "mc-choice", "the magnitudes at or above mc do not pass the check's test of a Gutenberg-Richter law"
    if not _close(numbers["sigma_b"], _ss_shi_bolt(used, numbers["b"]), 0.02):
        return "sigma", "sigma_b does not match Shi and Bolt's formula for those events"
    if not _close(numbers["b_positive"], _ss_bpositive(used, dm, dmc), 0.01):
        return "b-positive", "b_positive does not match the events at or above mc in time order"
    if abs(numbers["t_start"] - t0) > 1e-9 or abs(numbers["t_end"] - t1) > 1e-9:
        return "keys", "t_start and t_end must be the values given to the function"
    days = (ev["origin_utc"] - main_time).dt.total_seconds().to_numpy() / DAY_S
    n_window = int(np.sum((mags >= mc - dm / 2) & (days >= t0) & (days <= t1)))
    K, c, p = numbers["K"], numbers["c"], numbers["p"]
    if K <= 0 or c <= 0:
        return "omori-count", "K and c must be positive"
    if not _close(_rate_integral(K, c, p, t0, t1), n_window, float(crit.get("count_rel_tol", 0.05))):
        return "omori-count", "the fitted rate does not add up to the number of events in the window"
    if truth is not None and abs(p - truth["p"]) > float(crit.get("p_tol", 0.12)):
        return "omori-fit", "p is far from the value the made-up sequence was built with"
    if real:
        lo, hi = crit.get("b_range", [0.5, 1.6])
        if not lo <= numbers["b"] <= hi or not lo - 0.1 <= numbers["b_positive"] <= hi + 0.4:
            return "b-range", "b or b-positive is outside the broad range seen for crustal earthquakes"
        lo, hi = crit.get("p_range", [0.5, 2.0])
        if not lo <= p <= hi:
            return "p-range", "p is outside the broad range seen for aftershock sequences"
    problem = _figure_problem(res["figure"], min_axes=2, need_log=True)
    if problem:
        return "figure", problem
    fitted = days[(mags >= mc - dm / 2) & (days >= t0) & (days <= t1)]
    problem = _rate_panel_problem(res["figure"], fitted, K, c, p, crit)
    if problem:
        return "rate-panel", problem
    return None


def check_T6(target: Any, ctx: Any) -> Outcome:
    import matplotlib.pyplot as plt
    from ..data import sequence

    crit = ctx.criteria
    seq_syn, truth = _synthetic_sequence(ctx.rng)
    syn_args = {"dm": 0.1, "mc": 1.5, "dmc": 0.2, "t_start": 0.01, "t_end": 365.0}
    before = set(plt.get_fignums())
    try:
        res, err = _call(target, seq_syn.copy(), *(syn_args[k] for k in ("dm", "mc", "dmc", "t_start", "t_end")))
        if err is not None:
            raise err
        found = _t6_review(res, seq_syn, syn_args, crit, real=False, truth=truth)
        if found:
            return Outcome(False, 1, 1, found[0], details={"example": {
                "inputs": f"a made-up sequence ({len(seq_syn)} events, b = {truth['b']:.3f}, "
                          f"p = {truth['p']:.3f}) with dm=0.1, mc=1.5, dmc=0.2, t_start=0.01, t_end=365",
                "got": found[1]}})
        missing = [k for k in T6_ARGS if _number(ctx.get(k)) is None]
        if missing:                                  # the check has no values of its own for these
            return Outcome(False, 2, 1, "arguments", details={"example": {
                "inputs": "the gyeongju2016 sequence", "got": "missing or not a number: " + ", ".join(missing)}})
        real_args = {"dm": 0.1, **{k: float(_number(ctx[k])) for k in T6_ARGS}}
        seq_real = sequence("gyeongju2016")
        res, err = _call(target, seq_real.copy(), *(real_args[k] for k in ("dm", "mc", "dmc", "t_start", "t_end")))
        if err is not None:
            raise err
        found = _t6_review(res, seq_real, real_args, crit, real=True, rng=ctx.rng)
        if found:
            return Outcome(False, 2, 1, found[0], details={"real_data": True, "example": {
                "inputs": "the gyeongju2016 sequence with your parameters " + ", ".join(
                    f"{k}={v:g}" for k, v in real_args.items()), "got": found[1]}})
    finally:
        _close_new_figures(before)
    return Outcome(True, 2, 0, details={"note": "Your mentor reads your figure and your choices of mc and t_start."})


# ------------------------------------------------------------------------ M05-T7 declustering (stretch)
T7_KEYS = ("events", "mainshock_flags", "mc", "b_all", "b_declustered", "figure")


def _gk_flags(events: pd.DataFrame) -> np.ndarray:
    from seismostats.analysis.declustering import GardnerKnopoffType1, GardnerKnopoffWindow

    when = pd.to_datetime(events["origin_utc"], utc=True).dt.tz_localize(None)
    table = pd.DataFrame({"time": when.to_numpy(), "magnitude": events["ml"].to_numpy(dtype=float),
                          "latitude": events["latitude"].to_numpy(dtype=float),
                          "longitude": events["longitude"].to_numpy(dtype=float)})
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return np.asarray(GardnerKnopoffType1(GardnerKnopoffWindow())(table), dtype=bool)


def _synthetic_national(rng: np.random.Generator) -> pd.DataFrame:
    """Background events plus a few clusters (a large event followed by smaller ones close by)."""
    from ..synth import KST, random_points, random_utc_times

    dm = 0.1
    n_bg = int(rng.integers(250, 400))
    t_bg = random_utc_times(rng, n_bg, "2020-01-01", "2022-01-01")
    lat, lon = random_points(rng, n_bg)
    mags = 2.1 + _grid(_geometric_levels(rng, n_bg, 1.0, dm), dm)
    rows = [pd.DataFrame({"origin_utc": t_bg, "latitude": lat, "longitude": lon, "ml": mags})]
    for _ in range(int(rng.integers(3, 6))):
        t_main = random_utc_times(rng, 1, "2020-02-01", "2021-10-01")[0]
        la, lo = random_points(rng, 1)
        k = int(rng.integers(10, 40))
        lag = pd.to_timedelta(rng.exponential(5.0, k), unit="D")
        rows.append(pd.DataFrame({
            "origin_utc": [t_main] + list(t_main + lag),
            "latitude": np.concatenate([la, la + rng.normal(0, 0.03, k)]),
            "longitude": np.concatenate([lo, lo + rng.normal(0, 0.03, k)]),
            "ml": np.concatenate([[round(float(rng.uniform(4.5, 5.2)), 1)],
                                  np.minimum(2.1 + _grid(_geometric_levels(rng, k, 1.0, dm), dm), 4.0)])}))
    df = pd.concat(rows, ignore_index=True)
    df["origin_utc"] = pd.to_datetime(df["origin_utc"], utc=True)
    df = df[df["origin_utc"] < pd.Timestamp("2022-01-01", tz="UTC")]
    df = df.sort_values("origin_utc", kind="mergesort").reset_index(drop=True)
    df.insert(0, "event_id", [f"SYN{i:06d}" for i in range(1, len(df) + 1)])
    df.insert(2, "origin_kst", df["origin_utc"].dt.tz_convert(KST))
    df["depth_km"] = np.round(rng.uniform(2.0, 20.0, len(df)), 1)
    df["latitude"] = df["latitude"].round(4)
    df["longitude"] = df["longitude"].round(4)
    df["ml"] = df["ml"].round(1)
    df.attrs["source"] = "synthetic catalog (M05-T7 check); not real earthquakes"
    return df


def _t7_review(res: Any, cat: pd.DataFrame, years: Tuple[int, int], mc: float, dm: float, *,
               real: bool, crit: dict) -> Optional[Tuple[str, str]]:
    if not isinstance(res, dict) or any(k not in res for k in T7_KEYS):
        missing = [k for k in T7_KEYS if not isinstance(res, dict) or k not in res]
        return "keys", f"missing keys: {', '.join(missing)}"
    ids = _event_ids(res["events"])
    if ids is None:
        return "selection", "events must be a DataFrame with the catalog columns"
    ev = res["events"]
    if real and (mc < 2.1 - 1e-9 or float(ev["ml"].min()) < 2.1 - dm / 2):
        return "pile-up", "the events include magnitudes below ML 2.1"
    start = pd.Timestamp(f"{years[0]}-01-01", tz="UTC")
    stop = pd.Timestamp(f"{years[1] + 1}-01-01", tz="UTC")
    inside = (cat["origin_utc"] >= start) & (cat["origin_utc"] < stop) & (cat["ml"] >= mc - dm / 2)
    if ids != set(cat.loc[inside, "event_id"].astype(str)):
        return "selection", "the events are not exactly the catalog events of those UTC years at or above mc"
    flags = res["mainshock_flags"]
    try:
        flags = np.asarray(flags)
    except (TypeError, ValueError):
        return "flags", "mainshock_flags is not an array"
    if flags.shape != (len(ev),) or flags.dtype != bool:
        return "flags", "mainshock_flags must hold one True or False per row of events"
    oracle = _gk_flags(ev.reset_index(drop=True))
    if float(np.mean(flags == oracle)) < float(crit.get("flag_agreement", 0.995)):
        return "declustering", "the flags differ from Gardner-Knopoff windows on these events"
    mags = ev["ml"].to_numpy(dtype=float)
    for key, sub in (("b_all", mags), ("b_declustered", mags[flags])):
        value = _number(res[key])
        if value is None or not any(_close(value, ref(sub, mc, dm), 0.01) for ref in (_ss_utsu, _ss_classic)):
            return "b-consistency", f"{key} does not match its events at mc"
    problem = _figure_problem(res["figure"], min_axes=1, min_series=2)
    if problem:
        return "figure", problem
    return None


def check_T7(target: Any, ctx: Any) -> Outcome:
    import matplotlib.pyplot as plt
    from ..data import kma_catalog

    crit = ctx.criteria
    mc_real = float(ctx.get("mc", (crit.get("defaults") or {}).get("mc", 2.1)))
    years_real = tuple(int(y) for y in crit.get("years", [2018, 2026]))
    syn = _synthetic_national(ctx.rng)
    before = set(plt.get_fignums())
    try:
        res, err = _call(target, syn.copy(), (2020, 2021), 2.1, 0.1)
        if err is not None:
            raise err
        found = _t7_review(res, syn, (2020, 2021), 2.1, 0.1, real=False, crit=crit)
        if found:
            return Outcome(False, 1, 1, found[0], details={"example": {
                "inputs": f"a made-up catalog of {len(syn)} events with years=(2020, 2021), mc=2.1, dm=0.1",
                "got": found[1]}})
        cat = kma_catalog()
        res, err = _call(target, cat.copy(), years_real, mc_real, 0.1)
        if err is not None:
            raise err
        found = _t7_review(res, cat, years_real, mc_real, 0.1, real=True, crit=crit)
        if found:
            return Outcome(False, 2, 1, found[0], details={"real_data": True, "example": {
                "inputs": f"the shipped KMA catalog with years={years_real}, mc={mc_real:g}, dm=0.1",
                "got": found[1]}})
    finally:
        _close_new_figures(before)
    return Outcome(True, 2, 0, details={"note": "Your mentor reads your figure and your explanation."})
