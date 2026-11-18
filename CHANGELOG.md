# Changelog

All notable changes to the SGTL earthquake source tutorial. Versions follow `vMAJOR.MINOR.PATCH`.
To get a new version into your private copy, run `bin/update-from-upstream` (dry run), then
`bin/update-from-upstream --apply` (see [docs/git_workflow.md](docs/git_workflow.md)).

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
