"""Checkers for M32 · HYPOINVERSE through PocketQuake.

Where the truth comes from (DESIGN.md section 1, rule 1):

* M32-T1: construction (made-up run logs whose matching runs and products are known from how they were written),
  then the student's own run log work/.sgtl/runs.jsonl and the files now in the student's cluster: the check computes
  the SHA-256 of every .sum, .arc and .prt file itself, compares the student's fingerprints with them (every file,
  every digest; the .prt files are not logged, so copying the log is not enough) and compares the .sum and .arc ones
  with the fingerprints sgtl logged for the student's last location run.
* M32-T2: construction (made-up archive files written column by column from the Y2000 station archive layout of
  Klein 2002, with fields that touch, combined P and S lines and closing lines), then the student's own archive
  files of both velocity models against HYPOINVERSE's summary files of the same run: the same events, and per event
  the number of readings with weight above 0.1 (the summary's NUM) and the weighted RMS residual
  (RMS^2 = sum (w r)^2 / sum w^2, Klein 2002 appendix 2), within rounding.
* M32-T3: construction (made-up locations with known offsets in time, position and depth, written in two time
  zones); epicentral distances from pyproj.Geod. Then the student's kim1983 summary against the shipped KMA
  catalog: loose properties only (every event finds a partner, offsets inside wide bounds).
* M32-T4: the answer holds the student's line comparison and the report. The comparison is screened by the AST
  guard (the spec's forbidden list; the engine screens only a function target) and run on made-up text files with
  known changed and extra lines; then the report: the two copies of the location folder (their .sum and .arc files
  against the run log), the student's per-file SHA-256 of both copies recomputed from every file (whether the rerun
  is a real second run is judged by the check itself: two copies of one folder, or result files whose bytes only one
  logged run wrote, fail), and the model table against the two summary files of the first copy (events paired by ID
  number, pyproj distances).
* M32-T5: construction (made-up residual tables whose station means and standard deviations are fixed exactly by
  design, plus readings of weight 0, 0.05 and 0.10 that must be left out); then the student's own archive files
  read with the student's own reader of task 2: properties only (no reading HYPOINVERSE left out may reach a
  station term, every row has enough earthquakes, labels follow the rule).

Failure categories are keys of ``checks/specs/M32.yaml``; the engine prints their fixed messages. Real-data values
are never printed.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import Outcome, outcome_from_cases

__all__ = ["check_T1", "check_T2", "check_T3", "check_T4", "check_T5"]

MODELS = ("kim1983", "kim2011")


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


def _is_frame(got: Any, columns: Sequence[str]) -> bool:
    import pandas as pd

    return isinstance(got, pd.DataFrame) and all(c in got.columns for c in columns)


def _hex(rng: np.random.Generator) -> str:
    return "".join("0123456789abcdef"[int(k)] for k in rng.integers(0, 16, 64))


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _run_folder(slug: str) -> Path:
    from .. import pq as _pq

    return _pq.pipeline_dir() / "pipeline" / "runs" / str(slug)


def _log_records(repo: Any) -> List[dict]:
    """Every JSON object of the clean room's run log (lines that do not parse are left out)."""
    log = Path(repo) / "work" / ".sgtl" / "runs.jsonl"
    found: List[dict] = []
    if not log.is_file():
        return found
    for text in log.read_text(encoding="utf-8", errors="replace").split("\n"):
        text = text.strip()
        if not text:
            continue
        try:
            obj = json.loads(text)
        except ValueError:
            continue
        if isinstance(obj, dict):
            found.append(obj)
    return found


def _location_runs(records: List[dict], slug: str) -> List[dict]:
    """Successful 'pq run' records of the cluster whose range of stages covers the location stage."""
    from .. import pq as _pq

    names = list(_pq.STAGES)
    where = names.index("hypoinverse")
    keep = []
    for obj in records:
        if (obj.get("command"), obj.get("cluster"), obj.get("returncode")) != ("pq run", slug, 0):
            continue
        lo, hi = obj.get("stage_from"), obj.get("through")
        if lo in names and hi in names and names.index(lo) <= where <= names.index(hi):
            keep.append(obj)
    return keep


def _summary(path: Path):
    """A HYPOINVERSE comma-separated summary file read with pandas (id, time in UTC, lat, lon, depth, num, rms)."""
    import pandas as pd

    raw = pd.read_csv(path)
    raw.columns = [str(c).strip() for c in raw.columns]
    day = [c for c in raw.columns if c.startswith("DATE")][0]
    stamp = pd.to_datetime(raw[day].astype(str).str.strip() + ":00", format="%Y/%m/%d %H:%M:%S", utc=True)
    table = pd.DataFrame({"id": raw["ID-NUM"].astype(int),
                          "time": stamp + pd.to_timedelta(raw["SEC"].astype(float), unit="s"),
                          "lat": raw["LAT"].astype(float), "lon": raw["LON"].astype(float),
                          "depth": raw["DEPTH"].astype(float), "num": raw["NUM"].astype(int),
                          "rms": raw["RMS"].astype(float)})
    return table


def _geod_km(lat1: Any, lon1: Any, lat2: Any, lon2: Any) -> np.ndarray:
    from pyproj import Geod

    a1, o1, a2, o2 = (np.atleast_1d(np.asarray(v, dtype=float)) for v in (lat1, lon1, lat2, lon2))
    _f, _b, metres = Geod(ellps="WGS84").inv(o1, a1, o2, a2)
    return np.asarray(metres, dtype=float) / 1000.0


# ============================================================================ M32-T1 the run log
T1_KEYS = {"reader", "slug", "fingerprints"}
_HEX = set("0123456789abcdef")
T1_COLUMNS = ("run", "ts", "product", "sha256")
T1_PRIORITY = ("format", "other-commands", "broken-lines", "failed-runs", "other-cluster", "stage-range",
               "numbering", "order", "wrong-values")


def _t1_record(rng: np.random.Generator, kind: str, slug: str, stages: Sequence[str], at: int, clock: int) -> dict:
    """One made-up log record of the given kind; 'at' is the index of the stage under test."""
    n = len(stages)
    if kind in ("match", "match-empty", "failed", "other-cluster"):
        lo = int(rng.integers(0, at + 1))
        hi = int(rng.integers(at, n))
    elif kind == "after":
        lo = int(rng.integers(at + 1, n))
        hi = int(rng.integers(lo, n))
    else:  # "before" (and the bootstrap record, which has no range)
        hi = int(rng.integers(0, at))
        lo = int(rng.integers(0, hi + 1))
    stamp = f"2031-0{1 + clock // 28 % 9}-{1 + clock % 28:02d}T{clock % 24:02d}:{(7 * clock) % 60:02d}:00Z"
    products: Dict[str, str] = {}
    if kind != "match-empty":
        for k in range(int(rng.integers(1, 5))):
            folder = ("1.HypoInv/kim1983", "1.HypoInv/kim2011", "2.HypoDD/01.dt.ct", "station_table")[k % 4]
            products[f"{folder}/Qx{int(rng.integers(10, 99))}_{k}.out"] = _hex(rng)
    rec = {"ts": stamp, "end": stamp, "user": "intern", "command": "pq run", "cluster": slug,
           "stage_from": stages[lo], "through": stages[hi], "picker": "phasenet_plus", "cores": 1,
           "returncode": 0, "seconds": round(float(rng.uniform(1, 300)), 1), "products": products}
    if kind == "failed":
        rec["returncode"] = int(rng.choice([1, 130]))
    if kind == "other-cluster":
        rec["cluster"] = slug + "_b" if rng.random() < 0.5 else "b" + slug
    if kind == "bootstrap":
        rec = {"ts": stamp, "end": stamp, "user": "intern", "command": "pq bootstrap", "cluster": slug,
               "branch": "dtcc", "n": 100, "seed": 0, "cores": 1, "returncode": 0, "seconds": 9.0,
               "products": {"2.HypoDD/02.dt.cc/bootstrap_errors.csv": _hex(rng)}}
    return rec


