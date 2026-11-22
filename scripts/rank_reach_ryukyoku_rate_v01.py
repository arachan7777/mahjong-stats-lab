"""第12指標「リーチ時流局率」全試合・全選手・年度別の独立検算。

SQL本体とは別の経路で全成立リーチのイベントIDを読み取り、流局局IDセットへ
照合する。各選手の分子分母、全体合計、2025-26年度の順位を確認する。
"""
import csv,json,os,sqlite3,sys
from pathlib import Path
from collections import defaultdict

root=Path(__file__).resolve().parents[1]
out=Path("results");out.mkdir(exist_ok=True)
c=sqlite3.connect("file:"+os.path.abspath(sys.argv[1])+"?mode=ro",uri=True)
c.row_factory=sqlite3.Row
c.execute("PRAGMA temp_store=MEMORY")
assert c.execute("PRAGMA quick_check").fetchone()[0]=="ok"
def query(q):return [dict(r) for r in c.execute(q)]
def save_csv(file,records):
 if not records:return
 with (out/file).open("w",newline="",encoding="utf-8-sig") as f:
  writer=csv.DictWriter(f,fieldnames=list(records[0]))
  writer.writeheader();writer.writerows(records)
def save_json(file,record):
 (out/file).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding="utf-8")

draws={r["kyoku_id"] for r in query("""
 SELECT e.kyoku_id
 FROM ryukyoku_event re JOIN event e ON e.id=re.event_id
""")}
accepted=query("""
 SELECT r.event_id AS reach_event_id,r.actor_player_id AS player_id,
        e.kyoku_id,ls.start_year,ss.stage
 FROM reach_event r
 JOIN event e ON e.id=r.event_id
 JOIN kyoku k ON k.id=e.kyoku_id
 JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
 WHERE r.is_accepted=1
 ORDER BY e.kyoku_id,r.event_id
""")
assert len({r["reach_event_id"] for r in accepted})==len(accepted)
assert len({(r["kyoku_id"],r["player_id"]) for r in accepted})==len(accepted),("duplicate riichi in same kyoku")
assert len(draws)>0 and len(accepted)>0
sql=(root/"sql/reach_ryukyoku_rate_v01.sql").read_text(encoding="utf-8")
original="SELECT NULL AS start_year, NULL AS stage"
assert sql.count(original)==1
all_rows=query(sql)
seasons=sorted(set(x["start_year"] for x in accepted))
assert len(all_rows)>=30
def check(ranking, subset,label):
 reference=defaultdict(lambda:[0,0])
 for e in subset:
  v=reference[e["player_id"]]
  v[0]+=1
  if e["kyoku_id"] in draws:v[1]+=1
 assert len(reference)==len(ranking),(label,"player_count",len(reference),len(ranking))
 all_den=all_num=0
 for row in ranking:
  pid=row["player_id"]
  assert pid in reference,(label,pid)
  den,num=reference[pid]
  assert row["accepted_reach_count"]==den,(label,pid,"den",row,reference[pid])
  assert row["reach_ryukyoku_count"]==num,(label,pid,"num",row,reference[pid])
  assert row["reach_non_ryukyoku_count"]==den-num,(label,pid,"other",row,reference[pid])
  assert abs(row["reach_ryukyoku_pct"]-round(100*num/den,4))<0.00006,(label,pid,"rate")
  all_den+=den;all_num+=num
 assert all_den==len(subset)
 assert all_num==sum(e["kyoku_id"] in draws for e in subset)
 return {"season":label,"players":len(ranking),"accepted_reach":all_den,
         "reach_then_ryukyoku":all_num,
         "reach_then_non_ryukyoku":all_den-all_num,
         "pct":round(100*all_num/all_den,4),
         "verified_individual_reach_events":len(subset)}

overall=check(all_rows,accepted,"all_years")
assert overall["accepted_reach"]==22205,(overall,"prior_verified_count_diverged")
assert overall["reach_then_ryukyoku"]==4420,(overall,"prior_riichi_deadwall_audit_diverged")
save_csv("reach_ryukyoku_v01_all_players_all_seasons.csv",all_rows)
annual=[]
for year in seasons:
 restricted=sql.replace(original,f"SELECT {year} AS start_year, NULL AS stage")
 rank=query(restricted)
 subset=[e for e in accepted if e["start_year"]==year]
 summary=check(rank,subset,f"{year}-{str(year+1)[-2:]}")
 annual.append(summary)
 if year==2025:
  save_csv("reach_ryukyoku_v01_2025_26_all_players.csv",rank)
  save_json("reach_ryukyoku_v01_2025_26_top10.json",rank[:10])
  print("TOP10_2025_26",json.dumps(rank[:10],ensure_ascii=False),flush=True)
save_csv("reach_ryukyoku_v01_by_season.csv",annual)
result={"sqlite_integrity":"ok","ryukyoku_kyoku_count":len(draws),
        "accepted_reach_event_ids_unique":True,"independent_all_player_event_match":True,
        "overall":overall,"by_season":annual,"top10_all":all_rows[:10]}
save_json("reach_ryukyoku_v01_verification.json",result)
save_json("reach_ryukyoku_v01_top10_all.json",all_rows[:10])
print("VALIDATION",json.dumps({"sqlite_integrity":result["sqlite_integrity"],"ryukyoku_kyoku_count":len(draws),"overall":overall,"by_season":annual},ensure_ascii=False),flush=True)
print("TOP10_ALL",json.dumps(all_rows[:10],ensure_ascii=False),flush=True)
