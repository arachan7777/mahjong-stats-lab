#!/usr/bin/env python3
"""永井孝典：赤ドラ取得後の行方（研究用・正本変更なし）。
赤取得は確定SQL sql/aka_loved_per_kyoku_v01.sql と同じ6経路を使用。
イベント追跡は各局の赤色×選手の取得イベントから、最初の該当打牌または局終了までを計測。
"""
import sqlite3,sys,json,csv,collections,statistics
from pathlib import Path
cn=sqlite3.connect("file:"+str(Path(sys.argv[1]).resolve())+"?mode=ro",uri=True)
cn.row_factory=sqlite3.Row;cn.execute("PRAGMA query_only=ON")
assert cn.execute("SELECT count(*) FROM game").fetchone()[0]==2068
def q(s):return [dict(r) for r in cn.execute(s)]
years="(2025,2026)"
base="""FROM event e JOIN kyoku k ON k.id=e.kyoku_id
 JOIN game g ON g.id=k.game_id JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
 WHERE ls.start_year IN (2025,2026)"""
meta={}
for r in q("""SELECT k.id kyoku_id,ls.start_year year,g.date date,g.id game_id,
 g.m_league_game_id external_game_id,k.round round,k.honba_count honba,ss.stage stage
 FROM kyoku k JOIN game g ON g.id=k.game_id JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id WHERE ls.start_year IN (2025,2026)"""):
 meta[r["kyoku_id"]]=r
acq=[]
sources=[
 ("haipai","haipai_event","actor_player_id","TRIM(j.value)",'JOIN json_each(\'["\'||replace(t.hand,\',\',\'"," \')||\'"]\') j'),
]
# canonical SQL six sources; JSON split of hand uses same representation as approved SQL
for origin,tbl,player,tile,extra in [
 ("haipai","haipai_event","actor_player_id","trim(j.value)",'''JOIN json_each('["'||replace(t.hand,',','","')||'"]') j'''),
 ("draw","draw_event","actor_player_id","t.tile",""),
 ("chi","chi_event","actor_player_id","t.tile",""),
 ("pon","pon_event","actor_player_id","t.tile",""),
 ("daiminkan","daiminkan_event","actor_player_id","t.tile",""),
 ("ron","agari_event","actor_player_id","t.agari_tile","")
]:
 add=" AND e.type='ron'" if origin=="ron" else ""
 sql=f"""SELECT e.kyoku_id, e.id event_id,e.event_order ord,
  t.{player} player_id, {tile} tile,
  '{origin}' origin
  FROM {tbl} t JOIN event e ON e.id=t.event_id
  JOIN kyoku k ON k.id=e.kyoku_id
  JOIN game g ON g.id=k.game_id
  JOIN season_stage ss ON ss.id=g.season_stage_id
  JOIN league_season ls ON ls.id=ss.league_season_id
  {extra}
  WHERE ls.start_year IN (2025,2026) AND {tile} IN ('0m','0p','0s') {add}"""
 acq.extend(q(sql))
for a in acq:a.update(meta[a["kyoku_id"]])
acq.sort(key=lambda x:(x["kyoku_id"],x["ord"],x["event_id"]))
assert sum(x["player_id"]==49 and x["year"]==2025 for x in acq)==333,collections.Counter((x["year"],x["player_id"]) for x in acq).most_common(5)
assert sum(x["player_id"]==49 and x["year"]==2026 for x in acq)==122
print("ACQ_AUDIT",json.dumps(collections.Counter(x["origin"] for x in acq if x["player_id"]==49 and x["year"]==2025),ensure_ascii=False),flush=True)
dis=q("""SELECT e.kyoku_id,e.event_order ord,e.id event_id,
 d.actor_player_id player_id,d.tile,d.is_tsumogiri,d.is_reach_declaration
 FROM discard_event d JOIN event e ON e.id=d.event_id
 JOIN kyoku k ON k.id=e.kyoku_id JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
 WHERE ls.start_year IN (2025,2026) AND d.tile IN ('0m','0p','0s')""")
reaches=q("""SELECT e.kyoku_id,e.event_order ord,r.actor_player_id player_id
 FROM reach_event r JOIN event e ON e.id=r.event_id
 JOIN kyoku k ON k.id=e.kyoku_id JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
 WHERE ls.start_year IN (2025,2026) AND r.is_accepted=1""")
wins=q("""SELECT e.kyoku_id,e.id event_id,e.event_order ord,e.type win_type,
 a.actor_player_id winner_id,a.target_player_id loser_id,a.agari_tile tile,
 a.agari_points,a.honba_points,a.is_yakuman
 FROM agari_event a JOIN event e ON e.id=a.event_id
 JOIN kyoku k ON k.id=e.kyoku_id JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
 WHERE ls.start_year IN (2025,2026)""")
