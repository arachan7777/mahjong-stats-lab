#!/usr/bin/env python3
"""茅森早香 vs 園田賢リーチ 独立研究：既存DB読み取り専用。
園田先制リーチと他者先制リーチの相対比較、および他者 vs 園田対照。
押しの代理指標は未リーチのまま自分の判断で切る非現物牌であり、
真の危険牌／押し引き意図を直接表すものではない。
"""
import sqlite3,sys,json,collections,statistics,csv
from pathlib import Path
cn=sqlite3.connect("file:"+str(Path(sys.argv[1]).resolve())+"?mode=ro",uri=True);cn.row_factory=sqlite3.Row;cn.execute("PRAGMA query_only=ON")
assert cn.execute("SELECT COUNT(*) FROM game").fetchone()[0]==2068
assert cn.execute("SELECT COUNT(*) FROM kyoku").fetchone()[0]==25238
pid_k=cn.execute("SELECT id FROM player WHERE name='茅森早香'").fetchone()[0]
pid_s=cn.execute("SELECT id FROM player WHERE name='園田賢'").fetchone()[0]
print("IDS",pid_k,pid_s,flush=True)
def q(sql,*args):return [dict(r) for r in cn.execute(sql,args)]
def norm(t):return "5"+t[1:] if t.startswith("0") else t
games=q("""SELECT g.id game_id,g.date,ls.start_year year,ss.stage
 FROM game g JOIN season_stage ss ON ss.id=g.season_stage_id JOIN league_season ls ON ls.id=ss.league_season_id
 JOIN game_player_result gp ON gp.game_id=g.id AND gp.player_id=?""",pid_k)
kay_games={g["game_id"]:g for g in games}
both=q("""SELECT g.id game_id,ls.start_year year,ss.stage
 FROM game g JOIN season_stage ss ON ss.id=g.season_stage_id JOIN league_season ls ON ls.id=ss.league_season_id
 JOIN game_player_result ka ON ka.game_id=g.id AND ka.player_id=?
 JOIN game_player_result so ON so.game_id=g.id AND so.player_id=?""",pid_k,pid_s)
print("GAMES",len(games),"TOGETHER",len(both),"ANNUAL",dict(collections.Counter(x["year"] for x in both)),flush=True)
rounds=q("""SELECT k.id kyoku_id,k.game_id,g.date,ls.start_year year,ss.stage,k.round,k.honba_count
 FROM kyoku k JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id JOIN league_season ls ON ls.id=ss.league_season_id
 JOIN game_player_result gp ON gp.game_id=g.id AND gp.player_id=?""",pid_k)
KM={x["kyoku_id"]:x for x in rounds}
print("KAY_ROUNDS",len(KM),flush=True)
dis=q("""SELECT e.kyoku_id,e.id id,e.event_order ord,d.actor_player_id player_id,
 d.tile,d.is_tsumogiri,d.is_reach_declaration
 FROM discard_event d JOIN event e ON e.id=d.event_id JOIN kyoku k ON k.id=e.kyoku_id
 JOIN game_player_result gp ON gp.game_id=k.game_id AND gp.player_id=?""",pid_k)
reach=q("""SELECT e.kyoku_id,e.id id,e.event_order ord,r.actor_player_id player_id,r.is_accepted
 FROM reach_event r JOIN event e ON e.id=r.event_id JOIN kyoku k ON k.id=e.kyoku_id
 JOIN game_player_result gp ON gp.game_id=k.game_id AND gp.player_id=?""",pid_k)
agari=q("""SELECT e.kyoku_id,e.id id,e.event_order ord,e.type,
 a.actor_player_id winner,a.target_player_id loser,a.agari_points
 FROM agari_event a JOIN event e ON e.id=a.event_id JOIN kyoku k ON k.id=e.kyoku_id
 JOIN game_player_result gp ON gp.game_id=k.game_id AND gp.player_id=?""",pid_k)
# shanten snapshots before each reach event (latest Kayamori state)
states=q("""SELECT e.kyoku_id,e.event_order ord,ps.player_id,ps.shanten_count
 FROM player_state ps JOIN event e ON e.id=ps.event_id JOIN kyoku k ON k.id=e.kyoku_id
 JOIN game_player_result gp ON gp.game_id=k.game_id AND gp.player_id=?
 WHERE ps.player_id=?""",pid_k,pid_k)
