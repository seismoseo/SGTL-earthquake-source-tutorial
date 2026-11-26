# Explore earthquakes with SeisComP

**Use this workshop after downloading your first records in M03, alongside M10,
and again for the manual picks in M20.** Allow 60–90 minutes for the first visit.
You will open a set of seismograms, identify a missing interval, inspect an event
on a map, and save your own P and S arrival measurements for the later notebooks.

**SeisComP** is an earthquake-monitoring software package. Its **graphical user
interface (GUI)** lets you explore data with windows, menus and a mouse. Here it
runs **offline**: it reads your local files without connecting to a live seismic
network. You do not need an operational monitoring system or a database.

The tutorial uses SeisComP as its desktop tool for waveform inspection and manual
picking. The notebooks teach the calculations and test your measurements. The
notebook picker E2 is also available if you cannot forward a desktop window.
**SAC files remain the original downloaded records; using the SAC program is not
a prerequisite.** A file format and a program that reads that format are different
things, just as a PDF file is different from the application that displays it.

| What you want to understand | Open | Bring back to the notebook |
|---|---|---|
| What did the instruments record? Are channels missing or clipped? | `scrttv`, the waveform viewer | station/channel IDs, UTC interval, gap and clipping observations (M03/M10) |
| Which part is earthquake signal, and what changes with filtering? | raw and filtered views in `scrttv` | a stated filter, units and an observation tied to a trace (M10) |
| Where are the event and stations? When do P and S arrive? | `scolv`, the event viewer and picker | manual picks, uncertainty intervals and clear P polarities (M20) |
| How well do automatic picks and detections match what you see? | the same saved waveform session | examples of agreement and failure (M21/M22) |
| What controls a location or depth estimate? | `scolv` for geometry; M30/M31 for the checked calculation | residual plots, a depth scan and a documented velocity model |

Click any screenshot to view it at full size.

## 1. Install and check the GUI once

On the **server**, in your tutorial folder, after the environment setup:

```bash
cd ~/sgtl/tutorial
bin/sgtl-install seiscomp
bin/sgtl-install seiscomp --apply
bin/sgtl gui doctor
```

The first command prints the installation plan; the second installs. This recipe
is tested with **SeisComP 7.4.0 on Rocky/RHEL 8, Linux x86_64**. It downloads verified
native binaries into `~/sgtl/seiscomp/`, separately from the Python environment.
It starts no services. A missing `DISPLAY` warning at this point is expected.

On another server operating system, the mentor must first supply a compatible
**GUI-enabled** SeisComP installation and its desktop libraries. Point the course
at it in each terminal:

```bash
export SGTL_SEISCOMP_ROOT=/path/provided/by/your/mentor/seiscomp
bin/sgtl gui doctor
```

