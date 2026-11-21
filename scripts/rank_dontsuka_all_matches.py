import csv, json, os, sqlite3, sys, time
from pathlib import Path

db = sys.argv[1]
out = Path("results")
out.mkdir(exist_ok=True)
con = sqlite3.connect(f"file:{os.path.abspath(db)}?mode=ro", uri=True)
con.execute("PRAGMA temp_store=MEMORY")
players = con.execute("""
SELECT DISTINCT p.id,p.name FROM player p
JOIN game_player_result gr ON gr.player_id=p.id
JOIN game g ON g.id=gr.game_id
JOIN season_stage ss ON ss.id=g.season_stage_id
ORDER BY p.id
""").fetchall()
sql = """
WITH
draws AS MATERIALIZED (
 SELECT e.id draw_id,e.kyoku_id,e.event_order draw_order,g.id game_id,
 CASE WHEN substr(d.tile,1,1)='0' THEN '5'||substr(d.tile,2) ELSE d.tile END tile
 FROM draw_event d JOIN event e ON e.id=d.event_id
 JOIN kyoku k ON k.id=e.kyoku_id JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
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
SELECT COUNT(*),COUNT(h.draw_id),COUNT(DISTINCT d.kyoku_id)
FROM draws d LEFT JOIN hit_draws h ON h.draw_id=d.draw_id
"""
rows=[]
for i,(pid,name) in enumerate(players,1):
    start=time.monotonic()
    draws,hits,kyoku=con.execute(sql,(pid,pid)).fetchone()
    rows.append(dict(player_id=pid,player_name=name,total_draws=draws,hit_draws=hits,
                     dontsuka_pct=round(100*hits/draws,4) if draws else None,
                     kyoku_count=kyoku,
                     hits_per_100_kyoku=round(100*hits/kyoku,4) if kyoku else None))
    print(f"{i}/{len(players)} {name}: {hits}/{draws} ({time.monotonic()-start:.1f}s)",flush=True)
rows.sort(key=lambda x:(-(x["dontsuka_pct"] or 0),-x["hit_draws"],x["player_name"]))
with open(out/"dontsuka_all_matches.csv","w",encoding="utf-8-sig",newline="") as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
(out/"dontsuka_top10.json").write_text(json.dumps(rows[:10],ensure_ascii=False,indent=2),encoding="utf-8")
print("TOP 10",json.dumps(rows[:10],ensure_ascii=False,indent=2),flush=True)
