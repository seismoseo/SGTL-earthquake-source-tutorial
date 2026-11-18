"""Checkers for M04 · Earthquake catalogs: read, clean, look.

Where the truth comes from (DESIGN.md section 1, rule 1):

* M04-T1: construction. Every practice magnitude starts as a whole bin number k; the student's code receives
  k * dm plus floating-point noise far below dm, so each value's bin is known beforehand. Per-bin counts come
  from those whole numbers (np.unique) and the cumulative counts from a comparison table, not from the floats.
* M04-T2: construction. Events sit at known whole-second offsets from time zero, some exactly on the ends of
  the window; time zero is handed over as text, Timestamp or datetime, in UTC, in KST or without a zone.
* M04-T3: construction. Catalog pairs are assembled from groups with known answers: true pairs, events of one
  catalog only, decoys that are too far away or too late, and rivals (a second candidate that is farther in
  time, and sometimes nearer in space, than the true partner). Distances come from ObsPy (an independent
  library). Four tiny probes isolate the time-difference and unit slips.
* M04-T4: the student's own fmd (task 1), which must pass made-up cases of task 1 again, on each epoch of the
  shipped KMA catalog: the by-eye value must lie near the tallest per-bin count of that FMD plus 0.2 (Wiemer &
  Wyss 2000; Woessner & Wiemer 2005). The check counts nothing itself and prints nothing.
* M04-T5: construction. Gutenberg-Richter catalogs built bin by bin (whole numbers of tenths) and year by year,
  with an added excess in some years, years without events in some bins, events late on 31 December (UTC) and
  noisy magnitudes; plus two property tests (row order, every event listed twice).
* M04-T6: the student's own products (a CSV table and a PNG figure); nothing here contacts a data center.

Failure categories are keys of ``checks/specs/M04.yaml``; the engine prints their fixed messages.
"""
from __future__ import annotations

import numbers
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from ..synth import KST, random_points
from . import Outcome, outcome_from_cases

__all__ = ["check_T1", "check_T2", "check_T3", "check_T4", "check_T5", "check_T6"]

SPHERE_KM = 6371.0
KM_PER_DEGREE = SPHERE_KM * np.pi / 180.0
NINE_HOURS_S = 9 * 3600
DAY_S = 86400


# ------------------------------------------------------------------------------------------- helpers
def _call(func: Any, *args: Any, **kwargs: Any) -> Tuple[Any, Optional[BaseException]]:
    """Run the student's code. NotImplementedError passes through (the engine reports NOT STARTED)."""
    try:
        return func(*args, **kwargs), None
    except NotImplementedError:
        raise
    except Exception as exc:  # noqa: BLE001 - classified by the caller
        return None, exc


def _show(values: Any, k: int = 4) -> list:
    """The first k values as a short list for an example line (floats to 9 decimals)."""
    flat = list(np.asarray(values).ravel()[:k])
    out = [round(float(v), 9) if isinstance(v, (float, np.floating)) else
           (int(v) if isinstance(v, (np.integer,)) else v) for v in flat]
    return out + (["..."] if np.asarray(values).size > k else [])


def _oracle_km(lat_a: Any, lon_a: Any, lat_b: Any, lon_b: Any) -> np.ndarray:
    """Great-circle distance from ObsPy (degrees of arc) on the 6371.0 km sphere."""
    from obspy.geodetics import locations2degrees

    arc = locations2degrees(np.asarray(lat_a, dtype=float), np.asarray(lon_a, dtype=float),
                            np.asarray(lat_b, dtype=float), np.asarray(lon_b, dtype=float))
    return np.asarray(arc, dtype=float) * KM_PER_DEGREE


def _moved(lat: float, lon: float, km: float, bearing: float) -> Tuple[float, float]:
    """A point about km kilometers from (lat, lon) toward bearing (radians); checked later with ObsPy."""
    north = km * np.cos(bearing) / KM_PER_DEGREE
    east = km * np.sin(bearing) / (KM_PER_DEGREE * np.cos(np.radians(lat)))
    return float(lat + north), float(lon + east)


def _filler(rng: np.random.Generator, n: int) -> Dict[str, np.ndarray]:
    """Depth and magnitude columns that make a made-up catalog look like a real one."""
    depth = np.round(rng.uniform(2.0, 20.0, n), 1)
    ml = np.round(1.0 + rng.exponential(1.0 / np.log(10.0), n), 1)
    return {"depth_km": depth, "ml": ml}


def _unchanged(given: pd.DataFrame, pristine: pd.DataFrame) -> bool:
    return bool(given.equals(pristine) and list(given.columns) == list(pristine.columns)
                and given.index.equals(pristine.index))


# ---------------------------------------------------------------------------------- M04-T1 the FMD
# (dm, number of values, lowest bin number, b-value, share of noisy values, container, dm given by keyword)
T1_CASES = (
    (0.1, 600, 5, 1.0, 0.5, "array", False),
    (0.1, 3000, 0, 0.9, 0.5, "series", True),
    (0.2, 900, 3, 1.1, 0.5, "list", True),
    (0.05, 1500, 20, 1.0, 0.5, "array", True),
    (0.1, 400, -8, 1.0, 0.6, "array", True),      # negative magnitudes
    (0.1, 1, 23, 1.0, 1.0, "list", True),         # one value
    (0.1, 150, 10, 0.5, 0.5, "series", True),     # sparse: empty bins inside the range
    (0.1, 2000, 8, 1.2, 0.5, "array", False),
)
T1_PRIORITY = ("format", "half-bin", "bin-range", "float-binning", "negative-magnitudes", "cumulative-direction",
               "cumulative-includes", "wrong-values")


def _t1_case(rng: np.random.Generator, spec: tuple) -> Tuple[np.ndarray, np.ndarray, Any]:
    """Whole bin numbers k, the float magnitudes built from them, and the container handed to the student."""
    dm, n, k_lo, b, noisy_share, kind, _ = spec
    step_up = 10.0 ** (-b * dm)                       # chance that an event reaches the next bin (G-R law)
    whole = (k_lo + rng.geometric(1.0 - step_up, int(n)) - 1).astype(np.int64)
    whole = rng.permutation(whole)
    clean = np.round(whole * dm, 6)
    noisy = rng.random(whole.size) < noisy_share
    wobble = rng.choice([-1.0, 1.0], whole.size) * 10.0 ** rng.uniform(-9.0, -6.6, whole.size)
    mags = np.where(noisy, clean + wobble, clean)
    if kind == "list":
        given: Any = [float(v) for v in mags]
    elif kind == "series":
        given = pd.Series(mags, index=pd.Index(7000 + rng.permutation(whole.size)), name="ml")
    else:
        given = mags.copy()
    return whole, mags, given


