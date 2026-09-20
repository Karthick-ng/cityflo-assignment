"""Direction-aware descriptive check for Route 11 / V-06."""
from pathlib import Path
import sys, numpy as np, pandas as pd
if hasattr(sys.stdout,'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
R=Path(__file__).resolve().parent; IST='Asia/Kolkata'; ASOF=pd.Timestamp('2026-06-17 07:45',tz=IST); NEAR=100.; SLOW=1.
def show(x,t,n=40):
 print('\n'+t);print('  None' if len(x)==0 else x.head(n).to_string(index=False))
def parse(x,c):
 for z in c:x[z]=pd.to_datetime(x[z],format='%Y-%m-%d %H:%M:%S%z',errors='coerce',utc=True).dt.tz_convert(IST)
 return x
def hav(a,b,c,d):
 a,b,c,d=map(np.radians,[a,b,c,d]);q=np.sin((c-a)/2)**2+np.cos(a)*np.cos(c)*np.sin((d-b)/2)**2
 return 6371000*2*np.arctan2(np.sqrt(q),np.sqrt(1-q))
def enrich(g,rid,stops,direction):
 s=stops[stops.route_id==rid].sort_values('seq');lat0=np.radians(s.lat.mean());x=(s.lon.to_numpy()-s.lon.iloc[0])*111320*np.cos(lat0);y=(s.lat.to_numpy()-s.lat.iloc[0])*111320;sg=np.hypot(np.diff(x),np.diff(y));cu=np.r_[0,np.cumsum(sg)];o=[];n=[]
 for q in g.itertuples():
  px=(q.lon-s.lon.iloc[0])*111320*np.cos(lat0);py=(q.lat-s.lat.iloc[0])*111320;best=(1e99,0)
  for i,L in enumerate(sg):
   vx,vy=x[i+1]-x[i],y[i+1]-y[i];u=0 if L==0 else np.clip(((px-x[i])*vx+(py-y[i])*vy)/L**2,0,1);d=np.hypot(px-x[i]-u*vx,py-y[i]-u*vy)
   if d<best[0]:best=(d,cu[i]+u*L)
  ds=hav(q.lat,q.lon,s.lat.to_numpy(),s.lon.to_numpy());j=np.argmin(ds);o.append(best);n.append((s.iloc[j].stop_name,s.iloc[j].stop_id,ds[j]))
 z=g.copy();z[['offset_m','along_m']]=o;z['route_m']=cu[-1];z['polyline_origin_pct']=100*z.along_m/z.route_m;z['travel_direction_pct']=np.where(direction=='outbound',100-z.polyline_origin_pct,z.polyline_origin_pct);z[['near_stop','near_stop_id','near_stop_m']]=n;return z
def tp(t,p):return p[(p.vehicle_id==t.vehicle_id)&(p.recorded_at>=t.scheduled_start)&(p.recorded_at<=t.scheduled_end)].copy()
def main():
 tr=parse(pd.read_csv(R/'data/trips.csv'),['scheduled_start','scheduled_end']);p=parse(pd.read_csv(R/'data/gps_pings.csv'),['recorded_at','received_at']);s=pd.read_csv(R/'data/stops.csv')
 print('ASSUMPTIONS\n1. Timestamps are explicit IST values.\n2. Trip pings share vehicle_id and have recorded_at within exact scheduled bounds.\n3. Direction-aware fraction uses origin-to-destination geometry for inbound, and 100 minus it for outbound.\n4. Near terminus means <=100m from first or last listed stop; slow/stationary means speed <=1 km/h.\n5. Five-minute samples select the last recorded ping in each 5-minute bucket; no interpolation.\n6. No reconciliation rule, exclusion, lateness metric, or operational verdict is applied.')
 print('\n1. DIRECTION VALUES')
 show(tr[['trip_id','route_id','vehicle_id','service_date','direction','scheduled_start','scheduled_end']],'All trips and direction',30)
 print('All 19 rows are inbound. Therefore all previous polyline fractions already run in the stated direction of travel; no recomputation changes a value. If any row were outbound, its direction-of-travel fraction would be 100 - origin-based fraction.')
 print('\n2. V-06 / TRIP_014')
 t=tr[tr.trip_id=='TRIP_014'].iloc[0];g=enrich(tp(t,p),11,s,t.direction).sort_values('recorded_at');h=g[g.recorded_at<=ASOF].copy();h['bucket']=h.recorded_at.dt.floor('5min');sample=h.groupby('bucket').tail(1)
 show(sample[['ping_id','recorded_at','received_at','speed_kmph','polyline_origin_pct','travel_direction_pct','near_stop','near_stop_id','near_stop_m']], 'V-06: 5-minute samples from scheduled start through 07:45',30)
 now=h.tail(1).iloc[0];print(f"Last pre-07:45: {now.ping_id}, {now.recorded_at}, {now.speed_kmph} km/h, {now.travel_direction_pct:.1f}% direction-aware, nearest {now.near_stop} {now.near_stop_m:.1f}m.")
 # first entry into 100m region around current nearest stop, and contiguous <=1 km/h tail
 same=h[(h.near_stop_id==now.near_stop_id)&(h.near_stop_m<=NEAR)];print(f"First observed within 100m of current nearest stop ({now.near_stop}): {same.recorded_at.min()} ({same.ping_id.iloc[0]}), {len(same)} qualifying pings.")
 slow=h[h.speed_kmph<=SLOW];
 # suffix only
 tail=0
 for v in h.speed_kmph.iloc[::-1]:
  if v<=SLOW:tail+=1
  else:break
 if tail: z=h.tail(tail);print(f"Contiguous <=1 km/h tail: {tail} pings, {z.recorded_at.iloc[0]} to {z.recorded_at.iloc[-1]}, {(z.recorded_at.iloc[-1]-z.recorded_at.iloc[0]).total_seconds()/60:.1f} minutes.")
 else: print('No contiguous <=1 km/h tail at 07:45.')
 print('\n3. ROUTE 11 COMPARISON')
 rows=[]
 for tid in ['TRIP_002','TRIP_008','TRIP_014']:
  q=tr[tr.trip_id==tid].iloc[0];x=enrich(tp(q,p),11,s,q.direction).sort_values('recorded_at');first=x.iloc[0];rows.append([tid,str(q.service_date),q.direction,q.scheduled_start,q.scheduled_end,first.ping_id,first.recorded_at,round(first.travel_direction_pct,1),first.near_stop,round(first.near_stop_m,1)])
 show(pd.DataFrame(rows,columns=['trip','date','direction','start','end','first_ping','first_ping_time','direction_pct','nearest_stop','distance_m']),'Route 11 trip starts',10)
 print('\n4. EARLIER-CODE DIRECTION AUDIT')
 print('profile.py: polyline-distance proximity, route length, stop counts, and far-from-route checks do not require direction. Its displayed progress only appears in later scripts, not profile.py.')
 print('drill.py: V-04/V-05 samples, Route 12 progress, and 07:45 route fractions used origin-based polyline percentage without consulting direction.')
 print('drill2.py: fixed-clock polyline percentages, V-05/Route 12 comparisons, raw 07:45 table, Route 21 positions, and endpoint labels used origin-based percentage without consulting direction.')
 print('For this extract all directions are inbound, so those output values are unaffected. An outbound row would require reversing percentage to 100 - origin-based percentage and swapping origin/destination endpoint interpretation.')
 print('\n5. OTHER TERMINUS / MID-TRIP PATTERN SCREEN')
 found=[]
 for q in tr.itertuples():
  x=enrich(tp(q,p),q.route_id,s,q.direction); mid=x[(x.recorded_at>q.scheduled_start+pd.Timedelta(minutes=5))&(x.recorded_at<q.scheduled_end-pd.Timedelta(minutes=5))]; ss=s[s.route_id==q.route_id].sort_values('seq');term={ss.iloc[0].stop_id,ss.iloc[-1].stop_id};z=mid[(mid.near_stop_id.isin(term))&(mid.near_stop_m<=NEAR)&(mid.speed_kmph<=SLOW)]
  if len(z):found.append([q.trip_id,q.route_id,z.ping_id.iloc[0],z.recorded_at.iloc[0],z.near_stop.iloc[0],z.speed_kmph.iloc[0]])
 show(pd.DataFrame(found,columns=['trip','route','ping','recorded_at','terminus','speed_kmph']),'Mid-schedule slow/stationary pings within 100m of a terminus',30)
 print('\nEND: descriptive direction check only.')
if __name__=='__main__':main()
