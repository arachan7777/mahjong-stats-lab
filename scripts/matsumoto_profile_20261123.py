#!/usr/bin/env python3
"""One-off read-only profile for Matsumoto, preserving Dontsuka v0.4 semantics."""
import sys,sqlite3,json,csv,os,time
from pathlib import Path

DB=sys.argv[1]
c=sqlite3.connect('file:'+os.path.abspath(DB)+'?mode=ro',uri=True,timeout=90)
c.row_factory=sqlite3.Row
c.execute('PRAGMA query_only=ON')
c.execute('PRAGMA temp_store=MEMORY')
P='松本吉弘'
meta=dict(c.execute('SELECT COUNT(*) games,MIN(date) first_date,MAX(date) last_date FROM game').fetchone())
meta['total_kyoku']=c.execute('SELECT COUNT(*) FROM kyoku').fetchone()[0]
players=[dict(z) for z in c.execute('SELECT p.id,p.name FROM player p WHERE EXISTS (SELECT 1 FROM game_player_result gr WHERE gr.player_id=p.id) ORDER BY p.id')]
assert len(players)==56,(len(players),players)
pid=next(x['id'] for x in players if x['name']==P)
print('DB_META',json.dumps(meta,ensure_ascii=False),flush=True)

SQL = """
WITH
draws AS MATERIALIZED (
 SELECT e.id draw_id,e.kyoku_id,e.event_order draw_order,g.id game_id,
        ls.start_year year,ss.stage stage,
 CASE WHEN substr(d.tile,1,1)='0' THEN '5'||substr(d.tile,2) ELSE d.tile END tile
 FROM draw_event d JOIN event e ON e.id=d.event_id
 JOIN kyoku k ON k.id=e.kyoku_id JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
 WHERE d.actor_player_id=?
),
last_actor AS MATERIALIZED (
 SELECT d.*,gr.player_id opponent_id,
 (SELECT e2.id FROM event e2 JOIN player_state ps2 ON ps2.event_id=e2.id
  WHERE e2.kyoku_id=d.kyoku_id AND e2.event_order<d.draw_order
  AND ps2.player_id=gr.player_id
  ORDER BY e2.event_order DESC,e2.id DESC LIMIT 1) actor_event_id
 FROM draws d JOIN game_player_result gr ON gr.game_id=d.game_id
 WHERE gr.player_id<>?
),
eligible_actor AS MATERIALIZED (
 SELECT a.*,ae.event_order actor_order FROM last_actor a
 JOIN player_state ps ON ps.event_id=a.actor_event_id AND ps.player_id=a.opponent_id
 JOIN event ae ON ae.id=a.actor_event_id WHERE ps.shanten_count=0
),
latest_snapshot AS MATERIALIZED (
 SELECT a.*,
 (SELECT pts.event_id FROM event se JOIN player_tenpai_state pts
 ON pts.event_id=se.id AND pts.player_id=a.opponent_id
 WHERE se.kyoku_id=a.kyoku_id AND se.event_order>=a.actor_order
 AND se.event_order<a.draw_order ORDER BY se.event_order DESC,se.id DESC LIMIT 1) snapshot_event_id
 FROM eligible_actor a
),
hit_draws AS MATERIALIZED (
 SELECT DISTINCT s.draw_id FROM latest_snapshot s
 JOIN player_tenpai_state pts ON pts.event_id=s.snapshot_event_id AND pts.player_id=s.opponent_id
 JOIN tenpai_agari_matrix m ON m.event_id=s.snapshot_event_id AND m.player_id=s.opponent_id
 WHERE pts.is_furiten=0 AND m.is_ron_agari=1
 AND (CASE WHEN substr(m.waiting_tile,1,1)='0'
 THEN '5'||substr(m.waiting_tile,2) ELSE m.waiting_tile END)=s.tile
)
SELECT d.year,d.stage,COUNT(*) total_draws,COUNT(h.draw_id) hits,COUNT(DISTINCT d.kyoku_id) kyoku_with_draw,
%(extra)s
FROM draws d LEFT JOIN hit_draws h ON h.draw_id=d.draw_id
GROUP BY d.year,d.stage ORDER BY d.year,d.stage
"""
EXTRA_BASE='0 AS dummy'
EXTRA_MATS="""SUM(CASE WHEN h.draw_id IS NOT NULL AND EXISTS
 (SELECT 1 FROM reach_event re JOIN event re_e ON re_e.id=re.event_id
  WHERE re.actor_player_id=%d AND re.is_accepted=1
    AND re_e.kyoku_id=d.kyoku_id AND re_e.event_order<d.draw_order)
 THEN 1 ELSE 0 END) hit_while_reached"""%pid

