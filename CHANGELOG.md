# Changelog

All notable changes to the SGTL earthquake source tutorial. Versions follow `vMAJOR.MINOR.PATCH`.
To get a new version into your private copy, run `bin/update-from-upstream` (dry run), then
`bin/update-from-upstream --apply` (see [docs/git_workflow.md](docs/git_workflow.md)).

## v0.3.0 — picking arrivals, deep-learning pickers and travel times

**After updating, update the course environment and add the PhaseNet weights once:**
`bin/sgtl-install env seisbench --apply`. The environment moves to SeisBench 0.11.7 (see Changed), and the new
component `seisbench` puts the weights that module M21 needs into `~/sgtl/seisbench`. Then restart the Jupyter kernel
"SGTL (Python 3.12)". No rebuild is needed.

### Added
- Module M20 (picking arrivals: an STA/LTA ratio and a two-threshold trigger, onset times with the Akaike
  information criterion, how band-pass filters move automatic picks, P and S picks by hand with an uncertainty and
  a first-motion polarity, the signs of each station's gains next to your polarities in a table by azimuth, your
  automatic picker against your own picks over a grid of settings, and ObsPy's `pk_baer` picker as a production
  tool: what each setting does, an unchanged rerun, then one setting changed), module M21 (deep-learning pickers:
  picks from a probability curve, two pretrained PhaseNet models in SeisBench, PocketQuake's picking stage run
  through `sgtl pq`, and a table of first motions for focal mechanisms) and module M30 (travel times in a layered
  crust: direct waves by shooting, head waves as a travel-time idea that is never used for locating, the Wadati
  diagram from your own picks, residuals of two published velocity models against each model's first arrival, the
  earliest of the direct wave and the head waves, and TauP as a production tool). All three work on the Sangju
  earthquake of 21 July 2019 from your M03 download and are delivered unexecuted; start them with
  `bin/sgtl new M20` and so on. Do M20 first: M21 and M30 read your M20 picks (`work/picks/M20_manual_picks.csv`).
  M21 runs PocketQuake on one CPU core and needs the components `tools` and `seisbench`.
- Three optional explorers: E2 in M20 (`st.widgets.phase_picker`) is a picker for P and S: click on a record (or
  type a time), give the uncertainty and the polarity, and "Save" writes your picks to the file that M21 and M30
  read; E3 in M20 (`st.widgets.stalta_tuner`) shows your STA/LTA ratio and your triggers under sliders; E4 in M30
  (`st.widgets.traveltime_explorer`) draws your direct-wave and head-wave travel times while you change the layers
  and the source depth. As before, an explorer never does a task for you, and the picker never chooses a pick.
- Installer component `seisbench` (`bin/sgtl-install seisbench`): the PhaseNet weights `stead` and `original`
  (version 2) for SeisBench, every file pinned by its SHA-256 checksum in `install/checksums.txt`, in
  `~/sgtl/seisbench` (about 2 MB). It sets `SEISBENCH_CACHE_ROOT` in `~/sgtl/tools/env.sh` and in the Jupyter
  kernel, so SeisBench reads these files and downloads nothing by itself, and its check-up runs both models on a
  made-up record. Like the other components, it is a dry run without `--apply` (details: `install/README.md`).
- `bin/sgtl doctor` has a new line, "SeisBench PhaseNet weights": PASS when the four files are in place and match
  their checksums, otherwise WARN with the command that fixes it.
- A new check result, `runtime-name`: a function fails when it builds the name of a module or an attribute while it
  runs, runs code given as text (`eval`, `exec`, `compile`), looks names up with `globals()`, `vars()`, `__dict__`
  or `sys.modules`, changes where imports come from or loads code from a file or from data (`sys.path`, `pickle`,
  `yaml.load`), or was itself made with `exec`. The message asks you to write the names out in full.
- Glossary terms and references for M20, M21 and M30.
- Dataset `sangju2019_hours` in `data/manifests/stp_datasets.yaml`: three hours of continuous records (one hour
  before to two hours after the Sangju ML 3.9 earthquake of 21 July 2019) from the broadband and short-period
  stations within 50 km, about 100 MB. The detection module M22 uses it; it arrives in a later version.

### Changed
- `bin/sgtl data fetch`: the size estimate of the dry run now grows with the length of the records, so long records
  are no longer underestimated.
