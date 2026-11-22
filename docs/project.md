# Your Suncheon research project

In weeks 9–13, use the methods you learned to study the Suncheon microearthquakes: their depths, fault geometry and
mechanisms, including what the data cannot resolve. Your answers and decision thresholds come from your own work.
The project begins in [M60](notebooks/M60_full_run/M60_full_run.ipynb), after the taught lessons.

## Begin in week 8

1. Finish M60's full analysis of the Gokseong sequence and its Suncheon data inventory.
2. Run `bin/sgtl new project` in your server terminal. M60 also offers the same copy step. It copies the templates
   once into `project/` and keeps any files you already have. Read `project/README.md`.
3. Read Kwak et al. (2022), listed in the [reading list](reading_list.md). Write your own `claims.csv`: what the
   paper claims, where it says it, and how your measurements could test it. Mark any abstract-only claim and verify
   it against the full paper with your mentor before testing it.
4. Write `ANALYSIS_PLAN.md` and fill `criteria.yaml` before analyzing project results. Record everything you have
   already seen, including the M60 inventory, in the plan's prior-exposure section.
5. Have your mentor review and sign the plan. Freeze the criteria with the date and checksum described in M60,
   record it in `LABBOOK.md`, run your M60 project audit, and commit the files together.

## Work from the frozen plan

Inspect `bin/sgtl data fetch suncheon_area` before downloading. This is a project dataset of several gigabytes;
download it with `--apply --large` only after agreeing on the data plan. Then run
`bin/sgtl data verify suncheon_area`. Waveforms stay outside the repository in your course data folder.

Keep a daily lab-book entry with the notebook or command, settings, run-record fingerprint and result. Compare
alternative models and station selections according to the plan. Preserve a direct-P/S location baseline within
about 100 km; exclude the Moho phases Pn and Sn, and document how each production locator handles crustal first
arrivals. Change a frozen decision rule only with a dated plan amendment that records whether you had already seen
results bearing on it.

## Finish in week 13

- Complete `project/REPORT.md`, including its Korean and English summaries. Give uncertainties and name the
  notebook or script that prints each reported number.
- Build your 15-minute talk from `project/TALK_OUTLINE.md` and prepare to explain your code and reasoning at the
  oral defense.
- Review the plan, amendments, claims table, lab book and reproducible analysis with your mentor. An unresolved
  mechanism or an unsupported hypothesis is a valid scientific result when you can explain the evidence.

Use the [Git workflow](git_workflow.md) to save your work and the [data policy](data_policy.md) for sharing and
attribution. The [curriculum](curriculum.md) gives the project schedule.
