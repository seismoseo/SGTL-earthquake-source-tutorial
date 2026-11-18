# shellcheck shell=bash
# install/components/pyfk.sh: the PyFK synthetic-seismogram environment "sgtl-pyfk" (sourced by bin/sgtl-install).
#
# PyFK computes synthetic seismograms in a layered (1-D) Earth with the frequency-wavenumber (FK) method.
# Its published conda package needs Python 3.9, so it gets its own small environment ~/sgtl/envs/sgtl-pyfk,
# made from envs/pyfk.yml. It is a worker environment, not a Jupyter kernel: notebooks run its python to write
# Green's functions to files that the course environment reads.
# Steps: find conda or mamba (or install the pinned Miniforge, as the env component does), create the
# environment (or update it when envs/pyfk.yml has changed), then a check-up that computes one seismogram.
# Uses the helpers of bin/sgtl-install and of install/components/env.sh.
#
# Copyright (c) 2026 Minseong Seo (SGTL, Seoul National University). MIT License.

PYFK_ENV_NAME="sgtl-pyfk"
PYFK_MIN_FREE_GB=2

if ! declare -F env_find_conda >/dev/null; then
  # shellcheck source=/dev/null
  source "$COMPONENT_DIR/env.sh"
fi

component_pyfk_summary() {
  printf '%s' 'PyFK synthetic-seismogram environment "sgtl-pyfk" (Python 3.9, PyFK 0.3.0)'
}

pyfk_check_disk() {
  local dir="$SGTL_HOME" avail_kb
  while [[ ! -d "$dir" ]]; do dir="$(dirname "$dir")"; done
  avail_kb="$(df -Pk "$dir" 2>/dev/null | awk 'NR == 2 { print $4 }')" || return 0
  [[ "$avail_kb" =~ ^[0-9]+$ ]] || return 0
  if ((avail_kb < PYFK_MIN_FREE_GB * 1048576)); then
    warn "Only about $((avail_kb / 1048576)) GB is free in $dir; the PyFK environment needs about $PYFK_MIN_FREE_GB GB."
  fi
}

# The check-up: one synthetic seismogram for the Kim and Kim (1983) crust (data/velocity_models/kim1983.csv),
# source 10 km deep, receiver 30 km away. It must give finite, non-zero traces. Prints versions, time, memory.
PYFK_CHECKUP=$(
  cat <<'PY'
import csv, resource, sys, time
import numpy as np
import obspy, scipy
import pyfk
from pyfk import Config, SeisModel, SourceModel, calculate_gf, calculate_sync, generate_source_time_function

t_start = time.time()
with open(sys.argv[1], newline="") as fh:
    rows = [(float(r["top_km"]), float(r["vp"]), float(r["vs"])) for r in csv.DictReader(fh)]
tops = [r[0] for r in rows]
# PyFK reads the model in the FK column order: thickness (km), Vs, Vp (km/s), density (g/cm3), Qs, Qp.
# The last layer is the half-space below the Moho: thickness 0. Density and Q are PyFK's own defaults.
layers = np.array([[(tops[i + 1] - tops[i]) if i + 1 < len(rows) else 0.0, vs, vp, 0.77 + 0.32 * vp, 500.0, 1000.0]
                   for i, (_, vp, vs) in enumerate(rows)])
earth = SeisModel(model=layers)
# Double couple given as (magnitude Mw, strike, dip, rake) in degrees.
quake = SourceModel(sdep=10.0, srcType="dc", source_mechanism=[3.5, 30.0, 60.0, 90.0])
setup = Config(model=earth, source=quake, receiver_distance=[30.0], npt=1024, dt=0.02)
basis = calculate_gf(setup)
pulse = generate_source_time_function(dura=0.4, rise=0.5, delta=0.02)
three = calculate_sync(basis, setup, 45.0, pulse)[0]
seconds = time.time() - t_start
peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0

print("versions: python %s, pyfk %s, obspy %s, numpy %s, scipy %s" % (
    sys.version.split()[0], pyfk.__version__, obspy.__version__, np.__version__, scipy.__version__))
print("layers (thickness km, Vs, Vp, density, Qs, Qp):")
for row in layers:
    print("  " + " ".join("%7.2f" % v for v in row))
for label, tr in zip(("vertical", "radial", "transverse"), three):
    print("  %-10s %d samples, dt %.3f s, max |value| %.3e" % (label, tr.stats.npts, tr.stats.delta,
                                                                np.abs(tr.data).max()))
ok = len(three) == 3 and all(np.isfinite(tr.data).all() and np.abs(tr.data).max() > 0 for tr in three)
print("run time %.1f s, peak memory %.0f MB" % (seconds, peak_mb))
if not ok:
    sys.exit("PyFK check-up FAILED: the three traces must be finite and not all zero.")
print("PyFK check-up OK: three finite, non-zero traces (vertical, radial, transverse).")
PY
)

