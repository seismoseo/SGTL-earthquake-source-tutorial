"""Checkers for M02 (figures and maps).

Where the truth comes from:

* T1: by construction: fresh magnitudes become diameters through the package's forward helper
  ``sgtl_tutorial.plot.mag_size_cm``, and the student's inverse must give the magnitudes back.
* T2, T5: made-up catalogs whose years (and, for T5, distances) are fixed by construction; years are
  read with NumPy ``datetime64`` arithmetic and counted with ``numpy.bincount``. The real-data case of
  T5 uses ``pyproj`` geodesics on the WGS84 ellipsoid and never prints its counts.
* T3, T4: properties of the figure the student's function returns (matplotlib) or of the PyGMT calls
  it makes (recorded while it runs). Style beyond these properties is judged by the mentor's rubric.
"""
from __future__ import annotations

import ast
import contextlib
import functools
import inspect
import re
import textwrap
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from . import Outcome, outcome_from_cases, within_tol

KST = "+09:00"


# ----------------------------------------------------------------------------- small helpers
def _crit(ctx: Any, key: str, default: Any) -> Any:
    crit = ctx.get("criteria") or {}
    return crit.get(key, default)


def _fail(category: str, n_cases: int, n_failed: int = 1, *, example: Optional[dict] = None,
          real_data: bool = False, note: Optional[str] = None) -> Outcome:
    details: Dict[str, Any] = {"real_data": bool(real_data)}
    if example:
        details["example"] = example
    if note:
        details["note"] = note
    return Outcome(passed=False, n_cases=int(n_cases), n_failed=max(1, int(n_failed)), category=category,
                   message="", details=details)


def _float_array(value: Any) -> Optional[np.ndarray]:
    """``value`` as a float array, or None when it is not numeric."""
    if value is None:
        return None
    try:
        out = np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        return None
    return out


def _calendar_years(times: Any, offset: str = "+00:00") -> np.ndarray:
    """Calendar year of each time-zone-aware timestamp, on the clock of ``offset`` (NumPy arithmetic)."""
    idx = pd.DatetimeIndex(times)
    hours = int(offset[:3])
    naive = idx.tz_convert("UTC").tz_localize(None) + pd.Timedelta(hours=hours)
    return naive.to_numpy().astype("datetime64[Y]").astype(np.int64) + 1970


def _per_year(years: np.ndarray, first: int, last: int) -> np.ndarray:
    inside = (years >= first) & (years <= last)
    return np.bincount((years[inside] - first).astype(np.int64), minlength=last - first + 1)


def _year_timestamps(rng: np.random.Generator, year: int, k: int) -> List[pd.Timestamp]:
    t0 = pd.Timestamp(year=int(year), month=1, day=1, tz="UTC")
    t1 = pd.Timestamp(year=int(year) + 1, month=1, day=1, tz="UTC")
    span_s = int((t1 - t0).total_seconds())
    secs = rng.integers(0, span_s, int(k))
    return [t0 + pd.Timedelta(seconds=int(s)) for s in secs]


