# Changelog

All notable changes to the SGTL earthquake source tutorial. Versions follow `vMAJOR.MINOR.PATCH`.
To get a new version into your private copy, run `bin/update-from-upstream` (dry run), then
`bin/update-from-upstream --apply` (see [docs/git_workflow.md](docs/git_workflow.md)).

## v0.5.0 — the focal sphere, mechanisms from first motions and synthetic seismograms

**After updating, install the PyFK environment once** (module M52 needs it): `bin/sgtl-install pyfk` (dry run: the
plan), then `bin/sgtl-install pyfk --apply` (about a minute). It makes the small Python 3.9 environment
`~/sgtl/envs/sgtl-pyfk` in which PyFK runs; it is not a Jupyter kernel, and the course environment is unchanged.
Module M51 runs SKHASH from the course tools that you installed for v0.4.0 (`bin/sgtl-install tools`);
`bin/sgtl pq check` shows whether they are in place. Then restart the Jupyter kernel "SGTL (Python 3.12)" so that it
loads the new version of the course package. There is nothing new to fetch: the three new modules use your Sangju
download of M03.

### Added
- Module M50 (the focal sphere): strike, dip and rake turned into the fault normal and the slip vector in
  north-east-down coordinates, and how the up-south-east order of the Global CMT catalog and ObsPy differs; the
  auxiliary plane and the P and T axes, tested against ObsPy and Pyrocko; rays on a lower-hemisphere equal-area net,
  with upward rays at the opposite point; takeoff angles from your own ray tracing of M30, first arrivals that are
  head waves included; your Sangju first motions of M20 on the net next to KIGAM's published mechanism; and ObsPy's
  beachball drawn unchanged, then with the other nodal plane. Before you code, you solve two hand exercises of the
  NMSOP-2 manual on a printed net: `docs/figures/equal_area_net.pdf` (print it on A4 at 100 %, without scaling).
- Module M51 (mechanisms from first motions): the polarities that a mechanism predicts and a weighted polarity
  misfit; a grid search over strike, dip and rake that returns the best and the acceptable mechanisms, tested on
  made-up polarities with some readings flipped; the Kagan angle between two mechanisms; families of acceptable
  mechanisms; SKHASH run through `sgtl pq` (a dry run first) on the PocketQuake cluster of your M21 picks, next to
  your grid search on the same polarities and to KIGAM's mechanism of the mainshock; and an unchanged rerun, then
  polarities only, with a measurement of what the S/P amplitude ratios that PocketQuake hands to SKHASH contain.
  Its SKHASH runs use one core and up to about 9 GB of memory for a few minutes each.
- Module M52 (synthetic seismograms): the moment tensor of a double couple in north-east-down and up-south-east
  coordinates; seismic moment M0 and moment magnitude Mw both ways; the P, SV and SH radiation patterns; a
  far-field synthetic in a whole space, compared with PyFK at several distances; a colleague's PyFK call to predict,
  measure and test against PyFK's code; and PyFK synthetics of the 2019 Sangju mainshock from KIGAM's mechanism next
  to your response-corrected, band-passed records (shape, time shift and amplitude ratio, also as a change of moment
  magnitude), rerun unchanged, then with velocity model kim2011. The notebook runs PyFK in its own environment through the course package
  (`sgtl_tutorial.pyfk_runner`): plain numbers go in, plain files come back, each checked by its SHA-256
  fingerprint. It runs on one core.
- All three are delivered unexecuted; start them with `bin/sgtl new M50` and so on, in order. M50 reads your M20
  first motions and uses your M30 and M31 results; M51 starts from your M21 PocketQuake cluster and your M32
  locations and asks you to paste your `fault_vectors` of M50 into its notebook; M52 asks you to paste your
  `equal_area` of M50 and your `xcorr_lag` of M41 into its notebook. When something a module reads is missing, it
  stops with a message that says what to finish first.
- Three optional explorers: E13 in M50 (`st.widgets.focal_sphere_fitter`) lets you fit a fault plane to first
  motions by hand, with your own net, agreement, P and T axes and auxiliary plane; E8 in M51
  (`st.widgets.beachball_explorer`) shades a beachball under strike, dip and rake sliders with your own predicted
  polarities and shows your misfit and the stations it gets wrong; E12 in M52 (`st.widgets.radiation_explorer`)
  draws your P, SV and SH radiation patterns for the mechanism under the sliders. All three place points with your
  `equal_area` of M50 (pass it as `project=`); as before, an explorer never does a task for you.
- `bin/sgtl submit MXX`: hands in a finished module. It is a dry run by default; with `--apply` it runs your work
  notebook from the first cell to the last (one core, low priority, at most 120 minutes), records the run with the
  SHA-256 fingerprints of what it wrote, commits it on a new branch of your private copy and opens a pull request
  for your mentor. It pushes only to a private copy: it stops before the run unless every address that `origin`
  pushes to is a GitHub repository that GitHub reports as private (it asks with `gh`, so log in with
  `gh auth login` first), and it never pushes to the public course repository, however its address is written.
  Your own branch and files stay as they are, and a run that fails commits nothing. Details:
  [docs/how_this_tutorial_works.md](docs/how_this_tutorial_works.md).
- `bin/sgtl oral [MXX] --salt WORD`: picks three code cells of tasks you have passed for the weekly oral check
  ("explain this cell"), seeded by the date, your name and a word your mentor says at the meeting (required, at
  least 6 characters, so nobody can know the cells in advance), and logs the choice in `work/.sgtl/oral.jsonl`
  with a fingerprint of the word.
- Glossary terms for M50, M51 and M52.

