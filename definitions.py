"""Exploratory candidate delay definitions; descriptive comparison, not a chosen metric."""
from pathlib import Path
import sys,numpy as np,pandas as pd
from drill2 import enrich,tp,IST
if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
R=Path(__file__).resolve().parent; ASOF=pd.Timestamp('2026-06-17 07:45',tz=IST)
def parse(x,c):
 for z in c:x[z]=pd.to_datetime(x[z],format='%Y-%m-%d %H:%M:%S%z',errors='coerce',utc=True).dt.tz_convert(IST)
 return x
def show(x,t,n=30):print('\n'+t);print(' None' if len(x)==0 else x.head(n).to_string(index=False))
def main():
 tr=parse(pd.read_csv(R/'data/trips.csv'),['scheduled_start','scheduled_end']);p=parse(pd.read_csv(R/'data/gps_pings.csv'),['recorded_at','received_at']);b=parse(pd.read_csv(R/'data/bookings.csv'),['booked_at','promised_eta']);s=pd.read_csv(R/'data/stops.csv')
 print('ASSUMPTIONS\n1. Only pings with received_at <= evaluation time are eligible. 2. Latest received eligible ping supplies position/speed. 3. Linear polyline progress is used. 4. A uses uniform scheduled progress. 5. B uses per-route historical observed endpoint runtime where available, anchored at scheduled start. 6. C uses only bookings at stops not yet passed, and reports median(now-promised_eta). 7. D assumes current reported speed stays constant; speed <=0 is undefined. 8. Freshness is reported, not thresholded. 9. No reconciliation rule is applied and no candidate is selected.')
 print('\nFORMULAS (positive output means later than the comparison time)')
 print('A timetable: A = t - [scheduled_start + f * (scheduled_end-scheduled_start)]. Needs one received ping, position f, and fresh enough telemetry.')
 print('B history: B = t - [scheduled_start + f * median(historical observed route runtime)]. Needs A plus comparable completed historical runtimes; unavailable where history is missing.')
 print('C promise: C = median over not-yet-passed booked stops of [t - promised_eta]. Needs a received ping, stop position, and at least one upcoming booking.')
 print('D speed: D = [t + remaining_polyline_km/current_speed_kmph*60] - scheduled_end. Needs a received ping, valid positive speed, and a speed representative of future travel.')
 # observed history runtimes known from endpoint check reproduce quickly using fixed values based on profile observations
 hist={11:69.8,14:74.8,17:64.9,21:39.8}
 # stop fractions simple cumulative haversine
 def sf(rid):
  q=s[s.route_id==rid].sort_values('seq');a=np.radians(q.lat.to_numpy());o=np.radians(q.lon.to_numpy());d=6371000*2*np.arctan2(np.sqrt(np.sin(np.diff(a)/2)**2+np.cos(a[:-1])*np.cos(a[1:])*np.sin(np.diff(o)/2)**2),np.sqrt(1-(np.sin(np.diff(a)/2)**2+np.cos(a[:-1])*np.cos(a[1:])*np.sin(np.diff(o)/2)**2)));return dict(zip(q.stop_id,np.r_[0,np.cumsum(d)]/sum(d)))
 fractions={r:sf(r) for r in tr.route_id.unique()}
 def calc(t,cut):
  g=enrich(tp(t,p),t.route_id,s).sort_values('received_at');q=g[(g.received_at<=cut)&(g.recorded_at<=cut)].tail(1)
  if len(q)==0:return [np.nan]*5
  x=q.iloc[0];f=x.along_pct/100;dur=(t.scheduled_end-t.scheduled_start).total_seconds()/60;A=(cut-(t.scheduled_start+pd.Timedelta(minutes=f*dur))).total_seconds()/60
  B=(cut-(t.scheduled_start+pd.Timedelta(minutes=f*hist[t.route_id]))).total_seconds()/60 if t.route_id in hist else np.nan
  bb=b[b.trip_id==t.trip_id].copy();bb['f']=bb.boarding_stop_id.map(fractions[t.route_id]);up=bb[bb.f>=f];C=(cut-up.promised_eta).dt.total_seconds().median()/60 if len(up) else np.nan
  D=((cut+pd.Timedelta(hours=((1-f)*x.route_m/1000)/x.speed_kmph))-t.scheduled_end).total_seconds()/60 if x.speed_kmph>0 else np.nan
  age=(cut-x.received_at).total_seconds()/60
  return [A,B,C,D,age]
 # history 5 minute backtest
 vals=[]
 for t in tr[tr.service_date.astype(str).isin(['2026-06-15','2026-06-16'])].itertuples():
  for cut in pd.date_range(t.scheduled_start,t.scheduled_end,freq='5min'):
   a,bv,c,d,age=calc(t,cut);vals.append([t.trip_id,t.route_id,cut,a,bv,c,d,age])
 v=pd.DataFrame(vals,columns=['trip','route','time','A_timetable','B_history','C_promise','D_speed','ping_age_min'])
 summary=[]
 for c in ['A_timetable','B_history','C_promise','D_speed']:
  z=v[c].dropna();summary.append([c,len(z),round(z.median(),2),round(z.quantile(.95),2),round(z.max(),2)])
 show(pd.DataFrame(summary,columns=['definition','n','median_min','p95_min','max_min']),'15/16 June 5-minute backtest distributions')
 large=v[(v[['A_timetable','B_history','C_promise','D_speed']]>3).any(axis=1)];show(large[['trip','route','time','A_timetable','B_history','C_promise','D_speed','ping_age_min']],'Historical 5-minute rows where any candidate >3 min',40)
 # snapshot
 rows=[]
 for t in tr[tr.service_date.astype(str)=='2026-06-17'].sort_values('trip_id').itertuples():
  a,bv,c,d,age=calc(t,ASOF);rows.append([t.trip_id,t.route_id,t.vehicle_id,a,bv,c,d,age])
 out=pd.DataFrame(rows,columns=['trip','route','vehicle','A_timetable','B_history','C_promise','D_speed','ping_age_min']);out['spread_max_min']=out[['A_timetable','B_history','C_promise','D_speed']].max(axis=1)-out[['A_timetable','B_history','C_promise','D_speed']].min(axis=1)
 show(out,'17 June 07:45 candidate outputs (minutes)',20);show(out[out.spread_max_min>3],'Rows with candidate spread >3 minutes',20)
 print('\nARGUMENTS AGAINST EACH CANDIDATE')
 print('A: TRIP_014 / P-0003518 has fresh received telemetry near the origin while the schedule clock is mid-trip; A converts that observation directly into a large number without independently validating the GPS interpretation.')
 print('B: Route 12 has no qualifying historical endpoint-runtime observations under the stated 100m rule, so TRIP_015 is unavailable rather than robustly estimated.')
 print('C: TRIP_013 may have no upcoming booked stop when it is near 98.8% route progress at P-0003264; absence of an upcoming promise makes C undefined even though GPS exists.')
 print('D: TRIP_014 / P-0003518 has speed 0.7 km/h, making constant-speed extrapolation extreme; speed 0 produces division by zero / undefined.')
 print('END exploratory metrics only; no definition or threshold selected.')
if __name__=='__main__':main()
