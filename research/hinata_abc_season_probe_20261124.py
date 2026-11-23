#!/usr/bin/env python3
"""日向藍子 A/B/C 候補比較用。正式DBの読み取り限定。既存指標を変更しない。
統計定義は sql/tsukamu_per_100_kyoku_v01.sql / 2026-11-20正本と一致。
"""
import sqlite3,sys,json,csv,collections
from pathlib import Path
cn=sqlite3.connect("file:"+str(Path(sys.argv[1]).resolve())+"?mode=ro",uri=True)
cn.row_factory=sqlite3.Row
cn.execute("PRAGMA query_only=ON")
assert cn.execute("SELECT COUNT(*) FROM game").fetchone()[0]==2068
assert cn.execute("SELECT COUNT(*) FROM kyoku").fetchone()[0]==25238
P=cn.execute("SELECT id FROM player WHERE name='日向藍子'").fetchall()
assert len(P)==1
pid=P[0][0]
assert pid==16
def drows(sql,*args):return [dict(x) for x in cn.execute(sql,args)]
def p(n,d):return round(100*n/d,4) if d else None
# Existing don-tsuka v0.4 logic: a tile that some opponent can legally win by ron
draws_sql="""
WITH
draws AS MATERIALIZED (
 SELECT e.id draw_id,e.kyoku_id,e.event_order draw_order,g.id game_id,
        ls.start_year AS year, ss.stage,
        CASE WHEN substr(d.tile,1,1)='0' THEN '5'||substr(d.tile,2) ELSE d.tile END tile
 FROM draw_event d
 JOIN event e ON e.id=d.event_id JOIN kyoku k ON k.id=e.kyoku_id
 JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
 WHERE d.actor_player_id=?
),
last_actor AS MATERIALIZED (
 SELECT d.*,gr.player_id opponent_id,
 (SELECT e2.id FROM event e2 JOIN player_state ps2 ON ps2.event_id=e2.id
  WHERE e2.kyoku_id=d.kyoku_id AND e2.event_order<d.draw_order
    AND ps2.player_id=gr.player_id
  ORDER BY e2.event_order DESC,e2.id DESC LIMIT 1) actor_event_id
 FROM draws d JOIN game_player_result gr ON gr.game_id=d.game_id
 WHERE gr.player_id<>?
),
eligible_actor AS MATERIALIZED (
 SELECT a.*,ae.event_order actor_order FROM last_actor a
 JOIN player_state ps ON ps.event_id=a.actor_event_id AND ps.player_id=a.opponent_id
 JOIN event ae ON ae.id=a.actor_event_id WHERE ps.shanten_count=0
),
latest_snapshot AS MATERIALIZED (
 SELECT a.*,
 (SELECT pts.event_id FROM event se JOIN player_tenpai_state pts
  ON pts.event_id=se.id AND pts.player_id=a.opponent_id
  WHERE se.kyoku_id=a.kyoku_id AND se.event_order>=a.actor_order
    AND se.event_order<a.draw_order
  ORDER BY se.event_order DESC,se.id DESC LIMIT 1) snapshot_event_id
 FROM eligible_actor a
),
hit_draws AS MATERIALIZED (
 SELECT DISTINCT s.draw_id FROM latest_snapshot s
 JOIN player_tenpai_state pts ON pts.event_id=s.snapshot_event_id AND pts.player_id=s.opponent_id
 JOIN tenpai_agari_matrix m ON m.event_id=s.snapshot_event_id AND m.player_id=s.opponent_id
 WHERE pts.is_furiten=0 AND m.is_ron_agari=1
 AND (CASE WHEN substr(m.waiting_tile,1,1)='0'
      THEN '5'||substr(m.waiting_tile,2) ELSE m.waiting_tile END)=s.tile
)
SELECT d.year,d.stage,d.kyoku_id,d.draw_id,CASE WHEN h.draw_id IS NOT NULL THEN 1 ELSE 0 END hit
FROM draws d LEFT JOIN hit_draws h ON h.draw_id=d.draw_id
"""
draws=drows(draws_sql,pid,pid)
assert len(draws)==25620,len(draws)
assert sum(x["hit"] for x in draws)==585,sum(x["hit"] for x in draws)
annual_draws=collections.defaultdict(list)
for r in draws:annual_draws[r["year"]].append(r)
out=[]
for yr,a in annual_draws.items():
  hits=sum(x["hit"] for x in a)
  out.append(dict(year=yr,total_draws=len(a),hit_draws=hits,dontsuka_pct=p(hits,len(a)),hit_kyoku_count=len({x["kyoku_id"] for x in a if x["hit"]})))
