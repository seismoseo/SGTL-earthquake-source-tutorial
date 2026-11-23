"""Checkers for M22 · Detecting earthquakes: network coincidence, template matching and a deep-learning detector.

Where the truth comes from (DESIGN.md section 1, rule 1):

* M22-T1: construction (made-up triggers whose events are fixed by how they were built: every trigger of an event is
  placed so that it joins, events and noise triggers are separated by more than the extension) and an independent
  library, ObsPy's ``coincidence_trigger`` on made-up characteristic functions (one box per station and event), with
  ObsPy's subset events (events that start inside an earlier one) dropped. The usual slips show up on small probes
  built so that exactly one slip changes the answer.
* M22-T2: an independent library, ObsPy's ``correlate_template(normalize="full", demean=True)``, and construction
  (noise-free copies give exactly 1 or -1 where they start). Slips are recognized on probes (offsets, a copy 1000
  times larger, flat stretches, int32 data) and from ObsPy's own result on the reversed template.
* M22-T3: independent libraries, ``scipy.stats.median_abs_deviation`` and ``scipy.signal.find_peaks``; slips from
  thresholds of the same libraries' numbers combined in the usual wrong ways.
* M22-T4: construction: event windows are the template windows scaled by known factors (with offsets added, some
  reshaped at the same L2 norm), so every channel's step is known without measuring anything.
* M22-T5: the student's own products and an independent library: the files, picks files and records of the
  student; the network cross-correlations are recomputed with ObsPy's ``correlate_template`` (which the student's
  normalized_cc may not use) from the student's own template windows, the MAD and the peaks with SciPy, and the
  magnitudes with the student's own relative_magnitude after it passed made-up cases of task 4 again. No hidden
  detection list; nothing printed.
* M22-T6: construction: made-up picks of known events whose back-projected times lie within the window by design,
  stray picks placed far from every event and from each other.
* M22-T7: construction: banks with known groups, winners, ties and support IDs. Then the student's own merger
  on their T5 CSV, exact source-file hashes, guarded rehearsal windows, exposure and protocol fields. The checker
  does not supply a real detection list or certify the scientific adequacy of a written plan.

Failure categories are keys of ``checks/specs/M22.yaml``; the engine prints their fixed messages.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import numbers
import os
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import Outcome, outcome_from_cases

__all__ = ["check_T1", "check_T2", "check_T3", "check_T4", "check_T5", "check_T6", "check_T7"]

DATASET_DEFAULT = "sangju2019_hours"
EVENT_FOLDER = "20190721020418"            # STP's folder of the three hours (the ML 3.9's UTC origin time)
# The forbidden lists of tasks 2-4 (checks/specs/M22.yaml); task 5 checks the same functions again under them.
T2_RULES = ("obspy.signal", "numpy.corrcoef", "numpy.ma.corrcoef", "pandas.Series.corr", "pandas.DataFrame.corr",
            "pandas.DataFrame.corrwith", "pandas.Series.autocorr", "pandas.core.window.rolling.Rolling.corr",
            "pandas.core.window.expanding.Expanding.corr", "pandas.core.window.ewm.ExponentialMovingWindow.corr",
            "statistics.correlation", "scipy.stats", "scipy.spatial.distance", "statsmodels", "torch", "jax",
            "tensorflow", "keras", "cupy", "polars", "xarray", "dask", "sklearn", "stumpy", "mass_ts", "tslearn",
            "librosa", "eqcorrscan", "fast_matched_filter", "skimage", "cv2", "pyrocko", "pipeline", "pocketquake",
            "sgtl_tutorial")
T3_RULES = ("scipy.stats", "scipy.signal", "scipy.ndimage", "statsmodels", "astropy", "pandas.Series.mad",
            "pandas.DataFrame.mad", "seisbench", "obspy.signal", "torch", "sgtl_tutorial")
T4_RULES = ("sgtl_tutorial",)


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


def _first(found: Sequence[Optional[str]], priority: Sequence[str]) -> Optional[str]:
    seen = {c for c in found if c}
    return next((c for c in priority if c in seen), "wrong-values" if seen else None)


def _quarter(value: float) -> float:
    """A time on a grid of 1/64 s, so that sums and comparisons of made-up times are exact."""
    return round(float(value) * 64.0) / 64.0


def _short(values: Any, n: int = 12) -> Any:
    arr = np.asarray(values, dtype=float).ravel()
    shown = [round(float(v), 4) for v in arr[:n]]
    return shown + (["..."] if arr.size > n else [])


# --------------------------------------------------------------------------- M22-T1 network coincidence
T1_PRIORITY = ("format", "time-order", "chaining", "extension", "edge", "station-count", "at-least", "start-end",
               "wrong-values")


def _t1_probes() -> List[Tuple[str, dict, int, float, list]]:
    """(category it targets, triggers, min_stations, extension_s, the detections by construction)."""
    a, b, c = "XX.STA1", "XX.STA2", "XX.STA3"
    return [
        ("wrong-values", {a: [(10.0, 12.0)], b: [(11.0, 13.0), (40.0, 41.0)], c: [(14.0, 15.0)]}, 3, 1.5,
         [(10.0, 15.0, (a, b, c))]),
        ("time-order", {c: [(0.0, 3.0)], a: [(30.0, 32.0)], b: [(1.0, 2.0), (30.5, 31.0)]}, 1, 0.0,
         [(0.0, 3.0, (b, c)), (30.0, 32.0, (a, b))]),
        ("chaining", {a: [(0.0, 2.0)], b: [(1.0, 4.0)], c: [(3.5, 5.0)]}, 2, 0.0, [(0.0, 5.0, (a, b, c))]),
        ("extension", {a: [(0.0, 1.0)], b: [(2.0, 3.0)]}, 1, 1.5, [(0.0, 3.0, (a, b))]),
        ("edge", {a: [(0.0, 1.0)], b: [(2.5, 3.0)]}, 1, 1.5, [(0.0, 3.0, (a, b))]),
        ("station-count", {a: [(0.0, 2.0), (1.5, 3.0)], b: [(1.0, 4.0)]}, 3, 0.0, []),
        ("at-least", {a: [(0.0, 2.0)], b: [(1.0, 3.0)], c: [(2.5, 4.0)]}, 3, 0.0, [(0.0, 4.0, (a, b, c))]),
        ("start-end", {a: [(5.0, 6.0)], b: [(4.0, 10.0)], c: [(4.5, 5.0)]}, 2, 0.0, [(4.0, 10.0, (a, b, c))]),
    ]


def _t1_case(rng: np.random.Generator) -> Tuple[dict, int, float, list]:
    """Made-up triggers of known events. Each trigger of an event starts at most at the event's end so far plus the
    extension (so it joins by construction); the next event starts more than the extension after the last end."""
    n_sta = int(rng.integers(2, 9))
    names = [f"XX.S{k:02d}" for k in range(n_sta)]
    extension = float(rng.choice([0.0, 0.5, 1.5, 3.0, 5.0]))
    needed = int(rng.integers(1, min(n_sta, 4) + 1))
    triggers: Dict[str, list] = {name: [] for name in names}
    truth = []
    clock = _quarter(rng.uniform(0.0, 20.0))
    for _ in range(int(rng.integers(0, 8))):
        k = int(rng.integers(1, n_sta + 1))
        chosen = [str(name) for name in rng.choice(names, size=k, replace=False)]
        if rng.uniform() < 0.3:
            chosen.append(chosen[int(rng.integers(0, k))])           # a station that triggers twice
        rng.shuffle(chosen)
        on = clock
        end = _quarter(on + rng.uniform(0.25, 6.0))
        triggers[chosen[0]].append((on, end))
        for name in chosen[1:]:
            on = _quarter(rng.uniform(on, end + extension))
            off = _quarter(on + rng.uniform(0.25, 6.0))
            triggers[name].append((on, off))
            end = max(end, off)
        if len(set(chosen)) >= needed:
            truth.append((clock, end, tuple(sorted(set(chosen)))))
        clock = _quarter(end + extension + rng.uniform(0.25, 40.0))
    order = list(names)
    rng.shuffle(order)
    return {name: sorted(triggers[name]) for name in order}, needed, extension, truth


def _t1_oracle_case(rng: np.random.Generator) -> Tuple[dict, int, float, list]:
    """Made-up characteristic functions (one box per station and event, plus single noise boxes) and the events
    of ObsPy's coincidence_trigger on them, without its subset events."""
    from obspy import Stream, Trace, UTCDateTime
    from obspy.signal.trigger import coincidence_trigger

    rate = 20.0
    n_sta = int(rng.integers(3, 7))
    codes = [f"S{k:02d}" for k in range(n_sta)]
    extension = float(rng.choice([0.0, 1.0, 2.5]))
    needed = int(rng.integers(2, n_sta + 1))
    boxes: Dict[str, list] = {code: [] for code in codes}
    clock = 30.0
    for _ in range(int(rng.integers(2, 5))):
        if rng.uniform() < 0.3:                                       # a noise trigger at one station
            code = str(rng.choice(codes))
            boxes[code].append((clock, clock + float(rng.uniform(0.5, 3.0))))
            clock += 60.0
            continue
        k = int(rng.integers(1, n_sta + 1))
        for code in rng.choice(codes, size=k, replace=False):
            on = clock + float(rng.uniform(0.0, 3.0))
            boxes[str(code)].append((on, clock + 3.0 + float(rng.uniform(0.5, 4.0))))
        clock += 60.0
    npts = int((clock + 30.0) * rate)
    start = UTCDateTime("2031-04-05T06:00:00")
    stream, triggers = Stream(), {}
    for code in codes:
        cft = np.ones(npts)
        pairs = []
        for on, off in sorted(boxes[code]):
            i, j = int(round(on * rate)), int(round(off * rate))
            cft[i:j + 1] = 10.0
            pairs.append((i / rate, j / rate))
        stream += Trace(cft, header={"network": "XX", "station": code, "channel": "HHZ", "sampling_rate": rate,
                                     "starttime": start})
        triggers[f"XX.{code}"] = pairs
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        events = coincidence_trigger(None, 5.0, 2.0, stream, needed, trigger_off_extension=extension)
    truth, last_end = [], -np.inf
    for event in sorted(events, key=lambda e: e["time"]):
        first = float(event["time"] - start)
        if first <= last_end:                                         # ObsPy's subset event: dropped
            continue
        last_end = first + float(event["duration"])
        truth.append((first, last_end, tuple(sorted(f"XX.{s}" for s in set(event["stations"])))))
    return triggers, needed, extension, truth


