# 07:45 decision record — 17 June 2026

## Final route verdicts

| Route | Verdict | Note |
|---|---|---|
| 9 — Ghodbunder Rd → Hiranandani | HOLD | `TRIP_013`: A = 0.7 min; fresh `P-0003264`. |
| 11 — Borivali Stn → BKC G-Block | CALL_DRIVER | `TRIP_014`: fresh `P-0003518`; only 15 m net displacement across the last 10 minutes; 8 bookings. |
| 12 — Mulund Check Naka → Chakala | PUSH_LATE 10 | `TRIP_015`: A = 10.2 min; fresh `P-0003624`; 9 bookings. |
| 14 — Kandivali E → Kamala Mills | NO_VERDICT | `TRIP_016`: latest received `P-0003828` is 48.0 minutes old. |
| 17 — Vashi Sector 17 → Worli Naka | NO_VERDICT | `TRIP_017`: latest received `P-0004087` is 17.3 minutes old. **This is the least certain call.** |
| 21 — Ghatkopar Metro → BKC | HOLD | `TRIP_018`: A = -0.1 min, `P-0004162`; `TRIP_019`: A = 1.1 min, `P-0004323`. |

## Worry-order

1. Route 11 — Borivali Stn → BKC G-Block — CALL_DRIVER; 8 bookings.
2. Route 17 — Vashi Sector 17 → Worli Naka — NO_VERDICT; 16 bookings; 17.3-minute silence.
3. Route 14 — Kandivali E → Kamala Mills — NO_VERDICT; 12 bookings; 48.0-minute silence.
4. Route 12 — Mulund Check Naka → Chakala — PUSH_LATE 10; 9 bookings.
5. Route 9 — Ghodbunder Rd → Hiranandani — HOLD; 12 bookings.
6. Route 21 — Ghatkopar Metro → BKC — HOLD; 12 bookings across two trips.

## 1. `received_at` is the as-of clock

### The rule

At an as-of time `t`, use only pings where `received_at <= t`. Ignore pings whose `recorded_at` cannot be parsed. Deduplicate on `(vehicle_id, recorded_at)`, then reject coordinate jumps whose implied speed from the preceding ping exceeds 130 km/h.

### The case it breaks on

`V-04` has `P-0003829` recorded at 06:57:13 but received at 08:27:13, and 145 such 90-minute-lag pings through `P-0003973`. This rule discards a spatially coherent device-time trace at 07:45. I keep the rule because the 07:45 live system did not possess those rows yet; using them would use future information.

### The cost and who eats it

Route 14's 12 bookings receive `NO_VERDICT` rather than a confident number. Priya absorbs the operational uncertainty; riders are not sent a number built from unseen telemetry. Healthy 15–16 June received-ping gaps max out at 38 seconds, so a 48.0-minute silence is not ordinary ingest timing.

### What would flip it

An audited source field proving the device-time rows were visible to the live operations screen by 07:45 would justify a different as-of clock. A new ingest watermark or event-time availability field would supersede `received_at`.

## 2. A is the lateness definition

### The rule

For the latest usable received ping, project it onto the route's ordered-stop polyline to obtain fraction `f`. Calculate `A = as_of - (scheduled_start + f × scheduled_runtime)`. Positive A is delay in minutes. Do not calculate A without a fresh usable ping.

### The case it breaks on

`TRIP_014` at `P-0003518` returns A = 58.95 minutes because the vehicle remains at the origin while the timetable is mid-trip. Someone could argue the GPS is wrong. I keep A because the route-11 trace is fresh, stays within 100m of Borivali for 177 pings, and has repeated <100m net-displacement windows.

### The cost and who eats it

The known healthy backtest noise for A is at most 2.33 minutes (median 0.18 minutes). Priya risks action on an imperfect polyline projection, but avoids presenting normal ~2-minute variation as rider delay. The rider-facing consequence applies only when A crosses the separate 5-minute push threshold.

C is rejected because its healthy-trip median is -15.75 minutes and it becomes undefined near the end when no booked stop remains ahead. D is rejected because its healthy-trip p95 is 20.30 minutes and it returns 1,549 minutes for `TRIP_014` at 0.7 km/h. B is rejected because it is nearly identical to A where history exists but unavailable for Route 12. The 12 `promised_eta` schedule-consistency mismatches are all on `TRIP_017` and `TRIP_018`, reinforcing that booking promises are not a stable primary route-level clock.

### What would flip it

Map-matched road geometry, validated stop-arrival events, or a stable historical test showing A regularly exceeds 5 minutes on observed on-time trips would replace A.

## 3. Freshness gate and startup grace

### The rule

Use a 3-minute freshness gate. If the latest usable received ping is older than 3 minutes, return `NO_VERDICT`. If no ping exists during the first 3 minutes after scheduled start, return `HOLD — just started, no ping yet`; after that, return `NO_VERDICT`.

### The case it breaks on

