# shellcheck shell=bash
# install/components/coulomb.sh: Elastic_stresses_py (Coulomb stress changes), in the course environment
# (sourced by bin/sgtl-install).
#
# Elastic_stresses_py (https://github.com/kmaterna/Elastic_stresses_py, by Kathryn Materna) computes the elastic
# displacement, strain and stress caused by slip on faults in a uniform half-space (Okada's equations, through
# the cutde library), and the Coulomb stress change on receiver faults. pip installs it from GitHub at a pinned
# commit into the course environment "sgtl" (or the one that SGTL_ENV names, an absolute path), with --no-deps:
# everything it needs (NumPy 1.26.4, SciPy, pandas, matplotlib, PyGMT, tectonic-utils 0.2.1, cutde) is already in
# the course environment, and nothing is upgraded.
# Its build tool poetry-core is installed first from a checksum-verified wheel (install/checksums.txt) when missing.
# Steps: check the course environment, poetry-core, Elastic_stresses_py, check-up (strain against pyrocko's Okada).
# Uses the helpers of bin/sgtl-install and of install/components/env.sh.
#
# Copyright (c) 2026 Minseong Seo (SGTL, Seoul National University). MIT License.

COULOMB_GIT_URL="https://github.com/kmaterna/Elastic_stresses_py"
COULOMB_COMMIT="5dfc485f920a23956538dc55c67feedbd36cb091" # 2026-11-03, "fixing units on potency calculation" (2.0.0)
COULOMB_PYTHON="3.12"
COULOMB_NUMPY="1.26.4"
COULOMB_BUILD_WHEEL="poetry_core-2.5.0-py3-none-any.whl"
# Python modules it needs from the course environment (environment.yml), and pyrocko for the check-up.
COULOMB_NEEDS=(numpy scipy pandas matplotlib pygmt tectonic_utils cutde pyrocko)
COULOMB_PY=""

if ! declare -F env_clean_shell >/dev/null; then
  # shellcheck source=/dev/null
  source "$COMPONENT_DIR/env.sh"
fi

component_coulomb_summary() {
  printf '%s' 'Elastic_stresses_py Coulomb stress (pinned GitHub commit) in the course environment'
}

# coulomb_version NAME: the installed version of the Python distribution NAME, or nothing.
coulomb_version() {
  [[ -x "$COULOMB_PY" ]] || return 0
  "$COULOMB_PY" -c 'import importlib.metadata as m, sys
try:
    print(m.version(sys.argv[1]))
except m.PackageNotFoundError:
    pass' "$1" 2>/dev/null || true
}

# coulomb_installed_commit: the git commit Elastic_stresses_py was installed from, or nothing.
coulomb_installed_commit() {
  [[ -x "$COULOMB_PY" ]] || return 0
  "$COULOMB_PY" -c 'import importlib.metadata as m, json
try:
    d = json.loads(m.distribution("elastic_stresses_py").read_text("direct_url.json") or "{}")
except m.PackageNotFoundError:
    d = {}
print(d.get("vcs_info", {}).get("commit_id", ""))' 2>/dev/null || true
}

# coulomb_check_course_env PREFIX: the course environment with Python 3.12, NumPy 1.26.4 and the modules it needs.
coulomb_check_course_env() {
  local prefix="$1" pyver npver missing
  if [[ ! -x "$COULOMB_PY" ]]; then
    if [[ $APPLY -eq 1 ]]; then
      die "The course environment $prefix is missing. Install it first:  bin/sgtl-install env --apply"
    fi
    warn "The course environment $prefix is missing; install it first (bin/sgtl-install env --apply). The steps below assume it exists."
    return 0
  fi
  pyver="$("$COULOMB_PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"
  [[ "$pyver" == "$COULOMB_PYTHON" ]] ||
    die "The course environment has Python '${pyver:-?}', not $COULOMB_PYTHON. Rebuild it:  bin/sgtl-install env --apply --rebuild"
  npver="$(coulomb_version numpy)"
  [[ "$npver" == "$COULOMB_NUMPY" ]] ||
    die "The course environment has NumPy '${npver:-none}', but the course needs NumPy $COULOMB_NUMPY. Repair it:  bin/sgtl-install env --apply"
  missing="$("$COULOMB_PY" -c 'import importlib.util, sys
print(" ".join(n for n in sys.argv[1:] if importlib.util.find_spec(n) is None))' "${COULOMB_NEEDS[@]}" 2>/dev/null)" ||
    die "Could not check the modules of the course environment with $COULOMB_PY."
  [[ -z "$missing" ]] ||
    die "The course environment lacks: $missing. Update it first:  bin/sgtl-install env --apply"
  say "Course environment: $prefix (Python $pyver, NumPy $npver)"
}

