"""第13B派生指標 ジュンカラリーチ和了率 全リーチ独立検証。
第13 v0.2の正本（山・王牌ともに物理的0枚）を使用。
配牌、全ツモ、公開ドラを復元した第13 v0.1監査イベントの
strict_physical_zero=1を抽出し、別途和了イベントでロンを照合する。
"""
import csv,json,sqlite3,os,sys
from collections import defaultdict,Counter
from pathlib import Path
root=Path(__file__).resolve().parents[1]
out=Path("results");out.mkdir(exist_ok=True)
con=sqlite3.connect("file:"+os.path.abspath(sys.argv[1])+"?mode=ro",uri=True)
con.row_factory=sqlite3.Row
con.execute("PRAGMA temp_store=MEMORY")
assert con.execute("PRAGMA quick_check").fetchone()[0]=="ok"
def query(q):return [dict(x) for x in con.execute(q)]
def csvout(fn,rows):
 if not rows:return
 with (out/fn).open("w",encoding="utf-8-sig",newline="") as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def jsonout(fn,x):
 (out/fn).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding="utf-8")
src=out/"pure_empty_reach_v01_all_accepted_reach_events.csv"
assert src.exists(),"The original 136-tile independent reconstruction must run first"
with src.open("r",encoding="utf-8-sig",newline="") as f:
 all_riichi=list(csv.DictReader(f))
assert len(all_riichi)==22205
jun=[r for r in all_riichi if int(r["strict_physical_zero"])==1]
assert len(jun)==1086,len(jun)
assert all(int(r["physical_including_dora"])==0
           and int(r["available"])==0 and int(r["visible_dora"])==0 for r in jun)
ids={int(r["declaration_event_id"]) for r in jun}
assert len(ids)==len(jun)
reach_event_orders={r["id"]:(r["kyoku_id"],r["event_order"]) for r in query("""
 SELECT id,kyoku_id,event_order FROM event WHERE type='discard'
""") if r["id"] in ids}
assert len(reach_event_orders)==len(ids)
wins=defaultdict(list)
for row in query("""
 SELECT e.kyoku_id,e.event_order,e.type,a.actor_player_id AS player_id,
        a.target_player_id
 FROM agari_event a JOIN event e ON e.id=a.event_id
 ORDER BY e.kyoku_id,e.event_order
"""):
 assert row["type"] in ("ron","tsumo"),row
 wins[(row["kyoku_id"],row["player_id"])].append(row)
independent=[]
for j in jun:
 ky=int(j["kyoku_id"]);pid=int(j["player_id"]);eid=int(j["declaration_event_id"])
 assert reach_event_orders[eid][0]==ky
 moment=reach_event_orders[eid][1]
 matches=[r for r in wins[(ky,pid)] if r["event_order"]>moment]
 assert len(matches)<=1,("multiple wins by same player in kyoku",ky,pid,matches)
 ron=int(any(r["type"]=="ron" for r in matches))
 tsumo=int(any(r["type"]=="tsumo" for r in matches))
 independent.append({"kyoku_id":ky,"player_id":pid,"start_year":int(j["start_year"]),
  "declaration_event_id":eid,"waiting_tiles":j["waiting_tiles"],
  "ron_win":ron,"tsumo_win":tsumo,"win_actor_after_declaration":ron+tsumo,
  "result":"ron" if ron else ("tsumo" if tsumo else "not_won")})
assert all(x["tsumo_win"]==0 for x in independent),"Impossible tsumo win after physical-zero riichi"
assert len(independent)==len(jun)
sql=(root/"sql/junkara_reach_agari_v01.sql").read_text(encoding="utf-8")
standard="SELECT NULL AS start_year, NULL AS stage"
assert sql.count(standard)==1
cut=sql.index("SELECT p.id AS player_id")
sql_details=query(sql[:cut]+"""
SELECT player_id,kyoku_id,declaration_event_id,won_by_ron,won_by_tsumo
FROM junkara_with_results ORDER BY declaration_event_id
""")
assert len(sql_details)==len(independent),(len(sql_details),len(independent))
reconstructed={r["declaration_event_id"]:r for r in independent}
for x in sql_details:
 r=reconstructed.get(x["declaration_event_id"])
 assert r is not None,("SQL had non-junkara reach",x)
 assert x["player_id"]==r["player_id"] and x["kyoku_id"]==r["kyoku_id"]
 assert x["won_by_ron"]==r["ron_win"] and x["won_by_tsumo"]==r["tsumo_win"],(r,x)

by_player=defaultdict(Counter)
by_yr=defaultdict(Counter)
by_yr_player=defaultdict(lambda:defaultdict(Counter))
for r in independent:
 for bucket in (by_player[r["player_id"]],by_yr[r["start_year"]],
                by_yr_player[r["start_year"]][r["player_id"]]):
  bucket["junkara"]+=1
  bucket["ron"]+=r["ron_win"]
  bucket["tsumo"]+=r["tsumo_win"]
def check(rows,reference,label):
 assert len(rows)==len(reference),(label,len(rows),len(reference))
 for r in rows:
  b=reference[r["player_id"]]
  assert r["junkara_reach_count"]==b["junkara"],(label,r,"den",b)
  assert r["junkara_reach_ron_count"]==b["ron"],(label,r,"num",b)
  assert r["junkara_reach_tsumo_count"]==b["tsumo"],(label,r,"tsumo",b)
  assert abs(r["junkara_reach_agari_pct"]-round(100*b["ron"]/b["junkara"],4))<0.00006
rank=query(sql);check(rank,by_player,"all")
annual=[]
for year in sorted(by_yr):
 subset=query(sql.replace(standard,f"SELECT {year} AS start_year, NULL AS stage"))
 check(subset,by_yr_player[year],year)
 b=by_yr[year]
 annual.append({"season":f"{year}-{str(year+1)[-2:]}","junkara_reaches":b["junkara"],
                "ron_wins":b["ron"],"tsumo_wins":b["tsumo"],
                "agari_pct":round(100*b["ron"]/b["junkara"],4)})
 if year==2025:
  csvout("junkara_reach_agari_v01_2025_26_all_players.csv",subset)
  jsonout("junkara_reach_agari_v01_2025_26_top10.json",subset[:10])
  print("TOP10_2025_26",json.dumps(subset[:10],ensure_ascii=False),flush=True)
num=sum(x["ron_win"] for x in independent)
total=len(independent)
overall={"junkara_reaches":total,"ron_wins":num,
         "tsumo_wins":sum(x["tsumo_win"] for x in independent),
         "not_won":total-num,"agari_pct":round(100*num/total,4)}
summary={"sqlite_quick_check":"ok","original_riichi_verified":len(all_riichi),
 "physical_zero_riichi_reconstructed":total,
 "independent_event_winner_checks":len(independent),
 "player_ranking_checked":len(rank),
 "overall":overall,"annual":annual,
 "ranking_all_top10":rank[:10]}
csvout("junkara_reach_agari_v01_all_players.csv",rank)
csvout("junkara_reach_agari_v01_all_events.csv",independent)
jsonout("junkara_reach_agari_v01_validation.json",summary)
jsonout("junkara_reach_agari_v01_all_top10.json",rank[:10])
print("VALIDATION",json.dumps({k:v for k,v in summary.items() if k!="ranking_all_top10"},ensure_ascii=False),flush=True)
print("TOP10_ALL",json.dumps(rank[:10],ensure_ascii=False),flush=True)
print("RON_EXAMPLES",json.dumps([x for x in independent if x["ron_win"]][:10],ensure_ascii=False),flush=True)
