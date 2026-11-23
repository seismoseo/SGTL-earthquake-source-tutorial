# Sangju: an independent study of depth and continuing activity

This is the second required research track, alongside [Suncheon](project.md). The questions are whether the selected
Sangju earthquakes are deeper than earthquakes recorded under comparable conditions elsewhere, and whether activity
persists outside short bursts. Write tests that can also conclude that the difference is absent or unresolved.

The public starting point is one KMA report: an earthquake at **23:10:17 KST on 17 November 2026**, equivalent to
**14:10:17 UTC**, with **ML 3.6**, at **36.516°N, 127.959°E**, and a **reported depth of 20 km**. Treat that depth as
a catalog baseline to investigate with your own observations and uncertainty analysis. The source is the
[official KMA earthquake analysis report](https://www.weather.go.kr/w/XML/INTENSITY/report_20261117231017.pdf).

The course's project definition records this starting provenance and its catalog cutoff:

```python
import sgtl_tutorial as st
st.data.project_definition("sangju")
```

Keep a copy of that definition and its SHA-256 fingerprint with your data plan. You choose the research events,
regions and search windows; the definition supplies a public anchor, not the result of your selection.

The shipped KMA teaching catalog ends at **6 November 2026, 13:07:46 UTC**. It does not contain this earthquake
or subsequent activity. The `sangju2019` and `sangju2019_hours` waveform datasets are earlier teaching examples.
Independently obtain and archive an updated public catalog and your chosen research waveforms; adding the one
reported earthquake to the old snapshot would still leave a gap and would not produce a complete research catalog.

## 1. Start with an independence record

Run `bin/sgtl new project` after updating, then open `project/sangju/README.md`. Existing project files are kept.
The child folder contains a separate `ANALYSIS_PLAN.md`, `criteria.yaml`, `DATA_PLAN.md`, `LABBOOK.md`, `REPORT.md`
and small data-record tables. The existing files at `project/` remain the Suncheon track.

Before viewing research results, record what you have already seen: the public KMA report, catalog plots, the
Sangju2019 teaching examples, readings and conversations. Reuse your own checked course functions and the documented
tools. Build the research selection and analysis from independent public-source records and personally requested
waveforms. Do not import preliminary lab catalogs, picks, relocations, inferred depths, mechanisms or figures,
and do not tune your plan to reproduce such products.

Define the study region, period, catalog version/cutoff and event inclusion rule without filtering for a desired
depth or temporal pattern. Archive the selection script, its input fingerprints and its exclusions. Keep source
catalog identifiers as published; record an absent identifier as absent rather than constructing a KMA ID.

## 2. Choose comparable reference regions before comparing outcomes

A reference region is an area analyzed with the same rules to show what the Sangju result should be compared with.
Choose and freeze regions using stated source and quality criteria before inspecting their relocated depths or
the outcome of the rate test. Document how you match or account for:

- the network epoch, station availability, nearest-station distance and angular coverage;
- magnitude range, number of usable P and S picks, pick uncertainty and waveform quality;
- usable observing time, gaps, channels and the event-selection/completeness rules;
- the velocity model, vertical reference and processing settings used for location.

Use `data/reference_regions.csv` to preserve the rule and the reasons for exclusions. If comparable records cannot
be obtained, narrow the claim and report that limitation instead of choosing a favorable comparison.

## 3. Freeze the data request and the tests

Complete `DATA_PLAN.md` and the schema-only tables under `project/sangju/data/`. Distinguish an **event window**, a
short record around a known earthquake, from the **search windows**, continuous observing intervals on which you
measure detections and activity. A collection of known-event windows cannot establish how often earthquakes
occurred during the time between them.

Before requesting the full data volume, freeze your event selection, reference regions, station/channel rules,
requested time windows, template/calibration/validation partitions and resource budget. Have the mentor sign the
plan. Use your personal STP access and an archived request script or supported request manifest; record the exact
command, UTC boundaries and request fingerprint in `DATA_PLAN.md`. Follow M03 for credentials and file permissions.
The teaching datasets listed by `bin/sgtl data list` keep their existing definitions; select the research windows
from your own frozen plan. Store waveforms under your course data folder, outside the repository.

For selected **known-event windows**, the child folder includes a draft manifest at
`project/sangju/data/stp_datasets.yaml`. Fill it from the signed selection using the same schema as the teaching
manifest. Choose your own unique dataset name, such as `sangju_pilot_v1`, and replace `YOUR_DATASET_NAME` below;
this example name chooses no events or windows. Keep `status: draft` until the request has been reviewed and frozen,
then set it to `active` and record the final fingerprint before requesting:

```bash
bin/sgtl data list --manifest project/sangju/data/stp_datasets.yaml
bin/sgtl data fetch YOUR_DATASET_NAME --manifest project/sangju/data/stp_datasets.yaml
bin/sgtl data fetch YOUR_DATASET_NAME --manifest project/sangju/data/stp_datasets.yaml --apply --large
bin/sgtl data verify YOUR_DATASET_NAME --manifest project/sangju/data/stp_datasets.yaml
```

Read the dry-run plan first. Custom names must differ from shipped dataset names. The received dataset's
`request_definition.json` binds the event/window/radius settings; a changed request needs a new dataset name and a
plan amendment. Use a published event identifier when one exists, or an explicit report namespace when it does not.
For continuous search intervals, document and pilot the STP client's time-window request protocol in `DATA_PLAN.md`;
the known-event fetch above does not establish months of continuous observing exposure.

After verification, register the selected event dataset as its own PocketQuake cluster. Replace
`YOUR_CLUSTER_SLUG` with a new name using lowercase letters, digits and underscores, then inspect the dry run:

```bash
bin/sgtl pq stage YOUR_DATASET_NAME --manifest project/sangju/data/stp_datasets.yaml --slug YOUR_CLUSTER_SLUG
bin/sgtl pq stage YOUR_DATASET_NAME --manifest project/sangju/data/stp_datasets.yaml --slug YOUR_CLUSTER_SLUG --apply
```

Keep that slug and request fingerprint in the lab book. Continue with the ordinary dry-run/preflight/`--apply`
stage workflow from [M32](notebooks/M32_hypoinverse/M32_hypoinverse.ipynb) and
[M60](notebooks/M60_full_run/M60_full_run.ipynb), using your research cluster and its planned settings. Run one
heavy job at a time and preserve the unchanged rerun and planned sensitivity comparisons. Continuous search
records still follow the separate frozen request/detection protocol; staging known events does not stage or
validate the intervening continuous observing windows.

Inventory what actually arrived, including missing channels and time intervals, and fingerprint the files. Make
any change to a frozen request a dated amendment that says which results you had already seen. Request a small
pilot first to check format, volume and station availability; distinguish that feasibility check from tuning a
scientific threshold, and record the pilot as prior exposure.

## 4. Test depths and their uncertainty

Begin with direct P and S within about 100 km, restricted further by their crossover distances for the candidate
depths and models; exclude Moho Pn and Sn. Record any crustal-head-wave treatment in production-tool comparisons.
Use the depth scan, synthetic recovery and uncertainty methods from M30–M32 and M41. Your preregistered tests should
ask how the result changes with station geometry, plausible velocity models, pick errors, the nearest station,
missing S phases, starting depth and the depth–origin-time tradeoff.

Analyze Sangju and the matched regions with the same pipeline and quality rules. Separate formal errors from
uncertainty under these alternative choices. Define in advance when depth is resolved and when the evidence is
too weak to classify an event. Report the events that fail a quality rule and the effect of their exclusion.

## 5. Separate background activity, bursts and changes in observability

Define **persistence** numerically before testing it. Count events against **usable observing time**, the intervals
in which the required station/channel set was actually available. Treat gaps as unobserved time. State how you
estimate completeness by network epoch and magnitude, using M05 and the detection validation below.

Freeze a rule for identifying bursts and compare the conclusions with and without those intervals, using the same
procedure in the reference regions. Quantify the uncertainty of the rate and persistence metrics. Check whether a
changed network, magnitude threshold, template bank or data availability can explain the apparent difference.
Distinguish a continuing background, a few short bursts, a mixture and an unresolved classification in your decision
rule; choose the numerical criteria yourself.

## 6. Validate template matching before making a larger catalog

Use [M22](notebooks/M22_detection/M22_detection.ipynb) as the method prerequisite. A template bank is the fixed set
of example signals you search for. Record its earthquake families, stations, channels, bands, windows and quality
rules in `data/template_bank.csv`, and freeze it with the validation design.

- Reserve real earthquakes and time windows that were not used to build templates or tune thresholds. Avoid
  putting copies of one earthquake into both construction and validation sets.
- Inject signals with known times and amplitudes into representative noise, preserving the real gaps and channel
  availability. Measure recovery across amplitude, noise, station and template conditions, and retain missed cases.
- Run noise-only/null windows to measure false alarms. Use the same preprocessing, station coincidence and merging
  rules as in the science run.
- Merge duplicate candidates from different templates before counting events. Validate candidates using independent
  station/phase evidence and report which cases remain uncertain.
- Measure how changing the bank or withholding a family changes recovery. Template matching favors signals similar
  to its examples; its validation describes the population it can detect, rather than every possible earthquake.

Freeze the validation partitions and acceptance thresholds before opening their results. Carry false alarms,
missed-event estimates and usable observing time into the comparison of rates and persistence. Apply the same
validation principles in the Suncheon track and compare the two detectors' limits.

## 7. Produce an auditable result

The mentor reviews the signed plans, data provenance, reference-region rules, uncertainty tests and independent
detection validation before accepting conclusions. Supply both reports and a joint comparison, with notebooks or
scripts that print every reported number. Reproduce the run from the archived inputs and settings, repeat it
unchanged, then perform the planned sensitivity changes. Keep the input fingerprints and executed run records.

The report may conclude that depth or persistence is unresolved. State what additional observation would change
that conclusion and whether it is feasible. The target is a defensible independent result, whichever outcome the
measurements support.