### Changed
- Two report values are now checked from file fingerprints: M21 task 4 and M32 task 4 take `fingerprints` (the
  SHA-256 of every file of the first run and of the rerun) in place of `identical`, and the check works out itself
  which files are the same. M32 task 4 is now checked with `st.check("M32-T4", answer=rerun_report)`, with your
  function under `differ`. If you have already started M21 or M32, `bin/sgtl diff M21` and `bin/sgtl diff M32` show
  the change.
- M21: the examples in task 2's Contract and in two check messages now use a made-up station code and a made-up
  event id.
- The course map in `README.md` and `docs/curriculum.md` now describes M50, M51 and M52 as they are, and the list of
  explorers names E8, E12 and E13. `docs/git_workflow.md` and `docs/how_this_tutorial_works.md` describe
  `sgtl submit` and `sgtl oral`.
- "How to cite" in `README.md` names version 0.5.0.

## v0.4.0 — locating earthquakes, HYPOINVERSE, relative relocation and detection

**After updating, there is nothing new to install** if you set up v0.3.0: the new modules use the course tools
(`bin/sgtl-install tools`: PocketQuake, HYPOINVERSE and HypoDD) and the PhaseNet weights
(`bin/sgtl-install seisbench`), and the course environment is unchanged. `bin/sgtl pq check` shows whether the tools
are in place (HYPOINVERSE, ph2dt and hypoDD among them) and `bin/sgtl doctor` whether the weights are; then restart
the Jupyter kernel "SGTL (Python 3.12)" so that it loads the new version of the course package. For module M22
only, fetch the three hours of records `sangju2019_hours` with your STP account:
`bin/sgtl data fetch sangju2019_hours` (dry run: the plan), then the same command with `--apply`.

### Added
- Module M31 (locating an earthquake): a grid search over the hypocenter and Geiger's method (damped least squares
  with the Jacobian of the travel times), both tested on a made-up earthquake whose position you know; the
  covariance matrix, the standard errors and the correlation of depth and origin time, confirmed with a Monte
  Carlo test of your own locator; the Sangju mainshock of 21 July 2019 located from your own M20 picks with the
  first arrivals of your M30 functions (never the Moho head waves Pn and Sn), next to the KMA catalog; a depth
  scan of the 2018 Sangju earthquake with and without the station nearest to it; and phase lines that you write
  for HYPOINVERSE, which you run with the commands of PocketQuake's location stage (printed next to PocketQuake's
  own), rerun unchanged, and then run with one setting changed.
- Module M32 (HYPOINVERSE through PocketQuake): PocketQuake's location stage run through `sgtl pq` (a dry run
  first) on the cluster of your M21 picks, and the SHA-256 fingerprints of the run log that show which files a run
  wrote; HYPOINVERSE's archive file read by its fixed columns, checked against its summary file; its locations
  matched with the KMA catalog and with your M31 location; an unchanged rerun, then velocity model kim2011 in
  place of kim1983; and stations whose residuals are early or late, and what a station delay can and cannot hold.
- Module M41 (relative relocation): catalog differential times for pairs of earthquakes, checked against HypoDD's
  file `dt.ct`; the lag between two waveforms by cross-correlation, to a fraction of a sample, and your
  differential times on the Sangju records next to PocketQuake's; the double-difference system G m = d, solved
  with damping and a fixed centroid and iterated to convergence; the Sangju earthquakes relocated with your own
  functions, each phase only at the stations inside its crossover distance for the deepest earthquake above the
  boundary at 15 km (from your M30 functions), and with HypoDD through PocketQuake; an unchanged rerun, a bootstrap of HypoDD's result with two
  seeds, and how to tell from the run log which run wrote a result file. Its PocketQuake runs use 3 cores (never
  more than 4 on the shared server); the longest, the cross-correlation stage, takes about 8 minutes.
- Module M22 (detecting earthquakes, a stretch module): network coincidence of per-station triggers, a normalized
  cross-correlation, a detection threshold from the median absolute deviation (MAD), a relative magnitude from
  amplitude ratios, template matching on the three hours `sangju2019_hours` with a null test, and an associator
  that groups the picks of a pretrained PhaseNet into earthquakes (an unchanged rerun, then one setting changed).
  It runs on one core. Its practice records with known answers come from the new course module
  `sgtl_tutorial.synth_detect`.
- All four are delivered unexecuted; start them with `bin/sgtl new M31` and so on. Do them in order: M31 reads your
  M20 picks and your M30 travel-time functions; M32 locates the PocketQuake cluster of your M21 picks and reads
  your M31 results; M41 starts from the locations of M32 and uses your M30 travel-time functions. M22 reads your M20 picks and uses your M21 and M30
  functions. When something a module reads is missing, it stops with a message that says what to finish or fetch
  first.
- Four optional explorers: E5 in M31 (`st.widgets.misfit_explorer`) draws the misfit of your own grid search in map
  view and in a depth section, with stations left out as you choose, and your Wadati line; E6 in M41
  (`st.widgets.lag_explorer`) makes a wavelet and a shifted copy under a filter band and noise, and shows the lag
  that your cross-correlation finds next to the true shift; E7 in M41 (`st.widgets.dd_toy`) puts a made-up cluster
  under pick errors and station delays and shows absolute positions next to the relative positions from your own
  double-difference functions; E11 in M22 (`st.widgets.detection_explorer`) shows your threshold and detections on
  the network cross-correlation next to the peaks on the null records. As before, an explorer never does a task
  for you.
- Glossary terms and references for M22, M31, M32 and M41.

### Changed
- The course map in `README.md` and `docs/curriculum.md` now describe M22, M31, M32 and M41 as they are, and the
  list of explorers names E5, E6, E7 and E11.
- "How to cite" in `README.md` names version 0.4.0.

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