D=collections.defaultdict(list);R=collections.defaultdict(list);W=collections.defaultdict(list);S=collections.defaultdict(list)
for r in dis:D[r["kyoku_id"]].append(r)
for r in reach:R[r["kyoku_id"]].append(r)
for r in agari:W[r["kyoku_id"]].append(r)
for r in states:S[r["kyoku_id"]].append(r)
for lst in [*D.values(),*R.values(),*W.values(),*S.values()]:lst.sort(key=lambda x:(x["ord"],x.get("id",0)))
# An exposure consists of opponent's FIRST accepted reach (avoid multi-riichi ambiguity).
# If Kayamori has already reached before that, don't count as deliberate push opportunity.
rows=[]
problems=[]
for ky,rm in KM.items():
 rr=[r for r in R[ky] if r["is_accepted"]]
 if not rr:continue
 first=min(rr,key=lambda x:x["ord"])
 if first["player_id"]==pid_k:continue
 decl=[d for d in D[ky] if d["player_id"]==first["player_id"] and d["is_reach_declaration"] and d["ord"]>first["ord"]]
 if not decl:
  problems.append((ky,"no declaration after reach",first));continue
 ddecl=decl[0]
 after_riichi= ddecl["ord"]
 next_other_reach=min((r["ord"] for r in rr if r["ord"]>first["ord"] and r["player_id"] not in (pid_k,first["player_id"])),default=float("inf"))
 next_k_reach=min((r["ord"] for r in rr if r["ord"]>first["ord"] and r["player_id"]==pid_k),default=float("inf"))
 # expose past declaration, until other player enters with second riichi; own riichi decision included at declaration cut but no forced discards after it
 k_reach_dec=[d for d in D[ky] if d["player_id"]==pid_k and d["is_reach_declaration"] and d["ord"]>next_k_reach] if next_k_reach!=float("inf") else []
 k_reach_decl_ord=k_reach_dec[0]["ord"] if k_reach_dec else float("inf")
 opp_discarded=set(norm(d["tile"]) for d in D[ky] if d["player_id"]==first["player_id"] and d["ord"]<=after_riichi)
 k_discards=[]
 opp_discards=sorted([d for d in D[ky] if d["player_id"]==first["player_id"] and d["ord"]>after_riichi],key=lambda x:x["ord"])
 for d in sorted([d for d in D[ky] if d["player_id"]==pid_k and after_riichi<d["ord"]<next_other_reach and d["ord"]<=k_reach_decl_ord],key=lambda x:x["ord"]):
  if next_k_reach!=float("inf") and d["ord"]>k_reach_decl_ord:continue
  current_sonoda_genbutsu=set(opp_discarded)
  current_sonoda_genbutsu.update(norm(x["tile"]) for x in opp_discards if x["ord"]<d["ord"])
  is_genbutsu=norm(d["tile"]) in current_sonoda_genbutsu
  k_discards.append(dict(**d,is_genbutsu=is_genbutsu,not_genbutsu=not is_genbutsu,own_reach_discard=bool(d["is_reach_declaration"])))
 # If another reaches, outcomes may be affected: annotate, but do not cherry-pick
 all_k_post=[d for d in D[ky] if d["player_id"]==pid_k and d["ord"]>after_riichi]
 resolved=[w for w in W[ky] if w["ord"]>after_riichi]
 k_wins=[w for w in resolved if w["winner"]==pid_k]
 opp_wins=[w for w in resolved if w["winner"]==first["player_id"]]
 k_dealins=[w for w in resolved if w["loser"]==pid_k and w["type"]=="ron"]
 k_to_opp=[w for w in k_dealins if w["winner"]==first["player_id"]]
 opp_to_k=[w for w in k_wins if w["loser"]==first["player_id"] and w["type"]=="ron"]
 prev=[s for s in S[ky] if s["ord"]<=after_riichi]
 sh=prev[-1]["shanten_count"] if prev else None
 # non-genbutsu when NOT already tenpai (as of at declaration)
 rec=dict(**rm,first_riichi_player=first["player_id"],against_sonoda=first["player_id"]==pid_s,
   reach_event_id=first["id"],reach_ord=first["ord"],riichi_discard_ord=after_riichi,
   k_shanten_at_reach=sh,
   k_discard_count=len(k_discards),non_genbutsu_count=sum(x["not_genbutsu"] for x in k_discards),
   first_k_discard_non_genbutsu=(k_discards[0]["not_genbutsu"] if k_discards else None),
   any_non_genbutsu=any(x["not_genbutsu"] for x in k_discards),
   k_follow_reach=(next_k_reach<next_other_reach),
   k_reach_event_id=(next(r["id"] for r in rr if r["player_id"]==pid_k and r["ord"]==next_k_reach) if next_k_reach!=float("inf") else None),
   k_wins=len(k_wins),k_ron_first=len(opp_to_k),k_dealin_count=len(k_dealins),k_dealin_to_first=len(k_to_opp),
   first_riicher_wins=len(opp_wins),
   k_win_points=sum(w["agari_points"] for w in k_wins),
   k_dealin_to_first_points=sum(w["agari_points"] for w in k_to_opp),
   interference_other_reach=(next_other_reach!=float("inf")),
   all_k_post_discards=len(all_k_post),
   details=[dict(tile=d["tile"],ord=d["ord"],is_genbutsu=d["is_genbutsu"],tsumogiri=d["is_tsumogiri"],own_reach_discard=d["own_reach_discard"]) for d in k_discards])
 rows.append(rec)
