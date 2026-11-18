"""Checkers for M10 · Seismograms: reading, filtering, spectra, record sections.

Where the truth comes from (DESIGN.md section 1, rule 1):

* M10-T1: construction, and raw header numbers. The check writes SAC files with ObsPy's SACTrace from
  reference times, b, o and picks that it drew itself. For files of the student's own download it copies each
  file, writes picks straight into the copy's header bytes, and computes the answer from the raw header
  integers with Python's datetime module (no ObsPy reader involved).
* M10-T2: construction. Sums of sines that sit exactly on the frequency grid, with known amplitudes inside and
  outside the band.
* M10-T3: construction. Fresh distances and speeds; only the forward relation (a difference of travel times).
* M10-T4: construction (symmetric pulses at known times after a known origin, stations at known places; the
  distances come from pyproj, a library the student may not use in this task) and, for the student's Sangju
  files, distances from the station coordinates in their headers. Real-data values are never printed.
* M10-T5: the student's own products (a JSON file, a PNG file and the Matplotlib Figure behind it), compared
  with the check's own response removal (ObsPy with the StationMetadata file the student named), the spectral
  peak of the student's own band_amplitude_spectrum (handed over in the answer and run again on made-up cases of
  task 2 first; the checker has no spectrum code) on that velocity record, and the formula stated in the task,
  evaluated on the student's own numbers. The check reads the figure's data: the record panel and the spectrum
  panel must follow those curves in the unit their y labels name, with the PGV and the peak marked and the
  numbers written. Its values stay inside check_T5 and are never printed.

Failure categories are keys of ``checks/specs/M10.yaml``; the engine prints their fixed messages.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import io
import json
import numbers
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import Outcome, outcome_from_cases

__all__ = ["check_T1", "check_T2", "check_T3", "check_T4", "check_T5"]

DATASET_DEFAULT = "sangju2019"
MAIN_EVENT = "2019009762"                 # the ML 3.9 Sangju earthquake of 21 July 2019 (KMA catalog)
UNSET = -12345.0
NINE_HOURS_S = 9 * 3600.0
DAY_S = 86400.0
QUANTUM = 1.0 / 256.0                     # header times on this grid are exact in 32-bit floats


# ------------------------------------------------------------------------------------------- helpers
def _call(func: Any, *args: Any, **kwargs: Any) -> Tuple[Any, Optional[BaseException]]:
    """Run the student's code. NotImplementedError passes through (the engine reports NOT STARTED)."""
    try:
        return func(*args, **kwargs), None
    except NotImplementedError:
        raise
    except Exception as exc:  # noqa: BLE001 - classified by the caller
        return None, exc


def _q(value: float) -> float:
    return round(float(value) / QUANTUM) * QUANTUM


def _scratch(prefix: str) -> Path:
    """A private temporary folder (mode 0700) for files the check writes."""
    return Path(tempfile.mkdtemp(prefix=prefix))


def _first(results: List[Tuple[bool, Optional[str]]], priority: Sequence[str]) -> Optional[str]:
    cats = {cat for good, cat in results if not good and cat}
    return next((c for c in priority if c in cats), None)


def _sac_root(ctx: Any) -> Path:
    name = str(ctx.get("dataset") or DATASET_DEFAULT)
    return Path(ctx.data_root) / name / "stp_download" / "SAC"


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


def _surface_km(lat0: float, lon0: float, lat: Any, lon: Any) -> np.ndarray:
    """Distance along the WGS84 ellipsoid in km (pyproj; the student may not use it in task 4)."""
    from pyproj import Geod

    lat = np.atleast_1d(np.asarray(lat, dtype=float))
    lon = np.atleast_1d(np.asarray(lon, dtype=float))
    _, _, meters = Geod(ellps="WGS84").inv(np.full(lat.shape, lon0), np.full(lat.shape, lat0), lon, lat)
    return np.asarray(meters, dtype=float) / 1000.0


# ---------------------------------------------------------------------- raw SAC headers (no ObsPy)
def _raw_header(path: Path) -> Optional[dict]:
    """Byte order and the time numbers of a SAC header, read with numpy only."""
    blob = Path(path).read_bytes()[:632]
    if len(blob) < 632:
        return None
    for order in ("<", ">"):
        ints = np.frombuffer(blob, dtype=order + "i4", count=40, offset=280)
        if int(ints[6]) == 6:                      # nvhdr, the header version
            floats = np.frombuffer(blob, dtype=order + "f4", count=70)
            return {"order": order, "nz": [int(v) for v in ints[:6]], "b": float(floats[5]),
                    "o": float(floats[7]), "a": float(floats[8]), "t0": float(floats[10])}
    return None


def _patch_picks(path: Path, order: str, a: Optional[float], t0: Optional[float]) -> None:
    """Write the P pick (word 8) and the S pick (word 10) into a SAC header in place."""
    with open(path, "r+b") as fh:
        for word, value in ((8, a), (10, t0)):
            fh.seek(4 * word)
            fh.write(np.array([UNSET if value is None else value], dtype=order + "f4").tobytes())


def _nz_moment(nz: Sequence[int]):
    """The reference time from the six nz integers, by calendar arithmetic of Python's datetime."""
    from obspy import UTCDateTime

    year, jday, hour, minute, second, msec = (int(v) for v in nz)
    clock = _dt.datetime(year, 1, 1, tzinfo=_dt.timezone.utc) + _dt.timedelta(
        days=jday - 1, hours=hour, minutes=minute, seconds=second, milliseconds=msec)
    return UTCDateTime(clock)


# ------------------------------------------------------------------------- M10-T1 pick times
# per case: ranges for b and o (None: o not set), which picks are set, millisecond part, day of the year
T1_SPECS = (
    {"b": (5.0, 40.0), "o": (-5.0, 30.0), "a": True, "t0": True, "jday": (32, 365)},
    {"b": (-40.0, -5.0), "o": (-60.0, -45.0), "a": True, "t0": True, "jday": (1, 28)},
    {"b": (0.0084, 0.0084), "o": (0.0, 0.0), "a": False, "t0": False, "jday": (150, 250)},
    {"b": (10.0, 30.0), "o": None, "a": True, "t0": False, "jday": (60, 200)},
    {"b": (1.0, 9.0), "o": (2.0, 20.0), "a": False, "t0": True, "jday": (2, 27)},
    {"b": (20.0, 60.0), "o": (5.0, 15.0), "a": True, "t0": True, "msec": (999, 999), "jday": (280, 330)},
    {"b": (-3.0, -1.0), "o": (0.5, 2.0), "a": True, "t0": True, "leap_end": True},
    {"b": (60.0, 120.0), "o": (-30.0, -10.0), "a": True, "t0": True, "msec": (100, 900), "jday": (100, 365)},
)
T1_PRIORITY = ("format", "missing-pick", "swapped", "time-zone", "b-offset", "origin-vs-reference",
               "milliseconds", "day-of-year", "wrong-values")


