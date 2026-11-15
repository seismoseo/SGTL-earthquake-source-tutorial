"""Checkers for M01 · Python for earthquake catalogs.

Where the truth comes from (DESIGN.md section 1, rule 1):

* M01-T1 and M01-T4: an independent library, ObsPy's ``locations2degrees``, scaled to a sphere of
  radius 6371.0 km.
* M01-T2 and M01-T3: construction. Every case starts as a moment in UTC; the KST clock reading that
  the student's code receives is derived from that moment, so the UTC answer is known beforehand.
* M01-T5: construction. Made-up catalogs mix moments at least a day inside the periods when the
  'Asia/Seoul' zone is not UTC + 9 h (``DST_FULL_UTC``) with moments at least a day outside them, so
  each answer is known from how the catalog was built. One more case runs the function on the shipped
  KMA catalog; ``check_T5`` recomputes that answer from the same periods and never prints it.

Failure categories are keys of ``checks/specs/M01.yaml``; the engine prints their fixed messages.
"""
from __future__ import annotations

import datetime as _dt
import numbers
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from ..synth import KST, gr_magnitudes, random_points, random_utc_times
from . import Outcome, outcome_from_cases, within_tol

__all__ = ["check_T1", "check_T2", "check_T3", "check_T4", "check_T5"]

SPHERE_KM = 6371.0
KM_PER_DEGREE = SPHERE_KM * np.pi / 180.0
NINE_HOURS = pd.Timedelta(hours=9)
# Korean daylight saving time (tz database): 1987-05-10 02:00 to 10-11 03:00 local, and 1988-05-08
# 02:00 to 10-09 03:00 local. Cases are drawn at least a day inside these spans (written in UTC).
DST_INSIDE_UTC = (("1987-05-11", "1987-10-09"), ("1988-05-09", "1988-10-07"))
DST_FULL_UTC = (("1987-05-09T17:00:00", "1987-10-10T17:00:00"), ("1988-05-07T17:00:00", "1988-10-08T17:00:00"))


# ------------------------------------------------------------------------------------------- helpers
def _call(func: Any, *args: Any) -> Tuple[Any, Optional[BaseException]]:
    """Run the student's code. NotImplementedError passes through (the engine reports NOT STARTED)."""
    try:
        return func(*args), None
    except NotImplementedError:
        raise
    except Exception as exc:  # noqa: BLE001 - classified by the caller
        return None, exc


def _floats(value: Any) -> Optional[np.ndarray]:
    try:
        return np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        return None


def _oracle_km(lat_a: Any, lon_a: Any, lat_b: Any, lon_b: Any) -> np.ndarray:
    """Great-circle distance from ObsPy (degrees of arc) on the 6371.0 km sphere."""
    from obspy.geodetics import locations2degrees

    arc = locations2degrees(np.asarray(lat_a, dtype=float), np.asarray(lon_a, dtype=float),
                            np.asarray(lat_b, dtype=float), np.asarray(lon_b, dtype=float))
    return np.asarray(arc, dtype=float) * KM_PER_DEGREE


def _epoch_seconds(stamps: Any) -> np.ndarray:
    idx = pd.DatetimeIndex(stamps)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    return np.asarray(idx.tz_convert("UTC").as_unit("s").asi8, dtype=np.int64)


def _digits_from_epoch(seconds: int) -> str:
    """'YYYYMMDDHHMMSS' of a UTC moment, from numpy's ISO text."""
    return re.sub(r"\D", "", np.datetime_as_string(np.datetime64(int(seconds), "s"), unit="s"))


def _uniform_seconds(rng: np.random.Generator, k: int, start: str, end: str) -> np.ndarray:
    lo = int(pd.Timestamp(start, tz="UTC").timestamp())
    hi = int(pd.Timestamp(end, tz="UTC").timestamp())
    return rng.integers(lo, hi, int(k)).astype(np.int64)


def _late_evening(rng: np.random.Generator, days: List[pd.Timestamp]) -> np.ndarray:
    """A UTC moment between 15:00 and 23:59:59 on each day: KST is then already the next day."""
    base = np.array([int(pd.Timestamp(d.date(), tz="UTC").timestamp()) for d in days], dtype=np.int64)
    return base + rng.integers(15 * 3600, 24 * 3600, len(days))


def _in_dst_span(seconds: np.ndarray) -> np.ndarray:
    """True for moments inside the full Korean daylight-saving periods (used to classify, not to draw)."""
    seconds = np.asarray(seconds, dtype=np.int64)
    hit = np.zeros(len(seconds), dtype=bool)
    for start, end in DST_FULL_UTC:
        lo = int(pd.Timestamp(start, tz="UTC").timestamp())
        hi = int(pd.Timestamp(end, tz="UTC").timestamp())
        hit |= (seconds >= lo) & (seconds < hi)
    return hit