def _t1_parse(got: Any) -> Optional[List[np.ndarray]]:
    if not isinstance(got, (tuple, list)) or len(got) != 3:
        return None
    arrays = []
    for part in got:
        try:
            arr = np.asarray(part, dtype=float)
        except (TypeError, ValueError):
            return None
        if arr.ndim != 1 or not np.all(np.isfinite(arr)):
            return None
        arrays.append(arr)
    if len({a.size for a in arrays}) != 1 or arrays[0].size == 0:
        return None
    return arrays


def _t1_verdict(parts: List[np.ndarray], whole: np.ndarray, mags: np.ndarray, dm: float,
                tol: float) -> Tuple[Optional[str], str]:
    centers, n_got, c_got = parts
    grid = np.arange(int(whole.min()), int(whole.max()) + 1)
    labels, tally = np.unique(whole, return_counts=True)
    n_true = np.zeros(grid.size, dtype=np.int64)
    n_true[labels - grid[0]] = tally
    c_true = (whole[np.newaxis, :] >= grid[:, np.newaxis]).sum(axis=1)

    ratio = centers / dm
    off_grid = np.abs(ratio - np.rint(ratio))
    if np.all(np.abs(off_grid - 0.5) < 1e-3):
        return "half-bin", "centers on bin edges"
    if not np.all(off_grid < 1e-3):
        return "bin-range", "centers that are not multiples of dm"
    got_k = np.rint(ratio).astype(np.int64)
    same_grid = got_k.size == grid.size and np.array_equal(got_k, grid) and \
        bool(np.all(np.abs(centers - grid * dm) <= tol))

    def tally_on(bins_of: np.ndarray) -> np.ndarray:
        return np.array([int(np.count_nonzero(bins_of == g)) for g in got_k])

    if same_grid and np.array_equal(n_got, n_true):
        if np.array_equal(c_got, c_true):
            return None, ""
        if np.array_equal(c_got, np.cumsum(n_true)):
            return "cumulative-direction", "n_cum adds up from the smallest bin"
        if np.array_equal(c_got, c_true - n_true):
            return "cumulative-includes", "n_cum without each bin's own events"
        return "cumulative-direction", "n_noncum right, n_cum wrong"
    floor_k = np.floor(mags / dm).astype(np.int64)
    cut_k = np.trunc(mags / dm).astype(np.int64)
    half_up_k = np.trunc(mags / dm + 0.5).astype(np.int64)
    if not same_grid and set(got_k.tolist()) < set(grid.tolist()) and np.array_equal(n_got, tally_on(whole)):
        return "bin-range", f"{got_k.size} bins instead of {grid.size}"
    if np.array_equal(n_got, tally_on(floor_k)) or np.array_equal(n_got, tally_on(cut_k)):
        return "float-binning", "values like 1.5999999 one bin too low"
    if np.any(mags < 0) and np.array_equal(n_got, tally_on(half_up_k)):
        return "negative-magnitudes", "negative values in the wrong bin"
    if not same_grid:
        return "bin-range", f"{got_k.size} bins from {got_k[0] * dm:.4g} instead of {grid.size} from {grid[0] * dm:.4g}"
    return "wrong-values", f"{int(np.count_nonzero(n_got != n_true))} of {grid.size} bin counts differ"


def check_T1(target: Any, ctx: Any) -> Outcome:
    tol = float(ctx.criteria.get("center_tol", 1e-6))
    trials = max(2, int(ctx.criteria.get("trials", len(T1_CASES))))
    specs = [T1_CASES[i % len(T1_CASES)] for i in range(trials)]
    ok: List[bool] = []
    fails: List[Tuple[str, dict, float]] = []
    for spec in specs:
        dm, by_keyword = spec[0], spec[6]
        whole, mags, given = _t1_case(ctx.rng, spec)
        got, err = (_call(target, given, dm=dm) if by_keyword else _call(target, given))
        if err is not None:
            raise err
        inputs = {"dm": dm if by_keyword else "default (0.1)", "values": int(mags.size),
                  "first values": _show(mags, 3)}
        parts = _t1_parse(got)
        if parts is None:
            category, shown = "format", f"a {type(got).__name__}" + (f" of length {len(got)}" if
                                                                      isinstance(got, (tuple, list)) else "")
        else:
            category, shown = _t1_verdict(parts, whole, mags, dm, tol)
            if category is not None:
                shown = (f"centers {_show(parts[0])}, n_noncum {_show(parts[1])}, n_cum {_show(parts[2])} "
                         f"({shown})")
        ok.append(category is None)
        if category is not None:
            fails.append((category, {"inputs": inputs, "got": shown}, dm))
    if not fails:
        return outcome_from_cases(ok)
    if all(abs(dm - 0.1) > 1e-12 for _, _, dm in fails):
        category = "bin-width"
    else:
        seen = {cat for cat, _, _ in fails}
        category = next(c for c in T1_PRIORITY if c in seen)
    example = next((ex for cat, ex, _ in fails if cat == category), fails[0][1])
    return outcome_from_cases(ok, category=category, example=example)


# ---------------------------------------------------------------------------- M04-T2 a time window
# (how time zero is written, days before, days after, a window without events?)
T2_CASES = (
    ("text-utc", 1.0, 30.0, False),
    ("text-kst", 2.0, 10.0, False),
    ("text-naive", 0.5, 3.0, False),
    ("stamp-kst", 1.0, 7.0, False),
    ("stamp-utc", 0.0, 1.25, False),
    ("stamp-naive", 3.0, 0.0, False),
    ("datetime-kst", 0.25, 2.0, False),
    ("text-utc", 1.0, 1.0, True),
)
_TZ_WORDS = ("tz", "zone", "locali", "naive", "aware", "invalid comparison", "offset")


def _spell_zero(moment_s: int, spelling: str) -> Any:
    utc = pd.Timestamp(moment_s, unit="s", tz="UTC")
    if spelling == "text-utc":
        return utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    if spelling == "text-kst":
        return utc.tz_convert(KST).strftime("%Y-%m-%dT%H:%M:%S+09:00")
    if spelling == "text-naive":
        return utc.strftime("%Y-%m-%d %H:%M:%S")
    if spelling == "stamp-kst":
        return utc.tz_convert(KST)
    if spelling == "stamp-utc":
        return utc
    if spelling == "stamp-naive":
        return utc.tz_localize(None)
    return utc.tz_convert(KST).to_pydatetime()


