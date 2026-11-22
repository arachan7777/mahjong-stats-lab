"""第17指標『赤に愛された指数』の全局・全選手・年度別独立検証。

赤ドラは0m/0p/0sの現物だけを数える。通常/カンドラ指定は無関係。
直接イベントを時系列再生し、和了しない局や本場も1局単位で数える。
第15指標v0.2の赤ドラ総数と一致することも照合。
"""
import csv,json,os,sqlite3,sys
from collections import Counter,defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=Path("results");OUT.mkdir(exist_ok=True)
db=sqlite3.connect("file:"+os.path.abspath(sys.argv[1])+"?mode=ro",uri=True)
db.row_factory=sqlite3.Row
db.execute("PRAGMA temp_store=MEMORY")
assert db.execute("PRAGMA quick_check").fetchone()[0]=="ok"
def query(q):return [dict(r) for r in db.execute(q)]
def csvout(filename,rows):
 if rows:
  with (OUT/filename).open("w",newline="",encoding="utf-8-sig") as f:
   w=csv.DictWriter(f,fieldnames=list(rows[0]))
   w.writeheader();w.writerows(rows)
def jsonout(filename,obj):
 (OUT/filename).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
participants=query("""
 SELECT r.kyoku_id,r.player_id,ls.start_year,ss.stage,k.honba_count,k.round
 FROM kyoku_player_result r
 JOIN kyoku k ON k.id=r.kyoku_id
 JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
""")
assert len(participants)==100952,("unexpected data version",len(participants))
part={(x["kyoku_id"],x["player_id"]):x for x in participants}
assert len(part)==len(participants)
all_kyoku=Counter(x["kyoku_id"] for x in participants)
assert len(all_kyoku)==25238 and all(v==4 for v in all_kyoku.values())

counts=defaultdict(Counter)
color_sets=defaultdict(set)
source_total=Counter()
# Unlike SQL's per-event UNION, independently play relevant events sequentially.
events=db.execute("""
 SELECT e.id AS event_id,e.kyoku_id,e.event_order,e.type,
        h.actor_player_id AS hp,h.hand,
        d.actor_player_id AS dp,d.tile AS dt,
        c.actor_player_id AS cp,c.tile AS ct,
        p.actor_player_id AS pp,p.tile AS pt,
        m.actor_player_id AS mp,m.tile AS mt,
        a.actor_player_id AS ap,a.agari_tile AS atile
 FROM event e
 LEFT JOIN haipai_event h ON h.event_id=e.id AND e.type='haipai'
 LEFT JOIN draw_event d ON d.event_id=e.id AND e.type='draw'
 LEFT JOIN chi_event c ON c.event_id=e.id AND e.type='chi'
 LEFT JOIN pon_event p ON p.event_id=e.id AND e.type='pon'
 LEFT JOIN daiminkan_event m ON m.event_id=e.id AND e.type='daiminkan'
 LEFT JOIN agari_event a ON a.event_id=e.id AND e.type='ron'
 WHERE e.type IN ('haipai','draw','chi','pon','daiminkan','ron')
 ORDER BY e.kyoku_id,e.event_order,e.id
""")
n=0
haipai_seen=Counter()
for e in events:
 n+=1
 typ=e["type"]; ky=e["kyoku_id"]
 if typ=="haipai":
  player=e["hp"]
  tiles=e["hand"].split(",")
  assert len(tiles)==13,(ky,player,len(tiles))
  haipai_seen[(ky,player)]+=1
  candidates=tiles
 elif typ=="draw":
  player=e["dp"];candidates=[e["dt"]]
 elif typ=="chi":
  player=e["cp"];candidates=[e["ct"]]
 elif typ=="pon":
  player=e["pp"];candidates=[e["pt"]]
 elif typ=="daiminkan":
  player=e["mp"];candidates=[e["mt"]]
 elif typ=="ron":
  player=e["ap"];candidates=[e["atile"]]
 else:raise AssertionError(typ)
 key=(ky,player)
 assert key in part,key
 for t in candidates:
  t=t.strip()
  if t not in ("0m","0p","0s"):continue
  # A physical red five of each suit can reach one person at most once per kyoku.
  assert t not in color_sets[key],("same red tile duplicated for person",key,t)
  color_sets[key].add(t)
  bucket=counts[key]
  bucket["red_count"]+=1
  bucket[{"0m":"red_manzu_count","0p":"red_pinzu_count","0s":"red_souzu_count"}[t]]+=1
  bucket[{"haipai":"red_haipai_count","draw":"red_draw_count",
          "chi":"red_call_count","pon":"red_call_count",
          "daiminkan":"red_call_count","ron":"red_ron_count"}[typ]]+=1
  source_total[typ]+=1
assert n>150000,("few source events",n)
assert len(haipai_seen)==len(part) and all(v==1 for v in haipai_seen.values()),("haipai missing/dupe")

rows=[]
for p in participants:
 key=(p["kyoku_id"],p["player_id"])
 cnt=counts[key]
 assert 0<=cnt["red_count"]<=3,(key,cnt)
 assert cnt["red_count"]==sum(cnt[col] for col in ("red_manzu_count","red_pinzu_count","red_souzu_count"))
 assert cnt["red_count"]==sum(cnt[col] for col in ("red_haipai_count","red_draw_count","red_call_count","red_ron_count"))
 rows.append({**p,**{field:cnt[field] for field in (
   "red_count","red_manzu_count","red_pinzu_count","red_souzu_count",
   "red_haipai_count","red_draw_count","red_call_count","red_ron_count")}})
assert len(rows)==len(participants)