def _t1_case(rng: np.random.Generator, number: int, stages: Sequence[str]) -> dict:
    """A made-up log and the rows that a correct reader gives for (slug, stage), plus the rows of common slips."""
    slug = "qz_" + "".join(str(rng.choice(list("abcdefgh"))) for _ in range(4))
    at = int(rng.integers(2, len(stages) - 2))
    plan = ["match", "match", "match-empty", "failed", "other-cluster", "after", "before"]
    if number >= 2:
        plan += ["bootstrap", "match"]
    if number >= 4:
        plan += ["broken", "blank", "match"]
    order = rng.permutation(len(plan))
    plan = [plan[i] for i in order]
    if plan[0] == "broken":
        plan = plan[1:] + plan[:1]
    lines, records = [], []
    for clock, kind in enumerate(plan):
        if kind == "blank":
            lines.append("")
            records.append((kind, None))
            continue
        if kind == "broken":
            text = json.dumps(_t1_record(rng, "match", slug, stages, at, clock))
            lines.append(text[: int(rng.integers(10, len(text) - 10))])
            records.append((kind, None))
            continue
        rec = _t1_record(rng, kind, slug, stages, at, clock)
        lines.append(json.dumps(rec))
        records.append((kind, rec))

    def rows(counted: Sequence[str], number_empty: bool = True, test=None) -> List[tuple]:
        out, k = [], 0
        for kind, rec in records:
            if rec is None or kind not in counted:
                continue
            if test is not None and not test(rec):
                continue
            if not rec["products"] and not number_empty:
                continue
            for name, value in rec["products"].items():
                out.append((k, rec["ts"], name, value))
            k += 1
        return out

    ok = ("match", "match-empty")
    stage = stages[at]
    case = {"slug": slug, "stage": stage, "lines": lines, "has_broken": any(k in ("broken", "blank") for k in plan),
            "has_bootstrap": "bootstrap" in plan, "want": rows(ok)}
    case["variants"] = {
        "failed-runs": rows(ok + ("failed",)),
        "other-cluster": rows(ok + ("other-cluster",)),
        "stage-range": [rows(ok + ("after", "before")), rows(ok, test=lambda r: r["stage_from"] == stage),
                        rows(ok, test=lambda r: r["through"] == stage)],
        "numbering": rows(ok, number_empty=False),
    }
    return case


def _t1_rows(got: Any) -> Optional[List[tuple]]:
    if not _is_frame(got, T1_COLUMNS):
        return None
    try:
        return [(int(a), str(b), str(c), str(d)) for a, b, c, d in
                zip(got["run"], got["ts"], got["product"], got["sha256"])]
    except (TypeError, ValueError):
        return None


def _t1_judge(got: Any, case: dict) -> Optional[str]:
    have = _t1_rows(got)
    if have is None:
        return "format"
    want = case["want"]
    if have == want:
        return None
    var = case["variants"]
    if have == var["failed-runs"] and var["failed-runs"] != want:
        return "failed-runs"
    if have == var["other-cluster"] and var["other-cluster"] != want:
        return "other-cluster"
    if any(have == v and v != want for v in var["stage-range"]):
        return "stage-range"
    if have == var["numbering"] and var["numbering"] != want:
        return "numbering"
    if sorted(have) == sorted(want):
        return "order"
    return "wrong-values"


def _t1_real(target: dict, ctx: Any) -> Tuple[int, Optional[str]]:
    """The student's own log and files: returns (number of passed steps, category of the first failure)."""
    from .. import pq as _pq

    slug = target["slug"]
    log = Path(ctx.repo) / "work" / ".sgtl" / "runs.jsonl"
    if not isinstance(slug, str) or not log.is_file():
        return 0, "runs-missing"
    runs = _location_runs(_log_records(ctx.repo), slug)
    if not any(name.endswith(".sum") for obj in runs for name in (obj.get("products") or {})):
        return 0, "runs-missing"
    got, err = _call(target["reader"], str(log), slug, "hypoinverse", tuple(_pq.STAGES))
    if err is not None:
        raise err
    have = _t1_rows(got)
    expect = []
    for k, obj in enumerate(runs):
        expect.extend((k, str(obj.get("ts")), str(name), str(value))
                      for name, value in (obj.get("products") or {}).items())
    if have is None or have != expect:
        return 1, "real-log"
    folder = _run_folder(slug) / "1.HypoInv"
    files = sorted(p for pattern in ("*/*.sum", "*/*.arc") for p in folder.glob(pattern))
    if not files:
        return 2, "runs-missing"
    printed = sorted(folder.glob("*/*.prt"))     # written by the run but not logged: only a hash of the file has them
    now = {f"1.HypoInv/{p.parent.name}/{p.name}": _digest(p) for p in files + printed}
    claim = target["fingerprints"]
    if set(claim) != set(now):
        return 2, "fingerprint-files"
    if any(claim[name].lower() != digest for name, digest in now.items()):
        return 3, "fingerprint-values"
    latest: Dict[str, str] = {}
    for obj in runs:
        latest.update(obj.get("products") or {})
    if any(latest.get(f"1.HypoInv/{p.parent.name}/{p.name}") != now[f"1.HypoInv/{p.parent.name}/{p.name}"]
           for p in files):
        return 4, "files-changed"
    return 5, None


def _t1_report_ok(target: Any) -> bool:
    """The report's shape: the three keys, a callable reader and fingerprints as {path: 64 hex letters}."""
    if not isinstance(target, dict) or set(target) != T1_KEYS or not callable(target.get("reader")):
        return False
    prints = target.get("fingerprints")
    if not isinstance(prints, dict) or not prints:
        return False
    return all(isinstance(k, str) and isinstance(v, str) and len(v) == 64 and set(v.lower()) <= _HEX
               for k, v in prints.items())