def _t1_case(rng: np.random.Generator, spec: dict, folder: Path, number: int) -> Tuple[Path, dict]:
    """Write one SAC file; return its path and what the check knows about it."""
    from obspy.io.sac import SACTrace

    if spec.get("leap_end"):
        year = int(rng.choice([2016, 2020, 2024, 2028]))
        jday, hour, minute, second = 366, 23, 59, int(rng.integers(56, 60))
    else:
        year = int(rng.integers(2001, 2031))
        lo, hi = spec.get("jday", (1, 365))
        jday = int(rng.integers(lo, hi + 1))
        hour, minute, second = int(rng.integers(0, 24)), int(rng.integers(0, 60)), int(rng.integers(0, 60))
    lo, hi = spec.get("msec", (0, 0))
    msec = int(rng.integers(lo, hi + 1))
    b_lo, b_hi = spec["b"]
    b = b_lo if b_lo == b_hi else _q(rng.uniform(b_lo, b_hi))
    o = None if spec["o"] is None else (spec["o"][0] if spec["o"][0] == spec["o"][1] else _q(rng.uniform(*spec["o"])))
    a = _q(b + rng.uniform(5.0, 60.0))
    t0 = _q(a + rng.uniform(2.0, 35.0))
    header = {"nzyear": year, "nzjday": jday, "nzhour": hour, "nzmin": minute, "nzsec": second, "nzmsec": msec,
              "b": b, "delta": 0.05, "knetwk": "XX", "kstnm": f"CK{number:02d}", "kcmpnm": "HHZ"}
    if o is not None:
        header["o"] = o
    if spec["a"]:
        header["a"] = a
    if spec["t0"]:
        header["t0"] = t0
    path = folder / f"case{number:02d}.XX.CK{number:02d}.HHZ.sac"
    SACTrace(data=rng.normal(0.0, 1.0, 2000).astype(np.float32), **header).write(str(path))
    zero = _nz_moment([year, jday, hour, minute, second, msec])
    info = {"nz": [year, jday, hour, minute, second, msec], "b": float(np.float32(b)),
            "o": None if o is None else float(o), "a": a if spec["a"] else None, "t0": t0 if spec["t0"] else None,
            "p": zero + a if spec["a"] else None, "s": zero + t0 if spec["t0"] else None, "msec": msec, "jday": jday}
    return path, info


def _t1_judge(got: Any, info: dict, tol: float) -> Optional[str]:
    """None when right, else the category of the slip."""
    from obspy import UTCDateTime

    if not isinstance(got, (tuple, list)) or len(got) != 2 or \
            not all(v is None or isinstance(v, UTCDateTime) for v in got):
        return "format"
    want = (info["p"], info["s"])

    def same(value: Any, truth: Any) -> bool:
        if value is None or truth is None:
            return value is None and truth is None
        return abs(float(value - truth)) <= tol

    if same(got[0], want[0]) and same(got[1], want[1]):
        return None
    if want[0] != want[1] and same(got[0], want[1]) and same(got[1], want[0]):
        return "swapped"
    for value, truth in zip(got, want):
        if truth is None and value is not None:
            return "missing-pick"
        if truth is not None and value is None:
            return "wrong-values"
    errors = [float(g - w) for g, w in zip(got, want) if w is not None]
    worst = max(errors, key=abs)
    if abs(abs(worst) - NINE_HOURS_S) <= 1.0:
        return "time-zone"
    if abs(info["b"]) > 10 * tol and all(abs(e - info["b"]) <= tol for e in errors):
        return "b-offset"
    o = info["o"]
    if o is not None and abs(o) > 10 * tol and (all(abs(e - o) <= tol for e in errors) or
                                                  all(abs(e + o) <= tol for e in errors)):
        return "origin-vs-reference"
    ms = info["msec"] / 1000.0
    if ms > 10 * tol and any(abs(e + ms) <= tol or abs(e + ms - ms / 1000.0) <= tol for e in errors):
        return "milliseconds"
    if abs(worst) >= DAY_S - 1.0 and abs(worst / DAY_S - round(worst / DAY_S)) * DAY_S <= 1.0:
        return "day-of-year"
    return "wrong-values"


def _t1_real(rng: np.random.Generator, files: List[Path], count: int, folder: Path) -> List[Tuple[Path, dict]]:
    """Copies of the student's files, most of them with picks written into the raw header."""
    cases = []
    for path in rng.permutation(np.array(files, dtype=object)):
        if len(cases) >= count:
            break
        raw = _raw_header(Path(path))
        if raw is None or raw["nz"][0] == int(UNSET):
            continue
        copy = folder / f"real{len(cases):02d}.sac"
        shutil.copyfile(path, copy)
        a = t0 = None
        if len(cases) < count - 3:
            a = _q(raw["b"] + rng.uniform(3.0, 60.0))
            t0 = _q(a + rng.uniform(2.0, 30.0))
            _patch_picks(copy, raw["order"], a, t0)
        else:
            a = None if raw["a"] == UNSET else raw["a"]
            t0 = None if raw["t0"] == UNSET else raw["t0"]
        zero = _nz_moment(raw["nz"])
        cases.append((copy, {"nz": raw["nz"], "b": raw["b"], "o": None if raw["o"] == UNSET else raw["o"],
                             "a": a, "t0": t0, "p": None if a is None else zero + a,
                             "s": None if t0 is None else zero + t0, "msec": raw["nz"][5], "jday": raw["nz"][1]}))
    return cases


