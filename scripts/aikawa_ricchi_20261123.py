#!/usr/bin/env python3
"""2026-11-20 public DB: read-only audit for Aikawa and Murakami."""
import sqlite3,os,sys,json,csv
from pathlib import Path
from collections import defaultdict
db=os.path.abspath(sys.argv[1])
con=sqlite3.connect("file:"+db+"?mode=ro",uri=True)
con.row_factory=sqlite3.Row
con.execute("PRAGMA query_only=ON")
con.execute("PRAGMA temp_store=MEMORY")
assert con.execute("PRAGMA quick_check").fetchone()[0]=="ok"
def query(sql,params=()):
 return [dict(r) for r in con.execute(sql,params)]
def rate(n,d):
 return round(100*n/d,4) if d else None
P_NAMES=("逢川恵夢","村上淳")
meta=query("SELECT COUNT(*) games,MIN(date) first_date,MAX(date) last_date FROM game")[0]
meta["kyoku"]=con.execute("SELECT COUNT(*) FROM kyoku").fetchone()[0]
meta["events"]=con.execute("SELECT COUNT(*) FROM event").fetchone()[0]
assert (meta["games"],meta["kyoku"],meta["last_date"])==(2068,25238,"2026-11-20"),meta
players={p["id"]:p["name"] for p in query("SELECT id,name FROM player")}
ids={v:k for k,v in players.items()}
assert all(n in ids for n in P_NAMES)
# Each reach event is one declaration. Event-level audit in original SQL confirms
# is_accepted=0 iff declaration discard was ron (756/756 exact-event matches).
reach=query("""
 SELECT r.event_id,r.actor_player_id player_id,r.is_accepted,
   e.kyoku_id,e.event_order,ls.start_year year,ss.stage
 FROM reach_event r
 JOIN event e ON e.id=r.event_id
 JOIN kyoku k ON k.id=e.kyoku_id
 JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
 ORDER BY r.event_id
""")
assert len(reach)==22961,len(reach)
assert len({r["event_id"] for r in reach})==len(reach)
assert sum(r["is_accepted"]==0 for r in reach)==756
assert len(query("SELECT event_id FROM discard_event WHERE is_reach_declaration=1"))==22961

def summarize(rs):
 d=len(rs);n=sum(x["is_accepted"]==0 for x in rs)
 return {"num":n,"den":d,"pct":rate(n,d)}
def player_summaries(rows):
 bag=defaultdict(list)
 for z in rows:bag[z["player_id"]].append(z)
 out=[]
 for pid,rs in bag.items():
  t=summarize(rs);t.update(player_id=pid,name=players[pid]);out.append(t)
 out.sort(key=lambda x:(-x["pct"],-x["num"],-x["den"],x["name"]))
 for i,x in enumerate(out): x["rank"]=i+1
 return out

def pack(rows):
 league=summarize(rows);ranked=player_summaries(rows)
 return {"league":league,"players_count":len(ranked),
   "targets":{name:next((x for x in ranked if x["name"]==name),None) for name in P_NAMES}}

all_ranked=player_summaries(reach)
full=pack(reach)
assert len(all_ranked)==56
assert full["league"]["num"]==756 and full["league"]["den"]==22961
assert (full["targets"]["逢川恵夢"]["num"],full["targets"]["逢川恵夢"]["den"])==(12,130)
assert (full["targets"]["村上淳"]["num"],full["targets"]["村上淳"]["den"])==(13,374)
assert full["targets"]["逢川恵夢"]["rank"]==1
years=sorted({x["year"] for x in reach})
annual={str(y):pack([x for x in reach if x["year"]==y]) for y in years}
stages={stage:pack([x for x in reach if x["stage"]==stage]) for stage in sorted({x["stage"] for x in reach})}
target_year_stages={}
for name in P_NAMES:
 pid=ids[name]
 target_year_stages[name]=[]
 for y in years:
  for stage in sorted({x["stage"] for x in reach}):
   rr=[x for x in reach if x["year"]==y and x["stage"]==stage]
   pr=[x for x in rr if x["player_id"]==pid]
   if pr:
    sr=summarize(pr)
    sr.update(year=y,stage=stage,league=summarize(rr),players_count=len({r["player_id"] for r in rr}))
    sr["rank"]=next(x["rank"] for x in player_summaries(rr) if x["player_id"]==pid)
    target_year_stages[name].append(sr)
assert annual["2025"]["league"]["den"]>=3367
reg25=next(x for x in target_year_stages["逢川恵夢"] if x["year"]==2025 and x["stage"]=="regular")
assert (reg25["num"],reg25["den"],reg25["league"]["num"],reg25["league"]["den"])==(8,86,109,3367),reg25

