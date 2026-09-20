"""Second descriptive GPS drill-down; no lateness metric or reconciliation rules."""
from pathlib import Path
import sys, numpy as np, pandas as pd
if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
ROOT=Path(__file__).resolve().parent; IST='Asia/Kolkata'; ASOF=pd.Timestamp('2026-06-17 07:45:00',tz=IST)
NEAR=100.; MOVING=1.
def show(x,title,n=30):
 print('\n'+title); print('  None' if x is None or len(x)==0 else x.head(n).to_string(index=False));
 if x is not None and len(x)>n: print(f'  ... {len(x)-n} more rows suppressed')
def parse(x,cs):
 for c in cs:x[c]=pd.to_datetime(x[c],format='%Y-%m-%d %H:%M:%S%z',errors='coerce',utc=True).dt.tz_convert(IST)
 return x
def hav(a,b,c,d):
 a,b,c,d=map(np.radians,[a,b,c,d]); z=np.sin((c-a)/2)**2+np.cos(a)*np.cos(c)*np.sin((d-b)/2)**2
 return 6371000*2*np.arctan2(np.sqrt(z),np.sqrt(1-z))
def enrich(g,rid,stops):
 s=stops[stops.route_id==rid].sort_values('seq'); lat0=np.radians(s.lat.mean()); x=(s.lon.to_numpy()-s.lon.iloc[0])*111320*np.cos(lat0); y=(s.lat.to_numpy()-s.lat.iloc[0])*111320; seg=np.hypot(np.diff(x),np.diff(y)); cum=np.r_[0,np.cumsum(seg)]
 out=g.copy(); vals=[]; near=[]
 for q in out.itertuples():
  px=(q.lon-s.lon.iloc[0])*111320*np.cos(lat0);py=(q.lat-s.lat.iloc[0])*111320; best=(1e99,0.)
  for i,L in enumerate(seg):
   vx,vy=x[i+1]-x[i],y[i+1]-y[i];t=0 if L==0 else np.clip(((px-x[i])*vx+(py-y[i])*vy)/L**2,0,1);d=np.hypot(px-x[i]-t*vx,py-y[i]-t*vy)
   if d<best[0]:best=(d,cum[i]+t*L)
  ds=hav(q.lat,q.lon,s.lat.to_numpy(),s.lon.to_numpy());j=int(np.argmin(ds)); vals.append(best);near.append((s.iloc[j].stop_id,s.iloc[j].stop_name,float(ds[j])))
 out[['offset_m','along_m']]=vals;out['route_m']=cum[-1];out['along_pct']=100*out.along_m/out.route_m;out[['near_stop_id','near_stop','near_stop_m']]=near
 return out
def tp(t,p):return p[(p.vehicle_id==t.vehicle_id)&(p.recorded_at>=t.scheduled_start)&(p.recorded_at<=t.scheduled_end)].copy()
def at(t,cut,p,stops):
 g=enrich(tp(t,p),t.route_id,stops); q=g[(g.recorded_at<=cut)&(g.received_at<=cut)].sort_values('received_at').tail(1)
 elapsed=100*(cut-t.scheduled_start).total_seconds()/(t.scheduled_end-t.scheduled_start).total_seconds()
 return q,elapsed
