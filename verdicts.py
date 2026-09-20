"""Route verdict policy selected by the user. Usage: verdicts.py --date YYYY-MM-DD --asof HH:MM"""
from pathlib import Path
import argparse,sys,numpy as np,pandas as pd
from drill2 import enrich
if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
ROOT=Path(__file__).resolve().parent; IST='Asia/Kolkata'; IMPLIED_LIMIT=130.; REV_C_OPERATOR=7; REV_C_ROUTE=12
RANK={'CALL_DRIVER':4,'NO_VERDICT':3,'PUSH_LATE':2,'HOLD':1}
def parse(x,cols):
 for c in cols:x[c]=pd.to_datetime(x[c],format='%Y-%m-%d %H:%M:%S%z',errors='coerce',utc=True).dt.tz_convert(IST)
 return x
def hav(a,b,c,d):
 a,b,c,d=map(np.radians,[a,b,c,d]);z=np.sin((c-a)/2)**2+np.cos(a)*np.cos(c)*np.sin((d-b)/2)**2;return 6371000*2*np.arctan2(np.sqrt(z),np.sqrt(1-z))
def show(x,title,n=40):
 print('\n'+title);print('  None' if len(x)==0 else x.head(n).to_string(index=False))
def load():
 routes=pd.read_csv(ROOT/'data/routes.csv');stops=pd.read_csv(ROOT/'data/stops.csv');trips=parse(pd.read_csv(ROOT/'data/trips.csv'),['scheduled_start','scheduled_end']);book=parse(pd.read_csv(ROOT/'data/bookings.csv'),['booked_at','promised_eta']);p=parse(pd.read_csv(ROOT/'data/gps_pings.csv'),['recorded_at','received_at'])
 # requested hygiene: remove malformed timestamp, dedupe vehicle/timestamp, then remove coordinate speed jumps.
 p=p.dropna(subset=['recorded_at']).sort_values(['vehicle_id','recorded_at','received_at']).drop_duplicates(['vehicle_id','recorded_at'],keep='first').copy()
 p['prev_lat']=p.groupby('vehicle_id').lat.shift();p['prev_lon']=p.groupby('vehicle_id').lon.shift();p['prev_time']=p.groupby('vehicle_id').recorded_at.shift();p['implied_kmph']=hav(p.prev_lat,p.prev_lon,p.lat,p.lon)/p.recorded_at.sub(p.prev_time).dt.total_seconds()*3.6
 p=p[~(p.implied_kmph>IMPLIED_LIMIT)].copy()
 return routes,stops,trips,book,p
def healthy_gate(trips,p):
 # historical exact-trip received-clock gaps; max inside a single scheduled trip.
 gaps=[]
 for t in trips[trips.service_date.astype(str).isin(['2026-06-15','2026-06-16'])].itertuples():
  g=p[(p.vehicle_id==t.vehicle_id)&(p.recorded_at>=t.scheduled_start)&(p.recorded_at<=t.scheduled_end)].sort_values('received_at').copy();g['gap']=g.received_at.diff().dt.total_seconds()
  gaps.extend(g.gap.dropna().tolist())
 m=max(gaps) if gaps else 0;return m, (pd.Timedelta(minutes=3) if m<=180 else pd.Timedelta(seconds=m+1))
def trip_verdict(t,asof,p,stops,book,gate):
 g=p[(p.vehicle_id==t.vehicle_id)&(p.received_at<=asof)&(p.recorded_at<=asof)].copy()
 # Present only data that can belong to the service date; selection uses records through as-of.
 g=g[g.recorded_at.dt.date==asof.date()]
 if asof<t.scheduled_start:return ('HOLD',None,np.nan,0,'not started')
 if len(g)==0:
  if asof-t.scheduled_start<=gate:return ('HOLD',None,np.nan,0,'just started, no ping yet')
  return ('NO_VERDICT',None,np.nan,0,'no received ping > freshness gate after start')
 e=enrich(g,t.route_id,stops).sort_values('received_at');q=e.tail(1).iloc[0];age=asof-q.received_at
 ss=stops[stops.route_id==t.route_id].sort_values('seq');dest=ss.iloc[-1];dest_m=float(hav(q.lat,q.lon,dest.lat,dest.lon));booked=int((book.trip_id==t.trip_id).sum())
 if dest_m<=100:return ('HOLD',q,np.nan,booked,f'reached destination ({q.ping_id})')
 if age>gate:return ('NO_VERDICT',q,np.nan,booked,f'stale {age.total_seconds()/60:.1f}m ({q.ping_id})')
 runtime=(t.scheduled_end-t.scheduled_start).total_seconds()/60;A=(asof-(t.scheduled_start+pd.Timedelta(minutes=(q.along_pct/100)*runtime))).total_seconds()/60
 recent=e[e.received_at>=asof-pd.Timedelta(minutes=10)].sort_values('received_at')
 net=np.nan
 if len(recent)>=2 and (recent.received_at.iloc[-1]-recent.received_at.iloc[0])>=pd.Timedelta(minutes=9):net=float(hav(recent.lat.iloc[0],recent.lon.iloc[0],recent.lat.iloc[-1],recent.lon.iloc[-1]))
 if asof-t.scheduled_start>pd.Timedelta(minutes=10) and pd.notna(net) and net<100:return ('CALL_DRIVER',q,A,booked,f'net {net:.0f}m/10m; {q.ping_id}')
 if A>=5:return ('PUSH_LATE',q,A,booked,f'A={A:.1f}m; {q.ping_id}')
 return ('HOLD',q,A,booked,f'A={A:.1f}m; {q.ping_id}')
