# Curriculum

Plan for about 35-40 hours a week, including about 2 hours of reading ([reading list](reading_list.md)). All times
are estimates: your mentor adjusts the plan after week 1, and again after the gates of weeks 3 and 5. If the pace is
slow, optional explorers and stretch tasks go first; M22 and both projects stay required.

| Week | Module | What you learn | Hours (+ optional) |
|---|---|---|---|
| 1 | M00 Start here | the server, terminal, JupyterLab, git and your private copy | 8 |
| 1 | M01 Python for earthquake catalogs | tested Python functions, pandas tables, UTC and KST | 10 (+1) |
| 1 | M02 Figures and maps | clear figures in the house style and PyGMT maps | 6 (+1.5) |
| 1 | M04 Earthquake catalogs | magnitude counts, sequences, catalog matching, completeness | 8 (+1.5) |
| 2 | M05 Statistical seismology | b-value, completeness and aftershock decay | 9 (+2) |
| 2 | M03 Getting seismic data | station codes, UTC windows, STP downloads, instrument responses | 5.7 (+1) |
| 2 | M10 Seismograms | SAC times, filters, spectra, response removal, record sections | 9.7 (+1.7) |
| 3 | M20 Picking arrivals | STA/LTA triggers, onset times and picks by hand | 9.7 |
| 3 | M21 Deep-learning pickers | PhaseNet picks and PocketQuake's picking stage | 7.8 |
| 3 | M30 Travel times in a layered crust | direct and head waves, Wadati diagrams, velocity models | 9 (+1) |
| 3-4 | M22 Detection and template matching | coincidence detection, template matching and its validation | 12 |
| 4 | M31 Earthquake location | grid search, Geiger's method and location uncertainty | 10.5 (+1) |
| 4 | M32 HYPOINVERSE via PocketQuake | a production locator, its files and its residuals | 7 |
| 5 | M41 Relative relocation | differential times, cross-correlation and double difference | 9.7 |
| 6 | M50 The focal sphere | fault vectors, P and T axes and the equal-area net | 9 |
| 6 | M51 Mechanisms from first motions | polarity misfit, grid search, Kagan angle and SKHASH | 10 |
| 6 | M52 Synthetic seismograms | moment tensors, radiation patterns and PyFK synthetics | 10 |
| 7 | M53 Moment tensor inversion | least squares, misfit norms, time shifts and MTUQ | 11 |
| 7 | M54 Coulomb stress change | stress on a receiver fault and what aftershocks can test | 10 |
| 8 | M60 Full run and project plan | the full chain on a new sequence and your Suncheon plan | 10 |
| 9-16 | [Research projects](project.md) | Suncheon and Sangju, both with validated template matching | see the project schedule |

The [SeisComP GUI workshop](seiscomp_gui.md) goes with M03, M10 and M20. The [lesson guide](notebooks/README.md)
says what to prepare for each module.

## Gates

- Weeks 1-7: gates G0 to G6; G2 and G4 also check your plan.
- Week 8: the Suncheon plan is frozen.
- Weeks 9-10: both research plans and data requests are signed.
- Weeks 13-14: your detection and sensitivity evidence is reviewed.
- Week 16: the final portfolio.

You pass a gate when all **core** checks of that week pass, your AI log is honest and complete, and your mentor's
rubric gives at least **6 of 8** points, with no item at 0. Each item scores 0-2:

- correctness: checks and figures;
- reasoning: your own predictions and explanations;
- craft: readable code, a tidy notebook, regular commits;
- honesty: a complete AI log, citations, saying what did not work.

If you do not pass, you take the **B-path**: new seeds for the synthetic checks, extra help from your mentor and a
second try a few days later. It is not a penalty; it is the normal way to catch up.

## The weekly oral check

Once a week you explain cells of your own work without notes, for about 15 minutes: what each line does, why it is
there, and what would change if an input changed. At the meeting, you or your mentor run:

```bash
bin/sgtl oral M04 --salt WORD      # or bin/sgtl oral --salt WORD for all modules
```

`WORD` is a new word your mentor says at the meeting (at least 6 characters; or the mentor sets `SGTL_ORAL_SALT` in
their own shell), so nobody knows the cells in advance. The command picks three code cells of tasks you have passed
and prints each with two questions. Commit the record it adds to `work/.sgtl/oral.jsonl`.
