"""Checkers for M20 · Picking arrivals: STA/LTA triggers, onset times and picks by hand.

Where the truth comes from (DESIGN.md section 1, rule 1):

* M20-T1: an independent library. ObsPy's ``classic_sta_lta`` on the float64 values of made-up records; where the
  long window holds only zeros the ratio is 0 by construction. The usual slips are recognized from ObsPy's own
  results run on changed inputs (absolute values, other window lengths, the reciprocal, the factor nsta / nlta) and
  from a property: on a noise-free step a ratio that looks only backward stays exactly 1 before the step.
* M20-T2: an independent library, ObsPy's ``trigger_onset``, on made-up curves; the slips from ``trigger_onset``
  with changed thresholds.
* M20-T3: construction (noise that changes size at a known sample) and ObsPy's ``aic_simple``.
* M20-T4: construction (``synth_onsets``: one arrival at a known sample) and the same five steps of the Contract
  done with ObsPy's own functions (``classic_sta_lta``, ``trigger_onset``, ``aic_simple``), which the student's
  function may not use.
* M20-T5: the student's own products: the picks file and the student's SAC files. The check tests format,
  stations, distances (KMA epicenter and the station coordinates in the SAC headers), that the record changes at
  each pick, and that the S-P times fit one source (a straight line of S-P against P time). There is no hidden
  reference pick, and no value is printed.
* M20-T6: the student's own products: the JSON file, the picks file and the student's auto_pick, which must pass
  made-up cases of task 4 again first. The check reruns that picker on the student's records and recomputes the
  errors and the statistics from the student's own numbers; it never prints them.

Failure categories are keys of ``checks/specs/M20.yaml``; the engine prints their fixed messages.
"""
from __future__ import annotations

import csv
import json
import math
import numbers
import os
import re
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import Outcome, outcome_from_cases

__all__ = ["check_T1", "check_T2", "check_T3", "check_T4", "check_T5", "check_T6"]

DATASET_DEFAULT = "sangju2019"
MAIN_EVENT = "2019009762"                 # the ML 3.9 Sangju earthquake of 21 July 2019 (KMA catalog)
T4_RULES = ("obspy.signal.trigger", "sgtl_tutorial")      # the forbidden list of M20-T4 (checks/specs/M20.yaml)


# ------------------------------------------------------------------------------------------- helpers
def _call(func: Any, *args: Any, **kwargs: Any) -> Tuple[Any, Optional[BaseException]]:
    """Run the student's code. NotImplementedError passes through (the engine reports NOT STARTED)."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            return func(*args, **kwargs), None
    except NotImplementedError:
        raise
    except Exception as exc:  # noqa: BLE001 - classified by the caller
        return None, exc


def _first(categories: Sequence[Optional[str]], priority: Sequence[str]) -> Optional[str]:
    found = {c for c in categories if c}
    return next((c for c in priority if c in found), "wrong-values" if found else None)


def _consensus(matches: Sequence[Sequence[str]], priority: Sequence[str]) -> Optional[str]:
    """The category of the failing cases: the slip that explains the most failing cases (on a tie, the first by
    priority). A slip that explains every failing case therefore wins over one that fits a few by chance.

    ``matches`` holds, per case, the categories that fit it, and an empty list for a passed case."""
    failing = [set(m) for m in matches if m]
    if not failing:
        return None
    rank = {c: i for i, c in enumerate(priority)}
    counts = {c: sum(c in m for m in failing) for c in set().union(*failing)}
    return min(counts, key=lambda c: (-counts[c], rank.get(c, len(rank))))


def _event(event_id: str) -> Optional[dict]:
    """KMA values of one event from the shipped catalog (origin as UTCDateTime), or None."""
    from obspy import UTCDateTime

    from .. import data as _data

    cat = _data.kma_catalog()
    rows = cat.loc[cat["event_id"] == str(event_id)]
    if rows.empty:
        return None
    row = rows.iloc[0]
    return {"origin": UTCDateTime(row["origin_utc"].isoformat()), "lat": float(row["latitude"]),
            "lon": float(row["longitude"]), "depth": float(row["depth_km"]), "ml": float(row["ml"])}


def _event_folder(ctx: Any, event: dict) -> Path:
    name = str(ctx.get("dataset") or DATASET_DEFAULT)
    return Path(ctx.data_root) / name / "stp_download" / "SAC" / event["origin"].strftime("%Y%m%d%H%M%S")


def _epicentral_km(event: dict, lat: float, lon: float) -> float:
    from obspy.geodetics import gps2dist_azimuth

    return gps2dist_azimuth(event["lat"], event["lon"], float(lat), float(lon))[0] / 1000.0


def _real(category: Optional[str], passed: int, total: int, note: str, station: Optional[str] = None) -> Outcome:
    """Outcome of a real-data check: never a value, at most the station concerned."""
    ok = [True] * total if category is None else [True] * passed + [False]
    example = {"inputs": {"station": station}} if (station and category) else None
    return outcome_from_cases(ok, category=category, example=example, real_data=True, note=note)


# ----------------------------------------------------------------------------------- M20-T1 STA/LTA
# (kind, samples, nsta, nlta)
T1_CASES = (
    ("step", 6000, 50, 1000),
    ("arrival", 6000, 50, 1000),
    ("list", 200, 3, 20),
    ("zeros-first", 4000, 20, 300),
    ("int32", 20000, 100, 2000),
    ("float32", 15000, 50, 500),
    ("clean-step", 6000, 40, 400),
    ("tiny", 50, 1, 5),
    ("full", 400, 10, 400),
    ("offset", 5000, 25, 600),
)
T1_PRIORITY = ("format", "zero-lta", "warm-up", "swapped", "normalization", "characteristic-function",
               "window-position", "window-length", "precision", "wrong-values")


def _t1_case(rng: np.random.Generator, kind: str, n: int) -> Tuple[Any, np.ndarray, dict]:
    """(what the student gets, its float64 values, facts about it)."""
    from .. import synth_onsets

    facts: Dict[str, Any] = {"kind": kind}
    if kind == "step":
        x = rng.normal(0.0, rng.uniform(0.5, 50.0), n)
        at = int(rng.integers(n // 3, 2 * n // 3))
        x[at:] *= rng.uniform(3.0, 8.0)
        facts["text"] = f"noise that grows at sample {at}"
        return x, x.copy(), facts
    if kind == "arrival":
        tr, truth = synth_onsets.onset_trace(rng, duration_s=n / 100.0, snr=float(rng.uniform(5.0, 30.0)))
        facts["text"] = f"a made-up arrival at sample {truth['onset_index']}"
        return tr.data.copy(), tr.data.astype(np.float64), facts
    if kind == "list":
        x = np.round(rng.normal(0.0, 2.0, n), 3)
        x[n // 2:] *= 4.0
        facts["text"] = "a Python list of floats"
        return [float(v) for v in x], x.copy(), facts
    if kind == "zeros-first":
        zeros = int(rng.integers(400, 900))
        x = np.zeros(n)
        x[zeros:] = rng.normal(0.0, 1000.0, n - zeros)
        facts.update(text=f"zeros up to sample {zeros}, then noise", zeros=zeros)
        return x, x.copy(), facts
    if kind == "int32":
        x = rng.normal(0.0, 1.0e5, n)
        x[n // 2:] *= 5.0
        counts = np.round(x).astype(np.int32)
        facts.update(text="int32 counts of about 100,000 with a jump at the middle", bits32=True)
        return counts, counts.astype(np.float64), facts
    if kind == "float32":
        loud = n // 3
        x = np.concatenate([rng.normal(0.0, 1.0e6, loud), rng.normal(0.0, 1.0e2, n - loud)]).astype(np.float32)
        facts.update(text=f"float32 samples, loud (1e6) up to sample {loud}, then quiet (1e2)", bits32=True)
        return x, x.astype(np.float64), facts
    if kind == "clean-step":
        at = int(rng.integers(n // 3, 2 * n // 3))
        x = np.where(np.arange(n) < at, 1.0, 3.0)
        facts.update(text=f"1.0 up to sample {at}, then 3.0 (no noise)", step=at)
        return x, x.copy(), facts
    if kind == "offset":
        x = 1.0e4 + rng.normal(0.0, 10.0, n)
        facts["text"] = "noise of size 10 around an offset of 10,000"
        return x, x.copy(), facts
    x = rng.normal(0.0, 1.0, n)                      # tiny, full
    facts["text"] = f"{n} samples of noise"
    return x, x.copy(), facts


def _t1_oracle(values: np.ndarray, nsta: int, nlta: int) -> np.ndarray:
    """ObsPy's classic_sta_lta, with 0 where the long window holds only zeros (ObsPy gives NaN there)."""
    from obspy.signal.trigger import classic_sta_lta

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        out = np.asarray(classic_sta_lta(np.ascontiguousarray(values, dtype=np.float64), nsta, nlta), dtype=float)
    nonzero = np.flatnonzero(values != 0.0)
    first = int(nonzero[0]) if nonzero.size else values.size
    out[:first] = 0.0                               # every window that ends before the first nonzero sample
    out[~np.isfinite(out)] = 0.0
    return out


