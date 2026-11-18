"""Checkers for M03 · Getting seismic data: STP, stations, time windows, responses.

Where the truth comes from (DESIGN.md section 1, rule 1):

* M03-T1: construction. Origins are multiples of 10 ms drawn by the check and handed over as text (Z, +09:00,
  no zone), pandas Timestamps (UTC, KST, no zone), an aware datetime (KST) or an ObsPy UTCDateTime; the expected
  ends are those integers minus and plus the given seconds.
* M03-T2: construction. Stations are placed at chosen distances and bearings from a center (none near the
  radius), with start and end dates at chosen offsets from the day asked for; the distances the student reports
  are compared with ObsPy's geodesic distance (an independent library).
* M03-T3: construction for made-up SAC trees that the check writes with ObsPy into a temporary folder. On the
  student's own Sangju tree the check counts nothing: the function must run without changing the tree, and on a
  copy of one real band folder from which the check removed one component file of a complete station, the
  student's own result must gain exactly that gap and keep its counts (a relation between two runs of the
  student's function).
* M03-T4: oracle. ObsPy's Inventory.get_response(...).instrument_sensitivity on made-up inventories (each epoch
  gets a chosen overall value first, and its digitizer gain is set to agree with it) and on the installed
  StationMetadata files for random channels of the Sangju dataset. The student's function receives copies in
  which reading instrument_sensitivity, or calling get_response or ObsPy's response calculators, is recorded.
* M03-T5: construction. corrected_window gets Korean clock readings of chosen UTC moments (made with a fixed
  +09:00 offset). envelope_evidence gets made-up records whose answers are known from how they were built: a weak
  sine with whole cycles (its envelope is its amplitude, the noise level), a wave group of known size at a known
  time, offsets, a short loud group in the first 20 s, a louder group after the window, stations at known
  distances in shuffled order, and a colleague's window that misses or overlaps a record by a known number of
  samples. On the real records the check computes nothing of its own: the evidence table must be what the
  student's own (verified) envelope_evidence returns for the row's records, at the origin of the student's own
  corrected_window.

Failure categories are keys of ``checks/specs/M03.yaml``; the engine prints their fixed messages.
"""
from __future__ import annotations

import copy
import datetime as _dt
import numbers
import os
import shutil
import tempfile
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from ..synth import KST
from . import Outcome, outcome_from_cases

__all__ = ["check_T1", "check_T2", "check_T3", "check_T4", "check_T5"]

DATASET = "sangju2019"
HOUR_MS = 3_600_000.0
DAY_MS = 24 * HOUR_MS
SPHERE_KM = 6371.0


# ------------------------------------------------------------------------------------------- helpers
def _call(func: Any, *args: Any, **kwargs: Any) -> Tuple[Any, Optional[BaseException]]:
    """Run the student's code. NotImplementedError passes through (the engine reports NOT STARTED)."""
    try:
        return func(*args, **kwargs), None
    except NotImplementedError:
        raise
    except Exception as exc:  # noqa: BLE001 - classified by the caller
        return None, exc


def _first(fails: List[Tuple[str, Optional[dict]]], order: Sequence[str]) -> Tuple[str, Optional[dict]]:
    """The failure category that comes first in `order`, with the example of its first case."""
    seen = {c for c, _ in fails}
    category = next((c for c in order if c in seen), fails[0][0])
    return category, next(ex for c, ex in fails if c == category)


def _short(value: Any, limit: int = 160) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _iso_ms(text: Any) -> Optional[float]:
    """Milliseconds since 1970 for ISO text that names UTC explicitly (Z or +00:00); None for anything else."""
    if not isinstance(text, str):
        return None
    try:
        stamp = pd.Timestamp(text.strip())
    except (ValueError, TypeError, OverflowError):
        return None
    if stamp is pd.NaT or stamp.tzinfo is None or stamp.utcoffset() != _dt.timedelta(0):
        return None
    return stamp.value / 1.0e6


def _window_kind(got: Any, want: Tuple[float, float], before_s: float, after_s: float, tol_ms: float,
                 shifts: Sequence[Tuple[str, Sequence[float]]], whole_days: bool) -> Optional[str]:
    """None when got matches the window `want` (ms); otherwise the most telling failure category."""
    if not isinstance(got, (tuple, list)) or len(got) != 2:
        return "format"
    ends = [_iso_ms(got[0]), _iso_ms(got[1])]
    if ends[0] is None or ends[1] is None:
        return "format"
    off_a, off_b = ends[0] - want[0], ends[1] - want[1]
    if abs(off_a) <= tol_ms and abs(off_b) <= tol_ms:
        return None
    if ends[0] > ends[1] + tol_ms:
        return "sign"
    if abs(off_a - off_b) <= 1000.0:
        for category, hours in shifts:
            if any(abs(off_a - h * HOUR_MS) <= 1000.0 for h in hours):
                return category
        days = off_a / DAY_MS
        if whole_days and abs(days) > 0.5 and abs(days - round(days)) * DAY_MS <= 1000.0:
            return "rollover"
    if (abs(off_a - 2000.0 * before_s) <= tol_ms and abs(off_b) <= tol_ms) or \
            (abs(off_b + 2000.0 * after_s) <= tol_ms and abs(off_a) <= tol_ms):
        return "sign"
    if max(abs(off_a), abs(off_b)) < 1000.0 + tol_ms:
        return "precision"
    return "wrong-window"


def _offsets_text(got: Any, want: Tuple[float, float]) -> Optional[str]:
    try:
        a, b = _iso_ms(got[0]), _iso_ms(got[1])
    except Exception:  # noqa: BLE001 - only for the message
        return None
    if a is None or b is None:
        return None
    return f"start off by {(a - want[0]) / 1000.0:+.3f} s, end off by {(b - want[1]) / 1000.0:+.3f} s"


# ---------------------------------------------------------------------------- M03-T1 UTC windows
T1_SPELLINGS = ("text-z", "text-kst", "text-naive", "stamp-utc", "stamp-kst", "stamp-naive", "datetime-kst",
                "obspy")
T1_SECONDS = ((30.0, 470.0), (10.0, 60.0), (5.25, 120.5), (0.0, 300.0), (12.5, 0.75), (60.0, 1800.0))
T1_SHIFTS = (("kst", (9.0, -9.0)),)


def _t1_origin(millis: int, spelling: str) -> Any:
    utc = pd.Timestamp(millis, unit="ms", tz="UTC")
    korea = utc.tz_convert(KST)
    if spelling == "text-z":
        return utc.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if spelling == "text-kst":
        return korea.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+09:00"
    if spelling == "text-naive":
        return utc.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    if spelling == "stamp-utc":
        return utc
    if spelling == "stamp-kst":
        return korea
    if spelling == "stamp-naive":
        return utc.tz_localize(None)
    if spelling == "datetime-kst":
        return korea.to_pydatetime()
    from obspy import UTCDateTime

    return UTCDateTime(ns=int(millis) * 1_000_000)


