# shellcheck shell=bash
# install/components/pyfk.sh: PyFK synthetic-seismogram environment "sgtl-pyfk" (sourced by bin/sgtl-install).
# Placeholder: this component arrives with release v0.2 of the tutorial; until then it installs nothing.
#
# Copyright (c) 2026 Minseong Seo (SGTL, Seoul National University). MIT License.

component_pyfk_summary() {
  printf '%s' 'PyFK synthetic-seismogram environment "sgtl-pyfk"  (from release v0.2)'
}

component_pyfk_run() {
  step "PyFK synthetic-seismogram environment \"sgtl-pyfk\" (pyfk)"
  say "It will install: the separate Python 3.9 environment \"sgtl-pyfk\" from envs/pyfk.yml (PyFK 0.3.0, frequency-wavenumber synthetic seismograms)."
  placeholder_component pyfk v0.2
}
