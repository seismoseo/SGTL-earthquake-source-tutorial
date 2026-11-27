# How this tutorial works

한국어: [how_this_tutorial_works_ko.md](how_this_tutorial_works_ko.md)

The course is a chain of **modules**, M00 to M60, each one Jupyter notebook. `bin/sgtl new MXX` copies a module
once into `work/MXX_slug/`; work only in that copy. The originals in `docs/notebooks/` belong to the tutorial, and
updates replace them. The [lesson guide](notebooks/README.md) gives the order and what to prepare.

A notebook starts with a header: the time it takes, the modules to finish first and the new words. Run two cells
first. **Parameters** is the only place for values you may change. **Setup** runs `S = st.init("MXX")`, which caps
threads and memory so you share the server fairly. Each Part then shows an idea with a short text and a code cell:
run it and look.

## A task in five steps

Every task, `MXX-Tn`, has the same cells. This one is from M05.

```text
### M05-T3 · Completeness from the peak of the histogram · core · about 60 min

Write `mc_maxc(mags, dm, correction=0.2)`: the center of the bin with the most events, plus `correction`.
- Bins have width `dm` and are centered on the listed values (multiples of `dm`).
- If several bins share the largest count, take the smallest magnitude.
- `np.unique(..., return_counts=True)` counts how often each value occurs.

Example: 1.0, 1.1, 1.1, 1.2 with `dm` = 0.1 give 1.1 + 0.2 = 1.3.

Not allowed: SeismoStats or `sgtl_tutorial` inside your function.
```

```python
# Before you code: for a catalog whose detection fades slowly over a whole magnitude unit, will MAXC + 0.2 be
# above or below the magnitude where detection is really complete?
st.predict("M05-T3", """

""")
```

```python
def mc_maxc(mags, dm, correction=0.2):
    """Maximum-curvature magnitude of completeness (Wiemer and Wyss 2000) plus a correction.

    mags       : numpy array of rounded magnitudes
    dm         : float, bin width
    correction : float, added to the peak bin (0.2 after Woessner and Wiemer 2005)
    returns    : float, magnitude of completeness
    """
    # YOUR CODE HERE
    raise NotImplementedError("M05-T3: write your code here")
```

```python
st.check("M05-T3", func=mc_maxc)
```

```text
**Explain:** In the demo below, where is MAXC + 0.2 compared with 99 % detection, and what does that do to $\hat b$?
```

1. **Read** the task text and the docstring: it lists the inputs, the outputs and their units.
2. **Predict.** Answer the `Before you code` question inside the quotes of `st.predict`, and run the cell. A wrong
   guess is fine: you learn from the gap. The check runs only after a prediction is saved.
3. **Code.** Put your code under `# YOUR CODE HERE`, in place of the `raise` line. Keep the name, the arguments
   and the docstring. Never use the course package (`st`, `sgtl_tutorial`) inside a task function: the check
   refuses it, and the same for the libraries a task lists as not allowed.
4. **Check.** Run the `st.check` cell; never edit it. It tests your function on cases with known answers and prints
   PASS, or FAIL with the reason. After a FAIL, `st.hint("MXX-Tn", 1)` gives a pointer; level 2 opens after one
   failed check, level 3 after two. Hints never count against you. `st.reroll("MXX-Tn")` draws new practice data.
5. **Explain.** Answer the one Explain question in 1-3 sentences of your own, with numbers your notebook printed.

A PASS means your function agrees with the reference on these cases. It does not prove that you understand the
method: your Explain answers and the weekly oral check test that. The gates, your mentor's rubric and the oral check
are in the [curriculum](curriculum.md#gates); other check messages are in [troubleshooting](troubleshooting.md#checks).

## Kernel restarts, Run All and optional cells

A restart (Kernel → Restart Kernel) clears all variables: run the parameters and setup cells, then your finished
cells in order. **Kernel → Restart Kernel and Run All Cells** also runs the optional cells, so use it when those are
ready too. Notebooks share no variables. When a module asks for an earlier function, paste your own checked function
into the marked cell, with its imports, constants and helpers, and run it.

A task is **core** (required; gates count only these), **stretch** (deeper, after core) or **research** (open
questions; some have no check). Explorers and other cells marked *optional* are never required.

## The AI log

AI may explain errors, formulas and concepts. It may not write your task functions, predictions or Explain answers
([AI policy](ai_policy.md)). Log every use in `work/ai_log/MXX.md`. Your predictions, checks, hints and rerolls are
logged in `work/.sgtl/progress.jsonl`; `st.progress()` shows them as a table. Your mentor reads both.

## Save and submit

Save with Ctrl+S (Cmd+S on a Mac) and commit every day ([Git workflow](git_workflow.md)). When all core checks pass
and your Explain answers and AI log are written, run in a server terminal:

```bash
bin/sgtl submit M04            # dry run: checks your copy and prints the plan; nothing runs
bin/sgtl submit M04 --apply    # runs core work, records it and opens a pull request for your mentor
bin/sgtl submit M04 --include-optional    # also select stretch/research work; add --apply after reading the plan
```

`--apply` runs a copy of your notebook from the top with **papermill**, a program that runs a notebook without a
browser. It uses one core and stops after 120 minutes (`--timeout MIN` changes that). Unfinished optional tasks do
not stop a core submission. Every selected check must PASS in this run; an old PASS does not count. Your notebook is
not changed. The executed copy, a run log and `submission.json` go to `work/submissions/M04/<UTC time>/`; the last
holds **SHA-256 fingerprints** of the files, codes that change when one byte of a file changes. They are committed on
a new branch `submit/M04-<UTC time>` of your private copy, and a pull request asks your mentor for a review. If a
cell fails, a check fails or time runs out, nothing is committed: read the run log, fix the notebook and submit
again.

`sgtl submit` pushes only to a private GitHub copy, never to the public course repository, and needs
`gh auth status` to show you logged in ([private copy](git_workflow.md)).
