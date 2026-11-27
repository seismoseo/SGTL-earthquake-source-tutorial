# Research projects: Suncheon and Sangju

After the lessons you answer two research questions with your own measurements. Both projects are required. Each has
its own plan, criteria, data record, lab book and report, and each includes validated template matching. Your
measurements decide the conclusions.

![Suncheon and Sangju project locations](figures/project_locator.png)

The circle marks the Suncheon course selection center; the star marks the epicenter KMA reported for 17 November
2026. Your plans define the study selections. Sources: the course's public
[selection settings](https://github.com/seismoseo/SGTL-earthquake-source-tutorial/blob/main/data/manifests/sequences.yaml),
the [KMA report](https://www.weather.go.kr/w/XML/INTENSITY/report_20261117231017.pdf) and the
[GSHHG coastline](https://www.soest.hawaii.edu/pwessel/gshhg/) through GMT.

| Project | Central questions |
|---|---|
| [Suncheon](suncheon_project.md): a published microearthquake cluster and a wider teaching-catalog selection; files in `project/` | Do apparent depth groups survive uncertainty tests? What fault geometry do the locations and mechanisms support? |
| [Sangju](sangju_project.md): a public November 2026 earthquake report and a regional sample you define; files in `project/sangju/` | How do the depths compare with matched reference regions? Does activity continue outside short bursts once observing limits are accounted for? |

## Rules for both projects

- **Plan before results** (**preregistration**). Write your hypotheses, selection rules and rejection criteria before
  you evaluate research results, and record what you have already seen (catalogs, course examples, papers,
  conversations). Change a frozen rule only by a dated amendment that says whether you had seen related results.
- **Your own measurements.** Make your own picks, locations and detections from documented source records, and trace
  every number to those inputs and your code. Keep published claims apart from measurements you checked.
- **Direct waves.** Keep a location baseline with direct P and S within about 100 km, without the Moho phases Pn and
  Sn. Record how each production locator handles first arrivals inside the crust.
- **Validated template matching** ([M22](notebooks/M22_detection/M22_detection.ipynb)). Freeze each template bank and
  its calibration and validation records first. Then test on held-out records, signal injections and noise-only
  windows, and merge duplicates across templates before counting. Missed events and gaps enter any rate comparison.
- **A lab book entry every working day:** the notebook or command, settings, run-record fingerprint and result.

## Start with the Suncheon plan (week 8)

1. Finish [M60](notebooks/M60_full_run/M60_full_run.ipynb): the Gokseong full run and the Suncheon data inventory
   (in `project/inventory/`).
2. Run `bin/sgtl new project` (M60 offers the same step). It copies the templates once into `project/`, keeps your
   files, and after an update adds missing templates. Read `project/README.md` and `project/sangju/README.md`.
3. Read Kwak et al. (2022) ([reading list](reading_list.md)) and write your own `claims.csv`. Check an
   abstract-only claim against the full paper with your mentor before you test it.
4. Write `ANALYSIS_PLAN.md` and fill `criteria.yaml`, with everything you have already seen (the M60 inventory too).
5. Your mentor signs the plan. Freeze the criteria with the date and checksum (as in M60), record them in
   `LABBOOK.md`, run your M60 project audit and commit the files together.

Then write the separate Sangju plan and data request ([Sangju guide](sangju_project.md)), with its own
`project/sangju/criteria.yaml`; M60 checks only the Suncheon files.

The Suncheon dataset holds several gigabytes. Read the plan of `bin/sgtl data fetch suncheon_area`, repeat it with
`--apply --large` only after you agree on the data plan, then run `bin/sgtl data verify suncheon_area`. Waveforms
stay in your course data folder, outside the repository.

## A phased schedule

| Weeks | Work in both projects | Review point |
|---|---|---|
| 9-10 | inventories, reference regions and usable observing time; freeze both plans and data requests | mentor signs selection rules, criteria and validation partitions |
| 11-12 | picks and locations from the source records; depth uncertainty and station/model/phase sensitivity | synthetic recovery and direct-P/S baselines, before interpreting depth |
| 13-14 | relocation, geometry and resolvable mechanisms; template matching on the frozen windows | held-out and injection tests, then completeness and rates |
| 15-16 | reference-region and sensitivity comparisons; reproduce the analysis; write both reports | evidence checklist, joint talk and oral defense |

You and your mentor may move a review point or request less data; keep both projects and their validation.

## Finish

- Two reports: `project/REPORT.md` (with Korean and English summaries) and `project/sangju/REPORT.md` (with the
  comparison of the two projects). Give uncertainties, and name the notebook or script that prints each number.
- A joint 15-minute talk from `project/TALK_OUTLINE.md`, and an oral defense of your code and reasoning.
- A review with your mentor of all plans, amendments, lab books, run records and reports. It includes the M60
  Suncheon audit and the Sangju evidence review in its README.

An unresolved or inconclusive result is valid when you can show the evidence. Save your work with the
[Git workflow](git_workflow.md); share and credit data by the [data policy](data_policy.md).