out.sort(key=lambda r:r["year"])
print("DONTSUKA_SEASONS",json.dumps(out,ensure_ascii=False),flush=True)
# annual ryukyoku tenpai for both player and league
r=drows("""
 SELECT ls.start_year year,rp.player_id player_id, COUNT(*) AS ryukyoku_count,
 SUM(rp.is_tenpai) AS tenpai_count
 FROM ryukyoku_player rp
 JOIN event e ON e.id=rp.ryukyoku_event_id
 JOIN kyoku k ON k.id=e.kyoku_id
 JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
 GROUP BY ls.start_year,rp.player_id
""")
annual_ryu=collections.defaultdict(lambda:dict(league_ryukyoku=0,league_tenpai=0))
for x in r:
 y=annual_ryu[x["year"]]
 y["league_ryukyoku"]+=x["ryukyoku_count"]
 y["league_tenpai"]+=x["tenpai_count"]
 if x["player_id"]==pid:
  y["hinata_ryukyoku"]=x["ryukyoku_count"]
  y["hinata_tenpai"]=x["tenpai_count"]
for yr,d in sorted(annual_ryu.items()):
 d.update(year=yr,hinata_pct=p(d.get("hinata_tenpai",0),d.get("hinata_ryukyoku",0)),league_pct=p(d["league_tenpai"],d["league_ryukyoku"]))
print("RYUKYOKU_SEASONS",json.dumps(list(annual_ryu.values()),ensure_ascii=False),flush=True)
assert sum(x.get("hinata_ryukyoku",0) for x in annual_ryu.values())==405
assert sum(x.get("hinata_tenpai",0) for x in annual_ryu.values())==142

# Annual hoju rate and played rounds
rounds=drows("""
 SELECT ls.start_year year,kpr.player_id player_id, COUNT(*) AS kyoku_count
 FROM kyoku_player_result kpr JOIN kyoku k ON k.id=kpr.kyoku_id
 JOIN game g ON g.id=k.game_id JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
 GROUP BY ls.start_year,kpr.player_id
""")
deal=drows("""
 SELECT ls.start_year year, a.target_player_id player_id, COUNT(*) AS dealin
 FROM agari_event a JOIN event e ON e.id=a.event_id AND e.type='ron'
 JOIN kyoku k ON k.id=e.kyoku_id JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
 GROUP BY ls.start_year, a.target_player_id
""")
dc={(x["year"],x["player_id"]):x["dealin"] for x in deal}
annual_h=collections.defaultdict(lambda:dict(league_kyoku=0,league_dealin=0))
for x in rounds:
 y=annual_h[x["year"]]; y["league_kyoku"]+=x["kyoku_count"]
 y["league_dealin"]+=dc.get((x["year"],x["player_id"]),0)
 if x["player_id"]==pid:
  y.update(hinata_kyoku=x["kyoku_count"],hinata_dealin=dc.get((x["year"],pid),0))
for yr,d in sorted(annual_h.items()):
 d.update(year=yr,hinata_pct=p(d.get("hinata_dealin",0),d.get("hinata_kyoku",0)),league_pct=p(d["league_dealin"],d["league_kyoku"]))
assert sum(x.get("hinata_kyoku",0) for x in annual_h.values())==2054
assert sum(x.get("hinata_dealin",0) for x in annual_h.values())==226
print("DEALIN_SEASONS",json.dumps(list(annual_h.values()),ensure_ascii=False),flush=True)

# All winning hands, yaku names strictly from established agari_yaku, ignoring yakuman for han.
wins=drows("""
 SELECT a.event_id,a.actor_player_id player_id, p.name player_name, ls.start_year year,
 a.agari_points, a.han, a.is_yakuman, e.type win_type
 FROM agari_event a JOIN event e ON e.id=a.event_id
 JOIN kyoku k ON k.id=e.kyoku_id
 JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
 JOIN player p ON p.id=a.actor_player_id
""")
assert len(wins)==20173
for w in wins:w.update(dora_han=0,yaku_han=0,aka_han=0,ura_han=0,omote_han=0)
byevent={w["event_id"]:w for w in wins}
parts=drows("""
 SELECT ay.agari_event_id id,yn.name,ay.han
 FROM agari_yaku ay JOIN yaku_name yn ON yn.id=ay.yaku_name_id
""")
assert len(parts)==60096
for x in parts:
 w=byevent[x["id"]]
 if "ドラ" in x["name"]:
  w["dora_han"]+=x["han"]
  if x["name"]=="ドラ":w["omote_han"]+=x["han"]
  if x["name"]=="赤ドラ":w["aka_han"]+=x["han"]
  if x["name"]=="裏ドラ":w["ura_han"]+=x["han"]
 else:w["yaku_han"]+=x["han"]
assert all(w["dora_han"]+w["yaku_han"]==w["han"] for w in wins if not w["is_yakuman"])

annual_wins=collections.defaultdict(list)
player_year=collections.defaultdict(list)
for w in wins:
 annual_wins[w["year"]].append(w)
 player_year[(w["year"],w["player_id"])].append(w)
