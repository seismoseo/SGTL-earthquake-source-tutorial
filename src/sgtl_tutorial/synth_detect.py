"""Made-up records, templates and picks with known events, for practising detectors (module M22).

Everything here only GENERATES data; nothing here correlates, detects, thresholds or associates. Each function takes
a numpy random Generator, so the same seed gives the same data.

- ``wavelet``: a made-up earthquake waveform of a given length (a few decaying wiggles), with zero mean.
- ``record_with_copies``: a long noise record with scaled copies of a waveform starting at known samples.
- ``noise_channels``: several channels of noise and one template per channel, with or without copies of the
  templates at known, aligned times (a made-up network).
- ``pick_table``: made-up phase picks of known events at known stations (with misses and stray picks), and the
  travel times that produced them.

Credit: Minseong Seo (SGTL, Seoul National University). License: MIT.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

__all__ = ["wavelet", "record_with_copies", "noise_channels", "pick_table"]


def _smooth_noise(rng: np.random.Generator, n: int, smooth: int) -> np.ndarray:
    """Gaussian noise with unit standard deviation; ``smooth`` > 1 makes neighbouring samples alike."""
    white = rng.normal(0.0, 1.0, n + max(smooth, 1))
    if smooth > 1:
        kernel = np.hanning(smooth + 2)[1:-1]
        white = np.convolve(white, kernel / np.sqrt(np.sum(kernel ** 2)), mode="same")
    noise = white[:n]
    return noise / max(float(np.std(noise)), 1e-12)


def wavelet(rng: np.random.Generator, n: int, *, cycles: Optional[float] = None,
            decay: Optional[float] = None) -> np.ndarray:
    """A made-up earthquake waveform: ``n`` samples of decaying wiggles with zero mean and a peak size near 1.

    cycles : how many wiggles fit into the ``n`` samples (default: drawn between 4 and 12)
    decay  : how fast the wiggles die away, as a fraction of ``n`` (default: drawn between 0.15 and 0.4)
    """
    n = int(n)
    if n < 4:
        raise ValueError("a wavelet needs at least 4 samples")
    cycles = float(rng.uniform(4.0, 12.0)) if cycles is None else float(cycles)
    decay = float(rng.uniform(0.15, 0.4)) if decay is None else float(decay)
    x = np.arange(n) / n
    phase = float(rng.uniform(0.0, 2.0 * np.pi))
    wiggle = np.sin(2.0 * np.pi * cycles * x * (1.0 + 0.3 * x) + phase)
    wiggle += 0.4 * rng.normal(0.0, 1.0, n) * np.exp(-x / decay)
    shape = wiggle * np.exp(-x / decay) * np.minimum(1.0, 8.0 * x + 0.1)
    shape = shape - shape.mean()
    return shape / max(float(np.abs(shape).max()), 1e-12)


def record_with_copies(rng: np.random.Generator, waveform: Sequence[float], n: int, starts: Sequence[int],
                       scales: Sequence[float], *, noise: float = 1.0, smooth: int = 1, offset: float = 0.0,
                       dtype: Any = np.float64) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Noise with scaled copies of ``waveform`` that start exactly at the samples ``starts``.

    n      : record length in samples
    starts : first sample of each copy (each copy must fit inside the record)
    scales : size of each copy relative to ``waveform`` (a negative scale turns the copy upside down)
    noise  : standard deviation of the noise (0 for none); ``smooth`` > 1 makes it smoother
    offset : a constant added to every sample (like the offset of raw counts)
    dtype  : number type of the returned record (for example np.int32: the values are rounded)

    Returns ``(record, truth)`` with ``truth = {"starts": [...], "scales": [...]}``.
    """
    w = np.asarray(waveform, dtype=np.float64)
    data = noise * _smooth_noise(rng, int(n), int(smooth)) if noise > 0 else np.zeros(int(n))
    starts = [int(s) for s in starts]
    scales = [float(s) for s in scales]
    if len(starts) != len(scales):
        raise ValueError("give one scale for every start")
    for start, scale in zip(starts, scales):
        if start < 0 or start + w.size > data.size:
            raise ValueError(f"a copy starting at sample {start} does not fit into {data.size} samples")
        data[start:start + w.size] += scale * w
    data = data + float(offset)
    if np.issubdtype(np.dtype(dtype), np.integer):
        data = np.round(data)
    return data.astype(dtype), {"starts": starts, "scales": scales}