def _t2_case(rng: np.random.Generator, number: int, spec: tuple) -> Tuple[pd.DataFrame, Any, np.ndarray, dict]:
    spelling, before_d, after_d, empty = spec
    lo = int(pd.Timestamp("2005-01-01", tz="UTC").timestamp())
    hi = int(pd.Timestamp("2025-06-01", tz="UTC").timestamp())
    zero_s = int(rng.integers(lo, hi))
    back, ahead = int(round(before_d * DAY_S)), int(round(after_d * DAY_S))
    if empty:
        offsets = np.concatenate([-back - rng.integers(2 * DAY_S, 5 * DAY_S, 12),
                                  ahead + rng.integers(2 * DAY_S, 5 * DAY_S, 12)])
    else:
        hour = 3600
        offsets = np.concatenate([
            [-back, ahead, 0, -back - 1, ahead + 1],
            rng.integers(-back, ahead + 1, 25),
            -back - rng.integers(60, 2 * DAY_S, 10), ahead + rng.integers(60, 2 * DAY_S, 10),
            ahead + rng.integers(hour, 8 * hour, 3), -back - rng.integers(hour, 8 * hour, 3),
            ahead - rng.integers(hour, 8 * hour, 3), -back + rng.integers(hour, 8 * hour, 3),
        ])
    offsets = rng.permutation(np.unique(offsets.astype(np.int64)))
    n = offsets.size
    lat, lon = random_points(rng, n)
    origin = pd.to_datetime(zero_s + offsets, unit="s", utc=True)
    df = pd.DataFrame({"event_id": [f"W{number}{j:03d}" for j in range(n)], "origin_utc": origin})
    df["origin_kst"] = df["origin_utc"].dt.tz_convert(KST)
    df["latitude"], df["longitude"] = np.round(lat, 4), np.round(lon, 4)
    for key, col in _filler(rng, n).items():
        df[key] = col
    df.index = pd.Index(3000 + rng.permutation(n))
    info = {"time zero": str(_spell_zero(zero_s, spelling)) if spelling != "datetime-kst" else
            f"datetime {_spell_zero(zero_s, spelling).isoformat()}", "zero type": type(
                _spell_zero(zero_s, spelling)).__name__, "days_before": before_d, "days_after": after_d,
            "rows": n}
    return df, _spell_zero(zero_s, spelling), offsets, {"back": back, "ahead": ahead, "info": info}


def _t2_ids(df: pd.DataFrame, offsets: np.ndarray, back: int, ahead: int, shift: int = 0) -> List[str]:
    """Event ids inside the window (shifted by `shift` seconds), ordered by time: by construction."""
    rel = offsets - shift
    inside = np.flatnonzero((rel >= -back) & (rel <= ahead))
    order = inside[np.argsort(offsets[inside], kind="stable")]
    return [str(df["event_id"].iat[j]) for j in order]


def check_T2(target: Any, ctx: Any) -> Outcome:
    trials = max(2, int(ctx.criteria.get("trials", len(T2_CASES))))
    specs = [T2_CASES[i % len(T2_CASES)] for i in range(trials)]
    ok: List[bool] = []
    fails: List[Tuple[str, dict]] = []
    for number, spec in enumerate(specs):
        df, zero, offsets, extra = _t2_case(ctx.rng, number, spec)
        back, ahead = extra["back"], extra["ahead"]
        pristine, given = df.copy(deep=True), df.copy(deep=True)
        got, err = _call(target, given, zero, spec[1], spec[2])
        category, shown, error = None, None, None
        if err is not None:
            if isinstance(err, (TypeError, ValueError)) and any(w in str(err).lower() for w in _TZ_WORDS):
                category, shown = "time-zone", f"{type(err).__name__}: {str(err)[:120]}"
            else:
                raise err
        elif not isinstance(got, pd.DataFrame) or list(got.columns) != list(df.columns):
            category = "return-type"
            shown = f"a {type(got).__name__}" + (f" with columns {list(got.columns)}" if
                                                  isinstance(got, pd.DataFrame) else "")
        else:
            ids = [str(x) for x in got["event_id"]]
            want = _t2_ids(df, offsets, back, ahead)
            if sorted(ids) == sorted(want):
                if ids != want:
                    category, shown = "sorting", "the right events in another order"
                elif not _unchanged(given, pristine):
                    category, shown = "changed-input", "df was changed by your function"
            else:
                shown = f"{len(ids)} rows"
                error = f"{len(set(want) - set(ids))} events missing, {len(set(ids) - set(want))} extra"
                ends = {str(df["event_id"].iat[j]) for j in np.flatnonzero((offsets == -back) | (offsets == ahead))}
                if any(sorted(ids) == sorted(_t2_ids(df, offsets, back, ahead, s)) for s in
                       (NINE_HOURS_S, -NINE_HOURS_S)):
                    category = "time-zone"
                elif (set(ids) ^ set(want)) <= ends and len(ids) == len(set(ids)):
                    category = "inclusive-ends"
                else:
                    category = "wrong-rows"
        ok.append(category is None)
        if category is not None:
            example = {"inputs": extra["info"], "got": shown}
            if error:
                example["error"] = error
            fails.append((category, example))
    if not fails:
        return outcome_from_cases(ok)
    order = ("return-type", "time-zone", "inclusive-ends", "sorting", "changed-input", "wrong-rows")
    seen = {c for c, _ in fails}
    category = next(c for c in order if c in seen)
    example = next(ex for c, ex in fails if c == category)
    return outcome_from_cases(ok, category=category, example=example)


# --------------------------------------------------------------------------- M04-T3 match two lists
T3_LIMITS = ((10.0, 20.0), (5.0, 10.0), (30.0, 50.0), (16.0, 25.0), (8.0, 15.0), (20.0, 30.0))
# group kind -> how many of them in every made-up pair of catalogs
T3_GROUPS = (("pair", 10), ("a_only", 4), ("b_only", 4), ("far", 3), ("late", 3), ("rival_after", 2),
             ("rival_before", 2), ("rival_b", 2))
T3_COLUMNS = ["id_a", "id_b", "dt_s", "dist_km"]


