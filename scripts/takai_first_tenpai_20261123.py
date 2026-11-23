#!/usr/bin/env python3
"""First-to-tenpai audit; frozen 2026-11-20 M-League DB; read-only."""
import sqlite3,sys,json,csv
from pathlib import Path
from collections import defaultdict

con=sqlite3.connect("file:"+sys.argv[1]+"?mode=ro",uri=True)
con.row_factory=sqlite3.Row
con.execute("PRAGMA query_only=ON")
con.execute("PRAGMA temp_store=MEMORY")
assert con.execute("PRAGMA quick_check").fetchone()[0]=="ok"
def query(sql,params=()):
 return [dict(x) for x in con.execute(sql,params)]
meta=query("SELECT COUNT(*) games,MIN(date) first_date,MAX(date) last_date FROM game")[0]
meta["kyoku"]=con.execute("SELECT COUNT(*) FROM kyoku").fetchone()[0]
assert (meta["games"],meta["kyoku"],meta["last_date"])==(2068,25238,"2026-11-20"),meta
players={x["id"]:x["name"] for x in query("SELECT id,name FROM player")}
assert "多井隆晴" in players.values()
kyokus={x["kyoku_id"]:(x["year"],x["stage"]) for x in query("""
 SELECT k.id AS kyoku_id,ls.start_year AS year,ss.stage AS stage
 FROM kyoku k
 JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
""")}
# Actor tenpai is recorded directly at haipai and after own discard.
# Other players' ongoing tenpai-state rows are excluded to avoid false firsts.
q="""
 SELECT e.kyoku_id,e.event_order,e.type,
        pts.player_id,ps.turn_number,ps.is_menzen,ps.furo_count,ps.shanten_count
 FROM player_tenpai_state AS pts
 JOIN event e ON e.id=pts.event_id
 JOIN player_state ps ON ps.event_id=pts.event_id AND ps.player_id=pts.player_id
 WHERE pts.is_actor=1 AND e.type IN ('haipai','discard')
 ORDER BY e.kyoku_id,e.event_order
"""
first=[]
seen_k=-1
n_tenpai_rows=0
n_inconsistent=0
for r in con.execute(q):
 n_tenpai_rows+=1
 k,order,typ,pid,turn,menzen,furo,shanten=r
 if k==seen_k:continue
 seen_k=k
 if shanten!=0:n_inconsistent+=1
 assert turn>=0 and turn<=25,(k,turn)
 year,stage=kyokus[k]
 first.append({"kyoku_id":k,"year":year,"stage":stage,"player_id":pid,
               "name":players[pid],"turn":turn,"event_order":order,
               "is_menzen":int(menzen),"furo_count":furo,"event_type":typ})
assert n_inconsistent==0,n_inconsistent
assert len(first)==len({x["kyoku_id"] for x in first})
assert len(first)>20000,(len(first),meta["kyoku"])
# Cross-check a SQL window query against the Python earliest actor-tenpai event.
test=query("""
 WITH first_order AS (
 SELECT e.kyoku_id,MIN(e.event_order) AS first_event_order
 FROM player_tenpai_state pts JOIN event e ON e.id=pts.event_id
 WHERE pts.is_actor=1 AND e.type IN ('haipai','discard')
 GROUP BY e.kyoku_id
 )
 SELECT COUNT(*) n FROM first_order
""")[0]
assert test["n"]==len(first),(test["n"],len(first))
# Group statistics by varying scopes. Each player can win 'first to tenpai' once per round.
def summarize(rs):
 c=len(rs);total=sum(x["turn"] for x in rs)
 return {"count":c,"turn_total":total,"avg_turn":round(total/c,4) if c else None,
         "haipai_count":sum(x["event_type"]=="haipai" for x in rs),
         "menzen_count":sum(x["is_menzen"]==1 for x in rs),
         "furo_count":sum(x["is_menzen"]==0 for x in rs),
         "min_turn":min((x["turn"] for x in rs),default=None),
         "max_turn":max((x["turn"] for x in rs),default=None)}
