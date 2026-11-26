# Suncheon project: small earthquakes and fault geometry

Small earthquakes can reveal a fault that is difficult to study from a single event. Their locations show where
slip occurs; their waveforms and first motions constrain how the rock moved. The challenge is to distinguish a
real underground structure from patterns produced by missed events, uncertain arrival times or the station network.
In this project you will make that distinction using the methods you built in the course.

## The observations that motivate the project

Suncheon is in southern South Korea. Kwak et al. (2022) studied a small earthquake cluster about 10 km
west-northwest of downtown Suncheon over September 2009–August 2020. Their abstract reports 33 KMA-cataloged events
with local magnitude below 2, and 101 additional events found with matched filtering. It also reports a concentrated
relocated structure and a comparison with focal mechanisms. These public observations motivate two questions:
how much seismicity a routine catalog misses, and how reliably small earthquakes reveal fault geometry.
See the [authors' institutional abstract and publication record](https://pure.korea.ac.kr/en/publications/seismological-characteristics-of-microearthquake-sequence-near-su/)
and [the paper](https://doi.org/10.1007/s12303-022-0010-5).

The abstract supplies context, not a complete method or a target answer. Read the full paper with your mentor
before testing a detailed published claim. In `project/claims.csv`, distinguish what you read in the abstract from
what you verified in a named section, figure, table or page. Record differences in selection, station coverage,
velocity model and processing before comparing your measurements with the publication.

Your M60 inventory uses a broader course selection: a 10 km radius around 34.92°N, 127.44°E, from 2002 through the
November 2026 teaching cutoff. That selection is not automatically the paper's cluster or study period. It also
raises the Suncheon plan's depth-group question from the catalog values. Catalog depths are estimates to check;
neither a repeated depth value nor a separated group in a histogram establishes a separate physical population.

## What the questions mean

An earthquake's **hypocenter** is its estimated starting point underground; its **epicenter** is the point above
it on a map. A depth estimate depends on the arrival times, station positions, assumed wave speeds and vertical
reference. **Depth resolution** means the data can distinguish the depths relevant to your question. A small
formal error from one fit does not establish resolution if another plausible model moves the event substantially.

**Fault geometry** describes a fault's position, orientation and extent. **Strike** is its compass direction and
**dip** its inclination below horizontal. Nearby earthquakes may outline a structure, but a narrow line in a map
view does not determine a plane in three dimensions. Shared location errors, a limited station layout or several
overlapping structures can affect the apparent shape. A **focal mechanism** describes the source motion; its two
possible nodal planes require additional evidence before either is identified as the physical fault.

The **seismogenic depth range** is the range in which earthquakes occur in the population being studied. A small
selected catalog can constrain that population without establishing the deepest possible earthquake in the region.
Detection matters here: a template matcher searches for signals resembling chosen examples, so its extra events
may represent some earthquake families better than others.

## Turn methods into tests

Write the numerical hypotheses and support, rejection and unresolved rules in your own plan. The guide supplies
the connections between methods and questions; it does not supply decision thresholds or an expected result.

| Question | Methods you bring from the lessons | Evidence to produce |
|---|---|---|
| Do the apparent depth groups survive measurement uncertainty? | M20–M21 picks with uncertainties; M30–M32 travel times, depth scans and location; synthetic recovery | depth intervals and sensitivity to station geometry, missing phases, starting depth and velocity model, with excluded events accounted for |
| Does the selected cluster support one plane? | M41 waveform time differences and relative relocation; a plane fit with uncertainty | map and depth sections, relative versus absolute uncertainty, and comparisons with alternative event selections or more than one structure |
| Is the inferred structure consistent with resolvable source motion? | M50–M51 first motions; M52–M53 waveform models where records support them | mechanism uncertainty, ambiguous nodal planes and the effect of station or instrument choices |
| Which additional earthquakes can matching recover? | M22 template construction, candidate merging and validation; M05 completeness concepts | a frozen template bank, held-out and injection recovery, false-alarm checks and the limits of the detected population |
| Which conclusions withstand plausible changes? | unchanged reruns and planned sensitivity runs across the pipeline | a table connecting each conclusion to its uncertainty, alternative explanation and reproducible run record |

Use a direct-P/S baseline within about 100 km and inside the phase-specific crossover distances for the candidate
depths and models. Exclude the Moho phases Pn and Sn. A production first-arrival solver can select a head wave along
a boundary inside the crust; identify and document its treatment when comparing with that baseline.

## Your work and final products

Use the [SeisComP GUI workflow](seiscomp_gui.md) to inspect the recordings behind a location or a
template-matching candidate. Start from your frozen event selection, create one local session per event,
and save reviewed P/S picks with uncertainties and their XML/CSV provenance. Inspect accepted candidates,
rejected transients and quiet controls with the same filter and time scale. These observations help you
explain whether apparent depth groups or activity changes could come from data quality. Estimate their
uncertainty quantitatively in your notebooks; a GUI map or its default locator depth does not establish a group.

Begin with [the project setup and schedule](project.md). M60 builds an inventory and helps you prepare the Suncheon
plan; you then choose the research selection and tests, obtain mentor sign-off, and freeze the criteria before
evaluating results. Use the existing `project/ANALYSIS_PLAN.md`, `criteria.yaml`, `claims.csv` and `LABBOOK.md`.
Complete `TEMPLATE_MATCHING_PLAN.md` before examining new detection outcomes. Keep the M60 question structure so
the project audit can check that the plan is complete.

You will produce a documented catalog selection, checked picks and locations, uncertainty and geometry tests,
validated detections, and a report whose figures and numbers can be regenerated. Show poorly resolved cases and
failed tests alongside successful ones. Compare what Suncheon and [Sangju](sangju_project.md) allow you to infer,
including differences in station coverage, observing time and detector sensitivity. A conclusion that the data
cannot distinguish two explanations is useful when the report shows why and identifies the observation needed next.
