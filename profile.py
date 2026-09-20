"""Descriptive profile for the Cityflo take-home CSV bundle.

Run (after installing uv):
    uv run --with pandas profile.py

This script deliberately does not calculate lateness, exclude any route/operator,
or alter the input data.  It writes no files and prints compact profile tables.
"""
from __future__ import annotations

from pathlib import Path
import re
import sys
from typing import Iterable

import numpy as np
import pandas as pd

# Windows PowerShell may default to cp1252, while route labels contain a Unicode arrow.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
IST = "Asia/Kolkata"
AS_OF = pd.Timestamp("2026-06-17 07:45:00", tz=IST)
EXAMPLE_N = 5

# Deliberately explicit, conservative profiling thresholds (not operational rules).
MUMBAI_LAT = (18.8, 19.6)
MUMBAI_LON = (72.7, 73.3)
REPORTED_SPEED_MAX = 120.0
IMPLIED_SPEED_MAX = 130.0
FAR_FROM_ROUTE_M = 300.0
NEAR_STOP_M = 100.0
STATIONARY_SPEED = 1.0
STATIONARY_MOVE_M = 25.0
STATIONARY_MINUTES = 5.0


def heading(text: str) -> None:
    print("\n" + "=" * 100 + "\n" + text + "\n" + "=" * 100)


def show(df: pd.DataFrame | pd.Series, title: str, n: int = 20) -> None:
    print(f"\n{title}")
    if isinstance(df, pd.Series):
        df = df.to_frame()
    if len(df) == 0:
        print("  None")
    else:
        print(df.head(n).to_string(index=False))
        if len(df) > n:
            print(f"  ... {len(df) - n:,} more rows suppressed")


def ids(values: Iterable, n: int = EXAMPLE_N) -> str:
    vals = pd.Series(list(values)).dropna().astype(str).drop_duplicates().head(n).tolist()
    return ", ".join(vals) if vals else "None"


def issue(label: str, mask: pd.Series, example_values: Iterable) -> None:
    print(f"- {label}: {int(mask.sum()):,}; examples: {ids(example_values)}")


