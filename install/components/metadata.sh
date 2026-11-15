# shellcheck shell=bash
# install/components/metadata.sh: KS/KG station metadata (sourced by bin/sgtl-install).
# Placeholder: this component arrives with release v0.2 of the tutorial; until then it installs nothing.
#
# Copyright (c) 2026 Minseong Seo (SGTL, Seoul National University). MIT License.

component_metadata_summary() {
  printf '%s' 'KS/KG station metadata  (from release v0.2)'
}

component_metadata_run() {
  step "KS/KG station metadata (metadata)"
  say "It will install: the StationMetadata collection (station coordinates and instrument responses) under ~/sgtl/metadata."
  placeholder_component metadata v0.2
}
