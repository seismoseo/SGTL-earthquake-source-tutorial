"""Checkers for M54 · Coulomb stress transfer.

Where the truth comes from (DESIGN.md section 1, rule 1):

* M54-T1: an independent library. Elastic_stresses_py's ``conversion_math.get_coulomb_stresses`` on made-up stress
  tensors and receivers. The student may not use Elastic_stresses_py, tectonic-utils, cutde or pyrocko.
* M54-T2: an independent library. Elastic_stresses_py's own reader of its text format
  (``io_intxt.get_source_patch``) reads the student's line; the fault it builds is compared with the made-up fault
  (its angles, size, slip, and its centre from ``Faults_object.get_fault_center``).
* M54-T3: an independent library. Elastic_stresses_py's strain at made-up points (``run_dc3d.compute_xy_strain``,
  through cutde) for made-up rectangles, and its Hooke's law (``conversion_math.stress_tensor_batch``). The
  rectangle's centre handed to the student comes from ``Faults_object.get_fault_center``.
* M54-T4: construction. Radii, stress drops and shear moduli drawn by the check; the moment follows from them by the
  formula of Part 4.
* M54-T5: construction. A made-up Coulomb map that depends only on the compass direction from a centre, so the
  fraction of positive points after any turn is known by counting directions.
* M54-T6: the student's own products. The student's read_stresses on made-up files written by
  Elastic_stresses_py's own writer, the student's T1 and T5 functions again on made-up cases, then the student's
  Gyeongju runs: SHA-256 fingerprints recomputed, the changed run's input compared with the first run's, the
  student's pyrocko-based Coulomb change compared with the one from Elastic_stresses_py's stress file, the
  sensitivity table and the rotation test recomputed with the student's own functions. It prints no real-data value.

Failure categories are keys of ``checks/specs/M54.yaml``; the engine prints their fixed messages.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import math
import numbers
import re
import warnings
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import Outcome, outcome_from_cases

__all__ = ["check_T1", "check_T2", "check_T3", "check_T4", "check_T5", "check_T6"]

SWAP = np.eye(3)[[1, 0, 2]] * np.array([[1.0], [1.0], [-1.0]])             # the other axes of the frame category


# ------------------------------------------------------------------------------------------- helpers
def _call(func: Any, *args: Any, **kwargs: Any) -> Tuple[Any, Optional[BaseException]]:
    """Run the student's code. NotImplementedError passes through (the engine reports NOT STARTED)."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return func(*args, **kwargs), None
    except NotImplementedError:
        raise
    except Exception as exc:  # noqa: BLE001 - classified by the caller
        return None, exc


def _real(value: Any) -> bool:
    return isinstance(value, numbers.Real) and not isinstance(value, (bool, np.bool_))


def _first(cats: Sequence[Optional[str]], priority: Sequence[str]) -> Optional[str]:
    present = {c for c in cats if c}
    return next((c for c in priority if c in present), None)


@contextlib.contextmanager
def _quiet():
    with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        yield


def _esp_resolve(tau: np.ndarray, strike: float, rake: float, dip: float, friction: float,
                 skempton: float) -> np.ndarray:
    """Elastic_stresses_py's resolved values in kPa: (shear, dry normal, pore change, effective normal, Coulomb)."""
    from elastic_stresses_py.PyCoulomb import conversion_math

    return np.asarray(conversion_math.get_coulomb_stresses(np.asarray(tau, dtype=float), strike, rake, dip,
                                                           friction, skempton), dtype=float)


def _three(got: Any, n: Optional[int]) -> Optional[np.ndarray]:
    """The student's (shear, normal, Coulomb) as a (3,) array (n None) or a (3, n) array, or None."""
    if not isinstance(got, tuple) or len(got) != 3:
        return None
    parts = []
    for part in got:
        try:
            arr = np.asarray(part, dtype=float)
        except (TypeError, ValueError):
            return None
        if n is None:
            if arr.shape != ():
                return None
        elif arr.shape != (n,):
            return None
        if not np.all(np.isfinite(arr)):
            return None
        parts.append(arr)
    return np.array(parts)


# =========================================================================================== M54-T1
T1_PRIORITY = ("format", "stack", "order", "units", "frame", "rake-direction", "normal-sign", "pore-pressure",
               "friction", "wrong-values")


def _t1_cases(rng: np.random.Generator, n: int) -> List[dict]:
    fixed = [(0.0, 90.0, 0.0), (90.0, 45.0, 90.0), (359.0, 0.0, -90.0), (200.0, 90.0, 180.0), (45.0, 30.0, 60.0),
             (300.0, 75.0, 20.0), (120.0, 60.0, -150.0), (10.0, 89.0, 5.0)]
    cases = []
    for k in range(n):
        if k < len(fixed):
            s, d, r = fixed[k]
        else:
            s, d, r = rng.uniform(0.0, 360.0), rng.uniform(0.0, 90.0), rng.uniform(-180.0, 180.0)
        a = rng.normal(size=(3, 3)) * 10.0 ** rng.uniform(2.0, 7.0)
        stack = 1 if k % 4 else int(rng.integers(2, 6))
        taus = []
        for _ in range(stack):
            b = rng.normal(size=(3, 3)) * 10.0 ** rng.uniform(2.0, 7.0)
            taus.append(0.5 * (b + b.T) if stack > 1 else 0.5 * (a + a.T))
        cases.append({"angles": (float(s), float(d), float(r)), "taus": np.array(taus), "stack": stack > 1,
                      "friction": float(rng.uniform(0.0, 0.85)),
                      "skempton": 0.0 if k % 3 == 0 else float(rng.uniform(0.05, 0.9))})
    return cases


def _t1_expected(case: dict, variant: str = "") -> np.ndarray:
    """(3, m): shear, effective normal and Coulomb from Elastic_stresses_py, or a known slip of it."""
    s, d, r = case["angles"]
    f, b = case["friction"], case["skempton"]
    out = []
    for tau in case["taus"]:
        t, ang, bb = tau, (s, r, d), b
        if variant == "order":
            ang = (s, d, r)
        elif variant == "frame":
            t = SWAP @ tau @ SWAP
        elif variant == "no-pore":
            bb = 0.0
        elif variant == "pore-sign":
            bb = -b
        vals = _esp_resolve(t, ang[0], ang[1], ang[2], f, bb)
        out.append([vals[0], vals[3], vals[4]])
    return np.array(out).T