`TRIP_017` / `P-0004087` was at 70.6% polyline progress at 07:27:40, but its 17.3-minute silence makes A at 07:45 appear +9.10 minutes. I reject that stale extrapolation. The startup grace breaks the literal no-ping rule at the exact start of every historical trip; without it, all 12 15–16 June trips produced spurious `NO_VERDICT` rows.

### The cost and who eats it

Route 17's 16 bookings get no late-number notification even though its last observed position was ahead of schedule; that is the least certain call. Priya absorbs the monitoring burden. The gate is conservative relative to the 38-second healthy maximum received gap. With the grace included, the 15–16 June five-minute backtest has zero non-HOLD verdicts.

### What would flip it

A proven normal received-ping gap above 3 minutes would raise the gate just above that measured maximum. A new received ping for Routes 14 or 17 would permit a fresh A calculation.

## 4. Route 11 is CALL_DRIVER

### The rule

Return `CALL_DRIVER` when the latest ping is fresh, the trip is more than 10 minutes past scheduled start, and at least two received pings spanning at least 9 of the previous 10 minutes show <100m net displacement.

### The case it breaks on

`TRIP_014` could be a vehicle parked with noisy GPS rather than a service problem. I keep `CALL_DRIVER` because `P-0003342` through `P-0003518` remain at Borivali Stn; the 10-minute windows move only 10.2–27.3m, and none of the healthy 15–16 June five-minute backtest trips triggers this tier.

### The cost and who eats it

Priya spends a potentially needless driver call and burns some depot goodwill for 8 bookings. The opposing cost is riders left at stops for a bus that has not moved. At 07:45, 4 of the 8 promised ETAs had already passed: `BKG_0148`, `BKG_0149`, `BKG_0151`, and `BKG_0152`. The 38-second healthy gap means this is not caused by a normal telemetry gap.

### What would flip it

A fresh ping showing >100m net movement over the qualifying window, a dispatch event proving a vehicle swap, or an operator-confirmed depot/maintenance state would remove the call-driver condition.

## 5. Route 12 is PUSH_LATE 10; rev. C is rejected in the real view

### The rule

For a fresh, non-destination, non-call-driver trip, return `PUSH_LATE round(A)` when A is at least 5 minutes; otherwise HOLD. Route 12 uses the same rule as every other route. The real view does not force Route 12 to zero.

### The case it breaks on

`TRIP_015` / `P-0003624` yields A = 10.2 minutes. The first observed Route-12 origin ping is `P-0003534` at 07:15. Measured stop-time offsets from each trip's scheduled start show a persistent shift: Mulund +10:00 versus both 15 and 16 June; Nahur +9:58 / +9:54; Bhandup +9:05 / +9:33; Vikhroli +8:40 / +9:19; Kanjurmarg +8:54 / +9:11; and Powai Jn +8:11 / +8:51. The observed stop-timing shift is real whether the original cause was later departure or reporting beginning late: the first observed 17-June Route-12 ping is still at Mulund at 07:15, and the vehicle does not first appear near Powai Jn until 07:55:51. I keep the push because the selected position ping is fresh (0.1 minutes old), A is well beyond the 2.33-minute healthy A maximum, and a forced zero would suppress the measured rider-facing discrepancy. The 5-minute push threshold is about twice the 2.33-minute healthy maximum, so it does not fire on observed noise; a false push burns rider trust.

### The cost and who eats it

9 bookings receive a 10-minute late message that could be wrong if reporting began late. Priya owns that communication risk. Forcing Route 12 to HOLD/zero shifts the risk to those 9 booked riders, who would receive no warning. This follows the handoff's discretionary wording, “Apply them as you see fit,” and Priya's instruction that “a wrong number is worse than no number.” The adjacent rev. C view makes that suppression visible rather than hiding it.

### What would flip it

A reliable dispatch departure record, or a validated case of the same stop-timing shift on a bus independently known to have run on time, would change this output. A validated healthy backtest A error above 5 minutes would also change the threshold.

## 6. Operator 7 stays in the real view

### The rule

Keep every operator in the real decision table. The rev. C operator-7 exclusion is shown only in the labelled comparison table.

### The case it breaks on

`V-09` is the only operator-7 vehicle and has only 181 pings / one trip, `TRIP_019`; that small sample could conceal reliability problems. I keep it because its median/p95 lag is 3s/4s, it has zero duplicate rows and zero >3-minute gaps, while the other operators contain the identified duplicate rows and 12 >3-minute gaps.

### The cost and who eats it

Keeping it preserves Route 21's `TRIP_019` and its 6 bookings in the real route assessment. Excluding it would show only `TRIP_018`'s 6 bookings and hide half of Route 21's 17-June booking load. The earlier 12 >3-minute gaps are all between service windows/overnight; the maximum *in-trip* healthy received-ping gap is 38 seconds.

