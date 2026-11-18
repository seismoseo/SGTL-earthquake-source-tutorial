# shellcheck shell=bash
# install/components/mt.sh: MTUQ moment-tensor inversion, in the course environment (sourced by bin/sgtl-install).
#
# MTUQ (moment tensor uncertainty quantification, https://github.com/mtuqorg/mtuq) is fetched from GitHub at a
# pinned commit into ~/sgtl/src/mtuq and installed into the course environment "sgtl" (or the one that SGTL_ENV
# names, an absolute path) in editable mode (the environment uses the files in ~/sgtl/src/mtuq, so you can read
# MTUQ's code and examples there).
# Every pip step uses --no-deps, so NumPy is never changed (MTUQ needs NumPy 1.x; the course pins 1.26.4).
# The dependencies MTUQ needs that the course environment lacks (numba and llvmlite for its fast misfit code,
# retry, and seisgen and seisclient: mtuq.open_db loads every Green's-function client, two of which import them,
# so without them open_db fails for every format, FK included) are installed one by one from wheels whose
# checksums are in install/checksums.txt. MPI (mpi4py) is deliberately not installed: MTUQ then runs serially,
# one core, as a shared server needs. "pip check" still lists what MTUQ declares but never imports in the
# course's use: cython (build only; MTUQ falls back to numba), instaseis (AxiSEM databases only, imported in a
# try block), tables, nose and flake8 (tests and linting), and retry's "py" (retry never imports it).
# Steps: check the course environment, fetch MTUQ, install the missing dependencies, install MTUQ, check-up.
# Uses the helpers of bin/sgtl-install and of install/components/env.sh.
#
# Copyright (c) 2026 Minseong Seo (SGTL, Seoul National University). MIT License.

MT_GIT_URL="https://github.com/mtuqorg/mtuq.git"
MT_COMMIT="2157be553ac24d69bf84b54f56d247a239b2e801" # 2026-04-27, "Merge pull request #346" (MTUQ 0.2.0)
MT_PYTHON="3.12"
MT_NUMPY="1.26.4"
# "<distribution> <wheel> [<wheel> ...]": the wheels (install/checksums.txt) are installed only when the
# distribution is missing from the course environment.
MT_DEPS=(
  "numba llvmlite-0.47.0-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.whl numba-0.65.1-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.whl"
  "retry retry-0.9.2-py2.py3-none-any.whl"
  "seisgen seisgen-0.2.1-py3-none-any.whl"
  "seisclient seisclient-0.0.2-py3-none-any.whl"
)
MT_PY=""
MT_GIT=()

if ! declare -F env_clean_shell >/dev/null; then
  # shellcheck source=/dev/null
  source "$COMPONENT_DIR/env.sh"
fi

component_mt_summary() {
  printf '%s' 'MTUQ moment-tensor inversion (pinned GitHub commit) in the course environment'
}

# mt_version NAME: the installed version of the Python distribution NAME in the course environment, or nothing.
mt_version() {
  [[ -x "$MT_PY" ]] || return 0
  "$MT_PY" -c 'import importlib.metadata as m, sys
try:
    print(m.version(sys.argv[1]))
except m.PackageNotFoundError:
    pass' "$1" 2>/dev/null || true
}

# mt_editable_from: the folder an editable MTUQ installation points to, or nothing.
mt_editable_from() {
  [[ -x "$MT_PY" ]] || return 0
  "$MT_PY" -c 'import importlib.metadata as m, json, os, urllib.parse as u
try:
    d = json.loads(m.distribution("mtuq").read_text("direct_url.json") or "{}")
except m.PackageNotFoundError:
    d = {}
if d.get("dir_info", {}).get("editable"):
    print(os.path.realpath(u.unquote(u.urlparse(d.get("url", "")).path)))' 2>/dev/null || true
}

