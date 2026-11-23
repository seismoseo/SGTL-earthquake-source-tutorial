# Start here

Welcome to the SGTL earthquake source tutorial. You will learn Python and seismology by working through a sequence
of notebooks, then use those methods in your own earthquake research project. You do not need to understand the
repository's software folders to begin.

## Your first day

1. Ask your mentor for your server account and server address. Have your laptop ready.
2. Follow [Setup: from your laptop to the first notebook](setup.md), or [한국어 설치 안내](setup_ko.md). Keep the
   server terminal and laptop tunnel terminal separate; the guide shows which one each command belongs in.
3. Open [M00 · Start here](notebooks/M00_start_here/M00_start_here.ipynb). On the server, `bin/sgtl new M00` creates
   your working copy; open `work/M00_start_here/M00_start_here.ipynb` in JupyterLab with the **SGTL (Python 3.12)** kernel.
4. Work through M00, including making your private GitHub copy. Then read [how the course works](how_this_tutorial_works.md)
   ([한국어](how_this_tutorial_works_ko.md)) and continue to M01.

The notebook links on GitHub show the lesson; they do not execute Python. Run the lessons in JupyterLab on the lab
server. Each `bin/sgtl new MXX` command copies a lesson into your `work/` folder once and keeps any existing work.

## Your route through the course

| When | Focus | Start with |
|---|---|---|
| Weeks 1–2 | Python, figures, catalogs, data and seismic records | [M00](notebooks/M00_start_here/M00_start_here.ipynb), then the [lesson guide](notebooks/README.md) |
| Weeks 3–5 | Arrival picks, travel times, location and relative relocation | [M20](notebooks/M20_picking/M20_picking.ipynb) |
| Weeks 6–7 | Fault motion, synthetic records, moment tensors and stress | [M50](notebooks/M50_focal_sphere/M50_focal_sphere.ipynb) |
| Week 8 | A full analysis on a new sequence and a signed research plan | [M60](notebooks/M60_full_run/M60_full_run.ipynb) |
| Weeks 9–16 | Two required tracks: Suncheon and independent Sangju, with validated template matching | [Project overview](project.md), [Sangju guide](sangju_project.md) |

Plan for about 35–40 hours a week; you and your mentor adjust the pace from your progress. The
[lesson guide](notebooks/README.md) gives the exact order. Before each module, check its
[software, data and earlier-result requirements](how_this_tutorial_works.md#before-each-module). Stretch tasks and
optional explorers can wait until core work is complete.

M22 and template matching in both research tracks are required; agree on phased data volumes and extend the
project schedule when needed.

## What you do in a lesson

For each task, **predict → write your code → run the check → explain what happened**. Keep your predictions and
explanations in your own words. Use the first built-in hint when you are stuck, then test a small example you can
work out by hand. Your mentor reviews your saved notebook and record; [submission instructions](how_this_tutorial_works.md#submitting-a-module-sgtl-submit)
explain how to hand it in.

Keep your own notebooks and logs in `work/`, and your research files in `project/`. Software and waveform data live
outside the repository under `~/sgtl/`; the setup guide and M03 show the paths. Keep the original lessons in
`docs/notebooks/` as they are so updates can replace them safely.

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
