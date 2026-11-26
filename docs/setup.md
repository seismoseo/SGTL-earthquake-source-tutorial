# Setup: from your laptop to the first notebook

Follow these steps in order. Each step says what to type and what you should see. Text in angle brackets is a
placeholder: replace `<your_id>` with your server user name and `<server>` with the server address your mentor
gave you (type them without the brackets). 한국어: [setup_ko.md](setup_ko.md).

**You need:** a laptop, your lab server account (user name, first password, server address) and about two hours.

## 1. Open a terminal on your laptop

A **terminal** is a window where you type commands; the **shell** is the program that runs them.

- **Windows 10/11:** press the Windows key, type `PowerShell`, open **Windows PowerShell**. Type `ssh -V` and press
  Enter; you should see a version such as `OpenSSH_for_Windows_9.5`. If you see "not recognized", open
  Settings → System → Optional features → Add a feature → **OpenSSH Client**, then reopen PowerShell.
- **macOS:** press Cmd+Space, type `Terminal`, press Enter. `ssh` is already installed.
- **Xshell or PuTTY (Windows):** you may use these instead. Xshell: File → New → Host = `<server>`, Port 22 → Connect.
  PuTTY: Host Name = `<your_id>@<server>`, Port 22, Connection type SSH → Open.

## 2. Log in to the server for the first time

```bash
ssh <your_id>@<server>
```

- The first time, ssh asks `Are you sure you want to continue connecting (yes/no)?`. Type `yes` only if your
  mentor has confirmed the fingerprint shown on screen.
- Type your password and press Enter. **Nothing appears while you type**; that is normal.
- You are in when the prompt changes to something like `<your_id>@...$`. Keep this server terminal open for the
  following steps. Type `exit` only when you want to log out; commands after logging out run on your laptop.

## 3. Change your password

```bash
passwd
```

Type the current password once and the new one twice. Use a long passphrase that you do not use anywhere else.
Never write a password in a file, a notebook, a commit or an AI chat.

## 4. Create a GitHub account with two-factor authentication

1. On your laptop, sign up at <https://github.com> (skip this if you already have an account).
2. Turn on **two-factor authentication (2FA)**: your profile picture → Settings → Password and authentication →
   Enable two-factor authentication. Use an authenticator app on your phone.
3. Save the recovery codes somewhere safe that is **not** the server (a password manager or paper).
4. Tell your mentor your GitHub user name.

## 5. Get the tutorial

On the server:

```bash
git clone https://github.com/seismoseo/SGTL-earthquake-source-tutorial.git ~/sgtl/tutorial
cd ~/sgtl/tutorial
ls
```

You should see `README.md`, `bin`, `docs` and more. `~` means your home folder; everything for the
course lives under `~/sgtl/`.

## 6. Install the course software

```bash
bin/sgtl-install            # dry run: prints every step with [dry-run] and changes nothing
bin/sgtl-install --apply    # does it; this takes a while (often 10-30 minutes)
```

Read the dry-run output first. The install puts everything under `~/sgtl/` and needs no administrator rights.
At the end it creates the Jupyter kernel **SGTL (Python 3.12)**. Put the course programs on this terminal's search
path, then check the environment:

```bash
export PATH="${SGTL_HOME:-$HOME/sgtl}/envs/sgtl/bin:$PATH"
bin/sgtl doctor
```