def check_T1(target: Any, ctx: Any) -> Outcome:
    trials = max(len(T1_SPELLINGS), int(ctx.criteria.get("trials", 12)))
    tol_ms = 1000.0 * float(ctx.criteria.get("tol_s", 0.001)) + 1e-6
    low = int(pd.Timestamp("2005-01-01", tz="UTC").value // 10_000_000)
    high = int(pd.Timestamp("2026-06-01", tz="UTC").value // 10_000_000)
    ok: List[bool] = []
    fails: List[Tuple[str, Optional[dict]]] = []
    for number in range(trials):
        spelling = T1_SPELLINGS[number % len(T1_SPELLINGS)]
        before_s, after_s = T1_SECONDS[int(ctx.rng.integers(len(T1_SECONDS)))]
        millis = int(ctx.rng.integers(low, high)) * 10
        if number % 4 == 3:
            millis -= millis % 1000
        origin = _t1_origin(millis, spelling)
        got, err = _call(target, origin, before_s, after_s)
        if err is not None:
            raise err
        want = (millis - 1000.0 * before_s, millis + 1000.0 * after_s)
        verdict = _window_kind(got, want, before_s, after_s, tol_ms, T1_SHIFTS, whole_days=False)
        ok.append(verdict is None)
        if verdict is not None:
            shown = origin if isinstance(origin, str) else f"{type(origin).__name__}({origin})"
            example = {"inputs": {"origin_utc": shown, "before_s": before_s, "after_s": after_s},
                       "got": _short(got)}
            gap = _offsets_text(got, want) if verdict != "format" else None
            if gap:
                example["error"] = gap
            fails.append((verdict, example))
    if not fails:
        return outcome_from_cases(ok)
    category, example = _first(fails, ("format", "kst", "sign", "precision", "wrong-window"))
    return outcome_from_cases(ok, category=category, example=example)


# ------------------------------------------------------------------- M03-T2 stations on a given day
# (radius in km, how on_date is handed over, whether the table has an end_date column)
T2_SETUPS = ((100.0, "text", True), (50.0, "stamp", True), (150.0, "text", False), (20.0, "stamp", True),
             (100.0, "stamp", True), (75.0, "text", False), (120.0, "text", True), (35.0, "stamp", True))
T2_LETTERS = list("ABCDEGHIJKLMNOPRSTUWY")


def _t2_destination(lat0: float, lon0: float, km: float, bearing: float) -> Tuple[float, float]:
    """The point km kilometers from (lat0, lon0) toward `bearing` (radians), on the 6371 km sphere."""
    arc = km / SPHERE_KM
    p0, l0 = np.radians(lat0), np.radians(lon0)
    p1 = np.arcsin(np.sin(p0) * np.cos(arc) + np.cos(p0) * np.sin(arc) * np.cos(bearing))
    l1 = l0 + np.arctan2(np.sin(bearing) * np.sin(arc) * np.cos(p0), np.cos(arc) - np.sin(p0) * np.sin(p1))
    return float(np.degrees(p1)), float(np.degrees(l1))


def _t2_build(rng: np.random.Generator, setup: tuple) -> Tuple[pd.DataFrame, dict]:
    radius, _, with_end = setup
    lat0, lon0 = float(rng.uniform(34.6, 37.8)), float(rng.uniform(126.4, 129.3))
    day = pd.Timestamp("2008-01-01") + pd.Timedelta(days=int(rng.integers(0, 6200)))
    taken: set = set()

    def fresh_code() -> str:
        while True:
            text = "".join(rng.choice(T2_LETTERS, size=int(rng.integers(3, 5))))
            if text not in taken:
                taken.add(text)
                return text

    specs: List[dict] = []

    def put(kind: str, near: bool, begin: int, finish: Optional[int], net: Optional[str] = None,
            code: Optional[str] = None) -> None:
        share = rng.uniform(0.05, 0.95) if near else rng.uniform(1.05, 3.0)
        specs.append({"kind": kind, "near": near, "begin": begin, "finish": finish, "km": float(share * radius),
                      "net": net or str(rng.choice(["KS", "KG"])), "code": code or fresh_code()})

    def later() -> Optional[int]:
        if not with_end or rng.random() < 0.5:
            return None
        return int(rng.integers(1, 3000))

    for _ in range(7):
        put("running", True, -int(rng.integers(30, 4000)), later())
    for _ in range(5):
        put("far", False, -int(rng.integers(30, 4000)), later())
    for _ in range(3):
        put("future", True, int(rng.integers(1, 900)), later())
    put("first-day", True, 0, int(rng.integers(1, 3000)) if with_end else None)
    if with_end:
        for _ in range(3):
            stop = -int(rng.integers(1, 900))
            put("ended", True, stop - int(rng.integers(200, 3000)), stop)
        put("last-day", True, -int(rng.integers(100, 3000)), 0)
        moved = fresh_code()
        stop = -int(rng.integers(5, 400))
        put("moved-old", True, stop - 2000, stop, "KS", moved)
        put("moved-new", False, stop + 1, None, "KS", moved)
        moved = fresh_code()
        put("moved-old", False, stop - 2500, stop, "KG", moved)
        put("moved-new", True, stop + 1, None, "KG", moved)
        twin = fresh_code()
        put("twin-on", True, -int(rng.integers(100, 3000)), None, "KS", twin)
        put("twin-off", True, -3500, -int(rng.integers(5, 90)), "KG", twin)
    else:
        twin = fresh_code()
        put("twin-on", True, -int(rng.integers(100, 3000)), None, "KS", twin)
        put("twin-off", True, int(rng.integers(5, 90)), None, "KG", twin)

    from obspy.geodetics import gps2dist_azimuth

    rows = []
    for spec in specs:
        lat, lon = _t2_destination(lat0, lon0, spec["km"], float(rng.uniform(0.0, 2.0 * np.pi)))
        spec["oracle_km"] = gps2dist_azimuth(lat0, lon0, lat, lon)[0] / 1000.0
        spec["start"] = day + pd.Timedelta(days=spec["begin"])
        row = {"network": spec["net"], "station": spec["code"], "latitude": round(lat, 5),
               "longitude": round(lon, 5), "start_date": spec["start"]}
        if with_end:
            row["end_date"] = pd.NaT if spec["finish"] is None else day + pd.Timedelta(days=spec["finish"])
        row["elevation_m"] = float(np.round(rng.uniform(5.0, 900.0), 1))
        rows.append(row)
    order = rng.permutation(len(rows))
    table = pd.DataFrame([rows[i] for i in order])
    specs = [specs[i] for i in order]
    table["start_date"] = pd.to_datetime(table["start_date"])
    if with_end:
        table["end_date"] = pd.to_datetime(table["end_date"])
    table.index = pd.Index(700 + rng.permutation(len(table)))
    info = {"center": (round(lat0, 4), round(lon0, 4)), "radius_km": radius, "day": day, "specs": specs}
    return table, info


def _t2_key(net: Any, sta: Any, start: Any) -> Tuple[str, str, pd.Timestamp]:
    return str(net), str(sta), pd.Timestamp(start)


def _t2_unchanged(given: pd.DataFrame, pristine: pd.DataFrame) -> bool:
    try:
        return (list(given.columns) == list(pristine.columns) and given.index.equals(pristine.index)
                and given.equals(pristine))
    except Exception:  # noqa: BLE001
        return False


def _t2_verdict(got: Any, table: pd.DataFrame, info: dict, rel_tol: float) -> Tuple[Optional[str], Optional[str]]:
    specs = info["specs"]
    keys = [_t2_key(s["net"], s["code"], s["start"]) for s in specs]
    spec_of = dict(zip(keys, specs))

    def running(s: dict) -> bool:
        return s["begin"] <= 0 and (s["finish"] is None or s["finish"] >= 0)

    want = {k for k, s in spec_of.items() if running(s) and s["near"]}
    needed = set(table.columns) | {"distance_km"}
    if not isinstance(got, pd.DataFrame) or not needed <= set(got.columns):
        return "format", f"a {type(got).__name__}" + (f" with columns {list(got.columns)}"
                                                      if isinstance(got, pd.DataFrame) else "")
    try:
        have_list = [_t2_key(n, s, b) for n, s, b in zip(got["network"], got["station"], got["start_date"])]
    except (TypeError, ValueError):
        return "format", "start_date values that are not dates"
    have = set(have_list)
    missing, extra = want - have, have - want
    if missing or extra or len(have_list) != len(have):
        text = f"{len(missing)} running stations within the radius missing, {len(extra)} extra rows"
        edge = {k for k in missing if spec_of[k]["begin"] == 0 or spec_of[k]["finish"] == 0}
        no_end = {k for k in missing if spec_of[k]["finish"] is None} - edge
        idle_near = {k for k, s in spec_of.items() if s["near"] and not running(s)}
        busy_far = {k for k, s in spec_of.items() if not s["near"] and running(s)}
        if not extra and missing and missing <= edge:
            return "inclusive", text
        if not extra and missing and missing <= no_end:
            return "still-running", text
        if not missing and extra and extra <= idle_near:
            return "inactive", text
        if (extra and extra <= busy_far) or (missing and not extra and not missing <= no_end | edge):
            return "units", text
        return "wrong-rows", text
    km = pd.to_numeric(got["distance_km"], errors="coerce").to_numpy(dtype=float)
    if not np.all(np.isfinite(km)):
        return "distance", "distance_km values that are not numbers"
    if np.any(np.diff(km) < 0):
        return "sorting", "the right stations, not sorted by distance_km"
    oracle = np.array([spec_of[k]["oracle_km"] for k in have_list])
    off = np.abs(km - oracle) > rel_tol * oracle + 0.01
    if off.any():
        j = int(np.flatnonzero(off)[0])
        return "distance", f"{have_list[j][0]}.{have_list[j][1]}: distance_km {km[j]:.3f}, off by " \
                           f"{100.0 * (km[j] - oracle[j]) / oracle[j]:+.2f} %"
    return None, None


def check_T2(target: Any, ctx: Any) -> Outcome:
    trials = max(4, int(ctx.criteria.get("trials", len(T2_SETUPS))))
    rel_tol = float(ctx.criteria.get("dist_rel_tol", 0.006))
    ok: List[bool] = []
    fails: List[Tuple[str, Optional[dict]]] = []
    for number in range(trials):
        setup = T2_SETUPS[number % len(T2_SETUPS)]
        table, info = _t2_build(ctx.rng, setup)
        day_arg = info["day"].strftime("%Y-%m-%d") if setup[1] == "text" else info["day"]
        pristine, given = table.copy(deep=True), table.copy(deep=True)
        lat0, lon0 = info["center"]
        got, err = _call(target, given, lat0, lon0, info["radius_km"], day_arg)
        inputs = {"center": info["center"], "radius_km": info["radius_km"], "on_date": str(day_arg)[:10],
                  "rows": len(table), "end_date column": setup[2]}
        if err is not None:
            if not setup[2] and isinstance(err, (KeyError, AttributeError)):
                category, shown = "still-running", f"{type(err).__name__}: {str(err)[:80]}"
            else:
                raise err
        else:
            category, shown = _t2_verdict(got, table, info, rel_tol)
            if category is None and not _t2_unchanged(given, pristine):
                category, shown = "changed-input", "stations_df was changed by your function"
        ok.append(category is None)
        if category is not None:
            fails.append((category, {"inputs": inputs, "got": shown}))
    if not fails:
        return outcome_from_cases(ok)
    category, example = _first(fails, ("format", "still-running", "inclusive", "inactive", "units", "wrong-rows",
                                       "sorting", "distance", "changed-input"))
    return outcome_from_cases(ok, category=category, example=example)


# --------------------------------------------------------------------------- M03-T3 a SAC tree census
T3_KINDS = ("plain", "messy", "twins")
T3_GAP_PATTERNS = ("EZ", "NZ", "Z", "EN", "E")


def _t3_layout(rng: np.random.Generator, kind: str) -> Tuple[Dict[str, Dict[str, Dict[Tuple[str, str], str]]],
                                                                List[str]]:
    """event -> band -> {(net, sta): component letters}; and the extra (non-record) paths to create."""
    events: set = set()
    while len(events) < (4 if kind == "messy" else 3):
        moment = pd.Timestamp("2016-01-01", tz="UTC") + pd.Timedelta(seconds=int(rng.integers(0, 9 * 365 * 86400)))
        events.add(moment.strftime("%Y%m%d%H%M%S"))
    names = sorted(events)
    pool: List[Tuple[str, str]] = []
    while len(pool) < 9:
        code = "".join(rng.choice(T2_LETTERS, size=int(rng.integers(3, 5))))
        if all(code != c for _, c in pool):
            pool.append((str(rng.choice(["KS", "KG"])), code))
    if kind == "twins":
        pool[0] = ("KS", pool[1][1])
        pool[1] = ("KG", pool[1][1])
    tree: Dict[str, Dict[str, Dict[Tuple[str, str], str]]] = {}
    for event in names:
        per_band: Dict[str, Dict[Tuple[str, str], str]] = {}
        for band in ("EL", "HG", "HH"):
            picked = rng.choice(len(pool), size=int(rng.integers(3, 7)), replace=False)
            per_band[band] = {pool[int(i)]: ("ENZ" if rng.random() < 0.75 else
                                             str(rng.choice(T3_GAP_PATTERNS))) for i in picked}
        tree[event] = per_band
    first_band = tree[names[0]]["HH"]
    first_band[pool[2]] = "NZ"                     # every tree has a gap ...
    first_band[pool[3]] = "ENZ"                    # ... and a complete station
    extras: List[str] = []
    if kind == "twins":
        for band in ("HG", "HH"):
            tree[names[1]][band][pool[0]] = "ENZ"
            tree[names[1]][band][pool[1]] = "EZ"
    if kind == "messy":
        tree[names[-1]] = {}
        del tree[names[0]]["HG"]
        tree[names[1]]["EL"] = {}
        extras = ["README.txt", "stp_batch.txt", f"{names[0]}/notes.txt", f"{names[0]}/.sgtl-fetched",
                  f"{names[1]}/HH/notes.txt",
                  f"{names[1]}/HH/.DS_Store", f"{names[1]}/HH/old/{names[1]}.KS.OLDX.HHZ.sac"]
    return tree, extras


def _t3_write(root: Path, tree: dict, extras: List[str]) -> None:
    from obspy.io.sac import SACTrace

    samples = np.zeros(8, dtype=np.float32)
    root.mkdir(parents=True)
    for event, per_band in tree.items():
        (root / event).mkdir()
        stamp = (pd.Timestamp(event) - pd.Timedelta(seconds=30)).strftime("%Y%m%d%H%M%S")
        for band, members in per_band.items():
            (root / event / band).mkdir()
            for (net, sta), letters in members.items():
                for letter in letters:
                    record = SACTrace(delta=0.01, b=0.0, knetwk=net, kstnm=sta, kcmpnm=band + letter, data=samples)
                    record.write(str(root / event / band / f"{stamp}.{net}.{sta}.{band}{letter}.sac"))
    for extra in extras:
        path = root / extra
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == ".sac":
            SACTrace(delta=0.01, b=0.0, knetwk="KS", kstnm="OLDX", kcmpnm="HHZ", data=samples).write(str(path))
        else:
            path.write_text("not a record\n", encoding="utf-8")


def _t3_truth(tree: dict) -> dict:
    """Expected tables by construction: station counts, file counts, code-only counts and gap rows."""
    events = sorted(tree)
    bands = sorted({b for per_band in tree.values() for b in per_band})
    shape = (len(events), len(bands))
    stations, files, codes = np.zeros(shape), np.zeros(shape), np.zeros(shape)
    holes = []
    for i, event in enumerate(events):
        for j, band in enumerate(bands):
            members = tree[event].get(band, {})
            stations[i, j] = len(members)
            files[i, j] = sum(len(v) for v in members.values())
            codes[i, j] = len({sta for _, sta in members})
            for (net, sta), letters in members.items():
                absent = "".join(c for c in "ENZ" if c not in letters)
                if absent:
                    holes.append((event, f"{net}.{sta}", band, absent))
    holes.sort(key=lambda r: (r[0], r[2], r[1]))
    return {"events": events, "bands": bands, "stations": stations, "files": files, "codes": codes,
            "holes": holes}


def _t3_rows(got: Any) -> Optional[Tuple[pd.DataFrame, set]]:
    """The student's counts and the set of gap rows (event, station, band, missing), or None if not that shape."""
    if not (isinstance(got, (tuple, list)) and len(got) == 2 and all(isinstance(x, pd.DataFrame) for x in got)):
        return None
    counts, gaps = got
    if not {"event", "station", "band", "missing"} <= set(gaps.columns):
        return None
    return counts, {tuple(str(v) for v in r) for r in gaps[["event", "station", "band", "missing"]].itertuples(
        index=False)}


def _t3_real(target: Any, real_root: Path, scratch: Path, rng: np.random.Generator) -> Optional[str]:
    """The real tree, judged against the student's own results (the check counts nothing in it): the function
    runs on the tree without changing it; then, on a copy of one real event folder, the check removes one
    component file of a station that has all three, and the student's own gaps must gain exactly that row while
    the counts stay as they were."""
    before = _t3_snapshot(real_root)
    got, err = _call(target, real_root)
    if err is not None:
        raise err
    if _t3_rows(got) is None:
        return "format"
    if _t3_snapshot(real_root) != before:
        return "changed-tree"
    full: List[Tuple[Path, str, str, str]] = []           # (file, event, band, station) of complete stations
    for event in sorted(p for p in real_root.iterdir() if p.is_dir()):
        for band in sorted(p for p in event.iterdir() if p.is_dir()):
            parts: Dict[str, Dict[str, Path]] = {}
            for path in band.glob("*.sac"):
                bits = path.name.split(".")
                if len(bits) == 5:
                    parts.setdefault(f"{bits[1]}.{bits[2]}", {})[bits[3][-1:]] = path
            full += [(files[c], event.name, band.name, sta) for sta, files in parts.items()
                     if set(files) == {"E", "N", "Z"} for c in "ENZ"]
    if not full:
        return None
    path, event, band, station = full[int(rng.integers(0, len(full)))]
    copy_root = scratch / "real" / "SAC"
    shutil.copytree(real_root / event / band, copy_root / event / band)
    results = []
    for step in ("as copied", "one file removed"):
        if step == "one file removed":
            (copy_root / event / band / path.name).unlink()
        got, err = _call(target, copy_root)
        if err is not None:
            raise err
        results.append(_t3_rows(got))
    first, second = results
    if first is None or second is None:
        return "format"
    if not first[0].equals(second[0]) or second[1] != first[1] | {(event, station, band, path.name.split(".")[3][-1])}:
        return "real-tree"
    return None


def _t3_snapshot(root: Path) -> List[Tuple[str, int, int]]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        for name in sorted(dirnames) + sorted(filenames):
            full = os.path.join(dirpath, name)
            info = os.stat(full)
            out.append((os.path.relpath(full, root), info.st_size, info.st_mtime_ns))
    return sorted(out)


def _t3_verdict(got: Any, truth: dict, messy: bool) -> Tuple[Optional[str], Optional[str]]:
    if not (isinstance(got, (tuple, list)) and len(got) == 2 and all(isinstance(x, pd.DataFrame) for x in got)):
        return "format", f"a {type(got).__name__}"
    counts, gaps = got
    if not {"event", "station", "band", "missing"} <= set(gaps.columns):
        return "format", f"gaps with columns {list(gaps.columns)}"
    rows, cols = [str(x) for x in counts.index], [str(x) for x in counts.columns]
    want_rows, want_cols = truth["events"], truth["bands"]
    if len(set(rows)) != len(rows) or len(set(cols)) != len(cols):
        return "format", "counts with repeated index or column labels"
    if set(rows) != set(want_rows) or set(cols) != set(want_cols):
        shown = f"counts with {len(rows)} rows and columns {cols}"
        if messy and (set(rows) - set(want_rows) or set(cols) - set(want_cols)):
            return "other-files", shown
        return "empty", shown
    framed = counts.copy()
    framed.index, framed.columns = rows, cols
    try:
        grid = framed.loc[want_rows, want_cols].astype(float).to_numpy()
    except (TypeError, ValueError):
        return "format", "counts that are not numbers"
    if np.isnan(grid).any():
        return "empty", "NaN in counts"
    if not np.array_equal(grid, truth["stations"]):
        shown = f"{int((grid != truth['stations']).sum())} of {grid.size} counts differ"
        if np.array_equal(grid, truth["files"]):
            return "files-not-stations", shown
        if np.array_equal(grid, truth["codes"]):
            return "network", shown
        if messy and np.all(grid >= truth["stations"]):
            return "other-files", shown
        return "wrong-counts", shown
    try:
        listed = [(str(e), str(s), str(b), str(m)) for e, s, b, m in
                  zip(gaps["event"], gaps["station"], gaps["band"], gaps["missing"])]
    except (TypeError, ValueError):
        return "format", "gaps that cannot be read"
    if sorted(listed) != sorted(truth["holes"]):
        shown = f"{len(listed)} gap rows (expected {len(truth['holes'])})"
        if listed and all("." not in s for _, s, _, _ in listed):
            return "network", shown
        return "gaps", shown
    if rows != want_rows or cols != want_cols or listed != truth["holes"]:
        return "sorting", "the right content in another order"
    return None, None


def check_T3(target: Any, ctx: Any) -> Outcome:
    trials = max(len(T3_KINDS), int(ctx.criteria.get("trials", 3)))
    ok: List[bool] = []
    fails: List[Tuple[str, Optional[dict]]] = []
    with tempfile.TemporaryDirectory(prefix="sgtl-m03-") as scratch:
        for number in range(trials):
            kind = T3_KINDS[number % len(T3_KINDS)]
            tree, extras = _t3_layout(ctx.rng, kind)
            root = Path(scratch) / f"tree{number}" / "SAC"
            _t3_write(root, tree, extras)
            truth = _t3_truth(tree)
            before = _t3_snapshot(root)
            got, err = _call(target, root if number % 2 else str(root))
            inputs = {"tree": kind, "events": len(truth["events"]), "bands": truth["bands"],
                      "extra files": [e.split("/")[-1] for e in extras]}
            if err is not None:
                if kind == "messy":
                    category, shown = "other-files", f"{type(err).__name__}: {str(err)[:100]}"
                else:
                    raise err
            else:
                category, shown = _t3_verdict(got, truth, kind == "messy")
                if category is None and _t3_snapshot(root) != before:
                    category, shown = "changed-tree", "files or folders changed"
            ok.append(category is None)
            if category is not None:
                fails.append((category, {"inputs": inputs, "got": shown}))
    if fails:
        category, example = _first(fails, ("format", "files-not-stations", "network", "other-files", "empty",
                                           "wrong-counts", "gaps", "sorting", "changed-tree"))
        return outcome_from_cases(ok, category=category, example=example)
    note = ("On your Sangju tree the check counts nothing itself: your function must run without changing it, "
            "and on a copy of one event folder with one file removed, your own result must change by that file.")
    real_root = Path(ctx.data_root) / DATASET / "stp_download" / "SAC"
    if not real_root.is_dir():
        return outcome_from_cases(ok + [False], category="no-data", real_data=True, note=note)
    with tempfile.TemporaryDirectory(prefix="sgtl-m03-real-") as scratch:
        category = _t3_real(target, real_root, Path(scratch), ctx.rng)
    return outcome_from_cases(ok + [category is None], category=category, real_data=True, note=note,
                              example={"inputs": {"tree": f"your {DATASET} tree"}})


# --------------------------------------------------------------- M03-T4 sensitivity from the stages
_SHORTCUTS: List[str] = []
_WATCH: Dict[str, type] = {}
T4_DIGITIZERS = (419430.0, 1677720.0, 838860.0, 209715.2)


def _watch_classes() -> Dict[str, type]:
    """Subclasses of ObsPy's Inventory, Network and Response that note every shortcut the student takes."""
    if _WATCH:
        return _WATCH
    from obspy.core.inventory import Inventory, Network
    from obspy.core.inventory.response import Response

    def noted(name: str, method: Any) -> Any:
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            _SHORTCUTS.append(name)
            return method(self, *args, **kwargs)

        wrapper.__name__ = name
        return wrapper

    def read_stored(self: Any) -> Any:
        _SHORTCUTS.append("instrument_sensitivity")
        return self.__dict__.get("instrument_sensitivity")

    def write_stored(self: Any, value: Any) -> None:
        self.__dict__["instrument_sensitivity"] = value

    body: Dict[str, Any] = {"instrument_sensitivity": property(read_stored, write_stored)}
    for name in ("get_evalresp_response", "get_evalresp_response_for_frequencies",
                 "recalculate_overall_sensitivity", "_get_overall_sensitivity_and_gain", "get_sacpz"):
        if hasattr(Response, name):
            body[name] = noted(name, getattr(Response, name))
    _WATCH["response"] = type("WatchedResponse", (Response,), body)
    _WATCH["inventory"] = type("WatchedInventory", (Inventory,),
                               {"get_response": noted("get_response", Inventory.get_response)})
    _WATCH["network"] = type("WatchedNetwork", (Network,),
                             {"get_response": noted("get_response", Network.get_response)})
    return _WATCH


def _watched(inventory: Any) -> Any:
    """A deep copy of `inventory` whose shortcuts are noted in _SHORTCUTS."""
    kinds = _watch_classes()
    twin = copy.deepcopy(inventory)
    twin.__class__ = kinds["inventory"]
    for network in twin.networks:
        network.__class__ = kinds["network"]
        for station in network.stations:
            for channel in station.channels:
                if channel.response is not None:
                    channel.response.__class__ = kinds["response"]
    return twin


def _t4_oracle(inventory: Any, seed_id: str, when: Any) -> Tuple[Optional[Tuple[float, str]], bool]:
    """ObsPy's stored sensitivity of the epoch at `when` (None when there is none); flag = ambiguous."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            found = inventory.get_response(seed_id, when)
        except Exception:  # noqa: BLE001 - ObsPy raises a bare Exception when nothing matches
            return None, False
    ambiguous = any("more than one" in str(w.message) for w in caught)
    stored = found.instrument_sensitivity
    return (float(stored.value), str(stored.input_units)), ambiguous


def _same_units(a: Any, b: Any) -> bool:
    return isinstance(a, str) and "".join(a.split()).upper() == "".join(str(b).split()).upper()


def _t4_kind(got: Any, want: Optional[Tuple[float, str]], decoys: List[Tuple[str, float]],
             rel_tol: float) -> Optional[str]:
    pair = isinstance(got, (tuple, list)) and len(got) == 2
    if want is None:
        return None if got is None else ("wrong-epoch" if pair else "format")
    if got is None:
        return "wrong-epoch"
    if not pair:
        return "format"
    value, units = got
    if isinstance(value, bool) or not isinstance(value, numbers.Real) or not np.isfinite(float(value)) \
            or not isinstance(units, str):
        return "format"
    value = float(value)
    near = lambda a, b: abs(a - b) <= rel_tol * abs(b)  # noqa: E731
    if near(value, want[0]):
        return None if _same_units(units, want[1]) else "units"
    if near(-value, want[0]):
        return "polarity"
    for category, other in decoys:
        if near(abs(value), other):
            return category
    return "stage-product"


def _t4_totals(rng: np.random.Generator, n: int) -> List[float]:
    """n overall values (counts per unit) that differ from each other by at least 30 %."""
    out: List[float] = []
    while len(out) < n:
        candidate = float(10 ** rng.uniform(5.0, 9.6))
        if all(abs(np.log(candidate / o)) > np.log(1.3) for o in out):
            out.append(candidate)
    return out


def _t4_inventory(rng: np.random.Generator) -> Tuple[Any, List[Tuple[str, Any, List[Tuple[str, float]]]]]:
    """A made-up inventory and its queries (seed id, time, values that a slip would return)."""
    from obspy import UTCDateTime
    from obspy.core.inventory import Channel, Inventory, Network, Station
    from obspy.core.inventory.response import (CoefficientsTypeResponseStage, InstrumentSensitivity,
                                               PolesZerosResponseStage, Response, ResponseStage)

    totals = iter(_t4_totals(rng, 10))
    year0 = int(rng.integers(2003, 2009))

    def at(years: float) -> Any:
        return UTCDateTime(year0, 1, 1) + float(years) * 365.25 * 86400.0

    def response(total: float, units: str, sign: float) -> Any:
        first_gain = sign * float(rng.choice([1500.0, 1201.5, 750.0, 2000.0] if units == "M/S" else [4.0789, 1.0197]))
        stages = [PolesZerosResponseStage(1, first_gain, 1.0, units, "V", "LAPLACE (RADIANS/SECOND)", 1.0,
                                          zeros=[0j, 0j], poles=[-0.037 + 0.037j, -0.037 - 0.037j],
                                          normalization_factor=1.0)]
        known = abs(first_gain)
        if rng.random() < 0.6:
            boost = float(rng.choice([2.0, 4.0, 8.0]))
            stages.append(ResponseStage(2, boost, 1.0, "V", "V"))
            known *= boost
        fir_gain = float(rng.choice([1.0, 1.0, 0.5, 2.0]))
        digitizer = total / (known * fir_gain)
        stages.append(CoefficientsTypeResponseStage(len(stages) + 1, digitizer, 1.0, "V", "COUNTS", "DIGITAL",
                                                    numerator=[], denominator=[]))
        stages.append(CoefficientsTypeResponseStage(len(stages) + 1, fir_gain, 1.0, "COUNTS", "COUNTS", "DIGITAL",
                                                    numerator=[1.0], denominator=[]))
        stages.append(CoefficientsTypeResponseStage(len(stages) + 1, 1.0, 1.0, "COUNTS", "COUNTS", "DIGITAL",
                                                    numerator=[1.0], denominator=[]))
        stored = InstrumentSensitivity(total, 1.0, units, "COUNTS")
        return Response(instrument_sensitivity=stored, response_stages=stages)

    nets = ("KS", "KG") if rng.random() < 0.5 else ("KG", "KS")
    code = "".join(rng.choice(T2_LETTERS, size=3))
    other = code[::-1] + "2"
    # (network, station, location, channel, start in years, end in years or None, units, sign of the first stage)
    plan = [(nets[0], code, "", "HHZ", 0.0, 4.5, "M/S", 1.0), (nets[0], code, "", "HHZ", 4.5, 9.0, "M/S", -1.0),
            (nets[0], code, "", "HHZ", 9.0, None, "M/S", 1.0), (nets[0], code, "", "HGZ", 0.0, None, "M/S**2", 1.0),
            (nets[0], code, "10", "HHZ", 2.0, None, "M/S", 1.0), (nets[1], code, "", "HHZ", 1.0, 6.0, "M/S", 1.0),
            (nets[1], code, "", "HHZ", 6.0, None, "M/S", 1.0), (nets[0], other, "", "ELZ", 1.0, 4.0, "M/S", 1.0),
            (nets[0], other, "", "ELZ", 5.0, 8.0, "M/S", 1.0)]
    value_of: List[float] = []
    stations: Dict[Tuple[str, str], Any] = {}
    for net, sta, loc, cha, begin, end, units, sign in plan:
        total = next(totals)
        value_of.append(total)
        epoch = Channel(cha, loc, 36.0, 128.0, 100.0, 0.0, sample_rate=100.0, start_date=at(begin),
                        end_date=None if end is None else at(end) - 1.0, response=response(total, units, sign))
        holder = stations.setdefault((net, sta), Station(sta, 36.0, 128.0, 100.0, channels=[]))
        holder.channels.append(epoch)
    networks = []
    for net in nets:
        networks.append(Network(net, stations=[s for (n, _), s in stations.items() if n == net]))
    inventory = Inventory(networks=networks, source="SGTL check (made up)")

    def decoys_for(index: int) -> List[Tuple[str, float]]:
        net, sta, loc, cha = plan[index][:4]
        same = [("wrong-epoch", value_of[k]) for k, p in enumerate(plan)
                if p[:4] == (net, sta, loc, cha) and k != index]
        other_channels = [("wrong-channel", value_of[k]) for k, p in enumerate(plan) if p[:4] != (net, sta, loc, cha)]
        return same + other_channels

    def mid(begin: float, end: Optional[float]) -> Any:
        stop = begin + 3.0 if end is None else end
        return at(begin + float(rng.uniform(0.25, 0.75)) * (stop - begin))

    queries = []
    for index in (0, 1, 2, 3, 4, 6, 7):
        net, sta, loc, cha, begin, end = plan[index][:6]
        queries.append((f"{net}.{sta}.{loc}.{cha}", mid(begin, end), decoys_for(index)))
    queries.append((f"{nets[0]}.{other}..ELZ", at(4.5), decoys_for(7)))           # between two epochs
    queries.append((f"{nets[0]}.{code}..HHZ", at(-1.5), decoys_for(0)))           # before the first epoch
    order = rng.permutation(len(queries))
    return inventory, [queries[i] for i in order]


def _t4_real_cases(ctx: Any, count: int) -> Optional[List[Tuple[Path, str, Any]]]:
    """Random (StationXML file, seed id, time) of the Sangju records; None when StationMetadata is missing."""
    from obspy import UTCDateTime

    xml_dir = Path(ctx.data_root) / "metadata" / "stationxml"
    if not xml_dir.is_dir():
        return None
    tree = Path(ctx.data_root) / DATASET / "stp_download" / "SAC"
    pool: List[Tuple[str, str, str, Any]] = []
    if tree.is_dir():
        for path in sorted(tree.glob("*/*/*.sac")):
            bits = path.name.split(".")
            if len(bits) == 5:
                pool.append((bits[1], bits[2], bits[3], UTCDateTime.strptime(path.parent.parent.name,
                                                                             "%Y%m%d%H%M%S")))
    if not pool:
        for path in sorted(xml_dir.glob("*.xml"))[:200]:
            net, sta = path.stem.split(".", 1)
            pool.append((net, sta, "HHZ", UTCDateTime(2016, 1, 1) + float(ctx.rng.uniform(0, 7 * 365.25 * 86400))))
    picks = []
    for index in ctx.rng.permutation(len(pool)):
        net, sta, cha, when = pool[int(index)]
        path = xml_dir / f"{net}.{sta}.xml"
        if path.is_file() and all(p[1] != f"{net}.{sta}..{cha}" for p in picks):
            picks.append((path, f"{net}.{sta}..{cha}", when))
        if len(picks) >= count:
            break
    return picks


def check_T4(target: Any, ctx: Any) -> Outcome:
    trials = max(1, int(ctx.criteria.get("trials", 2)))
    rel_tol = float(ctx.criteria.get("rel_tol", 1.0e-6))
    ok: List[bool] = []
    fails: List[Tuple[str, Optional[dict]]] = []
    for _ in range(trials):
        inventory, queries = _t4_inventory(ctx.rng)
        for seed_id, when, decoys in queries:
            want, _ = _t4_oracle(inventory, seed_id, when)
            handed = _watched(inventory)
            _SHORTCUTS.clear()
            got, err = _call(target, handed, seed_id, when)
            used = sorted(set(_SHORTCUTS))
            _SHORTCUTS.clear()
            if err is not None and not used:
                raise err
            category = "shortcut" if used else _t4_kind(got, want, decoys, rel_tol)
            ok.append(category is None)
            if category is not None:
                example = {"inputs": {"seed_id": seed_id, "time": str(when)[:19]},
                           "got": f"used {', '.join(used)}" if used else _short(got)}
                fails.append((category, example))
    if fails:
        category, example = _first(fails, ("shortcut", "format", "wrong-channel", "wrong-epoch", "polarity",
                                           "units", "stage-product"))
        return outcome_from_cases(ok, category=category, example=example)

    from obspy import read_inventory

    note = "The real channels were compared with ObsPy's reading of StationMetadata; their values are not printed."
    cases = _t4_real_cases(ctx, int(ctx.criteria.get("real_cases", 5)))
    if not cases:
        return outcome_from_cases(ok + [False], category="no-metadata", real_data=True, note=note)
    real_tol = float(ctx.criteria.get("real_rel_tol", 0.02))
    real_fail = None
    checked = 0
    for path, seed_id, when in cases:
        inventory = read_inventory(str(path))
        want, ambiguous = _t4_oracle(inventory, seed_id, when)
        if ambiguous:
            continue
        handed = _watched(inventory)
        _SHORTCUTS.clear()
        got, err = _call(target, handed, seed_id, when)
        used = sorted(set(_SHORTCUTS))
        _SHORTCUTS.clear()
        if err is not None and not used:
            raise err
        category = "shortcut" if used else _t4_kind(got, want, [], real_tol)
        checked += 1
        ok.append(category is None)
        if category is not None and real_fail is None:
            real_fail = ("shortcut" if category == "shortcut" else "real-data",
                         {"inputs": {"seed_id": seed_id, "time": str(when)[:19]}, "got": _short(got)})
    if real_fail is None:
        return outcome_from_cases(ok, real_data=checked > 0, note=note)
    return outcome_from_cases(ok, category=real_fail[0], example=real_fail[1], real_data=True, note=note)


# ------------------------------------------------------------- M03-T5 a window without an earthquake
T5_KINDS = ("same-day", "early", "month-end", "year-end", "leap-day", "summer-1987", "fraction", "same-day",
            "early", "fraction")
T5_SECONDS = ((10.0, 60.0), (30.0, 470.0), (2.5, 7.25))
T5_SHIFTS = (("kst-as-utc", (9.0,)), ("direction", (18.0,)), ("dst", (-1.0, 1.0)))
T5_COLUMNS = ("station", "distance_km", "n_wrong", "t_peak_s", "peak_ratio")


def _t5_moment(rng: np.random.Generator, kind: str) -> int:
    """A UTC moment in milliseconds whose Korean clock reading has the property named by `kind`."""
    def stamp(text: str, low_h: int, high_h: int) -> int:
        base = pd.Timestamp(text, tz="UTC") + pd.Timedelta(hours=int(rng.integers(low_h, high_h)),
                                                           minutes=int(rng.integers(0, 60)),
                                                           seconds=int(rng.integers(0, 60)))
        return int(base.value // 1_000_000)

    year = int(rng.integers(2010, 2026))
    if kind == "early":                          # 15:00-23:59 UTC is after midnight in Korea
        day = pd.Timestamp(f"{year}-01-01") + pd.Timedelta(days=int(rng.integers(0, 360)))
        return stamp(day.strftime("%Y-%m-%d"), 15, 24)
    if kind == "month-end":
        last = (pd.Timestamp(f"{year}-{int(rng.integers(1, 12)):02d}-01") + pd.offsets.MonthEnd(0))
        return stamp(last.strftime("%Y-%m-%d"), 15, 24)
    if kind == "year-end":
        return stamp(f"{year}-12-31", 15, 24)
    if kind == "leap-day":
        return stamp(f"{int(rng.choice([2012, 2016, 2020, 2024]))}-02-29", 15, 24)
    if kind == "summer-1987":
        return stamp(f"1987-07-{int(rng.integers(1, 29)):02d}", 1, 12)
    day = pd.Timestamp(f"{year}-01-01") + pd.Timedelta(days=int(rng.integers(0, 360)))
    millis = stamp(day.strftime("%Y-%m-%d"), 0, 14)
    if kind == "fraction":
        millis += int(rng.integers(1, 100)) * 10
    return millis


def _t5_row(rng: np.random.Generator, millis: int, as_series: bool) -> Any:
    korea = pd.Timestamp(millis, unit="ms", tz="UTC").tz_convert(KST)
    fields = {"Year": korea.year, "Month": korea.month, "Day": korea.day, "Hour": korea.hour,
              "Minute": korea.minute, "Second": korea.second + korea.microsecond / 1.0e6,
              "Latitude": round(float(rng.uniform(34.0, 38.0)), 2),
              "Longitude": round(float(rng.uniform(126.0, 130.0)), 2),
              "Depth": float(rng.integers(3, 25)), "Magnitude": round(float(rng.uniform(1.0, 4.0)), 1)}
    return pd.Series(fields, dtype=float) if as_series else fields


T5_KEYS = ("corrected_window", "envelope_evidence", "evidence", "row")
T5_NOISE_S = 20.0                                   # the noise: median of the envelope over the record's first 20 s
T5_CASES = (                                        # (sampling rate, before_s, after_s, colleague window)
    (100.0, 10.0, 60.0, "nine-hours"), (50.0, 5.0, 40.0, "overlap"), (100.0, 15.0, 90.0, "nine-hours-early"))
T5_EVIDENCE_ORDER = ("evidence-table", "evidence-changed-input", "evidence-distance", "evidence-order",
                     "evidence-colleague", "evidence-envelope")


def _t5_guard(answer: dict, ctx: Any) -> Optional[Outcome]:
    """The task's library rule for both functions of the answer (the engine screens only a function target)."""
    from .. import astguard

    rules = list((ctx.spec or {}).get("forbidden") or [])
    for key in ("corrected_window", "envelope_evidence"):
        rep = astguard.check_function(answer[key], rules) if rules else None
        if rep is not None and not rep.ok:
            msg = ("This task asks you to write this step yourself, so the rule is: do not use "
                   f"{', '.join(rep.violations)} here (found in {key}).")
            return Outcome(False, 0, 0, "forbidden-import", msg, details={"found": rep.offending})
    return None


def _t5_group(t: np.ndarray, center: float, width: float, freq: float, amp: float, phase: float) -> np.ndarray:
    """A wave group: a sine under a Gaussian bell. Its envelope is the bell (height amp, top at center)."""
    return amp * np.exp(-((t - center) / width) ** 2) * np.sin(2.0 * np.pi * freq * (t - center) + phase)


def _t5_made_up(rng: np.random.Generator, number: int):
    """Made-up HHZ records of one event with planted problems; returns the Stream, the row, the true and the
    colleague's origin, before_s, after_s and the truth per station (known from how the records were built)."""
    from obspy import Stream, Trace, UTCDateTime
    from obspy.core.util import AttribDict

    rate, before_s, after_s, kind = T5_CASES[number % len(T5_CASES)]
    dt = 1.0 / rate
    lat0, lon0 = float(rng.uniform(35.0, 37.5)), float(rng.uniform(126.5, 129.0))
    row = {"Year": 2019.0, "Month": 7.0, "Day": 21.0, "Hour": 11.0, "Minute": 4.0, "Second": 8.0,
           "Latitude": round(lat0, 4), "Longitude": round(lon0, 4), "Depth": 14.0, "Magnitude": 3.9}
    origin = UTCDateTime(2019, 7, 21, 2, 4, 8) + float(rng.integers(0, 86400 * 300))
    n_rec = 5
    km = np.sort(rng.choice(np.arange(5, 150), n_rec, replace=False)).astype(float) + rng.uniform(0, 0.5, n_rec)
    traces, truth = [], {}
    for j in range(n_rec):
        n_pre = int(round(float(rng.uniform(25.0, 40.0)) * rate))
        npts = int(round(float(rng.uniform(200.0, 320.0)) * rate))
        t = (np.arange(npts) - n_pre) * dt                  # seconds after the true origin
        noise = float(rng.uniform(5.0, 50.0))
        cycles = int(round(float(rng.uniform(1.0, 3.0)) * npts * dt))
        data = noise * np.sin(2.0 * np.pi * cycles * np.arange(npts) / npts + rng.uniform(0, 2 * np.pi))
        if j % 2 == 0:                                      # an offset: the mean must go before the envelope
            data += noise * float(rng.uniform(20.0, 60.0)) * float(rng.choice([-1.0, 1.0]))
        if j % 2 == 1:                                      # a short loud group in the first 20 s
            data += _t5_group(t, t[0] + float(rng.uniform(5.0, 15.0)), 0.08, 10.0,
                              noise * float(rng.uniform(300.0, 600.0)), 0.0)
        center = float(np.clip(km[j] / 3.5 + rng.uniform(-1.0, 1.0), 1.0, after_s - 4.0))
        ratio = float(10.0 ** rng.uniform(1.5, 3.3))
        data += _t5_group(t, center, float(rng.uniform(0.4, 0.9)), float(rng.uniform(3.0, 8.0)), noise * ratio,
                          float(rng.uniform(0.0, 2.0 * np.pi)))
        if j % 3 != 2:                                      # a louder group after the window
            data += _t5_group(t, after_s + float(rng.uniform(10.0, 40.0)), 0.6, 4.0,
                              noise * ratio * float(rng.uniform(2.0, 4.0)), 0.0)
        lat, lon = _t2_destination(lat0, lon0, float(km[j]), float(rng.uniform(0.0, 2.0 * np.pi)))
        net, sta = ("XX", "YY")[j % 2], f"S{int(rng.integers(10, 99))}{chr(65 + j)}"
        tr = Trace(data=data.astype(np.float32), header={
            "network": net, "station": sta, "channel": "HHZ", "sampling_rate": rate,
            "starttime": origin - n_pre * dt, "sac": AttribDict({"stla": round(lat, 5), "stlo": round(lon, 5)})})
        traces.append(tr)
        truth[f"{net}.{sta}"] = {"distance_km": float(km[j]), "t_peak_s": center, "peak_ratio": ratio,
                                 "start": tr.stats.starttime, "npts": npts}
    if kind == "overlap":                                   # the colleague's window covers the end of one record
        last = traces[int(rng.integers(0, n_rec))]
        wrong = last.stats.endtime - (int(rng.integers(100, 800)) - 1) * dt + before_s
    else:
        wrong = origin + (9.0 if kind == "nine-hours" else -9.0) * 3600.0
    for name, info in truth.items():
        first = int(np.ceil((wrong - before_s - info["start"]) / dt - 1e-6))
        last_k = int(np.floor((wrong + after_s - info["start"]) / dt + 1e-6))
        info["n_wrong"] = float(max(0, min(last_k, info["npts"] - 1) - max(first, 0) + 1))
    order = rng.permutation(n_rec)
    return Stream([traces[i] for i in order]), row, origin, wrong, before_s, after_s, truth


def _t5_table(got: Any, names: List[str]) -> Optional[pd.DataFrame]:
    """The student's table with float columns, or None when it is not one row per record with the columns."""
    if not isinstance(got, pd.DataFrame) or not set(T5_COLUMNS) <= set(got.columns) or len(got) != len(names):
        return None
    table = got.reset_index(drop=True)
    if sorted(str(s) for s in table["station"]) != sorted(names):
        return None
    try:
        values = table[list(T5_COLUMNS[1:])].astype(float)
    except (TypeError, ValueError):
        return None
    values.insert(0, "station", [str(s) for s in table["station"]])
    return values


def _t5_judge(got: Any, truth: Dict[str, dict], stream: Any, pristine: Any, crit: dict) -> Tuple[Optional[str], str]:
    names = list(truth)
    table = _t5_table(got, names)
    if table is None:
        shown = list(got.columns) if isinstance(got, pd.DataFrame) else type(got).__name__
        return "evidence-table", f"{shown} ({len(got) if hasattr(got, '__len__') else '?'} rows for {len(names)} records)"
    if len(stream) != len(pristine) or any(a.stats.npts != b.stats.npts or a.stats.starttime != b.stats.starttime
                                           or not np.array_equal(a.data, b.data) for a, b in zip(stream, pristine)):
        return "evidence-changed-input", "the records given to the function changed"
    d_tol = float(crit.get("dist_rel_tol", 0.01))
    t_tol = float(crit.get("t_peak_tol_s", 0.5))
    r_tol = float(crit.get("ratio_rel_tol", 0.15))
    rows = {name: line for name, (_, line) in zip(table["station"], table.iterrows())}
    for name, want in truth.items():
        if not abs(rows[name]["distance_km"] - want["distance_km"]) <= max(0.5, d_tol * want["distance_km"]):
            return "evidence-distance", f"{name}: distance_km {rows[name]['distance_km']:.3f}, " \
                                        f"built {want['distance_km']:.3f}"
    if list(table["station"]) != sorted(names, key=lambda n: truth[n]["distance_km"]):
        return "evidence-order", "stations in the order " + ", ".join(table["station"])
    for name, want in truth.items():
        line = rows[name]
        if abs(line["n_wrong"] - want["n_wrong"]) > 1.0:
            return "evidence-colleague", f"{name}: n_wrong {line['n_wrong']:g}, built {want['n_wrong']:g}"
        if not (abs(line["t_peak_s"] - want["t_peak_s"]) <= t_tol
                and abs(line["peak_ratio"] - want["peak_ratio"]) <= r_tol * want["peak_ratio"]):
            return "evidence-envelope", (f"{name}: t_peak_s {line['t_peak_s']:.3f} and peak_ratio "
                                         f"{line['peak_ratio']:.4g}; built {want['t_peak_s']:.3f} and "
                                         f"{want['peak_ratio']:.4g}")
    return None, ""


def _t5_folder(ctx: Any, origin: Any) -> Optional[Path]:
    """The event folder of the student's Sangju dataset whose UTC name lies within 1.5 s of `origin`."""
    from obspy import UTCDateTime

    root = Path(ctx.data_root) / DATASET / "stp_download" / "SAC"
    for folder in sorted(p for p in root.glob("*") if p.is_dir()) if root.is_dir() else []:
        try:
            when = UTCDateTime(_dt.datetime.strptime(folder.name, "%Y%m%d%H%M%S"))
        except ValueError:
            continue
        if abs(when - origin) <= 1.5 and sorted((folder / "HH").glob("*.HHZ.sac")):
            return folder
    return None


def _t5_same(table: Any, own: Any) -> bool:
    """True when the student's table is what the student's own function returned (same rows, same numbers)."""
    if not isinstance(own, pd.DataFrame) or not isinstance(table, pd.DataFrame):
        return False
    names = [str(s) for s in own["station"]] if "station" in own.columns else []
    a, b = _t5_table(table, names), _t5_table(own, names)
    if a is None or b is None or list(a["station"]) != list(b["station"]):
        return False
    return bool(np.allclose(a[list(T5_COLUMNS[1:])].to_numpy(), b[list(T5_COLUMNS[1:])].to_numpy(),
                            rtol=1e-6, atol=1e-6, equal_nan=False))


def _t5_evidence(answer: dict, ctx: Any) -> Tuple[List[bool], Optional[str], Optional[dict], bool]:
    """Made-up records first (truth by construction), then the real records with the student's own functions.
    Returns the case results, the first category, its example and whether that case used real data."""
    from obspy import UTCDateTime, read

    crit, func = ctx.criteria, answer["envelope_evidence"]
    ok: List[bool] = []
    fails: List[Tuple[str, Optional[dict]]] = []
    for number in range(max(len(T5_CASES), int(crit.get("evidence_trials", len(T5_CASES))))):
        stream, row, origin, wrong, before_s, after_s, truth = _t5_made_up(ctx.rng, number)
        pristine = stream.copy()
        got, err = _call(func, stream, pd.Series(row) if number % 2 else row, origin, wrong, before_s, after_s)
        if err is not None:
            raise err
        category, shown = _t5_judge(got, truth, stream, pristine, crit)
        ok.append(category is None)
        if category is not None:
            fails.append((category, {"inputs": {"made-up records": len(truth), "sampling_rate": stream[0].stats.sampling_rate,
                                                "before_s": before_s, "after_s": after_s,
                                                "colleague's origin": str(wrong), "true origin": str(origin)},
                                     "got": shown}))
    if fails:
        category, example = _first(fails, T5_EVIDENCE_ORDER)
        return ok, category, example, False
    row, table = answer["row"], answer["evidence"]
    try:
        start, _ = answer["corrected_window"](row, 10.0, 60.0)
        origin = UTCDateTime(start) + 10.0
        parts = [int(float(row[k])) for k in ("Year", "Month", "Day", "Hour", "Minute", "Second")]
        wrong = UTCDateTime(*parts)                     # the colleague's origin, as in the colleague's cell
    except NotImplementedError:
        raise
    except Exception:  # noqa: BLE001 - not a row of event_catalog.csv
        return ok + [False], "no-data", {"inputs": "row", "got": _short(row, 120)}, True
    folder = _t5_folder(ctx, origin)
    if folder is None:
        return ok + [False], "no-data", {"inputs": "row", "got": _short(row, 120)}, True
    records = read(str(folder / "HH" / "*.HHZ.sac"))
    own, err = _call(func, records, row, origin, wrong, 10.0, 60.0)
    if err is not None:
        raise err
    if not _t5_same(table, own):
        shown = f"{type(table).__name__} of {len(table) if hasattr(table, '__len__') else '?'} rows"
        return ok + [False], "evidence-not-yours", {"inputs": f"the {len(records)} HHZ records of the row's event",
                                                    "got": shown}, True
    return ok + [True], None, None, True


def check_T5(target: Any, ctx: Any) -> Outcome:
    if not isinstance(target, dict) or set(map(str, target)) != set(T5_KEYS) or \
            not callable(target.get("corrected_window")) or not callable(target.get("envelope_evidence")):
        shown = sorted(map(str, target)) if isinstance(target, dict) else type(target).__name__
        return outcome_from_cases([False], category="answer", example={"inputs": "answer", "got": shown})
    refused = _t5_guard(target, ctx)
    if refused is not None:
        return refused
    window = target["corrected_window"]
    trials = max(len(T5_KINDS), int(ctx.criteria.get("trials", 10)))
    tol_ms = 1000.0 * float(ctx.criteria.get("tol_s", 0.001)) + 1e-6
    ok: List[bool] = []
    fails: List[Tuple[str, Optional[dict]]] = []
    for number in range(trials):
        kind = T5_KINDS[number % len(T5_KINDS)]
        millis = _t5_moment(ctx.rng, kind)
        row = _t5_row(ctx.rng, millis, as_series=number % 2 == 0)
        before_s, after_s = T5_SECONDS[number % len(T5_SECONDS)]
        want = (millis - 1000.0 * before_s, millis + 1000.0 * after_s)
        got, err = _call(window, row, before_s, after_s)
        shown_row = {k: (round(float(row[k]), 3) if k == "Second" else int(row[k])) for k in
                     ("Year", "Month", "Day", "Hour", "Minute", "Second")}
        example = {"inputs": {"row": shown_row, "before_s": before_s, "after_s": after_s}}
        if err is not None:
            if isinstance(err, (ValueError, OverflowError)) and kind in ("early", "month-end", "year-end", "leap-day"):
                category = "rollover"
                example["got"] = f"{type(err).__name__}: {str(err)[:80]}"
            else:
                raise err
        else:
            category = _window_kind(got, want, before_s, after_s, tol_ms, T5_SHIFTS, whole_days=True)
            example["got"] = _short(got)
            gap = _offsets_text(got, want) if category not in (None, "format") else None
            if gap:
                example["error"] = gap
        ok.append(category is None)
        if category is not None:
            fails.append((category, example))
    if fails:
        category, example = _first(fails, ("format", "kst-as-utc", "direction", "rollover", "dst", "sign",
                                           "precision", "wrong-window"))
        return outcome_from_cases(ok, category=category, example=example)
    more, category, example, real = _t5_evidence(target, ctx)
    note = ("Your envelope_evidence was tested on made-up records; on the real records your table must be what "
            "your own function returns (the check computes nothing of its own there).")
    return outcome_from_cases(ok + more, category=category, example=example, real_data=real, note=note)