# mt_check_course_env PREFIX: the course environment must exist, with Python 3.12 and NumPy 1.26.4.
mt_check_course_env() {
  local prefix="$1" pyver npver
  if [[ "$(uname -s)" != Linux || "$(uname -m)" != x86_64 ]]; then
    die "The pinned numba and llvmlite wheels are for Linux x86_64 only, and this computer is $(uname -s) $(uname -m)."
  fi
  if [[ ! -x "$MT_PY" ]]; then
    if [[ $APPLY -eq 1 ]]; then
      die "The course environment $prefix is missing. Install it first:  bin/sgtl-install env --apply"
    fi
    warn "The course environment $prefix is missing; install it first (bin/sgtl-install env --apply). The steps below assume it exists."
    return 0
  fi
  pyver="$("$MT_PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"
  [[ "$pyver" == "$MT_PYTHON" ]] ||
    die "The course environment has Python '${pyver:-?}', but MTUQ's pinned wheels need Python $MT_PYTHON. Rebuild it:  bin/sgtl-install env --apply --rebuild"
  npver="$(mt_version numpy)"
  [[ "$npver" == "$MT_NUMPY" ]] ||
    die "The course environment has NumPy '${npver:-none}', but the course needs NumPy $MT_NUMPY (MTUQ does not work with NumPy 2). Repair it:  bin/sgtl-install env --apply"
  say "Course environment: $prefix (Python $pyver, NumPy $npver)"
}

# mt_fetch SRC: MTUQ's files at the pinned commit in SRC (a git checkout of only that commit).
mt_fetch() {
  local src="$1" head
  if [[ -e "$src" && ! -d "$src/.git" ]]; then
    die "$src exists but is not a git checkout. Move it away and run this again."
  fi
  if [[ -d "$src/.git" ]]; then
    head="$("${MT_GIT[@]}" -C "$src" rev-parse -q --verify 'HEAD^{commit}' 2>/dev/null || true)"
    if [[ "$head" == "$MT_COMMIT" ]]; then
      say "MTUQ source: $src (at the pinned commit ${MT_COMMIT:0:7})"
      return 0
    fi
    if [[ -n "$("${MT_GIT[@]}" -C "$src" status --porcelain --untracked-files=no 2>/dev/null || true)" ]]; then
      die "$src has changes of yours and is not at the pinned commit ${MT_COMMIT:0:7}. Copy your changes elsewhere, move $src away, and run this again."
    fi
    if [[ -n "$head" ]]; then
      say "MTUQ source: $src is at ${head:0:7}; moving it to the pinned commit ${MT_COMMIT:0:7}."
    else
      say "MTUQ source: $src has no files yet (an interrupted download?); downloading again."
    fi
  else
    run mkdir -p "$(dirname "$src")"
    run "${MT_GIT[@]}" init -q "$src"
  fi
  if [[ $APPLY -eq 0 ]] || ! "${MT_GIT[@]}" -C "$src" cat-file -e "$MT_COMMIT^{commit}" 2>/dev/null; then
    run "${NICE[@]}" "${MT_GIT[@]}" -C "$src" fetch -q --depth 1 "$MT_GIT_URL" "$MT_COMMIT" ||
      die "Downloading MTUQ from GitHub failed (see the messages above). Check that https://github.com can be reached, then run this again."
  fi
  run "${MT_GIT[@]}" -C "$src" -c advice.detachedHead=false checkout -q --detach "$MT_COMMIT" ||
    die "Checking out MTUQ commit ${MT_COMMIT:0:7} in $src failed (see the messages above)."
  if [[ $APPLY -eq 1 ]]; then
    head="$("${MT_GIT[@]}" -C "$src" rev-parse HEAD)"
    [[ "$head" == "$MT_COMMIT" ]] || die "$src is at $head, not at the pinned commit $MT_COMMIT."
    say "MTUQ source: $src (commit $MT_COMMIT checked)"
  fi
}