def _t1_close(got: np.ndarray, want: np.ndarray, scale: float, rel: float) -> bool:
    return bool(got.shape == want.shape and np.all(np.abs(got - want) <= rel * scale))


def _t1_judge(got: Any, case: dict, rel: float) -> Optional[str]:
    m = len(case["taus"])
    vals = _three(got, m if case["stack"] else None)
    if vals is None:
        if case["stack"] and _three(got, None) is not None:
            return "stack"
        return "format"
    vals = vals.reshape(3, m)
    want = _t1_expected(case)
    scale = max(float(np.abs(case["taus"]).max()) / 1000.0, 1e-12)
    if _t1_close(vals, want, scale, rel):
        return None
    s, d, r = case["angles"]
    if 0.0 <= r <= 90.0 and _t1_close(vals, _t1_expected(case, "order"), scale, rel):
        return "order"
    for factor in (1000.0, 1e-3):
        if _t1_close(vals, factor * want, factor * scale, rel):
            return "units"
    if _t1_close(vals, _t1_expected(case, "frame"), scale, rel):
        return "frame"
    shear_ok = np.all(np.abs(vals[0] - want[0]) <= rel * scale)
    normal_ok = np.all(np.abs(vals[1] - want[1]) <= rel * scale)
    if not shear_ok and np.all(np.abs(vals[0] + want[0]) <= rel * scale):
        return "rake-direction"
    if not normal_ok and np.all(np.abs(vals[1] + want[1]) <= rel * scale):
        return "normal-sign"
    if not normal_ok and case["skempton"] > 0.0:
        for variant in ("no-pore", "pore-sign"):
            alt = _t1_expected(case, variant)
            if np.all(np.abs(vals[1] - alt[1]) <= rel * scale):
                return "pore-pressure"
    if shear_ok and normal_ok:
        return "friction"
    return "wrong-values"