def check_T1(target: Any, ctx: Any) -> Outcome:
    from .. import pq as _pq

    crit = dict(ctx.criteria)
    if not _t1_report_ok(target):
        return Outcome(passed=False, n_cases=1, n_failed=1, category="format", message="", details={})
    stages = tuple(_pq.STAGES)
    rng = ctx.rng
    oks, cats, example = [], [], None
    with tempfile.TemporaryDirectory(prefix="sgtl-m32-t1-") as tmp:
        for k in range(max(4, int(crit.get("trials", 8)))):
            case = _t1_case(rng, k, stages)
            path = Path(tmp) / f"log_{k}.jsonl"
            path.write_text("\n".join(case["lines"]) + "\n", encoding="utf-8")
            got, err = _call(target["reader"], str(path), case["slug"], case["stage"], stages)
            if err is not None:
                if case["has_bootstrap"] and isinstance(err, (KeyError, TypeError, ValueError)) and \
                        not case["has_broken"]:
                    cat = "other-commands"
                elif case["has_broken"] and isinstance(err, (ValueError, TypeError, KeyError)):
                    cat = "broken-lines"
                else:
                    raise err
            else:
                cat = _t1_judge(got, case)
            oks.append(cat is None)
            if cat:
                cats.append(cat)
                if example is None:
                    example = {"inputs": {"log lines": len(case["lines"]), "slug": case["slug"],
                                          "stage": case["stage"]},
                               "got": f"{len(_t1_rows(got) or [])} rows" if err is None else type(err).__name__,
                               "error": f"expected {len(case['want'])} rows"}
    category = _first(cats, T1_PRIORITY)
    if category is not None:
        return outcome_from_cases(np.array(oks), category=category, example=example)
    passed, cat = _t1_real(target, ctx)
    steps = 5
    ok = np.array(oks + [True] * passed + [False] * (steps - passed if cat else 0), dtype=bool)
    note = ("The check read your run log with your reader, computed the SHA-256 fingerprints of the .sum, .arc and "
            ".prt files now in your cluster itself, and compared them with yours and (.sum and .arc) with the ones "
            "your last location run logged; it never prints them.")
    return outcome_from_cases(ok, category=cat, real_data=True, note=note)


# ============================================================================ M32-T2 the archive file
T2_COLUMNS = ("event", "station", "phase", "residual_s", "weight", "distance_km", "azimuth_deg")
T2_PRIORITY = ("format", "terminator", "phase-rows", "event-id", "station-name", "implied-decimal",
               "weight-column", "touching-fields", "wrong-values")
_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"


def _place(buf: List[str], first: int, text: str) -> None:
    """Write text into the line buffer from column 'first' (counted from 1, as in the format tables)."""
    for k, ch in enumerate(text):
        buf[first - 1 + k] = ch


def _arc_header(rng: np.random.Generator, ident: int) -> str:
    buf = list(" " * 180)
    digits = "".join(str(int(d)) for d in rng.integers(0, 10, 130))
    _place(buf, 1, "2031" + digits[:12])
    _place(buf, 17, digits[12:40])
    _place(buf, 60, digits[40:70])
    _place(buf, 111, "qzm" + digits[70:80])
    _place(buf, 137, f"{ident:10d}")
    _place(buf, 150, digits[80:100])
    return "".join(buf).rstrip()


def _arc_station(rng: np.random.Generator, row: dict, touch: bool) -> str:
    """One station line (Y2000 station archive format, Klein 2002) holding the P and/or S reading of 'row'."""
    buf = list(" " * 122)
    _place(buf, 1, f"{row['sta']:<5s}")
    _place(buf, 6, f"{row['net']:<2s}")
    _place(buf, 10, row["comp"])
    _place(buf, 18, "203103171246")
    p, s = row.get("P"), row.get("S")
    _place(buf, 17, str(p["code"]) if p else "0")
    if p:
        _place(buf, 14, p["remark"])
        if touch:
            _place(buf, 16, str(rng.choice([" ", "U", "D"])))
        _place(buf, 30, f"{int(rng.integers(100, 5999)):5d}")
        _place(buf, 35, f"{int(round(p['res'] * 100)):4d}")
        _place(buf, 39, f"{int(round(p['w'] * 100)):3d}")
    else:
        _place(buf, 30, f"{0:5d}")
        _place(buf, 35, f"{0:4d}")
        _place(buf, 39, f"{0:3d}")
    if s:
        _place(buf, 42, f"{int(rng.integers(100, 9999)):5d}")
        _place(buf, 47, s["remark"])
        _place(buf, 50, str(s["code"]))
        _place(buf, 51, f"{int(round(s['res'] * 100)):4d}")
        _place(buf, 64, f"{int(round(s['w'] * 100)):3d}")
    else:
        _place(buf, 42, f"{0:5d}")
        _place(buf, 51, f"{0:4d}")
        _place(buf, 64, f"{0:3d}")
    _place(buf, 55, f"{0:7d}")
    _place(buf, 62, f"{0:2d}")
    _place(buf, 67, f"{0:4d}")
    _place(buf, 71, f"{0:4d}")
    _place(buf, 75, f"{int(round(row['dist'] * 10)):4d}")
    if touch:
        _place(buf, 79, f"{int(rng.integers(91, 179)):3d}")
        _place(buf, 82, "00")
    _place(buf, 84, f"{0:3d}")
    _place(buf, 92, f"{int(round(row['az'])):3d}")
    _place(buf, 101, f"{int(rng.integers(0, 999)):4d}")
    _place(buf, 109, " ")
    _place(buf, 116, row["comp"])
    return "".join(buf).rstrip()


def _t2_reading(rng: np.random.Generator, phase: str, touch: bool) -> dict:
    if touch:
        res = float(rng.choice([rng.uniform(-9.5, -1.0), rng.uniform(-0.99, 0.99), rng.uniform(1.0, 9.9), 0.0]))
        weight = float(rng.choice([rng.uniform(1.0, 2.2), rng.uniform(0.01, 0.99), 0.0]))
    else:
        res = float(rng.uniform(-0.99, 0.99))
        weight = float(rng.uniform(0.01, 0.99))
    return {"remark": ("I" if rng.random() < 0.6 else "E") + phase, "code": int(rng.integers(0, 5)),
            "res": round(res, 2), "w": round(weight, 2)}


def _t2_case(rng: np.random.Generator, number: int) -> dict:
    """A made-up archive file and its readings, in file order (a line's P before its S)."""
    touch = number > 0
    lines, want, n_lines = [], [], 0
    used = set()
    for e in range(int(rng.integers(2, 5))):
        ident = int(rng.integers(3_000_000, 9_999_999))
        lines.append(_arc_header(rng, ident))
        for _k in range(int(rng.integers(3, 10))):
            while True:
                sta = "QQ" + "".join(str(rng.choice(list(_LETTERS))) for _ in range(int(rng.integers(1, 3 + touch))))
                net = str(rng.choice(["XX", "XY", "ZQ"]))
                if (sta, net) not in used:
                    used.add((sta, net))
                    break
            kind = int(rng.integers(0, 3)) if touch else int(rng.integers(0, 2))
            row = {"sta": sta, "net": net, "comp": str(rng.choice(["HHZ", "HGZ", "ELZ"])),
                   "dist": round(float(rng.uniform(100.0, 999.0) if touch and rng.random() < 0.5
                                       else rng.uniform(0.5, 99.4)), 1),
                   "az": float(rng.integers(0, 360))}
            if kind in (0, 2):
                row["P"] = _t2_reading(rng, "P", touch)
            if kind in (1, 2):
                row["S"] = _t2_reading(rng, "S", touch)
            lines.append(_arc_station(rng, row, touch))
            n_lines += 1
            for phase in ("P", "S"):
                if phase in row:
                    want.append({"event": ident, "station": f"{net}.{sta}", "phase": phase,
                                 "residual_s": row[phase]["res"], "weight": row[phase]["w"],
                                 "distance_km": row["dist"], "azimuth_deg": row["az"],
                                 "p_weight": row["P"]["w"] if "P" in row else 0.0, "combined": kind == 2})
        lines.append(" " * 62 + f"{ident:10d}")
    return {"text": "\n".join(lines) + "\n", "want": want, "touch": touch, "n_lines": n_lines}