# Official base aggregate view, same one used for the first Matsumoto profile.
base=query("SELECT * FROM player_season_stage_stats_base")
assert sum(x["total_game_count"] for x in base)==4*meta["games"]
assert sum(x["total_kyoku_count"] for x in base)==4*meta["kyoku"]
columns=["total_game_count","total_kyoku_count","agari_count","dealin_count","reach_count","furo_count",
         "rank1_count","rank2_count","rank3_count","rank4_count","tsumo_agari_count","reach_agari_count"]
def aggregate(rows):
 z={key:sum((r[key] or 0) for r in rows) for key in columns}
 g=z["total_game_count"];k=z["total_kyoku_count"]
 z.update(agari_pct=rate(z["agari_count"],k),dealin_pct=rate(z["dealin_count"],k),
          reach_pct=rate(z["reach_count"],k),furo_pct=rate(z["furo_count"],k),
          top_pct=rate(z["rank1_count"],g),
          avg_rank=round(sum(i*z["rank"+str(i)+"_count"] for i in (1,2,3,4))/g,4) if g else None)
 return z
base_target={}
for name in P_NAMES:
 rows=[r for r in base if r["player_name"]==name]
 base_target[name]={"all":aggregate(rows),"annual":{str(y):aggregate([r for r in rows if r["season_start_year"]==y])
             for y in sorted({r["season_start_year"] for r in rows})}}
assert base_target["逢川恵夢"]["all"]["total_game_count"]==40,base_target["逢川恵夢"]["all"]
# affiliation by actual game participation, not current player master team
team_records=query("""
 SELECT p.name player_name,ls.start_year year,t.name team,COUNT(*) games
 FROM game_player_result gr JOIN player p ON p.id=gr.player_id
 JOIN team t ON t.id=gr.team_id
 JOIN game g ON g.id=gr.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
 WHERE p.name IN ('逢川恵夢','村上淳')
 GROUP BY p.name,ls.start_year,t.name
 ORDER BY p.name,ls.start_year
""")
# Reach fulfillment: fulfilled accepted reach if same player wins after reach order.
accepted=[r for r in reach if r["is_accepted"]==1 and r["player_id"]==ids["逢川恵夢"]]
wins=query("""
 SELECT e.kyoku_id,e.event_order,e.type
 FROM agari_event a JOIN event e ON e.id=a.event_id
 WHERE a.actor_player_id=? AND e.type IN ('ron','tsumo')
""",(ids["逢川恵夢"],))
byky=defaultdict(list)
for w in wins:byky[w["kyoku_id"]].append(w)
success=[]
for r in accepted:
 matches=[w for w in byky[r["kyoku_id"]] if w["event_order"]>r["event_order"]]
 success.append({"year":r["year"],"stage":r["stage"],"success":int(bool(matches))})
reach_success={"all":{"fulfilled":sum(x["success"] for x in success),"accepted":len(success)},"annual":{}}
for y in sorted({x["year"] for x in success}):
 a=[x for x in success if x["year"]==y]
 reach_success["annual"][str(y)]={"fulfilled":sum(x["success"] for x in a),"accepted":len(a)}
for d in [reach_success["all"],*reach_success["annual"].values()]:d["pct"]=rate(d["fulfilled"],d["accepted"])
assert reach_success["all"]["accepted"]==118
# final reconciliation
assert sum(x["num"] for x in (annual[str(y)]["league"] for y in years))==756
assert sum(x["den"] for x in (annual[str(y)]["league"] for y in years))==22961
assert sum(x["num"] for x in (stages[s]["league"] for s in stages))==756
assert sum(x["den"] for x in (stages[s]["league"] for s in stages))==22961
result={"meta":meta,"source_tag":"20261120-2341-04338cbb",
 "definition":"リーチ宣言牌が相手にロンされた回数/リーチ宣言回数; declarer is_accepted=0 verified against 756 exact ron events",
 "overall":full,"annual":annual,"stages":stages,
 "target_year_stages":target_year_stages,"target_basic_stats":base_target,
 "target_team_seasons":team_records,"aikawa_reach_fulfillment":reach_success,
 "top10":all_ranked[:10],"all_players":all_ranked}
out=Path("results");out.mkdir(exist_ok=True)
(out/"aikawa_ricchi_murakami_report.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
for filename,rows in [("ricchi_all_players.csv",all_ranked),("aikawa_year_stages.csv",target_year_stages["逢川恵夢"]),
                      ("murakami_year_stages.csv",target_year_stages["村上淳"])]:
 if rows:
  with (out/filename).open("w",encoding="utf-8-sig",newline="") as f:
   w=csv.DictWriter(f,fieldnames=list(rows[0]))
   w.writeheader();w.writerows(rows)
print("SUCCESS",json.dumps({"scope":meta,"aikawa":full["targets"]["逢川恵夢"],"murakami":full["targets"]["村上淳"],"seasons":{k:v["targets"] for k,v in annual.items()}},ensure_ascii=False),flush=True)