- M03 Part 6 said that a negative stage gain in the station metadata means that the channel records the ground
  motion upside down. For the Sangju records this is not so. Eleven broadband channels of the Sangju ML 3.9
  earthquake have a negative first-stage gain, yet the same files store a positive overall sensitivity. On all
  eleven the first motion goes the same way as on the accelerometer at the same site (whose gains are positive)
  and on neighbouring stations at nearly the same azimuth, and the same way that KIGAM's published mechanism
  predicts. M03 now shows this disagreement and lets the records decide: take first-motion polarities from the
  counts. If you have already started M03, `bin/sgtl diff M03` shows the change.
- The library check of `st.check` (the part that refuses a ready-made function where a task asks you to write your
  own) also catches the same step done another way: a method such as `Trace.trigger`, a twin such as
  `np.ma.polyfit`, a module reached through another name, a list or a helper function. M01 tasks 1 and 4 now also
  refuse `obspy.taup` and `pyrocko`.
- M10 task 1: the example in the Contract is now a made-up file, with a made-up date and pick time. The rule it
  shows is the same: `a` counts from the reference time. `bin/sgtl diff M10` shows the change.
- The course environment pins SeisBench 0.11.7 instead of 0.11.0: with 0.11.0, `import seisbench.models` failed
  unless the extra package xdas was installed.
- The Jupyter kernel also sets `SEISBENCH_CACHE_ROOT=~/sgtl/seisbench`, and `bin/sgtl-install tools` writes the
  same line into `~/sgtl/tools/env.sh`.
- The glossary's "Terms by module" and the reading list now list every term and reference that a module's header
  names; some terms of M03 and M10 were missing.
- `st.data.velocity_model` (and `src/sgtl_tutorial/data.py`): the documentation now names the columns as they are in
  the files (`top_km`, `vp`, `vs`).

## v0.2.0 — waveform data, seismograms, earthquake catalogs and statistical seismology

**After updating, rebuild the course environment once:** `bin/sgtl-install env --apply --rebuild`. PyTorch now
comes from conda-forge instead of the pip wheel (see Changed), and a rebuild is the clean way to swap it; it also
rewrites the Jupyter kernel with one new setting.

### Added
- Module M03 (getting seismic data: STP, stations, time windows, responses) and module M10 (seismograms: reading,
  filtering, spectra, record sections), both on the Sangju earthquakes that you fetch from STP with your own
  account, and module M04 (earthquake catalogs: read, clean, look) and module M05 (statistical seismology: b-value,
  completeness, aftershock decay). All are delivered unexecuted; start them with `bin/sgtl new M03` and so on.
  M04's two optional downloads from USGS ComCat need the internet; without it the notebook says so and goes on.
  Where a check uses real data (M03 task 5, M04 task 4, M10 task 5), you hand in your functions together with your
  answer: the check first runs them again on made-up cases, then works with what your own functions give on the
  real records, and it never shows a value of its own. M05 task 6 takes your own choices of `mc`, `dmc`,
  `t_start` and `t_end` (there are no defaults).
- `bin/sgtl data` (`list`, `fetch`, `verify`): the STP waveform datasets of `data/manifests/stp_datasets.yaml`,
  fetched into `~/sgtl/data/` with your STP account and the STP program from your mentor (kept in `~/.sgtl/`,
  never in the repository). `fetch` is a dry run unless you add `--apply`; `verify` checks file counts, damaged
  files and SHA-256 fingerprints. The large dataset of the research project also needs `--large`. The STP program
  gets only a short list of environment variables, so Perl or loader settings in your shell (`PERL5OPT`,
  `PERL5LIB`, `LD_PRELOAD`) never reach it.
- Two optional explorers (sliders over a figure, not checked): E9 in M05 (`st.widgets.fmd_explorer`) draws the
  frequency-magnitude distribution for the Mc and bin width you choose, and E1 in M10 (`st.widgets.filter_bench`)
  is a filter bench that shows a record and its amplitude spectrum as you change the corners, the order and
  zero-phase or causal. An explorer never does a task for you: the counts, b-value, Mc and spectrum it shows come
  from your own functions.
- `bin/sgtl doctor` has a new line, "numpy + PyTorch + PyGMT in one process": it loads the three together in a
  separate test process and draws a small map, so a clash of math libraries shows up as a FAIL with its fix
  instead of a notebook kernel that dies.
- `bin/sgtl pq` (`check`, `stage`, `run`, `bootstrap`): PocketQuake on a dataset you fetched; `stage`, `run` and
  `bootstrap` are dry runs unless you add `--apply`.
