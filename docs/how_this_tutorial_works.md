# How this tutorial works

한국어: [how_this_tutorial_works_ko.md](how_this_tutorial_works_ko.md)

## Modules

The course is a series of **modules** (M00, M01, ... M60; see [curriculum.md](curriculum.md)). Each module is
one Jupyter notebook. `bin/sgtl new MXX` copies it once into `work/MXX_slug/`; you work only in that copy. The
originals in `modules/` belong to the tutorial and are replaced by updates.

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
bin/sgtl submit M04 --apply    # runs it, records it and opens a pull request for your mentor
```

With `--apply` the command runs your work notebook `work/M04_.../M04_....ipynb` from the first cell to the last
with **papermill** (a program that runs a notebook without a browser, like Kernel → Restart Kernel and Run All
Cells). It runs in your account on one core with the same thread limits as the course kernel, at low priority, and
stops after 120 minutes (`--timeout MIN` changes that). Your notebook file is not changed: the run writes an
executed copy, a run log and `submission.json` into `work/submissions/M04/<UTC time>/`. `submission.json` lists
what ran and when, and the **SHA-256 fingerprints** (a 64-character code that changes if a single byte of a file
changes) of your notebook, of the executed copy and of the files the run wrote, including the products that
`sgtl pq` logged in `work/.sgtl/runs.jsonl`.

If every cell ran, these files and your notebook, AI log and logs go into one commit on a new branch
`submit/M04-<UTC time>`, which is pushed to your private copy; then a pull request asks your mentor for a review.
Your current branch and the files in your folder stay as they are. If a cell stops with an error or the time limit
is reached, nothing is committed or pushed: read the run log, fix the notebook and submit again. The checks run
again during a submission and are logged as usual; your mentor counts them apart from your own attempts.
`sgtl submit` pushes only to a private copy: before anything runs it reads every address that `origin` pushes to
and stops unless each one is a GitHub repository that GitHub itself reports as private (it asks with `gh`, so
`gh auth status` must show you logged in). It also stops if any address is the public course repository, in any
form of the address (make your private copy first, [git_workflow.md](git_workflow.md)).

## Gates and the B-path

At the end of each week there is a **gate** (G0 to G6, then the frozen project plan in week 8 and the final
defense). You pass a gate when:

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