def _kst_parts(seconds: int) -> Tuple[int, int, int, int, int, int]:
    clock = pd.Timestamp(int(seconds), unit="s", tz="UTC").tz_convert(KST)
    return (int(clock.year), int(clock.month), int(clock.day), int(clock.hour), int(clock.minute),
            int(clock.second))


# ----------------------------------------------------------------------------------- M01-T1 distance
def _t1_pairs(rng: np.random.Generator, n: int) -> Tuple[np.ndarray, ...]:
    """Pairs in Korea, on the whole globe, a few metres to 2 km apart, and a few fixed ones."""
    fixed = np.array([
        [0.0, 0.0, 0.0, 1.0],              # one degree along the equator
        [35.76, 129.19, 35.76, 129.19],    # the same point twice
        [37.5665, 126.978, 37.5665, 126.978],
        [90.0, 0.0, -90.0, 0.0],           # pole to pole
        [10.0, 179.5, -10.0, -179.5],      # across the date line
        [-33.87, 151.21, 51.51, -0.13],    # Sydney to London
    ])
    n = max(int(n), 4 * len(fixed))
    n_short = n // 8
    n_korea = (n - n_short - len(fixed)) // 2
    n_world = n - n_short - n_korea - len(fixed)
    ka, ko = random_points(rng, n_korea)
    kb, kob = random_points(rng, n_korea)
    wa = np.degrees(np.arcsin(rng.uniform(-1.0, 1.0, n_world)))
    wo = rng.uniform(-180.0, 180.0, n_world)
    wb = np.degrees(np.arcsin(rng.uniform(-1.0, 1.0, n_world)))
    wob = rng.uniform(-180.0, 180.0, n_world)
    sa, so = random_points(rng, n_short)
    step = 10.0 ** rng.uniform(-5.3, -1.7, n_short)   # degrees: about 0.5 m to 2 km
    turn = rng.uniform(0.0, 2.0 * np.pi, n_short)
    sb, sob = sa + step * np.cos(turn), so + step * np.sin(turn)
    columns = [np.concatenate(parts) for parts in zip(
        (ka, ko, kb, kob), (wa, wo, wb, wob), (sa, so, sb, sob),
        (fixed[:, 0], fixed[:, 1], fixed[:, 2], fixed[:, 3]))]
    order = rng.permutation(n)
    return tuple(np.round(c[order], 7) for c in columns)


def _t1_category(target: Any, got: np.ndarray, expected: np.ndarray, ok: np.ndarray,
                 args: Tuple[np.ndarray, ...], rel_tol: float, abs_tol: float) -> str:
    far = expected > 1.0
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = got[far] / expected[far]
    finite = ratio[np.isfinite(ratio)]
    if finite.size > 0.9 * ratio.size:
        r = float(np.median(finite))
        for factor in (1000.0, 1.0 / KM_PER_DEGREE, 1.0 / SPHERE_KM):   # metres, degrees, radians
            if abs(r / factor - 1.0) < 1e-3:
                return "units"
        spread = float(np.max(np.abs(finite / r - 1.0)))
        if abs(r - 1.0) > rel_tol and abs(r - 1.0) < 0.01 and spread < 1e-7:
            return "radius"
    if ok[far].all():
        return "precision"
    again, err = _call(target, *[np.radians(a) for a in args])
    again = _floats(again) if err is None else None
    if again is not None and again.shape == expected.shape:
        if within_tol(again, expected, rel_tol=1e-6, abs_tol=1e-6).mean() > 0.95:
            return "radians"
    return "wrong-values"


