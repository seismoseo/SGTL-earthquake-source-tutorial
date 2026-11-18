# KMA earthquake catalog (`kma_catalog.csv`)

The Korea Meteorological Administration (KMA, 기상청) domestic earthquake list, with origin times
converted to UTC. It holds 16,084 events from 1978-08-29T17:29:43Z to 2026-11-06T13:07:46Z.
Use it through `st.data.kma_catalog()`, which also adds a KST column and the attribution text.

Source and license: see `ATTRIBUTION.txt`. The list is used under the Korea Open Government License
(KOGL, 공공누리) Type 1, which requires attribution. We changed only the time format and the columns.

## Columns

| column | meaning | units and format |
|---|---|---|
| `event_id` | KMA event number (10 digits) | text; keep it as text, not a number |
| `origin_utc` | origin time: when the earthquake started | ISO 8601 in UTC, for example `2016-09-12T11:32:54Z` |
| `latitude` | epicenter latitude | decimal degrees north |
| `longitude` | epicenter longitude | decimal degrees east |
| `depth_km` | hypocenter depth as reported by KMA | kilometers; empty when KMA gives no depth |
| `ml` | local magnitude (ML) as reported by KMA | one decimal place |

The *epicenter* is the point on the surface above the place where the rupture started (the
*hypocenter*). Rows are sorted by `origin_utc`; every `event_id` appears once.
The first four digits of `event_id` are a label, not a date: in 778 rows
they differ from the UTC year. Use `origin_utc` for time.

## Time rule: UTC in the file, KST = UTC + 9 h

- Every time in this file is UTC (Coordinated Universal Time); the `Z` at the end means UTC.
- KMA announces times in Korea Standard Time (KST). KST = UTC + 9 hours, always.
- Convert with a fixed +09:00 offset. Do not use the `Asia/Seoul` time zone from a time-zone
  database: for some old events it gives a clock reading one hour off (module M01 asks you to find
  which events and why).
- Seismograms (waveform data) are stamped in UTC, so compare them with `origin_utc` directly.

## Precision limits

- Magnitudes come in steps of 0.1 (one decimal place); ML ranges from 0.0 to 5.8.
- Depths are whole kilometers (written like `12.0`). Depth is empty for every event before
  2009 and for some events up to 2015
  (1,738 empty depths in all); from 2016 on every event has a depth.
- Epicenters are given to 0.1 degree (about 11 km) before 2005 and to 0.01 degree
  (about 1 km) from 2005 on. A later value written with one decimal, such as `36.5`,
  means 36.50 with the trailing zero dropped.
- These are rounding steps, not error bars. The real location error is usually larger.

## Magnitudes near ML 2.0

Before you fit a magnitude-frequency relation to this list, count the events in the 0.1 bins on both sides of
ML 2.0, year by year, and compare the counts with what the Gutenberg-Richter law predicts. Module M04 asks you
to measure what you find there and to say what it means for b-values.

## Network-growth epochs

What the list contains depends on how many seismic stations were running. Three epochs show up in
the file itself (counts below come from this file; the first and last years are partial):

| epoch | events | median events per full year | smallest ML | events below ML 2.0 | events with a depth |
|---|---|---|---|---|---|
| 1978-2007 | 748 | 21 | 1.7 | 1 % | 0 % |
| 2008-2015 | 2,830 | 318 | 0.0 | 84 % | 65 % |
| 2016-2026 | 12,506 | 854 | 0.0 | 90 % | 100 % |

- 1978-2007: almost all listed events have ML 2.0 or more; no depths.
- 2008-2015: many events below ML 2.0 are listed from 2008 on; depths appear in
  2009 and are given for almost every event from 2012 on.
- 2016-2026: starts with the 2016 Gyeongju sequence (the 2016 total is far above the median);
  every event has a depth. Of the 404 KS stations in `data/stations/stations.csv`,
  366 have a start date in 2016 or later (a start date can be the start
  of the current installation, so that list does not show the full history).

A denser network detects smaller earthquakes, so the smallest complete magnitude changes with time.
Compare event rates only within one epoch, or above a magnitude that is complete in all epochs you use.

Prepared for the SGTL earthquake source tutorial by Minseong Seo (SGTL, Seoul National University).
