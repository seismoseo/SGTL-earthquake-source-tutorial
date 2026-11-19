"""E11 · Detection explorer: your threshold, your detections and the null test, under two sliders.

Controls: ``k`` (the threshold in MADs above the median), the minimum gap between two detections (s), and the stretch
of time shown. The explorer draws the network cross-correlation of the records and, below it, that of the null
records (for example the records reversed in time). On the records it draws the threshold and the detections that
your ``detect`` function returns; on the null records the same threshold and the peaks that your ``peaks`` function
finds there at that threshold, the false detections.

What the explorer does itself: it only draws. To keep redraws fast on long records it thins each curve for the
picture (the largest and the smallest value of every pixel column). What it never does itself: a median, a MAD, a
threshold or a peak search. Pass ``detect=`` your function ``detect(cc, delta, k, min_gap_s) -> (times_s, values,
threshold)`` and ``peaks=`` your function ``peaks(cc, delta, threshold, min_gap_s) -> (times_s, values)``
(``mad_detections`` of module M22 and ``picks_from_probability`` of module M21). Without them it shows the curves
only.

Credit: Minseong Seo (SGTL, Seoul National University). License: MIT.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Dict, Optional, Tuple

import numpy as np

from ._common import Explorer, call_yours, func_name, status_html

COLUMNS = 1500                   # pixel columns of the thinned curves


def _as_curve(values: Any, name: str) -> np.ndarray:
    try:
        arr = np.asarray(values, dtype=float)
    except (TypeError, ValueError):
        raise TypeError(f"{name} must be a 1-D sequence of numbers") from None
    if arr.ndim != 1 or arr.size < 8:
        raise ValueError(f"{name} must be a 1-D sequence of at least 8 numbers")
    return arr


def _as_detections(result: Any, size: int, delta: float, with_level: bool) -> Optional[Tuple]:
    """Your result as (times, values[, threshold]) inside the record, or None when it is not that."""
    try:
        parts = tuple(result)
        if len(parts) != (3 if with_level else 2):
            return None
        times = np.asarray(parts[0], dtype=float).ravel()
        values = np.asarray(parts[1], dtype=float).ravel()
        level = float(parts[2]) if with_level else None
    except (TypeError, ValueError):
        return None
    if times.size != values.size or np.any(~np.isfinite(times)) or np.any(times < 0.0) or \
            np.any(times > (size - 1) * delta + 1e-9) or (with_level and not math.isfinite(level)):
        return None
    return (times, values, level) if with_level else (times, values)


def _thin(t: np.ndarray, y: np.ndarray, columns: int = COLUMNS) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """For the picture only: (column times, smallest values, largest values) of y in ``columns`` columns."""
    if y.size <= 2 * columns:
        return t, y, y
    per = int(math.ceil(y.size / columns))
    pad = per * columns - y.size
    padded = np.concatenate([y, np.full(pad, y[-1])])
    blocks = padded.reshape(columns, per)
    times = np.concatenate([t, np.full(pad, t[-1])]).reshape(columns, per)[:, 0]
    return times, blocks.min(axis=1), blocks.max(axis=1)


class DetectionExplorer(Explorer):
    """E11: the network cross-correlation of the records and of null records, with your threshold and detections.

    network_cc : 1-D sequence, the network cross-correlation of the records (one value per sample); never changed
    delta      : sample spacing (s)
    detect     : your function detect(cc, delta, k, min_gap_s) -> (times_s, values, threshold), or None
    peaks      : your function peaks(cc, delta, threshold, min_gap_s) -> (times_s, values), or None
    null_cc    : the network cross-correlation of null records (same length), or None
    starttime  : ObsPy UTCDateTime of the first sample (times in the status line are then given in UTC)
    k          : threshold in MADs to start with
    min_gap_s  : minimum gap (s) to start with
    marks      : {label: UTCDateTime} drawn as vertical lines (needs starttime), for example the KMA events
    """

    def __init__(self, network_cc: Any, delta: float, *, detect: Optional[Callable] = None,
                 peaks: Optional[Callable] = None, null_cc: Any = None, starttime: Any = None, k: float = 8.0,
                 min_gap_s: float = 2.0, marks: Optional[Dict[str, Any]] = None,
                 xlabel: Optional[str] = None) -> None:
        self.cc = _as_curve(network_cc, "network_cc").copy()
        self.null = _as_curve(null_cc, "null_cc").copy() if null_cc is not None else None
        if self.null is not None and self.null.size != self.cc.size:
            raise ValueError("null_cc must have as many values as network_cc")
        try:
            delta = float(delta)
        except (TypeError, ValueError):
            raise TypeError("delta must be a number of seconds") from None
        if not (math.isfinite(delta) and delta > 0.0):
            raise ValueError("delta must be a positive number of seconds")
        for name, func in (("detect", detect), ("peaks", peaks)):
            if func is not None and not callable(func):
                raise TypeError(f"{name} must be one of your functions (or None)")
        super().__init__(9.5, 5.6 if self.null is not None else 3.4)
        self.delta = float(delta)
        self.detect = detect
        self.peaks = peaks
        self.starttime = starttime
        self.marks = dict(marks or {})
        self.xlabel = xlabel or ("Minutes after the first sample" if starttime is None
                                 else f"Minutes after {starttime.strftime('%H:%M:%S')} UTC")
        self.minutes = np.arange(self.cc.size) * self.delta / 60.0
        length_min = float(self.minutes[-1])

        w = self._widgets
        style = {"description_width": "initial"}
        self.k_slider = w.FloatSlider(value=min(max(float(k), 1.0), 30.0), min=1.0, max=30.0, step=0.1,
                                      description="k (MADs)", continuous_update=False, style=style)
        self.gap_slider = w.FloatLogSlider(value=min(max(float(min_gap_s), self.delta), 120.0), base=10,
                                           min=math.log10(self.delta), max=math.log10(120.0), step=0.01,
                                           readout_format=".3g", description="Minimum gap (s)",
                                           continuous_update=False, style=style)
        self.range_slider = w.FloatRangeSlider(value=(0.0, length_min), min=0.0, max=length_min,
                                               step=max(length_min / 2000.0, self.delta / 60.0),
                                               readout_format=".2f", description="Shown (minutes)",
                                               continuous_update=False, style=style, layout=w.Layout(width="70%"))
        for control in (self.k_slider, self.gap_slider, self.range_slider):
            control.observe(self._changed, names="value")
        self.box = w.VBox([w.HBox([self.k_slider, self.gap_slider]), self.range_slider, self.image, self.status])
        self.redraw()

    # ------------------------------------------------------------------------------------------- helpers
    def _when(self, seconds: float) -> str:
        if self.starttime is None:
            return f"{seconds:.2f} s"
        return (self.starttime + float(seconds)).strftime("%H:%M:%S.%f")[:-4]

    def _mark_minutes(self) -> Dict[str, float]:
        out = {}
        if self.starttime is None:
            return out
        for label, moment in self.marks.items():
            try:
                out[label] = float(moment - self.starttime) / 60.0
            except TypeError:
                continue
        return out

    def _curve(self, ax: Any, values: np.ndarray, keep: slice, label: str) -> None:
        t_col, low, high = _thin(self.minutes[keep], values[keep])
        if t_col.size == values[keep].size and np.array_equal(low, high):
            self.lines[label], = ax.plot(t_col, low, color="k", lw=0.5)
        else:
            self.lines[label] = ax.fill_between(t_col, low, high, color="k", lw=0.0, step="mid")

    # -------------------------------------------------------------------------------------------- draw
    def _draw(self) -> None:
        k = float(self.k_slider.value)
        gap = float(self.gap_slider.value)
        lo, hi = (float(v) for v in self.range_slider.value)
        first = int(max(0, math.floor(lo * 60.0 / self.delta)))
        last = int(min(self.cc.size, math.ceil(hi * 60.0 / self.delta) + 1))
        keep = slice(first, max(last, first + 2))
        notes = []

        found, level = None, None
        if self.detect is None:
            notes.append("Pass detect=your mad_detections to see the threshold and the detections.")
        else:
            name = func_name(self.detect, "detect")
            result, problem = call_yours(self.detect, name, self.cc.copy(), self.delta, k, gap)
            found = _as_detections(result, self.cc.size, self.delta, True) if problem is None else None
            if problem:
                notes.append(problem + ".")
            elif found is None:
                notes.append(f"your {name} did not return (times_s, values, threshold) inside the record.")
            else:
                level = found[2]
        false_ones = None
        if self.null is not None and level is not None:
            if self.peaks is None:
                notes.append("Pass peaks=your picks_from_probability to count the false detections.")
            else:
                name = func_name(self.peaks, "peaks")
                result, problem = call_yours(self.peaks, name, self.null.copy(), self.delta, level, gap)
                false_ones = _as_detections(result, self.null.size, self.delta, False) if problem is None else None
                if problem:
                    notes.append(problem + ".")
                elif false_ones is None:
                    notes.append(f"your {name} did not return (times_s, values) inside the record.")

        fig = self.figure
        panels = [("records", self.cc)] + ([("null records", self.null)] if self.null is not None else [])
        axes = []
        for row, (label, values) in enumerate(panels):
            ax = fig.add_subplot(len(panels), 1, row + 1, sharex=axes[0] if axes else None)
            axes.append(ax)
            self._curve(ax, values, keep, label)
            ax.set_ylabel(f"Network CC,\n{label}", fontsize=8)
            if level is not None:
                self.lines[f"threshold {label}"] = ax.axhline(level, color="tab:red", lw=0.8, ls="--")
            for mark, at in self._mark_minutes().items():
                ax.axvline(at, color="tab:green", lw=0.8)
                if row == 0:
                    ax.text(at, 1.0, f" {mark}", transform=ax.get_xaxis_transform(), color="tab:green",
                            fontsize=7, va="bottom")
        if found is not None and found[0].size:
            self.lines["detections"], = axes[0].plot(found[0] / 60.0, found[1], "o", mfc="none",
                                                    color="tab:red", ms=6)
        if false_ones is not None and false_ones[0].size and len(axes) > 1:
            self.lines["false"], = axes[1].plot(false_ones[0] / 60.0, false_ones[1], "x", color="tab:red", ms=6)
        axes[-1].set_xlabel(self.xlabel)
        axes[-1].set_xlim(self.minutes[keep.start], self.minutes[keep.stop - 1])

        hours = self.cc.size * self.delta / 3600.0
        self.state = {"k": k, "min_gap_s": gap, "threshold": level,
                      "n_detections": None if found is None else int(found[0].size),
                      "detections_s": [] if found is None else [float(v) for v in found[0]],
                      "n_null": None if false_ones is None else int(false_ones[0].size),
                      "shown_minutes": (lo, hi)}
        lines = [f"k {k:.1f} MADs, minimum gap {gap:.3g} s; {hours:.2f} hours of record."]
        if level is not None:
            text = (f"Threshold {level:.4g} (from your {func_name(self.detect, 'detect')}): "
                    f"{found[0].size} detections on the records")
            if found[0].size:
                text += " at " + ", ".join(self._when(s) for s in found[0][:6]) + (" ..." if found[0].size > 6
                                                                                  else "")
            lines.append(text + ".")
        if false_ones is not None:
            lines.append(f"Null records: {false_ones[0].size} peaks at or above the same threshold "
                         f"({false_ones[0].size / hours:.2f} per hour).")
        self.status.value = status_html(lines + notes)


def detection_explorer(network_cc: Any, delta: float, *, detect: Optional[Callable] = None,
                       peaks: Optional[Callable] = None, null_cc: Any = None, starttime: Any = None,
                       k: float = 8.0, min_gap_s: float = 2.0, marks: Optional[Dict[str, Any]] = None,
                       xlabel: Optional[str] = None) -> DetectionExplorer:
    """E11 detection explorer (see DetectionExplorer). Show it by making it the last line of a cell.

    Example (module M22, with your own functions)::

        detection_explorer(real_cc, 0.01, detect=mad_detections, peaks=picks_from_probability, null_cc=null_cc)
    """
    return DetectionExplorer(network_cc, delta, detect=detect, peaks=peaks, null_cc=null_cc, starttime=starttime,
                             k=k, min_gap_s=min_gap_s, marks=marks, xlabel=xlabel)
