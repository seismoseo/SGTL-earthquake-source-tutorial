"""Waveform datasets from STP: list them, fetch them (a dry run unless you add ``--apply``), verify them.

Plain words:

* STP is the program that sends you waveforms from the lab's data center when you log in with your
  personal account. The waveforms arrive as SAC files (one file per station and component, raw counts).
  The tutorial never stores waveforms, your account or the STP program in the repository.
* A dataset (``data/manifests/stp_datasets.yaml``) is a list of earthquakes plus what to request for
  each one: which networks, how far from the earthquakes (``station_radius_km``), which time window
  (``window_s``) and which sensor bands.
* ``sgtl data fetch NAME --apply`` lets PocketQuake (your clone in ``~/sgtl/PocketQuake``, installed by
  ``bin/sgtl-install tools``) make the requests, so the files land exactly where PocketQuake reads them::

      ~/sgtl/data/NAME/                        (or $SGTL_DATA/NAME/)
        event_catalog/event_catalog.csv        the events in Korean time (KST = UTC + 9 h), one row each
        station_table/KS_station.csv, ...      STP's station list (its "sta" command), one file per network
        stp_download/stp_batch.txt             every STP request of the dataset (all events, bands, stations)
        stp_download/SAC/<UTC time>/<band>/<start>.<NET>.<STA>.<CHAN>.sac    the waveforms
        MANIFEST.sha256                        a SHA-256 fingerprint of every file, for sgtl data verify

  ``<UTC time>`` is the origin time as YYYYMMDDHHMMSS, ``<band>`` is HH, HG or EL, ``<start>`` is the
  start of the record. Fetching again skips the events you already have.

Your STP account and the STP program (both personal, both outside the repository):

* ``~/.sgtl/credentials.env``: two lines, ``STP_USER=...`` and ``STP_PASS=...``. Only you may read it
  (``chmod 600 ~/.sgtl/credentials.env``); sgtl refuses to use it otherwise.
* ``~/.sgtl/stp-client.pl``: the STP program the mentor gave you. Its SHA-256 fingerprint must match the
  one in ``install/checksums.txt``.

Both are handed only to the program that talks to STP (through its environment), never printed and never
written anywhere else; anything STP prints is shown with your id and password replaced by ``***``. That program
gets only a short list of environment variables (``CLIENT_ENV_KEEP``: PATH, HOME, LANG, LC_*, TMPDIR, USER, LOGNAME,
TZ, plus thread limits and the STP variables), so settings such as PERL5OPT, PERL5LIB or LD_PRELOAD in your shell
cannot change what runs with your password.

Credit: Minseong Seo (SGTL, Seoul National University). License: MIT.
"""
from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import _paths

__all__ = [
    "Event",
    "Dataset",
    "StpConfig",
    "Plan",
    "datasets",
    "dataset",
    "dataset_folder",
    "kst_catalog_csv",
    "event_state",
    "make_plan",
    "list_datasets",
    "fetch",
    "verify",
    "sac_problem",
    "credentials_file",
    "client_file",
]

UTC = _dt.timezone.utc
KST = _dt.timezone(_dt.timedelta(hours=9))  # Korean Standard Time, the clock of the KMA catalog
KST_OFFSET_HOURS = 9
MANIFEST = ("data", "manifests", "stp_datasets.yaml")
CHECKSUMS = ("install", "checksums.txt")
CLIENT_NAME = "stp-client.pl"
PERL = "/usr/bin/perl"            # PocketQuake starts the STP program with this interpreter
# PocketQuake gives one STP session at most 3600 s. Even at 1 request per second (a very busy server)
# a session of this many requests fits; at the usual 10 per second it takes about 5 minutes. Each course
# dataset (at most 2772 requests) then needs one session; the large project dataset needs several.
MAX_REQUESTS_PER_SESSION = 2800
MARK_RUNNING = ".sgtl-incomplete"  # in SAC/<event>/ while a session for that event is running
MARK_DONE = ".sgtl-fetched"        # in SAC/<event>/ after its session finished without an error
CHECKSUM_FILE = "MANIFEST.sha256"
SAC_HEADER_BYTES = 632
CATALOG_COLUMNS = ("Year", "Month", "Day", "Hour", "Minute", "Second",
                   "Latitude", "Longitude", "Depth", "Magnitude")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UTC_TEXT = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d+)?Z$")
_SAC_NAME = re.compile(r"^(\d{14})\.([^.]+)\.([^.]+)\.([^.]+)\.sac$")


# ----------------------------------------------------------------------------- datasets
@dataclass(frozen=True)
class Event:
    """One earthquake of a dataset (values copied from the shipped KMA catalog; times in UTC)."""

    event_id: str
    origin_utc: _dt.datetime
    latitude: float
    longitude: float
    depth_km: Optional[float]
    ml: float

    @property
    def folder(self) -> str:
        """Name of the event's waveform folder: the UTC origin time to the second, YYYYMMDDHHMMSS."""
        return self.origin_utc.strftime("%Y%m%d%H%M%S")

    @property
    def origin_kst(self) -> _dt.datetime:
        return self.origin_utc.astimezone(KST)


