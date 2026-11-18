# shellcheck shell=bash
# install/components/data.sh: your STP files and the course's waveform datasets (sourced by bin/sgtl-install).
#
# Waveforms come only from STP, with your personal STP account and the STP program the mentor gives you; neither
# is ever in this repository. This component:
#   1. makes the data folder ~/sgtl/data (or $SGTL_DATA) and the folder ~/.sgtl that only you can open (mode 700);
#   2. writes a template ~/.sgtl/credentials.env (mode 600) when there is none, for you to fill in with your STP
#      id and password, and makes an existing one readable only by you (chmod 600);
#   3. checks ~/.sgtl/stp-client.pl (the STP program) against its SHA-256 fingerprint in install/checksums.txt;
#   4. fetches every dataset of data/manifests/stp_datasets.yaml that is not marked large, with
#      "sgtl data fetch NAME --apply" (through your PocketQuake clone, so install the tools component first), and
#      checks each one with "sgtl data verify NAME". Large (project) datasets are fetched only by hand:
#      bin/sgtl data fetch NAME --apply --large
# Running it again skips the events you already have. Your id and password are never printed.
# Uses the helpers of bin/sgtl-install (say, step, warn, die, have, run, action, sha256_of) and its variables
# (APPLY, REPO, CHECKSUMS, SGTL_HOME).
#
# Copyright (c) 2026 Minseong Seo (SGTL, Seoul National University). MIT License.

DATA_NICE=(env)

component_data_summary() {
  printf '%s' 'your STP files (~/.sgtl) and the course waveform datasets, fetched with your STP account'
}

# data_fingerprint: the SHA-256 that install/checksums.txt gives for stp-client.pl
# (a comment line "#fingerprint stp-client.pl <sha256>": the installer never downloads the STP program).
data_fingerprint() {
  awk '$1 == "#fingerprint" && $2 == "stp-client.pl" { print $3; exit }
       $1 == "#" && $2 == "fingerprint" && $3 == "stp-client.pl" { print $4; exit }' "$CHECKSUMS"
}

# data_has_value KEY FILE: true when FILE sets KEY to something (the value itself is never printed).
data_has_value() {
  [[ -f "$2" ]] && grep -Eq "^[[:space:]]*(export[[:space:]]+)?$1=[[:space:]]*[^[:space:]#]" "$2"
}

data_write_template() {
  local f="$1"
  action "write a template $f (only you can read it: mode 600) for your STP id and password"
  [[ $APPLY -eq 1 ]] || return 0
  (
    umask 077
    cat >"$f.part" <<'EOF'
# Your personal STP account for the SGTL tutorial. Write your id and password after the "=" signs
# (no spaces around them). Only you may read this file (chmod 600). Never copy it into a repository,
# never share it, never paste it into a chat or an AI tool.
STP_USER=
STP_PASS=
EOF
  )
  mv -f -- "$f.part" "$f"
}

# data_course_datasets PYTHON: the names of the datasets that are not marked large, from the manifest.
data_course_datasets() {
  "$1" -I -c 'import sys
sys.path.insert(0, sys.argv[1])
from sgtl_tutorial import datafetch
print(" ".join(n for n, ds in datafetch.datasets().items() if not ds.large))' "$REPO/src"
}