- Installer components `tools` (HYPOINVERSE, HypoDD with the lab patch, PocketQuake v1.16.1, EQNet with PhaseNet+
  weights, SKHASH), `metadata` (KS and KG station metadata from StationMetadata by Byeong-Seok Ahn, PKNU), `data`
  (your STP files and the course's waveform datasets), `pyfk` (the PyFK environment), `mt` (MTUQ, with seisgen
  and seisclient, two small packages that MTUQ's `open_db` imports for every Green's-function format) and `coulomb`
  (Elastic_stresses_py). Each is a dry run without `--apply` and ends with a short check-up. M03 and M10 need
  `metadata` and `data` (and `tools`, which `data` uses to download); install the others when a module asks you
  to (details and disk sizes: `install/README.md`).
- Glossary terms and references for M03, M04, M05 and M10.

### Changed
- The course environment takes PyTorch 2.6 from conda-forge (the CPU build with OpenBLAS) instead of the pip
  wheel, which loaded the system's C++ library and then clashed with conda's.
- The course environment no longer installs nbmake: nothing in the course uses it, and its package pulled in an
  old pydantic and a `pip check` complaint. The rebuild above removes it.
- The Jupyter kernel also sets `NUMBA_NUM_THREADS=1` (one CPU core for numba, which MTUQ uses).
- A check must judge your own work: `st.check` now gives FAIL (`checker-internals`) for every kind of task,
  including those where you hand in a number, a table or a figure, when your notebook session imported, called
  or copied the checkers' own code (`sgtl_tutorial.checkers`), or read one of its files. The message says where;
  delete that code, restart the kernel, run your cells again from the top and check again. Checks on real data
  never show an expected value or the size of your error. If a check says ERROR because its guard could not
  start, nothing was counted: restart the kernel and run your cells again.
- Hints 2 and 3 open as before (after one and two failed checks). `st.checks.task_spec` now shows only the hints
  you have opened and the failure messages your checks have reported, and `checks/checks.json` keeps the others
  encoded.
- M01 task 5: the note after the Explain prompt gave the cause of the one-hour mystery away. It is gone from the
  notebook; talk it over with your mentor after you have written your answer (`bin/sgtl diff M01` shows the
  change if you have already started M01).
- M02 task 5: on the real catalog the check now tests properties of your own counts (every year once, whole
  numbers, never fewer events inside a larger circle) instead of counting the catalog itself; the made-up catalog
  with events at known distances is unchanged.
- `data/catalogs/README.md`: the section on magnitudes near ML 2.0 now points to module M04 instead of giving the
  result away.
- `data/manifests/stp_datasets.yaml` is no longer a placeholder: it lists the datasets that `bin/sgtl data` fetches,
  with what a complete download looks like.
- `st.synth.gr_magnitudes` draws its made-up magnitudes in a different way (same distribution), so practice data
  in M01 and M02 checks differ from v0.1.0. Checks you passed stay in your progress record.
- `bin/sgtl-install --help` and `install/README.md` list every component as available.

## v0.1.0 — first release

### Added
- Modules M00 (start here: server, terminal, git, install), M01 (Python for earthquake catalogs) and
  M02 (figures and maps), delivered unexecuted. Later modules arrive in later releases.
- The `sgtl_tutorial` helper package: predictions, checks, hints, progress, server-safe defaults and house style.
- `bin/sgtl` (`doctor`, `new`, `status`, `diff`, `setup-ai`), `bin/sgtl-install` (course environment),
  `bin/sgtl-lab` (JupyterLab on the shared server), `bin/make-private-copy` and `bin/update-from-upstream`.
  The tools that install software, start or stop JupyterLab, change your git setup or copy files into your home
  folder are dry runs unless you add `--apply`; `bin/sgtl new` acts at once, because it only copies a module into
  `work/` and never overwrites a file.
- Student documents in `docs/`: setup (English and Korean), how the tutorial works, AI-use policy, git workflow,
  server manners, data policy, troubleshooting, curriculum, reading list and glossary.
- AI-tutor rules: `AGENTS.md`, `CLAUDE.md` and the Claude Code output style `sgtl-tutor`.
- Glossary of technical terms with Korean equivalents (`glossary/glossary.csv`) and a verified reference list
  (`references/references.yaml`).
- Licenses: MIT for code, CC BY 4.0 for text and figures; KMA catalog subsets under KOGL Type 1.
