"""House plotting style for matplotlib and PyGMT.

* ``use_house_style()``: Helvetica (fallback Nimbus Sans, then DejaVu Sans with a visible
  warning), all four axis spines, readable sizes, fonts embedded in PDF files.
* ``mag_size_cm(m)``: magnitude marker size in cm, 0.025 * sqrt(5 * exp(2 m)).
* ``ML_LABEL``: the local magnitude written as an italic M with a roman subscript L.
* ``gmt_style()``: a context manager with the PyGMT map settings (decimal degrees, plain frame).
* ``scale_bar_spec(region)``: the ``map_scale`` string for a PyGMT scale bar.

matplotlib and pygmt are imported only inside the functions, so ``st.init`` can point them to
this environment and to writable folders first.
"""
from __future__ import annotations

import contextlib
import math
import warnings
from typing import Any, Iterator, Optional, Sequence

import numpy as np

__all__ = ["ML_LABEL", "FONT_FAMILIES", "use_house_style", "mag_size_cm", "gmt_style", "scale_bar_spec"]

ML_LABEL = r"$\mathit{M}_{\mathrm{L}}$"
FONT_FAMILIES = ["Helvetica", "Nimbus Sans", "Nimbus Sans L", "DejaVu Sans"]
_WARNED = False


def _available_family() -> str:
    from matplotlib import font_manager

    names = {f.name for f in font_manager.fontManager.ttflist}
    for fam in FONT_FAMILIES:
        if fam in names:
            return fam
    return "DejaVu Sans"


def use_house_style(quiet: bool = False) -> str:
    """Apply the lab's matplotlib style. Returns a one-line note about the font in use."""
    global _WARNED
    import matplotlib as mpl

    mpl.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": FONT_FAMILIES,
        "font.size": 10,
        "axes.titlesize": 11,
        "axes.labelsize": 10,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "legend.fontsize": 9,
        "axes.spines.left": True,
        "axes.spines.right": True,
        "axes.spines.top": True,
        "axes.spines.bottom": True,
        "axes.linewidth": 0.8,
        "lines.linewidth": 1.2,
        "xtick.direction": "out",
        "ytick.direction": "out",
        "figure.dpi": 100,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "mathtext.fontset": "custom",
        "mathtext.rm": "sans",
        "mathtext.it": "sans:italic",
        "mathtext.bf": "sans:bold",
        "mathtext.cal": "sans",  # the default 'cursive' is rarely installed and prints a findfont warning
    })
    fam = _available_family()
    if fam == "Helvetica":
        return "Helvetica"
    note = (f"Helvetica not found; figures use {fam} instead "
            "(install Helvetica for publication figures; see docs)")
    if not _WARNED:
        _WARNED = True
        warnings.warn(note, UserWarning, stacklevel=2)
        if not quiet:
            print("Note: " + note)
    return note


def mag_size_cm(m: Any) -> Any:
    """Marker size in cm for magnitude ``m``: 0.025 * sqrt(5 * exp(2 m)).

    Works on a number (returns a float), a list or array (returns an array), or a pandas Series
    (returns a Series with the same index).
    """
    arr = np.asarray(m, dtype=float)
    out = 0.025 * np.sqrt(5.0 * np.exp(2.0 * arr))
    if arr.ndim == 0:
        return float(out)
    try:
        import pandas as pd

        if isinstance(m, pd.Series):
            return pd.Series(out, index=m.index, name="size_cm")
    except ImportError:
        pass
    return out


@contextlib.contextmanager
def gmt_style(**extra: Any) -> Iterator[None]:
    """PyGMT settings for lab maps: decimal-degree labels, plain frame, Helvetica.

    Usage::

        with st.plot.gmt_style():
            fig = pygmt.Figure()
            ...
    """
    from .session import gmt_guard

    gmt_guard()
    import pygmt

    settings = dict(
        FORMAT_GEO_MAP="ddd.xx",
        MAP_FRAME_TYPE="plain",
        FONT_ANNOT_PRIMARY="9p,Helvetica",
        FONT_LABEL="10p,Helvetica",
    )
    settings.update(extra)
    with pygmt.config(**settings):
        yield


def _map_width_km(lon_min: float, lon_max: float, lat: float) -> float:
    try:
        from pyproj import Geod

        _az, _baz, dist_m = Geod(ellps="WGS84").inv(lon_min, lat, lon_max, lat)
        return abs(dist_m) / 1000.0
    except ImportError:  # rough fallback: one degree of longitude shrinks with latitude
        return abs(lon_max - lon_min) * 111.32 * math.cos(math.radians(lat))


def _nice_km(target: float) -> float:
    """Largest of 1, 2, 5 x 10^k that is not larger than ``target``."""
    if not target > 0:
        return 1.0
    exp = math.floor(math.log10(target))
    best = 10.0 ** exp
    for mult in (1, 2, 5):
        val = mult * 10.0 ** exp
        if val <= target * (1 + 1e-9):
            best = val
    return float(f"{best:.6g}")


def scale_bar_spec(region: Sequence[float], km: Optional[float] = None, *, corner: str = "BL",
                   offset: str = "0.5c/0.5c") -> str:
    """PyGMT ``map_scale`` string for ``region = [lon_min, lon_max, lat_min, lat_max]``.

    When ``km`` is None, the bar length is a round number (1, 2 or 5 times a power of ten)
    close to one fifth of the map width. The scale is true at the map's middle latitude.
    Example: ``"jBL+w50k+o0.5c/0.5c+c36"``.
    """
    lon_min, lon_max, lat_min, lat_max = (float(v) for v in list(region)[:4])
    lat_c = round((lat_min + lat_max) / 2.0, 2)
    if km is None:
        km = _nice_km(_map_width_km(lon_min, lon_max, lat_c) / 5.0)
    return f"j{corner}+w{float(km):g}k+o{offset}+c{lat_c:g}"
