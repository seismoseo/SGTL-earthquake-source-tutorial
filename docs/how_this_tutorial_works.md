# How this tutorial works

한국어: [how_this_tutorial_works_ko.md](how_this_tutorial_works_ko.md)

## Modules

The course is a series of **modules** (M00, M01, ... M60; see [curriculum.md](curriculum.md)). Each module is
one Jupyter notebook. `bin/sgtl new MXX` copies it once into `work/MXX_slug/`; you work only in that copy. The
originals in `docs/notebooks/` belong to the tutorial and are replaced by updates.

Every notebook starts the same way. The header lists the goals, the expected time and what to read first. Then:

1. the **parameters** cell, the only place for values you may change (file names, frequencies, seeds);
2. the **setup** cell: `import sgtl_tutorial as st` and `S = st.init("MXX")`. It caps threads and memory so you
   share the server fairly, sets the figure style and prints a short environment report.

Most methods are taught in three rungs: **(1)** write the core function on synthetic data where the true answer
is known; **(2)** apply it to real Korean data and compare with an independent reference (KMA, KIGAM, USGS, or
your own tool results); **(3)** run the production tool, first unchanged (to see run-to-run noise), then with one
parameter changed, and explain the difference. Some steps are done **by hand first**: the epicenter exercise
NMSOP-2 EX 11.1 before M30, and the fault-plane exercises EX 3.2 and EX 3.3 on printed stereonets before M50.
NMSOP-2 is the *New Manual of Seismological Observatory Practice*, 2nd edition (Bormann, 2012), a free online
handbook for seismologists; EX 11.1 is its exercise 11.1 (see [reading_list.md](reading_list.md)).

## Before each module

Follow the [curriculum](curriculum.md), rather than sorting module numbers. Start with M00 → M01 → M02 → M04,
then M05 → M03 → M10. In weeks 3–4, continue M20 → M21 → M30 → M22; M22 is required preparation for both research tracks. Read the next notebook's header
before starting its first task: it names the modules, readings and data you need.

The first-day installer installs the environment only. Run the commands below in a **server terminal**, from
`~/sgtl/tutorial`. The commands in the table are dry runs: read their plans, then repeat with `--apply` when you
are ready. Installation and downloads can take several minutes; do one at a time.

| Before | Extra preparation | How to check |
|---|---|---|
| M03 real-data work | `bin/sgtl-install tools metadata`; then put your personal STP client and credentials in `~/.sgtl/` exactly as M03 Part 1 shows; `bin/sgtl data fetch sangju2019` | `bin/sgtl pq check` and `bin/sgtl data verify sangju2019` |
| M21 | `bin/sgtl-install seisbench` (two pretrained PhaseNet models); keep the tools installed for M03 | `bin/sgtl doctor` reports the PhaseNet weights |
| M22 | `bin/sgtl data fetch sangju2019_hours` | `bin/sgtl data verify sangju2019_hours` |
| M52 | `bin/sgtl-install pyfk` (its separate worker environment) | the notebook's PyFK environment check |
| M53 | `bin/sgtl-install mt`; finish M52 and M51 first | the notebook's imports and prerequisite-file checks |
| M54 | `bin/sgtl-install coulomb`; internet access for the public Gyeongju mechanisms on the first run | the notebook's tool checks; later reruns use its saved mechanism file |
| M60 | `bin/sgtl data fetch gokseong2018`; `bin/sgtl new project` copies templates immediately | `bin/sgtl data verify gokseong2018`; `project/README.md` exists |
| Suncheon project, after the plan is approved | `bin/sgtl data fetch suncheon_area`; inspect the size before repeating with `--apply --large` | `bin/sgtl data verify suncheon_area` |
| Independent Sangju project | inspect `st.data.project_definition("sangju")`; freeze your own selection/request and follow the [Sangju guide](sangju_project.md) | separate plan, matched reference regions, request fingerprints and validation evidence under `project/sangju/` |

