# shellcheck shell=bash
# install/components/seisbench.sh: pretrained PhaseNet weights for SeisBench, used in module M21
# (sourced by bin/sgtl-install).
#
# Installs under ~/sgtl/ (SGTL_HOME):
#   seisbench/models/v3/phasenet/   the PhaseNet weights 'stead' and 'original', version 2, in SeisBench's own cache
#                                   layout: for each a .json (description) and a .pt (the numbers) file, every file
#                                   pinned by its SHA-256 in install/checksums.txt
#   seisbench/config.json           SeisBench's settings file (kept as it is when it exists)
# and sets SEISBENCH_CACHE_ROOT=~/sgtl/seisbench, so SeisBench reads these files instead of downloading:
#   - in tools/env.sh (when the tools component has written it; a later tools run writes the line itself),
#   - in the Jupyter kernel "SGTL (Python 3.12)" (when the env component has written it; it writes the line itself
#     from this release on).
# At the end the course environment loads both weights from this folder with every download switched off, and runs
# them on a made-up record. Uses the helpers of bin/sgtl-install (say, step, warn, die, have, run, action,
# fetch_verified, sha256_of) and its variables (APPLY, REPO, SGTL_HOME).
#
# Copyright (c) 2026 Minseong Seo (SGTL, Seoul National University). MIT License.

SB_FILES=(phasenet/stead.json.v2 phasenet/stead.pt.v2 phasenet/original.json.v2 phasenet/original.pt.v2)
SB_WEIGHTS=("stead:2" "original:2")   # name:version, as SeisBench's PhaseNet.from_pretrained takes them
SB_KERNEL_NAME="sgtl"
SB_NICE=(env)

component_seisbench_summary() {
  printf '%s' 'SeisBench PhaseNet weights (stead and original, version 2) for module M21'
}

seisbench_clean_shell() {
  local v
  for v in PYTHONPATH PYTHONHOME PYTHONSTARTUP LD_LIBRARY_PATH; do
    if [[ -n "${!v:-}" ]]; then
      say "Note: $v is set in your shell. It is ignored here."
      unset "$v"
    fi
  done
  export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_MAX_THREADS=1
  export NUMPY_MADVISE_HUGEPAGE=0 PYTHONNOUSERSITE=1
  if have nice; then SB_NICE=(nice -n 10); else SB_NICE=(env); fi
}

seisbench_check_env() {
  [[ -x "$SB_PREFIX/bin/python" ]] && return 0
  if [[ $APPLY -eq 1 ]]; then
    die "The course environment $SB_PREFIX is missing (no python). Install it first: bin/sgtl-install env --apply"
  fi
  warn "The course environment $SB_PREFIX is missing (no python). Install it first (bin/sgtl-install env --apply), or both at once: bin/sgtl-install env seisbench --apply"
}

seisbench_fetch() {
  local models="$SB_CACHE/models/v3" name
  step "PhaseNet weights for SeisBench: $models/phasenet"
  run mkdir -p "$models/phasenet"
  for name in "${SB_FILES[@]}"; do
    fetch_verified "$name" "$models"
  done
  if [[ -f "$SB_CACHE/config.json" ]]; then
    say "Kept: $SB_CACHE/config.json"
  else
    action "write $SB_CACHE/config.json (SeisBench's settings file, empty: its defaults)"
    if [[ $APPLY -eq 1 ]]; then printf '{}\n' >"$SB_CACHE/config.json"; fi
  fi
}

seisbench_envsh() {
  local f="$SGTL_HOME/tools/env.sh" line
  step "SEISBENCH_CACHE_ROOT for your shell and for Jupyter"
  line="export SEISBENCH_CACHE_ROOT=$(printf '%q' "$SB_CACHE")"
  if [[ ! -f "$f" ]]; then
    say "No $f yet: bin/sgtl-install tools writes it, with this setting."
  elif grep -qxF "$line" "$f"; then
    say "Already set in $f"
  else
    action "add the line '$line' to $f"
    if [[ $APPLY -eq 1 ]]; then printf '%s\n' "$line" >>"$f"; fi
  fi
}

