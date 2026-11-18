# shellcheck shell=bash
# install/components/tools.sh: location, relocation, picking and mechanism tools (sourced by bin/sgtl-install).
#
# Installs under ~/sgtl/ (SGTL_HOME):
#   tools/bin/      hyp1.40 (HYPOINVERSE-2000 version 1.40, USGS), and hypoDD, ph2dt and ncsn2pha
#                   (HypoDD 2.1b by Felix Waldhauser, with the lab patch), compiled from source with the
#                   compilers of the course environment
#   tools/src/      their source code, manuals and examples
#   PocketQuake/    PocketQuake v1.16.1 with its two submodules
#   tools/EQNet/    EQNet (AI4EPS) at a pinned commit, with the PhaseNet+ weights
#   tools/SKHASH/   SKHASH (USGS) at a pinned commit
#   tools/env.sh    settings for your shell:  source ~/sgtl/tools/env.sh
# Every download is pinned: files by SHA-256 (install/checksums.txt), git repositories by commit.
# At the end a short test runs every tool on its own example and compares with the authors' results.
# Uses the helpers of bin/sgtl-install (say, step, warn, die, have, run, action, fetch_verified,
# checksum_entry, sha256_of) and its variables (APPLY, REPO, SGTL_HOME).
#
# Copyright (c) 2026 Minseong Seo (SGTL, Seoul National University). MIT License.

TOOLS_HYP_TAR="hyp1.40.tar"
TOOLS_HYP_FFLAGS="-O -std=legacy"
TOOLS_HYPODD_COMMIT="fb40407fb768cbdc23a11e27bc841f5d4a98abb7" # tag V2.1b
TOOLS_HYPODD_FFLAGS="-O -I../../include -std=legacy -mcmodel=large -fno-pie"
TOOLS_HYPODD_CFLAGS="-O -I../../include -mcmodel=large -fno-pie"
TOOLS_HYPODD_LDFLAGS="-no-pie -mcmodel=large"
TOOLS_PQ_URL="https://github.com/seismoseo/PocketQuake.git"
TOOLS_PQ_TAG="v1.16.1"
TOOLS_PQ_COMMIT="a97a021ca11699b4ba58349a895c1f2481065211"
TOOLS_PQ_SUB="external/korea-cluster-relocation"
TOOLS_PQ_SUB_COMMIT="d0679858c09ecdd14e7406375a4fc872a545060d"
TOOLS_EQNET_URL="https://github.com/AI4EPS/EQNet.git"
TOOLS_EQNET_COMMIT="ad492ef0fe93493662d324f7747851be2c9fc7b8"
TOOLS_WEIGHTS="model_99.pth" # PhaseNet+ weights, release PhaseNet-Plus-v1 of github.com/AI4EPS/models
TOOLS_SKHASH_URL="https://code.usgs.gov/esc/SKHASH.git"
TOOLS_SKHASH_COMMIT="352816d6308e2a94b10510b28b997d923318b3b3"
TOOLS_MIN_FREE_GB=3
TOOLS_NICE=(env)
TOOLS_ENVCMD=(env)

component_tools_summary() {
  printf '%s' 'HYPOINVERSE, HypoDD (lab patch), PocketQuake v1.16.1, EQNet + PhaseNet+ weights, SKHASH'
}

# Settings from your shell that would change what the builds and tests use.
tools_clean_shell() {
  local v
  for v in LD_LIBRARY_PATH PYTHONPATH PYTHONHOME PYTHONSTARTUP MAKEFLAGS MFLAGS GIT_DIR GIT_WORK_TREE; do
    if [[ -n "${!v:-}" ]]; then
      say "Note: $v is set in your shell. It is ignored here."
      unset "$v"
    fi
  done
  # Shared-server manners: one thread per library, low priority, packages in ~/.local not used.
  export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_MAX_THREADS=1
  export NUMPY_MADVISE_HUGEPAGE=0 PYTHONNOUSERSITE=1 GIT_TERMINAL_PROMPT=0
  if have nice; then TOOLS_NICE=(nice -n 10); else TOOLS_NICE=(env); fi
}

