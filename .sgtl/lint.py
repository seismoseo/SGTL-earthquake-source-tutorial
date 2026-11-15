#!/usr/bin/env python3
"""Repository checks for the SGTL earthquake source tutorial and every private copy of it.

Checks (standard library only; works with Python 3.6 and newer):
  1. data files   - no seismic waveform files (.sac, .mseed, .miniseed, .ms, .msd, .seed) are tracked;
  2. file size    - no tracked file is larger than 2 MB;
  3. tutorial files - the files that belong to the tutorial ("upstream-owned": everything outside
     work/ and project/) match .sgtl/MANIFEST.sha256, and nothing was added outside work/ and project/;
  4. notebooks    - every notebook (.ipynb) in work/ and project/ is valid JSON.

Run it from anywhere:  python3 .sgtl/lint.py        (exit status 0 = passed, 1 = a check failed)
The git pre-commit hook (.githooks/pre-commit) already applies the main rules before every commit.

Manifest format (.sgtl/MANIFEST.sha256, written by the tutorial's release tool): one line per
upstream-owned file, "<64 hex characters><two spaces><path relative to the repository root>", the same
format as the output of `sha256sum`. Blank lines and lines starting with "#" are ignored.

Copyright (c) 2026 Minseong Seo (SGTL, Seoul National University). MIT License.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys

MAX_BYTES = 2 * 1024 * 1024
WAVEFORM_SUFFIXES = (".sac", ".mseed", ".miniseed", ".ms", ".msd", ".seed")
STUDENT_DIRS = ("work/", "project/")
MANIFEST = ".sgtl/MANIFEST.sha256"
# Written by the release tool next to the manifest; never reported as "added" (checked if listed).
RELEASE_META = (MANIFEST, ".sgtl/release.json")


def default_root():
    """The repository root: the folder that contains this file's .sgtl/ folder."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def tracked_files(root):
    """Paths tracked by git (relative, '/' separated). Falls back to walking the folder without git."""
    try:
        out = subprocess.check_output(["git", "-C", root, "ls-files", "-z"], stderr=subprocess.DEVNULL)
        return sorted(p for p in out.decode("utf-8", "surrogateescape").split("\0") if p)
    except (OSError, subprocess.CalledProcessError):
        pass
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in filenames:
            rel = os.path.relpath(os.path.join(dirpath, name), root)
            found.append(rel.replace(os.sep, "/"))
    return sorted(found)


def is_student_path(path):
    return path.startswith(STUDENT_DIRS)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_manifest(path):
    """Return ({relative path: sha256}, [problems with the manifest itself])."""
    entries, problems = {}, []
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.rstrip("\r\n")
            if not line.strip() or line.startswith("#"):
                continue
            digest, sep, rel = line[:64], line[64:66], line[66:]
            if len(digest) != 64 or sep not in ("  ", " *") or not rel:
                problems.append("line {}: not in '<sha256>  <path>' form".format(lineno))
                continue
            try:
                int(digest, 16)
            except ValueError:
                problems.append("line {}: '{}' is not a sha256 value".format(lineno, digest))
                continue
            if rel.startswith("./"):
                rel = rel[2:]
            entries[rel] = digest.lower()
    return entries, problems


def check_data_files(root, files):
    bad = [p for p in files if p.lower().endswith(WAVEFORM_SUFFIXES)]
    return [
        "{} looks like a seismic waveform file. Waveforms must never be in the repository; "
        "keep them under ~/sgtl/data/. Remove it with: git rm --cached \"{}\"".format(p, p)
        for p in bad
    ]


def check_sizes(root, files):
    problems = []
    for p in files:
        full = os.path.join(root, p)
        try:
            size = os.path.getsize(full)
        except OSError:
            continue  # deleted in the working folder; the manifest check reports tutorial files
        if size > MAX_BYTES:
            problems.append(
                "{} is {:.1f} MB (limit 2 MB). Large files do not belong in git; keep data and results "
                "under ~/sgtl/.".format(p, size / 1048576.0)
            )
    return problems


def check_manifest(root, files):
    manifest_path = os.path.join(root, MANIFEST)
    if not os.path.isfile(manifest_path):
        return ["{} is missing, so the tutorial's own files cannot be checked.".format(MANIFEST)]
    entries, problems = read_manifest(manifest_path)
    problems = ["{}: {}".format(MANIFEST, p) for p in problems]
    for rel in sorted(entries):
        full = os.path.join(root, rel)
        if not os.path.isfile(full):
            problems.append("{} belongs to the tutorial but is missing.".format(rel))
        elif sha256_file(full) != entries[rel]:
            problems.append(
                "{} belongs to the tutorial but was changed. Copy your edits into work/ if you want to "
                "keep them, then restore the file (bin/update-from-upstream --restore-upstream-owned).".format(rel)
            )
    for rel in files:
        if is_student_path(rel) or rel in RELEASE_META or rel in entries:
            continue
        problems.append(
            "{} was added outside work/ and project/. Your own files go in work/ or project/.".format(rel)
        )
    return problems


def check_notebooks(root, files):
    problems = []
    for rel in files:
        if not (is_student_path(rel) and rel.endswith(".ipynb")):
            continue
        full = os.path.join(root, rel)
        if not os.path.isfile(full):
            continue
        try:
            with open(full, "r", encoding="utf-8") as fh:
                nb = json.load(fh)
        except UnicodeDecodeError:
            problems.append("{} is not UTF-8 text, so it is not a valid notebook.".format(rel))
            continue
        except ValueError as exc:  # json.JSONDecodeError is a subclass of ValueError
            problems.append(
                "{} is not valid JSON ({}). Open an earlier version with `git log -p -- {}` or ask "
                "the mentor.".format(rel, exc, rel)
            )
            continue
        if not isinstance(nb, dict) or not isinstance(nb.get("cells"), list) or "nbformat" not in nb:
            problems.append("{} is valid JSON but not a notebook (no 'cells' list or 'nbformat').".format(rel))
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Check this copy of the SGTL tutorial: no data files, no files over 2 MB, tutorial "
        "files unchanged, notebooks in work/ and project/ readable."
    )
    parser.add_argument("--root", default=default_root(), help="repository root (default: the folder above .sgtl/)")
    parser.add_argument("--quiet", action="store_true", help="print only problems")
    args = parser.parse_args(argv)

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print("lint: {} is not a folder".format(root), file=sys.stderr)
        return 2
    files = tracked_files(root)

    checks = [
        ("no seismic data files", check_data_files),
        ("no files larger than 2 MB", check_sizes),
        ("tutorial files match .sgtl/MANIFEST.sha256", check_manifest),
        ("notebooks in work/ and project/ are valid JSON", check_notebooks),
    ]
    failed = 0
    for title, func in checks:
        problems = func(root, files)
        if problems:
            failed += 1
            print("FAIL  {}".format(title))
            for p in problems:
                print("      - {}".format(p))
        elif not args.quiet:
            print("ok    {}".format(title))
    if failed:
        print("\n{} of {} checks failed. Each line above says what to do; ask the mentor if unsure.".format(
            failed, len(checks)))
        return 1
    if not args.quiet:
        print("\nAll {} checks passed ({} tracked files).".format(len(checks), len(files)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