def parse_ist(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Parse offset-bearing input timestamps explicitly and normalize them to IST."""
    for col in columns:
        frame[col] = pd.to_datetime(
            frame[col], format="%Y-%m-%d %H:%M:%S%z", errors="coerce", utc=True
        ).dt.tz_convert(IST)
    return frame


def haversine_m(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 6_371_000 * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))


def point_segment_distance_m(lat, lon, a_lat, a_lon, b_lat, b_lon) -> float:
    """Local equirectangular point-to-segment distance; appropriate for this small area."""
    scale_y = 111_320.0
    scale_x = scale_y * np.cos(np.radians((a_lat + b_lat + lat) / 3))
    px, py = (lon - a_lon) * scale_x, (lat - a_lat) * scale_y
    bx, by = (b_lon - a_lon) * scale_x, (b_lat - a_lat) * scale_y
    denom = bx * bx + by * by
    t = 0.0 if denom == 0 else min(1.0, max(0.0, (px * bx + py * by) / denom))
    return float(np.hypot(px - t * bx, py - t * by))


def polyline_distance_m(lat: float, lon: float, stops: pd.DataFrame) -> float:
    pts = stops.sort_values("seq")
    if len(pts) == 1:
        return float(haversine_m(lat, lon, pts.iloc[0].lat, pts.iloc[0].lon))
    return min(
        point_segment_distance_m(lat, lon, a.lat, a.lon, b.lat, b.lon)
        for a, b in zip(pts.iloc[:-1].itertuples(), pts.iloc[1:].itertuples())
    )


def timestamp_profile(name: str, raw: pd.DataFrame, parsed: pd.DataFrame, cols: list[str]) -> None:
    print(f"\n{name}")
    for col in cols:
        rawvals = raw[col].dropna().astype(str)
        offsets = rawvals.str.extract(r"([+-]\d\d:\d\d)$", expand=False)
        formats = rawvals.str.replace(r"\d", "D", regex=True).value_counts().to_dict()
        parsedvals = parsed[col].dropna()
        print(
            f"  {col}: {parsedvals.min()} to {parsedvals.max()}; "
            f"raw format(s) {formats}; offsets {offsets.value_counts().to_dict()}; "
            f"parse failures {int(parsed[col].isna().sum()):,}"
        )


def quantiles(s: pd.Series) -> dict:
    s = s.dropna()
    return {
        "n": len(s), "min": s.min(), "median": s.median(),
        "p95": s.quantile(.95), "p99": s.quantile(.99), "max": s.max(),
    }


def lag_table(g: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    return (g.groupby(by, dropna=False)["lag_s"].agg(
        n="count", min_s="min", median_s="median",
        p95_s=lambda x: x.quantile(.95), p99_s=lambda x: x.quantile(.99), max_s="max"
    ).reset_index().round(1))


def nearest_stop_kind(lat: float, lon: float, route_id: int, stops: pd.DataFrame) -> str:
    ss = stops[stops.route_id == route_id].sort_values("seq")
    if ss.empty:
        return "unassigned route"
    d = haversine_m(lat, lon, ss.lat.to_numpy(), ss.lon.to_numpy())
    i, nearest = int(np.argmin(d)), float(np.min(d))
    if nearest > NEAR_STOP_M:
        return "mid-route"
    if i in (0, len(ss) - 1):
        return "terminus"
    return "stop"


def main() -> None:
    raw = {name: pd.read_csv(DATA / f"{name}.csv", dtype=str) for name in
           ["routes", "stops", "trips", "bookings", "gps_pings"]}
    routes = pd.read_csv(DATA / "routes.csv")
    stops = pd.read_csv(DATA / "stops.csv")
    trips = pd.read_csv(DATA / "trips.csv")
    bookings = pd.read_csv(DATA / "bookings.csv")
    pings = pd.read_csv(DATA / "gps_pings.csv")
    parse_ist(trips, ["scheduled_start", "scheduled_end"])
    parse_ist(bookings, ["booked_at", "promised_eta"])
    parse_ist(pings, ["recorded_at", "received_at"])

    heading("ASSUMPTIONS AND SCOPE")
    print("1. Every offset-bearing timestamp is parsed with %Y-%m-%d %H:%M:%S%z and normalized to Asia/Kolkata.")
    print("2. 'Mumbai bounds' means latitude 18.8 to 19.6 and longitude 72.7 to 73.3; it is a coarse data-quality screen.")
    print("3. Reported speed >120 km/h or <0, and coordinate-implied speed >130 km/h, are flagged as implausible, not proved wrong.")
    print("4. A ping is assigned to a trip only when its vehicle matches and recorded_at is inside that trip's scheduled window. This is for description, not a lateness model.")
    print("5. 'Far from route' means >300 m from the stop polyline; sub-100m geometry is explicitly not over-interpreted.")
    print("6. A stationary stretch is consecutive pings with reported speed <=1 km/h and movement <=25 m, lasting >=5 minutes.")
    print("7. Boarding-stop scheduled time is a linear interpolation by stop-polyline distance; this is only a schedule consistency check.")
    print("8. 'Future' is reported both relative to the run clock and relative to the requested 07:45 snapshot. Neither is a claim of bad data.")
    print("9. No rows are filtered, corrected, excluded, or used to calculate lateness. Operator 7 and Route 12 remain included everywhere.")

    heading("1. BASICS: SHAPE, TYPES, NULLS, TIMESTAMPS, FOREIGN KEYS")
    for name, frame in [("routes", routes), ("stops", stops), ("trips", trips), ("bookings", bookings), ("gps_pings", pings)]:
        print(f"\n{name}: {len(frame):,} rows, {len(frame.columns)} columns")
        show(pd.DataFrame({"column": frame.columns, "dtype": frame.dtypes.astype(str).values,
                           "nulls": frame.isna().sum().values}), "  columns / nulls", 30)
    timestamp_profile("Timestamp formats and ranges", raw["trips"], trips, ["scheduled_start", "scheduled_end"])
    timestamp_profile("", raw["bookings"], bookings, ["booked_at", "promised_eta"])
    timestamp_profile("", raw["gps_pings"], pings, ["recorded_at", "received_at"])
    print("\nAll parseable timestamp offsets above must be +05:30 to be consistently IST.")

    orphan_trips = trips[~trips.route_id.isin(routes.route_id)]
    orphan_bookings = bookings[~bookings.trip_id.isin(trips.trip_id)]
    orphan_stops = stops[~stops.route_id.isin(routes.route_id)]
    issue("Trips whose route_id does not resolve", orphan_trips.route_id.notna(), orphan_trips.trip_id)
    issue("Bookings whose trip_id does not resolve", orphan_bookings.trip_id.notna(), orphan_bookings.booking_id)
    issue("Stops whose route_id does not resolve", orphan_stops.route_id.notna(), orphan_stops.stop_id)

    heading("2. GPS TWO-CLOCK PROFILE")
    pings["lag_s"] = (pings.received_at - pings.recorded_at).dt.total_seconds()
    show(pd.DataFrame([quantiles(pings.lag_s)]).round(1), "Overall received_at - recorded_at, seconds")
    pings["service_date"] = pings.recorded_at.dt.date.astype("string")
    show(lag_table(pings, ["service_date"]), "Lag by recorded service date", 10)
    show(lag_table(pings, ["vehicle_id"]), "Lag by vehicle", 30)
    show(lag_table(pings, ["operator_id"]), "Lag by operator", 30)
    negative = pings.lag_s < 0
    issue("Negative lags (received before recorded)", negative, pings.loc[negative, "ping_id"])
    drift_rows = []
    for vehicle, g in pings.dropna(subset=["recorded_at", "lag_s"]).groupby("vehicle_id"):
        if len(g) >= 3:
            x = (g.recorded_at - g.recorded_at.min()).dt.total_seconds() / 3600
            slope = np.polyfit(x, g.lag_s, 1)[0]
            med = g.lag_s.median()
            if abs(med) >= 60 or abs(slope) >= 30:
                drift_rows.append([vehicle, len(g), round(med, 1), round(slope, 1), ids(g.ping_id)])
    show(pd.DataFrame(drift_rows, columns=["vehicle_id", "n", "median_lag_s", "lag_drift_s_per_hour", "example_ping_ids"]),
         "Vehicles with consistent >=60s clock offset or >=30s/hour estimated lag drift")

    # Exact scheduled-window matching, retaining all pings via a compact vehicle-level loop.
    trip_matches = []
    for vehicle, gp in pings.groupby("vehicle_id"):
        vt = trips[trips.vehicle_id == vehicle]
        for ping in gp.itertuples():
            matched = vt[(vt.scheduled_start <= ping.recorded_at) & (ping.recorded_at <= vt.scheduled_end)]
            for t in matched.itertuples():
                trip_matches.append([ping.Index, t.trip_id, t.route_id])
    matches = pd.DataFrame(trip_matches, columns=["ping_index", "trip_id", "route_id"])
    outside = ~pings.index.isin(matches.ping_index if not matches.empty else [])
    issue("Pings recorded outside every exact scheduled trip window", outside, pings.loc[outside, "ping_id"])
    # Direct test of the handoff's claimed before/after scheduled-trip telemetry buffer.
    buffer_rows = []
    for t in trips.itertuples():
        g = pings[(pings.vehicle_id == t.vehicle_id) & (pings.recorded_at.dt.date == t.scheduled_start.date())]
        before = g[g.recorded_at < t.scheduled_start]
        after = g[g.recorded_at > t.scheduled_end]
        buffer_rows.append([t.trip_id, len(before), len(after),
                            round((t.scheduled_start - before.recorded_at.max()).total_seconds() / 60, 1) if not before.empty else np.nan,
                            round((after.recorded_at.min() - t.scheduled_end).total_seconds() / 60, 1) if not after.empty else np.nan])
    buffer_check = pd.DataFrame(buffer_rows, columns=["trip_id", "pings_before_start", "pings_after_end", "closest_pre_start_min", "closest_post_end_min"])
    show(buffer_check, "Telemetry buffer around each scheduled trip (positive minutes are outside schedule)", 25)
    now = pd.Timestamp.now(tz=IST)
    future_run = pings.recorded_at > now
    future_snapshot = pings.recorded_at > AS_OF
    issue(f"Pings recorded after script run time ({now.strftime('%Y-%m-%d %H:%M %Z')})", future_run, pings.loc[future_run, "ping_id"])
    issue("Pings recorded after the requested 07:45 snapshot", future_snapshot, pings.loc[future_snapshot, "ping_id"])
    unavailable = (pings.recorded_at <= AS_OF) & (pings.received_at > AS_OF) & (pings.recorded_at.dt.date == AS_OF.date())
    issue("17 Jun pings recorded by 07:45 but received after 07:45", unavailable, pings.loc[unavailable, "ping_id"])
    show(pings.loc[unavailable, ["ping_id", "vehicle_id", "recorded_at", "received_at", "lag_s"]].sort_values("received_at"),
         "Those not-yet-ingested-at-as-of pings", 20)

    heading("3. PING QUALITY")
    dupe_id = pings.ping_id.duplicated(keep=False)
    dupe_vt = pings.duplicated(["vehicle_id", "recorded_at"], keep=False)
    issue("Rows sharing a duplicate ping_id", dupe_id, pings.loc[dupe_id, "ping_id"])
    issue("Rows sharing (vehicle_id, recorded_at)", dupe_vt, pings.loc[dupe_vt, "ping_id"])
    ordered_received = pings.sort_values(["vehicle_id", "received_at", "ping_id"]).copy()
    ordered_received["recorded_diff_s"] = ordered_received.groupby("vehicle_id").recorded_at.diff().dt.total_seconds()
    out_of_order = ordered_received.recorded_diff_s < 0
    issue("Pings whose recorded_at goes backwards in received_at order", out_of_order, ordered_received.loc[out_of_order, "ping_id"])
    bad_speed = (pings.speed_kmph < 0) | (pings.speed_kmph > REPORTED_SPEED_MAX)
    bad_coord = ~pings.lat.between(*MUMBAI_LAT) | ~pings.lon.between(*MUMBAI_LON)
    issue("Reported speeds <0 or >120 km/h", bad_speed, pings.loc[bad_speed, "ping_id"])
    issue("Coordinates outside coarse Mumbai bounds", bad_coord, pings.loc[bad_coord, "ping_id"])
    seq = pings.sort_values(["vehicle_id", "recorded_at", "ping_id"]).copy()
    seq["prev_lat"] = seq.groupby("vehicle_id").lat.shift()
    seq["prev_lon"] = seq.groupby("vehicle_id").lon.shift()
    seq["delta_s"] = seq.groupby("vehicle_id").recorded_at.diff().dt.total_seconds()
    seq["move_m"] = haversine_m(seq.prev_lat, seq.prev_lon, seq.lat, seq.lon)
    seq["implied_kmph"] = seq.move_m / seq.delta_s * 3.6
    impossible_implied = (seq.delta_s > 0) & (seq.implied_kmph > IMPLIED_SPEED_MAX)
    issue("Consecutive-coordinate implied speeds >130 km/h", impossible_implied, seq.loc[impossible_implied, "ping_id"])
    show(seq.loc[impossible_implied, ["ping_id", "vehicle_id", "delta_s", "move_m", "implied_kmph"]].round(1),
         "Implied-speed examples", 20)
    gaps = seq.delta_s > 180
    show(seq.groupby("vehicle_id").delta_s.agg(pings="count", median_gap_s="median", max_gap_s="max").reset_index().round(1),
         "Ping frequency by vehicle", 30)
    issue("Inter-ping gaps longer than 3 minutes", gaps, seq.loc[gaps, "ping_id"])
    show(seq.loc[gaps, ["ping_id", "vehicle_id", "recorded_at", "delta_s"]].sort_values("delta_s", ascending=False), "Longest gaps", 20)

    # Stationary runs are built from adjacent stationary observations, then labelled by route/nearest stop.
    seq["stationary"] = (seq.speed_kmph <= STATIONARY_SPEED) & (seq.move_m.fillna(0) <= STATIONARY_MOVE_M)
    seq["new_stationary_run"] = (~seq.stationary) | (~seq.stationary.groupby(seq.vehicle_id).shift(fill_value=False))
    seq["stationary_run"] = seq.groupby("vehicle_id").new_stationary_run.cumsum()
    runs = []
    for (veh, run), g in seq[seq.stationary].groupby(["vehicle_id", "stationary_run"]):
        duration = (g.recorded_at.max() - g.recorded_at.min()).total_seconds() / 60
        if duration >= STATIONARY_MINUTES:
            row = g.iloc[len(g) // 2]
            mt = matches[matches.ping_index.isin(g.index)]
            route = int(mt.route_id.mode().iloc[0]) if not mt.empty else None
            where = nearest_stop_kind(row.lat, row.lon, route, stops) if route is not None else "unassigned / possible depot"
            runs.append([veh, g.ping_id.iloc[0], g.ping_id.iloc[-1], len(g), round(duration, 1), route, where])
    stationary = pd.DataFrame(runs, columns=["vehicle_id", "first_ping_id", "last_ping_id", "pings", "duration_min", "route_id", "where"])
    show(stationary.sort_values("duration_min", ascending=False), "Stationary stretches >=5 min (all; labelled geometrically)", 30)

    heading("4. ENTITY CONSISTENCY")
    ping_vehicles = set(pings.vehicle_id.dropna())
    trip_vehicles = set(trips.vehicle_id.dropna())
    print(f"- Vehicles in pings but not trips: {len(ping_vehicles - trip_vehicles):,}; examples: {ids(ping_vehicles - trip_vehicles)}")
    print(f"- Vehicles in trips but not pings: {len(trip_vehicles - ping_vehicles):,}; examples: {ids(trip_vehicles - ping_vehicles)}")
    pinged_trips = set(matches.trip_id) if not matches.empty else set()
    zero_ping_trips = trips[~trips.trip_id.isin(pinged_trips)]
    issue("Trips with zero pings in their exact scheduled window", zero_ping_trips.trip_id.notna(), zero_ping_trips.trip_id)
    op_counts = pings.groupby("vehicle_id").operator_id.nunique()
    inconsistent_ops = op_counts[op_counts != 1]
    print(f"- Vehicles with other than exactly one operator_id: {len(inconsistent_ops):,}; examples: {ids(inconsistent_ops.index)}")
    show(pings[pings.vehicle_id.isin(inconsistent_ops.index)].groupby("vehicle_id").operator_id.agg(lambda x: ",".join(map(str, sorted(set(x))))).reset_index(name="operator_ids"), "Operator inconsistencies")
    vehicle_schedule = trips.sort_values(["vehicle_id", "scheduled_start"]).copy()
    vehicle_schedule["previous_end"] = vehicle_schedule.groupby("vehicle_id").scheduled_end.shift()
    vehicle_schedule["gap_from_previous_min"] = (vehicle_schedule.scheduled_start - vehicle_schedule.previous_end).dt.total_seconds() / 60
    overlap_or_back = vehicle_schedule.gap_from_previous_min <= 0
    issue("Trips that overlap or exactly abut a previous trip for that vehicle", overlap_or_back, vehicle_schedule.loc[overlap_or_back, "trip_id"])
    show(vehicle_schedule.loc[overlap_or_back, ["vehicle_id", "trip_id", "scheduled_start", "previous_end", "gap_from_previous_min"]], "Overlapping/back-to-back trip details")
    multi_match = matches.ping_index.value_counts() > 1 if not matches.empty else pd.Series(dtype=bool)
    print(f"- Pings falling in two or more scheduled windows for one vehicle: {int(multi_match.sum()):,}; examples: {ids(pings.loc[multi_match.index[multi_match], 'ping_id'] if len(multi_match) else [])}")

    heading("5. REFERENCE DATA AND ROUTE-GEOMETRY CHECKS")
    actual_stops = stops.groupby("route_id").size().rename("actual_stop_rows")
    route_stop_check = routes.merge(actual_stops, on="route_id", how="left")
    route_stop_check["difference"] = route_stop_check.actual_stop_rows - route_stop_check.stops_count
    show(route_stop_check, "Declared versus actual stop counts", 30)
    route_runtime = trips.copy()
    route_runtime["actual_scheduled_min"] = (route_runtime.scheduled_end - route_runtime.scheduled_start).dt.total_seconds() / 60
    route_runtime = route_runtime.merge(routes[["route_id", "scheduled_runtime_min"]], on="route_id")
    route_runtime["difference_min"] = route_runtime.actual_scheduled_min - route_runtime.scheduled_runtime_min
    show(route_runtime.groupby("route_id").agg(trips=("trip_id", "count"), declared_min=("scheduled_runtime_min", "first"), actual_min=("actual_scheduled_min", "median"), min_difference=("difference_min", "min"), max_difference=("difference_min", "max")).reset_index(), "Runtime agreement by route")
    issue("Trips whose scheduled interval differs from route runtime", route_runtime.difference_min != 0, route_runtime.loc[route_runtime.difference_min != 0, "trip_id"])
    seq_check = stops.groupby("route_id").agg(rows=("stop_id", "count"), min_seq=("seq", "min"), max_seq=("seq", "max"), unique_seq=("seq", "nunique")).reset_index()
    seq_check["missing_or_duplicate"] = seq_check.rows != seq_check.unique_seq
    show(seq_check, "Stop sequence completeness summary", 30)
    dup_seq = stops.duplicated(["route_id", "seq"], keep=False)
    bad_stop_coords = ~stops.lat.between(*MUMBAI_LAT) | ~stops.lon.between(*MUMBAI_LON)
    issue("Stops with duplicate route_id/seq", dup_seq, stops.loc[dup_seq, "stop_id"])
    issue("Stop coordinates outside coarse Mumbai bounds", bad_stop_coords, stops.loc[bad_stop_coords, "stop_id"])
    segment_checks = []
    for rid, ss in stops.groupby("route_id"):
        ss = ss.sort_values("seq")
        segments = haversine_m(ss.lat.to_numpy()[:-1], ss.lon.to_numpy()[:-1], ss.lat.to_numpy()[1:], ss.lon.to_numpy()[1:]) / 1000
        segment_checks.append([rid, len(segments), round(float(segments.min()), 3), round(float(segments.max()), 3), int((segments < .01).sum()), int((segments > 5).sum())])
    show(pd.DataFrame(segment_checks, columns=["route_id", "segments", "shortest_segment_km", "longest_segment_km", "near_zero_segments", "segments_over_5km"]),
         "Stop-order geographic screen (map-free: zero-length or >5km adjacent jumps)")
    print("Interpretation limit: this map-free screen can flag pathological adjacent jumps, but cannot prove a road-realistic stop order.")
    route_lines = []
    for rid, ss in stops.groupby("route_id"):
        ss = ss.sort_values("seq")
        segment_km = haversine_m(ss.lat.to_numpy()[:-1], ss.lon.to_numpy()[:-1], ss.lat.to_numpy()[1:], ss.lon.to_numpy()[1:]) / 1000
        length = float(segment_km.sum())
        runtime = float(routes.loc[routes.route_id == rid, "scheduled_runtime_min"].iloc[0])
        route_lines.append([rid, round(length, 2), runtime, round(length / (runtime / 60), 1), round(float(segment_km.max()), 2)])
    show(pd.DataFrame(route_lines, columns=["route_id", "polyline_km", "runtime_min", "implied_avg_kmph", "longest_stop_segment_km"]), "Route polyline lengths and schedule-implied average speed")
    if not matches.empty:
        assigned = pings.loc[matches.ping_index].copy()
        assigned["route_id"] = matches.set_index("ping_index").loc[assigned.index, "route_id"].to_numpy()
        assigned["polyline_distance_m"] = [
            polyline_distance_m(r.lat, r.lon, stops[stops.route_id == r.route_id])
            for r in assigned.itertuples()
        ]
        assigned["far"] = assigned.polyline_distance_m > FAR_FROM_ROUTE_M
        route_distance = assigned.groupby(["vehicle_id", "route_id"]).agg(pings=("ping_id", "count"), median_distance_m=("polyline_distance_m", "median"), p95_distance_m=("polyline_distance_m", lambda x: x.quantile(.95)), far_pings=("far", "sum")).reset_index()
        route_distance["far_share_pct"] = 100 * route_distance.far_pings / route_distance.pings
        show(route_distance.round(1), "Assigned-ping distances from route polyline", 30)
        consistent_far = (route_distance.pings >= 5) & (route_distance.far_share_pct >= 50)
        print(f"- Vehicle-route pair consistently far (>300m for >=50% of >=5 assigned pings): {int(consistent_far.sum()):,}; examples: {ids(route_distance.loc[consistent_far].vehicle_id)}")

    heading("6. BOOKINGS")
    booking_counts = bookings.groupby("trip_id").size().rename("bookings").reset_index()
    show(trips[["trip_id", "route_id", "vehicle_id"]].merge(booking_counts, on="trip_id", how="left").fillna({"bookings": 0}).sort_values("trip_id"), "Bookings per trip", 40)
    after_start = bookings.merge(trips[["trip_id", "scheduled_start"]], on="trip_id", how="left")
    booked_after = after_start.booked_at > after_start.scheduled_start
    issue("Bookings made after their trip's scheduled start", booked_after, after_start.loc[booked_after, "booking_id"])
    # Expected stop time from cumulative stop-polyline distance.
    stop_expected = []
    for trip in trips.itertuples():
        ss = stops[stops.route_id == trip.route_id].sort_values("seq").copy()
        ss["seg_m"] = np.r_[0, haversine_m(ss.lat.to_numpy()[:-1], ss.lon.to_numpy()[:-1], ss.lat.to_numpy()[1:], ss.lon.to_numpy()[1:])]
        ss["cum_fraction"] = ss.seg_m.cumsum() / ss.seg_m.sum()
        for s in ss.itertuples():
            expected = trip.scheduled_start + (trip.scheduled_end - trip.scheduled_start) * s.cum_fraction
            stop_expected.append([trip.trip_id, s.stop_id, expected])
    expected_eta = pd.DataFrame(stop_expected, columns=["trip_id", "boarding_stop_id", "expected_stop_eta"])
    eta = bookings.merge(expected_eta, on=["trip_id", "boarding_stop_id"], how="left")
    eta["eta_difference_s"] = (eta.promised_eta - eta.expected_stop_eta).dt.total_seconds()
    unresolved_stops = eta.expected_stop_eta.isna()
    eta_inconsistent = eta.eta_difference_s.abs() > 60
    issue("Bookings whose boarding stop is not found on their trip route", unresolved_stops, eta.loc[unresolved_stops, "booking_id"])
    issue("Promised ETAs differing by >60s from polyline-interpolated schedule", eta_inconsistent, eta.loc[eta_inconsistent, "booking_id"])
    show(eta.loc[eta_inconsistent, ["booking_id", "trip_id", "boarding_stop_id", "promised_eta", "expected_stop_eta", "eta_difference_s"]].sort_values("eta_difference_s"), "Promised-ETA consistency examples", 20)

    heading("7. WHAT THE TWO RECONCILIATION RULES WOULD HIDE (DESCRIPTIVE ONLY)")
    op7_vehicles = set(pings.loc[pings.operator_id == 7, "vehicle_id"])
    op7_trips = trips[trips.vehicle_id.isin(op7_vehicles)]
    op7_bookings = bookings[bookings.trip_id.isin(op7_trips.trip_id)]
    print(f"Operator 7: {len(op7_vehicles):,} vehicles ({ids(op7_vehicles)}); {len(op7_trips):,} trips ({ids(op7_trips.trip_id)}); {int((pings.operator_id == 7).sum()):,} pings ({ids(pings.loc[pings.operator_id == 7, 'ping_id'])}); {len(op7_bookings):,} bookings; {op7_bookings.rider_id.nunique():,} distinct riders ({ids(op7_bookings.rider_id)}).")
    show(op7_trips.groupby("route_id").agg(trips=("trip_id", "count"), vehicles=("vehicle_id", lambda x: ",".join(sorted(set(x)))), bookings=("trip_id", lambda x: int(bookings.trip_id.isin(x).sum()))).reset_index(), "Operator 7 routes")
    route_operators = trips.merge(pings[["vehicle_id", "operator_id"]].drop_duplicates(), on="vehicle_id", how="left").groupby("route_id").operator_id.agg(lambda x: sorted(set(x.dropna()))).reset_index()
    show(route_operators, "All operators represented by each route's vehicles")
    only7 = route_operators[route_operators.operator_id.apply(lambda x: x == [7])]
    print(f"- Routes represented only by operator 7 in this extract: {len(only7):,}; examples: {ids(only7.route_id)}")
    quality = pings.assign(operator_group=np.where(pings.operator_id == 7, "operator_7", "other_operators")).groupby("operator_group").agg(
        pings=("ping_id", "count"), vehicles=("vehicle_id", "nunique"), median_lag_s=("lag_s", "median"), p95_lag_s=("lag_s", lambda x: x.quantile(.95)), negative_lags=("lag_s", lambda x: int((x < 0).sum())), duplicate_ping_id=("ping_id", lambda x: int(x.duplicated(keep=False).sum()))).reset_index()
    quality["long_gaps"] = [int(gaps[pings.operator_id == 7].sum()), int(gaps[pings.operator_id != 7].sum())] if len(quality) == 2 else np.nan
    show(quality.round(1), "Operator 7 versus other-operator clock/duplicate/gap profile")
    if not stationary.empty:
        print(f"- Stationary stretches: operator 7 {int(stationary.vehicle_id.isin(op7_vehicles).sum()):,}; other operators {int((~stationary.vehicle_id.isin(op7_vehicles)).sum()):,}; examples op7: {ids(stationary.loc[stationary.vehicle_id.isin(op7_vehicles), 'first_ping_id'])}")
    route12 = trips[trips.route_id == 12]
    b12 = bookings[bookings.trip_id.isin(route12.trip_id)]
    ops12 = pings[pings.vehicle_id.isin(route12.vehicle_id)].groupby("vehicle_id").operator_id.agg(lambda x: sorted(set(x))).to_dict()
    print(f"Route 12: {len(route12):,} trips ({ids(route12.trip_id)}); {len(b12):,} bookings; {b12.rider_id.nunique():,} riders ({ids(b12.rider_id)}); vehicle/operators {ops12}.")
    raw12 = route12.merge(matches.groupby("trip_id").size().rename("pings_in_scheduled_window"), on="trip_id", how="left").fillna({"pings_in_scheduled_window": 0})
    if not matches.empty:
        p12 = matches[matches.trip_id.isin(route12.trip_id)].merge(
            pings[["ping_id", "recorded_at"]], left_on="ping_index", right_index=True, how="left"
        )
        raw_telemetry = p12.groupby("trip_id").agg(first_recorded=("recorded_at", "min"), last_recorded=("recorded_at", "max"), ping_rows=("ping_id", "count")).reset_index()
        raw12 = raw12.merge(raw_telemetry, on="trip_id", how="left")
    show(raw12[[c for c in ["trip_id", "service_date", "vehicle_id", "scheduled_start", "scheduled_end", "pings_in_scheduled_window", "first_recorded", "last_recorded", "ping_rows"] if c in raw12]], "Route 12: raw schedule and telemetry coverage by morning", 20)

    heading("8. 07:45 IST SNAPSHOT ON 2026-06-17 (DESCRIPTIVE ONLY)")
    today = trips[trips.service_date.astype(str) == "2026-06-17"].copy()
    today["in_progress"] = (today.scheduled_start <= AS_OF) & (AS_OF < today.scheduled_end)
    today["not_started"] = today.scheduled_start > AS_OF
    snapshot_counts = today.groupby("route_id").agg(trips_scheduled=("trip_id", "count"), in_progress=("in_progress", "sum"), not_yet_started=("not_started", "sum")).reset_index()
    show(snapshot_counts, "Trips scheduled / in progress / not yet started at 07:45", 30)
    active = today[today.in_progress].copy()
    snapshot_rows = []
    for t in active.itertuples():
        g = pings[(pings.vehicle_id == t.vehicle_id) & (pings.recorded_at.dt.date == AS_OF.date())]
        by_received = g[g.received_at <= AS_OF].sort_values("received_at").tail(1)
        by_recorded = g[g.recorded_at <= AS_OF].sort_values("recorded_at").tail(1)
        r = by_received.iloc[0] if not by_received.empty else None
        q = by_recorded.iloc[0] if not by_recorded.empty else None
        snapshot_rows.append([t.route_id, t.trip_id, t.vehicle_id,
            r.ping_id if r is not None else None, r.received_at if r is not None else pd.NaT,
            round((AS_OF - r.received_at).total_seconds()/60, 1) if r is not None else np.nan,
            q.ping_id if q is not None else None, q.recorded_at if q is not None else pd.NaT,
            round((AS_OF - q.recorded_at).total_seconds()/60, 1) if q is not None else np.nan])
    snapshot = pd.DataFrame(snapshot_rows, columns=["route_id", "trip_id", "vehicle_id", "last_by_received_ping_id", "last_received_at", "received_age_min", "last_by_recorded_ping_id", "last_recorded_at", "recorded_age_min"])
    show(snapshot, "Active vehicles: most recent pings under each clock cutoff", 30)
    usable_routes = set(snapshot.loc[snapshot.last_by_received_ping_id.notna() | snapshot.last_by_recorded_ping_id.notna(), "route_id"])
    active_routes = set(active.route_id)
    print(f"- Active routes with no usable ping by either cutoff: {len(active_routes - usable_routes):,}; examples: {ids(active_routes - usable_routes)}")

    heading("END OF DESCRIPTIVE PROFILE")
    print("The script intentionally does not rank routes, produce a lateness value, make operational recommendations, or apply reconciliation rules.")


if __name__ == "__main__":
    main()
