#!/usr/bin/env python3
"""園田の先制リーチ79局：園田・茅森の局単位の点数収支と直接ロンを検算。
read-only 20261120-2341-04338cbb DB. 指標の新設/公式変更は行わない。
"""
import sqlite3,sys,json,collections,statistics,csv
from pathlib import Path
db=Path(sys.argv[1]); c=sqlite3.connect("file:"+str(db.resolve())+"?mode=ro",uri=True);c.row_factory=sqlite3.Row
c.execute("PRAGMA query_only=ON")
def q(sql,*a):return [dict(r) for r in c.execute(sql,a)]
assert c.execute("SELECT COUNT(*) FROM kyoku").fetchone()[0]==25238
P=dict((r["name"],r["id"]) for r in q("SELECT id,name FROM player"))
s=P["園田賢"];k=P["茅森早香"]
both=q("""SELECT g.id game_id,g.date,ls.start_year year,ss.stage
 FROM game g JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
 JOIN game_player_result sk ON sk.game_id=g.id AND sk.player_id=?
 JOIN game_player_result kk ON kk.game_id=g.id AND kk.player_id=?""",s,k)
assert len(both)==32, len(both)
gdict={x["game_id"]:x for x in both}
ids=[x["game_id"] for x in both]
qs=",".join("?" for _ in ids)
rounds=q(f"""SELECT k.id kyoku_id,k.game_id,k.round,k.honba_count,
   g.date,ls.start_year year,ss.stage
 FROM kyoku k JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id JOIN league_season ls ON ls.id=ss.league_season_id
 WHERE k.game_id IN ({qs})""",*ids)
ks={x["kyoku_id"]:x for x in rounds}
kyp=q(f"""SELECT r.kyoku_id,ky.game_id,r.player_id,r.score
 FROM kyoku_player_result r JOIN kyoku ky ON ky.id=r.kyoku_id
 WHERE ky.game_id IN ({qs}) ORDER BY ky.game_id,r.player_id,r.kyoku_id""",*ids)
prev={}
score_deltas={}
first_per_game=collections.defaultdict(dict)
for z in kyp:
 g,p,ki=z["game_id"],z["player_id"],z["kyoku_id"]
 old=prev.get((g,p),25000)
 score_deltas[(ki,p)]=z["score"]-old
 prev[g,p]=z["score"]
r=q(f"""SELECT e.kyoku_id,e.event_order ord,e.id event_id,rr.actor_player_id player_id,
  rr.is_accepted
 FROM reach_event rr JOIN event e ON e.id=rr.event_id
 JOIN kyoku ky ON ky.id=e.kyoku_id
 WHERE ky.game_id IN ({qs}) ORDER BY e.kyoku_id,e.event_order""",*ids)
reaches=collections.defaultdict(list)
for z in r:reaches[z["kyoku_id"]].append(z)
decl=q(f"""SELECT e.kyoku_id,e.event_order ord,d.actor_player_id player_id
 FROM discard_event d JOIN event e ON e.id=d.event_id JOIN kyoku ky ON ky.id=e.kyoku_id
 WHERE ky.game_id IN ({qs}) AND d.is_reach_declaration=1""",*ids)
decls=collections.defaultdict(list)
for z in decl:decls[z["kyoku_id"]].append(z)
agari_cols={z["name"] for z in q("PRAGMA table_info(agari_event)")}
kyotaku_sel="a.kyotaku_points" if "kyotaku_points" in agari_cols else "0"
wins=q(f"""SELECT e.kyoku_id,e.event_order ord,e.type win_type,
  a.actor_player_id winner,a.target_player_id loser,
  a.agari_points,a.honba_points,{kyotaku_sel} AS kyotaku_points
 FROM agari_event a JOIN event e ON e.id=a.event_id JOIN kyoku ky ON ky.id=e.kyoku_id
 WHERE ky.game_id IN ({qs})""",*ids)
