# Curriculum

About 35-40 hours per week, including about 2 hours of reading. All times are estimates; the plan is adjusted after
week 1 from your recorded progress, and again after the gates of weeks 3 and 5. If the pace is slow, M22, the
interactive explorers and stretch items are dropped first. Required reading for each module is listed in its header;
the full list is in [reading_list.md](reading_list.md). Gates are explained in
[how_this_tutorial_works.md](how_this_tutorial_works.md).

**Explorers** (E1-E10) are optional interactive widgets for building intuition: you move a slider and watch a
filter, a trigger, a misfit landscape or a beachball change.

## Part 0 and 1: tools, catalogs and statistics (weeks 1-2)

| Week | Module | You will be able to | Data | Tools |
|---|---|---|---|---|
| 1 | **M00** Start here | use the shared server politely; open the SSH tunnel and JupyterLab; commit and push to your private copy; install the course software | none | bash, git, gh, tmux, JupyterLab |
| 1 | **M01** Python for earthquake catalogs | load and filter a catalog with pandas; write small, tested functions; compute great-circle distances | KMA catalog subset (in the repository) | Python, pandas, NumPy |
| 1 | **M02** Figures and maps | make clear figures in the house style; draw PyGMT maps with a scale bar and magnitude-scaled symbols | KMA catalog subset | Matplotlib, PyGMT |
| 1 | **M04** Earthquake catalogs | read the KMA catalog and convert KST to UTC; clean it; select a sequence; plot magnitude-frequency counts; know the catalog's precision; judge completeness by eye; compare KMA with ISC and ComCat | KMA subset; USGS ComCat and ISC (public) | pandas, ObsPy FDSN client, PyGMT; explorer E9 |
| 2 | **M05** Statistical seismology | estimate the b-value and its uncertainty with the bin-width correction; estimate the magnitude of completeness; fit Omori-Utsu aftershock decay by maximum likelihood; decluster a catalog; compare with SeismoStats and synthetic truth | Gyeongju 2016, Pohang 2017, Ridgecrest 2019, nationwide KMA catalog | NumPy, SciPy, SeismoStats (as a reference); research tier: nearest-neighbor clustering, ETAS |
| 2 | **M03** Getting waveforms | fetch waveforms with your own STP account; attach station metadata and instrument responses | Sangju 2019 sequence (fetched by you) | STP client, ObsPy, StationMetadata |
| 2 | **M10** Seismograms | tell counts from ground motion; remove the instrument response; filter; rotate to radial and transverse | Sangju 2019 | ObsPy; explorer E1 (filter bench) |

## Part 2: picking, detection, travel times and location (weeks 3-5)

| Week | Module | You will be able to | Data | Tools |
|---|---|---|---|---|
| 3 | **M20** Picking and triggers | pick P and S by hand with polarities; write an STA/LTA trigger and tune it | Sangju 2019; one practice day of continuous data | ObsPy (as a reference); explorers E2 (picker), E3 (trigger) |
| 3 | **M21** Deep-learning pickers | run PhaseNet-type pickers; compare their picks and polarities with yours | Sangju 2019 | SeisBench, EQNet / PhaseNet+ |
| 3 | **M22** Detection (stretch) | explain association and template matching; find small events in continuous data | continuous data | cross-correlation, PyOcto |
| 3 | **M30** Travel times | compute direct-wave travel times in layered models; use the Wadati diagram; know head waves as a concept (never used to locate) | kim1983 and kim2011 velocity models | NumPy, ObsPy TauP (as a reference); explorer E4; hand exercise NMSOP-2 EX 11.1 first (exercise 11.1 of the *New Manual of Seismological Observatory Practice*, 2nd edition) |
| 4 | **M31** Earthquake location | locate by grid search and by Geiger's method with direct P and S within about 100 km; estimate uncertainty | Sangju 2019 picks | NumPy; explorer E5 (misfit landscape) |
| 4 | **M32** HYPOINVERSE via PocketQuake | run a production locator; rerun it unchanged, then change one setting and explain | Sangju 2019 | PocketQuake, HYPOINVERSE |
| 5 | **M41** Relative relocation | build differential times from the catalog and from cross-correlation; set up and solve the double-difference system; bootstrap the result; run HypoDD | Sangju 2019 | NumPy, SciPy, PocketQuake, HypoDD; explorers E6 (lag and cycle skipping), E7 (DD toy) |

## Part 3: the source (weeks 6-7)

| Week | Module | You will be able to | Data | Tools |
|---|---|---|---|---|
| 6 | **M50** The focal sphere | describe a fault by strike, dip and rake; plot rays on the focal sphere; draw beachballs; find nodal planes | synthetic; hand exercises NMSOP-2 EX 3.2 and EX 3.3 on printed stereonets | ObsPy, Matplotlib; explorer E8 (beachball fitter) |
| 6 | **M51** Mechanisms from polarities | find mechanisms by grid search over polarities; run SKHASH; avoid the S/P ratio trap | Sangju 2019; a published KIGAM mechanism for comparison | SKHASH |
| 6 | **M52** Synthetic seismograms | build a moment tensor from strike, dip and rake; convert M0 and Mw; predict radiation; compute whole-space point-source synthetics and check them against PyFK; compare layered-model synthetics with response-corrected data | synthetic; Sangju 2019 | PyFK (separate small environment), ObsPy |
| 7 | **M53** Moment tensor inversion | recover a known moment tensor by least squares with noise and gaps; see what norms and time shifts do; measure Kagan angles and lune coordinates; run an MTUQ search for a real event and say when a result is not resolved | synthetic; Sangju 2019 | NumPy, MTUQ |
| 7 | **M54** Coulomb stress change | compute and resolve Coulomb stress changes on synthetic faults; judge when a stress change is too small to matter; test a published Gyeongju 2016 fault model against its aftershocks with a randomized null test; check sensitivity to friction and the Skempton coefficient | synthetic; Sangju 2019; Gyeongju 2016 | Elastic_stresses_py, pyrocko, cutde; explorer E10 (Coulomb lobes) |

## Part 4: putting it together and the project (weeks 8-13)

| Week | Step | What happens |
|---|---|---|
| 8 | **M60** Full run and project plan | Run the whole chain, with a preflight check, on a new sequence (Gokseong). Write your project plan and data inventory for the Suncheon microearthquake sequence, starting from a table of the claims in Kwak et al. (2022). The plan is frozen at the end of the week. |
| 9-10 | Project: depths | How deep are the Suncheon earthquakes, and how sure can we be? |
| 11-12 | Project: geometry and mechanisms | Fault geometry from relocated events; focal mechanisms (SKHASH; a moment tensor attempt on the largest events, where "not resolved" is an acceptable answer). |
| 13 | Report and defense | Written report, a 15-minute lab talk and an oral defense. |
| 14+ | Beyond | Optional: detection and template matching, stress interactions, a manuscript. |

## Gates

| End of week | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 13 |
|---|---|---|---|---|---|---|---|---|---|
| Gate | G0 | G1 | G2 (plan check) | G3 | G4 (plan check) | G5 | G6 | plan frozen | final |