def _close(got: np.ndarray, expected: np.ndarray, rel: float, absolute: float) -> bool:
    return bool(np.all(np.abs(got - expected) <= np.maximum(absolute, rel * np.abs(expected))))


def _t1_judge(got: Any, values: np.ndarray, facts: dict, nsta: int, nlta: int, rel: float,
              absolute: float) -> Tuple[Optional[str], Optional[int]]:
    """(category or None, a sample where it goes wrong)."""
    n = values.size
    try:
        arr = np.asarray(got, dtype=float)
    except (TypeError, ValueError):
        return "format", None
    if arr.ndim != 1 or arr.size != n:
        return "format", None
    expected = _t1_oracle(values, nsta, nlta)
    if not np.all(np.isfinite(arr)):
        return ("zero-lta" if facts["kind"] == "zeros-first" else "format"), int(np.flatnonzero(~np.isfinite(arr))[0])
    if _close(arr, expected, rel, absolute):
        return None, None
    bad = int(np.flatnonzero(np.abs(arr - expected) > np.maximum(absolute, rel * np.abs(expected)))[0])
    defined = np.arange(n) >= nlta - 1
    if np.any(np.abs(arr[:nlta - 1]) > absolute) or (nlta < n and expected[nlta - 1] != 0.0
                                                    and abs(arr[nlta - 1]) <= absolute
                                                    and _close(arr[nlta:], expected[nlta:], rel, absolute)):
        return "warm-up", bad
    live = defined & (expected > 0) & (arr > 0)
    if live.sum() > 5 and _close(arr[live], 1.0 / expected[live], rel, absolute):
        return "swapped", bad
    if _close(arr, expected * nsta / nlta, rel, absolute):
        return "normalization", bad
    if _close(arr, _t1_oracle(np.sqrt(np.abs(values)), nsta, nlta), rel, absolute):
        return "characteristic-function", bad
    if facts["kind"] == "clean-step":
        before = (np.arange(n) >= nlta) & (np.arange(n) < facts["step"])
        if np.any(np.abs(arr[before] - 1.0) > 1e-6):
            return "window-position", bad
    for dsta, dlta in ((1, 1), (-1, -1), (1, 0), (0, 1), (-1, 0), (0, -1)):
        s, lw = nsta + dsta, nlta + dlta
        if 1 <= s < lw <= n and _close(arr, _t1_oracle(values, s, lw), rel, absolute):
            return "window-length", bad
    if facts.get("bits32") or _close(arr, expected, 1e-2, absolute):
        return "precision", bad                      # a 32-bit record, or digits lost on large values
    return "wrong-values", bad