def check_T1(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    rel_tol = float(crit.get("rel_tol", 1e-6))
    abs_tol = float(crit.get("abs_tol_km", 1e-6))
    lat1, lon1, lat2, lon2 = _t1_pairs(ctx.rng, int(crit.get("trials", 1000)))
    n = lat1.size
    expected = _oracle_km(lat1, lon1, lat2, lon2)
    first = (float(lat1[0]), float(lon1[0]), float(lat2[0]), float(lon2[0]))

    got, err = _call(target, lat1.copy(), lon1.copy(), lat2.copy(), lon2.copy())
    if err is not None:
        _, err_one = _call(target, *first)
        if err_one is not None:
            raise err  # broken for every input: the engine shows the student's own error
        return Outcome(False, n + 2, n, "shape", details={
            "example": {"inputs": f"{n} pairs as numpy arrays", "got": f"{type(err).__name__}: {err}"},
            "note": "Your function works for one pair of plain numbers but stops on numpy arrays."})
    values = _floats(got)
    if values is None or values.shape != (n,):
        return Outcome(False, n + 2, n, "shape", details={"example": {
            "inputs": f"{n} pairs as numpy arrays of shape ({n},)",
            "got": f"{type(got).__name__} of shape {np.shape(got)}"}})
    ok = within_tol(values, expected, rel_tol=rel_tol, abs_tol=abs_tol)
    if not ok.all():
        i = int(np.flatnonzero(~ok)[0])
        example = {"inputs": {"lat1": f"{lat1[i]:.7f}", "lon1": f"{lon1[i]:.7f}", "lat2": f"{lat2[i]:.7f}",
                              "lon2": f"{lon2[i]:.7f}"},
                   "got": float(values[i]), "error": float(values[i] - expected[i])}
        category = _t1_category(target, values, expected, ok, (lat1, lon1, lat2, lon2), rel_tol, abs_tol)
        return outcome_from_cases(np.concatenate([ok, [True, True]]), category=category, example=example)

    # one pair of plain numbers -> one number; one point against many -> one value per point
    single, err = _call(target, *first)
    if err is not None or np.ndim(single) != 0 or not within_tol(single, expected[0], rel_tol=rel_tol,
                                                                  abs_tol=abs_tol).all():
        shown = f"{type(err).__name__}: {err}" if err is not None else \
            f"{type(single).__name__} of shape {np.shape(single)}"
        return Outcome(False, n + 2, 1, "shape", details={"example": {
            "inputs": {"lat1": first[0], "lon1": first[1], "lat2": first[2], "lon2": first[3]},
            "got": shown}, "note": "One pair of plain numbers must give one plain number."})
    k = min(50, n)
    many, err = _call(target, first[0], first[1], lat2[:k].copy(), lon2[:k].copy())
    many_ok = err is None and _floats(many) is not None and np.shape(many) == (k,)
    if many_ok:
        many_ok = bool(within_tol(_floats(many), _oracle_km(first[0], first[1], lat2[:k], lon2[:k]),
                                  rel_tol=rel_tol, abs_tol=abs_tol).all())
    if not many_ok:
        shown = f"{type(err).__name__}: {err}" if err is not None else f"shape {np.shape(many)}"
        return Outcome(False, n + 2, 1, "shape", details={"example": {
            "inputs": f"one point (two plain numbers) and {k} points (two arrays of shape ({k},))",
            "got": shown}, "note": "One point against an array of points must give one distance per point."})
    return Outcome(True, n + 2, 0)


# ------------------------------------------------------------------------------------- M01-T2 KST id
def _t2_cases(rng: np.random.Generator, n: int) -> Tuple[np.ndarray, np.ndarray]:
    """UTC moments (epoch seconds) and a group label for each case."""
    n = max(int(n), 40)
    k_dst = max(4, (3 * n) // 10)
    k_mid, k_month, k_year, k_leap = n // 8, n // 10, n // 20, n // 20
    k_plain = n - k_dst - k_mid - k_month - k_year - k_leap
    parts: List[np.ndarray] = []
    groups: List[str] = []

    days = _uniform_seconds(rng, k_plain, "1978-01-01", "2030-12-31")
    plain = days - days % 86400 + rng.integers(0, 15 * 3600, k_plain)  # KST still on the same date
    parts.append(plain)
    groups += ["plain"] * k_plain

    mid_days = [pd.Timestamp(int(y), int(m), int(d)) for y, m, d in zip(
        rng.integers(1978, 2031, k_mid), rng.integers(1, 13, k_mid), rng.integers(1, 28, k_mid))]
    parts.append(_late_evening(rng, mid_days))
    groups += ["midnight"] * k_mid

    month_days = [pd.Timestamp(int(y), int(m), 1) + pd.offsets.MonthEnd(0) for y, m in zip(
        rng.integers(1978, 2031, k_month), rng.integers(1, 12, k_month))]
    parts.append(_late_evening(rng, month_days))
    groups += ["month"] * k_month

    year_days = [pd.Timestamp(int(y), 12, 31) for y in rng.integers(1978, 2030, k_year)]
    parts.append(_late_evening(rng, year_days))
    groups += ["year"] * k_year

    leap_years = [y for y in range(1980, 2031) if y % 4 == 0]
    leap_days = []
    for j in range(k_leap):
        if j % 2 == 0:
            leap_days.append(pd.Timestamp(int(rng.choice(leap_years)), 2, 29))
        else:
            leap_days.append(pd.Timestamp(int(rng.choice([y for y in range(1978, 2031) if y % 4])), 2, 28))
    parts.append(_late_evening(rng, leap_days))
    groups += ["leap"] * k_leap

    half = k_dst // 2
    parts.append(np.concatenate([_uniform_seconds(rng, half, *DST_INSIDE_UTC[0]),
                                 _uniform_seconds(rng, k_dst - half, *DST_INSIDE_UTC[1])]))
    groups += ["dst"] * k_dst

    seconds = np.concatenate(parts)
    labels = np.array(groups)
    order = rng.permutation(seconds.size)
    return seconds[order], labels[order]


def check_T2(target: Any, ctx: Any) -> Outcome:
    seconds, groups = _t2_cases(ctx.rng, int(ctx.criteria.get("trials", 200)))
    n = seconds.size
    kst = [_kst_parts(s) for s in seconds]
    want = [_digits_from_epoch(s) for s in seconds]
    crosses = np.array([parts[2] != pd.Timestamp(int(s), unit="s").day for parts, s in zip(kst, seconds)])

    got: List[Any] = []
    errors: List[Optional[BaseException]] = []
    for parts in kst:
        value, err = _call(target, *parts)
        got.append(value)
        errors.append(err)
    raised = np.array([e is not None for e in errors])

    def example(i: int, shown: Any, error: Any = None) -> dict:
        names = ("year", "month", "day", "hour", "minute", "second")
        out = {"inputs": dict(zip(names, kst[i])), "got": shown}
        if error is not None:
            out["error"] = error
        return out

    if raised.any():
        # 'rollover' only when every case that failed (error or wrong text) crosses midnight
        good = np.array([e is None and got[i] == want[i] for i, e in enumerate(errors)])
        if raised.all() or not crosses[~good].all():
            raise next(e for e in errors if e is not None)
        i = int(np.flatnonzero(raised)[0])
        return outcome_from_cases(good, category="rollover",
                                  example=example(i, f"{type(errors[i]).__name__}: {errors[i]}"))

    shape_ok = np.array([isinstance(v, str) and len(v) == 14 and v.isdigit() for v in got])
    if not shape_ok.all():
        i = int(np.flatnonzero(~shape_ok)[0])
        return outcome_from_cases(shape_ok & np.array([g == w for g, w in zip(got, want)]),
                                  category="format", example=example(i, got[i]))
    ok = np.array([g == w for g, w in zip(got, want)])
    if ok.all():
        return outcome_from_cases(ok)

    shift_h = np.full(n, np.nan)
    for i in np.flatnonzero(~ok):
        try:
            mine = pd.Timestamp(_dt.datetime.strptime(got[i], "%Y%m%d%H%M%S"), tz="UTC")
        except ValueError:
            continue
        shift_h[i] = (int(mine.timestamp()) - int(seconds[i])) / 3600.0
    bad = ~ok
    i = int(np.flatnonzero(bad)[0])
    if np.all(shift_h[bad] == 18.0) and bad.all():
        category = "sign"
    elif np.all(shift_h[bad] == 9.0) and bad.all():
        category = "no-shift"
    elif np.all(_in_dst_span(seconds[bad])) and np.all(np.abs(shift_h[bad]) == 1.0):
        category = "dst"
    elif np.all(crosses[bad]):
        category = "rollover"
    else:
        category = "wrong-values"
    error = f"{shift_h[i]:+g} hours" if np.isfinite(shift_h[i]) else "not a real date"
    return outcome_from_cases(ok, category=category, example=example(i, got[i], error))


# --------------------------------------------------------------------------------- M01-T3 load file
T3_COLUMNS = ["origin_utc", "latitude", "longitude", "depth_km", "ml"]
# (clock of the time columns, Magnitude before Depth?, byte order mark?, rows, share of blank depths, mix)
T3_FILES = (
    ("UTC", False, False, 30, 0.3, "plain"),
    ("KST", True, True, 30, 0.3, "plain"),
    ("KST", False, True, 36, 0.2, "edges"),
    ("UTC", True, False, 24, 0.0, "plain"),
    ("KST", False, False, 30, 0.25, "edges"),
)


def _t3_times(rng: np.random.Generator, rows: int, mix: str) -> np.ndarray:
    if mix == "plain":
        stamps = random_utc_times(rng, rows, "1990-01-01", "2026-01-01")
        return np.sort(_epoch_seconds(stamps))
    k_dst = rows // 3
    k_edge = rows // 3
    edge_days = [pd.Timestamp(int(y), int(m), 1) + pd.offsets.MonthEnd(0) for y, m in zip(
        rng.integers(1990, 2026, k_edge), rng.integers(1, 13, k_edge))]
    parts = [_uniform_seconds(rng, k_dst // 2, *DST_INSIDE_UTC[0]),
             _uniform_seconds(rng, k_dst - k_dst // 2, *DST_INSIDE_UTC[1]),
             _late_evening(rng, edge_days),
             _uniform_seconds(rng, rows - k_dst - k_edge, "1978-01-01", "2026-01-01")]
    return np.sort(np.concatenate(parts))


def _t3_file(rng: np.random.Generator, folder: Path, number: int, spec: tuple) -> Tuple[Path, pd.DataFrame]:
    clock, mag_first, bom, rows, blank_share, mix = spec
    seconds = _t3_times(rng, rows, mix)
    lat, lon = random_points(rng, rows)
    lat, lon = np.round(lat, 4), np.round(lon, 4)
    depth = np.round(rng.uniform(1.0, 25.0, rows), 1)
    depth[rng.random(rows) < blank_share] = np.nan
    mag = gr_magnitudes(rng, rows, b=1.0, mc=0.5, dm=0.1)
    utc = pd.to_datetime(seconds, unit="s", utc=True)
    shown = utc.tz_convert(KST) if clock == "KST" else utc
    last = ["Magnitude", "Depth"] if mag_first else ["Depth", "Magnitude"]
    lines = [",".join(["Year", "Month", "Day", "Hour", "Minute", "Second", "Latitude", "Longitude"] + last)]
    for j in range(rows):
        t = shown[j]
        d_txt = "" if np.isnan(depth[j]) else f"{depth[j]:.1f}"
        tail = [f"{mag[j]:.1f}", d_txt] if mag_first else [d_txt, f"{mag[j]:.1f}"]
        lines.append(",".join([str(t.year), str(t.month), str(t.day), str(t.hour), str(t.minute), str(t.second),
                               f"{lat[j]:.4f}", f"{lon[j]:.4f}"] + tail))
    path = folder / f"colleague_{number}.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig" if bom else "utf-8")
    truth = pd.DataFrame({"origin_utc": utc, "latitude": lat, "longitude": lon, "depth_km": depth,
                          "ml": np.round(mag, 1)})
    return path, truth


def _t3_compare(got: Any, truth: pd.DataFrame, clock: str) -> Optional[Tuple[str, Any, Any]]:
    """None when right, else (category, what the student returned, size of the error)."""
    if not isinstance(got, pd.DataFrame):
        return "columns", f"a {type(got).__name__}, not a DataFrame", None
    names = [str(c) for c in got.columns]
    if names != T3_COLUMNS:
        return "columns", f"columns {names}", None
    if len(got) != len(truth):
        return "rows", f"{len(got)} rows", f"{len(got) - len(truth):+d} rows"
    got = got.reset_index(drop=True)
    num = {c: pd.to_numeric(got[c], errors="coerce").to_numpy(dtype=float)
           for c in ("latitude", "longitude", "depth_km", "ml")}
    exp = {c: truth[c].to_numpy(dtype=float) for c in ("latitude", "longitude", "depth_km", "ml")}
    close = lambda a, b: bool(np.all((np.abs(a - b) <= 1e-6) | (np.isnan(a) & np.isnan(b))))  # noqa: E731
    if not (close(num["latitude"], exp["latitude"]) and close(num["longitude"], exp["longitude"])):
        if close(num["latitude"], exp["longitude"]):
            return "columns", "latitude and longitude swapped", None
        return "wrong-values", f"latitude {num['latitude'][0]:.4f}, longitude {num['longitude'][0]:.4f}", None
    both = np.isfinite(exp["depth_km"])
    if both.any() and close(num["depth_km"][both], exp["ml"][both]) and close(num["ml"][both], exp["depth_km"][both]):
        return "columns", "depth_km holds the magnitudes and ml holds the depths", None
    blank = np.isnan(exp["depth_km"])
    if not pd.api.types.is_float_dtype(got["depth_km"]) or not np.array_equal(np.isnan(num["depth_km"]), blank):
        j = int(np.flatnonzero(np.isnan(num["depth_km"]) != blank)[0]) if \
            not np.array_equal(np.isnan(num["depth_km"]), blank) else 0
        return "depth-nan", f"depth_km of type {got['depth_km'].dtype}, row {j}: {got['depth_km'].iloc[j]!r}", None
    if not (close(num["depth_km"], exp["depth_km"]) and close(num["ml"], exp["ml"])):
        return "wrong-values", "depth_km or ml differ from the file", None
    text_like = [c for c in ("latitude", "longitude", "ml") if not pd.api.types.is_float_dtype(got[c])]
    if text_like:
        return "types", ", ".join(f"{c} of type {got[c].dtype}" for c in text_like), None

    times = got["origin_utc"]
    if not isinstance(times.dtype, pd.DatetimeTZDtype):
        try:
            times = pd.to_datetime(times)
        except (TypeError, ValueError):
            return "tz", f"origin_utc of type {got['origin_utc'].dtype}", None
        if not isinstance(times.dtype, pd.DatetimeTZDtype):
            return "tz", f"time-zone-naive times (dtype {times.dtype})", None
    mine = _epoch_seconds(times)
    want = _epoch_seconds(truth["origin_utc"])
    off = (mine - want) / 3600.0
    if np.all(off == 0):
        wall = times.dt.tz_localize(None) - times.dt.tz_convert("UTC").dt.tz_localize(None)
        if (wall != pd.Timedelta(0)).any():
            return "tz", f"times in the zone {times.dt.tz}, not UTC", None
        return None
    j = int(np.flatnonzero(off != 0)[0])
    shown = str(times.iloc[j])
    if np.all(np.abs(off) == 9.0):
        return "tz", shown, f"{off[j]:+g} hours"
    dst = _in_dst_span(want)
    if clock == "KST" and np.all(off[~dst] == 0) and np.all(np.abs(off[off != 0]) == 1.0):
        return "dst", shown, f"{off[j]:+g} hours"
    return "wrong-values", shown, f"{off[j]:+g} hours"


def check_T3(target: Any, ctx: Any) -> Outcome:
    n_files = max(1, int(ctx.criteria.get("trials", len(T3_FILES))))
    specs = [T3_FILES[i % len(T3_FILES)] for i in range(n_files)]
    results: List[Optional[Tuple[str, Any, Any]]] = []
    errors: List[Optional[BaseException]] = []
    with tempfile.TemporaryDirectory(prefix="sgtl-m01-") as tmp:
        folder = Path(tmp)
        for number, spec in enumerate(specs, start=1):
            path, truth = _t3_file(ctx.rng, folder, number, spec)
            arg = str(path) if number % 2 else path
            got, err = _call(target, arg, spec[0])
            errors.append(err)
            results.append(None if err is not None else _t3_compare(got, truth, spec[0]))

    def describe(spec: tuple) -> str:
        clock, mag_first, bom, rows, _, _ = spec
        order = "Magnitude before Depth" if mag_first else "Depth before Magnitude"
        return f"{rows}-row file, tz={clock!r}, {order}, {'with' if bom else 'no'} byte order mark"

    raised = [e is not None for e in errors]
    if any(raised):
        with_bom = [spec[2] for spec in specs]
        if all(raised):
            raise next(e for e in errors if e is not None)
        if all(r == b for r, b in zip(raised, with_bom)):
            i = raised.index(True)
            ok = [not r and res is None for r, res in zip(raised, results)]
            return outcome_from_cases(ok, category="bom", example={
                "inputs": describe(specs[i]), "got": f"{type(errors[i]).__name__}: {errors[i]}"})
        raise next(e for e in errors if e is not None)
    ok = [res is None for res in results]
    if all(ok):
        return outcome_from_cases(ok)
    i = ok.index(False)
    category, shown, error = results[i]
    example = {"inputs": describe(specs[i]), "got": shown}
    if error is not None:
        example["error"] = error
    return outcome_from_cases(ok, category=category, example=example)


# ------------------------------------------------------------------------------ M01-T4 within radius
T4_RADII_KM = (3.0, 10.0, 25.0, 60.0, 150.0)


def _t4_case(rng: np.random.Generator, number: int, skip_km: float) -> Tuple[pd.DataFrame, float, float, float, np.ndarray]:
    (lat0,), (lon0,) = random_points(rng, 1, (34.0, 37.8), (126.0, 129.5))
    empty = number == 0
    r_km = 2.0 if empty else float(T4_RADII_KM[(number - 1) % len(T4_RADII_KM)])
    half_lat = max(2.2 * r_km / KM_PER_DEGREE, 0.05)
    half_lon = half_lat / np.cos(np.radians(lat0))
    lat_c = lat0 + (5.0 if empty else 0.0)
    cat = _synthetic(rng, 150, (lat_c - half_lat, lat_c + half_lat), (lon0 - half_lon, lon0 + half_lon))
    dist = _oracle_km(lat0, lon0, cat["latitude"].to_numpy(), cat["longitude"].to_numpy())
    keep = np.abs(dist - r_km) >= skip_km
    cat, dist = cat.loc[keep], dist[keep]
    order = rng.permutation(len(cat))
    cat, dist = cat.iloc[order].copy(), dist[order]
    cat.index = pd.Index(1000 + rng.permutation(len(cat)))
    return cat, float(lat0), float(lon0), r_km, dist


def _synthetic(rng: np.random.Generator, n: int, lat_range: tuple, lon_range: tuple) -> pd.DataFrame:
    from ..synth import synthetic_catalog

    return synthetic_catalog(rng, n, lat_range=lat_range, lon_range=lon_range, start="2016-01-01",
                             end="2026-01-01", id_prefix="EV", blank_depth_fraction=0.1)


def check_T4(target: Any, ctx: Any) -> Outcome:
    trials = max(2, int(ctx.criteria.get("trials", 6)))
    skip_km = float(ctx.criteria.get("boundary_skip_km", 0.01))
    ok: List[bool] = []
    fails: List[Tuple[str, dict, bool]] = []   # (category, example, looks like a unit mix-up)
    for number in range(trials):
        df, lat0, lon0, r_km, dist = _t4_case(ctx.rng, number, skip_km)
        pristine = df.copy(deep=True)
        given = df.copy(deep=True)
        # expected order: positions of the oracle-inside events, ranked by their origin time in seconds
        hits = np.flatnonzero(dist <= r_km)
        ranks = np.argsort(_epoch_seconds(df["origin_utc"])[hits], kind="stable")
        want = [str(df["event_id"].iat[k]) for k in hits[ranks]]
        got, err = _call(target, given, lat0, lon0, r_km)
        if err is not None:
            raise err
        inputs = {"lat0": round(lat0, 4), "lon0": round(lon0, 4), "r_km": r_km, "rows in df": len(df)}
        category, shown, error, unit_like = None, None, None, False
        if not isinstance(got, pd.DataFrame) or "event_id" not in got.columns:
            category = "return-type"
            shown = f"a {type(got).__name__}" + ("" if not isinstance(got, pd.DataFrame)
                                                  else " without the column event_id")
        else:
            ids = [str(x) for x in got["event_id"]]
            if set(ids) != set(want) or len(ids) != len(set(ids)):
                missing, extra = len(set(want) - set(ids)), len(set(ids) - set(want))
                category, shown, error = "inclusive", f"{len(ids)} rows", f"{missing} events missing, {extra} extra"
                unit_like = any(set(ids) == set(df.loc[dist * scale <= r_km, "event_id"])
                                for scale in (1000.0, 1.0 / KM_PER_DEGREE, 1.0 / SPHERE_KM))  # m, deg, rad
            elif ids != want:
                category, shown = "sorting", "the right events in another order"
            elif not (given.equals(pristine) and list(given.columns) == list(pristine.columns)):
                category, shown = "changed-input", "df was changed by your function"
        ok.append(category is None)
        if category is not None:
            example = {"inputs": inputs, "got": shown}
            if error is not None:
                example["error"] = error
            fails.append((category, example, unit_like))
    if not fails:
        return outcome_from_cases(ok)
    category, example, _ = fails[0]
    if all(cat == "inclusive" and unit_like for cat, _, unit_like in fails):
        category = "units"
    return outcome_from_cases(ok, category=category, example=example)


# ------------------------------------------------------------------------- M01-T5 a one-hour mystery
# Made-up catalogs are built so that their answer is known beforehand. 'Agree' moments lie in other years, or in
# 1987-1988 at least a day outside the periods of DST_FULL_UTC; 'differ' moments lie at least a day inside them.
# Catalog 0 has no 'differ' moment. Catalog 1 has 'differ' moments only at the edges of a KST month: KST
# 00:00-08:59 on the 1st (1987: the UTC date is still in the month before) and KST 23:00-23:59 on the last day
# (1988: the 'Asia/Seoul' clock already shows the next month).
T5_AGREE_UTC = (("1978-01-01", "1987-01-01"), ("1989-01-01", "2030-12-31"))
T5_NEAR_UTC = (("1987-01-01", "1987-05-08T17:00:00"), ("1987-10-11T17:00:00", "1988-05-06T17:00:00"),
               ("1988-10-09T17:00:00", "1988-12-31"))
# the days of May and October outside those periods: the same months as some 'differ' moments
T5_SHOULDER_UTC = (("1987-05-01", "1987-05-08T17:00:00"), ("1987-10-11T17:00:00", "1987-10-31T15:00:00"),
                   ("1988-05-01", "1988-05-06T17:00:00"), ("1988-10-09T17:00:00", "1988-10-31T15:00:00"))


def _t5_month_edges(rng: np.random.Generator) -> np.ndarray:
    starts = sorted(int(m) for m in rng.choice([6, 7, 8, 9, 10], int(rng.integers(2, 4)), replace=False))
    ends = sorted(int(m) for m in rng.choice([5, 6, 7, 8, 9], int(rng.integers(2, 4)), replace=False))
    early = _late_evening(rng, [pd.Timestamp(1987, m, 1) - pd.Timedelta(days=1) for m in starts])
    last_days = [pd.Timestamp(1988, m, 1) + pd.offsets.MonthEnd(0) for m in ends]
    late = np.array([int(pd.Timestamp(d.date(), tz="UTC").timestamp()) for d in last_days], dtype=np.int64)
    late = late + 14 * 3600 + rng.integers(0, 3600, len(last_days))   # UTC 14:00-14:59 on the last day
    return np.concatenate([early, late]).astype(np.int64)


def _t5_made_up(rng: np.random.Generator, number: int) -> Tuple[pd.DataFrame, int, List[str]]:
    """A made-up catalog, and the count and the months it was built to have."""
    k_agree = int(rng.integers(24, 41))
    agree = np.concatenate([_uniform_seconds(rng, k_agree // 4, *T5_AGREE_UTC[0]),
                            _uniform_seconds(rng, k_agree - k_agree // 4, *T5_AGREE_UTC[1])])
    near = [_uniform_seconds(rng, int(rng.integers(2, 5)), *T5_NEAR_UTC[0]),
            _uniform_seconds(rng, int(rng.integers(1, 4)), *T5_NEAR_UTC[1]),
            _uniform_seconds(rng, int(rng.integers(1, 3)), *T5_NEAR_UTC[2])]
    for j in rng.choice(len(T5_SHOULDER_UTC), int(rng.integers(1, 3)), replace=False):
        near.append(_uniform_seconds(rng, 1, *T5_SHOULDER_UTC[int(j)]))
    near = np.concatenate(near)
    if number == 0:
        differ = np.zeros(0, dtype=np.int64)
    elif number == 1:
        differ = _t5_month_edges(rng)
    else:
        differ = np.concatenate([_uniform_seconds(rng, int(rng.integers(1, 5)), *DST_INSIDE_UTC[0]),
                                 _uniform_seconds(rng, int(rng.integers(0, 5)), *DST_INSIDE_UTC[1])])
    seconds = np.concatenate([agree, near, differ]).astype(np.int64)
    built_to_differ = np.r_[np.zeros(agree.size + near.size, dtype=bool), np.ones(differ.size, dtype=bool)]
    order = rng.permutation(seconds.size)
    seconds, built_to_differ = seconds[order], built_to_differ[order]
    lat, lon = random_points(rng, seconds.size)
    df = pd.DataFrame({
        "event_id": [f"MU{number}{k:03d}" for k in range(seconds.size)],
        "origin_utc": pd.to_datetime(seconds, unit="s", utc=True),
        "latitude": np.round(lat, 3),
        "longitude": np.round(lon, 3),
        "ml": gr_magnitudes(rng, seconds.size),
    })
    df.index = pd.Index(500 + rng.permutation(seconds.size))   # row labels that are not 0, 1, 2, ...
    months = sorted({"%04d-%02d" % _kst_parts(s)[:2] for s in seconds[built_to_differ]})
    return df, int(built_to_differ.sum()), months


def _t5_shape_ok(answer: Any) -> bool:
    if not isinstance(answer, dict) or set(answer) != {"n_wrong", "months"}:
        return False
    count, months = answer["n_wrong"], answer["months"]
    if isinstance(count, bool) or not isinstance(count, numbers.Integral):
        return False
    if not isinstance(months, (list, tuple)):
        return False
    if not all(isinstance(m, str) and re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", m) for m in months):
        return False
    return list(months) == sorted(set(months))


def check_T5(target: Any, ctx: Any) -> Outcome:
    trials = max(2, int(ctx.criteria.get("trials", 6)))
    note = (f"The check ran your function on {trials} made-up catalogs and on the shipped KMA catalog; it "
            "recomputes the KMA answer itself and never prints it.")
    ok: List[bool] = []
    fails: List[Tuple[str, dict, bool]] = []   # (category, example, real data?)
    for number in range(trials + 1):
        real = number == trials
        if not real:
            df, n_true, months_true = _t5_made_up(ctx.rng, number)
            inputs = {"catalog": f"made-up {number + 1} of {trials}", "rows": len(df)}
        else:
            from .. import data as _data

            df = _data.kma_catalog()
            inputs = {"catalog": "the shipped KMA catalog", "rows": len(df)}
            # its answer, from the clock-change periods (not from the student's method): moments inside them
            # and their months on the fixed KST clock
            moment = _epoch_seconds(df["origin_utc"])
            inside = np.zeros(moment.size, dtype=bool)
            for start, end in DST_FULL_UTC:
                inside |= ((moment >= int(pd.Timestamp(start, tz="UTC").timestamp()))
                           & (moment < int(pd.Timestamp(end, tz="UTC").timestamp())))
            n_true = int(inside.sum())
            months_true = sorted({"%04d-%02d" % _kst_parts(s)[:2] for s in moment[inside]})
        pristine = df.copy(deep=True)
        given = df.copy(deep=True)
        got, err = _call(target, given)
        if err is not None:
            raise err
        category, error = None, None
        if not _t5_shape_ok(got):
            category = "format"
        elif int(got["n_wrong"]) != n_true:
            count = int(got["n_wrong"])
            category = "same-instant" if count == 0 else "count"
            error = f"n_wrong is {abs(count - n_true)} too {'low' if count < n_true else 'high'}"
        elif list(got["months"]) != months_true:
            missing = len(set(months_true) - set(got["months"]))
            extra = len(set(got["months"]) - set(months_true))
            category, error = "months", f"{missing} month(s) missing, {extra} extra"
        elif not (given.equals(pristine) and list(given.columns) == list(pristine.columns)):
            category, error = "changed-input", "df was changed by your function"
        ok.append(category is None)
        if category is not None:
            example = {"inputs": inputs, "got": got}
            if error is not None:
                example["error"] = error
            fails.append((category, example, real))
    if not fails:
        return outcome_from_cases(ok, note=note)
    seen = [cat for cat, _, _ in fails]
    if "format" in seen:
        category = "format"
    elif all(cat == "same-instant" for cat in seen):
        category = "same-instant"
    elif "count" in seen or "same-instant" in seen:
        category = "count"
    elif "months" in seen:
        category = "months"
    else:
        category = "changed-input"
    shown = ("count", "same-instant") if category == "count" else (category,)
    _, example, real = next(f for f in fails if f[0] in shown)
    return outcome_from_cases(ok, category=category, example=example, real_data=real, note=note)