# The check-up: a small right-lateral strike-slip patch (a Source_Patch line) and one receiver; Elastic_stresses_py
# computes the strain at the receiver and the Coulomb stress change on it, and pyrocko's independent Okada code
# (one thread) computes the strain again. The strain tensors must agree to 1e-3 (relative), and the Coulomb stress
# change must be finite and not zero. Prints versions, one strain component, the Coulomb stress change, time, memory.
COULOMB_CHECKUP=$(
  cat <<'PY'
import contextlib, importlib.metadata as md, io, resource, sys, time
t_start = time.time()
import numpy as np
from elastic_stresses_py.PyCoulomb import configure_calc, run_dc3d
from elastic_stresses_py.PyCoulomb.inputs_object import io_intxt
from elastic_stresses_py.PyCoulomb.inputs_object.input_obj import Input_object
from pyrocko.modelling import okada_ext

names = ("elastic_stresses_py", "numpy", "cutde", "tectonic-utils", "pyrocko")
print("versions: python %s, " % sys.version.split()[0] + ", ".join("%s %s" % (n, md.version(n)) for n in names))
problems = []
if np.__version__ != sys.argv[1]:
    problems.append("NumPy is %s, not %s" % (np.__version__, sys.argv[1]))

# Elastic_stresses_py, with lines in its input-file format. Source_Patch: strike rake dip length_km width_km lon lat
# depth_km slip_m (the point is the top corner where the patch starts). Receiver: the same without slip.
lon0, lat0, shear_mod, lame1 = 127.5, 36.0, 30e9, 30e9
patch = io_intxt.get_source_patch("Source_Patch: 30 180 80 2.0 2.0 127.5 36.0 1.0 0.1", lon0, lat0)
target = io_intxt.get_receiver_fault("Receiver: 30 180 80 0.2 0.2 127.53 36.01 2.0", lon0, lat0)
inputs = Input_object(PR1=0.25, FRIC=0.4, depth=0, start_gridx=-5, finish_gridx=5, start_gridy=-5, finish_gridy=5,
                      xinc=1, yinc=1, minlon=127.4, maxlon=127.6, zerolon=lon0, minlat=35.9, maxlat=36.1,
                      zerolat=lat0, source_object=[patch], receiver_object=[target])
params = configure_calc.Params(mu=shear_mod, lame1=lame1, plot_grd_disp=False)
with contextlib.redirect_stdout(io.StringIO()):
    out = run_dc3d.compute_strains_stresses(params, inputs)
esp_strain = np.asarray(out.eij[0])  # axes east, north, up
esp_coulomb = float(out.coulomb[0])  # kPa

# pyrocko: Okada (1992) for the same rectangle, at the receiver's centre (axes north, east, down; metres).
east_km, north_km, depth_km = target.get_fault_center()
rect = np.array([[patch.ystart * 1e3, patch.xstart * 1e3, patch.top * 1e3, patch.strike, patch.dipangle,
                  0.0, patch.L * 1e3, -patch.W * 1e3, 0.0]])
disl = np.array([[-patch.rtlat, patch.reverse, patch.tensile]])  # left-lateral, up-dip, opening (m)
where = np.array([[north_km * 1e3, east_km * 1e3, depth_km * 1e3]])
grad = okada_ext.okada(rect, disl, where, lame1, shear_mod, nthreads=1, rotate_sdn=0)[0, 3:].reshape(3, 3)
swap = np.array([[0.0, 1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, -1.0]])  # north-east-down -> east-north-up
pyr_strain = swap @ (0.5 * (grad + grad.T)) @ swap.T
diff = np.abs(esp_strain - pyr_strain).max() / np.abs(pyr_strain).max()

seconds = time.time() - t_start
peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
print("receiver point: %.3f km east, %.3f km north, %.3f km deep" % (east_km, north_km, depth_km))
print("east-north strain: Elastic_stresses_py %.6e, pyrocko %.6e" % (esp_strain[0, 1], pyr_strain[0, 1]))
print("largest strain difference / largest strain: %.1e" % diff)
print("Coulomb stress change on the receiver (Elastic_stresses_py): %.3f kPa" % esp_coulomb)
print("run time %.1f s, peak memory %.0f MB" % (seconds, peak_mb))
if not (np.isfinite(diff) and diff < 1e-3):
    problems.append("the strain tensors differ by %.1e (relative)" % diff)
if not (np.isfinite(esp_coulomb) and esp_coulomb != 0.0):
    problems.append("the Coulomb stress change is %r" % esp_coulomb)
if problems:
    sys.exit("Elastic_stresses_py check-up FAILED: " + "; ".join(problems))
print("Elastic_stresses_py check-up OK: its strain agrees with pyrocko's Okada; Coulomb stress change computed.")
PY
)

