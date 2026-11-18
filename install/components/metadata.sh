# shellcheck shell=bash
# install/components/metadata.sh: KS/KG station metadata (sourced by bin/sgtl-install).
#
# Downloads StationMetadata 1.0.2 by Byeong-Seok Ahn (Pukyong National University) from his GitHub
# repository at a pinned commit (two zip files; SHA-256 in install/checksums.txt) and fills
# ~/sgtl/data/metadata/ (or $SGTL_DATA/metadata):
#   KS_KG_metadata_1.0.2.xml     all KS and KG stations in one StationXML file (148 MB)
#   KS_KG_metadata_1.0.2.SACPZ   their poles and zeros in SAC format (SACPZ)
#   stationxml/NET.STA.xml       the same StationXML, one file per station (547 files)
#   ACKNOWLEDGMENT.txt           who made the files, how to cite them, where they come from
# The split reads the big file piece by piece (about 200 MB of memory and 15 s, not the 2 GB that
# reading it whole takes) and reads every new file back with ObsPy. Needs the course environment.
# Uses the helpers of bin/sgtl-install (say, step, warn, die, run, action, fetch_verified,
# checksum_entry) and its variables (APPLY, SGTL_HOME).
#
# Copyright (c) 2026 Minseong Seo (SGTL, Seoul National University). MIT License.

META_REPO_URL="https://github.com/ByeongSeokAhn/StationMetadata"
META_COMMIT="483055001ae45b6a5a9546753cd49cb900f498de"
META_VERSION="1.0.2"
META_XML_ZIP="KS_KG_metadata_1.0.2.xml.zip"
META_PZ_ZIP="KS_KG_metadata_1.0.2.SACPZ.zip"
# Network-station pairs in this file: 547 (545 station codes; BRD and CHS are in both KG and KS, at
# different sites). The source's README says 546 stations.
META_STATIONS=547
META_SPLIT_VERSION=1
META_NICE=(env)

component_metadata_summary() {
  printf '%s' 'KS/KG station metadata (StationMetadata 1.0.2 by Byeong-Seok Ahn), one StationXML file per station'
}

metadata_sha() {
  local entry sha
  entry="$(checksum_entry "$1")" || die "install/checksums.txt has no entry for $1."
  read -r sha _ <<<"$entry"
  printf '%s' "$sha"
}

metadata_write_acknowledgment() {
  local f="$1/ACKNOWLEDGMENT.txt" xml_sha pz_sha
  xml_sha="$(metadata_sha "$META_XML_ZIP")"
  pz_sha="$(metadata_sha "$META_PZ_ZIP")"
  action "write $f (credit, citation and source)"
  [[ $APPLY -eq 1 ]] || return 0
  cat >"$f.part" <<EOF
KS/KG station metadata: StationMetadata version $META_VERSION

These files were integrated by Byeong-Seok Ahn (Pukyong National University). They describe the
stations of the regional seismic networks in the southern Korean Peninsula run by the Korea
Meteorological Administration, the Korea Institute of Geoscience and Mineral Resources and the
Korea Institute of Nuclear Safety: where each station is, its instruments and their responses,
and how they changed from the installation of each station to July 2023. The files use the
network codes KS and KG.

Please cite this paper whenever you use the files:
  Ahn, B.-S., Kang, T.-S., & Jung, J.-O. (2024). Station metadata integration of regional seismic
  networks in the southern Korean Peninsula. Journal of the Geological Society of Korea, 60(1),
  111-119. https://doi.org/10.14770/jgsk.2024.001  (in Korean, with an English abstract)

Source: $META_REPO_URL
  commit $META_COMMIT
  $META_XML_ZIP    SHA-256 $xml_sha
  $META_PZ_ZIP  SHA-256 $pz_sha
The repository states no license: do not share copies of these files; point others to the
repository instead. The author asks to be told about errors and updates (see the repository).

What is in this folder:
  KS_KG_metadata_$META_VERSION.xml    all stations in one StationXML file, as published
  KS_KG_metadata_$META_VERSION.SACPZ  poles and zeros of every channel in SAC format, as published
  stationxml/NET.STA.xml       the StationXML file split into one file per station (for example
                               stationxml/KS.ADO2.xml), with the same header and network
                               description; nothing else was changed
The split gives $META_STATIONS network-station pairs (545 station codes: BRD and CHS exist in
both KG and KS, at different sites); the repository's README speaks of 546 stations.

Unpacked and split by bin/sgtl-install (component metadata) of the SGTL earthquake source tutorial,
by Minseong Seo (SGTL, Seoul National University).
EOF
  mv -f -- "$f.part" "$f"
}

