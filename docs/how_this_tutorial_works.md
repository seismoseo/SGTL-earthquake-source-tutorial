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

Once a week your mentor picks a cell from your work (a `bin/sgtl oral` command that picks one at random is coming
later) and you explain it
without notes for about 15 minutes: what each line does, why it is there, and what would change if an input
changed. If you can explain your own code, you are learning, whoever helped you. Write code you can explain.