component_data_run() {
  step "Your STP files and the course waveform data (data)"
  local prefix="${SGTL_ENV:-$SGTL_HOME/envs/sgtl}" data dot creds client want got name v listed ready=1
  local names=() failed=() sgtl=()
  prefix="${prefix%/}"
  data="${SGTL_DATA:-$SGTL_HOME/data}"
  data="${data%/}"
  [[ "$prefix" == /* ]] || die "SGTL_ENV must be an absolute path (it is '$prefix')."
  [[ "$data" == /* ]] || die "SGTL_DATA must be an absolute path (it is '$data')."
  dot="${HOME:?HOME is not set}/.sgtl"
  creds="$dot/credentials.env"
  client="$dot/stp-client.pl"
  for v in LD_LIBRARY_PATH PYTHONPATH PYTHONHOME; do unset "$v"; done
  export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_MAX_THREADS=1
  export NUMPY_MADVISE_HUGEPAGE=0 PYTHONNOUSERSITE=1
  if have nice; then DATA_NICE=(nice -n 10); else DATA_NICE=(env); fi
  say "Data folder:     $data"
  say "Your STP files:  $dot (account: credentials.env, program: stp-client.pl)"
  if [[ ! -x "$prefix/bin/python" ]]; then
    [[ $APPLY -eq 1 ]] && die "The course environment $prefix is missing (no bin/python). Install it first: bin/sgtl-install env --apply"
    warn "The course environment $prefix is missing (no bin/python): --apply will stop here. Install it first: bin/sgtl-install env --apply"
  fi
  if [[ ! -f "$SGTL_HOME/PocketQuake/pocketquake/stp_bridge.py" ]]; then
    [[ $APPLY -eq 1 ]] && die "PocketQuake is missing ($SGTL_HOME/PocketQuake); it makes the STP requests. Install the tools first: bin/sgtl-install tools --apply"
    warn "PocketQuake is missing ($SGTL_HOME/PocketQuake): --apply will stop here. Install the tools first: bin/sgtl-install tools --apply"
  fi

  # 1. folders (~/.sgtl: only you can open it)
  run mkdir -p "$data" "$dot"
  run chmod 700 "$dot"

  # 2. the account file: a template when missing; readable only by you
  if [[ -f "$creds" ]]; then
    run chmod 600 "$creds"
  else
    data_write_template "$creds"
  fi
  if ! data_has_value STP_USER "$creds" || ! data_has_value STP_PASS "$creds"; then
    ready=0
    say "Your STP account is not filled in yet: write your STP id and password into $creds"
  else
    say "STP account file: $creds (filled in; the values are not shown)"
  fi

  # 3. the STP program, checked by its fingerprint
  want="$(data_fingerprint)"
  if [[ ! "$want" =~ ^[0-9a-f]{64}$ ]]; then
    [[ $APPLY -eq 1 ]] && die "install/checksums.txt gives no verified fingerprint for stp-client.pl ('${want:-no entry}'), so the STP program cannot be checked. Tell the mentor (friction issue)."
    warn "install/checksums.txt gives no verified fingerprint for stp-client.pl ('${want:-no entry}'): --apply will refuse."
  fi
  if [[ ! -f "$client" ]]; then
    ready=0
    say "The STP program is missing: put the file the mentor gave you at $client"
  elif [[ "$want" =~ ^[0-9a-f]{64}$ ]]; then
    got="$(sha256_of "$client")"
    if [[ "$got" == "$want" ]]; then
      say "STP program: $client (fingerprint matches install/checksums.txt)"
    else
      ready=0
      say "$client is not the STP program the tutorial was checked with (its fingerprint differs). Ask the mentor for the current one."
    fi
  fi
  if [[ $APPLY -eq 1 && $ready -eq 0 ]]; then
    die "Nothing was fetched yet: do what the lines above say, then run this again (bin/sgtl-install data --apply)."
  fi

  # 4. the course datasets (not the large project datasets), each fetched and then checked
  sgtl=("${DATA_NICE[@]}" env "PYTHONPATH=$REPO/src" "SGTL_REPO=$REPO" "SGTL_DATA=$data" "SGTL_HOME=$SGTL_HOME"
    "$prefix/bin/python" -m sgtl_tutorial.cli)
  if [[ -x "$prefix/bin/python" ]]; then
    listed="$(data_course_datasets "$prefix/bin/python")" ||
      die "Could not read data/manifests/stp_datasets.yaml with $prefix/bin/python (see the messages above)."
    read -r -a names <<<"$listed"
  fi
  if [[ ${#names[@]} -eq 0 ]]; then
    action "fetch and check every dataset of data/manifests/stp_datasets.yaml that is not marked large"
  fi
  for name in ${names[@]+"${names[@]}"}; do
    step "Dataset $name"
    if ! run "${sgtl[@]}" data fetch "$name" --apply; then
      failed+=("$name")
      continue
    fi
    run "${sgtl[@]}" data verify "$name" || failed+=("$name")
  done
  say ""
  say "Waveforms: $data/<dataset>/stp_download/SAC/<UTC origin time>/<band>/ (see: bin/sgtl data list)"
  say "Large datasets for your project are fetched only by hand:  bin/sgtl data fetch <dataset> --apply --large"
  if [[ ${#failed[@]} -gt 0 ]]; then
    die "Not complete: ${failed[*]}. Run bin/sgtl-install data --apply again (it continues where it stopped); if the same error comes back, send the messages above to the mentor (friction issue)."
  fi
}
