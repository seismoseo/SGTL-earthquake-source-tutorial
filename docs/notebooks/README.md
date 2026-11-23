# Lesson guide

Start at the top and follow this order. Module numbers are labels; for example, M04 comes before M03. In weeks 3–4,
M22 follows M30 because its event associator needs your travel-time function. Its seven core tasks provide the
required template-matching and validation preparation for both research tracks.

To work on a lesson, run `bin/sgtl new MXX` from `~/sgtl/tutorial` in a server terminal. Open the notebook copied to
`work/MXX_name/` in JupyterLab, choose **SGTL (Python 3.12)**, then read and run it in order. The links below let you
read the original lesson. For a first visit, use the [setup guide](../setup.md) ([한국어](../setup_ko.md)).

| Week | Lesson | What to have ready |
|---|---|---|
| 1 | [M00 · Start here](M00_start_here/M00_start_here.ipynb) | your server account; setup guide |
| 1 | [M01 · Python for earthquake catalogs](M01_python_catalogs/M01_python_catalogs.ipynb) | M00; the catalog comes with the course |
| 1 | [M02 · Figures and maps](M02_figures_maps/M02_figures_maps.ipynb) | M01 |
| 1 | [M04 · Earthquake catalogs](M04_earthquake_catalogs/M04_earthquake_catalogs.ipynb) | M01–M02 |
| 2 | [M05 · Statistical seismology](M05_statistical_seismology/M05_statistical_seismology.ipynb) | M01, M02 and M04 |
| 2 | [M03 · Getting seismic data](M03_getting_data/M03_getting_data.ipynb) | M01, M02 and M04; personal STP access, tools and station metadata |
| 2 | [M10 · Seismograms](M10_seismograms/M10_seismograms.ipynb) | M03; your verified `sangju2019` download |
| 3 | [M20 · Picking arrivals](M20_picking/M20_picking.ipynb) | M10; the Sangju records and station metadata |
| 3 | [M21 · Deep-learning pickers](M21_dl_pickers/M21_dl_pickers.ipynb) | M20 manual picks; PhaseNet weights and PocketQuake |
| 3 | [M30 · Travel times in a layered crust](M30_travel_times/M30_travel_times.ipynb) | M10 and M20; your manual picks |
| 3–4 | [M22 · Detection and template matching](M22_detection/M22_detection.ipynb) | M20, M21 and M30; `sangju2019_hours` |
| 4 | [M31 · Earthquake location](M31_location/M31_location.ipynb) | M20 and M30 functions and manual picks |
| 4 | [M32 · HYPOINVERSE via PocketQuake](M32_hypoinverse/M32_hypoinverse.ipynb) | M21 cluster and M31 location table |
| 5 | [M41 · Relative relocation](M41_relative_relocation/M41_relative_relocation.ipynb) | M32 locations and cluster; M30 travel-time functions |
| 6 | [M50 · The focal sphere](M50_focal_sphere/M50_focal_sphere.ipynb) | M20 first motions, M30 functions and M31 locations; [printable net](../figures/equal_area_net.pdf) |
| 6 | [M51 · Mechanisms from first motions](M51_first_motions/M51_first_motions.ipynb) | M50 functions; the M21/M32 cluster |
| 6 | [M52 · Synthetic seismograms](M52_synthetics/M52_synthetics.ipynb) | M10, M41 and M50; PyFK worker environment |
| 7 | [M53 · Moment tensor inversion](M53_mt_inversion/M53_mt_inversion.ipynb) | M51/M52 functions, manual picks and SKHASH results; MTUQ |
| 7 | [M54 · Coulomb stress change](M54_coulomb/M54_coulomb.ipynb) | M04, M50 and M52; Elastic_stresses_py |
| 8 | [M60 · Full run and project plan](M60_full_run/M60_full_run.ipynb) | earlier methods; `gokseong2018`; your project templates |
| 9–16 | [Suncheon](../project.md) and [independent Sangju](../sangju_project.md), both required | separate signed plans/data requests, validated template matching and two reports |

[Preparation commands and exact result-file paths](../how_this_tutorial_works.md#before-each-module) explain each
handoff. Read each notebook's header for its full prerequisites and reading. When a file is missing, return to the
named module and finish that output; the notebooks do not share kernel variables.

Before moving on, save your notebook, complete its core checks and explanations, update the AI log, and
[submit it for review](../how_this_tutorial_works.md#submitting-a-module-sgtl-submit). Use `--include-optional` when
including stretch/research work. The [full curriculum](../curriculum.md) describes weekly gates, optional explorers
and the project schedule.

M22 has seven core tasks and uses the normal submission command.
