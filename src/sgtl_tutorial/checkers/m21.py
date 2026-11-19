"""Checkers for M21 · Deep-learning pickers.

Where the truth comes from (DESIGN.md section 1, rule 1):

* M21-T1: construction and an oracle. Made-up probability curves (bell-shaped bumps of known size on a small
  wiggle); the expected picks come from scipy.signal.find_peaks (height = the threshold, distance = the gap in
  samples), a library the student's function may not use.
* M21-T2: construction, then the model under study. Made-up annotation streams whose best picks are known from
  how they were built; then records of the Sangju mainshock from the student's own download, annotated by the
  check itself with the pinned PhaseNet weights (the same numbers on every run on a CPU). For the clear picks the
  reference is SeisBench's own peak extraction (WaveformModel.picks_from_annotations); every row of the student
  must also lie on the model's curve, inside the window and above the threshold. Values are never printed.
* M21-T3: construction (two made-up pick tables with known differences, keys in only one table, repeated keys).
* M21-T4: construction for the reader (made-up PocketQuake pick folders), then the student's own run products:
  the copied pick folders, their SHA-256 fingerprints against the run log work/.sgtl/runs.jsonl that sgtl writes
  for every run, and the probabilities inside the files. The student's per-file fingerprints of the first run and
  the rerun are recomputed from the files (every pick file, every digest); whether the rerun is a real second run
  is judged by the check itself (two copies of one folder, or bytes that only one logged run wrote, fail).
* M21-T5: construction (pick tables whose first motions are known from how they were drawn).

Failure categories are keys of ``checks/specs/M21.yaml``; the engine prints their fixed messages.
"""
from __future__ import annotations

import hashlib
import json
import math
import numbers
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import Outcome, outcome_from_cases

__all__ = ["check_T1", "check_T2", "check_T3", "check_T4", "check_T5"]

DATASET_DEFAULT = "sangju2019"
MAIN_EVENT = "2019009762"                 # the ML 3.9 Sangju earthquake of 21 July 2019 (KMA catalog)
PHASES = ("P", "S")


# ------------------------------------------------------------------------------------------- helpers
def _call(func: Any, *args: Any, **kwargs: Any) -> Tuple[Any, Optional[BaseException]]:
    """Run the student's code. NotImplementedError passes through (the engine reports NOT STARTED)."""
    try:
        return func(*args, **kwargs), None
    except NotImplementedError:
        raise
    except Exception as exc:  # noqa: BLE001 - classified by the caller
        return None, exc


def _first(cats: Sequence[str], priority: Sequence[str]) -> Optional[str]:
    found = set(cats)
    return next((c for c in priority if c in found), None)


def _bump(n: int, center: float, sigma: float) -> np.ndarray:
    x = (np.arange(n) - center) / sigma
    return np.exp(-0.5 * x * x)


def _wiggle(rng: np.random.Generator, n: int, size: float) -> np.ndarray:
    """A small, smooth, positive background (what a picker gives on noise)."""
    raw = np.convolve(rng.standard_normal(n + 60), np.ones(61) / 61.0, mode="valid")[:n]
    return size * np.abs(raw) / max(1e-12, float(np.abs(raw).max()))


def _is_frame(got: Any) -> bool:
    try:
        import pandas as pd
    except ImportError:  # pragma: no cover - pandas is part of the course environment
        return False
    return isinstance(got, pd.DataFrame)


def _utc(value: Any):
    """An obspy UTCDateTime, or None when the value is not one."""
    from obspy import UTCDateTime

    return value if isinstance(value, UTCDateTime) else None


def _missing(value: Any) -> bool:
    """None, NaN, NaT or pandas NA: an empty place in a table."""
    if value is None:
        return True
    try:
        import pandas as pd

        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


# ===================================================================== M21-T1 picks from a probability curve
T1_DELTAS = (0.01, 0.005, 0.02, 0.025, 0.004)
T1_PRIORITY = ("format", "index-units", "values", "not-peaks", "edge", "below-threshold", "order", "no-gap",
               "gap-order", "wrong-values")


def _t1_case(rng: np.random.Generator, number: int) -> dict:
    """One made-up curve: bumps of known size and width, some closer together than the gap, some far apart."""
    from scipy.signal import find_peaks

    for _ in range(200):
        delta = float(T1_DELTAS[number % len(T1_DELTAS)])
        n = int(rng.integers(1500, 6000))
        gap = int(rng.integers(8, 120))
        thr = float(rng.uniform(0.1, 0.6))
        curve = _wiggle(rng, n, float(rng.uniform(0.01, 0.06)))
        centers: List[float] = []
        for _k in range(int(rng.integers(3, 10))):
            if centers and rng.random() < 0.45:          # a neighbour of an earlier bump: closer or farther than the gap
                near = rng.random() < 0.5
                lag = rng.uniform(0.3, 0.8) * gap if near else rng.uniform(1.25, 2.5) * gap
                c = centers[int(rng.integers(len(centers)))] + float(lag) * (1 if rng.random() < 0.5 else -1)
            else:
                c = float(rng.uniform(0.05 * n, 0.95 * n))
            sigma = float(rng.uniform(2.0, max(3.0, min(25.0, gap / 3.0))))
            if not 4 * sigma < c < n - 1 - 4 * sigma:
                continue
            centers.append(c)
            curve = curve + float(rng.uniform(0.05, 0.95)) * _bump(n, c, sigma)
        if number % 4 == 1:                               # rising at the last sample: not a peak
            curve = curve + float(rng.uniform(thr + 0.05, 0.95)) * _bump(n, n - 1 + 3.0, 6.0)
        if number % 4 == 3:                               # falling from the first sample: not a peak
            curve = curve + float(rng.uniform(thr + 0.05, 0.95)) * _bump(n, -3.0, 6.0)
        top = float(curve.max())
        if top > 0.99:
            curve = curve * (0.99 / top)
        curve = curve + 1e-7 * rng.random(n)              # no two neighbours exactly equal
        cand, _ = find_peaks(curve, height=thr)
        if cand.size == 0:
            continue
        sep = np.abs(cand[:, None] - cand[None, :])
        if np.any(np.abs(sep - gap) <= 2) or np.any(np.abs(curve[cand] - thr) < 1e-4) or \
                np.any(np.abs(curve[find_peaks(curve)[0]] - thr) < 1e-4):
            continue                                      # keep clear of the two boundaries of the contract
        want, _ = find_peaks(curve, height=thr, distance=gap)
        if want.size and cand.size > want.size or number % 3 == 0:
            return {"curve": curve, "delta": delta, "thr": thr, "gap": gap, "want": want}
    return {"curve": curve, "delta": delta, "thr": thr, "gap": gap, "want": find_peaks(curve, height=thr,
                                                                                         distance=gap)[0]}


