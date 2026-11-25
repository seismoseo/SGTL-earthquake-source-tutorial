# Sangju analysis plan

- Author: [write here]
- Started: {{date}}
- Mentor sign-off: [write here: name and YYYY-MM-DD]
- Frozen on: [write here: YYYY-MM-DD]
- SHA-256 of `criteria.yaml` at the freeze: [write here]
- SHA-256 of `DATA_PLAN.md` at the freeze: [write here]

Answer every question in your own words. Keep the questions and replace each `[write here]` placeholder. Set the
dates and file fingerprints after completing the criteria and data plan, then commit the signed files together.
After the freeze, record changes as dated amendments; preserve what was decided before the results were visible.

## 1. Prior exposure and source records

> Which public reports, catalog plots, teaching examples, papers and conversations have you already encountered?
> Which results or expectations might they suggest, and how will you record that influence?

[write here]

> Which source records and versions will you obtain? How will you derive the research picks, locations, detections
> and figures from those records, preserve their provenance and keep prior interpretations from determining the
> event selection or tests?

[write here]

## 2. Study selection and reference regions

> What are the geographic, time, magnitude, catalog-version and event-quality inclusion rules? How can another
> person reproduce the event inventory before seeing relocated depths or the result of the activity test?

[write here]

> Which reference regions will you choose, from which primary sources, and by what rule independent of the tested
> depth or persistence outcome? How will you match network epoch, station geometry, phase quality, magnitude and
> usable observing time? What will you do if an adequate comparison cannot be obtained?

[write here]

## 3. Hypotheses and alternative explanations

> What precisely does the depth question mean: which population, depth metric, comparison and uncertainty? State
> a hypothesis and the numerical support/rejection/unresolved rules in `criteria.yaml` without treating a catalog
> depth as a known answer.

[write here]

> What precisely does persistence mean: the observation interval, usable-time denominator, rate or occupancy metric,
> completeness limit and rule for bursts? State the hypothesis and the rules that distinguish continuing background,
> bursts, a mixture and unresolved evidence.

[write here]

> Which measurement or selection effects could create or hide either pattern? Which planned test addresses each
> explanation, and which ambiguity would remain?

[write here]

## 4. Data and the order of access

> Which records belong to template construction, threshold calibration and independent validation? Define events,
> families and windows so that copies of a signal do not cross those partitions. Which feasibility data have you
> already examined, and which results remain unopened until the plan is signed?

[write here]

> How will you request the frozen records, record gaps and station epochs, and compute usable observing time?
> Refer to `DATA_PLAN.md` and the tables under `data/`. What is the resource budget and the fallback if records
> are unavailable?

[write here]

## 5. Location, phase selection and uncertainty

> What is the direct-P/S baseline within about 100 km, and what phase-specific crossover distances restrict it for
> the candidate depths and models? How will you exclude Moho Pn/Sn and document any crustal-head-wave treatment
> in production comparisons, including the vertical reference used for depth?

[write here]

> Which synthetic recovery, depth-scan and uncertainty tests will you run? How will you vary station geometry,
> nearest-station availability, P/S phase coverage, pick errors, velocity model, starting depth and the depth–time
> tradeoff? When is depth too poorly resolved to classify?

[write here]

## 6. Template matching and independent validation

> How will you choose and freeze the template bank, filters, channels, windows and candidate-merging rules? What
> family or station bias could that bank introduce?

[write here]

> Which real events/windows will remain held out from construction and tuning? How will you inject known signals
> into representative noise with real gaps, measure recovery and false alarms, and test the effect of withholding
> templates or families? Write the numerical acceptance criteria in `criteria.yaml` before viewing these results.

[write here]

> What independent station/phase evidence will validate a new candidate? How will you merge duplicates across
> templates and keep uncertain candidates visible without counting them as confirmed events?

[write here]

## 7. Activity, completeness and bursts

> How will you estimate completeness by network epoch and magnitude, using both catalog information and detection
> tests? How will false alarms, missed events and gaps enter the uncertainty of the activity metric?

[write here]

> Which frozen rule identifies bursts? How will you compare with and without burst intervals, using the same
> rules in the reference regions? Which changes in observability could still explain a difference?

[write here]

## 8. Decisions, comparison and reproducibility

> For each hypothesis, which metric, threshold and decision rule will you use? Confirm that the plan agrees with
> `criteria.yaml` and specify which plausible changes would reverse the conclusion.

[write here]

> What will the Sangju–Suncheon comparison test, and which differences in data quality or design prevent a direct
> comparison? Which notebooks/scripts and run records will reproduce every reported number?

[write here]

## 9. Risks and phased schedule

> Which unavailable records, processing limits or time constraints could stop the plan? How will you reduce data
> volume or extend the schedule while preserving both required projects and independent validation?

[write here]

## Amendments

Append one row per change after the freeze; keep earlier decisions and rows.

| date (YYYY-MM-DD) | what changed | why | results already seen that bear on it |
|---|---|---|---|