class _T3Case:
    """A pair of made-up catalogs and everything known about them from how they were built."""

    def __init__(self) -> None:
        self.a: List[Tuple[float, float, float]] = []   # (seconds, lat, lon)
        self.b: List[Tuple[float, float, float]] = []
        self.truth: List[Tuple[int, int]] = []          # (row in a, row in b)
        self.decoys: List[Tuple[int, int]] = []         # too far or too late: never a pair
        self.rivals: List[Tuple[int, int]] = []         # candidates that must lose to the true partner

    def add_a(self, t: float, lat: float, lon: float) -> int:
        self.a.append((t, lat, lon))
        return len(self.a) - 1

    def add_b(self, t: float, lat: float, lon: float) -> int:
        self.b.append((t, lat, lon))
        return len(self.b) - 1


def _t3_build(rng: np.random.Generator, max_dt: float, max_km: float) -> _T3Case:
    case = _T3Case()
    kinds = [k for k, count in T3_GROUPS for _ in range(count)]
    kinds = [kinds[i] for i in rng.permutation(len(kinds))]
    start = pd.Timestamp("2012-01-01", tz="UTC").timestamp()
    anchors = start + np.cumsum(rng.uniform(3 * 3600, 20 * DAY_S, len(kinds)))
    lat0, lon0 = random_points(rng, len(kinds), (34.2, 37.8), (126.2, 129.3))
    signs = rng.permutation(np.resize([-1.0, 1.0], len(kinds)))
    ms = lambda x: float(np.round(x, 3))  # noqa: E731 - times kept to the millisecond
    for g, kind in enumerate(kinds):
        t, la, lo, sign = float(anchors[g]), float(lat0[g]), float(lon0[g]), float(signs[g])
        turn = rng.uniform(0.0, 2.0 * np.pi, 3)
        if kind == "a_only":
            case.add_a(t, la, lo)
        elif kind == "b_only":
            case.add_b(t, la, lo)
        elif kind == "pair":
            ia = case.add_a(t, la, lo)
            ib = case.add_b(ms(t + sign * rng.uniform(0.05, 0.3) * max_dt),
                            *_moved(la, lo, rng.uniform(0.0, 0.5) * max_km, turn[0]))
            case.truth.append((ia, ib))
        elif kind == "far":
            ia = case.add_a(t, la, lo)
            ib = case.add_b(ms(t + sign * rng.uniform(0.0, 0.5) * max_dt),
                            *_moved(la, lo, rng.uniform(1.8, 4.0) * max_km, turn[0]))
            case.decoys.append((ia, ib))
        elif kind == "late":
            ia = case.add_a(t, la, lo)
            ib = case.add_b(ms(t + sign * rng.uniform(1.6, 3.0) * max_dt),
                            *_moved(la, lo, rng.uniform(0.0, 0.5) * max_km, turn[0]))
            case.decoys.append((ia, ib))
        else:
            ia = case.add_a(t, la, lo)
            tb = ms(t + sign * rng.uniform(0.05, 0.2) * max_dt)
            near_km = rng.uniform(0.3, 0.5) * max_km if kind == "rival_b" else rng.uniform(0.0, 0.5) * max_km
            lb, ob = _moved(la, lo, near_km, turn[0])
            ib = case.add_b(tb, lb, ob)
            case.truth.append((ia, ib))
            gap = rng.uniform(0.5, 0.9) * max_dt
            if kind == "rival_after":        # a second event of catalog a, later than both, nearer to b
                ir = case.add_a(ms(tb + gap), *_moved(lb, ob, rng.uniform(0.0, 0.3) * max_km, turn[1]))
                case.rivals.append((ir, ib))
            elif kind == "rival_before":     # a second event of catalog a, earlier than both, nearer to b
                ir = case.add_a(ms(tb - gap), *_moved(lb, ob, rng.uniform(0.0, 0.3) * max_km, turn[1]))
                case.rivals.append((ir, ib))
            else:                            # a second event of catalog b, farther in time but almost on top
                jr = case.add_b(ms(t - sign * gap), *_moved(la, lo, rng.uniform(0.0, 0.05) * max_km, turn[1]))
                case.rivals.append((ia, jr))
    return case


def _t3_frames(rng: np.random.Generator, case: _T3Case, tag: str) -> Tuple[pd.DataFrame, pd.DataFrame,
                                                                             List[str], List[str]]:
    """Catalog DataFrames in shuffled row order, with ids that say nothing about the groups."""
    frames, ids = [], []
    for side, rows in (("A", case.a), ("B", case.b)):
        n = len(rows)
        names = [f"{side}{tag}{j:03d}" for j in rng.permutation(n)]
        sec = np.array([r[0] for r in rows])
        df = pd.DataFrame({"event_id": names,
                           "origin_utc": pd.to_datetime(np.round(sec * 1000.0).astype(np.int64), unit="ms", utc=True),
                           "latitude": np.round([r[1] for r in rows], 5),
                           "longitude": np.round([r[2] for r in rows], 5)})
        for key, col in _filler(rng, n).items():
            df[key] = col
        order = rng.permutation(n)
        df = df.iloc[order]
        df.index = pd.Index(100 + rng.permutation(n))
        frames.append(df)
        ids.append(names)
    return frames[0], frames[1], ids[0], ids[1]


def _t3_expected(case: _T3Case, ids_a: List[str], ids_b: List[str], a: pd.DataFrame,
                 b: pd.DataFrame) -> Dict[Tuple[str, str], Tuple[float, float]]:
    """(id_a, id_b) -> (dt_s, dist_km) for the true pairs: times from construction, distances from ObsPy."""
    pos_a = a.set_index("event_id")
    pos_b = b.set_index("event_id")
    out = {}
    for ia, ib in case.truth:
        na, nb = ids_a[ia], ids_b[ib]
        dt = (pos_b.at[nb, "origin_utc"] - pos_a.at[na, "origin_utc"]).value / 1e9
        km = float(_oracle_km(pos_a.at[na, "latitude"], pos_a.at[na, "longitude"],
                              pos_b.at[nb, "latitude"], pos_b.at[nb, "longitude"]))
        out[(na, nb)] = (float(dt), km)
    return out


def _t3_pairs(got: Any) -> Optional[List[Tuple[str, str, float, float]]]:
    if not isinstance(got, pd.DataFrame) or not set(T3_COLUMNS) <= set(map(str, got.columns)):
        return None
    try:
        return [(str(r[0]), str(r[1]), float(r[2]), float(r[3]))
                for r in got[T3_COLUMNS].itertuples(index=False, name=None)]
    except (TypeError, ValueError):
        return None