def _t1_judge(got: Any, case: dict, tol_samples: float) -> Optional[str]:
    curve, delta, thr, gap, want = case["curve"], case["delta"], case["thr"], case["gap"], case["want"]
    n = curve.size
    if not isinstance(got, tuple) or len(got) != 2:
        return "format"
    try:
        times = np.asarray(got[0], dtype=float)
        values = np.asarray(got[1], dtype=float)
    except (TypeError, ValueError):
        return "format"
    if times.ndim != 1 or values.shape != times.shape or not np.all(np.isfinite(times)) or \
            not np.all(np.isfinite(values)):
        return "format"
    want_t = want * delta
    if times.size == want.size and np.all(np.abs(times - want_t) <= tol_samples * delta) and \
            np.all(np.abs(values - curve[want]) <= 1e-9):
        return None
    if times.size and np.allclose(times, np.round(times)) and \
            set(np.round(times).astype(int).tolist()) == set(want.tolist()):
        return "index-units"
    idx = np.round(times / delta).astype(int)
    if np.any(idx < 0) or np.any(idx >= n) or np.any(np.abs(times - idx * delta) > tol_samples * delta):
        return "wrong-values"
    if np.any(np.abs(values - curve[idx]) > 1e-9):
        return "values"
    inner = idx[(idx > 0) & (idx < n - 1)]
    if not np.all((curve[inner] > curve[inner - 1]) & (curve[inner] > curve[inner + 1])):
        return "not-peaks"
    if inner.size != idx.size:
        return "edge"
    if np.any(curve[idx] < thr):
        return "below-threshold"
    if np.any(np.diff(idx) < 0):
        return "order"
    if np.any(np.diff(np.sort(idx)) < gap):
        return "no-gap"
    return "gap-order"


def check_T1(target: Any, ctx: Any) -> Outcome:
    trials = max(20, int(ctx.criteria.get("trials", 150)))
    tol = float(ctx.criteria.get("time_tol_samples", 0.25))
    rng = ctx.rng
    oks, cats, example = [], [], None
    for k in range(trials):
        case = _t1_case(rng, k)
        got, err = _call(target, case["curve"].copy(), case["delta"], case["thr"], case["gap"] * case["delta"])
        if err is not None:
            raise err
        cat = _t1_judge(got, case, tol)
        oks.append(cat is None)
        if cat:
            cats.append(cat)
            if example is None:
                want = case["want"]
                shown = got if not isinstance(got, tuple) else tuple(np.round(np.asarray(x, dtype=float)[:6], 4)
                                                                    for x in got)
                example = {"inputs": {"samples": int(case["curve"].size), "delta": case["delta"],
                                      "threshold": round(case["thr"], 4),
                                      "min_gap_s": round(case["gap"] * case["delta"], 6)},
                           "got": shown,
                           "error": f"expected {want.size} picks, the first at "
                                    f"{np.round(want[:6] * case['delta'], 4).tolist()} s"}
    return outcome_from_cases(np.array(oks), category=_first(cats, T1_PRIORITY), example=example)


# ===================================================================== M21-T2 best picks from model annotations
T2_PRIORITY = ("format", "station-name", "noise-trace", "duplicate", "time-reference", "outside-window",
               "threshold", "not-best", "missing-picks", "order", "wrong-values")
T2_COLUMNS = ("station", "phase", "time", "probability")


