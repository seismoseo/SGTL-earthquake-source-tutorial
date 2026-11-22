"""Checkers for M60 · Putting it together: a full run on a new sequence, and the plan for your project.

Where the truth comes from (DESIGN.md section 1, rule 1):

* M60-T1: construction. Made-up dataset folders (a catalog in Korean time, waveform folders named in UTC, file names
  only) and made-up pick tables, each built with a known state; the expected status of every check and the expected
  counts are set while the folder is built.
* M60-T2: the student's own function and tool products. A short re-test of the preflight on made-up folders; then
  the student's preflight run again on the real folder and on the pick files of the student's own run (their
  combined fingerprint looked up in work/.sgtl/runs.jsonl), and the run log searched for successful runs of every
  stage of the chain.
* M60-T3: construction (made-up tool tables with known events, missing rows and repeated mechanism rows), then the
  student's own run: the copied products against their fingerprints in the run log, and the saved table against the
  student's own function on those copies.
* M60-T4: construction for the function (made-up locations moved by known amounts, distances from pyproj on a
  sphere), then the student's own runs: three copied folders, their fingerprints in the run log, the phase files
  that show the one change, and the reported table against the student's own function on the copies.
* M60-T5: construction (made-up stations placed at known distances with pyproj on a sphere, known dates), then the
  student's inventory against the student's own function on the files the student read, the shipped catalog
  subset, and the dry-run plan of the course package.
* M60-T6: construction (made-up project folders, each with one known problem or none), then the student's own
  project files: their fingerprints, the student's audit run again, and the content rules of the Contract read
  by the check itself (words per entry and answer, a place in the paper, a threshold with its unit, the mentor
  sign-off, the questions of the template).

No real-data value is computed or printed here. Failure categories are keys of ``checks/specs/M60.yaml``.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
import numbers
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .. import _paths
from . import Outcome, outcome_from_cases

__all__ = ["check_T1", "check_T2", "check_T3", "check_T4", "check_T5", "check_T6"]

HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX32 = re.compile(r"[0-9a-f]{32}")
CHECKS = ("catalog", "time_zone", "events", "stations", "polarity", "cores", "memory")
STAGES = ("stations", "waveforms", "picking", "hypoinverse", "ph2dt", "dtct", "rereference", "xcorr", "dtcc",
          "focal_mechanism")
CAT_COLUMNS = ("Year", "Month", "Day", "Hour", "Minute", "Second", "Latitude", "Longitude", "Depth", "Magnitude")


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


def _logged(ctx: Any, slug: str) -> List[dict]:
    """Successful records of the cluster in work/.sgtl/runs.jsonl, in file order."""
    out: List[dict] = []
    try:
        text = (Path(ctx.repo) / "work" / ".sgtl" / "runs.jsonl").read_text(encoding="utf-8")
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


def _writes(records: Sequence[dict], pattern: str) -> Dict[str, int]:
    """fingerprint -> number of logged runs that wrote a product whose key matches the regular expression."""
    found: Dict[str, int] = {}
    rx = re.compile(pattern)
    for rec in records:
        for key, sha in (rec.get("products") or {}).items():
            if rx.fullmatch(str(key)):
                found[str(sha)] = found.get(str(sha), 0) + 1
    return found


def _picks_fingerprint(folder: Path) -> Optional[str]:
    """The combined fingerprint that sgtl logs for pick files: SHA-256 of sorted '<sha256>  <name>' lines."""
    files = sorted(folder.glob("*.csv"))
    if not files:
        return None
    joined = "".join(f"{_sha256(p)}  {p.name}\n" for p in files)
    return hashlib.sha256(joined.encode()).hexdigest()


def _status_list(report: Any) -> Optional[List[str]]:
    """The status column of a preflight report in CHECKS order, or None when the report has the wrong form."""
    if not _frame(report) or not {"check", "status", "detail"} <= set(report.columns):
        return None
    if [str(c) for c in report["check"]] != list(CHECKS):
        return None
    return [str(s) for s in report["status"]]


def _counts_ok(counts: Any) -> bool:
    return _frame(counts) and {"stations", "polarities"} <= set(counts.columns)


def _num_equal(value: Any, want: Optional[float]) -> bool:
    """value equals want (a number), or is NaN when want is None."""
    if isinstance(value, (bool, np.bool_)):
        return False
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    return math.isnan(v) if want is None else v == float(want)


def _missing(value: Any) -> bool:
    """None, NaN, NaT or pandas' NA."""
    try:
        import pandas as pd

        return bool(pd.isna(value))
    except (ImportError, TypeError, ValueError):
        return value is None


def _same_counts(counts: Any, expected: Dict[str, Tuple[int, Optional[int]]], column: str) -> bool:
    """The counts table has one row per expected event folder (sorted) with the expected value in ``column``."""
    try:
        idx = [str(i) for i in counts.index]
        if sorted(idx) != sorted(expected) or idx != sorted(idx):
            return False
        k = 0 if column == "stations" else 1
        return all(_num_equal(v, expected[e][k]) for e, v in zip(idx, counts[column].tolist()))
    except (TypeError, ValueError, KeyError):
        return False


# ------------------------------------------------------------------------------------------- M60-T1
T1_PRIORITY = ("format", "changed-input", "catalog", "time-zone", "events", "stations", "polarity", "skip", "cores",
               "memory")
_CHECK_CATEGORY = {"catalog": "catalog", "time_zone": "time-zone", "events": "events", "stations": "stations",
                   "polarity": "polarity", "cores": "cores", "memory": "memory"}
_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"


def _made_up_code(rng: np.random.Generator, used: set) -> str:
    while True:
        code = "Q" + "".join(rng.choice(list(_LETTERS), size=int(rng.integers(2, 4))))
        if code not in used:
            used.add(code)
            return code


def _kst_times(rng: np.random.Generator, n: int) -> List[_dt.datetime]:
    """n distinct KST clock readings; some in the first 9 hours of a day, of a month or of a year."""
    out: List[_dt.datetime] = []
    while len(out) < n:
        year = int(rng.integers(2005, 2026))
        kind = int(rng.integers(0, 4))
        if kind == 0:
            t = _dt.datetime(year, 1, 1, int(rng.integers(0, 9)), int(rng.integers(0, 60)), int(rng.integers(0, 60)))
        elif kind == 1:
            month = int(rng.integers(1, 13))
            t = _dt.datetime(year, month, 1, int(rng.integers(0, 9)), int(rng.integers(0, 60)),
                             int(rng.integers(0, 60)))
        else:
            t = _dt.datetime(year, int(rng.integers(1, 13)), int(rng.integers(1, 29)), int(rng.integers(0, 24)),
                             int(rng.integers(0, 60)), int(rng.integers(0, 60)))
        if t not in out:
            out.append(t)
    return out


def _id(t: _dt.datetime) -> str:
    return t.strftime("%Y%m%d%H%M%S")


def _write_station(event_dir: Path, start: str, net: str, sta: str, band: str, comps: str) -> None:
    (event_dir / band).mkdir(parents=True, exist_ok=True)
    for c in comps:
        (event_dir / band / f"{start}.{net}.{sta}.{band}{c}.sac").write_bytes(b"made-up record\n")


T1_KINDS = ("ok", "no-catalog", "kst-folders", "missing-event", "extra-folder", "few-stations", "bands-twice",
            "no-polarity-column", "weak-polarities", "down-polarities", "no-picks", "cores-high", "cores-zero",
            "memory-short", "memory-edge", "memory-cap")