The output uses **PASS**, **WARN** and **FAIL**. Fix any FAIL before continuing. At this stage, warnings about the
data folder, SeisBench weights and Git hooks are expected: later steps install or enable them. A font fallback is
also allowed. Read every other warning with your mentor ([troubleshooting.md](troubleshooting.md)). The default
installer installs only the environment; the extra tools and datasets are added when their modules need them
([how_this_tutorial_works.md](how_this_tutorial_works.md#before-each-module)).

## 7. Connect the server to your GitHub account

`gh` is the GitHub command-line program; it comes with the course environment.

```bash
gh auth login
```

Choose **GitHub.com** → **HTTPS** → authenticate Git with your GitHub credentials: **Yes** →
**Login with a web browser**. It prints a one-time code. On your laptop, open <https://github.com/login/device>,
enter the code and approve. Back on the server, `gh auth status` should say you are logged in.

Set your name for commits. Use GitHub's private no-reply address so your real email stays private
(find yours under GitHub → Settings → Emails):

```bash
git config --global user.name "Your Name"
git config --global user.email "<your exact no-reply address from GitHub Settings>"
```

Making your private copy of the tutorial is part of module M00 ([git_workflow.md](git_workflow.md)).

## 8. Start JupyterLab on the server

```bash
bin/sgtl-lab start            # dry run: shows what it would start
bin/sgtl-lab start --apply    # starts JupyterLab inside tmux, listening only on the server itself
```

JupyterLab keeps running after you log out (it runs inside **tmux**, a program that keeps terminal sessions
alive). `sgtl-lab` prints three things: a **port** number, the **tunnel recipes**, and a **link** with a token.
The token works like a password: never share the link or paste it into an issue or an AI chat.

## 9. Open the SSH tunnel from your laptop

An **SSH tunnel** lets the browser on your laptop reach JupyterLab on the server through your ssh connection.
Use the exact port number `sgtl-lab` printed; below it is written `<port>`.

- **PowerShell or macOS Terminal:** open a **new** terminal window on your laptop and run
  ```bash
  ssh -N -L <port>:127.0.0.1:<port> <your_id>@<server>
  ```
  After the password it shows nothing and seems to hang. That is correct: the tunnel is open while this window
  stays open.
- **Xshell:** session Properties → Connection → SSH → Tunneling → Add: type Local (Outgoing), source host
  `localhost`, listen port `<port>`, destination host `127.0.0.1`, destination port `<port>`. Reconnect.
- **PuTTY:** before Open, go to Connection → SSH → Tunnels: source port `<port>`, destination `127.0.0.1:<port>`,
  choose Local, click Add. Then Session → Open.

Now paste the printed link (`http://127.0.0.1:<port>/lab?token=...`) into your laptop's browser.

## 10. Open your first notebook

In a server terminal (JupyterLab also has one: File → New → Terminal):

```bash
cd ~/sgtl/tutorial
bin/sgtl new M00
```

This copies the M00 notebook into `work/M00_.../` once. Unlike the installer it has no dry run and acts at once,
because it only copies files and never overwrites your work. In JupyterLab's file
browser, open `work/M00_*/M00_*.ipynb`. Check the kernel name at the top right: it must be
**SGTL (Python 3.12)** (if not: Kernel → Change Kernel). Run the first **code** cell, labeled "Parameters", then
the setup code cell starting with `import sgtl_tutorial as st`, using Shift+Enter. The setup prints a short
environment and server-limit report. Title and instruction cells are text, so do not count them as code cells.
Then read on in the notebook.

## The SGTL kernel

For desktop exploration of seismograms in weeks 2–3, continue with the
[SeisComP GUI workshop](seiscomp_gui.md). It adds a separate native GUI installation and X11 forwarding
from your laptop. Your Jupyter browser connection alone does not forward desktop windows.

The **kernel** is the program that runs your notebook cells. The SGTL kernel uses the course environment, so
everyone has the same versions of Python and the packages. Do not install packages into it (`pip install`);
ask your mentor if something is missing. If the kernel is missing from the list, run `bin/sgtl doctor`.

## Every day after this

1. Log in to the server (step 2). Run `cd ~/sgtl/tutorial` and the `export PATH=...` command from step 6 in each
   new server terminal, then open the tunnel (step 9).
2. If the link does not work, check with `bin/sgtl-lab status`, then start JupyterLab again with
   `bin/sgtl-lab start --apply`.
3. Commit your work at least once a day ([git_workflow.md](git_workflow.md)).

Next: read [how_this_tutorial_works.md](how_this_tutorial_works.md) and [server_manners.md](server_manners.md).