def pack(rs):
 b=defaultdict(list)
 for r in rs:b[r["name"]].append(r)
 ranked=[]
 for name,rr in b.items():
  a=summarize(rr);a["name"]=name;ranked.append(a)
 ranked.sort(key=lambda a:(a["turn_total"]/a["count"],-a["count"],a["name"]))
 for i,a in enumerate(ranked):a["rank"]=i+1
 return {"league":summarize(rs),"players_count":len(ranked),
         "takai":next((z for z in ranked if z["name"]=="多井隆晴"),None),
         "all_players":ranked}
allp=pack(first)
annual={str(y):pack([r for r in first if r["year"]==y]) for y in sorted({r["year"] for r in first})}
stages={st:pack([r for r in first if r["stage"]==st]) for st in sorted({r["stage"] for r in first})}
annual_regular={str(y):pack([r for r in first if r["year"]==y and r["stage"]=="regular"]) for y in sorted({r["year"] for r in first})}
recent4=pack([r for r in first if 2023<=r["year"]<=2026])
recent4_reg=pack([r for r in first if 2023<=r["year"]<=2026 and r["stage"]=="regular"])
# Count game/round participation to support frequency comparisons in each period.
base=query("SELECT * FROM player_season_stage_stats_base")
assert sum(r["total_game_count"] for r in base)==4*meta["games"]
assert sum(r["total_kyoku_count"] for r in base)==4*meta["kyoku"]
takai_base=[r for r in base if r["player_name"]=="多井隆晴"]
def participation(rows):
 return {"games":sum(r["total_game_count"] for r in rows),
         "kyoku":sum(r["total_kyoku_count"] for r in rows)}
parts={"all":participation(takai_base),
       "recent4":participation([r for r in takai_base if 2023<=r["season_start_year"]<=2026]),
       "annual":{str(y):participation([r for r in takai_base if r["season_start_year"]==y])
                 for y in sorted({r["season_start_year"] for r in takai_base})},
       "annual_regular":{str(y):participation([r for r in takai_base if r["season_start_year"]==y and r["stage"]=="regular"])
                         for y in sorted({r["season_start_year"] for r in takai_base})}}
assert sum(r["count"] for r in (annual[str(y)]["league"] for y in sorted({r["year"] for r in first})))==len(first)
assert sum(r["count"] for r in (stages[st]["league"] for st in stages))==len(first)
assert sum(1 for r in first if r["name"]=="多井隆晴")==allp["takai"]["count"]
assert len(first)<=meta["kyoku"]
# Conditions can matter for comparison with a third-party time-slice.
result={"source_release":"20261120-2341-04338cbb","meta":meta,
        "definition":"earliest first own (haipai/discard) event where player_tenpai_state.is_actor=1 within kyoku; ps.turn_number; no other-player state rows",
        "actor_tenpai_state_rows":n_tenpai_rows,"first_tenpai_kyoku":len(first),
        "kyoku_without_observed_actor_tenpai":meta["kyoku"]-len(first),
        "all":allp,"annual":annual,"annual_regular":annual_regular,
        "stages":stages,"recent4_2023_2026":recent4,
        "recent4_regular_2023_2026":recent4_reg,"takai_participation":parts,
        "takai_first_tenpai_detail":[r for r in first if r["name"]=="多井隆晴"]}
out=Path("results");out.mkdir(exist_ok=True)
(out/"takai_first_tenpai_20261120.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
with (out/"all_players_first_tenpai.csv").open("w",encoding="utf-8-sig",newline="") as f:
 w=csv.DictWriter(f,fieldnames=list(allp["all_players"][0]));w.writeheader();w.writerows(allp["all_players"])
with (out/"takai_first_tenpai_detail.csv").open("w",encoding="utf-8-sig",newline="") as f:
 rr=result["takai_first_tenpai_detail"]
 w=csv.DictWriter(f,fieldnames=list(rr[0]));w.writeheader();w.writerows(rr)
print("AUDIT_OK",json.dumps({"meta":meta,"first_events":len(first),"actor_tenpai_rows":n_tenpai_rows,
 "all_league":allp["league"],"takai_all":allp["takai"],
 "recent4_league":recent4["league"],"recent4_takai":recent4["takai"],
 "reg_2025_league":annual_regular["2025"]["league"],
 "reg_2025_takai":annual_regular["2025"]["takai"],
 "annual":{y:{"takai":v["takai"],"league":v["league"]} for y,v in annual.items()},
 "part":parts},ensure_ascii=False),flush=True)
