"""Offline SeisComP sessions: file conversion and launch, never automatic picking.

Waveforms and metadata stay local under work/; the original SAC/StationXML are
read only. SeisComP is a separate native installation, outside the Python kernel.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from . import _paths

NS = "http://geofon.gfz-potsdam.de/ns/seiscomp3-schema/0.13"
COLUMNS = ("station", "phase", "channel", "time_utc", "uncertainty_s", "polarity")


def _sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def installation() -> Path:
    return Path(os.environ.get("SGTL_SEISCOMP_ROOT", str(
        Path(os.environ.get("SGTL_HOME", str(Path.home() / "sgtl"))) / "seiscomp"))).expanduser().resolve()


def _environment(session: Path, *, display=True):
    """Do not load another application's Qt plugins, Python or shared libraries."""
    root = installation()
    env = os.environ.copy()
    for key in ("LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONPATH", "PYTHONHOME",
                "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QT_QPA_PLATFORM"):
        env.pop(key, None)
    env.update(SEISCOMP_ROOT=str(root), SEISCOMP_LOCAL_CONFIG=str(session / ".seiscomp"),
               XDG_CONFIG_HOME=str(session / ".config"), XDG_CACHE_HOME=str(session / ".cache"),
               LD_LIBRARY_PATH=os.pathsep.join(map(str, (root / "lib", root / "lib64",
                                                         root / "extra" / "lib64"))),
               OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    if not display:
        env["QT_QPA_PLATFORM"] = "offscreen"
    return env


def _runtime_dirs(session):
    for name in (".seiscomp", ".config", ".cache"):
        (session / name).mkdir(mode=0o700, exist_ok=True)


def doctor() -> int:
    """Native executables/dependencies and the current SSH display, no server setup."""
    root = installation()
    failures = 0
    print(f"SeisComP installation: {root}")
    # SeisComP itself creates a local log directory even for --version. Isolate it.
    with tempfile.TemporaryDirectory(prefix="sgtl-gui-check-") as folder:
        runtime = Path(folder)
        _runtime_dirs(runtime)
        env = _environment(runtime, display=False)
        for name in ("scrttv", "scolv", "fdsnxml2inv"):
            exe = root / "bin" / name
            if not exe.is_file() or not os.access(exe, os.X_OK):
                print(f"FAIL {name}: missing; see docs/seiscomp_gui.md installation")
                failures += 1
                continue
            p = subprocess.run([str(exe), "--version"], env=env, capture_output=True, text=True, timeout=20)
            output = (p.stdout + p.stderr).strip()
            print(f"{'PASS' if p.returncode == 0 else 'FAIL'} {name}: {output}")
            failures += p.returncode != 0
    if os.environ.get("DISPLAY"):
        print("PASS DISPLAY is set; opening a window is the final display check.")
    else:
        print("WARN no DISPLAY: reconnect with X11 forwarding (docs/seiscomp_gui.md). "
              "Conversion and notebook work still work in this terminal.")
    return 1 if failures else 0


def _origin_xml(path, origin, lat, lon, depth, label):
    """SCML depths are kilometres; QuakeML depths would be metres."""
    ET.register_namespace("", NS)
    def child(parent, tag, text=None, **attrs):
        element = ET.SubElement(parent, f"{{{NS}}}{tag}", attrs)
        if text is not None:
            element.text = str(text)
        return element
    root = ET.Element(f"{{{NS}}}seiscomp", version="0.13")
    ep = child(root, "EventParameters", publicID="sgtl/gui/session")
    oid = "sgtl/gui/catalog-origin"
    org = child(ep, "origin", publicID=oid)
    for name, value in (("time", origin), ("latitude", lat), ("longitude", lon), ("depth", depth)):
        child(child(org, name), "value", value)
    child(org, "methodID", "catalog-context-only")
    ev = child(ep, "event", publicID="sgtl/gui/event")
    child(ev, "preferredOriginID", oid)
    child(ev, "type", "earthquake")
    desc = child(ev, "description")
    child(desc, "text", label)
    child(desc, "type", "region name")
    child(child(ev, "originReference"), "originID", oid)
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding="UTF-8", xml_declaration=True)


