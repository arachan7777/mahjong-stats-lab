"""第13指標 v0.2: 成立リーチ時点で生きた山にも王牌にも当たり牌が0枚。

v0.1で独立再構成した配牌・全ツモ・表示ドラの22,205件の原明細を
参照し、v0.2のSQLに対して全宣言打牌・全選手・全年度を再照合する。
v0.1自身をこのプログラムより先に同じDBで再実行すること。
"""
import csv, json, os, sqlite3, sys
from collections import defaultdict,Counter
from pathlib import Path
root=Path(__file__).resolve().parents[1]
out=Path("results");out.mkdir(exist_ok=True)
c=sqlite3.connect("file:"+os.path.abspath(sys.argv[1])+"?mode=ro",uri=True)
c.row_factory=sqlite3.Row
c.execute("PRAGMA temp_store=MEMORY")
assert c.execute("PRAGMA quick_check").fetchone()[0]=="ok"
def query(s):return [dict(r) for r in c.execute(s)]
def csvout(name,rows):
 if not rows:return
 with (out/name).open("w",encoding="utf-8-sig",newline="") as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]))
  w.writeheader();w.writerows(rows)
def jsonout(name,obj):(out/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
path=out/"pure_empty_reach_v01_all_accepted_reach_events.csv"
assert path.exists(),"Run full independent reconstruction audit script v0.1 first"
with path.open("r",encoding="utf-8-sig",newline="") as f:
 original=list(csv.DictReader(f))
assert original and len(original)==22205,len(original)
events={}
for r in original:
 eid=int(r["declaration_event_id"])
 assert eid not in events,eid
 assert int(r["physical_including_dora"])==int(r["available"])+int(r["visible_dora"])
 assert int(r["strict_physical_zero"])==int(int(r["physical_including_dora"])==0)
 assert int(r["pure"])==int(int(r["available"])==0)
 assert int(r["dora_only"])==int(int(r["available"])==0 and int(r["visible_dora"])>0)
 events[eid]=r

sql=(root/"sql/pure_empty_reach_v02.sql").read_text(encoding="utf-8")
standard="SELECT NULL AS start_year, NULL AS stage"
assert sql.count(standard)==1
cut=sql.index("SELECT p.id AS player_id")
details=query(sql[:cut]+"""
SELECT player_id,kyoku_id,declaration_event_id,available_tile_count,
       dora_indicator_tile_count
FROM declaration_states
ORDER BY declaration_event_id
""")
assert len(details)==len(events),(len(details),len(events))
for d in details:
 eid=d["declaration_event_id"]
 assert eid in events,("unexpected",eid)
 r=events[eid]
 assert d["player_id"]==int(r["player_id"])
 assert d["kyoku_id"]==int(r["kyoku_id"])
 assert d["available_tile_count"]==int(r["available"])
 assert d["dora_indicator_tile_count"]==int(r["visible_dora"])
 assert int(d["available_tile_count"]==0 and d["dora_indicator_tile_count"]==0)==int(r["strict_physical_zero"])

ranking=query(sql)
by_player=defaultdict(Counter)
by_year=defaultdict(Counter)
by_year_player=defaultdict(lambda:defaultdict(Counter))
for r in original:
 p=int(r["player_id"]);y=int(r["start_year"])
 strict=int(r["strict_physical_zero"]); broader=int(r["pure"]);doraonly=int(r["dora_only"])
 for bucket in (by_player[p],by_year[y],by_year_player[y][p]):
  bucket["accepted"]+=1
  bucket["strict"]+=strict
  bucket["broader"]+=broader
  bucket["doraonly"]+=doraonly
def check(rows,reference,label):
 assert len(rows)==len(reference),(label,len(rows),len(reference))
 for r in rows:
  b=reference[r["player_id"]]
  assert r["accepted_reach_count"]==b["accepted"],(label,r["player_name"],"accepted")
  assert r["pure_empty_reach_count"]==b["strict"],(label,r["player_name"],"strict")
  assert r["zero_excluding_visible_dora_count"]==b["broader"],(label,r["player_name"],"broader")
  assert r["visible_dora_only_count"]==b["doraonly"],(label,r["player_name"],"doraonly")
  assert b["broader"]==b["strict"]+b["doraonly"]
  assert abs(r["pure_empty_reach_pct"]-round(100*b["strict"]/b["accepted"],4))<.00006
check(ranking,by_player,"all")
by_season=[]
for year in sorted(by_year):
 rows=query(sql.replace(standard,f"SELECT {year} AS start_year, NULL AS stage"))
 check(rows,by_year_player[year],year)
 b=by_year[year]
 summary={"start_year":year,"season":f"{year}-{str(year+1)[-2:]}",
          "accepted":b["accepted"],"true_junkara":b["strict"],
          "visible_dora_only_excluded":b["doraonly"],
          "old_broader_zero_count":b["broader"],
          "rate_pct":round(100*b["strict"]/b["accepted"],4)}
 by_season.append(summary)
 if year==2025:
  csvout("pure_empty_reach_v02_2025_26_all_players.csv",rows)
  jsonout("pure_empty_reach_v02_2025_26_top10.json",rows[:10])
  print("TOP10_2025_26",json.dumps(rows[:10],ensure_ascii=False),flush=True)
allaccepted=sum(b["accepted"] for b in by_player.values())
allstrict=sum(b["strict"] for b in by_player.values())
allold=sum(b["broader"] for b in by_player.values())
alldora=sum(b["doraonly"] for b in by_player.values())
assert (allaccepted,allstrict,allold,alldora)==(22205,1086,1150,64),(allaccepted,allstrict,allold,alldora)
assert by_year[2025]["strict"]==160
overall={"accepted":allaccepted,"true_junkara":allstrict,
         "excluded_visible_dora_only":alldora,"old_broader_zero_count":allold,
         "rate_pct":round(100*allstrict/allaccepted,4)}
summary={"sqlite_check":"ok","all_declaration_events_revalidated":len(details),
         "players":len(ranking),"overall":overall,"annual":by_season,
         "validated_against":"Independent full 136-tile hand/draw/dora reconstruction in v0.1"}
csvout("pure_empty_reach_v02_all_players.csv",ranking)
jsonout("pure_empty_reach_v02_verification.json",summary)
jsonout("pure_empty_reach_v02_top10_all.json",ranking[:10])
print("VALIDATION",json.dumps(summary,ensure_ascii=False),flush=True)
print("TOP10_ALL",json.dumps(ranking[:10],ensure_ascii=False),flush=True)