component_metadata_run() {
  step "KS/KG station metadata (metadata)"
  local prefix="${SGTL_ENV:-$SGTL_HOME/envs/sgtl}" data meta key stamp n_files v
  prefix="${prefix%/}"
  data="${SGTL_DATA:-$SGTL_HOME/data}"
  data="${data%/}"
  [[ "$prefix" == /* ]] || die "SGTL_ENV must be an absolute path (it is '$prefix')."
  [[ "$data" == /* ]] || die "SGTL_DATA must be an absolute path (it is '$data')."
  meta="$data/metadata"
  stamp="$meta/.sgtl-metadata"
  say "StationMetadata $META_VERSION by Byeong-Seok Ahn ($META_REPO_URL, commit ${META_COMMIT:0:7})"
  say "Folder: $meta"
  if [[ ! -x "$prefix/bin/python" ]]; then
    [[ $APPLY -eq 1 ]] && die "The course environment $prefix is missing (no bin/python). Install it first: bin/sgtl-install env --apply"
    warn "The course environment $prefix is missing (no bin/python): --apply will stop here. Install it first: bin/sgtl-install env --apply"
  fi
  for v in LD_LIBRARY_PATH PYTHONPATH PYTHONHOME; do unset "$v"; done
  export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_MAX_THREADS=1
  export NUMPY_MADVISE_HUGEPAGE=0 PYTHONNOUSERSITE=1
  if have nice; then META_NICE=(nice -n 10); else META_NICE=(env); fi

  key="xml=$(metadata_sha "$META_XML_ZIP") sacpz=$(metadata_sha "$META_PZ_ZIP") stations=$META_STATIONS split=$META_SPLIT_VERSION"
  n_files=0
  if [[ -d "$meta/stationxml" ]]; then
    n_files="$(find "$meta/stationxml" -maxdepth 1 -name '*.xml' -type f | wc -l | tr -d ' ')"
  fi
  if [[ -f "$stamp" && "$(cat "$stamp")" == "$key" && "$n_files" -eq $META_STATIONS && -f "$meta/ACKNOWLEDGMENT.txt" ]]; then
    say "Already installed: $meta ($META_STATIONS station files)."
    return 0
  fi

  fetch_verified "$META_XML_ZIP" "$SGTL_HOME/downloads"
  local xml_zip="$FETCHED"
  fetch_verified "$META_PZ_ZIP" "$SGTL_HOME/downloads"
  local pz_zip="$FETCHED"
  run mkdir -p "$meta"
  run rm -f -- "$stamp"
  action "unpack $xml_zip and $pz_zip into $meta"
  action "split $meta/${META_XML_ZIP%.zip} into $meta/stationxml.part/NET.STA.xml (one file per station; about 15 s)"
  action "read every new file back with ObsPy; expect $META_STATIONS stations"
  if [[ $APPLY -eq 1 ]]; then
    "${META_NICE[@]}" "$prefix/bin/python" -I - "$xml_zip" "$pz_zip" "$meta" "$META_STATIONS" <<'SPLIT_PY' || die "Splitting the station metadata failed (see the messages above). Send them to the mentor (friction issue)."
"""Unpack StationMetadata and split its StationXML file into one file per station.

Arguments: XML_ZIP SACPZ_ZIP METADATA_DIR EXPECTED_STATIONS. The big file is streamed (lxml iterparse):
only the current station is kept as a parsed tree; the others are kept as bytes until written.
"""
import copy
import json
import os
import re
import resource
import shutil
import sys
import time
import zipfile

from lxml import etree

NS = "{http://www.fdsn.org/xml/station/1}"
CODE = re.compile(r"[A-Za-z0-9_-]{1,8}")


def fail(msg):
    sys.exit("ERROR: " + msg)


def unpack(zip_path, meta_dir):
    want = os.path.basename(zip_path)[: -len(".zip")]
    with zipfile.ZipFile(zip_path) as zf:
        names = [i.filename for i in zf.infolist() if not i.is_dir()]
        if names != [want]:
            fail("{} should hold exactly one file, {}; it holds {}".format(zip_path, want, names))
        dest = os.path.join(meta_dir, want)
        with zf.open(want) as src, open(dest + ".part", "wb") as out:
            shutil.copyfileobj(src, out, 1 << 20)  # the zip's own check (CRC) runs at the end
    os.replace(dest + ".part", dest)
    print("  unpacked {} ({:.1f} MB)".format(dest, os.path.getsize(dest) / 1e6), flush=True)
    return dest


def split(xml_path):
    """Return (root tag, attributes, namespaces), header elements, networks, stations by NET.STA."""
    root_info, header, networks, groups, depth = None, [], [], {}, 0
    for event, el in etree.iterparse(xml_path, events=("start", "end"), remove_blank_text=True,
                                     resolve_entities=False, no_network=True):
        if event == "start":
            depth += 1
            if depth == 1:
                root_info = (el.tag, dict(el.attrib), dict(el.nsmap))
            elif depth == 2 and el.tag == NS + "Network":
                networks.append((dict(el.attrib), []))
            continue
        depth -= 1
        if depth == 1 and el.tag != NS + "Network":
            header.append(copy.deepcopy(el))  # Source, Sender, Module, ModuleURI, Created
        elif depth == 2 and el.tag != NS + "Station":
            networks[-1][1].append(copy.deepcopy(el))  # Description, Comment, ... of the network
        elif depth == 2:
            net, sta = networks[-1][0].get("code", ""), el.get("code", "")
            if not (CODE.fullmatch(net) and CODE.fullmatch(sta)):
                fail("unexpected network or station code {!r}.{!r}".format(net, sta))
            nchan = len(el.findall(NS + "Channel"))
            groups.setdefault(net + "." + sta, []).append(
                (len(networks) - 1, etree.tostring(el, with_tail=False), nchan))
            el.clear()
            while el.getprevious() is not None:  # free what is done
                del el.getparent()[0]
    if root_info is None or root_info[0] != NS + "FDSNStationXML":
        fail("{} is not an FDSN StationXML file".format(xml_path))
    return root_info, header, networks, groups


def write(out_dir, root_info, header, networks, groups):
    parser = etree.XMLParser(remove_blank_text=True, resolve_entities=False, no_network=True)
    for key in sorted(groups):
        tag, attrib, nsmap = root_info
        root = etree.Element(tag, attrib=attrib, nsmap=nsmap)
        for h in header:
            root.append(copy.deepcopy(h))
        for idx in sorted({i for i, _, _ in groups[key]}):
            net = etree.SubElement(root, NS + "Network", attrib=networks[idx][0])
            for child in networks[idx][1]:
                net.append(copy.deepcopy(child))
            for i, data, _ in groups[key]:
                if i == idx:
                    net.append(etree.fromstring(data, parser))
        etree.cleanup_namespaces(root)
        etree.ElementTree(root).write(os.path.join(out_dir, key + ".xml"), xml_declaration=True,
                                      encoding="UTF-8", pretty_print=True)


def read_back(out_dir, groups):
    from obspy import read_inventory

    for key in sorted(groups):
        inv = read_inventory(os.path.join(out_dir, key + ".xml"), format="STATIONXML")
        got = [(n.code + "." + s.code, len(s.channels)) for n in inv for s in n]
        want = [(key, n) for _, _, n in groups[key]]
        if got != want:
            fail("{}.xml reads back as {}, not {}".format(key, got, want))


def main():
    xml_zip, pz_zip, meta_dir, expected = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
    t0 = time.time()
    xml_path = unpack(xml_zip, meta_dir)
    unpack(pz_zip, meta_dir)
    root_info, header, networks, groups = split(xml_path)
    out_dir = os.path.join(meta_dir, "stationxml.part")
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir)
    write(out_dir, root_info, header, networks, groups)
    t_split = time.time() - t0
    read_back(out_dir, groups)
    summary = {
        "stations": len(groups),
        "station_codes": len({k.split(".", 1)[1] for k in groups}),
        "channels": sum(n for g in groups.values() for _, _, n in g),
        "split_s": round(t_split, 1),
        "total_s": round(time.time() - t0, 1),
        "peak_memory_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024),
    }
    print("  split: " + json.dumps(summary, sort_keys=True), flush=True)
    if summary["stations"] != expected:
        fail("found {} stations, expected {}".format(summary["stations"], expected))


main()
SPLIT_PY
  fi
  run rm -rf -- "$meta/stationxml"
  run mv -- "$meta/stationxml.part" "$meta/stationxml"
  metadata_write_acknowledgment "$meta"
  action "record the finished installation in $stamp"
  if [[ $APPLY -eq 1 ]]; then printf '%s\n' "$key" >"$stamp"; fi
  say ""
  say "Station files: $meta/stationxml/NET.STA.xml   (for example: obspy.read_inventory(\"$meta/stationxml/KS.ADO2.xml\"))"
  say "Please read and follow $meta/ACKNOWLEDGMENT.txt: cite Ahn, Kang & Jung (2024) when you use these files."
}
