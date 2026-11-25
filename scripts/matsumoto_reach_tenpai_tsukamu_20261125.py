#!/usr/bin/env python3
"""松本吉弘・掴み発生時の自分の立直/テンパイ状態別抽出。既存DBの読み取り専用。"""
import sqlite3, json, sys, os
from collections import defaultdict
c=sqlite3.connect('file:'+os.path.abspath(sys.argv[1])+'?mode=ro',uri=True,timeout=120)
c.row_factory=sqlite3.Row
c.execute('PRAGMA query_only=ON')
pid=c.execute("SELECT id FROM player WHERE name='松本吉弘'").fetchone()[0]
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
SELECT d.year,d.stage,d.own_shanten,d.own_reached,COUNT(*) draws,
       COUNT(h.draw_id) hits,COUNT(DISTINCT d.kyoku_id) kyoku_with_draw
FROM draws d LEFT JOIN hit_draws h ON h.draw_id=d.draw_id
GROUP BY d.year,d.stage,d.own_shanten,d.own_reached
ORDER BY d.year,d.stage,d.own_reached,d.own_shanten
"""
rows=[dict(x) for x in c.execute(q,(pid,pid))]
assert sum(x['draws'] for x in rows)==41881, ('draws',sum(x['draws'] for x in rows))
assert sum(x['hits'] for x in rows)==916, ('hits',sum(x['hits'] for x in rows))
assert sum(x['hits'] for x in rows if x['own_reached'])==94, ('reached hits',rows)
assert all(x['own_shanten'] is not None for x in rows), rows
assert all(x['own_shanten']==0 for x in rows if x['own_reached']),('reach while not tenpai',rows)
def groups(parts):
 out={}
 for name, filterfn in parts.items():
  subset=[x for x in rows if filterfn(x)]
  n=sum(x['draws'] for x in subset);h=sum(x['hits'] for x in subset)
  out[name]={'draws':n,'hits':h,'pct':round(100*h/n,4) if n else None}
 assert out['all']['draws']==out['reached']['draws']+out['not_reached_tenpai']['draws']+out['not_tenpai']['draws']
 assert out['all']['hits']==out['reached']['hits']+out['not_reached_tenpai']['hits']+out['not_tenpai']['hits']
 assert out['tenpai_including_reach']['hits']==out['reached']['hits']+out['not_reached_tenpai']['hits']
 return out
parts={
'all':lambda r:True,
'reached':lambda r:bool(r['own_reached']),
'tenpai_including_reach':lambda r:r['own_shanten']==0,
'not_reached_tenpai':lambda r:r['own_shanten']==0 and not r['own_reached'],
'not_tenpai':lambda r:r['own_shanten']>0,
'not_reached_all':lambda r:not r['own_reached'],
}
print('ALL',json.dumps(groups(parts),ensure_ascii=False),flush=True)
years=sorted(set(x['year'] for x in rows))
for year in years:
 items=[x for x in rows if x['year']==year]
 print('SEASON',year,json.dumps(groups({k:(lambda r, fn=fn: r['year']==year and fn(r)) for k,fn in parts.items()}),ensure_ascii=False),flush=True)
for stage in ('regular','semifinal','final'):
 print('STAGE',stage,json.dumps(groups({k:(lambda r, fn=fn: r['stage']==stage and fn(r)) for k,fn in parts.items()}),ensure_ascii=False),flush=True)
print('VALIDATION_SUCCESS',flush=True)