def _config_files(folder, manifest):
    from obspy import UTCDateTime
    span = max(UTCDateTime(r["end"]) for r in manifest["records"]) - min(UTCDateTime(r["start"]) for r in manifest["records"])
    # Explicit module files prevent loading an existing real-time configuration.
    common = "\n".join((
        "# SGTL local offline session; all times UTC.",
        "author = SGTL-trainee", "agencyID = SGTL",
        "connection.server = localhost/production",  # unused with --offline
        "scheme.unit.distanceInKM = true", "scheme.records.showEngineeringValues = false",
        "scheme.precision.time = 3",
        "scheme.map.showGrid = true", "scheme.map.showCities = false",
        "map.layers = grid, cities, features, stations, origins",
        ""))
    (folder / "scrttv.cfg").write_text(common + "\n".join((
        "# --no-inventory displays original counts (no gain correction).",
        "autoApplyFilter = false", f"bufferSize = {math.ceil(span) + 2}",
        f"streams.rows = {min(18, len({r['id'] for r in manifest['records']}))}",
        'filters = "Causal 1-10 Hz;RMHP(10)>>ITAPER(5)>>BW(3,1,10)"',
        "")), encoding="utf-8")
    (folder / "scolv.cfg").write_text(common + "\n".join((
        "picker.phases.favourites = P, S", "picker.showPhases = P, S",
        "picker.loadAllPicks = false", "picker.loadAllComponents = true",
        "picker.showAllComponents = true", "picker.showDataInSensorUnit = false",
        "picker.ignoreUnconfiguredStations = false", "picker.limitStationAcquisition = false",
        "picker.preOffset = 30", "picker.postOffset = 90", "picker.minimumTimeWindow = 120",
        "picker.uncertainties = 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0",
        'picker.filters = "Causal 1-10 Hz;RMHP(10)>>ITAPER(5)>>BW(3,1,10)"',
        "olv.computeMagnitudesAfterRelocate = false", "olv.computeMissingTakeOffAngles = false",
        "olv.defaultAddStationsDistance = 0.9", "olv.loadAdditionalStations = true",
        "olv.hideStationsWithoutData = true", "olv.map.event.defaultRadius = 1.0",
        "")), encoding="utf-8")


