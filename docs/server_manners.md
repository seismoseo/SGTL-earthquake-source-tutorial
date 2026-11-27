# Sharing the server

The lab server is shared: many people run work on it at the same time. One careless command can slow down or kill
everyone else's jobs. These rules keep it usable for all. (Glossary: **CPU core**, **thread**, **memory**.)

## The rules

1. **Threads: one per program unless told otherwise.** NumPy and similar libraries start one thread per CPU core by
   default, which can take over the whole machine. `st.init()` caps this in notebooks. In a terminal script, set the
   caps **before** Python starts:
   ```bash
   export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 NUMPY_MADVISE_HUGEPAGE=0
   ```
   Setting them inside Python after `import numpy` is too late.
2. **Memory: stay under your cap.** Notebooks are capped at 16 GB by `st.init()`. Load only the data you need. If the
   server runs out of memory, programs are killed, possibly someone else's.
3. **Be nice.** Run anything longer than a minute with `nice`, which lets interactive users go first:
   `nice -n 15 python my_script.py`.
4. **One heavy run at a time, at most 4 cores.** A heavy run is anything that takes many minutes, many cores or many
   GB. The tutorial's run commands (from M32 on) enforce this; do not work around them.
5. **No `sudo`, no system-wide installs.** Everything you install lives under `~/sgtl/`. Ask your mentor if you need
   a package.
6. **Mind your disk quota.** The course needs a few GB under `~/sgtl/`. Keep data in `~/sgtl/data/`, never in the
   repository, and delete what you no longer need.
7. **Clean up.** Shut down notebook kernels you are not using (JupyterLab: the Running tab, the square-stop icon), and
   stop your JupyterLab when you leave for a few days.
8. **Never look into other people's folders**, even if the permissions would let you.

## How to see the load

```bash
nproc                         # how many CPU cores the server has
uptime                        # load average: compare it with nproc
free -g                       # memory in GB: look at "available"
top -u $USER                  # your own processes (press q to quit; htop is nicer if installed)
ps -u $USER -o pid,ni,pcpu,pmem,etime,cmd --sort=-pcpu | head    # your busiest processes
quota -s                      # your disk quota (if quotas are set)
du -sh ~/sgtl/*               # how much space each of your course folders uses
```

In a notebook, `st.server_rules()` reports the thread caps, memory cap and CPU state of your kernel (module M00,
task 3, reads three of them).

If the load average is far above the number of cores, or available memory is low, wait before starting anything
heavy. If something of yours runs away, stop it: `kill <pid>` (from `ps` or `top`), or in JupyterLab restart the
kernel. Tell your mentor if you are not sure; nobody minds a question, everybody minds a frozen server.
