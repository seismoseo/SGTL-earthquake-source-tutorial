# Git workflow

**git** records snapshots (**commits**) of your files, so you can see and undo changes. A **repository** is a folder
that git tracks; a **branch** is a named line of commits; **upstream** is the public tutorial your copy came from.
Practice first with the Software Carpentry lesson "Version Control with Git"
(<https://swcarpentry.github.io/git-novice/>).

## Who owns what

| Path | Owner | What it means for you |
|---|---|---|
| `work/` (notebooks, `ai_log/`, `.sgtl/progress.jsonl`) | you | Edit and commit freely. |
| `project/` | you | Your research project. |
| everything else | the tutorial (upstream) | Read it, never edit it. Updates replace it. |

A **pre-commit hook** is a check that runs before every commit. It stops a commit that changes tutorial files, adds a
file larger than 2 MB or adds a waveform file (`.sac`, `.mseed`, ...). GitHub runs the same checks on every push. If your
mentor asks you to change a tutorial file, they will tell you how.

## Make your private copy (once, in M00)

Your own **private** GitHub repository keeps the tutorial's history, so you can save your work, get updates and send
modules for review. Do not use GitHub's Fork button: a fork of a public repository cannot be private.

```bash
cd ~/sgtl/tutorial
bin/make-private-copy            # dry run: read what it will do
bin/make-private-copy --apply    # creates the private repository in your GitHub account
git remote -v                    # origin = your private copy, upstream = the public tutorial
```

Then add your mentor: your private repository on GitHub → Settings → Collaborators → Add people → your mentor's
GitHub user name. Keep the repository private, during the course and after it.

## Every day

```bash
git status                                   # what changed?
git add work/M04_earthquake_catalogs/ work/ai_log/M04.md work/.sgtl/
git commit -m "M04: select_sequence passes; Explain T2 written"
git push
```

The last path holds the prediction, check and run records your mentor needs. Check `git diff --cached --stat` before
you commit: no waveform files and no credentials. Commit at least once a day, with a message that says what you did.
If a notebook grows near 2 MB, clear large outputs (Edit → Clear Outputs of a cell) before you commit.

## Get tutorial updates

When your mentor announces a new release (see `CHANGELOG.md`):

```bash
git status                           # commit your work first; the update needs a clean tree
bin/update-from-upstream             # dry run: shows what will change
bin/update-from-upstream --apply     # merges the new release; work/ and project/ are not touched
```

If it reports a conflict, stop and ask your mentor. If the changelog says so, run `bin/sgtl-install --apply` again.

## Submit a module by pull request

A **pull request** (PR) asks someone to review a branch before it is merged.

1. Commit your current work before you change branches. When you start a module, run `git switch main`,
   `git pull --ff-only`, then `git switch -c m04` (your module's id) in the terminal.
2. Work and commit on that branch. The first push is `git push -u origin m04`; after that, `git push`.
3. When the module is ready, run `bin/sgtl submit M04` (dry run), then `bin/sgtl submit M04 --apply`
   ([save and submit](how_this_tutorial_works.md#save-and-submit)); add `--include-optional` for stretch and research
   work. It commits the record on a **new** branch `submit/M04-<UTC time>` and opens a PR for your mentor. Your
   working branch stays `m04`.
4. Read the comments on the PR. Revise your notebook, save and commit on `m04`, then submit again: this makes a new
   run record and a new PR. Link the earlier PR in the new one; your mentor can close the old one. A push to `m04`
   does not update a PR whose branch is `submit/M04-...`.
5. After approval, merge the PR on GitHub (or `gh pr merge <PR-number> --merge`). Commit any remaining local work,
   then `git switch main` and `git pull --ff-only` before the next module.

If your mentor asks for a manual review instead, open a PR from your working branch:

```bash
gh pr create --base main --head m04 --title "M04 Earthquake catalogs"
```

List what you finished, what you skipped and your questions. New pushes to `m04` update this PR. It has no automatic
submission-run record, so agree with your mentor how to show that the notebook runs.

## Never

- `git push --force`, or rewriting commits you already pushed;
- committing data, passwords, tokens, your JupyterLab link or files larger than 2 MB;
- editing tutorial files outside `work/` and `project/`;
- making your private copy public. At the end of the course your copy goes to the lab, still private.