tools_check_disk() {
  local dir="$SGTL_HOME" avail_kb
  while [[ ! -d "$dir" ]]; do dir="$(dirname "$dir")"; done
  avail_kb="$(df -Pk "$dir" 2>/dev/null | awk 'NR == 2 { print $4 }')" || return 0
  [[ "$avail_kb" =~ ^[0-9]+$ ]] || return 0
  if ((avail_kb < TOOLS_MIN_FREE_GB * 1048576)); then
    warn "Only about $((avail_kb / 1048576)) GB is free in $dir; the tools need about $TOOLS_MIN_FREE_GB GB (PocketQuake alone 1.2 GB)."
  else
    say "Free space in $dir: about $((avail_kb / 1048576)) GB (enough)."
  fi
}

# The course environment provides the compilers (gfortran, gcc), make, git and Python.
tools_check_env() {
  local prog missing=()
  for prog in gfortran gcc make git python; do
    [[ -x "$TOOLS_PREFIX/bin/$prog" ]] || missing+=("$prog")
  done
  [[ ${#missing[@]} -eq 0 ]] && return 0
  if [[ $APPLY -eq 1 ]]; then
    die "The course environment $TOOLS_PREFIX is missing or incomplete (no ${missing[*]}). Install it first: bin/sgtl-install env --apply"
  fi
  warn "The course environment $TOOLS_PREFIX is missing or incomplete (no ${missing[*]}). Install it first (bin/sgtl-install env --apply), or both at once: bin/sgtl-install env tools --apply"
}

# A stamp records how a program was built; a later run with the same inputs skips the build.
# tools_stamp_ok NAME KEY PATH...: the stamp of NAME is KEY and every PATH (program or folder) exists.
tools_stamp_ok() {
  local name="$1" key="$2" f
  shift 2
  for f in "$@"; do [[ -x "$f" ]] || return 1; done
  [[ -f "$TOOLS_DIR/.stamps/$name" && "$(cat "$TOOLS_DIR/.stamps/$name")" == "$key" ]]
}

tools_stamp_write() {
  action "record the build of $1 in $TOOLS_DIR/.stamps/$1"
  [[ $APPLY -eq 1 ]] || return 0
  mkdir -p "$TOOLS_DIR/.stamps"
  printf '%s\n' "$2" >"$TOOLS_DIR/.stamps/$1"
}

tools_sha_of_entry() {
  local entry sha
  entry="$(checksum_entry "$1")" || die "install/checksums.txt has no entry for $1."
  read -r sha _ <<<"$entry"
  printf '%s' "$sha"
}

tools_require_file() {
  [[ -f "$1" ]] || die "$1 is missing; is this a complete copy of the tutorial?"
}

# tools_head DIR: the commit checked out in DIR (nothing when DIR is not a git checkout).
tools_head() {
  [[ -e "$1/.git" ]] || return 0
  "${TOOLS_ENVCMD[@]}" git -C "$1" rev-parse -q --verify 'HEAD^{commit}' 2>/dev/null || true
}

tools_verify_commit() {
  local dir="$1" commit="$2" label="$3" head
  if [[ $APPLY -eq 0 ]]; then
    action "check that $dir is at commit $commit"
    return 0
  fi
  head="$(tools_head "$dir")"
  [[ "$head" == "$commit" ]] ||
    die "$label: expected commit $commit, got ${head:-none}. This is not the version the tutorial pins, so it is not used. Tell the mentor (friction issue)."
  say "Commit OK: $label = $commit"
}

tools_existing_checkout() {
  local dir="$1" commit="$2" label="$3" head msg
  head="$(tools_head "$dir")"
  if [[ "$head" == "$commit" ]]; then
    say "Already installed: $dir ($label)"
    return 0
  fi
  msg="$dir exists but is not $label (commit ${head:-none}; expected $commit). Nothing in it was changed. Move it away (mv $dir $dir.old) and run this again."
  [[ $APPLY -eq 1 ]] && die "$msg"
  warn "$msg (--apply will stop here)"
}

# tools_git_pinned URL COMMIT DEST LABEL: fetch exactly one commit of a git repository into DEST.
tools_git_pinned() {
  local url="$1" commit="$2" dest="$3" label="$4" part="$3.part"
  if [[ -e "$dest" ]]; then
    tools_existing_checkout "$dest" "$commit" "$label"
    return 0
  fi
  run rm -rf -- "$part"
  run "${TOOLS_ENVCMD[@]}" git init -q "$part"
  run "${TOOLS_ENVCMD[@]}" git -C "$part" remote add origin "$url"
  run "${TOOLS_ENVCMD[@]}" "${TOOLS_NICE[@]}" git -C "$part" fetch -q --depth 1 origin "$commit" ||
    die "Downloading $label from $url failed (see the messages above). Try again later; if it fails again, tell the mentor."
  run "${TOOLS_ENVCMD[@]}" git -C "$part" -c advice.detachedHead=false checkout -q --detach FETCH_HEAD ||
    die "Checking out $label failed (see the messages above)."
  tools_verify_commit "$part" "$commit" "$label"
  run mv -- "$part" "$dest"
}

# tools_apply_patch DIR PATCHFILE: GNU patch if present, otherwise git apply (from the course environment).
tools_apply_patch() {
  local dir="$1" patchf="$2"
  if have patch; then
    run patch -d "$dir" -p1 --forward --batch -i "$patchf" || die "The patch $patchf does not apply to $dir."
  else
    # GIT_CEILING_DIRECTORIES: never treat a folder above DIR as a git repository.
    run "${TOOLS_ENVCMD[@]}" "GIT_CEILING_DIRECTORIES=$(dirname "$dir")" git -C "$dir" apply -v "$patchf" ||
      die "The patch $patchf does not apply to $dir."
  fi
}

tools_build_hypoinverse() {
  step "HYPOINVERSE-2000 version 1.40 (Fred Klein, USGS): earthquake location"
  local src="$TOOLS_DIR/src/hyp1.40" mk="$REPO/install/patches/hyp1.40-gfortran.mk" key
  tools_require_file "$mk"
  key="$TOOLS_HYP_TAR=$(tools_sha_of_entry "$TOOLS_HYP_TAR") makefile=$(sha256_of "$mk") FFLAGS=$TOOLS_HYP_FFLAGS compiler=$TOOLS_PREFIX/bin/gfortran"
  if tools_stamp_ok hyp1.40 "$key" "$TOOLS_BIN/hyp1.40" "$src/testone"; then
    say "Already built: $TOOLS_BIN/hyp1.40"
    return 0
  fi
  fetch_verified "$TOOLS_HYP_TAR" "$SGTL_HOME/downloads"
  run rm -rf -- "$src"
  run mkdir -p "$src" "$TOOLS_BIN"
  run tar --no-same-owner -xf "$FETCHED" -C "$src"
  say "The USGS makefile calls g77, an old compiler; install/patches/hyp1.40-gfortran.mk replaces it."
  run cp -- "$mk" "$src/source/makefile"
  run "${TOOLS_ENVCMD[@]}" "${TOOLS_NICE[@]}" make -C "$src/source" FC=gfortran "FFLAGS=$TOOLS_HYP_FFLAGS" hyp1.40 ||
    die "Building hyp1.40 failed (see the messages above). Send the last 30 lines to the mentor (friction issue)."
  run install -m 0755 "$src/source/hyp1.40" "$TOOLS_BIN/hyp1.40"
  tools_stamp_write hyp1.40 "$key"
}

tools_build_hypodd() {
  step "HypoDD 2.1b (Felix Waldhauser): double-difference relocation, with the lab patch"
  local name="$TOOLS_HYPODD_COMMIT.tar.gz" src="$TOOLS_DIR/src/HypoDD-2.1b" prog key
  local patchf="$REPO/install/patches/hypodd-2.1b-sgtl.patch"
  tools_require_file "$patchf"
  key="$name=$(tools_sha_of_entry "$name") patch=$(sha256_of "$patchf") FFLAGS=$TOOLS_HYPODD_FFLAGS CFLAGS=$TOOLS_HYPODD_CFLAGS LDFLAGS=$TOOLS_HYPODD_LDFLAGS compiler=$TOOLS_PREFIX/bin/gfortran"
  if tools_stamp_ok hypodd "$key" "$TOOLS_BIN/hypoDD" "$TOOLS_BIN/ph2dt" "$TOOLS_BIN/ncsn2pha" "$src/examples/example1"; then
    say "Already built: $TOOLS_BIN/hypoDD, ph2dt, ncsn2pha"
    return 0
  fi
  fetch_verified "$name" "$SGTL_HOME/downloads"
  run rm -rf -- "$src" "$TOOLS_DIR/src/HypoDD-$TOOLS_HYPODD_COMMIT"
  run mkdir -p "$TOOLS_DIR/src" "$TOOLS_BIN"
  run tar --no-same-owner -xzf "$FETCHED" -C "$TOOLS_DIR/src"
  run mv -- "$TOOLS_DIR/src/HypoDD-$TOOLS_HYPODD_COMMIT" "$src"
  say "Lab patch: room for 15 million differential times (MAXDATA), and no macOS-only linker setting."
  tools_apply_patch "$src" "$patchf"
  if [[ $APPLY -eq 1 ]]; then
    grep -q 'MAXDATA= 15000000' "$src/include/hypoDD.inc" || die "The lab patch did not change $src/include/hypoDD.inc."
  fi
  # -mcmodel=large: the arrays of hypoDD need about 4 GB of address space (memory is used only as needed).
  run "${TOOLS_ENVCMD[@]}" "${TOOLS_NICE[@]}" make -C "$src/src" FC=gfortran CC=gcc "FFLAGS=$TOOLS_HYPODD_FFLAGS" \
    "CFLAGS=$TOOLS_HYPODD_CFLAGS" "LDFLAGS=$TOOLS_HYPODD_LDFLAGS" ||
    die "Building HypoDD failed (see the messages above). Send the last 30 lines to the mentor (friction issue)."
  for prog in hypoDD ph2dt ncsn2pha; do
    run install -m 0755 "$src/src/$prog/$prog" "$TOOLS_BIN/$prog"
  done
  tools_stamp_write hypodd "$key"
}

tools_install_pocketquake() {
  step "PocketQuake $TOOLS_PQ_TAG (the lab's earthquake catalog pipeline), with its submodules"
  local dest="$SGTL_HOME/PocketQuake" rec got
  if [[ -e "$dest" ]]; then
    tools_existing_checkout "$dest" "$TOOLS_PQ_COMMIT" "PocketQuake $TOOLS_PQ_TAG"
  else
    say "This downloads about 1.2 GB (mostly example clusters) and takes a few minutes."
    run rm -rf -- "$dest.part"
    run "${TOOLS_ENVCMD[@]}" "${TOOLS_NICE[@]}" git -c advice.detachedHead=false clone --depth 1 --branch "$TOOLS_PQ_TAG" \
      --recurse-submodules --shallow-submodules "$TOOLS_PQ_URL" "$dest.part" ||
      die "Downloading PocketQuake failed (see the messages above). Run the same command again; a broken connection is the usual cause."
    tools_verify_commit "$dest.part" "$TOOLS_PQ_COMMIT" "PocketQuake $TOOLS_PQ_TAG"
    run mv -- "$dest.part" "$dest"
  fi
  if [[ $APPLY -eq 0 ]]; then
    action "check that $dest/$TOOLS_PQ_SUB is at commit $TOOLS_PQ_SUB_COMMIT"
    return 0
  fi
  rec="$("${TOOLS_ENVCMD[@]}" git -C "$dest" rev-parse -q --verify "HEAD:$TOOLS_PQ_SUB" 2>/dev/null || true)"
  got="$(tools_head "$dest/$TOOLS_PQ_SUB")"
  [[ "$rec" == "$TOOLS_PQ_SUB_COMMIT" ]] ||
    die "PocketQuake $TOOLS_PQ_TAG records $TOOLS_PQ_SUB at ${rec:-nothing}, not $TOOLS_PQ_SUB_COMMIT. Tell the mentor."
  [[ "$got" == "$TOOLS_PQ_SUB_COMMIT" ]] ||
    die "$dest/$TOOLS_PQ_SUB is at ${got:-nothing}, not $TOOLS_PQ_SUB_COMMIT. Run: git -C $dest submodule update --init"
  say "Commit OK: $TOOLS_PQ_SUB = $TOOLS_PQ_SUB_COMMIT"
}

tools_install_eqnet() {
  step "EQNet (AI4EPS) with the PhaseNet+ weights: phase picking"
  tools_git_pinned "$TOOLS_EQNET_URL" "$TOOLS_EQNET_COMMIT" "$TOOLS_DIR/EQNet" "EQNet ${TOOLS_EQNET_COMMIT:0:7}"
  # PocketQuake looks for the weights at EQNet/docs/model_phasenet_plus/model_99.pth.
  fetch_verified "$TOOLS_WEIGHTS" "$TOOLS_DIR/EQNet/docs/model_phasenet_plus"
}

tools_install_skhash() {
  step "SKHASH (Skoumal, Hardebeck and Shearer; USGS): focal mechanisms"
  tools_git_pinned "$TOOLS_SKHASH_URL" "$TOOLS_SKHASH_COMMIT" "$TOOLS_DIR/SKHASH" "SKHASH ${TOOLS_SKHASH_COMMIT:0:7}"
}

tools_write_envsh() {
  local f="$TOOLS_DIR/env.sh"
  step "Settings for your shell: $f"
  action "write $f (EQNET_DIR, SKHASH_DIR, POCKETQUAKE_DIR, POCKETQUAKE_PYTHON, and $TOOLS_BIN on PATH)"
  [[ $APPLY -eq 1 ]] || return 0
  mkdir -p "$TOOLS_DIR"
  {
    printf '# Settings for the SGTL tutorial tools, written by bin/sgtl-install (component tools).\n'
    printf '# Load them in a shell with:  source %q\n' "$f"
    printf 'export SGTL_TOOLS=%q\n' "$TOOLS_DIR"
    printf 'export EQNET_DIR=%q\n' "$TOOLS_DIR/EQNet"
    printf 'export SKHASH_DIR=%q\n' "$TOOLS_DIR/SKHASH/SKHASH"
    printf 'export POCKETQUAKE_DIR=%q\n' "$SGTL_HOME/PocketQuake"
    printf 'export POCKETQUAKE_PYTHON=%q\n' "$TOOLS_PREFIX/bin/python"
    # shellcheck disable=SC2016  # ${PATH} is for the file, expanded when it is sourced
    printf 'case ":${PATH}:" in *:%q:*) ;; *) export PATH=%q:"${PATH}" ;; esac\n' "$TOOLS_BIN" "$TOOLS_BIN"
  } >"$f.part"
  mv -f -- "$f.part" "$f"
}

tools_checks() {
  step "Checks: every tool runs its own example and is compared with the authors' results"
  local py="$TOOLS_PREFIX/bin/python" wsha
  wsha="$(tools_sha_of_entry "$TOOLS_WEIGHTS")"
  if [[ $APPLY -eq 0 ]]; then
    action "hyp1.40: locate the USGS example earthquake (testone) and compare with the USGS output"
    action "ph2dt and hypoDD: run Waldhauser's example 1 and compare with his output; ncsn2pha starts"
    action "PocketQuake: import pocketquake and (in $TOOLS_PQ_SUB) pipeline with the course environment"
    action "EQNet: the PhaseNet+ weights have SHA-256 $wsha, and eqnet imports"
    action "SKHASH: run its example hash1 (about 15 s and 2 GB of memory) and compare with the USGS output"
    return 0
  fi
  printf '+ %s\n' "$(quote_cmd "${TOOLS_NICE[@]}" "$py" -I - "$TOOLS_BIN" "$TOOLS_DIR/src" "$SGTL_HOME/PocketQuake" "$TOOLS_DIR/EQNet" "$TOOLS_DIR/SKHASH/SKHASH" "$wsha" "$TOOLS_PREFIX" "${TOOLS_PQ_TAG#v}") <<(tool checks)"
  "${TOOLS_NICE[@]}" "$py" -I - "$TOOLS_BIN" "$TOOLS_DIR/src" "$SGTL_HOME/PocketQuake" "$TOOLS_DIR/EQNet" \
    "$TOOLS_DIR/SKHASH/SKHASH" "$wsha" "$TOOLS_PREFIX" "${TOOLS_PQ_TAG#v}" <<'CHECKS_PY' || die "Some checks failed (lines with FAIL above). Send this output to the mentor (friction issue)."
import csv
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time

bin_dir, src_dir, pq_dir, eqnet_dir, skhash_dir, weights_sha, prefix, pq_version = sys.argv[1:9]
ENV = {k: v for k, v in os.environ.items() if k not in ("LD_LIBRARY_PATH", "PYTHONPATH", "PYTHONHOME")}
ENV.update(PATH=prefix + "/bin:/usr/local/bin:/usr/bin:/bin", PYTHONNOUSERSITE="1",
           PYTHONDONTWRITEBYTECODE="1", MPLBACKEND="Agg", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
           MKL_NUM_THREADS="1", NUMEXPR_MAX_THREADS="1", NUMPY_MADVISE_HUGEPAGE="0")
PY = prefix + "/bin/python"
failed = []


def report(status, name, detail):
    print("  {:5} {}: {}".format(status, name, detail), flush=True)
    if status == "FAIL":
        failed.append(name)


def call(args, cwd, stdin=None, timeout=600):
    t = time.time()
    p = subprocess.run(args, cwd=cwd, env=ENV, input=stdin, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, universal_newlines=True, timeout=timeout)
    return p.returncode, p.stdout, time.time() - t


def tail(text, n=5):
    return " | ".join(line.strip() for line in text.strip().splitlines()[-n:])


def example(src, work, refs):
    """Copy an example folder and rename its stored results to ref.<name>."""
    shutil.copytree(src, work)
    for name in refs:
        if os.path.exists(os.path.join(work, name)):
            os.rename(os.path.join(work, name), os.path.join(work, "ref." + name))


def check(name, func):
    try:
        func()
    except Exception as exc:  # report every check, even when one breaks
        report("FAIL", name, "{}: {}".format(type(exc).__name__, exc))


def hypoinverse(tmp):
    work = os.path.join(tmp, "testone")
    example(os.path.join(src_dir, "hyp1.40", "testone"), work, ["testone.sum", "testone.arc", "testone.prt"])
    # The command file asks for four file names; empty lines keep them. Then locate and stop.
    rc, out, dt = call([os.path.join(bin_dir, "hyp1.40")], work, "@testone.hyp\n\n\n\n\nloc\nstop\n", 120)
    with open(os.path.join(work, "ref.testone.sum")) as fh:
        ref = [line[:80] for line in fh]
    with open(os.path.join(work, "testone.sum")) as fh:
        got = [line[:80] for line in fh]
    if rc == 0 and got == ref and len(got) == 1:
        report("OK", "hyp1.40", "located the USGS example earthquake exactly as in the USGS output ({:.1f} s)".format(dt))
    else:
        report("FAIL", "hyp1.40", "exit {}; summary {!r} instead of {!r}; {}".format(rc, got, ref, tail(out)))


def hypodd(tmp):
    work = os.path.join(tmp, "example1")
    example(os.path.join(src_dir, "HypoDD-2.1b", "examples", "example1"), work,
            ["dt.ct", "event.dat", "event.sel", "ph2dt.log", "hypoDD.loc", "hypoDD.reloc", "hypoDD.res",
             "hypoDD.src", "hypoDD.sta", "hypoDD.log"])
    rc, out, dt = call([os.path.join(bin_dir, "ph2dt"), "ph2dt.inp"], work, "", 300)
    with open(os.path.join(work, "dt.ct"), "rb") as a, open(os.path.join(work, "ref.dt.ct"), "rb") as b:
        same = a.read() == b.read()
    if rc == 0 and same:
        report("OK", "ph2dt", "differential times of example 1 identical to Waldhauser's ({:.1f} s)".format(dt))
    else:
        report("FAIL", "ph2dt", "exit {}; dt.ct identical: {}; {}".format(rc, same, tail(out)))
    rc, out, dt = call([os.path.join(bin_dir, "hypoDD"), "hypoDD.inp"], work, "", 300)

    def table(path):
        with open(path) as fh:
            return {int(r[0]): [float(x) for x in r[1:4]] for r in (line.split() for line in fh) if r}

    got, ref = table(os.path.join(work, "hypoDD.reloc")), table(os.path.join(work, "ref.hypoDD.reloc"))
    worst = max((max(abs(a - b) for a, b in zip(got[k][:2], ref[k][:2])) for k in ref if k in got), default=9.0)
    worst_z = max((abs(got[k][2] - ref[k][2]) for k in ref if k in got), default=9.0)
    # Other compilers round differently: allow 0.0001 degrees (about 10 m) and 0.01 km in depth.
    if rc == 0 and sorted(got) == sorted(ref) and worst <= 1e-4 and worst_z <= 0.01:
        report("OK", "hypoDD", "relocated the {} events of example 1 within {:.0f} m of Waldhauser's results "
               "({:.1f} s)".format(len(got), max(worst * 111e3, worst_z * 1e3), dt))
    else:
        report("FAIL", "hypoDD", "exit {}; {} of {} events; largest difference {:.6f} deg, {:.3f} km; {}".format(
            rc, len(got), len(ref), worst, worst_z, tail(out)))
    rc, out, dt = call([os.path.join(bin_dir, "ncsn2pha")], tmp, "", 60)
    if "ncsn2pha" in out:
        report("OK", "ncsn2pha", "starts and prints its usage")
    else:
        report("FAIL", "ncsn2pha", "exit {}; {}".format(rc, tail(out)))


def pocketquake(tmp):
    rc, out, dt = call([PY, "-c", "import pocketquake; print(pocketquake.__version__)"], pq_dir, None, 600)
    if rc == 0 and out.strip().splitlines()[-1:] == [pq_version]:
        report("OK", "PocketQuake", "import pocketquake: version {} ({:.1f} s)".format(pq_version, dt))
    else:
        report("FAIL", "PocketQuake", "exit {}; {}".format(rc, tail(out)))
    sub = os.path.join(pq_dir, "external", "korea-cluster-relocation")
    rc, out, dt = call([PY, "-c", "import pipeline"], sub, None, 600)
    if rc == 0:
        report("OK", "PocketQuake pipeline", "import pipeline works ({:.1f} s)".format(dt))
    else:
        report("FAIL", "PocketQuake pipeline", "exit {}; {}".format(rc, tail(out)))


def eqnet(tmp):
    path = os.path.join(eqnet_dir, "docs", "model_phasenet_plus", "model_99.pth")
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    if h.hexdigest() == weights_sha:
        report("OK", "PhaseNet+ weights", "SHA-256 matches ({:.1f} MB)".format(os.path.getsize(path) / 1e6))
    else:
        report("FAIL", "PhaseNet+ weights", "SHA-256 {} instead of {}".format(h.hexdigest(), weights_sha))
    # The same imports, in the same order, as PocketQuake's PhaseNet+ step.
    code = ("import sys, numpy, pandas; sys.path.insert(0, sys.argv[1]); import torch, eqnet; "
            "print('torch', torch.__version__)")
    rc, out, dt = call([PY, "-c", code, eqnet_dir], tmp, None, 600)
    if rc == 0:
        report("OK", "EQNet", "import eqnet works with {} ({:.1f} s)".format(out.strip().splitlines()[-1], dt))
    else:
        report("FAIL", "EQNet", "exit {}; {}".format(rc, tail(out)))


def skhash(tmp):
    script = os.path.join(skhash_dir, "SKHASH.py")
    rc, out, dt = call([PY, script, "--help"], tmp, None, 600)
    if rc != 0:
        report("FAIL", "SKHASH", "SKHASH.py --help: exit {}; {}".format(rc, tail(out)))
        return
    work = os.path.join(tmp, "skhash")
    os.makedirs(os.path.join(work, "examples"))
    shutil.copytree(os.path.join(skhash_dir, "examples", "hash1"), os.path.join(work, "examples", "hash1"))
    os.rename(os.path.join(work, "examples", "hash1", "OUT"), os.path.join(work, "examples", "hash1", "REF"))
    os.mkdir(os.path.join(work, "examples", "hash1", "OUT"))
    rc, out, dt = call([PY, script, "examples/hash1/control_file.txt"], work, None, 1800)
    keys = ("event_id", "strike", "dip", "rake", "quality")

    def mechanisms(path):
        with open(path, newline="") as fh:
            return [tuple(row[k] for k in keys) for row in csv.DictReader(fh)]

    got_path = os.path.join(work, "examples", "hash1", "OUT", "out.txt")
    got = mechanisms(got_path) if os.path.exists(got_path) else []
    ref = mechanisms(os.path.join(work, "examples", "hash1", "REF", "out.txt"))
    if rc == 0 and got == ref and ref:
        report("OK", "SKHASH", "the {} mechanisms of example hash1 match the USGS output ({:.0f} s)".format(len(got), dt))
    else:
        bad = sum(1 for a, b in zip(got, ref) if a != b) + abs(len(got) - len(ref))
        report("FAIL", "SKHASH", "exit {}; {} of {} mechanisms differ; {}".format(rc, bad, len(ref), tail(out)))


tmp = tempfile.mkdtemp(prefix="sgtl-tools-check-")
try:
    for name, func in [("hyp1.40", hypoinverse), ("HypoDD", hypodd), ("PocketQuake", pocketquake),
                       ("EQNet", eqnet), ("SKHASH", skhash)]:
        check(name, lambda f=func: f(tmp))
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("Checks: {} failed.".format(len(failed)) if failed else "Checks: all passed.", flush=True)
sys.exit(1 if failed else 0)
CHECKS_PY
}

component_tools_run() {
  step "Location, relocation, picking and mechanism tools (tools)"
  TOOLS_PREFIX="${SGTL_ENV:-$SGTL_HOME/envs/sgtl}"
  TOOLS_PREFIX="${TOOLS_PREFIX%/}"
  [[ "$TOOLS_PREFIX" == /* ]] || die "SGTL_ENV must be an absolute path (it is '$TOOLS_PREFIX')."
  TOOLS_DIR="$SGTL_HOME/tools"
  TOOLS_BIN="$TOOLS_DIR/bin"
  TOOLS_ENVCMD=(env "PATH=$TOOLS_PREFIX/bin:/usr/local/bin:/usr/bin:/bin")
  say "Course environment (compilers, git, Python): $TOOLS_PREFIX"
  tools_clean_shell
  tools_check_env
  tools_check_disk
  run mkdir -p "$TOOLS_DIR"

  tools_build_hypoinverse
  tools_build_hypodd
  tools_install_pocketquake
  tools_install_eqnet
  tools_install_skhash
  tools_write_envsh
  tools_checks

  say ""
  say "Next:  source $TOOLS_DIR/env.sh"
  say "       (puts hyp1.40, hypoDD, ph2dt on your PATH and sets EQNET_DIR, SKHASH_DIR, POCKETQUAKE_DIR)"
  say "       Add that line to ~/.bashrc to have it in every new shell."
}