def _t2_judge(got: Any, case: dict) -> Optional[str]:
    import pandas as pd

    if not _is_frame(got, T2_COLUMNS):
        return "format"
    want = case["want"]
    if len(got) != len(want):
        if len(got) == len(want) + len({w["event"] for w in want}):
            return "terminator"
        return "phase-rows"
    try:
        ev = [int(v) for v in got["event"]]
        sta = [str(v) for v in got["station"]]
        ph = [str(v) for v in got["phase"]]
        num = {c: pd.to_numeric(got[c], errors="coerce").to_numpy(dtype=float)
               for c in ("residual_s", "weight", "distance_km", "azimuth_deg")}
    except (TypeError, ValueError):
        return "format"
    if ph != [w["phase"] for w in want]:
        return "phase-rows"
    if ev != [w["event"] for w in want]:
        return "event-id"
    if sta != [w["station"] for w in want]:
        return "station-name"
    exp = {c: np.array([w[c] for w in want], dtype=float) for c in num}
    good = {c: np.isfinite(num[c]) & (np.abs(num[c] - exp[c]) <= 0.0051) for c in num}
    if all(g.all() for g in good.values()):
        return None
    scaled = (np.abs(num["residual_s"] - 100 * exp["residual_s"]) <= 0.51) & (exp["residual_s"] != 0)
    if scaled.any() or (np.abs(num["distance_km"] - 10 * exp["distance_km"]) <= 0.51).any():
        return "implied-decimal"
    is_s = np.array([w["phase"] == "S" for w in want])
    p_w = np.array([w["p_weight"] for w in want])
    if is_s.any() and np.all(np.abs(num["weight"][is_s] - p_w[is_s]) <= 0.0051) and \
            not np.all(np.abs(exp["weight"][is_s] - p_w[is_s]) <= 0.0051):
        return "weight-column"
    if case["touch"]:
        return "touching-fields"
    return "wrong-values"


def _t2_real(func: Any, slug: Any, crit: dict) -> Tuple[List[bool], Optional[str]]:
    """The student's archive files of both models against the summary files of the same run."""
    oks: List[bool] = []
    folder = _run_folder(str(slug)) / "1.HypoInv"
    for model in MODELS:
        arcs = sorted((folder / model).glob("*.arc"))
        sums = sorted((folder / model).glob("*.sum"))
        if not isinstance(slug, str) or len(arcs) != 1 or len(sums) != 1:
            return oks + [False], "real-missing"
        got, err = _call(func, str(arcs[0]))
        if err is not None:
            raise err
        if not _is_frame(got, T2_COLUMNS):
            return oks + [False], "format"
        summ = _summary(sums[0])
        try:
            events = np.array([int(v) for v in got["event"]])
            w = got["weight"].to_numpy(dtype=float)
            r = got["residual_s"].to_numpy(dtype=float)
        except (TypeError, ValueError):
            return oks + [False], "format"
        if set(events.tolist()) != set(summ["id"].tolist()):
            return oks + [False], "real-events"
        oks.append(True)
        for ident, num, rms in zip(summ["id"], summ["num"], summ["rms"]):
            sel = events == ident
            n_used = int(np.sum(w[sel] > 0.1))
            if abs(n_used - int(num)) > int(crit.get("num_tol", 1)):
                return oks + [False], "real-num"
            top, bottom = float(np.sum((w[sel] * r[sel]) ** 2)), float(np.sum(w[sel] ** 2))
            if bottom <= 0 or not abs(math.sqrt(top / bottom) - float(rms)) <= float(crit.get("rms_tol_s", 0.011)):
                return oks + [False], "real-rms"
            oks.append(True)
    return oks, None