@dataclass(frozen=True)
class Dataset:
    """One entry of ``data/manifests/stp_datasets.yaml``."""

    name: str
    title: str
    sequence: Optional[str]
    use: str
    large: bool
    networks: Tuple[str, ...]
    radius_km: float
    window_s: Tuple[float, float]
    bands: Tuple[str, ...]
    expected: dict
    events: Tuple[Event, ...]

    @property
    def center(self) -> Tuple[float, float]:
        """(latitude, longitude): the mean of the events' coordinates; stations are counted from here."""
        n = len(self.events)
        return (sum(e.latitude for e in self.events) / n, sum(e.longitude for e in self.events) / n)

    @property
    def expected_stations(self) -> int:
        return int(self.expected.get("stations", 0))

    def files_range(self, band: str) -> Tuple[int, int]:
        lo, hi = self.expected.get("files_per_event", {}).get(band, (0, 10 ** 9))
        return int(lo), int(hi)


@dataclass(frozen=True)
class StpConfig:
    """The small configuration object that PocketQuake's ``stp_bridge`` reads (the names are its own).

    ``event_catalog_csv`` is a CSV in Korean time with the columns Year, Month, Day, Hour, Minute,
    Second, Latitude, Longitude, Depth, Magnitude; PocketQuake subtracts ``kst_offset_hours``.
    """

    src_root: str
    epicenter: Tuple[float, float]
    radius_km: float
    event_catalog_csv: str
    kst_offset_hours: int = KST_OFFSET_HOURS


def _parse_utc(text: str) -> _dt.datetime:
    m = _UTC_TEXT.match(str(text))
    if not m:
        raise ValueError(f"origin_utc {text!r} does not look like 2019-07-21T02:04:18Z")
    y, mo, d, h, mi, s = (int(v) for v in m.groups()[:6])
    return _dt.datetime(y, mo, d, h, mi, s, tzinfo=UTC) + _dt.timedelta(seconds=float(m.group(7) or 0))


