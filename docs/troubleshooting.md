# Troubleshooting

Start with `bin/sgtl doctor`: it checks the environment, the kernel, the thread caps and the folders, and says
what to do for each problem it finds. If you are stuck for more than 20 minutes, ask your mentor or open a
**friction report** (GitHub → Issues → New issue → Friction report). Never paste passwords, tokens or your
JupyterLab link.

## Logging in

| Symptom | Likely cause and fix |
|---|---|
| `ssh` is "not recognized" (Windows) | Install OpenSSH Client: Settings → System → Optional features ([setup.md](setup.md), step 1). |
| `Connection timed out` or `Connection refused` | Wrong server address, or you are outside the network the server accepts. Check the address; ask your mentor whether you need the university VPN. |
| `Permission denied (publickey,password)` | Wrong user name or password. Passwords are case-sensitive and invisible while you type. |
| `WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED` | Stop. Do not continue; tell your mentor. |

## Installing

| Symptom | Likely cause and fix |
|---|---|
| `bin/sgtl-install: No such file or directory` | You are not in the repository: `cd ~/sgtl/tutorial`. |
| `Permission denied` when running a `bin/` script | Run it with bash: `bash bin/sgtl-install`. |
| A download fails | Run the same command again. If it fails at the same step, put the last 20 lines of output in a friction report. |
| `Disk quota exceeded` | `du -sh ~/sgtl/*` shows what is big. Ask your mentor before deleting anything you did not make. |
| `gh: command not found` (or another course program) | The course environment is not active in this terminal. Follow the last lines `sgtl-install` printed, open a new terminal, then run `bin/sgtl doctor`. |

## JupyterLab and the tunnel

| Symptom | Likely cause and fix |
|---|---|
| Browser: "This site can't be reached" at `127.0.0.1:<port>` | The tunnel is not open or uses another port. Keep the tunnel window open; the port in the `ssh -L` command and in the link must be the one `sgtl-lab` printed. |
| Tunnel: `bind: Address already in use` | Something on your laptop already uses that port (often an old tunnel). Close old tunnel windows, or use another local port: `ssh -N -L 8899:127.0.0.1:<port> <your_id>@<server>`, then open `http://127.0.0.1:8899/lab?token=...`. |
| `sgtl-lab` says the port is taken | Your old JupyterLab may still run, or another user has that port. See `bin/sgtl-lab --help`. |
| JupyterLab asks for a token | Use the full link with `?token=...` that `sgtl-lab` printed. |
| Kernel "SGTL (Python 3.12)" is missing | Run `bin/sgtl doctor`; if it says so, `bin/sgtl-install --apply` again. |
| "Kernel restarting" or the kernel dies | Usually the memory cap. Load less data, delete big variables (`del x`), restart the kernel. |
| Everything is slow | Check `uptime` and `free -g` ([server_manners.md](server_manners.md)); shut down kernels you are not using. |
| PyGMT error about the GMT library or version | You are not using the SGTL kernel. Switch kernel; `bin/sgtl doctor` reports the GMT version. |
| Warning that Helvetica is missing | Harmless: the house style falls back to a similar font. |

## Checks

| Message | Meaning |
|---|---|
| No prediction logged | Run the prediction cell (`st.predict(...)`) for this task first. |
| `NOT STARTED` | Your function still raises `NotImplementedError`. |
| FAIL with category `forbidden-import` | Your function uses a library this task forbids. Write the method yourself. |
| FAIL with another category | Read the fixed message, test your function on a case you can work out by hand, then ask for the next hint level. |

## Git

| Symptom | Likely cause and fix |
|---|---|
| The pre-commit hook refuses the commit | Read its message. To take a file out of the commit: `git restore --staged <file>`. |
| `git push` is rejected (non-fast-forward) | Run `git pull`, then push again. Never force-push. |
| `bin/update-from-upstream` reports a conflict | Stop and ask your mentor. |
| `git commit` asks who you are | Set `user.name` and `user.email` ([setup.md](setup.md), step 7). |
