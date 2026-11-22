"""Interactive explorers: optional sliders over a figure, for building intuition (not checked).

- E1 ``filter_bench(trace, spectrum=..., inventory=...)`` (module M10): band-pass corners, filter order,
  zero-phase or causal, counts or ground velocity; the record and its amplitude spectrum before and after.
- E2 ``phase_picker(source, origin=..., csv_path=...)`` (module M20): pick P and S by hand, one station at a time,
  with an uncertainty and a first-motion polarity; "Save" writes your picks to a CSV file.
- E3 ``stalta_tuner(trace, sta_lta=..., trigger=...)`` (module M20): STA and LTA windows, thresholds and a causal
  band-pass under sliders, with the ratio and the triggers that your own functions return.
- E4 ``traveltime_explorer(model, direct=..., head=...)`` (module M30): change the layers of a flat crust and the
  source depth, and watch the travel-time curves of your own direct-wave and head-wave functions.
- E5 ``misfit_explorer(obs, tt, grid_search=..., wadati=...)`` (module M31): the RMS of your own grid search in
  map view and in a depth section, with stations left out at will, and the Wadati line of your own fit.
- E6 ``lag_explorer(xcorr=...)`` (module M41): a wavelet and a shifted copy under a filter band and noise; your
  cross-correlation finds the lag, and the status line shows when it skips a cycle.
- E7 ``dd_toy(system=..., solve=..., relocate=...)`` (module M41): a toy cluster under pick errors and station
  delays; absolute positions against the relative positions of your own double-difference relocation.
- E8 ``beachball_explorer(azimuth, takeoff, polarity, weight, project=..., misfit=...)`` (module M51): strike, dip
  and rake under sliders; the stations on your own equal-area net, shaded by your own predicted polarities, with
  your misfit and the stations it gets wrong.
- E9 ``fmd_explorer(mags, fmd=..., b_estimator=..., mc_estimator=...)`` (module M05): the frequency-magnitude
  distribution for the Mc and bin width you choose, with the Gutenberg-Richter line of your b-value.
- E10 ``coulomb_explorer(resolve=..., stress=..., source=..., receiver=...)`` (module M54): a map of your own
  shear, normal and Coulomb stress changes around a slipping rectangle, for the source rake and slip, the receiver
  fault, friction and Skempton coefficient under the sliders.
- E11 ``detection_explorer(network_cc, delta, detect=..., peaks=...)`` (module M22): your threshold and your
  detections on the network cross-correlation, next to the false detections on the null records.
- E12 ``radiation_explorer(radiation=..., project=...)`` (module M52): your P, SV and SH radiation patterns on your
  own equal-area net for the mechanism under the sliders, with station directions that you type.
- E13 ``focal_sphere_fitter(first_motions, project=..., agreement=..., axes=..., aux_plane=...)`` (module M50): fit
  a fault plane to first motions by hand on your own equal-area net, with your agreement, P and T axes and
  auxiliary plane.
- E14 ``mt_norm_explorer(misfit_budget, moment_tensor, kagan_angle, kernels=..., ...)`` (module M53): a toy
  moment-tensor grid search under one station's wrong gain, the misfit norm and leaving that station out; each
  station's share of the misfit from your own budget, and the Kagan angle of the best mechanism from your own.

An explorer never does a task for you: whatever a task asks you to write (counting magnitudes, a b-value, Mc,
an amplitude spectrum, an STA/LTA ratio, a travel time, a misfit, a lag, a double-difference system, a threshold,
a projection onto the focal sphere, a polarity, a radiation pattern, a misfit budget, a moment tensor, a stress
change)
comes from the function you pass in, and without it the explorer shows the data only; the picker E2 never chooses a pick for you. Each redraw renders a static PNG with
Matplotlib (ipywidgets 8), works without a display, and starts no threads or processes, so it stays within the
thread caps of ``st.init``. Only E2 uses ipympl, for clicking on a record; without it you type the times. Make
the explorer the last line of a cell to show it; ``explorer.figure.savefig(...)`` keeps the current picture.

Credit: Minseong Seo (SGTL, Seoul National University). License: MIT.
"""
from __future__ import annotations

import importlib
from typing import Any

_WHERE = {"filter_bench": "e1_filter", "FilterBench": "e1_filter",
          "phase_picker": "e2_picker", "PhasePicker": "e2_picker",
          "stalta_tuner": "e3_stalta", "StaLtaTuner": "e3_stalta",
          "traveltime_explorer": "e4_traveltimes", "TravelTimeExplorer": "e4_traveltimes",
          "misfit_explorer": "e5_misfit", "MisfitExplorer": "e5_misfit",
          "lag_explorer": "e6_lag", "LagExplorer": "e6_lag",
          "dd_toy": "e7_ddtoy", "DDToy": "e7_ddtoy",
          "fmd_explorer": "e9_fmd", "FMDExplorer": "e9_fmd",
          "detection_explorer": "e11_detection", "DetectionExplorer": "e11_detection",
          "beachball_explorer": "e8_beachball", "BeachballExplorer": "e8_beachball",
          "radiation_explorer": "e12_radiation", "RadiationExplorer": "e12_radiation",
          "focal_sphere_fitter": "e13_focal_sphere", "FocalSphereFitter": "e13_focal_sphere",
          "coulomb_explorer": "e10_coulomb", "CoulombExplorer": "e10_coulomb",
          "mt_norm_explorer": "e14_mt_norms", "MTNormExplorer": "e14_mt_norms"}

__all__ = sorted(_WHERE)


def __getattr__(name: str) -> Any:
    if name in _WHERE:
        value = getattr(importlib.import_module(f"{__name__}.{_WHERE[name]}"), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list:
    return sorted(set(globals()) | set(_WHERE))
