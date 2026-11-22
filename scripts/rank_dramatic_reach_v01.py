"""第18指標群 ドラマチックリーチ・成就率の独立全件検算。

リーチ宣言直後の1種類の待ちが、宣言時点までに公開された
表ドラ・カンドラである場合のみ認定。両面の高めドラなどは除外。
成立リーチ全件と本人の宣言後ロン/ツモを独立照合。
"""
import csv,json,os,sqlite3,sys
from collections import defaultdict,Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=Path("results");OUT.mkdir(exist_ok=True)
con=sqlite3.connect("file:"+os.path.abspath(sys.argv[1])+"?mode=ro",uri=True)
con.row_factory=sqlite3.Row
con.execute("PRAGMA temp_store=MEMORY")
assert con.execute("PRAGMA quick_check").fetchone()[0]=="ok"
def qry(s):return [dict(x) for x in con.execute(s)]
def csvout(name,rows):
 if rows:
  with (OUT/name).open("w",newline="",encoding="utf-8-sig") as f:
   w=csv.DictWriter(f,fieldnames=list(rows[0]))
   w.writeheader();w.writerows(rows)
def jsonout(name,o):
 (OUT/name).write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding="utf-8")
def normalize(t):
 t=t.strip()
 # 和了牌の原データにはツモ印 t（例: t2s）が先頭に付くことがある。
 if len(t)==3 and t[0] in ('t','r') and t[1] in '0123456789':
  t=t[1:]
 return '5'+t[1:] if t.startswith("0") else t

reaches=qry("""
 SELECT r.event_id AS reach_event_id,e.kyoku_id,e.event_order AS reach_order,
        r.actor_player_id AS player_id,
        ls.start_year,ss.stage
 FROM reach_event r
 JOIN event e ON e.id=r.event_id
 JOIN kyoku k ON k.id=e.kyoku_id
 JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
 WHERE r.is_accepted=1
""")
assert len(reaches)==22205,("base accepted reach count changed",len(reaches))
discards=qry("""
 SELECT e.kyoku_id,e.id,e.event_order,e.type,
        d.actor_player_id AS player_id,
        s.waiting_tiles,s.tile_type_count,s.waiting_type,
        s.available_tile_count,s.dora_indicator_tile_count,
        s.is_actor
 FROM discard_event d JOIN event e ON e.id=d.event_id
 JOIN player_tenpai_state s ON s.event_id=d.event_id
                          AND s.player_id=d.actor_player_id
 WHERE d.is_reach_declaration=1
""")
by_declare=defaultdict(list)
for d in discards:
 assert d["type"]=="discard" and d["is_actor"]==1
 by_declare[(d["kyoku_id"],d["player_id"])].append(d)

dora=qry("""
 SELECT e.kyoku_id,e.event_order,e.id,d.dora_type,d.dora_tile
 FROM dora_indicator_event d JOIN event e ON e.id=d.event_id
 WHERE d.dora_type='omote'
 ORDER BY e.kyoku_id,e.event_order,e.id
""")
by_dora=defaultdict(list)
for d in dora:
 by_dora[d["kyoku_id"]].append(d)

wins=qry("""
 SELECT e.kyoku_id,e.event_order,e.type,a.actor_player_id AS player_id,
        a.agari_tile,e.id AS win_event_id
 FROM agari_event a JOIN event e ON e.id=a.event_id
 ORDER BY e.kyoku_id,e.event_order
""")
by_win=defaultdict(list)
for w in wins:
 assert w["type"] in ('ron','tsumo')
 by_win[(w["kyoku_id"],w["player_id"])].append(w)

