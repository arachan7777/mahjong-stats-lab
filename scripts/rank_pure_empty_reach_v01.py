"""第13指標ジュンカラリーチ率の独立検証。
対象の成立リーチを自力で列挙し、牌譜から配牌、リーチ時点までの
全ツモと公開ドラを復元。残存牌0枚判定の全イベント・全選手・各年度を比較する。
"""
import os,sys,sqlite3,json,csv
from collections import defaultdict,Counter
from pathlib import Path

c=sqlite3.connect("file:"+os.path.abspath(sys.argv[1])+"?mode=ro",uri=True)
c.row_factory=sqlite3.Row
c.execute("PRAGMA temp_store=MEMORY")
root=Path(__file__).resolve().parents[1]
out=Path("results");out.mkdir(exist_ok=True)
assert c.execute("PRAGMA quick_check").fetchone()[0]=="ok"
def query(s):return [dict(x) for x in c.execute(s)]
def norm(x):
 x=x.strip()
 if x.startswith("t"):x=x[1:]
 return "5"+x[1:] if x.startswith("0") else x
def tiles(x):return [norm(t) for t in x.split(",") if t.strip()]
def csvout(fn,rows):
 if rows:
  with (out/fn).open("w",encoding="utf-8-sig",newline="") as f:
   w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def jsonout(fn,o):(out/fn).write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding="utf-8")

base=Counter({f"{i}{s}":4 for s in "mps" for i in range(1,10)})
base.update({f"{i}z":4 for i in range(1,8)})
accepted=query("""
 SELECT re.id AS reach_event_id,re.kyoku_id,re.event_order AS reach_order,
        r.actor_player_id AS player_id,ls.start_year,ss.stage
 FROM reach_event r
 JOIN event re ON re.id=r.event_id
 JOIN kyoku k ON k.id=re.kyoku_id
 JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
 WHERE r.is_accepted=1
 ORDER BY re.kyoku_id,re.event_order
""")
kyokus={x["kyoku_id"] for x in accepted}
assert len(accepted)==22205,(len(accepted),"prior validated denominator mismatch")
assert len({(x["kyoku_id"],x["player_id"]) for x in accepted})==len(accepted)
flags=query("""
 SELECT e.id AS declaration_event_id,e.kyoku_id,e.event_order AS discard_order,
        d.actor_player_id AS player_id,
        pts.waiting_tiles,pts.available_tile_count,
        pts.dora_indicator_tile_count,pts.is_actor
 FROM discard_event d JOIN event e ON e.id=d.event_id
 LEFT JOIN player_tenpai_state pts ON pts.event_id=e.id AND pts.player_id=d.actor_player_id
 WHERE d.is_reach_declaration=1
 ORDER BY e.kyoku_id,e.event_order
""")
flagby=defaultdict(list)
for r in flags:
 if r["kyoku_id"] in kyokus:flagby[(r["kyoku_id"],r["player_id"])].append(r)
hands=defaultdict(Counter);draws=defaultdict(list);doras=defaultdict(list)
for h in c.execute("SELECT e.kyoku_id,h.hand FROM haipai_event h JOIN event e ON e.id=h.event_id"):
 if h["kyoku_id"] in kyokus:hands[h["kyoku_id"]].update(tiles(h["hand"]))
for d in c.execute("SELECT e.kyoku_id,e.event_order,d.tile FROM draw_event d JOIN event e ON e.id=d.event_id"):
 if d["kyoku_id"] in kyokus:draws[d["kyoku_id"]].append((d["event_order"],norm(d["tile"])))
for v in c.execute("""
 SELECT e.kyoku_id,e.event_order,di.dora_indicator_tile
 FROM dora_indicator_event di JOIN event e ON e.id=di.event_id
 WHERE di.dora_type='omote'
"""):
 if v["kyoku_id"] in kyokus:doras[v["kyoku_id"]].append((v["event_order"],norm(v["dora_indicator_tile"])))
assert len(hands)==len(kyokus),(len(hands),len(kyokus))

