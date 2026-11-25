#!/usr/bin/env python3
"""全56選手の立直・門前ヤミテン・副露テンパイ・非テンパイを再集計。ドンツカv0.4は不変。"""
import sqlite3,json,os,sys,time,csv
from collections import defaultdict
from pathlib import Path
c=sqlite3.connect('file:'+os.path.abspath(sys.argv[1])+'?mode=ro',uri=True,timeout=180)
c.row_factory=sqlite3.Row
c.execute('PRAGMA query_only=ON')
c.execute('PRAGMA temp_store=MEMORY')
players=[dict(x) for x in c.execute('SELECT id,name FROM player WHERE EXISTS(SELECT 1 FROM game_player_result gr WHERE gr.player_id=player.id) ORDER BY id')]
assert len(players)==56
meta=dict(c.execute("SELECT COUNT(*) AS games,MIN(date) AS from_date,MAX(date) AS to_date FROM game").fetchone())
meta['kyoku']=c.execute('SELECT COUNT(*) FROM kyoku').fetchone()[0]
assert (meta['games'],meta['kyoku'])==(2068,25238),meta
print('DB_META',json.dumps(meta,ensure_ascii=False),flush=True)
q="""
WITH
draws AS MATERIALIZED (
 SELECT e.id draw_id,e.kyoku_id,e.event_order draw_order,g.id game_id,
        ls.start_year year,ss.stage stage,
        CASE WHEN substr(d.tile,1,1)='0' THEN '5'||substr(d.tile,2) ELSE d.tile END tile,
        (SELECT ps.shanten_count FROM event pe JOIN player_state ps ON ps.event_id=pe.id
         WHERE pe.kyoku_id=e.kyoku_id AND ps.player_id=d.actor_player_id AND pe.event_order<e.event_order
         ORDER BY pe.event_order DESC,pe.id DESC LIMIT 1) own_shanten,
        (SELECT ps.is_menzen FROM event pe JOIN player_state ps ON ps.event_id=pe.id
         WHERE pe.kyoku_id=e.kyoku_id AND ps.player_id=d.actor_player_id AND pe.event_order<e.event_order
         ORDER BY pe.event_order DESC,pe.id DESC LIMIT 1) own_is_menzen,
        EXISTS(SELECT 1 FROM reach_event re JOIN event ree ON ree.id=re.event_id
         WHERE re.actor_player_id=d.actor_player_id AND re.is_accepted=1
         AND ree.kyoku_id=e.kyoku_id AND ree.event_order<e.event_order) own_reached
 FROM draw_event d JOIN event e ON e.id=d.event_id
 JOIN kyoku k ON k.id=e.kyoku_id JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id JOIN league_season ls ON ls.id=ss.league_season_id
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
SELECT d.year,d.stage,d.own_shanten,d.own_reached,d.own_is_menzen,COUNT(*) draws,
       COUNT(h.draw_id) hits,COUNT(DISTINCT d.kyoku_id) kyoku_with_draw
FROM draws d LEFT JOIN hit_draws h ON h.draw_id=d.draw_id
GROUP BY d.year,d.stage,d.own_shanten,d.own_reached,d.own_is_menzen
ORDER BY d.year,d.stage,d.own_reached,d.own_shanten
"""

rows=[]
for i,p in enumerate(players,1):
 t=time.monotonic()
 x=[dict(z) for z in c.execute(q,(p['id'],p['id']))]
 for y in x:y['player']=p['name']
 rows+=x
 print('PROGRESS',i,len(players),p['name'],round(time.monotonic()-t,2),flush=True)
assert sum(x['draws'] for x in rows)==1257732
assert sum(x['hits'] for x in rows)==27578
mats=[x for x in rows if x['player']=='松本吉弘']
assert sum(x['draws'] for x in mats)==41881
assert sum(x['hits'] for x in mats)==916
assert sum(x['hits'] for x in mats if x['own_reached'])==94
assert all(x['own_shanten'] is not None for x in rows)
assert all(x['own_shanten']==0 for x in rows if x['own_reached'])
assert all(x['own_is_menzen'] is not None for x in rows)
assert all(x['own_is_menzen']==1 for x in rows if x['own_reached'])
print('STATE_VALIDATION',json.dumps({'nonmenzen_reached':sum(x['draws'] for x in rows if x['own_reached'] and not x['own_is_menzen']),'all_player_rows':len(rows)},ensure_ascii=False),flush=True)
labels=('all','reached','tenpai','nonreach_tenpai_legacy','closed_dama','open_tenpai','not_tenpai')
def condition(r,label):
 if label=='all':return True
 if label=='reached':return bool(r['own_reached'])
 if label=='tenpai':return r['own_shanten']==0
 if label=='nonreach_tenpai_legacy':return r['own_shanten']==0 and not r['own_reached']
 if label=='closed_dama':return r['own_shanten']==0 and not r['own_reached'] and bool(r['own_is_menzen'])
 if label=='open_tenpai':return r['own_shanten']==0 and not r['own_reached'] and not r['own_is_menzen']
 if label=='not_tenpai':return r['own_shanten']>0
 raise KeyError(label)
def calc(items,label):
 sub=[r for r in items if condition(r,label)]
 d=sum(x['draws'] for x in sub)
 h=sum(x['hits'] for x in sub)
 return {'hits':h,'draws':d,'rate':round(100*h/d,4) if d else None}