# The check-up: imports MTUQ, checks its moment-tensor functions on known double couples, and runs its compiled
# (numba) misfit code on a tiny problem whose answer is known. One thread, no MPI. Prints versions, time, memory.
MT_CHECKUP=$(
  cat <<'PY'
import importlib.metadata as md, resource, sys, tempfile, time
t_start = time.time()
import numpy as np
import mtuq
import mtuq.util
from mtuq.util import math as mtm
from mtuq.misfit.waveform import ext_numba

names = ("mtuq", "numpy", "numba", "llvmlite", "obspy", "retry", "seisgen", "seisclient")
problems = []
versions = {}
for n in names:
    try:
        versions[n] = md.version(n)
    except md.PackageNotFoundError:
        versions[n] = "MISSING"
        problems.append("%s is not installed" % n)
print("versions: python %s, " % sys.version.split()[0] + ", ".join("%s %s" % (n, versions[n]) for n in names))
if np.__version__ != sys.argv[1]:
    problems.append("NumPy is %s, not %s" % (np.__version__, sys.argv[1]))
if mtuq.util.is_mpi_env():
    problems.append("MTUQ thinks it runs under MPI; run it without mpirun")

# 1. Vertical strike-slip fault striking north (strike 0, dip 90, rake 0) with scalar moment M0. In MTUQ's
#    up-south-east order (Mrr, Mtt, Mpp, Mrt, Mrp, Mtp) its only non-zero element is Mtp = -M0.
M0 = 1.0e15
rho = np.sqrt(2.0) * M0  # MTUQ's size parameter rho is sqrt(2) times the scalar moment
known = mtm.to_mij(rho, 0.0, 0.0, 0.0, 0.0, 0.0)  # rho, v, w, strike, rake, cos(dip)
if not np.allclose(known, [0, 0, 0, 0, 0, -M0], rtol=0, atol=1e-9 * M0):
    problems.append("to_mij of a vertical strike-slip fault gave %s" % np.array2string(known / M0, precision=6))

# 2. Any double couple has eigenvalues (M0, 0, -M0), and its lune coordinates are v = w = 0.
tilted = mtm.to_mij(rho, 0.0, 0.0, 30.0, 60.0, np.cos(np.deg2rad(50.0)))
full = np.array([[tilted[0], tilted[3], tilted[4]], [tilted[3], tilted[1], tilted[5]], [tilted[4], tilted[5], tilted[2]]])
if not np.allclose(np.linalg.eigvalsh(full), [-M0, 0.0, M0], rtol=0, atol=1e-9 * M0):
    problems.append("double-couple eigenvalues are %s x M0" % np.array2string(np.linalg.eigvalsh(full) / M0))
back = mtm.from_mij(tilted)
if abs(back[1]) > 1e-6 or abs(back[2]) > 1e-6 or abs(back[0] / rho - 1) > 1e-9:
    problems.append("from_mij gave rho/rho0 %.9f, v %.2e, w %.2e" % (back[0] / rho, back[1], back[2]))
if abs(mtm.to_Mw(mtm.to_rho(4.3)) - 4.3) > 1e-9:
    problems.append("to_Mw(to_rho(4.3)) is not 4.3")

# 3. MTUQ's compiled misfit (numba): one station, one component, six basis traces, no time shift. Its L2 misfit
#    must equal the sum of squared differences computed directly (zero for the source that made the data).
gen = np.random.default_rng(7)
basis = gen.standard_normal((6, 50))
trial = np.vstack([gen.standard_normal(6), gen.standard_normal(6)])
data = trial[0] @ basis
got = ext_numba.misfit_L2(
    np.array([[data @ data]]), (basis @ data).reshape(1, 1, 6, 1), (basis @ basis.T).reshape(1, 1, 1, 6, 6),
    trial, np.ones((1, 1), dtype=np.int64), np.ones((1, 1)), 0, 1.0, 0, 0, 0, 0, 0, 0)[:, 0]
direct = ((trial @ basis - data) ** 2).sum(axis=1)
if not np.allclose(got, direct, rtol=1e-9, atol=1e-9 * direct.max()):
    problems.append("numba misfit %s differs from the direct sum %s" % (got, direct))

# 4. mtuq.open_db loads every Green's-function client before it picks one (some need seisgen and seisclient).
with tempfile.TemporaryDirectory() as fk_dir:
    try:
        client = mtuq.open_db(fk_dir, format="FK")
        if type(client).__module__ != "mtuq.io.clients.FK_SAC":
            problems.append("open_db(format='FK') gave %s" % type(client).__module__)
    except Exception as exc:
        problems.append("open_db(format='FK') failed: %s: %s" % (type(exc).__name__, exc))

seconds = time.time() - t_start
peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
print("MTUQ from %s" % mtuq.__file__)
print("run time %.1f s (import and numba compilation included), peak memory %.0f MB" % (seconds, peak_mb))
if problems:
    sys.exit("MTUQ check-up FAILED: " + "; ".join(problems))
print("MTUQ check-up OK: double-couple tensors, lune coordinates, magnitudes and the numba misfit agree; "
      "open_db reaches its FK client.")
PY
)

