# shellcheck shell=bash
# install/components/mt.sh: MTUQ moment-tensor inversion (sourced by bin/sgtl-install).
# Placeholder: this component arrives with release v0.2 of the tutorial; until then it installs nothing.
#
# Copyright (c) 2026 Minseong Seo (SGTL, Seoul National University). MIT License.

component_mt_summary() {
  printf '%s' 'MTUQ moment-tensor inversion  (from release v0.2)'
}

component_mt_run() {
  step "MTUQ moment-tensor inversion (mt)"
  say "It will install: MTUQ (moment tensor uncertainty quantification) into the course environment."
  placeholder_component mt v0.2
}