def _t1_as_list(got: Any) -> Optional[list]:
    """The student's detections as [(float, float, tuple of str)], or None when the format is wrong."""
    if not isinstance(got, (list, tuple)):
        return None
    out = []
    for item in got:
        try:
            first, last, names = item
            names = tuple(names)
        except (TypeError, ValueError):
            return None
        if isinstance(names, str) or not all(isinstance(n, str) for n in names) or list(names) != sorted(names):
            return None
        if not all(isinstance(v, numbers.Real) and not isinstance(v, bool) for v in (first, last)):
            return None
        out.append((float(first), float(last), names))
    return out


def _t1_same(got: list, truth: list, tol: float) -> bool:
    return len(got) == len(truth) and all(
        abs(g[0] - t[0]) <= tol and abs(g[1] - t[1]) <= tol and g[2] == t[2] for g, t in zip(got, truth))


def check_T1(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    trials = max(20, int(crit.get("trials", 200)))
    tol = float(crit.get("abs_tol_s", 1e-9))
    rng = ctx.rng
    cats: List[Optional[str]] = []
    ok: List[bool] = []
    example = None

    def run(category: str, triggers: dict, needed: int, extension: float, truth: list, tolerance: float,
            source: str) -> None:
        nonlocal example
        given = {name: [tuple(p) for p in pairs] for name, pairs in triggers.items()}
        got, err = _call(target, given, needed, extension)
        if err is not None:
            raise err
        mine = _t1_as_list(got)
        passed = mine is not None and _t1_same(mine, truth, tolerance)
        ok.append(passed)
        if not passed:
            cats.append("format" if mine is None else category)
            if example is None:
                shown = {name: pairs[:4] + (["..."] if len(pairs) > 4 else []) for name, pairs in triggers.items()}
                example = {"inputs": {"triggers": shown, "min_stations": needed, "extension_s": extension},
                           "got": got if mine is None else mine[:6], "error": f"{source}: {truth[:6]}"}

    for category, triggers, needed, extension, truth in _t1_probes():
        run(category, triggers, needed, extension, truth, 1e-12, "by construction")
    for _ in range(trials):
        triggers, needed, extension, truth = _t1_case(rng)
        run("wrong-values", triggers, needed, extension, truth, tol, "by construction")
    for _ in range(int(crit.get("oracle_cases", 8))):
        triggers, needed, extension, truth = _t1_oracle_case(rng)
        run("wrong-values", triggers, needed, extension, truth, 1e-5, "ObsPy's coincidence_trigger")
    return outcome_from_cases(ok, category=_first(cats, T1_PRIORITY), example=example)


# ---------------------------------------------------------------------- M22-T2 normalized cross-correlation
T2_PRIORITY = ("format", "length", "flat", "precision", "normalization", "flipped", "lag", "template-mean",
               "window-mean", "wrong-values")
T2_EXAMPLE = ([1, 2, 3], [0, 1, 2, 3, 2, 4, 6], [1.0, 1.0, 0.0, 0.5, 1.0])


def _t2_oracle(template: Any, data: Any, demean: bool = True) -> np.ndarray:
    from obspy.signal.cross_correlation import correlate_template

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return np.asarray(correlate_template(np.asarray(data, dtype=np.float64), np.asarray(template, np.float64),
                                             mode="valid", normalize="full", demean=demean), dtype=float)


def _t2_case(rng: np.random.Generator, number: int) -> Tuple[Any, Any, dict]:
    """A made-up record with copies of a made-up template; facts: copies, kind and the noise-free flag."""
    from .. import synth_detect

    n = int(rng.integers(500, 20001))
    m = int(rng.integers(10, min(400, n // 3)))
    template = synth_detect.wavelet(rng, m) * float(rng.uniform(0.5, 50.0)) + float(rng.uniform(-5.0, 5.0))
    k = int(rng.integers(1, 4))
    starts = sorted(int(s) for s in rng.choice(np.arange(0, n - m, m + 1), size=k, replace=False))
    scales = [float(rng.choice([-1.0, 1.0]) * rng.uniform(0.3, 20.0)) for _ in starts]
    clean = number % 5 == 0
    noise = 0.0 if clean else float(rng.uniform(0.1, 3.0))
    # noise-free records get no offset: their flat stretches must be exactly flat (a constant offset in a flat
    # stretch leaves rounding noise in any running sum, in ObsPy's too)
    offset = float(rng.uniform(-1000.0, 1000.0)) * noise if number % 3 and not clean else 0.0
    data, truth = synth_detect.record_with_copies(rng, template - template.mean(), n, starts, scales, noise=noise,
                                                  smooth=int(rng.integers(1, 6)), offset=offset)
    kind = number % 4
    if kind == 1 and not clean:     # a flat stretch of zeros longer than the template
        at = int(rng.integers(0, n - 2 * m))
        if all(abs(at - s) > 2 * m for s in starts):
            data[at:at + 2 * m] = 0.0
    given: Any = data
    exact = True                    # the copies are exact in what the student gets (so they give exactly 1 or -1)
    if kind == 2:
        given, exact = data.astype(np.float32), False
    elif kind == 3 and number % 2:
        given, exact = np.round(data).astype(np.int32), False
    elif number % 7 == 6:
        given = [float(v) for v in data]
    return template, given, {"starts": truth["starts"], "scales": truth["scales"], "clean": clean and exact}


def _t2_judge(got: Any, template: Any, data: Any, tol: float) -> Optional[str]:
    """None when right; else 'format', 'length' or 'wrong-values' (the probes name the slip). The reference is
    ObsPy's result on the float64 values of exactly what the student got."""
    n, m = len(data), len(template)
    if not isinstance(got, np.ndarray) or got.ndim != 1:
        return "format"
    if got.size != n - m + 1:
        return "length"
    values = got.astype(float)
    expected = _t2_oracle(template, data)
    bad = ~np.isfinite(values)
    if np.any(bad):                         # 0 / 0 where a piece is flat, or something else
        return "flat" if np.all(expected[bad] == 0.0) else "format"
    return None if np.allclose(values, expected, rtol=0.0, atol=tol) else "wrong-values"


def _t2_probes(rng: np.random.Generator) -> List[Tuple[str, Any, Any]]:
    """(category, template, data) probes built so that one slip shows."""
    from .. import synth_detect

    wave = synth_detect.wavelet(rng, 30)
    quiet = rng.normal(0.0, 0.001, 300)
    one = quiet.copy()
    one[117:147] += wave
    noisy = rng.normal(0.0, 1.0, 400)
    noisy[150:180] += 3.0 * wave
    big = rng.normal(0.0, 1.0, 400)
    big[200:230] += 1000.0 * wave
    flat = rng.normal(0.0, 1.0, 400)
    flat[100:200] = 0.0
    ints = np.round(rng.normal(0.0, 1.0, 2000) * 300000.0).astype(np.int32)
    tmpl_int = np.round(wave * 200000.0).astype(np.int32)
    ints[700:730] += tmpl_int
    return [("lag", wave, one), ("template-mean", wave, noisy), ("normalization", wave, big),
            ("flat", wave, flat), ("window-mean", wave, noisy), ("precision", tmpl_int, ints)]


def _t2_probe_category(category: str, target: Any, got: Any, template: Any, data: Any,
                       tol: float) -> Optional[str]:
    """None when the probe passed; else the slip it shows, or 'wrong-values' when it shows none."""
    shape_ok = isinstance(got, np.ndarray) and got.ndim == 1 and got.size == len(data) - len(template) + 1
    if category == "flat" and shape_ok and (not np.all(np.isfinite(got[100:171])) or np.any(got[100:171] != 0)):
        return "flat"
    first = _t2_judge(got, template, data, tol)
    if first in (None, "format", "length"):
        return first
    values = got.astype(float)
    expected = _t2_oracle(template, data)
    if np.allclose(values, _t2_oracle(np.asarray(template)[::-1], data), atol=1e-6):
        return "flipped"
    if category == "lag":
        top_at = int(np.argmax(values))
        return "lag" if top_at != 117 and abs(top_at - 117) < 30 and values[top_at] > 0.99 else "wrong-values"
    if category == "normalization":
        return "normalization" if np.max(np.abs(values)) > 1.0001 else "wrong-values"
    if category == "precision":
        again, err = _call(target, np.asarray(template, dtype=np.float64), np.asarray(data, dtype=np.float64))
        good = err is None and _t2_judge(again, template, data, tol) is None
        return "precision" if good else "wrong-values"
    return "wrong-values"


def _t2_invariance(category: str, target: Any, got: Any, template: Any, data: Any) -> Optional[str]:
    """A correlation coefficient does not change when a constant is added to the template (template-mean) or to
    the data (window-mean); a function whose values change then shows that slip."""
    if not isinstance(got, np.ndarray) or got.ndim != 1:
        return None
    if category == "template-mean":
        moved, err = _call(target, np.asarray(template, dtype=float) + 7.5, np.asarray(data, dtype=float))
    elif category == "window-mean":
        moved, err = _call(target, np.asarray(template, dtype=float), np.asarray(data, dtype=float) + 100.0)
    else:
        return None
    if err is not None or not isinstance(moved, np.ndarray) or moved.shape != got.shape:
        return None
    with np.errstate(invalid="ignore", over="ignore"):
        same = np.allclose(moved.astype(float), got.astype(float), atol=1e-6, equal_nan=True)
    return None if same else category


def check_T2(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    trials = max(10, int(crit.get("trials", 30)))
    tol = float(crit.get("abs_tol", 1e-6))
    rng = ctx.rng
    cats: List[Optional[str]] = []
    ok: List[bool] = []
    example = None

    def note(template: Any, data: Any, got: Any, text: str) -> None:
        nonlocal example
        if example is None:
            example = {"inputs": {"template": _short(template), "data": _short(data), "len(data)": len(data),
                                  "dtype": str(np.asarray(data).dtype)},
                       "got": _short(got) if isinstance(got, np.ndarray) else got, "error": text}

    template, data, expected = T2_EXAMPLE
    got, err = _call(target, list(template), list(data))
    if err is not None:
        raise err
    good = isinstance(got, np.ndarray) and got.shape == (5,) and np.allclose(got, expected, atol=1e-9)
    ok.append(bool(good))
    if not good:
        cats.append(_t2_judge(got, template, data, tol) or "wrong-values")
        note(template, data, got, f"the example of the Contract gives {expected}")
    for category, template, data in _t2_probes(rng):
        got, err = _call(target, template.copy(), data.copy())
        if err is not None:
            raise err
        cat = _t2_invariance(category, target, got, template, data) or \
            _t2_probe_category(category, target, got, template, data, tol)
        ok.append(cat is None)
        if cat:
            cats.append(cat)
            note(template, data, got, "compare with ObsPy's correlate_template(normalize='full')")
    for number in range(trials):
        template, data, facts = _t2_case(rng, number)
        given = data.copy() if isinstance(data, np.ndarray) else list(data)
        got, err = _call(target, template.copy(), given)
        if err is not None:
            raise err
        cat = _t2_judge(got, template, data, tol)
        if cat is None and facts["clean"]:
            values = got.astype(float)
            for start, scale in zip(facts["starts"], facts["scales"]):
                if abs(values[start] - math.copysign(1.0, scale)) > 1e-6:
                    cat = "wrong-values"
        ok.append(cat is None)
        if cat:
            cats.append(cat)
            note(template, data, got, "compare with ObsPy's correlate_template(normalize='full'), and with 1 or -1 "
                                      f"at the noise-free copies starting at {facts['starts']}")
    return outcome_from_cases(ok, category=_first(cats, T2_PRIORITY), example=example)


# ------------------------------------------------------------------------------ M22-T3 a threshold from the MAD
T3_PRIORITY = ("format", "changed-input", "units", "median-offset", "mad-center", "std", "scale", "gap",
               "wrong-values")
T3_EXAMPLE = ([0.0, 0.1, -0.1, 0.0, 0.9, 0.0, 0.05, -0.05, 0.6, 0.0], 0.5, 4.0, 1.0)


def _t3_oracle(cc: np.ndarray, delta: float, k: float, gap: float,
               level: Optional[float] = None) -> Tuple[np.ndarray, np.ndarray, float]:
    from scipy.signal import find_peaks
    from scipy.stats import median_abs_deviation

    x = np.asarray(cc, dtype=float)
    if level is None:
        level = float(np.median(x) + k * median_abs_deviation(x, scale=1.0))
    distance = gap / delta
    peaks, _ = find_peaks(x, height=level, distance=distance if distance >= 1.0 else None)
    return peaks * float(delta), x[peaks], float(level)


def _t3_case(rng: np.random.Generator, number: int) -> Tuple[np.ndarray, float, float, float]:
    """A made-up network cross-correlation: smooth noise, an offset, bumps of known height (or none)."""
    n = int(rng.integers(2000, 60001))
    delta = float(rng.choice([0.01, 0.02, 0.005, 0.025]))
    smooth = int(rng.integers(2, 12))
    kernel = np.hanning(smooth + 2)[1:-1]
    x = np.convolve(rng.normal(0.0, 1.0, n + smooth), kernel / kernel.sum(), mode="same")[:n]
    x = x / np.std(x) * float(rng.uniform(0.005, 0.05))
    if number % 3:
        x = x + float(rng.uniform(-0.3, 0.3))
    if number % 4 != 3:                                                # pure noise every fourth case
        spread = float(np.median(np.abs(x - np.median(x))))
        width = int(rng.integers(3, 40))
        shape = np.exp(-0.5 * ((np.arange(-3 * width, 3 * width + 1)) / width) ** 2)
        for _ in range(int(rng.integers(1, 12))):
            at = int(rng.integers(3 * width, n - 3 * width - 1))
            x[at - 3 * width:at + 3 * width + 1] += float(rng.uniform(2.0, 60.0)) * spread * shape
    k = float(rng.uniform(3.0, 12.0))
    gap = (int(rng.integers(1, 400)) + 0.5) * delta                     # never on the edge of a whole sample
    return x, delta, k, gap


def _t3_unpack(got: Any) -> Optional[Tuple[np.ndarray, np.ndarray, float]]:
    try:
        times, values, level = got
        times = np.asarray(times, dtype=float).ravel()
        values = np.asarray(values, dtype=float).ravel()
        level = float(level)
    except (TypeError, ValueError):
        return None
    if times.size != values.size or not math.isfinite(level) or (times.size > 1 and np.any(np.diff(times) < 0)):
        return None
    return times, values, level


def _t3_judge(got: Any, cc: np.ndarray, delta: float, k: float, gap: float, tol: float) -> Optional[str]:
    from scipy.stats import median_abs_deviation

    mine = _t3_unpack(got)
    if mine is None:
        return "format"
    times, values, level = mine
    want_t, want_v, want_level = _t3_oracle(cc, delta, k, gap)
    scale = max(1.0, abs(want_level))
    if abs(level - want_level) <= tol * scale:
        if times.size == want_t.size and np.allclose(times, want_t, atol=1e-9) and np.allclose(values, want_v,
                                                                                                atol=1e-12):
            return None
        if times.size == want_t.size and np.allclose(times, want_t / delta, atol=1e-6) and delta != 1.0:
            return "units"
        return "gap"
    x = np.asarray(cc, dtype=float)
    middle = float(np.median(x))
    mad = float(median_abs_deviation(x, scale=1.0))
    slips = {"median-offset": k * mad, "mad-center": middle + k * float(np.median(np.abs(x))),
             "std": middle + k * float(np.std(x)), "scale": middle + k * 1.482602218505602 * mad}
    near = sorted((abs(level - value), name) for name, value in slips.items()
                  if abs(level - value) <= 1e-7 * max(1.0, abs(value)))
    return near[0][1] if near else "wrong-values"


def check_T3(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    trials = max(10, int(crit.get("trials", 60)))
    tol = float(crit.get("abs_tol", 1e-9))
    rng = ctx.rng
    cats: List[Optional[str]] = []
    ok: List[bool] = []
    example = None
    cases = [(np.array(T3_EXAMPLE[0]), *T3_EXAMPLE[1:])]
    probe = rng.normal(0.0, 0.01, 4000) + 0.3                           # an offset: median-offset and mad-center
    probe[1000:1003] += np.array([0.3, 0.6, 0.3])
    probe[3000:3003] += np.array([0.2, 0.5, 0.2])
    cases.append((probe, 0.01, 6.0, 0.505))
    huge = rng.normal(0.0, 0.01, 4000)                                  # a few huge values: std
    huge[500:503] += np.array([2.0, 5.0, 2.0])
    huge[2500:2503] += np.array([0.03, 0.08, 0.03])
    cases.append((huge, 0.02, 5.0, 1.01))
    close = rng.normal(0.0, 0.001, 3000)                                # two detections closer than the gap
    close[1000:1003] += np.array([0.5, 1.0, 0.5])
    close[1150:1153] += np.array([0.4, 0.8, 0.4])
    close[2000:2003] += np.array([0.4, 0.8, 0.4])
    cases.append((close, 0.01, 8.0, 2.005))
    cases += [_t3_case(rng, number) for number in range(trials)]
    for cc, delta, k, gap in cases:
        given = np.array(cc, dtype=float)
        got, err = _call(target, given, delta, k, gap)
        if err is not None:
            raise err
        cat = "changed-input" if not np.array_equal(given, cc) else _t3_judge(got, cc, delta, k, gap, tol)
        ok.append(cat is None)
        if cat:
            cats.append(cat)
            if example is None:
                want_t, want_v, want_level = _t3_oracle(cc, delta, k, gap)
                example = {"inputs": {"cc": _short(cc), "len(cc)": len(cc), "delta": delta, "k": round(k, 3),
                                      "min_gap_s": gap},
                           "got": got if not isinstance(got, tuple) else tuple(
                               _short(v) if isinstance(v, np.ndarray) else v for v in got),
                           "error": f"SciPy gives threshold {want_level:.6g} and {want_t.size} detections at "
                                    f"{_short(want_t, 8)} s"}
    return outcome_from_cases(ok, category=_first(cats, T3_PRIORITY), example=example)


# ------------------------------------------------------------------------------- M22-T4 a relative magnitude
T4_PRIORITY = ("format", "offset", "energy", "log-base", "direction", "cc-weighted", "peak-amplitude", "median",
               "flat-channel", "wrong-values")


def _t4_reshape(rng: np.random.Generator, t: np.ndarray, how: str) -> np.ndarray:
    """Another zero-mean waveform with exactly the L2 norm of t (t has zero mean)."""
    if how == "same":
        return t.copy()
    if how == "reversed":
        return t[::-1].copy()
    if how == "flipped":
        return -t
    w = rng.normal(0.0, 1.0, t.size) * np.exp(-np.linspace(0.0, 3.0, t.size))
    w = w - w.mean()
    return w * (np.linalg.norm(t) / np.linalg.norm(w))


def _t4_case(rng: np.random.Generator, steps: Sequence[float], hows: Sequence[str], *, offsets: bool = True,
             flat: Sequence[str] = ()) -> Tuple[list, list, float]:
    """Windows whose channel steps are fixed by construction: event = 10**step x (reshaped template) + offset."""
    from .. import synth_detect

    tw, ew = [], []
    for step, how in zip(steps, hows):
        m = int(rng.integers(20, 400))
        t = synth_detect.wavelet(rng, m) * float(rng.uniform(0.1, 1000.0))
        t = t - t.mean()
        e = (10.0 ** step) * _t4_reshape(rng, t, how)
        a = float(rng.uniform(-500.0, 500.0)) if offsets else 0.0
        b = float(rng.uniform(-500.0, 500.0)) if offsets else 0.0
        tw.append(t + a)
        ew.append(e + b)
    for kind in flat:
        m = int(rng.integers(20, 100))
        level = float(rng.integers(-40, 41)) / 4.0       # exact in binary, so the mean of the window is exact
        if kind == "template":
            tw.append(np.full(m, level))
            ew.append(rng.normal(0.0, 1.0, m))
        else:
            tw.append(rng.normal(0.0, 1.0, m))
            ew.append(np.full(m, level))
    ml = float(np.round(rng.uniform(-1.0, 5.0), 1))
    return tw, ew, ml


def _t4_value(got: Any) -> Optional[float]:
    if isinstance(got, bool) or not isinstance(got, (numbers.Real, np.floating, np.integer)):
        if isinstance(got, np.ndarray) and got.size == 1:
            return float(got.ravel()[0])
        return None
    return float(got)


def _t4_run(target: Any, tw: list, ew: list, ml: float) -> Tuple[Any, Optional[BaseException]]:
    return _call(target, [np.array(w) for w in tw], [np.array(w) for w in ew], ml)


def check_T4(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    trials = max(10, int(crit.get("trials", 80)))
    tol = float(crit.get("abs_tol", 1e-6))
    rng = ctx.rng
    cats: List[Optional[str]] = []
    ok: List[bool] = []
    example = None

    def judge(category: str, tw: list, ew: list, ml: float, want: float, slips: Dict[str, float]) -> None:
        nonlocal example
        got, err = _t4_run(target, tw, ew, ml)
        if err is not None:
            if category == "flat-channel":
                cats.append("flat-channel")
                ok.append(False)
                return
            raise err
        value = _t4_value(got)
        if value is None:
            cat: Optional[str] = "format"
        elif math.isnan(want):
            cat = None if math.isnan(value) else category
        elif math.isfinite(value) and abs(value - want) <= tol:
            cat = None
        elif category == "flat-channel":            # a crash, nan or infinity shows the slip; a number does not
            cat = "wrong-values" if math.isfinite(value) else category
        else:
            cat = next((name for name, v in slips.items() if math.isfinite(value) and abs(value - v) <= 1e-4),
                       category)
        ok.append(cat is None)
        if cat:
            cats.append(cat)
            if example is None:
                example = {"inputs": {"channels": len(tw), "template_ml": ml,
                                      "template_windows[0]": _short(tw[0], 8), "event_windows[0]": _short(ew[0], 8)},
                           "got": got, "error": f"by construction the magnitude is {want:.6g}"}

    tw, ew = [[1, -1, 1, -1], [2, 0, -2, 0]], [[10, -10, 10, -10], [0, 2, 0, -2]]
    judge("wrong-values", tw, ew, 1.0, 1.5, {})
    step = math.log10(3.0)
    tw, ew, ml = _t4_case(rng, [step] * 3, ["same"] * 3, offsets=False)
    judge("wrong-values", tw, ew, ml, ml + step, {"energy": ml + 2 * step, "log-base": ml + math.log(3.0),
                                                  "direction": ml - step})
    two = math.log10(2.0)
    tw, ew, ml = _t4_case(rng, [two] * 3, ["same"] * 3, offsets=True)
    judge("offset", tw, ew, ml, ml + two, {"energy": ml + 2 * two, "log-base": ml + math.log(2.0),
                                           "direction": ml - two})
    tw, ew, ml = _t4_case(rng, [0.7] * 3, ["reversed"] * 3, offsets=False)
    judge("cc-weighted", tw, ew, ml, ml + 0.7, {})
    tw, ew, ml = _t4_case(rng, [0.4] * 3, ["other"] * 3, offsets=False)
    judge("peak-amplitude", tw, ew, ml, ml + 0.4, {})
    tw, ew, ml = _t4_case(rng, [0.0, 0.1, 0.2, 1.5], ["same"] * 4, offsets=False)
    judge("median", tw, ew, ml, ml + 0.15, {})
    tw, ew, ml = _t4_case(rng, [0.3, -0.2, 0.5], ["same"] * 3, offsets=True, flat=("template", "event"))
    judge("flat-channel", tw, ew, ml, ml + 0.3, {})
    tw, ew, ml = _t4_case(rng, [], [], flat=("template", "event"))
    judge("flat-channel", tw, ew, ml, float("nan"), {})
    for _ in range(trials):
        n = int(rng.integers(1, 13))
        steps = [float(rng.uniform(-3.0, 3.0)) for _ in range(n)]
        hows = [str(rng.choice(["same", "reversed", "flipped", "other"])) for _ in range(n)]
        flat = tuple(rng.choice(["template", "event"]) for _ in range(int(rng.integers(0, 2))))
        tw, ew, ml = _t4_case(rng, steps, hows, offsets=bool(rng.uniform() < 0.7), flat=flat)
        judge("wrong-values", tw, ew, ml, ml + float(np.median(steps)), {})
    return outcome_from_cases(ok, category=_first(cats, T4_PRIORITY), example=example)


# ------------------------------------------------------------------------ M22-T5 template matching, real data
T5_NOTE = ("This check reads your two files, your picks files and your records; it recomputes your network "
           "cross-correlations with ObsPy. It never prints the values it compares with.")
T5_KEYS = ("dataset", "band_hz", "corners", "taper_s", "pre_s", "p_len_s", "s_len_s", "k_mad", "min_gap_s",
           "match_s", "detections_csv", "templates")
T5_TEMPLATE_KEYS = ("event_id", "ml", "origin_utc", "picks_csv", "channels", "median", "mad", "threshold",
                    "n_detections", "null_threshold", "null_n_detections")
T5_COLUMNS = ("template", "time_utc", "network_cc", "magnitude", "kma_event_id")


def _t5_fail(category: str, passed: int, total: int, template: Optional[str] = None) -> Outcome:
    ok = [True] * passed + [False] * max(1, total - passed)
    example = {"inputs": {"template": template}} if template else None
    return outcome_from_cases(ok, category=category, example=example, real_data=True, note=T5_NOTE)


def _t5_own_functions(result: dict, rng: np.random.Generator, cases: int) -> bool:
    """True when the three functions pass made-up cases of tasks 2-4 again, under their library rules."""
    from .. import astguard

    for key, rules in (("ncc", T2_RULES), ("detect", T3_RULES), ("magnitude", T4_RULES)):
        func = result.get(key)
        if not callable(func) or not astguard.check_function(func, rules).ok:
            return False
    for number in range(max(1, cases)):
        template, data, _facts = _t2_case(rng, 1 + 2 * number)
        got, err = _call(result["ncc"], template.copy(), np.array(data, dtype=float))
        if err is not None or _t2_judge(got, template, np.array(data, dtype=float), 1e-6) is not None:
            return False
        cc, delta, k, gap = _t3_case(rng, number)
        got, err = _call(result["detect"], cc.copy(), delta, k, gap)
        if err is not None or _t3_judge(got, cc, delta, k, gap, 1e-9) is not None:
            return False
        steps = [float(rng.uniform(-2.0, 2.0)) for _ in range(5)]
        tw, ew, ml = _t4_case(rng, steps, ["same", "reversed", "other", "same", "flipped"])
        got, err = _t4_run(result["magnitude"], tw, ew, ml)
        value = _t4_value(got) if err is None else None
        if value is None or not math.isfinite(value) or abs(value - (ml + float(np.median(steps)))) > 1e-6:
            return False
    return True


def _t5_records(folder: Path, band_hz: Sequence[float], corners: int, taper_s: float) -> Any:
    """The records of the three hours, prepared as in Part 0 of the module (ObsPy's own methods)."""
    from obspy import Stream, read

    stream = Stream()
    for band in ("HH", "EL"):
        for path in sorted((folder / band).glob("*.sac")):
            stream += read(str(path))
    for tr in stream:
        tr.data = tr.data.astype(np.float64)
    stream.detrend("demean")
    stream.taper(max_percentage=None, max_length=float(taper_s), type="hann")
    stream.filter("bandpass", freqmin=float(band_hz[0]), freqmax=float(band_hz[1]), corners=int(corners),
                  zerophase=False)
    return stream


def _t5_kma() -> Dict[str, Tuple[Any, float]]:
    from obspy import UTCDateTime

    from .. import data as _data

    cat = _data.kma_catalog()
    return {str(r.event_id): (UTCDateTime(r.origin_utc.isoformat()), float(r.ml)) for r in cat.itertuples()}


def _t5_number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _t5_picks(path: Any) -> Optional[Dict[Tuple[str, str], Any]]:
    """{(station, phase): UTCDateTime} of a picks file, or None when it cannot be read."""
    from obspy import UTCDateTime

    try:
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        out = {}
        for row in rows:
            out[(row["station"].strip(), row["phase"].strip())] = UTCDateTime(row["time_utc"].strip())
        return out
    except (OSError, KeyError, ValueError, TypeError, AttributeError):
        return None


def _t5_network(stream: Any, channels: List[dict], npts: int, reverse: bool) -> np.ndarray:
    """Mean over channels of ObsPy's correlation at q + lag (0 outside), from the student's windows."""
    from obspy.signal.cross_correlation import correlate_template

    total = np.zeros(npts)
    for ch in channels:
        data = ch["trace"].data[:npts]
        values = correlate_template(data[::-1] if reverse else data, ch["window"], mode="valid", normalize="full",
                                    demean=True)
        q = np.arange(npts)
        j = q + ch["lag"]
        inside = (j >= 0) & (j < values.size)
        total[inside] += values[j[inside]]
    return total / max(1, len(channels))


def check_T5(target: Any, ctx: Any) -> Outcome:
    from obspy import UTCDateTime
    from scipy.signal import find_peaks
    from scipy.stats import median_abs_deviation

    crit = dict(ctx.criteria)
    cc_tol = float(crit.get("cc_tol", 1e-4))
    thr_tol = float(crit.get("threshold_tol", 1e-4))
    time_tol = float(crit.get("time_tol_s", 0.011))
    mag_tol = float(crit.get("magnitude_tol", 0.01))
    min_stations = int(crit.get("min_stations", 3))
    total = 12
    if not isinstance(target, dict) or set(target) != {"json", "ncc", "detect", "magnitude", "network"} or \
            not isinstance(target["json"], (str, os.PathLike)) or not isinstance(target["network"], dict):
        return _t5_fail("format", 0, total)
    if not _t5_own_functions(target, ctx.rng, int(crit.get("cases", 2))):
        return _t5_fail("own-functions", 0, total)
    try:
        info = json.loads(Path(target["json"]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _t5_fail("format", 1, total)
    if not isinstance(info, dict) or any(key not in info for key in T5_KEYS) or \
            not isinstance(info["templates"], list) or not info["templates"]:
        return _t5_fail("format", 1, total)
    numbers_ok = [_t5_number(info.get(key)) for key in ("taper_s", "pre_s", "p_len_s", "s_len_s", "k_mad",
                                                         "min_gap_s", "match_s")]
    band = info.get("band_hz")
    if any(v is None or v < 0 for v in numbers_ok) or not isinstance(band, list) or len(band) != 2 or \
            any(_t5_number(b) is None for b in band) or _t5_number(info.get("corners")) is None:
        return _t5_fail("format", 1, total)
    taper_s, pre_s, p_len, s_len, k_mad, min_gap, match_s = numbers_ok
    if k_mad <= 0:
        return _t5_fail("threshold", 1, total)
    try:
        with open(info["detections_csv"], newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            columns = tuple(reader.fieldnames or ())
            rows = list(reader)
    except (OSError, TypeError, ValueError):
        return _t5_fail("format", 1, total)
    if columns != T5_COLUMNS:
        return _t5_fail("format", 1, total)
    for t in info["templates"]:
        if not isinstance(t, dict) or any(key not in t for key in T5_TEMPLATE_KEYS) or \
                not isinstance(t["channels"], list):
            return _t5_fail("format", 1, total)

    dataset = str(ctx.get("dataset") or info.get("dataset") or DATASET_DEFAULT)
    folder = Path(ctx.data_root) / dataset / "stp_download" / "SAC" / EVENT_FOLDER
    if not (folder / "HH").is_dir():
        return _t5_fail("records", 1, total)
    stream = _t5_records(folder, band, int(info["corners"]), taper_s)
    by_id = {tr.id: tr for tr in stream}
    if not by_id:
        return _t5_fail("records", 1, total)
    t_start = min(tr.stats.starttime for tr in stream)
    delta = float(stream[0].stats.delta)
    npts = min(tr.stats.npts for tr in stream)
    kma = _t5_kma()
    t_end = t_start + (npts - 1) * delta
    in_window = {e: v for e, v in kma.items() if t_start <= v[0] <= t_end}
    seen_kma = set()
    passed = 2

    for t in info["templates"]:
        name = str(t["event_id"])
        if name not in in_window or _t5_number(t["ml"]) is None or abs(float(t["ml"]) - in_window[name][1]) > 1e-6:
            return _t5_fail("templates", passed, total, name)
        origin = in_window[name][0]
        try:
            if abs(UTCDateTime(str(t["origin_utc"])) - origin) > 1e-6:
                return _t5_fail("templates", passed, total, name)
        except (TypeError, ValueError):
            return _t5_fail("templates", passed, total, name)
        picks = _t5_picks(t["picks_csv"])
        if picks is None:
            return _t5_fail("picks-file", passed, total, name)
        wanted = set()
        for (station, phase) in picks:
            if phase not in ("P", "S") or "." not in station:
                continue
            for tr_id, tr in by_id.items():
                if f"{tr.stats.network}.{tr.stats.station}" == station and \
                        tr.stats.channel[-1] in (("Z",) if phase == "P" else ("N", "E")):
                    wanted.add((tr_id, phase))
        channels, used = [], set()
        for ch in t["channels"]:
            try:
                tr = by_id[str(ch["id"])]
                phase = str(ch["phase"])
                start = UTCDateTime(str(ch["start_utc"]))
                lag = int(ch["lag_samples"])
            except (KeyError, TypeError, ValueError):
                return _t5_fail("templates", passed, total, name)
            station = f"{tr.stats.network}.{tr.stats.station}"
            if (station, phase) not in picks or (tr.id, phase) not in wanted or (tr.id, phase) in used:
                return _t5_fail("templates", passed, total, name)
            used.add((tr.id, phase))
            t_first, step = tr.stats.starttime, float(tr.stats.delta)
            cut_at = int(np.rint(float(picks[(station, phase)] - t_first - pre_s) / step))
            origin_at = int(np.rint(float(origin - t_first) / step))
            if abs(float(start - t_first) - cut_at * step) > 0.25 * step or lag != cut_at - origin_at:
                return _t5_fail("templates", passed, total, name)
            n_win = int(np.rint((p_len if phase == "P" else s_len) / step))
            if cut_at < 0 or cut_at + n_win > npts or n_win < 2:
                return _t5_fail("templates", passed, total, name)
            channels.append({"trace": tr, "lag": lag, "window": tr.data[cut_at:cut_at + n_win].copy()})
        if used != wanted:
            return _t5_fail("templates", passed, total, name)
        if len({ch["trace"].stats.station for ch in channels}) < min_stations:
            return _t5_fail("too-few", passed, total, name)
        passed = 3

        real = _t5_network(stream, channels, npts, reverse=False)
        null = _t5_network(stream, channels, npts, reverse=True)
        mine = target["network"].get(name, target["network"].get(int(name)) if name.isdigit() else None)
        try:
            mine_real, mine_null = (np.asarray(v, dtype=float) for v in mine)
        except (TypeError, ValueError):
            return _t5_fail("network", passed, total, name)
        if mine_real.shape != real.shape or not np.allclose(mine_real, real, rtol=0.0, atol=cc_tol):
            return _t5_fail("network", passed, total, name)
        passed = 5
        center = float(np.median(real))
        spread = float(median_abs_deviation(real, scale=1.0))
        level = center + k_mad * spread
        values = [_t5_number(t[key]) for key in ("median", "mad", "threshold")]
        if any(v is None for v in values) or abs(values[0] - center) > thr_tol or abs(values[1] - spread) > thr_tol \
                or abs(values[2] - level) > thr_tol:
            return _t5_fail("threshold", passed, total, name)
        passed = 6
        distance = min_gap / delta
        peaks, _ = find_peaks(real, height=values[2], distance=distance if distance >= 1.0 else None)
        mine_rows = [r for r in rows if str(r["template"]).strip() == name]
        if len(mine_rows) != peaks.size or _t5_number(t["n_detections"]) != float(peaks.size):
            return _t5_fail("detections", passed, total, name)
        windows = [ch["window"] for ch in channels]
        for row, q in zip(sorted(mine_rows, key=lambda r: str(r["time_utc"])), peaks):
            try:
                when = UTCDateTime(str(row["time_utc"]))
                value = float(row["network_cc"])
            except (TypeError, ValueError):
                return _t5_fail("format", passed, total, name)
            try:
                size = float(row["magnitude"])
            except (TypeError, ValueError):
                size = float("nan")
            if abs(when - (t_start + q * delta)) > time_tol or abs(value - real[q]) > cc_tol * 10:
                return _t5_fail("detections", passed, total, name)
            # the magnitude of the student's own relative_magnitude (checked on made-up cases above) at this q
            ours, theirs = [], []
            for w, ch in zip(windows, channels):
                at = q + ch["lag"]
                if at >= 0 and at + w.size <= npts:
                    ours.append(w)
                    theirs.append(ch["trace"].data[at:at + w.size])
            again, err = _call(target["magnitude"], ours, theirs, float(t["ml"]))
            expected = _t4_value(again) if err is None else None
            if expected is None or not (math.isfinite(size) and abs(size - expected) <= mag_tol):
                return _t5_fail("magnitudes", passed + 1, total, name)
            near = sorted((abs(v[0] - when), e) for e, v in kma.items() if abs(v[0] - when) <= match_s)
            if str(row["kma_event_id"] or "").strip() != (near[0][1] if near else ""):
                return _t5_fail("catalog", passed + 2, total, name)
            if near:
                seen_kma.add(near[0][1])
        own = int(round((origin - t_start) / delta))
        selfish = [q for q in peaks if abs(q - own) <= 1]
        if not selfish or real[selfish[0]] < 0.999:
            return _t5_fail("self-detection", passed + 3, total, name)
        if not mine_null.shape == null.shape or not np.allclose(mine_null, null, rtol=0.0, atol=cc_tol):
            return _t5_fail("null-test", passed + 3, total, name)
        null_level = _t5_number(t["null_threshold"])
        null_peaks, _ = find_peaks(null, height=values[2], distance=distance if distance >= 1.0 else None)
        if null_level is None or abs(null_level - values[2]) > 1e-9 * max(1.0, abs(values[2])) or \
                _t5_number(t["null_n_detections"]) != float(null_peaks.size):
            return _t5_fail("null-test", passed + 3, total, name)
    known = {str(r["template"]).strip() for r in rows}
    if known - {str(t["event_id"]) for t in info["templates"]}:
        return _t5_fail("detections", 10, total)
    if set(in_window) - seen_kma:
        return _t5_fail("catalog", 11, total)
    return outcome_from_cases([True] * total, real_data=True, note=T5_NOTE)


# ------------------------------------------------------------------------------------- M22-T6 an associator
T6_PRIORITY = ("format", "changed-input", "missing-travel-time", "back-projection", "station-count", "at-least",
               "window-edge", "reuse", "origin-time", "wrong-values")
T6_COLUMNS = ["origin_s", "n_stations", "n_picks"]


def _t6_frame(rows: List[Tuple[str, str, float]]) -> Any:
    import pandas as pd

    return pd.DataFrame(rows, columns=["station", "phase", "time_s"])


def _t6_probes() -> List[Tuple[str, Any, dict, float, int, list]]:
    """(category, picks, travel times, window, min stations, events (origin, stations, picks)) by construction."""
    tt = {("XX.STA1", "P"): 2.0, ("XX.STA2", "P"): 3.2, ("XX.STA3", "S"): 6.1, ("XX.STA1", "S"): 3.5}
    example = _t6_frame([("XX.STA1", "P", 12.0), ("XX.STA2", "P", 13.0), ("XX.STA3", "S", 16.4),
                         ("XX.STA1", "S", 30.0)])
    far = {("XX.A", "P"): 2.0, ("XX.B", "P"): 6.0, ("XX.C", "P"): 10.0}
    back = _t6_frame([("XX.A", "P", 12.0), ("XX.B", "P", 16.0), ("XX.C", "P", 20.0)])
    two = {("XX.A", "P"): 2.0, ("XX.A", "S"): 3.5, ("XX.B", "P"): 4.0, ("XX.B", "S"): 7.0}
    twos = _t6_frame([("XX.A", "P", 12.0), ("XX.A", "S", 13.5), ("XX.B", "P", 14.0), ("XX.B", "S", 17.0)])
    three = {("XX.A", "P"): 1.0, ("XX.B", "P"): 2.0, ("XX.C", "P"): 3.0, ("XX.D", "P"): 4.0}
    edge = _t6_frame([("XX.A", "P", 11.0), ("XX.B", "P", 12.25), ("XX.C", "P", 13.5)])
    mean = _t6_frame([("XX.A", "P", 11.0), ("XX.B", "P", 12.125), ("XX.C", "P", 13.5)])
    reuse = _t6_frame([("XX.A", "P", 11.0), ("XX.B", "P", 12.125), ("XX.C", "P", 13.25), ("XX.D", "P", 14.375)])
    missing = _t6_frame([("XX.A", "P", 11.0), ("XX.Q", "P", 11.5), ("XX.B", "P", 12.0), ("XX.C", "S", 13.0),
                         ("XX.C", "P", 13.0)])
    return [
        ("wrong-values", example, tt, 0.6, 3, [(10.0, 3, 3)]),
        ("back-projection", back, far, 0.5, 3, [(10.0, 3, 3)]),
        ("station-count", twos, two, 0.5, 3, []),
        ("at-least", back, far, 0.5, 3, [(10.0, 3, 3)]),
        ("window-edge", edge, three, 0.5, 3, [(10.25, 3, 3)]),
        ("origin-time", mean, three, 0.5, 3, [(10.125, 3, 3)]),
        ("reuse", reuse, three, 0.5, 3, [(10.1875, 4, 4)]),
        ("missing-travel-time", missing, three, 0.5, 3, [(10.0, 3, 3)]),
    ]


def _t6_case(rng: np.random.Generator) -> Tuple[Any, dict, float, int, list]:
    """Made-up picks of known events; stray picks far (in back-projected time) from events and each other."""
    n_sta = int(rng.integers(3, 11))
    names = [f"XX.S{k:02d}" for k in range(n_sta)]
    travel = {}
    for name in names:
        p = _quarter(rng.uniform(1.0, 12.0))
        travel[(name, "P")] = p
        travel[(name, "S")] = _quarter(p * rng.uniform(1.6, 1.9))
    window = float(rng.choice([0.5, 1.0, 1.5, 2.0, 3.0]))
    needed = int(rng.integers(2, min(n_sta, 5) + 1))
    jitter = 0.4 * window
    rows, truth, blocked = [], [], []
    clock = _quarter(rng.uniform(10.0, 60.0))
    for _ in range(int(rng.integers(0, 7))):
        back = []
        for name in names:
            for phase in ("P", "S"):
                if rng.uniform() < 0.35:
                    continue
                shift = _quarter(rng.uniform(0.0, 2.0 * jitter)) if rng.uniform() < 0.9 else 0.0
                rows.append((name, phase, clock + shift + travel[(name, phase)]))
                back.append((clock + shift, name))
        if back:
            who = {s for _, s in back}
            if len(who) >= needed:
                truth.append((float(np.median([b for b, _ in back])), len(who), len(back)))
            blocked.append((clock, clock + 2.0 * jitter))
        clock = _quarter(clock + 2.0 * jitter + 3.0 * window + rng.uniform(1.0, 60.0))
    strays = []
    for _ in range(int(rng.integers(0, 15))):
        at = _quarter(rng.uniform(0.0, clock + 30.0))
        if all(at < lo - 2.0 * window or at > hi + 2.0 * window for lo, hi in blocked + strays):
            name = str(rng.choice(names))
            phase = str(rng.choice(["P", "S"]))
            rows.append((name, phase, at + travel[(name, phase)]))
            strays.append((at, at))
    if needed == 1:
        truth += [(at, 1, 1) for at, _ in strays]
    order = rng.permutation(len(rows))
    picks = _t6_frame([rows[i] for i in order])
    return picks, travel, window, needed, sorted(truth)


def _t6_rows(got: Any) -> Optional[List[Tuple[float, int, int]]]:
    try:
        import pandas as pd
    except ImportError:  # pragma: no cover
        return None
    if not isinstance(got, pd.DataFrame) or list(got.columns) != T6_COLUMNS:
        return None
    out = []
    try:
        for a, b, c in zip(got["origin_s"], got["n_stations"], got["n_picks"]):
            if not float(b).is_integer() or not float(c).is_integer():
                return None
            out.append((float(a), int(b), int(c)))
    except (TypeError, ValueError):
        return None
    if any(out[i][0] > out[i + 1][0] for i in range(len(out) - 1)):
        return None
    return out


def check_T6(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    trials = max(20, int(crit.get("trials", 150)))
    tol = float(crit.get("abs_tol", 1e-9))
    rng = ctx.rng
    cats: List[Optional[str]] = []
    ok: List[bool] = []
    example = None

    def run(category: str, picks: Any, travel: dict, window: float, needed: int, truth: list) -> None:
        nonlocal example
        given = picks.copy()
        got, err = _call(target, given, dict(travel), window, needed)
        if err is not None:
            if category == "missing-travel-time" and isinstance(err, KeyError):
                ok.append(False)
                cats.append(category)
                return
            raise err
        if not given.equals(picks):
            ok.append(False)
            cats.append("changed-input")
            return
        mine = _t6_rows(got)
        same = mine is not None and len(mine) == len(truth) and all(
            abs(a[0] - b[0]) <= tol and a[1] == b[1] and a[2] == b[2] for a, b in zip(mine, truth))
        ok.append(same)
        if not same:
            shown = "wrong-values" if category == "missing-travel-time" else category
            cats.append("format" if mine is None else shown)
            if example is None:
                example = {"inputs": {"picks": picks.head(8).to_dict("list"), "n_picks": len(picks),
                                      "window_s": window, "min_stations": needed},
                           "got": got.head(6).to_dict("list") if hasattr(got, "head") else got,
                           "error": f"by construction the events (origin_s, n_stations, n_picks) are {truth[:6]}"}

    for category, picks, travel, window, needed, truth in _t6_probes():
        run(category, picks, travel, window, needed, truth)
    for _ in range(trials):
        run("wrong-values", *_t6_case(rng))
    return outcome_from_cases(ok, category=_first(cats, T6_PRIORITY), example=example)


# ---------------------------------------------------------------------- M22-T7 one candidate per bank match
T7_PRIORITY = ("format", "changed-input", "time-order", "chaining", "window-edge", "best-score", "ties",
               "provenance", "wrong-values")
T7_WRITTEN = ("threshold_freeze", "control_and_exposure", "injection_recovery", "selection_bias",
              "prior_exposure", "suncheon_transfer", "sangju2026_transfer")
T7_PROTOCOL_KEYS = {"dataset", "exercise_status", "bank_version", "template_ids", "score_definition",
                    "merge_window_s", "calibration_window_s", "evaluation_window_s", "guard_s",
                    "calibration_live_hours", "evaluation_live_hours", "matching_json_sha256",
                    "matches_csv_sha256", *T7_WRITTEN}
T7_CANDIDATE_COLUMNS = ("time_s", "time_utc", "score", "representative", "templates", "n_matches")


def _t7_probes() -> list:
    return [
        ("wrong-values", [], 1.0, []),
        ("time-order", [("C", 4.0, 8.0), ("A", 0.0, 8.0), ("B", 2.0, 8.0)], 0.5,
         [(0.0, 8.0, "A", ("A",), 1), (2.0, 8.0, "B", ("B",), 1), (4.0, 8.0, "C", ("C",), 1)]),
        ("chaining", [("A", 0.0, 8.0), ("B", 0.75, 9.0), ("C", 1.5, 10.0)], 1.0,
         [(0.75, 9.0, "B", ("A", "B"), 2), (1.5, 10.0, "C", ("C",), 1)]),
        ("window-edge", [("A", 0.0, 8.0), ("B", 1.0, 9.0)], 1.0,
         [(1.0, 9.0, "B", ("A", "B"), 2)]),
        ("best-score", [("A", 0.0, 8.0), ("B", 0.25, 11.0), ("C", 0.5, 9.0)], 1.0,
         [(0.25, 11.0, "B", ("A", "B", "C"), 3)]),
        ("ties", [("Z", 0.5, 9.0), ("B", 0.0, 9.0), ("A", 0.0, 9.0)], 1.0,
         [(0.0, 9.0, "A", ("A", "B", "Z"), 3)]),
        ("provenance", [("B", 0.0, 8.0), ("A", 0.25, 9.0), ("B", 0.5, 10.0)], 1.0,
         [(0.5, 10.0, "B", ("A", "B"), 3)]),
        ("window-edge", [("B", 2.0, 8.0), ("A", 2.0, 9.0)], 0.0,
         [(2.0, 9.0, "A", ("A", "B"), 2)]),
    ]


def _t7_case(rng: np.random.Generator) -> tuple:
    """Known, separated groups; the winner is selected before generating each group's scores."""
    width = float(rng.choice([0.25, 0.5, 1.0, 2.0]))
    matches, expected = [], []
    for group in range(int(rng.integers(1, 7))):
        size = int(rng.integers(1, 7))
        anchor = group * (4.0 * width + 1.0)
        offsets = np.r_[0.0, rng.uniform(0.05, 0.75, size - 1) * width]
        winner = int(rng.integers(size))
        scores = rng.uniform(1.0, 8.0, size)
        scores[winner] = 12.0
        labels = [str(rng.choice(["A", "B", "C", "D"])) for _ in range(size)]
        matches.extend((labels[i], float(anchor + offsets[i]), float(scores[i])) for i in range(size))
        expected.append((float(anchor + offsets[winner]), 12.0, labels[winner], tuple(sorted(set(labels))), size))
    rng.shuffle(matches)
    return "wrong-values", matches, width, expected


def _t7_unpack(value: Any) -> Optional[list]:
    if not isinstance(value, list):
        return None
    clean = []
    for row in value:
        if not isinstance(row, tuple) or len(row) != 5:
            return None
        when, score, representative, sources, count = row
        if _t5_number(when) is None or _t5_number(score) is None or not isinstance(representative, str) or \
                not isinstance(sources, tuple) or not all(isinstance(s, str) for s in sources) or \
                tuple(sorted(set(sources))) != sources or not sources or \
                isinstance(count, (bool, np.bool_)) or not isinstance(count, numbers.Integral) or count < 1:
            return None
        clean.append((float(when), float(score), representative, sources, int(count)))
    return clean


def _t7_judge(value: Any, expected: list, kind: str, tolerance: float) -> Optional[str]:
    actual = _t7_unpack(value)
    if actual is None:
        return "format"
    if any(b[0] < a[0] for a, b in zip(actual, actual[1:])):
        return "time-order"
    if len(actual) != len(expected):
        return kind if kind in {"chaining", "window-edge"} else "wrong-values"
    for got, want in zip(actual, expected):
        if got[3:] != want[3:]:
            return "provenance"
        if abs(got[1] - want[1]) > tolerance:
            return "best-score"
        if abs(got[0] - want[0]) > tolerance or got[2] != want[2]:
            return "ties" if kind == "ties" else "best-score"
    return None


def _t7_protocol_windows(plan: dict, info: dict, start: Any, duration: float, delta: float) -> Optional[str]:
    from obspy import UTCDateTime

    try:
        guard = _t5_number(plan["guard_s"])
        lag = max(abs(float(ch["lag_samples"])) * delta for entry in info["templates"] for ch in entry["channels"])
        minimum = lag + max(float(info["p_len_s"]), float(info["s_len_s"])) + float(info["taper_s"])
        if guard is None or guard < minimum:
            return "windows"
        windows = []
        for field, exposure in (("calibration_window_s", "calibration_live_hours"),
                                ("evaluation_window_s", "evaluation_live_hours")):
            interval = plan[field]
            if not isinstance(interval, list) or len(interval) != 2 or any(_t5_number(v) is None for v in interval):
                return "windows"
            left, right = map(float, interval)
            if not guard <= left < right <= duration - guard:
                return "windows"
            for entry in info["templates"]:
                origin = UTCDateTime(entry["origin_utc"]) - start
                if left < origin + guard and right > origin - guard:
                    return "windows"
            hours = _t5_number(plan[exposure])
            if hours is None or abs(hours - (right - left) / 3600.0) > 1e-9:
                return "exposure"
            windows.append((left, right))
        earlier, later = sorted(windows)
        if earlier[1] + 2.0 * guard > later[0]:
            return "windows"
    except (KeyError, TypeError, ValueError, OverflowError):
        return "report"
    return None


def _t7_artifacts(target: Any, ctx: Any, tolerance: float) -> Optional[str]:
    from obspy import UTCDateTime, read

    report = ctx.get("report")
    if report is None:
        return "no-report"
    if not isinstance(report, dict) or set(report) != {"matching_json", "candidates_csv", "validation_json"}:
        return "report"
    try:
        matching_path, candidate_path, protocol_path = (Path(report[name]) for name in
                                                       ("matching_json", "candidates_csv", "validation_json"))
        info = json.loads(matching_path.read_text(encoding="utf-8"))
        plan = json.loads(protocol_path.read_text(encoding="utf-8"))
        if not isinstance(info, dict) or not isinstance(plan, dict) or set(plan) != T7_PROTOCOL_KEYS:
            return "report"
        entries = {entry["event_id"]: entry for entry in info["templates"]}
        dataset = str(ctx.get("dataset", DATASET_DEFAULT))
        if info["dataset"] != dataset or plan["dataset"] != dataset or not entries:
            return "report"
        if plan["exercise_status"] != "retrospective_teaching_plan" or \
                plan["score_definition"] != "mads_above_median" or plan["template_ids"] != sorted(entries) or \
                not isinstance(plan["bank_version"], str) or not plan["bank_version"].strip():
            return "plan"
        for key in T7_WRITTEN:
            text = plan[key]
            if not isinstance(text, str) or "[write here" in text.lower() or \
                    sum(sum(character.isalpha() for character in word) >= 2 for word in text.split()) < \
                    int(ctx.criteria.get("min_plan_words", 12)):
                return "plan"
        window = _t5_number(plan["merge_window_s"])
        if window is None or window < 0.0:
            return "report"
        raw_path = Path(info["detections_csv"])
        for key, path in (("matching_json_sha256", matching_path), ("matches_csv_sha256", raw_path)):
            if plan[key] != hashlib.sha256(path.read_bytes()).hexdigest():
                return "stale"
        folder = Path(ctx.data_root) / dataset / "stp_download" / "SAC" / EVENT_FOLDER
        headers = sorted(folder.glob("*/*.sac"))
        if not headers:
            return "report"
        stats = [read(str(path), headonly=True)[0].stats for path in headers]
        start = min(head.starttime for head in stats)
        delta = float(stats[0].delta)
        duration = float(max(head.endtime for head in stats) - start)
        problem = _t7_protocol_windows(plan, info, start, duration, delta)
        if problem is not None:
            return problem
        with raw_path.open(encoding="utf-8", newline="") as handle:
            table = csv.DictReader(handle)
            if tuple(table.fieldnames or ()) != T5_COLUMNS:
                return "report"
            matches = []
            for row in table:
                entry = entries[row["template"]]
                mad = _t5_number(entry["mad"])
                if mad is None or mad <= 0.0:
                    return "report"
                score = (float(row["network_cc"]) - float(entry["median"])) / mad
                matches.append((row["template"], float(UTCDateTime(row["time_utc"]) - start), score))
        expected, error = _call(target, matches, float(window))
        if error is not None or _t7_unpack(expected) is None:
            return "candidate-file"
        with candidate_path.open(encoding="utf-8", newline="") as handle:
            table = csv.DictReader(handle)
            if tuple(table.fieldnames or ()) != T7_CANDIDATE_COLUMNS:
                return "candidate-file"
            actual = []
            for row in table:
                when, score = float(row["time_s"]), float(row["score"])
                if abs(float(UTCDateTime(row["time_utc"]) - start) - when) > 1e-6:
                    return "candidate-file"
                actual.append((when, score, row["representative"], tuple(json.loads(row["templates"])),
                               int(row["n_matches"])))
        if _t7_judge(actual, expected, "wrong-values", tolerance) is not None:
            return "candidate-file"
    except (OSError, KeyError, TypeError, ValueError, IndexError, OverflowError):
        return "report"
    return None


def check_T7(target: Any, ctx: Any) -> Outcome:
    tolerance = float(ctx.criteria.get("abs_tol", 1e-9))
    cases = _t7_probes() + [_t7_case(ctx.rng) for _ in range(int(ctx.criteria.get("trials", 100)))]
    passed, categories, example = [], [], None
    for kind, matches, window, expected in cases:
        original = list(matches)
        result, error = _call(target, matches, window)
        category = "format" if error is not None else _t7_judge(result, expected, kind, tolerance)
        if matches != original:
            category = "changed-input"
        passed.append(category is None)
        categories.append(category)
        if category and example is None:
            example = {"inputs": {"matches": original, "window_s": window}, "got": repr(result)[:300],
                       "error": "compared with known groups, winners and provenance on made-up matches"}
    if not all(passed):
        return outcome_from_cases(passed, category=_first(categories, T7_PRIORITY), example=example)
    category = _t7_artifacts(target, ctx, tolerance)
    return outcome_from_cases(passed + [category is None], category=category, real_data=True,
                              note="The candidate file is checked against your own verified merger; the protocol "
                                   "is checked for consistency, not scientific adequacy. Review it with your mentor.")