redhan={r["agari_event_id"]:r["h"] for r in q("""SELECT ay.agari_event_id,SUM(ay.han) h
 FROM agari_yaku ay JOIN yaku_name n ON n.id=ay.yaku_name_id
 WHERE n.name='赤ドラ' GROUP BY ay.agari_event_id""")}
roundkind=q("""SELECT e.kyoku_id,e.type FROM ryukyoku_event r JOIN event e ON e.id=r.event_id
 JOIN kyoku k ON k.id=e.kyoku_id JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
 WHERE ls.start_year IN (2025,2026)""")
ryukyoku={r["kyoku_id"] for r in roundkind}
D=collections.defaultdict(list)
R=collections.defaultdict(list)
W=collections.defaultdict(list)
A=collections.defaultdict(list)
for d in dis:D[(d["kyoku_id"],d["player_id"],d["tile"])].append(d)
for r in reaches:R[(r["kyoku_id"],r["player_id"])].append(r["ord"])
for w in wins:W[w["kyoku_id"]].append(w)
for a in acq:A[(a["kyoku_id"],a["player_id"],a["tile"])].append(a)
for a in D.values():a.sort(key=lambda x:(x["ord"],x["event_id"]))
for a in W.values():a.sort(key=lambda x:(x["ord"],x["event_id"]))
for a in A.values():a.sort(key=lambda x:(x["ord"],x["event_id"]))
records=[]
duplicate={k:len(v) for k,v in A.items() if len(v)>1}
print("DUPLICATE_ACQ_PAIRS",len(duplicate),"for_nagai",sum(k[1]==49 for k in duplicate),flush=True)
for key,alist in A.items():
 ky,player,tile=key
 ds=D.get(key,[])
 rons=[x for x in W.get(ky,[]) if x["win_type"]=="ron" and x["loser_id"]==player and x["tile"]==tile]
 ownwins=[x for x in W.get(ky,[]) if x["winner_id"]==player]
 for j,a in enumerate(alist):
  next_acq=alist[j+1]["ord"] if j+1<len(alist) else float("inf")
  # Any own red discard before reacquiring a same color belongs to this acquisition
  d=next((x for x in ds if a["ord"]<x["ord"]<next_acq),None)
  w=next((x for x in ownwins if x["ord"]>=a["ord"] and x["ord"]<next_acq),None)
  reached_before=any(ord<a["ord"] for ord in R.get((ky,player),[]))
  if d:
   reds=[x for x in rons if x["ord"]>d["ord"] and x["ord"]<next_acq]
   result="discard_ron" if reds else ("discard_tsumogiri" if d["is_tsumogiri"] else "discard_tedashi")
   late=bool(a["origin"]=="draw" and reached_before and d["is_tsumogiri"])
   detail=dict(result=result,dis_event_id=d["event_id"],dis_ord=d["ord"],
    tsumogiri=bool(d["is_tsumogiri"]),reach_declaration=bool(d["is_reach_declaration"]),
    late_after_reach=late,after_reach_discard=any(ord<d["ord"] for ord in R.get((ky,player),[])),
    dealin=len(reds)>0,dealin_count=len(reds),dealin_points=sum(x["agari_points"]+x["honba_points"] for x in reds),
    win_event_id=None,win_points=None,win_aka_han=None)
  elif w:
   detail=dict(result="own_win_held",dis_event_id=None,dis_ord=None,tsumogiri=False,
    reach_declaration=False,late_after_reach=False,after_reach_discard=False,
    dealin=False,dealin_count=0,dealin_points=0,win_event_id=w["event_id"],
    win_points=w["agari_points"],win_aka_han=redhan.get(w["event_id"],0))
  else:
   detail=dict(result="other_end_held" if ky not in ryukyoku else "draw_end_held",
    dis_event_id=None,dis_ord=None,tsumogiri=False,reach_declaration=False,
    late_after_reach=False,after_reach_discard=False,dealin=False,dealin_count=0,
    dealin_points=0,win_event_id=None,win_points=None,win_aka_han=None)
  records.append(dict(**a,**detail))
nagai=[x for x in records if x["player_id"]==49]
print("NAGAI_COUNTS",json.dumps({str(yr):dict(
 acquisitions=len(d),origins=dict(collections.Counter(x["origin"] for x in d)),
 outcome=dict(collections.Counter(x["result"] for x in d)),
 tedashi=sum(x["result"] in ["discard_tedashi","discard_ron"] and not x["tsumogiri"] for x in d),
 tsumogiri=sum(x["tsumogiri"] for x in d),
 late_after_reach=sum(x["late_after_reach"] for x in d),
 post_reach_discards=sum(x["after_reach_discard"] for x in d),
 reach_declaration_red=sum(x["reach_declaration"] for x in d),
 dealin_red=sum(x["dealin"] for x in d),
 dealin_points=sum(x["dealin_points"] for x in d),
 own_win_held=sum(x["result"]=="own_win_held" for x in d),
 unique_win_hands=len({x["win_event_id"] for x in d if x["win_event_id"]}),
 red_in_held_at_ryukyoku=sum(x["result"]=="draw_end_held" for x in d),
 red_ended_other_agari=sum(x["result"]=="other_end_held" for x in d))
 for yr in (2025,2026) for d in [[x for x in nagai if x["year"]==yr]]},ensure_ascii=False),flush=True)