W=collections.defaultdict(list)
for z in wins:W[z["kyoku_id"]].append(z)
rows=[]
for z in rounds:
 ky=z["kyoku_id"]
 accepted=[x for x in reaches[ky] if x["is_accepted"]]
 if not accepted:continue
 fst=min(accepted,key=lambda x:x["ord"])
 if fst["player_id"]==k:continue
 dd=[x for x in decls[ky] if x["player_id"]==fst["player_id"] and x["ord"]>fst["ord"]]
 assert len(dd)>=1,(ky,"no declaring discard")
 dord=min(x["ord"] for x in dd)
 sx=score_deltas[(ky,s)];kx=score_deltas[(ky,k)]
 winpost=[w for w in W[ky] if w["ord"]>dord]
 sonoda_ron_k=[w for w in winpost if w["win_type"]=="ron" and w["winner"]==s and w["loser"]==k]
 kay_ron_s=[w for w in winpost if w["win_type"]=="ron" and w["winner"]==k and w["loser"]==s]
 assert not any(w["ord"]<=dord for w in W[ky])
 pair=dict(**z,first_reach_player=fst["player_id"],sonoda_first=fst["player_id"]==s,
   sonoda_delta=sx,kayamori_delta=kx,pair_gap_kay_minus_sonoda=kx-sx,
   sonoda_win=sum(w["winner"]==s for w in winpost),kayamori_win=sum(w["winner"]==k for w in winpost),
   kay_ron_s_count=len(kay_ron_s),s_ron_k_count=len(sonoda_ron_k),
   kay_ron_s_points=sum((w["agari_points"] or 0)+(w["honba_points"] or 0) for w in kay_ron_s),
   s_ron_k_points=sum((w["agari_points"] or 0)+(w["honba_points"] or 0) for w in sonoda_ron_k),
   kay_ron_s_kyotaku=sum(w["kyotaku_points"] or 0 for w in kay_ron_s),
   s_ron_k_kyotaku=sum(w["kyotaku_points"] or 0 for w in sonoda_ron_k),
   win_event_count=len(winpost))
 rows.append(pair)
son=[x for x in rows if x["sonoda_first"]]
assert len(son)==79, len(son)
assert sum(x["kay_ron_s_count"] for x in son)==5
assert sum(x["s_ron_k_count"] for x in son)==4
other=[x for x in rows if not x["sonoda_first"]]
assert len(other)==116, len(other)
def stats(v):
 a=sum(x["sonoda_delta"] for x in v);b=sum(x["kayamori_delta"] for x in v);n=len(v)
 return dict(hands=n,sonoda_total=a,kayamori_total=b,
  sonoda_per_hand=round(a/n,1),kayamori_per_hand=round(b/n,1),
  kay_minus_sonoda=b-a,
  kay_ron_s_count=sum(x["kay_ron_s_count"] for x in v),
  s_ron_k_count=sum(x["s_ron_k_count"] for x in v),
  kay_ron_s_points=sum(x["kay_ron_s_points"] for x in v),
  s_ron_k_points=sum(x["s_ron_k_points"] for x in v),
  kay_minus_s_direct_ron=sum(x["kay_ron_s_points"]-x["s_ron_k_points"] for x in v),
  kay_ron_s_kyotaku=sum(x["kay_ron_s_kyotaku"] for x in v),
  s_ron_k_kyotaku=sum(x["s_ron_k_kyotaku"] for x in v),
  s_wins=sum(x["sonoda_win"] for x in v),k_wins=sum(x["kayamori_win"] for x in v),
  kay_positive_hands=sum(x["pair_gap_kay_minus_sonoda"]>0 for x in v),
  s_positive_hands=sum(x["pair_gap_kay_minus_sonoda"]<0 for x in v),
  tied_hands=sum(x["pair_gap_kay_minus_sonoda"]==0 for x in v),
  biggest_kay_minus_s=max(x["pair_gap_kay_minus_sonoda"] for x in v),
  smallest_kay_minus_s=min(x["pair_gap_kay_minus_sonoda"] for x in v))
result=dict(source_db="20261120-2341-04338cbb",definition="kyoku_player_result.score 差分, 初局25000, post first accepted reach; includes all wins/discards/riichi bets; ron amount agari_points+honba_points excludes kyotaku",same_table_games=len(both),first_reach_sonoda=stats(son),
 same_table_other_first_reach=stats(other),
 yearly={str(year):stats([x for x in son if x["year"]==year]) for year in sorted({x["year"] for x in son})},
 direct_ron_cases=[{**x} for x in son if x["kay_ron_s_count"] or x["s_ron_k_count"]])
print("PAIR_NET",json.dumps(result["first_reach_sonoda"],ensure_ascii=False),flush=True)
print("OTHER_CONTROL",json.dumps(result["same_table_other_first_reach"],ensure_ascii=False),flush=True)
print("YEARLY",json.dumps(result["yearly"],ensure_ascii=False),flush=True)
print("DIRECT_CASES",json.dumps(result["direct_ron_cases"],ensure_ascii=False),flush=True)
# Score sanity: sum of all players' delta = -1000 x newly accumulated reach stakes (possibly previous kyotaku)
valid={ky:sum(score_deltas[(ky,p)] for p in (pp["player_id"] for pp in kyp if pp["kyoku_id"]==ky)) for ky in ks}
print("SCORE_SUM_DISTRIBUTION",json.dumps(dict(collections.Counter(valid[x["kyoku_id"]] for x in son)),ensure_ascii=False),flush=True)
Path("results").mkdir(exist_ok=True)
Path("results/sonoda_kayamori_pair_score_20261125.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
with Path("results/sonoda_kayamori_pair_score_20261125.csv").open("w",encoding="utf-8-sig",newline="") as f:
 fields=list(son[0]); w=csv.DictWriter(f,fields);w.writeheader();w.writerows(son)
