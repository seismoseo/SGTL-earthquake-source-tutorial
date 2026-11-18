"""E3 · STA/LTA tuner: your STA/LTA ratio and your triggers on one record, under sliders.

Controls: the STA and LTA window lengths (s), the on and off thresholds, and a causal band-pass on or off. The tuner
shows the record and, from your own functions, the STA/LTA ratio with both thresholds and the stretches where your
trigger function says an arrival is on.

What the tuner does itself, with ObsPy: remove the mean, taper the ends (Hann) and, when the box is ticked, apply
a causal Butterworth band-pass (``zerophase=False``). It turns the window lengths into whole numbers of samples
(at least one) and hands them to your function. What it never does itself: the ratio and the triggers. Pass
``sta_lta=`` your function ``sta_lta(data, nsta, nlta) -> ratio`` and ``trigger=`` your function
``trigger(cft, thr_on, thr_off) -> [(on, off), ...]`` (``sta_lta`` and ``trigger_windows`` of module M20). Without
them, the tuner shows the record only.

Credit: Minseong Seo (SGTL, Seoul National University). License: MIT.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Dict, Optional, Sequence

import numpy as np

from ._common import Explorer, call_yours, func_name, status_html


def _as_ratio(result: Any, size: int) -> Optional[np.ndarray]:
    """Your ratio as a float array of the record's length, or None when it is not that."""
    try:
        values = np.asarray(result, dtype=float).ravel()
    except (TypeError, ValueError):
        return None
    return values if values.size == size else None


def _as_pairs(result: Any, size: int) -> Optional[list]:
    """Your triggers as a list of (on, off) sample pairs inside the record, or None when they are not that."""
    try:
        pairs = [(int(pair[0]), int(pair[1])) for pair in result]
    except (TypeError, ValueError, IndexError):
        return None
    if any(not 0 <= on <= off < size for on, off in pairs):
        return None
    return pairs