`bin/sgtl doctor`, `bin/sgtl pq check` and `bin/sgtl data verify ...` only inspect your installation or files;
they do not need `--apply`. A data fetch that reports STOP needs the stated prerequisite fixed first. Do not
replace a missing download or an earlier result by an invented file just to reach the next cell.

Keep the names and folder structure that `sgtl new` creates. Later modules reuse these products:

| Produced by | Keep available | Used later |
|---|---|---|
| M20, task 5 | your saved `work/picks/M20_manual_picks.csv` | M21, M22, M30, M31, M50 and M53 |
| M21, then M32 | your PocketQuake cluster `sangju_m21`, its picks, locations and run log | M41 and M51 |
| M31, task 6 | `work/M31_location/results/M31_hypoinverse_runs.csv` | M32 and M50 |
| M51, task 5 | `work/M51_first_motions/results/M51_skhash_first/mechanisms.csv` | M53 |
| M60 | `project/inventory/`, your own Suncheon claims table, signed plan, criteria and lab book; separate `project/sangju/` templates | both required research tracks and their reports |

A notebook that asks you to paste an earlier function means **your own checked function**, with its required
imports, constants and helpers. Copy its definition into the marked cell and run that cell in the new notebook;
variables in another notebook's kernel are not shared. Keep that cell so a kernel restart can reproduce the work.
If a default file path or cluster name differs from yours, change the value in the parameters cell. Do not rename
the original template or edit its check cells.

## Tiers

- **core**: required. Gates count only core tasks.
- **stretch**: do them when core is done; they deepen the same idea.
- **research**: open questions with no single right answer; some have no automatic check.

## The task rhythm: predict, code, check, explain

Each task (named `MXX-Tn`) has the same five cells:

1. **Task text**: goal, given data, the **contract** (inputs, outputs, units, conventions) and when you are done.
2. **Prediction**: before coding, write what you expect inside `st.predict("MXX-Tn", """ ... """)`: a number, a
   shape, a sign, a trend, and why. A wrong prediction is fine; the gap between prediction and result is where you
   learn. The check refuses to run until a prediction is saved.
3. **Your code**: fill in the function where it says `# YOUR CODE HERE`. Keep the signature and the docstring.
4. **Check**: run `st.check(...)`. Never edit this cell.
5. **Explain**: answer the prompt in 3-5 sentences. Quote only numbers your notebook printed.

**Debug-the-trap** tasks give you a cell with a real mistake that has caught researchers before (for example a
time-zone error). You find it, predict its effect and explain it.

## Hints

`st.hint("MXX-Tn", 1)` gives a concept pointer (a glossary term and what to read). Level 2 (the plan in plain
words) unlocks after one failed check; level 3 (the shape of the code with blanks, not runnable) after two.
Hints are logged; using them is normal and never counts against you.

## What checks do and do not tell you

A check runs your function on test cases whose answers are known **by construction** (synthetic data with your
own random seed), from a **different library** or formula, or from **your own tool results**. It prints:
PASS or FAIL, how many cases passed, the tolerance, the seed, and for a failure a **category** with a fixed
message (for example "Your distances look like degrees or meters, not kilometers"). For synthetic cases it shows
the inputs and your value with the size of the error.

It never shows solution code, and it never prints an expected value for real data. Some tasks forbid a shortcut
library inside your function (the check then fails with category `forbidden-import`). `NOT STARTED` means the
function still raises `NotImplementedError`. `st.reroll("MXX-Tn")` draws new synthetic cases (it is logged).

A PASS means your function agrees with the reference on these cases. It does not prove that you understand the
method, and it cannot catch every mistake. That is what the Explain cells and the oral check are for.

## Your record

Every prediction, check, hint and reroll is appended to `work/.sgtl/progress.jsonl` with a time stamp.
`st.progress()` shows a table of your tasks. Your mentor reads this record to plan the course with you. AI help
goes in `work/ai_log/` ([ai_policy.md](ai_policy.md)).

## Submitting a module: `sgtl submit`

When a module is ready (all core checks pass, Explain cells and AI log written), save the notebook in JupyterLab
and run:

