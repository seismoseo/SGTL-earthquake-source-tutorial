# Data policy

## What is in this public repository

- **KMA catalog subsets** in `data/catalogs/` (Korea Open Government License Type 1; attribution in
  `LICENSE-CONTENT.md`). Read them with `st.data.kma_catalog()` and `st.data.sequence(name)`.
- **Dataset manifests** in `data/manifests/`: lists of what to fetch (stations, channels, time windows), no data.
- **Velocity models** in `data/velocity_models/`, each with its citation.
- The glossary and the reference list.

It contains **no waveforms, no station response files, no lab results and no credentials**, and it must stay that way.

## What you fetch yourself

- **Waveforms** of the KS and KG networks, with your **own STP account** (from module M03). Your STP settings live in
  your home folder, outside the repository; M03 shows where. The account is personal: never share it or the login.
- **Station metadata** (StationMetadata by Byeong-Seok Ahn), fetched from its public repository by
  `bin/sgtl-install metadata --apply`.
- **Public catalogs and waveforms** (USGS ComCat, ISC, EarthScope) through FDSN web services with ObsPy; no account needed.

Everything you download goes under `~/sgtl/data/` (or the folder in `SGTL_DATA`; `st.data.root()` tells you), never
inside the repository.

## Never

- **Never commit data**: waveforms (`.sac`, `.mseed`, ...), station XML or response files, large tables, downloaded
  PDFs. The pre-commit hook blocks some of these, not all.
- **Never commit or paste credentials**: passwords, tokens, STP settings, your JupyterLab link.
- **Never upload** data you fetched with your account (or figures made from it) to public places or AI tools. Ask your
  mentor before you show KMA or KIGAM data outside the lab.
- **Never copy** lab results or files from other people's folders. Results your mentor shares with you stay in the lab.

## Times: UTC everywhere, KST only at the door

- All times in this tutorial are **UTC** (Coordinated Universal Time). Waveform files are in UTC.
- The KMA catalog and KMA web pages give **KST** (Korea Standard Time) = UTC + 9 hours.
- Convert with a **fixed offset**: UTC = KST - 9 hours. Do **not** use the `Asia/Seoul` time zone for this: for some
  old events it gives a clock reading one hour off (task M01-T5 asks you to find which events and why).
- Keep times time-zone-aware in pandas (UTC) and label axes "(UTC)".
- Watch the date: 05:00 KST on 2 January is 20:00 UTC on 1 January. Selecting a "day" in KST and in UTC gives
  different events.
- Read every new source's documentation to learn which time it uses. If it does not say, ask.

## Citing data

Name your data sources in every report and figure caption: KMA (catalog, KS network), KIGAM (KG network), USGS ComCat,
ISC, and StationMetadata (Ahn, Kang & Jung, 2024). The reference keys are in `references/references.yaml`.