def _t2_case(rng: np.random.Generator, number: int) -> dict:
    """Made-up annotations of 1-3 stations; the best pick of each station and phase is known by construction."""
    from obspy import Stream, Trace, UTCDateTime

    delta = (0.01, 0.01, 0.02, 0.005)[number % 4]
    n = int(rng.integers(4000, 9000))
    gap = int(rng.integers(30, 120))
    gap_s = float(np.round(gap * delta, 6))
    thr = float(rng.uniform(0.2, 0.5))
    rec0 = UTCDateTime(2020, 1, 1) + float(np.round(rng.uniform(0.0, 86000.0), 3))
    span = n * delta
    w0 = float(np.round(rng.uniform(0.25, 0.35) * span, 2))
    w1 = float(np.round(rng.uniform(0.6, 0.7) * span, 2))
    start, end = rec0 + w0, rec0 + w1
    prefix = ("PhaseNet", "PhaseNetPlus", "EQTransformer")[number % 3]
    traces, truth = [], []
    codes = ["S%02d" % int(c) for c in rng.choice(99, size=3, replace=False)]
    nets = ["KS", "KG", "XX"]
    for j in range(int(rng.integers(1, 4))):
        net, sta = nets[j % 3], codes[j]
        t0 = rec0 + float(np.round(rng.uniform(1.0, 3.0), 4))       # each station's trace starts at its own time
        lo = int(math.ceil((start - t0) / delta))                    # first sample inside the window
        hi = int(math.floor((end - t0) / delta))
        for phase in ("P", "S", "N"):
            curve = _wiggle(rng, n, float(rng.uniform(0.01, 0.05)))
            if phase == "N":
                curve = curve + 0.97 * _bump(n, float(rng.uniform(lo + 50, hi - 50)), 30.0)
                traces.append(Trace(data=np.minimum(curve, 0.99), header={
                    "network": net, "station": sta, "location": "", "channel": f"{prefix}_{phase}",
                    "starttime": t0, "delta": delta}))
                continue
            inside = int(rng.integers(0, 4)) if not (j == 0 and phase == "P") else int(rng.integers(1, 4))
            for _redraw in range(100):
                curve = _wiggle(rng, n, float(rng.uniform(0.01, 0.05)))
                spots: List[Tuple[float, float]] = []
                for _ in range(inside):
                    for _try in range(50):
                        c = float(rng.uniform(lo + 2 * gap + 20, hi - 2 * gap - 20))
                        if all(abs(c - s) > 2 * gap + 40 for s, _w in spots):
                            spots.append((c, float(rng.uniform(3.0, 10.0))))
                            break
                for c, sig in spots:
                    curve = curve + float(rng.uniform(0.05, 0.95)) * _bump(n, c, sig)
                # higher bumps outside the window: they must not be chosen
                for a, b in ((60.0, lo - 2 * gap - 40.0), (hi + 2 * gap + 40.0, n - 60.0)):
                    if a < b and rng.random() < 0.8:
                        curve = curve + 0.98 * _bump(n, float(rng.uniform(a, b)), float(rng.uniform(3.0, 10.0)))
                top = float(curve.max())
                if top > 0.99:
                    curve = curve * (0.99 / top)
                curve = curve + 1e-7 * rng.random(n)
                tops = []
                for c, sig in spots:                     # each bump's highest sample, known from where it was put
                    a, b = int(c - 4 * sig), int(c + 4 * sig) + 1
                    tops.append(a + int(np.argmax(curve[a:b])))
                if all(abs(curve[k] - thr) > 2e-3 for k in tops):
                    break
            above = [k for k in tops if curve[k] > thr]
            if above:
                k = max(above, key=lambda i: curve[i])
                truth.append({"station": f"{net}.{sta}", "phase": phase, "time": t0 + k * delta,
                              "probability": float(curve[k])})
            traces.append(Trace(data=curve, header={"network": net, "station": sta, "location": "",
                                                    "channel": f"{prefix}_{phase}", "starttime": t0,
                                                    "delta": delta}))
    order = rng.permutation(len(traces))
    stream = Stream([traces[i] for i in order])
    truth.sort(key=lambda r: (r["station"], r["phase"]))
    return {"stream": stream, "thr": thr, "gap_s": gap_s, "start": start, "end": end, "truth": truth,
            "delta": delta, "rec0": rec0}


def _t2_rows(got: Any) -> Tuple[Optional[List[dict]], Optional[str]]:
    """The student's table as a list of dicts, or a format category."""
    if not _is_frame(got) or not set(T2_COLUMNS) <= set(got.columns):
        return None, "format"
    rows = []
    for rec in got.to_dict("records"):
        t = _utc(rec["time"])
        if t is None or not isinstance(rec["station"], str) or not isinstance(rec["phase"], str):
            return None, "format"
        try:
            p = float(rec["probability"])
        except (TypeError, ValueError):
            return None, "format"
        rows.append({"station": rec["station"], "phase": rec["phase"], "time": t, "probability": p})
    return rows, None


def _t2_judge_synthetic(got: Any, case: dict) -> Optional[str]:
    rows, cat = _t2_rows(got)
    if cat:
        return cat
    truth, delta = case["truth"], case["delta"]
    stations = {f"{tr.stats.network}.{tr.stats.station}" for tr in case["stream"]}
    if any(r["station"] not in stations for r in rows):
        return "station-name"
    if any(r["phase"] not in PHASES for r in rows):
        return "noise-trace"
    keys = [(r["station"], r["phase"]) for r in rows]
    if len(set(keys)) != len(keys):
        return "duplicate"
    want = {(r["station"], r["phase"]): r for r in truth}
    if set(keys) == set(want):
        same_p = all(abs(r["probability"] - want[k]["probability"]) <= 1e-6 for k, r in zip(keys, rows))
        same_t = all(abs(r["time"] - want[k]["time"]) <= 0.5 * delta for k, r in zip(keys, rows))
        if same_p and same_t:
            return None if keys == sorted(keys) else "order"
        if same_p:                                  # the right picks, timed from the wrong start
            return "time-reference"
    if any(not (case["start"] - 0.5 * delta <= r["time"] <= case["end"] + 0.5 * delta) for r in rows):
        return "outside-window"
    if any(r["probability"] < case["thr"] for r in rows):
        return "threshold"
    if any(k in want and abs(r["time"] - want[k]["time"]) > 0.5 * delta for k, r in zip(keys, rows)):
        return "not-best"
    if set(want) - set(keys):
        return "missing-picks"
    return "wrong-values"


def _seisbench_model(name: str, version: str):
    """The pinned PhaseNet weights from the SeisBench cache, without any download; None when missing."""
    try:
        import seisbench
        import seisbench.models as sbm
        import torch
    except Exception:  # noqa: BLE001 - not installed or broken: reported as a category
        return None
    folder = Path(seisbench.cache_model_root) / "phasenet"
    if not all((folder / f"{name}.{kind}.v{version}").is_file() for kind in ("json", "pt")):
        return None
    try:
        torch.set_num_threads(1)
        model = sbm.PhaseNet.from_pretrained(name, version_str=str(version))
        model.eval()
        return model
    except Exception:  # noqa: BLE001
        return None