component_mt_run() {
  step "MTUQ moment-tensor inversion (mt)"
  local prefix="${SGTL_ENV:-$SGTL_HOME/envs/sgtl}" src="$SGTL_HOME/src/mtuq" src_real paths entry dist wheels_line have_v wheel
  local wheels=() files=()
  local build=(--no-build-isolation --no-index) reinstall=()
  prefix="${prefix%/}"
  [[ "$prefix" == /* ]] || die "SGTL_ENV must be an absolute path (it is '$prefix')."
  MT_PY="$prefix/bin/python"
  paths="$prefix/bin:/usr/local/bin:/usr/bin:/bin"
  env_clean_shell

  # 1. the course environment (MTUQ goes into it; nothing else changes)
  mt_check_course_env "$prefix"
  if [[ -x "$prefix/bin/git" ]]; then
    MT_GIT=("$prefix/bin/git")
  elif have git; then
    MT_GIT=(git)
  else
    die "git was not found (it comes with the course environment). Install the course environment first:  bin/sgtl-install env --apply"
  fi
  MT_GIT+=(-c protocol.allow=never -c protocol.https.allow=always)

  # 2. MTUQ's files at the pinned commit
  mt_fetch "$src"

  # 3. MTUQ's missing dependencies, from checksum-verified wheels, without their own dependencies
  for entry in "${MT_DEPS[@]}"; do
    read -r dist wheels_line <<<"$entry"
    read -r -a wheels <<<"$wheels_line"
    have_v="$(mt_version "$dist")"
    if [[ -n "$have_v" ]]; then
      say "$dist $have_v is already in the course environment (kept)."
      continue
    fi
    for wheel in "${wheels[@]}"; do
      fetch_verified "$wheel" "$SGTL_HOME/downloads"
      files+=("$FETCHED")
    done
  done
  if [[ ${#files[@]} -gt 0 ]]; then
    run "${NICE[@]}" "$MT_PY" -m pip install --no-deps --no-index "${files[@]}" ||
      die "Installing MTUQ's dependencies failed (see the messages above)."
  fi

  # 4. MTUQ itself (editable: the environment uses the files in $src)
  if [[ -x "$MT_PY" ]] && ! "$MT_PY" -c 'import setuptools' >/dev/null 2>&1; then
    build=() # no setuptools in the environment: let pip build in its own temporary environment
  fi
  if [[ $REBUILD -eq 1 ]]; then reinstall=(--force-reinstall); fi
  src_real="$(cd "$src" 2>/dev/null && pwd -P || printf '%s' "$src")"
  if [[ $REBUILD -eq 0 && -n "$(mt_version mtuq)" && "$(mt_editable_from)" == "$src_real" ]]; then
    say "MTUQ $(mt_version mtuq) is already installed from $src (add --rebuild to install it again)."
  else
    run "${NICE[@]}" env "PATH=$paths" "$MT_PY" -m pip install --no-deps ${build[@]+"${build[@]}"} \
      ${reinstall[@]+"${reinstall[@]}"} -e "$src" ||
      die "Installing MTUQ failed (see the messages above)."
  fi

  # 5. check-up (NumPy unchanged, MTUQ's functions and its numba misfit code)
  action "check-up: import MTUQ, known double couples, and its numba misfit on a tiny problem (one thread, no MPI)"
  if [[ $APPLY -eq 1 ]]; then
    "${NICE[@]}" env -u LD_LIBRARY_PATH "PATH=$paths" NUMBA_NUM_THREADS=1 MPLBACKEND=Agg \
      "$MT_PY" -c "$MT_CHECKUP" "$MT_NUMPY" ||
      die "The MTUQ check-up failed (see the messages above). Try: bin/sgtl-install mt --apply --rebuild"
  fi
}
