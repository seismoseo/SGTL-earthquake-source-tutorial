# SGTL earthquake source tutorial

Learn to work with earthquake catalogs and seismic records, then locate earthquakes and study their sources. The
course is for a new intern. Each notebook shows an idea, gives you a small method to write and checks your work
before you use real Korean data. **Version 1.4.0 · 20 lessons · about 8 weeks, then the Suncheon and Sangju research
projects.**

## Start here

1. **First visit:** follow the [setup guide](docs/setup.md) ([한국어 설치 안내](docs/setup_ko.md)), from your laptop
   to JupyterLab on the lab server.
2. **Ready to learn:** open [Start here](docs/index.md) and [M00, your first lesson](docs/notebooks/M00_start_here/M00_start_here.ipynb).
3. **Returning:** run `bin/sgtl new MXX` in your server terminal and open the copy in `work/` in JupyterLab. The
   notebook links below are for reading: GitHub does not run their cells.

**한국어:** [설치 안내](docs/setup_ko.md) → [진행 방식](docs/how_this_tutorial_works_ko.md). 과제마다
**예측 → 코드 작성 → 점검 → 설명** 순서로 진행합니다. 막히면 첫 번째 힌트와 [도움말](docs/troubleshooting.md)을 보세요.

## Lessons

Follow this order; module numbers are labels. The [lesson guide](docs/notebooks/README.md) says what to prepare for
each lesson, and the [curriculum](docs/curriculum.md) what each one teaches.

| Week | Lessons |
|---|---|
| 1 | [M00 · Start here](docs/notebooks/M00_start_here/M00_start_here.ipynb) · [M01 · Python and catalogs](docs/notebooks/M01_python_catalogs/M01_python_catalogs.ipynb) · [M02 · Figures and maps](docs/notebooks/M02_figures_maps/M02_figures_maps.ipynb) · [M04 · Earthquake catalogs](docs/notebooks/M04_earthquake_catalogs/M04_earthquake_catalogs.ipynb) |
| 2 | [M05 · Statistical seismology](docs/notebooks/M05_statistical_seismology/M05_statistical_seismology.ipynb) · [M03 · Getting seismic data](docs/notebooks/M03_getting_data/M03_getting_data.ipynb) · [SeisComP GUI workshop](docs/seiscomp_gui.md) · [M10 · Seismograms](docs/notebooks/M10_seismograms/M10_seismograms.ipynb) |
| 3-4 | [M20 · Picking arrivals](docs/notebooks/M20_picking/M20_picking.ipynb) · [M21 · Deep-learning pickers](docs/notebooks/M21_dl_pickers/M21_dl_pickers.ipynb) · [M30 · Travel times](docs/notebooks/M30_travel_times/M30_travel_times.ipynb) · [M22 · Detection and template matching](docs/notebooks/M22_detection/M22_detection.ipynb) (required for both projects) · [M31 · Earthquake location](docs/notebooks/M31_location/M31_location.ipynb) · [M32 · HYPOINVERSE](docs/notebooks/M32_hypoinverse/M32_hypoinverse.ipynb) |
| 5 | [M41 · Relative relocation](docs/notebooks/M41_relative_relocation/M41_relative_relocation.ipynb) |
| 6 | [M50 · The focal sphere](docs/notebooks/M50_focal_sphere/M50_focal_sphere.ipynb) · [M51 · First-motion mechanisms](docs/notebooks/M51_first_motions/M51_first_motions.ipynb) · [M52 · Synthetic seismograms](docs/notebooks/M52_synthetics/M52_synthetics.ipynb) |
| 7 | [M53 · Moment tensor inversion](docs/notebooks/M53_mt_inversion/M53_mt_inversion.ipynb) · [M54 · Coulomb stress](docs/notebooks/M54_coulomb/M54_coulomb.ipynb) |
| 8 | [M60 · Full run and project plan](docs/notebooks/M60_full_run/M60_full_run.ipynb) |
| 9-16 | [Suncheon](docs/suncheon_project.md) and [Sangju](docs/sangju_project.md) research projects, both required: depths, geometry, activity and detector limits, in two reports |

## Help

[Troubleshooting](docs/troubleshooting.md) · [glossary](docs/glossary.md) · [reading list](docs/reading_list.md) ·
[how the course works](docs/how_this_tutorial_works.md) · [Git workflow](docs/git_workflow.md) ·
[AI as a tutor](docs/ai_policy.md) · [sharing the server](docs/server_manners.md) · [data policy](docs/data_policy.md)

## Files

- [docs/](docs/index.md): guides, notebooks, readings and project templates
- [bin/](bin/): the course commands
- [data/](data/): small public catalogs, dataset descriptions and velocity models
- [install/](install/): installation recipes
- [src/](src/): the supporting Python package
- [environment.yml](environment.yml), [pyproject.toml](pyproject.toml): the software environment and package description

Your `work/` and `project/` folders appear as you start the lessons; downloads go under `~/sgtl/data/`.

Created by **Minseong Seo, SGTL, Seoul National University**. [Credits and data attribution](docs/credits.md) ·
[Authors](AUTHORS.md) · [Cite this course](CITATION.cff) · [Release notes](CHANGELOG.md).
Code: [MIT](LICENSE). Text and figures: [CC BY 4.0](LICENSE-CONTENT.md). Data retain their source licenses.
