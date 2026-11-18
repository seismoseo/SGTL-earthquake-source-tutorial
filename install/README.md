# Installing the tutorial software

This page explains how to install everything the tutorial needs, how to open JupyterLab on the
server from your own computer, and how to keep your work in your own private GitHub repository.
You do not need administrator (root) rights for any of it.

## Quick start

```bash
git clone https://github.com/seismoseo/SGTL-earthquake-source-tutorial.git
cd SGTL-earthquake-source-tutorial
bin/sgtl-install                 # dry run: shows what would happen, changes nothing
bin/sgtl-install --apply         # installs (about 20 to 40 minutes the first time)
bin/sgtl doctor                  # checks the installation
bin/sgtl-lab start --apply       # starts JupyterLab and prints how to open it
```

Every script here is a **dry run** unless you add `--apply`: it prints each action with a
`[dry-run]` prefix and changes nothing. Read the dry run first, then add `--apply`.
Every script has `--help`.

## Where things go

Everything big lives in `~/sgtl/`, outside the repository (set `SGTL_HOME` to use another folder):

| Folder | What it holds |
|---|---|
| `~/sgtl/miniforge3/` | Miniforge, the conda package manager (only if you had no conda or mamba) |
| `~/sgtl/envs/sgtl/` | the course environment: Python 3.12 and every package of `environment.yml` |
| `~/sgtl/conda-pkgs/` | downloaded packages when your own conda is used (you may delete it after installing) |
| `~/sgtl/downloads/` | the Miniforge installer |
| `~/sgtl/run/`, `~/sgtl/logs/` | the JupyterLab start script and its log |
| `~/sgtl/data/` | waveforms and other data you download later (never in the repository) |
| `~/sgtl/seisbench/` | the PhaseNet weights for SeisBench (component `seisbench`, module M21) |

To remove everything: stop JupyterLab (`bin/sgtl-lab stop --apply`), then delete `~/sgtl/`.

## Components

`bin/sgtl-install [--apply] [component ...]` (the default component is `env`):

