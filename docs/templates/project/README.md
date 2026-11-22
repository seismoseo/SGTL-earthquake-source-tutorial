# Your research project: the Suncheon earthquakes

`sgtl new project` copied these files from `docs/templates/project/` of the tutorial into `project/` once. They are
yours now: the tutorial never overwrites them, and the pre-commit hook lets you commit anything inside `project/`.
Each template only asks questions; the answers, the numbers and the decisions are yours.

| file | what it is for | when |
|---|---|---|
| `ANALYSIS_PLAN.md` | your questions, the two hypotheses you write from the questions it names (with their sources), how you will test them, what would change your conclusion, what you have already seen, your mentor's sign-off, and every later change (dated) | written in week 8 (module M60), signed off by your mentor and frozen at the end of week 8 |
| `criteria.yaml` | the numbers that decide each test, written before you look at any result | frozen with the plan; its MD5 checksum goes into the plan and the lab book |
| `claims.csv` | the claims of the published Suncheon study (Kwak et al. 2022) as statements you can test; `where` names the section, figure, table or page, or `abstract` for a claim read only in the abstract (check it against the full paper before you test it) | week 8 (module M60, task 6) |
| `LABBOOK.md` | a dated diary: what you ran, with which settings, what came out, what surprised you | every working day |
| `REPORT.md` | the written report, with a Korean summary at the top | weeks 12-13 |
| `TALK_OUTLINE.md` | the outline of your 15-minute lab talk | week 13 |

Module M60 writes your data inventory into `inventory/` (task 5).

Rules that do not change during the project (they are the lab's, and the tutorial's):

- Freeze `criteria.yaml` before you look at results, after your mentor has read the plan and written the sign-off
  line (name and day) into `ANALYSIS_PLAN.md`. A later change is allowed, but only as a dated amendment in
  `ANALYSIS_PLAN.md` that says what changed, why, and whether you had seen results before the change.
- Locate with direct P and S within about 100 km, never with the Moho head waves Pn or Sn. Whether a station's
  first arrival is the direct wave depends on its distance and on the source depth: before you choose the stations,
  compute the crossover distance per phase (P and S) for your deepest event in your velocity model, for every
  boundary below the source (module M30, task 2), and write the numbers into section 4 of the plan. Keep the
  direct-wave baseline inside the relevant crossover distances as well as the distance limit. HYPOINVERSE's
  layered model predicts the first arrival (module M32), which can be a head wave along a boundary inside the
  crust even within 100 km. Identify those stations explicitly and record their treatment in the signed plan;
  compare any such production-tool result separately with the direct-wave baseline. Pn and Sn remain excluded.
- Picks that feed a focal mechanism need a first-motion polarity read from the counts (a negative gain in the station
  metadata is not a polarity flag).
- A zero-phase (two-pass) filter can put energy before the true onset and move automatic picks early. Measure the
  timing effect with your own picker and filter settings, as in M20.
- Every number in the report comes from a notebook or script in this folder or in `work/` that prints it.
- Shared-server manners: at most 4 cores, thread caps, `nice`, one heavy run at a time, memory below 16 GB.
- Acknowledge the station metadata of Byeong-Seok Ahn (Pukyong National University) whenever you use instrument
  responses, and the KMA catalog (KOGL Type 1) whenever you use its events.

Credit for the templates: Minseong Seo (SGTL, Seoul National University). CC BY 4.0.
