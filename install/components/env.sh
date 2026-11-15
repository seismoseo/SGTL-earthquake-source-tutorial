# shellcheck shell=bash
# install/components/env.sh: the course environment "sgtl" (sourced by bin/sgtl-install).
#
# Steps: find conda or mamba (or install the pinned Miniforge into ~/sgtl/miniforge3), create or update
# the environment ~/sgtl/envs/sgtl from environment.yml, install the tutorial's helper package
# (pip install -e), write the Jupyter kernel "SGTL (Python 3.12)", and check that GMT loads from the
# environment. Uses the helpers of bin/sgtl-install (say, step, warn, die, have, run, action,
# fetch_verified, checksum_names) and its variables (APPLY, REBUILD, OWN_MINIFORGE, REPO, SGTL_HOME).
#
# Copyright (c) 2026 Minseong Seo (SGTL, Seoul National University). MIT License.

ENV_NAME="sgtl"
ENV_KERNEL_NAME="sgtl"
ENV_DISPLAY_NAME="SGTL (Python 3.12)"
ENV_MIN_FREE_GB=10
CONDA=""
CONDA_KIND=""
NICE=(env)

component_env_summary() {
  printf '%s' 'course environment "sgtl" (Python 3.12), helper package, Jupyter kernel "SGTL (Python 3.12)"'
}

# Variables from your shell that make programs load the wrong libraries or packages.
env_clean_shell() {
  local v
  for v in LD_LIBRARY_PATH PYTHONPATH PYTHONHOME PYTHONSTARTUP PIP_USER PIP_REQUIRE_VIRTUALENV; do
    if [[ -n "${!v:-}" ]]; then
      say "Note: $v is set in your shell. It is ignored here, so that the course environment uses its own libraries."
      unset "$v"
    fi
  done
  # Shared-server manners: one thread per library, low priority, packages in ~/.local not used.
  export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_MAX_THREADS=1
  export NUMPY_MADVISE_HUGEPAGE=0 PYTHONNOUSERSITE=1
  if have nice; then NICE=(nice -n 10); else NICE=(env); fi
}

env_check_disk() {
  local dir="$SGTL_HOME" avail_kb
  while [[ ! -d "$dir" ]]; do dir="$(dirname "$dir")"; done
  avail_kb="$(df -Pk "$dir" 2>/dev/null | awk 'NR == 2 { print $4 }')" || return 0
  [[ "$avail_kb" =~ ^[0-9]+$ ]] || return 0
  if ((avail_kb < ENV_MIN_FREE_GB * 1048576)); then
    warn "Only about $((avail_kb / 1048576)) GB is free in $dir; the course environment needs about $ENV_MIN_FREE_GB GB."
  else
    say "Free space in $dir: about $((avail_kb / 1048576)) GB (enough)."
  fi
}

env_conda_kind() {
  case "${1##*/}" in
    micromamba*) printf 'micromamba' ;;
    mamba*) printf 'mamba' ;;
    *) printf 'conda' ;;
  esac
}

# Sets CONDA to a conda, mamba or micromamba program. Returns 1 when none is found.
env_find_conda() {
  local c
  if [[ -n "${SGTL_CONDA:-}" ]]; then
    c="$(type -P -- "$SGTL_CONDA" || true)"
    [[ -n "$c" ]] || die "SGTL_CONDA is set to '$SGTL_CONDA', but no such program was found."
    CONDA="$c"
    return 0
  fi
  if [[ -x "$SGTL_HOME/miniforge3/bin/conda" ]]; then
    CONDA="$SGTL_HOME/miniforge3/bin/conda"
    return 0
  fi
  [[ $OWN_MINIFORGE -eq 0 ]] || return 1
  if [[ -n "${CONDA_EXE:-}" && -x "${CONDA_EXE}" ]]; then
    CONDA="$CONDA_EXE"
    return 0
  fi
  for c in conda mamba micromamba; do
    if c="$(type -P "$c")"; then
      CONDA="$c"
      return 0
    fi
  done
  return 1
}

env_warn_old_conda() {
  local v major minor
  [[ "$CONDA_KIND" == conda ]] || return 0
  v="$("$CONDA" --version 2>/dev/null | awk '{ print $2; exit }')" || return 0
  major="${v%%.*}"
  minor="${v#*.}"
  minor="${minor%%.*}"
  [[ "$major" =~ ^[0-9]+$ && "$minor" =~ ^[0-9]+$ ]] || return 0
  if ((major < 23 || (major == 23 && minor < 10))); then
    warn "This conda ($v) is old and may need an hour or more. For a faster, separate installation run:"
    warn "  bin/sgtl-install env --apply --own-miniforge"
  fi
}

