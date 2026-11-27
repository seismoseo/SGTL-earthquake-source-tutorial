# Start here

Welcome to the SGTL earthquake source tutorial. You learn Python and seismology in a sequence of notebooks, then
use those methods in your own research projects. You do not need to understand the repository's software folders
to begin.

## Your first day

1. Ask your mentor for your server account and the server address. Have your laptop ready.
2. Follow the [setup guide](setup.md) ([한국어 설치 안내](setup_ko.md)). It shows which commands go in the server
   terminal and which in the laptop tunnel terminal; keep the two apart.
3. On the server, run `bin/sgtl new M00`. Open `work/M00_start_here/M00_start_here.ipynb` in JupyterLab with the
   **SGTL (Python 3.12)** kernel.
4. Work through [M00 · Start here](notebooks/M00_start_here/M00_start_here.ipynb), including your private GitHub
   copy. Then read [how the course works](how_this_tutorial_works.md) ([한국어](how_this_tutorial_works_ko.md)) and
   go on to M01 with the [lesson guide](notebooks/README.md).

Run the lessons in JupyterLab on the lab server: the notebook links on GitHub show a lesson but do not run Python.
`bin/sgtl new MXX` copies a lesson into your `work/` folder once and keeps any existing work.

## The plan

Weeks 1-8 are twenty lessons, from Python and catalogs to earthquake locations and sources
([curriculum](curriculum.md)). Weeks 9-16 are the Suncheon and Sangju research projects, both required
([projects](project.md)). Plan for about 35-40 hours a week; you and your mentor adjust the pace.

Keep your notebooks and logs in `work/` and your research files in `project/`. Software and waveform data live
outside the repository, under `~/sgtl/`. Leave the original lessons in `docs/notebooks/` as they are, so updates can
replace them safely.

## Find help

| You need… | Open… |
|---|---|
| A fix for an error or a connection problem | [Troubleshooting](troubleshooting.md) |
| The meaning of a term | [English–Korean glossary](glossary.md) |
| What to read before a lesson | [Reading list](reading_list.md) |
| How to save, update or submit work | [Git workflow](git_workflow.md) |
| How to use an AI tutor | [AI policy](ai_policy.md) ([한국어](ai_policy_ko.md)) |
| How to share the server and handle data | [Server manners](server_manners.md), [data policy](data_policy.md) |

Created by Minseong Seo (SGTL, Seoul National University). [Credits, licenses and citation](credits.md).
