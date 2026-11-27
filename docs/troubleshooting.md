# Troubleshooting

Start with `bin/sgtl doctor`: it checks the environment, the kernel, the thread caps and the folders, and says what
to do about each problem. Stuck for more than 20 minutes? Ask your mentor or open a **friction report** (GitHub →
Issues → New issue → Friction report). Never paste passwords, tokens or your JupyterLab link. SeisComP windows have
[their own list](seiscomp_gui.md#when-something-goes-wrong).

## Logging in

**Windows says `ssh` is "not recognized"?** Install OpenSSH Client: Settings → System → Optional features
([setup](setup.md), step 1).

**`Connection timed out` or `Connection refused`?** The address is wrong, or you are outside the network the server
accepts. Check the address; ask your mentor whether you need the university VPN.

**`Permission denied (publickey,password)`?** Wrong user name or password. Passwords are case-sensitive and stay
invisible while you type.

**`WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED`?** Stop. Do not continue; tell your mentor.

## Installing

**`bin/sgtl-install: No such file or directory`?** You are not in the repository: `cd ~/sgtl/tutorial`.

**`Permission denied` when you run a `bin/` script?** Run it with bash: `bash bin/sgtl-install`.

**A download fails?** Run the same command again. If it fails at the same step, put the last 20 lines of output in a
friction report.

**`Disk quota exceeded`?** `du -sh ~/sgtl/*` shows what is big. Ask your mentor before you delete anything you did
not make.

**`gh: command not found`, or another course program is missing?** The course environment is not active in this
terminal. Follow the last lines `sgtl-install` printed, open a new terminal, then run `bin/sgtl doctor`.

## JupyterLab and the tunnel

**The browser says "This site can't be reached" at `127.0.0.1:<port>`?** The tunnel is closed or uses another port.
Keep the tunnel window open. The port in the `ssh -L` command and in the link must be the one `sgtl-lab` printed.

**The tunnel says `bind: Address already in use`?** Something on your laptop, often an old tunnel, uses that port.
Close old tunnel windows, or use another local port: `ssh -N -L 8899:127.0.0.1:<port> <your_id>@<server>`, then
open `http://127.0.0.1:8899/lab?token=...`.

**`sgtl-lab` says the port is taken?** Your old JupyterLab may still run, or another user has that port. See
`bin/sgtl-lab --help`.

**JupyterLab asks for a token?** Use the full link with `?token=...` that `sgtl-lab` printed.

**The kernel "SGTL (Python 3.12)" is missing?** Run `bin/sgtl doctor`; if it says so, run `bin/sgtl-install --apply`
again.

**"Kernel restarting", or the kernel dies?** Run `bin/sgtl doctor` in a server terminal. If its numpy/PyTorch/PyGMT
stack check fails, the math libraries do not match: follow its rebuild advice with your mentor. Otherwise check the
memory cap, load less data and restart the kernel.

**Everything is slow?** Check `uptime` and `free -g` ([server manners](server_manners.md)), and shut down kernels you
are not using.

**PyGMT error about the GMT library or version?** You are not using the SGTL kernel. Switch the kernel;
`bin/sgtl doctor` reports the GMT version.

**A warning that Helvetica is missing?** Harmless: the house style falls back to a similar font.

**`NameError` in a later module?** Run the parameters and setup cells first. If the message names an earlier
function, paste your checked definition, with its constants and helpers, into the marked cell and run it.

**A file from an earlier module is missing?** The [lesson guide](notebooks/README.md) names the lesson that makes it:
finish that task and save its output. If you chose another file name, change it in the next module's parameters cell.

**The code runs, but no figure appears?** Run this in a code cell, then rerun the cell that makes the plot:

```python
%matplotlib inline
```

`fig.savefig(...)` only writes an image file. Use `plt.show()` before `plt.close(fig)` in the same cell, and
`fig.show()` for a PyGMT figure. Check that the cell finished without an error. An explorer's controls need a running
kernel: a notebook on GitHub shows only its saved output.

## Checks

**`NO PREDICTION`?** Run the task's prediction cell (`st.predict(...)`) first.

**`NOT STARTED`?** Your function still raises `NotImplementedError`.

**FAIL with category `forbidden-import`?** Your function uses a library this task forbids. Write the method yourself.

**FAIL with another category?** Read the message and test your function on a case you can work out by hand. Then ask
for the next hint level.

**The submission says no core tasks were selected?** Your work copy may not match the current release and module
id; `bin/sgtl diff MXX` shows the template changes. Ask your mentor how to move your work to the current template.
Do not edit check cells.

**The submission stops because a selected check did not pass?** Read this run's log and check output. An earlier PASS
does not replace this run: fix the task, save the notebook and submit again.

## Git

**The pre-commit hook refuses the commit?** Read its message. To take a file out of the commit:
`git restore --staged <file>`.

**`git push` is rejected (non-fast-forward)?** Run `git pull`, then push again. Never force-push.

**`bin/update-from-upstream` reports a conflict?** Stop and ask your mentor.

**`git commit` asks who you are?** Set `user.name` and `user.email` ([setup](setup.md), step 7).
