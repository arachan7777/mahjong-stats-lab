#!/usr/bin/env python3
"""園田賢のリーチ基礎指標＋先制・追いかけ・収支の全選手比較。正本を参照する独立読取研究。
対象: 2026-11-20 DB 2068 games/25238 rounds。正式指標を変更しない。
単位: 成立リーチイベント1回。複数人和了は対象選手和了の有無を計上。
先制: 局で最も早く成立したリーチ（不成立宣言は無視）。
局収支: kyoku_player_result.score の直前局からの差分、初局は25000。
"""
import sqlite3,sys,json,collections,statistics,csv
from pathlib import Path
c=sqlite3.connect("file:"+str(Path(sys.argv[1]).resolve())+"?mode=ro",uri=True);c.row_factory=sqlite3.Row;c.execute("PRAGMA query_only=ON")
def q(sql,*a):return [dict(r) for r in c.execute(sql,a)]
assert c.execute("SELECT COUNT(*) FROM game").fetchone()[0]==2068
assert c.execute("SELECT COUNT(*) FROM kyoku").fetchone()[0]==25238
P={p["id"]:p["name"] for p in q("SELECT id,name FROM player")}
sonoda_id=next(x for x,n in P.items() if n=="園田賢")
kayamori_id=next(x for x,n in P.items() if n=="茅森早香")
K={r["kyoku_id"]:r for r in q("""SELECT ky.id kyoku_id,ky.game_id,ky.round,ky.honba_count,
g.date,ss.stage,ls.start_year year
FROM kyoku ky JOIN game g ON g.id=ky.game_id JOIN season_stage ss ON ss.id=g.season_stage_id JOIN league_season ls ON ls.id=ss.league_season_id""")}
result_rows=q("""SELECT kr.kyoku_id,ky.game_id,kr.player_id,kr.score
FROM kyoku_player_result kr JOIN kyoku ky ON ky.id=kr.kyoku_id
ORDER BY ky.game_id,kr.player_id,kr.kyoku_id""")
previous={};score={}
for r in result_rows:
 key=(r["game_id"],r["player_id"])
 score[(r["kyoku_id"],r["player_id"])]=r["score"]-previous.get(key,25000)
 previous[key]=r["score"]
R=collections.defaultdict(list)
for r in q("""SELECT e.kyoku_id,e.id event_id,e.event_order ord,
r.actor_player_id player_id,r.is_accepted
FROM reach_event r JOIN event e ON e.id=r.event_id
ORDER BY e.kyoku_id,e.event_order"""):
 R[r["kyoku_id"]].append(r)
W=collections.defaultdict(list)
for r in q("""SELECT e.kyoku_id,e.id event_id,e.event_order ord,e.type,
a.actor_player_id winner,a.target_player_id loser,
a.agari_points,a.honba_points
FROM agari_event a JOIN event e ON e.id=a.event_id ORDER BY e.kyoku_id,e.event_order"""):
 W[r["kyoku_id"]].append(r)
D=collections.defaultdict(list)
for r in q("""SELECT e.kyoku_id,e.event_order ord,d.actor_player_id player_id,
d.tile,d.is_reach_declaration,d.is_tsumogiri
FROM discard_event d JOIN event e ON e.id=d.event_id
ORDER BY e.kyoku_id,e.event_order"""):
 D[r["kyoku_id"]].append(r)
entries=[]
for ky,ree in R.items():
 acc=[x for x in ree if x["is_accepted"]==1]
 if not acc:continue
 first=min(acc,key=lambda x:x["ord"])
 base=K[ky]
 for x in acc:
  actor=x["player_id"]
  ddecl=[d for d in D[ky] if d["player_id"]==actor and d["is_reach_declaration"] and d["ord"]>x["ord"]]
  if not ddecl:raise ValueError(f"missing reach disc {ky} {actor}")
  after=min(d["ord"] for d in ddecl)
  ws=[w for w in W[ky] if w["ord"]>after]
  win_self=[w for w in ws if w["winner"]==actor]
  win_others=[w for w in ws if w["winner"]!=actor]
  chased=[r for r in acc if r["ord"]>x["ord"] and r["player_id"]!=actor]
  own_ron_dealin=[w for w in win_others if w["type"]=="ron" and w["loser"]==actor]
  self_pts=score[(ky,actor)]
  entries.append(dict(**base,player_id=actor,player_name=P[actor],reach_id=x["event_id"],
   is_first=int(x["event_id"]==first["event_id"]),
   is_later=int(x["event_id"]!=first["event_id"]),
   first_reacher_id=first["player_id"],
   own_win=int(bool(win_self)),own_ron=int(any(w["type"]=="ron" for w in win_self)),
   own_tsumo=int(any(w["type"]=="tsumo" for w in win_self)),
   others_win=int(bool(win_others)),
   own_dealin=int(bool(own_ron_dealin)),
   draw=int(not bool(ws)),
   followed_by_riichi=int(bool(chased)),
   other_reach_count=len(chased),n_reachers=len(acc),
   own_points=self_pts,
   own_win_point_delta=self_pts if win_self else 0,
   own_dealin_point_delta=self_pts if own_ron_dealin else 0,
   points_gained_from_others=sum((w["agari_points"] or 0)+(w["honba_points"] or 0) for w in win_self),
   self_ron_target_players=",".join(str(w["loser"]) for w in win_self if w["type"]=="ron"),
   reached_before_other=int(len(acc)>1 and x["event_id"]==first["event_id"]),
   reached_after_other=int(x["event_id"]!=first["event_id"])
  ))
