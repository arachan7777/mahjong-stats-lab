"""2025-26シーズン リーチ王牌幽閉率ランキング。
既存 v0.1 SQL の期間パラメータだけ2025に設定し、全期間の独立検証済み
イベント明細から同一シーズンを抽出して、全選手とイベント単位で照合。
"""
import csv,json,os,sqlite3,sys
from pathlib import Path
from collections import defaultdict
root=Path(__file__).resolve().parents[1]
out=Path("results");out.mkdir(exist_ok=True)
con=sqlite3.connect("file:"+os.path.abspath(sys.argv[1])+"?mode=ro",uri=True)
con.row_factory=sqlite3.Row
sql=(root/"sql/reach_dead_wall_confinement_v01.sql").read_text(encoding="utf-8")
original="SELECT NULL AS start_year, NULL AS stage"
assert sql.count(original)==1
sub=sql.replace(original,"SELECT 2025 AS start_year, NULL AS stage")
def query(q):
 return [dict(r) for r in con.execute(q)]
def write_csv(name,rows):
 if not rows:return
 with (out/name).open("w",encoding="utf-8-sig",newline="") as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def write_json(name,x):
 (out/name).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding="utf-8")
rows=query(sub)
assert len(rows)>=10,("insufficient ranking candidates",len(rows))
seasons={r["kyoku_id"]:r["start_year"] for r in query("""
 SELECT k.id AS kyoku_id,ls.start_year AS start_year
 FROM kyoku k
 JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
""")}
source=out/"reach_dead_wall_confinement_event_details.csv"
assert source.exists(),"The independently validated all-season details must be present"
with source.open("r",encoding="utf-8-sig",newline="") as f:
 full=list(csv.DictReader(f))
selected=[x for x in full if seasons[int(x["kyoku_id"])]==2025]
assert selected,"No eligible event records in 2025-26 season"
# Compare every SQL-generated period event to the independent full-period event.
start=sub.index("SELECT p.id AS player_id,p.name AS player_name")
details=query(sub[:start]+"""
SELECT kyoku_id,player_id,wait_event_id,remaining_when_reached,
       dead_wall_reach_wait_tiles,initial_dora_indicators,final_dora_indicators
FROM eligible_reaches
ORDER BY kyoku_id,player_id,wait_event_id
""")
fields=("kyoku_id","player_id","wait_event_id","remaining_when_reached",
        "dead_wall_reach_wait_tiles","initial_dora_indicators","final_dora_indicators")
reference={tuple(int(x[k]) for k in fields[:3]):tuple(int(x[k]) for k in fields[3:]) for x in selected}
assert len(reference)==len(selected)==len(details),(len(reference),len(selected),len(details))
for x in details:
 key=tuple(int(x[k]) for k in fields[:3])
 assert key in reference,("missing in independently audited events",x)
 assert tuple(int(x[k]) for k in fields[3:])==reference[key],("episode changed",x)
totals=defaultdict(lambda:[0,0,0,0,0])
for x in selected:
 bucket=totals[int(x["player_id"])]
 bucket[0]+=1
 bucket[1]+=int(x["remaining_when_reached"])
 bucket[2]+=int(x["dead_wall_reach_wait_tiles"])
 bucket[3]+=int(x["initial_dora_indicators"])
 bucket[4]+=int(x["final_dora_indicators"])
for r in rows:
 counts=totals[r["player_id"]]
 assert [r["accepted_reach_ryukyoku_count"],r["remaining_when_reached_total"],
         r["dead_wall_reach_wait_tiles_total"],r["initial_dora_indicator_wait_tiles"],
         r["final_dora_indicator_wait_tiles"]]==counts,(r,counts)
 assert 0<=r["reach_dead_wall_confinement_pct"]<=100
 expected=round(100*r["dead_wall_reach_wait_tiles_total"]/r["remaining_when_reached_total"],4)
 assert abs(r["reach_dead_wall_confinement_pct"]-expected)<0.00006
league_den=sum(r["remaining_when_reached_total"] for r in rows)
league_num=sum(r["dead_wall_reach_wait_tiles_total"] for r in rows)
summary={"start_year":2025,"season":"2025-26","stages":"all",
 "players":len(rows),"eligible_accepted_reach_draws":len(selected),
 "wait_tiles_at_reach":league_den,"dead_wall_wait_tiles":league_num,
 "league_weighted_confinement_pct":round(100*league_num/league_den,4),
 "independent_event_checks":len(details),"ranking_top10":rows[:10]}
write_csv("reach_dead_wall_2025_26_all_stages.csv",rows)
write_json("reach_dead_wall_2025_26_top10.json",summary)
print("SEASON_VALIDATION",json.dumps({k:v for k,v in summary.items() if k!="ranking_top10"},ensure_ascii=False),flush=True)
print("SEASON_TOP10",json.dumps(rows[:10],ensure_ascii=False),flush=True)
