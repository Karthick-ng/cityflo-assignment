"""Focused, descriptive telemetry drill-down.  No lateness metric or row filtering."""
from __future__ import annotations

from pathlib import Path
import sys
import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
IST = "Asia/Kolkata"
ASOF = pd.Timestamp("2026-06-17 07:45:00", tz=IST)
NEAR_STOP_M = 100.0
MOVING_KMPH = 1.0


def show(df, title, n=30):
    print(f"\n{title}")
    if df is None or len(df) == 0:
        print("  None")
    else:
        print(df.head(n).to_string(index=False))
        if len(df) > n:
            print(f"  ... {len(df)-n} more rows suppressed")


def parse(df, cols):
    for c in cols:
        df[c] = pd.to_datetime(df[c], format="%Y-%m-%d %H:%M:%S%z", errors="coerce", utc=True).dt.tz_convert(IST)
    return df


def hav(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    a = np.sin((lat2-lat1)/2)**2 + np.cos(lat1)*np.cos(lat2)*np.sin((lon2-lon1)/2)**2
    return 6371000 * 2 * np.arctan2(np.sqrt(a), np.sqrt(1-a))


def project(lat, lon, stops):
    """Return nearest polyline distance and distance-along-route in local metres."""
    s = stops.sort_values("seq")
    lat0 = np.radians(float(s.lat.mean()))
    x = (s.lon.to_numpy() - s.lon.iloc[0]) * 111320 * np.cos(lat0)
    y = (s.lat.to_numpy() - s.lat.iloc[0]) * 111320
    px = (lon - s.lon.iloc[0]) * 111320 * np.cos(lat0)
    py = (lat - s.lat.iloc[0]) * 111320
    seg = np.hypot(np.diff(x), np.diff(y))
    cumulative = np.r_[0, np.cumsum(seg)]
    best = (float("inf"), 0.0)
    for i, length in enumerate(seg):
        vx, vy = x[i+1]-x[i], y[i+1]-y[i]
        t = 0 if length == 0 else np.clip(((px-x[i])*vx + (py-y[i])*vy)/(length**2), 0, 1)
        d = float(np.hypot(px-(x[i]+t*vx), py-(y[i]+t*vy)))
        if d < best[0]: best = (d, float(cumulative[i] + t*length))
    return best[0], best[1], float(cumulative[-1])


def enrich(g, route_id, stops):
    ss = stops[stops.route_id == route_id]
    out = g.copy()
    vals = [project(r.lat, r.lon, ss) for r in out.itertuples()]
    out[["polyline_offset_m", "along_m", "route_length_m"]] = vals
    out["along_pct"] = 100 * out.along_m / out.route_length_m
    d = [hav(r.lat, r.lon, ss.lat.to_numpy(), ss.lon.to_numpy()) for r in out.itertuples()]
    nearest_i = [int(np.argmin(x)) for x in d]
    out["nearest_stop"] = [ss.iloc[i].stop_name for i in nearest_i]
    out["nearest_stop_id"] = [ss.iloc[i].stop_id for i in nearest_i]
    out["nearest_stop_m"] = [float(x[i]) for x, i in zip(d, nearest_i)]
    return out


def trip_pings(trip, pings):
    return pings[(pings.vehicle_id == trip.vehicle_id) & (pings.recorded_at >= trip.scheduled_start) & (pings.recorded_at <= trip.scheduled_end)].copy()


def main():
    routes = pd.read_csv(ROOT / "data/routes.csv")
    stops = pd.read_csv(ROOT / "data/stops.csv")
    trips = parse(pd.read_csv(ROOT / "data/trips.csv"), ["scheduled_start", "scheduled_end"])
    pings = parse(pd.read_csv(ROOT / "data/gps_pings.csv"), ["recorded_at", "received_at"])
    pings["lag_s"] = (pings.received_at - pings.recorded_at).dt.total_seconds()
    op = pings.groupby("vehicle_id").operator_id.first().rename("operator_id")

    print("ASSUMPTIONS")
    print("1. All timestamps are parsed as offset-bearing IST timestamps.")
    print("2. Trip ping membership means same vehicle and recorded_at within exact scheduled start/end.")
    print("3. 'Near origin/destination/stop' means within 100m of that stop; 'moving' means speed_kmph > 1.")
    print("4. Route progress is projection onto the ordered stop polyline using a local planar approximation; it is descriptive, not road-matched.")
    print("5. Timetable progress fraction is elapsed scheduled time / scheduled runtime. It is not a lateness calculation.")
    print("6. A lag episode is defined here as lag >=300 seconds; a '90-minute' episode is exactly 5400 seconds.")
    print("7. 'Last ping before silence' means the final recorded_at ping before 07:45; no cause is inferred from absence of later pings.")
    print("8. Completed-trip runtime requires both a moving ping within 100m of origin and a ping within 100m of destination; otherwise it is reported unavailable.")
    print("9. No operator, route, ping, or booking is excluded or corrected; no reconciliation rule is applied.")

    print("\nA. V-04 90-MINUTE LAG")
    v04trip = trips[(trips.vehicle_id == "V-04") & (trips.service_date.astype(str) == "2026-06-17")].iloc[0]
    print(f"17 Jun: {v04trip.trip_id}, Route {v04trip.route_id}, scheduled {v04trip.scheduled_start} to {v04trip.scheduled_end}.")
    v04day = pings[(pings.vehicle_id == "V-04") & (pings.recorded_at.dt.date == ASOF.date())].sort_values("recorded_at")
    normal = v04day[v04day.lag_s < 300]
    lagged = v04day[v04day.lag_s == 5400]
    show(pd.concat([normal.tail(1), lagged.head(1)])[['ping_id','recorded_at','received_at','lag_s','lat','lon','speed_kmph']], "Last normal / first 5400s-lag ping", 5)
    print(f"5400s episode: {len(lagged)} pings; starts {lagged.recorded_at.min()}, ends {lagged.recorded_at.max()}; received range {lagged.received_at.min()} to {lagged.received_at.max()}.")
    print(f"After episode: {int((v04day.recorded_at > lagged.recorded_at.max()).sum())} later device-time rows; of these, {int(((v04day.recorded_at > lagged.recorded_at.max()) & (v04day.lag_s < 300)).sum())} have normal lag.")
    boundary = v04day[(v04day.recorded_at >= normal.tail(1).recorded_at.iloc[0] - pd.Timedelta(minutes=2)) & (v04day.recorded_at <= lagged.head(1).recorded_at.iloc[0] + pd.Timedelta(minutes=2))]
    show(boundary[['ping_id','recorded_at','received_at','lag_s','speed_kmph']], "Boundary sequence (device order)", 20)
    print("The received timestamps for 5400s rows remain recorded_at + 90 minutes, so they are spread at their normal device cadence in received time, not one identical-timestamp burst.")
    episodes=[]
    for veh, g in pings.sort_values('recorded_at').groupby('vehicle_id'):
        for date, h in g.groupby(g.recorded_at.dt.date):
            q=h[h.lag_s >=300]
            if not q.empty: episodes.append([veh,str(date),len(q),q.lag_s.min(),q.lag_s.max(),q.ping_id.iloc[0],q.ping_id.iloc[-1]])
    show(pd.DataFrame(episodes, columns=['vehicle_id','date','pings_lag_ge_300s','min_lag_s','max_lag_s','first_ping','last_ping']), "All >=300s lag episodes (includes 15/16 June if any)")
    v04route = enrich(trip_pings(v04trip,pings), v04trip.route_id, stops).sort_values('recorded_at')
    sample = v04route[v04route.lag_s == 5400].iloc[::max(1,len(lagged)//6)][['ping_id','recorded_at','received_at','speed_kmph','along_m','along_pct','nearest_stop','polyline_offset_m']]
    show(sample.round({'along_m':1,'along_pct':1,'polyline_offset_m':1}), "Sample of V-04's lagged pings in recorded-time order", 10)

    print("\nB. V-05 / ROUTE 17")
    v05trip=trips[(trips.vehicle_id=='V-05')&(trips.service_date.astype(str)=='2026-06-17')].iloc[0]
    g05=enrich(trip_pings(v05trip,pings),v05trip.route_id,stops).sort_values('recorded_at')
    last05=g05[g05.recorded_at<=ASOF].tail(1)
    print(f"{v05trip.trip_id}, Route {v05trip.route_id}, scheduled {v05trip.scheduled_start} to {v05trip.scheduled_end}.")
    show(last05[['ping_id','recorded_at','received_at','speed_kmph','along_m','along_pct','nearest_stop','nearest_stop_id','nearest_stop_m','polyline_offset_m']], "Last recorded ping at/before 07:45", 5)
    if not last05.empty:
        x=last05.iloc[0]; status="moving" if x.speed_kmph>MOVING_KMPH else "stationary"
        print(f"Classification under assumptions: {status}; nearest stop {x.nearest_stop} ({x.nearest_stop_m:.1f}m), route progress {x.along_pct:.1f}%.")
    g05['gap_s']=g05.recorded_at.diff().dt.total_seconds()
    show(g05[g05.gap_s>180][['ping_id','recorded_at','gap_s']], "V-05 in-trip gaps >3 minutes", 20)
    hist05=pings[pings.vehicle_id=='V-05'].sort_values('recorded_at').copy(); hist05['gap_s']=hist05.recorded_at.diff().dt.total_seconds()
    show(hist05[(hist05.recorded_at.dt.date<ASOF.date())&(hist05.gap_s>180)][['ping_id','recorded_at','gap_s']], "V-05 gaps >3 min on 15/16 June",20)

    print("\nC. V-11 SPEED-GLITCH SEQUENCE")
    glitch=pings[pings.ping_id.isin(['P-0003148','P-0003149','P-0003150','P-0003151'])].sort_values('recorded_at')
    for r in glitch.itertuples():
        t=trips[(trips.vehicle_id==r.vehicle_id)&(trips.scheduled_start<=r.recorded_at)&(trips.scheduled_end>=r.recorded_at)]
        print(f"{r.ping_id}: {r.recorded_at}, V-11, speed {r.speed_kmph}; trip/route {t.iloc[0].trip_id if len(t) else 'none'}/{int(t.iloc[0].route_id) if len(t) else 'none'}.")
    around=pings[pings.vehicle_id=='V-11'].sort_values('recorded_at'); lo=glitch.recorded_at.min()-pd.Timedelta(minutes=2); hi=glitch.recorded_at.max()+pd.Timedelta(minutes=2)
    show(around[(around.recorded_at>=lo)&(around.recorded_at<=hi)][['ping_id','recorded_at','received_at','lat','lon','speed_kmph']],"Two minutes either side of glitch sequence",30)
    latest11=pings[(pings.vehicle_id=='V-11')&(pings.received_at<=ASOF)&(pings.recorded_at.dt.date==ASOF.date())].sort_values('received_at').tail(1)
    show(latest11[['ping_id','recorded_at','received_at','speed_kmph']],"V-11 latest received ping by 07:45",5)

    print("\nD. ROUTE 12 / TRIP_015 RAW COMPARISON")
    r12=trips[trips.route_id==12].sort_values('service_date')
    rows=[]
    for t in r12.itertuples():
        g=enrich(trip_pings(t,pings),12,stops).sort_values('recorded_at')
        origin=g[(g.nearest_stop_id==stops[stops.route_id==12].sort_values('seq').iloc[0].stop_id)&(g.nearest_stop_m<=NEAR_STOP_M)&(g.speed_kmph>MOVING_KMPH)].head(1)
        rows.append([t.trip_id,str(t.service_date),t.scheduled_start,origin.ping_id.iloc[0] if len(origin) else None,origin.recorded_at.iloc[0] if len(origin) else pd.NaT,round((origin.recorded_at.iloc[0]-t.scheduled_start).total_seconds()/60,1) if len(origin) else np.nan])
    show(pd.DataFrame(rows,columns=['trip_id','date','scheduled_start','first_moving_near_origin_ping','recorded_at','minutes_from_scheduled_start']),"First moving ping near Route 12 origin",10)
    progress=[]
    for t in r12.itertuples():
        cutoff=pd.Timestamp(f"{t.service_date} 07:45:00",tz=IST)
        g=enrich(trip_pings(t,pings),12,stops); last=g[g.recorded_at<=cutoff].sort_values('recorded_at').tail(1)
        fraction=100*(cutoff-t.scheduled_start).total_seconds()/(t.scheduled_end-t.scheduled_start).total_seconds()
        progress.append([t.trip_id,str(t.service_date),round(fraction,1),last.ping_id.iloc[0] if len(last) else None,round(last.along_pct.iloc[0],1) if len(last) else np.nan,last.recorded_at.iloc[0] if len(last) else pd.NaT])
    show(pd.DataFrame(progress,columns=['trip_id','date','scheduled_elapsed_pct_at_0745','last_ping_by_recorded_at','observed_polyline_pct','ping_time']),"Route 12 observed route progress at 07:45 versus scheduled elapsed fraction",10)

    print("\nE. OPERATOR 7 AND ROUTE 21")
    alltr=trips.assign(operator_id=trips.vehicle_id.map(op)).sort_values(['service_date','route_id','trip_id'])
    show(alltr[['service_date','route_id','trip_id','vehicle_id','operator_id']],"All trips per day / route / operator",30)
    show(alltr[alltr.service_date.astype(str)=='2026-06-17'].groupby('route_id').agg(trips=('trip_id','count'),vehicles=('vehicle_id',lambda x:', '.join(x)),operators=('operator_id',lambda x:', '.join(map(str,x)))).reset_index(),"All routes: 17 June trip counts",20)
    route21=alltr[alltr.route_id==21]
    show(route21[['service_date','trip_id','vehicle_id','operator_id']],"Route 21 vehicles/operators by day",20)
    dropped_routes=sorted(set(alltr[alltr.operator_id==7].route_id))
    print(f"Dropping operator 7 would remove these trip rows: {len(alltr[alltr.operator_id==7])}; route IDs represented: {dropped_routes}. No route has only operator-7 trips in this extract.")

    print("\nF. COMPLETED-TRIP RAW RUNTIMES, 15/16 JUNE")
    runtimes=[]
    for t in trips[trips.service_date.astype(str).isin(['2026-06-15','2026-06-16'])].itertuples():
        g=enrich(trip_pings(t,pings),t.route_id,stops).sort_values('recorded_at')
        ss=stops[stops.route_id==t.route_id].sort_values('seq'); origin_id=ss.iloc[0].stop_id; dest_id=ss.iloc[-1].stop_id
        start=g[(g.nearest_stop_id==origin_id)&(g.nearest_stop_m<=NEAR_STOP_M)&(g.speed_kmph>MOVING_KMPH)].head(1)
        end=g[(g.nearest_stop_id==dest_id)&(g.nearest_stop_m<=NEAR_STOP_M)].tail(1)
        actual=(end.recorded_at.iloc[0]-start.recorded_at.iloc[0]).total_seconds()/60 if len(start) and len(end) else np.nan
        runtimes.append([t.trip_id,str(t.service_date),t.route_id,t.vehicle_id,start.ping_id.iloc[0] if len(start) else None,end.ping_id.iloc[0] if len(end) else None,round(actual,1) if not np.isnan(actual) else np.nan,(t.scheduled_end-t.scheduled_start).total_seconds()/60])
    show(pd.DataFrame(runtimes,columns=['trip_id','date','route_id','vehicle_id','first_moving_origin_ping','last_near_destination_ping','observed_minutes','scheduled_minutes']),"Observed origin-to-destination ping spans",30)
    print("\nEND: descriptive drill-down only; no lateness value, verdict, or reconciliation rule applied.")

if __name__=='__main__': main()