def _t2_real(target: Any, ctx: Any, crit: dict) -> Tuple[List[bool], Optional[str]]:
    """Records of the student's download, annotated by the check; SeisBench's own peaks as the reference."""
    from obspy import Stream, UTCDateTime, read

    from .. import data as _data

    name = str(ctx.get("dataset") or DATASET_DEFAULT)
    cat = _data.kma_catalog()
    rows = cat.loc[cat["event_id"] == MAIN_EVENT]
    if rows.empty:
        return [False], "no-data"
    origin = UTCDateTime(rows.iloc[0]["origin_utc"].isoformat())
    folder = Path(ctx.data_root) / name / "stp_download" / "SAC" / origin.strftime("%Y%m%d%H%M%S") / "HH"
    groups: Dict[str, List[Path]] = {}
    for f in sorted(folder.glob("*.sac")) if folder.is_dir() else []:
        parts = f.name.split(".")
        if len(parts) >= 5:
            groups.setdefault(".".join(parts[1:3]), []).append(f)
    full = sorted(k for k, v in groups.items() if len(v) == 3)
    count = int(crit.get("real_stations", 3))
    if len(full) < count:
        return [False], "no-data"
    model = _seisbench_model(str(crit.get("model", "stead")), str(crit.get("version", "2")))
    if model is None:
        return [False], "no-model"
    import seisbench.models as sbm

    chosen = [full[i] for i in sorted(ctx.rng.choice(len(full), size=count, replace=False))]
    stream = Stream()
    for key in chosen:
        for f in groups[key]:
            stream += read(str(f))
    ann = model.annotate(stream)
    thr = float(crit.get("threshold", 0.3))
    w0, w1 = (float(x) for x in crit.get("window_s", (-2.0, 40.0)))
    start, end = origin + w0, origin + w1
    got, err = _call(target, ann.copy(), thr, float(crit.get("min_gap_s", 1.0)), start, end)
    if err is not None:
        raise err
    rows, cat_ = _t2_rows(got)
    if cat_:
        return [False], cat_
    curves = {}
    for tr in ann:
        phase = tr.stats.channel.split("_")[-1]
        if phase in PHASES:
            curves[(f"{tr.stats.network}.{tr.stats.station}", phase)] = tr
    oks: List[bool] = []
    cats: List[str] = []
    keys = [(r["station"], r["phase"]) for r in rows]
    if len(set(keys)) != len(keys):
        return [False], "duplicate"
    for r, key in zip(rows, keys):                                    # every row lies on the model's curve
        tr = curves.get(key)
        if tr is None:
            oks.append(False)
            cats.append("noise-trace" if r["phase"] not in PHASES else "station-name")
            continue
        k = int(round((r["time"] - tr.stats.starttime) / tr.stats.delta))
        on = 0 <= k < tr.stats.npts and abs(r["time"] - (tr.stats.starttime + k * tr.stats.delta)) <= \
            0.5 * tr.stats.delta and abs(float(tr.data[k]) - r["probability"]) <= float(crit.get("prob_tol", 1e-6))
        inside = start - 0.5 * tr.stats.delta <= r["time"] <= end + 0.5 * tr.stats.delta
        ok = bool(on and inside and r["probability"] >= thr)
        oks.append(ok)
        if not ok:
            cats.append("time-reference" if not on else ("outside-window" if not inside else "threshold"))
    strong = float(crit.get("strong_prob", 0.5))
    margin = max(1.0, float(crit.get("min_gap_s", 1.0)))          # no pick outside the window can prune it
    by_key = {key: r for key, r in zip(keys, rows)}
    for key, tr in sorted(curves.items()):                           # the clear picks: SeisBench's own peaks
        found = sbm.WaveformModel.picks_from_annotations([tr], thr, key[1])
        inside = [p for p in found if start <= p.peak_time <= end]
        if not inside:
            continue
        best = max(inside, key=lambda p: p.peak_value)
        if best.peak_value < strong or not (start + margin <= best.peak_time <= end - margin):
            continue
        mine = by_key.get(key)
        ok = mine is not None and abs(mine["time"] - best.peak_time) <= 0.5 * tr.stats.delta
        oks.append(bool(ok))
        if not ok:
            cats.append("missing-picks" if mine is None else "not-best")
    return oks, _first(cats, T2_PRIORITY)


