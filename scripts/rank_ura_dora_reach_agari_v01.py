"""第14指標群 裏ドラ乗り回数・率・総枚数・的中時平均の全件独立検算。

SQLとは別のイベント列で全成立リーチと全和了を突合し、
裏ドラ役の翻数を和了イベントごとに独立に合算する。
全選手・年度別および1回あたり裏ドラ枚数分布を照合する。
"""
import csv,json,os,sqlite3,sys
from collections import defaultdict,Counter
from pathlib import Path
root=Path(__file__).resolve().parents[1]
out=Path("results");out.mkdir(exist_ok=True)
c=sqlite3.connect("file:"+os.path.abspath(sys.argv[1])+"?mode=ro",uri=True)
c.row_factory=sqlite3.Row
c.execute("PRAGMA temp_store=MEMORY")
assert c.execute("PRAGMA quick_check").fetchone()[0]=="ok"
def query(q):return [dict(r) for r in c.execute(q)]
def csvout(name,records):
 if not records:return
 with (out/name).open("w",encoding="utf-8-sig",newline="") as f:
  writer=csv.DictWriter(f,fieldnames=list(records[0]));writer.writeheader();writer.writerows(records)
def jsonout(name,record):
 (out/name).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding="utf-8")

names=query("SELECT id,name,name_furigana FROM yaku_name WHERE name LIKE '%裏%' OR name_furigana LIKE '%ウラ%'")
assert len([y for y in names if y["name"]=="裏ドラ"])==1,("裏ドラ役名を特定できない",names)
ura_id=next(y["id"] for y in names if y["name"]=="裏ドラ")
accepted=query("""
 SELECT r.event_id AS reach_event_id,r.actor_player_id AS player_id,
        e.kyoku_id,e.event_order AS reach_order,
        ls.start_year,ss.stage
 FROM reach_event r JOIN event e ON e.id=r.event_id
 JOIN kyoku k ON k.id=e.kyoku_id
 JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
 WHERE r.is_accepted=1
""")
reachby={}
for r in accepted:
 key=(r["kyoku_id"],r["player_id"])
 assert key not in reachby,key
 reachby[key]=r
assert len(accepted)==22205,(len(accepted),"historic denominator changed")
wins=query("""
 SELECT a.event_id AS agari_event_id,a.actor_player_id AS player_id,
        e.kyoku_id,e.event_order AS agari_order,e.type AS agari_type,
        ls.start_year
 FROM agari_event a JOIN event e ON e.id=a.event_id
 JOIN kyoku k ON k.id=e.kyoku_id
 JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
""")
ura_per_agari=defaultdict(int)
all_yaku_rows=query("SELECT agari_event_id,yaku_name_id,han FROM agari_yaku")
for y in all_yaku_rows:
 if y["yaku_name_id"]==ura_id:
  assert y["han"]>0,y
  ura_per_agari[y["agari_event_id"]]+=y["han"]
events=[]
allura_wins=0
for w in wins:
 if ura_per_agari[w["agari_event_id"]]>0:allura_wins+=1
 r=reachby.get((w["kyoku_id"],w["player_id"]))
 if r is None or w["agari_order"]<=r["reach_order"]:
  assert ura_per_agari[w["agari_event_id"]]==0,("裏ドラがあるのに成立リーチがない和了",w)
  continue
 count=ura_per_agari[w["agari_event_id"]]
 events.append({"agari_event_id":w["agari_event_id"],"kyoku_id":w["kyoku_id"],
  "player_id":w["player_id"],"start_year":w["start_year"],
  "agari_type":w["agari_type"],"ura_tiles":count,
  "ura_hit":int(count>=1),"ura_multi_hit":int(count>=2),
  "reach_event_id":r["reach_event_id"]})
assert len({e["agari_event_id"] for e in events})==len(events)
assert sum(x["ura_hit"] for x in events)==allura_wins
assert len(events)>5000,len(events)

sql=(root/"sql/ura_dora_reach_agari_v01.sql").read_text(encoding="utf-8")
period="SELECT NULL AS start_year, NULL AS stage"
assert sql.count(period)==1
i=sql.index("SELECT p.id AS player_id")
event_rows=query(sql[:i]+"""
SELECT agari_event_id,kyoku_id,player_id,agari_type,ura_tiles
FROM scored_reach_agari ORDER BY agari_event_id
""")
assert len(event_rows)==len(events),("Event count mismatch",len(event_rows),len(events))
by_event={x["agari_event_id"]:x for x in events}
for q in event_rows:
 original=by_event[q["agari_event_id"]]
 assert q["kyoku_id"]==original["kyoku_id"]
 assert q["player_id"]==original["player_id"]
 assert q["agari_type"]==original["agari_type"]
 assert q["ura_tiles"]==original["ura_tiles"],(q,original)