results=[]
for i,p in enumerate(players,1):
 t=time.monotonic();q=SQL%{'extra':EXTRA_MATS if p['id']==pid else EXTRA_BASE}
 rs=[dict(x) for x in c.execute(q,(p['id'],p['id']))]
 for r in rs:r.update(player_id=p['id'],player_name=p['name'])
 results.extend(rs)
 print('PROGRESS',i,'/',len(players),p['name'],sum(x['hits'] for x in rs),'/',sum(x['total_draws'] for x in rs),'secs',round(time.monotonic()-t,2),flush=True)
assert sum(x['hits'] for x in results)==27578,('hit check',sum(x['hits'] for x in results))
assert sum(x['total_draws'] for x in results)==1257732,('draw check',sum(x['total_draws'] for x in results))
assert sum(x['hits'] for x in results if x['player_name']==P)==916
assert sum(x['total_draws'] for x in results if x['player_name']==P)==41881

base=[dict(x) for x in c.execute('SELECT * FROM player_season_stage_stats_base')]
assert base, 'player_season_stage_stats_base empty'
by_name={p['name']:p['id'] for p in players}
for r in base:
 r['year']=r['season_start_year'];r['player_id']=by_name[r['player_name']]
assert sum(r['total_kyoku_count'] for r in base)==4*meta['total_kyoku']
assert sum(r['total_game_count'] for r in base)==4*meta['games']
assert sum(r['total_kyoku_count'] for r in base if r['player_name']==P)==3329

def select(scope, arr):
 if scope=='all':return arr
 if scope.startswith('yr:'):
  yr=int(scope[3:]);return [x for x in arr if x['year']==yr]
 if scope.startswith('stage:'):
  st=scope[6:];return [x for x in arr if x['stage']==st]
 if scope=='pre2025':return [x for x in arr if x['year']<2025]
 if scope=='2025only':return [x for x in arr if x['year']==2025]
 if scope=='2026only':return [x for x in arr if x['year']==2026]
 if scope=='post2025':return [x for x in arr if x['year']>=2025]
 raise ValueError(scope)

def rate(n,d):return round(100*n/d,4) if d else None
def sumrow(s,which):
 z={}
 for col in which:z[col]=sum((x[col] or 0) for x in s)
 return z

H_COLS=['total_draws','hits','kyoku_with_draw']
B_COLS=['total_game_count','total_kyoku_count','agari_count','dealin_count','reach_count','furo_count','rank1_count','rank2_count','rank3_count','rank4_count','tsumo_agari_count','reach_agari_count']

def pack(scope):
 r=select(scope,results);b=select(scope,base)
 league=sumrow(r,H_COLS);ms=sumrow([x for x in r if x['player_name']==P],H_COLS)
 league_b=sumrow(b,B_COLS);ms_b=sumrow([x for x in b if x['player_name']==P],B_COLS)
 if ms_b['total_game_count']:
  assert ms_b['total_kyoku_count']>=ms['kyoku_with_draw']
 assert ms['hits']<=ms['total_draws']
 assert ms_b['total_kyoku_count']==ms['kyoku_with_draw'] or ms_b['total_kyoku_count']==0,(scope,ms,ms_b)
 assert league_b['total_kyoku_count']==league['kyoku_with_draw'] or not r, (scope,league,league_b)
 eligible=[x for x in players if sum(y['total_draws'] for y in r if y['player_id']==x['id'])>0]
 rates=[(x['id'],sum(y['hits'] for y in r if y['player_id']==x['id'])/sum(y['total_draws'] for y in r if y['player_id']==x['id'])) for x in eligible]
 rank=1+sum(x[1]>ms['hits']/ms['total_draws'] for x in rates) if ms['total_draws'] else None
 nplayers=len(eligible)
 games=sum(x['total_game_count'] for x in b)//4
 kyokus=sum(x['total_kyoku_count'] for x in b)//4
 ranknumerator=lambda x:sum((i+1)*x[f'rank{i+1}_count'] for i in range(4))
 out={'scope':scope,'league_games':games,'league_kyoku':kyokus,'active_players':nplayers,
      'matsumoto':{**ms,**ms_b,'dontsuka_pct':rate(ms['hits'],ms['total_draws']),
                    'tsukamu_index':rate(ms['hits'],ms_b['total_kyoku_count']),
                    'dealin_pct':rate(ms_b['dealin_count'],ms_b['total_kyoku_count']),
                    'agari_pct':rate(ms_b['agari_count'],ms_b['total_kyoku_count']),
                    'reach_pct':rate(ms_b['reach_count'],ms_b['total_kyoku_count']),
                    'furo_pct':rate(ms_b['furo_count'],ms_b['total_kyoku_count']),
                    'top_pct':rate(ms_b['rank1_count'],ms_b['total_game_count']),
                    'average_rank':round(ranknumerator(ms_b)/ms_b['total_game_count'],4) if ms_b['total_game_count'] else None,
                    'rank_numerator':ranknumerator(ms_b),
                    'reached_hit':sum(x.get('hit_while_reached',0) for x in r if x['player_name']==P),
                    'dontsuka_rank':rank},
      'league':{**league,**league_b,
                 'dontsuka_pct':rate(league['hits'],league['total_draws']),
                 'tsukamu_index':rate(league['hits'],league_b['total_kyoku_count']),
                 'dealin_pct':rate(league_b['dealin_count'],league_b['total_kyoku_count']),
                 'agari_pct':rate(league_b['agari_count'],league_b['total_kyoku_count']),
                 'reach_pct':rate(league_b['reach_count'],league_b['total_kyoku_count']),
                 'furo_pct':rate(league_b['furo_count'],league_b['total_kyoku_count']),
                 'top_pct':rate(league_b['rank1_count'],league_b['total_game_count']),
                 'average_rank':round(ranknumerator(league_b)/league_b['total_game_count'],4) if league_b['total_game_count'] else None,
                 'rank_numerator':ranknumerator(league_b)}}
 return out

