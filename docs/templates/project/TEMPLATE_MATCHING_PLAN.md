# Suncheon template-matching plan

- Author: [write here]
- Started: {{date}}
- Mentor sign-off: [write here: name and YYYY-MM-DD]
- Frozen on: [write here: YYYY-MM-DD]
- Frozen bank/request/partition fingerprints: [write here]

This required extension keeps the existing Suncheon `ANALYSIS_PLAN.md`, `criteria.yaml` and M60 audit format intact.
Reference it from your analysis plan. If that plan was already frozen, record an amendment before evaluating new
matching results, with what you have already seen. Record this extension's final SHA-256 fingerprint in LABBOOK.md.

## 1. Selection and observing time

> Which Suncheon events can become templates, by what rule? Which continuous search windows, stations and channels
> will you use, and how will gaps and network epochs define usable observing time?

[write here]

## 2. Frozen template bank and processing

> Where is the template-bank inventory with event, family, source fingerprint, stations/channels, band and window?
> How do you choose templates without selecting for the desired research result, and how will you measure bank bias?

[write here]

> Which thresholds, station-coincidence rules, time tolerances and cross-template duplicate-merging rules will you
> freeze? How will independent station/phase evidence distinguish confirmed and uncertain candidates?

[write here]

## 3. Calibration and independent validation

> Which records/events tune the detector, and which remain held out? How will you keep copies of one signal or
> event family from leaking between template construction, calibration and validation?

[write here]

> How will you inject known signals into representative noise and gaps, retain missed cases, and measure recovery
> across amplitudes, stations and template families? Which noise-only/null windows estimate false alarms?

[write here]

Write numerical acceptance rules before viewing the validation outcomes.

| test | metric and unit | acceptance threshold | result that requires revision or leaves the claim unresolved |
|---|---|---|---|
| held-out real cases | [write here] | [write here] | [write here] |
| signal injection recovery | [write here] | [write here] | [write here] |
| noise-only false alarms | [write here] | [write here] | [write here] |
| template-bank sensitivity | [write here] | [write here] | [write here] |
| duplicate merging and independent candidate checks | [write here] | [write here] | [write here] |

## 4. Research interpretation and comparison

> Which event population does the detector's validation cover, and which might it miss? How will false alarms,
> missed events, magnitude/epoch completeness and usable observing time enter the research uncertainty?

[write here]

> What can you compare with the independently designed Sangju detector, given their different records, banks and
> station coverage? Which scripts/run records will reproduce the comparison?

[write here]

## Amendments

| date (YYYY-MM-DD) | what changed | why | relevant outcomes already seen |
|---|---|---|---|
