"""PyFK runner: synthetic seismograms from the separate PyFK environment, passed back through files.

PyFK (Xi et al., https://github.com/ziyixi/pyfk) computes synthetic seismograms in a layered (1-D) Earth with the
frequency-wavenumber (FK) method of Zhu & Rivera (2002). Its conda package needs Python 3.9, so
``bin/sgtl-install pyfk --apply`` puts it in its own small environment ``~/sgtl/envs/sgtl-pyfk`` (a worker
environment, not a Jupyter kernel). This file is both halves of the bridge:

* in the course environment, :func:`run` writes a request (plain JSON), starts the PyFK environment's Python on
  this same file, waits, and reads the result back with :func:`load`;
* in the PyFK environment, the worker (``python -I pyfk_runner.py --worker request.json``) builds PyFK's
  ``SeisModel``, ``SourceModel`` and ``Config`` from the request, calls ``calculate_gf`` once for all distances and
  ``calculate_sync`` once per receiver, and writes plain numbers: ``result.npz`` (numeric arrays only, read with
  ``allow_pickle=False``), ``result.json`` (the request, versions, run time, SHA-256 of the npz) and, if asked, one
  SAC file per receiver and component. Nothing is pickled across the two environments.

The runner adds nothing to PyFK's physics: the source list goes to ``SourceModel(source_mechanism=...)`` exactly as
given, and the arrays ``z``, ``r``, ``t`` are exactly what ``calculate_sync`` returns (Z up, R away from the source,
T clockwise seen from above). PyFK's docstrings describe both; module M52 measures what they mean. Read PyFK's
``SourceModel.calculate_radiation_pattern`` to see how it reads a source list of each length.

PyFK chooses its wavenumber step from the LARGEST distance of a call (``dk * pi / max(distance, depth)``), so one
station can come out a little differently when it is computed alone or together with far stations. The runner
always makes one call for all the distances of a request and records the step in ``result.json``; compute the
synthetics you compare in the same way.

In a notebook::

    from sgtl_tutorial import pyfk_runner as fk
    layers = fk.model_layers(st.data.velocity_model("kim1983"))
    res = fk.run(layers, source_depth_km=10.0, distances_km=[20.0, 40.0], azimuths_deg=[30.0, 120.0],
                 source=[...], dt_s=0.05, npt=2048, stf=stf_samples, out_dir="results/fk_demo")
    res.z[0], res.times(0)                  # first receiver: vertical samples and seconds after the origin

Server manners: one core (thread caps), ``nice -n 15``, a memory cap (2 GB by default) and a time limit.

Credit: Minseong Seo (SGTL, Seoul National University). License: MIT.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

__all__ = ["pyfk_python", "model_layers", "trapezoid_stf", "run", "load", "FKResult", "ENV_NAME"]

ENV_NAME = "sgtl-pyfk"
REQUEST_VERSION = 1
COMPONENTS = ("z", "r", "t")
THREAD_CAPS = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
               "NUMEXPR_NUM_THREADS": "1", "NUMPY_MADVISE_HUGEPAGE": "0"}


# ============================================================================== course-environment side
def pyfk_python() -> Path:
    """The Python of the PyFK environment: ``$SGTL_PYFK_PYTHON`` if set, else ``$SGTL_HOME/envs/sgtl-pyfk/bin/python``
    (``SGTL_HOME`` defaults to ``~/sgtl``). Raises FileNotFoundError with the install command when it is missing."""
    env = os.environ.get("SGTL_PYFK_PYTHON", "").strip()
    if env:
        path = Path(env).expanduser()
    else:
        home = os.environ.get("SGTL_HOME", "").strip()
        root = Path(home).expanduser() if home else Path.home() / "sgtl"
        path = root / "envs" / ENV_NAME / "bin" / "python"
    if not path.is_file():
        raise FileNotFoundError(
            f"The PyFK environment's Python was not found at {path}. Install it once with "
            "'bin/sgtl-install pyfk --apply' (about 1 minute), or set SGTL_PYFK_PYTHON to that Python.")
    return path


def model_layers(model: Any, *, density: Optional[Sequence[float]] = None, qs: float = 500.0,
                 qp: float = 1000.0) -> List[List[float]]:
    """PyFK's layer rows from a course velocity model (columns ``top_km``, ``vp``, ``vs``, as from
    ``st.data.velocity_model``).

    Each row is ``[thickness_km, vs, vp, density, qs, qp]`` (PyFK's column order); the last layer is the half-space
    (thickness 0). Without ``density`` the rows use density = 0.77 + 0.32 vp (g/cm3, vp in km/s), a straight-line
    rule of thumb that ties density to P speed (Berteussen 1977), the same rule as the test run that
    ``bin/sgtl-install pyfk --apply`` makes after installing PyFK; qs and qp are quality factors (larger = less
    attenuation)."""
    tops = [float(v) for v in model["top_km"]]
    vp = [float(v) for v in model["vp"]]
    vs = [float(v) for v in model["vs"]]
    if not tops or tops[0] != 0.0 or any(b <= a for a, b in zip(tops, tops[1:])):
        raise ValueError("top_km must start at 0 and increase from layer to layer.")
    if density is not None and len(density) != len(tops):
        raise ValueError("density needs one value per layer.")
    rows = []
    for i in range(len(tops)):
        thick = tops[i + 1] - tops[i] if i + 1 < len(tops) else 0.0
        rho = float(density[i]) if density is not None else 0.77 + 0.32 * vp[i]
        rows.append([thick, vs[i], vp[i], rho, float(qs), float(qp)])
    return rows


def trapezoid_stf(duration_s: float, rise: float, dt_s: float) -> List[float]:
    """The samples of PyFK's ``generate_source_time_function(dura, rise, delta)`` (a trapezoid whose samples add up
    to 1), written out so that the course environment can draw it without PyFK."""
    ns = max(int(duration_s / dt_s), 2)
    nr = max(int(rise * ns), 1)
    if 2 * nr > ns:
        nr = ns / 2
    amp = 1.0 / (nr * (ns - nr))
    out = []
    for i in range(ns + 1):
        if i < nr:
            out.append(amp * i)
        elif i < ns - nr:
            out.append(nr * amp)
        else:
            out.append((ns - i) * amp)
    return out


class FKResult:
    """What one PyFK run wrote. Arrays have one row per receiver (in the order of the request).

    ``z``, ``r``, ``t``: calculate_sync's samples, unchanged. ``b_s``: seconds after the origin of each row's first
    sample; ``dt_s``: sample interval; ``t_p_s``, ``t_s_s``: PyFK's first P and S arrival times (SAC headers t1, t2);
    ``takeoff_p_deg``, ``takeoff_s_deg``: PyFK's take-off angles of those first arrivals (SAC headers user1, user2);
    ``meta``: the request and the run record (``result.json``); ``path``: the folder."""

    def __init__(self, path: Path, arrays: Dict[str, Any], meta: Dict[str, Any]):
        self.path = Path(path)
        self.meta = meta
        self.z, self.r, self.t = arrays["z"], arrays["r"], arrays["t"]
        self.b_s, self.t_p_s, self.t_s_s = arrays["b_s"], arrays["t_p_s"], arrays["t_s_s"]
        self.takeoff_p_deg, self.takeoff_s_deg = arrays["takeoff_p_deg"], arrays["takeoff_s_deg"]
        self.distances_km, self.azimuths_deg = arrays["distances_km"], arrays["azimuths_deg"]
        self.dt_s = float(arrays["dt_s"])

    def __len__(self) -> int:
        return int(len(self.distances_km))

    def times(self, i: int):
        """Seconds after the origin time of the samples of receiver ``i``."""
        import numpy as np
        return float(self.b_s[i]) + self.dt_s * np.arange(self.z.shape[1])

    def component(self, name: str):
        """The array of one component: 'z', 'r' or 't'."""
        if name not in COMPONENTS:
            raise ValueError("component must be 'z', 'r' or 't'")
        return getattr(self, name)

    def __repr__(self) -> str:
        return (f"FKResult({len(self)} receivers, {self.z.shape[1]} samples at {self.dt_s:g} s, "
                f"folder {self.path.name})")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load(out_dir: Any) -> FKResult:
    """Read a finished run (``result.npz`` and ``result.json`` in ``out_dir``), checking the npz against the
    SHA-256 that the worker recorded."""
    import numpy as np
    folder = Path(out_dir)
    npz, meta_path = folder / "result.npz", folder / "result.json"
    if not (npz.is_file() and meta_path.is_file()):
        raise FileNotFoundError(f"No finished PyFK run in {folder} (result.npz and result.json are missing).")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("npz_sha256") != _sha256(npz):
        raise ValueError(f"{npz} does not match the SHA-256 in result.json: the run is incomplete or was edited. "
                         "Run it again.")
    with np.load(npz, allow_pickle=False) as data:
        arrays = {k: data[k] for k in data.files}
    return FKResult(folder, arrays, meta)


def _request(layers: Sequence[Sequence[float]], source_depth_km: float, distances_km: Sequence[float],
             azimuths_deg: Any, source: Sequence[float], src_type: str, dt_s: float, npt: int,
             stf: Sequence[float], receiver_depth_km: float, samples_before_first_arrival: int,
             write_sac: bool, config_extra: Dict[str, Any]) -> Dict[str, Any]:
    dists = [float(d) for d in distances_km]
    if not dists or any(not math.isfinite(d) or d <= 0 for d in dists):
        raise ValueError("distances_km must be positive numbers.")
    if isinstance(azimuths_deg, (int, float)):
        azis = [float(azimuths_deg)] * len(dists)
    else:
        azis = [float(a) for a in azimuths_deg]
    if len(azis) != len(dists):
        raise ValueError("Give one azimuth per distance (or one number for all).")
    rows = [[float(v) for v in row] for row in layers]
    if not rows or any(len(row) != 6 for row in rows):
        raise ValueError("Each layer row needs 6 numbers: thickness_km, vs, vp, density, qs, qp (see model_layers).")
    src = [float(v) for v in source]
    if src_type not in ("dc", "sf", "ep"):
        raise ValueError("src_type must be 'dc', 'sf' or 'ep'.")
    pulse = [float(v) for v in stf]
    if len(pulse) < 2 or not all(math.isfinite(v) for v in pulse):
        raise ValueError("stf must hold at least two finite samples (at dt_s).")
    if int(npt) < 16 or float(dt_s) <= 0:
        raise ValueError("npt must be at least 16 and dt_s positive.")
    allowed = {"dk", "taper", "smth", "pmin", "pmax", "kmax", "updn", "suppression_sigma", "filter"}
    unknown = sorted(set(config_extra) - allowed)
    if unknown:
        raise ValueError(f"Unknown PyFK Config options: {', '.join(unknown)} (allowed: {', '.join(sorted(allowed))}).")
    return {"version": REQUEST_VERSION, "layers": rows, "source_depth_km": float(source_depth_km),
            "receiver_depth_km": float(receiver_depth_km), "distances_km": dists, "azimuths_deg": azis,
            "source": src, "src_type": src_type, "dt_s": float(dt_s), "npt": int(npt), "stf": pulse,
            "samples_before_first_arrival": int(samples_before_first_arrival), "write_sac": bool(write_sac),
            "config": {k: config_extra[k] for k in sorted(config_extra)}}


def run(layers: Sequence[Sequence[float]], *, source_depth_km: float, distances_km: Sequence[float],
        azimuths_deg: Any, source: Sequence[float], dt_s: float, npt: int, stf: Sequence[float], out_dir: Any,
        src_type: str = "dc", receiver_depth_km: float = 0.0, samples_before_first_arrival: int = 50,
        write_sac: bool = False, timeout_s: float = 900.0, mem_gb: float = 2.0, quiet: bool = False,
        **config_extra: Any) -> FKResult:
    """Run PyFK in its own environment and return the result (see :class:`FKResult`).

    layers: rows of :func:`model_layers`. source_depth_km, receiver_depth_km: depths below the free surface (km).
    distances_km, azimuths_deg: horizontal distance of each receiver and its azimuth from the source (degrees
    clockwise from north; one number = the same for all). source: the list handed to PyFK's
    ``SourceModel(source_mechanism=...)`` unchanged; src_type: 'dc', 'sf' or 'ep'. dt_s, npt: sample interval and
    number of samples. stf: the source time function's samples at dt_s, handed to ``calculate_sync`` unchanged (for
    example :func:`trapezoid_stf`). out_dir: a new or reusable folder for request.json, result.npz, result.json and
    the SAC files (``<i>.<distance>km.<z|r|t>.sac`` when write_sac). Extra keywords go to PyFK's ``Config``
    (dk, taper, smth, pmin, pmax, kmax, updn, suppression_sigma, filter). Every run starts from scratch and replaces
    the folder's earlier result."""
    req = _request(layers, source_depth_km, distances_km, azimuths_deg, source, src_type, dt_s, npt, stf,
                   receiver_depth_km, samples_before_first_arrival, write_sac, config_extra)
    folder = Path(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("result.npz", "result.json"):
        (folder / name).unlink(missing_ok=True)
    for old in folder.glob("*.sac"):
        old.unlink()
    req_path = folder / "request.json"
    req_path.write_text(json.dumps(req, indent=1) + "\n", encoding="utf-8")
    python = pyfk_python()
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME", "LD_LIBRARY_PATH")}
    env.update(THREAD_CAPS)
    env["PATH"] = os.pathsep.join([str(python.parent), "/usr/local/bin", "/usr/bin", "/bin"])
    cmd = [str(python), "-I", str(Path(__file__).resolve()), "--worker", str(req_path.resolve())]
    if Path("/usr/bin/nice").is_file() or Path("/bin/nice").is_file():
        cmd = ["nice", "-n", "15"] + cmd
    limit = int(mem_gb * 1024 ** 3)

    def _cap() -> None:  # runs in the child before PyFK starts
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        except (ImportError, ValueError, OSError):
            pass

    if not quiet:
        print(f"PyFK: {len(req['distances_km'])} receiver(s), {req['npt']} samples at {req['dt_s']:g} s, "
              f"source {req['source_depth_km']:g} km deep -> {folder}")
    t0 = time.time()
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout_s,
                          preexec_fn=_cap if os.name == "posix" else None)
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout or "").strip().splitlines()[-15:])
        raise RuntimeError(f"The PyFK worker stopped with return code {proc.returncode}:\n{tail}")
    result = load(folder)
    if not quiet:
        print(f"PyFK: done in {time.time() - t0:.1f} s (wavenumber step {result.meta.get('dk_per_km', float('nan')):.4g}"
              f" per km, from the largest distance {result.meta.get('xmax_km', float('nan')):g} km)")
    return result


