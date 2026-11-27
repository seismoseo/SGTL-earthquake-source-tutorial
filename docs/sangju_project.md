# Sangju project: earthquake depths and activity

At what depths do earthquakes occur near Sangju, inland South Korea, and does activity continue between short bursts?
Alongside the [Suncheon project](suncheon_project.md), you define the study, get the observations, test other
explanations and report what the evidence can resolve.

## The starting point

One public [KMA earthquake analysis report](https://www.weather.go.kr/w/XML/INTENSITY/report_20261117231017.pdf)
gives an earthquake with

- time **23:10:17 KST on 17 November 2026** (**14:10:17 UTC**);
- magnitude **ML 3.6**;
- epicenter **36.516°N, 127.959°E**;
- **reported depth 20 km**.

The report also lists 52 earthquakes of ML 2.0 or larger within 30 km since 1978 (as of 18 November 2026), including
an ML 5.2 event in 1978. One reported depth does not show that Sangju earthquakes are unusually deep. A list of past
events does not show a steady rate, a common fault or constant detection.

**Watch out:** the course's KMA teaching catalog ends at **6 November 2026, 13:07:46 UTC**: it lacks this earthquake
and everything after it. `sangju2019` and `sangju2019_hours` are earlier teaching examples. Get and archive an updated
public catalog and your own research waveforms.

## Questions to test

- **Depth.** Which depths stay compatible with the arrivals under reasonable velocity models and pick errors? Does
  the regional depth distribution differ from reference regions of matched recording quality?
- **Activity.** Does activity continue outside short bursts (**persistence**), counted over **usable observing time**
  and above the **completeness** limit (the sizes at which detection is reliable)?
- **Observation bias.** Could changes in stations, instruments, noise or detection make one period look quieter, or
  one region deeper?

Your tests must allow a supported difference, no difference or an unresolved result; if a question stays unresolved,
say which observation would change that. You choose the numbers before you see the outcomes, and the
[shared rules](project.md) apply.

## 1. Record the sources and plan

Keep a copy of the course's project definition and its SHA-256 fingerprint with your data plan. It is a public
anchor, not your selection:

```python
import sgtl_tutorial as st
st.data.project_definition("sangju")
```

Run `bin/sgtl new project` after updating and open `project/sangju/README.md`, which lists your separate Sangju
plan, criteria, data plan, lab book, report and data tables. Define the region, period, catalog version and inclusion
rule without filtering for a desired depth or pattern. Keep catalog IDs as published; never construct a KMA ID.

## 2. Choose reference regions first

A reference region gets the same rules, to show what Sangju should be compared with. Freeze the regions before you
see their depths or rates, and record the rule in `data/reference_regions.csv`. Did you match the network epoch,
station distances and coverage, magnitudes, pick quality, observing time, velocity model and processing? If no
comparable records exist, narrow the claim.

## 3. Freeze the data request

An **event window** is a short record around a known earthquake; a **search window** is a continuous interval in
which you count detections. Event windows alone cannot show what happened between them. Freeze the selection,
regions, stations, windows, partitions and budget in `DATA_PLAN.md`, and have your mentor sign. Use your personal STP
access as in M03; waveforms stay in your course data folder.

For known-event windows, fill the draft manifest `project/sangju/data/stp_datasets.yaml` from the signed plan (its
comments give the naming rules), and change `status: draft` to `active` only after review, with the final
fingerprint. Replace `YOUR_DATASET_NAME` with your new name, such as `sangju_pilot_v1`, and read each dry run first:

```bash
bin/sgtl data list --manifest project/sangju/data/stp_datasets.yaml
bin/sgtl data fetch YOUR_DATASET_NAME --manifest project/sangju/data/stp_datasets.yaml
bin/sgtl data fetch YOUR_DATASET_NAME --manifest project/sangju/data/stp_datasets.yaml --apply --large
bin/sgtl data verify YOUR_DATASET_NAME --manifest project/sangju/data/stp_datasets.yaml
```

- `request_definition.json` binds the request: a change needs a new dataset name and a plan amendment.
- The fetch picks stations around the dataset's mean epicenter (check the printed center and radius): request
  separated regions separately.
- Event windows give no continuous observing time: document and pilot the STP time-window protocol for search windows
  in `DATA_PLAN.md`.
- A small pilot first checks format, volume and stations; record it as prior exposure.

Then register the events as a PocketQuake cluster (`YOUR_CLUSTER_SLUG`: lowercase letters, digits and underscores):

```bash
bin/sgtl pq stage YOUR_DATASET_NAME --manifest project/sangju/data/stp_datasets.yaml --slug YOUR_CLUSTER_SLUG
bin/sgtl pq stage YOUR_DATASET_NAME --manifest project/sangju/data/stp_datasets.yaml --slug YOUR_CLUSTER_SLUG --apply
```

Then follow the dry-run, preflight and `--apply` steps of [M32](notebooks/M32_hypoinverse/M32_hypoinverse.ipynb) and
[M60](notebooks/M60_full_run/M60_full_run.ipynb), one heavy job at a time. Inventory what arrived, with its gaps, and
fingerprint the files.

## 4. Test the depths

Inspect the records and station geometry with the [SeisComP workflow](seiscomp_gui.md), and save your own picks.
Do a deep candidate and a shallower event both have close stations, clear S arrivals and usable components? Use
direct P and S within about 100 km and inside the crossover distances for your candidate depths, without Moho Pn and
Sn. With M30-M32 and M41, test station geometry, velocity models, pick errors, the nearest station, missing S,
starting depth and the depth-origin-time trade-off, in the reference regions too. When does a depth count as
resolved? Decide in advance.

## 5. Separate background, bursts and observability

Define persistence in numbers. Count events against usable observing time (gaps are unobserved time), and estimate
completeness by network epoch and magnitude (M05). Freeze a burst rule and compare results with and without the
bursts, here and in the reference regions. Allow for a continuing background, a few bursts, a mixture or an
unresolved result.

## 6. Validate template matching

Follow [M22](notebooks/M22_detection/M22_detection.ipynb) and the shared rules. Record the bank in
`data/template_bank.csv`. Never put copies of one earthquake in both the construction and the validation set. Keep
the real gaps when you inject signals. Measure how withholding a template family changes recovery.

Finally, reproduce the run from archived inputs, repeat it unchanged, make the planned sensitivity changes, and
compare the evidence with Suncheon.