def calc_all(items):
 out={label:calc(items,label) for label in labels}
 assert out['all']['draws']==out['reached']['draws']+out['closed_dama']['draws']+out['open_tenpai']['draws']+out['not_tenpai']['draws']
 assert out['all']['hits']==out['reached']['hits']+out['closed_dama']['hits']+out['open_tenpai']['hits']+out['not_tenpai']['hits']
 assert out['tenpai']['hits']==out['reached']['hits']+out['closed_dama']['hits']+out['open_tenpai']['hits']
 assert out['nonreach_tenpai_legacy']['draws']==out['closed_dama']['draws']+out['open_tenpai']['draws']
 assert out['nonreach_tenpai_legacy']['hits']==out['closed_dama']['hits']+out['open_tenpai']['hits']
 return out
def unit_result(name,subset):
 league=calc_all(subset)
 mats=calc_all([x for x in subset if x['player']=='松本吉弘'])
 peers=calc_all([x for x in subset if x['player']!='松本吉弘'])
 individual=[]
 for p in players:
  rr=[x for x in subset if x['player']==p['name']]
  if rr:
   individual.append({'player':p['name'],**calc_all(rr)})
 ranked={}
 for label in labels:
  ranked[label]=sorted([{'player':p['player'],**p[label]} for p in individual if p[label]['draws']>0],
                        key=lambda t:(-t['hits']/t['draws'],t['player']))
 ranks={label:next((i+1 for i,p in enumerate(ranked[label]) if p['player']=='松本吉弘'),None) for label in labels}
 if mats['all']['draws']:
  assert mats['all']['draws']+peers['all']['draws']==league['all']['draws']
  assert mats['all']['hits']+peers['all']['hits']==league['all']['hits']
 print('RESULT_CONTEXT',name,json.dumps({'league':league,'peers_excluding_matsumoto':peers,'matsumoto':mats,'rank':ranks,'player_count':len(individual)},ensure_ascii=False,separators=(',',':')),flush=True)
 return {'scope':name,'league':league,'peers':peers,'matsumoto':mats,'ranks':ranks,'players':individual,
         'ranked':ranked}
scopes={'all':rows}
for year in sorted(set(x['year'] for x in rows)):
 scopes['season_'+str(year)]=[x for x in rows if x['year']==year]
for stage in ('regular','semifinal','final'):
 scopes['stage_'+stage]=[x for x in rows if x['stage']==stage]
scopes['pre2025']=[x for x in rows if x['year']<2025]
scopes['post2025']=[x for x in rows if x['year']>=2025]
scopes['peak2024_2025']=[x for x in rows if x['year'] in (2024,2025)]
report=[unit_result(k,v) for k,v in scopes.items()]
assert report[0]['league']['nonreach_tenpai_legacy']['draws']==71088
assert report[0]['league']['nonreach_tenpai_legacy']['hits']==2856
assert report[0]['matsumoto']['nonreach_tenpai_legacy']['draws']==2269
assert report[0]['matsumoto']['nonreach_tenpai_legacy']['hits']==93
assert report[0]['league']['reached']['draws']==90653
assert report[0]['league']['reached']['hits']==2838
overall=report[0]
for label in labels:
 print('RESULT_OVERALL_RANKING',label,json.dumps(overall['ranked'][label],ensure_ascii=False,separators=(',',':')),flush=True)
print('RESULT_2024_RANKING',json.dumps(next(r for r in report if r['scope']=='season_2024')['ranked']['closed_dama'],ensure_ascii=False,separators=(',',':')),flush=True)
print('RESULT_2022_RANKING',json.dumps(next(r for r in report if r['scope']=='season_2022')['ranked']['closed_dama'],ensure_ascii=False,separators=(',',':')),flush=True)
print('RESULT_2025_RANKING',json.dumps(next(r for r in report if r['scope']=='season_2025')['ranked']['damaten'],ensure_ascii=False,separators=(',',':')),flush=True)
out=Path('results');out.mkdir(exist_ok=True)
(out/'all_players_reach_closed_dama_open_tenpai_dontsuka_20261126.json').write_text(json.dumps({'data_scope':meta,'report':[{k:v for k,v in rr.items() if k!='ranked'} for rr in report]},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
with (out/'all_players_reach_closed_dama_open_tenpai_dontsuka_20261126.csv').open('w',newline='',encoding='utf-8-sig') as f:
 cols=['scope','player','category','hits','draws','pct','rank']
 w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
 for item in report:
  for player in item['players']:
   for label in labels:
    data=player[label]
    rank=next((n for n,z in enumerate(item['ranked'][label],1) if z['player']==player['player']),None)
    w.writerow({'scope':item['scope'],'player':player['player'],'category':label,'hits':data['hits'],'draws':data['draws'],'pct':data['rate'],'rank':rank})
print('CLASSIFICATION',json.dumps({'reached':'受理済み立直中','closed_dama':'非立直かつ門前のテンパイ','open_tenpai':'非立直かつ非門前のテンパイ','not_tenpai':'シャンテン数1以上（副露を含む）','nonreach_tenpai_legacy':'旧分類の非立直テンパイ合算'},ensure_ascii=False),flush=True)
print('VALIDATION_SUCCESS',flush=True)