| Component | What it installs | Details |
|---|---|---|
| `env` | the course environment `sgtl`, the tutorial's helper package, the Jupyter kernel | [below](#what-env-does) |
| `tools` | HYPOINVERSE, HypoDD with the lab patch, PocketQuake v1.16.1, EQNet with PhaseNet+ weights, SKHASH | [below](#tools-hypoinverse-hypodd-pocketquake-eqnet-and-skhash) |
| `seisbench` | the PhaseNet weights `stead` and `original` (version 2) for SeisBench, used in module M21 | [below](#the-component-seisbench-phasenet-weights-for-seisbench) |
| `pyfk` | the separate Python 3.9 environment `sgtl-pyfk` (`envs/pyfk.yml`) for PyFK synthetic seismograms | [below](#pyfk-synthetic-seismograms-with-pyfk) |
| `mt` | MTUQ (moment tensor inversion) | [below](#mt-moment-tensors-with-mtuq) |
| `coulomb` | Elastic_stresses_py (Coulomb stress changes) | [below](#coulomb-coulomb-stress-with-elastic_stresses_py) |
| `metadata` | station metadata (coordinates and instrument responses) | [below](#metadata-station-metadata-of-the-ks-and-kg-networks) |
| `data` | your STP files in `~/.sgtl/` and the course's waveform datasets, fetched with your own STP account | [below](#the-component-data-your-stp-files-and-the-course-waveforms) |

Every component except `env` needs the course environment first: install `env`, then the others (you can name
several at once, for example `bin/sgtl-install env tools metadata --apply`).

### What `env` does

1. Looks for conda or mamba. If there is none, it downloads the pinned Miniforge installer, checks
   its checksum (see below) and installs it into `~/sgtl/miniforge3/` without changing your shell
   start-up files.
2. Creates the environment `~/sgtl/envs/sgtl/` from `environment.yml` (or updates it, if it exists).
3. Installs the tutorial's helper package `sgtl_tutorial` from `src/` in "editable" mode: the
   environment uses the files in your clone directly, so updates of the tutorial apply at once.
4. Writes the Jupyter kernel **SGTL (Python 3.12)** (a kernel is the Python process that runs a
   notebook's cells) to `~/sgtl/envs/sgtl/share/jupyter/kernels/sgtl/kernel.json`.
5. Checks that PyGMT loads GMT from the environment, and runs `bin/sgtl doctor`.

Running it again is safe: it updates what exists. `--rebuild` deletes the environment and creates it
again. `--own-miniforge` installs the tutorial's Miniforge even if you have conda (use it when your
conda is old and slow).

### The kernel settings, and why

The kernel sets a few environment variables (settings that programs read when they start):

- `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS`, `NUMEXPR_MAX_THREADS`, `NUMBA_NUM_THREADS` = 1 and
  `NUMPY_MADVISE_HUGEPAGE` = 0: numerical libraries use one CPU core each, because the server is shared.
- `PATH` starts with the environment's `bin/`, `GMT_LIBRARY_PATH` points to its `lib/`, and
  `LD_LIBRARY_PATH` is empty: PyGMT then uses the GMT inside the environment and not another GMT
  installed on the server (a mismatch gives confusing errors or wrong maps).
- `PYTHONNOUSERSITE` = 1: packages you once installed with `pip install --user` are not used.
- `SGTL_REPO` and `SGTL_HOME`: where your clone and `~/sgtl/` are.

To use the kernel from another Jupyter program (for example VS Code), also register it for your user:
`~/sgtl/envs/sgtl/bin/jupyter kernelspec install --user ~/sgtl/envs/sgtl/share/jupyter/kernels/sgtl`

### Checksums

`install/checksums.txt` lists every file the installer downloads with its SHA-256 checksum, a
fingerprint of the file: if one byte differs, the fingerprint differs. The installer refuses a
download whose checksum does not match, and with `--apply` it refuses any entry whose checksum is
`TO-VERIFY`. To pin a new Miniforge release (mentor), copy the `sha256:` digest of the asset
`Miniforge3-<version>-Linux-x86_64.sh` from the GitHub release (its web page or
`https://api.github.com/repos/conda-forge/miniforge/releases/tags/<version>`) into the file.

### Settings

| Variable | Meaning |
|---|---|
| `SGTL_HOME` | install folder (default `~/sgtl`) |
| `SGTL_CONDA` | the conda, mamba or micromamba program to use (default: found automatically) |
| `SGTL_ENV_FILE` | another environment file instead of `environment.yml` (mentor use) |
| `SGTL_ENV` | `tools`, `seisbench`, `mt`, `coulomb`, `metadata` and `data`: the course environment to use instead of `~/sgtl/envs/sgtl` (mentor use) |
| `SGTL_LAB_PORT` | the JupyterLab port instead of your default one |

## JupyterLab on the server: `bin/sgtl-lab`

`bin/sgtl-lab start --apply` starts JupyterLab in a tmux session named `sgtl-lab` (it keeps running
after you log out). It listens only on the server itself (address 127.0.0.1) on your own port,
20000 + (your user ID % 10000), so it does not clash with other users. It asks for a token (a
password it makes up at start), stops kernels that have been idle for 2 hours, and runs at low
priority. `bin/sgtl-lab status` prints how to reach it from your computer through an SSH tunnel
(OpenSSH on macOS, Linux and Windows PowerShell; Xshell; PuTTY), and how to see the token. Never
paste the token into an issue, a chat or an AI tool. `bin/sgtl-lab stop --apply` stops it.

## Your private copy on GitHub

1. Log in once with the GitHub command-line tool (it is in the course environment):
   `gh auth login` (choose GitHub.com, HTTPS, and "Login with a web browser").
2. `bin/make-private-copy` (dry run), then `bin/make-private-copy --apply`. Afterwards `origin` is
   your private repository, `upstream` is the public tutorial (fetch only), the mentor is invited
   as a collaborator, and the pre-commit check below is on.
3. Work only in `work/` (your copies of the notebooks, made with `bin/sgtl new MXX`) and in
   `project/`. Save your work with `git add work/ && git commit -m "..." && git push`.
4. When the mentor announces a new release: `bin/update-from-upstream` (dry run: shows what is new),
   then `bin/update-from-upstream --apply`. If it says the software list changed, run
   `bin/sgtl-install --apply` again.

The **pre-commit check** (`.githooks/pre-commit`) stops a commit that changes files outside `work/`
and `project/` (those belong to the tutorial; changing them makes updates fail), that adds a file
larger than 2 MB, or that adds a waveform file (`.sac`, `.mseed`, `.ms`, ...). Waveforms must never
be committed: the data license does not allow sharing them. GitHub also runs `.sgtl/lint.py` on every
push (the same rules, plus: the tutorial's files match `.sgtl/MANIFEST.sha256`, and notebooks in
`work/` are valid). You can run it yourself: `python3 .sgtl/lint.py`.

## When something goes wrong

- **conda takes very long or fails to solve**: `bin/sgtl-install env --apply --own-miniforge`.
- **"Another kernel named 'sgtl' hides this one"**: delete the folder the message names.
- **PyGMT errors or GMT version warnings**: use the kernel "SGTL (Python 3.12)" (not another one),
  start JupyterLab with `bin/sgtl-lab`, and run `bin/sgtl doctor`.
- **Disk quota exceeded**: the environment needs about 10 GB. Delete `~/sgtl/conda-pkgs/` after
  installing, or set `SGTL_HOME` to a folder with more space (then install again).
- **Anything else**: open a friction issue in your private repository (Issues > New issue > Friction
  report) with the command you ran and the last 30 lines it printed. Never include passwords or tokens.

## The components `pyfk`, `mt` and `coulomb`

These three add the software for synthetic seismograms, moment tensors and Coulomb stress. They need the course
environment first; you can also install everything in one go: `bin/sgtl-install env pyfk mt coulomb --apply`.
Like `env`, each one is a dry run without `--apply`, ends with a short test computation (a *check-up*) whose
result it prints, and can be run again safely: what is already installed and up to date is kept (a second run takes
a few seconds). `--rebuild` installs that part again. Measured on a shared server (November 2026):

| Component | What goes where | Disk | First install |
|---|---|---|---|
| `pyfk` | the environment `~/sgtl/envs/sgtl-pyfk/`; its downloaded packages and conda's channel index in `~/sgtl/conda-pkgs/` | 0.5 GB + up to 0.9 GB | about 1 minute |
| `mt` | MTUQ's files in `~/sgtl/src/mtuq/`; numba, llvmlite, retry, seisgen, seisclient and MTUQ in the course environment; wheels in `~/sgtl/downloads/` | 0.1 GB + 0.2 GB + 0.06 GB | under 1 minute |
| `coulomb` | Elastic_stresses_py and poetry-core in the course environment | under 1 MB | under 1 minute |

You may delete `~/sgtl/conda-pkgs/` and the wheels in `~/sgtl/downloads/` after installing.

### `pyfk`: synthetic seismograms with PyFK

A *synthetic seismogram* is the ground motion that a model earthquake would cause at a station. PyFK computes them
for a layered (1-D) Earth with the frequency-wavenumber ("FK") method. Its conda package needs Python 3.9, so it gets
its own small environment `~/sgtl/envs/sgtl-pyfk/`, made from `envs/pyfk.yml` (PyFK 0.3.0 from its author's conda
channel `ziyixi`; Python 3.9, ObsPy 1.4.2, NumPy 1.26.4 and SciPy from conda-forge) with the same conda as the course
environment. It is a *worker* environment: there is no Jupyter kernel for it. Notebooks run its Python,
`~/sgtl/envs/sgtl-pyfk/bin/python`, which writes results to files that the course environment reads.

The check-up computes one seismogram for the Kim and Kim (1983) crust (`data/velocity_models/kim1983.csv`), with the
source 10 km deep and the station 30 km away, and checks that its three components (vertical, radial, transverse)
are finite and not zero. It takes about 1 second and 60 MB of memory. When a new release changes `envs/pyfk.yml`,
run the component again: it notices the change and updates the environment.

### `mt`: moment tensors with MTUQ

MTUQ (moment tensor uncertainty quantification) estimates an earthquake's moment tensor by comparing recorded and
synthetic waveforms over a grid of possible mechanisms. The component downloads MTUQ with git at the commit the lab
uses (`2157be5`, April 2026) into `~/sgtl/src/mtuq/` (its code and examples are there to read), and installs it into
the course environment in *editable* mode: the environment uses those files directly.

Every pip step uses `--no-deps`, so NumPy stays at 1.26.4 (MTUQ does not work with NumPy 2). The five packages
MTUQ needs that the course environment lacks come from wheels whose checksums are in `install/checksums.txt`:
numba and llvmlite (they compile MTUQ's fast misfit code), retry, and seisgen and seisclient (two small
pure-Python packages: `mtuq.open_db` loads every Green's-function client before it picks the one you asked for,
and two of those clients import them, so without them `open_db` fails even for FK databases). Left out on
purpose: mpi4py (without it MTUQ runs on one core, as a shared server needs), instaseis (only for AxiSEM
databases; MTUQ imports it inside a `try`), PyTables, and the build and test tools cython, nose and flake8.
`pip check` lists these as missing, plus `py` for retry (retry never imports it); that is expected. Without
PyTables, `.save()` works for results on a regular grid (a NetCDF file) but not for a random grid search (a
table): save that with `.to_csv()`.

The check-up imports MTUQ, tests its moment-tensor functions on known double couples, runs its numba misfit
code on a tiny problem whose answer is known, and checks that `open_db` reaches its FK client (one core, about
0.3 GB of memory; about a minute the first time, while numba compiles, and a few seconds after that).

### `coulomb`: Coulomb stress with Elastic_stresses_py

Elastic_stresses_py (by Kathryn Materna) computes the displacement, strain and stress that slip on a fault causes in
an elastic half-space (Okada's equations), and the *Coulomb stress change* on a receiver fault: how much closer to
failure (positive) or further from it (negative) the stress change brings that fault. pip installs it from GitHub
at the pinned commit `5dfc485` (November 2026) into the course environment with `--no-deps`; everything it needs is
already there (tectonic-utils 0.2.1, cutde, PyGMT, pandas). pip builds it with poetry-core, which is installed
first from a checksum-verified wheel.

The check-up computes the Coulomb stress change of a small strike-slip fault patch at one receiver point, and
recomputes the strain there with pyrocko's independent Okada code. The two strain tensors must agree to 1e-3
(relative); they agree to about 1e-13. It takes about 1 second and 0.2 GB of memory.

### Updating a pin (mentor)

The pinned versions are at the top of `install/components/mt.sh` and `install/components/coulomb.sh` (full
40-character git commits; git checks the download against them) and in `envs/pyfk.yml`. A wheel pin is a line of
`install/checksums.txt`: take the file's URL and `sha256` digest from `https://pypi.org/pypi/<name>/<version>/json`,
then run the component with `--apply` once to confirm the download matches.

## The components `tools` and `metadata`

`tools` installs the programs of the location, relocation and mechanism modules; `metadata` installs the station
metadata of the Korean networks KS and KG. Both need the course environment first (`tools` compiles with its
compilers and uses its git and Python); `bin/sgtl-install env tools metadata --apply` installs all three in one go.
Like the others, each is a dry run without `--apply`, ends with a check-up, and can be run again safely: what is
installed and up to date is kept (a second run of `tools` takes about 20 seconds, mostly its check-up; of `metadata`,
under a second). Measured on a shared server (November 2026):

| Component | What goes where | Disk | First install |
|---|---|---|---|
| `tools` | programs in `~/sgtl/tools/bin/`; their source code, manuals and examples in `~/sgtl/tools/src/`; `~/sgtl/PocketQuake/`; `~/sgtl/tools/EQNet/`; `~/sgtl/tools/SKHASH/`; the settings file `~/sgtl/tools/env.sh`; archives in `~/sgtl/downloads/` | 0.08 GB + 1.2 GB (PocketQuake) + 0.05 GB + 0.01 GB + 0.02 GB | about 2 minutes |
| `metadata` | `~/sgtl/data/metadata/` (or `$SGTL_DATA/metadata/`); the two zip files in `~/sgtl/downloads/` | 0.3 GB + 0.01 GB | under 1 minute |

Both use the course environment `~/sgtl/envs/sgtl/`; set `SGTL_ENV` to use one elsewhere (mentor use).

### `tools`: HYPOINVERSE, HypoDD, PocketQuake, EQNet and SKHASH

- **HYPOINVERSE-2000** version 1.40 (Klein, 2002; reference `klein2002`) locates earthquakes from P and S arrival
  times. Its Fortran source code comes from the USGS (`hyp1.40.tar`). Its makefile calls g77, a compiler that no
  longer exists, so `install/patches/hyp1.40-gfortran.mk` replaces it, and the program is *compiled* (turned from
  source code into a program) with the course environment's gfortran.
- **HypoDD** 2.1b (Waldhauser and Ellsworth, 2000; Waldhauser, 2001; references `waldhauser2000`, `waldhauser2001`)
  relocates earthquakes relative to each other from differences of their arrival times. The source is Felix
  Waldhauser's own GitHub repository, tag V2.1b (his web page offers only version 1.3). The lab patch
  `install/patches/hypodd-2.1b-sgtl.patch` raises MAXDATA, the most differential times hypoDD can hold, from 3 to 15
  million, and removes a linker setting that works only on macOS. The program then needs about 4.4 GB of *address
  space* (memory it may use; it takes real memory only as needed, about 10 MB for the example), so it is compiled with
  `-mcmodel=large`. Installed: `hypoDD`, `ph2dt` (makes differential times from phase picks) and `ncsn2pha`
  (converts Northern California phase files).
- **PocketQuake** v1.16.1, the lab's pipeline from a catalog to relocated earthquakes and mechanisms, comes with git
  as a *shallow* copy (this version only) with its two *submodules* (git repositories inside it):
  `external/korea-cluster-relocation` (the pipeline itself, commit `d067985`) and `external/necis-downloader`. The
  installer checks that the tag still points to the pinned commit.
- **EQNet** (AI4EPS), commit `ad492ef`, contains PhaseNet+ (Zhu et al., 2025; reference `zhu2025_phasenetplus`), the
  neural network that picks P and S arrivals and first-motion polarities for PocketQuake. Its *weights* (the numbers
  the network learned in training: `model_99.pth`, 19 MB, release PhaseNet-Plus-v1 of github.com/AI4EPS/models) go to
  `EQNet/docs/model_phasenet_plus/`, where PocketQuake looks for them.
- **SKHASH** (Skoumal et al., 2024; reference `skoumal2024`), commit `352816d` of the USGS GitLab repository,
  computes focal mechanisms from first-motion polarities and S/P amplitude ratios in the way of HASH (Hardebeck and
  Shearer, 2002, 2003).

Files are pinned by checksum (`install/checksums.txt`) and git repositories by commit (top of
`install/components/tools.sh`); git checks every downloaded object against the commit.

`~/sgtl/tools/env.sh` sets what PocketQuake and the notebooks look for: `EQNET_DIR`, `SKHASH_DIR` (the folder with
`SKHASH.py`), `POCKETQUAKE_DIR`, `POCKETQUAKE_PYTHON` (the course environment's Python), and puts `~/sgtl/tools/bin`
first on your `PATH`. Load it with `source ~/sgtl/tools/env.sh`, or add that line to `~/.bashrc` to have it in every
new shell. The installer does not write PocketQuake's own settings file `~/sgtl/PocketQuake/.env` (it holds your
data-center login).

The check-up runs every tool on its authors' own example and compares with their results: HYPOINVERSE locates the
USGS example earthquake (`testone`) and must give the USGS summary line (it does, character for character); `ph2dt`
must give the differential times of Waldhauser's example 1 (identical) and `hypoDD` his 16 relocated events within
about 10 m (they agree within 1 m); `pocketquake` and its `pipeline` import; the PhaseNet+ weights match their
checksum and EQNet imports with PyTorch; and SKHASH's example `hash1` must give the USGS mechanisms (strike, dip,
rake and quality of all 24 events: identical). It takes about 20 seconds; SKHASH needs about 2 GB of memory for a
few seconds.

The compiled programs use the Fortran library of the course environment (they find it there by themselves), so keep
that environment; after `bin/sgtl-install env --apply --rebuild` they work again. To compile them again anyway,
delete `~/sgtl/tools/.stamps/` and run the component. If `~/sgtl/PocketQuake/`, `~/sgtl/tools/EQNet/` or
`~/sgtl/tools/SKHASH/` holds another version, the component stops and changes nothing in it: move the folder away
(for example `mv ~/sgtl/PocketQuake ~/sgtl/PocketQuake.old`) and run it again. If `hypoDD` stops at once without a
message, your shell limits virtual memory (`ulimit -v` prints the limit in KB); it needs at least about 4.5 GB.

### `metadata`: station metadata of the KS and KG networks

*Station metadata* tell where each station is and how each channel's instrument turns ground motion into numbers
(its *response*); you need them to correct waveforms for the instrument and to locate earthquakes. StationMetadata
1.0.2 (Ahn, Kang and Jung, 2024; reference `ahn2024`), by Byeong-Seok Ahn (Pukyong National University), integrates
the metadata of the regional networks in the southern Korean Peninsula. The component downloads its two zip files
from github.com/ByeongSeokAhn/StationMetadata at commit `4830550` (checksums pinned) and fills `~/sgtl/data/metadata/`:

| File | What it is |
|---|---|
| `KS_KG_metadata_1.0.2.xml` | all stations in one *StationXML* file (the standard XML format for station metadata), as published (148 MB) |
| `KS_KG_metadata_1.0.2.SACPZ` | the responses as poles and zeros in SAC format, as published |
| `stationxml/NET.STA.xml` | the same StationXML, one file per station, for example `stationxml/KS.ADO2.xml` |
| `ACKNOWLEDGMENT.txt` | who made the files, the paper to cite, and the source (repository, commit, checksums) |

Reading the whole StationXML file with ObsPy takes about 12 seconds and 2.2 GB of memory; a station file takes a
quarter of a second: `obspy.read_inventory(os.path.expanduser("~/sgtl/data/metadata/stationxml/KS.ADO2.xml"))`.
The split reads the big file piece by piece (about 0.2 GB of memory and 12 seconds), copies the file's header and
network description into every station file, changes nothing else, and then reads every new file back with ObsPy
(the check-up). It gives 547 files for 545 station codes: BRD and CHS are in both networks, KG and KS, at different
sites. (The repository's README speaks of 546 stations.) Please cite Ahn et al. (2024) whenever you use these files.
The repository states no license, so do not share copies; point others to the repository instead.

## The component `seisbench`: PhaseNet weights for SeisBench

Module M21 runs two pretrained PhaseNet pickers with SeisBench (version 0.11.7 in the course environment). A
*pretrained model* is a neural network whose *weights* (its numbers) were already fitted to a large set of records
with known picks: `stead` was trained by the SeisBench team on the STEAD data set, and `original` is the model of
Zhu and Beroza (2019), trained on records from Northern California. SeisBench would download weights the first time
a model is used; this component downloads them once, checks every file against its SHA-256 checksum in
`install/checksums.txt`, and puts them where SeisBench looks. Measured on a shared server (November 2026):

| What goes where | Disk | First install |
|---|---|---|
| `~/sgtl/seisbench/models/v3/phasenet/`: a `.json` description and a `.pt` weights file for `stead` and for `original` (version 2); SeisBench's settings file `~/sgtl/seisbench/config.json` (kept if it exists) | about 2.2 MB | under 1 minute |

It also sets `SEISBENCH_CACHE_ROOT=~/sgtl/seisbench` in `~/sgtl/tools/env.sh` and in the Jupyter kernel
"SGTL (Python 3.12)", so SeisBench reads these files and never downloads anything by itself; restart the kernel
afterwards. The check-up loads both models with every download switched off and runs each on a made-up 60-second
record on one CPU core (a few seconds). Like the others, it is a dry run without `--apply` and can be run again
safely. It needs the course environment first: `bin/sgtl-install env seisbench --apply` installs both.
`bin/sgtl doctor` shows whether the weights are in place (the line "SeisBench PhaseNet weights").

## The component `data`: your STP files and the course waveforms

Waveforms come only from STP (the Seismogram Transfer Program; glossary `stp`), with your personal STP account and
the STP program `stp-client.pl` that your mentor gives you. Neither is ever in this repository, and the installer
never downloads the program. Install `env` and `tools` first: the download runs through your PocketQuake copy.
`bin/sgtl-install data` (a dry run without `--apply`):

1. makes the data folder `~/sgtl/data/` (or `$SGTL_DATA`) and the folder `~/.sgtl/` that only you can open;
2. writes a template `~/.sgtl/credentials.env` (only you can read it) for your STP id and password, if there is none;
3. checks `~/.sgtl/stp-client.pl` against its SHA-256 fingerprint in `install/checksums.txt`;
4. fetches every dataset of `data/manifests/stp_datasets.yaml` that is not marked large, with
   `bin/sgtl data fetch NAME --apply`, and checks each one with `bin/sgtl data verify NAME`.

Your id and password are never printed. Running it again skips the events you already have. Module M03 explains
the datasets, the file layout (`~/sgtl/data/NAME/stp_download/SAC/<UTC origin time>/<band>/`) and how to check what
arrived. The large dataset of the research project is fetched only by hand:
`bin/sgtl data fetch suncheon_area --apply --large`. The test fetches of November 2026 took 279 s for `sangju2019`
(373 MB) and 116 s for `suncheon2019` (307 MB); STP is slower when it is busy. `bin/sgtl data list` shows every
dataset, its estimated size, and what you already have.
