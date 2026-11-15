"""Data shipped with the repository (small catalogs, station lists, velocity models).

Large files (waveforms, downloads) live outside the repository under ``root()``
(``~/sgtl/data`` unless ``SGTL_DATA`` is set).

File formats (all plain text, written by the data maintainers):

* ``data/catalogs/kma_catalog.csv``: ``event_id,origin_utc,latitude,longitude,depth_km,ml``;
  ``origin_utc`` like ``2016-09-12T11:32:54Z``; ``depth_km`` may be blank.
  Attribution text in ``data/catalogs/ATTRIBUTION.txt``.
* ``data/manifests/sequences.yaml``: ``{name: {center_lat, center_lon, radius_km, start_utc,
  end_utc, description}}``.
* ``data/stations/stations.csv``: ``network,station,latitude,longitude,start_date``.
* ``data/velocity_models/<name>.csv``: ``top_km,vp_km_s,vs_km_s``; citations in
  ``data/velocity_models/citations.yaml`` as ``{name: citation}``.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

from . import _paths

__all__ = [
    "KST",
    "root",
    "repo_path",
    "kma_catalog",
    "sequences",
    "sequence",
    "stations",
    "velocity_models",
    "velocity_model",
]

KST = _dt.timezone(_dt.timedelta(hours=9))  # fixed +09:00 offset, the clock of the KMA catalog
DEFAULT_KMA_SOURCE = ("Earthquake catalog: Korea Meteorological Administration (KMA), "
                      "used under the Korea Open Government License Type 1 (attribution).")


def root() -> Path:
    """Folder for large data files: ``$SGTL_DATA`` or ``~/sgtl/data``."""
    return _paths.data_root()


def repo_path(*parts: str) -> Path:
    """A path inside the cloned repository, e.g. ``repo_path("data", "catalogs")``."""
    return _paths.repo_root().joinpath(*parts)


def _read_yaml(path: Path):
    import yaml

    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _to_utc(values: pd.Series) -> pd.Series:
    try:
        out = pd.to_datetime(values, utc=True, format="ISO8601")
    except (TypeError, ValueError):
        out = pd.to_datetime(values, utc=True)
    if hasattr(out.dt, "as_unit"):
        out = out.dt.as_unit("ns")
    return out


def kma_catalog() -> pd.DataFrame:
    """The KMA catalog subset shipped in ``data/catalogs/kma_catalog.csv``.

    Columns: ``event_id`` (text), ``origin_utc`` (time zone UTC), ``origin_kst`` (the same moment
    written in Korea Standard Time, UTC+09:00), ``latitude``, ``longitude`` (degrees),
    ``depth_km`` (NaN when the catalog gives no depth), ``ml`` (local magnitude).
    The attribution text is in ``df.attrs["source"]``.
    """
    path = repo_path("data", "catalogs", "kma_catalog.csv")
    raw = pd.read_csv(path, dtype={"event_id": str}, keep_default_na=False, na_values=[""])
    df = pd.DataFrame({"event_id": raw["event_id"].astype(str).str.strip()})
    df["origin_utc"] = _to_utc(raw["origin_utc"].astype(str).str.strip())
    df["origin_kst"] = df["origin_utc"].dt.tz_convert(KST)
    for col in ("latitude", "longitude", "depth_km", "ml"):
        df[col] = pd.to_numeric(raw[col], errors="coerce").astype(float)
    att = path.parent / "ATTRIBUTION.txt"
    try:
        df.attrs["source"] = att.read_text(encoding="utf-8").strip() or DEFAULT_KMA_SOURCE
    except OSError:
        df.attrs["source"] = DEFAULT_KMA_SOURCE
    return df


def sequences() -> Dict[str, dict]:
    """Named earthquake sequences from ``data/manifests/sequences.yaml``."""
    return dict(_read_yaml(repo_path("data", "manifests", "sequences.yaml")))


def _distance_km(lat0: float, lon0: float, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Distance along the Earth's surface, computed by a geodesy library (pyproj, else obspy)."""
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    try:
        from pyproj import Geod

        _f, _b, dist = Geod(ellps="WGS84").inv(np.full(lat.shape, lon0), np.full(lat.shape, lat0), lon, lat)
        return np.asarray(dist) / 1000.0
    except ImportError:
        pass
    try:
        from obspy.geodetics import gps2dist_azimuth
    except ImportError as exc:
        raise ImportError("st.data.sequence needs pyproj or obspy; install the course environment.") from exc
    return np.array([gps2dist_azimuth(lat0, lon0, a, o)[0] / 1000.0 for a, o in zip(lat, lon)])


def sequence(name: str) -> pd.DataFrame:
    """Events of a named sequence: within ``radius_km`` of the center and between the start and end
    times (both inclusive). The sequence settings are in ``df.attrs["sequence"]``."""
    seqs = sequences()
    if name not in seqs:
        raise KeyError(f"Unknown sequence {name!r}. Known sequences: {', '.join(sorted(seqs)) or 'none'}.")
    spec = dict(seqs[name])
    cat = kma_catalog()
    keep = np.ones(len(cat), dtype=bool)
    if spec.get("radius_km") is not None:
        dist = _distance_km(float(spec["center_lat"]), float(spec["center_lon"]),
                            cat["latitude"].to_numpy(), cat["longitude"].to_numpy())
        keep &= dist <= float(spec["radius_km"])
    for key, op in (("start_utc", "ge"), ("end_utc", "le")):
        if spec.get(key):
            t = pd.Timestamp(str(spec[key]))
            t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
            keep &= getattr(cat["origin_utc"], op)(t).to_numpy()
    out = cat.loc[keep].reset_index(drop=True)
    out.attrs["source"] = cat.attrs.get("source", DEFAULT_KMA_SOURCE)
    out.attrs["sequence"] = {"name": name, **spec}
    return out


def stations() -> pd.DataFrame:
    """Station list ``data/stations/stations.csv`` (network, station, latitude, longitude, start_date)."""
    path = repo_path("data", "stations", "stations.csv")
    df = pd.read_csv(path, dtype={"network": str, "station": str}, keep_default_na=False, na_values=[""])
    for col in ("latitude", "longitude"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)
    if "start_date" in df:
        df["start_date"] = pd.to_datetime(df["start_date"], errors="coerce")
    return df


def velocity_models() -> List[str]:
    """Names of the shipped 1-D velocity models."""
    folder = repo_path("data", "velocity_models")
    return sorted(p.stem for p in folder.glob("*.csv"))


def velocity_model(name: str) -> pd.DataFrame:
    """A 1-D layered velocity model: columns ``top_km`` (depth of the layer top), ``vp_km_s``,
    ``vs_km_s``. The source is in ``df.attrs["citation"]``."""
    folder = repo_path("data", "velocity_models")
    path = folder / f"{name}.csv"
    if not path.is_file():
        raise FileNotFoundError(
            f"No velocity model {name!r}. Available: {', '.join(velocity_models()) or 'none'}.")
    df = pd.read_csv(path)
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)
    cites = folder / "citations.yaml"
    citation = ""
    if cites.is_file():
        citation = str((_read_yaml(cites) or {}).get(name, "") or "")
    df.attrs["name"] = name
    df.attrs["citation"] = citation
    return df