# ============================================================================== PyFK-environment side
def _worker(req_path: str) -> int:
    import numpy as np
    import obspy
    import pyfk
    from pyfk import Config, SeisModel, SourceModel, calculate_gf, calculate_sync

    t_start = time.time()
    req_file = Path(req_path)
    req = json.loads(req_file.read_text(encoding="utf-8"))
    if req.get("version") != REQUEST_VERSION:
        raise SystemExit(f"request version {req.get('version')} is not {REQUEST_VERSION}")
    folder = req_file.parent
    dt = float(req["dt_s"])
    model = SeisModel(model=np.array(req["layers"], dtype=float))
    source = SourceModel(sdep=float(req["source_depth_km"]), srcType=req["src_type"],
                         source_mechanism=list(req["source"]))
    extra = dict(req.get("config") or {})
    if "filter" in extra:
        extra["filter"] = tuple(extra["filter"])
    config = Config(model=model, source=source, receiver_distance=list(req["distances_km"]), npt=int(req["npt"]),
                    dt=dt, rdep=float(req["receiver_depth_km"]),
                    samples_before_first_arrival=int(req["samples_before_first_arrival"]), **extra)
    basis = calculate_gf(config)
    pulse = obspy.Trace(data=np.array(req["stf"], dtype=float))
    pulse.stats.delta = dt
    n_rec = len(req["distances_km"])
    out = {c: [] for c in COMPONENTS}
    b_s, t_p, t_s, i_p, i_s = [], [], [], [], []
    for i in range(n_rec):
        three = calculate_sync(basis[i], config, float(req["azimuths_deg"][i]), pulse)[0]
        for c, tr in zip(COMPONENTS, three):
            out[c].append(np.asarray(tr.data, dtype=float))
        sac = three[0].stats.sac
        b_s.append(float(sac["b"]))
        t_p.append(float(sac["t1"]))
        t_s.append(float(sac["t2"]))
        i_p.append(float(sac["user1"]))
        i_s.append(float(sac["user2"]))
        if req.get("write_sac"):
            for c, tr in zip(COMPONENTS, three):
                tr.stats.network, tr.stats.station = "SY", f"R{i:03d}"
                tr.stats.channel = {"z": "BXZ", "r": "BXR", "t": "BXT"}[c]
                tr.write(str(folder / f"{i:03d}.{req['distances_km'][i]:g}km.{c}.sac"), format="SAC")
    npts = min(len(a) for a in out["z"])
    arrays = {c: np.vstack([a[:npts] for a in out[c]]) for c in COMPONENTS}
    arrays.update(b_s=np.array(b_s), t_p_s=np.array(t_p), t_s_s=np.array(t_s), takeoff_p_deg=np.array(i_p),
                  takeoff_s_deg=np.array(i_s),
                  distances_km=np.array(req["distances_km"], dtype=float),
                  azimuths_deg=np.array(req["azimuths_deg"], dtype=float), dt_s=np.array(dt))
    npz = folder / "result.npz"
    np.savez(npz, **arrays)
    xmax = max(float(req["source_depth_km"]), max(req["distances_km"]))
    meta = {"request": req, "npz_sha256": _sha256(npz), "seconds": round(time.time() - t_start, 3),
            "xmax_km": xmax, "dk_per_km": float(config.dk) * math.pi / xmax,
            "m0_pyfk": float(config.source.m0),
            "versions": {"python": sys.version.split()[0], "pyfk": getattr(pyfk, "__version__", "?"),
                         "obspy": obspy.__version__, "numpy": np.__version__},
            "outputs": ("z, r, t = calculate_sync samples, unchanged; b_s, t_p_s, t_s_s, takeoff_p_deg, takeoff_s_deg "
                        "from the SAC headers b, t1, t2, user1, user2")}
    (folder / "result.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        sys.exit(_worker(sys.argv[2]))
    sys.exit("usage: python -I pyfk_runner.py --worker request.json   (started by sgtl_tutorial.pyfk_runner.run)")