def check_T1(target: Any, ctx: Any) -> Outcome:
    tol = float(ctx.criteria.get("tol_s", 1e-4))
    trials = max(2, min(len(T1_SPECS), int(ctx.criteria.get("trials", len(T1_SPECS)))))
    n_real = int(ctx.criteria.get("real_files", 10))
    folder = _scratch("sgtl-m10-t1-")
    try:
        results: List[Tuple[bool, Optional[str]]] = []
        example = None
        crashed: List[Tuple[BaseException, dict]] = []
        for number, spec in enumerate(T1_SPECS[:trials]):
            path, info = _t1_case(ctx.rng, spec, folder, number)
            got, err = _call(target, str(path) if number % 2 else path)
            if err is not None:
                crashed.append((err, info))
                results.append((False, None))
                continue
            cat = _t1_judge(got, info, tol)
            results.append((cat is None, cat))
            if cat is not None and example is None:
                shown = {k: info[k] for k in ("b", "o", "a", "t0")}
                shown["nz (year, day of year, hour, minute, second, ms)"] = info["nz"]
                example = {"inputs": shown, "got": [None if v is None else str(v) for v in got]
                           if isinstance(got, (tuple, list)) else repr(got)}
        if crashed:
            if all(info["a"] is None or info["t0"] is None for _, info in crashed) and \
                    len(crashed) < len(results):
                results = [(good, cat) if cat or good else (False, "missing-pick") for good, cat in results]
            elif all(info["jday"] > 28 for _, info in crashed) and len(crashed) < len(results):
                results = [(good, cat) if cat or good else (False, "day-of-year") for good, cat in results]
            else:
                raise crashed[0][0]
        category = _first(results, T1_PRIORITY)
        if category is not None:
            return outcome_from_cases([good for good, _ in results], category=category, example=example)

        # the student's own files
        root = _sac_root(ctx)
        files = sorted(root.glob("*/*/*.sac")) if root.is_dir() else []
        if len(files) < n_real:
            return outcome_from_cases([True] * len(results) + [False], category="no-data")
        real_results: List[Tuple[bool, Optional[str]]] = []
        for copy, info in _t1_real(ctx.rng, files, n_real, folder):
            got, err = _call(target, copy)
            if err is not None:
                cat = "missing-pick" if info["a"] is None or info["t0"] is None else None
                if cat is None:
                    raise err
            else:
                cat = _t1_judge(got, info, tol)
            real_results.append((cat is None, cat))
        category = _first(real_results, T1_PRIORITY)
        return outcome_from_cases([good for good, _ in results + real_results], category=category, real_data=True,
                                  note=f"{len(results)} files written by the check and {len(real_results)} of your "
                                       "own files (copies; their answers are not printed).")
    finally:
        shutil.rmtree(folder, ignore_errors=True)


# --------------------------------------------------------------------- M10-T2 band amplitude spectrum
# (sampling rate in Hz, number of samples, fmin, fmax, whole-number data)
T2_SPECS = (
    (100.0, 6000, 1.0, 10.0, False),
    (100.0, 5001, 2.0, 8.0, True),
    (40.0, 4000, 0.5, 4.0, False),
    (200.0, 12000, 2.0, 20.0, False),
    (20.0, 2401, 0.2, 2.0, True),
    (50.0, 3000, 1.0, 5.0, False),
    (100.0, 30001, 0.5, 5.0, False),
    (250.0, 10000, 5.0, 40.0, True),
)
T2_PRIORITY = ("format", "changed-input", "nyquist", "normalization", "corner-units", "no-filter", "filter-order",
               "wrong-values")


def _t2_case(rng: np.random.Generator, spec: tuple):
    """A Trace made of sines on the frequency grid; returns it, the sines and the grid step.

    Inside the band: one sine at each end of its safe part (1.8 fmin and fmax / 1.8) and one near its middle;
    outside: one sine at fmin / 2.5 and one at 2.5 fmax (the nearest grid points beyond them).
    """
    from obspy import Trace, UTCDateTime

    rate, npts, fmin, fmax, whole = spec
    step = rate / npts                                   # the grid of the check: k * rate / npts
    scale = 1000.0 if whole else 1.0
    bottom, top = int(np.ceil(1.8 * fmin / step)), int(np.floor(fmax / 1.8 / step))
    middle = int(np.clip(round(rng.uniform(0.9, 1.1) * np.sqrt(fmin * fmax) / step), bottom + 2, top - 2))
    low, high = int(np.floor(fmin / 2.5 / step)), int(np.ceil(2.5 * fmax / step))
    sines = [(bottom, "bottom"), (middle, "middle"), (top, "top"), (low, "low"), (high, "high")]
    sines = [(k, rng.uniform(1.0, 5.0) * scale, where) for k, where in sines]
    t = np.arange(npts) / rate
    signal = np.full(npts, rng.uniform(-3.0, 3.0) * scale)
    for k, amp, _ in sines:
        signal += amp * np.sin(2.0 * np.pi * (k * step) * t + rng.uniform(0.0, 2.0 * np.pi))
    data = np.round(signal).astype(np.int32) if whole else signal
    start = UTCDateTime(2019, 7, 21, 2, 3, 48) + float(rng.uniform(0.0, 86400.0))
    tr = Trace(data=data, header={"sampling_rate": rate, "starttime": start, "network": "XX", "station": "SPEC",
                                  "channel": "HHZ"})
    return tr, sines, step


