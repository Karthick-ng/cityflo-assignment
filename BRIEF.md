# Cityflo — Data Engineer take-home

You're standing in for the person who answers one question every single morning, before the 07:45 ops
standup: **for each route, is the bus late right now, by how much, and what do we DO about it** — push a
"your bus is running late" notification to the riders, hold a downstream connection, or call the driver.

Read `HANDOFF.md` first — it's the actual ask, from Priya, the ops lead, in her words, plus the two
standing reconciliation rules the analytics team applies to every extract. You have three mornings of
GPS telemetry and the trips/bookings/route reference tables behind it. You'll build a small runnable
slice your agent can drive, and you'll hand back **the decision, not just the tool.**

The as-of moment is fixed: **07:45 IST on the live morning (2026-06-17).** Monday and Tuesday are there
as history; Wednesday is "this morning," and Priya needs the verdicts before the 07:45 standup.

**Timebox: 8–12 focused hours.** Use whatever AI tooling you normally use — that's the point, and it's
the subject of the exercise; see below. Going well past the box is a signal we'd rather not see: if
you're over budget, stop and use the decision record to say what you'd do next.

---

## What's in the bundle

Fetchable at **https://careers.cityflo.com/takehomes/data-engineer/** and attached to this assignment.

- `HANDOFF.md` — Priya's ask, in her voice, with the two signed-off reconciliation rules (rev. C).
- `DATA_GUIDE.md` — a neutral, column-level reference for every file. It documents what the fields
  *are*, not what to conclude from them. Treat it as a starting point, not gospel: **the data is the
  source of truth; the notes only describe what someone believed when they pulled the extract.**
- `data/gps_pings.csv` — raw pings: `ping_id, vehicle_id, operator_id, lat, lon, speed_kmph`,
  `recorded_at` (device clock, IST), `received_at` (server ingest clock, IST). This is the bulk of it.
- `data/trips.csv` — scheduled trips: `trip_id, route_id, vehicle_id, service_date, scheduled_start,
  scheduled_end, direction`.
- `data/bookings.csv` — rider bookings: `booking_id, trip_id, rider_id, boarding_stop_id, booked_at,
  promised_eta`.
- `data/routes.csv` — `route_id, route_name, origin_stop, dest_stop, scheduled_runtime_min, stops_count`.
- `data/stops.csv` — `stop_id, stop_name, lat, lon, route_id, seq`. Stops are ordered along each route,
  so distance-along-route is computable.

The dataset is small on purpose — small enough to eyeball a route end to end, large enough to hide
things in. There's no server to stand up: load the CSVs into Postgres, DuckDB, SQLite, or pandas —
whatever you can defend. Identifiers are synthetic; no real rider data.

## What to build

A runnable slice — a script, a few SQL views, a notebook, your call — that ingests the files and, for a
route as-of a timestamp, produces a lateness read with enough context to trust it. **"Late" is not
defined for you.** Against the timetable? Against the typical runtime for that route and time of day?
Against the arrival the rider was promised in-app? Against distance-remaining at current speed? Each is
defensible and each breaks differently. Pick one, and own the consequences of the pick.

A working pipeline that parses the data and survives the obvious junk is **assumed, not scored.** It's
the floor. The marks are in the calls you make on top of it. We are not grading polish, test count,
framework choice, a tidy README, or how many anomalies you can enumerate.

## What to hand back (this is what we grade)

1. **The 07:45 verdict table** — one row per route, as-of 07:45 on the live morning:

   | route | verdict | note |
   |---|---|---|
   | … | one of: `PUSH_LATE <n> min` · `HOLD` · `CALL_DRIVER` · `NO_VERDICT` (+ one-line reason) | … |

   `PUSH_LATE n` means you'd fire "your bus is n minutes late" to that route's riders right now. `HOLD`
   means running fine, do nothing. `CALL_DRIVER` means something's wrong that a push won't fix.
   `NO_VERDICT` is a valid, sometimes correct answer — if you can't trust the number, say so and say why;
   a confident wrong number is worse than an honest blank. Then give a single **ranked worry-order**: if
   Priya can only chase things in order, which route first, and why.

2. **A decision record** — Priya's real deliverable. Your verdict table will get fought over in the
   standup, so for **every consequential call** (each borderline verdict, the worry-order, your
   definition of "late", what you did with anything that looked wrong), give four things:
   - **The rule** — stated so a stranger could re-run it tomorrow and get the same answer.
   - **The case it breaks on** — the specific trip / route / ping (by id) where your own rule returns
     an answer you'd argue against, and why you're keeping the rule anyway.
   - **The cost, and who eats it** — in Priya's terms (a false push burns rider trust; a suppressed one
     strands people at a stop; a needless driver call burns the depot's goodwill). Size it from your
     own numbers where you can.
   - **What would flip it** — the observation that would change the call.

   A balanced memo that lays out options and hands the choice back to Priya scores near zero here. A
   committed, defended, quantified call is the whole assignment.

3. **The raw session transcript** — the real one. Export it, don't summarise or reconstruct it (a
   reconstruction caps your score). Upload it via `get_session_log_upload_url("data-engineer")` with an
   HTTP PUT and pass the returned `session_log_key` to `submit_assignment`.

4. **A steering ledger — `decisions.jsonl`** — one line per consequential decision:

   ```json
   {"decision": "…what you decided…", "quote": "…the exact words you typed to the agent…", "anchor": "turn 14"}
   ```

   The `quote` must be a verbatim message you actually sent; `anchor` must point to where it sits in the
   transcript. We cross-check these against your transcript when grading — unanchored entries are not
   read. Honesty scores well:
   "the agent proposed X, I kept it because Y" is worth more than an inflated claim you overruled it when
   the transcript shows you didn't. No minimum count; one real, load-bearing decision beats ten cosmetic
   ones.

## On AI tools (required, and the actual subject of this exercise)

Use your normal agent, fully. We are not testing whether you can write a lateness query — your model
can, in seconds, and it will do it confidently even when the number is wrong. We are testing the
judgment you add on top: what you told it to do, where you overruled it, the cases it got confidently
wrong, and the calls it could not make for you. This problem is built so that an agent on autopilot
produces a clean, plausible, wrong verdict table. Show us where you caught it.

## What we grade

We grade the decisions and their defense, not the pipeline. There is no checklist to reverse-engineer.

## Submitting, and the live debrief

Put `decisions.jsonl` in your repo alongside your code and decision record, then submit with the
`submit_assignment` MCP tool: your repo/gist URL and your `session_log_key`. **After you submit**, we'll
schedule a **15-minute live round**. In it we'll hand
you a fresh **fourth morning** of the same shape and one new constraint, on the spot — you'll run your
own slice on it in front of us, defend your worry-order, name the call you were least sure of, and say
what would change it. We're not looking for a new build — we're looking at whether your tool and your
reasoning hold up on data you've never seen and couldn't tune against.
