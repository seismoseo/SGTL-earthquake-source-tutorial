"""E1 · Filter bench: one record before and after a Butterworth band-pass that you set with sliders.

Controls: the two corner frequencies, the filter order (ObsPy's ``corners``), zero-phase or causal, and counts or
ground velocity (response removed). The bench shows the record before and after the band-pass and, from your own
spectrum function, both amplitude spectra.

What the bench does itself, with ObsPy, as in Parts 4 and 6 of M10: remove the mean and taper the ends
(``taper`` of the length at each end, Hann); for ground velocity, ``remove_response(output="VEL")`` with your
``pre_filt`` (or ObsPy's water level of 60 dB when you give none); then ``filter("bandpass", ...)``.
What it never does itself: the amplitude spectrum. Pass ``spectrum=`` your function
``spectrum(trace, fmin, fmax) -> (freqs, amps)`` (for example ``band_amplitude_spectrum`` of M10). The bench calls
it with one fixed wide band, ``spectrum_band``, for the record before and after the band-pass, so the two curves
differ only by the filter you set. Without it, the bench shows the records only.

Credit: Minseong Seo (SGTL, Seoul National University). License: MIT.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Optional, Sequence

import numpy as np

from ._common import Explorer, call_yours, func_name, status_html


def _two_arrays(result: Any) -> Optional[tuple]:
    """Your spectrum result as two float arrays of one length, or None when it is not that."""
    try:
        parts = [np.asarray(part, dtype=float).ravel() for part in result]
    except (TypeError, ValueError):
        return None
    if len(parts) != 2 or parts[0].size == 0 or parts[0].size != parts[1].size:
        return None
    return tuple(parts)


class FilterBench(Explorer):
    """E1: a record before and after a band-pass, with your amplitude spectra.

    trace         : one ObsPy Trace (a Stream with one Trace is accepted); it is never changed
    spectrum      : your function spectrum(trace, fmin, fmax) -> (freqs, amps), or None
    inventory     : ObsPy Inventory of the station, for the ground-velocity choice (None: counts only)
    pre_filt      : four frequencies (Hz) of the frequency taper of the response removal (None: water level 60 dB)
    fmin, fmax    : corner frequencies (Hz) to start with
    corners       : filter order to start with
    zerophase     : start zero-phase (True) or causal (False)
    output        : start with "counts" or "velocity"
    spectrum_band : the wide band (Hz) handed to your spectrum function (default: 10 / record length, at least
                    0.01 Hz, to 0.9 times the Nyquist frequency)
    reftime       : ObsPy UTCDateTime that time zero of the plots refers to (default: the first sample)
    window        : (start, end) of the plotted time, in seconds after reftime (default: the whole record)
    taper         : fraction of the record tapered at each end before anything else (default 0.05)
    xlabel        : label of the time axis
    """

    def __init__(self, trace: Any, *, spectrum: Optional[Callable] = None, inventory: Any = None,
                 pre_filt: Optional[Sequence[float]] = None, fmin: float = 1.0, fmax: float = 10.0,
                 corners: int = 4, zerophase: bool = True, output: str = "counts",
                 spectrum_band: Optional[Sequence[float]] = None, reftime: Any = None,
                 window: Optional[Sequence[float]] = None, taper: float = 0.05, xlabel: Optional[str] = None) -> None:
        from obspy import Stream, Trace

        if isinstance(trace, Stream) and len(trace) == 1:
            trace = trace[0]
        if not isinstance(trace, Trace):
            raise TypeError("filter_bench needs one ObsPy Trace (for a Stream, pick one: stream[0])")
        if trace.stats.npts < 16:
            raise ValueError("filter_bench needs a record of at least 16 samples")
        if spectrum is not None and not callable(spectrum):
            raise TypeError("spectrum must be one of your functions (or None)")
        if output not in ("counts", "velocity"):
            raise ValueError('output must be "counts" or "velocity"')
        super().__init__(9.5, 5.2)
        self.trace = trace.copy()
        self.spectrum = spectrum
        self.inventory = inventory
        self.pre_filt = tuple(float(f) for f in pre_filt) if pre_filt is not None else None
        self.reftime = reftime
        self.taper = float(taper)
        self.xlabel = xlabel or ("Time after the reference time (s)" if reftime is not None
                                 else "Time after the first sample (s)")
        rate = float(self.trace.stats.sampling_rate)
        self.nyquist = rate / 2.0
        length_s = self.trace.stats.npts / rate
        if spectrum_band is None:
            spectrum_band = (max(10.0 / length_s, 0.01), 0.9 * self.nyquist)
        lo, hi = (float(f) for f in spectrum_band)
        if not 0.0 < lo < hi < self.nyquist:
            raise ValueError("spectrum_band must satisfy 0 < fmin < fmax < the Nyquist frequency")
        self.spectrum_band = (lo, hi)
        self.window = tuple(float(t) for t in window) if window is not None else None
        self._prepared: dict = {}           # "counts" / "velocity" -> (trace or None, problem or None)
        self._spectra_before: dict = {}     # same keys -> (freqs, amps) or None, problem

        w = self._widgets
        style = {"description_width": "initial"}
        low_end = max(1.0 / length_s, 0.001)
        high_end = 0.95 * self.nyquist
        self.fmin_slider = w.FloatLogSlider(value=min(max(float(fmin), low_end), high_end), base=10,
                                            min=math.log10(low_end), max=math.log10(high_end), step=0.01,
                                            readout_format=".3g", description="Low corner (Hz)",
                                            continuous_update=False, style=style)
        self.fmax_slider = w.FloatLogSlider(value=min(max(float(fmax), low_end), high_end), base=10,
                                            min=math.log10(low_end), max=math.log10(high_end), step=0.01,
                                            readout_format=".3g", description="High corner (Hz)",
                                            continuous_update=False, style=style)
        self.order_slider = w.IntSlider(value=int(corners), min=1, max=8, description="Order (corners)",
                                        continuous_update=False, style=style)
        self.zerophase_box = w.Checkbox(value=bool(zerophase), description="Zero-phase (off: causal)",
                                        style=style)
        modes = [("Counts", "counts"), ("Ground velocity", "velocity")]
        self.output_buttons = w.ToggleButtons(options=modes, value=output if inventory is not None else "counts",
                                              disabled=inventory is None,
                                              tooltips=["The record as the digitizer wrote it",
                                                        "Instrument response removed (needs inventory=)"])
        for control in (self.fmin_slider, self.fmax_slider, self.order_slider, self.zerophase_box,
                        self.output_buttons):
            control.observe(self._changed, names="value")
        self.box = w.VBox([w.HBox([self.fmin_slider, self.fmax_slider]),
                           w.HBox([self.order_slider, self.zerophase_box, self.output_buttons]),
                           self.image, self.status])
        self.redraw()

    # ------------------------------------------------------------------------------------------- the record
    def _prepare(self, mode: str) -> tuple:
        """(the record before the band-pass, None) or (None, message); computed once per mode."""
        if mode not in self._prepared:
            work = self.trace.copy()
            work.detrend("demean")
            work.taper(max_percentage=self.taper, type="hann")
            problem = None
            if mode == "velocity":
                level = None if self.pre_filt is not None else 60.0
                try:
                    work.remove_response(inventory=self.inventory, output="VEL", pre_filt=self.pre_filt,
                                         water_level=level)
                except Exception as exc:  # no matching response, bad pre_filt, ...
                    work, problem = None, f"the response removal failed ({type(exc).__name__}: {exc})"
            self._prepared[mode] = (work, problem)
        return self._prepared[mode]

    def _your_spectrum(self, record: Any) -> tuple:
        name = func_name(self.spectrum, "spectrum")
        result, problem = call_yours(self.spectrum, name, record.copy(), *self.spectrum_band)
        pair = _two_arrays(result) if problem is None else None
        if problem is None and pair is None:
            problem = f"your {name} did not return two arrays of the same length"
        return pair, problem

    def _times(self, record: Any) -> np.ndarray:
        return record.times(reftime=self.reftime) if self.reftime is not None else record.times()

    # -------------------------------------------------------------------------------------------------- draw
    def _draw(self) -> None:
        lo, hi = float(self.fmin_slider.value), float(self.fmax_slider.value)
        order, zerophase, mode = int(self.order_slider.value), bool(self.zerophase_box.value), self.output_buttons.value
        before, problem = self._prepare(mode)
        notes = [problem[:1].upper() + problem[1:] + "."] if problem else []
        after = None
        if before is not None and lo < hi:
            after = before.copy()
            after.filter("bandpass", freqmin=lo, freqmax=hi, corners=order, zerophase=zerophase)
        elif before is not None:
            notes.append("The low corner must be below the high corner: no band-pass.")

        spectra = {}
        if self.spectrum is not None and before is not None:
            if mode not in self._spectra_before:
                self._spectra_before[mode] = self._your_spectrum(before)
            spectra["before"], problem = self._spectra_before[mode]
            if problem:
                notes.append(problem + ".")
            if after is not None and spectra["before"] is not None:
                spectra["after"], problem = self._your_spectrum(after)
                if problem:
                    notes.append(problem + ".")
        elif self.spectrum is None:
            notes.append("Pass spectrum=your spectrum function (for example band_amplitude_spectrum) to see the "
                         "amplitude spectra.")

        scale, unit = (1000.0, "mm/s") if mode == "velocity" else (1.0, "counts")
        fig = self.figure
        grid = fig.add_gridspec(2, 2, width_ratios=(1.35, 1.0))
        ax_before = fig.add_subplot(grid[0, 0])
        ax_after = fig.add_subplot(grid[1, 0], sharex=ax_before)
        ax_freq = fig.add_subplot(grid[:, 1])
        channel = self.trace.stats.channel or "record"
        for key, ax, record, color in (("before", ax_before, before, "0.35"), ("after", ax_after, after, "k")):
            if record is None:
                ax.text(0.5, 0.5, "nothing to show", transform=ax.transAxes, ha="center", va="center",
                        color="0.4")
                continue
            t = self._times(record)
            keep = (t >= self.window[0]) & (t <= self.window[1]) if self.window else np.ones(t.size, bool)
            self.lines[key], = ax.plot(t[keep], record.data[keep] * scale, color=color, lw=0.6)
            ax.set_ylabel(f"{channel} ({unit})")
        ax_before.set_title("Before the band-pass", fontsize=10, loc="left")
        ax_after.set_title(f"After: {lo:.3g}-{hi:.3g} Hz, {order} corners, "
                           f"{'zero-phase' if zerophase else 'causal'}", fontsize=10, loc="left")
        ax_after.set_xlabel(self.xlabel)
        if self.window:
            ax_after.set_xlim(*self.window)

        ax_freq.axvspan(min(lo, hi), max(lo, hi), color="tab:blue", alpha=0.08, lw=0)
        for corner in (lo, hi):
            ax_freq.axvline(corner, color="tab:blue", lw=0.8, ls=":")
        for key, color, width in (("before", "0.6", 0.7), ("after", "k", 0.7)):
            pair = spectra.get(key)
            if pair is None:
                continue
            freqs, amps = pair
            positive = (freqs > 0) & (amps > 0)
            self.lines[f"spectrum_{key}"], = ax_freq.plot(freqs[positive], amps[positive], color=color, lw=width,
                                                          label=f"{key.capitalize()} the band-pass")
        ax_freq.set_xscale("log")
        ax_freq.set_xlabel("Frequency (Hz)")
        drawn = [line.get_ydata() for key, line in self.lines.items() if key.startswith("spectrum_")]
        drawn = [y for y in drawn if np.size(y)]
        if drawn:
            top = max(float(np.max(y)) for y in drawn)
            ax_freq.set_yscale("log")
            ax_freq.set_ylim(top * 1e-6, top * 3.0)      # six decades: the stop bands would squeeze the rest
            ax_freq.set_ylabel(f"Amplitude ({'m/s' if mode == 'velocity' else 'counts'})")
            ax_freq.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2, frameon=False, fontsize=9)
        else:
            ax_freq.set_yticks([])
            ax_freq.text(0.5, 0.5, "no spectrum function" if self.spectrum is None else "no spectrum to show",
                         transform=ax_freq.transAxes, ha="center", va="center", color="0.4")
        ax_freq.set_xlim(self.spectrum_band[0] / 2.0, self.nyquist)

        self.state = {"fmin": lo, "fmax": hi, "corners": order, "zerophase": zerophase, "output": mode}
        what = "counts"
        if mode == "velocity" and self.pre_filt:
            what = f"ground velocity (response removed, pre_filt {', '.join(f'{f:g}' for f in self.pre_filt)} Hz)"
        elif mode == "velocity":
            what = "ground velocity (response removed, water level 60 dB)"
        line = (f"{self.trace.id}: band-pass {lo:.3g}-{hi:.3g} Hz, {order} corners, "
                f"{'zero-phase' if zerophase else 'causal'}; {what}.")
        band = (f"Spectra: your {func_name(self.spectrum, 'spectrum')} with the wide band "
                f"{self.spectrum_band[0]:.3g}-{self.spectrum_band[1]:.3g} Hz, before and after." if drawn else "")
        self.status.value = status_html([line, band, *notes])


def filter_bench(trace: Any, *, spectrum: Optional[Callable] = None, inventory: Any = None,
                 pre_filt: Optional[Sequence[float]] = None, fmin: float = 1.0, fmax: float = 10.0,
                 corners: int = 4, zerophase: bool = True, output: str = "counts",
                 spectrum_band: Optional[Sequence[float]] = None, reftime: Any = None,
                 window: Optional[Sequence[float]] = None, taper: float = 0.05,
                 xlabel: Optional[str] = None) -> FilterBench:
    """E1 filter bench (see FilterBench). Show it by making it the last line of a cell.

    Example (module M10, with your own spectrum function)::

        st.widgets.filter_bench(z_raw, spectrum=band_amplitude_spectrum, inventory=near_inv,
                                pre_filt=PRE_FILT_HZ, reftime=ORIGIN, window=(-5.0, 40.0))
    """
    return FilterBench(trace, spectrum=spectrum, inventory=inventory, pre_filt=pre_filt, fmin=fmin, fmax=fmax,
                       corners=corners, zerophase=zerophase, output=output, spectrum_band=spectrum_band,
                       reftime=reftime, window=window, taper=taper, xlabel=xlabel)