# "same red in each win" physical hold vs. 赤ドラ yaku: compare by event ID, count all player wins
for yr in (2025,2026):
 k=[x for x in nagai if x["year"]==yr]
 grouped=collections.Counter(x["win_event_id"] for x in k if x["win_event_id"])
 diffs=[]
 for wid,count in grouped.items():
  h=redhan.get(wid,0)
  if h!=count:diffs.append(dict(event_id=wid,physical_red=count,han=h))
 print("WIN_RED_HAN_AUDIT",yr,json.dumps(dict(wins_with_red=len(grouped),mismatches=diffs[:15],mismatch_count=len(diffs)),ensure_ascii=False),flush=True)
# Add comparison with all active players in same year, benchmark fraction of red acquisitions that ended in each way
base=[]
for yr in (2025,2026):
 by=collections.defaultdict(list)
 for r in records:
  if r["year"]==yr:by[r["player_id"]].append(r)
 rows=[]
 for pid,v in by.items():
  n=len(v)
  rows.append(dict(player_id=pid,acq=n,
   tedashi_rate=round(100*sum(x["result"] in ("discard_tedashi","discard_ron") and not x["tsumogiri"] for x in v)/n,4),
   all_discard_rate=round(100*sum(x["dis_event_id"] is not None for x in v)/n,4),
   win_held_rate=round(100*sum(x["result"]=="own_win_held" for x in v)/n,4),
   late_after_reach_rate=round(100*sum(x["late_after_reach"] for x in v)/n,4)))
 qualified=[v for v in rows if v["acq"]>=100]
 top={}
 for metric in ("tedashi_rate","all_discard_rate","win_held_rate","late_after_reach_rate"):
  ss=sorted(qualified,key=lambda v:-v[metric])
  top[metric]=dict(nagai=next(v[metric] for v in rows if v["player_id"]==49),
   rank=next(i for i,v in enumerate(ss,1) if v["player_id"]==49),
   qualified=len(ss),league_weighted=round(sum(v[metric]*v["acq"] for v in rows)/sum(v["acq"] for v in rows),4))
 base.append(dict(year=yr,results=top))
print("BENCHMARK",json.dumps(base,ensure_ascii=False),flush=True)
# Win-conversion: 赤ドラ有和了数 and red discard -> later own win in same round
for yr in (2025,2026):
 own=[w for w in wins if w["winner_id"]==49 and meta[w["kyoku_id"]]["year"]==yr]
 with_red=[w for w in own if redhan.get(w["event_id"],0)>0]
 league=[w for w in wins if meta[w["kyoku_id"]]["year"]==yr]
 red_discard_then_win={x["kyoku_id"] for x in nagai if x["year"]==yr and x["dis_event_id"] is not None and any(w["winner_id"]==49 for w in W[x["kyoku_id"]])}
 red_tedashi_then_win={x["kyoku_id"] for x in nagai if x["year"]==yr and x["result"] in ("discard_tedashi","discard_ron") and not x["tsumogiri"] and any(w["winner_id"]==49 for w in W[x["kyoku_id"]])}
 print("WIN_CONVERSION",json.dumps(dict(year=yr,own_win_count=len(own),own_win_with_red_count=len(with_red),
  own_win_with_red_pct=round(100*len(with_red)/len(own),4),
  league_win_count=len(league),league_win_with_red_count=sum(redhan.get(w["event_id"],0)>0 for w in league),
  league_win_with_red_pct=round(100*sum(redhan.get(w["event_id"],0)>0 for w in league)/len(league),4),
  own_win_after_red_discard_kyoku=len(red_discard_then_win),
  own_win_after_red_tedashi_kyoku=len(red_tedashi_then_win)),ensure_ascii=False),flush=True)

out=Path("results");out.mkdir(exist_ok=True)
with (out/"nagai_red_acquisitions_outcomes_20261124.csv").open("w",encoding="utf-8-sig",newline="") as f:
 fields=list(nagai[0]);dw=csv.DictWriter(f,fieldnames=fields);dw.writeheader();dw.writerows(nagai)
(out/"nagai_red_story_comparison_20261124.json").write_text(json.dumps(base,ensure_ascii=False,indent=2),encoding="utf8")