class StaLtaTuner(Explorer):
    """E3: one record, your STA/LTA ratio and your triggers, with sliders for the settings.

    trace            : one ObsPy Trace (a Stream with one Trace is accepted); it is never changed
    sta_lta          : your function sta_lta(data, nsta, nlta) -> ratio array, or None
    trigger          : your function trigger(cft, thr_on, thr_off) -> list of (on, off) sample pairs, or None
    reftime          : ObsPy UTCDateTime that time zero of the plots refers to (default: the first sample)
    window           : (start, end) of the plotted time, in seconds after reftime (default: the whole record)
    fmin, fmax       : corners (Hz) of the causal band-pass (Butterworth, ``corners`` corners)
    sta_s, lta_s     : window lengths (s) to start with
    thr_on, thr_off  : thresholds to start with
    bandpass         : start with the band-pass on (True) or off
    marks            : {label: UTCDateTime} drawn as vertical lines, for example {"my P pick": t}
    taper            : fraction of the record tapered at each end before anything else (default 0.05)
    """

    def __init__(self, trace: Any, *, sta_lta: Optional[Callable] = None, trigger: Optional[Callable] = None,
                 reftime: Any = None, window: Optional[Sequence[float]] = None, fmin: float = 1.0,
                 fmax: float = 10.0, corners: int = 4, sta_s: float = 0.5, lta_s: float = 10.0, thr_on: float = 4.0,
                 thr_off: float = 1.5, bandpass: bool = True, marks: Optional[Dict[str, Any]] = None,
                 taper: float = 0.05, xlabel: Optional[str] = None) -> None:
        from obspy import Stream, Trace

        if isinstance(trace, Stream) and len(trace) == 1:
            trace = trace[0]
        if not isinstance(trace, Trace):
            raise TypeError("stalta_tuner needs one ObsPy Trace (for a Stream, pick one: stream[0])")
        if trace.stats.npts < 32:
            raise ValueError("stalta_tuner needs a record of at least 32 samples")
        for name, func in (("sta_lta", sta_lta), ("trigger", trigger)):
            if func is not None and not callable(func):
                raise TypeError(f"{name} must be one of your functions (or None)")
        rate = float(trace.stats.sampling_rate)
        if not 0.0 < float(fmin) < float(fmax) < rate / 2.0:
            raise ValueError("fmin and fmax must satisfy 0 < fmin < fmax < the Nyquist frequency")
        super().__init__(9.5, 5.4)
        self.trace = trace.copy()
        self.sta_lta = sta_lta
        self.trigger = trigger
        self.reftime = reftime
        self.window = tuple(float(t) for t in window) if window is not None else None
        self.band = (float(fmin), float(fmax))
        self.corners = int(corners)
        self.taper = float(taper)
        self.marks = dict(marks or {})
        self.xlabel = xlabel or ("Time after the reference time (s)" if reftime is not None
                                 else "Time after the first sample (s)")
        self._records: dict = {}                    # True / False (band-pass on or off) -> prepared record

        w = self._widgets
        style = {"description_width": "initial"}
        length_s = self.trace.stats.npts / rate
        shortest = 1.0 / rate
        self.sta_slider = w.FloatLogSlider(value=min(max(float(sta_s), shortest), 5.0), base=10,
                                           min=math.log10(shortest), max=math.log10(5.0), step=0.01,
                                           readout_format=".3g", description="STA (s)", continuous_update=False,
                                           style=style)
        longest = max(min(120.0, 0.9 * length_s), 2.0 * shortest)
        self.lta_slider = w.FloatLogSlider(value=min(max(float(lta_s), 2.0 * shortest), longest), base=10,
                                           min=math.log10(2.0 * shortest), max=math.log10(longest), step=0.01,
                                           readout_format=".3g", description="LTA (s)", continuous_update=False,
                                           style=style)
        self.on_slider = w.FloatLogSlider(value=min(max(float(thr_on), 1.05), 50.0), base=10,
                                          min=math.log10(1.05), max=math.log10(50.0), step=0.01,
                                          readout_format=".3g", description="thr_on", continuous_update=False,
                                          style=style)
        self.off_slider = w.FloatLogSlider(value=min(max(float(thr_off), 0.2), 20.0), base=10,
                                           min=math.log10(0.2), max=math.log10(20.0), step=0.01,
                                           readout_format=".3g", description="thr_off", continuous_update=False,
                                           style=style)
        self.bandpass_box = w.Checkbox(value=bool(bandpass), style=style,
                                       description=f"Causal band-pass {self.band[0]:g}-{self.band[1]:g} Hz")
        for control in (self.sta_slider, self.lta_slider, self.on_slider, self.off_slider, self.bandpass_box):
            control.observe(self._changed, names="value")
        self.box = w.VBox([w.HBox([self.sta_slider, self.lta_slider]),
                           w.HBox([self.on_slider, self.off_slider]), self.bandpass_box, self.image, self.status])
        self.redraw()

    # ------------------------------------------------------------------------------------------- the record
    def _record(self, filtered: bool) -> Any:
        if filtered not in self._records:
            work = self.trace.copy()
            work.detrend("demean")
            work.taper(max_percentage=self.taper, type="hann")
            if filtered:
                work.filter("bandpass", freqmin=self.band[0], freqmax=self.band[1], corners=self.corners,
                            zerophase=False)
            self._records[filtered] = work
        return self._records[filtered]

    def _times(self, record: Any) -> np.ndarray:
        return record.times(reftime=self.reftime) if self.reftime is not None else record.times()

    def _offset(self, moment: Any) -> Optional[float]:
        try:
            zero = self.reftime if self.reftime is not None else self.trace.stats.starttime
            return float(moment - zero)
        except TypeError:
            return None

    # -------------------------------------------------------------------------------------------------- draw
    def _draw(self) -> None:
        sta_s, lta_s = float(self.sta_slider.value), float(self.lta_slider.value)
        thr_on, thr_off = float(self.on_slider.value), float(self.off_slider.value)
        filtered = bool(self.bandpass_box.value)
        record = self._record(filtered)
        rate = float(record.stats.sampling_rate)
        n_short = max(1, int(round(sta_s * rate)))
        n_long = max(n_short + 1, int(round(lta_s * rate)))
        t = self._times(record)
        keep = (t >= self.window[0]) & (t <= self.window[1]) if self.window else np.ones(t.size, bool)
        notes = []

        ratio, pairs = None, None
        if self.sta_lta is None:
            notes.append("Pass sta_lta=your STA/LTA function to see the ratio.")
        elif n_long > record.stats.npts:
            notes.append("The LTA window is longer than the record.")
        else:
            name = func_name(self.sta_lta, "sta_lta")
            result, problem = call_yours(self.sta_lta, name, record.data.copy(), n_short, n_long)
            ratio = _as_ratio(result, record.stats.npts) if problem is None else None
            if problem:
                notes.append(problem + ".")
            elif ratio is None:
                notes.append(f"your {name} did not return one number per sample.")
        if lta_s <= sta_s:
            notes.append("The LTA window should be longer than the STA window.")
        if thr_off >= thr_on:
            notes.append("thr_off should be below thr_on.")
        if ratio is not None and self.trigger is None:
            notes.append("Pass trigger=your trigger function to see the triggers.")
        elif ratio is not None:
            name = func_name(self.trigger, "trigger")
            result, problem = call_yours(self.trigger, name, ratio.copy(), thr_on, thr_off)
            pairs = _as_pairs(result, record.stats.npts) if problem is None else None
            if problem:
                notes.append(problem + ".")
            elif pairs is None:
                notes.append(f"your {name} did not return (on, off) sample pairs inside the record.")

        fig = self.figure
        ax_rec = fig.add_subplot(2, 1, 1)
        ax_ratio = fig.add_subplot(2, 1, 2, sharex=ax_rec)
        self.lines["record"], = ax_rec.plot(t[keep], record.data[keep], color="k", lw=0.5)
        ax_rec.set_ylabel(f"{record.stats.channel or 'record'} ({'band-passed' if filtered else 'as recorded'})")
        if ratio is not None:
            self.lines["ratio"], = ax_ratio.plot(t[keep], ratio[keep], color="k", lw=0.8, label="your ratio")
            ax_ratio.axhline(thr_on, color="tab:red", lw=0.8, ls="--", label="thr_on")
            ax_ratio.axhline(thr_off, color="tab:blue", lw=0.8, ls=":", label="thr_off")
            ax_ratio.set_ylabel("STA/LTA")
            ax_ratio.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=3, frameon=False, fontsize=8)
        else:
            ax_ratio.set_yticks([])
            ax_ratio.text(0.5, 0.5, "no ratio to show", transform=ax_ratio.transAxes, ha="center", va="center",
                          color="0.4")
        shown_on = []
        for on, off in pairs or []:
            start, end = float(t[on]), float(t[off])
            for ax in (ax_rec, ax_ratio):
                ax.axvspan(start, end, color="tab:orange", alpha=0.15, lw=0)
            shown_on.append(start)
        for label, moment in self.marks.items():
            at = self._offset(moment)
            if at is not None:
                for ax in (ax_rec, ax_ratio):
                    ax.axvline(at, color="tab:green", lw=0.9)
                ax_rec.text(at, 1.0, f" {label}", transform=ax_rec.get_xaxis_transform(), color="tab:green",
                            fontsize=8, va="bottom")
        ax_ratio.set_xlabel(self.xlabel)
        if self.window:
            ax_ratio.set_xlim(*self.window)

        self.state = {"sta_s": sta_s, "lta_s": lta_s, "nsta": n_short, "nlta": n_long, "thr_on": thr_on,
                      "thr_off": thr_off, "bandpass": filtered, "n_triggers": None if pairs is None else len(pairs),
                      "on_times": shown_on}
        line = (f"{self.trace.id}: STA {sta_s:.3g} s ({n_short} samples), LTA {lta_s:.3g} s ({n_long} samples), "
                f"thr_on {thr_on:.3g}, thr_off {thr_off:.3g}; "
                f"{'causal band-pass' if filtered else 'no band-pass'}.")
        found = ""
        if pairs is not None:
            found = f"Your triggers: {len(pairs)}"
            if shown_on:
                found += "; on at " + ", ".join(f"{s:.2f}" for s in shown_on[:6])
                found += (" ..." if len(shown_on) > 6 else "") + " s"
                for label, moment in self.marks.items():
                    at = self._offset(moment)
                    if at is not None:
                        found += f"; first on minus {label}: {shown_on[0] - at:+.2f} s"
            found += "."
        self.status.value = status_html([line, found, *notes])


def stalta_tuner(trace: Any, *, sta_lta: Optional[Callable] = None, trigger: Optional[Callable] = None,
                 reftime: Any = None, window: Optional[Sequence[float]] = None, fmin: float = 1.0,
                 fmax: float = 10.0, corners: int = 4, sta_s: float = 0.5, lta_s: float = 10.0, thr_on: float = 4.0,
                 thr_off: float = 1.5, bandpass: bool = True, marks: Optional[Dict[str, Any]] = None,
                 taper: float = 0.05, xlabel: Optional[str] = None) -> StaLtaTuner:
    """E3 STA/LTA tuner (see StaLtaTuner). Show it by making it the last line of a cell.

    Example (module M20, with your own functions)::

        stalta_tuner(near_z, sta_lta=sta_lta, trigger=trigger_windows, reftime=ORIGIN, window=(-25.0, 60.0))
    """
    return StaLtaTuner(trace, sta_lta=sta_lta, trigger=trigger, reftime=reftime, window=window, fmin=fmin,
                       fmax=fmax, corners=corners, sta_s=sta_s, lta_s=lta_s, thr_on=thr_on, thr_off=thr_off,
                       bandpass=bandpass, marks=marks, taper=taper, xlabel=xlabel)
