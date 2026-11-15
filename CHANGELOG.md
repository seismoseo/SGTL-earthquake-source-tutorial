# Changelog

All notable changes to the SGTL earthquake source tutorial. Versions follow `vMAJOR.MINOR.PATCH`.
To get a new version into your private copy, run `bin/update-from-upstream` (dry run), then
`bin/update-from-upstream --apply` (see [docs/git_workflow.md](docs/git_workflow.md)).

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