def _made_up_years(rng: np.random.Generator) -> Tuple[int, int, np.ndarray, List[int]]:
    """A year range, the event times (UTC) and the empty years inside the range.

    Two busy years just outside the range test the filtering; at least one year inside the range has
    no events; one or two events fall on 31 December after 15:00 UTC (already the next year in Korea).
    """
    first = int(rng.integers(1988, 2016))
    n_years = int(rng.integers(6, 13))
    last = first + n_years - 1
    years = np.arange(first - 2, last + 3)
    per = rng.integers(1, 8, years.size)
    inner = np.arange(first + 1, last)
    n_empty = int(rng.integers(1, max(1, n_years // 3) + 1))
    empty = sorted(int(y) for y in rng.choice(inner, size=min(n_empty, inner.size), replace=False))
    per[np.isin(years, empty)] = 0
    times: List[pd.Timestamp] = []
    for y, k in zip(years, per):
        times += _year_timestamps(rng, int(y), int(k))
    busy = [int(y) for y in range(first, last + 1) if y not in empty]
    for y in rng.choice(busy, size=min(2, len(busy)), replace=False):
        late = pd.Timestamp(year=int(y), month=12, day=31, hour=15, tz="UTC")
        times.append(late + pd.Timedelta(seconds=int(rng.integers(0, 9 * 3600 - 1))))
    order = rng.permutation(len(times))
    utc = pd.DatetimeIndex([times[i] for i in order]).as_unit("ns")
    return first, last, utc, empty


def _catalog_from_times(rng: np.random.Generator, utc: pd.DatetimeIndex, lat: np.ndarray,
                        lon: np.ndarray) -> pd.DataFrame:
    from .. import synth

    n = len(utc)
    df = pd.DataFrame({
        "event_id": [f"CHK{i:05d}" for i in range(1, n + 1)],
        "origin_utc": pd.Series(utc, dtype="datetime64[ns, UTC]"),
        "latitude": np.round(np.asarray(lat, dtype=float), 4),
        "longitude": np.round(np.asarray(lon, dtype=float), 4),
        "depth_km": np.round(rng.uniform(2.0, 20.0, n), 1),
        "ml": synth.gr_magnitudes(rng, n, b=1.0, mc=0.8, dm=0.1),
    })
    df.insert(2, "origin_kst", df["origin_utc"].dt.tz_convert(synth.KST))
    df.attrs["source"] = "made-up catalog for a check; not real earthquakes"
    return df


def _series_problem(res: Any, first: int, last: int, empty: Sequence[int]) -> Tuple[Optional[str], str]:
    """(category, what was found) for the shape of a yearly-count Series; (None, '') when the shape is right."""
    if not isinstance(res, pd.Series):
        return "index-type", f"a {type(res).__name__}, not a pandas Series"
    idx = res.index
    if isinstance(idx, pd.MultiIndex) or not pd.api.types.is_integer_dtype(idx.dtype) or \
            pd.api.types.is_bool_dtype(idx.dtype):
        return "index-type", f"an index of type {idx.dtype}"
    got = np.asarray(idx, dtype=np.int64)
    want = np.arange(first, last + 1)
    if np.array_equal(got, want):
        return None, ""
    if got.size and (got.min() < first - 60 or got.max() > last + 60):
        return "index-type", f"index values from {got.min()} to {got.max()}, which do not look like years"
    if set(got.tolist()) == set(want.tolist()):
        return "index-type", "the right years, but not once each in increasing order"
    missing = sorted(set(want.tolist()) - set(got.tolist()))
    extra = sorted(set(got.tolist()) - set(want.tolist()))
    if not extra and missing and set(missing) <= set(int(y) for y in empty):
        return "missing-zero-years", f"years {missing} are missing"
    return "off-by-one", (f"index from {got.min()} to {got.max()}" if got.size else "an empty Series") + \
        (f"; missing {missing}" if missing else "") + (f"; extra {extra}" if extra else "")


def _plain_source(func: Any, depth: int = 2) -> List[ast.AST]:
    """Syntax trees of ``func`` and of the same-notebook helper functions it calls (``depth`` levels)."""
    out: List[ast.AST] = []
    seen: set = set()

    def visit(f: Any, level: int) -> None:
        f = inspect.unwrap(f) if callable(f) else f
        if id(f) in seen:
            return
        seen.add(id(f))
        try:
            tree = ast.parse(textwrap.dedent(inspect.getsource(f)))
        except (OSError, TypeError, SyntaxError, IndentationError):
            return
        out.append(tree)
        if level >= depth:
            return
        glb = getattr(f, "__globals__", {}) or {}
        home = getattr(f, "__module__", None)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in glb:
                obj = glb[node.id]
                if inspect.isfunction(obj) and getattr(obj, "__module__", None) == home:
                    visit(obj, level + 1)

    visit(func, 0)
    return out


# ----------------------------------------------------------------------------- M02-T1
def _t1_wrong(truth: Any, got: Any) -> str:
    """Failure category for magnitudes that miss: 'log-base' or 'algebra'.

    'log-base' when the values lie exactly on a straight line in the true magnitudes whose slope is the
    slope of a base-10 or base-2 logarithm read in place of the natural one (times 1, 2 or 1/2, so that a
    slipped factor 2 on top of it still counts); anything else is 'algebra'.
    """
    truth = np.asarray(truth, dtype=float).ravel()
    got = np.asarray(got, dtype=float).ravel()
    if truth.size < 3 or got.size != truth.size or not np.isfinite(got).all():
        return "algebra"
    design = np.column_stack([truth, np.ones_like(truth)])
    coef, *_ = np.linalg.lstsq(design, got, rcond=None)
    if np.abs(design @ coef - got).max() > 1e-6 * max(1.0, float(np.abs(got).max())):
        return "algebra"
    slope = float(coef[0])
    for ln_base in (np.log(10.0), np.log(2.0)):
        if any(abs(slope * ln_base - k) <= 1e-4 * k for k in (0.5, 1.0, 2.0)):
            return "log-base"
    return "algebra"


def check_T1(target: Any, ctx: Any) -> Outcome:
    """Magnitude from marker diameter (cm), the inverse of the house rule; truth by construction.

    Fresh magnitudes are turned into diameters with the package's forward helper
    ``sgtl_tutorial.plot.mag_size_cm``; the student's function must give those magnitudes back.
    """
    from ..plot import mag_size_cm

    rng = ctx.rng
    rel = float(_crit(ctx, "rel_tol", 1e-9))
    tol_abs = float(_crit(ctx, "abs_tol", 1e-9))
    trials = max(40, int(_crit(ctx, "trials", 220)))
    n_total = trials

    def diameters(mags: np.ndarray) -> np.ndarray:
        return np.asarray(mag_size_cm(np.asarray(mags, dtype=float)), dtype=float)

    def off_by(got: float, want: float) -> str:
        return f"{abs(got - want):.3g} magnitude units off"

    # 1. one number at a time (an error here is shown as the student's own exception)
    m_one = np.append(rng.uniform(-1.0, 7.0, 5), 0.0)
    d_one = diameters(m_one)
    got_one = np.empty(m_one.size)
    for i, d in enumerate(d_one):
        got = target(float(d))
        arr = _float_array(got)
        if arr is None or arr.size != 1:
            return _fail("vectorize", n_total, example={"inputs": {"size_cm": float(d)}, "got": got})
        got_one[i] = float(arr.reshape(-1)[0])
    ok = within_tol(got_one, m_one, rel_tol=rel, abs_tol=tol_abs)
    if not ok.all():
        i = int(np.flatnonzero(~ok)[0])
        return _fail(_t1_wrong(m_one, got_one), n_total, n_failed=int((~ok).sum()),
                     example={"inputs": {"size_cm": float(d_one[i])}, "got": float(got_one[i]),
                              "error": off_by(got_one[i], m_one[i])})

    # 2. a NumPy array, a Python list and a pandas Series (vectorized use)
    n_arr = n_total - m_one.size - 9
    batches = [("a NumPy array", rng.uniform(-1.0, 7.5, n_arr)),
               ("a Python list", rng.uniform(0.0, 5.0, 4)),
               ("a pandas Series", rng.uniform(0.5, 4.5, 5))]
    for label, mags in batches:
        sizes = diameters(mags)
        if label == "a Python list":
            values: Any = [float(v) for v in sizes]
        elif label == "a pandas Series":
            values = pd.Series(sizes, index=[f"event{i}" for i in range(1, sizes.size + 1)])
        else:
            values = sizes.copy()
        what = f"{label} of {sizes.size} diameters"
        try:
            got = target(values)
        except NotImplementedError:
            raise
        except Exception as exc:  # scalar-only code (math.log, if/else on a number, list arithmetic) breaks here
            return _fail("vectorize", n_total, n_failed=sizes.size,
                         example={"inputs": what, "got": f"{type(exc).__name__}: {exc}"})
        if label == "a NumPy array" and not isinstance(got, (np.ndarray, pd.Series)):
            return _fail("vectorize", n_total, n_failed=sizes.size,
                         example={"inputs": what, "got": f"a {type(got).__name__}, not an array"})
        arr = _float_array(got)
        if arr is None or arr.shape != (sizes.size,):
            shape = None if arr is None else arr.shape
            return _fail("vectorize", n_total, n_failed=sizes.size,
                         example={"inputs": what, "got": f"a result of shape {shape}"})
        ok = within_tol(arr, mags, rel_tol=rel, abs_tol=tol_abs)
        if not ok.all():
            i = int(np.flatnonzero(~ok)[0])
            return _fail(_t1_wrong(mags, arr), n_total, n_failed=int((~ok).sum()),
                         example={"inputs": {"size_cm": float(sizes[i]), "within": what}, "got": float(arr[i]),
                                  "error": off_by(float(arr[i]), float(mags[i]))})
    return outcome_from_cases(np.ones(n_total, dtype=bool))


# ----------------------------------------------------------------------------- M02-T2
def check_T2(target: Any, ctx: Any) -> Outcome:
    """Events per UTC year with every year present; truth by construction (bincount of known years)."""
    rng = ctx.rng
    n_cases = max(2, int(_crit(ctx, "cases", 4)))
    float_note = None
    for case in range(n_cases):
        first, last, utc, empty = _made_up_years(rng)
        lat = rng.uniform(34.0, 38.0, len(utc))
        lon = rng.uniform(126.0, 129.5, len(utc))
        df = _catalog_from_times(rng, utc, lat, lon)
        truth = _per_year(_calendar_years(df["origin_utc"]), first, last)
        korea = _per_year(_calendar_years(df["origin_kst"], KST), first, last)
        inputs = {"start_year": first, "end_year": last, "n_events": len(df), "empty_years": empty}
        res = target(df.copy(), first, last)
        cat, found = _series_problem(res, first, last, empty)
        if cat:
            return _fail(cat, n_cases, example={"inputs": inputs, "got": found})
        vals = _float_array(res.to_numpy())
        if vals is None:
            return _fail("counts", n_cases, example={"inputs": inputs, "got": f"values of type {res.dtype}"})
        zero_idx = np.isin(np.arange(first, last + 1), empty)
        if np.isnan(vals).any():
            bad = np.isnan(vals)
            cat = "missing-zero-years" if np.array_equal(bad, zero_idx) or (bad <= zero_idx).all() else "counts"
            return _fail(cat, n_cases, example={"inputs": inputs, "got": f"NaN for years "
                                                f"{np.arange(first, last + 1)[bad].tolist()}"})
        if not np.array_equal(vals, truth.astype(float)):
            wrong = np.arange(first, last + 1)[vals != truth]
            if np.array_equal(vals, korea.astype(float)):
                return _fail("time-zone", n_cases, example={"inputs": inputs, "got": f"wrong counts for years "
                                                            f"{wrong.tolist()}"})
            return _fail("counts", n_cases, example={"inputs": inputs, "got": dict(zip(
                [int(y) for y in wrong[:4]], [float(v) for v in vals[np.isin(np.arange(first, last + 1), wrong[:4])]]))})
        if not pd.api.types.is_integer_dtype(res.dtype):
            float_note = ("Note: your counts are stored as " + str(res.dtype) + "; counts are whole numbers, "
                          "so an integer type is cleaner (for example .astype(int)).")
    return outcome_from_cases(np.ones(n_cases, dtype=bool), note=float_note)


# ----------------------------------------------------------------------------- M02-T3
_BRITISH = ("colour", "centre", "metre", "grey")
_TITLES = ("Practice catalog", "Synthetic events", "Made-up sequence", "Check catalog, test run")


def _strip_math(text: str) -> str:
    return re.sub(r"\$[^$]*\$", " ", text or "")


def _case_problem(text: str) -> Optional[str]:
    """Why ``text`` is not sentence case, or None."""
    raw = (text or "").strip()
    if not raw:
        return None
    raw = re.sub(r"^\(?[a-z]\)\s+", "", raw)  # a panel letter such as "(a) " may stay lower case
    plain = _strip_math(raw)
    letters = [c for c in plain if c.isalpha()]
    if not letters:
        return None  # only a symbol, such as the magnitude label
    if len(letters) >= 4 and all(c.isupper() for c in letters):
        return "written in capitals"
    first_word = re.search(r"[^\W_]+", plain)
    if not raw.startswith("$") and first_word and first_word.group(0)[0].isalpha() and \
            first_word.group(0)[0].islower():
        return "starts with a lower-case letter"
    long_words = [w for w in re.findall(r"[A-Za-z]+", plain) if len(w) >= 4]
    if len(long_words) >= 2 and all(w[0].isupper() for w in long_words):
        return "has Every Word Capitalized"
    return None


def _is_date_axis(axis: Any) -> bool:
    conv = axis.get_converter() if hasattr(axis, "get_converter") else getattr(axis, "converter", None)
    names = [type(conv).__name__ if conv is not None else "", type(axis.get_major_formatter()).__name__]
    return any(("Date" in n) or ("Period" in n) for n in names)


def _plotted_y(ax: Any) -> np.ndarray:
    ys: List[np.ndarray] = []
    for line in ax.get_lines():
        xy = np.ma.filled(np.ma.asarray(line.get_xydata(), dtype=float), np.nan)
        if xy.ndim == 2 and xy.shape[1] == 2:
            ys.append(xy[:, 1])
    for coll in ax.collections:
        offs = coll.get_offsets()
        if offs is not None and len(offs):
            offs = np.ma.filled(np.ma.asarray(offs, dtype=float), np.nan)
            if offs.ndim == 2 and offs.shape[1] == 2:
                ys.append(offs[:, 1])
        if hasattr(coll, "get_segments"):
            for seg in coll.get_segments():
                seg = np.asarray(seg, dtype=float)
                if seg.ndim == 2 and seg.shape[1] == 2:
                    ys.append(seg[:, 1])
    return np.concatenate(ys) if ys else np.empty(0)


def _figure_texts(fig: Any) -> List[Tuple[str, str]]:
    """(where, text) of every label, title and legend entry in the figure."""
    out: List[Tuple[str, str]] = []
    for i, ax in enumerate(fig.axes):
        out += [(f"axes {i} x label", ax.get_xlabel()), (f"axes {i} y label", ax.get_ylabel())]
        out += [(f"axes {i} title", ax.get_title(loc=loc)) for loc in ("center", "left", "right")]
        leg = ax.get_legend()
        if leg is not None:
            out += [(f"axes {i} legend", t.get_text()) for t in leg.get_texts()]
            out.append((f"axes {i} legend title", leg.get_title().get_text()))
    sup = getattr(fig, "_suptitle", None)
    if sup is not None:
        out.append(("figure title", sup.get_text()))
    for leg in getattr(fig, "legends", []):
        out += [("figure legend", t.get_text()) for t in leg.get_texts()]
    return [(w, t) for w, t in out if t and t.strip()]


def check_T3(target: Any, ctx: Any) -> Outcome:
    """Properties of a time-magnitude figure on made-up catalogs."""
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure
    from matplotlib.text import Text

    from .. import synth

    rng = ctx.rng
    n_cases = max(1, int(_crit(ctx, "cases", 2)))
    max_chars = int(_crit(ctx, "max_title_chars", 40))
    titles = list(rng.permutation(_TITLES))
    for case in range(n_cases):
        n = int(rng.integers(25, 121))
        y0 = int(rng.integers(2000, 2021))
        span = int(rng.integers(1, 6))
        df = synth.synthetic_catalog(rng, n, start=f"{y0}-01-01", end=f"{y0 + span}-01-01")
        title = str(titles[case % len(titles)])
        inputs = {"n_events": n, "years": f"{y0}-{y0 + span - 1}", "title": title}
        before = set(plt.get_fignums())
        res = target(df.copy(), title)
        try:
            out = _t3_case(res, df, title, max_chars, Figure, Text)
        finally:
            for num in set(plt.get_fignums()) - before:
                plt.close(num)
            if isinstance(res, Figure):
                plt.close(res)
        if out is not None:
            cat, found = out
            return _fail(cat, n_cases, example={"inputs": inputs, "got": found})
    return outcome_from_cases(np.ones(n_cases, dtype=bool),
                              note="Your mentor still looks at how the figure reads (rubric: correctness of figures).")


def _t3_case(res: Any, df: pd.DataFrame, title: str, max_chars: int, Figure: Any, Text: Any):
    if not isinstance(res, Figure):
        return "not-a-figure", f"a {type(res).__name__}"
    if not res.axes:
        return "not-a-figure", "a figure without axes"
    date_axes = [ax for ax in res.axes if _is_date_axis(ax.xaxis)]
    if not date_axes:
        return "date-axis", "no axes whose x axis holds dates"
    ax = date_axes[0]
    ys = _plotted_y(ax)
    ys = ys[np.isfinite(ys)]
    mags = df["ml"].to_numpy(dtype=float)
    if ys.size == 0:
        return "data", "nothing plotted on the time axis"
    nearest = np.abs(ys[:, None] - mags[None, :]).min(axis=0)
    missing = int((nearest > 1e-6).sum())
    if missing:
        return "data", f"{missing} of {mags.size} magnitudes are not among the plotted y values"
    if not ax.get_xlabel().strip():
        return "labels", "an empty x label"
    if "M" not in ax.get_ylabel():
        return "labels", f"y label {ax.get_ylabel()!r}"
    for where, text in _figure_texts(res):
        why = _case_problem(text)
        if why:
            return "sentence-case", f"{where} {text!r} {why}"
    shown = [t for w, t in _figure_texts(res) if "title" in w and "legend" not in w]
    if not any(title in t for t in shown):
        return "title", f"titles {shown}" if shown else "no title"
    longest = max(shown, key=len)
    if len(longest) > max_chars:
        return "title", f"a title of {len(longest)} characters"
    for obj in res.findobj(Text):
        low = (obj.get_text() or "").lower()
        hit = next((w for w in _BRITISH if w in low), None)
        if hit:
            return "spelling", f"the text {obj.get_text()!r}"
    hidden = [s for s in ("left", "right", "top", "bottom") if not ax.spines[s].get_visible()]
    if hidden:
        return "frame", f"hidden frame lines: {', '.join(hidden)}"
    return None


# ----------------------------------------------------------------------------- M02-T4
_RECORDED = ("plot", "text", "basemap", "coast")


@contextlib.contextmanager
def _recording(pygmt: Any) -> Iterator[List[Tuple[str, Dict[str, Any]]]]:
    """Record the arguments of some pygmt.Figure methods while the student's function runs."""
    calls: List[Tuple[str, Dict[str, Any]]] = []
    saved = {name: getattr(pygmt.Figure, name) for name in _RECORDED}

    def make(name: str, orig: Any) -> Any:
        sig = inspect.signature(orig)

        @functools.wraps(orig)
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            try:
                bound = sig.bind_partial(self, *args, **kwargs).arguments
                rec = {k: v for k, v in bound.items() if k not in ("self", "kwargs")}
                rec.update(bound.get("kwargs") or {})
            except TypeError:
                rec = dict(kwargs)
            calls.append((name, rec))
            return orig(self, *args, **kwargs)

        return wrapper

    try:
        for name, orig in saved.items():
            setattr(pygmt.Figure, name, make(name, orig))
        yield calls
    finally:
        for name, orig in saved.items():
            setattr(pygmt.Figure, name, orig)


def _xy(rec: Dict[str, Any]) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    x, y = rec.get("x"), rec.get("y")
    if x is None or y is None:
        return None, None
    xa, ya = _float_array(x), _float_array(y)
    if xa is None or ya is None:
        return None, None
    xa, ya = np.atleast_1d(xa).ravel(), np.atleast_1d(ya).ravel()
    return (xa, ya) if xa.size == ya.size else (None, None)


def _key(lon: float, lat: float) -> Tuple[float, float]:
    return (round(float(lon), 5), round(float(lat), 5))


def _event_sizes(calls: List[Tuple[str, Dict[str, Any]]], df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray, int]:
    """(magnitudes, sizes) of the events drawn with a per-point ``size``, and how many events were found."""
    sized: Dict[Tuple[float, float], List[float]] = {}
    for name, rec in calls:
        if name != "plot" or rec.get("size") is None:
            continue
        xa, ya = _xy(rec)
        sa = _float_array(rec.get("size"))
        if xa is None or sa is None:
            continue
        sa = np.atleast_1d(sa).ravel()
        if sa.size != xa.size:
            continue
        for lo, la, s in zip(xa, ya, sa):
            sized.setdefault(_key(lo, la), []).append(float(s))
    groups: Dict[Tuple[float, float], List[float]] = {}
    for lo, la, m in zip(df["longitude"], df["latitude"], df["ml"]):
        groups.setdefault(_key(lo, la), []).append(float(m))
    mags: List[float] = []
    sizes: List[float] = []
    found = 0
    for key, ms in groups.items():
        # events at the same spot: a size that grows with magnitude pairs sorted sizes with sorted magnitudes
        ss = sorted(sized.get(key, []))
        ms = sorted(ms)
        k = min(len(ss), len(ms))
        found += k
        mags += ms[:k]
        sizes += ss[:k]
    return np.asarray(mags, dtype=float), np.asarray(sizes, dtype=float), found


def _grows_with_magnitude(mags: np.ndarray, sizes: np.ndarray) -> bool:
    if mags.size == 0 or not np.isfinite(sizes).all() or (sizes <= 0).any():
        return False
    levels = np.unique(np.round(mags, 6))
    per_level = []
    for lev in levels:
        s = sizes[np.isclose(mags, lev, atol=1e-6)]
        if s.max() - s.min() > 1e-6 * max(1.0, abs(s.max())):
            return False  # one magnitude, several sizes: the size does not follow the magnitude
        per_level.append(float(s.mean()))
    steps = np.diff(per_level)
    if (steps < -1e-9 * max(per_level)).any():
        return False
    return levels.size < 2 or float(max(per_level) - min(per_level)) > 0.0


def _scale_lengths_km(calls: List[Tuple[str, Dict[str, Any]]]) -> List[Optional[float]]:
    out: List[Optional[float]] = []
    for name, rec in calls:
        if name not in ("basemap", "coast"):
            continue
        for key in ("map_scale", "L"):
            spec = rec.get(key)
            if spec is None or spec is False:
                continue
            m = re.search(r"\+w(\d+(?:\.\d+)?)([a-zA-Z]?)", str(spec))
            if not m:
                out.append(None)
                continue
            val, unit = float(m.group(1)), m.group(2)
            out.append(val / 1000.0 if unit == "e" else (val if unit in ("", "k") else None))
    return out


def _uses_house_style(func: Any) -> Optional[bool]:
    trees = _plain_source(func)
    if not trees:
        return None
    strings: List[str] = []
    for tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "gmt_style":
                return True
            if isinstance(node, ast.Name) and node.id == "gmt_style":
                return True
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                strings.append(node.value)
    joined = " ".join(strings)
    return "ddd.xx" in joined and "plain" in joined


def _stations_within(radius_km: float, lat0: float, lon0: float) -> pd.DataFrame:
    from pyproj import Geod

    from .. import data as sdata

    sta = sdata.stations().dropna(subset=["latitude", "longitude"])
    n = len(sta)
    _a, _b, dist = Geod(ellps="WGS84").inv(np.full(n, lon0), np.full(n, lat0), sta["longitude"].to_numpy(),
                                           sta["latitude"].to_numpy())
    return sta.loc[np.asarray(dist) / 1000.0 <= radius_km].reset_index(drop=True)


def _padded_region(lons: np.ndarray, lats: np.ndarray, pad: float = 0.15) -> List[float]:
    lo = [np.floor((np.min(lons) - pad) * 20) / 20, np.ceil((np.max(lons) + pad) * 20) / 20]
    la = [np.floor((np.min(lats) - pad) * 20) / 20, np.ceil((np.max(lats) + pad) * 20) / 20]
    return [float(lo[0]), float(lo[1]), float(la[0]), float(la[1])]


def _t4_inputs(rng: np.random.Generator, ctx: Any) -> List[Dict[str, Any]]:
    from .. import data as sdata
    from .. import synth

    # case 1: a made-up sequence with made-up stations
    lat_c = float(rng.uniform(34.8, 37.6))
    lon_c = float(rng.uniform(126.6, 128.9))
    n = int(rng.integers(12, 31))
    ev = synth.synthetic_catalog(rng, n, lat_range=(lat_c - 0.08, lat_c + 0.08),
                                 lon_range=(lon_c - 0.1, lon_c + 0.1), mc=0.5)
    k = int(rng.integers(4, 9))
    sta = pd.DataFrame({
        "network": ["XX"] * k,
        "station": [f"SY{i:02d}" for i in range(1, k + 1)],
        "latitude": np.round(lat_c + rng.uniform(-0.5, 0.5, k), 4),
        "longitude": np.round(lon_c + rng.uniform(-0.6, 0.6, k), 4),
        "start_date": pd.to_datetime(["2015-01-01"] * k),
    })
    region = _padded_region(np.r_[ev["longitude"], sta["longitude"]], np.r_[ev["latitude"], sta["latitude"]])
    cases = [{"label": "made-up catalog", "df": ev, "stations": sta, "region": region,
              "scale_km": float(rng.choice([5.0, 10.0, 20.0])), "real": False}]
    # case 2: the Sangju sequence with the stations within the radius of its center
    seq = sdata.sequence("sangju2019")
    spec = seq.attrs.get("sequence", {})
    lat0, lon0 = float(spec.get("center_lat", 36.5)), float(spec.get("center_lon", 128.1))
    near = _stations_within(float(_crit(ctx, "station_radius_km", 100.0)), lat0, lon0)
    region2 = ctx.get("region")
    if region2 is None:
        region2 = _padded_region(np.r_[seq["longitude"], near["longitude"]], np.r_[seq["latitude"], near["latitude"]])
    scale2 = ctx.get("scale_km") or 50.0
    cases.append({"label": "Sangju sequence", "df": seq, "stations": near, "region": [float(v) for v in region2],
                  "scale_km": float(scale2), "real": True})
    return cases


def check_T4(target: Any, ctx: Any) -> Outcome:
    """Properties of the PyGMT map: type, region, magnitude-sized circles, stations, scale bar, house style."""
    from ..session import gmt_guard

    gmt_guard()
    import pygmt

    from ..plot import mag_size_cm

    cases = _t4_inputs(ctx.rng, ctx)
    n_cases = len(cases)
    style_ok = _uses_house_style(target)
    notes: List[str] = []
    if style_ok is None:
        notes.append("Note: the source of your function was not available, so the house-style rule was not checked.")
    for case in cases:
        df, sta, region, km, real = case["df"], case["stations"], case["region"], case["scale_km"], case["real"]
        inputs = {"case": case["label"], "region": region, "scale_km": km}
        with _recording(pygmt) as calls:
            res = target(df.copy(), sta.copy(), list(region), km)

        def fail(cat: str, found: str) -> Outcome:
            return _fail(cat, n_cases, example={"inputs": inputs, "got": found}, real_data=real)

        if not isinstance(res, pygmt.Figure):
            return fail("not-a-figure", f"a {type(res).__name__}")
        try:
            shown = [float(v) for v in np.asarray(res.region, dtype=float)]
        except Exception as exc:  # noqa: BLE001 - a figure that was never given a region
            return fail("region", f"no map region ({type(exc).__name__})")
        w, e, s, n = region
        inside = ((df["longitude"] >= w) & (df["longitude"] <= e) & (df["latitude"] >= s) &
                  (df["latitude"] <= n)).all()
        if not np.allclose(shown, region, atol=1e-6) or not bool(inside):
            return fail("region", f"map region {shown}" + ("" if inside else "; some events lie outside it"))
        mags, sizes, found = _event_sizes(calls, df)
        if found < len(df) or not _grows_with_magnitude(mags, sizes):
            got = (f"per-event sizes for {found} of {len(df)} events" if found < len(df)
                   else "sizes that do not grow with magnitude")
            return fail("marker-size", got)
        if not bool(within_tol(sizes, mag_size_cm(mags), rel_tol=1e-6).all()):
            msg = ("Note: your marker sizes grow with magnitude but are not the house size "
                   "0.025*sqrt(5*exp(2M)) cm; your mentor will ask why.")
            if msg not in notes:
                notes.append(msg)
        drawn = set()
        for name, rec in calls:
            if name == "plot":
                xa, ya = _xy(rec)
                if xa is not None:
                    drawn.update(_key(a, b) for a, b in zip(xa, ya))
        labels: List[str] = []
        for name, rec in calls:
            if name == "text" and rec.get("text") is not None:
                txt = rec.get("text")
                labels += [str(t) for t in (np.atleast_1d(np.asarray(txt, dtype=object)).ravel())]
        no_symbol = [c for c, lo, la in zip(sta["station"], sta["longitude"], sta["latitude"])
                     if _key(lo, la) not in drawn]
        no_label = [c for c in sta["station"] if not any(str(c) in t for t in labels)]
        if no_symbol or no_label:
            got = (f"{len(no_symbol)} of {len(sta)} stations without a symbol" if no_symbol else
                   f"{len(no_label)} of {len(sta)} station codes not written")
            return fail("stations", got)
        lengths = _scale_lengths_km(calls)
        if not lengths:
            return fail("scale-bar", "no map_scale in fig.basemap or fig.coast")
        if not any(v is not None and abs(v - km) <= 1e-6 * km for v in lengths):
            return fail("scale-bar", f"scale bar lengths {lengths} km")
        if style_ok is False:
            return fail("house-style", "no gmt_style() and not both 'ddd.xx' and 'plain' in your function")
    notes.append("Passing checks the properties above; how the map looks is judged by your mentor (rubric).")
    return outcome_from_cases(np.ones(n_cases, dtype=bool), note=" ".join(notes))


# ----------------------------------------------------------------------------- M02-T5
def _t5_made_up(rng: np.random.Generator, radius: float, rel: float) -> Dict[str, Any]:
    """Events at known geodesic distances from a known center; none within 2*rel of the radius."""
    from pyproj import Geod

    first, last, utc, empty = _made_up_years(rng)
    n = len(utc)
    lat0 = float(rng.uniform(34.5, 37.8))
    lon0 = float(rng.uniform(126.3, 129.3))
    near = rng.random(n) < 0.55
    dist = np.where(near, rng.uniform(0.0, 1.0 - 2 * rel, n), rng.uniform(1.0 + 2 * rel, 2.5, n)) * radius
    az = rng.uniform(0.0, 360.0, n)
    lon, lat, _ = Geod(ellps="WGS84").fwd(np.full(n, lon0), np.full(n, lat0), az, dist * 1000.0)
    df = _catalog_from_times(rng, utc, lat, lon)
    years = _calendar_years(df["origin_utc"])
    counts = _per_year(years[near], first, last)
    # an empty year here means: no event inside the radius in that year
    empty_inside = [int(y) for y, c in zip(range(first, last + 1), counts) if c == 0]
    return {"df": df, "lat0": lat0, "lon0": lon0, "first": first, "last": last, "lo": counts, "hi": counts,
            "empty": empty_inside}


def _t5_real_inputs(rng: np.random.Generator, ctx: Any) -> Dict[str, Any]:
    """Inputs for the real catalog around the Sangju mainshock. No expected counts (DESIGN.md section 4)."""
    from .. import data as sdata

    cat = sdata.kma_catalog()
    seq = sdata.sequence("sangju2019")
    big = (seq.attrs.get("sequence") or {}).get("largest_event") or {}
    row = cat.loc[cat["event_id"].astype(str) == str(big.get("event_id"))]
    if row.empty:
        row = seq.loc[[seq["ml"].idxmax()]]
    r_min = float(_crit(ctx, "radius_min_km", 10.0))
    r_max = float(_crit(ctx, "radius_max_km", 30.0))
    radius = float(np.round(rng.uniform(r_min, r_max), 1))
    first = int(rng.integers(1990, 2006))
    last = int(rng.integers(2020, 2026))
    return {"df": cat, "lat0": float(row["latitude"].iloc[0]), "lon0": float(row["longitude"].iloc[0]),
            "radius": radius, "first": first, "last": last}


def _t5_real_problem(target: Any, case: Dict[str, Any]) -> Tuple[Optional[str], str]:
    """Properties of the student's own counts on the real catalog: every year once, whole non-negative
    numbers, and never fewer events inside a larger circle (the same function at 1.5 times the radius)."""
    counts = []
    for scale in (1.0, 1.5):
        res = target(case["df"].copy(), case["lat0"], case["lon0"], case["radius"] * scale, case["first"],
                     case["last"])
        cat, found = _series_problem(res, case["first"], case["last"], [])
        if cat:
            return ("year-range" if cat in ("missing-zero-years", "off-by-one") else cat), found
        vals = _float_array(res.to_numpy())
        if vals is None or np.isnan(vals).any():
            return "year-range", "missing (NaN) counts"
        if (vals < 0).any() or not np.allclose(vals, np.round(vals)):
            return "distance", "counts that are negative or not whole numbers"
        counts.append(vals)
    if (counts[1] < counts[0]).any():
        return "distance", "fewer events inside a larger circle than inside a smaller one in some years"
    return None, ""


def check_T5(target: Any, ctx: Any) -> Outcome:
    """Yearly counts within a radius: made-up events at known distances (truth by construction), then
    properties of the student's own counts on the real catalog (the check never counts the real catalog)."""
    rng = ctx.rng
    rel = float(_crit(ctx, "distance_rel_tol", 0.005))
    r_min = float(_crit(ctx, "radius_min_km", 10.0))
    r_max = float(_crit(ctx, "radius_max_km", 30.0))
    radius = float(np.round(rng.uniform(r_min, r_max), 1))
    made = _t5_made_up(rng, radius, rel)
    n_cases = 2
    inputs = {"case": "made-up catalog", "lat0": round(made["lat0"], 4), "lon0": round(made["lon0"], 4),
              "radius_km": radius, "start_year": made["first"], "end_year": made["last"]}
    res = target(made["df"].copy(), made["lat0"], made["lon0"], radius, made["first"], made["last"])
    cat, found = _series_problem(res, made["first"], made["last"], made["empty"])
    if cat == "missing-zero-years" or cat == "off-by-one":
        cat = "year-range"
    if cat:
        return _fail(cat, n_cases, example={"inputs": inputs, "got": found}, real_data=False)
    vals = _float_array(res.to_numpy())
    if vals is None or np.isnan(vals).any():
        return _fail("year-range", n_cases, example={"inputs": inputs, "got": "missing (NaN) counts"},
                     real_data=False)
    bad = (vals < made["lo"]) | (vals > made["hi"])
    if bad.any():
        yrs = np.arange(made["first"], made["last"] + 1)[bad]
        return _fail("distance", n_cases, n_failed=int(bad.sum()), real_data=False,
                     example={"inputs": inputs, "got": f"wrong counts in {int(bad.sum())} years "
                              f"(first: {int(yrs[0])})"})
    real = _t5_real_inputs(rng, ctx)
    cat, found = _t5_real_problem(target, real)
    if cat:
        inputs = {"case": "Sangju mainshock, KMA catalog", "lat0": round(real["lat0"], 4),
                  "lon0": round(real["lon0"], 4), "radius_km": real["radius"], "start_year": real["first"],
                  "end_year": real["last"]}
        return _fail(cat, n_cases, example={"inputs": inputs, "got": found}, real_data=True)
    return outcome_from_cases(np.ones(n_cases, dtype=bool))