seisbench_kernel() {
  local kjson="$SB_PREFIX/share/jupyter/kernels/$SB_KERNEL_NAME/kernel.json"
  if [[ ! -f "$kjson" ]]; then
    say "No Jupyter kernel '$SB_KERNEL_NAME' in $SB_PREFIX yet: bin/sgtl-install env writes it, with this setting."
    return 0
  fi
  if grep -qF "\"SEISBENCH_CACHE_ROOT\": \"$SB_CACHE\"" "$kjson"; then
    say "Already set in the Jupyter kernel ($kjson)"
    return 0
  fi
  action "set SEISBENCH_CACHE_ROOT=$SB_CACHE in the settings (\"env\") of the Jupyter kernel $kjson"
  [[ $APPLY -eq 1 ]] || return 0
  "$SB_PREFIX/bin/python" -I - "$kjson" "$SB_CACHE" <<'PY' || die "Could not update $kjson."
import json
import sys

path, root = sys.argv[1:3]
with open(path, encoding="utf-8") as fh:
    spec = json.load(fh)
spec.setdefault("env", {})["SEISBENCH_CACHE_ROOT"] = root
with open(path + ".part", "w", encoding="utf-8") as fh:
    json.dump(spec, fh, indent=1, sort_keys=True)
    fh.write("\n")
PY
  mv -f -- "$kjson.part" "$kjson"
}

seisbench_test() {
  step "Test: the course environment loads both weights from $SB_CACHE with downloads switched off"
  if [[ $APPLY -eq 0 ]]; then
    action "import seisbench.models; PhaseNet.from_pretrained for ${SB_WEIGHTS[*]} (any download attempt is a failure); run each on a made-up 60-s record on one thread"
    return 0
  fi
  printf '+ %s\n' "SEISBENCH_CACHE_ROOT=$SB_CACHE $(quote_cmd "${SB_NICE[@]}" "$SB_PREFIX/bin/python" -I - "${SB_WEIGHTS[@]}") <<(test)"
  SEISBENCH_CACHE_ROOT="$SB_CACHE" "${SB_NICE[@]}" "$SB_PREFIX/bin/python" -I - "${SB_WEIGHTS[@]}" <<'PY' || die "The test failed (lines with FAIL above). Send this output to the mentor (friction issue)."
import sys

try:
    import numpy as np
    import torch
    import seisbench
    import seisbench.models as sbm
    import seisbench.util as sbu
    from obspy import Stream, Trace, UTCDateTime
except Exception as exc:  # noqa: BLE001
    print("FAIL  SeisBench {}: cannot load its models ({}: {}). The course environment needs a SeisBench release "
          "that imports without optional packages; update it with bin/sgtl-install env --apply and tell the mentor "
          "(friction issue).".format(getattr(sys.modules.get("seisbench"), "__version__", "?"),
                                     type(exc).__name__, exc))
    sys.exit(1)


def no_download(*args, **kwargs):
    raise RuntimeError("SeisBench tried to download a file")


for name in ("download_http", "download_ftp"):
    if hasattr(sbu, name):
        setattr(sbu, name, no_download)
torch.set_num_threads(1)
rng = np.random.default_rng(0)
start = UTCDateTime(2020, 1, 1)
record = Stream([Trace(rng.standard_normal(6000), header={"network": "XX", "station": "TEST", "channel": "HH" + c,
                                                          "sampling_rate": 100.0, "starttime": start})
                 for c in "ZNE"])
failed = 0
for item in sys.argv[1:]:
    name, version = item.split(":")
    try:
        model = sbm.PhaseNet.from_pretrained(name, version_str=version)
        model.eval()
        curves = model.annotate(record)
        total = np.sum([tr.data for tr in curves], axis=0)
        ok = len(curves) == 3 and np.allclose(total, 1.0, atol=1e-3)
        print("{}  PhaseNet {} v{}: loaded from {} and ran ({} curves, P + S + noise = 1: {})".format(
            "OK  " if ok else "FAIL", name, version, seisbench.cache_model_root, len(curves), ok))
        failed += 0 if ok else 1
    except Exception as exc:  # noqa: BLE001
        print("FAIL  PhaseNet {} v{}: {}: {}".format(name, version, type(exc).__name__, exc))
        failed += 1
print("Test: {}.".format("all passed" if not failed else "{} failed".format(failed)))
sys.exit(1 if failed else 0)
PY
}

component_seisbench_run() {
  step "SeisBench PhaseNet weights (seisbench)"
  SB_PREFIX="${SGTL_ENV:-$SGTL_HOME/envs/sgtl}"
  SB_PREFIX="${SB_PREFIX%/}"
  [[ "$SB_PREFIX" == /* ]] || die "SGTL_ENV must be an absolute path (it is '$SB_PREFIX')."
  SB_CACHE="$SGTL_HOME/seisbench"
  say "Course environment (Python, SeisBench, PyTorch): $SB_PREFIX"
  say "Weights folder (SEISBENCH_CACHE_ROOT): $SB_CACHE"
  seisbench_clean_shell
  seisbench_check_env
  seisbench_fetch
  seisbench_envsh
  seisbench_kernel
  seisbench_test
  say ""
  say "Next:  source $SGTL_HOME/tools/env.sh   (or open a new terminal) so that SeisBench finds the weights;"
  say "       in Jupyter, restart the kernel \"SGTL (Python 3.12)\"."
}