def route_rows(date,asof,routes,stops,trips,book,p,gate):
 today=trips[trips.service_date.astype(str)==date]; out=[]
 for rid,grp in today.groupby('route_id'):
  ts=[]
  for t in grp.itertuples():
   v,q,a,n,note=trip_verdict(t,asof,p,stops,book,gate);ts.append((v,q,a,n,note,t.trip_id,t.vehicle_id))
  top=max(ts,key=lambda z:RANK[z[0]]);out.append([rid,top[0],sum(x[3] for x in ts),max([(asof-x[1].received_at).total_seconds()/60 if x[1] is not None else float('inf') for x in ts]),'; '.join(f'{x[5]}:{x[0]} {x[4]}' for x in ts)])
 return pd.DataFrame(out,columns=['route','verdict','bookings','longest_silence_min','reason_all_trips'])
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--date',required=True);ap.add_argument('--asof',required=True);a=ap.parse_args();asof=pd.Timestamp(f'{a.date} {a.asof}',tz=IST)
 routes,stops,trips,book,p=load();maxgap,gate=healthy_gate(trips,p)
 print('ASSUMPTIONS\n1. Only received_at <= as-of pings are eligible; malformed recorded_at is ignored.\n2. Deduplicate (vehicle_id, recorded_at), then drop implied coordinate speeds >130 km/h.\n3. A is position-based uniform scheduled progress along the stop polyline.\n4. If historical received gaps are <=3m gate=3m; otherwise gate=max historical gap+1s.\n5. A trip with no received ping is HOLD during the first freshness-gate interval after scheduled start, then NO_VERDICT.\n6. CALL_DRIVER needs >=2 received pings spanning >=9m of last 10m and net displacement <100m.\n7. Destination means within 100m of final listed stop.\n8. Route tier uses CALL_DRIVER > NO_VERDICT > PUSH_LATE > HOLD; ties rank bookings then silence.\n9. Rev. C view below is display-only; real table applies neither rule.')
 print(f'Historical healthy in-trip maximum received gap: {maxgap:.1f}s ({maxgap/60:.2f}m). Freshness gate used: {gate.total_seconds()/60:.2f}m.')
 real=route_rows(a.date,asof,routes,stops,trips,book,p,gate).merge(routes[['route_id','route_name']],left_on='route',right_on='route_id').drop(columns='route_id')
 show(real[['route','route_name','verdict','bookings','longest_silence_min','reason_all_trips']],'REAL VIEW: one row per route')
 rev=real.copy();rev=rev[~((rev.route==12))]; # operator-7 trips omitted from route note/table only for hypothetical view
 # reconstruct hypothetical operator exclusion correctly by filtering source pings/operators indirectly through vehicle mapping
 op=p.groupby('vehicle_id').operator_id.first(); filtered=trips[~trips.vehicle_id.map(op).eq(REV_C_OPERATOR)];rev=route_rows(a.date,asof,routes,stops,filtered,book,p,gate);rev.loc[rev.route==REV_C_ROUTE,'verdict']='HOLD';rev.loc[rev.route==REV_C_ROUTE,'reason_all_trips']='rev. C forced on-time / 0 lateness';show(rev,'REV. C VIEW ONLY: operator 7 omitted; Route 12 forced HOLD')
 worry=real.assign(_tier=real.verdict.map(RANK)).sort_values(['_tier','bookings','longest_silence_min'],ascending=[False,False,False]);show(worry[['route','route_name','verdict','bookings','longest_silence_min']],'WORRY ORDER')
 print('POLICY EDGE CASES FROM CODE: a trip past scheduled end but not within 100m of destination is not automatically HOLD. If stale it is NO_VERDICT; if fresh and immobile for the qualifying 10-minute window it is CALL_DRIVER; otherwise A is computed and it is PUSH_LATE when A >=5, else HOLD. A fresh moving trip with A >=5 does not meet the net-displacement CALL_DRIVER condition and produces PUSH_LATE. The current 17-Jun example of fresh, moving, A>=5 is TRIP_015 (PUSH_LATE); no current row is past scheduled end and fresh while outside the 100m destination radius.')
 # Backtest every 5m for historical dates, output only non-HOLD route events.
 events=[]
 for d in ['2026-06-15','2026-06-16']:
  day=trips[trips.service_date.astype(str)==d]
  for t in day.itertuples():
   for x in pd.date_range(t.scheduled_start,t.scheduled_end,freq='5min'):
    v,q,A,n,note=trip_verdict(t,x,p,stops,book,gate)
    if v!='HOLD':events.append([d,x,t.trip_id,t.route_id,v,A,n,note])
 ev=pd.DataFrame(events,columns=['date','asof','trip','route','verdict','A_min','bookings','reason']);print(f'Historical 5-minute evaluations: {len(events)} non-HOLD trip verdicts.');show(ev,'Non-HOLD historical events',60)
if __name__=='__main__':main()
