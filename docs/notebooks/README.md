# Lesson guide

Follow this order. Module numbers are labels: M04 comes before M03, and M22 follows M30 because its event
associator uses your travel-time function.

To start a lesson, run `bin/sgtl new MXX` in a server terminal, in `~/sgtl/tutorial`. Open the copy in
`work/MXX_name/` in JupyterLab with the **SGTL (Python 3.12)** kernel and run it from the top. The links below show
the original lessons. First visit: the [setup guide](../setup.md) ([한국어](../setup_ko.md)).

The last column says what to finish or run first. Install and fetch commands are dry runs: read the plan, then repeat
the command with `--apply`, one at a time. `doctor`, `pq check` and `data verify` only look and need no `--apply`.

| Week | Lesson | Before you start |
|---|---|---|
| 1 | [M00 · Start here](M00_start_here/M00_start_here.ipynb) | your server account and the setup guide |
| 1 | [M01 · Python and catalogs](M01_python_catalogs/M01_python_catalogs.ipynb) | M00 |
| 1 | [M02 · Figures and maps](M02_figures_maps/M02_figures_maps.ipynb) | M01 |
| 1 | [M04 · Earthquake catalogs](M04_earthquake_catalogs/M04_earthquake_catalogs.ipynb) | M01, M02 |
| 2 | [M05 · Statistical seismology](M05_statistical_seismology/M05_statistical_seismology.ipynb) | M04 |
| 2 | [M03 · Getting seismic data](M03_getting_data/M03_getting_data.ipynb) | M04; `bin/sgtl-install tools metadata`; your STP client and credentials in `~/.sgtl/` as M03 Part 1 shows; `bin/sgtl data fetch sangju2019`. Check: `bin/sgtl pq check`, `bin/sgtl data verify sangju2019` |
| 2-3 | [SeisComP GUI workshop](../seiscomp_gui.md) | your first M03 download |
| 2 | [M10 · Seismograms](M10_seismograms/M10_seismograms.ipynb) | M03 |
| 3 | [M20 · Picking arrivals](M20_picking/M20_picking.ipynb) | M10; the SeisComP workshop (or the notebook picker E2) |
| 3 | [M21 · Deep-learning pickers](M21_dl_pickers/M21_dl_pickers.ipynb) | your M20 picks; the M03 tools; `bin/sgtl-install seisbench`. Check: `bin/sgtl doctor` reports the PhaseNet weights |
| 3 | [M30 · Travel times](M30_travel_times/M30_travel_times.ipynb) | M10, your M20 picks; the hand exercise NMSOP-2 EX 11.1 |
| 3-4 | [M22 · Detection and template matching](M22_detection/M22_detection.ipynb) | M20, M21, M30; `bin/sgtl data fetch sangju2019_hours`. Check: `bin/sgtl data verify sangju2019_hours` |
| 4 | [M31 · Earthquake location](M31_location/M31_location.ipynb) | your M20 picks and M30 functions |
| 4 | [M32 · HYPOINVERSE](M32_hypoinverse/M32_hypoinverse.ipynb) | your M21 cluster; `work/M31_location/results/M31_hypoinverse_runs.csv` (M31, task 6) |
| 5 | [M41 · Relative relocation](M41_relative_relocation/M41_relative_relocation.ipynb) | the cluster `sangju_m21` after M32; M30 functions |
| 6 | [M50 · The focal sphere](M50_focal_sphere/M50_focal_sphere.ipynb) | M20 first motions, M30, M31; NMSOP-2 EX 3.2 and EX 3.3 on the [printable net](../figures/equal_area_net.pdf) |
| 6 | [M51 · First-motion mechanisms](M51_first_motions/M51_first_motions.ipynb) | M50; the `sangju_m21` cluster |
| 6 | [M52 · Synthetic seismograms](M52_synthetics/M52_synthetics.ipynb) | M10, M41, M50; `bin/sgtl-install pyfk` |
| 7 | [M53 · Moment tensor inversion](M53_mt_inversion/M53_mt_inversion.ipynb) | M51, M52; `work/M51_first_motions/results/M51_skhash_first/mechanisms.csv` (M51, task 5); `bin/sgtl-install mt` |
| 7 | [M54 · Coulomb stress](M54_coulomb/M54_coulomb.ipynb) | M04, M50, M52; `bin/sgtl-install coulomb`; internet on the first run |
| 8 | [M60 · Full run and project plan](M60_full_run/M60_full_run.ipynb) | `bin/sgtl data fetch gokseong2018`. Check: `bin/sgtl data verify gokseong2018` |
| 9-16 | [Suncheon](../suncheon_project.md) and [Sangju](../sangju_project.md), both required | the [project overview](../project.md) |

Your M20 picks, `work/picks/M20_manual_picks.csv`, feed M21, M22, M30, M31, M50 and M53. Keep the names and folders
that `sgtl new` creates; if yours differ, change them in the parameters cell. If a file is missing, finish the named
lesson: never replace it with an invented file. A fetch that reports STOP needs its prerequisite fixed first.

Before you move on, [save and submit](../how_this_tutorial_works.md#save-and-submit) the lesson.