component_coulomb_run() {
  step "Elastic_stresses_py Coulomb stress (coulomb)"
  local prefix="${SGTL_ENV:-$SGTL_HOME/envs/sgtl}" paths have_v commit reinstall=()
  prefix="${prefix%/}"
  [[ "$prefix" == /* ]] || die "SGTL_ENV must be an absolute path (it is '$prefix')."
  COULOMB_PY="$prefix/bin/python"
  paths="$prefix/bin:/usr/local/bin:/usr/bin:/bin"
  env_clean_shell

  # 1. the course environment (Elastic_stresses_py goes into it; nothing else changes)
  coulomb_check_course_env "$prefix"
  if [[ ! -x "$prefix/bin/git" ]]; then # pip needs git on its PATH to download Elastic_stresses_py
    have git ||
      die "git was not found (it comes with the course environment). Install the course environment first:  bin/sgtl-install env --apply"
    paths="$paths:$(dirname "$(type -P git)")"
  fi

  # 2. poetry-core, the tool that builds Elastic_stresses_py (pinned wheel, only when missing)
  have_v="$(coulomb_version poetry-core)"
  if [[ -n "$have_v" ]]; then
    say "poetry-core $have_v is already in the course environment (kept)."
  else
    fetch_verified "$COULOMB_BUILD_WHEEL" "$SGTL_HOME/downloads"
    run "${NICE[@]}" "$COULOMB_PY" -m pip install --no-deps --no-index "$FETCHED" ||
      die "Installing poetry-core failed (see the messages above)."
  fi

  # 3. Elastic_stresses_py at the pinned commit (pip downloads it with git over https)
  commit="$(coulomb_installed_commit)"
  if [[ $REBUILD -eq 1 ]]; then reinstall=(--force-reinstall); fi
  if [[ $REBUILD -eq 0 && "$commit" == "$COULOMB_COMMIT" ]]; then
    say "Elastic_stresses_py $(coulomb_version elastic_stresses_py) is already installed from commit ${COULOMB_COMMIT:0:7} (add --rebuild to install it again)."
  else
    run "${NICE[@]}" env "PATH=$paths" "$COULOMB_PY" -m pip install --no-deps --no-build-isolation --no-index \
      ${reinstall[@]+"${reinstall[@]}"} "elastic_stresses_py @ git+$COULOMB_GIT_URL@$COULOMB_COMMIT" ||
      die "Installing Elastic_stresses_py failed (see the messages above). Check that https://github.com can be reached, then run this again."
  fi

  # 4. check-up against pyrocko's Okada code (NumPy unchanged)
  action "check-up: Coulomb stress change of a small strike-slip patch at one receiver; strain compared with pyrocko's Okada"
  if [[ $APPLY -eq 1 ]]; then
    "${NICE[@]}" env -u LD_LIBRARY_PATH "PATH=$paths" MPLBACKEND=Agg "$COULOMB_PY" -c "$COULOMB_CHECKUP" "$COULOMB_NUMPY" ||
      die "The Elastic_stresses_py check-up failed (see the messages above). Try: bin/sgtl-install coulomb --apply --rebuild"
  fi
}