def _manifest(repo: Optional[Path] = None) -> dict:
    import yaml

    repo = repo or _paths.repo_root()
    path = Path(repo).joinpath(*MANIFEST)
    with open(path, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    if doc.get("schema_version") != 1:
        raise RuntimeError(f"{'/'.join(MANIFEST)} has schema_version {doc.get('schema_version')!r}; this sgtl "
                           "reads version 1. Update your copy of the tutorial (bin/update-from-upstream).")
    if doc.get("status") != "active":
        raise RuntimeError(f"{'/'.join(MANIFEST)} is not active yet (status {doc.get('status')!r}).")
    return doc


def _dataset_from(name: str, spec: dict) -> Dataset:
    events = []
    for ev in spec.get("events") or []:
        depth = ev.get("depth_km")
        events.append(Event(event_id=str(ev["event_id"]), origin_utc=_parse_utc(ev["origin_utc"]),
                            latitude=float(ev["latitude"]), longitude=float(ev["longitude"]),
                            depth_km=None if depth is None else float(depth), ml=float(ev["ml"])))
    if not events:
        raise RuntimeError(f"dataset {name} lists no events")
    window = tuple(float(v) for v in spec["window_s"])
    return Dataset(name=name, title=str(spec.get("title", name)), sequence=spec.get("sequence"),
                   use=str(spec.get("use", "module")), large=bool(spec.get("large", False)),
                   networks=tuple(spec["networks"]), radius_km=float(spec["station_radius_km"]),
                   window_s=(window[0], window[1]), bands=tuple(spec.get("bands") or ("HH", "HG", "EL")),
                   expected=dict(spec.get("expected") or {}), events=tuple(events))


def datasets(repo: Optional[Path] = None) -> Dict[str, Dataset]:
    """Every dataset of the manifest, by name."""
    doc = _manifest(repo)
    return {name: _dataset_from(name, spec) for name, spec in (doc.get("datasets") or {}).items()}


def dataset(name: str, repo: Optional[Path] = None) -> Dataset:
    """One dataset by name; a plain-language error lists the names when it does not exist."""
    all_ds = datasets(repo)
    if name not in all_ds:
        raise RuntimeError(f"There is no dataset called {name!r}. Datasets: {', '.join(all_ds)} "
                           "(see: sgtl data list).")
    return all_ds[name]


def dataset_folder(name: str) -> Path:
    """``$SGTL_DATA/NAME`` (``~/sgtl/data/NAME`` unless SGTL_DATA is set)."""
    return _paths.data_root() / name


def kst_catalog_csv(events: Iterable[Event]) -> str:
    """The events as PocketQuake's catalog CSV: Korean time (UTC + 9 h) to the second, one row each."""
    lines = [",".join(CATALOG_COLUMNS)]
    for ev in events:
        k = ev.origin_kst
        depth = "" if ev.depth_km is None else repr(float(ev.depth_km))
        lines.append(",".join([str(k.year), str(k.month), str(k.day), str(k.hour), str(k.minute), str(k.second),
                               repr(ev.latitude), repr(ev.longitude), depth, repr(ev.ml)]))
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------- files on disk
def _sac_root(folder: Path) -> Path:
    return folder / "stp_download" / "SAC"


def _sac_files(event_dir: Path, band: Optional[str] = None) -> List[Path]:
    pattern = f"{band}/*.sac" if band else "*/*.sac"
    return sorted(p for p in event_dir.glob(pattern) if p.is_file())


def event_state(folder: Path, ev: Event) -> str:
    """'present', 'partial' (a session stopped before it finished) or 'missing'."""
    d = _sac_root(folder) / ev.folder
    if (d / MARK_RUNNING).exists():
        return "partial"
    if (d / MARK_DONE).exists():
        return "present"
    if d.is_dir() and _sac_files(d):
        return "present"  # fetched without sgtl, for example by PocketQuake directly
    return "missing"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sac_problem(path: Path) -> Optional[str]:
    """None when ``path`` looks like a complete binary SAC file, else what is wrong (in plain words).

    A SAC file starts with a 632-byte header; for an evenly sampled record the samples follow as
    4-byte numbers, so the file must hold at least 632 + 4 x npts bytes (npts = number of samples).
    """
    import struct

    try:
        size = path.stat().st_size
        with open(path, "rb") as fh:
            head = fh.read(SAC_HEADER_BYTES)
    except OSError as exc:
        return f"cannot be read ({exc.strerror})"
    if size == 0:
        return "is empty"
    if len(head) < SAC_HEADER_BYTES:
        return "is shorter than a SAC header"
    for order in ("<", ">"):
        nvhdr, npts = struct.unpack(order + "i", head[304:308])[0], struct.unpack(order + "i", head[316:320])[0]
        if nvhdr in (6, 7) and npts >= 0:
            need = SAC_HEADER_BYTES + 4 * npts
            if size < need:
                return f"is cut short ({size} of {need} bytes)"
            return None
    return "is not a SAC file (unknown header version)"


def _read_checksums(path: Path) -> Dict[str, str]:
    out = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and _SHA256.match(parts[0]):
            out[parts[1].strip().lstrip("*")] = parts[0]
    return out


def _write_checksums(path: Path, entries: Dict[str, str]) -> None:
    """``sha256sum`` format, so ``sha256sum -c MANIFEST.sha256`` also works inside the folder."""
    tmp = path.with_name(path.name + ".part")
    tmp.write_text("".join(f"{entries[k]}  {k}\n" for k in sorted(entries)), encoding="utf-8")
    os.replace(tmp, path)


def _tracked_files(folder: Path, event_dirs: Optional[Iterable[str]] = None) -> List[Path]:
    files = [folder / "event_catalog" / "event_catalog.csv"]
    files += sorted((folder / "station_table").glob("*_station.csv"))
    sac = _sac_root(folder)
    dirs = [sac / e for e in event_dirs] if event_dirs is not None else sorted(p for p in sac.glob("*") if p.is_dir())
    for d in dirs:
        files += _sac_files(d)
    return [p for p in files if p.is_file()]


def _update_checksums(folder: Path, event_dirs: Iterable[str]) -> int:
    """Record the fingerprints of the catalog, the station lists and the given events' SAC files."""
    path = folder / CHECKSUM_FILE
    entries = _read_checksums(path)
    event_dirs = list(event_dirs)
    prefixes = tuple(f"stp_download/SAC/{e}/" for e in event_dirs)
    entries = {k: v for k, v in entries.items() if not k.startswith(prefixes)}
    files = _tracked_files(folder, event_dirs)
    for p in files:
        entries[p.relative_to(folder).as_posix()] = _sha256(p)
    _write_checksums(path, entries)
    return len(files)


def _write_if_changed(path: Path, text: str) -> bool:
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return True


# ----------------------------------------------------------------------------- stations and the plan
def _station_rows(folder: Path, networks: Sequence[str]) -> Optional[List[Tuple[str, str, float, float]]]:
    """Rows (network, station, latitude, longitude) of the station lists, or None if one is missing."""
    rows = []
    for net in networks:
        path = folder / "station_table" / f"{net}_station.csv"
        if not path.is_file():
            return None
        with open(path, newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                rows.append((r["Network"].strip(), r["Code"].strip(), float(r["Latitude"]), float(r["Longitude"])))
    return rows


def _distance_km(lat0: float, lon0: float, lat: float, lon: float) -> float:
    """Distance on the WGS84 ellipsoid, by the same library call as PocketQuake (ObsPy; else pyproj)."""
    try:
        from obspy.geodetics.base import gps2dist_azimuth

        return gps2dist_azimuth(lat0, lon0, lat, lon)[0] / 1000.0
    except ImportError:
        from pyproj import Geod

        return Geod(ellps="WGS84").inv(lon0, lat0, lon, lat)[2] / 1000.0


def _stations_within(rows, center: Tuple[float, float], radius_km: float) -> List[Tuple[str, str]]:
    return [(net, code) for net, code, lat, lon in rows if _distance_km(center[0], center[1], lat, lon) <= radius_km]


def _present_stations(band_dir: Path) -> set:
    found = set()
    if band_dir.is_dir():
        for p in band_dir.glob("*.sac"):
            m = _SAC_NAME.match(p.name)
            if m:
                found.add((m.group(2), m.group(3)))
    return found


@dataclass
class Plan:
    """What ``sgtl data fetch`` would do for one dataset."""

    dataset: Dataset
    folder: Path
    states: Dict[str, str]
    stations: Optional[List[Tuple[str, str]]]     # None: STP's station list is not fetched yet
    requests: Dict[str, int]                      # remaining STP requests per pending event folder
    sessions: List[List[Event]] = field(default_factory=list)

    @property
    def pending(self) -> List[Event]:
        return [e for e in self.dataset.events if self.states[e.folder] != "present"]

    @property
    def n_stations(self) -> int:
        return len(self.stations) if self.stations is not None else self.dataset.expected_stations

    @property
    def total_requests(self) -> int:
        return sum(self.requests.values())


def make_plan(ds: Dataset, folder: Optional[Path] = None) -> Plan:
    """Which events are missing, how many STP requests they need, and how they split into sessions.

    The requests are counted the way PocketQuake builds them: one per station within the radius and per
    band, leaving out stations that already have files for that event and band.
    """
    folder = folder or dataset_folder(ds.name)
    states = {e.folder: event_state(folder, e) for e in ds.events}
    rows = _station_rows(folder, ds.networks)
    stations = _stations_within(rows, ds.center, ds.radius_km) if rows is not None else None
    requests = {}
    for ev in ds.events:
        if states[ev.folder] == "present":
            continue
        if stations is None:
            requests[ev.folder] = len(ds.bands) * ds.expected_stations
            continue
        n = 0
        for band in ds.bands:
            have = _present_stations(_sac_root(folder) / ev.folder / band)
            n += sum(1 for s in stations if s not in have)
        requests[ev.folder] = n
    plan = Plan(dataset=ds, folder=folder, states=states, stations=stations, requests=requests)
    session, size = [], 0
    for ev in plan.pending:
        n = requests[ev.folder]
        if n == 0:
            continue
        if session and size + n > MAX_REQUESTS_PER_SESSION:
            plan.sessions.append(session)
            session, size = [], 0
        session.append(ev)
        size += n
    if session:
        plan.sessions.append(session)
    return plan


def _fmt_mb(mb: float) -> str:
    if mb >= 100000:
        return f"{mb / 1000:.0f} GB"
    return f"{mb / 1000:.1f} GB" if mb >= 1000 else f"{mb:.0f} MB"


def _n(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")


def _fmt_minutes(seconds: float) -> str:
    return "under 1 min" if seconds < 60 else f"about {math.ceil(seconds / 60)} min"


def _rates(meta: dict) -> Tuple[float, float]:
    return float(meta.get("mb_per_request", 0.14)), float(meta.get("requests_per_second", 10))


# ----------------------------------------------------------------------------- account, program, PocketQuake
def credentials_file() -> Path:
    return Path.home() / ".sgtl" / "credentials.env"


def client_file() -> Path:
    return Path.home() / ".sgtl" / CLIENT_NAME


def _read_credentials() -> Tuple[Optional[Dict[str, str]], str]:
    """(values, message). The values never appear in the message."""
    path = credentials_file()
    short = _paths.short_path(path)
    if not path.is_file():
        return None, (f"{short} is missing. Create it with two lines, STP_USER=<your STP id> and "
                      f"STP_PASS=<your STP password>, then run: chmod 600 {short}")
    st = path.stat()
    if st.st_uid != os.getuid():
        return None, f"{short} belongs to another user; it must be your own file."
    if st.st_mode & 0o077:
        return None, (f"{short} can be read by other people (permissions {oct(st.st_mode & 0o777)[2:]}). "
                      f"Run: chmod 600 {short}")
    values = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, val = line.split("=", 1)
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
            val = val[1:-1]
        values[key.strip()] = val
    missing = [k for k in ("STP_USER", "STP_PASS") if not values.get(k)]
    if missing:
        return None, f"{short} has no value for {' and '.join(missing)}."
    return {"STP_USER": values["STP_USER"], "STP_PASS": values["STP_PASS"]}, f"{short} (only you can read it)"


def _expected_client_fingerprint(repo: Path) -> Tuple[Optional[str], str]:
    """(SHA-256, raw value) of ``stp-client.pl`` in install/checksums.txt.

    The entry is a comment line ``#fingerprint stp-client.pl <sha256>`` (the installer never downloads
    the STP program, so it has no download address); a plain ``stp-client.pl <sha256> ...`` row also works.
    """
    path = Path(repo).joinpath(*CHECKSUMS)
    raw = ""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None, ""
    for line in lines:
        m = re.match(r"^\s*#\s*fingerprint\s+(\S+)\s+(\S+)", line)
        if not m and not line.lstrip().startswith("#"):
            m = re.match(r"^\s*(\S+)\s+(\S+)", line)
        if m and m.group(1) == CLIENT_NAME:
            raw = m.group(2)
            break
    return (raw if _SHA256.match(raw) else None), raw


def _check_client(repo: Path) -> Tuple[Optional[Path], str]:
    path = client_file()
    short = _paths.short_path(path)
    if not path.is_file():
        return None, (f"{short} is missing. Put the STP program that the mentor gave you there "
                      "(it is personal: never copy it into the repository).")
    want, raw = _expected_client_fingerprint(repo)
    if want is None:
        what = f"says {raw!r}" if raw else "has no entry"
        return None, (f"install/checksums.txt {what} for {CLIENT_NAME}, so the STP program cannot be checked. "
                      "Tell the mentor (friction issue).")
    if _sha256(path) != want:
        return None, (f"{short} is not the STP program the tutorial was checked with (its SHA-256 fingerprint "
                      "differs from install/checksums.txt). Ask the mentor for the current one.")
    return path, f"{short} (fingerprint matches install/checksums.txt)"


def _pocketquake_dir() -> Path:
    from .pq import clone_dir

    return clone_dir()


def _check_pocketquake() -> Tuple[Optional[Path], str]:
    clone = _pocketquake_dir()
    short = _paths.short_path(clone)
    if not (clone / "pocketquake" / "stp_bridge.py").is_file():
        return None, f"{short} has no PocketQuake (pocketquake/stp_bridge.py). Run: bin/sgtl-install tools --apply"
    return clone, short


def _free_mb(path: Path) -> Optional[float]:
    p = path
    while not p.exists() and p != p.parent:
        p = p.parent
    try:
        return shutil.disk_usage(p).free / 1e6
    except OSError:
        return None


# ----------------------------------------------------------------------------- talking to STP (via PocketQuake)
# Runs in a separate Python process with the account in its environment only. Arguments: one JSON object.
_BRIDGE_RUNNER = r'''
import json, sys
from types import SimpleNamespace
a = json.loads(sys.argv[1])
sys.path.insert(0, a["pocketquake"])
from pocketquake import stp_bridge
cfg = SimpleNamespace(**a["config"])
cfg.epicenter = tuple(cfg.epicenter)
if a["stations"]:
    stp_bridge.fetch_stp_station_table(cfg, networks=tuple(a["networks"]))
if a["download"]:
    stp_bridge.download_events_via_stp(
        cfg, window_pre_s=a["window_pre_s"], window_total_s=a["window_total_s"],
        sensor_bands=tuple(a["bands"]), networks=tuple(a["networks"]), skip_existing_station=True)
'''


# Writes stp_download/stp_batch.txt as PocketQuake's batch for ALL events of the dataset (no STP contact, no
# account): after several sessions or a resumed fetch it lists every request of the dataset, as after one session.
_BATCH_RUNNER = r'''
import json, os, sys
from types import SimpleNamespace
a = json.loads(sys.argv[1])
sys.path.insert(0, a["pocketquake"])
from pocketquake import stp_bridge
cfg = SimpleNamespace(**a["config"])
cfg.epicenter = tuple(cfg.epicenter)
stations = stp_bridge._stations_within_radius(cfg, tuple(a["networks"]))
batch = stp_bridge._build_batch(cfg, stations, window_pre_s=a["window_pre_s"], window_total_s=a["window_total_s"],
                                sensor_bands=tuple(a["bands"]))
path = os.path.join(cfg.src_root, "stp_download", "stp_batch.txt")
with open(path + ".part", "w") as fh:
    fh.write(batch + "\n")
os.replace(path + ".part", path)
print("SGTL-RESULT %d" % sum(1 for ln in batch.splitlines() if ln.startswith("win ")))
'''


def _redact(text: str, secrets: Sequence[str]) -> str:
    for s in sorted((s for s in secrets if s), key=len, reverse=True):
        text = text.replace(s, "***")
    return text


# The helper processes (and the STP program, which inherits their environment) get an environment built from this
# allowlist, never a copy of os.environ: variables such as PERL5OPT, PERL5LIB or LD_PRELOAD would change what Perl
# runs with the account, although the program's SHA-256 fingerprint was checked.
CLIENT_ENV_KEEP = ("PATH", "HOME", "LANG", "TMPDIR", "USER", "LOGNAME", "TZ")  # plus every LC_* variable
CLIENT_ENV_SET = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                  "NUMEXPR_MAX_THREADS": "1", "NUMPY_MADVISE_HUGEPAGE": "0", "PYTHONNOUSERSITE": "1"}


def _client_env(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in CLIENT_ENV_KEEP or k.startswith("LC_")}
    env.update(CLIENT_ENV_SET)
    env.update(extra or {})
    return env


def _bridge_env(creds: Dict[str, str], client: Path) -> Dict[str, str]:
    return _client_env({"STP_USER": creds["STP_USER"], "STP_PASS": creds["STP_PASS"],
                        "STP_PERL_SCRIPT": str(client)})


def _run_bridge(clone: Path, cfg: StpConfig, ds: Dataset, creds: Dict[str, str], client: Path, *,
                stations: bool, download: bool) -> int:
    args = {"pocketquake": str(clone), "config": asdict(cfg), "networks": list(ds.networks),
            "bands": list(ds.bands), "window_pre_s": -ds.window_s[0],
            "window_total_s": ds.window_s[1] - ds.window_s[0], "stations": stations, "download": download}
    nice = ["nice", "-n", "10"] if shutil.which("nice") else []
    cmd = nice + [sys.executable, "-I", "-c", _BRIDGE_RUNNER, json.dumps(args)]
    what = []
    if stations:
        what.append("fetch_stp_station_table")
    if download:
        what.append("download_events_via_stp")
    print(f"+ {' '.join(nice)} python: pocketquake.stp_bridge.{' + '.join(what)} "
          f"(PocketQuake {_paths.short_path(clone)}; account and program handed over in the environment)",
          flush=True)
    secrets = [creds["STP_USER"], creds["STP_PASS"]]
    proc = subprocess.Popen(cmd, cwd=str(Path(cfg.src_root)), env=_bridge_env(creds, client),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1)
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write("  | " + _redact(line, secrets))
            sys.stdout.flush()
        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        proc.wait()
        print("Stopped. Run the same command again later: it continues where it stopped.")
        return 130


def _write_full_batch(clone: Path, ds: Dataset, folder: Path, catalog: Path) -> None:
    """stp_download/stp_batch.txt = every request of the dataset (PocketQuake's batch builder, all events)."""
    cfg = StpConfig(src_root=str(folder), epicenter=ds.center, radius_km=ds.radius_km, event_catalog_csv=str(catalog))
    args = {"pocketquake": str(clone), "config": asdict(cfg), "networks": list(ds.networks), "bands": list(ds.bands),
            "window_pre_s": -ds.window_s[0], "window_total_s": ds.window_s[1] - ds.window_s[0]}
    env = _client_env()
    try:
        out = subprocess.run([sys.executable, "-I", "-c", _BATCH_RUNNER, json.dumps(args)], cwd=str(folder), env=env,
                             capture_output=True, text=True, timeout=600)
        n = [ln.split()[1] for ln in out.stdout.splitlines() if ln.startswith("SGTL-RESULT ")]
    except (OSError, subprocess.SubprocessError):
        out, n = None, []
    if out is not None and out.returncode == 0 and n:
        print(f"wrote stp_download/stp_batch.txt: all {n[0]} requests of the dataset (PocketQuake's batch format)")
    else:
        print("Note: stp_download/stp_batch.txt still lists only the requests of the last STP session.")


def _mark(folder: Path, events: Iterable[Event], running: bool) -> None:
    for ev in events:
        d = _sac_root(folder) / ev.folder
        d.mkdir(parents=True, exist_ok=True)
        if running:
            (d / MARK_DONE).unlink(missing_ok=True)
            (d / MARK_RUNNING).write_text(f"session started {_dt.datetime.now(UTC):%Y-%m-%dT%H:%M:%SZ}\n")
        else:
            n = len(_sac_files(d))
            (d / MARK_DONE).write_text(json.dumps({"event_id": ev.event_id, "sac_files": n,
                                                   "finished_utc": f"{_dt.datetime.now(UTC):%Y-%m-%dT%H:%M:%SZ}"})
                                       + "\n")
            (d / MARK_RUNNING).unlink(missing_ok=True)


# ----------------------------------------------------------------------------- sgtl data list
def list_datasets() -> int:
    repo = _paths.repo_root()
    meta = _manifest(repo)
    mb_per, _ = _rates(meta)
    root = _paths.data_root()
    print(f"Datasets in {'/'.join(MANIFEST)}; files go to {_paths.short_path(root)}/<dataset>/")
    print(f"{'dataset':<15}{'use':<9}{'events':>6}{'stations':>10}{'size':>13}   on this computer")
    for name, ds in datasets(repo).items():
        size = len(ds.events) * len(ds.bands) * ds.expected_stations * mb_per
        folder = root / name
        states = [event_state(folder, e) for e in ds.events]
        have, part = states.count("present"), states.count("partial")
        if not folder.exists() or (have == 0 and part == 0):
            here = "not fetched"
        else:
            here = f"{have} of {len(states)} events" + (f" ({part} interrupted)" if part else "")
        note = "  (large: fetching needs --large)" if ds.large else ""
        print(f"{name:<15}{ds.use:<9}{len(ds.events):>6}{ds.expected_stations:>10}{'about ' + _fmt_mb(size):>13}"
              f"   {here}{note}")
    print("Sizes and station counts are estimates from the maintainers' test downloads (see the manifest).")
    print("See the plan for one dataset (nothing is downloaded):  sgtl data fetch <dataset>")
    return 0


# ----------------------------------------------------------------------------- sgtl data fetch
def _print_plan(plan: Plan, meta: dict) -> None:
    ds = plan.dataset
    mb_per, rps = _rates(meta)
    have = sum(1 for s in plan.states.values() if s == "present")
    part = sum(1 for s in plan.states.values() if s == "partial")
    print(f"Dataset {ds.name}: {ds.title} ({len(ds.events)} events, {ds.use} dataset"
          + (", large" if ds.large else "") + ")")
    print(f"Folder: {_paths.short_path(plan.folder)}")
    print(f"Events: {have} already here, {len(plan.pending)} to fetch"
          + (f" ({part} of them interrupted earlier; only their missing stations are requested)" if part else ""))
    lat, lon = ds.center
    if plan.stations is not None:
        print(f"Stations: {plan.n_stations} within {ds.radius_km:g} km of ({lat:.3f}, {lon:.3f}) in STP's station "
              "list (station_table/, fetched earlier)")
    else:
        print(f"Stations: about {plan.n_stations} within {ds.radius_km:g} km of ({lat:.3f}, {lon:.3f}) (number from "
              "the manifest; --apply first fetches STP's own station list)")
    if not plan.pending:
        return
    n = plan.total_requests
    start = ds.window_s[0]
    when = f"{abs(start):g} s {'before' if start < 0 else 'after'} the origin time"
    print(f"Requests: {n} STP 'win' commands, one per station and band ({', '.join(ds.bands)}), each a record "
          f"of {ds.window_s[1] - ds.window_s[0]:g} s starting {when}; in {_n(len(plan.sessions), 'STP session')}")
    # mb_per_request was measured on records of 500 s; a longer record is proportionally larger.
    size_mb = n * mb_per * (ds.window_s[1] - ds.window_s[0]) / 500.0
    print(f"Download: about {_fmt_mb(size_mb)}, {_fmt_minutes(n / rps)} at {rps:g} requests per second "
          "(longer when STP is busy)")


def _write_session_catalog(folder: Path, events: Sequence[Event]) -> Path:
    path = folder / "stp_download" / "fetch_catalog.csv"
    _write_if_changed(path, kst_catalog_csv(events))
    return path


def _summary(plan: Plan) -> None:
    ds = plan.dataset
    print(f"{'event':<16}" + "".join(f"{b:>6}" for b in ds.bands) + "   SAC files per band")
    total, size = 0, 0
    for ev in ds.events:
        d = _sac_root(plan.folder) / ev.folder
        counts = [len(_sac_files(d, b)) for b in ds.bands]
        total += sum(counts)
        size += sum(p.stat().st_size for p in _sac_files(d))
        print(f"{ev.folder:<16}" + "".join(f"{c:>6}" for c in counts))
    print(f"{total} SAC files, {_fmt_mb(size / 1e6)} in {_paths.short_path(_sac_root(plan.folder))}")


def fetch(name: str, apply: bool = False, large: bool = False) -> int:
    """``sgtl data fetch NAME [--apply] [--large]``: the plan, and with ``--apply`` the download."""
    repo = _paths.repo_root()
    meta = _manifest(repo)
    ds = dataset(name, repo)
    folder = dataset_folder(name)
    plan = make_plan(ds, folder)
    mb_per, rps = _rates(meta)
    _print_plan(plan, meta)
    if not plan.pending:
        print(f"Nothing to fetch: all {len(ds.events)} events are here. Check them with:  sgtl data verify {name}")
        return 0

    problems = []
    print("Before starting:")

    def status(ok: bool, what: str, text: str) -> None:
        print(f"  {'OK  ' if ok else 'STOP'}  {what}: {text}")
        if not ok:
            problems.append(what)

    if ds.large:
        status(large, "Size", f"this dataset is large (about {_fmt_mb(plan.total_requests * mb_per)})"
               + ("" if large else "; add --large to confirm"))
    creds, msg = _read_credentials()
    status(creds is not None, "STP account", msg)
    client, msg = _check_client(repo)
    status(client is not None, "STP program", msg)
    status(os.access(PERL, os.X_OK), "Perl", PERL + (" (runs the STP program)" if os.access(PERL, os.X_OK)
                                                     else " is missing; ask the server administrator"))
    clone, msg = _check_pocketquake()
    status(clone is not None, "PocketQuake", msg)
    free = _free_mb(folder)
    need = plan.total_requests * mb_per * 1.2 + 500
    if free is not None:
        status(free >= need, "Disk space", f"{_fmt_mb(free)} free in {_paths.short_path(_paths.data_root())}"
               + ("" if free >= need else f"; about {_fmt_mb(need)} is needed"))

    print("Steps:")
    print(f"  write {_paths.short_path(folder / 'event_catalog' / 'event_catalog.csv')} "
          f"({len(ds.events)} events, Korean time)")
    if plan.stations is None:
        print(f"  fetch STP's station list (sta) into station_table/{{{','.join(ds.networks)}}}_station.csv")
    for i, sess in enumerate(plan.sessions, 1):
        n = sum(plan.requests.get(e.folder, 0) for e in sess)
        print(f"  STP session {i}: {_n(len(sess), 'event')}, {_n(n, 'request')}")
    done = [e for e in plan.pending if plan.requests.get(e.folder, 0) == 0]
    if done:
        print(f"  mark {_n(len(done), 'interrupted event')} complete (every station already has its files)")
    print(f"  record SHA-256 fingerprints in {CHECKSUM_FILE}")
    if not apply:
        extra = " --large" if ds.large else ""
        print(f"Dry run: nothing was downloaded. To do it:  sgtl data fetch {name} --apply{extra}")
        if problems:
            print(f"Fix the STOP lines first ({', '.join(problems)}).")
        return 1 if problems else 0
    if problems:
        print(f"Not started: fix the STOP lines above first ({', '.join(problems)}).")
        return 1
    assert creds is not None and client is not None and clone is not None

    print()
    (folder / "stp_download" / "SAC").mkdir(parents=True, exist_ok=True)
    catalog = folder / "event_catalog" / "event_catalog.csv"
    if _write_if_changed(catalog, kst_catalog_csv(ds.events)):
        print(f"wrote {_paths.short_path(catalog)}")
    if plan.stations is None:
        print("== STP's station list")
        cfg = StpConfig(src_root=str(folder), epicenter=ds.center, radius_km=ds.radius_km,
                        event_catalog_csv=str(catalog))
        rc = _run_bridge(clone, cfg, ds, creds, client, stations=True, download=False)
        if rc != 0 or _station_rows(folder, ds.networks) is None:
            print("Fetching STP's station list failed (see the lines above). Nothing else was requested.")
            return 1
        plan = make_plan(ds, folder)
        print(f"Stations: {plan.n_stations} within {ds.radius_km:g} km; {_n(plan.total_requests, 'request')} "
              f"in {_n(len(plan.sessions), 'STP session')}")
    for ev in plan.pending:  # nothing left to request for these: complete already
        if plan.requests.get(ev.folder, 0) == 0:
            _mark(folder, [ev], running=False)
            _update_checksums(folder, [ev.folder])
    for i, sess in enumerate(plan.sessions, 1):
        n = sum(plan.requests[e.folder] for e in sess)
        print(f"== STP session {i} of {len(plan.sessions)}: {_n(len(sess), 'event')}, {_n(n, 'request')} "
              f"({_fmt_minutes(n / rps)})")
        cfg = StpConfig(src_root=str(folder), epicenter=ds.center, radius_km=ds.radius_km,
                        event_catalog_csv=str(_write_session_catalog(folder, sess)))
        _mark(folder, sess, running=True)
        rc = _run_bridge(clone, cfg, ds, creds, client, stations=False, download=True)
        if rc == 130:
            return 130
        if rc != 0:
            print(f"STP session {i} failed (see the lines above). The files that arrived are kept. Run the same "
                  "command again: it requests only what is still missing.")
            return 1
        _mark(folder, sess, running=False)
        n_files = _update_checksums(folder, [e.folder for e in sess])
        print(f"session {i} finished; fingerprints of {n_files} files recorded in {CHECKSUM_FILE}")
    _write_full_batch(clone, ds, folder, catalog)
    _summary(make_plan(ds, folder))
    print(f"Next, check the files:  sgtl data verify {name}")
    return 0


# ----------------------------------------------------------------------------- sgtl data verify
def verify(name: str, write: bool = False) -> int:
    """``sgtl data verify NAME [--write]``: counts, damaged files and SHA-256 fingerprints."""
    repo = _paths.repo_root()
    ds = dataset(name, repo)
    folder = dataset_folder(name)
    results: List[str] = []

    def line(status: str, what: str, text: str) -> None:
        print(f"{status:<4}  {what}: {text}")
        results.append(status)

    print(f"Dataset {name} in {_paths.short_path(folder)}")
    if not folder.is_dir():
        line("FAIL", "Folder", f"missing. Fetch the dataset first:  sgtl data fetch {name} --apply")
        return 1
    catalog = folder / "event_catalog" / "event_catalog.csv"
    if not catalog.is_file():
        line("FAIL", "Event catalog", f"missing; run:  sgtl data fetch {name} --apply")
    elif catalog.read_text(encoding="utf-8") != kst_catalog_csv(ds.events):
        line("FAIL", "Event catalog", f"differs from the manifest; run:  sgtl data fetch {name} --apply")
    else:
        line("PASS", "Event catalog", f"{len(ds.events)} events, as in the manifest")
    rows = _station_rows(folder, ds.networks)
    if rows is None:
        line("FAIL", "Station lists", f"missing for {', '.join(ds.networks)}; run:  sgtl data fetch {name} --apply")
    else:
        line("PASS", "Station lists", ", ".join(f"{n} {sum(1 for r in rows if r[0] == n)}" for n in ds.networks))

    basis = ds.expected.get("basis", "estimate")
    print(f"Files per event and band (allowed range from the manifest, basis: {basis}):")
    n_files, n_bytes, broken, short_sets, no_data = 0, 0, [], 0, []
    for ev in ds.events:
        state = event_state(folder, ev)
        d = _sac_root(folder) / ev.folder
        if state == "missing":
            line("FAIL", ev.folder, f"not fetched yet; run:  sgtl data fetch {name} --apply")
            continue
        if state == "partial":
            line("FAIL", ev.folder, f"its download stopped before the end; run:  sgtl data fetch {name} --apply")
            continue
        parts, bad = [], False
        for band in ds.bands:
            files = _sac_files(d, band)
            lo, hi = ds.files_range(band)
            ok = lo <= len(files) <= hi
            bad |= not ok
            parts.append(f"{band} {len(files)}" + ("" if ok else f" (allowed {lo}-{hi})"))
            comps: Dict[Tuple[str, str], int] = {}
            for p in files:
                n_files += 1
                n_bytes += p.stat().st_size
                problem = sac_problem(p)
                if problem:
                    broken.append(f"{p.relative_to(folder).as_posix()} {problem}")
                m = _SAC_NAME.match(p.name)
                if m:
                    comps[(m.group(2), m.group(3))] = comps.get((m.group(2), m.group(3)), 0) + 1
            short_sets += sum(1 for v in comps.values() if v < 3)
        if not _sac_files(d):
            no_data.append(ev.folder)
        line("FAIL" if bad else "PASS", ev.folder, ", ".join(parts))
    if no_data:
        line("WARN", "No files", f"{len(no_data)} event(s) have no SAC file at all (STP may hold no data for that "
             f"time): {', '.join(no_data[:5])}" + (" ..." if len(no_data) > 5 else ""))
    if broken:
        line("FAIL", "Damaged files", f"{len(broken)}; delete them and fetch again:  sgtl data fetch {name} --apply "
             f"(first: {broken[0]})")
    else:
        line("PASS", "SAC files", f"{n_files} files ({_fmt_mb(n_bytes / 1e6)}), none empty or cut short")
    if short_sets:
        line("WARN", "Components", f"{short_sets} station-band set(s) have fewer than three components "
             "(normal for some old single-component stations)")

    path = folder / CHECKSUM_FILE
    recorded = _read_checksums(path)
    if recorded:
        changed, missing = [], []
        for rel, sha in sorted(recorded.items()):
            p = folder / rel
            if not p.is_file():
                missing.append(rel)
            elif _sha256(p) != sha:
                changed.append(rel)
        current = {p.relative_to(folder).as_posix() for p in _tracked_files(folder)}
        new = sorted(current - set(recorded))
        if changed or missing:
            first = (changed + missing)[0]
            line("FAIL", "Fingerprints", f"{len(changed)} changed, {len(missing)} missing of {len(recorded)} "
                 f"recorded files (first: {first}). Fetch again, or run with --write if you changed them on purpose")
        else:
            line("PASS", "Fingerprints", f"all {len(recorded)} recorded files unchanged ({CHECKSUM_FILE})")
        if new:
            line("WARN", "Fingerprints", f"{len(new)} file(s) are not recorded yet (first: {new[0]}); "
                 "add them with --write")
    elif not write:
        line("WARN", "Fingerprints", f"no {CHECKSUM_FILE} yet. Record the files you have now:  "
             f"sgtl data verify {name} --write")
    if write:
        entries = {p.relative_to(folder).as_posix(): _sha256(p) for p in _tracked_files(folder)}
        _write_checksums(path, entries)
        print(f"wrote {_paths.short_path(path)} ({len(entries)} files)")
    n_fail, n_warn = results.count("FAIL"), results.count("WARN")
    verdict = " Fix the FAIL lines first." if n_fail else " The dataset is complete."
    print(f"\n{n_fail} FAIL, {n_warn} WARN.{verdict}")
    return 1 if n_fail else 0