def noise_channels(rng: np.random.Generator, n_channels: int, n: int, length: int, *,
                   lags: Optional[Sequence[int]] = None, events: Sequence[int] = (),
                   scales: Sequence[float] = (), noise: float = 1.0,
                   smooth: int = 4) -> Tuple[List[np.ndarray], List[np.ndarray], Dict[str, Any]]:
    """A made-up network: ``n_channels`` records of ``n`` samples and one ``length``-sample template per channel.

    lags   : where each channel's template window starts after the made-up event's origin (samples); default:
             drawn between 0 and 4 x length, like the later arrival of a wave at a farther station
    events : origin samples of copies of the event put into the records (none by default: pure noise); on each
             channel the copy starts at its origin + that channel's lag, so all channels line up on the origin
    scales : size of each copy relative to the template (default 1 for every event)
    noise  : standard deviation of the noise; ``smooth`` makes neighbouring samples alike, like band-passed noise

    Returns ``(templates, records, truth)`` with ``truth = {"lags": [...], "events": [...], "scales": [...]}``.
    """
    n_channels, n, length = int(n_channels), int(n), int(length)
    lags = [int(v) for v in (rng.integers(0, 4 * length + 1, n_channels) if lags is None else lags)]
    if len(lags) != n_channels:
        raise ValueError("give one lag for every channel")
    events = [int(e) for e in events]
    scales = [1.0] * len(events) if not len(scales) else [float(s) for s in scales]
    templates, records = [], []
    for lag in lags:
        shape = wavelet(rng, length)
        starts = [e + lag for e in events]
        data, _ = record_with_copies(rng, shape, n, starts, scales, noise=noise, smooth=smooth)
        templates.append(shape)
        records.append(data)
    return templates, records, {"lags": lags, "events": events, "scales": scales}


def pick_table(rng: np.random.Generator, stations: Sequence[str], travel_times: Dict[Tuple[str, str], float],
               origins: Sequence[float], *, jitter_s: float = 0.2, p_miss: float = 0.2,
               n_stray: int = 10, duration_s: Optional[float] = None) -> Tuple[Any, Any]:
    """Made-up P and S picks of known events, plus stray picks that belong to no event.

    stations     : station names
    travel_times : {(station, "P" or "S"): seconds} from the made-up source to each station
    origins      : origin times of the events (s after the start of the made-up record)
    jitter_s     : picks scatter around the true arrival by up to this much (uniformly)
    p_miss       : chance that a pick is missing
    n_stray      : number of stray picks at random times, stations and phases
    duration_s   : length of the made-up record (default: the last origin + 120 s)

    Returns ``(picks, truth)``: two pandas DataFrames. ``picks`` has the columns station, phase, time_s, sorted by
    time; ``truth`` has one row per event with its origin_s and the stations that got a pick (column stations,
    a tuple of names).
    """
    import pandas as pd

    origins = sorted(float(o) for o in origins)
    duration = float(duration_s) if duration_s is not None else (origins[-1] if origins else 0.0) + 120.0
    rows, truth = [], []
    for origin in origins:
        got = set()
        for name in stations:
            for phase in ("P", "S"):
                if (name, phase) not in travel_times or rng.uniform() < p_miss:
                    continue
                when = origin + float(travel_times[(name, phase)]) + float(rng.uniform(-jitter_s, jitter_s))
                rows.append({"station": name, "phase": phase, "time_s": when})
                got.add(name)
        truth.append({"origin_s": origin, "stations": tuple(sorted(got))})
    for _ in range(int(n_stray)):
        rows.append({"station": str(rng.choice(list(stations))), "phase": str(rng.choice(["P", "S"])),
                     "time_s": float(rng.uniform(0.0, duration))})
    picks = pd.DataFrame(rows, columns=["station", "phase", "time_s"]).sort_values("time_s", ignore_index=True)
    return picks, pd.DataFrame(truth, columns=["origin_s", "stations"])
