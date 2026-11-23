#!/usr/bin/env python3
"""検証済みドンツカ率v0.4の判定ロジックを一切変えず、年度別リーグ分母だけ集計。
隔離研究、正本読み取り限定。既存SQL・指標定義は変更しない。
"""
import csv,json,sqlite3,sys,collections,time
from pathlib import Path
cn=sqlite3.connect("file:"+str(Path(sys.argv[1]).resolve())+"?mode=ro",uri=True)
cn.execute("PRAGMA temp_store=MEMORY")
cn.execute("PRAGMA query_only=ON")
assert cn.execute("SELECT COUNT(*) FROM game").fetchone()[0]==2068
players=cn.execute("SELECT DISTINCT p.id,p.name FROM player p JOIN game_player_result gr ON gr.player_id=p.id ORDER BY p.id").fetchall()
assert len(players)==56
SQL="""
WITH draws AS MATERIALIZED (
 SELECT e.id draw_id,e.kyoku_id,e.event_order draw_order,g.id game_id,
 ls.start_year year,
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
 AND se.event_order<a.draw_order
 ORDER BY se.event_order DESC,se.id DESC LIMIT 1) snapshot_event_id
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
SELECT d.year,COUNT(*) total_draws,COUNT(h.draw_id) hit_draws
FROM draws d LEFT JOIN hit_draws h ON h.draw_id=d.draw_id GROUP BY d.year
"""
allrows=[]
for i,(pid,name) in enumerate(players,1):
 for year,total,hits in cn.execute(SQL,(pid,pid)):
  allrows.append(dict(year=year,player_id=pid,player_name=name,total_draws=total,hit_draws=hits,
   dontsuka_pct=round(100*hits/total,4)))
 print("PLAYER_DONE",i,name,flush=True)
assert sum(x["total_draws"] for x in allrows)==1257732
assert sum(x["hit_draws"] for x in allrows)==27578
annual=collections.defaultdict(lambda:dict(total_draws=0,hit_draws=0))
for row in allrows:
 a=annual[row["year"]];a["total_draws"]+=row["total_draws"];a["hit_draws"]+=row["hit_draws"]
league=[]
for yr,a in sorted(annual.items()):
 a.update(year=yr,dontsuka_pct=round(100*a["hit_draws"]/a["total_draws"],4));league.append(a)
hinata=[]
for yr in sorted(annual):
 kvals=[x for x in allrows if x["year"]==yr and x["player_name"]=="日向藍子"]
 if not kvals:continue
 k=kvals[0]
 # ranking threshold: draw count >= 1,000 to include initial partial season
 qual=sorted([x for x in allrows if x["year"]==yr and x["total_draws"]>=1000],
    key=lambda x:(-x["dontsuka_pct"],-x["hit_draws"],x["player_name"]))
 hinata.append(dict(year=yr,draws=k["total_draws"],hits=k["hit_draws"],
  dontsuka_pct=k["dontsuka_pct"],league_dontsuka_pct=annual[yr]["dontsuka_pct"],
  delta_pp=round(k["dontsuka_pct"]-annual[yr]["dontsuka_pct"],4),
  rank_min1000=1+next(i for i,x in enumerate(qual) if x["player_name"]=="日向藍子"),
  qualified_min1000=len(qual)))
print("LEAGUE_YEAR",json.dumps(league,ensure_ascii=False),flush=True)
print("HINATA_YEAR",json.dumps(hinata,ensure_ascii=False),flush=True)
out=Path("results");out.mkdir(exist_ok=True)
for name,records in [("dontsuka_all_players_season_20261124.csv",allrows),("dontsuka_league_season_20261124.csv",league),("hinata_dontsuka_vs_league_season_20261124.csv",hinata)]:
 with (out/name).open("w",encoding="utf-8-sig",newline="") as f:
  w=csv.DictWriter(f,fieldnames=list(records[0]));w.writeheader();w.writerows(records)