```bash
bin/sgtl submit M04            # dry run: checks your copy and prints the plan; nothing runs
bin/sgtl submit M04 --apply    # runs core work, records it and opens a pull request for your mentor
bin/sgtl submit M04 --include-optional    # also select stretch/research work; add --apply after reading the plan
```

With `--apply` the command runs a copy of your work notebook `work/M04_.../M04_....ipynb` in cell order with
**papermill** (a program that runs a notebook without a browser). It selects core work by default and skips optional
task blocks in the execution copy, so unfinished stretch work does not stop a core submission. Use
`--include-optional` to execute stretch and research work too.
The selected checks must all record PASS during this run; an old PASS or a skipped core check is not enough.
It runs in your account on one core with the same thread limits as the course kernel, at low priority, and
stops after 120 minutes (`--timeout MIN` changes that). Your notebook file is not changed: the run writes an
executed copy, a run log and `submission.json` into `work/submissions/M04/<UTC time>/`. `submission.json` lists
what ran and when, and the **SHA-256 fingerprints** (a 64-character code that changes if a single byte of a file
changes) of your notebook, of the executed copy and of the files the run wrote, including the products that
`sgtl pq` logged in `work/.sgtl/runs.jsonl`.

If the selected work ran and its checks passed, these files and your notebook, AI log and logs go into one commit on a new branch
`submit/M04-<UTC time>`, which is pushed to your private copy; then a pull request asks your mentor for a review.
Your current branch and the files in your folder stay as they are. If a selected cell errors, a selected check fails or the time limit
is reached, nothing is committed or pushed: read the run log, fix the notebook and submit again. The checks run
again during a submission and are logged as usual; your mentor counts them apart from your own attempts.
`sgtl submit` pushes only to a private copy: before anything runs it reads every address that `origin` pushes to
and stops unless each one is a GitHub repository that GitHub itself reports as private (it asks with `gh`, so
`gh auth status` must show you logged in). It also stops if any address is the public course repository, in any
form of the address (make your private copy first, [git_workflow.md](git_workflow.md)).

## Gates and the B-path

At the end of each taught week there is a **gate** (G0 to G6, then the Suncheon plan in week 8). The phased
project schedule adds review points for both signed plans/data requests, detection and sensitivity evidence, and
the final two-track portfolio and defense ([curriculum](curriculum.md)). You pass a gate when:

- all **core** checks of that week pass;
- the mentor's rubric gives at least **6 of 8** points with no item at 0. The four items, 0-2 points each:
  correctness (checks and figures), reasoning (your own predictions and explanations), craft (readable code, tidy
  notebook, regular commits) and honesty (a complete AI log, citations, saying what did not work);
- your AI log is honest and complete.

If you do not pass, you take the **B-path**: new seeds for the synthetic checks, extra support from your mentor
and a second try a few days later. It is not a penalty; it is the normal way to catch up. After weeks 3 and 5
the plan is adjusted to the hours you actually needed; stretch items are dropped first.

## The weekly oral check: "explain this cell"

Once a week your mentor picks cells from your work and you explain them without notes for about 15 minutes: what
each line does, why it is there, and what would change if an input changed. If you can explain your own code, you
are learning, whoever helped you. Write code you can explain.

At the meeting you or your mentor run:

```bash
bin/sgtl oral M04 --salt WORD      # or bin/sgtl oral --salt WORD for all modules
```

`WORD` is a new word your mentor says at the meeting (at least 6 characters; the mentor may instead set
`SGTL_ORAL_SALT` in their own shell). Without it nothing is picked, so nobody can know the cells before the
meeting. It picks three code cells of tasks whose check you have passed, at random but seeded by the date, your
name and the word (the same three give the same cells); only a fingerprint of the word is logged. It prints each cell with
line numbers and two questions: what one line does, and what would change if one detail were different. It only
reads your notebooks; it never runs them. The choice is added to `work/.sgtl/oral.jsonl`: commit it with your work.
