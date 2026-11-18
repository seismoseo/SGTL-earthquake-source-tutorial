"""Made-up records with arrivals at known samples, for practising pickers (module M20).

Everything here only GENERATES data; nothing here picks, triggers or measures. Each function takes a numpy random
Generator, so the same seed gives the same data.

- ``onset_trace``: noise, then one arrival that starts exactly at a known sample (its first motion up or down).
- ``onset_set``: many such records at once, with their truths.
- ``variance_step``: noise whose size changes at a known sample (for change-point pickers).

Credit: Minseong Seo (SGTL, Seoul National University). License: MIT.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np

__all__ = ["STARTTIME", "onset_trace", "onset_set", "variance_step"]

STARTTIME = "2020-01-01T00:00:00"


def onset_trace(rng: np.random.Generator, *, rate: float = 100.0, duration_s: float = 60.0,
                onset_s: Optional[float] = None, snr: float = 20.0, freq_hz: Optional[float] = None,
                decay_s: Optional[float] = None, rise_s: float = 0.0, polarity: Optional[int] = None,
                microseism: float = 4.0, starttime: Any = None, station: str = "SYN01") -> Tuple[Any, Dict]:
    """One made-up record (an ObsPy Trace) with one arrival that starts exactly at a known sample.

    rate        : samples per second
    duration_s  : record length (s)
    onset_s     : time of the arrival after the first sample (s); default: drawn between 40 % and 60 % of the record
                  (always rounded to a whole sample)
    snr         : peak size of the arrival over the standard deviation of the white noise
    freq_hz     : frequency of the arrival (Hz); default: drawn between 3 and 8 Hz
    decay_s     : how fast the arrival dies away (s); default: drawn between 0.5 and 2 s
    rise_s      : 0 for a sharp (impulsive) start; larger values make the arrival grow slowly (emergent)
    polarity    : +1 (first motion up) or -1 (down); default: drawn at random
    microseism  : size of slow ocean-wave noise near 0.12-0.3 Hz, relative to the white noise (0 for none)

    The arrival is zero before the onset sample and starts there with the sign of ``polarity``. Returns
    ``(trace, truth)``: truth holds ``onset`` (UTCDateTime), ``onset_index``, ``onset_s``, ``polarity`` ("U" or
    "D"), ``snr``, ``freq_hz``, ``decay_s`` and ``rise_s``.
    """
    from obspy import Trace, UTCDateTime

    rate = float(rate)
    n = int(round(float(duration_s) * rate))
    if n < 50:
        raise ValueError("onset_trace needs at least 50 samples")
    if onset_s is None:
        onset_s = rng.uniform(0.4, 0.6) * n / rate
    index = int(round(float(onset_s) * rate))
    if not 1 <= index < n - 1:
        raise ValueError("onset_s must lie inside the record")
    freq = float(freq_hz) if freq_hz is not None else float(rng.uniform(3.0, 8.0))
    decay = float(decay_s) if decay_s is not None else float(rng.uniform(0.5, 2.0))
    sign = int(polarity) if polarity is not None else int(rng.choice([-1, 1]))
    if sign not in (-1, 1):
        raise ValueError("polarity must be +1 or -1")

    t = np.arange(n) / rate
    after = np.clip(t - index / rate, 0.0, None)
    started = np.arange(n) >= index
    noise = rng.normal(0.0, 1.0, n)
    if microseism:
        for _ in range(3):
            noise += float(microseism) / 3.0 * np.sin(2.0 * np.pi * rng.uniform(0.12, 0.3) * t
                                                      + rng.uniform(0.0, 2.0 * np.pi))
    shape = np.where(started, np.exp(-after / decay), 0.0)
    if rise_s and rise_s > 0:
        shape *= 1.0 - np.exp(-after / float(rise_s))
    wavelet = shape * np.sin(2.0 * np.pi * freq * after)
    coda = np.where(started, rng.normal(0.0, 1.0, n), 0.0) * (1.0 - np.exp(-after / 0.3)) * \
        np.exp(-after / (3.0 * decay))
    data = noise + sign * float(snr) * (wavelet + 0.3 * coda)

    start = UTCDateTime(starttime if starttime is not None else STARTTIME)
    trace = Trace(data=data.astype(np.float64), header={"delta": 1.0 / rate, "starttime": start,
                                                         "network": "XX", "station": str(station),
                                                         "channel": "HHZ"})
    truth = {"onset": start + index / rate, "onset_index": index, "onset_s": index / rate,
             "polarity": "U" if sign > 0 else "D", "snr": float(snr), "freq_hz": freq, "decay_s": decay,
             "rise_s": float(rise_s or 0.0)}
    return trace, truth


def onset_set(rng: np.random.Generator, n: int, **kwargs: Any) -> List[Tuple[Any, Dict]]:
    """``n`` made-up records from :func:`onset_trace` (same keywords for all; frequencies, decays, onsets and
    polarities drawn anew for each one). Returns a list of ``(trace, truth)`` pairs."""
    return [onset_trace(rng, station=f"SYN{i + 1:02d}", **kwargs) for i in range(int(n))]


def variance_step(rng: np.random.Generator, n: int, index: int, ratio: float = 5.0,
                  offset: float = 0.0) -> Tuple[np.ndarray, int]:
    """Gaussian noise of standard deviation 1 before sample ``index`` and ``ratio`` from it on, plus ``offset``.

    Returns ``(data, index)``: the samples and the first sample of the second part.
    """
    n, index = int(n), int(index)
    if not 2 <= index <= n - 2:
        raise ValueError("index must leave at least two samples on each side")
    data = rng.normal(0.0, 1.0, n)
    data[index:] *= float(ratio)
    return data + float(offset), index