def _write_session(stream, inventory, *, out, origin, lat, lon, depth, label, sources):
    """Stage completely, convert with the actual native tool, then rename once."""
    import numpy as np
    from obspy import UTCDateTime

    out = Path(out).expanduser().resolve()
    if out.exists():
        raise ValueError(f"Session already exists: {out}. Choose a new --out; your work is never overwritten.")
    origin = UTCDateTime(origin)
    if not all(math.isfinite(float(v)) for v in (lat, lon, depth)) or not (-90 <= lat <= 90 and -180 <= lon <= 180 and depth >= 0):
        raise ValueError("Origin latitude/longitude/depth must be finite degrees/degrees/nonnegative km.")
    if not stream:
        raise ValueError("No records selected.")
    stream = stream.copy().sort(keys=["network", "station", "location", "channel", "starttime"])
    previous = {}
    records = []
    for tr in stream:
        if not re.fullmatch(r"[A-Z0-9]{1,2}\.[A-Z0-9]{1,5}\.[A-Z0-9]{0,2}\.[A-Z0-9]{3}", tr.id):
            raise ValueError(f"Invalid MiniSEED 2 stream ID: {tr.id}")
        if np.ma.is_masked(tr.data) or not np.all(np.isfinite(tr.data)) or tr.stats.npts < 2 or tr.stats.sampling_rate <= 0:
            raise ValueError(f"Nonfinite, masked, empty or invalid record: {tr.id}; repair the source explicitly first.")
        if tr.id in previous and tr.stats.starttime <= previous[tr.id]:
            raise ValueError(f"Overlapping records for {tr.id}; select one source instead of silently merging.")
        previous[tr.id] = tr.stats.endtime
        matches = inventory.select(network=tr.stats.network, station=tr.stats.station,
                                   location=tr.stats.location, channel=tr.stats.channel, time=origin)
        channels = [ch for net in matches for sta in net for ch in sta]
        if len(channels) != 1:
            raise ValueError(f"Need exactly one matching StationXML channel epoch at origin: {tr.id}; got {len(channels)}.")
        ch = channels[0]
        if ch.start_date and ch.start_date > tr.stats.starttime or ch.end_date and ch.end_date < tr.stats.endtime:
            raise ValueError(f"Record crosses a metadata epoch: {tr.id}; split the session at that epoch.")
        if ch.sample_rate is None or not np.isclose(float(ch.sample_rate), tr.stats.sampling_rate):
            raise ValueError(f"Sample rate disagrees with StationXML: {tr.id}.")
        records.append(dict(id=tr.id, start=str(tr.stats.starttime), end=str(tr.stats.endtime),
                            sampling_rate=float(tr.stats.sampling_rate), npts=tr.stats.npts,
                            latitude=ch.latitude, longitude=ch.longitude))
        # FLOAT64 stores the original int32/float32 counts exactly; no filtering,
        # zero filling, response correction or SAC reference-pick headers.
        tr.data = np.asarray(tr.data, dtype=np.float64)
    # Keep exactly the channels and epochs represented by the selected records.
    # A station metadata file may also contain accelerometers and other epochs.
    inventory = inventory.copy()
    for net in inventory:
        for sta in net:
            sta.channels = [ch for ch in sta if f"{net.code}.{sta.code}.{ch.location_code}.{ch.code}" in previous
                            and (ch.start_date is None or ch.start_date <= origin)
                            and (ch.end_date is None or ch.end_date >= origin)]
        net.stations = [sta for sta in net if sta.channels]
    inventory.networks = [net for net in inventory if net.stations]
    converter = installation() / "bin" / "fdsnxml2inv"
    if not converter.is_file():
        raise RuntimeError("fdsnxml2inv is missing. Run bin/sgtl-install seiscomp --apply, then bin/sgtl gui doctor.")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".sgtl-gui-", dir=out.parent) as tmp:
        stage = Path(tmp) / "session"
        stage.mkdir(mode=0o700)
        _runtime_dirs(stage)
        stream.write(str(stage / "waveforms.mseed"), format="MSEED", encoding="FLOAT64", reclen=4096)
        inventory.write(str(stage / "stations.xml"), format="STATIONXML", validate=True)
        (stage / "convert.cfg").write_text("# Offline inventory conversion: no database plugins.\n", encoding="utf-8")
        p = subprocess.run([str(converter), "--config-file", str(stage / "convert.cfg"), "-f", str(stage / "stations.xml"), str(stage / "inventory.xml")],
                           env=_environment(stage, display=False), capture_output=True, text=True, timeout=120)
        (stage / "inventory-conversion.log").write_text(p.stdout + p.stderr, encoding="utf-8")
        if p.returncode or not (stage / "inventory.xml").is_file():
            raise RuntimeError(f"StationXML conversion failed; no session was installed:\n{p.stderr[-4000:]}")
        _origin_xml(stage / "event.xml", str(origin), lat, lon, depth, label)
        manifest = dict(schema=1, label=label, origin_utc=str(origin), latitude=lat,
                        longitude=lon, depth_km=depth, units="original counts", records=records,
                        sources=sources, original_picks_exported=False,
                        files={name: _sha(stage / name) for name in ("waveforms.mseed", "stations.xml", "inventory.xml", "event.xml")})
        (stage / "session.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        _map_geometry(stage)
        _config_files(stage, manifest)
        stage.rename(out)
    print(f"Prepared {len(records)} records in {out}; original counts and UTC preserved; no reference picks.")
    return out


def prepare(dataset="sangju2019", *, event="20190721020418", band="HH", out, apply=False,
            waveforms=None, stationxml=None, origin=None, latitude=None, longitude=None, depth_km=None):
    """Teaching selection or an explicitly described, personally fetched project event."""
    from obspy import read, read_inventory, Stream, UTCDateTime
    from obspy.core.inventory import Inventory
    from . import data

    if not re.fullmatch(r"[A-Z0-9]{2}", band):
        raise ValueError("--band must be two channel-code characters, e.g. HH.")
    if waveforms is None:
        if not re.fullmatch(r"[a-z0-9_]+", dataset) or not re.fullmatch(r"\d{14}", event):
            raise ValueError("Use a dataset name and a UTC event folder YYYYMMDDHHMMSS.")
        origin = UTCDateTime.strptime(event, "%Y%m%d%H%M%S")
        catalog = data.kma_catalog()
        rows = catalog.loc[catalog.origin_utc.map(lambda x: abs(UTCDateTime(x.to_pydatetime()) - origin) < .001)]
        if len(rows) != 1:
            raise ValueError("No unique teaching catalog event. For a research event use --waveforms and explicit origin/coordinates.")
        row = rows.iloc[0]
        latitude, longitude, depth_km = float(row.latitude), float(row.longitude), float(row.depth_km)
        if not math.isfinite(depth_km):
            raise ValueError("Catalog depth is missing. Choose an explicit context depth with --waveforms and document its assumption.")
        waveforms = _paths.data_root() / dataset / "stp_download" / "SAC" / event / band
        label = f"KMA {row.event_id}; catalog context, own picks"
    else:
        if any(v is None for v in (origin, latitude, longitude, depth_km)):
            raise ValueError("Project mode needs --origin (explicit UTC), --latitude, --longitude, --depth-km.")
        if not re.search(r"(?:Z|\+00:00)$", str(origin)):
            raise ValueError("--origin must have an explicit UTC suffix Z or +00:00.")
        origin = UTCDateTime(origin)
        label = "Student-selected event; context origin, own picks"
    files = sorted(Path(waveforms).expanduser().glob(f"*.{band}?.sac"))
    if not files:
        raise FileNotFoundError(f"No {band} SAC files under {waveforms}. Fetch the data in M03 first.")
    meta = Path(stationxml).expanduser() if stationxml else _paths.data_root() / "metadata" / "stationxml"
    print(f"Plan: read {len(files)} SAC files, select records within 100 km, check StationXML epochs, "
          f"convert local copies for SeisComP, write {out}.")
    print("No server, messaging, database, automatic picks or relocation is started.")
    if not apply:
        print("Dry run: nothing written. Repeat with --apply.")
        return 0
    from obspy.geodetics import gps2dist_azimuth
    stream, inventory, sources = Stream(), Inventory([], source="SGTL; original StationXML attribution retained"), []
    selected = {}
    for path in files:
        tr = read(str(path), format="SAC")[0]
        key = f"{tr.stats.network}.{tr.stats.station}"
        if key not in selected:
            ipath = meta / f"{key}.xml"
            if not ipath.is_file():
                raise FileNotFoundError(f"Missing {ipath}; install metadata before preparing the session.")
            inv = read_inventory(str(ipath)).select(time=origin)
            if not inv.networks or not inv[0].stations:
                raise ValueError(f"No station metadata valid at {origin}: {key}")
            km = gps2dist_azimuth(latitude, longitude, inv[0][0].latitude, inv[0][0].longitude)[0] / 1000
            selected[key] = inv if km <= 100 else None
            if km <= 100:
                inventory += inv
                sources.append(dict(name=ipath.name, sha256=_sha(ipath), kind="StationXML"))
        if selected[key] is not None:
            stream += tr
            sources.append(dict(name=path.name, sha256=_sha(path), kind="SAC"))
    _write_session(stream, inventory, out=out, origin=origin, lat=latitude, lon=longitude,
                   depth=depth_km, label=label, sources=sources)
    return 0


def demo(*, out, apply=False):
    """A reproducible public-data-free rehearsal, including a deliberately visible gap."""
    print(f"Plan: create a synthetic 3-station, 3-component rehearsal under {out} (no STP data).")
    if not apply:
        print("Dry run: nothing written. Repeat with --apply.")
        return 0
    import numpy as np
    from obspy import Trace, Stream, UTCDateTime
    from obspy.core.inventory import Inventory, Network, Station, Channel, Site, Response, InstrumentSensitivity
    rng = np.random.default_rng(207)
    origin = UTCDateTime("2031-04-05T06:07:00Z")
    stations, stream = [], Stream()
    for n, (lat, lon) in enumerate(((36.59, 128.10), (36.34, 128.10), (36.50, 128.43)), 1):
        code = f"DEMO{n}"
        channels = []
        p, s = 3.0 + n, 1.73 * (3.0 + n)
        times = np.arange(12000) / 100 - 30
        for cmp in "ZNE":
            values = rng.normal(0, 5, len(times))
            for onset, amplitude, freq in ((p, 250 if cmp == "Z" else 60, 5),
                                          (s, 70 if cmp == "Z" else 300, 3)):
                t = times - onset
                values += np.where(t >= 0, amplitude * np.sin(2 * np.pi * freq * t) * np.exp(-np.maximum(t, 0) / 3), 0)
            header = dict(network="XX", station=code, location="", channel=f"HH{cmp}",
                          sampling_rate=100.0, starttime=origin - 30)
            tr = Trace(values.astype(np.float32), header)
            # A real missing interval, stored as two segments, never filled with zeros.
            if n == 3 and cmp == "Z":
                stream += tr.slice(endtime=origin + 25)
                stream += tr.slice(starttime=origin + 30)
            else:
                stream += tr
            channels.append(Channel(code=f"HH{cmp}", location_code="", latitude=lat, longitude=lon,
                                    elevation=100, depth=0, azimuth=90 if cmp == "E" else 0,
                                    dip=-90 if cmp == "Z" else 0, sample_rate=100,
                                    start_date=origin - 86400,
                                    response=Response(instrument_sensitivity=InstrumentSensitivity(1, 1, "M/S", "COUNTS"))))
        stations.append(Station(code=code, latitude=lat, longitude=lon, elevation=100,
                                site=Site(name="Synthetic station"), channels=channels, start_date=origin - 86400))
    inv = Inventory([Network(code="XX", stations=stations, start_date=origin - 86400)], source="SGTL synthetic rehearsal")
    _write_session(stream, inv, out=out, origin=origin, lat=36.5, lon=128.1, depth=12.0,
                   label="SYNTHETIC REHEARSAL — not a Korean earthquake", sources=[dict(kind="synthetic", seed=207)])
    return 0


def _session(folder):
    folder = Path(folder).expanduser().resolve()
    meta = json.loads((folder / "session.json").read_text(encoding="utf-8"))
    if meta.get("schema") != 1:
        raise ValueError("Unsupported session schema; prepare a new session.")
    for name, sha in meta["files"].items():
        if Path(name).name != name or _sha(folder / name) != sha:
            raise ValueError(f"Prepared session file changed: {name}. Keep originals; prepare a new session.")
    return folder, meta


def _map_geometry(folder):
    """Small attributed vector coastline, no tile service or internet dependency."""
    source = _paths.course_path("docs", "resources", "seiscomp", "korea_coast.bna")
    if not source.is_file():
        raise FileNotFoundError("Missing course coastline resource; update the tutorial checkout.")
    vector = folder / ".seiscomp" / "spatial" / "vector"
    vector.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, vector / source.name)
    (vector / "map.cfg").write_text('visible = true\npen.color = 80, 100, 115\npen.width = 1\ndrawName = false\n', encoding="utf-8")