byplayer=defaultdict(lambda:Counter())
byseason=defaultdict(lambda:Counter())
detail=[]
errors=[]
zero_example=[]
reach_end=defaultdict(Counter)
ryukyoku={r["kyoku_id"] for r in query("SELECT e.kyoku_id FROM ryukyoku_event re JOIN event e ON e.id=re.event_id")}
for r in accepted:
 ky=r["kyoku_id"];pid=r["player_id"]
 candidates=[z for z in flagby[(ky,pid)] if z["discard_order"]>r["reach_order"]]
 assert len(candidates)==1,("missing/duplicate declaration",r,candidates)
 d=candidates[0]
 assert d["is_actor"]==1 and d["waiting_tiles"],("no post-discard waiting state",r,d)
 wait=set(tiles(d["waiting_tiles"]))
 assert wait,(r,d)
 before=Counter(t for order,t in draws[ky] if order<d["discard_order"])
 unseen=base-hands[ky]-before
 count_physical=sum(unseen[t] for t in wait)
 visible=sum(1 for order,t in doras[ky] if order<=d["discard_order"] and t in wait)
 available=count_physical-visible
 assert available>=0,(r,available,visible,count_physical)
 if d["available_tile_count"]!=available or d["dora_indicator_tile_count"]!=visible:
  errors.append({"kyoku":ky,"player":pid,"event":d["declaration_event_id"],
                 "source":d["available_tile_count"],"rebuilt":available,
                 "source_dora":d["dora_indicator_tile_count"],"rebuilt_dora":visible})
  if len(errors)>10:raise AssertionError(errors[:11])
 pure=int(available==0)
 strict=int(count_physical==0)
 doraonly=int(pure and count_physical>0)
 b=byplayer[pid];b["accepted_reach_count"]+=1;b["pure_empty_reach_count"]+=pure
 b["zero_even_including_visible_dora_count"]+=strict
 b["zero_except_visible_dora_count"]+=doraonly
 y=byseason[r["start_year"]];y["accepted"]+=1;y["pure"]+=pure;y["strict"]+=strict;y["doraonly"]+=doraonly
 end="ryukyoku" if ky in ryukyoku else "agari"
 reach_end[end]["accepted"]+=1;reach_end[end]["pure"]+=pure
 entry={"kyoku_id":ky,"player_id":pid,"start_year":r["start_year"],
        "declaration_event_id":d["declaration_event_id"],
        "waiting_tiles":d["waiting_tiles"],"available":available,
        "physical_including_dora":count_physical,"visible_dora":visible,
        "pure":pure,"strict_physical_zero":strict,"dora_only":doraonly,"ending":end}
 detail.append(entry)
 if pure and len(zero_example)<20:zero_example.append(entry)
assert not errors,errors
assert len(detail)==len(accepted)
assert sum(q["pure"] for q in detail)==sum(p["pure_empty_reach_count"] for p in byplayer.values())

sql=(root/"sql/pure_empty_reach_v01.sql").read_text(encoding="utf-8")
p="SELECT NULL AS start_year, NULL AS stage"
assert sql.count(p)==1
ranking=query(sql)
assert len(ranking)==len(byplayer)==56,(len(ranking),len(byplayer))
for row in ranking:
 expected=byplayer[row["player_id"]]
 for field in ("accepted_reach_count","pure_empty_reach_count",
               "zero_even_including_visible_dora_count","zero_except_visible_dora_count"):
  assert row[field]==expected[field],("mismatch",row["player_name"],field,row[field],expected[field])
 assert abs(row["pure_empty_reach_pct"]-round(100*expected["pure_empty_reach_count"]/expected["accepted_reach_count"],4))<.00006
years=[]
for year in sorted(byseason):
 yr=query(sql.replace(p,f"SELECT {year} AS start_year, NULL AS stage"))
 exact=defaultdict(Counter)
 for q in detail:
  if q["start_year"]!=year:continue
  b=exact[q["player_id"]]
  b["accepted_reach_count"]+=1;b["pure_empty_reach_count"]+=q["pure"]
  b["zero_even_including_visible_dora_count"]+=q["strict_physical_zero"]
  b["zero_except_visible_dora_count"]+=q["dora_only"]
 assert len(yr)==len(exact)
 for row in yr:
  for field,val in exact[row["player_id"]].items():
   assert row[field]==val,(year,row["player_name"],field,row[field],val)
 x=byseason[year]
 years.append({"season":f"{year}-{str(year+1)[-2:]}","accepted":x["accepted"],"pure":x["pure"],
               "strict_zero":x["strict"],"dora_only":x["doraonly"],
               "pct":round(100*x["pure"]/x["accepted"],4)})
 if year==2025:
  csvout("pure_empty_reach_v01_2025_26_all_players.csv",yr)
  jsonout("pure_empty_reach_v01_2025_26_top10.json",yr[:10])
  print("TOP10_2025_26",json.dumps(yr[:10],ensure_ascii=False),flush=True)
overall={"accepted":len(accepted),"pure":sum(x["pure"] for x in detail),
         "strict_zero":sum(x["strict_physical_zero"] for x in detail),
         "dora_only":sum(x["dora_only"] for x in detail)}
overall["pct"]=round(100*overall["pure"]/overall["accepted"],4)
summary={"sqlite_quick_check":"ok","accepted_reaches_all_checked":len(detail),
         "unique_kyoku":len(kyokus),"players":len(ranking),
         "reconstructed_wait_count_matches_database":len(detail),
         "overall":overall,"ending":{k:dict(v) for k,v in reach_end.items()},
         "by_season":years,"top10_all":ranking[:10],
         "zero_examples":zero_example}
csvout("pure_empty_reach_v01_all_players.csv",ranking)
csvout("pure_empty_reach_v01_all_accepted_reach_events.csv",detail)
jsonout("pure_empty_reach_v01_verification.json",summary)
jsonout("pure_empty_reach_v01_top10_all.json",ranking[:10])
print("VALIDATION",json.dumps({k:v for k,v in summary.items() if k not in ("top10_all","zero_examples")},ensure_ascii=False),flush=True)
print("TOP10_ALL",json.dumps(ranking[:10],ensure_ascii=False),flush=True)
print("ZERO_EXAMPLES",json.dumps(zero_example[:5],ensure_ascii=False),flush=True)