def _t1_case(rng: np.random.Generator, root: Path, kind: str, crit: dict) -> dict:
    """Build one made-up dataset folder (and picks) whose expected preflight result is known by construction."""
    import pandas as pd

    min_st, min_pol = int(crit.get("min_stations", 8)), int(crit.get("min_polarities", 8))
    min_w, min_p = float(crit.get("min_weight", 0.3)), float(crit.get("min_prob", 0.5))
    folder = root / f"case{len(list(root.iterdir())):02d}_{kind}"
    n_ev = int(rng.integers(2, 5))
    kst = _kst_times(rng, n_ev)
    utc_ids = [_id(t - _dt.timedelta(hours=9)) for t in kst]
    status = {"catalog": "PASS", "time_zone": "PASS", "events": "PASS", "stations": "PASS", "polarity": "PASS",
              "cores": "PASS", "memory": "PASS"}
    if kind != "no-catalog":
        (folder / "event_catalog").mkdir(parents=True, exist_ok=True)
        rows = ["Year,Month,Day,Hour,Minute,Second,Latitude,Longitude,Depth,Magnitude"]
        for t in kst:
            rows.append(f"{t.year},{t.month},{t.day},{t.hour},{t.minute},{t.second},"
                        f"{rng.uniform(34, 38):.2f},{rng.uniform(126, 130):.2f},{rng.uniform(3, 20):.1f},"
                        f"{rng.uniform(1, 4):.1f}")
        (folder / "event_catalog" / "event_catalog.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    else:
        status.update(catalog="FAIL", time_zone="FAIL", events="FAIL")
    folders = list(utc_ids)
    if kind == "kst-folders":
        folders = [_id(t) for t in kst]
        status.update(time_zone="FAIL", events="FAIL")
    elif kind == "missing-event":
        folders = folders[:-1]
        status.update(events="FAIL")
    elif kind == "extra-folder":
        extra = _id(_dt.datetime(2004, 6, 15, 12, 0, 0) + _dt.timedelta(seconds=int(rng.integers(0, 10 ** 6))))
        folders = folders + [extra]
        status.update(events="FAIL")
    sac_root = folder / "stp_download" / "SAC"
    sac_root.mkdir(parents=True, exist_ok=True)
    expected: Dict[str, Tuple[int, Optional[int]]] = {}
    used: set = set()
    pick_rows: List[dict] = []
    short = int(rng.integers(0, len(folders)))
    for k, event in enumerate(folders):
        start = _id(_dt.datetime.strptime(event, "%Y%m%d%H%M%S") - _dt.timedelta(seconds=30))
        n_st = int(rng.integers(min_st, min_st + 6))
        if kind in ("few-stations", "bands-twice") and k == short:
            n_st = min_st - 1
        codes = [_made_up_code(rng, used) for _ in range(n_st)]
        for j, code in enumerate(codes):
            net = "XA" if j % 3 else "XB"
            bands = ["HH"] if j % 4 == 0 else (["HG"] if j % 4 == 1 else ["EL"])
            if kind == "bands-twice" or j % 5 == 0:
                bands = ["HH", "HG"]
            for band in bands:
                _write_station(sac_root / event, start, net, code, band, "ENZ")
        for _ in range(int(rng.integers(1, 4))):        # horizontal-only stations: no vertical record
            _write_station(sac_root / event, start, "XA", _made_up_code(rng, used), "HG", "EN")
        if kind in ("few-stations", "bands-twice") and k == short:
            status["stations"] = "FAIL"
        # picks: usable P polarities, weak ones, uncertain ones, S rows
        n_pol = int(rng.integers(min_pol, min_pol + 5))
        if kind == "weak-polarities" and k == short:
            n_pol = min_pol - 1
            status["polarity"] = "FAIL"
        evid = int(event)
        for j in range(n_pol):
            size = rng.uniform(min_w, 1.0) if j else min_w                      # one exactly at the limit
            sign = -1.0 if (kind == "down-polarities" and j % 3 != 2) or rng.random() < 0.3 else 1.0
            prob = rng.uniform(min_p, 1.0) if j != 1 else min_p
            pick_rows.append({"Event_ID": evid, "Network": "XA", "Station": codes[j % len(codes)], "Phase": "P",
                              "Time": f"{event}", "Probability": round(prob, 3), "Polarity": round(sign * size, 3),
                              "Amplitude": 100.0})
        for _ in range(int(rng.integers(2, 6))):         # too small, or too uncertain, or S rows
            r = int(rng.integers(0, 3))
            pick_rows.append({"Event_ID": evid, "Network": "XA", "Station": codes[0],
                              "Phase": "S" if r == 2 else "P", "Time": f"{event}",
                              "Probability": round(rng.uniform(0.2, min_p - 0.01) if r == 1 else 0.9, 3),
                              "Polarity": (round(rng.uniform(-min_w + 0.01, min_w - 0.01), 3) if r == 0 else
                                           (round(rng.uniform(0.5, 1.0), 3) if r == 1 else float("nan"))),
                              "Amplitude": 50.0})
        expected[event] = (n_st, n_pol)
    picks = pd.DataFrame(pick_rows).sample(frac=1.0, random_state=int(rng.integers(0, 2 ** 31))).reset_index(drop=True)
    if kind == "no-polarity-column":
        picks = picks.drop(columns=["Polarity"])
        status["polarity"] = "FAIL"
        expected = {e: (s, None) for e, (s, _) in expected.items()}
    if kind == "no-picks":
        picks = None
        status["polarity"] = "SKIP"
        expected = {e: (s, None) for e, (s, _) in expected.items()}
    cores, mem_gb, avail = int(rng.integers(1, 5)), float(rng.choice([4.0, 6.0, 8.0])), 100.0
    if kind == "cores-high":
        cores = int(rng.integers(5, 17))
        status["cores"] = "FAIL"
    elif kind == "cores-zero":
        cores = 0
        status["cores"] = "FAIL"
    elif kind == "memory-short":
        avail = round(mem_gb * float(rng.uniform(1.0, 1.45)), 1)
        status["memory"] = "FAIL"
    elif kind == "memory-edge":
        avail = 1.5 * mem_gb
    elif kind == "memory-cap":
        mem_gb = float(rng.choice([20.0, 24.0, 32.0]))
        status["memory"] = "FAIL"
    return {"kind": kind, "folder": folder, "picks": picks, "status": status, "counts": expected,
            "kwargs": {"cores": cores, "mem_gb": mem_gb, "mem_available_gb": avail, "min_stations": min_st,
                       "min_polarities": min_pol, "min_weight": min_w, "min_prob": min_p}}


def _tree(folder: Path) -> List[Tuple[str, int]]:
    return sorted((p.relative_to(folder).as_posix(), p.stat().st_size) for p in folder.rglob("*"))


def _t1_judge(case: dict, got: Any, err: Optional[BaseException]) -> Optional[str]:
    if err is not None or not isinstance(got, tuple) or len(got) != 2:
        return "format"
    report, counts = got
    statuses = _status_list(report)
    if statuses is None or not _counts_ok(counts):
        return "format"
    want = [case["status"][c] for c in CHECKS]
    if not _same_counts(counts, case["counts"], "stations"):
        return "stations"
    if not _same_counts(counts, case["counts"], "polarities"):
        return "polarity"
    for name, have, need in zip(CHECKS, statuses, want):
        if have != need:
            if name == "polarity" and "SKIP" in (have, need):
                return "skip"
            return _CHECK_CATEGORY[name]
    return None


def _t1_run(func: Any, case: dict) -> Optional[str]:
    picks = case["picks"]
    before_picks = picks.copy() if picks is not None else None
    before_tree = _tree(case["folder"])
    got, err = _call(func, case["folder"], picks, **case["kwargs"])
    if err is None and (_tree(case["folder"]) != before_tree or
                        (picks is not None and not picks.equals(before_picks))):
        return "changed-input"
    return _t1_judge(case, got, err)


def check_T1(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    rng = ctx.rng
    oks: List[bool] = []
    cats: List[str] = []
    example = None
    with tempfile.TemporaryDirectory(prefix="sgtl-m60-t1-") as tmp:
        root = Path(tmp)
        kinds = list(T1_KINDS) + list(rng.choice(T1_KINDS, size=max(0, int(crit.get("trials", 20)) - len(T1_KINDS))))
        for kind in kinds:
            case = _t1_case(rng, root, str(kind), crit)
            cat = _t1_run(target, case)
            oks.append(cat is None)
            if cat:
                cats.append(cat)
                if example is None:
                    example = {"inputs": {"case": case["kind"], "folders": sorted(case["counts"]),
                                          **{k: v for k, v in case["kwargs"].items() if k in ("cores", "mem_gb",
                                                                                               "mem_available_gb")}},
                               "got": f"category {cat}",
                               "error": "expected statuses " + ", ".join(f"{c}={case['status'][c]}" for c in CHECKS)}
    category = _first(cats, T1_PRIORITY)
    return outcome_from_cases(np.array(oks), category=category, example=example)


# ------------------------------------------------------------------------------------------- M60-T2
T2_KEYS = {"preflight", "read_picks", "folder", "slug", "run_dir", "settings", "data_check", "picks_sha256",
           "picks_check"}
T2_FUNC_PRIORITY = ("format", "changed-input", "read-rows", "read-types", "fingerprint-rule")
T2_BLOCKING = ("catalog", "time_zone", "events", "stations", "cores")
T2_SETTINGS = ("cores", "mem_gb", "mech_mem_gb", "min_stations", "min_polarities", "min_weight", "min_prob")


def _t2_pick_files(rng: np.random.Generator, root: Path) -> Tuple[Any, str, int]:
    """Made-up pick files (some events with no picks file, one empty file); the expected table and fingerprint."""
    import pandas as pd

    root.mkdir(parents=True, exist_ok=True)
    frames = []
    n_files = int(rng.integers(2, 6))
    base = _dt.datetime(2017, 1, 1) + _dt.timedelta(seconds=int(rng.integers(0, 2 * 10 ** 8)))
    for k in range(n_files):
        event = _id(base + _dt.timedelta(minutes=int(37 * k + rng.integers(1, 30))))
        n = 0 if k == 1 else int(rng.integers(3, 9))
        rows = []
        for j in range(n):
            phase = "P" if j % 2 == 0 else "S"
            rows.append({"Event_ID": int(event), "Network": "XA", "Station": f"QZ{j // 2}", "Phase": phase,
                         "Time": f"{event[:4]}-{event[4:6]}-{event[6:8]}T00:00:{10 + j:02d}.000000Z",
                         "Probability": round(float(rng.uniform(0.3, 1.0)), 3),
                         "Polarity": round(float(rng.uniform(-1, 1)), 3) if phase == "P" else float("nan"),
                         "Amplitude": float(rng.integers(10, 1000))})
        df = pd.DataFrame(rows, columns=["Event_ID", "Network", "Station", "Phase", "Time", "Probability",
                                         "Polarity", "Amplitude"])
        df.to_csv(root / f"{event}_picks.csv", index=False)
        frames.append(df)
    (root / "notes.txt").write_text("not a pick file\n", encoding="utf-8")
    table = pd.concat([f for f in frames if len(f)], ignore_index=True)
    return table, str(_picks_fingerprint(root)), len(table)


def _t2_judge_read(expected: Any, fingerprint: str, got: Any, err: Optional[BaseException]) -> Optional[str]:
    if err is not None or not isinstance(got, tuple) or len(got) != 2 or not _frame(got[0]):
        return "format"
    table, fp = got
    need = ["Event_ID", "Network", "Station", "Phase", "Time", "Probability", "Polarity", "Amplitude"]
    if list(table.columns[:len(need)]) != need or len(table) != len(expected):
        return "read-rows"
    try:
        if [str(v) for v in table["Event_ID"]] != [str(v) for v in expected["Event_ID"]]:
            return "read-rows"
        if not all(isinstance(v, str) for v in table["Event_ID"]):
            return "read-types"
        ok_num = np.allclose(table["Probability"].to_numpy(float), expected["Probability"].to_numpy(float)) and \
            np.allclose(table["Polarity"].to_numpy(float), expected["Polarity"].to_numpy(float), equal_nan=True)
    except (TypeError, ValueError, KeyError):
        return "read-types"
    if not ok_num or [str(v) for v in table["Station"]] != [str(v) for v in expected["Station"]]:
        return "read-rows"
    if not isinstance(fp, str) or fp.lower() != fingerprint:
        return "fingerprint-rule"
    return None


def _t2_function_cases(target: dict, rng: np.random.Generator, n: int) -> Tuple[List[bool], List[str], Any]:
    oks: List[bool] = []
    cats: List[str] = []
    example = None
    with tempfile.TemporaryDirectory(prefix="sgtl-m60-t2-") as tmp:
        for k in range(n):
            folder = Path(tmp) / f"picks{k}"
            expected, fp, n_rows = _t2_pick_files(rng, folder)
            before = _tree(folder)
            got, err = _call(target["read_picks"], folder)
            cat = _t2_judge_read(expected, fp, got, err)
            if cat is None and _tree(folder) != before:
                cat = "changed-input"
            oks.append(cat is None)
            if cat:
                cats.append(cat)
                if example is None:
                    example = {"inputs": {"pick files": len(list(folder.glob("*_picks.csv")))},
                               "got": (type(err).__name__ if err is not None else
                                       (f"{len(got[0])} rows" if isinstance(got, tuple) and got and _frame(got[0])
                                        else repr(got)[:80])),
                               "error": f"expected {n_rows} rows"}
        root = Path(tmp) / "pf"
        root.mkdir()
        for kind in ("ok", "kst-folders", "few-stations", "weak-polarities")[:max(1, int(n))]:
            case = _t1_case(rng, root, kind, {})
            if _t1_run(target["preflight"], case) is not None:
                oks.append(False)
                cats.append("function-changed")
                break
    return oks, cats, example


def _same_check(a: Any, b: Any, skip: Sequence[str] = ()) -> bool:
    """Two (report, counts) tuples agree in every status (rows in ``skip`` left out) and every count."""
    if not (isinstance(a, tuple) and isinstance(b, tuple) and len(a) == len(b) == 2):
        return False
    sa, sb = _status_list(a[0]), _status_list(b[0])
    if sa is None or sb is None or not _counts_ok(a[1]) or not _counts_ok(b[1]):
        return False
    if [s for c, s in zip(CHECKS, sa) if c not in skip] != [s for c, s in zip(CHECKS, sb) if c not in skip]:
        return False
    try:
        if [str(i) for i in a[1].index] != [str(i) for i in b[1].index]:
            return False
        return all(np.array_equal(np.asarray(a[1][c], dtype=float), np.asarray(b[1][c], dtype=float), equal_nan=True)
                   for c in ("stations", "polarities"))
    except (TypeError, ValueError):
        return False


def _t2_artifacts(target: dict, ctx: Any) -> Tuple[int, Optional[str]]:
    passed = 0
    settings = target["settings"]
    if not isinstance(settings, dict) or set(settings) != set(T2_SETTINGS) or \
            not all(_real(settings[k]) for k in T2_SETTINGS):
        return passed, "format"
    limits = {k: (int(settings[k]) if k in ("min_stations", "min_polarities") else float(settings[k]))
              for k in ("min_stations", "min_polarities", "min_weight", "min_prob")}
    if not isinstance(target["folder"], (str, os.PathLike)) or not isinstance(target["run_dir"], (str, os.PathLike)):
        return passed, "format"
    folder = Path(target["folder"]).expanduser()
    if not (folder / "event_catalog" / "event_catalog.csv").is_file() or \
            not any(p.is_dir() for p in (folder / "stp_download" / "SAC").glob("*")):
        return passed, "folder"
    passed += 1
    big = 1.0e6     # the memory row is not compared: free memory changes from minute to minute
    again, err = _call(target["preflight"], folder, cores=int(settings["cores"]), mem_gb=float(settings["mem_gb"]),
                       mem_available_gb=big, **limits)
    if err is not None or not _same_check(again, target["data_check"], skip=("memory",)):
        return passed, "data-check"
    statuses = dict(zip(CHECKS, _status_list(target["data_check"][0]) or []))
    if any(statuses.get(c) != "PASS" for c in T2_BLOCKING):
        return passed, "data-not-ready"
    passed += 1
    pick_dir = Path(target["run_dir"]).expanduser() / "picks"
    records = _logged(ctx, str(target["slug"])) if isinstance(target["slug"], str) else []
    pick_writes = [str(sha) for rec in records for key, sha in (rec.get("products") or {}).items()
                   if str(key).startswith("picks/*.csv")]
    actual = _picks_fingerprint(pick_dir) if pick_dir.is_dir() else None
    if actual is None or not pick_writes or str(target["picks_sha256"]).lower() != actual or \
            pick_writes[-1] != actual:
        return passed, "picks-fingerprint"
    passed += 1
    got, err = _call(target["read_picks"], pick_dir)
    if err is not None or not isinstance(got, tuple) or len(got) != 2:
        return passed, "picks-check"
    again, err = _call(target["preflight"], folder, got[0], cores=1, mem_gb=float(settings["mech_mem_gb"]),
                       mem_available_gb=big, **limits)
    if err is not None or not _same_check(again, target["picks_check"], skip=("memory",)):
        return passed, "picks-check"
    passed += 1
    covered = set()
    for rec in records:
        if rec.get("command") == "pq run" and rec.get("stage_from") in STAGES and rec.get("through") in STAGES:
            i, j = STAGES.index(rec["stage_from"]), STAGES.index(rec["through"])
            covered.update(STAGES[i:j + 1])
    if not set(STAGES) <= covered:
        return passed, "chain-missing"
    passed += 1
    return passed, None


def check_T2(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    if not isinstance(target, dict) or set(target) != T2_KEYS or not callable(target.get("preflight")) or \
            not callable(target.get("read_picks")):
        return Outcome(passed=False, n_cases=1, n_failed=1, category="format", message="", details={})
    guarded = _guard(target, ("preflight", "read_picks"), ctx)
    if guarded is not None:
        return guarded
    oks, cats, example = _t2_function_cases(target, ctx.rng, int(crit.get("retest", 4)))
    category = _first(cats, T2_FUNC_PRIORITY + ("function-changed",))
    if category is not None:
        return outcome_from_cases(np.array(oks), category=category, example=example)
    passed, cat = _t2_artifacts(target, ctx)
    steps = 5
    ok = np.array(oks + [True] * passed + [False] * (steps - passed if cat else 0), dtype=bool)
    note = ("The check ran your preflight again on your folder and on your pick files, recomputed the combined "
            "fingerprint of the pick files, looked it up in work/.sgtl/runs.jsonl and searched the log for every stage; "
            "it never prints a count of the real data.")
    return outcome_from_cases(ok, category=cat, real_data=True, note=note)


# ------------------------------------------------------------------------------------------- tool files (T3, T4)
SUM_HEADER = ("   DATE     TIME, SEC ,   LAT  ,   LON   , DEPTH,PREF,MAG,NM,NUM,GAP, DMIN, RMS ,  ERH,  ERZ,QASR,"
              "    ID-NUM,LOC,DUR,MAG1,AMP,MAG1,EXT,MAG ,")
# the columns of a made-up mechanisms.csv (sorted by name: a reader must find columns by name, not by place)
MECH_COLUMNS = tuple(sorted("""aux_plane_uncertainty azimuthal_gap cuspid dip event_id fault_plane_uncertainty horz_uncert_km magnitude
                                mult_solution_flag num_p_pol num_sp_ratios origin_depth_km origin_lat origin_lon polarity_misfit prob_mech
                                quality rake sp_misfit sta_distribution_ratio strike takeoff_gap time vert_uncert_km""".split()))


def _sum_line(ev: dict) -> str:
    """One line of a made-up HYPOINVERSE summary file in the comma layout that PocketQuake writes."""
    t = ev["origin"]
    sec = t.second + t.microsecond / 1e6
    return (f"{t:%Y/%m/%d %H:%M},{sec:5.2f},{ev['lat']:8.4f},{ev['lon']:9.4f},{ev['depth']:6.2f},     ,  ,  ,"
            f"{ev['num']:3d},{ev['gap']:3d},{ev['dmin']:5.1f},{ev['rms']:5.2f},{ev['erh']:5.1f},{ev['erz']:5.1f},"
            f"{ev['qual']:<4s},{ev['id']:10d},   ,     ,  ,     ,  ,     ,  ")


def _write_sum(path: Path, events: Sequence[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SUM_HEADER + "\n" + "".join(_sum_line(e) + "\n" for e in events), encoding="utf-8")


def _made_up_origin(rng: np.random.Generator) -> _dt.datetime:
    t = _dt.datetime(2014, 1, 1) + _dt.timedelta(seconds=int(rng.integers(0, 3 * 10 ** 8)))
    return t.replace(microsecond=int(rng.integers(0, 100)) * 10000)


def _made_up_events(rng: np.random.Generator, n: int) -> List[dict]:
    lat0, lon0 = float(rng.uniform(34.5, 37.5)), float(rng.uniform(126.5, 129.3))
    first = 300000 + int(rng.integers(0, 1000))
    out = []
    for k in range(n):
        out.append({"id": first + k, "origin": _made_up_origin(rng),
                    "lat": round(lat0 + float(rng.normal(0, 0.01)), 4), "lon": round(lon0 + float(rng.normal(0, 0.01)), 4),
                    "depth": round(float(rng.uniform(2, 25)), 2), "num": int(rng.integers(10, 150)),
                    "gap": int(rng.integers(20, 200)), "dmin": round(float(rng.uniform(1, 30)), 1),
                    "rms": round(float(rng.uniform(0.05, 0.4)), 2), "erh": round(float(rng.uniform(0.1, 3)), 1),
                    "erz": round(float(rng.uniform(0.2, 5)), 1), "qual": str(rng.choice(list("ABCD")))})
    return out


# ------------------------------------------------------------------------------------------- M60-T3
T3_KEYS = {"results_table", "slug", "copies", "sha256", "table"}
T3_FILES = {"sum": "hypoinverse.sum", "reloc": "hypoDD.reloc", "boot": "bootstrap_errors.csv",
            "mech": "mechanisms.csv"}
T3_LOG_KEYS = {"sum": r"1\.HypoInv/kim1983/[^/]+\.sum", "reloc": r"2\.HypoDD/02\.dt\.cc/hypoDD\.reloc",
               "boot": r"2\.HypoDD/02\.dt\.cc/bootstrap_errors\.csv", "mech": r"3\.FocalMech/kim1983/mechanisms\.csv"}
T3_COLUMNS = ("id", "hyp_depth_km", "hyp_erh_km", "hyp_erz_km", "hyp_rms_s", "lat", "lon", "depth_km", "dz_km",
              "err_h95_km", "err_z95_km", "strike", "dip", "rake", "quality", "fp_uncert_deg", "n_pol", "n_solutions")
T3_PRIORITY = ("format", "changed-input", "rows", "sum-values", "reloc-values", "dz-sign", "error-units",
               "error-rule", "mech-first-row", "mech-missing", "solutions", "wrong-values")


def _t3_case(rng: np.random.Generator, folder: Path) -> Tuple[Dict[str, Path], Dict[int, dict]]:
    """Made-up tool files of one cluster and the expected row of every event (by construction)."""
    folder.mkdir(parents=True, exist_ok=True)
    events = _made_up_events(rng, int(rng.integers(4, 9)))
    ids = [e["id"] for e in events]
    no_reloc = set(rng.choice(ids, size=int(rng.integers(0, 2)), replace=False).tolist())
    no_boot = set(rng.choice([i for i in ids if i not in no_reloc], size=1, replace=False).tolist()) \
        if rng.random() < 0.5 else set()
    no_mech = set(rng.choice(ids, size=int(rng.integers(1, 3)), replace=False).tolist())
    two_mech = set(rng.choice([i for i in ids if i not in no_mech], size=1, replace=False).tolist())
    _write_sum(folder / T3_FILES["sum"], events)
    expected: Dict[int, dict] = {}
    reloc_lines, boot_lines, mech_rows = [], [], []
    for e in events:
        row = {"id": e["id"], "hyp_depth_km": e["depth"], "hyp_erh_km": e["erh"], "hyp_erz_km": e["erz"],
               "hyp_rms_s": e["rms"], "lat": np.nan, "lon": np.nan, "depth_km": np.nan, "dz_km": np.nan,
               "err_h95_km": np.nan, "err_z95_km": np.nan, "strike": np.nan, "dip": np.nan, "rake": np.nan,
               "quality": None, "fp_uncert_deg": np.nan, "n_pol": np.nan, "n_solutions": 0}
        if e["id"] not in no_reloc:
            lat, lon = round(e["lat"] + float(rng.normal(0, 0.003)), 6), round(e["lon"] + float(rng.normal(0, 0.003)), 6)
            dep = round(e["depth"] + float(rng.normal(0, 1.0)), 3)
            t = e["origin"]
            reloc_lines.append(f"{e['id']:9d} {lat:10.6f} {lon:11.6f} {dep:9.3f} {rng.normal(0, 300):8.1f} "
                               f"{rng.normal(0, 300):8.1f} {rng.normal(0, 300):8.1f} {rng.uniform(1, 20):6.1f} "
                               f"{rng.uniform(1, 20):6.1f} {rng.uniform(1, 40):6.1f} {t.year:4d} {t.month:2d} "
                               f"{t.day:2d} {t.hour:2d} {t.minute:2d} {t.second + t.microsecond / 1e6:6.2f} "
                               f"{0.0:5.1f} {0:5d} {0:5d} {int(rng.integers(20, 300)):5d} {int(rng.integers(20, 300)):5d}"
                               f" {-9.0:6.1f} {rng.uniform(0.005, 0.05):6.3f} {1:3d}")
            row.update(lat=lat, lon=lon, depth_km=dep, dz_km=dep - e["depth"])
            if e["id"] not in no_boot:
                ex, ey, ez = (round(float(rng.uniform(0.5, 40)), 4) for _ in range(3))
                boot_lines.append(f"{e['id']},200,{rng.normal(0, 50):.1f},{rng.normal(0, 50):.1f},"
                                  f"{rng.normal(0, 50):.1f},{ex},{ey},{ez}")
                row.update(err_h95_km=max(ex, ey) / 1000.0, err_z95_km=ez / 1000.0)
        if e["id"] not in no_mech:
            n_sol = 2 if e["id"] in two_mech else 1
            for j in range(n_sol):
                s, d, r = round(float(rng.uniform(0, 360)), 1), round(float(rng.uniform(10, 90)), 1), \
                    round(float(rng.uniform(-180, 180)), 1)
                q = str(rng.choice(list("ABCD")))
                fp = round(float(rng.uniform(5, 40)), 1)
                npol = int(rng.integers(8, 80))
                mech_rows.append({"event_id": e["origin"].strftime("%Y%m%d%H%M%S"), "cuspid": e["id"], "strike": s,
                                  "dip": d, "rake": r, "quality": q, "fault_plane_uncertainty": fp,
                                  "aux_plane_uncertainty": fp + 1.0, "num_p_pol": npol, "num_sp_ratios": npol - 2,
                                  "azimuthal_gap": 50.0, "takeoff_gap": 30.0, "polarity_misfit": 5.0,
                                  "prob_mech": 90.0, "sta_distribution_ratio": 0.5, "sp_misfit": 0.2,
                                  "mult_solution_flag": n_sol > 1, "time": e["origin"].isoformat(), "magnitude": 1.5,
                                  "origin_lat": e["lat"], "origin_lon": e["lon"], "origin_depth_km": e["depth"],
                                  "horz_uncert_km": e["erh"], "vert_uncert_km": e["erz"]})
                if j == 0:
                    row.update(strike=s, dip=d, rake=r, quality=q, fp_uncert_deg=fp, n_pol=npol)
            row["n_solutions"] = n_sol
        expected[e["id"]] = row
    order = rng.permutation(len(reloc_lines))
    (folder / T3_FILES["reloc"]).write_text("".join(reloc_lines[i] + "\n" for i in order), encoding="utf-8")
    (folder / T3_FILES["boot"]).write_text("# bootstrap_errors n=200 seed=0 branch=dtcc cluster=madeup\n"
                                           "id,n_boot,x_med,y_med,z_med,ex95,ey95,ez95\n"
                                           + "".join(b + "\n" for b in boot_lines), encoding="utf-8")
    import pandas as pd

    pd.DataFrame(mech_rows, columns=list(MECH_COLUMNS)).to_csv(folder / T3_FILES["mech"], index=False)
    return {k: folder / v for k, v in T3_FILES.items()}, expected


def _t3_judge(expected: Dict[int, dict], got: Any, err: Optional[BaseException]) -> Optional[str]:
    if err is not None or not _frame(got) or not set(T3_COLUMNS) <= set(got.columns):
        return "format"
    try:
        ids = [int(v) for v in got["id"]]
    except (TypeError, ValueError):
        return "format"
    if ids != sorted(expected):
        return "rows"
    rows = {int(r["id"]): r for r in got.to_dict("records")}

    def close(col: str) -> bool:
        a = np.array([float(rows[i][col]) if rows[i][col] is not None else np.nan for i in ids])
        b = np.array([float(expected[i][col]) for i in ids])
        return bool(np.all((np.isnan(a) & np.isnan(b)) | (np.abs(a - b) <= 1e-6 + 1e-9 * np.abs(b))))

    try:
        if not all(close(c) for c in ("hyp_depth_km", "hyp_erh_km", "hyp_erz_km", "hyp_rms_s")):
            return "sum-values"
        if not all(close(c) for c in ("lat", "lon", "depth_km")):
            return "reloc-values"
        if not close("dz_km"):
            flipped = all(abs(float(rows[i]["dz_km"]) + float(expected[i]["dz_km"])) < 1e-6
                          for i in ids if not np.isnan(expected[i]["dz_km"]))
            return "dz-sign" if flipped else "wrong-values"
        if not (close("err_h95_km") and close("err_z95_km")):
            ez = [i for i in ids if not np.isnan(expected[i]["err_z95_km"])]
            if ez and all(abs(float(rows[i]["err_z95_km"]) - 1000.0 * float(expected[i]["err_z95_km"])) < 1e-3
                          for i in ez):
                return "error-units"
            return "error-rule" if close("err_z95_km") else "wrong-values"
        mech_ids = [i for i in ids if expected[i]["n_solutions"] > 0]
        none_ids = [i for i in ids if expected[i]["n_solutions"] == 0]
        if not all(close(c) for c in ("n_solutions",)):
            return "solutions"
        for i in none_ids:
            if not _missing(rows[i]["quality"]) or \
                    any(not math.isnan(float(rows[i][c])) for c in ("strike", "dip", "rake", "n_pol")):
                return "mech-missing"
        for i in mech_ids:
            if str(rows[i]["quality"]) != expected[i]["quality"] or \
                    any(abs(float(rows[i][c]) - float(expected[i][c])) > 1e-6
                        for c in ("strike", "dip", "rake", "fp_uncert_deg", "n_pol")):
                return "mech-first-row"
    except (TypeError, ValueError, KeyError):
        return "wrong-values"
    return None


def _t3_function_cases(func: Any, rng: np.random.Generator, n: int) -> Tuple[List[bool], List[str], Any]:
    oks: List[bool] = []
    cats: List[str] = []
    example = None
    with tempfile.TemporaryDirectory(prefix="sgtl-m60-t3-") as tmp:
        for k in range(n):
            files, expected = _t3_case(rng, Path(tmp) / f"case{k}")
            before = _tree(Path(tmp) / f"case{k}")
            got, err = _call(func, files["sum"], files["reloc"], files["boot"], files["mech"])
            cat = _t3_judge(expected, got, err)
            if cat is None and _tree(Path(tmp) / f"case{k}") != before:
                cat = "changed-input"
            oks.append(cat is None)
            if cat:
                cats.append(cat)
                if example is None:
                    example = {"inputs": {"events in the summary file": len(expected),
                                          "relocated": sum(1 for r in expected.values() if not np.isnan(r["lat"])),
                                          "with a mechanism": sum(1 for r in expected.values() if r["n_solutions"])},
                               "got": (type(err).__name__ if err is not None else
                                       (f"{len(got)} rows" if _frame(got) else repr(got)[:80])),
                               "error": f"category {cat}"}
    return oks, cats, example


def _same_table(a: Any, b: Any) -> bool:
    if not (_frame(a) and _frame(b)) or list(a.columns) != list(b.columns) or len(a) != len(b):
        return False
    for col in a.columns:
        x, y = a[col].tolist(), b[col].tolist()
        for u, v in zip(x, y):
            if _real(u) or _real(v):
                if not (_real(u) and _real(v) and abs(float(u) - float(v)) <= 1e-9 * max(1.0, abs(float(v)))):
                    return False
            elif str(u) != str(v):
                return False
    return True


def _t3_artifacts(target: dict, ctx: Any) -> Tuple[int, Optional[str]]:
    passed = 0
    if not isinstance(target["copies"], (str, os.PathLike)) or not isinstance(target["sha256"], dict) or \
            set(target["sha256"]) != set(T3_FILES) or not isinstance(target["slug"], str):
        return passed, "format"
    copies = Path(target["copies"]).expanduser()
    files = {k: copies / v for k, v in T3_FILES.items()}
    if not all(p.is_file() for p in files.values()):
        return passed, "copies"
    passed += 1
    actual = {k: _sha256(p) for k, p in files.items()}
    if any(str(target["sha256"][k]).lower() != actual[k] for k in files):
        return passed, "fingerprint-claim"
    passed += 1
    records = _logged(ctx, target["slug"])
    if not records:
        return passed, "runs-missing"
    for k, pattern in T3_LOG_KEYS.items():
        if actual[k] not in _writes(records, pattern):
            return passed, "not-run-product"
    passed += 1
    got, err = _call(target["results_table"], files["sum"], files["reloc"], files["boot"], files["mech"])
    if err is not None or not _same_table(got, target["table"]):
        return passed, "table"
    passed += 1
    return passed, None


def check_T3(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    if not isinstance(target, dict) or set(target) != T3_KEYS or not callable(target.get("results_table")):
        return Outcome(passed=False, n_cases=1, n_failed=1, category="format", message="", details={})
    guarded = _guard(target, ("results_table",), ctx)
    if guarded is not None:
        return guarded
    oks, cats, example = _t3_function_cases(target["results_table"], ctx.rng, int(crit.get("trials", 10)))
    category = _first(cats, T3_PRIORITY)
    if category is not None:
        return outcome_from_cases(np.array(oks), category=category, example=example)
    passed, cat = _t3_artifacts(target, ctx)
    steps = 4
    ok = np.array(oks + [True] * passed + [False] * (steps - passed if cat else 0), dtype=bool)
    note = ("The check recomputed the SHA-256 of your four copied files, looked them up in work/.sgtl/runs.jsonl and "
            "ran your function again on the copies; it never prints a value of the real data.")
    return outcome_from_cases(ok, category=cat, real_data=True, note=note)


# ------------------------------------------------------------------------------------------- M60-T4
T4_KEYS = {"location_shift", "slug", "first", "rerun", "changed", "sum_sha256", "phs_sha256", "rerun_shift",
           "changed_shift"}
T4_RUNS = ("first", "rerun", "changed")
T4_COLUMNS = ("id", "dh_km", "dz_km", "dt_s")
T4_PRIORITY = ("format", "changed-input", "rows", "distance", "dz-sign", "time", "wrong-values")
WEIGHT_COLUMNS = (16, 49)       # 0-based columns of the P and S weight codes in a phase line of the .phs file


def _geod() -> Any:
    from pyproj import Geod
    return Geod(a=6371000.0, b=6371000.0)


def _t4_case(rng: np.random.Generator, folder: Path) -> Tuple[Path, Path, Dict[int, Tuple[float, float, float]]]:
    """Two made-up summary files; the second moves each event by a known distance, depth and time."""
    folder.mkdir(parents=True, exist_ok=True)
    geod = _geod()
    a = _made_up_events(rng, int(rng.integers(4, 9)))
    b, truth = [], {}
    for k, e in enumerate(a):
        if k == 0 and rng.random() < 0.5:
            continue                                   # an event the second run did not locate
        f = dict(e)
        az, dist = float(rng.uniform(0, 360)), float(rng.uniform(0.0, 3000.0))
        lon2, lat2, _ = geod.fwd(e["lon"], e["lat"], az, dist)
        f["lat"], f["lon"] = round(lat2, 4), round(lon2, 4)
        f["depth"] = round(max(0.0, e["depth"] + float(rng.normal(0, 1.5))), 2)
        if k == 1:                                     # across a minute (and maybe an hour) boundary
            f["origin"] = e["origin"].replace(second=59, microsecond=950000)
            e["origin"] = f["origin"]
            f["origin"] = f["origin"] + _dt.timedelta(seconds=0.12)
        else:
            f["origin"] = e["origin"] + _dt.timedelta(seconds=float(rng.integers(-50, 51)) / 100.0)
        b.append(f)
        dh = geod.inv(e["lon"], e["lat"], f["lon"], f["lat"])[2] / 1000.0
        t0 = e["origin"].replace(microsecond=0) + _dt.timedelta(seconds=round(e["origin"].microsecond / 1e6, 2))
        t1 = f["origin"].replace(microsecond=0) + _dt.timedelta(seconds=round(f["origin"].microsecond / 1e6, 2))
        truth[e["id"]] = (dh, f["depth"] - e["depth"], (t1 - t0).total_seconds())
    extra = _made_up_events(rng, 1)[0]
    extra["id"] = max(x["id"] for x in a) + 7
    b.append(extra)                                    # an event only the second run has
    _write_sum(folder / "a.sum", a)
    _write_sum(folder / "b.sum", list(rng.permutation(np.array(b, dtype=object))))
    return folder / "a.sum", folder / "b.sum", truth


def _t4_judge(truth: Dict[int, Tuple[float, float, float]], got: Any, err: Optional[BaseException],
              tol_km: float) -> Optional[str]:
    if err is not None or not _frame(got) or list(got.columns[:4]) != list(T4_COLUMNS):
        return "format"
    try:
        ids = [int(v) for v in got["id"]]
        if ids != sorted(truth):
            return "rows"
        dh, dz, dts = (got[c].to_numpy(dtype=float) for c in ("dh_km", "dz_km", "dt_s"))
    except (TypeError, ValueError):
        return "format"
    want = np.array([truth[i] for i in ids], dtype=float)
    if not np.all(np.abs(dh - want[:, 0]) <= tol_km):
        return "distance"
    if not np.all(np.abs(dz - want[:, 1]) <= 1e-6):
        return "dz-sign" if np.all(np.abs(dz + want[:, 1]) <= 1e-6) else "wrong-values"
    if not np.all(np.abs(dts - want[:, 2]) <= 1e-6):
        return "time"
    return None


def _t4_function_cases(func: Any, rng: np.random.Generator, n: int, tol_km: float) -> Tuple[List[bool], List[str],
                                                                                           Any]:
    oks: List[bool] = []
    cats: List[str] = []
    example = None
    with tempfile.TemporaryDirectory(prefix="sgtl-m60-t4-") as tmp:
        for k in range(n):
            first, second, truth = _t4_case(rng, Path(tmp) / f"case{k}")
            before = _tree(Path(tmp) / f"case{k}")
            got, err = _call(func, first, second)
            cat = _t4_judge(truth, got, err, tol_km)
            if cat is None and _tree(Path(tmp) / f"case{k}") != before:
                cat = "changed-input"
            oks.append(cat is None)
            if cat:
                cats.append(cat)
                if example is None:
                    i = sorted(truth)[0]
                    example = {"inputs": {"events in both files": len(truth), "first id": i},
                               "got": (type(err).__name__ if err is not None else
                                       (f"{len(got)} rows" if _frame(got) else repr(got)[:80])),
                               "error": (f"expected dh_km {truth[i][0]:.4f}, dz_km {truth[i][1]:.2f}, "
                                         f"dt_s {truth[i][2]:.2f} for id {i}")}
    return oks, cats, example


def _phase_lines(path: Path) -> List[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def _diff_columns(a: List[str], b: List[str]) -> Optional[set]:
    """0-based columns where two equally long lists of lines differ; None when the line counts or lengths differ."""
    if len(a) != len(b):
        return None
    cols: set = set()
    for u, v in zip(a, b):
        if len(u) != len(v):
            return None
        cols.update(i for i, (p, q) in enumerate(zip(u, v)) if p != q)
    return cols


def _t4_artifacts(target: dict, ctx: Any) -> Tuple[int, Optional[str]]:
    passed = 0
    if not all(isinstance(target[n], (str, os.PathLike)) for n in T4_RUNS) or not isinstance(target["slug"], str):
        return passed, "format"
    shas = {k: target[k] for k in ("sum_sha256", "phs_sha256")}
    if any(not isinstance(v, dict) or set(v) != set(T4_RUNS) for v in shas.values()):
        return passed, "format"
    files: Dict[str, Dict[str, Path]] = {}
    for n in T4_RUNS:
        folder = Path(target[n]).expanduser()
        sums, phs = sorted(folder.glob("kim1983/*.sum")), sorted(folder.glob("PHS/*.phs"))
        if len(sums) != 1 or len(phs) != 1:
            return passed, "copies"
        files[n] = {"sum": sums[0], "phs": phs[0]}
    passed += 1
    actual = {n: {"sum": _sha256(files[n]["sum"]), "phs": _sha256(files[n]["phs"])} for n in T4_RUNS}
    for n in T4_RUNS:
        if str(shas["sum_sha256"][n]).lower() != actual[n]["sum"] or \
                str(shas["phs_sha256"][n]).lower() != actual[n]["phs"]:
            return passed, "fingerprint-claim"
    passed += 1
    records = _logged(ctx, target["slug"])
    if not records:
        return passed, "runs-missing"
    sum_writes = _writes(records, r"1\.HypoInv/kim1983/[^/]+\.sum")
    phs_writes = _writes(records, r"1\.HypoInv/PHS/[^/]+\.phs")
    if any(actual[n]["sum"] not in sum_writes or actual[n]["phs"] not in phs_writes for n in T4_RUNS):
        return passed, "not-run-product"
    if len({Path(target[n]).expanduser().resolve() for n in T4_RUNS}) < 3:
        return passed, "no-rerun"
    if actual["first"]["sum"] == actual["rerun"]["sum"] and sum_writes[actual["first"]["sum"]] < 2:
        return passed, "no-rerun"
    passed += 1
    lines = {n: _phase_lines(files[n]["phs"]) for n in T4_RUNS}
    same = _diff_columns(lines["first"], lines["rerun"])
    changed = _diff_columns(lines["rerun"], lines["changed"])
    if same is None or changed is None or same & set(WEIGHT_COLUMNS) or not changed or \
            not changed <= set(WEIGHT_COLUMNS):
        return passed, "one-change"
    passed += 1
    for key, (a, b) in (("rerun_shift", ("first", "rerun")), ("changed_shift", ("rerun", "changed"))):
        got, err = _call(target["location_shift"], files[a]["sum"], files[b]["sum"])
        if err is not None or not _same_table(got, target[key]):
            return passed, "shift-tables"
    passed += 1
    return passed, None


def check_T4(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    if not isinstance(target, dict) or set(target) != T4_KEYS or not callable(target.get("location_shift")):
        return Outcome(passed=False, n_cases=1, n_failed=1, category="format", message="", details={})
    guarded = _guard(target, ("location_shift",), ctx)
    if guarded is not None:
        return guarded
    oks, cats, example = _t4_function_cases(target["location_shift"], ctx.rng, int(crit.get("trials", 8)),
                                            float(crit.get("tol_km", 1e-5)))
    category = _first(cats, T4_PRIORITY)
    if category is not None:
        return outcome_from_cases(np.array(oks), category=category, example=example)
    passed, cat = _t4_artifacts(target, ctx)
    steps = 5
    ok = np.array(oks + [True] * passed + [False] * (steps - passed if cat else 0), dtype=bool)
    note = ("The check recomputed the SHA-256 of your three copied summary and phase files, looked them up in "
            "work/.sgtl/runs.jsonl, compared the phase files column by column and ran your function again on the "
            "copies; it never prints a value of the real data.")
    return outcome_from_cases(ok, category=cat, real_data=True, note=note)


# ------------------------------------------------------------------------------------------- the library rule
def _guard(target: dict, keys: Sequence[str], ctx: Any) -> Optional[Outcome]:
    """The task's forbidden list for the functions of an answer (the engine screens only a function target)."""
    from .. import astguard

    rules = list((getattr(ctx, "spec", None) or {}).get("forbidden") or [])
    for key in keys:
        rep = astguard.check_function(target[key], rules) if rules else None
        if rep is not None and not rep.ok:
            msg = ("This task asks you to write this step yourself, so the rule is: do not use "
                   f"{', '.join(rep.violations) or 'names built while the code runs'} here (found in {key}).")
            return Outcome(False, 0, 0, "forbidden-import", msg, details={"found": rep.offending})
    return None


# ------------------------------------------------------------------------------------------- M60-T5
T5_KEYS = {"inventory", "sequence", "radii_km", "years", "per_event", "per_year", "files", "plan", "national"}
T5_PRIORITY = ("format", "changed-input", "event-rows", "station-dates", "unknown-start", "start-day", "distance",
               "years", "year-events", "year-min")
T5_PLAN_KEYS = ("dataset", "events", "pending", "stations", "requests", "sessions")


def _t5_case(rng: np.random.Generator) -> Tuple[Any, Any, Tuple[float, ...], List[int], dict]:
    """Made-up events and dated stations; the expected counts by pyproj on a sphere and by the dates set here."""
    import pandas as pd

    geod = _geod()
    radii = tuple(sorted(float(r) for r in rng.choice([8.0, 12.5, 20.0, 35.0, 60.0], size=2, replace=False)))
    lat0, lon0 = float(rng.uniform(34.0, 38.0)), float(rng.uniform(126.0, 129.5))
    first_year = int(rng.integers(2003, 2016))
    n_ev = int(rng.integers(5, 10))
    rows = []
    for k in range(n_ev):
        year = first_year + int(rng.choice([0, 0, 1, 3, 4]))
        t = _dt.datetime(year, int(rng.integers(1, 13)), int(rng.integers(1, 29)), int(rng.integers(0, 24)),
                         int(rng.integers(0, 60)), int(rng.integers(0, 60)))
        if k == 0:
            t = t.replace(month=1, day=1, hour=0, minute=int(rng.integers(1, 59)))     # just after New Year, UTC
        lon, lat, _ = geod.fwd(lon0, lat0, float(rng.uniform(0, 360)), float(rng.uniform(0, 1500)))
        rows.append({"event_id": f"{year}{900000 + k:06d}", "origin_utc": t, "latitude": round(lat, 4),
                     "longitude": round(lon, 4), "depth_km": (np.nan if rng.random() < 0.25
                                                              else round(float(rng.uniform(2, 25)), 1)),
                     "ml": round(float(rng.uniform(0.5, 3.0)), 1)})
    events = pd.DataFrame(rows)
    events["origin_utc"] = pd.to_datetime(events["origin_utc"]).dt.tz_localize("UTC")
    times = sorted(events["origin_utc"].dt.tz_localize(None))
    used: set = set()
    st_rows = []
    for j in range(int(rng.integers(14, 24))):
        r = float(rng.choice(radii))
        dist = max(0.5, r + float(rng.choice([-1.0, 1.0])) * float(rng.uniform(0.15, 0.6))) if j % 3 else \
            float(rng.uniform(0.5, 1.6 * max(radii)))
        lon, lat, _ = geod.fwd(lon0, lat0, float(rng.uniform(0, 360)), dist * 1000.0)
        kind = j % 6
        if kind == 0:
            start = pd.NaT                                              # never dated
        elif kind == 1:
            start = pd.Timestamp(times[int(rng.integers(0, len(times)))].normalize())   # started on an event's day
        elif kind == 2:
            start = pd.Timestamp(times[int(rng.integers(0, len(times)))].normalize()) + pd.Timedelta(days=1)
        else:
            start = pd.Timestamp(_dt.date(first_year - 8, 1, 1)) + pd.Timedelta(days=int(rng.integers(0, 6000)))
        st_rows.append({"network": "XA" if j % 2 else "XB", "station": _made_up_code(rng, used),
                        "latitude": round(lat, 4), "longitude": round(lon, 4), "start_date": start})
    stations = pd.DataFrame(st_rows)
    stations["start_date"] = pd.to_datetime(stations["start_date"])
    years = list(range(first_year - 1, first_year + 6))
    return events, stations, radii, years, {}


def _t5_counts(events: Any, stations: Any, radii: Sequence[float], rule: str) -> Dict[str, List[int]]:
    """Station counts per radius for the events in time order, under the stated rule or a named wrong one."""
    geod = _geod()
    ev = events.sort_values(by=["origin_utc", "event_id"], ignore_index=True)
    began = stations["start_date"]
    out: Dict[str, List[int]] = {f"n_{r:g}km": [] for r in radii}
    for _, e in ev.iterrows():
        t = e["origin_utc"].tz_localize(None)
        n = len(stations)
        dist = np.asarray(geod.inv(np.full(n, e["longitude"]), np.full(n, e["latitude"]),
                                   stations["longitude"].to_numpy(float), stations["latitude"].to_numpy(float))[2])
        if rule == "dates-ignored":
            on = np.ones(n, dtype=bool)
        elif rule == "unknown-counts":
            on = (began.isna() | (began <= t)).to_numpy()
        elif rule == "same-day-out":
            on = (began < t.normalize()).fillna(False).to_numpy(dtype=bool)
        else:
            on = (began <= t).fillna(False).to_numpy(dtype=bool)
        for r in radii:
            out[f"n_{r:g}km"].append(int(np.sum(on & (dist / 1000.0 <= r))))
    return out


def _t5_judge(events: Any, stations: Any, radii: Sequence[float], years: Sequence[int], got: Any,
              err: Optional[BaseException]) -> Optional[str]:
    import pandas as pd

    if err is not None or not isinstance(got, tuple) or len(got) != 2 or not (_frame(got[0]) and _frame(got[1])):
        return "format"
    per_event, per_year = got
    names = [f"n_{r:g}km" for r in radii]
    want_cols = ["event_id", "origin_utc", "year", "latitude", "longitude", "depth_km", "ml"] + names
    if list(per_event.columns) != want_cols or list(per_year.columns) != \
            ["n_events", "n_depth", "ml_max"] + [f"{c}_min" for c in names]:
        return "format"
    ev = events.sort_values(by=["origin_utc", "event_id"], ignore_index=True)
    if [str(v) for v in per_event["event_id"]] != [str(v) for v in ev["event_id"]] or \
            list(per_event.index) != list(range(len(ev))):
        return "event-rows"
    try:
        if [int(v) for v in per_event["year"]] != [int(v) for v in ev["origin_utc"].dt.year]:
            return "event-rows"
        have = {c: [int(v) for v in per_event[c]] for c in names}
    except (TypeError, ValueError):
        return "format"
    right = _t5_counts(events, stations, radii, "stated")
    if have != right:
        for rule, cat in (("dates-ignored", "station-dates"), ("unknown-counts", "unknown-start"),
                          ("same-day-out", "start-day")):
            if have == _t5_counts(events, stations, radii, rule):
                return cat
        return "distance"
    try:
        if [int(y) for y in per_year.index] != sorted(int(y) for y in years):
            return "years"
    except (TypeError, ValueError):
        return "years"
    frame = pd.DataFrame({"year": [int(v) for v in ev["origin_utc"].dt.year], "depth": ev["depth_km"],
                          "ml": ev["ml"], **right})
    for y in per_year.index:
        part = frame[frame["year"] == int(y)]
        row = per_year.loc[y]
        n_ok = _num_equal(row["n_events"], len(part)) and _num_equal(row["n_depth"], int(part["depth"].notna().sum()))
        ml_ok = _num_equal(row["ml_max"], float(part["ml"].max()) if len(part) else None)
        if not (n_ok and ml_ok):
            return "year-events"
        for c in names:
            if not _num_equal(row[f"{c}_min"], int(part[c].min()) if len(part) else None):
                return "year-min"
    return None


def _t5_function_cases(func: Any, rng: np.random.Generator, n: int) -> Tuple[List[bool], List[str], Any]:
    oks: List[bool] = []
    cats: List[str] = []
    example = None
    for _ in range(n):
        events, stations, radii, years, _info = _t5_case(rng)
        before = (events.copy(), stations.copy())
        got, err = _call(func, events, stations, radii_km=radii, years=years)
        cat = _t5_judge(events, stations, radii, years, got, err)
        if cat is None and not (events.equals(before[0]) and stations.equals(before[1])):
            cat = "changed-input"
        oks.append(cat is None)
        if cat:
            cats.append(cat)
            if example is None:
                example = {"inputs": {"events": len(events), "stations": len(stations), "radii_km": list(radii),
                                      "years": f"{years[0]}-{years[-1]}"},
                           "got": (type(err).__name__ if err is not None else f"category {cat}"),
                           "error": "the tables differ from the counts known by construction"}
    return oks, cats, example


def _t5_artifacts(target: dict, ctx: Any) -> Tuple[int, Optional[str]]:
    import pandas as pd
    from .. import data as _data
    from .. import datafetch as _fetch

    passed = 0
    if not isinstance(target["sequence"], str) or not isinstance(target["files"], dict) or \
            set(target["files"]) != {"events", "years"} or not isinstance(target["plan"], dict) or \
            set(target["plan"]) != set(T5_PLAN_KEYS) or not isinstance(target["national"], dict) or \
            set(target["national"]) != {"folder", "within", "undated"}:
        return passed, "format"
    try:
        radii = tuple(float(r) for r in target["radii_km"])
        years = [int(y) for y in target["years"]]
        events = _data.sequence(target["sequence"])
        dated = _data.stations()
    except (TypeError, ValueError, KeyError):
        return passed, "subset"
    if not radii or not years:
        return passed, "format"
    passed += 1
    got, err = _call(target["inventory"], events, dated, radii_km=radii, years=years)
    if err is not None or not isinstance(got, tuple) or len(got) != 2 or \
            not _same_table(got[0].astype({"origin_utc": str}) if _frame(got[0]) else got[0],
                            target["per_event"].astype({"origin_utc": str}) if _frame(target["per_event"]) else None) \
            or not _same_table(got[1].reset_index(), target["per_year"].reset_index() if _frame(target["per_year"])
                               else None):
        return passed, "tables"
    if [str(v) for v in target["per_event"]["event_id"]] != \
            [str(v) for v in events.sort_values(["origin_utc", "event_id"])["event_id"]]:
        return passed, "subset"
    passed += 1
    try:
        saved_e = pd.read_csv(Path(target["files"]["events"]).expanduser(), dtype={"event_id": str})
        saved_y = pd.read_csv(Path(target["files"]["years"]).expanduser())
    except (OSError, ValueError):
        return passed, "files"
    in_project = all(Path(target["files"][k]).expanduser().resolve().parent ==
                     (Path(ctx.repo) / "project" / "inventory").resolve() for k in ("events", "years"))
    names = [c for c in target["per_event"].columns if str(c).startswith("n_")]
    if not in_project or list(saved_e.columns) != [str(c) for c in target["per_event"].columns] or \
            not _same_table(saved_e[["event_id"] + names], target["per_event"][["event_id"] + names].astype(
                {"event_id": str})) or \
            not _same_table(saved_y, target["per_year"].reset_index()):
        return passed, "files"
    passed += 1
    name = target["plan"]["dataset"]
    try:
        ds = _fetch.dataset(str(name))
        plan = _fetch.make_plan(ds)
    except Exception:  # noqa: BLE001 - an unknown dataset name
        return passed, "plan"
    want = {"dataset": str(name), "events": len(ds.events), "pending": len(plan.pending), "stations": plan.n_stations,
            "requests": plan.total_requests, "sessions": len(plan.sessions)}
    if ds.sequence != target["sequence"] or any(str(target["plan"][k]) != str(want[k]) for k in T5_PLAN_KEYS):
        return passed, "plan"
    passed += 1
    folder = Path(str(target["national"]["folder"])).expanduser()
    try:
        inside = folder.resolve().parent.parent == _data.root().resolve() and folder.name == "station_table"
        tables = [pd.read_csv(folder / f"{net}_station.csv", dtype={"Code": str}) for net in ("KS", "KG")]
    except (OSError, ValueError):
        return passed, "national-folder"
    if not inside:
        return passed, "national-folder"
    national = pd.concat(tables, ignore_index=True)
    geod = _geod()
    n = len(national)
    dist = np.asarray(geod.inv(np.full(n, ds.center[1]), np.full(n, ds.center[0]),
                               national["Longitude"].to_numpy(float), national["Latitude"].to_numpy(float))[2])
    near = national[dist / 1000.0 <= ds.radius_km]
    known = set(zip(dated["network"].astype(str), dated["station"].astype(str)))
    lost = sum((str(a), str(b)) not in known for a, b in zip(near["Network"], near["Code"]))
    if not (_num_equal(target["national"]["within"], len(near)) and _num_equal(target["national"]["undated"], lost)):
        return passed, "national"
    passed += 1
    return passed, None


def check_T5(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    if not isinstance(target, dict) or set(target) != T5_KEYS or not callable(target.get("inventory")):
        return Outcome(passed=False, n_cases=1, n_failed=1, category="format", message="", details={})
    guarded = _guard(target, ("inventory",), ctx)
    if guarded is not None:
        return guarded
    oks, cats, example = _t5_function_cases(target["inventory"], ctx.rng, int(crit.get("trials", 10)))
    category = _first(cats, T5_PRIORITY)
    if category is not None:
        return outcome_from_cases(np.array(oks), category=category, example=example)
    passed, cat = _t5_artifacts(target, ctx)
    steps = 5
    ok = np.array(oks + [True] * passed + [False] * (steps - passed if cat else 0), dtype=bool)
    note = ("The check ran your function again on the subset and the dated list, read your two saved files, made the "
            "download plan again and counted the national list itself; it never prints a value of the real data.")
    return outcome_from_cases(ok, category=cat, real_data=True, note=note)


# ------------------------------------------------------------------------------------------- M60-T6
T6_KEYS = {"project_audit", "project", "reference_keys", "criteria_md5", "sha256", "audit"}
T6_ITEMS = ("claims", "numbers", "criteria", "freeze", "plan", "amendments")
T6_FILES = ("claims.csv", "criteria.yaml", "ANALYSIS_PLAN.md", "LABBOOK.md")
T6_KINDS = ("ok", "ok-amended", "missing-column", "few-claims", "repeated-id", "empty-cell", "unknown-source",
            "short-claim", "where-no-place", "x-fill", "number-text", "number-no-unit", "few-numbers",
            "criteria-null", "criteria-no-h2", "criteria-short", "threshold-no-unit", "frozen-text", "md5-stale",
            "md5-not-in-book", "date-differs", "no-signoff", "signoff-late", "placeholder", "book-placeholder",
            "short-answer", "amend-before", "amend-empty", "no-files")
T6_PRIORITY = ("format", "changed-input") + T6_ITEMS
_CLAIM_HEAD = ("claim_id", "source", "where", "topic", "statement", "quantity", "reported_value", "unit", "test",
               "data_needed", "refuted_if")
_CLAIM_WORDY = ("statement", "test", "data_needed", "refuted_if")
_CRIT_WORDY = ("statement", "test", "events", "metric", "decision")
_MD5_LINE = "- MD5 checksum of `criteria.yaml` at the freeze:"
_SIGN_LINE = "- Mentor sign-off:"
_POOL = ("made", "up", "events", "stations", "plane", "depth", "model", "with", "each", "the", "test", "about",
         "rule", "before", "after", "records", "careful", "result", "range", "group", "cluster", "reading")
_NOT_WORDS = ("x", "3", "-", "a", "12", "+", "Q")


def _n_words(text: Any) -> int:
    """Pieces of text between spaces with at least two letters in them."""
    return sum(1 for piece in str(text).split() if sum(ch.isalpha() for ch in piece) >= 2)


def _is_day(text: Any) -> bool:
    try:
        return re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(text)) is not None and bool(_dt.date.fromisoformat(str(text)))
    except ValueError:
        return False


def _questions(lines: Sequence[str]) -> List[Tuple[str, int]]:
    """(question text, words of its answer) for every run of lines that start with '>'."""
    out: List[Tuple[str, int]] = []
    question: Optional[List[str]] = None
    words = 0
    for line in list(lines) + ["#"]:
        if line.startswith(">"):
            if question is not None and words == -1:
                question.append(line[1:].strip())
                continue
            if question is not None:
                out.append((" ".join(" ".join(question).split()), words))
            question, words = [line[1:].strip()], -1
            continue
        if question is not None and words == -1:
            words = 0
        if line.startswith("#"):
            if question is not None:
                out.append((" ".join(" ".join(question).split()), words))
            question = None
            continue
        if question is not None:
            words += _n_words(line)
    return out


def _made_up_words(rng: np.random.Generator, n: int) -> str:
    return " ".join(str(w) for w in rng.choice(_POOL, size=n))


def _short_text(rng: np.random.Generator, n_words: int) -> str:
    """Fewer words than asked for, padded with pieces that are not words (so that it has enough pieces)."""
    pieces = [str(w) for w in rng.choice(_POOL, size=max(0, n_words - 1))]
    pieces += [str(w) for w in rng.choice(_NOT_WORDS, size=3)]
    rng.shuffle(pieces)
    return " ".join(pieces)


def _t6_case(rng: np.random.Generator, root: Path, kind: str, crit: dict) -> Tuple[Path, Dict[str, str], dict]:
    """A made-up project folder with one known problem (or none) and the expected status of every check."""
    import pandas as pd

    folder = root / f"proj{len(list(root.iterdir())):02d}"
    folder.mkdir(parents=True)
    keys = sorted({f"madeup{int(y)}{c}" for y, c in zip(rng.integers(1990, 2030, size=4), "abcd")})
    min_claims, min_numbers = int(crit.get("min_claims", 6)), int(crit.get("min_numbers", 3))
    min_words, min_answer = int(crit.get("min_words", 4)), int(crit.get("min_answer_words", 12))
    status = {item: "PASS" for item in T6_ITEMS}
    n = min_claims + int(rng.integers(0, 4))
    rows = []
    for k in range(n):
        numeric = k < min_numbers + 1
        rows.append({"claim_id": f"K{k + 1}", "source": str(rng.choice(keys)),
                     "where": str(rng.choice([f"Fig. {k + 2}", f"Section {k + 1}.2", f"p. {k + 5}", "Abstract",
                                              f"Table {k + 1}"])),
                     "topic": str(rng.choice(["depth", "rate", "geometry"])),
                     "statement": f"A made-up statement about the made-up events, number {k + 1}.",
                     "quantity": "a made-up quantity" if numeric else "",
                     "reported_value": (f"{float(rng.uniform(0.5, 90)):.1f}" if numeric else ""),
                     "unit": str(rng.choice(["km", "events", "degrees"])) if numeric else "",
                     "test": "a made-up test of the made-up claim " + _made_up_words(rng, int(rng.integers(0, 4))),
                     "data_needed": "made-up records of made-up stations",
                     "refuted_if": "a made-up result outside its made-up range"})
    frame = pd.DataFrame(rows, columns=list(_CLAIM_HEAD))
    pick = int(rng.integers(0, n))
    if kind == "missing-column":
        frame = frame.drop(columns=["refuted_if"])
        status.update(claims="FAIL", numbers="FAIL")
    elif kind == "few-claims":
        frame = frame.iloc[:min_claims - 1]
        status["claims"] = "FAIL"
        if min_claims - 1 < min_numbers:
            status["numbers"] = "FAIL"
    elif kind == "repeated-id":
        frame.loc[pick, "claim_id"] = frame.loc[(pick + 1) % n, "claim_id"]
        status["claims"] = "FAIL"
    elif kind == "empty-cell":
        frame.loc[pick, str(rng.choice(["claim_id", "topic"]))] = "   "
        status["claims"] = "FAIL"
    elif kind == "unknown-source":
        frame.loc[pick, "source"] = "nobody1999"
        status["claims"] = "FAIL"
    elif kind == "short-claim":
        frame.loc[pick, str(rng.choice(list(_CLAIM_WORDY)))] = _short_text(rng, min_words)
        status["claims"] = "FAIL"
    elif kind == "where-no-place":
        frame.loc[pick, "where"] = str(rng.choice(["the paper", "Discussion", "x", "see the text", "Figure"]))
        status["claims"] = "FAIL"
    elif kind == "x-fill":
        for col in ("where", "topic", "statement", "test", "data_needed", "refuted_if"):
            frame[col] = "x"
        frame.loc[frame["quantity"] != "", ["quantity", "unit"]] = "x"
        status.update(claims="FAIL", criteria="FAIL", plan="FAIL")
    elif kind == "number-text":
        frame.loc[0, "reported_value"] = str(rng.choice(["about 11", "10-12", "deep", "nan"]))
        status["numbers"] = "FAIL"
    elif kind == "number-no-unit":
        frame.loc[1, "unit"] = ""
        status["numbers"] = "FAIL"
    elif kind == "few-numbers":
        frame.loc[:, ["quantity", "reported_value", "unit"]] = ""
        frame.loc[0, ["quantity", "reported_value", "unit"]] = ["a made-up quantity", "4", "km"]
        status["numbers"] = "FAIL"
    if kind != "no-files":
        frame.to_csv(folder / "claims.csv", index=False)
    frozen = _dt.date(2031, 1, 1) + _dt.timedelta(days=int(rng.integers(0, 3000)))
    crit_lines = ["project: madeup", "author: A. Made-up", f"frozen: {frozen.isoformat()}", "hypotheses:"]
    short_h, short_f = str(rng.choice(["H1", "H2"])), str(rng.choice(list(_CRIT_WORDY)))
    for h in ("H1", "H2"):
        if kind == "criteria-no-h2" and h == "H2":
            continue
        crit_lines.append(f"  {h}:")
        for field in ("statement", "test", "events", "metric", "threshold", "decision"):
            if field == "threshold":
                unit = str(rng.choice(["km", "degrees", "standard errors"]))
                value = f"{float(rng.uniform(0.5, 80)):.1f} {unit}"
                if kind == "threshold-no-unit" and h == short_h:
                    value = str(rng.choice(["3", "0.5", "12.5", "75"]))
            else:
                value = f"made-up {field} of the made-up {h} " + _made_up_words(rng, int(rng.integers(0, 3)))
                if kind == "criteria-short" and (h, field) == (short_h, short_f):
                    value = _short_text(rng, min_words)
            if kind == "x-fill":
                value = "x"
            crit_lines.append(f"    {field}: {value}")
    if kind == "criteria-null":
        at = crit_lines.index(f"  {rng.choice(['H1', 'H2'])}:") + 1
        crit_lines.insert(at, "    note: " + str(rng.choice(["null", "''", "~"])))
        status["criteria"] = "FAIL"
    if kind in ("criteria-no-h2", "criteria-short", "threshold-no-unit"):
        status["criteria"] = "FAIL"
    frozen_text = frozen.isoformat()
    if kind == "frozen-text":
        frozen_text = str(rng.choice(["next week", "31.01.2031", "2031/01/31"]))
        crit_lines[2] = f"frozen: {frozen_text}"
        status.update(criteria="FAIL", freeze="FAIL")
    text = "\n".join(crit_lines) + "\n"
    md5 = hashlib.md5(text.encode("utf-8")).hexdigest()
    if kind == "md5-stale":
        text = text.replace("made-up metric of the made-up H1", "made-up metric of the made-up H1, changed later")
        status["freeze"] = "FAIL"
    if kind != "no-files":
        (folder / "criteria.yaml").write_text(text, encoding="utf-8")
    shown_date = frozen_text if kind not in ("date-differs", "frozen-text") else \
        (frozen + _dt.timedelta(days=int(rng.integers(1, 9)))).isoformat()
    if kind == "date-differs":
        status["freeze"] = "FAIL"
    signed = frozen - _dt.timedelta(days=int(rng.integers(0, 20)))
    sign_line = f"{_SIGN_LINE} B. Made-up, {signed.isoformat()}"
    if kind == "signoff-late":
        sign_line = f"{_SIGN_LINE} B. Made-up, {(frozen + _dt.timedelta(days=int(rng.integers(1, 9)))).isoformat()}"
    plan = ["# Analysis plan: a made-up project", "", "- Author: A. Made-up", "- Started: 2030-12-01"]
    if kind == "no-signoff":
        plan += [str(rng.choice([f"{_SIGN_LINE} B. Made-up", f"{_SIGN_LINE} {signed.isoformat()}",
                                 "- Mentor: B. Made-up"]))]
    else:
        plan.append(sign_line)
    if kind in ("no-signoff", "signoff-late"):
        status["freeze"] = "FAIL"
    plan += [f"- Frozen on: {shown_date}", f"{_MD5_LINE} {md5}", "", "A made-up paragraph before any question.", ""]
    n_q = int(rng.integers(2, 6))
    short_q = int(rng.integers(0, n_q))
    for q in range(n_q):
        if q in (0, 2):
            plan += [f"## {q + 1}. A made-up section", ""]
        plan += [f"> - A made-up question number {q + 1}?"]
        if rng.random() < 0.5:
            plan += ["> It goes on over a second line."]
        plan.append("")
        answer = _made_up_words(rng, min_answer + int(rng.integers(0, 8)))
        if kind == "short-answer" and q == short_q:
            answer = str(rng.choice([_short_text(rng, min_answer), "", "x"]))
        if kind == "placeholder" and q == short_q:
            answer += " [write here: a made-up hint]"
        if kind == "x-fill":
            answer = "x"
        if rng.random() < 0.4 and answer and kind != "x-fill":
            half = len(answer.split()) // 2
            answer = " ".join(answer.split()[:half]) + "\n\n- " + " ".join(answer.split()[half:])
        plan += [answer, ""]
    if kind in ("placeholder", "short-answer", "book-placeholder"):
        status["plan"] = "FAIL"
    plan += ["## Amendments", "", "Add one row for every change after the freeze.", "",
             "| date (YYYY-MM-DD) | what changed | why | had you seen results that bear on it? |", "|---|---|---|---|"]
    if kind in ("ok-amended", "amend-before", "amend-empty"):
        for k in range(int(rng.integers(1, 4))):
            day = frozen + _dt.timedelta(days=int(rng.integers(0, 60)) if k else 0)
            plan.append(f"| {day.isoformat()} | a made-up change {k} | a made-up reason | no |")
        if kind == "amend-before":
            plan.append(f"| {(frozen - _dt.timedelta(days=int(rng.integers(1, 30)))).isoformat()} | a change | why | no |")
            status["amendments"] = "FAIL"
        if kind == "amend-empty":
            plan.append(f"| {(frozen + _dt.timedelta(days=3)).isoformat()} | a change |  | no |")
            status["amendments"] = "FAIL"
    if kind == "frozen-text":
        plan.append(f"| {(frozen + _dt.timedelta(days=3)).isoformat()} | a change | why | no |")
        status["amendments"] = "FAIL"
    if kind != "no-files":
        (folder / "ANALYSIS_PLAN.md").write_text("\n".join(plan) + "\n", encoding="utf-8")
        book = f"# Lab book\n\n## 2031-01-01\n\n- froze criteria.yaml" + (f", MD5 {md5}" if kind != "md5-not-in-book"
                                                                         else "") + "\n"
        if kind == "book-placeholder":
            book += "- What surprised me: [write here]\n"
        (folder / "LABBOOK.md").write_text(book, encoding="utf-8")
    if kind == "md5-not-in-book":
        status["freeze"] = "FAIL"
    if kind == "no-files":
        status = {item: "FAIL" for item in T6_ITEMS}
    return folder, status, {"reference_keys": keys, "min_claims": min_claims, "min_numbers": min_numbers,
                            "min_words": min_words, "min_answer_words": min_answer}


def _t6_statuses(report: Any) -> Optional[List[str]]:
    if not _frame(report) or not {"item", "status", "detail"} <= set(report.columns):
        return None
    if [str(c) for c in report["item"]] != list(T6_ITEMS):
        return None
    return [str(s) for s in report["status"]]


def _t6_kwargs(crit: dict) -> dict:
    return {"min_claims": int(crit.get("min_claims", 6)), "min_numbers": int(crit.get("min_numbers", 3)),
            "min_words": int(crit.get("min_words", 4)), "min_answer_words": int(crit.get("min_answer_words", 12))}


def _t6_function_cases(func: Any, rng: np.random.Generator, crit: dict) -> Tuple[List[bool], List[str], Any]:
    oks: List[bool] = []
    cats: List[str] = []
    example = None
    with tempfile.TemporaryDirectory(prefix="sgtl-m60-t6-") as tmp:
        root = Path(tmp)
        n = int(crit.get("trials", len(T6_KINDS)))
        kinds = list(T6_KINDS) + list(rng.choice(T6_KINDS, size=max(0, n - len(T6_KINDS))))
        for kind in kinds:
            folder, status, kwargs = _t6_case(rng, root, str(kind), crit)
            before = _tree(folder)
            got, err = _call(func, folder, kwargs.pop("reference_keys"), **kwargs)
            have = _t6_statuses(got) if err is None else None
            if have is None:
                cat: Optional[str] = "format"
            elif _tree(folder) != before:
                cat = "changed-input"
            else:
                cat = next((item for item, h in zip(T6_ITEMS, have) if h != status[item]), None)
            oks.append(cat is None)
            if cat:
                cats.append(cat)
                if example is None:
                    example = {"inputs": {"case": str(kind), **kwargs},
                               "got": (type(err).__name__ if err is not None else f"category {cat}"),
                               "error": "expected " + ", ".join(f"{i}={status[i]}" for i in T6_ITEMS)}
    return oks, cats, example


def _t6_content(folder: Path, template: Path, crit: dict) -> Optional[Dict[str, str]]:
    """The check's own reading of the content rules of the Contract (and of the template's questions); the first
    rule that the folder breaks, by file and rule name, or None."""
    import pandas as pd
    import yaml

    kw = _t6_kwargs(crit)
    try:
        claims = pd.read_csv(folder / "claims.csv", dtype=str, keep_default_na=False)
    except (OSError, ValueError):
        return {"file": "claims.csv", "rule": "reads as a table"}
    for col in _CLAIM_WORDY:
        if col not in claims or any(_n_words(v) < kw["min_words"] for v in claims[col]):
            return {"file": "claims.csv", "rule": f"words in {col}"}
    if "where" not in claims or any(not re.search(r"\d", str(v)) and "abstract" not in str(v).lower()
                                    for v in claims["where"]):
        return {"file": "claims.csv", "rule": "a place in the paper in where"}
    try:
        data = yaml.safe_load((folder / "criteria.yaml").read_text(encoding="utf-8"))
        hyps = data["hypotheses"]
        frozen = str(data["frozen"])
        entries = [(h, hyps[h]) for h in ("H1", "H2")]
    except (OSError, yaml.YAMLError, TypeError, KeyError):
        return {"file": "criteria.yaml", "rule": "reads as the template's mapping"}
    for h, entry in entries:
        if not isinstance(entry, dict) or any(_n_words(entry.get(f, "")) < kw["min_words"] for f in _CRIT_WORDY):
            return {"file": "criteria.yaml", "rule": f"words in every entry of {h}"}
        pieces = str(entry.get("threshold", "")).split(None, 1)
        try:
            number_ok = len(pieces) == 2 and math.isfinite(float(pieces[0])) and _n_words(pieces[1]) >= 1
        except ValueError:
            number_ok = False
        if not number_ok:
            return {"file": "criteria.yaml", "rule": f"a number and its unit in the threshold of {h}"}
    try:
        plan = (folder / "ANALYSIS_PLAN.md").read_text(encoding="utf-8")
        book = (folder / "LABBOOK.md").read_text(encoding="utf-8")
        wanted = [q for q, _ in _questions(template.read_text(encoding="utf-8").splitlines())]
    except OSError:
        return {"file": "ANALYSIS_PLAN.md", "rule": "the template's questions (docs/templates/project/)"}
    lines = plan.splitlines()
    sign = next((x for x in lines if x.startswith(_SIGN_LINE)), None)
    name, _, day = (sign[len(_SIGN_LINE):].strip().rpartition(",") if sign is not None else ("", "", ""))
    if sign is None or _n_words(name) < 1 or not _is_day(day.strip()) or not _is_day(frozen) or \
            day.strip() > frozen:
        return {"file": "ANALYSIS_PLAN.md", "rule": "the mentor sign-off, dated on or before the freeze"}
    if "[write here" in plan or "[write here" in book:
        return {"file": "ANALYSIS_PLAN.md or LABBOOK.md", "rule": "no placeholder left"}
    found = _questions(lines)
    if any(words < kw["min_answer_words"] for _, words in found):
        return {"file": "ANALYSIS_PLAN.md", "rule": "words in every answer"}
    asked = iter(q for q, _ in found)
    if not wanted or not all(any(q == have for have in asked) for q in wanted):
        return {"file": "ANALYSIS_PLAN.md", "rule": "every question of the template, in its order"}
    return None


def _t6_artifacts(target: dict, ctx: Any, crit: dict) -> Tuple[int, Optional[str], Optional[dict]]:
    import yaml

    passed = 0
    if not isinstance(target["project"], (str, os.PathLike)) or not isinstance(target["sha256"], dict) or \
            set(target["sha256"]) != set(T6_FILES) or not isinstance(target["criteria_md5"], str):
        return passed, "format", None
    folder = Path(target["project"]).expanduser()
    if folder.resolve() != (Path(ctx.repo) / "project").resolve() or \
            not all((folder / name).is_file() for name in T6_FILES):
        return passed, "project-files", None
    passed += 1
    crit_bytes = (folder / "criteria.yaml").read_bytes()
    if target["criteria_md5"].lower() != hashlib.md5(crit_bytes).hexdigest() or \
            any(str(target["sha256"][name]).lower() != _sha256(folder / name) for name in T6_FILES):
        return passed, "fingerprint-claim", None
    passed += 1
    try:
        refs = yaml.safe_load(_paths.course_path("references", "references.yaml", repo=ctx.repo).read_text(encoding="utf-8"))
        keys = sorted(str(e["key"]) for e in refs)
    except (OSError, yaml.YAMLError, TypeError, KeyError):
        keys = []
    try:
        given = sorted(str(k) for k in target["reference_keys"])
    except TypeError:
        given = []
    if not keys or given != keys:
        return passed, "reference-keys", None
    passed += 1
    again, err = _call(target["project_audit"], folder, keys, **_t6_kwargs(crit))
    reported = _t6_statuses(target["audit"])
    if err is not None or _t6_statuses(again) is None or reported is None or _t6_statuses(again) != reported:
        return passed, "audit-again", None
    if any(s != "PASS" for s in reported):
        return passed, "not-ready", None
    passed += 1
    import pandas as pd

    try:
        claims = pd.read_csv(folder / "claims.csv", keep_default_na=False, dtype=str)
        source = str(crit.get("source", "kwak2022"))
        n_source = int((claims["source"].str.strip() == source).sum())
    except (OSError, ValueError, KeyError):
        n_source = 0
    md5 = hashlib.md5(crit_bytes).hexdigest()
    plan = (folder / "ANALYSIS_PLAN.md").read_text(encoding="utf-8")
    if n_source < int(crit.get("min_source", 4)):
        return passed, "claims-source", None
    if not any(line.startswith(_MD5_LINE) and md5 in line for line in plan.splitlines()):
        return passed, "not-ready", None
    passed += 1
    broken = _t6_content(folder, _paths.course_path("templates", "project", "ANALYSIS_PLAN.md", repo=ctx.repo), crit)
    if broken is not None:
        return passed, "content", broken
    passed += 1
    return passed, None, None


def check_T6(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    if not isinstance(target, dict) or set(target) != T6_KEYS or not callable(target.get("project_audit")):
        return Outcome(passed=False, n_cases=1, n_failed=1, category="format", message="", details={})
    guarded = _guard(target, ("project_audit",), ctx)
    if guarded is not None:
        return guarded
    oks, cats, example = _t6_function_cases(target["project_audit"], ctx.rng, crit)
    category = _first(cats, T6_PRIORITY)
    if category is not None:
        return outcome_from_cases(np.array(oks), category=category, example=example)
    passed, cat, broken = _t6_artifacts(target, ctx, crit)
    steps = 6
    ok = np.array(oks + [True] * passed + [False] * (steps - passed if cat else 0), dtype=bool)
    note = ("The check recomputed the checksums of your four project files, ran your audit again on your folder, "
            "counted your claims of the required source and read the content rules of the Contract in your files "
            "itself; it prints none of your text.")
    return outcome_from_cases(ok, category=cat, real_data=True, note=note,
                              example=({"inputs": broken} if broken else None))
