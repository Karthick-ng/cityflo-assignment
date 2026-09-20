from pathlib import Path
import sys,numpy as np,pandas as pd
if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
R=Path(__file__).resolve().parent; IST='Asia/Kolkata'; NEAR=100
def parse(x,c):
 for z in c:x[z]=pd.to_datetime(x[z],format='%Y-%m-%d %H:%M:%S%z',errors='coerce',utc=True).dt.tz_convert(IST)
 return x
def h(a,b,c,d):
 a,b,c,d=map(np.radians,[a,b,c,d]);q=np.sin((c-a)/2)**2+np.cos(a)*np.cos(c)*np.sin((d-b)/2)**2;return 6371000*2*np.arctan2(np.sqrt(q),np.sqrt(1-q))
def show(x,t,n=50):print('\n'+t);print(' None' if len(x)==0 else x.head(n).to_string(index=False))
def main():
 tr=parse(pd.read_csv(R/'data/trips.csv'),['scheduled_start','scheduled_end']);b=parse(pd.read_csv(R/'data/bookings.csv'),['booked_at','promised_eta']);p=parse(pd.read_csv(R/'data/gps_pings.csv'),['recorded_at','received_at']);s=pd.read_csv(R/'data/stops.csv')
 print('ASSUMPTIONS\n1. IST timestamps. 2. A trip ping is same vehicle, recorded within exact schedule. 3. Near a stop is <=100m. 4. Moving departure is speed >5 km/h. 5. Net-displacement screen uses first/last GPS fixes in a 10-minute recorded-time window and <100m net displacement. 6. Window locations use the start ping nearest stop; no map matching. 7. No rows/rules are excluded.')
 t=tr[tr.trip_id=='TRIP_014'].iloc[0];x=b[b.trip_id=='TRIP_014'].merge(s[['stop_id','stop_name']],left_on='boarding_stop_id',right_on='stop_id');show(x[['booking_id','rider_id','boarding_stop_id','stop_name','promised_eta']],'1. TRIP_014 bookings')
 print('Promised ETAs are schedule-derived values in bookings.csv; they can be compared to scheduled stop interpolation but cannot independently confirm whether V-06 departed.')
 # net displacement all trip windows
 rows=[]
 for q in tr.itertuples():
  g=p[(p.vehicle_id==q.vehicle_id)&(p.recorded_at>=q.scheduled_start)&(p.recorded_at<=q.scheduled_end)].sort_values('recorded_at')
  for i,r in enumerate(g.itertuples()):
   z=g[g.recorded_at>=r.recorded_at+pd.Timedelta(minutes=10)].head(1)
   if len(z):
    e=z.iloc[0];d=h(r.lat,r.lon,e.lat,e.lon)
    if d<100:
     ss=s[s.route_id==q.route_id];ds=h(r.lat,r.lon,ss.lat.to_numpy(),ss.lon.to_numpy());j=np.argmin(ds);kind='terminus' if ss.iloc[j].seq in (ss.seq.min(),ss.seq.max()) else ('stop' if ds[j]<=NEAR else 'mid-route')
     rows.append([q.trip_id,q.route_id,q.vehicle_id,r.ping_id,e.ping_id,r.recorded_at,e.recorded_at,round(d,1),ss.iloc[j].stop_name,kind])
 # collapse overlapping windows, preserving first per 10min bin
 z=pd.DataFrame(rows,columns=['trip','route','vehicle','start_ping','end_ping','start','end','net_m','location','kind']);z['bucket']=z.start.dt.floor('10min');z=z.groupby(['trip','bucket']).first().reset_index();show(z,'2. All net displacement <100m over >=10 min windows',80)
 # origin departures and dwell
 dep=[]
 for q in tr.itertuples():
  g=p[(p.vehicle_id==q.vehicle_id)&(p.recorded_at>=q.scheduled_start)&(p.recorded_at<=q.scheduled_end)].sort_values('recorded_at');ss=s[s.route_id==q.route_id].sort_values('seq').iloc[0];d=h(g.lat,g.lon,ss.lat,ss.lon);move=g[(d<=NEAR)&(g.speed_kmph>5)].head(1)
  dep.append([q.trip_id,str(q.service_date),q.route_id,q.vehicle_id,q.scheduled_start,move.ping_id.iloc[0] if len(move) else None,move.recorded_at.iloc[0] if len(move) else pd.NaT,round((move.recorded_at.iloc[0]-q.scheduled_start).total_seconds()/60,1) if len(move) else np.nan])
 dep=pd.DataFrame(dep,columns=['trip','date','route','vehicle','schedule_start','first_gt5_ping','departure_ping_time','minutes_from_start']);show(dep[dep.trip.isin(['TRIP_002','TRIP_008','TRIP_014'])],'3. Route 11 first >5 km/h origin ping')
 hist=dep[dep.date.isin(['2026-06-15','2026-06-16'])].minutes_from_start.dropna();print(f'Historical first->moving origin offset: n={len(hist)}, median={hist.median():.1f} min, p95={hist.quantile(.95):.1f}, min={hist.min():.1f}, max={hist.max():.1f}.')
 # parked comparison summary: V06 vs all points near origin/any stop
 v=p[(p.vehicle_id=='V-06')&(p.recorded_at.dt.date==pd.Timestamp('2026-06-17').date())];origin=s[(s.route_id==11)&(s.seq==1)].iloc[0];dv=h(v.lat,v.lon,origin.lat,origin.lon);vv=v[dv<=NEAR]
 others=[]
 for q in tr.itertuples():
  g=p[(p.vehicle_id==q.vehicle_id)&(p.recorded_at>=q.scheduled_start)&(p.recorded_at<=q.scheduled_end)];ss=s[s.route_id==q.route_id];near=np.min(h(g.lat.to_numpy()[:,None],g.lon.to_numpy()[:,None],ss.lat.to_numpy(),ss.lon.to_numpy()),axis=1);others.extend(g.loc[near<=NEAR,'speed_kmph'].tolist())
 print(f'V-06 near Borivali 17 Jun: {len(vv)} pings; speed median={vv.speed_kmph.median():.1f}, p95={vv.speed_kmph.quantile(.95):.1f}, max={vv.speed_kmph.max():.1f}. All trip pings near any stop: n={len(others)}, median={np.median(others):.1f}, p95={np.quantile(others,.95):.1f}, max={np.max(others):.1f}.')
 print('END descriptive only.')
if __name__=='__main__':main()