def check_T2(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    rng = ctx.rng
    oks, cats, example = [], [], None
    plain_ok = True
    with tempfile.TemporaryDirectory(prefix="sgtl-m32-t2-") as tmp:
        for k in range(max(3, int(crit.get("trials", 10)))):
            case = _t2_case(rng, k)
            path = Path(tmp) / f"made_up_{k}.arc"
            path.write_text(case["text"], encoding="utf-8")
            got, err = _call(target, str(path))
            if err is not None:
                if case["touch"] and plain_ok and isinstance(err, (ValueError, IndexError, TypeError)):
                    cat = "touching-fields"
                else:
                    raise err
            else:
                cat = _t2_judge(got, case)
                if cat == "touching-fields" and not plain_ok:
                    cat = "wrong-values"
            if not case["touch"]:
                plain_ok = cat is None
            oks.append(cat is None)
            if cat:
                cats.append(cat)
                if example is None:
                    example = {"inputs": {"file": f"{len(case['want'])} readings on {case['n_lines']} station lines",
                                          "first line": case["text"].split("\n")[1][:96]},
                               "got": (got.head(2).to_dict("records") if _is_frame(got, T2_COLUMNS)
                                       else (type(err).__name__ if err is not None else type(got).__name__)),
                               "error": f"expected {case['want'][0]['phase']} residual "
                                        f"{case['want'][0]['residual_s']:g} s, weight {case['want'][0]['weight']:g}"}
    category = _first(cats, T2_PRIORITY)
    if category is not None:
        return outcome_from_cases(np.array(oks), category=category, example=example)
    real, cat = _t2_real(target, ctx.get("slug"), crit)
    ok = np.array(oks + real, dtype=bool)
    note = ("The check read your two archive files (kim1983, kim2011) with your function and compared every "
            "event with HYPOINVERSE's own summary file of the same run (events, NUM, RMS); it never prints them.")
    return outcome_from_cases(ok, category=cat, real_data=True, note=note)


# ============================================================================ M32-T3 matching locations
T3_COLUMNS = ("match", "dt_s", "dist_km", "ddepth_km")
T3_PRIORITY = ("format", "naive-time", "order", "time-zone", "threshold", "nearest", "sign", "units",
               "wrong-values")


def _t3_case(rng: np.random.Generator, number: int, max_dt: float) -> dict:
    """Two made-up tables of locations: ref in UTC, other in another time zone, with known partners."""
    import pandas as pd

    n = int(rng.integers(5, 11))
    start = pd.Timestamp("2031-02-01T00:00:00Z")
    secs = np.sort(rng.uniform(0, 300 * 86400, n))
    secs = secs + np.arange(n) * 20 * max_dt              # keep events apart
    ref = pd.DataFrame({"time": [start + pd.Timedelta(seconds=float(s)) for s in secs],
                        "lat": rng.uniform(33.2, 38.6, n).round(4), "lon": rng.uniform(124.6, 130.8, n).round(4),
                        "depth": rng.uniform(1.0, 28.0, n).round(2)})
    ref.index = [f"r{k}" for k in range(n)] if number % 2 else list(range(100, 100 + n))
    rows, labels, want = [], [], []
    for k in range(n):
        if rng.random() < 0.25 and k:
            want.append(None)
            continue
        dt = float(rng.uniform(-0.85, 0.85) * max_dt)
        lab = f"o{len(rows)}"
        rows.append({"time": ref["time"].iloc[k] + pd.Timedelta(seconds=dt),
                     "lat": float(ref["lat"].iloc[k] + rng.uniform(-0.15, 0.15)),
                     "lon": float(ref["lon"].iloc[k] + rng.uniform(-0.15, 0.15)),
                     "depth": float(ref["depth"].iloc[k] + rng.uniform(-6, 6))})
        labels.append(lab)
        if number >= 3 and rng.random() < 0.4:            # a second candidate, farther in time
            far = dt + float(np.sign(dt) or 1.0) * float(rng.uniform(0.1, 0.14) * max_dt)
            rows.append({"time": ref["time"].iloc[k] + pd.Timedelta(seconds=far),
                         "lat": float(ref["lat"].iloc[k] + rng.uniform(-0.3, 0.3)),
                         "lon": float(ref["lon"].iloc[k] + rng.uniform(-0.3, 0.3)), "depth": 9.0})
            labels.append(f"o{len(rows) - 1}")
        want.append(lab)
    for k in range(int(rng.integers(1, 4))):              # decoys well outside the window of every event
        rows.append({"time": start + pd.Timedelta(seconds=float(secs[-1] + (k + 3) * 7 * max_dt)),
                     "lat": 35.0, "lon": 127.0, "depth": 5.0})
        labels.append(f"d{k}")
    for k in range(n):                                     # near misses: just outside the window
        if want[k] is None and rng.random() < 0.7:
            rows.append({"time": ref["time"].iloc[k] + pd.Timedelta(seconds=float(rng.uniform(1.05, 1.6) * max_dt)),
                         "lat": float(ref["lat"].iloc[k]), "lon": float(ref["lon"].iloc[k]), "depth": 3.0})
            labels.append(f"m{k}")
    import datetime as _dt

    other = pd.DataFrame(rows, index=labels)
    other = other.iloc[rng.permutation(len(other))]
    zone = ["Asia/Seoul", _dt.timezone(_dt.timedelta(hours=9)), "UTC",
            _dt.timezone(_dt.timedelta(hours=-5))][number % 4]
    other["time"] = [t.tz_convert(zone) for t in other["time"]]
    if number % 3 == 1:
        ref["time"] = [t.tz_convert("Asia/Seoul") for t in ref["time"]]
    exp = {"match": want, "dt_s": [], "dist_km": [], "ddepth_km": []}
    for k, lab in enumerate(want):
        if lab is None:
            exp["dt_s"].append(np.nan)
            exp["dist_km"].append(np.nan)
            exp["ddepth_km"].append(np.nan)
            continue
        o = other.loc[lab]
        exp["dt_s"].append((o["time"] - ref["time"].iloc[k]).total_seconds())
        exp["dist_km"].append(float(_geod_km(ref["lat"].iloc[k], ref["lon"].iloc[k], o["lat"], o["lon"])[0]))
        exp["ddepth_km"].append(float(o["depth"] - ref["depth"].iloc[k]))
    return {"ref": ref, "other": other, "max_dt": max_dt, "exp": exp, "zone": zone}


def _t3_judge(got: Any, case: dict, crit: dict) -> Optional[str]:
    import pandas as pd

    if not _is_frame(got, T3_COLUMNS):
        return "format"
    ref, exp = case["ref"], case["exp"]
    if len(got) != len(ref) or list(got.index) != list(ref.index):
        return "order"
    have = [None if (v is None or (isinstance(v, float) and math.isnan(v))) else v for v in got["match"]]
    want = exp["match"]
    if have != want:
        times = {lab: t for lab, t in zip(case["other"].index, case["other"]["time"])}
        if all(h is None for h in have) and any(w is not None for w in want):
            return "time-zone"
        for k, (h, w) in enumerate(zip(have, want)):
            if h == w:
                continue
            if h is not None and h in times and \
                    abs((times[h] - ref["time"].iloc[k]).total_seconds()) > case["max_dt"] + 1e-6:
                return "threshold"
            if h is None and w is not None:
                return "threshold"
            if h is not None and w is not None:
                return "nearest"
        return "wrong-values"
    try:
        got_v = {c: pd.to_numeric(got[c], errors="coerce").to_numpy(dtype=float)
                 for c in ("dt_s", "dist_km", "ddepth_km")}
    except (TypeError, ValueError):
        return "format"
    e = {c: np.array(exp[c], dtype=float) for c in got_v}
    hit = ~np.isnan(e["dt_s"])
    if np.any(~np.isnan(got_v["dt_s"][~hit])) or np.any(np.isnan(got_v["dt_s"][hit])):
        return "wrong-values"
    if not hit.any():
        return None
    tol_t = float(crit.get("dt_tol_s", 1.0e-3))
    tol_z = float(crit.get("depth_tol_km", 1.0e-3))
    rel = float(crit.get("dist_rel_tol", 0.005))
    ab = float(crit.get("dist_abs_tol_km", 0.005))
    ok_t = np.abs(got_v["dt_s"][hit] - e["dt_s"][hit]) <= tol_t
    ok_z = np.abs(got_v["ddepth_km"][hit] - e["ddepth_km"][hit]) <= tol_z
    ok_d = np.abs(got_v["dist_km"][hit] - e["dist_km"][hit]) <= np.maximum(ab, rel * e["dist_km"][hit])
    if ok_t.all() and ok_z.all() and ok_d.all():
        return None
    flip_t = np.abs(got_v["dt_s"][hit] + e["dt_s"][hit]) <= tol_t
    flip_z = np.abs(got_v["ddepth_km"][hit] + e["ddepth_km"][hit]) <= tol_z
    if (not ok_t.all() and flip_t.all()) or (not ok_z.all() and flip_z.all()):
        return "sign"
    if not ok_d.all():
        for factor in (1.0 / 111.19, 1000.0, 1.0 / 1.609344):
            if np.all(np.abs(got_v["dist_km"][hit] - factor * e["dist_km"][hit]) <=
                      np.maximum(ab, 0.02 * factor * e["dist_km"][hit])):
                return "units"
    return "wrong-values"


def _t3_naive(func: Any, case: dict) -> bool:
    """True when the student's function refuses times without a time zone (ValueError)."""
    ref = case["ref"].copy()
    ref["time"] = [t.tz_convert("UTC").tz_localize(None) for t in ref["time"]]
    _got, err = _call(func, ref, case["other"], case["max_dt"])
    return isinstance(err, ValueError)


def _t3_real(func: Any, slug: Any, crit: dict) -> Tuple[List[bool], Optional[str]]:
    from .. import data as _data

    sums = sorted((_run_folder(str(slug)) / "1.HypoInv" / "kim1983").glob("*.sum"))
    if not isinstance(slug, str) or len(sums) != 1:
        return [False], "real-missing"
    mine = _summary(sums[0])[["time", "lat", "lon", "depth"]]
    seq = _data.sequence(str(crit.get("sequence", "sangju2019")))
    kma = seq.rename(columns={"origin_utc": "time", "latitude": "lat", "longitude": "lon", "depth_km": "depth"})
    kma = kma[["time", "lat", "lon", "depth"]]
    got, err = _call(func, mine, kma, float(crit.get("real_max_dt_s", 5.0)))
    if err is not None:
        raise err
    if not _is_frame(got, T3_COLUMNS) or len(got) != len(mine):
        return [False], "format"
    vals = {c: np.asarray(got[c], dtype=float) for c in ("dt_s", "dist_km", "ddepth_km")}
    found = np.array([v is not None and not (isinstance(v, float) and math.isnan(v)) for v in got["match"]])
    ok = (found & (np.abs(vals["dt_s"]) <= float(crit.get("real_dt_s", 2.0)))
          & (vals["dist_km"] >= 0) & (vals["dist_km"] <= float(crit.get("real_dist_km", 5.0)))
          & (np.abs(vals["ddepth_km"]) <= float(crit.get("real_depth_km", 15.0))))
    return [bool(v) for v in ok], (None if ok.all() else "real-matches")


def check_T3(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    rng = ctx.rng
    max_dt = float(crit.get("max_dt_s", 5.0))
    oks, cats, example = [], [], None
    for k in range(max(4, int(crit.get("trials", 12)))):
        case = _t3_case(rng, k, max_dt)
        got, err = _call(target, case["ref"].copy(), case["other"].copy(), max_dt)
        if err is not None:
            raise err
        cat = _t3_judge(got, case, crit)
        if cat is None and k == 0 and not _t3_naive(target, case):
            cat = "naive-time"
        oks.append(cat is None)
        if cat:
            cats.append(cat)
            if example is None:
                first = case["ref"].iloc[0]
                example = {"inputs": {"ref rows": len(case["ref"]), "other rows": len(case["other"]),
                                      "other time zone": str(case["zone"]), "max_dt_s": max_dt,
                                      "first ref time": str(first["time"])},
                           "got": (got.head(3).to_dict("records") if _is_frame(got, T3_COLUMNS)
                                   else type(got).__name__),
                           "error": f"expected match {case['exp']['match'][:3]}"}
    category = _first(cats, T3_PRIORITY)
    if category is not None:
        return outcome_from_cases(np.array(oks), category=category, example=example)
    real, cat = _t3_real(target, ctx.get("slug"), crit)
    ok = np.array(oks + real, dtype=bool)
    note = ("The check also matched your kim1983 summary with the KMA catalog through your function; every event "
            "must find a partner within loose bounds. It never prints the values.")
    return outcome_from_cases(ok, category=cat, real_data=True, note=note)


# ============================================================================ M32-T4 rerun and second model
T4_KEYS = {"differ", "slug", "first", "rerun", "fingerprints", "model_change"}
T4_PRIORITY = ("format", "line-numbers", "eol", "missing-extra", "wrong-values")
_WORDS = ("depth", "station", "residual", "weight", "model", "origin", "phase", "layer", "trial", "gap")


def _t4_case(rng: np.random.Generator, number: int) -> dict:
    n = int(rng.integers(4, 30))
    base = [" ".join(str(rng.choice(_WORDS)) for _ in range(int(rng.integers(1, 6)))) + f" {k}"
            for k in range(n)]
    other = list(base)
    for k in rng.choice(n, size=int(rng.integers(0, min(4, n) + 1)), replace=False):
        other[int(k)] = other[int(k)] + " changed"
    if number % 3 == 1:
        other += [f"extra {k}" for k in range(int(rng.integers(1, 4)))]
    elif number % 3 == 2:
        base += [f"more {k}" for k in range(int(rng.integers(1, 3)))]
    if number == 0:
        other = list(base)
    want = []
    for k in range(max(len(base), len(other))):
        a = base[k] if k < len(base) else None
        b = other[k] if k < len(other) else None
        if a != b:
            want.append((k + 1, a, b))
    end_a = "\n"
    end_b = "" if number % 4 == 3 else "\n"
    return {"a": "\n".join(base) + end_a, "b": "\n".join(other) + end_b, "want": want}


def _t4_rows(got: Any) -> Optional[List[tuple]]:
    if not isinstance(got, (list, tuple)):
        return None
    out = []
    for item in got:
        if not isinstance(item, (list, tuple)) or len(item) != 3:
            return None
        n, a, b = item
        if isinstance(n, bool) or not isinstance(n, (int, np.integer)):
            return None
        out.append((int(n), a, b))
    return out


def _t4_judge(got: Any, case: dict) -> Optional[str]:
    have = _t4_rows(got)
    if have is None:
        return "format"
    want = case["want"]
    if have == want:
        return None
    if [(n + 1, a, b) for n, a, b in have] == want:
        return "line-numbers"
    strip = [(n, a.rstrip("\r\n") if isinstance(a, str) else a, b.rstrip("\r\n") if isinstance(b, str) else b)
             for n, a, b in have]
    if [r for r in strip if r[1] != r[2]] == want or strip == want:
        return "eol"
    if have == [r for r in want if r[1] is not None and r[2] is not None]:
        return "missing-extra"
    return "wrong-values"


def _t4_files(root: Path) -> Dict[str, Path]:
    return {p.relative_to(root).as_posix(): p for p in sorted(root.rglob("*")) if p.is_file()}


def _t4_real(target: dict, ctx: Any, crit: dict) -> Tuple[int, Optional[str]]:
    import pandas as pd

    passed = 0
    roots = {}
    for key in ("first", "rerun"):
        value = target[key]
        if not isinstance(value, (str, os.PathLike)):
            return passed, "format"
        root = Path(value).expanduser()
        found = {m: (sorted((root / m).glob("*.sum")), sorted((root / m).glob("*.arc"))) for m in MODELS}
        if not root.is_dir() or any(len(s) != 1 or len(a) != 1 for s, a in found.values()):
            return passed, "copies"
        roots[key] = root
    passed += 1
    for key, root in roots.items():               # every file of the copy, each digest recomputed from its bytes
        claim = target["fingerprints"][key]
        files = _t4_files(root)
        if set(claim) != set(files):
            return passed, "fingerprint-files"
        if any(claim[rel].lower() != _digest(path) for rel, path in files.items()):
            return passed, "fingerprint-claim"
    passed += 1
    slug = target["slug"]
    runs = _location_runs(_log_records(ctx.repo), str(slug)) if isinstance(slug, str) else []
    logged = {}
    for obj in runs:
        for name, value in (obj.get("products") or {}).items():
            logged.setdefault(name, set()).add(value)
    if len(runs) < int(crit.get("min_runs", 2)):
        return passed, "runs-missing"
    passed += 1
    for root in roots.values():
        for model in MODELS:
            for p in list((root / model).glob("*.sum")) + list((root / model).glob("*.arc")):
                if _digest(p) not in logged.get(f"1.HypoInv/{model}/{p.name}", set()):
                    return passed, "not-run-products"
    passed += 1
    if roots["first"].resolve() == roots["rerun"].resolve():
        return passed, "no-rerun"                     # one copy named for both runs
    results = {f"{m}/{p.name}": _digest(p) for m in MODELS
               for p in list((roots["first"] / m).glob("*.sum")) + list((roots["first"] / m).glob("*.arc"))}
    same = all((roots["rerun"] / rel).is_file() and _digest(roots["rerun"] / rel) == digest
               for rel, digest in results.items())
    writers = {rel: sum(1 for obj in runs if (obj.get("products") or {}).get(f"1.HypoInv/{rel}") == digest)
               for rel, digest in results.items()}
    if same and min(writers.values()) < 2:
        return passed, "no-rerun"                     # the same result bytes twice, but only one run wrote them
    passed += 1
    table = target["model_change"]
    a = _summary(sorted((roots["first"] / MODELS[0]).glob("*.sum"))[0])
    b = _summary(sorted((roots["first"] / MODELS[1]).glob("*.sum"))[0]).set_index("id")
    if not _is_frame(table, ("dt_s", "dist_km", "ddepth_km")) or len(table) != len(a):
        return passed, "model-table"
    try:
        got = {c: pd.to_numeric(table[c], errors="coerce").to_numpy(dtype=float) for c in ("dt_s", "dist_km",
                                                                                           "ddepth_km")}
    except (TypeError, ValueError):
        return passed, "model-table"
    if not set(a["id"]).issubset(set(b.index)):
        return passed, "model-table"
    b = b.loc[a["id"]]
    dz = b["depth"].to_numpy() - a["depth"].to_numpy()
    dt = np.array([(t2 - t1).total_seconds() for t1, t2 in zip(a["time"], b["time"])])
    dd = _geod_km(a["lat"], a["lon"], b["lat"], b["lon"])
    tol = float(crit.get("table_tol", 0.006))
    ok = (np.abs(got["ddepth_km"] - dz) <= tol) & (np.abs(got["dt_s"] - dt) <= tol) & \
        (np.abs(got["dist_km"] - dd) <= np.maximum(tol, 0.005 * dd))
    if not ok.all():
        flipped = (np.abs(got["ddepth_km"] + dz) <= tol) | (np.abs(got["dt_s"] + dt) <= tol)
        return passed, "model-sign" if flipped[~ok].all() and np.any(np.abs(dz) > tol) else "model-table"
    passed += 1
    return passed, None


def _t4_prints_ok(value: Any) -> bool:
    """The report's fingerprints: {"first": {path: 64 hex letters}, "rerun": {path: 64 hex letters}}, none empty."""
    if not isinstance(value, dict) or set(value) != {"first", "rerun"}:
        return False
    return all(isinstance(per, dict) and per and
               all(isinstance(k, str) and isinstance(v, str) and len(v) == 64 and set(v.lower()) <= _HEX
                   for k, v in per.items())
               for per in value.values())


def _t4_guard(func: Any, ctx: Any) -> Optional[Outcome]:
    """The task's library rule for the line comparison inside the answer (the engine screens only a function)."""
    from .. import astguard
    from ..checks import DEFAULT_MESSAGES

    rules = list((ctx.spec or {}).get("forbidden") or [])
    rep = astguard.check_function(func, rules) if rules else None
    if rep is None or rep.ok:
        return None
    if rep.category == "runtime-name":
        return Outcome(False, 0, 0, "runtime-name", DEFAULT_MESSAGES["runtime-name"],
                       details={"found": list(rep.runtime)})
    msg = DEFAULT_MESSAGES["forbidden-import"].replace("{rules}", ", ".join(rep.violations))
    return Outcome(False, 0, 0, "forbidden-import", msg + " (found in differ)", details={"found": rep.offending})


def check_T4(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    if not isinstance(target, dict) or set(target) != T4_KEYS or not callable(target.get("differ")) or \
            not _t4_prints_ok(target.get("fingerprints")):
        return Outcome(passed=False, n_cases=1, n_failed=1, category="format", message="", details={})
    refused = _t4_guard(target["differ"], ctx)
    if refused is not None:
        return refused
    rng = ctx.rng
    oks, cats, example = [], [], None
    with tempfile.TemporaryDirectory(prefix="sgtl-m32-t4-") as tmp:
        for k in range(max(4, int(crit.get("trials", 8)))):
            case = _t4_case(rng, k)
            pa, pb = Path(tmp) / f"a_{k}.txt", Path(tmp) / f"b_{k}.txt"
            pa.write_text(case["a"], encoding="utf-8")
            pb.write_text(case["b"], encoding="utf-8")
            got, err = _call(target["differ"], str(pa), str(pb))
            if err is not None:
                raise err
            cat = _t4_judge(got, case)
            oks.append(cat is None)
            if cat:
                cats.append(cat)
                if example is None:
                    example = {"inputs": {"lines in a": case["a"].count("\n"), "lines in b": len(case["b"].split("\n")),
                                          "first difference": case["want"][0] if case["want"] else None},
                               "got": (_t4_rows(got) or [])[:2] if _t4_rows(got) is not None else type(got).__name__,
                               "error": f"expected {len(case['want'])} differing lines"}
    category = _first(cats, T4_PRIORITY)
    if category is not None:
        return outcome_from_cases(np.array(oks), category=category, example=example)
    passed, cat = _t4_real(target, ctx, crit)
    steps = 6
    ok = np.array(oks + [True] * passed + [False] * (steps - passed if cat else 0), dtype=bool)
    note = ("The check recomputed the SHA-256 fingerprints of every file of your two copies, compared them with yours "
            "and the result files with the fingerprints your runs logged, and your model table with the two summary "
            "files of your first copy; it never prints them.")
    return outcome_from_cases(ok, category=cat, real_data=True, note=note)


# ============================================================================ M32-T5 station terms
T5_COLUMNS = ("station", "phase", "n", "mean_s", "se_s", "label")
T5_PRIORITY = ("format", "weight-filter", "weight-boundary", "min-events", "sort", "se-formula", "label-rule",
               "wrong-values")


def _t5_case(rng: np.random.Generator, number: int, min_events: int) -> dict:
    """Readings whose used part has, per station and phase, an exact mean and an exact sample SD by design."""
    import pandas as pd

    rows, want = [], {}
    var_all, var_edge = {}, {}
    n_sta = int(rng.integers(4, 10))
    for s in range(n_sta):
        station = f"XX.QQ{_LETTERS[s]}{int(rng.integers(1, 9))}"
        for phase in ("P", "S"):
            if rng.random() < 0.15:
                continue
            n = int(rng.integers(max(2, min_events - 2), min_events + 6))
            sd = float(rng.uniform(0.02, 0.2))
            se = sd / math.sqrt(n)
            ratio = float(rng.choice([0.0, rng.uniform(0.2, 1.6), rng.uniform(2.6, 9.0)]))
            mean = float(rng.choice([-1, 1])) * ratio * se
            z = rng.normal(size=n)
            z = (z - z.mean()) / z.std(ddof=1)
            used = mean + sd * z
            events = rng.choice(np.arange(5000, 5100), size=n + 3, replace=False)
            for k in range(n):
                rows.append((int(events[k]), station, phase, float(used[k]),
                             float(rng.choice([rng.uniform(0.11, 0.99), rng.uniform(1.0, 2.2)])), "used"))
            extra = []
            if rng.random() < 0.7:
                extra.append((float(rng.choice([-1, 1]) * rng.uniform(3, 11)), 0.0, "zero"))
            if rng.random() < 0.5:
                extra.append((float(rng.uniform(-2, 2)), 0.05, "low"))
            if rng.random() < 0.5:
                extra.append((float(rng.uniform(1.5, 4)), 0.10, "edge"))
            for j, (res, w, kind) in enumerate(extra):
                rows.append((int(events[n + j]), station, phase, res, w, kind))
            if n >= min_events:
                label = "late" if mean - 2 * se > 0 else ("early" if mean + 2 * se < 0 else "")
                want[(station, phase)] = (n, mean, se, label)
            all_r = list(used) + [e[0] for e in extra]
            edge_r = list(used) + [e[0] for e in extra if e[2] == "edge"]
            if len(all_r) >= min_events:
                var_all[(station, phase)] = float(np.mean(all_r))
            if len(edge_r) >= min_events:
                var_edge[(station, phase)] = float(np.mean(edge_r))
    order = rng.permutation(len(rows))
    table = pd.DataFrame([rows[i][:5] for i in order], columns=["event", "station", "phase", "residual_s", "weight"])
    table["distance_km"] = rng.uniform(5, 99, len(table)).round(1)
    table["azimuth_deg"] = rng.integers(0, 360, len(table)).astype(float)
    table.index = rng.permutation(len(table)) + 7
    small = {k: v for k, v in want.items()}
    return {"table": table, "want": dict(sorted(small.items())), "var_all": var_all, "var_edge": var_edge,
            "min_events": min_events}


def _t5_judge(got: Any, case: dict, tol: float) -> Optional[str]:
    import pandas as pd

    if not _is_frame(got, T5_COLUMNS):
        return "format"
    want = case["want"]
    try:
        keys = [(str(a), str(b)) for a, b in zip(got["station"], got["phase"])]
        n = [int(v) for v in got["n"]]
        mean = pd.to_numeric(got["mean_s"], errors="coerce").to_numpy(dtype=float)
        se = pd.to_numeric(got["se_s"], errors="coerce").to_numpy(dtype=float)
        label = ["" if (v is None or (isinstance(v, float) and math.isnan(v))) else str(v) for v in got["label"]]
    except (TypeError, ValueError):
        return "format"
    if set(keys) != set(want) or any(n[i] != want[k][0] for i, k in enumerate(keys) if k in want):
        mine = dict(zip(keys, mean))

        def fits(variant):  # every row of the student sits on this variant, and the variant is not the truth
            hit = [k in variant and abs(mine[k] - variant[k]) <= tol for k in mine]
            new = [k in variant and abs(variant[k] - want.get(k, (0, np.inf))[1]) > tol for k in mine]
            return bool(hit) and all(hit) and any(new)

        if fits(case["var_edge"]) and not fits(case["var_all"]):
            return "weight-boundary"
        if fits(case["var_all"]):
            return "weight-filter"
        if set(want).issubset(set(keys)):
            return "min-events"
        return "wrong-values"
    if keys != list(want):
        return "sort"
    w_mean = np.array([want[k][1] for k in keys])
    w_se = np.array([want[k][2] for k in keys])
    if not np.all(np.abs(mean - w_mean) <= tol):
        return "wrong-values"
    if not np.all(np.abs(se - w_se) <= tol):
        return "se-formula"
    if label != [want[k][3] for k in keys]:
        return "label-rule"
    return None


def _t5_real(func: Any, reader: Any, slug: Any, crit: dict) -> Tuple[List[bool], Optional[str]]:
    import pandas as pd

    min_events = int(crit.get("real_min_events", 4))
    oks: List[bool] = []
    folder = _run_folder(str(slug)) / "1.HypoInv"
    if not callable(reader) or not isinstance(slug, str):
        return [False], "real-missing"
    for model in MODELS:
        arcs = sorted((folder / model).glob("*.arc"))
        if len(arcs) != 1:
            return oks + [False], "real-missing"
        phases, err = _call(reader, str(arcs[0]))
        if err is not None:
            raise err
        got, err = _call(func, phases, min_events)
        if err is not None:
            raise err
        if not _is_frame(got, T5_COLUMNS) or len(got) == 0:
            return oks + [False], "format"
        mean = pd.to_numeric(got["mean_s"], errors="coerce").to_numpy(dtype=float)
        se = pd.to_numeric(got["se_s"], errors="coerce").to_numpy(dtype=float)
        n = pd.to_numeric(got["n"], errors="coerce").to_numpy(dtype=float)
        if not (np.all(n >= min_events) and np.all(np.isfinite(se)) and np.all(se >= 0)):
            return oks + [False], "real-rows"
        if not np.all(np.abs(mean) <= float(crit.get("real_max_abs_mean_s", 1.0))):
            return oks + [False], "real-outliers"
        rule = np.where(mean - 2 * se > 0, "late", np.where(mean + 2 * se < 0, "early", ""))
        label = ["" if (v is None or (isinstance(v, float) and math.isnan(v))) else str(v) for v in got["label"]]
        if label != list(rule):
            return oks + [False], "label-rule"
        oks.append(True)
    return oks, None


def check_T5(target: Any, ctx: Any) -> Outcome:
    crit = dict(ctx.criteria)
    rng = ctx.rng
    tol = float(crit.get("tol_s", 1.0e-6))
    oks, cats, example = [], [], None
    for k in range(max(4, int(crit.get("trials", 10)))):
        min_events = int(rng.integers(3, 6))
        case = _t5_case(rng, k, min_events)
        got, err = _call(target, case["table"].copy(), min_events)
        if err is not None:
            raise err
        cat = _t5_judge(got, case, tol)
        oks.append(cat is None)
        if cat:
            cats.append(cat)
            if example is None:
                first = next(iter(case["want"].items()), None)
                example = {"inputs": {"rows": len(case["table"]), "min_events": min_events},
                           "got": (got.head(3).to_dict("records") if _is_frame(got, T5_COLUMNS)
                                   else type(got).__name__),
                           "error": (f"expected for {first[0]}: n {first[1][0]}, mean_s {first[1][1]:.4f}, "
                                     f"se_s {first[1][2]:.4f}, label {first[1][3]!r}") if first else "no rows"}
    category = _first(cats, T5_PRIORITY)
    if category is not None:
        return outcome_from_cases(np.array(oks), category=category, example=example)
    real, cat = _t5_real(target, ctx.get("reader"), ctx.get("slug"), crit)
    ok = np.array(oks + real, dtype=bool)
    note = ("The check also ran your function on your two archive files, read with your reader; it tests only "
            "properties (rows, outliers, labels) and never prints the values.")
    return outcome_from_cases(ok, category=cat, real_data=True, note=note)
