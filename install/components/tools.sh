# shellcheck shell=bash
# install/components/tools.sh: location, relocation, picking and mechanism tools (sourced by bin/sgtl-install).
# Placeholder: this component arrives with release v0.2 of the tutorial; until then it installs nothing.
#
# Copyright (c) 2026 Minseong Seo (SGTL, Seoul National University). MIT License.

component_tools_summary() {
  printf '%s' 'location, relocation, picking and mechanism tools  (from release v0.2)'
}

component_tools_run() {
  step "location, relocation, picking and mechanism tools (tools)"
  say "It will install: HYPOINVERSE, HypoDD with the lab patch, PocketQuake v1.16.1, EQNet with the PhaseNet+ weights, and SKHASH."
  placeholder_component tools v0.2
}