def _t3_verdict(got: Any, expected: Dict[Tuple[str, str], Tuple[float, float]], decoys: set, rivals: set,
                crit: dict) -> Tuple[Optional[str], Any, Any]:
    rows = _t3_pairs(got)
    if rows is None:
        cols = list(got.columns) if isinstance(got, pd.DataFrame) else None
        return "format", f"a {type(got).__name__}" + (f" with columns {cols}" if cols is not None else ""), None
    pairs = [(a, b) for a, b, _, _ in rows]
    if len({a for a, _ in pairs}) < len(pairs) or len({b for _, b in pairs}) < len(pairs):
        return "many-to-one", f"{len(pairs)} pairs", "an event appears in two pairs"
    found, truth = set(pairs), set(expected)
    if found == truth:
        dt_tol = float(crit.get("dt_tol_s", 1e-3))
        rel, absol = float(crit.get("dist_rel_tol", 0.01)), float(crit.get("dist_abs_tol_km", 0.05))
        dt_ok = [abs(dt - expected[(a, b)][0]) <= dt_tol for a, b, dt, _ in rows]
        if not all(dt_ok):
            flipped = all(abs(dt + expected[(a, b)][0]) <= dt_tol for a, b, dt, _ in rows)
            j = dt_ok.index(False)
            return ("dt-sign" if flipped else "values"), f"dt_s {rows[j][2]:.3f}", \
                f"{rows[j][2] - expected[pairs[j]][0]:+.3f} s"
        for a, b, _, km in rows:
            want = expected[(a, b)][1]
            if not abs(km - want) <= max(absol, rel * want):
                return "values", f"dist_km {km:.3f}", f"{km - want:+.3f} km"
        return None, None, None
    shown = f"{len(found)} pairs"
    error = f"{len(truth - found)} true pairs missing, {len(found - truth)} wrong pairs"
    if found & decoys or (truth and not found):
        return "units", shown, error
    if found & rivals:
        return "closest-first", shown, error
    return "wrong-pairs", shown, error


def _t3_probe(kind: str) -> Tuple[pd.DataFrame, pd.DataFrame, float, float, set, str]:
    """Four tiny cases that isolate one slip each; their answers are obvious from the layout."""
    t0 = pd.Timestamp("2019-03-14T05:06:07", tz="UTC")
    lat, lon = 36.25, 128.10

    def table(prefix: str, rows: Sequence[Tuple[float, float, float]]) -> pd.DataFrame:
        return pd.DataFrame({"event_id": [f"{prefix}{j + 1}" for j in range(len(rows))],
                             "origin_utc": [t0 + pd.Timedelta(seconds=s) for s, _, _ in rows],
                             "latitude": [r[1] for r in rows], "longitude": [r[2] for r in rows],
                             "depth_km": 10.0, "ml": 2.0})

    a = table("PA", [(0.0, lat, lon)])
    near = _moved(lat, lon, 1.0, 0.7)
    if kind == "earlier":      # b three seconds before a, 1 km away: one pair
        return a, table("PB", [(-3.0, *near)]), 10.0, 20.0, {("PA1", "PB1")}, "time-difference"
    if kind == "wrapped":      # b an hour before a, and b one day and 3 s after a, same place: no pair
        return a, table("PB", [(-3600.0, lat, lon), (DAY_S + 3.0, lat, lon)]), 10.0, 20.0, set(), "time-difference"
    if kind == "far":          # b at the same time, 50 km away: no pair
        return a, table("PB", [(2.0, *_moved(lat, lon, 50.0, 2.0))]), 10.0, 20.0, set(), "units"
    return a, table("PB", [(2.0, *near)]), 10.0, 20.0, {("PA1", "PB1")}, "units"   # 2 s, 1 km: one pair


