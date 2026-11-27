# Suncheon project: small earthquakes and fault geometry

Small earthquakes can reveal a fault. Their locations show where slip happens; their waveforms and first motions show
how the rock moved. Can you tell a real structure underground from a pattern made by missed events, uncertain arrival
times or the station network?

## What motivates the project

Kwak et al. (2022) studied a small earthquake cluster about 10 km west-northwest of downtown Suncheon, from
September 2009 to August 2020. Their abstract reports 33 KMA-cataloged events below local magnitude 2 and 101 more
events found by matched filtering. It also reports a concentrated relocated structure and a comparison with focal
mechanisms ([abstract and publication record](https://pure.korea.ac.kr/en/publications/seismological-characteristics-of-microearthquake-sequence-near-su/),
[paper](https://doi.org/10.1007/s12303-022-0010-5)). Two questions follow. How much does a routine catalog miss? How
reliably do small earthquakes show a fault's shape?

The abstract is context, not a method or a target answer. Read the full paper with your mentor before you test a
detailed claim. In `project/claims.csv`, mark what you read only in the abstract and what you checked in a named
section, figure, table or page. Note differences in selection, stations, velocity model and processing.

Your M60 inventory uses a wider course selection: within 10 km of 34.92°N, 127.44°E, from 2002 to the November 2026
teaching cutoff. It is not the paper's cluster or period. Its catalog depths raise the depth-group question of your
plan.

## Watch out

- Catalog depths are estimates to check. Neither a repeated depth value nor a separate group in a histogram proves a
  separate population.
- A small formal error from one fit does not show **depth resolution** (that the data tell apart the depths your
  question needs) if another reasonable model moves the event a lot.
- A narrow line on a map does not fix a fault plane in three dimensions: shared location errors, few stations or
  several structures can change the apparent shape.
- Either nodal plane of a focal mechanism needs more evidence before you call it the fault.
- A template matcher finds signals like its examples, so its extra events may favor some earthquake families.

## Questions to test

Write the numerical hypotheses and your support, rejection and unresolved rules in your own plan. This guide gives no
thresholds and no expected result.

| Question | Methods | Evidence to produce |
|---|---|---|
| Do the apparent depth groups survive measurement uncertainty? | M20-M21 picks; M30-M32 depth scans and locations; synthetic recovery | depth intervals; sensitivity to stations, missing phases, starting depth and velocity model; excluded events counted |
| Does the selected cluster support one plane? | M41 relative relocation; a plane fit with uncertainty | map and depth sections; relative versus absolute uncertainty; other selections or several structures |
| Is the structure consistent with resolvable source motion? | M50-M53 first motions and waveform models | mechanism uncertainty; ambiguous nodal planes; station and instrument choices |
| Which extra earthquakes can matching recover? | M22 template matching; M05 completeness | a frozen bank; held-out and injection recovery; false alarms; limits of the detected population |
| Which conclusions survive plausible changes? | unchanged reruns and planned sensitivity runs | each conclusion with its uncertainty, other explanations and run record |

Use direct P and S inside the phase-specific crossover distances for your candidate depths and models, as well as
within about 100 km ([shared rules](project.md)). A production first-arrival solver can choose a head wave along a
boundary inside the crust: identify and document those stations.

## Your work and products

Look at the records behind a location or a candidate detection with the [SeisComP workflow](seiscomp_gui.md). Make
one session per event of your frozen selection, and save reviewed P/S picks, uncertainties and their XML/CSV
provenance. Compare accepted candidates, rejected transients and quiet controls with the same filter and time scale.
A GUI map or its default depth does not establish a depth group; your notebooks measure the uncertainty.

Work in the existing `ANALYSIS_PLAN.md`, `criteria.yaml`, `claims.csv` and `LABBOOK.md`, keeping the M60 question
structure for the audit, and complete `TEMPLATE_MATCHING_PLAN.md` before you look at new detection results. Report
failed tests and poorly resolved cases too. "The data cannot tell these explanations apart" is a useful conclusion
when you show why and name the observation needed next. Compare what Suncheon and [Sangju](sangju_project.md) let
you infer.