def check_T2(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    trials = max(4, int(crit.get("trials", 8)))
    rng = ctx.rng
    oks, cats, example = [], [], None
    for k in range(trials):
        case = _t2_case(rng, k)
        got, err = _call(target, case["stream"].copy(), case["thr"], case["gap_s"], case["start"], case["end"])
        if err is not None:
            raise err
        cat = _t2_judge_synthetic(got, case)
        oks.append(cat is None)
        if cat:
            cats.append(cat)
            if example is None:
                example = {"inputs": {"stations": sorted({f"{t.stats.network}.{t.stats.station}"
                                                          for t in case["stream"]}),
                                      "threshold": round(case["thr"], 4), "min_gap_s": case["gap_s"],
                                      "start": str(case["start"]), "end": str(case["end"])},
                           "got": (got.head(6).to_dict("records") if _is_frame(got) else type(got).__name__),
                           "error": "expected " + "; ".join(f"{r['station']} {r['phase']} at {r['time']} "
                                                           f"(probability {r['probability']:.4f})"
                                                           for r in case["truth"][:6])}
    category = _first(cats, T2_PRIORITY)
    if category is not None:
        return outcome_from_cases(np.array(oks), category=category, example=example)
    real_oks, real_cat = _t2_real(target, ctx, crit)
    note = ("The check ran the pinned PhaseNet weights on records of your own download and compared your rows "
            "with the model's curves and SeisBench's own picks; it never prints those values.")
    all_ok = np.array(oks + real_oks, dtype=bool)
    if real_cat is not None and all_ok.all():
        all_ok = np.append(all_ok, False)
    return outcome_from_cases(all_ok, category=real_cat, real_data=True, note=note)


# ===================================================================== M21-T3 matching two pick sets
T3_PRIORITY = ("format", "duplicate", "key", "missing-rows", "status", "sign", "units", "order", "wrong-values")
T3_STATUS = ("both", "only_a", "only_b")


def _t3_case(rng: np.random.Generator, number: int) -> dict:
    import pandas as pd
    from obspy import UTCDateTime

    with_event = number % 3 == 2
    t0 = UTCDateTime(2019, 7, 21, 2, 4, 18) + float(np.round(rng.uniform(0, 3e6), 3))
    stations = ["%s.%s" % (("KS", "KG")[i % 2], "ST%02d" % i) for i in rng.choice(60, size=8, replace=False)]
    events = ["2019%010d" % int(e) for e in rng.choice(10 ** 9, size=2, replace=False)] if with_event else [None]
    keys = [(e, s, p) for e in events for s in stations for p in PHASES]
    keys = [keys[i] for i in rng.permutation(len(keys))[: int(rng.integers(6, len(keys) + 1))]]
    rows_a, rows_b, truth = [], [], []
    for (e, s, p) in keys:
        base = t0 + float(rng.uniform(1.0, 60.0)) + (4.0 if p == "S" else 0.0)
        kind = rng.choice(["both", "both", "both", "only_a", "only_b"])
        diff = float(np.round(rng.normal(0.0, 0.08), 3)) if rng.random() < 0.8 else float(rng.choice([-1.5, 2.25]))
        key = {"event_id": e} if with_event else {}
        if kind in ("both", "only_a"):
            rows_a.append({**key, "station": s, "phase": p, "time": base})
        if kind in ("both", "only_b"):
            rows_b.append({**key, "station": s, "phase": p, "time": base + diff})
        truth.append({**key, "station": s, "phase": p, "status": kind,
                      "diff_s": diff if kind == "both" else float("nan"),
                      "time_a": base if kind != "only_b" else None, "time_b": base + diff if kind != "only_a" else None})
    if not rows_a or not rows_b:
        return _t3_case(rng, number + 3)
    cols = (["event_id"] if with_event else []) + ["station", "phase", "time"]
    a = pd.DataFrame(rows_a, columns=cols).sample(frac=1.0, random_state=int(rng.integers(1 << 30)))
    b = pd.DataFrame(rows_b, columns=cols).sample(frac=1.0, random_state=int(rng.integers(1 << 30)))
    if number % 4 == 1:                                   # extra columns that are not part of the key
        a["probability"] = rng.uniform(0.3, 1.0, len(a))
        b["polarity"] = rng.choice(["U", "D", "?"], len(b))
    order = ["event_id", "station", "phase"] if with_event else ["station", "phase"]
    truth.sort(key=lambda r: tuple(r[c] for c in order))
    return {"a": a.reset_index(drop=True), "b": b.reset_index(drop=True), "truth": truth, "keys": order}


def _t3_judge(got: Any, case: dict, tol: float) -> Optional[str]:
    keys = case["keys"]
    need = set(keys) | {"time_a", "time_b", "diff_s", "status"}
    if not _is_frame(got) or not need <= set(got.columns):
        return "format"
    truth = case["truth"]
    want = {tuple(r[c] for c in keys): r for r in truth}
    try:
        rows = got.to_dict("records")
        mine = [tuple(r[c] for c in keys) for r in rows]
    except Exception:  # noqa: BLE001
        return "format"
    if len(mine) != len(set(mine)):
        return "key"                                # rows repeated: matched on too few columns
    if set(mine) != set(want):
        return "missing-rows" if set(mine) < set(want) else "key"
    bad_status = bad_sign = bad_units = bad_value = False
    for r, k in zip(rows, mine):
        w = want[k]
        if str(r["status"]) != w["status"]:
            bad_status = True
            continue
        for col in ("time_a", "time_b"):
            if w[col] is None:
                if not _missing(r[col]):
                    bad_value = True
            elif _utc(r[col]) is None or abs(r[col] - w[col]) > 1e-6:
                bad_value = True
        d = r["diff_s"]
        try:
            d = float(d)
        except (TypeError, ValueError):
            bad_value = True
            continue
        if w["status"] != "both":
            if not math.isnan(d):
                bad_value = True
            continue
        if not abs(d - w["diff_s"]) <= tol:
            if abs(d + w["diff_s"]) <= tol and abs(w["diff_s"]) > tol:
                bad_sign = True
            elif abs(d - 1000.0 * w["diff_s"]) <= 1000 * tol and abs(w["diff_s"]) > tol:
                bad_units = True
            else:
                bad_value = True
    if bad_status:
        return "status"
    if bad_sign:
        return "sign"
    if bad_units:
        return "units"
    if bad_value:
        return "wrong-values"
    if mine != [tuple(r[c] for c in keys) for r in truth]:
        return "order"
    return None


def check_T3(target: Any, ctx: Any) -> Outcome:
    trials = max(10, int(ctx.criteria.get("trials", 40)))
    tol = float(ctx.criteria.get("diff_tol_s", 1e-6))
    rng = ctx.rng
    oks, cats, example = [], [], None
    for k in range(trials):
        case = _t3_case(rng, k)
        a_before, b_before = case["a"].copy(), case["b"].copy()
        got, err = _call(target, case["a"], case["b"])
        if err is not None:
            raise err
        cat = _t3_judge(got, case, tol)
        if cat is None and not (case["a"].equals(a_before) and case["b"].equals(b_before)):
            cat = "wrong-values"
        oks.append(cat is None)
        if cat:
            cats.append(cat)
            if example is None:
                example = {"inputs": {"rows in a": len(case["a"]), "rows in b": len(case["b"]),
                                      "key": case["keys"]},
                           "got": got.head(4).to_dict("records") if _is_frame(got) else type(got).__name__,
                           "error": "expected " + str([{c: (str(r[c]) if c.startswith("time") else r[c])
                                                        for c in case["keys"] + ["status", "diff_s"]}
                                                       for r in case["truth"][:3]])}
    # a key that appears twice in one table must stop the function
    import pandas as pd

    for k in range(3):
        case = _t3_case(rng, 100 + k)
        a = case["a"]
        doubled = pd.concat([a, a.iloc[[0]].copy()], ignore_index=True)
        pair = (doubled, case["b"]) if k != 1 else (case["b"], doubled)
        got, err = _call(target, *pair)
        ok = isinstance(err, ValueError)
        oks.append(ok)
        if not ok:
            if err is not None and not isinstance(err, ValueError):
                raise err
            cats.append("duplicate")
    return outcome_from_cases(np.array(oks), category=_first(cats, T3_PRIORITY), example=example)


# ===================================================================== M21-T4 PocketQuake pick files and runs
T4_KEYS = {"reader", "slug", "first", "rerun", "changed", "min_prob_changed", "fingerprints"}
T4_COLUMNS = ("event_id", "station", "phase", "time", "probability")
T4_PRIORITY = ("format", "reader-format", "event-id", "station-name", "time-type", "invented-column",
               "other-files", "reader-values", "copies", "fingerprint-files", "fingerprint-claim", "runs-missing",
               "not-run-products", "no-rerun", "threshold", "no-change")
_HEX = set("0123456789abcdef")
PQ_HEADER_FULL = "Event_ID,Network,Station,Phase,Time,Probability,Polarity,Amplitude"
PQ_HEADER_PLAIN = "Event_ID,Network,Station,Phase,Time,Probability"


def _t4_folder(rng: np.random.Generator, root: Path, number: int) -> dict:
    """A made-up PocketQuake picks folder: one <event>_picks.csv per event, plus files that are not picks."""
    from obspy import UTCDateTime

    folder = root / f"case{number}"
    folder.mkdir(parents=True)
    with_polarity = number % 3 != 2
    rows = []
    n_events = int(rng.integers(2, 5))
    for e in range(n_events):
        origin = UTCDateTime(2018, 1, 1) + float(np.round(rng.uniform(0, 1.5e8), 0))
        event_id = origin.strftime("%Y%m%d%H%M%S")
        lines = [PQ_HEADER_FULL if with_polarity else PQ_HEADER_PLAIN]
        for s in rng.choice(90, size=int(rng.integers(2, 7)), replace=False):
            net = ("KS", "KG")[int(s) % 2]
            sta = "ST%02d" % int(s)
            for phase in PHASES:
                if rng.random() < 0.15:
                    continue
                t = origin + float(np.round(rng.uniform(2, 30), 2)) + (3.0 if phase == "S" else 0.0)
                prob = float(np.round(rng.uniform(0.3, 0.99), 3))
                pol = float(np.round(rng.uniform(-1, 1), 3)) if phase == "P" else float("nan")
                amp = float(np.round(rng.uniform(10, 1e6), 1))
                text = f"{event_id},{net},{sta},{phase},{str(t)},{prob}"
                if with_polarity:
                    text += f",{'' if math.isnan(pol) else pol},{amp}"
                lines.append(text)
                rows.append({"event_id": event_id, "station": f"{net}.{sta}", "phase": phase, "time": t,
                             "probability": prob, "polarity": pol})
        (folder / f"{event_id}_picks.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (folder / "notes.txt").write_text("not a pick file\n", encoding="utf-8")
    (folder / "summary.csv").write_text("Event_ID,n\n1,2\n", encoding="utf-8")
    return {"folder": folder, "rows": rows, "with_polarity": with_polarity}


def _t4_reader_judge(got: Any, case: dict) -> Optional[str]:
    if not _is_frame(got) or not set(T4_COLUMNS) <= set(got.columns):
        return "reader-format"
    if case["with_polarity"] and "polarity" not in got.columns:
        return "reader-format"
    if not case["with_polarity"] and "polarity" in got.columns:
        return "invented-column"
    if len(got) != len(case["rows"]):
        return "other-files" if len(got) > len(case["rows"]) else "reader-values"
    recs = got.to_dict("records")
    if not all(isinstance(r["event_id"], str) for r in recs):
        return "event-id"
    if not all(_utc(r["time"]) is not None for r in recs):
        return "time-type"
    want = {(r["event_id"], r["station"], r["phase"]): r for r in case["rows"]}
    mine = {(r["event_id"], r["station"], r["phase"]): r for r in recs}
    if set(mine) != set(want):
        stations = {k[1] for k in mine}
        if stations and not any("." in s for s in stations):
            return "station-name"
        return "reader-values"
    for k, w in want.items():
        r = mine[k]
        if abs(_utc(r["time"]) - w["time"]) > 1e-6 or abs(float(r["probability"]) - w["probability"]) > 1e-9:
            return "reader-values"
        if case["with_polarity"]:
            pol = float(r["polarity"]) if r["polarity"] is not None else float("nan")
            if (math.isnan(pol) != math.isnan(w["polarity"])) or \
                    (not math.isnan(pol) and abs(pol - w["polarity"]) > 1e-9):
                return "reader-values"
    return None


def _pick_fingerprint(folder: Path) -> Optional[str]:
    """The fingerprint sgtl logs for the pick files of a run: SHA-256 of the sorted '<sha256>  <name>' lines."""
    files = sorted(folder.glob("*_picks.csv"))
    if not files:
        return None
    lines = []
    for f in files:
        h = hashlib.sha256(f.read_bytes()).hexdigest()
        lines.append(f"{h}  {f.name}\n")
    return hashlib.sha256("".join(lines).encode()).hexdigest()


def _csv_rows(folder: Path) -> List[dict]:
    import csv

    out = []
    for f in sorted(folder.glob("*_picks.csv")):
        with open(f, newline="", encoding="utf-8") as fh:
            out.extend(csv.DictReader(fh))
    return out


def _t4_prints_ok(value: Any) -> bool:
    """The report's fingerprints: {"first": {name: 64 hex letters}, "rerun": {name: 64 hex letters}}, none empty."""
    if not isinstance(value, dict) or set(value) != {"first", "rerun"}:
        return False
    return all(isinstance(per, dict) and per and
               all(isinstance(k, str) and isinstance(v, str) and len(v) == 64 and set(v.lower()) <= _HEX
                   for k, v in per.items())
               for per in value.values())


def _t4_artifacts(target: dict, ctx: Any, crit: dict) -> Tuple[int, Optional[str]]:
    """The student's own run products: returns (number of passed steps, category of the first failure)."""
    passed = 0
    folders = {}
    for key in ("first", "rerun", "changed"):
        value = target[key]
        if not isinstance(value, (str, os.PathLike)):
            return passed, "format"
        folder = Path(value).expanduser()
        if not folder.is_dir() or not list(folder.glob("*_picks.csv")):
            return passed, "copies"
        folders[key] = folder
    reader = target["reader"]
    for key, folder in folders.items():
        got, err = _call(reader, str(folder))
        if err is not None:
            raise err
        if not _is_frame(got) or len(got) != len(_csv_rows(folder)):
            return passed, "copies"
    passed += 1
    for key in ("first", "rerun"):              # every pick file of the copy, each digest recomputed from its bytes
        claim = target["fingerprints"][key]
        files = {p.relative_to(folders[key]).as_posix(): p for p in sorted(folders[key].glob("*_picks.csv"))}
        if set(claim) != set(files):
            return passed, "fingerprint-files"
        if any(claim[name].lower() != hashlib.sha256(p.read_bytes()).hexdigest() for name, p in files.items()):
            return passed, "fingerprint-claim"
    passed += 1
    log = Path(ctx.repo) / "work" / ".sgtl" / "runs.jsonl"
    slug = target["slug"]
    if not isinstance(slug, str) or not log.is_file():
        return passed, "runs-missing"
    from .. import pq as _pq

    order = list(_pq.STAGES)
    logged = []
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("command") != "pq run" or rec.get("cluster") != slug or rec.get("returncode") != 0:
            continue
        first, last = rec.get("stage_from"), rec.get("through")
        if first not in order or last not in order or \
                not order.index(first) <= order.index("picking") <= order.index(last):
            continue
        for name, value in (rec.get("products") or {}).items():
            if name.startswith("picks/*.csv"):
                logged.append(value)
    if len(logged) < int(crit.get("min_runs", 3)):
        return passed, "runs-missing"
    passed += 1
    prints = {key: _pick_fingerprint(folder) for key, folder in folders.items()}
    if any(p not in logged for p in prints.values()):
        return passed, "not-run-products"
    passed += 1
    if folders["first"].resolve() == folders["rerun"].resolve():
        return passed, "no-rerun"                     # one copy named for both runs
    if prints["first"] == prints["rerun"] and logged.count(prints["first"]) < 2:
        return passed, "no-rerun"                     # the same bytes twice, but only one run wrote them
    passed += 1
    default = float(crit.get("default_min_prob", 0.3))
    try:
        changed = float(target["min_prob_changed"])
    except (TypeError, ValueError):
        return passed, "format"
    probs = {key: [float(r["Probability"]) for r in _csv_rows(folder)] for key, folder in folders.items()}
    if abs(changed - default) < 1e-9 or min(probs["changed"]) < changed - 1e-9 or \
            min(probs["first"]) < default - 1e-9 or min(probs["rerun"]) < default - 1e-9:
        return passed, "threshold"
    passed += 1
    if prints["changed"] == prints["first"]:
        return passed, "no-change"
    passed += 1
    return passed, None


def check_T4(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    if not isinstance(target, dict) or set(target) != T4_KEYS or not callable(target.get("reader")) or \
            not _t4_prints_ok(target.get("fingerprints")):
        return Outcome(passed=False, n_cases=1, n_failed=1, category="format", message="", details={})
    rng = ctx.rng
    oks, cats, example = [], [], None
    with tempfile.TemporaryDirectory(prefix="sgtl-m21-t4-") as tmp:
        for k in range(max(3, int(crit.get("trials", 6)))):
            case = _t4_folder(rng, Path(tmp), k)
            got, err = _call(target["reader"], str(case["folder"]))
            if err is not None:
                raise err
            cat = _t4_reader_judge(got, case)
            oks.append(cat is None)
            if cat:
                cats.append(cat)
                if example is None:
                    example = {"inputs": {"files": sorted(p.name for p in case["folder"].iterdir()),
                                          "polarity column": case["with_polarity"]},
                               "got": (got.head(3).to_dict("records") if _is_frame(got) else type(got).__name__),
                               "error": f"expected {len(case['rows'])} picks"}
    category = _first(cats, T4_PRIORITY)
    if category is not None:
        return outcome_from_cases(np.array(oks), category=category, example=example)
    passed, cat = _t4_artifacts(target, ctx, crit)
    steps = 7
    ok = np.array(oks + [True] * passed + [False] * (steps - passed if cat else 0), dtype=bool)
    note = ("The check read your copied pick folders, recomputed the SHA-256 fingerprint of every pick file and "
            "compared them with yours and with the ones sgtl logged for your runs in work/.sgtl/runs.jsonl; it never "
            "prints the pick values or the fingerprints.")
    return outcome_from_cases(ok, category=cat, real_data=True, note=note)


# ===================================================================== M21-T5 first motions from a pick table
T5_PRIORITY = ("format", "missing-column", "s-picks", "pick-probability", "sign", "boundary", "nan", "order",
               "wrong-values")


def _t5_case(rng: np.random.Generator, number: int) -> dict:
    import pandas as pd

    with_event = number % 2 == 0
    w = float(np.round(rng.uniform(0.15, 0.5), 2))
    pmin = float(np.round(rng.uniform(0.3, 0.7), 2))
    rows, truth = [], []
    for i in rng.permutation(60)[: int(rng.integers(8, 30))]:
        station = "%s.ST%02d" % (("KS", "KG")[int(i) % 2], int(i))
        event = "2019%010d" % int(rng.integers(10 ** 9)) if with_event else None
        for phase in PHASES:
            prob = float(np.round(rng.uniform(0.3, 0.99), 3))
            if rng.random() < 0.2:
                prob = pmin if rng.random() < 0.5 else float(np.round(pmin - 0.01, 3))
            label = str(rng.choice(["U", "D", "?", "?b", "?n"]))
            if phase == "S":
                pol = float("nan")
            elif label == "U":
                pol = w if rng.random() < 0.2 else float(np.round(rng.uniform(w + 0.01, 1.0), 3))
            elif label == "D":
                pol = -w if rng.random() < 0.2 else float(np.round(-rng.uniform(w + 0.01, 1.0), 3))
            elif label == "?n":
                pol = float("nan")
            else:
                pol = float(np.round(rng.uniform(-w + 0.005, w - 0.005), 3))
            row = {"station": station, "phase": phase, "probability": prob, "polarity": pol}
            if with_event:
                row = {"event_id": event, **row}
            rows.append(row)
            if phase == "P":
                fm = label[0] if prob >= pmin else "?"
                truth.append({**({"event_id": event} if with_event else {}), "station": station,
                              "first_motion": fm, "pol": pol, "prob": prob})
    frame = pd.DataFrame(rows)
    keys = ["event_id", "station"] if with_event else ["station"]
    truth.sort(key=lambda r: tuple(r[c] for c in keys))
    return {"picks": frame, "w": w, "pmin": pmin, "truth": truth, "keys": keys}


def _t5_judge(got: Any, case: dict) -> Optional[str]:
    keys = case["keys"]
    if not _is_frame(got) or not set(keys + ["first_motion"]) <= set(got.columns):
        return "format"
    recs = got.to_dict("records")
    if any(str(r["first_motion"]) not in ("U", "D", "?") for r in recs):
        return "format"
    truth = case["truth"]
    if len(recs) != len(truth):
        return "s-picks" if len(recs) > len(truth) else "wrong-values"
    want = {tuple(t[c] for c in keys): t for t in truth}
    mine = {tuple(r[c] for c in keys): r for r in recs}
    if set(mine) != set(want):
        return "wrong-values"
    cats = []
    for k, t in want.items():
        fm = str(mine[k]["first_motion"])
        if fm == t["first_motion"]:
            continue
        pol, prob = t["pol"], t["prob"]
        if prob < case["pmin"] and fm != "?":
            cats.append("pick-probability")
        elif math.isnan(pol):
            cats.append("nan")
        elif abs(abs(pol) - case["w"]) < 1e-9:
            cats.append("boundary")
        elif t["first_motion"] in "UD" and fm in "UD":
            cats.append("sign")
        else:
            cats.append("wrong-values")
    if cats:
        return _first(cats, T5_PRIORITY)
    if [tuple(r[c] for c in keys) for r in recs] != [tuple(t[c] for c in keys) for t in truth]:
        return "order"
    return None


def check_T5(target: Any, ctx: Any) -> Outcome:
    trials = max(10, int(ctx.criteria.get("trials", 40)))
    rng = ctx.rng
    oks, cats, example = [], [], None
    for k in range(trials):
        case = _t5_case(rng, k)
        before = case["picks"].copy()
        got, err = _call(target, case["picks"], case["w"], case["pmin"])
        if err is not None:
            raise err
        cat = _t5_judge(got, case)
        if cat is None and not case["picks"].equals(before):
            cat = "wrong-values"
        oks.append(cat is None)
        if cat:
            cats.append(cat)
            if example is None:
                example = {"inputs": {"P picks": len(case["truth"]), "min_weight": case["w"],
                                      "min_prob": case["pmin"]},
                           "got": got.head(4).to_dict("records") if _is_frame(got) else type(got).__name__,
                           "error": "expected " + str([(t["station"], t["first_motion"]) for t in case["truth"][:4]])}
    for k in range(3):                     # no polarity column at all: the function must stop, never guess
        case = _t5_case(rng, 50 + k)
        plain = case["picks"].drop(columns=["polarity"])
        got, err = _call(target, plain, case["w"], case["pmin"])
        ok = isinstance(err, ValueError)
        oks.append(ok)
        if not ok:                         # first motions, or another error (KeyError, ...): the category tells why
            cats.append("missing-column")
    return outcome_from_cases(np.array(oks), category=_first(cats, T5_PRIORITY), example=example)