sql=(ROOT/"sql/aka_loved_per_kyoku_v01.sql").read_text(encoding="utf-8")
period="SELECT NULL AS start_year, NULL AS stage"
assert sql.count(period)==1
cut=sql.index("SELECT p.id AS player_id")
fields=("red_count","red_manzu_count","red_pinzu_count","red_souzu_count",
        "red_haipai_count","red_draw_count","red_call_count","red_ron_count")
each=query(sql[:cut]+"""
SELECT kyoku_id,player_id,
       red_count,red_manzu_count,red_pinzu_count,red_souzu_count,
       red_haipai_count,red_draw_count,red_call_count,red_ron_count
FROM by_kyoku_player
ORDER BY kyoku_id,player_id
""")
assert len(each)==len(rows)
ref={(x["kyoku_id"],x["player_id"]):x for x in rows}
for x in each:
 p=ref[(x["kyoku_id"],x["player_id"])]
 for f in fields:
  assert x[f]==p[f],("per-event source disagreement",x["kyoku_id"],x["player_id"],f,x[f],p[f])
 assert x["red_count"]<=3

def grouped(data):
 result=defaultdict(Counter)
 for p in data:
  d=result[p["player_id"]]
  d["played_kyoku_count"]+=1
  d["red_total_count"]+=p["red_count"]
  d["red_seen_kyoku_count"]+=int(p["red_count"]>=1)
  d["red_two_kyoku_count"]+=int(p["red_count"]==2)
  d["red_three_kyoku_count"]+=int(p["red_count"]==3)
  d["max_red_per_kyoku"]=max(d["max_red_per_kyoku"],p["red_count"])
  for col,name in (
   ("red_manzu_count","red_manzu_total"),("red_pinzu_count","red_pinzu_total"),
   ("red_souzu_count","red_souzu_total"),("red_haipai_count","red_haipai_total"),
   ("red_draw_count","red_draw_total"),("red_call_count","red_call_total"),
   ("red_ron_count","red_ron_total")):
   d[name]+=p[col]
 return result
def check(rank,data,label):
 results=grouped(data)
 assert len(rank)==len(results),(label,len(rank),len(results))
 for q in rank:
  b=results[q["player_id"]]
  for f,expected in b.items():
   assert q[f]==expected,(label,q["player_name"],f,q[f],expected)
  assert abs(q["aka_loved_per_kyoku"]-b["red_total_count"]/b["played_kyoku_count"])<.000051
  assert abs(q["aka_seen_kyoku_pct"]-100*b["red_seen_kyoku_count"]/b["played_kyoku_count"])<.000051
  assert b["max_red_per_kyoku"]<=3

rank=query(sql)
check(rank,rows,"all")
annual=[]
for year in sorted({x["start_year"] for x in rows}):
 yr_rows=[x for x in rows if x["start_year"]==year]
 yr_sql=query(sql.replace(period,f"SELECT {year} AS start_year, NULL AS stage"))
 check(yr_sql,yr_rows,str(year))
 tot=len(yr_rows);red=sum(x["red_count"] for x in yr_rows)
 nonzero=sum(x["red_count"]>0 for x in yr_rows)
 annual.append({"season":f"{year}-{str(year+1)[-2:]}",
   "player_kyoku":tot,"red_tiles_acquired":red,
   "red_per_player_kyoku":round(red/tot,4),"red_kyoku_pct":round(100*nonzero/tot,4)})
 if year==2025:
  csvout("aka_loved_v01_2025_26_all_players.csv",yr_sql)
  jsonout("aka_loved_v01_2025_26_top10.json",yr_sql[:10])
  print("TOP10_2025_26",json.dumps(yr_sql[:10],ensure_ascii=False),flush=True)
red=sum(x["red_count"] for x in rows)
assert red==57645,("does not reconcile with No.15 v0.2 red total",red)
hist=dict(sorted(Counter(x["red_count"] for x in rows).items()))
assert all(i in (0,1,2,3) for i in hist)
assert sum(hist.values())==len(rows)
assert sum(i*v for i,v in hist.items())==red
overall={"total_kyoku":len(all_kyoku),"player_kyoku":len(rows),
         "red_total":red,"red_per_player_kyoku":round(red/len(rows),4),
         "red_some_kyoku":sum(x["red_count"]>0 for x in rows),
         "red_some_kyoku_pct":round(100*sum(x["red_count"]>0 for x in rows)/len(rows),4),
         "red_count_histogram":hist,
         "by_origin":dict(source_total)}
summary={"sqlite_check":"ok","event_rows_independently_replayed":n,
         "all_100952_player_kyoku_checked":len(rows),
         "all_13_tile_initial_hands_checked":len(haipai_seen),
         "red_total_agrees_with_no15_v02":True,
         "player_and_season_sql_audit":"PASS","players":len(rank),
         "overall":overall,"annual":annual}
csvout("aka_loved_v01_all_players.csv",rank)
csvout("aka_loved_v01_per_kyoku_player.csv",rows)
jsonout("aka_loved_v01_validation.json",summary)
jsonout("aka_loved_v01_all_top10.json",rank[:10])
print("VALIDATION",json.dumps(summary,ensure_ascii=False),flush=True)
print("TOP10_ALL",json.dumps(rank[:10],ensure_ascii=False),flush=True)
# 完全ランキングから内川幸太郎選手の位置と比較対象期間を出力
for period_label,listing in (("ALL",rank),("2025_26",next((query(sql.replace(period,"SELECT 2025 AS start_year, NULL AS stage")) for _ in (0,)),[]))):
 for i,row in enumerate(listing,1):
  if row["player_name"]=="内川幸太郎":
   print("UCHIKAWA",json.dumps({"period":period_label,"rank":i,**row},ensure_ascii=False),flush=True)