| Vehicle | Gap start | Gap end | Duration |
|---|---|---|---:|
| V-03 | 15 Jun 08:25:49 | 16 Jun 07:21:00 | 82,511s |
| V-03 | 16 Jun 08:25:55 | 17 Jun 07:20:00 | 82,445s |
| V-04 | 15 Jun 08:14:52 | 16 Jun 06:45:00 | 81,008s |
| V-04 | 16 Jun 08:24:49 | 17 Jun 06:40:00 | 80,111s |
| V-05 | 15 Jun 08:24:52 | 16 Jun 06:45:00 | 80,408s |
| V-05 | 16 Jun 08:15:00 | 17 Jun 06:50:00 | 81,300s |
| V-06 | 15 Jun 08:15:00 | 16 Jun 06:41:00 | 80,760s |
| V-06 | 16 Jun 08:15:48 | 17 Jun 06:46:00 | 81,012s |
| V-10 | 15 Jun 08:32:51 | 16 Jun 07:02:00 | 80,949s |
| V-10 | 16 Jun 08:26:55 | 17 Jun 07:15:00 | 82,085s |
| V-11 | 15 Jun 08:13:48 | 16 Jun 06:45:00 | 81,072s |
| V-11 | 16 Jun 08:04:54 | 17 Jun 06:50:00 | 81,906s |

Each interval begins after the prior day's trip telemetry and ends at the next service day's first/early scheduled ping. The endpoint is inside the next trip window, but no part of the multi-hour gap is an in-trip telemetry gap.

### What would flip it

Evidence of onboarding-only telemetry semantics, a material operator-7 clock/gap failure, or a governance instruction that is mandatory rather than discretionary would justify excluding it.

## 7. Routes 14 and 17 are NO_VERDICT

### The rule

Return `NO_VERDICT` when a started trip has no received ping more than 3 minutes after start, or when its latest usable received ping is older than 3 minutes. Do not compute or publish A from stale telemetry.

### The case it breaks on

Route 17 is the hardest case: `P-0004087` is fresh at 07:27:42 and around 8 minutes ahead under A at that moment, but then stops. The rule withholds an encouraging number at 07:45. I keep it because its 17.3-minute silence is far above the 38-second healthy maximum and stale A would be an assumption that no movement occurred.

### The cost and who eats it

Route 14's 12 bookings and Route 17's 16 bookings receive no late-number verdict. Priya bears the operational follow-up burden. V-04's delayed device-time rows show it at 85.6% along the polyline at 07:44:46, versus 86.4% expected under the schedule: NO_VERDICT therefore hid a bus that looks healthy in data unavailable at 07:45. It is still the right call because that apparent health was not in the live system; publishing it would use future information. Route 17 is explicitly the least certain call because its last observed position was plausible and ahead, unlike Route 14's long ingest-lag problem.

### What would flip it

Any received ping at or before 07:45 that is within the 3-minute gate would restore a calculable A. A validated alternative state source (driver app, dispatch, or vehicle ignition) would also resolve the uncertainty.

## 8. Worry-order is tier, bookings, then silence

### The rule

Sort one-row-per-route verdicts by tier: `CALL_DRIVER`, `NO_VERDICT`, `PUSH_LATE`, `HOLD`. Within each tier sort descending total bookings across the route's represented trips, then descending longest received-ping silence.

### The case it breaks on

Route 14 has a 48.0-minute silence, longer than Route 17's 17.3 minutes, but Route 17 ranks first within `NO_VERDICT` because it has 16 bookings versus 12. Someone could reasonably prioritize the longer technical outage. I keep this order because the explicit rule prioritizes bookings before telemetry duration.

### The cost and who eats it

Priya sees Route 17 before Route 14 within the same uncertainty tier, despite Route 14's longer silence. The cost is delayed attention to the 12 Route-14 bookings; the benefit is that the 16 Route-17 bookings are considered first. Route 12 ranks below both NO_VERDICT routes because its push can go out without anyone chasing, whereas blind routes and the parked bus need a person. Counts are raw bookings, not distinct riders, because one booking is one affected seat/ride commitment.

### What would flip it

Priya changing the stated tie-breaker to silence-first, a new route-level impact measure, or a higher-severity tier for an ingest incident would change the order.

## Measured vs guessed

Measured values include ping timestamps, 90-minute V-04 lag, route positions, booking counts, the 38-second healthy received-gap maximum, the 2.33-minute healthy A maximum, and the zero non-HOLD historical verdicts after startup grace.

Guesses are operational interpretations: that calling V-06's driver can resolve the issue, that a rider push changes rider behaviour, and that the lack of Route-12 pre-07:15 telemetry reflects departure/reporting uncertainty rather than a known cause. They are called out above rather than treated as measured facts.

## Data hygiene

Ignore `P-0001797` because its `recorded_at` is unparseable (`06:60:23`). Deduplicate on `(vehicle_id, recorded_at)`, never on `ping_id` alone: `P-0002821` is reused by V-05 and V-11. Remove the V-11 coordinate-speed glitches `P-0003148` through `P-0003150` before selecting a latest ping; their coordinates create implied speeds far above 130 km/h.