years=sorted({x['year'] for x in results})
seasons=[pack('yr:'+str(y)) for y in years]
stages=[pack('stage:'+s) for s in ('regular','semifinal','final')]
periods=[pack(s) for s in ('pre2025','2025only','2026only','post2025')]
overall=pack('all')
assert overall['matsumoto']['dontsuka_rank']==28
assert overall['matsumoto']['reached_hit']<=916
assert sum(x['matsumoto']['hits'] for x in seasons)==overall['matsumoto']['hits']
assert sum(x['matsumoto']['hits'] for x in stages)==overall['matsumoto']['hits']
assert sum(x['league']['hits'] for x in seasons)==overall['league']['hits']
assert sum(x['league']['hits'] for x in stages)==overall['league']['hits']
assert sum(x['matsumoto']['total_game_count'] for x in seasons)==overall['matsumoto']['total_game_count']
assert overall['matsumoto']['total_kyoku_count']==3329
assert overall['matsumoto']['total_draws']==41881
assert overall['matsumoto']['hits']==916
assert overall['matsumoto']['reached_hit']+sum(x['hits']-x.get('hit_while_reached',0) for x in results if x['player_name']==P)==916

result={'data_scope':meta,'matsumoto_player_id':pid,'seasons':seasons,'stages':stages,'periods':periods,'overall':overall,
        'definition':'ドンツカ v0.4; どんだけ掴むねん指数=hit draws/participated kyoku*100; dealin=dealin count/participated kyoku; hit while reached=accepted reach before the draw in same kyoku; other hits not conclusively foldable.'}
out=Path('results');out.mkdir(exist_ok=True)
(out/'matsumoto_stats_report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
for name,items in [('seasons',seasons),('stages',stages),('periods',periods)]:
 with (out/('matsumoto_'+name+'.csv')).open('w',encoding='utf-8-sig',newline='') as f:
  writer=csv.DictWriter(f,fieldnames=['scope','league_games','league_kyoku','active_players','player_games','player_kyoku','hit','draw','dontsuka_pct','dontsuka_rank','tsukamu_index','dealin_count','dealin_pct','league_hits','league_draws','league_dontsuka_pct','league_dealin_count','league_participated_kyoku','league_dealin_pct','hit_while_reached'])
  writer.writeheader()
  for z in items:
   m=z['matsumoto'];l=z['league']
   writer.writerow(dict(scope=z['scope'],league_games=z['league_games'],league_kyoku=z['league_kyoku'],active_players=z['active_players'],player_games=m['total_game_count'],player_kyoku=m['total_kyoku_count'],hit=m['hits'],draw=m['total_draws'],dontsuka_pct=m['dontsuka_pct'],dontsuka_rank=m['dontsuka_rank'],tsukamu_index=m['tsukamu_index'],dealin_count=m['dealin_count'],dealin_pct=m['dealin_pct'],league_hits=l['hits'],league_draws=l['total_draws'],league_dontsuka_pct=l['dontsuka_pct'],league_dealin_count=l['dealin_count'],league_participated_kyoku=l['total_kyoku_count'],league_dealin_pct=l['dealin_pct'],hit_while_reached=m['reached_hit']))

for key,value in [('SEASONS',seasons),('STAGES',stages),('PERIODS',periods),('OVERALL',overall)]:
 print('RESULT_'+key+' '+json.dumps(value,ensure_ascii=False,separators=(',',':')),flush=True)
print('VALIDATION_SUCCESS',flush=True)