def launch(folder, *, app="waveforms", apply=False):
    folder, meta = _session(folder)
    name = {"waveforms": "scrttv", "event": "scolv"}[app]
    argv = [str(installation() / "bin" / name), "--offline", "--config-file", str(folder / f"{name}.cfg"),
            "-I", "file://" + str(folder / "waveforms.mseed")]
    if app == "waveforms":
        from obspy import UTCDateTime
        end = max(UTCDateTime(r["end"]) for r in meta["records"])
        end = UTCDateTime(math.ceil(end.timestamp))  # include the final fractional second
        argv += ["--no-inventory", "--end-time", end.strftime("%Y-%m-%d %H:%M:%S")]
    else:
        argv += ["--inventory-db", str(folder / "inventory.xml"), "-i", str(folder / "event.xml")]
    print(shlex.join(argv))
    print("Offline session; the command returns when you close the window.")
    if not apply:
        print("Dry run: no GUI started. Repeat with --apply from an X11-enabled terminal.")
        return 0
    if not os.environ.get("DISPLAY"):
        raise RuntimeError("No DISPLAY. Follow docs/seiscomp_gui.md: connect with X11 forwarding, then retry in that terminal.")
    _runtime_dirs(folder)
    return subprocess.run(argv, env=_environment(folder), cwd=folder).returncode