details=[]
n_highside=0
n_dora_after=0
for r in reaches:
 candidates=[d for d in by_declare[(r["kyoku_id"],r["player_id"])]
             if d["event_order"]>r["reach_order"]]
 assert len(candidates)==1,("declaration ambiguous",r,len(candidates))
 d=candidates[0]
 types=[normalize(v) for v in d["waiting_tiles"].split(",") if v.strip()]
 unique=set(types)
 assert len(unique)==d["tile_type_count"],("waiting tile count mismatch",r,d,types)
 assert len(unique)>=1
 active={normalize(v["dora_tile"]) for v in by_dora[r["kyoku_id"]]
         if v["event_order"]<=d["event_order"]}
 future={normalize(v["dora_tile"]) for v in by_dora[r["kyoku_id"]]
         if v["event_order"]>d["event_order"]}
 dramatic=int(len(unique)==1 and d["waiting_type"]!='複合形'
              and next(iter(unique)) in active)
 if len(unique)>=2 and (unique & active):n_highside+=1
 if len(unique)==1 and not dramatic and next(iter(unique)) in future:n_dora_after+=1
 matching=[w for w in by_win[(r["kyoku_id"],r["player_id"])]
           if w["event_order"]>d["event_order"]]
 assert len(matching)<=1,("one player won more than once",r,matching)
 win_type=matching[0]["type"] if matching else None
 if dramatic and matching:
  assert normalize(matching[0]["agari_tile"]) in unique,("won on unexpected tile",r,d,matching)
 details.append({
  "kyoku_id":r["kyoku_id"],"player_id":r["player_id"],
  "start_year":r["start_year"],"stage":r["stage"],
  "reach_event_id":r["reach_event_id"],
  "declaration_event_id":d["id"],
  "waiting_tiles":d["waiting_tiles"],"waiting_type":d["waiting_type"],
  "public_omote_dora_at_reach":','.join(sorted(active)),
  "dramatic_reach":dramatic,
  "own_agari":int(bool(matching)),
  "dramatic_agari":int(dramatic and bool(matching)),
  "dramatic_ron":int(dramatic and win_type=='ron'),
  "dramatic_tsumo":int(dramatic and win_type=='tsumo')
 })
assert len(details)==len(reaches)
assert len({d["declaration_event_id"] for d in details})==len(details)
sql=(ROOT/"sql/dramatic_reach_v01.sql").read_text(encoding="utf-8")
param="SELECT NULL AS start_year, NULL AS stage"
assert sql.count(param)==1
cut=sql.index("SELECT p.id AS player_id")
event_sql=qry(sql[:cut]+"""
SELECT kyoku_id,player_id,declaration_event_id,waiting_tiles,waiting_type,
       is_dramatic_reach,own_agari,own_ron,own_tsumo
FROM reach_outcomes ORDER BY declaration_event_id
""")
assert len(event_sql)==len(details),("SQL event count",len(event_sql),len(details))
indep={d["declaration_event_id"]:d for d in details}
for s in event_sql:
 x=indep.get(s["declaration_event_id"])
 assert x is not None,("unknown reach",s)
 assert s["player_id"]==x["player_id"] and s["kyoku_id"]==x["kyoku_id"]
 assert s["waiting_tiles"]==x["waiting_tiles"]
 assert s["waiting_type"]==x["waiting_type"]
 assert s["is_dramatic_reach"]==x["dramatic_reach"],("classification",s,x)
 assert s["own_agari"]==x["own_agari"],("win",s,x)
 assert s["own_ron"]==int(x["own_agari"] and x["dramatic_ron"] if x["dramatic_reach"] else any(
  w["type"]=="ron" and w["event_order"]>next(d["event_order"] for d in by_declare[(x["kyoku_id"],x["player_id"])] if d["id"]==x["declaration_event_id"])
  for w in by_win[(x["kyoku_id"],x["player_id"])])
 ),("ron",s,x)
 assert s["own_tsumo"]==s["own_agari"]-s["own_ron"],("ron+tsumo",s)

def grouped(rows):
 out=defaultdict(Counter)
 for d in rows:
  b=out[d["player_id"]]
  b["accepted"]+=1
  b["dramatic"]+=d["dramatic_reach"]
  b["agari"]+=d["dramatic_agari"]
  b["ron"]+=d["dramatic_ron"]
  b["tsumo"]+=d["dramatic_tsumo"]
 return out

