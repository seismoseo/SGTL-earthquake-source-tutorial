"""E6 · Lag explorer: a wavelet, a shifted copy, a filter band and noise; your cross-correlation finds the lag.

The explorer makes two windows and draws them: window a holds a Ricker wavelet (the second derivative of a bell
curve) with the peak frequency you choose, window b the same wavelet delayed by the true shift you choose. Both get
independent noise on a record three times longer than the window, then the same Butterworth band-pass (four poles,
run forward and backward, so zero-phase), and the middle of each record becomes the window: the filter moves
neither window against the other. Every correlation value and every lag comes from the function you give it:

- ``xcorr(a, b, dt_s, max_lag_s) -> (lag_s, cc_peak, lags_s, cc)``: your function of M41 (``xcorr_lag``).

Controls: the true shift (ms), the peak frequency of the wavelet, the filter band, the noise level (as a fraction of
the wavelet's largest amplitude), the search window (``max_lag_s``, in ms) and a button for new noise. The status
line gives your lag, its error against the true shift, and that error in periods of the band's middle frequency;
an error of about one whole period is **cycle skipping**. Without a function the explorer shows the two windows.

Credit: Minseong Seo (SGTL, Seoul National University). License: MIT.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Optional, Tuple

import numpy as np

from ._common import Explorer, call_yours, func_name, status_html


def _ricker(t: np.ndarray, peak_hz: float) -> np.ndarray:
    arg = (math.pi * peak_hz * t) ** 2
    return (1.0 - 2.0 * arg) * np.exp(-arg)


def _yours(result: Any) -> Optional[Tuple[float, float, np.ndarray, np.ndarray]]:
    """Your result as (lag_s, cc_peak, lags_s, cc), or None when it is not that."""
    if not isinstance(result, tuple) or len(result) != 4:
        return None
    try:
        lag, peak = float(result[0]), float(result[1])
        lags = np.asarray(result[2], dtype=float).ravel()
        values = np.asarray(result[3], dtype=float).ravel()
    except (TypeError, ValueError):
        return None
    if lags.size == 0 or lags.size != values.size or not (math.isfinite(lag) and math.isfinite(peak)):
        return None
    return lag, peak, lags, values


class LagExplorer(Explorer):
    """E6: two windows (a wavelet and its delayed copy) and the correlation and lag of your function.

    xcorr      : your function xcorr(a, b, dt_s, max_lag_s) -> (lag_s, cc_peak, lags_s, cc), or None
    rate_hz    : samples per second of the windows
    window_s   : length of each window (s)
    shift_ms   : true delay of b against a (ms) to start with
    peak_hz    : peak frequency of the Ricker wavelet (Hz) to start with
    band_hz    : (low, high) corners of the band-pass (Hz) to start with
    noise      : noise level to start with, a fraction of the wavelet's largest amplitude
    max_lag_ms : search window to start with (ms)
    seed       : seed of the first noise draw
    """

    def __init__(self, *, xcorr: Optional[Callable] = None, rate_hz: float = 100.0, window_s: float = 1.6,
                 shift_ms: float = 13.7, peak_hz: float = 8.0, band_hz: Tuple[float, float] = (2.0, 20.0),
                 noise: float = 0.1, max_lag_ms: float = 300.0, seed: int = 6) -> None:
        if xcorr is not None and not callable(xcorr):
            raise TypeError("xcorr must be one of your functions (or None)")
        if not (rate_hz >= 20.0 and window_s * rate_hz >= 32):
            raise ValueError("rate_hz must be at least 20 and the window at least 32 samples long")
        if not 0.0 < band_hz[0] < band_hz[1] < rate_hz / 2.0:
            raise ValueError("band_hz must be (low, high) with 0 < low < high < rate_hz / 2")
        super().__init__(9.5, 5.6)
        self.xcorr = xcorr
        self.rate = float(rate_hz)
        self.dt = 1.0 / self.rate
        half = int(round(window_s * self.rate / 2.0))
        self.t = np.arange(-half, half + 1) * self.dt
        self.seed = int(seed)
        nyq = self.rate / 2.0
        w = self._widgets
        style = {"description_width": "initial"}
        self.shift_slider = w.FloatSlider(min=-150.0, max=150.0, step=0.1, value=float(shift_ms),
                                          description="True shift of b (ms)", continuous_update=False, style=style,
                                          layout=w.Layout(width="340px"))
        self.peak_slider = w.FloatSlider(min=1.0, max=min(25.0, 0.4 * nyq), step=0.5, value=float(peak_hz),
                                         description="Wavelet peak (Hz)", continuous_update=False, style=style,
                                         layout=w.Layout(width="300px"))
        self.band_slider = w.FloatRangeSlider(min=0.5, max=round(0.9 * nyq, 1), step=0.5,
                                              value=(float(band_hz[0]), float(band_hz[1])),
                                              description="Band (Hz)", continuous_update=False, style=style,
                                              layout=w.Layout(width="340px"))
        self.noise_slider = w.FloatSlider(min=0.0, max=1.5, step=0.05, value=float(noise),
                                          description="Noise (x largest amplitude)", continuous_update=False,
                                          style=style, layout=w.Layout(width="330px"))
        self.window_slider = w.FloatSlider(min=10.0, max=500.0, step=10.0, value=float(max_lag_ms),
                                           description="Search window max_lag (ms)", continuous_update=False,
                                           style=style, layout=w.Layout(width="340px"))
        self.noise_button = w.Button(description="New noise", tooltip="Draw new noise for both windows")
        for control in (self.shift_slider, self.peak_slider, self.band_slider, self.noise_slider,
                        self.window_slider):
            control.observe(self._changed, names="value")
        self.noise_button.on_click(self._new_noise)
        self.box = w.VBox([w.HBox([self.shift_slider, self.peak_slider, self.noise_button]),
                           w.HBox([self.band_slider, self.noise_slider]),
                           w.HBox([self.window_slider]), self.image, self.status])
        self.redraw()

    # ------------------------------------------------------------------------------------------- windows
    def _new_noise(self, _button: Any = None) -> None:
        self.seed += 1
        self.redraw()

    def windows(self) -> Tuple[np.ndarray, np.ndarray]:
        """The two windows (a, b) for the current controls: wavelet, delayed copy, noise, the same band-pass."""
        from scipy.signal import butter, sosfiltfilt

        peak = float(self.peak_slider.value)
        shift = float(self.shift_slider.value) / 1000.0
        rng = np.random.default_rng(self.seed)
        size = float(self.noise_slider.value)
        n = self.t.size
        long_t = (np.arange(3 * n) - n) * self.dt + self.t[0]          # the window is the middle third
        a = _ricker(long_t, peak) + size * rng.standard_normal(long_t.size)
        b = _ricker(long_t - shift, peak) + size * rng.standard_normal(long_t.size)
        low, high = (float(v) for v in self.band_slider.value)
        sos = butter(4, [low, high], btype="bandpass", fs=self.rate, output="sos")
        return sosfiltfilt(sos, a)[n:2 * n], sosfiltfilt(sos, b)[n:2 * n]

    # ---------------------------------------------------------------------------------------------- draw
    def _draw(self) -> None:
        a, b = self.windows()
        shift = float(self.shift_slider.value) / 1000.0
        low, high = (float(v) for v in self.band_slider.value)
        middle = math.sqrt(low * high)
        period = 1.0 / middle
        max_lag = float(self.window_slider.value) / 1000.0
        notes, found = [], None
        if self.xcorr is not None:
            name = func_name(self.xcorr, "xcorr")
            result, problem = call_yours(self.xcorr, name, a.copy(), b.copy(), self.dt, max_lag)
            found = _yours(result) if problem is None else None
            if problem is None and found is None:
                problem = f"your {name} did not return (lag_s, cc_peak, lags_s, cc)"
            if problem:
                notes.append(problem + ".")
        else:
            notes.append("Pass xcorr=your xcorr_lag to see the correlation and the lag.")

        fig = self.figure
        ax_w, ax_c = fig.subplots(2, 1)
        ms = 1000.0 * self.t
        ax_w.plot(ms, a, color="0.25", lw=1.1, label="Window a")
        ax_w.plot(ms, b, color="tab:orange", lw=1.1, label="Window b (delayed copy)")
        ax_w.set_xlim(ms[0], ms[-1])
        ax_w.set_xlabel("Time in the window (ms)")
        ax_w.set_ylabel("Amplitude")
        ax_w.set_title(f"Ricker wavelet, {self.peak_slider.value:g} Hz peak; band-pass {low:g}-{high:g} Hz, both "
                       "windows alike", fontsize=10)
        self.state = {"a": a, "b": b, "dt_s": self.dt, "true_shift_s": shift, "max_lag_s": max_lag,
                      "period_s": period, "lag_s": None, "cc_peak": None, "error_s": None, "cycle_skip": None}
        lines = [f"True shift of b: {shift * 1000:.2f} ms; band middle {middle:.1f} Hz (one period "
                 f"{period * 1000:.0f} ms); search window +-{max_lag * 1000:.0f} ms."]
        if found is not None:
            lag, peak, lags, values = found
            error = lag - shift
            skip = abs(error) > 0.5 * period
            ax_c.plot(1000.0 * lags, values, color="tab:blue", lw=1.2, label="Your correlation coefficients")
            ax_c.axvline(1000.0 * lag, color="k", lw=1.2, label=f"Your lag ({lag * 1000:.2f} ms)")
            ax_c.axvline(1000.0 * shift, color="tab:red", lw=1.0, ls="--", label="True shift")
            for k in (-1, 1):
                ax_c.axvline(1000.0 * (shift + k * period), color="tab:red", lw=0.6, ls=":")
            ax_c.set_ylim(-1.05, 1.05)
            self.lines["cc"] = ax_c.lines[0]
            self.state.update(lag_s=lag, cc_peak=peak, error_s=error, cycle_skip=skip, lags_s=lags, cc=values)
            lines.append(f"Your lag {lag * 1000:.2f} ms, peak coefficient {peak:.3f}; error {error * 1000:+.2f} ms "
                         f"= {error / period:+.2f} periods.")
            if skip:
                lines.append(f"Cycle skipping: your lag is about {round(error / period):+d} period(s) off the true "
                             "shift. Try a wider band, less noise or a shorter search window.")
        else:
            ax_c.text(0.5, 0.5, "No correlation: pass your function", transform=ax_c.transAxes, ha="center",
                      va="center", color="0.4")
        ax_c.set_xlim(-1000.0 * max_lag, 1000.0 * max_lag)
        ax_c.set_xlabel("Lag of b against a (ms); dotted: true shift +- one period")
        ax_c.set_ylabel("Correlation coefficient")
        handles, labels = [], []
        for ax in (ax_w, ax_c):
            h, lab = ax.get_legend_handles_labels()
            handles += h
            labels += lab
        fig.legend(handles, labels, loc="outside upper center", ncol=min(len(handles), 5), frameon=False, fontsize=8)
        self.status.value = status_html(lines + notes)


def lag_explorer(*, xcorr: Optional[Callable] = None, rate_hz: float = 100.0, window_s: float = 1.6,
                 shift_ms: float = 13.7, peak_hz: float = 8.0, band_hz: Tuple[float, float] = (2.0, 20.0),
                 noise: float = 0.1, max_lag_ms: float = 300.0, seed: int = 6) -> LagExplorer:
    """E6 explorer (see LagExplorer). Show it by making it the last line of a cell.

    Example (module M41, with your own function)::

        st.widgets.lag_explorer(xcorr=xcorr_lag)
    """
    return LagExplorer(xcorr=xcorr, rate_hz=rate_hz, window_s=window_s, shift_ms=shift_ms, peak_hz=peak_hz,
                       band_hz=band_hz, noise=noise, max_lag_ms=max_lag_ms, seed=seed)