def aggregate(records):
 d=defaultdict(Counter)
 for r in records:
  v=d[r["player_id"]]
  v["reach_agari_count"]+=1
  v["ura_hit_agari_count"]+=r["ura_hit"]
  v["ura_total_tiles"]+=r["ura_tiles"]
  v["ura_multi_hit_count"]+=r["ura_multi_hit"]
  v["ura_max_tiles_in_agari"]=max(v["ura_max_tiles_in_agari"],r["ura_tiles"])
 return d
def check(rows,ref,label):
 assert len(rows)==len(ref),(label,len(rows),len(ref))
 for q in rows:
  b=ref[q["player_id"]]
  for k in ("reach_agari_count","ura_hit_agari_count","ura_total_tiles",
            "ura_multi_hit_count","ura_max_tiles_in_agari"):
   assert q[k]==b[k],(label,q["player_name"],k,q[k],b[k])
  assert abs(q["ura_hit_rate_pct"]-round(100*b["ura_hit_agari_count"]/b["reach_agari_count"],4))<0.00006
  conditional=round(b["ura_total_tiles"]/b["ura_hit_agari_count"],4) if b["ura_hit_agari_count"] else None
  if conditional is None:assert q["ura_avg_tiles_when_hit"] is None
  else:assert abs(q["ura_avg_tiles_when_hit"]-conditional)<0.00006
ranking=query(sql)
check(ranking,aggregate(events),"overall")
years=sorted(set(r["start_year"] for r in accepted))
annual=[]
for year in years:
 selected=[v for v in events if v["start_year"]==year]
 yr=query(sql.replace(period,f"SELECT {year} AS start_year, NULL AS stage"))
 check(yr,aggregate(selected),str(year))
 n=len(selected);hits=sum(x["ura_hit"] for x in selected)
 tiles=sum(x["ura_tiles"] for x in selected)
 multi=sum(x["ura_multi_hit"] for x in selected)
 annual.append({"season":f"{year}-{str(year+1)[-2:]}",
    "reach_wins":n,"ura_hit_wins":hits,"ura_total_tiles":tiles,
    "hit_rate_pct":round(100*hits/n,4) if n else None,
    "avg_tiles_per_hit":round(tiles/hits,4) if hits else None,
    "multi_hit_wins":multi})
 if year==2025:
  csvout("ura_dora_v01_2025_26_all_players.csv",yr)
  jsonout("ura_dora_v01_2025_26_top10_hit_rate.json",yr[:10])
  print("TOP10_2025_26",json.dumps(yr[:10],ensure_ascii=False),flush=True)
allN=len(events);hits=sum(x["ura_hit"] for x in events);tiles=sum(x["ura_tiles"] for x in events)
hist=dict(sorted(Counter(x["ura_tiles"] for x in events).items()))
overall={"all_accepted_reaches":len(accepted),"reach_wins":allN,"ura_hit_wins":hits,
 "ura_total_tiles":tiles,"ura_no_hit_wins":allN-hits,
 "ura_hit_rate_pct":round(100*hits/allN,4),
 "avg_tiles_per_hit":round(tiles/hits,4),"multi_hit_wins":sum(x["ura_multi_hit"] for x in events),
 "tiles_per_reach_win":round(tiles/allN,4),
 "ura_tiles_distribution":hist,
 "ura_name_matches":names}
assert sum(int(k)*v for k,v in hist.items())==tiles
assert sum(hist.values())==allN
assert sum(x["ura_hit_agari_count"] for x in ranking)==hits
assert sum(x["reach_agari_count"] for x in ranking)==allN
csvout("ura_dora_v01_all_players.csv",ranking)
csvout("ura_dora_v01_all_reach_wins.csv",events)
jsonout("ura_dora_v01_all_top10_by_hit_rate.json",ranking[:10])
jsonout("ura_dora_v01_verification.json",{"overall":overall,"annual":annual,
 "all_reach_win_events_independently_checked":len(events),
 "players":len(ranking),"sqlite_check":"ok"})
print("VALIDATION",json.dumps({"overall":overall,"annual":annual,
 "all_reach_win_events_independently_checked":len(events),
 "players":len(ranking),"sqlite_check":"ok"},ensure_ascii=False),flush=True)
print("TOP10_ALL",json.dumps(ranking[:10],ensure_ascii=False),flush=True)
print("TOP10_COUNT",json.dumps(sorted(ranking,key=lambda x:(-x["ura_hit_agari_count"],-x["reach_agari_count"],x["player_name"]))[:10],ensure_ascii=False),flush=True)
print("TOP10_CONDITIONAL",json.dumps(sorted((x for x in ranking if x["ura_hit_agari_count"]>0),key=lambda x:(-x["ura_avg_tiles_when_hit"],-x["ura_hit_agari_count"],x["player_name"]))[:10],ensure_ascii=False),flush=True)