def check(rank,reference,label):
 assert len(rank)==len(reference),(label,len(rank),len(reference))
 for x in rank:
  b=reference[x["player_id"]]
  for column,key in [
   ("accepted_reach_count","accepted"),("dramatic_reach_count","dramatic"),
   ("dramatic_agari_count","agari"),("dramatic_ron_count","ron"),
   ("dramatic_tsumo_count","tsumo")]:
   assert x[column]==b[key],(label,x["player_name"],column,x[column],b[key])
  assert abs(x["dramatic_reach_pct"]-100*b["dramatic"]/b["accepted"])<.000051
  if b["dramatic"]:
   assert abs(x["dramatic_success_pct"]-100*b["agari"]/b["dramatic"])<.000051
  else:assert x["dramatic_success_pct"] is None
  assert b["agari"]==b["ron"]+b["tsumo"]

rank=qry(sql)
check(rank,grouped(details),"all")
annual=[]
for year in sorted({d["start_year"] for d in details}):
 subset=[d for d in details if d["start_year"]==year]
 yr=qry(sql.replace(param,f"SELECT {year} AS start_year, NULL AS stage"))
 check(yr,grouped(subset),f"{year}")
 n=len(subset)
 dr=sum(x["dramatic_reach"] for x in subset)
 w=sum(x["dramatic_agari"] for x in subset)
 annual.append({"season":f"{year}-{str(year+1)[-2:]}",
  "accepted_reaches":n,"dramatic_reaches":dr,
  "dramatic_reach_pct":round(100*dr/n,4),
  "dramatic_wins":w,
  "dramatic_success_pct":round(100*w/dr,4) if dr else None,
  "ron":sum(x["dramatic_ron"] for x in subset),
  "tsumo":sum(x["dramatic_tsumo"] for x in subset)})
 if year==2025:
  csvout("dramatic_reach_v01_2025_26_all_players.csv",yr)
  jsonout("dramatic_reach_v01_2025_26_top10.json",yr[:10])
  print("TOP10_2025_26",json.dumps(yr[:10],ensure_ascii=False),flush=True)

number=len(details)
dramatic=sum(x["dramatic_reach"] for x in details)
wins_count=sum(x["dramatic_agari"] for x in details)
assert sum(x["dramatic_ron"]+x["dramatic_tsumo"] for x in details)==wins_count
overall={"accepted_reach_count":number,"dramatic_reach_count":dramatic,
         "dramatic_reach_pct":round(100*dramatic/number,4),
         "dramatic_agari_count":wins_count,
         "dramatic_success_pct":round(100*wins_count/dramatic,4) if dramatic else None,
         "dramatic_ron":sum(x["dramatic_ron"] for x in details),
         "dramatic_tsumo":sum(x["dramatic_tsumo"] for x in details),
         "all_accepted_multiwait_with_any_dora":n_highside,
         "singlewait_matches_future_dora_not_yet_public":n_dora_after}
result={"sqlite_check":"ok","independent_declared_reaches_verified":number,
        "all_player_and_season_sql_audit":"PASS","players":len(rank),
        "overall":overall,"annual":annual}
csvout("dramatic_reach_v01_all_players.csv",rank)
csvout("dramatic_reach_v01_all_events.csv",details)
jsonout("dramatic_reach_v01_top10_by_reach_pct.json",rank[:10])
jsonout("dramatic_reach_v01_top10_by_success.json",sorted((x for x in rank if x["dramatic_reach_count"]),
key=lambda x:(-x["dramatic_success_pct"],-x["dramatic_agari_count"],x["player_name"]))[:10])
jsonout("dramatic_reach_v01_verification.json",result)
print("VALIDATION",json.dumps(result,ensure_ascii=False),flush=True)
print("TOP10_BY_REACH_RATE",json.dumps(rank[:10],ensure_ascii=False),flush=True)
print("TOP10_BY_SUCCESS_RATE",json.dumps(sorted((x for x in rank if x["dramatic_reach_count"]),
key=lambda x:(-x["dramatic_success_pct"],-x["dramatic_agari_count"],x["player_name"]))[:10],ensure_ascii=False),flush=True)
