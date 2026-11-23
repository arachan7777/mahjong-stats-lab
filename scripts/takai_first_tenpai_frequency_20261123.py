#!/usr/bin/env python3
"""Read-only first-to-tenpai frequency; verified against official per-player kyoku counts."""
import sqlite3,sys,json,csv
from pathlib import Path
from collections import defaultdict

con=sqlite3.connect("file:"+sys.argv[1]+"?mode=ro",uri=True)
con.row_factory=sqlite3.Row
con.execute("PRAGMA query_only=ON")
con.execute("PRAGMA temp_store=MEMORY")
assert con.execute("PRAGMA quick_check").fetchone()[0]=="ok"

def query(sql,args=()):return [dict(r) for r in con.execute(sql,args)]
meta=query("SELECT COUNT(*) games, MIN(date) first_date, MAX(date) last_date FROM game")[0]
meta["kyoku"]=con.execute("SELECT COUNT(*) FROM kyoku").fetchone()[0]
assert (meta["games"],meta["kyoku"],meta["last_date"])==(2068,25238,"2026-11-20"),meta
players={x["id"]:x["name"] for x in query("SELECT id,name FROM player")}
base=query("SELECT player_name,season_start_year,stage,total_kyoku_count,total_game_count FROM player_season_stage_stats_base")
assert len({x["player_name"] for x in base})==56
assert sum(x["total_kyoku_count"] for x in base)==4*meta["kyoku"]
assert sum(x["total_game_count"] for x in base)==4*meta["games"]
# Events ordered within a round; first actor with an observed completed tenpai.
# Other-player tenpai records are excluded: they represent an ongoing tenpai, not its creation.
q="""
 SELECT e.kyoku_id,e.event_order,e.type,p.name player_name,
        ls.start_year year,ss.stage stage,ps.turn_number turn
 FROM player_tenpai_state pts
 JOIN event e ON e.id=pts.event_id
 JOIN player p ON p.id=pts.player_id
 JOIN player_state ps ON ps.event_id=e.id AND ps.player_id=pts.player_id
 JOIN kyoku k ON k.id=e.kyoku_id
 JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
 WHERE pts.is_actor=1 AND e.type IN ('haipai','discard')
 ORDER BY e.kyoku_id,e.event_order
"""
first=[]
lastky=-1
for r in con.execute(q):
 if r['kyoku_id']==lastky:continue
 lastky=r['kyoku_id']
 first.append(dict(r))
assert len(first)==25120,(len(first))
assert len({x["kyoku_id"] for x in first})==len(first)
assert all(0<=x['turn']<=25 for x in first)
# Counter per player/year/stage. Denominator matches the pre-existing official base-view
# per-player participations and works for partial seasons or teams changing.
first_bykey=defaultdict(list)
for x in first:
 first_bykey[(x["player_name"],x["year"],x["stage"])].append(x["turn"])
part_bykey={}
for b in base:
 key=(b["player_name"],b["season_start_year"],b["stage"])
 assert key not in part_bykey,key
 part_bykey[key]=(b["total_kyoku_count"],b["total_game_count"])
assert set(first_bykey).issubset(set(part_bykey)),set(first_bykey)-set(part_bykey)
assert all(len(rs)<=part_bykey[key][0] for key,rs in first_bykey.items())
def summary(year=None,stage=None,years=None):
 bag=defaultdict(lambda:{'kyoku':0,'games':0,'first':0,'turn_sum':0})
 for (name,y,st),(k,g) in part_bykey.items():
  if year is not None and y!=year: continue
  if stage is not None and st!=stage: continue
  if years is not None and y not in years: continue
  bag[name]['kyoku']+=k; bag[name]['games']+=g
  v=first_bykey.get((name,y,st),[])
  bag[name]['first']+=len(v);bag[name]['turn_sum']+=sum(v)
 arr=[]
 for name,b in bag.items():
  assert b["first"]<=b["kyoku"],(name,b)
  d={"name":name,**b,"first_rate":round(100*b["first"]/b["kyoku"],4),
     "first_avg_turn":round(b["turn_sum"]/b["first"],4) if b["first"] else None}
  arr.append(d)
 arr.sort(key=lambda z:(-z["first"]/z["kyoku"],-z["first"],z["name"]))
 for i,d in enumerate(arr):d["rank"]=i+1
 qualified=[d for d in arr if d["games"]>=50]
 for i,d in enumerate(qualified):d["rank_games_ge_50"]=i+1
 total_first=sum(d["first"] for d in arr)
 total_kyoku=sum(d["kyoku"] for d in arr)
 assert total_kyoku>0
 return {"league":{"first":total_first,"kyoku_participation":total_kyoku,
                   "rate":round(100*total_first/total_kyoku,4)},
         "players":len(arr),"qualified_ge50":len(qualified),
         "takai":next((d for d in arr if d["name"]=="多井隆晴"),None),
         "all_players":arr}
allx=summary()
assert allx["league"]["first"]==25120 and allx["league"]["kyoku_participation"]==100952
years=sorted({b["season_start_year"] for b in base})
annual={str(y):summary(year=y) for y in years}
regular={str(y):summary(year=y,stage="regular") for y in years}
stages={st:summary(stage=st) for st in sorted({b['stage'] for b in base})}
recent4=summary(years={2023,2024,2025,2026})
recent4_reg=summary(years={2023,2024,2025,2026},stage="regular")
assert allx["takai"]["first"]==872 and allx["takai"]["kyoku"]==3479
assert regular["2025"]["takai"]["first"]==109 and regular["2025"]["takai"]["kyoku"]==480
assert annual["2026"]["takai"]["first"]==44 and annual["2026"]["takai"]["kyoku"]==193
assert allx["takai"]["turn_sum"]==6993
assert sum(x["league"]["first"] for x in annual.values())==25120
assert sum(x["league"]["kyoku_participation"] for x in annual.values())==100952
out={"meta":meta,"source":"20261120-2341-04338cbb",
"definition":"player_tenpai_state actor initial tenpai: first per round, one winner of first to tenpai; divided by each player participation kyoku count from existing official base view",
"all":allx,"annual":annual,"annual_regular":regular,"stages":stages,
"recent4_2023_26":recent4,"recent4_regular_2023_26":recent4_reg}
Path("results").mkdir(exist_ok=True)
Path("results/takai_first_tenpai_frequency.json").write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
with open("results/first_tenpai_frequency_all_players.csv","w",encoding="utf-8-sig",newline="") as f:
 w=csv.DictWriter(f,fieldnames=list(allx["all_players"][0]));w.writeheader();w.writerows(allx["all_players"])
print("FREQUENCY_VERIFIED",json.dumps({"all":{"league":allx["league"],"takai":allx["takai"],"qualified_ge50":allx["qualified_ge50"]},
 "annual":{k:{"league":v["league"],"takai":v["takai"]} for k,v in annual.items()},
 "annual_regular":{k:{"league":v["league"],"takai":v["takai"]} for k,v in regular.items()},
 "recent4":{"league":recent4["league"],"takai":recent4["takai"]},
 "stages":{k:{"league":v["league"],"takai":v["takai"]} for k,v in stages.items()}},ensure_ascii=False),flush=True)
