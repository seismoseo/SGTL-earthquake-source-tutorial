# Your two research tracks

Complete both tracks: the **Suncheon microearthquakes** and an **independent Sangju study** centered on the public
2026 earthquake report. Use your own measurements to decide what the data support. Each track has its own plan,
criteria, data record, lab book and report; both include template matching and its validation.

The project begins in [M60](notebooks/M60_full_run/M60_full_run.ipynb). A realistic starting schedule is weeks 9–16,
with the two tracks developed in phases. You and your mentor may extend it or reduce the requested data volume;
keep both tracks and their validation. The [Sangju guide](sangju_project.md) explains its independent design.

| Track | Files you own | Central questions |
|---|---|---|
| Suncheon | existing files in `project/`, including `ANALYSIS_PLAN.md`, `criteria.yaml`, `claims.csv`, `LABBOOK.md` and `REPORT.md` | What do depths, relocated geometry and mechanisms show, with uncertainties? |
| Sangju | separate files under `project/sangju/` | Is seismicity deeper than comparable reference regions, and does activity persist beyond bursts after accounting for observing time and completeness? |

The Sangju descriptions are questions to test. Write the numerical hypotheses, selection rules and rejection
criteria yourself before evaluating research results. Record prior exposure to the course's Sangju2019 examples,
public reports and any conversations. Keep preliminary lab catalogs, locations, depth interpretations, mechanisms,
figures and processed waveforms outside both research inputs and the selection of the Sangju tests.

## Begin with the Suncheon plan

1. Finish M60's full analysis of the Gokseong sequence and its Suncheon data inventory.
2. Run `bin/sgtl new project` in your server terminal. M60 also offers the same copy step. It copies the templates
   once into `project/` and keeps any files you already have. Read `project/README.md` and `project/sangju/README.md`.
   Existing learners can run the same command after updating to add the new child templates without replacing
   their Suncheon files.
3. Read Kwak et al. (2022), listed in the [reading list](reading_list.md). Write your own `claims.csv`: what the
   paper claims, where it says it, and how your measurements could test it. Mark any abstract-only claim and verify
   it against the full paper with your mentor before testing it.
4. Write `ANALYSIS_PLAN.md` and fill `criteria.yaml` before analyzing project results. Record everything you have
   already seen, including the M60 inventory, in the plan's prior-exposure section.
5. Have your mentor review and sign the plan. Freeze the criteria with the date and checksum described in M60,
   record it in `LABBOOK.md`, run your M60 project audit, and commit the files together.

Then write and obtain sign-off on the separate Sangju plan and data request as described in
[its guide](sangju_project.md). The Suncheon files retain their M60 audit contract; keep the Sangju criteria in
`project/sangju/criteria.yaml` so neither track changes the other's frozen decisions.

## Work from the two frozen plans

Inspect `bin/sgtl data fetch suncheon_area` before downloading. This is a project dataset of several gigabytes;
download it with `--apply --large` only after agreeing on the data plan. Then run
`bin/sgtl data verify suncheon_area`. Waveforms stay outside the repository in your course data folder.

Keep a daily lab-book entry with the notebook or command, settings, run-record fingerprint and result. Compare
alternative models and station selections according to the plan. Preserve a direct-P/S location baseline within
about 100 km; exclude the Moho phases Pn and Sn, and document how each production locator handles crustal first
arrivals. Change a frozen decision rule only with a dated plan amendment that records whether you had already seen
results bearing on it.

Template matching from [M22](notebooks/M22_detection/M22_detection.ipynb) is required in both tracks. Complete the
Suncheon `TEMPLATE_MATCHING_PLAN.md` extension and the matching sections of the Sangju plan; retain the original
Suncheon M60 plan/criteria format. If its plan was already frozen, record the extension as a dated amendment before
viewing new detection outcomes. Freeze each
template bank, its channel/window rules, calibration records and validation records before measuring performance.
Evaluate records and earthquakes held out from template construction and tuning; inject known signals into
representative noise, run a noise-only null, and merge duplicate detections across templates before counting events.
Report the dependence on template choice, stations, time period and magnitude. A detector's missed events and gaps
must enter the uncertainty of a rate comparison.

## A phased schedule

| Target weeks | Work in both tracks | Review point |
|---|---|---|
| 9–10 | complete inventories, define reference regions and usable observing time, freeze the two plans and data requests | mentor signs selection rules, criteria and validation partitions |
| 11–12 | pick and locate independently; test depth uncertainty and station/model/phase sensitivity | compare synthetic recovery and direct-P/S baselines before interpreting depth |
| 13–14 | relocate, examine geometry and resolvable mechanisms; run template matching on the frozen windows | assess detections on held-out and injection tests, then compare completeness and rates |
| 15–16 | finish the reference-region and sensitivity comparisons, reproduce the analysis and write both reports | evidence checklist, joint talk and oral defense |

Move a review point when the data or pace require it. Do not trade away validation to finish a larger catalog.

## Finish with two reports and one comparison

- Complete `project/REPORT.md`, including its Korean and English summaries. Give uncertainties and name the
  notebook or script that prints each reported number.
- Complete `project/sangju/REPORT.md`, including the independence record, matched reference regions, depth tests,
  observing-time/completeness analysis and template-matching validation. Add its comparison with Suncheon.
- Adapt `project/TALK_OUTLINE.md` into one joint 15-minute talk covering both tracks and their different limits.
  Prepare to explain your code and reasoning at the oral defense.
- Review both plans, amendments, inventories, lab books, run records and reports with your mentor. Completion
  includes the M60 Suncheon audit and the Sangju evidence review in its README. An unresolved mechanism, an
  unsupported hypothesis or an inconclusive comparison is a valid result when you can explain the evidence.

Use the [Git workflow](git_workflow.md) to save your work and the [data policy](data_policy.md) for sharing and
attribution. The [curriculum](curriculum.md) gives the project schedule.