env_install_miniforge() {
  local name dest="$SGTL_HOME/miniforge3"
  say "No conda or mamba was found (or --own-miniforge was given): installing Miniforge into $dest."
  if [[ "$(uname -s)" != Linux || "$(uname -m)" != x86_64 ]]; then
    die "The pinned Miniforge installer is for Linux x86_64 only, and this computer is $(uname -s) $(uname -m). Install Miniforge yourself (https://conda-forge.org/download/) and run this again."
  fi
  if [[ -e "$dest" ]]; then
    die "$dest exists but contains no bin/conda (an interrupted installation?). Delete it (rm -rf $dest) and run this again."
  fi
  name="$(checksum_names | grep -E '^Miniforge3-.*-Linux-x86_64\.sh$' | head -n 1 || true)"
  [[ -n "$name" ]] || die "install/checksums.txt lists no Miniforge3 Linux x86_64 installer."
  fetch_verified "$name" "$SGTL_HOME/downloads"
  # -b: batch mode (no questions, and your shell start-up files are not changed); -p: where to install.
  run "${NICE[@]}" bash "$FETCHED" -b -p "$dest" ||
    die "The Miniforge installer failed (see the messages above). Delete $dest and run this again."
  CONDA="$dest/bin/conda"
}

env_create() {
  local prefix="$1" env_file="$2"
  if [[ "$CONDA_KIND" == micromamba ]]; then
    run "${NICE[@]}" "$CONDA" create -p "$prefix" -f "$env_file"
  else
    run "${NICE[@]}" "$CONDA" env create -p "$prefix" -f "$env_file"
  fi
}

env_update() {
  local prefix="$1" env_file="$2"
  if [[ "$CONDA_KIND" == micromamba ]]; then
    run "${NICE[@]}" "$CONDA" install -p "$prefix" -f "$env_file"
  else
    run "${NICE[@]}" "$CONDA" env update -p "$prefix" -f "$env_file"
  fi
}