def _xml(path):
    path = Path(path)
    if path.stat().st_size > 20_000_000:
        raise ValueError("Reviewed XML exceeds 20 MB; export this one event only.")
    raw = path.read_bytes()
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("DTD/entities are not supported in reviewed XML.")
    root = ET.fromstring(raw)
    namespace = root.tag.partition("}")[0].lstrip("{")
    if (root.tag.rsplit("}", 1)[-1] != "seiscomp" or namespace not in
        {f"http://geofon.gfz-potsdam.de/ns/seiscomp3-schema/0.{v}" for v in range(10, 14)} |
        {"http://geofon.gfz.de/ns/seiscomp-schema/0.14"}):
        raise ValueError("Expected SeisComP XML (SCML), not QuakeML or StationXML.")
    # Work with local names after verifying the document namespace.
    for node in root.iter():
        node.tag = node.tag.rsplit("}", 1)[-1]
    ep = root.find("EventParameters")
    if ep is None:
        raise ValueError("SCML has no EventParameters.")
    return ep


def import_picks(folder, *, xml, out, origin_id=None, apply=False):
    """Import only explicitly associated manual P/S picks, with no guessed values."""
    from obspy import UTCDateTime
    folder, meta = _session(folder)
    ep = _xml(xml)
    origins = ep.findall("origin")
    for org in origins:
        print(f"Origin {org.get('publicID')}: {len(org.findall('arrival'))} associated picks; "
              f"time {org.findtext('time/value')}")
    if origin_id is None and len(origins) != 1:
        raise ValueError("Choose the reviewed origin above with --origin-id; the importer never guesses between revisions.")
    chosen = [o for o in origins if origin_id is None or o.get("publicID") == origin_id]
    if len(chosen) != 1:
        raise ValueError("--origin-id must identify exactly one origin in your saved XML.")
    origin = chosen[0]
    pick_nodes = ep.findall("pick")
    picks = {p.get("publicID"): p for p in pick_nodes}
    if None in picks or len(picks) != len(pick_nodes):
        raise ValueError("Duplicate or missing pick publicID in saved XML.")
    rows, audit, seen = [], [], set()
    for arr in origin.findall("arrival"):
        pid, phase = arr.findtext("pickID"), arr.findtext("phase")
        if arr.findtext("timeUsed") == "false" or arr.findtext("weight") is not None and float(arr.findtext("weight")) == 0:
            print(f"Skip disabled arrival {pid}.")
            continue
        if phase not in ("P", "S"):
            raise ValueError(f"{pid}: expected P or S, got {phase!r}; review phase names.")
        p = picks.get(pid)
        if p is None:
            raise ValueError(f"Missing pick object {pid}; Apply all, Commit, then File → Save XML.")
        if p.findtext("evaluationMode") != "manual":
            raise ValueError(f"{pid}: only explicitly manual picks can be your M20 reference.")
        wid = p.find("waveformID")
        if wid is None:
            raise ValueError(f"{pid}: no waveformID.")
        net, sta, loc, cha = (wid.get(k, "") for k in ("networkCode", "stationCode", "locationCode", "channelCode"))
        sid, station = f"{net}.{sta}.{loc}.{cha}", f"{net}.{sta}"
        hint = (p.findtext("phaseHint/code") or p.findtext("phaseHint") or "").strip()
        if hint and hint != phase:
            raise ValueError(f"{pid}: phase hint and arrival phase disagree.")
        if len(cha) != 3 or (phase == "P" and cha[-1] != "Z") or (phase == "S" and cha[-1] not in "NE"):
            raise ValueError(f"{pid}: pick P on original Z and S on original N/E; rotated R/T picks need re-review.")
        time_text = p.findtext("time/value", "")
        if not re.search(r"(?:Z|\+00:00)$", time_text):
            raise ValueError(f"{pid}: pick time must explicitly be UTC.")
        time = UTCDateTime(time_text)
        records = [r for r in meta["records"] if r["id"] == sid and UTCDateTime(r["start"]) <= time <= UTCDateTime(r["end"])]
        if len(records) != 1 or time <= UTCDateTime(meta["origin_utc"]):
            raise ValueError(f"{pid}: pick is outside a single recorded segment or not after the context origin.")
        # A displayed time interval is a measurement, not a confidence level.
        u = p.findtext("time/uncertainty")
        lower, upper = p.findtext("time/lowerUncertainty"), p.findtext("time/upperUncertainty")
        if lower is not None and upper is not None:
            bounds = (float(lower), float(upper))
            if any(not math.isfinite(b) or b < 0 for b in bounds):
                raise ValueError(f"{pid}: invalid asymmetric uncertainty bounds.")
            uncertainty = max(bounds)
        elif u is not None:
            uncertainty = float(u)
        else:
            raise ValueError(f"{pid}: missing uncertainty; set it in the picker and save again.")
        lo, hi = (.005, .5) if phase == "P" else (.01, 1.0)
        if not math.isfinite(uncertainty) or not lo <= uncertainty <= hi:
            raise ValueError(f"{pid}: {phase} uncertainty must be {lo}–{hi} s for M20.")
        polarity = {None: "?", "undecidable": "?", "positive": "U", "negative": "D"}.get(p.findtext("polarity"))
        if polarity is None:
            raise ValueError(f"{pid}: unsupported polarity.")
        if phase == "S":
            polarity = "?"
        if (station, phase) in seen:
            raise ValueError(f"More than one {phase} at {station}; choose one channel/revision before export.")
        seen.add((station, phase))
        rows.append(dict(station=station, phase=phase, channel=cha, time_utc=str(time),
                         uncertainty_s=uncertainty, polarity=polarity))
        audit.append(dict(pick_id=pid, stream_id=sid, lower_uncertainty_s=lower, upper_uncertainty_s=upper))
    if not rows:
        raise ValueError("No associated manual picks. In the picker: Apply all (F5); in Location: Commit; then File → Save XML.")
    by_station = {}
    for row in rows:
        by_station.setdefault(row["station"], {})[row["phase"]] = UTCDateTime(row["time_utc"])
    for station, phases in by_station.items():
        if "P" in phases and "S" in phases and phases["S"] <= phases["P"]:
            raise ValueError(f"{station}: S must follow P.")
    rows.sort(key=lambda r: (r["station"], r["phase"]))
    out = Path(out).expanduser()
    receipt = out.with_suffix(out.suffix + ".seiscomp.json")
    if out.exists() or receipt.exists():
        raise ValueError(f"Output exists: {out} or its receipt; choose a new --out and review before replacing your M20 CSV.")
    print(f"Validated {len(rows)} manual picks at {len(by_station)} stations; output {out}.")
    print("M20-T5 still checks station coverage and scientific quality; an imported file is not a task pass.")
    if not apply:
        print("Dry run: nothing written. Repeat with --apply.")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    receipt.write_text(json.dumps(dict(schema=1, source_xml_sha256=_sha(xml), session_sha256=_sha(folder / "session.json"),
                                       origin_id=origin.get("publicID"), uncertainty_rule="max(lower, upper), or symmetric",
                                       picks=audit, csv_sha256=_sha(out)), indent=2) + "\n", encoding="utf-8")
    print(f"Saved {out} and {receipt}; keep your reviewed XML too.")
    return 0
