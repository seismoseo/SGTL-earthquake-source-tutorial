# Seismic stations (`stations.csv`)

Coordinates and start dates of 465 seismic stations in South Korea: 404 of the KS network
(Korea Meteorological Administration, KMA) and 61 of the KG network (Korea Institute of
Geoscience and Mineral Resources, KIGAM). Start dates run from 1994-12-14 to 2025-12-26.

| column | meaning | units and format |
|---|---|---|
| `network` | network code: `KS` (KMA) or `KG` (KIGAM) | text |
| `station` | station code | text |
| `latitude` | station latitude | decimal degrees north |
| `longitude` | station longitude | decimal degrees east |
| `start_date` | first day of the station in the source list | ISO date `YYYY-MM-DD` |

Source: station information of the Korea Meteorological Administration (KMA, network KS) and the
Korea Institute of Geoscience and Mineral Resources (KIGAM, network KG), as compiled in the public
PocketQuake repository (<https://github.com/seismoseo/PocketQuake>, file
`stations/KP_station_list.csv`). We kept the coordinates as written there and turned the start date
into an ISO date. Rows are sorted by network, then station.

Limits:
- There are no end dates, elevations, sensor types or instrument responses. A start date can be the
  start of the current installation rather than the first one.
- For full station metadata (all epochs, channels and responses) use the integrated KS/KG station
  metadata of Ahn, Kang and Jung (2024; doi:10.14770/jgsk.2024.001), which the tutorial installer
  fetches from its public repository.

Prepared for the SGTL earthquake source tutorial by Minseong Seo (SGTL, Seoul National University).