def check_T1(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    rel = float(crit.get("rel_tol", 1e-9))
    cases = _t1_cases(ctx.rng, int(crit.get("trials", 40)))
    oks: List[bool] = []
    cats: List[Optional[str]] = []
    example = None
    for case in cases:
        s, d, r = case["angles"]
        taus = case["taus"] if case["stack"] else case["taus"][0]
        got, err = _call(target, taus.copy(), s, d, r, case["friction"], case["skempton"])
        cat = "format" if err is not None else _t1_judge(got, case, rel)
        oks.append(cat is None)
        cats.append(cat)
        if cat and example is None:
            want = _t1_expected(case)
            example = {"inputs": {"stress_enu_pa": np.round(taus, 1).tolist(), "strike_deg": round(s, 3),
                                  "dip_deg": round(d, 3), "rake_deg": round(r, 3),
                                  "friction": round(case["friction"], 4), "skempton": round(case["skempton"], 4)},
                       "got": (f"{type(err).__name__}: {err}" if err is not None else repr(got)[:200]),
                       "error": "expected (shear, normal, coulomb) in kPa "
                                f"{np.round(want[:, 0] if not case['stack'] else want, 4).tolist()}"}
    return outcome_from_cases(oks, category=_first(cats, T1_PRIORITY), example=example)


# =========================================================================================== M54-T2
T2_PRIORITY = ("format", "order", "units", "slip", "rounded", "centre", "depth", "wrong-values")


def _t2_cases(rng: np.random.Generator, n: int) -> List[dict]:
    cases = []
    for k in range(n):
        dip = 89.99 if k == 1 else float(rng.uniform(5.0, 89.99))
        rake = float(rng.uniform(-180.0, 180.0)) if k % 3 else float(rng.uniform(100.0, 180.0))
        length = float(10.0 ** rng.uniform(math.log10(0.5), math.log10(30.0)))
        width = float(10.0 ** rng.uniform(math.log10(0.5), math.log10(20.0)))
        depth = 0.5 * width * math.sin(math.radians(dip)) + float(rng.uniform(0.3, 15.0))
        cases.append({"strike": float(rng.uniform(0.0, 360.0)), "dip": dip, "rake": rake, "length_km": length,
                      "width_km": width, "lon": float(rng.uniform(124.5, 131.0)), "lat": float(rng.uniform(33.0, 38.8)),
                      "depth_km": depth, "slip_m": float(10.0 ** rng.uniform(-3.0, 0.7))})
    return cases


_NUMBER = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")


def _decimals(text: str) -> int:
    if "e" in text.lower():
        return 99
    return len(text.split(".")[1]) if "." in text else 0


def _t2_judge(got: Any, case: dict, crit: dict) -> Optional[str]:
    if not isinstance(got, str) or "\n" in got.strip():
        return "format"
    fields = got.split("#")[0].split()
    if len(fields) < 10 or fields[0] != "Source_Patch:" or not all(_NUMBER.match(f) for f in fields[1:10]):
        return "format"
    nums = [float(f) for f in fields[1:10]]
    tol_a = float(crit.get("angle_tol_deg", 1e-5))
    if abs(nums[1] - case["dip"]) <= tol_a and abs(nums[2] - case["rake"]) <= tol_a and \
            abs(case["dip"] - case["rake"]) > 1e-3:
        return "order"
    for got_km, want_km in ((nums[3], case["length_km"]), (nums[4], case["width_km"])):
        if abs(got_km - 1000.0 * want_km) <= 1e-3 * 1000.0 * want_km:
            return "units"
    from elastic_stresses_py.PyCoulomb.inputs_object import io_intxt

    try:
        with _quiet():
            fault = io_intxt.get_source_patch(got.strip(), case["lon"], case["lat"])
            centre = np.asarray(fault.get_fault_center(), dtype=float)
    except Exception:  # noqa: BLE001 - Elastic_stresses_py refused the line
        return "format"
    if abs(((fault.strike - case["strike"] + 180.0) % 360.0) - 180.0) > tol_a or \
            abs(fault.dipangle - case["dip"]) > tol_a or abs(fault.rake - case["rake"]) > tol_a:
        return "wrong-values"
    size_tol = float(crit.get("size_rel_tol", 1e-5))
    for got_km, want_km in ((fault.L, case["length_km"]), (fault.W, case["width_km"])):
        if abs(got_km - want_km) > size_tol * want_km + 1e-6:
            if abs(got_km - 1000.0 * want_km) <= 1e-3 * 1000.0 * want_km:
                return "units"
            return "wrong-values"
    slip = math.hypot(fault.rtlat, fault.reverse)
    if abs(slip - case["slip_m"]) > float(crit.get("slip_rel_tol", 1e-5)) * case["slip_m"]:
        return "slip"
    tol_h = float(crit.get("centre_tol_km", 0.005)) + float(crit.get("centre_rel_tol", 0.004)) * 0.5 * (
        case["length_km"] + case["width_km"])
    horizontal = math.hypot(centre[0], centre[1])
    if horizontal > tol_h:
        if min(_decimals(fields[6]), _decimals(fields[7])) < 5 and horizontal < 0.5:
            return "rounded"
        return "centre"
    if abs(centre[2] - case["depth_km"]) > float(crit.get("depth_tol_km", 1e-4)):
        return "rounded" if _decimals(fields[8]) < 4 else "depth"
    return None


def check_T2(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    cases = _t2_cases(ctx.rng, int(crit.get("trials", 30)))
    oks: List[bool] = []
    cats: List[Optional[str]] = []
    example = None
    for case in cases:
        args = (case["strike"], case["dip"], case["rake"], case["length_km"], case["width_km"], case["lon"],
                case["lat"], case["depth_km"], case["slip_m"])
        got, err = _call(target, *args)
        cat = "format" if err is not None else _t2_judge(got, case, crit)
        oks.append(cat is None)
        cats.append(cat)
        if cat and example is None:
            example = {"inputs": {k: round(v, 6) for k, v in case.items()},
                       "got": f"{type(err).__name__}: {err}" if err is not None else repr(got)[:200],
                       "error": "Elastic_stresses_py's reader did not rebuild this fault from your line"}
    return outcome_from_cases(oks, category=_first(cats, T2_PRIORITY), example=example)


# =========================================================================================== M54-T3
T3_PRIORITY = ("format", "units", "strain", "hooke", "moduli", "frame", "slip-sense", "reference", "wrong-values")


def _esp_fault(x0: float, y0: float, strike: float, dip: float, rake: float, top: float, length: float,
               width: float, slip: float):
    """An Elastic_stresses_py fault object (km and m)."""
    from elastic_stresses_py.PyCoulomb.pyc_fault_object import Faults_object
    from tectonic_utils.geodesy import fault_vector_functions as fvf

    x1, y1 = fvf.add_vector_to_point(x0, y0, length, strike)
    rtlat, reverse = fvf.get_rtlat_dip_slip(slip, rake)
    bottom = top + width * math.sin(math.radians(dip))
    return Faults_object(xstart=x0, xfinish=x1, ystart=y0, yfinish=y1, zerolon=127.5, zerolat=36.0, strike=strike,
                         dipangle=dip, rake=rake, top=top, bottom=bottom, rtlat=rtlat, reverse=reverse)


def _esp_stress(fault: Any, points: np.ndarray, lame1: float, mu: float, strain: bool = False) -> np.ndarray:
    """Elastic_stresses_py's stress (Pa) or strain at points (east, north, depth in km), east-north-up axes."""
    from elastic_stresses_py.PyCoulomb import configure_calc, conversion_math, run_dc3d
    from elastic_stresses_py.PyCoulomb.disp_points_object.disp_points_object import Displacement_points
    from elastic_stresses_py.PyCoulomb.inputs_object.input_obj import Input_object

    inputs = Input_object(PR1=0.25, FRIC=0.4, depth=0, start_gridx=-5, finish_gridx=5, start_gridy=-5,
                          finish_gridy=5, xinc=1, yinc=1, minlon=127.4, maxlon=127.6, zerolon=127.5, minlat=35.9,
                          maxlat=36.1, zerolat=36.0, source_object=[fault], receiver_object=[])
    with _quiet():
        params = configure_calc.Params(mu=mu, lame1=lame1, plot_grd_disp=False)
        where = [Displacement_points(lon=float(e), lat=float(n), depth=float(z)) for e, n, z in points]
        eps = np.array(run_dc3d.compute_xy_strain(inputs, params, where), dtype=float)
    if strain:
        return eps
    return np.asarray(conversion_math.stress_tensor_batch(eps, lame1, mu), dtype=float)


def _t3_cases(rng: np.random.Generator, n: int) -> List[dict]:
    from tectonic_utils.geodesy import fault_vector_functions as fvf

    cases = []
    for k in range(n):
        strike = float(rng.uniform(0.0, 360.0))
        dip = 88.0 if k == 0 else float(rng.uniform(10.0, 88.0))
        rake = (0.0, 90.0, 180.0, -90.0)[k] if k < 4 else float(rng.uniform(-180.0, 180.0))
        length, width = float(rng.uniform(0.5, 20.0)), float(rng.uniform(0.5, 15.0))
        top, slip = float(rng.uniform(0.3, 10.0)), float(10.0 ** rng.uniform(-2.5, 0.5))
        x0, y0 = (float(v) for v in rng.uniform(-8.0, 8.0, 2))
        lame1, mu = float(rng.uniform(15e9, 45e9)), float(rng.uniform(15e9, 45e9))
        fault = _esp_fault(x0, y0, strike, dip, rake, top, length, width, slip)
        ce, cn, cz = (float(v) for v in fault.get_fault_center())
        normal = np.asarray(fvf.get_plane_normal(strike, dip), dtype=float)
        pts: List[np.ndarray] = []
        while len(pts) < 12:
            q = np.array([ce, cn, cz]) + rng.normal(size=3) * 1.2 * max(length, width)
            q[2] = abs(q[2]) + 0.2
            rel = np.array([q[0] - ce, q[1] - cn, -(q[2] - cz)])
            if abs(rel @ normal) < 0.25 * max(length, width):
                continue
            pts.append(q)
        cases.append({"fault": {"strike": strike, "dip": dip, "rake": rake, "length_km": length, "width_km": width,
                                "east_km": ce, "north_km": cn, "depth_km": cz, "slip_m": slip},
                      "esp": fault, "points": np.array(pts), "lame1": lame1, "mu": mu})
    return cases


def _t3_judge(got: Any, case: dict, rel: float) -> Optional[str]:
    pts, lame1, mu = case["points"], case["lame1"], case["mu"]
    try:
        g = np.asarray(got, dtype=float)
    except (TypeError, ValueError):
        return "format"
    if g.shape != (len(pts), 3, 3) or not np.all(np.isfinite(g)):
        return "format"
    want = _esp_stress(case["esp"], pts, lame1, mu)

    def close(a: np.ndarray, b: np.ndarray, factor: float = 1.0) -> bool:
        return bool(np.all(np.abs(a - b) <= rel * factor * max(float(np.abs(b).max()), 1e-300)))

    if close(g, want):
        return None
    for factor in (1e-3, 1e3, 1e-6, 1e6):
        if close(g, factor * want, 1.0):
            return "units"
    eps = _esp_stress(case["esp"], pts, lame1, mu, strain=True)
    if close(g, eps) or close(g, 2.0 * mu * eps):
        return "strain"
    if close(g, mu * eps + lame1 * np.trace(eps, axis1=1, axis2=2)[:, None, None] * np.eye(3)):
        return "hooke"
    from elastic_stresses_py.PyCoulomb import conversion_math

    eps_sw = _esp_stress(case["esp"], pts, mu, lame1, strain=True)
    for e_try, l_try, m_try in ((eps_sw, lame1, mu), (eps_sw, mu, lame1), (eps, mu, lame1)):
        if close(g, np.asarray(conversion_math.stress_tensor_batch(e_try, l_try, m_try))):
            return "moduli"
    if close(g, SWAP @ want @ SWAP):
        return "frame"
    f = case["fault"]
    e = case["esp"]
    flipped = _esp_fault(e.xstart, e.ystart, f["strike"], f["dip"], 180.0 - f["rake"], e.top, f["length_km"],
                         f["width_km"], f["slip_m"])
    if abs(math.cos(math.radians(f["rake"]))) > 0.2 and close(g, _esp_stress(flipped, pts, lame1, mu)):
        return "slip-sense"
    z_given = f["depth_km"]
    if z_given > 0.0:
        shifted = _esp_fault(f["east_km"], f["north_km"], f["strike"], f["dip"], f["rake"], z_given,
                             f["length_km"], f["width_km"], f["slip_m"])
        if close(g, _esp_stress(shifted, pts, lame1, mu)):
            return "reference"
    return "wrong-values"


def check_T3(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    rel = float(crit.get("rel_tol", 1e-5))
    cases = _t3_cases(ctx.rng, int(crit.get("trials", 16)))
    oks: List[bool] = []
    cats: List[Optional[str]] = []
    example = None
    for case in cases:
        got, err = _call(target, dict(case["fault"]), case["points"].copy(), case["lame1"], case["mu"])
        cat = "format" if err is not None else _t3_judge(got, case, rel)
        oks.append(cat is None)
        cats.append(cat)
        if cat and example is None:
            want = _esp_stress(case["esp"], case["points"][:1], case["lame1"], case["mu"])[0]
            shown = None
            if err is None:
                try:
                    shown = np.round(np.asarray(got, dtype=float)[0] / 1e3, 4).tolist()
                except (TypeError, ValueError, IndexError):
                    shown = repr(got)[:160]
            example = {"inputs": {"fault": {k: round(v, 4) for k, v in case["fault"].items()},
                                  "first point (east, north, depth km)": np.round(case["points"][0], 4).tolist(),
                                  "lame1_pa": f"{case['lame1']:.4g}", "mu_pa": f"{case['mu']:.4g}"},
                       "got": f"{type(err).__name__}: {err}" if err is not None else f"first point (kPa) {shown}",
                       "error": f"expected at the first point (kPa) {np.round(want / 1e3, 4).tolist()}"}
    return outcome_from_cases(oks, category=_first(cats, T3_PRIORITY), example=example)


# =========================================================================================== M54-T4
T4_PRIORITY = ("format", "radius", "diameter", "metres", "constant", "slip-area", "slip-units", "wrong-values")


def _t4_values(got: Any, shape: Tuple[int, ...]) -> Optional[np.ndarray]:
    if not isinstance(got, tuple) or len(got) != 2:
        return None
    out = []
    for part in got:
        try:
            arr = np.asarray(part, dtype=float)
        except (TypeError, ValueError):
            return None
        if arr.shape != shape or not np.all(np.isfinite(arr)):
            return None
        out.append(arr)
    return np.array(out)


def check_T4(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    rel = float(crit.get("rel_tol", 1e-9))
    rng = ctx.rng
    oks: List[bool] = []
    cats: List[Optional[str]] = []
    example = None
    for k in range(int(crit.get("trials", 200))):
        size = () if k % 5 else (int(rng.integers(2, 7)),)
        radius_m = 10.0 ** rng.uniform(1.5, 4.5, size)
        drop = 10.0 ** rng.uniform(5.0, 8.0, size)
        mu = rng.uniform(20e9, 45e9, size)
        m0 = (16.0 / 7.0) * drop * radius_m ** 3          # Eshelby's circular crack (Part 4), forward
        side_km = math.sqrt(math.pi) * radius_m / 1000.0
        slip_m = m0 / (mu * math.pi * radius_m ** 2)
        args = (float(m0), float(drop), float(mu)) if size == () else (m0.copy(), drop.copy(), mu.copy())
        got, err = _call(target, *args)
        vals = None if err is not None else _t4_values(got, np.shape(side_km))
        cat: Optional[str]
        if vals is None:
            cat = "format"
        elif np.all(np.abs(vals[0] - side_km) <= rel * side_km) and np.all(np.abs(vals[1] - slip_m) <= rel * slip_m):
            cat = None
        else:
            ratio = vals[0] / side_km
            slip_ratio = vals[1] / slip_m

            def near(r: np.ndarray, value: float) -> bool:
                return bool(np.all(np.abs(r - value) <= 1e-6 * abs(value)))

            if near(ratio, 1.0 / math.sqrt(math.pi)):
                cat = "radius"
            elif near(ratio, 2.0 / math.sqrt(math.pi)):
                cat = "diameter"
            elif near(ratio, 1000.0):
                cat = "metres"
            elif near(ratio, (16.0 / 7.0) ** (2.0 / 3.0)) or near(ratio, (7.0 / 16.0) ** (2.0 / 3.0)):
                cat = "constant"
            elif near(ratio, 1.0) and (near(slip_ratio, math.pi) or near(slip_ratio, 1.0 / math.pi)):
                cat = "slip-area"
            elif near(ratio, 1.0) and (near(slip_ratio, 100.0) or near(slip_ratio, 1000.0)):
                cat = "slip-units"
            else:
                cat = "wrong-values"
        oks.append(cat is None)
        cats.append(cat)
        if cat and example is None:
            example = {"inputs": {"m0_nm": np.round(np.atleast_1d(m0), 1).tolist(),
                                  "stress_drop_pa": np.round(np.atleast_1d(drop), 1).tolist(),
                                  "shear_modulus_pa": np.round(np.atleast_1d(mu), 1).tolist()},
                       "got": f"{type(err).__name__}: {err}" if err is not None else repr(got)[:200],
                       "error": f"expected side_km {np.round(np.atleast_1d(side_km), 6).tolist()}, "
                                f"slip_m {np.round(np.atleast_1d(slip_m), 6).tolist()}"}
    return outcome_from_cases(oks, category=_first(cats, T4_PRIORITY), example=example)


# =========================================================================================== M54-T5
T5_PRIORITY = ("format", "calls", "rng", "degrees", "direction", "center", "nan", "observed", "p-value",
               "wrong-values")


class _SectorMap:
    """A made-up Coulomb map that depends only on the compass direction from a centre (and is left out near it)."""

    def __init__(self, rng: np.random.Generator, center: Tuple[float, float]) -> None:
        self.center = center
        starts = np.sort(rng.uniform(0.0, 360.0, int(rng.integers(2, 5))))
        widths = rng.uniform(15.0, 70.0, starts.size)
        self.sectors = list(zip(starts, widths))
        self.gap = (float(rng.uniform(0.0, 360.0)), float(rng.uniform(10.0, 40.0)))
        self.inner_km = float(rng.uniform(0.5, 2.0))
        self.calls: List[Tuple[int, np.ndarray]] = []

    @staticmethod
    def _inside(az: np.ndarray, start: float, width: float) -> np.ndarray:
        return ((az - start) % 360.0) < width

    def value(self, az: np.ndarray, rho: np.ndarray) -> np.ndarray:
        positive = np.zeros(az.shape, dtype=bool)
        for start, width in self.sectors:
            positive |= self._inside(az, start, width)
        out = np.where(positive, 1.0 + rho, -(1.0 + rho))
        out[self._inside(az, *self.gap) | (rho < self.inner_km)] = np.nan
        return out

    def __call__(self, east_km: Any, north_km: Any, depth_km: Any) -> np.ndarray:
        e = np.asarray(east_km, dtype=float)
        n = np.asarray(north_km, dtype=float)
        self.calls.append((e.size, np.asarray(depth_km, dtype=float).copy()))
        de, dn = e - self.center[0], n - self.center[1]
        return self.value(np.degrees(np.arctan2(de, dn)) % 360.0, np.hypot(de, dn))


def _fractions(values: np.ndarray) -> float:
    ok = np.isfinite(values)
    return float(np.mean(values[ok] > 0.0)) if np.any(ok) else float("nan")


def _t5_case(rng: np.random.Generator) -> dict:
    center = (float(rng.uniform(-5.0, 5.0)), float(rng.uniform(-5.0, 5.0)))
    m = _SectorMap(rng, center)
    n = int(rng.integers(30, 120))
    az = rng.uniform(0.0, 360.0, n)
    rho = rng.uniform(0.2, 15.0, n)
    east = center[0] + rho * np.sin(np.radians(az))
    north = center[1] + rho * np.cos(np.radians(az))
    return {"map": m, "east": east, "north": north, "depth": rng.uniform(1.0, 20.0, n), "az": az, "rho": rho,
            "n_rot": int(rng.integers(40, 160)), "seed": int(rng.integers(0, 2 ** 31 - 1))}


def _t5_expected(case: dict, angles: np.ndarray, mode: str = "") -> np.ndarray:
    m = case["map"]
    az, rho = case["az"], case["rho"]
    if mode == "center":                        # turned about (0, 0) instead of the centre
        out = []
        r0 = np.hypot(case["east"], case["north"])
        a0 = np.degrees(np.arctan2(case["east"], case["north"]))
        for a in angles:
            e = r0 * np.sin(np.radians(a0 + a)) - m.center[0]
            n = r0 * np.cos(np.radians(a0 + a)) - m.center[1]
            out.append(_fractions(m.value(np.degrees(np.arctan2(e, n)) % 360.0, np.hypot(e, n))))
        return np.array(out)
    sign = -1.0 if mode == "direction" else 1.0
    scale = (180.0 / math.pi) if mode == "degrees" else 1.0
    return np.array([_fractions(m.value((az + sign * scale * a) % 360.0, rho)) for a in angles])


def _t5_judge(got: Any, case: dict, tol: float) -> Optional[str]:
    keys = {"observed", "null", "angles_deg", "p_value"}
    if not isinstance(got, dict) or set(got) != keys:
        return "format"
    try:
        angles = np.asarray(got["angles_deg"], dtype=float)
        null = np.asarray(got["null"], dtype=float)
        observed, p_value = float(got["observed"]), float(got["p_value"])
    except (TypeError, ValueError):
        return "format"
    n_rot = case["n_rot"]
    if angles.shape != (n_rot,) or null.shape != (n_rot,) or not (np.all(np.isfinite(null)) and
                                                                  math.isfinite(observed) and math.isfinite(p_value)):
        return "format"
    m = case["map"]
    if not m.calls or any(size != case["east"].size for size, _ in m.calls) or \
            any(not np.allclose(depth, case["depth"]) for _, depth in m.calls):
        return "calls"
    want_angles = np.random.default_rng(case["seed"]).uniform(0.0, 360.0, n_rot)
    if not np.allclose(angles, want_angles, rtol=0.0, atol=1e-9):
        return "rng"
    want_null = _t5_expected(case, angles)
    want_obs = _fractions(m.value(case["az"], case["rho"]))
    if not np.allclose(null, want_null, rtol=0.0, atol=tol):
        for mode in ("degrees", "direction", "center"):
            if np.allclose(null, _t5_expected(case, angles, mode), rtol=0.0, atol=tol):
                return mode
        def counted(fill: float) -> List[float]:
            res = []
            for a in angles:
                v = m.value((case["az"] + a) % 360.0, case["rho"])
                res.append(float(np.mean(np.where(np.isfinite(v), v, fill) > 0.0)))
            return res
        if np.allclose(null, counted(-1.0), atol=tol) or np.allclose(null, counted(1.0), atol=tol):
            return "nan"
        return "wrong-values"
    if abs(observed - want_obs) > tol:
        return "observed"
    want_p = (1.0 + float(np.sum(want_null >= want_obs))) / (n_rot + 1.0)
    if abs(p_value - want_p) > tol:
        return "p-value"
    return None


def check_T5(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    tol = float(crit.get("abs_tol", 1e-12))
    oks: List[bool] = []
    cats: List[Optional[str]] = []
    example = None
    for _ in range(int(crit.get("trials", 12))):
        case = _t5_case(ctx.rng)
        got, err = _call(target, case["map"], case["east"].copy(), case["north"].copy(), case["depth"].copy(),
                         case["map"].center[0], case["map"].center[1], case["n_rot"],
                         np.random.default_rng(case["seed"]))
        cat = "format" if err is not None else _t5_judge(got, case, tol)
        oks.append(cat is None)
        cats.append(cat)
        if cat and example is None:
            example = {"inputs": {"points": int(case["east"].size), "center_km": np.round(case["map"].center, 3).tolist(),
                                  "n_rotations": case["n_rot"]},
                       "got": f"{type(err).__name__}: {err}" if err is not None else
                       (f"observed {got.get('observed')!r}, p_value {got.get('p_value')!r}"
                        if isinstance(got, dict) else repr(got)[:160]),
                       "error": "the made-up map's positive fraction is known for every turn by construction"}
    return outcome_from_cases(oks, category=_first(cats, T5_PRIORITY), example=example)


# =========================================================================================== M54-T6
T6_KEYS = {"read_stresses", "coulomb_change", "rotation_test", "okada_stress", "dcfs_at", "faults", "elastic_pa",
           "runs", "sha256", "changed_friction", "points_csv", "receiver", "friction", "skempton", "sensitivity",
           "null", "esp_vs_pyrocko"}
T6_FAULT_KEYS = ("strike", "dip", "rake", "length_km", "width_km", "east_km", "north_km", "depth_km", "slip_m")
T6_FILES = ("ll_stresses.txt", "horizontal_profile_stresses.txt")
T6_PRIORITY = ("format", "read-format", "read-units", "read-order", "resolve", "null-function", "stress-function",
               "runs-missing", "fingerprint", "rerun", "changed-run", "points", "dcfs-function", "esp-vs-pyrocko",
               "sensitivity", "null")


def _write_esp_stress_file(path: Path, rng: np.random.Generator, n: int) -> Tuple[np.ndarray, np.ndarray]:
    """A made-up stress file written by Elastic_stresses_py's own writer; returns (lon, lat, depth) and stress (Pa)."""
    from elastic_stresses_py.PyCoulomb import io_additionals
    from elastic_stresses_py.PyCoulomb.disp_points_object.disp_points_object import Displacement_points

    lame1, mu = float(rng.uniform(20e9, 40e9)), float(rng.uniform(20e9, 40e9))
    where = np.column_stack([rng.uniform(126.0, 130.0, n), rng.uniform(34.0, 38.0, n), rng.uniform(1.0, 25.0, n)])
    strains = []
    for _ in range(n):
        a = rng.normal(size=(3, 3)) * 10.0 ** rng.uniform(-7.0, -4.0)
        strains.append(0.5 * (a + a.T))
    points = [Displacement_points(lon=float(x), lat=float(y), depth=float(z)) for x, y, z in where]
    with _quiet():
        io_additionals.write_stress_results(points, strains, lame1, mu, str(path))
    from elastic_stresses_py.PyCoulomb import conversion_math

    stress = np.array([conversion_math.get_stress_tensor(e, lame1, mu) for e in strains])
    return where, stress


def _read_ok(func: Any, rng: np.random.Generator, folder: Path) -> Optional[str]:
    for k in range(3):
        path = folder / f"made_up_{k}.txt"
        where, stress = _write_esp_stress_file(path, rng, int(rng.integers(3, 12)))
        got, err = _call(func, str(path))
        if err is not None or not isinstance(got, tuple) or len(got) != 4:
            return "read-format"
        try:
            lon, lat, dep = (np.asarray(v, dtype=float) for v in got[:3])
            tau = np.asarray(got[3], dtype=float)
        except (TypeError, ValueError):
            return "read-format"
        n = len(where)
        if lon.shape != (n,) or lat.shape != (n,) or dep.shape != (n,) or tau.shape != (n, 3, 3):
            return "read-format"
        if not (np.allclose(lon, where[:, 0], atol=1e-5) and np.allclose(lat, where[:, 1], atol=1e-5) and
                np.allclose(dep, where[:, 2], atol=1e-5)):
            return "read-format"
        tol = 2e-3 + 1e-9 * np.abs(stress).max()             # the file keeps a fixed number of decimals
        if np.allclose(tau, stress, rtol=0.0, atol=tol):
            continue
        if np.allclose(tau * 1000.0, stress, rtol=0.0, atol=tol) or np.allclose(tau / 1000.0, stress, atol=tol):
            return "read-units"
        return "read-order"
    return None


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _general(path: Path) -> Optional[List[str]]:
    lines = [ln.split() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    found = [ln for ln in lines if ln and ln[0] == "General:"]
    return found[0] if len(found) == 1 else None


def _read_points(path: Path) -> Optional[np.ndarray]:
    import pandas as pd

    try:
        table = pd.read_csv(path)
        cols = ["lon", "lat", "depth_km", "east_km", "north_km"]
        return table[cols].to_numpy(dtype=float)
    except Exception:  # noqa: BLE001 - reported as a category
        return None


def _dcfs_consistent(target: dict, got: Any, pts: np.ndarray, rec: Tuple[float, ...], friction: float,
                     skempton: float, lame1: float, mu: float) -> bool:
    """dcfs_at at pts against the intern's own okada_stress (summed over the faults) and coulomb_change.

    got None: dcfs_at is called here and may give NaN at up to half of the points; otherwise every value must be
    finite."""
    strict = got is not None
    if got is None:
        got, err = _call(target["dcfs_at"], pts[:, 0].copy(), pts[:, 1].copy(), pts[:, 2].copy())
        if err is not None:
            return False
    try:
        got = np.asarray(got, dtype=float).reshape(-1)
    except (TypeError, ValueError):
        return False
    if got.shape != (len(pts),):
        return False
    total = None
    for f in target["faults"].values():
        part, err = _call(target["okada_stress"], dict(f), pts.copy(), lame1, mu)
        if err is not None:
            return False
        part = np.asarray(part, dtype=float)
        total = part if total is None else total + part
    resolved, err = _call(target["coulomb_change"], total, rec[0], rec[1], rec[2], friction, skempton)
    if err is not None:
        return False
    ref = np.asarray(resolved[2], dtype=float).reshape(-1)
    finite = np.isfinite(got)
    if (strict and not finite.all()) or finite.sum() < 0.5 * len(pts):
        return False
    scale = max(float(np.nanmax(np.abs(ref[finite]))), 1e-12)
    return bool(np.all(np.abs(got[finite] - ref[finite]) <= 1e-6 * scale))


def check_T6(target: Any, ctx: Any) -> Outcome:
    crit = ctx.criteria
    rng = ctx.rng
    note = "Real-data part: your files are rerun with your own functions; no value of the check is shown."
    if not isinstance(target, dict) or set(target) != T6_KEYS:
        return outcome_from_cases([False], category="format", note=note)
    funcs = [target[k] for k in ("read_stresses", "coulomb_change", "rotation_test", "okada_stress", "dcfs_at")]
    faults = target["faults"]
    if not all(callable(f) for f in funcs) or not isinstance(target["runs"], dict) or \
            set(target["runs"]) != {"first", "rerun", "changed"} or not isinstance(target["sha256"], dict) or \
            not isinstance(target["null"], dict) or not isinstance(target["sensitivity"], list) or \
            not isinstance(faults, dict) or not faults or \
            not all(isinstance(f, dict) and all(_real(f.get(key)) for key in T6_FAULT_KEYS) for f in faults.values()):
        return outcome_from_cases([False], category="format", note=note)
    try:
        lame1, mu = (float(v) for v in target["elastic_pa"])
        assert lame1 > 0.0 and mu > 0.0
    except (TypeError, ValueError, AssertionError):
        return outcome_from_cases([False], category="format", note=note)
    oks: List[bool] = []
    cats: List[Optional[str]] = []

    def record(cat: Optional[str]) -> None:
        oks.append(cat is None)
        cats.append(cat)

    import tempfile

    with tempfile.TemporaryDirectory(prefix="sgtl_m54_") as tmp:
        record(_read_ok(target["read_stresses"], rng, Path(tmp)))
    # the intern's T1 and T5 again, on made-up cases
    resolve_ok = True
    for case in _t1_cases(rng, 8):
        s, d, r = case["angles"]
        taus = case["taus"] if case["stack"] else case["taus"][0]
        got, err = _call(target["coulomb_change"], taus.copy(), s, d, r, case["friction"], case["skempton"])
        if err is not None or _t1_judge(got, case, 1e-9) is not None:
            resolve_ok = False
    record(None if resolve_ok else "resolve")
    null_ok = True
    for _ in range(3):
        case = _t5_case(rng)
        got, err = _call(target["rotation_test"], case["map"], case["east"].copy(), case["north"].copy(),
                         case["depth"].copy(), case["map"].center[0], case["map"].center[1], case["n_rot"],
                         np.random.default_rng(case["seed"]))
        if err is not None or _t5_judge(got, case, 1e-12) is not None:
            null_ok = False
    record(None if null_ok else "null-function")
    stress_ok = True
    for case in _t3_cases(rng, 3):
        got, err = _call(target["okada_stress"], dict(case["fault"]), case["points"].copy(), case["lame1"],
                         case["mu"])
        if err is not None or _t3_judge(got, case, 1e-5) is not None:
            stress_ok = False
    record(None if stress_ok else "stress-function")
    if not all(oks):
        return outcome_from_cases(oks, category=_first(cats, T6_PRIORITY), note=note)
    # --- the R3 runs
    folders: Dict[str, Path] = {}
    for key in ("first", "rerun", "changed"):
        folder = Path(str(target["runs"][key])).expanduser()
        if not folder.is_absolute():
            folder = Path.cwd() / folder
        if not all((folder / name).is_file() for name in T6_FILES + ("used_inputs.txt",)):
            record("runs-missing")
            return outcome_from_cases(oks, category=_first(cats, T6_PRIORITY), real_data=True, note=note)
        folders[key] = folder
    if len({str(p.resolve()) for p in folders.values()}) != 3:
        record("runs-missing")
        return outcome_from_cases(oks, category=_first(cats, T6_PRIORITY), real_data=True, note=note)
    shas = {key: {name: _sha(folders[key] / name) for name in T6_FILES} for key in folders}
    told = target["sha256"]
    same = all(isinstance(told.get(key), dict) and all(str(told[key].get(name, "")).lower() == shas[key][name]
                                                       for name in T6_FILES) for key in folders)
    record(None if same else "fingerprint")
    record(None if all(shas["first"][n] == shas["rerun"][n] for n in T6_FILES) else "rerun")
    g1, g2 = _general(folders["first"] / "used_inputs.txt"), _general(folders["changed"] / "used_inputs.txt")
    other1 = [ln for ln in (folders["first"] / "used_inputs.txt").read_text(encoding="utf-8").splitlines()
              if ln.strip() and not ln.startswith(("General:", "#"))]
    other2 = [ln for ln in (folders["changed"] / "used_inputs.txt").read_text(encoding="utf-8").splitlines()
              if ln.strip() and not ln.startswith(("General:", "#"))]
    changed_ok = (g1 is not None and g2 is not None and len(g1) == len(g2) == 9 and other1 == other2 and
                  sum(1 for i in range(1, 9) if abs(float(g1[i]) - float(g2[i])) > 1e-9) == 1 and
                  abs(float(g1[2]) - float(g2[2])) > 1e-9 and _real(target["changed_friction"]) and
                  abs(float(g2[2]) - float(target["changed_friction"])) <= 5e-4 and
                  sum(1 for ln in other1 if ln.startswith("Source_Patch:")) >= 2)
    record(None if changed_ok else "changed-run")
    # --- the points, and Elastic_stresses_py against the intern's pyrocko-based Coulomb change
    raw = np.loadtxt(folders["first"] / "ll_stresses.txt", ndmin=2)
    read, err = _call(target["read_stresses"], str(folders["first"] / "ll_stresses.txt"))
    if err is not None:
        record("read-format")
        return outcome_from_cases(oks, category=_first(cats, T6_PRIORITY), real_data=True, note=note)
    tau = np.asarray(read[3], dtype=float)
    table = _read_points(Path(str(target["points_csv"])))
    if table is None or table.shape[0] != raw.shape[0] or not (
            np.allclose(table[:, 0], raw[:, 0], atol=2e-6) and np.allclose(table[:, 1], raw[:, 1], atol=2e-6) and
            np.allclose(table[:, 2], raw[:, 2], atol=2e-6)) or raw.shape[0] < int(crit.get("min_points", 20)):
        record("points")
        return outcome_from_cases(oks, category=_first(cats, T6_PRIORITY), real_data=True, note=note)
    try:
        rec = tuple(float(v) for v in target["receiver"])
        friction, skempton = float(target["friction"]), float(target["skempton"])
        assert len(rec) == 3 and 0.0 <= skempton <= 1.0
    except (TypeError, ValueError, AssertionError):
        return outcome_from_cases([False], category="format", note=note)
    resolved, err = _call(target["coulomb_change"], tau, rec[0], rec[1], rec[2], friction, skempton)
    if err is not None:
        return outcome_from_cases([False], category="resolve", note=note)
    esp_cfs = np.asarray(resolved[2], dtype=float)
    mine, err = _call(target["dcfs_at"], table[:, 3].copy(), table[:, 4].copy(), table[:, 2].copy())
    # dcfs_at must be the intern's okada_stress of the faults, summed and resolved: at the points of the run and at
    # made-up points around them (NaN allowed there, near a fault, but not for most of them)
    pts_run = table[:, [3, 4, 2]]
    shifted = pts_run[rng.integers(0, len(pts_run), 40)] + np.column_stack(
        [rng.uniform(-3.0, 3.0, 40), rng.uniform(-3.0, 3.0, 40), rng.uniform(-2.0, 2.0, 40)])
    shifted[:, 2] = np.abs(shifted[:, 2]) + 0.5
    record(None if err is None and _dcfs_consistent(target, mine, pts_run, rec, friction, skempton, lame1, mu) and
           _dcfs_consistent(target, None, shifted, rec, friction, skempton, lame1, mu) else "dcfs-function")
    agree = False
    if err is None:
        mine = np.asarray(mine, dtype=float)
        if mine.shape == esp_cfs.shape and np.all(np.isfinite(mine)):
            diff = float(np.abs(mine - esp_cfs).max() / max(float(np.abs(esp_cfs).max()), 1e-12))
            agree = diff <= float(crit.get("esp_pyrocko_rel", 1e-3)) and _real(target["esp_vs_pyrocko"]) and \
                abs(float(target["esp_vs_pyrocko"]) - diff) <= 1e-6 + 1e-3 * diff
    record(None if agree else "esp-vs-pyrocko")
    # --- sensitivity rows, recomputed from the first run's stresses with the intern's own function
    sens_ok = len(target["sensitivity"]) >= int(crit.get("min_rows", 6))
    seen = set()
    for row in target["sensitivity"] if sens_ok else []:
        try:
            r3 = tuple(float(v) for v in row["receiver"])
            fr, n_pts, frac = float(row["friction"]), int(row["n"]), float(row["fraction"])
        except (TypeError, ValueError, KeyError):
            sens_ok = False
            break
        seen.add((r3, fr))
        resolved, err = _call(target["coulomb_change"], tau, r3[0], r3[1], r3[2], fr, skempton)
        if err is not None:
            sens_ok = False
            break
        cfs = np.asarray(resolved[2], dtype=float)
        if n_pts != cfs.size or abs(frac - float(np.mean(cfs > 0.0))) > 1e-9:
            sens_ok = False
    frictions = {fr for _, fr in seen}
    receivers = {r3 for r3, _ in seen}
    if len(frictions) < 3 or len(receivers) < 2:
        sens_ok = False
    record(None if sens_ok else "sensitivity")
    # --- the rotation test again, with the intern's own functions and seed
    null = target["null"]
    try:
        seed, n_rot = int(null["seed"]), int(null["n_rotations"])
        ce, cn = (float(v) for v in null["center_km"])
        want = target["rotation_test"](target["dcfs_at"], table[:, 3].copy(), table[:, 4].copy(),
                                       table[:, 2].copy(), ce, cn, n_rot, np.random.default_rng(seed))
        good = (n_rot >= int(crit.get("min_rotations", 100)) and
                abs(float(null["observed"]) - float(want["observed"])) <= 1e-9 and
                abs(float(null["null_mean"]) - float(np.mean(want["null"]))) <= 1e-9 and
                abs(float(null["p_value"]) - float(want["p_value"])) <= 1e-9)
    except Exception:  # noqa: BLE001 - anything wrong in the record is a category
        good = False
    record(None if good else "null")
    return outcome_from_cases(oks, category=_first(cats, T6_PRIORITY), real_data=True, note=note)
