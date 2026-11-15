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

To remove everything: stop JupyterLab (`bin/sgtl-lab stop --apply`), then delete `~/sgtl/`.

## Components

`bin/sgtl-install [--apply] [component ...]` (the default component is `env`):

| Component | What it installs | Available |
|---|---|---|
| `env` | the course environment `sgtl`, the tutorial's helper package, the Jupyter kernel | now |
| `tools` | HYPOINVERSE, HypoDD with the lab patch, PocketQuake v1.16.1, EQNet with PhaseNet+ weights, SKHASH | release v0.2 |
| `pyfk` | the separate Python 3.9 environment `sgtl-pyfk` (`envs/pyfk.yml`) for PyFK synthetic seismograms | release v0.2 |
| `mt` | MTUQ (moment tensor inversion) | release v0.2 |
| `coulomb` | Elastic_stresses_py (Coulomb stress changes) | release v0.2 |
| `metadata` | station metadata (coordinates and instrument responses) | release v0.2 |

A component that is not available yet prints a message and installs nothing.

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

- `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS`, `NUMEXPR_MAX_THREADS` = 1 and
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
