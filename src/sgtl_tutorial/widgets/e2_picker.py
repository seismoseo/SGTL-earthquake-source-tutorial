"""E2 · Phase picker: pick P and S by hand on the three components of one station at a time.

You choose a station, a phase (P or S), the time window and, if you like, a causal band-pass. A click on a record
(or a time typed in the box) marks a moment; "Set pick" stores it with the uncertainty and, for P, the polarity you
chose; "Save" writes all picks to a CSV file (columns station, phase, channel, time_utc, uncertainty_s,
polarity). When the picker starts it reads that file again, so you can stop and go on later.

Clicking needs ipympl (installed in the course environment). Without it, or with ``click=False``, the picture is a
static image and you type the times; ``set_pick(...)`` and ``save()`` work from code in both cases.

What the picker never does: choose a time, an uncertainty or a polarity for you. It draws the records (mean
removed; optionally band-passed), your picks and their uncertainties, and nothing else.

Credit: Minseong Seo (SGTL, Seoul National University). License: MIT.
"""
from __future__ import annotations

import csv
import html
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ._common import Explorer, status_html

COLUMNS = ("station", "phase", "channel", "time_utc", "uncertainty_s", "polarity")
PHASE_COLORS = {"P": "tab:blue", "S": "tab:red"}
SAC_NAME = re.compile(r"(?:^|\.)(?P<net>[A-Z0-9]{1,2})\.(?P<sta>[A-Z0-9]{2,5})\.(?P<cha>[A-Z0-9]{3})\.sac$", re.I)


def _ipympl_canvas(figure: Any) -> Any:
    """An ipympl canvas for the figure, or None when ipympl is missing."""
    try:
        from ipympl.backend_nbagg import Canvas, FigureManager
    except ImportError:
        return None
    canvas = Canvas(figure)
    FigureManager(canvas, 0)
    for name, value in (("header_visible", False), ("footer_visible", False), ("toolbar_visible", False),
                        ("resizable", False)):
        try:
            setattr(canvas, name, value)
        except Exception:  # an older ipympl without that switch
            pass
    return canvas


