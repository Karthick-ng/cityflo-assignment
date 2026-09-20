# Data guide — Mumbai lateness extract

A neutral, column-level reference. It documents what the fields *are*, not what to conclude from them.
For the ask and the reconciliation rules, see `HANDOFF.md`.

## What this is

A small extract pulled to answer one operational question: at the 07:45 standup, **for each route, is
the bus late right now, by how much, and what do we do?** It covers a handful of Cityflo's Mumbai
commute routes over three consecutive mornings — Monday 2026-06-15 through Wednesday 2026-06-17 — across
the morning peak. The live morning is Wednesday the 17th; the as-of is 07:45 IST.

It is deliberately small — small enough to load into anything and eyeball end to end, large enough to
hide things in. Everything is local CSV; there is no server to stand up and no external API. Load the
files into Postgres, DuckDB, SQLite, or pandas — whatever you can defend.

All timestamps carry the `+05:30` (IST) offset. Identifiers (riders, vehicles) are synthetic — there is
no real personal data here.

A general caveat before you start: GPS is messy, and device clocks are not always what they claim.
Sanity-check the rows before you trust a number that comes out of them.

---

## Files

All files live under `data/`.

### `data/routes.csv`

One row per route.

| column | type | meaning |
|---|---|---|
| `route_id` | int | Stable route identifier. |
| `route_name` | str | Human label, e.g. `Borivali → BKC`. |
| `origin_stop` | str | Name of the first boarding stop (terminus). |
| `dest_stop` | str | Name of the final stop. |
| `scheduled_runtime_min` | int | Planned origin→dest runtime, in minutes, per the published timetable. |
| `stops_count` | int | Number of stops on the route. |

### `data/stops.csv`

One row per stop. Stops are laid out **in order along the route**, so the `seq` column lets you compute
distance-along-route and resolve where a ping sits between two stops.

| column | type | meaning |
|---|---|---|
| `stop_id` | str | Stop identifier, encodes route + sequence (e.g. `S-1103` = route 11, seq 3). |
| `stop_name` | str | Human label. |
| `lat` | float | Latitude (~6 dp). |
| `lon` | float | Longitude (~6 dp). |
| `route_id` | int | Route this stop belongs to. |
| `seq` | int | Order along the route, `1..stops_count`. `seq = 1` is the origin terminus. |

### `data/trips.csv`

One row per scheduled trip — one vehicle running one route on one service date. All trips in this window
are morning `inbound` runs.

| column | type | meaning |
|---|---|---|
| `trip_id` | str | Trip identifier, `TRIP_001..`. |
| `route_id` | int | Route being run. |
| `vehicle_id` | str | Vehicle assigned, `V-01..V-12`. A vehicle does one or two trips a morning. |
| `service_date` | date | `YYYY-MM-DD`. |
| `scheduled_start` | datetime (IST) | Planned departure from origin, per the timetable. |
| `scheduled_end` | datetime (IST) | Planned arrival — `scheduled_start + scheduled_runtime_min`. |
| `direction` | str | `inbound` throughout this extract. |

The vehicle ↔ operator mapping is not a column here — operator is carried on each ping (see below). A
given vehicle is owned by one operator for the whole window.

### `data/bookings.csv`

One row per rider booking against a trip. Roughly 5–20 bookings per trip.

| column | type | meaning |
|---|---|---|
| `booking_id` | str | Booking identifier, `BKG_0001..`. |
| `trip_id` | str | Trip the seat is booked on. |
| `rider_id` | str | Synthetic rider identifier. |
| `boarding_stop_id` | str | Stop the rider boards at — a stop on that trip's route. |
| `booked_at` | datetime (IST) | When the booking was made (hours to days before `scheduled_start`). |
| `promised_eta` | datetime (IST) | The arrival-at-boarding-stop time the rider was shown in the app. |

`promised_eta` is the in-app promise: when the rider was told the bus would reach *their* boarding stop.
It is derived from the schedule and the along-route position of the boarding stop, so it's a legitimate
alternative baseline for "late" if you'd rather measure against what the rider was promised than against
the raw timetable.

### `data/gps_pings.csv`

The raw telemetry — one row per GPS ping. Vehicles emit only during and around their assigned trips, at
a nominal cadence of roughly one ping every 20 seconds while a trip is active.

| column | type | meaning |
|---|---|---|
| `ping_id` | str | Ping identifier, `P-0000001..`. |
| `vehicle_id` | str | Emitting vehicle. |
| `operator_id` | int | Operator that owns the vehicle. |
| `lat` | float | Latitude (~6 dp). |
| `lon` | float | Longitude (~6 dp). |
| `speed_kmph` | float | Instantaneous speed reported by the device. |
| `recorded_at` | datetime (IST) | The **device clock** — when the device says it took the fix. |
| `received_at` | datetime (IST) | The **server ingest clock** — when our ingester first saw the ping. |

There are two timestamps on every ping for a reason. `recorded_at` comes off the device; `received_at`
is stamped by our pipeline when the ping lands. They usually agree to within a few seconds of network
latency. When they don't agree, which one you believe — and for what — is a judgment call.

---

## Routes in this extract

| route | name | origin → dest | scheduled runtime | stops |
|---|---|---|---|---|
| 9 | Thane → Powai | Ghodbunder Rd → Hiranandani | 55 min | 7 |
| 11 | Borivali → BKC | Borivali Stn → BKC G-Block | 70 min | 9 |
| 12 | Mulund → Andheri E | Mulund Check Naka → Chakala | 60 min | 8 |
| 14 | Kandivali → Lower Parel | Kandivali E → Kamala Mills | 75 min | 10 |
| 17 | Vashi → Worli | Vashi Sector 17 → Worli Naka | 65 min | 8 |
| 21 | Ghatkopar → BKC | Ghatkopar Metro → BKC | 40 min | 6 |

---

## Working with it

- Load the CSVs wherever you like — `COPY` into Postgres, `read_csv` into DuckDB, `.import` into SQLite,
  or `pandas.read_csv`. No external API, no credentials, no live service.
- The natural join path: `gps_pings` → `trips` (by vehicle + service date / time window) → `routes` and
  `stops` for reference; `bookings` hang off `trips`.
- To place a ping along its route, project it onto the ordered `stops` geometry for that route (`seq`
  gives you the order) and measure distance-along-route. That, against time, is the raw material for a
  progress-based lateness read.
- Times are tz-aware (`+05:30`). Parse them as such rather than stripping the offset — you'll want
  correct ordering when timestamps from different clocks are in play.

## A note on realism

This is real-shaped, not real. The traces, speeds and timings are synthesized to behave like Mumbai
morning telemetry — congestion in the dense middle of a route, faster running at the edges, the usual
scatter of a consumer GPS chip — but the rider and vehicle identifiers are made up and no production data
is included. It is sized to be inspected by hand: if a number looks wrong, you can go read the rows
behind it.
