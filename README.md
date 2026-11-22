# SGTL earthquake source tutorial

Learn to work with earthquake catalogs and seismic records, then locate earthquakes and study their sources.
This course is for a new intern: each notebook explains the idea, gives you a small method to write, and checks
your work before you use real Korean data. **Version 1.0.0 · 20 lessons · about 8 weeks, followed by a project.**

## Start here

1. **First visit:** follow the [setup guide](docs/setup.md) ([한국어 설치 안내](docs/setup_ko.md)). It takes you from
   your laptop to JupyterLab on the lab server, with the commands and expected results at every step.
2. **Ready to learn:** open [Start here](docs/index.md) and [M00: your first lesson](docs/notebooks/M00_start_here/M00_start_here.ipynb).
3. **Returning:** choose your lesson below. To work on it, run `bin/sgtl new MXX` in your server terminal, then open
   the copy in `work/` in JupyterLab. The notebook links here are for reading; GitHub does not run their cells.

**한국어:** [시작 안내](docs/setup_ko.md) → [진행 방식](docs/how_this_tutorial_works_ko.md). 과제마다
**예측 → 코드 작성 → 점검 → 설명** 순서로 진행합니다. 막히면 첫 번째 힌트와 [도움말](docs/troubleshooting.md)을 보세요.

## Lessons

Follow the order in this table; module numbers are labels. [Full lesson guide](docs/notebooks/README.md) ·
[Software and data needed before each module](docs/how_this_tutorial_works.md#before-each-module).

| Week | Open your notebook | You will learn to… |
|---|---|---|
| 1 | [M00 · Start here](docs/notebooks/M00_start_here/M00_start_here.ipynb) | use the server, JupyterLab and your private GitHub copy |
| 1 | [M01 · Python and catalogs](docs/notebooks/M01_python_catalogs/M01_python_catalogs.ipynb) | read a table and write small Python functions |
| 1 | [M02 · Figures and maps](docs/notebooks/M02_figures_maps/M02_figures_maps.ipynb) | show your data clearly |
| 1 | [M04 · Earthquake catalogs](docs/notebooks/M04_earthquake_catalogs/M04_earthquake_catalogs.ipynb) | compare catalogs and understand their limits |
| 2 | [M05 · Statistical seismology](docs/notebooks/M05_statistical_seismology/M05_statistical_seismology.ipynb) | measure earthquake rates and magnitude distributions |
| 2 | [M03 · Getting seismic data](docs/notebooks/M03_getting_data/M03_getting_data.ipynb) | download records and understand instrument responses |
| 2 | [M10 · Seismograms](docs/notebooks/M10_seismograms/M10_seismograms.ipynb) | filter, inspect and measure a seismic record |
| 3 | [M20 · Picking arrivals](docs/notebooks/M20_picking/M20_picking.ipynb) | mark when P and S waves arrive |
| 3 | [M21 · Deep-learning pickers](docs/notebooks/M21_dl_pickers/M21_dl_pickers.ipynb) | compare automatic picks with your own |
| 3 | [M30 · Travel times](docs/notebooks/M30_travel_times/M30_travel_times.ipynb) | predict how long a wave takes to reach a station |
| 3, optional | [M22 · Detection](docs/notebooks/M22_detection/M22_detection.ipynb) | find earthquakes in a longer record; take after M30 |
| 4 | [M31 · Earthquake location](docs/notebooks/M31_location/M31_location.ipynb) | estimate an earthquake's position and uncertainty |
| 4 | [M32 · A production locator](docs/notebooks/M32_hypoinverse/M32_hypoinverse.ipynb) | run HYPOINVERSE through PocketQuake and audit its results |
| 5 | [M41 · Relative relocation](docs/notebooks/M41_relative_relocation/M41_relative_relocation.ipynb) | resolve the relative positions of nearby earthquakes |
| 6 | [M50 · The focal sphere](docs/notebooks/M50_focal_sphere/M50_focal_sphere.ipynb) | describe fault motion and first motions |
| 6 | [M51 · First-motion mechanisms](docs/notebooks/M51_first_motions/M51_first_motions.ipynb) | infer a mechanism and compare it with SKHASH |
| 6 | [M52 · Synthetic seismograms](docs/notebooks/M52_synthetics/M52_synthetics.ipynb) | predict a record from a source model |
| 7 | [M53 · Moment tensor inversion](docs/notebooks/M53_mt_inversion/M53_mt_inversion.ipynb) | fit source models and judge what the records resolve |
| 7 | [M54 · Coulomb stress](docs/notebooks/M54_coulomb/M54_coulomb.ipynb) | test stress changes and their limits |
| 8 | [M60 · Full run and project plan](docs/notebooks/M60_full_run/M60_full_run.ipynb) | analyze a new sequence and prepare your research plan |
| 9–13 | [Your Suncheon project](docs/project.md) | investigate depths, fault geometry and mechanisms; present your findings |

## When you need help

- **A command or notebook does not work:** [troubleshooting](docs/troubleshooting.md).
- **A term is unfamiliar:** [glossary](docs/glossary.md) and [reading list](docs/reading_list.md).
- **Saving or submitting work:** [Git workflow](docs/git_workflow.md) and [how the course works](docs/how_this_tutorial_works.md).
- **Course expectations:** [AI as a tutor](docs/ai_policy.md), [sharing the server](docs/server_manners.md),
  [data policy](docs/data_policy.md), and the [full curriculum](docs/curriculum.md).

## Find your way around the files

| Folder or file | What it contains |
|---|---|
| [docs/](docs/index.md) | start guide, notebooks, help, readings and project templates |
| [bin/](bin/) | the course commands used in the guides |
| [data/](data/) | small public catalogs, dataset descriptions and velocity models |
| [install/](install/) | software installation recipes |
| [src/](src/) | supporting Python package |
| [environment.yml](environment.yml), [pyproject.toml](pyproject.toml) | the software environment and package description |

Your own `work/` and `project/` folders appear as you start the lessons; downloads live under `~/sgtl/data/`.

Created by **Minseong Seo, SGTL, Seoul National University**. [Credits and data attribution](docs/credits.md) ·
[Authors](AUTHORS.md) · [Cite this course](CITATION.cff) · [Release notes](CHANGELOG.md).
Code: [MIT](LICENSE). Text and figures: [CC BY 4.0](LICENSE-CONTENT.md). Data retain their source licenses.