Replace that path with the actual one. Do not copy a binary built for a different
operating system, or install packages into the SGTL Python kernel to repair Qt.
Qt is the desktop library used by these windows. For the mentor, official
[binary downloads](https://www.seiscomp.de/downloader/) and
[source installation instructions](https://docs.gempa.de/seiscomp/current/base/build.html)
describe supported platforms and dependencies. A source build needs
`SC_GLOBAL_GUI=ON`; a successful headless build alone does not provide these GUIs.

## 2. Let a server window appear on your laptop

Your Jupyter browser tunnel carries notebook pages. A SeisComP desktop window
uses **X11 forwarding**, which carries a graphical application through SSH.

1. Prepare an X server on your **laptop**. Windows: start the X server bundled
   with [MobaXterm](https://mobaxterm.mobatek.net/documentation.html), then use its
   local terminal. macOS: install and start [XQuartz](https://www.xquartz.org/),
   log out/in once after installation, then open a new Terminal. A Linux desktop
   usually already provides X11 or XWayland.
2. From that laptop terminal, connect to the lab server your mentor confirmed:

   ```bash
   ssh -Y <your_id>@<server>
   ```

3. In **that new server terminal**, run:

   ```bash
   cd ~/sgtl/tutorial
   export PATH="${SGTL_HOME:-$HOME/sgtl}/envs/sgtl/bin:$PATH"
   echo "$DISPLAY"
   bin/sgtl gui doctor
   ```

`DISPLAY` should contain an SSH-assigned value, often `localhost:10.0`. Keep this
terminal open while using the GUI. A terminal opened inside JupyterLab does not
inherit this SSH display. Do not type a guessed value into `DISPLAY`: if it is
empty, reconnect from the laptop X server and ask the mentor to check the SSH
server's X11 support. Close a GUI window to return to the terminal prompt.

## 3. Rehearse with synthetic records

Start here even if you already have real data. These are **made-up signals** at
three invented stations, dated 5 April 2031. They demonstrate the controls without
STP access or a hidden answer file. One vertical channel has a five-second gap.

```bash
bin/sgtl gui demo
bin/sgtl gui demo --apply
bin/sgtl gui open work/seiscomp/demo
bin/sgtl gui open work/seiscomp/demo --apply
```

Every writing/launching command prints a dry run first unless you add `--apply`.
Preparation refuses an existing session directory: keep it and choose a new
`--out`, such as `work/seiscomp/demo2`, for another rehearsal.

[![SeisComP waveform viewer showing synthetic three-component records and a gap](figures/seiscomp_waveforms.png)](figures/seiscomp_waveforms.png)

*A real `scrttv` window from the synthetic rehearsal. The blank interval is missing
data, not a quiet instrument. These are not observations from Suncheon or Sangju.*

In the waveform viewer (`scrttv`):

1. Read a stream ID: `XX.DEMO1..HHZ` means network `XX`, station `DEMO1`, a blank
   location code, and vertical channel `HHZ`. N and E are the north and east
   components. The two dots are intentional.
2. Compare the quiet interval before the event with the later oscillations.
   Find the gap in `XX.DEMO3..HHZ`. Press **B** to show record borders if helpful.
   A flat trace with samples is different from a gap with no samples.
3. Zoom by dragging along the time axis with the right mouse button. Use the
   **View** menu if your laptop intercepts a shortcut. Press **Ctrl+N** to reset.
4. Press **F** to toggle the configured causal 1–10 Hz filter. A causal filter
   uses present and earlier samples; it can delay an onset. Name the filter and
   explain which features became clearer and which were suppressed. Return to
   the raw trace before judging a first-motion polarity.
5. Compare two components of one station and two stations at different distances.
   Identify what you can infer from timing, and what requires metadata or a model.

This course's `scrttv` launcher uses `--no-inventory` to show **original counts**
and every stream actually present in the file. It does not apply gain or remove
the instrument response. An amplitude in counts cannot be compared between
instruments as ground velocity. M03/M10 teach the response correction explicitly.

## 4. Inspect the event and station geometry

Close `scrttv`, then open the other application:

```bash
bin/sgtl gui open work/seiscomp/demo --app event
bin/sgtl gui open work/seiscomp/demo --app event --apply
```

[![SeisComP event view linking synthetic station geometry and manual arrivals](figures/seiscomp_event.png)](figures/seiscomp_event.png)

*The event view links a map, the origin information and the arrival table. The
coastline supplies geographic context; it does not represent a mapped fault.
The synthetic origin remains fixed while picks are added in this exercise.*

Find the origin time, latitude, longitude and depth. An **origin** is one estimate
of an earthquake's position and start time. An event can have several origins
from different agencies or processing revisions. A triangle represents a station;
the earthquake symbol marks the epicenter. Before picking, the arrival table is
empty because the preparation does not copy SAC header picks or generate picks.

Click **Picker** at the lower right. Click a station row to load its enlarged
three-component view. Look at stations around the event: which directions are
well observed? An **azimuthal gap** is the largest angle around the event with no
station. A small map separation does not guarantee a well-constrained depth;
depth also trades off with origin time and the assumed wave speeds (M30/M31).

## 5. Measure and save P and S

Rehearse these steps at one invented station, then repeat them on your own M20
records. A **pick** is your measured arrival time, not the largest peak in a trace.
Its **uncertainty** describes the range of onset times that you would still accept.

[![SeisComP picker displaying the synthetic P and S on three components](figures/seiscomp_picker.png)](figures/seiscomp_picker.png)

*The selected station appears enlarged above the station list. Read P on Z, and
compare N and E for S. Keep uncertainty and first-motion polarity with the pick.*

1. Select a station in the lower list. In **View**, leave **Show trace values in
   sensor units** off: the labels should say **counts**. Keep the original Z/N/E
   components; do not rotate into R/T for this file. To inspect an onset closely,
   use **Ctrl+Right** to zoom in and **Ctrl+Left** to zoom out in the tested
   7.4.0 picker. Check the time-axis labels: the menu's timespan wording can be
   confusing. Drag the time axis to bring the onset back into view if needed.
   You can also right-drag across the time axis beneath the enlarged traces to
   select the interval to magnify; press **W** to reset the time/amplitude scale.
2. Press **F1** (Pick P phase), click on the Z onset to position the cursor, and press
   **Space** (Set pick). A moving cursor line alone is not a saved pick. Use
   **Esc** to leave picking mode; the placed marker should remain. Find the last
   noise sample before the signal leaves the background, rather than the peak.
3. Hover over the placed marker, then right-click **on that marker**. Choose
   **Uncertainty** and an interval you can defend. Choose **Define…** for an
   asymmetric interval. Do this for every pick; the importer refuses to invent
   missing uncertainty. M20 accepts P intervals 0.005–0.5 s and S intervals
   0.01–1.0 s. These are admissible bounds, not instructions to use one standard
   value. At 100 samples/s, one sample is 0.01 s.
4. In the same context menu choose **Polarity → positive**, **negative** or
   **undecidable** for P. Positive is U and negative is D in the course CSV.
   Judge the first swing in **raw counts**, checking the metadata discussion in
   M20. An unclear onset should stay `?`; do not force a mechanism-compatible sign.
5. Press **F2** (Pick S phase), select the N or E component with the clearer onset,
   click at the change in amplitude and oscillation within the P coda, then press
   **Space**. Record the S uncertainty. S must follow P. The S channel must be
   the original HHN or HHE, not a generic channel or a rotated R/T component.
6. Repeat at the stations you can read confidently. For M20, use at least six
   stations within 100 km, each with a P and S, and at least three clear P
   polarities. More picks help only when their quality is defensible.
7. In the **picker**, press **Apply all (F5)**. Return to the **Location** window
   and inspect the arrival table. Press **Commit**, then **File → Save**. Save
   as `reviewed.xml` inside this session directory. Keep the original `event.xml`.
   Open the saved XML through **File → Open** and verify that the picks survived.

   To resume a saved review, launch the event viewer and use **File → Open** on
   your `reviewed.xml`. In **Events**, expand/select the reviewed origin revision
   and open it in **Location**. The initial catalog origin may still have zero
   arrivals; that does not mean the later revision was lost. Check its origin ID
   and arrival count before making more measurements or exporting.

**Apply all, Commit and Save are separate steps.** In this offline session Commit
updates the in-memory event data; Save writes the XML file. The command-line
importer will list the origins and their associated-pick counts so you can catch
an empty or older export. If you close the application without saving, the GUI
changes are lost.

For this exercise, leave the **Relocate** and magnitude buttons alone. **Apply all**
updates the arrival list while preserving the context origin. Default SeisComP
travel-time curves and residuals can use a global model such as iasp91. They are
predictions under that model, and are not the course's kim1983/kim2011 crustal
calculations. Do not move an observed pick onto a predicted line. You will test
location, origin time and depth with your own functions in M30/M31 and HYPOINVERSE
in M32, including the exclusion of Moho Pn/Sn arrivals.

## 6. Use your downloaded Sangju teaching records

After M03 has fetched `sangju2019` and installed the station metadata:

```bash
bin/sgtl data verify sangju2019
bin/sgtl gui prepare sangju2019 --out work/seiscomp/sangju2019
bin/sgtl gui prepare sangju2019 --out work/seiscomp/sangju2019 --apply
bin/sgtl gui open work/seiscomp/sangju2019 --app event --apply
```

The default event is **21 July 2019, 02:04:18 UTC (11:04:18 KST), ML 3.9**. This is
the course's teaching earthquake, distinct from the 2026 Sangju research project.
The session selects the original HH records within 100 km, validates stream IDs,
sample rates and metadata epochs, and converts local copies. It preserves gaps
and counts; it neither filters nor copies any pre-existing SAC arrival markers.
An **epoch** is the time span during which a metadata entry is valid. Using today's
instrument response for a 2019 record can give a wrong amplitude or sign.

Repeat section 5 and save `work/seiscomp/sangju2019/reviewed.xml`. Back in the same
server terminal, from the tutorial root:

```bash
bin/sgtl gui import-picks work/seiscomp/sangju2019 \
  --xml work/seiscomp/sangju2019/reviewed.xml \
  --out work/picks/M20_manual_picks.csv
```

The dry run validates your export. If it lists several origins, copy the ID of
the reviewed revision with the intended arrival count and add
`--origin-id 'the ID printed above'`. Repeat the same command with **`--apply`**
to write the CSV and its `.seiscomp.json` provenance receipt. Keep the saved XML
beside them. The conversion preserves UTC to microseconds, channel identity and
polarity; asymmetric uncertainty becomes the larger half-width, with both
original bounds recorded in the receipt. Disabled arrivals are excluded.

The output has the same six columns that M20 and the later modules read:
`station,phase,channel,time_utc,uncertainty_s,polarity`. It rejects automatic picks,
missing or duplicate measurements, out-of-record times and absent uncertainty.
It never overwrites an existing CSV. For a revision, export to a new file, compare
it with the old one, and deliberately choose which file your notebook reads.

In M20, keep the default `PICKS_CSV = "../picks/M20_manual_picks.csv"`, skip saving
from E2, and run the **unchanged M20-T5 check**. Importing a file checks its format;
M20 still tests the station coverage and physical consistency of your measurements.
M21, M22, M30, M31, M50 and M53 then reuse your CSV without a second conversion.

## 7. Carry the workflow into both research projects

For **Suncheon** and **Sangju**, first freeze your research area, time window and
data selection in the project plan. Fetch your own records and event-time metadata.
For an event in a private research dataset, use explicit context information:

```bash
bin/sgtl gui prepare --waveforms /path/to/your/event/HH \
  --stationxml /path/to/your/stationxml \
  --origin 2031-04-05T06:07:00Z --latitude 36.5 --longitude 128.1 --depth-km 12 \
  --out work/seiscomp/project-event
```

**Every value above is an invented example.** Replace the paths, origin and
coordinates with your selected event and cite their catalog source. `--depth-km`
sets map/picker context; if the catalog lacks depth, label your assumed value in
the lab book. It is not a measured research depth. Read the plan, then repeat with
`--apply`. This preparation uses the same 100 km observation limit; document any
change to station selection in your research plan and use the course's direct-wave
checks before location.

Use the GUI to examine candidate detections from template matching (M22): view the
candidate and the template with the same components, filter and time scale; check
several stations, gaps and competing transients. Include a rejected candidate and
a quiet control in your lab book. A high correlation peak alone does not establish
an earthquake, a shared fault or an accurate depth. Quantify held-out/injection/null
tests in the notebooks and record why each inspected example was accepted or rejected.

Keep one new session per event/review under `work/`, and separate project products
under `project/` for Suncheon and `project/sangju/` for Sangju as their guides specify. Waveforms,
GUI session exports and real-data screenshots remain private. `work/seiscomp/` is
ignored by Git because sessions contain waveform copies; commit your reviewed
CSV and receipt under `work/picks/` in your private copy instead. The public figures
on this page use synthetic signals only.

## When something goes wrong

| What you see | What to check next |
|---|---|
| `No DISPLAY` / cannot open display | use the SSH terminal opened from your laptop X server; reconnect with `ssh -Y`; do not set `DISPLAY` by hand |
| a Qt plugin/shared-library error | run `bin/sgtl gui doctor`; give the output to the mentor; keep the native GUI separate from conda's Qt libraries |
| `scolv`/`scrttv` missing | your installation may be headless; use a GUI-enabled build and the correct `SGTL_SEISCOMP_ROOT` |
| empty trace view | verify the UTC date, stream IDs, data window and station epoch; select a station row; a yellow/blank interval can be a gap |
| stations but no coastline | update the course; the session includes a small offline GSHHG vector coastline; it does not require a web tile server |
| no saved picks / zero arrivals | Set pick with Space; Apply all in the picker; Commit in Location; File → Save; reopen that saved XML |
| “several origins” during import | inspect the printed IDs and arrival counts; explicitly select the revision you reviewed |
| output already exists | export to a new session/CSV; compare revisions before choosing one for your notebook |
| a polarity differs between GUI and notebook | confirm both show unfiltered original counts, the same Z channel, and the same metadata epoch; inspect the response-sign discussion in M20 |

The primary manuals for the tested applications are
[`scrttv`](https://docs.gempa.de/seiscomp/current/apps/scrttv.html),
[`scolv`](https://docs.gempa.de/seiscomp/current/apps/scolv.html), and
[`fdsnxml2inv`](https://docs.gempa.de/seiscomp/current/apps/fdsnxml2inv.html).
The converter translates FDSN StationXML into SeisComP's inventory XML; the course
keeps both files and fingerprints the original inputs. SeisComP also supplies live
network displays (`scmv`, `scesv`, `scheli`) and archive utilities (`scart`,
`scmssort`, `scxmlmerge`). These become useful in observatory work after you know
which observations and assumptions go into an event estimate. They are not needed
to run this offline workshop.