component_pyfk_run() {
  step "PyFK synthetic-seismogram environment \"$PYFK_ENV_NAME\" (pyfk)"
  local prefix="$SGTL_HOME/envs/$PYFK_ENV_NAME" env_file="$REPO/envs/pyfk.yml" stamp want model
  local paths="$SGTL_HOME/envs/$PYFK_ENV_NAME/bin:/usr/local/bin:/usr/bin:/bin"
  model="$REPO/data/velocity_models/kim1983.csv"
  stamp="$prefix/.sgtl-envfile.sha256"
  [[ -f "$env_file" ]] || die "The environment file $env_file is missing; is this a complete copy of the tutorial?"
  [[ -f "$model" ]] || die "The velocity model $model is missing; is this a complete copy of the tutorial?"
  env_clean_shell
  pyfk_check_disk

  # 1. conda or mamba (the same one the course environment uses)
  if env_find_conda; then
    CONDA_KIND="$(env_conda_kind "$CONDA")"
    say "Using $CONDA_KIND: $CONDA"
  else
    env_install_miniforge
    CONDA_KIND=conda
  fi
  if [[ "$CONDA" != "$SGTL_HOME/miniforge3/"* ]]; then
    export CONDA_PKGS_DIRS="$SGTL_HOME/conda-pkgs"
  fi
  export CONDA_ALWAYS_YES=true MAMBA_ALWAYS_YES=true

  # 2. the environment; envs/pyfk.yml pins Python 3.9, PyFK 0.3.0 (channel ziyixi), ObsPy 1.4.2, NumPy 1.26.4
  say "Environment: $prefix  (from $env_file)"
  want="$(sha256_of "$env_file")"
  if [[ -d "$prefix" && $REBUILD -eq 1 ]]; then
    run rm -rf -- "$prefix"
  fi
  if [[ -d "$prefix" && $REBUILD -eq 0 ]]; then
    [[ -d "$prefix/conda-meta" ]] ||
      die "$prefix exists but is not a conda environment. Move it away, or add --rebuild to delete it."
    if [[ -f "$stamp" && "$(cat "$stamp")" == "$want" ]]; then
      say "The environment exists and matches envs/pyfk.yml: nothing to update (add --rebuild to start from scratch)."
    else
      say "The environment exists: updating it from envs/pyfk.yml (add --rebuild to start from scratch)."
      env_update "$prefix" "$env_file" ||
        die "Updating the PyFK environment failed (see the messages above). Try: bin/sgtl-install pyfk --apply --rebuild"
    fi
  else
    run mkdir -p "$SGTL_HOME/envs"
    env_create "$prefix" "$env_file" ||
      die "Creating the PyFK environment failed (see the messages above). Run the same command again; if it fails again, send the last 30 lines to the mentor (friction issue)."
  fi

  # 3. check-up: one synthetic seismogram (finite and non-zero), with versions, run time and memory
  action "check-up: one PyFK seismogram for the kim1983 model, source 10 km deep, receiver 30 km away"
  if [[ $APPLY -eq 1 ]]; then
    "${NICE[@]}" env -u LD_LIBRARY_PATH "PATH=$paths" "$prefix/bin/python" -c "$PYFK_CHECKUP" "$model" ||
      die "The PyFK check-up failed (see the messages above). Try: bin/sgtl-install pyfk --apply --rebuild"
    printf '%s\n' "$want" >"$stamp"
  fi

  say ""
  if [[ $APPLY -eq 1 ]]; then
    say "PyFK is ready. Its Python:  $prefix/bin/python  (a separate worker environment; no Jupyter kernel)."
  else
    say "With --apply, PyFK's Python will be  $prefix/bin/python  (a separate worker environment; no Jupyter kernel)."
  fi
}