def check_T1(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    rel, absolute = float(crit.get("rel_tol", 1e-4)), float(crit.get("abs_tol", 1e-6))
    trials = max(4, min(len(T1_CASES), int(crit.get("trials", len(T1_CASES)))))
    rng = ctx.rng
    cats: List[Optional[str]] = []
    ok: List[bool] = []
    example = None
    for kind, n, nsta, nlta in T1_CASES[:trials]:
        given, values, facts = _t1_case(rng, kind, n)
        got, err = _call(target, given, nsta, nlta)
        if err is not None:
            raise err
        cat, where = _t1_judge(got, values, facts, nsta, nlta, rel, absolute)
        cats.append(cat)
        ok.append(cat is None)
        if cat is not None and example is None:
            example = {"inputs": {"data": facts["text"], "nsta": nsta, "nlta": nlta}}
            if where is not None:
                mine = np.asarray(got, dtype=float)
                example["got"] = f"ratio[{where}] = {mine[where]:.6g}"
                example["error"] = f"ObsPy's classic_sta_lta gives {_t1_oracle(values, nsta, nlta)[where]:.6g} there"
    # the order of the cases puts the 32-bit records after plain ones: a precision slip shows only there
    category = _first(cats, T1_PRIORITY)
    if category == "precision" and any(c not in (None, "precision") for c in cats):
        category = _first([c for c in cats if c != "precision"], T1_PRIORITY)
    return outcome_from_cases(ok, category=category, example=example)


# --------------------------------------------------------------------------------- M20-T2 triggers
T2_PRIORITY = ("format", "equality", "off-index", "hysteresis", "open-end", "wrong-values")
_EPS = 1e-9


def _t2_oracle(cft: np.ndarray, thr_on: float, thr_off: float) -> List[Tuple[int, int]]:
    from obspy.signal.trigger import trigger_onset

    return [(int(a), int(b)) for a, b in trigger_onset(np.asarray(cft, dtype=float), thr_on, thr_off)]


def _t2_case(rng: np.random.Generator, number: int) -> Tuple[Any, float, float]:
    """A made-up curve and two thresholds; whole-number curves make values equal to the thresholds."""
    kind = number % 6
    n = int(rng.integers(6, 60))
    if kind in (0, 1, 2):
        cft = rng.integers(0, 9, n).astype(float)
        thr_on = float(rng.integers(3, 8))
        thr_off = float(rng.integers(0, int(thr_on)))
    elif kind == 3:
        cft = np.abs(rng.normal(0.0, 3.0, n))
        thr_on, thr_off = float(rng.uniform(2.0, 5.0)), float(rng.uniform(0.5, 1.9))
    elif kind == 4:                                   # ends while a trigger is on
        cft = rng.integers(0, 9, n).astype(float)
        thr_on, thr_off = 5.0, 2.0
        cft[-3:] = [6.0, 7.0, 8.0]
    else:                                             # never triggers, or only at the very start
        cft = rng.uniform(0.0, 2.0, n)
        thr_on, thr_off = 3.0, 1.0
        if rng.random() < 0.5:
            cft[0] = 4.0
    as_list = number % 4 == 1
    return ([float(v) for v in cft] if as_list else cft), thr_on, thr_off


def _t2_pairs(got: Any) -> Optional[List[Tuple[int, int]]]:
    try:
        pairs = []
        for pair in got:
            if len(pair) != 2:
                return None
            a, b = pair
            if isinstance(a, bool) or isinstance(b, bool) or not all(
                    isinstance(v, (numbers.Integral, np.integer)) or (isinstance(v, float) and v.is_integer())
                    for v in (a, b)):
                return None
            pairs.append((int(a), int(b)))
        return pairs
    except TypeError:
        return None


def _t2_judge(got: Any, cft: np.ndarray, thr_on: float, thr_off: float) -> List[str]:
    """The categories that fit this case (best first); [] when it passed."""
    pairs = _t2_pairs(got)
    if pairs is None:
        return ["format"]
    expected = _t2_oracle(cft, thr_on, thr_off)
    if pairs == expected:
        return []
    if pairs != sorted(pairs):
        return ["format"]
    fits = []
    if any(pairs == _t2_oracle(cft, thr_on - on_eps, thr_off - off_eps)
           for on_eps, off_eps in ((_EPS, 0.0), (0.0, _EPS), (_EPS, _EPS))):
        fits.append("equality")
    last = cft.size - 1
    if len(pairs) == len(expected) and all(a == c and (b == d + 1 or (d == last and b in (last, last + 1)))
                                           for (a, b), (c, d) in zip(pairs, expected)):
        fits.append("off-index")
    if pairs in (_t2_oracle(cft, thr_on, thr_on), _t2_oracle(cft, thr_off, thr_off)):
        fits.append("hysteresis")
    if expected and expected[-1][1] == last and pairs == expected[:-1]:
        fits.append("open-end")
    return fits or ["wrong-values"]


def check_T2(target: Any, ctx: Any) -> Outcome:
    trials = max(30, int(ctx.criteria.get("trials", 300)))
    rng = ctx.rng
    fixed = [([0, 5, 5, 2, 1, 0, 5, 0], 4.0, 1.5), ([0, 5, 3, 5, 1, 5], 4.0, 1.5), ([1, 2, 1], 3.0, 1.0)]
    cases = fixed + [_t2_case(rng, i) for i in range(trials)]
    cats: List[List[str]] = []
    example = None
    for cft, thr_on, thr_off in cases:
        values = np.asarray(cft, dtype=float)
        given = list(cft) if isinstance(cft, list) else values.copy()
        got, err = _call(target, given, thr_on, thr_off)
        if err is not None:
            raise err
        cat = _t2_judge(got, values, thr_on, thr_off)
        cats.append(cat)
        if cat and example is None:
            shown = [float(v) if not float(v).is_integer() else int(v) for v in np.round(values, 3)]
            example = {"inputs": {"cft": shown, "thr_on": thr_on, "thr_off": thr_off}, "got": got,
                       "error": f"ObsPy's trigger_onset gives {_t2_oracle(values, thr_on, thr_off)}"}
    return outcome_from_cases([not c for c in cats], category=_consensus(cats, T2_PRIORITY), example=example)


# ------------------------------------------------------------------------------------ M20-T3 AIC onset
T3_PRIORITY = ("format", "edge", "maximum", "weights", "wrong-values")
T3_EXAMPLE = [1.0, -1.0, 1.0, -1.0, 1.0, 6.0, -6.0, 6.0, -6.0, 6.0]


def _t3_oracle(values: np.ndarray, pick: str = "min") -> int:
    """The k of the Contract from ObsPy's aic_simple (its index j belongs to k = j + 1; k runs 2 .. N - 2)."""
    from obspy.signal.trigger import aic_simple

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        scores = np.asarray(aic_simple(np.ascontiguousarray(values, dtype=np.float64)), dtype=float)
    inner = scores[1:values.size - 2]
    position = int(np.nanargmin(inner)) if pick == "min" else int(np.nanargmax(inner))
    return position + 2


def _t3_case(rng: np.random.Generator, number: int) -> Tuple[np.ndarray, int]:
    from .. import synth_onsets

    n = int(rng.integers(30, 500))
    index = int(rng.integers(max(8, n // 5), n - max(8, n // 5)))
    factor = float(rng.uniform(2.0, 30.0))
    if number % 5 == 3:
        factor = 1.0 / factor                       # the record gets quieter
    offset = float(rng.uniform(-50.0, 50.0)) if number % 4 == 2 else 0.0
    data, index = synth_onsets.variance_step(rng, n, index, factor, offset)
    if number % 7 == 5:                             # two nearly equal first samples: a tiny first variance at k = 2
        data[1] = data[0] + 1e-6 * rng.normal()
    return data, index


def _t3_judge(got: Any, values: np.ndarray, tol: int) -> List[str]:
    """The categories that fit this case (best first); [] when it passed."""
    n = values.size
    if isinstance(got, bool) or not isinstance(got, (numbers.Integral, np.integer)):
        return ["format"]
    k = int(got)
    if k <= 1:
        return ["edge"]
    if k > n - 2:
        return ["format"]
    expected = _t3_oracle(values)
    if abs(k - expected) <= tol:
        return []
    fits = []
    if k == _t3_oracle(values, "max"):
        fits.append("maximum")
    if min(k - 2, n - 2 - k) <= 3 and min(expected - 2, n - 2 - expected) >= 10:
        fits.append("weights")                     # unweighted logarithms favour a tiny part at either end
    return fits or ["wrong-values"]


def check_T3(target: Any, ctx: Any) -> Outcome:
    trials = max(10, int(ctx.criteria.get("trials", 40)))
    tol = int(ctx.criteria.get("tol_samples", 1))
    rng = ctx.rng
    cases = [(np.array(T3_EXAMPLE), 5)] + [_t3_case(rng, i) for i in range(trials)]
    cats: List[List[str]] = []
    example = None
    for values, index in cases:
        got, err = _call(target, values.copy())
        if err is not None:
            raise err
        cat = _t3_judge(got, values, tol)
        cats.append(cat)
        if cat and example is None:
            example = {"inputs": {"samples": int(values.size), "change at sample": int(index)},
                       "got": got, "error": f"ObsPy's aic_simple gives k = {_t3_oracle(values)}"}
    return outcome_from_cases([not c for c in cats], category=_consensus(cats, T3_PRIORITY), example=example)


# ---------------------------------------------------------------------------- M20-T4 automatic picker
# (rate, snr, rise_s, zerophase, fmin, fmax, sta_s, lta_s, thr_on, thr_off, pre_s, post_s); snr 0 = no arrival
T4_SPECS = (
    (100.0, 60.0, 0.0, True, 1.0, 10.0, 0.5, 10.0, 4.0, 1.5, 2.0, 0.5),
    (100.0, 60.0, 0.0, False, 1.0, 10.0, 0.5, 10.0, 4.0, 1.5, 2.0, 0.5),
    (200.0, 30.0, 0.0, True, 2.0, 15.0, 0.2, 5.0, 3.0, 1.0, 1.0, 0.5),
    (50.0, 25.0, 0.3, False, 1.0, 10.0, 1.0, 10.0, 3.0, 1.5, 2.0, 1.0),
    (100.0, 100.0, 0.0, True, 0.5, 8.0, 0.3, 8.0, 5.0, 2.0, 1.5, 0.5),
    (100.0, 0.0, 0.0, False, 1.0, 10.0, 0.5, 10.0, 25.0, 1.5, 2.0, 0.5),
    (200.0, 80.0, 0.0, False, 2.0, 20.0, 0.2, 10.0, 4.0, 1.5, 2.0, 0.5),
    (100.0, 12.0, 0.3, True, 1.0, 10.0, 0.5, 10.0, 3.0, 1.5, 2.0, 0.5),
    (50.0, 40.0, 0.0, True, 1.0, 10.0, 0.4, 6.0, 4.0, 1.0, 1.0, 0.4),
    (100.0, 8.0, 0.0, False, 1.0, 10.0, 0.5, 10.0, 3.0, 1.5, 2.0, 0.5),
    (100.0, 0.0, 0.0, True, 1.0, 10.0, 0.5, 10.0, 25.0, 1.5, 2.0, 0.5),
    (200.0, 50.0, 0.0, True, 1.0, 20.0, 0.25, 10.0, 4.0, 1.5, 2.0, 0.5),
)
T4_PRIORITY = ("format", "changed-input", "no-trigger", "filter-type", "no-filter", "trigger-only", "aic-window",
               "time", "wrong-values")


def _t4_case(rng: np.random.Generator, spec: tuple) -> Tuple[Any, dict]:
    from .. import synth_onsets

    rate, snr = spec[0], spec[1]
    trace, truth = synth_onsets.onset_trace(rng, rate=rate, duration_s=60.0, snr=max(snr, 0.0), rise_s=spec[2],
                                            onset_s=float(rng.uniform(25.0, 35.0)))
    return trace, truth


def _t4_chain(tr: Any, spec: tuple, *, zerophase: Optional[bool] = None, band: bool = True,
              aic: str = "window") -> Dict[str, Any]:
    """The five steps of the Contract with ObsPy's own functions: trigger-on sample, AIC window and onset."""
    from obspy.signal.trigger import aic_simple, classic_sta_lta, trigger_onset

    rate, zp = spec[0], spec[3] if zerophase is None else zerophase
    fmin, fmax, sta_s, lta_s, thr_on, thr_off, pre_s, post_s = spec[4:]
    ready = tr.copy().detrend(type="demean").taper(0.05, "hann")
    if band:
        ready.filter(type="bandpass", corners=4, zerophase=zp, freqmax=fmax, freqmin=fmin)
    samples = np.asarray(ready.data, dtype=np.float64)
    last = samples.size - 1
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        ratio = np.nan_to_num(classic_sta_lta(samples, int(round(rate * sta_s)), int(round(rate * lta_s))))
        found = trigger_onset(ratio, thr_on, thr_off)
        if len(found) == 0:
            return {"pick": None}
        on = int(found[0][0])
        back, ahead = int(round(rate * pre_s)), int(round(rate * post_s))
        a, b = {"whole": (0, last), "before": (max(on - back, 0), on)}.get(aic, (max(on - back, 0),
                                                                                min(on + ahead, last)))
        part = np.ascontiguousarray(samples[a:b + 1])
        scores = np.asarray(aic_simple(part), dtype=float)[1:part.size - 2]
        k = a + int(np.nanargmin(scores)) + 2
    start = tr.stats.starttime
    return {"pick": start + k / rate, "on": start + on / rate, "a": a, "k": k, "start": start}


def _same_trace(a: Any, b: Any) -> bool:
    return (a.stats.npts == b.stats.npts and a.stats.starttime == b.stats.starttime
            and a.stats.sampling_rate == b.stats.sampling_rate and np.array_equal(a.data, b.data))


def _t4_judge(got: Any, tr: Any, pristine: Any, spec: tuple, tol_s: float) -> List[str]:
    """The categories that fit this case (best first); [] when it passed."""
    from obspy import UTCDateTime

    if got is not None and not isinstance(got, UTCDateTime):
        return ["format"]
    if not _same_trace(tr, pristine):
        return ["changed-input"]
    expected = _t4_chain(pristine, spec)
    if expected["pick"] is None or got is None:
        if expected["pick"] is None and got is None:
            return []
        return ["no-trigger"] if expected["pick"] is None else ["wrong-values"]

    def near(moment: Any) -> bool:
        return moment is not None and abs(got - moment) <= tol_s

    if near(expected["pick"]):
        return []
    fits = []
    if near(_t4_chain(pristine, spec, zerophase=not spec[3])["pick"]):
        fits.append("filter-type")
    if near(_t4_chain(pristine, spec, band=False)["pick"]):
        fits.append("no-filter")
    if near(expected["on"]):
        fits.append("trigger-only")
    rate = spec[0]
    if any(near(_t4_chain(pristine, spec, aic=kind)["pick"]) for kind in ("whole", "before")) or \
            near(expected["start"] + (expected["k"] - expected["a"]) / rate):
        fits.append("aic-window")
    start, k = expected["start"], expected["k"]
    if near(start + k) or near(start + k * rate) or abs(got - expected["pick"]) >= 30.0:
        fits.append("time")
    return fits or ["wrong-values"]


def check_T4(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    trials = max(6, min(len(T4_SPECS), int(crit.get("trials", len(T4_SPECS)))))
    tol = int(crit.get("tol_samples", 2))
    rng = ctx.rng
    cats: List[List[str]] = []
    example = None
    for spec in T4_SPECS[:trials]:
        tr, truth = _t4_case(rng, spec)
        pristine = tr.copy()
        got, err = _call(target, tr, spec[4], spec[5], spec[3], *spec[6:])
        if err is not None:
            raise err
        cat = _t4_judge(got, tr, pristine, spec, (tol + 0.01) / spec[0])
        cats.append(cat)
        if cat and example is None:
            from obspy import UTCDateTime

            expected = _t4_chain(pristine, spec)["pick"]
            if expected is None:
                error = "ObsPy's steps give no pick (None)"
            elif isinstance(got, UTCDateTime):
                error = f"ObsPy's steps give {expected}, {(got - expected) * spec[0]:+.0f} samples from yours"
            else:
                error = f"ObsPy's steps give {expected}"
            example = {"inputs": {"sampling rate": spec[0], "signal-to-noise": spec[1] or "no arrival",
                                  "rise_s": spec[2], "fmin": spec[4], "fmax": spec[5], "zerophase": spec[3],
                                  "sta_s": spec[6], "lta_s": spec[7], "thr_on": spec[8], "thr_off": spec[9],
                                  "pre_s": spec[10], "post_s": spec[11], "true onset": str(truth["onset"])},
                       "got": str(got) if got is not None else None, "error": error}
    return outcome_from_cases([not c for c in cats], category=_consensus(cats, T4_PRIORITY), example=example)


# ------------------------------------------------------------------------------ M20-T5 manual picks
T5_COLUMNS = ("station", "phase", "channel", "time_utc", "uncertainty_s", "polarity")
T5_STATION = re.compile(r"^[A-Z0-9]{1,2}\.[A-Z0-9]{2,5}$")
T5_CHANNEL = re.compile(r"^[A-Z0-9]{2}[A-Z0-9]$")
T5_NOTE = ("The check read your picks file and your SAC files; it compares your picks with each other and with "
           "the records, never with hidden answers, and prints no values.")


def _t5_read(path: Path) -> Tuple[Optional[str], Optional[List[dict]]]:
    """(category, rows): the rows of the picks file with times as UTCDateTime."""
    from obspy import UTCDateTime

    try:
        with open(path, newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or not set(T5_COLUMNS) <= {f.strip() for f in reader.fieldnames}:
                return "format", None
            raw = [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader]
    except (OSError, UnicodeDecodeError, csv.Error):
        return "no-file", None
    rows = []
    for row in raw:
        try:
            if not T5_STATION.match(row["station"]) or row["phase"] not in ("P", "S") or \
                    not T5_CHANNEL.match(row["channel"]) or "T" not in row["time_utc"]:
                return "format", None
            unc = float(row["uncertainty_s"])
            if not math.isfinite(unc):
                return "format", None
            rows.append({"station": row["station"], "phase": row["phase"], "channel": row["channel"],
                         "time": UTCDateTime(row["time_utc"]), "unc": unc, "polarity": row["polarity"]})
        except (ValueError, TypeError, KeyError):
            return "format", None
    return None, rows


def _t5_jump(tr: Any, at: Any, before: Tuple[float, float], after: float) -> float:
    """RMS in the second after a moment over the RMS of a stretch before it, on a causal 1 Hz high-pass."""
    work = tr.copy()
    work.detrend("demean")
    work.taper(max_percentage=0.02, type="hann")
    work.filter("highpass", freq=1.0, corners=2, zerophase=False)
    t = work.times(reftime=at)
    late = work.data[(t >= 0.0) & (t <= after)]
    early = work.data[(t >= -before[0]) & (t <= -before[1])]
    if late.size < 5 or early.size < 5:
        return 0.0
    noise = float(np.sqrt(np.mean(early.astype(float) ** 2)))
    return float(np.sqrt(np.mean(late.astype(float) ** 2))) / noise if noise > 0 else float("inf")


def check_T5(target: Any, ctx: Any) -> Outcome:
    from obspy import read

    crit = dict(ctx.criteria)
    total = 11
    if not isinstance(target, (str, os.PathLike)) or not Path(target).expanduser().is_file():
        return _real("no-file", 0, total, T5_NOTE)
    category, rows = _t5_read(Path(target).expanduser())
    if category is not None:
        return _real(category, 0, total, T5_NOTE)
    passed = 1
    by_station: Dict[str, Dict[str, List[dict]]] = {}
    for row in rows:
        by_station.setdefault(row["station"], {"P": [], "S": []})[row["phase"]].append(row)
    if any(len(p["P"]) > 1 or len(p["S"]) > 1 for p in by_station.values()):
        return _real("too-few", passed, total, T5_NOTE)
    complete = {s: (p["P"][0], p["S"][0]) for s, p in by_station.items() if p["P"] and p["S"]}
    if len(complete) < int(crit.get("min_stations", 6)):
        return _real("too-few", passed, total, T5_NOTE)
    passed += 1
    event = _event(MAIN_EVENT)
    folder = _event_folder(ctx, event) if event is not None else None
    if folder is None or not folder.is_dir():
        return _real("no-data", passed, total, T5_NOTE)
    records: Dict[Tuple[str, str], Any] = {}
    for station, pair in complete.items():
        for row in pair:
            channel = row["channel"]
            files = sorted((folder / channel[:2]).glob(f"*.{station}.{channel}.sac"))
            if not files:
                return _real("station", passed, total, T5_NOTE, station)
            try:
                records[(station, row["phase"])] = read(str(files[0]), format="SAC")[0]
            except Exception:  # noqa: BLE001 - an unreadable file counts as missing
                return _real("station", passed, total, T5_NOTE, station)
    passed += 1
    hypo: Dict[str, float] = {}
    for station in complete:
        sac = records[(station, "P")].stats.sac
        epi = _epicentral_km(event, sac.stla, sac.stlo)
        if epi > float(crit.get("max_epi_km", 100.0)) + 0.5:
            return _real("distance", passed, total, T5_NOTE, station)
        hypo[station] = float(np.hypot(epi, event["depth"]))
    passed += 1
    for station, (p, s) in complete.items():
        if not p["channel"].endswith("Z") or s["channel"][-1] not in "NE12":
            return _real("component", passed, total, T5_NOTE, station)
    passed += 1
    for station, (p, s) in complete.items():
        for row in (p, s):
            tr = records[(station, row["phase"])]
            if not (tr.stats.starttime <= row["time"] <= tr.stats.endtime) or row["time"] < event["origin"]:
                return _real("window", passed, total, T5_NOTE, station)
    passed += 1
    for station, (p, s) in complete.items():
        if not s["time"] > p["time"]:
            return _real("order", passed, total, T5_NOTE, station)
    passed += 1
    p_lo, p_hi = (float(v) for v in crit.get("p_unc_s", (0.005, 0.5)))
    s_lo, s_hi = (float(v) for v in crit.get("s_unc_s", (0.01, 1.0)))
    for station, (p, s) in complete.items():
        if not (p_lo <= p["unc"] <= p_hi and s_lo <= s["unc"] <= s_hi):
            return _real("uncertainty", passed, total, T5_NOTE, station)
    passed += 1
    clear = 0
    for station, (p, s) in complete.items():
        if p["polarity"] not in ("U", "D", "?") or s["polarity"] not in ("?", ""):
            return _real("polarity", passed, total, T5_NOTE, station)
        clear += p["polarity"] in ("U", "D")
    if clear < int(crit.get("min_polarities", 3)):
        return _real("polarity", passed, total, T5_NOTE)
    passed += 1
    p_jump, s_jump = float(crit.get("p_jump", 3.0)), float(crit.get("s_jump", 1.5))
    for station, (p, s) in complete.items():
        if _t5_jump(records[(station, "P")], p["time"], (5.5, 0.5), 1.0) < p_jump or \
                _t5_jump(records[(station, "S")], s["time"], (2.0, 0.5), 1.0) < s_jump:
            return _real("no-onset", passed, total, T5_NOTE, station)
    passed += 1
    origin = event["origin"]
    names = sorted(complete)
    p_after = np.array([complete[s][0]["time"] - origin for s in names])
    s_minus_p = np.array([complete[s][1]["time"] - complete[s][0]["time"] for s in names])
    slope, intercept = np.polyfit(p_after, s_minus_p, 1)
    residual = s_minus_p - (slope * p_after + intercept)
    lo, hi = (float(v) for v in crit.get("wadati_slope", (0.45, 1.1)))
    per_km_lo, per_km_hi = (float(v) for v in crit.get("sp_per_km", (0.07, 0.17)))
    per_km = s_minus_p / np.array([hypo[s] for s in names])
    consistent = (lo <= slope <= hi and float(np.sqrt(np.mean(residual ** 2))) <= float(crit.get("wadati_rms_s", 0.3))
                  and float(np.max(np.abs(residual))) <= float(crit.get("wadati_max_s", 0.6))
                  and abs(-intercept / slope) <= float(crit.get("origin_tol_s", 3.0))
                  and bool(np.all((per_km >= per_km_lo) & (per_km <= per_km_hi))))
    if not consistent:
        return _real("one-source", passed, total, T5_NOTE)
    return _real(None, total, total, T5_NOTE + f" Stations checked: {len(complete)}.")


# ----------------------------------------------------------------------- M20-T6 picker against picks
T6_KEYS = ("picks_csv", "band_hz", "window_s", "aic_s", "grid", "chosen", "rows")
T6_SETTING = ("sta_s", "lta_s", "thr_on", "thr_off")
T6_STATS = ("n_picked", "median_error_s", "median_abs_error_s", "max_abs_error_s")
T6_MEDIANS = T6_STATS[1:]
T6_CASES = (1, 2, 5)                       # the T4 cases the picker must pass again (one of them without arrival)
T4_TOL = 2                                 # tol_samples of M20-T4 (criteria/M20.yaml)
T6_NOTE = ("The check reran your own auto_pick on your records and recomputed your numbers; it prints none of "
           "them.")


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, numbers.Real) or not math.isfinite(float(value)):
        return None
    return float(value)


def _t6_setting(entry: Any) -> Optional[Tuple[float, ...]]:
    if not isinstance(entry, dict) or not all(k in entry for k in T6_SETTING + T6_STATS):
        return None
    values = tuple(_number(entry[k]) for k in T6_SETTING)
    if any(v is None for v in values) or not 0 < values[0] < values[1] or not 0 < values[3] < values[2]:
        return None
    if _number(entry["n_picked"]) is None or float(entry["n_picked"]) != int(entry["n_picked"]):
        return None
    for key in T6_MEDIANS:
        if entry[key] is not None and _number(entry[key]) is None:
            return None
    return values


def _t6_stats(errors: Sequence[Optional[float]]) -> Tuple[int, ...]:
    """(n_picked, median error, median absolute error, largest absolute error) of the picked stations."""
    kept = np.array([e for e in errors if e is not None], dtype=float)
    if kept.size == 0:
        return 0, None, None, None
    return int(kept.size), float(np.median(kept)), float(np.median(np.abs(kept))), float(np.max(np.abs(kept)))


def _t6_matches(entry: dict, stats: Tuple[Any, ...], tol: float) -> bool:
    """True when a grid entry holds these statistics (count exactly, times within tol)."""
    return int(entry["n_picked"]) == stats[0] and all(_t6_same(_number(entry[key]), value, tol)
                                                      for key, value in zip(T6_MEDIANS, stats[1:]))


def _t6_same(a: Optional[float], b: Optional[float], tol: float) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) <= tol


def _t6_own_picker(picker: Any, rng: np.random.Generator, cases: int) -> bool:
    """True when the student's auto_pick passes made-up cases of task 4 again under the library rule of task 4."""
    from .. import astguard

    if not callable(picker) or not astguard.check_function(picker, T4_RULES).ok:
        return False
    for number in T6_CASES[:max(1, cases)]:
        spec = T4_SPECS[number]
        tr, _truth = _t4_case(rng, spec)
        pristine = tr.copy()
        got, err = _call(picker, tr, spec[4], spec[5], spec[3], *spec[6:])
        if err is not None:
            raise err
        if _t4_judge(got, tr, pristine, spec, (T4_TOL + 0.01) / spec[0]):
            return False
    return True


def _t6_fail(category: str, passed: int, total: int, station: Optional[str] = None) -> Outcome:
    return _real(category, passed, total, T6_NOTE, station)


def check_T6(target: Any, ctx: Any) -> Outcome:
    from obspy import UTCDateTime, read

    crit = dict(ctx.criteria)
    total = 10
    tol_samples = int(crit.get("tol_samples", 1))
    stat_tol = float(crit.get("stat_tol_s", 0.011))
    if not isinstance(target, dict) or set(target) != {"json", "picker"} or \
            not isinstance(target["json"], (str, os.PathLike)):
        return _t6_fail("format", 0, total)
    if not _t6_own_picker(target["picker"], ctx.rng, int(crit.get("picker_cases", 3))):
        return _t6_fail("picker", 0, total)
    passed = 1
    try:
        summary = json.loads(Path(target["json"]).expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _t6_fail("format", passed, total)
    if not isinstance(summary, dict) or not set(T6_KEYS) <= set(summary):
        return _t6_fail("format", passed, total)
    try:
        band = [float(v) for v in summary["band_hz"]]
        window = [float(v) for v in summary["window_s"]]
        aic = [float(v) for v in summary["aic_s"]]
    except (TypeError, ValueError):
        return _t6_fail("format", passed, total)
    if len(band) != 2 or len(window) != 2 or len(aic) != 2 or not 0 < band[0] < band[1] or \
            not window[0] < window[1] or min(aic) <= 0 or not isinstance(summary["rows"], list) or \
            not isinstance(summary["grid"], list):
        return _t6_fail("format", passed, total)
    grid = [_t6_setting(entry) for entry in summary["grid"]]
    chosen = _t6_setting(summary["chosen"])
    if chosen is None or any(g is None for g in grid):
        return _t6_fail("format", passed, total)
    passed += 1

    given = Path(str(summary["picks_csv"])).expanduser()
    here = Path(target["json"]).expanduser().parent
    picks_path = next((p for p in (given, here / given, here.parent / given) if p.is_file()), given)
    category, pick_rows = _t5_read(picks_path) if picks_path.is_file() else ("no-file", None)
    if category is not None:
        return _t6_fail("picks-file", passed, total)
    manual = {}
    for row in pick_rows:
        if row["phase"] == "P":
            manual.setdefault(row["station"], row["time"])
    if len(manual) < 6:
        return _t6_fail("picks-file", passed, total)
    passed += 1

    event = _event(MAIN_EVENT)
    folder = _event_folder(ctx, event) if event is not None else None
    if folder is None or not folder.is_dir():
        return _t6_fail("no-data", passed, total)
    rows: Dict[str, dict] = {}
    for row in summary["rows"]:
        if not isinstance(row, dict) or not {"station", "sac_path", "manual_p_utc", "auto_p_utc",
                                            "error_s"} <= set(row):
            return _t6_fail("rows", passed, total)
        rows[str(row["station"])] = row
    if set(rows) != set(manual) or len(rows) != len(summary["rows"]):
        return _t6_fail("rows", passed, total)
    records = {}
    for station, row in rows.items():
        path = Path(str(row["sac_path"])).expanduser()
        match = re.search(r"\.([A-Z0-9]{1,2}\.[A-Z0-9]{2,5})\.([A-Z0-9]{2})Z\.sac$", path.name)
        try:
            inside = path.resolve().parent.parent == folder.resolve()
        except OSError:
            inside = False
        if not (path.is_file() and match and match.group(1) == station and inside):
            return _t6_fail("rows", passed, total, station)
        try:
            records[station] = read(str(path), format="SAC")[0].trim(event["origin"] + window[0],
                                                                    event["origin"] + window[1])
        except Exception:  # noqa: BLE001 - unreadable
            return _t6_fail("rows", passed, total, station)
    passed += 1
    for station, row in rows.items():
        try:
            same = abs(UTCDateTime(str(row["manual_p_utc"])) - manual[station]) <= 0.001
        except (TypeError, ValueError):
            same = False
        if not same:
            return _t6_fail("manual", passed, total, station)
    passed += 1

    def run(setting: Tuple[float, ...]) -> Dict[str, Optional[Any]]:
        out = {}
        for name, record in records.items():
            got, err = _call(target["picker"], record.copy(), band[0], band[1], False, *setting, aic[0], aic[1])
            if err is not None:
                raise err
            out[name] = got if isinstance(got, UTCDateTime) else None
        return out

    mine = run(chosen)
    for station, row in rows.items():
        written = row["auto_p_utc"]
        try:
            moment = None if written is None else UTCDateTime(str(written))
        except (TypeError, ValueError):
            return _t6_fail("format", passed, total, station)
        tol = (tol_samples + 0.01) * records[station].stats.delta
        if (moment is None) != (mine[station] is None) or (moment is not None and abs(moment - mine[station]) > tol):
            return _t6_fail("auto-picks", passed, total, station)
    passed += 1
    errors = {}
    flipped = True
    for station, row in rows.items():
        error = row["error_s"]
        if row["auto_p_utc"] is None:
            if error is not None:
                return _t6_fail("errors", passed, total, station)
            errors[station] = None
            continue
        value = _number(error)
        if value is None:
            return _t6_fail("errors", passed, total, station)
        truth = UTCDateTime(str(row["auto_p_utc"])) - UTCDateTime(str(row["manual_p_utc"]))
        flipped &= abs(value + truth) <= 1e-3 and abs(truth) > 1e-3
        errors[station] = value if abs(value - truth) <= 1e-3 else float("nan")
    if any(e is not None and not math.isfinite(e) for e in errors.values()):
        return _t6_fail("sign" if flipped else "errors", passed, total)
    passed += 1
    stats = _t6_stats(list(errors.values()))
    if not _t6_matches(summary["chosen"], stats, 1e-6):
        return _t6_fail("statistics", passed, total)
    passed += 1
    min_settings = int(crit.get("min_settings", 4))
    same_entry = [entry for entry, values in zip(summary["grid"], grid) if values == chosen]
    if len(grid) < min_settings or len({g[0] for g in grid}) < 2 or len({g[2] for g in grid}) < 2 or \
            not same_entry or not all(_t6_matches(e, stats, 1e-6) for e in same_entry):
        return _t6_fail("grid", passed, total)
    passed += 1
    others = [i for i, values in enumerate(grid) if values != chosen]
    if others:
        pick = int(ctx.rng.choice(others))
        entry, setting = summary["grid"][pick], grid[pick]
        found = run(setting)
        again = [None if found[s] is None else float(found[s] - manual[s]) for s in records]
        if not _t6_matches(entry, _t6_stats(again), stat_tol):
            return _t6_fail("grid-values", passed, total)
    return _real(None, total, total, T6_NOTE + f" Stations: {len(rows)}; settings in your grid: {len(grid)}.")