class PhasePicker(Explorer):
    """E2: manual P and S picks with uncertainties and polarities, written to a CSV file.

    source     : a folder of SAC files of one band (names ending in .<NET>.<STA>.<CHA>.sac), or an ObsPy Stream
    origin     : ObsPy UTCDateTime that times refer to (default: the earliest first sample)
    epicenter  : (lat, lon) in degrees; stations are then listed by epicentral distance (from stla, stlo)
    max_km     : list only stations within this epicentral distance (needs epicenter)
    csv_path   : the file that Save writes (and that the picker reads again when it starts)
    window     : (start, end) of the time shown first, in seconds after origin
    fmin, fmax : corners (Hz) of the optional causal band-pass (Butterworth, ``corners`` corners)
    click      : "auto" (clicks when ipympl is installed), True or False
    """

    dpi = 90

    def __init__(self, source: Any, *, origin: Any = None, epicenter: Optional[Sequence[float]] = None,
                 max_km: Optional[float] = None, csv_path: Any = None, window: Sequence[float] = (-5.0, 30.0),
                 fmin: float = 1.0, fmax: float = 10.0, corners: int = 4, click: Any = "auto") -> None:
        super().__init__(9.5, 6.2)
        self._sources = self._collect(source)
        if not self._sources:
            raise ValueError("phase_picker found no records (SAC files named *.<NET>.<STA>.<CHA>.sac, or a Stream)")
        self.origin = origin if origin is not None else min(info["start"] for info in self._sources.values())
        self.epicenter = tuple(float(v) for v in epicenter) if epicenter is not None else None
        self._distances = self._epicentral_km()
        names = sorted(self._sources, key=lambda s: (self._distances.get(s, np.inf), s))
        if max_km is not None:
            if self.epicenter is None:
                raise ValueError("max_km needs epicenter=(lat, lon)")
            names = [s for s in names if self._distances.get(s, np.inf) <= float(max_km)]
        if not names:
            raise ValueError("no station is left within max_km")
        self.station_names = names
        self.csv_path = Path(csv_path).expanduser() if csv_path is not None else None
        self.band = (float(fmin), float(fmax))
        self.corners = int(corners)
        self._loaded: Dict[str, Any] = {}
        self._picks: Dict[Tuple[str, str], dict] = {}
        self._pending: Optional[float] = None
        self._message = ""
        self._axes: Dict[Any, str] = {}
        if self.csv_path is not None and self.csv_path.is_file():
            self.load(self.csv_path, redraw=False)

        w = self._widgets
        style = {"description_width": "initial"}
        labels = [(self._label(s), s) for s in names]
        self.station_menu = w.Dropdown(options=labels, value=names[0], description="Station", style=style)
        self.phase_buttons = w.ToggleButtons(options=["P", "S"], value="P", description="Phase", style=style)
        self.channel_menu = w.Dropdown(options=[], description="Channel", style=style)
        lo, hi = (float(v) for v in window)
        self.window_slider = w.FloatRangeSlider(value=(lo, hi), min=lo - 30.0, max=hi + 60.0, step=0.01,
                                                readout_format=".2f", description="Window (s)",
                                                continuous_update=False, style=style,
                                                layout=w.Layout(width="60%"))
        self.zoom_button = w.Button(description="Zoom to the mark", tooltip="1 s around the marked time")
        self.wide_button = w.Button(description="Wide view", tooltip="Back to the first window")
        self.filter_box = w.Checkbox(value=False, style=style,
                                     description=f"Causal band-pass {self.band[0]:g}-{self.band[1]:g} Hz")
        self.zerophase_box = w.Checkbox(value=False, description="Zero-phase instead", style=style)
        self.time_box = w.FloatText(value=0.0, description="Time (s after origin)", step=0.005, style=style)
        self.uncertainty_box = w.BoundedFloatText(value=0.0, min=0.0, max=2.0, step=0.005,
                                                  description="Uncertainty (s)", style=style)
        self.polarity_buttons = w.ToggleButtons(options=["U", "D", "?"], value="?", description="Polarity",
                                                style=style)
        self.set_button = w.Button(description="Set pick", button_style="primary")
        self.delete_button = w.Button(description="Delete pick")
        self.save_button = w.Button(description="Save", button_style="success")
        self.table = w.HTML()
        self._first_window = (lo, hi)

        self.canvas = None
        if click is True or click == "auto":
            self.canvas = _ipympl_canvas(self.figure)
            if self.canvas is None and click is True:
                raise ImportError("Clicking needs ipympl (bin/sgtl-install env --apply); use click=False to type")
        if self.canvas is not None:
            self.canvas.mpl_connect("button_press_event", self._clicked)
        picture = self.canvas if self.canvas is not None else self.image

        self._fill_channels()
        with self.hold():
            for control in (self.window_slider, self.filter_box, self.zerophase_box, self.time_box):
                control.observe(self._changed, names="value")
            self.station_menu.observe(self._station_changed, names="value")
            self.phase_buttons.observe(self._phase_changed, names="value")
            self.zoom_button.on_click(self._zoom)
            self.wide_button.on_click(self._wide)
            self.set_button.on_click(lambda _b: self._set_from_controls())
            self.delete_button.on_click(lambda _b: self._delete_from_controls())
            self.save_button.on_click(lambda _b: self._save_from_button())
        self.box = w.VBox([w.HBox([self.station_menu, self.phase_buttons, self.channel_menu]),
                           w.HBox([self.window_slider, self.zoom_button, self.wide_button]),
                           w.HBox([self.filter_box, self.zerophase_box]), picture,
                           w.HBox([self.time_box, self.uncertainty_box]),
                           w.HBox([self.polarity_buttons, self.set_button, self.delete_button, self.save_button]),
                           self.status, self.table])
        self.redraw()

    # --------------------------------------------------------------------------------------------- the data
    @staticmethod
    def _collect(source: Any) -> Dict[str, dict]:
        """{network.station: {"channels": {channel: path or Trace}, "start", "lat", "lon"}} from a folder or Stream."""
        from obspy import Stream, read

        found: Dict[str, dict] = {}
        if isinstance(source, Stream):
            for tr in source:
                name = f"{tr.stats.network}.{tr.stats.station}"
                info = found.setdefault(name, {"channels": {}, "start": tr.stats.starttime, "lat": None, "lon": None})
                info["channels"][tr.stats.channel] = tr.copy()
                info["start"] = min(info["start"], tr.stats.starttime)
                sac = tr.stats.get("sac", {})
                if "stla" in sac and "stlo" in sac:
                    info["lat"], info["lon"] = float(sac["stla"]), float(sac["stlo"])
            return found
        folder = Path(source).expanduser()
        if not folder.is_dir():
            raise ValueError(f"phase_picker: {folder} is not a folder")
        for path in sorted(folder.glob("*.sac")):
            match = SAC_NAME.search(path.name)
            if not match:
                continue
            head = read(str(path), headonly=True)[0].stats
            name = f"{head.network}.{head.station}"
            info = found.setdefault(name, {"channels": {}, "start": head.starttime, "lat": None, "lon": None})
            info["channels"][head.channel] = path
            info["start"] = min(info["start"], head.starttime)
            sac = head.get("sac", {})
            if "stla" in sac and "stlo" in sac:
                info["lat"], info["lon"] = float(sac["stla"]), float(sac["stlo"])
        return found

    def _epicentral_km(self) -> Dict[str, float]:
        if self.epicenter is None:
            return {}
        from obspy.geodetics import gps2dist_azimuth

        out = {}
        for name, info in self._sources.items():
            if info["lat"] is not None:
                out[name] = gps2dist_azimuth(self.epicenter[0], self.epicenter[1], info["lat"], info["lon"])[0] / 1e3
        return out

    def _label(self, name: str) -> str:
        km = self._distances.get(name)
        return f"{name} ({km:.1f} km)" if km is not None else name

    def _stream(self, name: str) -> Any:
        """The station's records (mean removed), read once."""
        from obspy import Stream, read

        if name not in self._loaded:
            parts = []
            for channel, item in sorted(self._sources[name]["channels"].items()):
                parts.append(item.copy() if not isinstance(item, Path) else read(str(item))[0])
            stream = Stream(parts)
            stream.detrend("demean")
            self._loaded[name] = stream
        return self._loaded[name]

    def _channels(self, name: str) -> List[str]:
        order = {"Z": 0, "N": 1, "1": 1, "E": 2, "2": 2}
        return sorted(self._sources[name]["channels"], key=lambda c: (order.get(c[-1], 9), c))

    def _default_channel(self, name: str, phase: str) -> Optional[str]:
        channels = self._channels(name)
        wanted = ("Z",) if phase == "P" else ("N", "1", "E", "2")
        return next((c for c in channels if c[-1] in wanted), channels[0] if channels else None)

    def _fill_channels(self) -> None:
        name, phase = self.station_menu.value, self.phase_buttons.value
        with self.hold():
            self.channel_menu.options = self._channels(name)
            self.channel_menu.value = self._default_channel(name, phase)

    # -------------------------------------------------------------------------------------------- your picks
    def _seconds(self, time: Any) -> float:
        from obspy import UTCDateTime

        if isinstance(time, UTCDateTime):
            return float(time - self.origin)
        return float(time)

    def set_pick(self, station: str, phase: str, time: Any, uncertainty_s: float, polarity: str = "?",
                 channel: Optional[str] = None) -> None:
        """Store one pick. time: seconds after origin, or an ObsPy UTCDateTime. Replaces an earlier pick of the
        same station and phase."""
        if station not in self.station_names:
            raise ValueError(f"{station} is not one of the picker's stations (see picker.station_names)")
        phase = str(phase).upper()
        if phase not in PHASE_COLORS:
            raise ValueError("phase must be 'P' or 'S'")
        unc = float(uncertainty_s)
        if not unc > 0:
            raise ValueError("set an uncertainty above 0 s (half the range of times you would still accept)")
        polarity = str(polarity).upper() if str(polarity) != "?" else "?"
        if polarity not in ("U", "D", "?"):
            raise ValueError("polarity must be 'U', 'D' or '?'")
        if phase == "S":
            polarity = "?"
        channel = channel or self._default_channel(station, phase)
        if channel not in self._sources[station]["channels"]:
            raise ValueError(f"{station} has no channel {channel}")
        seconds = self._seconds(time)
        self._picks[(station, phase)] = {"channel": channel, "seconds": seconds, "uncertainty_s": unc,
                                         "polarity": polarity}
        self._message = f"Set {phase} at {station}: {seconds:.3f} s ± {unc:g} s ({channel}, polarity {polarity})."
        if station == self.station_menu.value:
            self.redraw()
        else:
            self._update_status()

    def delete_pick(self, station: str, phase: str) -> bool:
        """Remove one pick; True when there was one."""
        gone = self._picks.pop((station, str(phase).upper()), None) is not None
        self._message = f"Deleted {phase} at {station}." if gone else f"No {phase} pick at {station} to delete."
        self.redraw()
        return gone

    @property
    def picks(self) -> Any:
        """Your picks as a pandas DataFrame with the columns of the CSV file."""
        import pandas as pd

        return pd.DataFrame(self._rows(), columns=list(COLUMNS))

    def _rows(self) -> List[dict]:
        rank = {s: i for i, s in enumerate(self.station_names)}
        rows = []
        for (station, phase), pick in sorted(self._picks.items(),
                                             key=lambda item: (rank.get(item[0][0], 10 ** 6), item[0][0], item[0][1])):
            rows.append({"station": station, "phase": phase, "channel": pick["channel"],
                         "time_utc": str(self.origin + pick["seconds"]),
                         "uncertainty_s": round(pick["uncertainty_s"], 6), "polarity": pick["polarity"]})
        return rows

    def save(self, path: Any = None) -> Path:
        """Write all picks to the CSV file (csv_path, or path) and return its path."""
        target = Path(path).expanduser() if path is not None else self.csv_path
        if target is None:
            raise ValueError("give a path: picker.save('work/picks/M20_manual_picks.csv')")
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(COLUMNS))
            writer.writeheader()
            writer.writerows(self._rows())
        self._message = f"Saved {len(self._picks)} picks to {target}."
        self._update_status()
        return target

    def load(self, path: Any, redraw: bool = True) -> int:
        """Read picks from a CSV file written by save(); returns how many were read."""
        from obspy import UTCDateTime

        count = 0
        with open(Path(path).expanduser(), newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                try:
                    station, phase = row["station"], row["phase"].upper()
                    self._picks[(station, phase)] = {
                        "channel": row["channel"], "seconds": float(UTCDateTime(row["time_utc"]) - self.origin),
                        "uncertainty_s": float(row["uncertainty_s"]), "polarity": row.get("polarity") or "?"}
                    count += 1
                except (KeyError, ValueError, TypeError):
                    continue
        self._message = f"Read {count} picks from {path}."
        if redraw:
            self.redraw()
        return count

    # ------------------------------------------------------------------------------------------ the controls
    def _station_changed(self, _change: Any = None) -> None:
        self._pending = None
        self._fill_channels()
        self.redraw()

    def _phase_changed(self, _change: Any = None) -> None:
        name, phase = self.station_menu.value, self.phase_buttons.value
        current = self.channel_menu.value or ""
        fits = current.endswith("Z") if phase == "P" else not current.endswith("Z")
        if not fits:
            with self.hold():
                self.channel_menu.value = self._default_channel(name, phase)
        self.redraw()

    def _zoom(self, _button: Any = None) -> None:
        mark = self._pending
        if mark is None:
            pick = self._picks.get((self.station_menu.value, self.phase_buttons.value))
            mark = pick["seconds"] if pick else None
        if mark is None:
            self._message = "Mark a time first (click a record or type it), then zoom."
            self._update_status()
            return
        self._set_window(mark - 0.5, mark + 0.5)

    def _wide(self, _button: Any = None) -> None:
        self._set_window(*self._first_window)

    def _set_window(self, lo: float, hi: float) -> None:
        slider = self.window_slider
        with self.hold():
            slider.min, slider.max = min(slider.min, lo), max(slider.max, hi)
            slider.value = (lo, hi)
        self.redraw()

    def _clicked(self, event: Any) -> None:
        channel = self._axes.get(event.inaxes)
        if channel is None or event.xdata is None or getattr(event, "button", 1) not in (1, None):
            return
        with self.hold():
            self.time_box.value = round(float(event.xdata), 4)
            if (self.phase_buttons.value == "P") == channel.endswith("Z"):
                self.channel_menu.value = channel
        self._pending = float(event.xdata)
        self._message = f"Marked {self._pending:.3f} s on {channel}: set the uncertainty (and polarity), then Set pick."
        self.redraw()

    def _changed(self, change: Any = None) -> None:
        if change is not None and getattr(change, "owner", None) is self.time_box or \
                (isinstance(change, dict) and change.get("owner") is self.time_box):
            self._pending = float(self.time_box.value)
        super()._changed(change)

    def _set_from_controls(self) -> None:
        try:
            self.set_pick(self.station_menu.value, self.phase_buttons.value, float(self.time_box.value),
                          float(self.uncertainty_box.value), self.polarity_buttons.value, self.channel_menu.value)
            self._pending = None
            self.redraw()
        except ValueError as exc:
            self._message = str(exc)
            self._update_status()

    def _delete_from_controls(self) -> None:
        self.delete_pick(self.station_menu.value, self.phase_buttons.value)

    def _save_from_button(self) -> None:
        try:
            self.save()
        except (OSError, ValueError) as exc:
            self._message = f"Could not save: {exc}"
            self._update_status()

    # -------------------------------------------------------------------------------------------------- draw
    def redraw(self) -> None:
        if self.canvas is None:
            super().redraw()
            return
        if self._held:
            return
        self.lines = {}
        self.figure.clear()
        self._draw()
        self.canvas.draw_idle()
        self.redraws += 1

    def _draw(self) -> None:
        name = self.station_menu.value
        lo, hi = (float(v) for v in self.window_slider.value)
        stream = self._stream(name)
        filtered = bool(self.filter_box.value)
        notes = []
        if filtered:
            stream = stream.copy()
            stream.taper(max_percentage=0.05, type="hann")
            stream.filter("bandpass", freqmin=self.band[0], freqmax=self.band[1], corners=self.corners,
                          zerophase=bool(self.zerophase_box.value))
            if self.zerophase_box.value:
                notes.append("Zero-phase band-pass on: energy spreads ahead of each arrival (task 4 of M20).")
        channels = self._channels(name)
        fig = self.figure
        axes = fig.subplots(len(channels), 1, sharex=True, squeeze=False)[:, 0]
        self._axes = {}
        for ax, channel in zip(axes, channels):
            tr = stream.select(channel=channel)[0]
            t = tr.times(reftime=self.origin)
            keep = (t >= lo) & (t <= hi)
            self.lines[channel], = ax.plot(t[keep], tr.data[keep], color="k", lw=0.6,
                                           marker="." if keep.sum() <= 400 else None, ms=2)
            ax.set_ylabel(channel)
            self._axes[ax] = channel
            for phase in ("P", "S"):
                pick = self._picks.get((name, phase))
                if pick is None:
                    continue
                color = PHASE_COLORS[phase]
                ax.axvspan(pick["seconds"] - pick["uncertainty_s"], pick["seconds"] + pick["uncertainty_s"],
                           color=color, alpha=0.12, lw=0)
                ax.axvline(pick["seconds"], color=color, lw=1.0)
                if channel == pick["channel"]:
                    text = phase + ("" if phase == "S" else f" {pick['polarity']}")
                    ax.text(pick["seconds"], 1.0, f" {text}", transform=ax.get_xaxis_transform(), color=color,
                            fontsize=9, va="bottom")
            if self._pending is not None:
                ax.axvline(self._pending, color="0.45", lw=0.9, ls="--")
        axes[-1].set_xlabel("Time after origin (s)")
        axes[-1].set_xlim(lo, hi)
        self.state = {"station": name, "window": (lo, hi), "filtered": filtered,
                      "zerophase": bool(self.zerophase_box.value) and filtered, "pending": self._pending,
                      "n_picks": len(self._picks)}
        self._notes = notes
        self._update_status()

    def _update_status(self) -> None:
        name = self.station_menu.value
        km = self._distances.get(name)
        stations_both = sorted({s for (s, _p) in self._picks if (s, "P") in self._picks and (s, "S") in self._picks})
        head = (f"{name}" + (f", {km:.1f} km from the epicenter" if km is not None else "") +
                f"; {len(self._picks)} picks, {len(stations_both)} stations with P and S" +
                ("" if self.csv_path is None else f"; file {self.csv_path}"))
        how = ("Click a record to mark a time" if self.canvas is not None else "Type a time") + \
            ", set the uncertainty and the polarity, then Set pick; Save writes the file."
        self.status.value = status_html([head, how, self._message, *getattr(self, "_notes", [])])
        self._update_table()

    def _update_table(self) -> None:
        rows = self._rows()
        if not rows:
            self.table.value = '<div style="font-size: 0.9em;">No picks yet.</div>'
            return
        cells = "".join("<tr>" + "".join(f"<td style='padding: 0 8px;'>{html.escape(str(r[c]))}</td>" for c in COLUMNS)
                        + "</tr>" for r in rows)
        head = "".join(f"<th style='padding: 0 8px; text-align: left;'>{c}</th>" for c in COLUMNS)
        self.table.value = f'<table style="font-size: 0.85em;"><tr>{head}</tr>{cells}</table>'


def phase_picker(source: Any, *, origin: Any = None, epicenter: Optional[Sequence[float]] = None,
                 max_km: Optional[float] = None, csv_path: Any = None, window: Sequence[float] = (-5.0, 30.0),
                 fmin: float = 1.0, fmax: float = 10.0, corners: int = 4, click: Any = "auto") -> PhasePicker:
    """E2 phase picker (see PhasePicker). Show it by making it the last line of a cell.

    Example (module M20)::

        picker = phase_picker(SAC_DIR / "HH", origin=ORIGIN, epicenter=(EV_LAT, EV_LON), max_km=100.0,
                              csv_path="../picks/M20_manual_picks.csv")
        picker
    """
    return PhasePicker(source, origin=origin, epicenter=epicenter, max_km=max_km, csv_path=csv_path, window=window,
                       fmin=fmin, fmax=fmax, corners=corners, click=click)
