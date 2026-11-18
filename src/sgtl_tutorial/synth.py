"""Random practice data with known properties (used by checkers and by notebooks).

Everything here only GENERATES data; nothing here solves a task.
All functions take a numpy random Generator so results are reproducible.
"""
from __future__ import annotations

import datetime as _dt
from typing import Sequence, Tuple

import numpy as np
import pandas as pd

from .session import seed_for

__all__ = [
    "KST",
    "CATALOG_COLUMNS",
    "seed_for",
    "rng_for",
    "random_points",
    "gr_magnitudes",
    "random_utc_times",
    "synthetic_catalog",
]

KST = _dt.timezone(_dt.timedelta(hours=9))
CATALOG_COLUMNS = ["event_id", "origin_utc", "origin_kst", "latitude", "longitude", "depth_km", "ml"]


def rng_for(user: str, task: str, reroll: int = 0) -> np.random.Generator:
    """Random generator seeded from sha256("user:task:reroll") (see ``seed_for``)."""
    return np.random.default_rng(seed_for(user, task, reroll))


def random_points(rng: np.random.Generator, n: int, lat_range: Sequence[float] = (33.0, 38.6),
                  lon_range: Sequence[float] = (124.5, 131.0)) -> Tuple[np.ndarray, np.ndarray]:
    """``n`` points drawn uniformly in latitude and longitude (degrees). Returns ``(lat, lon)``."""
    lat = rng.uniform(float(lat_range[0]), float(lat_range[1]), int(n))
    lon = rng.uniform(float(lon_range[0]), float(lon_range[1]), int(n))
    return lat, lon


def _decimals(dm: float) -> int:
    return max(0, int(np.ceil(-np.log10(dm) - 1e-9))) if dm < 1 else 0


def gr_magnitudes(rng: np.random.Generator, n: int, b: float = 1.0, mc: float = 1.0,
                  dm: float = 0.1) -> np.ndarray:
    """``n`` made-up magnitudes that follow the Gutenberg-Richter law from ``mc`` up, on the grid ``mc + k dm``.

    Practice data for demos and checks; with ``dm = 0`` the magnitudes are not binned (all >= ``mc``).
    """
    n = int(n)
    if dm and dm > 0:
        q = 10.0 ** (-float(b) * float(dm))
        k = rng.geometric(1.0 - q, n) - 1
        return np.round(mc + k * float(dm), _decimals(dm) + 1)
    return mc - np.log10(1.0 - rng.random(n)) / float(b)


def random_utc_times(rng: np.random.Generator, n: int, start="2020-01-01", end="2021-01-01",
                     sort: bool = True) -> pd.DatetimeIndex:
    """``n`` times drawn uniformly between ``start`` and ``end`` (UTC), to the millisecond."""
    t0 = pd.Timestamp(start)
    t1 = pd.Timestamp(end)
    t0 = t0.tz_localize("UTC") if t0.tzinfo is None else t0.tz_convert("UTC")
    t1 = t1.tz_localize("UTC") if t1.tzinfo is None else t1.tz_convert("UTC")
    span_ms = int((t1 - t0) / pd.Timedelta(milliseconds=1))
    offs = rng.integers(0, max(span_ms, 1), int(n))
    if sort:
        offs = np.sort(offs)
    idx = pd.DatetimeIndex(t0 + pd.to_timedelta(offs, unit="ms"))
    return idx.as_unit("ns") if hasattr(idx, "as_unit") else idx


def synthetic_catalog(rng: np.random.Generator, n: int, *, lat_range=(35.0, 37.0), lon_range=(127.0, 129.5),
                      start="2020-01-01", end="2021-01-01", b: float = 1.0, mc: float = 1.0, dm: float = 0.1,
                      depth_range=(2.0, 20.0), id_prefix: str = "SYN",
                      blank_depth_fraction: float = 0.0) -> pd.DataFrame:
    """A made-up catalog with the same columns as ``st.data.kma_catalog()``.

    ``blank_depth_fraction`` sets that share of depths to NaN (like blank depths in real catalogs).
    """
    n = int(n)
    times = random_utc_times(rng, n, start, end, sort=True)
    lat, lon = random_points(rng, n, lat_range, lon_range)
    depth = np.round(rng.uniform(float(depth_range[0]), float(depth_range[1]), n), 1)
    if blank_depth_fraction > 0:
        depth[rng.random(n) < blank_depth_fraction] = np.nan
    df = pd.DataFrame({
        "event_id": [f"{id_prefix}{i:06d}" for i in range(1, n + 1)],
        "origin_utc": pd.Series(times, dtype="datetime64[ns, UTC]"),
        "latitude": np.round(lat, 4),
        "longitude": np.round(lon, 4),
        "depth_km": depth,
        "ml": gr_magnitudes(rng, n, b=b, mc=mc, dm=dm),
    })
    df.insert(2, "origin_kst", df["origin_utc"].dt.tz_convert(KST))
    df.attrs["source"] = "synthetic catalog (sgtl_tutorial.synth); not real earthquakes"
    return df

