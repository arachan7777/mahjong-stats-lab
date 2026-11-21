"""Read-only feasibility audit for 王牌幽閉率. NOT a finalized indicator definition."""
from pathlib import Path
from collections import Counter
import sqlite3,os,sys,json,csv
con=sqlite3.connect("file:"+os.path.abspath(sys.argv[1])+"?mode=ro",uri=True)
con.row_factory=sqlite3.Row
out=Path("results");out.mkdir(exist_ok=True)
def query(q,args=()):
    return [dict(x) for x in con.execute(q,args)]
def write_json(name,x):
    (out/name).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding="utf-8")
def write_csv(name,x):
    if not x:return
    with (out/name).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(x[0]))
        w.writeheader();w.writerows(x)

assert con.execute("PRAGMA quick_check").fetchone()[0]=="ok"
columns=query("PRAGMA table_info(player_tenpai_state)")
ryu=query("""
SELECT e.id AS ryukyoku_event_id,e.kyoku_id,e.event_order AS end_order,
       k.game_id,rp.player_id,p.name AS player_name,
       rp.is_tenpai,pts.is_actor,pts.is_reached,pts.waiting_tiles,
       pts.waiting_type,pts.ideal_tile_count,
       pts.available_tile_count,pts.dora_indicator_tile_count
FROM ryukyoku_event r
JOIN event e ON e.id=r.event_id
JOIN kyoku k ON k.id=e.kyoku_id
JOIN ryukyoku_player rp ON rp.ryukyoku_event_id=r.event_id
JOIN player p ON p.id=rp.player_id
LEFT JOIN player_tenpai_state pts
  ON pts.event_id=r.event_id AND pts.player_id=rp.player_id
ORDER BY e.kyoku_id,rp.player_id
""")
tenpai=[r for r in ryu if r["is_tenpai"]==1]
noten=[r for r in ryu if r["is_tenpai"]==0]
missing=[r for r in tenpai if r["available_tile_count"] is None]
extra=[r for r in noten if r["available_tile_count"] is not None]
invalid=[r for r in tenpai if r["available_tile_count"] is not None
 and (r["available_tile_count"]<0 or r["ideal_tile_count"]<0 or r["available_tile_count"]>r["ideal_tile_count"])]
available=[r for r in tenpai if r["available_tile_count"] is not None]
by_player={}
for r in available:
    p=by_player.setdefault(r["player_id"],{"player_id":r["player_id"],"player_name":r["player_name"],
             "tenpai_at_draw":0,"at_least_one_dead_wall_wait":0,"zero_dead_wall_wait":0,
             "dead_wall_wait_tiles_total":0,"ideal_wait_tiles_total":0,
             "reached_at_draw":0})
    p["tenpai_at_draw"]+=1
    p["at_least_one_dead_wall_wait"]+=r["available_tile_count"]>0
    p["zero_dead_wall_wait"]+=r["available_tile_count"]==0
    p["dead_wall_wait_tiles_total"]+=r["available_tile_count"]
    p["ideal_wait_tiles_total"]+=r["ideal_tile_count"]
    p["reached_at_draw"]+=r["is_reached"]==1
outrows=sorted(by_player.values(),key=lambda r:(-r["at_least_one_dead_wall_wait"]/r["tenpai_at_draw"],-r["tenpai_at_draw"],r["player_name"]))
for r in outrows:
    r["dead_wall_presence_pct_of_draw_tenpai"]=round(100*r["at_least_one_dead_wall_wait"]/r["tenpai_at_draw"],4)
    r["dead_wall_wait_tiles_per_100_draw_tenpai"]=round(100*r["dead_wall_wait_tiles_total"]/r["tenpai_at_draw"],4)
write_csv("dead_wall_draw_tenpai_observations_all_players.csv",outrows)

# The same player_tenpai_state field changes semantic meaning at ryukyoku;
# compare its values at actor's first own-tenpai event and terminal draw event.
first=query("""
WITH seq AS (
 SELECT pts.player_id,e.kyoku_id,e.id AS state_event_id,e.event_order,
        e.type,pts.available_tile_count,pts.ideal_tile_count,
        ROW_NUMBER() OVER (
           PARTITION BY e.kyoku_id,pts.player_id
           ORDER BY e.event_order,e.id
        ) AS rn
 FROM player_tenpai_state pts
 JOIN event e ON e.id=pts.event_id
 WHERE pts.is_actor=1
)
SELECT * FROM seq WHERE rn=1
""")
first_kind=Counter(x["type"] for x in first)
first_ava=Counter(x["available_tile_count"] for x in first)
end_ava=Counter(x["available_tile_count"] for x in available)
partial_info={
 "note":"TECHNICAL AUDIT ONLY, not official 11th metric. End-of-exhaustive-draw available_tile_count is dead-wall remaining wait count according to source documentation. Other event types mean remaining wall count.",
 "sqlite_quick_check":"ok","player_tenpai_state_schema":[x["name"] for x in columns],
 "total_ryukyoku_events":len(set(x["ryukyoku_event_id"] for x in ryu)),
 "total_ryukyoku_player_rows":len(ryu),
 "tenpai_at_ryukyoku":len(tenpai),
 "noten_at_ryukyoku":len(noten),
 "tenpai_missing_terminal_snapshot":len(missing),
 "noten_with_terminal_snapshot":len(extra),
 "invalid_terminal_availability":len(invalid),
 "available_terminal_tenpai":len(available),
 "with_dead_wall_wait_tile":sum(x["available_tile_count"]>0 for x in available),
 "without_dead_wall_wait_tile":sum(x["available_tile_count"]==0 for x in available),
 "total_dead_wall_wait_tiles":sum(x["available_tile_count"] for x in available),
 "total_ideal_wait_tiles":sum(x["ideal_tile_count"] for x in available),
 "players":len(outrows),
 "first_tenpai_state_records":len(first),
 "first_tenpai_event_types":dict(first_kind),
 "first_tenpai_available_distribution_sample":first_ava.most_common(15),
 "terminal_tenpai_dead_wall_wait_distribution":dict(sorted(end_ava.items())),
 "examples_terminal":available[:15],
 "examples_first":first[:15]
}
write_json("dead_wall_feasibility_audit.json",partial_info)
print("AUDIT",json.dumps({k:v for k,v in partial_info.items() if k not in ("examples_terminal","examples_first")},ensure_ascii=False),flush=True)
print("OBSERVATION_TOP10_NOT_RANKING",json.dumps(outrows[:10],ensure_ascii=False),flush=True)
if missing or extra or invalid:
    print("DATA LIMITATIONS",json.dumps({"missing":missing[:5],"extra":extra[:5],"invalid":invalid[:5]},ensure_ascii=False),flush=True)