def _t2_judge(got: Any, tr, pristine, sines, step: float, crit: dict) -> Tuple[Optional[str], dict]:
    if not isinstance(got, (tuple, list)) or len(got) != 2:
        return "format", {}
    try:
        freqs = np.asarray(got[0], dtype=float)
        amps = np.asarray(got[1], dtype=float)
    except (TypeError, ValueError):
        return "format", {}
    if freqs.ndim != 1 or amps.ndim != 1 or freqs.size != amps.size or freqs.size == 0 or \
            not (np.all(np.isfinite(freqs)) and np.all(np.isfinite(amps))):
        return "format", {}
    if not (np.array_equal(np.asarray(tr.data), pristine.data) and tr.stats.npts == pristine.stats.npts
            and tr.stats.starttime == pristine.stats.starttime and tr.stats.delta == pristine.stats.delta):
        return "changed-input", {}
    npts = pristine.stats.npts
    grid = np.arange(npts // 2 + 1) * step
    if freqs.size != grid.size or np.max(np.abs(freqs - grid)) > float(crit.get("freq_rel_tol", 1e-6)) * grid[-1]:
        return "nyquist", {"got": f"{freqs.size} frequencies from {freqs[0]:.4g} to {freqs[-1]:.4g} Hz"}
    ratio = {where: amps[k] / a for k, a, where in sines}
    inside = np.array([ratio["bottom"], ratio["middle"], ratio["top"]])
    outside = np.array([ratio["low"], ratio["high"]])
    shown = {"got": [round(float(amps[k]), 6) for k, _, _ in sines],
             "error": "amplitude ratios " + ", ".join(f"{amps[k] / a:.4g} at {k * step:.4g} Hz" for k, a, _ in sines)}
    tol_in = float(crit.get("in_band_rel_tol", 0.05))
    limit = 10.0 ** (-float(crit.get("out_band_db", 20.0)) / 20.0)
    if np.all(np.abs(inside - 1.0) <= tol_in):
        if np.any(outside > 0.8):
            return "no-filter", shown
        if np.any(outside > limit):
            return "filter-order", shown
        return None, shown
    if inside.min() > 0 and inside.max() / inside.min() - 1.0 <= 0.02 and abs(np.median(inside) - 1.0) > tol_in:
        return "normalization", shown                    # every in-band sine off by the same factor
    if np.any(inside < 0.5):
        return "corner-units", shown
    gentle = abs(ratio["middle"] - 1.0) <= 2 * tol_in and min(ratio["bottom"], ratio["top"]) < ratio["middle"]
    if gentle or np.any(outside > limit):                # a gentle filter eats into the band's edges
        return "filter-order", shown
    return "wrong-values", shown


def check_T2(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    trials = max(2, min(len(T2_SPECS), int(crit.get("trials", len(T2_SPECS)))))
    results: List[Tuple[bool, Optional[str]]] = []
    example = None
    for spec in T2_SPECS[:trials]:
        tr, sines, step = _t2_case(ctx.rng, spec)
        pristine = tr.copy()
        got, err = _call(target, tr, spec[2], spec[3])
        if err is not None:
            raise err
        cat, shown = _t2_judge(got, tr, pristine, sines, step, crit)
        results.append((cat is None, cat))
        if cat is not None and example is None:
            example = {"inputs": {"sampling_rate": spec[0], "npts": spec[1], "fmin": spec[2], "fmax": spec[3],
                                  "sines (Hz, amplitude, inside the band)":
                                      [(round(k * step, 6), round(float(a), 4), ins) for k, a, ins in sines]}}
            example.update(shown)
    category = _first(results, T2_PRIORITY)
    return outcome_from_cases([good for good, _ in results], category=category, example=example)


# ---------------------------------------------------------------------------- M10-T3 S-P distance
def _t3_judge(got: Any, truth: np.ndarray, sp: np.ndarray, vp: np.ndarray, vs: np.ndarray, scalar: bool,
              rel: float) -> Tuple[np.ndarray, Optional[str]]:
    if scalar:
        if isinstance(got, (bool, np.bool_)) or not isinstance(got, numbers.Real):
            return np.zeros(1, dtype=bool), "format"
        values = np.array([float(got)])
    else:
        if not isinstance(got, np.ndarray) or got.shape != truth.shape:
            return np.zeros(truth.size, dtype=bool), "format"
        values = got.astype(float)
    ok = np.isfinite(values) & (np.abs(values - truth) <= rel * np.abs(truth))
    if ok.all():
        return ok, None
    bad = ~ok
    ratio = values[bad] / truth[bad]
    if np.all(np.abs(ratio + 1.0) <= 1e-3):
        return ok, "swapped"
    if np.all((np.abs(ratio / 1000.0 - 1.0) <= 1e-3) | (np.abs(ratio * 1000.0 - 1.0) <= 1e-3)):
        return ok, "units"
    one = np.abs(values[bad] - sp[bad] * vp[bad]) <= 1e-6 * np.abs(sp[bad] * vp[bad]) + 1e-12
    two = np.abs(values[bad] - sp[bad] * vs[bad]) <= 1e-6 * np.abs(sp[bad] * vs[bad]) + 1e-12
    if np.all(one | two):
        return ok, "one-speed"
    return ok, "wrong-values"


def check_T3(target: Any, ctx: Any) -> Outcome:
    trials = max(20, int(ctx.criteria.get("trials", 200)))
    rel = float(ctx.criteria.get("rel_tol", 1e-6))
    rng = ctx.rng
    dist = rng.uniform(1.0, 300.0, trials)
    vp = rng.uniform(5.0, 8.0, trials)
    vs = vp / rng.uniform(1.6, 1.9, trials)
    sp = dist / vs - dist / vp                       # the forward relation: S travel time minus P travel time
    n_scalar = trials // 2
    oks: List[np.ndarray] = []
    cats: List[str] = []
    example = None
    for i in range(n_scalar):
        got, err = _call(target, float(sp[i]), float(vp[i]), float(vs[i]))
        if err is not None:
            raise err
        ok, cat = _t3_judge(got, dist[i:i + 1], sp[i:i + 1], vp[i:i + 1], vs[i:i + 1], True, rel)
        oks.append(ok)
        if cat:
            cats.append(cat)
            if example is None:
                example = {"inputs": {"sp_s": round(float(sp[i]), 6), "vp": round(float(vp[i]), 6),
                                      "vs": round(float(vs[i]), 6)}, "got": got,
                           "error": f"the distance was {dist[i]:.6g} km"}
    common_vp, common_vs = float(vp[n_scalar]), float(vs[n_scalar])
    rest = dist[n_scalar:]
    sp_rest = rest / common_vs - rest / common_vp
    got, err = _call(target, sp_rest.copy(), common_vp, common_vs)
    if err is not None:
        raise err
    ok, cat = _t3_judge(got, rest, sp_rest, np.full(rest.size, common_vp), np.full(rest.size, common_vs), False, rel)
    oks.append(ok)
    if cat:
        cats.append(cat)
        if example is None:
            example = {"inputs": {"sp_s": "an array of " + str(rest.size) + " values", "vp": common_vp,
                                  "vs": common_vs}, "got": type(got).__name__ if not isinstance(got, np.ndarray)
                       else f"array of shape {got.shape}"}
    priority = ("format", "swapped", "units", "one-speed", "wrong-values")
    category = next((c for c in priority if c in cats), None)
    all_ok = np.concatenate(oks)
    if category == "format" and all_ok.all():
        all_ok = np.append(all_ok, False)
    return outcome_from_cases(all_ok, category=category, example=example)


# -------------------------------------------------------------------------- M10-T4 record section
# (number of traces, sampling rate, given as, scale_km, fmin, fmax, whole-number data)
T4_SPECS = (
    (6, 100.0, "stream", 2.0, 1.0, 10.0, False),
    (9, 100.0, "files", 1.5, 1.0, 10.0, True),
    (12, 50.0, "stream", 3.0, 0.5, 8.0, False),
    (7, 100.0, "files", 2.0, 2.0, 12.0, False),
    (8, 200.0, "stream", 1.0, 1.0, 15.0, True),
)
T4_PRIORITY = ("format", "not-printed", "changed-input", "sorting", "distance", "lines", "position", "time-axis",
               "scaling", "zero-phase", "peak", "labels", "wrong-values")
T4_COLUMNS = ("id", "epi_km", "hypo_km", "peak")


def _ricker(t: np.ndarray, center: float, f0: float) -> np.ndarray:
    arg = (np.pi * f0 * (t - center)) ** 2
    return (1.0 - 2.0 * arg) * np.exp(-arg)


def _t4_section(rng: np.random.Generator, spec: tuple, folder: Path, number: int):
    """A made-up record section: Stream (or SAC paths), origin, hypocenter and the truth for every trace."""
    from obspy import Stream, Trace, UTCDateTime
    from obspy.core.util import AttribDict

    n, rate, given_as, scale_km, fmin, fmax, whole = spec
    ev_lat, ev_lon, depth = rng.uniform(34.5, 37.5), rng.uniform(126.8, 129.2), rng.uniform(3.0, 20.0)
    while True:
        along = np.sort(rng.uniform(5.0, 150.0, n))
        if np.min(np.diff(along)) >= 4.0:
            break
    bearing = rng.uniform(0.0, 2.0 * np.pi, n)
    sta_lat = ev_lat + along * np.cos(bearing) / 111.2
    sta_lon = ev_lon + along * np.sin(bearing) / (111.2 * np.cos(np.radians(ev_lat)))
    epi = _surface_km(ev_lat, ev_lon, sta_lat, sta_lon)
    hypo = np.hypot(epi, depth)
    origin = UTCDateTime(2020, 1, 1) + float(np.round(rng.uniform(0.0, 5 * 365 * 86400.0), 2))
    f0 = rng.uniform(2.0 * fmin, fmax / 2.5)
    codes = rng.choice(np.arange(100, 1000), n, replace=False)
    duration = float(np.ceil(hypo.max() / 6.0 + 25.0))
    traces, truth = [], []
    for i in range(n):
        lead = np.round(rng.uniform(5.0, 20.0) * rate) / rate      # seconds of record before the origin
        npts = int(round((duration + lead) * rate))
        t_rel = -lead + np.arange(npts) / rate
        center = float(hypo[i] / 6.0)
        amp = rng.uniform(0.5, 50.0) * (1000.0 if whole else 1.0)
        values = amp * _ricker(t_rel, center, f0) + rng.normal(0.0, 0.003 * amp, npts)
        data = np.round(values).astype(np.int32) if whole else values
        tr = Trace(data=data, header={"network": "XS", "station": f"S{codes[i]}", "location": "", "channel": "HHZ",
                                      "sampling_rate": rate, "starttime": origin - lead})
        tr.stats.sac = AttribDict({"stla": float(sta_lat[i]), "stlo": float(sta_lon[i])})
        traces.append(tr)
        truth.append({"id": tr.id, "station": tr.stats.station, "epi": float(epi[i]), "hypo": float(hypo[i]),
                      "start": -lead, "end": -lead + (npts - 1) / rate, "center": center, "amp": amp, "npts": npts})
    order = rng.permutation(n)
    stream = Stream([traces[i] for i in order])
    if given_as == "files":
        paths = []
        for i, tr in enumerate(stream):
            path = folder / f"sec{number}_{i:02d}.{tr.id}.sac"
            tr.write(str(path), format="SAC")
            paths.append(str(path) if i % 2 else path)
        given: Any = paths
    else:
        given = stream
    return given, stream, origin, (float(ev_lat), float(ev_lon), float(depth)), truth, spec


def _run_section(target: Any, given: Any, origin, hypocenter: Tuple[float, float, float], **kwargs: Any):
    """Call the student's function with stdout captured; returns (result, printed text, error, new figures)."""
    import matplotlib.pyplot as plt

    before = set(plt.get_fignums())
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        got, err = _call(target, given, origin, *hypocenter, **kwargs)
    made = [num for num in plt.get_fignums() if num not in before]
    return got, buffer.getvalue(), err, made


def _close(numbers_: List[int], got: Any) -> None:
    import matplotlib.pyplot as plt

    for num in numbers_:
        plt.close(num)
    if isinstance(got, (tuple, list)) and got:
        with contextlib.suppress(Exception):
            plt.close(got[0])


def _t4_table(got: Any, n: int):
    import pandas as pd
    from matplotlib.figure import Figure

    if not isinstance(got, (tuple, list)) or len(got) != 2:
        return None, None
    fig, table = got
    if not isinstance(fig, Figure) or not isinstance(table, pd.DataFrame) or len(table) != n or \
            not set(T4_COLUMNS) <= set(table.columns):
        return None, None
    try:
        numeric = {c: pd.to_numeric(table[c]).to_numpy(dtype=float) for c in ("epi_km", "hypo_km", "peak")}
    except (TypeError, ValueError):
        return None, None
    if not all(np.all(np.isfinite(v)) for v in numeric.values()):
        return None, None
    return fig, {"id": [str(v) for v in table["id"]], **numeric}


def _printed_in_order(text: str, ids: List[str]) -> bool:
    where, pos = [], 0
    for tid in ids:
        found = text.find(tid, pos)
        if found < 0:
            return False
        where.append(found)
        pos = found + len(tid)
    return True


def _t4_judge(fig, table: dict, printed: str, truth: List[dict], stream_before, stream_after, scale_km: float,
              crit: dict) -> Optional[str]:
    from matplotlib.lines import Line2D

    if not _printed_in_order(printed, table["id"]):
        return "not-printed"
    if stream_before is not None:
        for old, new in zip(stream_before, stream_after):
            if old.stats.npts != new.stats.npts or not np.array_equal(old.data, new.data) or \
                    old.stats.starttime != new.stats.starttime:
                return "changed-input"
    hypo_s = table["hypo_km"]
    if np.any(np.diff(hypo_s) < -1e-9):
        return "sorting"
    by_id = {row["id"]: row for row in truth}
    if set(table["id"]) != set(by_id):
        return "distance"
    rel, absolute = float(crit.get("dist_rel_tol", 0.01)), float(crit.get("dist_abs_tol_km", 0.1))
    for tid, epi, hypo in zip(table["id"], table["epi_km"], hypo_s):
        row = by_id[tid]
        if abs(epi - row["epi"]) > rel * row["epi"] + absolute or \
                abs(hypo - row["hypo"]) > rel * row["hypo"] + absolute:
            return "distance"
    min_len = 0.5 * min(r["npts"] for r in truth)
    lines = [ln for ax in fig.axes for ln in ax.get_lines() if isinstance(ln, Line2D)
             and np.asarray(ln.get_xdata()).size >= max(50, min_len)]
    if len(lines) != len(truth):
        return "lines"
    middles = [float(np.median(np.asarray(ln.get_ydata(), dtype=float))) for ln in lines]
    lines = [ln for _, ln in sorted(zip(middles, lines), key=lambda pair: pair[0])]
    middles = sorted(middles)
    rows = [by_id[tid] for tid in table["id"]]                 # the student's order, closest first
    for middle, row in zip(middles, rows):
        if abs(middle - row["hypo"]) > 0.25 * scale_km + 0.1 + rel * row["hypo"] + absolute:
            return "position"
    time_tol = float(crit.get("time_tol_s", 0.03))
    peak_ratio = []
    for ln, row, own_hypo, own_peak in zip(lines, rows, hypo_s, table["peak"]):
        x = np.asarray(ln.get_xdata(), dtype=float)
        y = np.asarray(ln.get_ydata(), dtype=float)
        step = (row["end"] - row["start"]) / max(1, x.size - 1)
        if abs(x[0] - row["start"]) > 1.5 * step or abs(x[-1] - row["end"]) > 1.5 * step:
            return "time-axis"
        swing = np.abs(y - own_hypo)
        if abs(swing.max() - scale_km) > float(crit.get("scale_rel_tol", 0.02)) * scale_km:
            return "scaling"
        if abs(x[int(np.argmax(swing))] - row["center"]) > time_tol:
            return "zero-phase"
        peak_ratio.append(own_peak / row["amp"])
    peak_ratio = np.asarray(peak_ratio)
    if np.any(peak_ratio <= 0) or peak_ratio.max() / peak_ratio.min() - 1.0 > float(crit.get("peak_rel_tol", 0.03)):
        return "peak"
    axes = [ax for ax in fig.axes if ax.get_lines()]
    xlabel = " ".join(ax.get_xlabel() for ax in axes).lower()
    ylabel = " ".join(ax.get_ylabel() for ax in axes).lower()
    texts = " ".join(t.get_text() for ax in fig.axes for t in ax.texts)
    if "origin" not in xlabel or "(s)" not in xlabel or "(km)" not in ylabel or \
            not all(row["station"] in texts for row in truth):
        return "labels"
    return None


def _main_event_files(ctx: Any) -> Tuple[Optional[dict], List[Path]]:
    event = _event(MAIN_EVENT)
    if event is None:
        return None, []
    folder = _sac_root(ctx) / event["origin"].strftime("%Y%m%d%H%M%S") / "HH"
    return event, (sorted(folder.glob("*HHZ.sac")) if folder.is_dir() else [])


def check_T4(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    trials = max(2, min(len(T4_SPECS), int(crit.get("trials", len(T4_SPECS)))))
    n_real = int(crit.get("real_files", 6))
    folder = _scratch("sgtl-m10-t4-")
    results: List[Tuple[bool, Optional[str]]] = []
    example = None
    try:
        for number, spec in enumerate(T4_SPECS[:trials]):
            given, stream, origin, hypocenter, truth, _ = _t4_section(ctx.rng, spec, folder, number)
            before = stream.copy() if spec[2] == "stream" else None
            got, printed, err, made = _run_section(target, given, origin, hypocenter, fmin=spec[4], fmax=spec[5],
                                                   scale_km=spec[3])
            try:
                if err is not None:
                    raise err
                fig, table = _t4_table(got, len(truth))
                cat = "format" if fig is None else _t4_judge(fig, table, printed, truth, before,
                                                             stream if before is not None else None, spec[3], crit)
            finally:
                _close(made, got)
            results.append((cat is None, cat))
            if cat is not None and example is None:
                example = {"inputs": {"traces": spec[0], "given as": "Stream" if spec[2] == "stream" else "SAC paths",
                                      "origin": str(origin), "hypocenter (lat, lon, depth km)":
                                          [round(v, 4) for v in hypocenter], "fmin": spec[4], "fmax": spec[5],
                                      "scale_km": spec[3]}}
        category = _first(results, T4_PRIORITY)
        if category is not None:
            return outcome_from_cases([good for good, _ in results], category=category, example=example)

        # the student's own Sangju files
        event, files = _main_event_files(ctx)
        if event is None or len(files) < n_real:
            return outcome_from_cases([True] * len(results) + [False], category="no-data")
        from obspy import read

        chosen = [Path(p) for p in ctx.rng.choice(np.array(files, dtype=object), n_real, replace=False)]
        heads = [read(str(p), headonly=True)[0] for p in chosen]
        epi = _surface_km(event["lat"], event["lon"], [h.stats.sac.stla for h in heads],
                          [h.stats.sac.stlo for h in heads])
        truth = [{"id": h.id, "epi": float(e), "hypo": float(np.hypot(e, event["depth"]))} for h, e in zip(heads, epi)]
        got, printed, err, made = _run_section(target, chosen, event["origin"],
                                               (event["lat"], event["lon"], event["depth"]))
        try:
            if err is not None:
                raise err
            fig, table = _t4_table(got, len(truth))
            cat = None
            if fig is None:
                cat = "format"
            elif not _printed_in_order(printed, table["id"]):
                cat = "not-printed"
            elif np.any(np.diff(table["hypo_km"]) < -1e-9):
                cat = "sorting"
            else:
                by_id = {row["id"]: row for row in truth}
                rel, absolute = float(crit.get("dist_rel_tol", 0.01)), float(crit.get("dist_abs_tol_km", 0.1))
                if set(table["id"]) != set(by_id) or any(
                        abs(e - by_id[t]["epi"]) > rel * by_id[t]["epi"] + absolute or
                        abs(h - by_id[t]["hypo"]) > rel * by_id[t]["hypo"] + absolute
                        for t, e, h in zip(table["id"], table["epi_km"], table["hypo_km"])):
                    cat = "distance"
                elif sum(1 for ax in fig.axes for ln in ax.get_lines() if np.asarray(ln.get_xdata()).size >= 1000) \
                        != len(truth):
                    cat = "lines"
        finally:
            _close(made, got)
        results.append((cat is None, cat))
        return outcome_from_cases([good for good, _ in results], category=cat, real_data=True,
                                  note=f"{len(results) - 1} made-up sections and one of {n_real} of your own HHZ "
                                       "files (its distances are not printed).")
    finally:
        shutil.rmtree(folder, ignore_errors=True)


# ---------------------------------------------------------------------- M10-T5 PGV and expectation
T5_KEYS = ("sac_path", "stationxml", "event_id", "ml", "hypo_km", "pgv_m_s", "f_peak_hz", "expected_pgv_m_s",
           "ratio")
T5_NUMBERS = ("ml", "hypo_km", "pgv_m_s", "f_peak_hz", "expected_pgv_m_s", "ratio")
T5_PRE_FILT = (0.3, 0.6, 30.0, 40.0)             # PRE_FILT_HZ of the notebook (and M03)
T5_BAND_HZ = (1.0, 20.0)                         # FPEAK_BAND_HZ of the notebook
T5_SHOWN_S = (-5.0, 40.0)                        # the record panel, in seconds after the origin
T5_UNITS = {"m": 1.0, "mm": 1e3, "um": 1e6, "µm": 1e6, "μm": 1e6}
T5_UNIT_TEXT = re.compile(r"(?<![A-Za-zµμ])(mm|um|µm|μm|m)\s*/\s*s(?![A-Za-z])")
T5_NUMBER_TEXT = re.compile(r"(?<![\w.])(\d+\.?\d*|\.\d+)(?:[eE]([-+]?\d{1,3}))?")


def _t5_fail(category: str, passed_before: int, note: str) -> Outcome:
    return outcome_from_cases([True] * passed_before + [False], category=category, real_data=True, note=note)


def _t5_xy(line: Any) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """The finite points of a plotted line, or None when its data are not numbers."""
    try:
        xs = np.asarray(line.get_xdata(), dtype=float).ravel()
        ys = np.asarray(line.get_ydata(), dtype=float).ravel()
    except (TypeError, ValueError):
        return None
    if xs.size == 0 or xs.size != ys.size:
        return None
    good = np.isfinite(xs) & np.isfinite(ys)
    return xs[good], ys[good]


def _t5_unit(ax: Any) -> Optional[float]:
    """How many of the y label's units make one m/s (m/s, mm/s or um/s), or None without such a unit."""
    found = T5_UNIT_TEXT.search(str(ax.get_ylabel() or ""))
    return T5_UNITS[found.group(1)] if found else None


def _t5_panel(fig: Any, grid: np.ndarray, own: np.ndarray, span: Tuple[float, float], edge: float, crit: dict,
              cut: bool) -> Optional[Tuple[Any, Any]]:
    """The axes and the line of a long curve over `span` that follows the check's own curve in its axes' unit.

    cut: the panel must show `span` only (data or x limits within `edge` of it); else it may show more.
    """
    factor = float(crit.get("pgv_factor", 1.5))
    least = float(crit.get("figure_corr_min", 0.9))
    lo, hi = span
    for ax in fig.axes:
        scale = _t5_unit(ax)
        if scale is None:
            continue
        x_lo, x_hi = sorted(float(v) for v in ax.get_xlim())
        for line in ax.get_lines():
            points = _t5_xy(line)
            if points is None or points[0].size < 100:
                continue
            xs, ys = points
            if xs.min() > lo + edge or xs.max() < hi - edge:
                continue
            if cut and (xs.min() < lo - edge or xs.max() > hi + edge) and \
                    not (lo - edge <= x_lo <= lo + edge and hi - edge <= x_hi <= hi + edge):
                continue
            used = (xs >= lo) & (xs <= hi)
            if np.count_nonzero(used) < 50:
                continue
            mine, theirs = scale * np.interp(xs[used], grid, own), ys[used]
            size = float(np.max(np.abs(mine)))
            if size <= 0 or not 1.0 / factor <= float(np.max(np.abs(theirs))) / size <= factor:
                continue
            if np.std(theirs) == 0 or np.std(mine) == 0:
                continue
            match = float(np.corrcoef(theirs, mine)[0, 1])
            if not np.isfinite(match) or match < least:
                continue
            return ax, line
    return None


def _t5_marks(ax: Any, skip: Any) -> List[Tuple[float, Optional[float]]]:
    """Marked points of a panel (x, y), with y None for a vertical line: short lines, scatter dots, annotations."""
    marks: List[Tuple[float, Optional[float]]] = []
    for line in ax.get_lines():
        points = None if line is skip else _t5_xy(line)
        if points is None:
            continue
        xs, ys = points
        if xs.size == 2 and xs[0] == xs[1]:
            marks.append((float(xs[0]), None))
        elif xs.size <= 3:
            marks.extend((float(a), float(b)) for a, b in zip(xs, ys))
    for group in ax.collections:
        if hasattr(group, "get_segments"):
            for seg in group.get_segments():
                seg = np.asarray(seg, dtype=float)
                if seg.ndim == 2 and seg.shape[0] == 2 and seg[0, 0] == seg[1, 0]:
                    marks.append((float(seg[0, 0]), None))
            continue
        try:
            dots = np.asarray(group.get_offsets(), dtype=float).reshape(-1, 2)
        except (TypeError, ValueError):
            continue
        if len(dots) <= 3:
            marks.extend((float(a), float(b)) for a, b in dots)
    for label in ax.texts:
        where = getattr(label, "xy", None)
        if where is not None and getattr(label, "xycoords", None) == "data":
            try:
                marks.append((float(where[0]), float(where[1])))
            except (TypeError, ValueError, IndexError):
                pass
    return marks


def _t5_words(fig: Any) -> str:
    """All text written in a figure: figure texts and titles, axes titles, texts, annotations and legends."""
    parts = [t.get_text() for t in fig.texts]
    legends = list(getattr(fig, "legends", []))
    for ax in fig.axes:
        parts += [ax.get_title(loc=where) for where in ("left", "center", "right")]
        parts += [t.get_text() for t in ax.texts]
        if ax.get_legend() is not None:
            legends.append(ax.get_legend())
    for legend in legends:
        parts += [t.get_text() for t in legend.get_texts()]
    return "\n".join(str(p) for p in parts)


def _t5_written(text: str, value: float, scales: Sequence[float]) -> bool:
    """True when `text` holds `value` (times one of `scales`) with at least two significant digits."""
    for found in T5_NUMBER_TEXT.finditer(text):
        body, power = found.group(1), found.group(2)
        if len(body.replace(".", "").lstrip("0")) < 2:
            continue
        places = len(body.split(".", 1)[1]) if "." in body else 0
        try:
            lift = 10.0 ** int(power) if power else 1.0
        except OverflowError:
            continue
        shown, last_digit = float(body) * lift, lift * 10.0 ** (-places)
        if any(abs(shown - value * s) <= 1.0001 * last_digit for s in scales):
            return True
    return False


T5_TARGET_KEYS = {"json", "png", "figure", "spectrum"}
T5_SPECTRUM_CASES = (0, 2, 4)                    # the T2 cases the spectrum function must pass again (40-100 Hz)
T2_RULES = ("sgtl_tutorial",)                    # the forbidden list of M10-T2 (checks/specs/M10.yaml)


def _t5_own_spectrum(spectrum: Any, rng: np.random.Generator, crit: dict) -> bool:
    """True when the student's band_amplitude_spectrum passes made-up cases of task 2 again (sines of known
    amplitude, truth by construction) under the library rule of task 2."""
    from .. import astguard

    if not callable(spectrum) or not astguard.check_function(spectrum, T2_RULES).ok:
        return False
    for number in T5_SPECTRUM_CASES:
        spec = T2_SPECS[number]
        tr, sines, step = _t2_case(rng, spec)
        pristine = tr.copy()
        got, err = _call(spectrum, tr, spec[2], spec[3])
        if err is not None:
            raise err
        if _t2_judge(got, tr, pristine, sines, step, crit)[0] is not None:
            return False
    return True


def check_T5(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    note = ("The check read your JSON file and your figure, removed the response itself and used your own "
            "band_amplitude_spectrum; it never prints its values.")
    if not isinstance(target, dict) or set(target) != T5_TARGET_KEYS or \
            not all(isinstance(target[k], (str, os.PathLike)) for k in ("json", "png")):
        return _t5_fail("format", 0, note)
    if not _t5_own_spectrum(target["spectrum"], ctx.rng, crit):
        return _t5_fail("spectrum-function", 0, note)
    try:
        summary = json.loads(Path(target["json"]).expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _t5_fail("format", 0, note)
    if not isinstance(summary, dict) or not set(T5_KEYS) <= set(summary):
        return _t5_fail("format", 0, note)
    values = {}
    for key in T5_NUMBERS:
        value = summary[key]
        if isinstance(value, bool) or not isinstance(value, numbers.Real) or not np.isfinite(float(value)):
            return _t5_fail("format", 0, note)
        values[key] = float(value)
    passed = 1
    from obspy import read, read_inventory

    sac_path = Path(str(summary["sac_path"])).expanduser()
    try:
        raw = read(str(sac_path), format="SAC")[0]
    except Exception:  # noqa: BLE001 - not a readable SAC file
        return _t5_fail("trace", passed, note)
    head = raw.stats
    if head.channel not in ("HHE", "HHN"):
        return _t5_fail("trace", passed, note)
    passed += 1
    xml_path = Path(str(summary["stationxml"])).expanduser()
    ground = {}
    try:
        inventory = read_inventory(str(xml_path))
        for kind in ("VEL", "DISP", "ACC"):
            one = raw.copy()
            one.detrend("demean")
            one.taper(0.05, type="hann")
            one.remove_response(inventory=inventory, output=kind, pre_filt=T5_PRE_FILT, water_level=None)
            ground[kind] = one
    except Exception:  # noqa: BLE001 - missing or unreadable metadata, or no response for this channel
        return _t5_fail("no-metadata", passed, note)
    passed += 1
    event = _event(str(summary["event_id"]))
    if event is None or not (head.starttime <= event["origin"] <= head.endtime) or \
            abs(values["ml"] - event["ml"]) > 0.05:
        return _t5_fail("event", passed, note)
    passed += 1
    tops = {kind: float(np.max(np.abs(tr.data))) for kind, tr in ground.items()}
    raw_top = float(np.max(np.abs(raw.data - np.mean(raw.data))))
    pgv = values["pgv_m_s"]
    if pgv >= 1.0 and abs(pgv / raw_top - 1.0) <= 0.5:
        return _t5_fail("counts", passed, note)
    factor = float(crit.get("pgv_factor", 1.5))
    near = lambda value, ref: ref > 0 and 1.0 / factor <= value / ref <= factor  # noqa: E731
    if not near(pgv, tops["VEL"]):
        if any(near(pgv, tops["VEL"] * scale) for scale in (1e3, 1e6, 1e9, 1e-3)):
            return _t5_fail("units", passed, note)
        if near(pgv, tops["DISP"]) or near(pgv, tops["ACC"]):
            return _t5_fail("output-type", passed, note)
        if pgv >= 1.0:
            return _t5_fail("counts", passed, note)
        return _t5_fail("pgv", passed, note)
    passed += 1
    epi = float(_surface_km(event["lat"], event["lon"], head.sac.stla, head.sac.stlo)[0])
    hypo = float(np.hypot(epi, event["depth"]))
    if abs(values["hypo_km"] - hypo) > float(crit.get("dist_rel_tol", 0.02)) * hypo + \
            float(crit.get("dist_abs_tol_km", 0.2)):
        return _t5_fail("distance", passed, note)
    passed += 1
    # the spectral peak: the student's own band_amplitude_spectrum (verified again above) of the check's own
    # velocity record (the whole record); the check has no spectrum code of its own
    velocity = ground["VEL"]
    low_hz, high_hz = T5_BAND_HZ
    got, err = _call(target["spectrum"], velocity.copy(), low_hz, high_hz)
    if err is not None:
        raise err
    try:
        grid_hz, heights = (np.asarray(part, dtype=float) for part in got)
    except (TypeError, ValueError):
        return _t5_fail("spectrum-function", passed, note)
    if grid_hz.ndim != 1 or grid_hz.shape != heights.shape or grid_hz.size < 2:
        return _t5_fail("spectrum-function", passed, note)
    in_band = (grid_hz >= low_hz) & (grid_hz <= high_hz)
    best = (float(grid_hz[np.argmax(heights)]), float(grid_hz[in_band][np.argmax(heights[in_band])]))
    f_rel = float(crit.get("fpeak_rel_tol", 0.05))
    if not any(abs(values["f_peak_hz"] / f - 1.0) <= f_rel for f in best if f > 0):
        return _t5_fail("frequency", passed, note)
    passed += 1
    own_r = values["hypo_km"]
    displacement_m = 1e-9 * 10.0 ** (values["ml"] + 2.09 - 0.00189 * own_r - 1.11 * np.log10(own_r))
    formula = 2.0 * np.pi * values["f_peak_hz"] * displacement_m
    if abs(values["expected_pgv_m_s"] / formula - 1.0) > float(crit.get("formula_rel_tol", 0.02)):
        return _t5_fail("expectation", passed, note)
    passed += 1
    if values["expected_pgv_m_s"] <= 0 or abs(values["ratio"] / (pgv / values["expected_pgv_m_s"]) - 1.0) > 0.01:
        return _t5_fail("ratio", passed, note)
    passed += 1
    from matplotlib.figure import Figure

    picture, fig = Path(target["png"]).expanduser(), target["figure"]
    is_png = False
    if picture.is_file() and picture.stat().st_size >= 5000:
        with open(picture, "rb") as fh:
            is_png = fh.read(8) == b"\x89PNG\r\n\x1a\n"
    if not is_png or not isinstance(fig, Figure):
        return _t5_fail("figure", passed, note)
    passed += 1
    after_origin = velocity.times(reftime=event["origin"])
    record = _t5_panel(fig, after_origin, velocity.data, T5_SHOWN_S, float(crit.get("window_tol_s", 0.5)), crit,
                       cut=True)
    if record is None:
        return _t5_fail("figure-record", passed, note)
    passed += 1
    swing = np.abs(velocity.data)
    loud = after_origin[swing >= 0.9 * swing.max()]
    gap, unit = float(crit.get("marker_tol_s", 0.05)), _t5_unit(record[0])
    if not any(np.min(np.abs(loud - x)) <= gap and (y is None or near(abs(y) / unit, tops["VEL"]))
               for x, y in _t5_marks(*record)):
        return _t5_fail("figure-marker", passed, note)
    passed += 1
    spectrum = _t5_panel(fig, grid_hz, heights, T5_BAND_HZ, 0.5, crit, cut=False)
    if spectrum is None:
        return _t5_fail("figure-spectrum", passed, note)
    passed += 1
    if not any(abs(x / values["f_peak_hz"] - 1.0) <= 0.02 for x, _ in _t5_marks(*spectrum)):
        return _t5_fail("figure-marker", passed, note)
    passed += 1
    text = _t5_words(fig)
    speeds = (1.0, 1e3, 1e6)
    shown = ((pgv, speeds), (values["f_peak_hz"], (1.0,)), (values["expected_pgv_m_s"], speeds),
             (values["ratio"], (1.0,)))
    if not all(_t5_written(text, value, scales) for value, scales in shown):
        return _t5_fail("figure-numbers", passed, note)
    return outcome_from_cases([True] * (passed + 1), real_data=True, note=note)
