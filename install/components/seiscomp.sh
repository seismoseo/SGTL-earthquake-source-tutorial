# shellcheck shell=bash
# Offline SeisComP GUI, separate from the numerical Python environment.
# Copyright (c) 2026 Minseong Seo (SGTL, Seoul National University). MIT License.

component_seiscomp_summary() {
  printf '%s' 'SeisComP 7.4.0 offline GUI (Rocky/RHEL 8 x86_64); no database or services'
}

component_seiscomp_run() {
  local prefix="${SGTL_ENV:-$SGTL_HOME/envs/sgtl}" root="$SGTL_HOME/seiscomp"
  local archive=seiscomp-7.4.0-centos8-x86_64.tar.gz
  local boost=boost-container-1.66.0-13.el8.x86_64.rpm os_id os_version downloads="$SGTL_HOME/downloads/seiscomp"
  step 'SeisComP offline GUI (pinned 7.4.0, separate native installation)'
  [[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] ||
    die 'This installer supports Linux x86_64. See docs/seiscomp_gui.md for a mentor-provided GUI installation.'
  os_id="$(. /etc/os-release && printf '%s' "$ID")"
  os_version="$(. /etc/os-release && printf '%s' "$VERSION_ID")"
  if [[ ! "$os_id" =~ ^(rocky|rhel|centos|almalinux)$ || "$os_version" != 8* ]]; then
    die 'This binary recipe is validated for Rocky/RHEL 8 only. See docs/seiscomp_gui.md; do not install an incompatible binary.'
  fi
  [[ -x "$prefix/bin/python" || $APPLY -eq 0 ]] || die 'Install the course environment first: bin/sgtl-install env --apply'
  have rpm2cpio && have cpio || die 'rpm2cpio and cpio are required; ask the mentor to prepare the GUI host.'
  if [[ -e "$root" ]]; then
    [[ -f "$root/.sgtl-7.4.0" ]] || die "$root already exists without the course installation marker. Keep it; set SGTL_SEISCOMP_ROOT to use it (docs/seiscomp_gui.md)."
    say "Keeping existing installation: $root"
  else
    fetch_verified "$archive" "$downloads"
    fetch_verified "$boost" "$downloads"
    action "safely unpack verified SeisComP and the boost-container library under $root (no system packages changed)"
    if [[ $APPLY -eq 1 ]]; then
      env -u LD_LIBRARY_PATH -u PYTHONPATH -u PYTHONHOME "$prefix/bin/python" - "$downloads" "$root" <<'PY'
from pathlib import Path
import shutil, subprocess, sys, tarfile, tempfile
downloads, root = map(Path, sys.argv[1:])
root.parent.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='.sgtl-seiscomp-', dir=root.parent) as tmp:
    tmp = Path(tmp)
    with tarfile.open(downloads / 'seiscomp-7.4.0-centos8-x86_64.tar.gz') as tar:
        tar.extractall(tmp, filter='data')
    rpm = tmp / 'rpm'
    rpm.mkdir()
    archive = subprocess.run(['rpm2cpio', str(downloads / 'boost-container-1.66.0-13.el8.x86_64.rpm')],
                             stdout=subprocess.PIPE, check=True).stdout
    subprocess.run(['cpio', '-idm', '--quiet', '--no-absolute-filenames'], input=archive, cwd=rpm, check=True)
    staged = tmp / 'seiscomp'
    extra = staged / 'extra' / 'lib64'
    extra.mkdir(parents=True)
    shutil.copy2(rpm / 'usr/lib64/libboost_container.so.1.66.0', extra)
    (staged / '.sgtl-7.4.0').write_text('Official SeisComP 7.4.0 CentOS8 binary + Rocky boost-container 1.66.0-13.el8\n')
    staged.rename(root)
PY
    fi
  fi
  action 'check native viewer, event picker and inventory converter (display checked separately)'
  if [[ $APPLY -eq 1 ]]; then
    env -u LD_LIBRARY_PATH -u PYTHONHOME PYTHONPATH="$REPO/src" SGTL_HOME="$SGTL_HOME" SGTL_SEISCOMP_ROOT="$root" \
      "$prefix/bin/python" -m sgtl_tutorial.cli gui doctor ||
      die 'Native GUI dependency check failed. Keep the log and follow docs/seiscomp_gui.md troubleshooting with the mentor.'
  fi
  say 'No services started and no database configured. Next: bin/sgtl gui demo --apply (see docs/seiscomp_gui.md).'
}