# env_write_kernel PREFIX: the Jupyter kernel spec PREFIX/share/jupyter/kernels/sgtl/kernel.json.
# Its "env" caps threads and makes GMT (used by PyGMT) and other programs come from this environment.
env_write_kernel() {
  local prefix="$1" kdir="$1/share/jupyter/kernels/$ENV_KERNEL_NAME" user_k vars
  vars=(OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_MAX_THREADS=1
    NUMPY_MADVISE_HUGEPAGE=0 PYTHONNOUSERSITE=1 LD_LIBRARY_PATH=
    "SGTL_REPO=$REPO" "SGTL_HOME=$SGTL_HOME" "GMT_LIBRARY_PATH=$prefix/lib"
    "PATH=$prefix/bin:/usr/local/bin:/usr/bin:/bin")
  if [[ "$SGTL_HOME" != "${HOME%/}/sgtl" ]]; then vars+=("SGTL_DATA=$SGTL_HOME/data"); fi
  action "write the Jupyter kernel \"$ENV_DISPLAY_NAME\" (name: $ENV_KERNEL_NAME) to $kdir/kernel.json"
  if [[ $APPLY -eq 1 ]]; then
    mkdir -p "$kdir"
    "$prefix/bin/python" - "$kdir/kernel.json" "$prefix/bin/python" "$ENV_DISPLAY_NAME" "${vars[@]}" <<'PY'
import json
import sys

out, python, display = sys.argv[1:4]
env = dict(item.split("=", 1) for item in sys.argv[4:])
spec = {
    "argv": [python, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
    "display_name": display,
    "language": "python",
    "interrupt_mode": "signal",
    "env": env,
    "metadata": {"debugger": True, "sgtl": {"written_by": "bin/sgtl-install"}},
}
with open(out, "w", encoding="utf-8") as fh:
    json.dump(spec, fh, indent=1, sort_keys=True)
    fh.write("\n")
PY
  fi
  say "  kernel settings: ${vars[*]%%=*}"
  user_k="${JUPYTER_DATA_DIR:-${HOME%/}/.local/share/jupyter}/kernels/$ENV_KERNEL_NAME/kernel.json"
  if [[ -f "$user_k" ]] && ! grep -qF "\"$prefix/bin/python\"" "$user_k"; then
    warn "Another kernel named '$ENV_KERNEL_NAME' ($user_k) hides this one in Jupyter."
    warn "Delete its folder if you do not need it:  rm -r \"$(dirname "$user_k")\""
  fi
}

# One line of Python: which GMT library PyGMT loads (it must be the one inside the environment).
ENV_GMT_CHECK="import os, sys; from pygmt.clib import Session; s = Session(); s.__enter__(); i = s.info; s.__exit__(None, None, None); p = i.get('library path', ''); print('GMT', i.get('version'), 'from', p or '(unknown)'); sys.exit(1 if p and not os.path.realpath(p).startswith(os.path.realpath(sys.prefix)) else 0)"

component_env_run() {
  step "Course environment \"$ENV_NAME\""
  local prefix="$SGTL_HOME/envs/$ENV_NAME" env_file="${SGTL_ENV_FILE:-$REPO/environment.yml}" py build=()
  py="$prefix/bin/python"
  [[ -f "$env_file" ]] || die "The environment file $env_file is missing; is this a complete copy of the tutorial?"
  env_clean_shell
  env_check_disk

  # 1. conda or mamba
  if env_find_conda; then
    CONDA_KIND="$(env_conda_kind "$CONDA")"
    say "Using $CONDA_KIND: $CONDA ($("$CONDA" --version 2>/dev/null | head -n 1 || true))"
    env_warn_old_conda
  else
    env_install_miniforge
    CONDA_KIND=conda
  fi
  if [[ "$CONDA" != "$SGTL_HOME/miniforge3/"* ]]; then
    export CONDA_PKGS_DIRS="$SGTL_HOME/conda-pkgs"
    say "Downloaded packages are kept in $CONDA_PKGS_DIRS (you may delete that folder after installing)."
  fi
  export CONDA_ALWAYS_YES=true MAMBA_ALWAYS_YES=true

  # 2. the environment
  say "Environment: $prefix  (from ${env_file})"
  if [[ -d "$prefix" && $REBUILD -eq 1 ]]; then
    run rm -rf -- "$prefix"
  fi
  if [[ -d "$prefix" && $REBUILD -eq 0 ]]; then
    [[ -d "$prefix/conda-meta" ]] ||
      die "$prefix exists but is not a conda environment. Move it away, or add --rebuild to delete it."
    say "The environment exists: updating it (add --rebuild to start from scratch)."
    env_update "$prefix" "$env_file" ||
      die "Updating the environment failed (see the messages above). Try: bin/sgtl-install env --apply --rebuild"
  else
    run mkdir -p "$SGTL_HOME/envs"
    env_create "$prefix" "$env_file" ||
      die "Creating the environment failed (see the messages above). Run the same command again; if it fails again, send the last 30 lines to the mentor (friction issue)."
  fi

  # 3. the tutorial's helper package, linked to this folder ("editable": edits to src/ apply at once)
  build=(--no-build-isolation)
  if [[ $APPLY -eq 1 ]] && ! "$py" -c 'import setuptools' >/dev/null 2>&1; then build=(); fi
  run "${NICE[@]}" "$py" -m pip install --no-deps ${build[@]+"${build[@]}"} -e "$REPO" ||
    die "Installing the helper package failed (see the messages above)."
  run "$py" -c 'import sgtl_tutorial' ||
    die "The helper package does not import (see the messages above)."

  # 4. the Jupyter kernel
  env_write_kernel "$prefix"

  # 5. checks: GMT from the environment, then the tutorial's own check-up
  run env -u LD_LIBRARY_PATH "PATH=$prefix/bin:/usr/local/bin:/usr/bin:/bin" "GMT_LIBRARY_PATH=$prefix/lib" \
    "$py" -c "$ENV_GMT_CHECK" ||
    warn "PyGMT did not load GMT from the course environment. Run bin/sgtl doctor and tell the mentor."
  run "$py" -m sgtl_tutorial.cli doctor || warn "bin/sgtl doctor reported problems (see above)."

  say ""
  say "Next:  bin/sgtl doctor          (check the installation)"
  say "       bin/sgtl-lab start --apply   (start JupyterLab; choose the kernel \"$ENV_DISPLAY_NAME\")"
}
