# Sangju data plan

- Author: [write here]
- Started: {{date}}
- Mentor sign-off: [write here: name and YYYY-MM-DD]
- Frozen on: [write here: YYYY-MM-DD]
- Source project-definition fingerprint: [write here]

Keep waveforms outside the repository. This file and the small tables under `data/` describe the selection,
requests, provenance, gaps and validation partitions. Do not put credentials, STP settings or private server paths here.

## 1. Primary sources and selection

> Which catalog release/cutoff and public anchor report do you use? Where are the archived input fingerprints?
> Which script implements the frozen region, period, magnitude and quality rules without filtering for the desired
> depth or persistence outcome?

[write here]

> How are source identifiers preserved, absent identifiers represented, duplicate catalog entries handled and
> exclusions recorded in `data/event_inventory.csv`?

[write here]

## 2. Reference regions

> Which independent rule selects reference regions before outcome comparisons? Describe the available records and
> matching variables in `data/reference_regions.csv`, including a fallback for inadequate coverage.

[write here]

## 3. Requested records and observing time

> Which short event windows and which continuous search windows are needed? Fill `data/search_windows.csv` with UTC
> start/end times, region, station/channel rules and construction/calibration/validation partitions before requests.

[write here]

> Which exact supported request method, command and private request-manifest/script will you use with your personal
> STP access? How will you preview its size, fingerprint the request and keep waveforms outside the repository?

[write here]

> How will you record station epochs, unavailable channels, gaps, clipped records and usable seconds per window?
> How will those losses enter the rate/completeness comparison rather than being counted as quiet time?

[write here]

## 4. Templates and validation

> Which independently obtained events may become templates, by what quality rule? Fill `data/template_bank.csv`
> with their source fingerprints, families, channels, bands and windows. Which real events/windows stay held out?

[write here]

> Which noise conditions and gap masks will be used for signal injections and null tests? How will you prevent
> template construction or threshold tuning from using the independent validation outcomes?

[write here]

## 5. Pilot, resources and actual inventory

> Which small pilot checks request format, availability and volume? Record what it exposed before the freeze.
> What are the core, memory, disk and elapsed-time budgets, and the order of the requests/runs?

[write here]

> Which manifest and SHA-256 record will document the received files and missing intervals? How will you compare
> requested and usable records and record any deviation from this signed plan?

[write here]

## Amendments

| date (YYYY-MM-DD) | request or selection change | why | relevant data/results already seen |
|---|---|---|---|