def metrics(ws):
 normal=[w for w in ws if not w["is_yakuman"]];den=len(normal)
 total_dora=sum(w["dora_han"] for w in normal)
 total_han=sum(w["han"] for w in normal)
 return dict(win_count=len(ws),nonyakuman_count=den,
  avg_win_points=round(sum(w["agari_points"] for w in ws)/len(ws),4),
  avg_dora_han=round(total_dora/den,4) if den else None,
  avg_yaku_han=round(sum(w["yaku_han"] for w in normal)/den,4) if den else None,
  avg_aka_han=round(sum(w["aka_han"] for w in normal)/den,4) if den else None,
  avg_ura_han=round(sum(w["ura_han"] for w in normal)/den,4) if den else None,
  avg_omote_han=round(sum(w["omote_han"] for w in normal)/den,4) if den else None,
  dora_han_share_pct=p(total_dora,total_han),
  no_dora_count=sum(w["dora_han"]==0 for w in ws),
  no_dora_pct=p(sum(w["dora_han"]==0 for w in ws),len(ws)))
r=[]
for yr, league_wins in annual_wins.items():
 k=player_year.get((yr,pid),[])
 if not k:continue
 hm=metrics(k);lm=metrics(league_wins)
 # year rank for average dora han, only active players with >= 20 wins
 peers20=[(j,metrics(z)) for (yy,j),z in player_year.items() if yy==yr and len(z)>=20]
 peers20.sort(key=lambda x:(-x[1]["avg_dora_han"],x[0]))
 r.append(dict(year=yr,hinata=hm,league=lm,
  dora_rank_min20=next((i for i,(j,z) in enumerate(peers20,1) if j==pid),None),
  qualified20_count=len(peers20)))
r.sort(key=lambda x:x["year"])
assert sum(x["hinata"]["win_count"] for x in r)==382
print("AGARI_DORA_SEASONS",json.dumps(r,ensure_ascii=False),flush=True)
print("AUDIT",json.dumps(dict(total_wins=len(wins),yaku_parts=len(parts),hinata_draws=len(draws),
  hinata_dontsuka_hit=sum(x["hit"] for x in draws)),ensure_ascii=False),flush=True)

output=Path("results");output.mkdir(exist_ok=True)
(output/"hinata_deepdive_seasons_20261124.json").write_text(json.dumps(dict(
 dontsuka=out,ryukyoku=list(annual_ryu.values()),dealin=list(annual_h.values()),agari_dora=r
),ensure_ascii=False,indent=2)+"\n",encoding="utf8")
with (output/"hinata_deepdive_seasons_20261124.csv").open("w",encoding="utf-8-sig",newline="") as f:
 fields=("season","draws","dontsuka_hits","dontsuka_pct","ryukyoku","ryukyoku_tenpai","ryukyoku_tenpai_pct","league_ryukyoku_tenpai_pct","played_kyoku","dealin","dealin_pct","league_dealin_pct","agari_count","avg_dora_han","league_avg_dora_han","avg_yaku_han","league_avg_yaku_han","dora_han_share_pct","league_dora_han_share_pct","no_dora_win_pct","league_no_dora_win_pct","dora_rank_min20","qualified20_count")
 wri=csv.DictWriter(f,fields);wri.writeheader()
 for a in out:
  yr=a["year"]; k=next(x for x in r if x["year"]==yr); t=annual_ryu[yr]; de=annual_h[yr]
  z=dict(season=f"{yr}-{str((yr+1)%100).zfill(2)}",draws=a["total_draws"],dontsuka_hits=a["hit_draws"],dontsuka_pct=a["dontsuka_pct"],
  ryukyoku=t["hinata_ryukyoku"],ryukyoku_tenpai=t["hinata_tenpai"],ryukyoku_tenpai_pct=t["hinata_pct"],league_ryukyoku_tenpai_pct=t["league_pct"],
  played_kyoku=de["hinata_kyoku"],dealin=de["hinata_dealin"],dealin_pct=de["hinata_pct"],league_dealin_pct=de["league_pct"],
  agari_count=k["hinata"]["win_count"],avg_dora_han=k["hinata"]["avg_dora_han"],league_avg_dora_han=k["league"]["avg_dora_han"],
  avg_yaku_han=k["hinata"]["avg_yaku_han"],league_avg_yaku_han=k["league"]["avg_yaku_han"],
  dora_han_share_pct=k["hinata"]["dora_han_share_pct"],league_dora_han_share_pct=k["league"]["dora_han_share_pct"],
  no_dora_win_pct=k["hinata"]["no_dora_pct"],league_no_dora_win_pct=k["league"]["no_dora_pct"],
  dora_rank_min20=k["dora_rank_min20"],qualified20_count=k["qualified20_count"])
  wri.writerow(z)
