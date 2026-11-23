#!/usr/bin/env python3
"""Independent, read-only M-League points audit for Takai by stage and season."""
import sqlite3,sys,json,csv
from pathlib import Path
from collections import defaultdict
from decimal import Decimal
con=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True)
con.row_factory=sqlite3.Row
con.execute('PRAGMA query_only=ON')
assert con.execute('PRAGMA quick_check').fetchone()[0]=='ok'
def query(sql,args=()):return [dict(x) for x in con.execute(sql,args)]
meta=query("SELECT COUNT(*) games,MIN(date) first_date,MAX(date) last_date FROM game")[0]
assert meta['games']==2068 and meta['last_date']=='2026-11-20'
q="""
 SELECT p.name, ls.start_year year,ss.stage,g.id game_id,
        gr.rank,gr.score,gr.league_points,gr.penalty_league_points
 FROM game_player_result gr
 JOIN player p ON p.id=gr.player_id
 JOIN game g ON g.id=gr.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
 ORDER BY ls.start_year,ss.stage,g.id,p.name
"""
r=query(q)
assert len(r)==4*meta['games'],len(r)
assert {x['rank'] for x in r}=={1,2,3,4}
assert len({x['name'] for x in r})==56
assert sum(1 for x in r if x['name']=='多井隆晴')==282
def pack(rows):
 byp=defaultdict(list)
 for x in rows:byp[x['name']].append(x)
 arr=[]
 for name,rr in byp.items():
  n=len(rr)
  pts=sum(Decimal(str(x['league_points']))+Decimal(str(x['penalty_league_points'])) for x in rr)
  total=float(pts)
  avg=float(pts/Decimal(n))
  raw=sum(x['score']-25000 for x in rr)/1000 # relative raw score, assuming 25000 baseline
  d={'name':name,'games':n,'total_pt':round(total,1),'pt_per_game':round(avg,4),
     'rank1':sum(x['rank']==1 for x in rr),'avg_rank':round(sum(x['rank'] for x in rr)/n,4),
     'score_per_game':round(sum(x['score'] for x in rr)/n,2)}
  arr.append(d)
 arr.sort(key=lambda x:(-x['total_pt'],-x['pt_per_game'],x['name']))
 for i,x in enumerate(arr):x['rank_total_pt']=i+1
 byavg=sorted(arr,key=lambda x:(-x['pt_per_game'],-x['games'],x['name']))
 for i,x in enumerate(byavg):x['rank_pt_per_game']=i+1
 takai=next((x for x in arr if x['name']=='多井隆晴'),None)
 total_pt=sum(x['total_pt'] for x in arr)
 return {'games':len(rows)//4,'league_games_per_player':len(rows),
         'league_total_pt':round(total_pt,1),'players_count':len(arr),
         'takai':takai,'players':arr}
allx=pack(r)
years=sorted({x['year'] for x in r})
annual={str(y):pack([x for x in r if x['year']==y]) for y in years}
stages={st:pack([x for x in r if x['stage']==st]) for st in sorted({x['stage'] for x in r})}
ystages={}
for year in years:
 for stage in sorted({x['stage'] for x in r if x['year']==year}):
  ss=[x for x in r if x['year']==year and x['stage']==stage]
  ystages[f'{year}:{stage}']=pack(ss)
assert sum(z['games'] for z in annual.values())==2068
assert sum(z['games'] for z in stages.values())==2068
assert sum(z['takai']['games'] for z in annual.values())==282
assert sum(z['takai']['games'] for z in stages.values())==282
# Cross-reconcile each stage to per-season totals, exact to 0.1 pt.
for st in stages:
 assert round(sum(v['takai']['total_pt'] for k,v in ystages.items() if k.endswith(':'+st) and v['takai'] is not None),1)==stages[st]['takai']['total_pt']
for y in years:
 assert round(sum(v['takai']['total_pt'] for k,v in ystages.items() if k.startswith(str(y)+':') and v['takai'] is not None),1)==annual[str(y)]['takai']['total_pt']
ret={'source':'20261120-2341-04338cbb','method':'game_player_result league_points + penalty_league_points, aggregate then round to 0.1', 'meta':meta,'all':allx,
'annual':annual,'stages':stages,'year_stages':ystages}
out=Path('results');out.mkdir(exist_ok=True)
(out/'takai_points_by_season_stage_20261120.json').write_text(json.dumps(ret,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
simple=[]
for key,z in ystages.items():
 x=z['takai']
 if x: simple.append({'year_stage':key,'games':x['games'],'total_pt':x['total_pt'],
 'pt_per_game':x['pt_per_game'],'rank_total_pt':x['rank_total_pt'],'rank_pt_per_game':x['rank_pt_per_game'],'players_count':z['players_count']})
with (out/'takai_points_by_stage.csv').open('w',newline='',encoding='utf-8-sig') as f:
 writer=csv.DictWriter(f,fieldnames=list(simple[0]));writer.writeheader();writer.writerows(simple)
print('POINTS_VERIFIED',json.dumps({'all':allx['takai'],'stages':{k:{'takai':v['takai'],'players_count':v['players_count']} for k,v in stages.items()},
'year_stages':{k:{'takai':v['takai'],'players_count':v['players_count']} for k,v in ystages.items()},
'annual':{k:v['takai'] for k,v in annual.items()}},ensure_ascii=False),flush=True)
