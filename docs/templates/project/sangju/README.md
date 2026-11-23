# Your independent Sangju research track

This is required alongside the Suncheon track in the parent `project/` folder. These files are yours to complete;
they contain questions and empty schemas, with no research answer or chosen threshold. `sgtl new project` adds new
templates and keeps existing files.

Read the tutorial's `docs/sangju_project.md` before writing the plan. The public KMA event report and the course
project definition supply provenance for the anchor earthquake. Treat catalog depths and descriptions of
continuing activity as things to test with your own measurements.

| File | Your task |
|---|---|
| `ANALYSIS_PLAN.md` | define independent selection, comparison regions, hypotheses, tests and alternatives; record prior exposure and obtain mentor sign-off |
| `criteria.yaml` | specify numerical quality, decision and detection-validation rules before viewing research results |
| `DATA_PLAN.md` | freeze the requested records, partitions, request method and resource budget; inventory what arrived |
| `data/event_inventory.csv` | record primary-source events, inclusion/exclusion rules and validation partitions |
| `data/reference_regions.csv` | document reference regions chosen by data-quality criteria before outcome comparisons |
| `data/template_bank.csv` | record the templates and their event/channel/window provenance |
| `data/search_windows.csv` | record requested and usable observing intervals, gaps and validation partitions |
| `data/stp_datasets.yaml` | draft custom known-event request manifest; fill from the signed plan and activate only after review |
| `LABBOOK.md` | append daily commands, settings, fingerprints, observations, failures and amendments |
| `REPORT.md` | report the measurements, uncertainty, validation and comparison with Suncheon, including unresolved results |

Only small provenance tables belong under `data/` here. Keep waveforms and large processed products under your
course data folder, outside the repository. Archive their fingerprints and the scripts that make the tables.

Reuse your own tested functions. Keep preliminary lab picks, catalogs, locations, depth estimates, mechanisms,
figures and processed waveforms outside this track's inputs and test selection. Record prior exposure to public
reports and the Sangju2019 teaching examples. Use personally requested data and independently reproduced products.

Before evaluating research results, finish the plan and data request, have the mentor sign them, fill and date the
criteria, and record SHA-256 fingerprints in the plan and lab book. A later change requires a dated amendment that
states what was already visible. Keep this track's decisions separate from the Suncheon criteria in the parent
folder; the existing M60 Suncheon audit remains part of that track.

The Sangju completion review requires:

- independent primary-source selection and a complete prior-exposure record;
- reference regions matched for observing and measurement quality, with frozen inclusion rules;
- depth uncertainty and sensitivity to geometry, velocity models, missing phases and starting conditions;
- usable observing time, completeness and a test separating background activity from bursts;
- a frozen template bank, records held out from tuning, injection recovery, noise-only tests and duplicate merging;
- reproducible run records, a report with uncertainties and a comparison with the required Suncheon track.

The mentor checks evidence for each item. A passing Suncheon audit alone does not complete the Sangju review.

Credit for the templates: Minseong Seo (SGTL, Seoul National University). CC BY 4.0.