print("PROBLEMS",len(problems),json.dumps(problems[:6],ensure_ascii=False),flush=True)
print("EXPOSURES",len(rows),sum(x["against_sonoda"] for x in rows),flush=True)
def summarize(rr):
 if not rr:return None
 t=sum(x["k_discard_count"] for x in rr);ng=sum(x["non_genbutsu_count"] for x in rr)
 fd=[x for x in rr if x["first_k_discard_non_genbutsu"] is not None]
 n=len(rr)
 return dict(exposures=n,with_decision=sum(x["k_discard_count"]>0 for x in rr),
  total_k_discards=t,non_genbutsu=ng,non_genbutsu_pct=round(100*ng/t,3) if t else None,
  any_non_genbutsu=sum(x["any_non_genbutsu"] for x in rr),any_non_genbutsu_pct=round(100*sum(x["any_non_genbutsu"] for x in rr)/n,3),
  first_discard_non_genbutsu=sum(x["first_k_discard_non_genbutsu"] for x in fd),
  first_discard_non_genbutsu_pct=round(100*sum(x["first_k_discard_non_genbutsu"] for x in fd)/len(fd),3) if fd else None,
  chase_reach=sum(x["k_follow_reach"] for x in rr),
  chase_reach_pct=round(100*sum(x["k_follow_reach"] for x in rr)/n,3),
  k_win_rounds=sum(x["k_wins"]>0 for x in rr),
  k_win_pct=round(100*sum(x["k_wins"]>0 for x in rr)/n,3),
  k_ron_riicher=sum(x["k_ron_first"] for x in rr),
  k_dealin_rounds=sum(x["k_dealin_count"]>0 for x in rr),
  k_dealin_to_riicher=sum(x["k_dealin_to_first"] for x in rr),
  riicher_wins=sum(x["first_riicher_wins"]>0 for x in rr),
  total_k_win_points=sum(x["k_win_points"] for x in rr),
  total_k_dealin_to_riicher_points=sum(x["k_dealin_to_first_points"] for x in rr),
  other_riichi_interference=sum(x["interference_other_reach"] for x in rr),
  mean_initial_shanten=round(statistics.mean(x["k_shanten_at_reach"] for x in rr if x["k_shanten_at_reach"] is not None),3),
  initial_shanten_distribution=dict(collections.Counter(x["k_shanten_at_reach"] for x in rr)))
groups={
 "sonoda_first_reach": [x for x in rows if x["against_sonoda"]],
 "all_other_first_reach": [x for x in rows if not x["against_sonoda"]],
 "sonoda_while_kay_not_tenpai":[x for x in rows if x["against_sonoda"] and x["k_shanten_at_reach"] is not None and x["k_shanten_at_reach"]>=1],
 "others_while_kay_not_tenpai":[x for x in rows if not x["against_sonoda"] and x["k_shanten_at_reach"] is not None and x["k_shanten_at_reach"]>=1],
 "sonoda_while_kay_tenpai":[x for x in rows if x["against_sonoda"] and x["k_shanten_at_reach"]==0],
 "others_while_kay_tenpai":[x for x in rows if not x["against_sonoda"] and x["k_shanten_at_reach"]==0],
}
for k,v in groups.items():print("GROUP",k,json.dumps(summarize(v),ensure_ascii=False),flush=True)
annual={}
for year in sorted(set(x["year"] for x in rows)):
 annual[str(year)]={k:summarize([x for x in v if x["year"]==year]) for k,v in groups.items() if k in ("sonoda_first_reach","all_other_first_reach")}
print("YEARLY",json.dumps(annual,ensure_ascii=False),flush=True)
print("SONODA_CASES",json.dumps([{k:v for k,v in x.items() if k!="details"} for x in rows if x["against_sonoda"]],ensure_ascii=False),flush=True)
print("SHANTEN_STATE_CHECK",json.dumps(dict(missing=sum(x["k_shanten_at_reach"] is None for x in rows),non_genbutsu_all=sum(x["non_genbutsu_count"] for x in rows)),ensure_ascii=False),flush=True)
Path("results").mkdir(exist_ok=True)
with Path("results/sonoda_kayamori_reach_exposures_20261124.csv").open("w",encoding="utf-8-sig",newline="") as f:
 fields=[k for k in rows[0] if k!="details"];w=csv.DictWriter(f,fields);w.writeheader();w.writerows({k:v for k,v in x.items() if k!="details"} for x in rows)
Path("results/sonoda_kayamori_reach_compare_20261124.json").write_text(json.dumps(dict(games=len(games),both_games=len(both),groups={k:summarize(v) for k,v in groups.items()},yearly=annual,sonoda_exposures=[x for x in rows if x["against_sonoda"]]),ensure_ascii=False,indent=2),encoding="utf-8")