def check_T3(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    trials = max(2, int(crit.get("trials", len(T3_LIMITS))))
    ok: List[bool] = []
    fails: List[Tuple[str, dict]] = []
    for kind in ("earlier", "wrapped", "far", "near"):
        a, b, max_dt, max_km, truth, slip = _t3_probe(kind)
        got, err = _call(target, a.copy(), b.copy(), max_dt, max_km)
        if err is not None:
            raise err
        rows = _t3_pairs(got)
        inputs = {"probe": kind, "max_dt_s": max_dt, "max_dist_km": max_km,
                  "b relative to a": [f"{(t - a['origin_utc'].iat[0]).total_seconds():+.0f} s"
                                      for t in b["origin_utc"]]}
        if rows is None:
            category = "format"
            shown = f"a {type(got).__name__}"
        else:
            found = {(x, y) for x, y, _, _ in rows}
            category = None if found == truth else slip
            shown = f"{len(found)} pairs"
        ok.append(category is None)
        if category is not None:
            fails.append((category, {"inputs": inputs, "got": shown,
                                     "error": f"{len(truth)} pair(s) expected"}))
    for number in range(trials):
        max_dt, max_km = T3_LIMITS[number % len(T3_LIMITS)]
        case = _t3_build(ctx.rng, max_dt, max_km)
        a, b, ids_a, ids_b = _t3_frames(ctx.rng, case, str(number))
        expected = _t3_expected(case, ids_a, ids_b, a, b)
        decoys = {(ids_a[i], ids_b[j]) for i, j in case.decoys}
        rivals = {(ids_a[i], ids_b[j]) for i, j in case.rivals}
        given_a, given_b = a.copy(deep=True), b.copy(deep=True)
        inputs = {"max_dt_s": max_dt, "max_dist_km": max_km, "rows of cat_a": len(a), "rows of cat_b": len(b),
                  "true pairs": len(expected)}
        got, err = _call(target, given_a, given_b, max_dt, max_km)
        if err is not None:
            if isinstance(err, ValueError) and "sorted" in str(err).lower():
                category, shown, error = "unsorted", f"ValueError: {str(err)[:100]}", None
            else:
                raise err
        else:
            category, shown, error = _t3_verdict(got, expected, decoys, rivals, crit)
            if category is None and not (_unchanged(given_a, a) and _unchanged(given_b, b)):
                category, shown = "changed-input", "cat_a or cat_b was changed by your function"
        if category not in (None, "format", "changed-input"):
            in_order_a = a.sort_values("origin_utc", kind="stable").reset_index(drop=True)
            in_order_b = b.sort_values("origin_utc", kind="stable").reset_index(drop=True)
            again, err2 = _call(target, in_order_a, in_order_b, max_dt, max_km)
            if err2 is None and _t3_verdict(again, expected, decoys, rivals, crit)[0] is None:
                category = "unsorted"
        ok.append(category is None)
        if category is not None:
            example = {"inputs": inputs, "got": shown}
            if error:
                example["error"] = error
            fails.append((category, example))
    if not fails:
        return outcome_from_cases(ok, note=f"The check ran 4 small probes and {trials} made-up pairs of catalogs.")
    order = ("format", "time-difference", "units", "many-to-one", "unsorted", "closest-first", "dt-sign", "values",
             "changed-input", "wrong-pairs")
    seen = {c for c, _ in fails}
    category = next(c for c in order if c in seen)
    example = next(ex for c, ex in fails if c == category)
    return outcome_from_cases(ok, category=category, example=example)


# ----------------------------------------------------------------------- M04-T4 completeness by eye
T4_EPOCHS = {"1978-2007": (1978, 2007), "2008-2015": (2008, 2015), "2016-2017": (2016, 2017),
             "2018-2026": (2018, 2026)}
T4_FMD_CASES = (0, 4, 6)          # the T1 cases the fmd function must pass again: plain, negative, sparse
T1_RULES = ("seismostats", "sgtl_tutorial")   # the forbidden list of M04-T1 (checks/specs/M04.yaml)


def _t4_own_fmd(fmd: Any, rng: np.random.Generator, tol: float) -> bool:
    """True when the student's fmd passes made-up cases of task 1 again (bin counts known from how the
    magnitudes were built) under the library rule of task 1."""
    from .. import astguard

    if not callable(fmd) or not astguard.check_function(fmd, T1_RULES).ok:
        return False
    for number in T4_FMD_CASES:
        spec = T1_CASES[number]
        whole, mags, given = _t1_case(rng, spec)
        got, err = _call(fmd, given, dm=spec[0])
        if err is not None:
            raise err
        parts = _t1_parse(got)
        if parts is None or _t1_verdict(parts, whole, mags, spec[0], tol)[0] is not None:
            return False
    return True


def check_T4(target: Any, ctx: Any) -> Outcome:
    tol = float(ctx.criteria.get("tolerance", 0.3))
    n = len(T4_EPOCHS)
    note = ("The check applied the rule of thumb to the counts of your own fmd for each epoch of the shipped "
            "catalog; it has no values of its own and prints none.")
    if not isinstance(target, dict) or set(map(str, target)) != {"mc_by_eye", "fmd"}:
        keys = sorted(map(str, target)) if isinstance(target, dict) else type(target).__name__
        return outcome_from_cases([False] * n, category="keys", example={"inputs": "answer", "got": keys}, note=note)
    by_eye = target["mc_by_eye"]
    if not isinstance(by_eye, dict) or set(map(str, by_eye)) != set(T4_EPOCHS) or \
            not all(isinstance(k, str) for k in by_eye):
        keys = sorted(map(str, by_eye)) if isinstance(by_eye, dict) else type(by_eye).__name__
        return outcome_from_cases([False] * n, category="keys", example={"inputs": "mc_by_eye", "got": keys},
                                  note=note)
    bad_type = [k for k, v in by_eye.items() if isinstance(v, bool) or not isinstance(v, numbers.Real)
                or not np.isfinite(float(v))]
    if bad_type:
        return outcome_from_cases([k not in bad_type for k in T4_EPOCHS], category="type",
                                  example={"inputs": {"epoch": bad_type[0]}, "got": repr(by_eye[bad_type[0]])},
                                  note=note)
    if not _t4_own_fmd(target["fmd"], ctx.rng, float(ctx.criteria.get("center_tol", 1e-6))):
        return outcome_from_cases([False] * n, category="fmd", note=note)
    from .. import data as _data

    cat = _data.kma_catalog()
    years = cat["origin_utc"].dt.year.to_numpy()
    ok = []
    for name, (first, last) in T4_EPOCHS.items():
        got, err = _call(target["fmd"], cat.loc[(years >= first) & (years <= last), "ml"].copy(), dm=0.1)
        if err is not None:
            raise err
        parts = _t1_parse(got)
        if parts is None:
            return outcome_from_cases([False] * n, category="fmd", note=note)
        centers, per_bin = parts[0], parts[1]
        tallest = centers[per_bin == per_bin.max()]           # any of tied bins counts
        ok.append(bool(np.any(np.abs(float(by_eye[name]) - (tallest + 0.2)) <= tol + 1e-9)))
    first_bad = next((k for k, good in zip(T4_EPOCHS, ok) if not good), None)
    example = None if first_bad is None else {"inputs": {"epoch": first_bad}, "got": float(by_eye[first_bad])}
    return outcome_from_cases(ok, category="outside", example=example, real_data=True, note=note)


# ------------------------------------------------------------------- M04-T5 a ratio around one line
# (years handed over, b-value, events per year, lowest tenth, years with an excess, years without high-bin
#  events, years without low-bin events, low bins, high bins, share of noisy magnitudes, late-December events)
T5_CASES = (
    {"years": list(range(2018, 2024)), "b": 1.0, "per_year": 1500, "low_k": 10, "excess": "all"},
    {"years": range(2008, 2016), "b": 0.9, "per_year": 400, "low_k": 5, "excess": "half", "no_high": 1},
    {"years": np.array([2021, 2019, 2020]), "b": 1.1, "per_year": 900, "low_k": 8, "excess": "all"},
    {"years": [2015, 2016, 2017, 2030], "b": 1.0, "per_year": 700, "low_k": 6, "excess": "none", "no_low": 1,
     "absent": [2030]},
    {"years": [2010, 2011, 2012], "b": 1.0, "per_year": 1200, "low_k": 9, "excess": "none",
     "low": (1.4,), "high": (1.5, 1.6)},
    {"years": range(2001, 2006), "b": 0.8, "per_year": 800, "low_k": 15, "excess": "half",
     "low": (2.3, 2.4), "high": (2.5, 2.6, 2.7)},
    {"years": [2020, 2021, 2022], "b": 1.0, "per_year": 1000, "low_k": 7, "excess": "all", "noise": 0.0,
     "late": 25},
)
T5_DEFAULT_LOW, T5_DEFAULT_HIGH = (1.8, 1.9), (2.0, 2.1)


def _t5_build(rng: np.random.Generator, spec: dict, number: int) -> Tuple[pd.DataFrame, dict]:
    years = list(map(int, spec["years"]))
    low = spec.get("low", T5_DEFAULT_LOW)
    high = spec.get("high", T5_DEFAULT_HIGH)
    low_k = [int(np.rint(v * 10)) for v in low]
    high_k = [int(np.rint(v * 10)) for v in high]
    present = [yr for yr in years if yr not in spec.get("absent", [])]
    excess_years = {"all": present, "half": present[::2], "none": []}[spec["excess"]]
    no_high = set(rng.choice(present, spec.get("no_high", 0), replace=False).tolist()) if spec.get("no_high") else set()
    no_low = set(rng.choice(present, spec.get("no_low", 0), replace=False).tolist()) if spec.get("no_low") else set()
    step_up = 10.0 ** (-0.1 * spec["b"])
    tenths, seconds, utc_year = [], [], []
    for y in present:
        k = spec["low_k"] + rng.geometric(1.0 - step_up, int(rng.poisson(spec["per_year"]))) - 1
        if y in excess_years:
            n_low_now = int(np.isin(k, low_k).sum())
            k = np.concatenate([k, rng.choice(low_k, int(rng.uniform(1.5, 4.0) * max(n_low_now, 5)))])
        if y in no_high:
            k = k[~np.isin(k, high_k)]
        if y in no_low:
            k = k[~np.isin(k, low_k)]
        start = pd.Timestamp(f"{y}-01-01", tz="UTC").timestamp()
        end = pd.Timestamp(f"{y + 1}-01-01", tz="UTC").timestamp()
        when = rng.uniform(start, end - 1.0, k.size)
        counted = np.flatnonzero(np.isin(k, low_k + high_k))
        late = rng.choice(counted, min(counted.size, int(spec.get("late", 8))), replace=False)
        when[late] = end - rng.uniform(1.0, 9 * 3600 - 1.0, late.size)   # 15:00-24:00 UTC on 31 December
        tenths.append(k)
        seconds.append(np.floor(when))
        utc_year.append(np.full(k.size, y))
    k_all = np.concatenate(tenths).astype(np.int64)
    sec_all = np.concatenate(seconds).astype(np.int64)
    year_all = np.concatenate(utc_year).astype(np.int64)
    kst_year = pd.to_datetime(sec_all + NINE_HOURS_S, unit="s", utc=True).year.to_numpy()
    noise_share = float(spec.get("noise", 0.4))
    wobble = rng.choice([-1.0, 1.0], k_all.size) * 10.0 ** rng.uniform(-9.0, -7.0, k_all.size)
    clean_ml = np.round(k_all / 10.0, 1)
    ml = np.where(rng.random(k_all.size) < noise_share, clean_ml + wobble, clean_ml)
    order = rng.permutation(k_all.size)
    df = pd.DataFrame({"event_id": [f"Y{number}{j:05d}" for j in range(k_all.size)],
                       "origin_utc": pd.to_datetime(sec_all[order], unit="s", utc=True)})
    df["origin_kst"] = df["origin_utc"].dt.tz_convert(KST)
    lat, lon = random_points(rng, k_all.size)
    df["latitude"], df["longitude"] = np.round(lat, 3), np.round(lon, 3)
    df["depth_km"] = np.round(rng.uniform(2.0, 20.0, k_all.size), 1)
    df["ml"] = ml[order]
    df.index = pd.Index(50_000 + rng.permutation(k_all.size))

    def ratios(year_of: np.ndarray, top: List[int], bottom: List[int]) -> np.ndarray:
        out = []
        for y in years:
            n_top = int(np.count_nonzero((year_of == y) & np.isin(k_all, top)))
            n_bottom = int(np.count_nonzero((year_of == y) & np.isin(k_all, bottom)))
            out.append(n_top / n_bottom if n_bottom else np.nan)
        return np.array(out, dtype=float)

    clean = df.copy()
    clean["ml"] = clean_ml[order]
    info = {"years": years, "low": tuple(low), "high": tuple(high), "rows": int(k_all.size), "spec": spec,
            "truth": ratios(year_all, low_k, high_k), "truth_kst": ratios(kst_year, low_k, high_k),
            "truth_swapped": ratios(year_all, high_k, low_k), "clean": clean}
    return df, info


def _t5_call(target: Any, df: pd.DataFrame, info: dict) -> Tuple[Any, Optional[BaseException]]:
    spec = info["spec"]
    if "low" in spec or "high" in spec:
        return _call(target, df, spec["years"], low=tuple(info["low"]), high=tuple(info["high"]))
    return _call(target, df, spec["years"])


def _t5_values(got: Any, years: List[int]) -> Tuple[Optional[str], Optional[np.ndarray]]:
    if not isinstance(got, pd.Series):
        return "format", None
    try:
        idx = [int(v) for v in got.index]
    except (TypeError, ValueError):
        return "format", None
    if idx != years:
        return ("missing-years" if set(idx) < set(years) else "format"), None
    try:
        return None, got.to_numpy(dtype=float)
    except (TypeError, ValueError):
        return "format", None


def _same(a: np.ndarray, b: np.ndarray) -> bool:
    return bool(a.shape == b.shape and np.allclose(a, b, rtol=1e-9, atol=1e-12, equal_nan=True))


def check_T5(target: Any, ctx: Any) -> Outcome:
    trials = max(2, int(ctx.criteria.get("trials", len(T5_CASES))))
    ok: List[bool] = []
    fails: List[Tuple[str, dict, bool]] = []   # (category, example, custom bins?)
    first_case: Optional[Tuple[pd.DataFrame, dict, np.ndarray]] = None
    for number in range(trials):
        spec = T5_CASES[number % len(T5_CASES)]
        df, info = _t5_build(ctx.rng, spec, number)
        years, truth = info["years"], info["truth"]
        pristine, given = df.copy(deep=True), df.copy(deep=True)
        got, err = _t5_call(target, given, info)
        custom = "low" in spec or "high" in spec
        inputs = {"years": years, "low": info["low"], "high": info["high"], "rows": info["rows"]}
        category, shown = None, None
        if err is not None:
            if isinstance(err, ZeroDivisionError):
                category, shown = "zero-division", f"ZeroDivisionError: {err}"
            else:
                raise err
        else:
            category, values = _t5_values(got, years)
            shown = got if not isinstance(got, pd.Series) else {y: (None if not np.isfinite(v) else round(float(v), 4))
                                                                 if isinstance(v, (float, np.floating)) else v
                                                                 for y, v in zip(got.index, got.to_numpy())}
            if category is None and values is not None:
                if _same(values, truth):
                    if not _unchanged(given, pristine):
                        category = "changed-input"
                    elif number == 0:
                        first_case = (df, info, values)
                else:
                    nan_truth = np.isnan(truth)
                    if _same(values, info["truth_swapped"]):
                        category = "inverted"
                    elif _same(values, info["truth_kst"]):
                        category = "time-zone"
                    elif np.any(np.isinf(values)) or np.any(nan_truth & np.isfinite(values)):
                        category = "zero-division"
                    else:
                        again, err2 = _t5_call(target, info["clean"].copy(), info)
                        _, again_values = _t5_values(again, years) if err2 is None else (None, None)
                        category = "float-binning" if again_values is not None and _same(again_values, truth) \
                            else "wrong-values"
        ok.append(category is None)
        if category is not None:
            fails.append((category, {"inputs": inputs, "got": shown}, custom))
    # two property tests on the first catalog: the row order and listing every event twice change nothing
    if first_case is not None:
        df, info, values = first_case
        for label, variant in (("rows shuffled", df.sample(frac=1.0, random_state=int(ctx.rng.integers(1 << 30)))),
                               ("every event twice", pd.concat([df, df]))):
            got, err = _t5_call(target, variant, info)
            good = err is None and _t5_values(got, info["years"])[1] is not None and \
                _same(_t5_values(got, info["years"])[1], values)
            ok.append(good)
            if not good:
                fails.append(("property", {"inputs": {"test": label, "rows": len(variant)},
                                           "got": "different ratios" if err is None else f"{type(err).__name__}"},
                              False))
    note = f"The check ran {trials} made-up catalogs" + (" and two property tests." if first_case is not None else ".")
    if not fails:
        return outcome_from_cases(ok, note=note)
    seen = [c for c, _, _ in fails]
    if all(custom for _, _, custom in fails) and len(fails) < trials:
        category = "custom-bins"
    else:
        order = ("format", "missing-years", "zero-division", "time-zone", "float-binning", "inverted", "custom-bins",
                 "property", "changed-input", "wrong-values")
        category = next(c for c in order if c in seen)
    example = next((ex for c, ex, _ in fails if c == category), fails[0][1])
    return outcome_from_cases(ok, category=category, example=example, note=note)


# ------------------------------------------------------------------ M04-T6 Ridgecrest from ComCat
T6_BOX = (35.4, 36.1, -117.9, -117.2)          # lat_min, lat_max, lon_min, lon_max (degrees)
T6_START, T6_END = pd.Timestamp("2019-07-04", tz="UTC"), pd.Timestamp("2019-08-04", tz="UTC")
T6_MIN_MAG = 2.5
T6_COLUMNS = ("origin_utc", "latitude", "longitude", "depth_km", "mag", "mag_type")
_ZONE_SUFFIX = re.compile(r"(Z|[+-]00:?00)$")


def _t6_cases(results: List[Tuple[bool, str]], note: str) -> Outcome:
    first = next((cat for good, cat in results if not good), None)
    return outcome_from_cases([good for good, _ in results], category=first, real_data=True, note=note)


def check_T6(target: Any, ctx: Any) -> Outcome:
    min_events = int(ctx.criteria.get("min_events", 1000))
    note = "The check read only your two files; it never contacts a data center."
    names = ("format", "no-data", "columns", "time", "box", "window", "magnitude", "too-few", "duplicates",
             "depth-units", "figure", "stale-figure")
    fail_from = lambda cat: _t6_cases([(names.index(c) < names.index(cat), c) for c in names], note)  # noqa: E731
    if not isinstance(target, dict) or set(target) != {"csv", "figure"} or \
            not all(isinstance(v, (str, os.PathLike)) for v in target.values()):
        return fail_from("format")
    table_path = Path(target["csv"]).expanduser()
    figure_path = Path(target["figure"]).expanduser()
    if not table_path.is_file():
        if os.environ.get("SGTL_SOLUTION_RUN", "") == "1":
            return Outcome(passed=True, n_cases=1, n_failed=0, category=None,
                           message="Skipped: no downloaded table (automatic solution run without network).",
                           details={"skipped": "solution run without network"})
        return fail_from("no-data")
    try:
        raw = pd.read_csv(table_path, dtype=str, keep_default_na=False)
    except Exception:  # noqa: BLE001 - an unreadable file is a columns problem for the student
        return fail_from("columns")
    if not set(T6_COLUMNS) <= set(raw.columns):
        return fail_from("columns")
    stamps = raw["origin_utc"].str.strip()
    try:
        when = pd.to_datetime(stamps, utc=True, format="ISO8601")
    except (TypeError, ValueError):
        when = None
    zoned = bool(len(stamps)) and bool(stamps.map(lambda s: bool(_ZONE_SUFFIX.search(s))).all())
    if when is None or not zoned or when.isna().any():
        return fail_from("time")
    num = {c: pd.to_numeric(raw[c], errors="coerce").to_numpy(dtype=float) for c in
           ("latitude", "longitude", "depth_km", "mag")}
    lat_min, lat_max, lon_min, lon_max = T6_BOX
    eps = 1e-9
    results = [(True, "format"), (True, "no-data"), (True, "columns"), (True, "time")]
    results.append((bool(np.all((num["latitude"] >= lat_min - eps) & (num["latitude"] <= lat_max + eps)
                                & (num["longitude"] >= lon_min - eps) & (num["longitude"] <= lon_max + eps))),
                    "box"))
    start, end = T6_START, T6_END
    results.append((bool(((when >= start) & (when <= end)).all()), "window"))
    results.append((bool(np.all(num["mag"] >= T6_MIN_MAG - eps)), "magnitude"))
    results.append((len(raw) >= min_events, "too-few"))
    keys = pd.DataFrame({"t": when.dt.tz_localize(None).astype("int64"), "la": np.round(num["latitude"], 5),
                         "lo": np.round(num["longitude"], 5)})
    results.append((not keys.duplicated().any(), "duplicates"))
    depth = num["depth_km"][np.isfinite(num["depth_km"])]
    results.append((depth.size > 0 and -5.0 <= float(np.median(depth)) <= 100.0, "depth-units"))
    is_png = False
    if figure_path.is_file() and figure_path.stat().st_size >= 5000:
        with open(figure_path, "rb") as fh:
            is_png = fh.read(8) == b"\x89PNG\r\n\x1a\n"
    results.append((is_png, "figure"))
    results.append((is_png and figure_path.stat().st_mtime >= table_path.stat().st_mtime - 1.0, "stale-figure"))
    return _t6_cases(results, note)