def main():
 routes=pd.read_csv(ROOT/'data/routes.csv');stops=pd.read_csv(ROOT/'data/stops.csv');trips=parse(pd.read_csv(ROOT/'data/trips.csv'),['scheduled_start','scheduled_end']);book=parse(pd.read_csv(ROOT/'data/bookings.csv'),['booked_at','promised_eta']);p=parse(pd.read_csv(ROOT/'data/gps_pings.csv'),['recorded_at','received_at']);p['lag_s']=(p.received_at-p.recorded_at).dt.total_seconds();op=p.groupby('vehicle_id').operator_id.first()
 print('ASSUMPTIONS\n1. Timestamps are parsed as explicit IST offsets.\n2. A trip ping uses same vehicle plus recorded_at inside exact scheduled start/end.\n3. Near stop/origin/destination means <=100m; moving means speed >1 km/h.\n4. GPS progress is a projection onto the ordered stop polyline using a local planar approximation.\n5. Scheduled-time fraction assumes uniform progress from 0% at start to 100% at end, including no explicit dwell allocation.\n6. Fixed-clock comparisons use 07:45 IST and last ping received by that time unless noted.\n7. Stop arrival is first ping within 100m of that stop, not proof of a physical stop.\n8. No row is excluded, corrected, or used to calculate lateness.')
 print('\n1. POLYLINE FRACTION VS SCHEDULED-TIME FRACTION')
 print('Polyline fraction is GPS location projected onto stop geometry / polyline length. Scheduled-time fraction is (time - scheduled_start) / (scheduled_end - scheduled_start). The latter is a straight-line-in-time assumption: at 50% of scheduled time, the bus is assumed 50% along the polyline. It has no dwell-time information.')
 fixed=[]
 for t in trips[trips.service_date.astype(str).isin(['2026-06-15','2026-06-16'])].itertuples():
  cut=pd.Timestamp(f'{t.service_date} 07:45:00',tz=IST);q,e=at(t,cut,p,stops)
  if len(q):fixed.append([t.trip_id,str(t.service_date),t.route_id,round(e,1),q.ping_id.iloc[0],round(q.along_pct.iloc[0],1),round(q.along_pct.iloc[0]-e,1)])
 d=pd.DataFrame(fixed,columns=['trip_id','date','route_id','scheduled_time_pct','last_ping','polyline_pct','polyline_minus_time_pp']);show(d,'15/16 June: fixed-clock 07:45 comparison',30);show(d.polyline_minus_time_pp.abs().describe().to_frame('absolute_percentage_points'),'Absolute gap summary')
 print('\n2. ROUTE 12 / V-10')
 v10=p[(p.vehicle_id=='V-10')&(p.recorded_at.dt.date==ASOF.date())].sort_values('recorded_at');show(v10[v10.recorded_at<pd.Timestamp('2026-06-17 07:15',tz=IST)][['ping_id','recorded_at','received_at','speed_kmph']],'All V-10 pings before 07:15 on 17 June')
 pre=[]
 for t in trips[trips.service_date.astype(str)=='2026-06-17'].itertuples():
  g=p[(p.vehicle_id==t.vehicle_id)&(p.recorded_at.dt.date==ASOF.date())& (p.recorded_at<t.scheduled_start)]
  pre.append([t.trip_id,t.vehicle_id,t.route_id,len(g),g.ping_id.iloc[0] if len(g) else None,g.recorded_at.min() if len(g) else pd.NaT])
 show(pd.DataFrame(pre,columns=['trip_id','vehicle','route','prestart_ping_count','first_prestart_id','first_prestart_recorded']),'17 June pre-scheduled-start pings by vehicle')
 r12=trips[trips.route_id==12].sort_values('service_date'); arrivals=[]
 for t in r12.itertuples():
  g=enrich(tp(t,p),12,stops).sort_values('recorded_at')
  for s in stops[stops.route_id==12].sort_values('seq').itertuples():
   q=g[(g.near_stop_id==s.stop_id)&(g.near_stop_m<=NEAR)].head(1);arrivals.append([s.seq,s.stop_id,s.stop_name,str(t.service_date),q.ping_id.iloc[0] if len(q) else None,q.recorded_at.iloc[0] if len(q) else pd.NaT])
 show(pd.DataFrame(arrivals,columns=['seq','stop_id','stop_name','date','first_near_ping','recorded_at']).pivot(index=['seq','stop_id','stop_name'],columns='date',values='recorded_at').reset_index(),'Route 12 first observed near-stop time by date',20)
 print('No pre-07:15 V-10 ping cannot by itself distinguish a later vehicle departure from a device/reporting start at 07:15; the CSV contains no independent engine/dispatch event.')
 print('\n3. V-05 / TRIP_017')
 v05=p[p.vehicle_id=='V-05'].sort_values('recorded_at');last=v05[v05.recorded_at<=pd.Timestamp('2026-06-17 07:27:42',tz=IST)].tail(10);t17=trips[trips.trip_id=='TRIP_017'].iloc[0];show(enrich(last,17,stops)[['ping_id','recorded_at','received_at','speed_kmph','along_pct','near_stop']],'Last 10 V-05 pings before 07:27:42',10)
 laterrec=p[(p.vehicle_id=='V-05')&(p.recorded_at>pd.Timestamp('2026-06-17 07:27:42',tz=IST))];laterrecv=p[(p.vehicle_id=='V-05')&(p.received_at>pd.Timestamp('2026-06-17 07:27:42',tz=IST))];print(f'V-05 later rows anywhere in file: recorded_at later {len(laterrec)}, received_at later {len(laterrecv)}.')
 target=enrich(v05[v05.recorded_at<=pd.Timestamp('2026-06-17 07:27:42',tz=IST)].tail(1),17,stops).along_pct.iloc[0];t05=trips[trips.trip_id=='TRIP_005'].iloc[0];g05=enrich(tp(t05,p),17,stops).sort_values('recorded_at');cross=g05[g05.along_pct>=target].head(1);show(cross[['ping_id','recorded_at','speed_kmph','along_pct','near_stop']],'TRIP_005 first observed ping at/after V-05 target progress',5)
 print('\n4. ALL 17-JUNE TRIPS AT 07:45')
 rows=[]
 for t in trips[trips.service_date.astype(str)=='2026-06-17'].sort_values('trip_id').itertuples():
  q,e=at(t,ASOF,p,stops);status='not started' if ASOF<t.scheduled_start else ('running' if ASOF<t.scheduled_end else 'scheduled end already passed')
  rows.append([t.trip_id,t.route_id,t.vehicle_id,op[t.vehicle_id],t.scheduled_start,t.scheduled_end,status,q.ping_id.iloc[0] if len(q) else None,round((ASOF-q.received_at.iloc[0]).total_seconds()/60,1) if len(q) else np.nan,round(q.along_pct.iloc[0],1) if len(q) else np.nan,round(e,1),round(q.speed_kmph.iloc[0],1) if len(q) else np.nan])
 show(pd.DataFrame(rows,columns=['trip_id','route','vehicle','operator','scheduled_start','scheduled_end','status','last_received_ping','received_age_min','polyline_pct','scheduled_time_pct','speed_kmph']),'Raw 07:45 table',20)
 print('\n5. ROUTE 21 PAIR')
 pair=[]
 for tid in ['TRIP_018','TRIP_019']:
  t=trips[trips.trip_id==tid].iloc[0];q,e=at(t,ASOF,p,stops);r=q.iloc[0];pair.append([tid,t.vehicle_id,op[t.vehicle_id],t.scheduled_start,t.scheduled_end,book[book.trip_id==tid].shape[0],r.ping_id,r.recorded_at,r.received_at,round(r.lat,6),round(r.lon,6),round(r.along_pct,1),round(r.speed_kmph,1)])
 pair=pd.DataFrame(pair,columns=['trip','vehicle','operator','start','end','bookings','ping','recorded','received','lat','lon','along_pct','speed']);show(pair,'Route 21 at 07:45',10);print(f"Straight-line separation of these two selected 07:45 positions: {hav(pair.lat.iloc[0],pair.lon.iloc[0],pair.lat.iloc[1],pair.lon.iloc[1]):.1f}m. They have distinct vehicle IDs and distinct ping IDs; the CSV alone does not establish whether one operationally shadows the other.")
 print('\n6. SMALL ITEMS')
 show(p[p.ping_id=='P-0003265'][['ping_id','vehicle_id','recorded_at','received_at','lag_s']],'P-0003265')
 du=p[(p.ping_id.isin(['P-0002821','P-0003248'])) | p.duplicated(['vehicle_id','recorded_at'],keep=False)].sort_values(['vehicle_id','recorded_at','ping_id']);details=[]
 for r in du.itertuples():
  x=trips[(trips.vehicle_id==r.vehicle_id)&(trips.scheduled_start<=r.recorded_at)&(trips.scheduled_end>=r.recorded_at)];details.append([r.ping_id,r.vehicle_id,r.recorded_at,r.lat,r.lon,r.speed_kmph,x.trip_id.iloc[0] if len(x) else None,x.route_id.iloc[0] if len(x) else None])
 show(pd.DataFrame(details,columns=['ping_id','vehicle','recorded_at','lat','lon','speed','trip','route']),'Duplicate-ID/time rows and their trip memberships',20)
 # same ETA expectation as profile.py
 ex=[]
 for t in trips.itertuples():
  s=stops[stops.route_id==t.route_id].sort_values('seq');seg=np.r_[0,hav(s.lat.to_numpy()[:-1],s.lon.to_numpy()[:-1],s.lat.to_numpy()[1:],s.lon.to_numpy()[1:])];f=np.cumsum(seg)/sum(seg)
  ex += [[t.trip_id,z.stop_id,t.scheduled_start+(t.scheduled_end-t.scheduled_start)*ff] for z,ff in zip(s.itertuples(),f)]
 eta=book.merge(pd.DataFrame(ex,columns=['trip_id','boarding_stop_id','expected']),on=['trip_id','boarding_stop_id']).merge(trips[['trip_id','route_id']],on='trip_id');bad=eta[(eta.promised_eta-eta.expected).dt.total_seconds().abs()>60];show(bad.groupby(['trip_id','route_id']).agg(bookings=('booking_id',lambda x:', '.join(x)),count=('booking_id','count')).reset_index(),'All promised_eta mismatches by trip and route',20)
 missing=['TRIP_001','TRIP_003','TRIP_004','TRIP_006','TRIP_007','TRIP_009','TRIP_011'];why=[]
 for tid in missing:
  t=trips[trips.trip_id==tid].iloc[0];g=enrich(tp(t,p),t.route_id,stops).sort_values('recorded_at');s=stops[stops.route_id==t.route_id].sort_values('seq');origin=s.iloc[0].stop_id;dest=s.iloc[-1].stop_id;why.append([tid,t.route_id,g.ping_id.iloc[0],g.recorded_at.iloc[0],round(g[g.near_stop_id==origin].near_stop_m.min(),1) if any(g.near_stop_id==origin) else np.nan,g.ping_id.iloc[-1],g.recorded_at.iloc[-1],round(g[g.near_stop_id==dest].near_stop_m.min(),1) if any(g.near_stop_id==dest) else np.nan])
 show(pd.DataFrame(why,columns=['trip','route','first_ping','first_time','closest_origin_m','last_ping','last_time','closest_dest_m']),'Why seven trips miss the <=100m endpoint observation rule',20)
 print('\nEND: descriptive output only.')
if __name__=='__main__':main()