print("COUNT",len(entries),"PERSONS",len({x["player_id"] for x in entries}),"SONODA",sum(x["player_id"]==sonoda_id for x in entries),flush=True)
def summ(rs):
 n=len(rs)
 if not n:return None
 s=lambda key:sum(x[key] for x in rs)
 pct=lambda key:round(100*s(key)/n,3)
 return dict(n=n,won=s("own_win"),win_pct=pct("own_win"),ron=s("own_ron"),tsumo=s("own_tsumo"),
   other_win=s("others_win"),other_win_pct=pct("others_win"),
   ryukyoku=s("draw"),ryukyoku_pct=pct("draw"),
   dealin=s("own_dealin"),dealin_pct=pct("own_dealin"),
   followed_by_reach=s("followed_by_riichi"),followed_by_reach_pct=pct("followed_by_riichi"),
   score_total=s("own_points"),score_per_riichi=round(s("own_points")/n,1),
   positive_points=sum(x["own_points"]>0 for x in rs),negative_points=sum(x["own_points"]<0 for x in rs),zero_points=sum(x["own_points"]==0 for x in rs),
   self_win_score_total=s("own_win_point_delta"),
   own_dealin_delta_total=s("own_dealin_point_delta"))
allfirst=[x for x in entries if x["is_first"]]
alllater=[x for x in entries if x["is_later"]]
son=[x for x in entries if x["player_id"]==sonoda_id]
sonfirst=[x for x in son if x["is_first"]]
sonlater=[x for x in son if x["is_later"]]
otherfirst=[x for x in allfirst if x["player_id"]!=sonoda_id]
def league_player_values(metric,first_only=True,min_count=100):
 rows=collections.defaultdict(list)
 for e in (allfirst if first_only else entries):rows[e["player_id"]].append(e)
 vs=[(pid,len(rs),summ(rs)[metric]) for pid,rs in rows.items() if len(rs)>=min_count]
 return sorted(vs,key=lambda x:-x[2])
ranks={}
for metric in ("win_pct","other_win_pct","dealin_pct","ryukyoku_pct","followed_by_reach_pct","score_per_riichi"):
 v=league_player_values(metric,True,100)
 pos=next((i+1 for i,a in enumerate(v) if a[0]==sonoda_id),None)
 ranks[metric]=dict(rank_desc=pos,n_eligible=len(v),sonoda=summ(sonfirst)[metric],top5=[(P[pid],n,score) for pid,n,score in v[:5]],bottom5=[(P[pid],n,score) for pid,n,score in v[-5:]])
out=dict(
 definition="先制成立リーチは局で最初の成立リーチ、1成立イベント単位、未成立リーチ除外。得失点は局開始から終了までの局間点差、供託・本場・リーチ棒を含み、リーチ以降の手牌結果を区別していない",
 sonoda_all=summ(son),sonoda_first=summ(sonfirst),sonoda_later=summ(sonlater),
 all_players_all=summ(entries),all_players_first=summ(allfirst),all_players_later=summ(alllater),
 all_players_other_than_sonoda_first=summ(otherfirst),
 first_ranks_min100=ranks,
 sonoda_by_year={str(yy):dict(first=summ([x for x in sonfirst if x["year"]==yy]),all=summ([x for x in son if x["year"]==yy])) for yy in sorted({x["year"] for x in son})},
 sonoda_first_sample=[x for x in sonfirst if x["others_win"] and x["own_dealin"]][:40],
 sonoda_first_events=sonfirst
)
for key in ("sonoda_all","sonoda_first","sonoda_later","all_players_first","all_players_later","all_players_other_than_sonoda_first","first_ranks_min100","sonoda_by_year"):
 print(key.upper(),json.dumps(out[key],ensure_ascii=False),flush=True)
print("SANITY",json.dumps(dict(sonoda_self_plus_opponent_plus_draw_counts=[sum(x["own_win"] or x["others_win"] or x["draw"] for x in son),len(son)], first_reaches=len(allfirst),rounds_with_riichi=len({x["kyoku_id"] for x in entries})),ensure_ascii=False),flush=True)
Path("results").mkdir(exist_ok=True)
Path("results/sonoda_riichi_scout_20261125.json").write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
with Path("results/sonoda_riichi_scout_20261125.csv").open("w",encoding="utf-8-sig",newline="") as f:
 cols=list(sonfirst[0]);w=csv.DictWriter(f,cols);w.writeheader();w.writerows(sonfirst)
