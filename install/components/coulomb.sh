# shellcheck shell=bash
# install/components/coulomb.sh: Elastic_stresses_py Coulomb stress (sourced by bin/sgtl-install).
# Placeholder: this component arrives with release v0.2 of the tutorial; until then it installs nothing.
#
# Copyright (c) 2026 Minseong Seo (SGTL, Seoul National University). MIT License.

component_coulomb_summary() {
  printf '%s' 'Elastic_stresses_py Coulomb stress  (from release v0.2)'
}

component_coulomb_run() {
  step "Elastic_stresses_py Coulomb stress (coulomb)"
  say "It will install: Elastic_stresses_py (Coulomb stress changes on receiver faults) into the course environment."
  placeholder_component coulomb v0.2
}
