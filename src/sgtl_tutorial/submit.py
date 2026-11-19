"""``sgtl submit MXX``: run your work notebook of a module from top to bottom and send it for review.

Plain words:

* Without ``--apply`` nothing runs and nothing changes: the command checks your copy and prints the plan.
* With ``--apply`` it runs ``work/MXX_slug/MXX_slug.ipynb`` from the first cell to the last with papermill (a
  program that runs a notebook without a browser), on one core with the thread limits of the course kernel,
  at low priority (nice) and with a time limit. The file you edit is never changed: the run writes an executed
  copy under ``work/submissions/MXX/<UTC time>/`` together with a run log and ``submission.json`` (what ran,
  when, the SHA-256 fingerprints of your notebook, of the executed copy and of the products the run wrote,
  read from ``work/.sgtl/runs.jsonl``).
* If every cell ran, it records these files as one commit on a new branch ``submit/MXX-<UTC time>``, pushes
  that branch to YOUR private copy (``origin``) and opens a pull request there with the mentor as reviewer.
  Your current branch and the files in your folder stay as they are.
* It pushes only to a PRIVATE repository on GitHub. It stops before anything runs when any address of
  ``origin`` (``git remote get-url --all`` and ``--push --all``) points to the public course repository, when
  ``origin`` pushes anywhere that is not a GitHub repository, and when GitHub (asked with
  ``gh repo view OWNER/NAME --json visibility``) does not answer PRIVATE for every push address: public,
  internal and "could not tell" (for example gh not logged in) all stop it. It asks again just before the
  push, so a change of ``origin`` during the run stops it too.

Copyright (c) 2026 Minseong Seo (SGTL, Seoul National University). MIT License.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import _paths
from .session import THREAD_VARS, release_version, user_name

__all__ = ["submit", "DEFAULT_UPSTREAM_SLUG", "MENTOR_LOGIN"]

DEFAULT_UPSTREAM_SLUG = "seismoseo/SGTL-earthquake-source-tutorial"
MENTOR_LOGIN = "seismoseo"
MAX_BYTES = 2 * 1024 * 1024  # the limit of the pre-commit check (.sgtl/lint.py)
WAVEFORM_SUFFIXES = (".sac", ".mseed", ".miniseed", ".ms", ".msd", ".seed")
DEFAULT_TIMEOUT_MIN = 120
NICE = 10
IMAGE_TYPES = ("image/png", "image/jpeg", "image/gif", "image/svg+xml", "application/pdf")
TEXT_LIMIT = 20000  # characters kept per output when an executed copy must be made smaller
MODULE_RE = re.compile(r"^M\d{2}$")
GITHUB_HOSTS = ("github.com", "www.github.com", "ssh.github.com")
GH_TIMEOUT_S = 60
_SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*)://(.*)$", re.S)
_SCP_RE = re.compile(r"^(?:[^@/\[]*@)?(\[[^\]]*\]|[^:/\[]+):(.*)$", re.S)
_OWNER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")
_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


# ----------------------------------------------------------------------------- small helpers
def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rel(path: Path, repo: Path) -> str:
    try:
        return Path(path).resolve().relative_to(Path(repo).resolve()).as_posix()
    except ValueError:
        return _paths.short_path(path)


def _utc_stamp() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _utc_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(repo: Path, *args: str, env: Optional[Dict[str, str]] = None, check: bool = True) -> str:
    proc = subprocess.run(["git", *args], cwd=str(repo), env=env, text=True, capture_output=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])} failed: {proc.stderr.strip()[:400]}")
    return proc.stdout.strip() if proc.returncode == 0 else ""


def upstream_slug() -> str:
    return os.environ.get("SGTL_UPSTREAM_SLUG", "").strip() or DEFAULT_UPSTREAM_SLUG


def mentor_login() -> str:
    return os.environ.get("SGTL_MENTOR", "").strip() or MENTOR_LOGIN


def _host_only(netloc: str) -> str:
    """The host of ``user@host:port`` or ``[user@host:port]``, lower case, without a final dot."""
    h = netloc.rsplit("@", 1)[-1]
    if h.startswith("["):
        h = h[1:].split("]", 1)[0].rsplit("@", 1)[-1]
        if h.count(":") == 1:
            h = h.split(":", 1)[0]
    else:
        h = h.split(":", 1)[0]
    return h.strip().rstrip(".").lower()


def split_remote(url: str) -> Tuple[Optional[str], List[str]]:
    """(host, path parts) of a git remote address, the way git reads it.

    Forms: ``scheme://[user@]host[:port]/path`` (https, ssh, git, ...), the short ssh form
    ``[user@]host:path`` and a local path (host None). ``%xx`` escapes, ``.``, ``..`` and repeated or
    trailing slashes are resolved. A ``transport::address`` (a remote helper) and ``file://`` have no host.
    """
    u = (url or "").strip()
    host: Optional[str] = None
    path = u
    m = _SCHEME_RE.match(u)
    if m:
        netloc, _, path = m.group(2).partition("/")
        path = path.split("?", 1)[0].split("#", 1)[0]
        host = None if m.group(1).lower() == "file" else _host_only(netloc)
    elif "::" in u.split("/", 1)[0]:
        path = u.split("::", 1)[1]
    elif not re.match(r"^[A-Za-z]:[\\/]", u):  # a drive letter starts a local Windows path
        m = _SCP_RE.match(u)
        if m:
            host, path = _host_only(m.group(1)), m.group(2)
    parts: List[str] = []
    for part in re.split(r"[/\\]+", unquote(path)):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return host or None, parts


def _strip_suffixes(name: str) -> str:
    while True:
        low = name.lower()
        if low.endswith(".git"):
            name = name[:-4]
        elif low.endswith(".wiki"):
            name = name[:-5]
        else:
            return name


def github_slug(url: str) -> Optional[str]:
    """``owner/name`` when ``url`` is a repository on github.com (any https, ssh or short form), else None."""
    host, parts = split_remote(url)
    if host not in GITHUB_HOSTS or len(parts) != 2:
        return None
    owner, name = parts[0], parts[1]
    if name.lower().endswith(".git"):
        name = name[:-4]
    if not (_OWNER_RE.match(owner) and _NAME_RE.match(name)) or name in (".", ".."):
        return None
    return f"{owner}/{name}"


def _upstream_slugs() -> set:
    return {DEFAULT_UPSTREAM_SLUG.lower(), upstream_slug().lower()}


def is_upstream(url: str) -> bool:
    """True when the address ends in the public course repository ``owner/name`` (any host, form or case)."""
    _, parts = split_remote(url)
    if len(parts) < 2:
        return False
    return f"{parts[-2]}/{_strip_suffixes(parts[-1])}".lower() in _upstream_slugs()


def repo_visibility(gh: str, slug: str) -> Tuple[Optional[str], str]:
    """('PRIVATE' | 'PUBLIC' | 'INTERNAL', '') as GitHub reports it, or (None, why it could not tell)."""
    env = dict(os.environ, GH_HOST="github.com", GH_PROMPT_DISABLED="1", NO_COLOR="1")
    env.pop("GH_REPO", None)
    try:
        proc = subprocess.run([gh, "repo", "view", slug, "--json", "visibility"], text=True, capture_output=True,
                              env=env, stdin=subprocess.DEVNULL, timeout=GH_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"gh did not answer: {exc.__class__.__name__}"
    if proc.returncode != 0:
        lines = [ln.strip() for ln in (proc.stderr or proc.stdout).splitlines() if ln.strip()]
        return None, f"gh: {lines[0][:200]}" if lines else f"gh stopped with exit code {proc.returncode}"
    try:
        vis = json.loads(proc.stdout).get("visibility")
    except (ValueError, AttributeError):
        vis = None
    if not isinstance(vis, str) or not vis.strip():
        return None, "gh gave no visibility"
    return vis.strip().upper(), ""


def check_push_targets(push_urls: Sequence[str], gh: Optional[str]) -> Tuple[List[Tuple[str, str]], List[str]]:
    """([(url, owner/name)] of the push addresses that are PRIVATE GitHub repositories, [problems])."""
    targets: List[Tuple[str, str]] = []
    problems: List[str] = []
    if not push_urls:
        return targets, ["origin has no push address (git remote get-url --push --all origin is empty)"]
    for url in push_urls:
        slug = github_slug(url)
        if not slug:
            problems.append(f"origin pushes to {url}, which is not a GitHub repository address, so sgtl submit "
                            "cannot tell whether it is private")
            continue
        if gh is None:
            problems.append(f"the GitHub command-line tool gh was not found, so sgtl submit cannot check that "
                            f"github.com/{slug} is private (gh comes with the course environment)")
            continue
        vis, why = repo_visibility(gh, slug)
        if vis == "PRIVATE":
            targets.append((url, slug))
        elif vis:
            problems.append(f"github.com/{slug} is {vis.lower()}, not private: others could read your solutions "
                            "there. sgtl submit only pushes to your private copy (bin/make-private-copy, "
                            "docs/git_workflow.md)")
        else:
            problems.append(f"could not tell whether github.com/{slug} is private ({why}). Check that gh is "
                            "logged in ('gh auth status'; docs/git_workflow.md) and the network works, then try again")
    return targets, problems


def find_gh() -> Optional[str]:
    env = os.environ.get("SGTL_GH", "").strip()
    if env:
        return env
    found = shutil.which("gh")
    if found:
        return found
    home = Path(os.environ.get("SGTL_HOME") or Path.home() / "sgtl")
    cand = home / "envs" / "sgtl" / "bin" / "gh"
    return str(cand) if cand.is_file() else None


def work_notebook(repo: Path, mid: str) -> Optional[Path]:
    found = sorted(repo.glob(f"work/{mid}_*/{mid}_*.ipynb"))
    return found[0] if found else None


def _count_lines(path: Path) -> int:
    try:
        with open(path, "rb") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def _records_after(path: Path, start: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as fh:
            for n, line in enumerate(fh):
                if n < start or not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict):
                    out.append(rec)
    except OSError:
        pass
    return out


def _skip_work_path(rel: str) -> bool:
    parts = rel.split("/")
    return (rel.startswith(("work/submissions/", "work/.sgtl/")) or ".ipynb_checkpoints" in parts
            or "__pycache__" in parts)


def _snapshot_work(repo: Path) -> Dict[str, Tuple[int, int]]:
    """{path: (size, mtime_ns)} of the files in work/ (not submissions/, .sgtl/ or checkpoints)."""
    snap: Dict[str, Tuple[int, int]] = {}
    root = repo / "work"
    if not root.is_dir():
        return snap
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".ipynb_checkpoints", "__pycache__")]
        for name in filenames:
            p = Path(dirpath) / name
            rel = p.relative_to(repo).as_posix()
            if _skip_work_path(rel) or p.is_symlink():
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            snap[rel] = (st.st_size, st.st_mtime_ns)
    return snap


def _committable(path: Path) -> Optional[str]:
    """None when the file may go into git, else the reason it may not (same rules as the pre-commit check)."""
    if path.name.lower().endswith(WAVEFORM_SUFFIXES):
        return "a waveform file"
    try:
        size = path.stat().st_size
    except OSError:
        return "missing"
    if size > MAX_BYTES:
        return f"{size / 1048576:.1f} MB (limit 2 MB)"
    return None


# ----------------------------------------------------------------------------- the run
def papermill_command(nb: Path, out: Path, cwd: Path, kernel: Optional[str]) -> List[str]:
    cmd = [sys.executable, "-m", "papermill", str(nb), str(out), "--cwd", str(cwd), "--log-output",
           "--no-progress-bar"]
    if kernel:
        cmd += ["--kernel", kernel]
    return cmd


def _run_env() -> Dict[str, str]:
    env = dict(os.environ)
    for var in THREAD_VARS:
        env[var] = "1"
    env["NUMPY_MADVISE_HUGEPAGE"] = "0"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _lower_priority() -> None:  # runs in the child before papermill starts
    try:
        os.nice(NICE)
    except OSError:
        pass


def run_notebook(cmd: Sequence[str], log_path: Path, timeout_s: float) -> Tuple[int, float, bool]:
    """Run ``cmd`` (papermill), output to ``log_path``; return (exit code, seconds, timed out)."""
    t0 = time.time()
    timed_out = False
    with open(log_path, "w", encoding="utf-8") as log:
        log.write("command: " + " ".join(cmd) + "\n")
        log.flush()
        proc = subprocess.Popen(list(cmd), stdout=log, stderr=subprocess.STDOUT, env=_run_env(),
                                start_new_session=True, preexec_fn=_lower_priority)  # noqa: PLW1509
        try:
            rc = proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            for sig, wait in ((signal.SIGTERM, 20), (signal.SIGKILL, 20)):
                try:
                    os.killpg(proc.pid, sig)
                except OSError:
                    pass
                try:
                    proc.wait(timeout=wait)
                    break
                except subprocess.TimeoutExpired:
                    continue
            rc = proc.returncode if proc.returncode is not None else -9
        except KeyboardInterrupt:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait()
            raise
        seconds = time.time() - t0
        log.write(f"\nexit code {rc} after {seconds:.0f} s" + (" (time limit reached)" if timed_out else "") + "\n")
    return rc, seconds, timed_out


def executed_summary(nb_path: Path) -> Dict[str, Any]:
    """Code cells, how many ran, and the first cell that stopped with an error (index and error name)."""
    try:
        nb = json.loads(nb_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"readable": False}
    code = [(i, c) for i, c in enumerate(nb.get("cells", [])) if c.get("cell_type") == "code"]
    ran = sum(1 for _, c in code if c.get("execution_count") is not None)
    first_error = None
    for i, c in code:
        for o in c.get("outputs", []) or []:
            if o.get("output_type") == "error":
                first_error = {"cell": i, "error": str(o.get("ename", ""))[:80]}
                break
        if first_error:
            break
    return {"readable": True, "code_cells": len(code), "ran": ran, "first_error": first_error}


def shrink_notebook(nb_path: Path, limit: int = MAX_BYTES) -> Optional[str]:
    """Make an executed copy small enough for git: drop pictures, then shorten long text outputs.

    Returns a note on what was removed, or None if the file was small enough already.
    """
    if nb_path.stat().st_size <= limit:
        return None
    nb = json.loads(nb_path.read_text(encoding="utf-8"))
    removed = shortened = 0
    for cell in nb.get("cells", []):
        for out in cell.get("outputs", []) or []:
            data = out.get("data")
            if isinstance(data, dict):
                for key in [k for k in data if k in IMAGE_TYPES]:
                    del data[key]
                    removed += 1
                    data.setdefault("text/plain", "[picture removed by sgtl submit to keep the file under 2 MB]")
    text = json.dumps(nb, indent=1, ensure_ascii=False) + "\n"
    if len(text.encode("utf-8")) > limit:
        for cell in nb.get("cells", []):
            for out in cell.get("outputs", []) or []:
                for key, val in list((out.get("data") or {}).items()) + [("text", out.get("text"))]:
                    joined = "".join(val) if isinstance(val, list) else val
                    if isinstance(joined, str) and len(joined) > TEXT_LIMIT:
                        cut = joined[:TEXT_LIMIT] + "\n[... output shortened by sgtl submit ...]\n"
                        if key == "text":
                            out["text"] = cut
                        else:
                            out["data"][key] = cut
                        shortened += 1
        text = json.dumps(nb, indent=1, ensure_ascii=False) + "\n"
    nb_path.write_text(text, encoding="utf-8")
    note = f"{removed} picture(s) removed, {shortened} long output(s) shortened to stay under 2 MB"
    if len(text.encode("utf-8")) > limit:
        note += "; still larger than 2 MB, so the executed copy is not committed"
    return note


# ----------------------------------------------------------------------------- git and GitHub
def origin_urls(repo: Path) -> Tuple[List[str], List[str]]:
    """Every fetch and every push address of ``origin``, as git uses them (insteadOf rules applied)."""
    def urls(*flags: str) -> List[str]:
        out = _git(repo, "remote", "get-url", *flags, "origin", check=False)
        return [u.strip() for u in out.splitlines() if u.strip()]
    return urls("--all"), urls("--push", "--all")


def commit_on_branch(repo: Path, branch: str, rels: Sequence[str], message: str) -> str:
    """One commit with ``rels`` on top of HEAD, stored as a NEW branch; the working tree and index are untouched."""
    head = _git(repo, "rev-parse", "--verify", "HEAD^{commit}")
    tmp = tempfile.mkdtemp(prefix="sgtl-submit-")
    try:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(tmp) / "index"))
        _git(repo, "read-tree", head, env=env)
        _git(repo, "update-index", "--add", "--", *rels, env=env)
        tree = _git(repo, "write-tree", env=env)
        commit = _git(repo, "commit-tree", tree, "-p", head, "-m", message)
        _git(repo, "update-ref", f"refs/heads/{branch}", commit, "")  # "" = the branch must not exist yet
        return commit
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def open_pull_request(gh: str, slug: str, base: str, branch: str, title: str, body_file: Path,
                      reviewer: str) -> Tuple[int, str]:
    base_cmd = [gh, "pr", "create", "--repo", slug, "--base", base, "--head", branch, "--title", title,
                "--body-file", str(body_file)]
    proc = subprocess.run(base_cmd + ["--reviewer", reviewer], text=True, capture_output=True)
    if proc.returncode == 0:
        return 0, proc.stdout.strip()
    print(f"Could not ask {reviewer} for a review ({proc.stderr.strip()[:200]}); opening the pull request "
          "without a reviewer.")
    proc = subprocess.run(base_cmd, text=True, capture_output=True)
    if proc.returncode == 0:
        print(f"Add the mentor as a collaborator of your private copy (docs/git_workflow.md), then on the pull "
              f"request page choose Reviewers -> {reviewer}.")
        return 0, proc.stdout.strip()
    return proc.returncode, proc.stderr.strip()[:400]


def _pr_body(mid: str, stamp: str, record: Dict[str, Any], files: Sequence[str]) -> str:
    s = record.get("executed", {})
    lines = [f"Submission of {mid} made by `sgtl submit {mid} --apply` at {stamp} (UTC).", "",
             f"- notebook: `{record['notebook']}` (sha256 `{record['notebook_sha256'][:12]}`)",
             f"- run: {s.get('ran', '?')} of {s.get('code_cells', '?')} code cells ran, "
             f"{record['seconds']:.0f} s, release {record['release']}",
             f"- products logged in work/.sgtl/runs.jsonl during the run: {len(record['products'])}",
             f"- checks during the run: " + (", ".join(f"{t} {v}" for t, v in sorted(record['checks'].items()))
                                              or "none"),
             "", "Files in this commit:", ""]
    lines += [f"- `{f}`" for f in files]
    lines += ["", "Write below what you finished, what you skipped and any question you have."]
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------- the command
def _say(ok: bool, text: str) -> None:
    print(("  " if ok else "  !! ") + text)


def submit(mid: str, *, apply: bool = False, timeout_min: float = DEFAULT_TIMEOUT_MIN, base: str = "main",
           kernel: Optional[str] = None, no_pr: bool = False) -> int:
    mid = mid.upper()
    if not MODULE_RE.match(mid):
        print("Module ids look like M04.")
        return 2
    repo = _paths.repo_root()
    print(f"sgtl submit {mid}: " + ("running (--apply)" if apply else
                                     "DRY RUN (nothing runs and nothing changes; add --apply to do it)"))

    # Checks: they only look, so they run in the dry run too.
    if not (repo / ".git").exists():
        print(f"{_paths.short_path(repo)} is not a git clone; make your private copy first (docs/git_workflow.md).")
        return 1
    fetch_urls, push_urls = origin_urls(repo)
    if not fetch_urls and not push_urls:
        print("This copy has no remote called origin. Make your private copy first: bin/make-private-copy")
        return 1
    public = [u for u in fetch_urls + push_urls if is_upstream(u)]
    if public:
        print(f"origin points to the public course repository ({public[0]}), so sgtl submit stops here: it only "
              "ever pushes to your private copy. Make it first: bin/make-private-copy (docs/git_workflow.md).")
        return 1
    nb = work_notebook(repo, mid)
    if nb is None:
        print(f"No work notebook for {mid} (work/{mid}_*/{mid}_*.ipynb). Start it with: sgtl new {mid}")
        return 1
    head = _git(repo, "rev-parse", "--verify", "-q", "HEAD^{commit}", check=False)
    if not head:
        print("This copy has no commit yet; commit your work first (docs/git_workflow.md).")
        return 1
    try:
        meta = json.loads(nb.read_text(encoding="utf-8")).get("metadata", {})
    except ValueError:
        print(f"{_rel(nb, repo)} is not valid notebook JSON; open it in JupyterLab and save it again.")
        return 1
    kernel = kernel or (meta.get("kernelspec") or {}).get("name") or "sgtl"
    stamp = _utc_stamp()
    branch = f"submit/{mid}-{stamp}"
    out_dir = repo / "work" / "submissions" / mid / stamp
    gh = find_gh()
    targets, push_problems = check_push_targets(push_urls, gh)
    slug = targets[0][1] if targets else None
    have_pm = subprocess.run([sys.executable, "-c", "import papermill"], capture_output=True).returncode == 0
    _say(True, f"notebook  {_rel(nb, repo)}  (sha256 {_sha256(nb)[:12]}; the file on disk: save it first)")
    _say(True, f"run       papermill with kernel '{kernel}', 1 core (thread limits 1), nice {NICE}, "
               f"stops after {timeout_min:g} min")
    _say(True, f"results   {_rel(out_dir, repo)}/  (executed copy, run.log, submission.json)")
    _say(True, f"branch    {branch}  (from your current commit; your branch and files stay as they are)")
    where = ", ".join(f"github.com/{t}, private" for _, t in targets) or "nowhere: see the problems below"
    _say(True, f"push      git push origin {branch}   ({where})")
    if not no_pr:
        _say(True, f"review    gh pr create --base {base} --head {branch} --reviewer {mentor_login()}")
    problems = list(push_problems)
    if not have_pm:
        problems.append("papermill is not installed in this Python; run bin/sgtl-install --apply")
    for p in problems:
        _say(False, p)
    if not apply:
        print("Dry run: nothing ran. Run 'sgtl submit " + mid + " --apply' to run the notebook and submit it.")
        return 1 if problems else 0
    if problems:
        print("Nothing ran and nothing was committed or pushed.")
        return 1

    # The run.
    out_dir.mkdir(parents=True, exist_ok=False)
    executed = out_dir / f"{nb.stem}.executed.ipynb"
    log_path = out_dir / "run.log"
    progress = _paths.progress_path(repo)
    runs = repo / "work" / ".sgtl" / "runs.jsonl"
    p0, r0 = _count_lines(progress), _count_lines(runs)
    before = _snapshot_work(repo)
    nb_sha = _sha256(nb)
    started = _utc_iso()
    print(f"Running {_rel(nb, repo)} ... (full output: {_rel(log_path, repo)})")
    rc, seconds, timed_out = run_notebook(papermill_command(nb, executed, nb.parent, kernel), log_path,
                                          timeout_min * 60)
    ended = _utc_iso()
    summary = executed_summary(executed) if executed.is_file() else {"readable": False}
    events = _records_after(progress, p0)
    checks: Dict[str, str] = {}
    for ev in events:
        if ev.get("event") == "check" and isinstance(ev.get("task"), str):
            if checks.get(ev["task"]) != "PASS":
                checks[ev["task"]] = str(ev.get("status"))
    run_recs = _records_after(runs, r0)
    products: Dict[str, str] = {}
    for rec in run_recs:
        for path, sha in (rec.get("products") or {}).items():
            products[f"{rec.get('cluster', '?')}/{path}"] = sha
    after = _snapshot_work(repo)
    changed = sorted(rel for rel, sig in after.items() if before.get(rel) != sig and rel != _rel(nb, repo))
    work_files = {rel: _sha256(repo / rel) for rel in changed}
    note = shrink_notebook(executed) if executed.is_file() else None
    record = {
        "module": mid, "stamp": stamp, "user": user_name(), "release": release_version(repo),
        "started": started, "ended": ended, "seconds": round(seconds, 1), "returncode": rc,
        "timed_out": timed_out, "timeout_min": timeout_min, "kernel": kernel, "cores": 1, "nice": NICE,
        "notebook": _rel(nb, repo), "notebook_sha256": nb_sha,
        "template_sha": (meta.get("sgtl") or {}).get("template_sha"),
        "executed_notebook": _rel(executed, repo) if executed.is_file() else None,
        "executed_sha256": _sha256(executed) if executed.is_file() else None,
        "executed_note": note, "executed": summary,
        "progress_lines": [p0, p0 + len(events)], "runs_lines": [r0, r0 + len(run_recs)],
        "checks": checks, "runs": run_recs, "products": products, "work_files": work_files,
        "git_head": head, "branch": branch,
    }
    (out_dir / "submission.json").write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n",
                                             encoding="utf-8")
    if rc != 0 or not summary.get("readable") or summary.get("first_error"):
        why = "the time limit was reached" if timed_out else (
            f"cell {summary['first_error']['cell']} stopped with {summary['first_error']['error']}"
            if summary.get("first_error") else f"papermill stopped with exit code {rc}")
        print(f"The notebook did not run to the end: {why}. Nothing was committed or pushed.")
        print(f"Read {_rel(log_path, repo)} and the executed copy, fix your notebook, save it and submit again.")
        return 1
    print(f"Ran {summary['ran']} of {summary['code_cells']} code cells in {seconds:.0f} s; "
          f"{len(products)} product fingerprint(s) from work/.sgtl/runs.jsonl.")
    if note:
        print(f"Executed copy: {note}.")

    # Ask again just before the push: the run may have changed origin.
    fetch_now, push_now = origin_urls(repo)
    if (fetch_now, push_now) != (fetch_urls, push_urls):
        print("origin changed while the notebook ran (git remote -v shows its addresses now), so nothing was "
              "committed or pushed. Check origin and submit again.")
        return 1
    _, push_problems = check_push_targets(push_now, gh)
    for p in push_problems:
        _say(False, p)
    if push_problems:
        print("Nothing was committed or pushed.")
        return 1

    # The commit on a new branch.
    cands = [nb, out_dir / "submission.json", log_path, executed, repo / "work" / "ai_log" / f"{mid}.md",
             progress, runs] + [repo / rel for rel in changed]
    files, skipped = [], []
    for p in cands:
        if not p.is_file():
            continue
        why_not = _committable(p)
        if why_not:
            skipped.append(f"{_rel(p, repo)}: {why_not}")
        else:
            files.append(_rel(p, repo))
    for s in skipped:
        print(f"not committed: {s}")
    message = f"Submit {mid} ({stamp})\n\nMade by sgtl submit: {summary['ran']} code cells ran in {seconds:.0f} s."
    commit = commit_on_branch(repo, branch, files, message)
    print(f"committed {len(files)} file(s) as {commit[:12]} on the new branch {branch}")
    proc = subprocess.run(["git", "push", "origin", f"refs/heads/{branch}:refs/heads/{branch}"], cwd=str(repo),
                          text=True, capture_output=True)
    if proc.returncode != 0:
        print(f"git push failed: {proc.stderr.strip()[:400]}")
        print(f"Your submission is on the local branch {branch}; push it later with: git push origin {branch}")
        return 1
    print(f"pushed {branch} to your private copy")
    if no_pr:
        return 0
    with tempfile.TemporaryDirectory(prefix="sgtl-submit-") as tmp:
        body = Path(tmp) / "pull_request.md"
        body.write_text(_pr_body(mid, stamp, record, files), encoding="utf-8")
        code, text = open_pull_request(gh or "gh", slug or "", base, branch, f"Submit {mid} ({stamp})", body,
                                       mentor_login())
    if code != 0:
        print(f"Opening the pull request failed: {text}")
        print(f"Open it by hand: gh pr create --base {base} --head {branch}")
        return 1
    print(f"pull request: {text}")
    return 0
