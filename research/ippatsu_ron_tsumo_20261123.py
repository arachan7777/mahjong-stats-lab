#!/usr/bin/env python3
"""リーチ一発（ロン・ツモ別）研究用集計。
研究所正式DB固定2026-11-20 / 既存正式指標・DB・SQLは変更しない。
成立リーチを分母、リーチ和了を別分母とし、一発役（agari_yaku）から判定。
"""
import sqlite3,sys,csv,json,collections
from pathlib import Path
con=sqlite3.connect("file:"+sys.argv[1]+"?mode=ro",uri=True)
con.row_factory=sqlite3.Row
con.execute("PRAGMA query_only=ON")
assert con.execute("SELECT COUNT(*) FROM game").fetchone()[0]==2068
assert con.execute("SELECT COUNT(*) FROM kyoku").fetchone()[0]==25238
players={r["id"]:r["name"] for r in con.execute("SELECT id,name FROM player")}
yaku=con.execute("SELECT id FROM yaku_name WHERE name='一発'").fetchall()
assert len(yaku)==1,("一発の名称を確認",len(yaku))
yaku_id=yaku[0][0]

reach=[dict(x) for x in con.execute("""
 SELECT r.event_id,r.actor_player_id player_id,r.is_accepted,e.kyoku_id,e.event_order,
        ls.start_year,ss.stage
 FROM reach_event r JOIN event e ON e.id=r.event_id
 JOIN kyoku k ON k.id=e.kyoku_id
 JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
""")]
assert len(reach)==22961,("total reach changed",len(reach))
accepted=[r for r in reach if r["is_accepted"]]
assert len(accepted)==22205,("accepted reach changed",len(accepted))
agari=[dict(x) for x in con.execute("""
 SELECT a.event_id,e.kyoku_id,e.event_order,e.type,a.actor_player_id player_id,
        CASE WHEN EXISTS(
            SELECT 1 FROM agari_yaku ay WHERE ay.agari_event_id=a.event_id
            AND ay.yaku_name_id=?
        ) THEN 1 ELSE 0 END ippatsu
 FROM agari_event a JOIN event e ON e.id=a.event_id
""",(yaku_id,))]
by_key=collections.defaultdict(list)
for a in agari:by_key[(a["kyoku_id"],a["player_id"])].append(a)
assert all(a["type"] in ("ron","tsumo") for a in agari)
assert len(agari)==20173

rows=[]
for r in accepted:
 wins=[a for a in by_key[(r["kyoku_id"],r["player_id"])] if a["event_order"]>r["event_order"]]
 assert len(wins)<=1,(r,wins)
 w=wins[0] if wins else None
 rows.append({
   "reach_event_id":r["event_id"],"player_id":r["player_id"],"player_name":players[r["player_id"]],
   "start_year":r["start_year"],"stage":r["stage"],
   "kyoku_id":r["kyoku_id"],
   "is_reach_win":int(w is not None),
   "is_reach_ron":int(w is not None and w["type"]=="ron"),
   "is_reach_tsumo":int(w is not None and w["type"]=="tsumo"),
   "is_ippatsu_win":int(w is not None and w["ippatsu"]),
   "is_ippatsu_ron":int(w is not None and w["ippatsu"] and w["type"]=="ron"),
   "is_ippatsu_tsumo":int(w is not None and w["ippatsu"] and w["type"]=="tsumo"),
 })
assert len(rows)==len(accepted)
def aggs(rows,keys=()):
 groups=collections.defaultdict(list)
 for r in rows:groups[tuple(r[k] for k in keys)].append(r)
 out=[]
 for vals,rs in groups.items():
  count=len(rs)
  sums={k:sum(z[k] for z in rs) for k in
        ("is_reach_win","is_reach_ron","is_reach_tsumo","is_ippatsu_win","is_ippatsu_ron","is_ippatsu_tsumo")}
  d=dict(zip(keys,vals))
  d.update(reach_count=count,
       reach_win_count=sums["is_reach_win"],
       reach_ron_count=sums["is_reach_ron"],
       reach_tsumo_count=sums["is_reach_tsumo"],
       ippatsu_total=sums["is_ippatsu_win"],
       ippatsu_ron=sums["is_ippatsu_ron"],
       ippatsu_tsumo=sums["is_ippatsu_tsumo"],
       ippatsu_per_reach_pct=round(100*sums["is_ippatsu_win"]/count,4),
       ippatsu_ron_per_reach_pct=round(100*sums["is_ippatsu_ron"]/count,4),
       ippatsu_tsumo_per_reach_pct=round(100*sums["is_ippatsu_tsumo"]/count,4),
       ippatsu_per_reach_win_pct=round(100*sums["is_ippatsu_win"]/sums["is_reach_win"],4) if sums["is_reach_win"] else None,
       ippatsu_ron_per_reach_ron_pct=round(100*sums["is_ippatsu_ron"]/sums["is_reach_ron"],4) if sums["is_reach_ron"] else None,
       ippatsu_tsumo_per_reach_tsumo_pct=round(100*sums["is_ippatsu_tsumo"]/sums["is_reach_tsumo"],4) if sums["is_reach_tsumo"] else None,
       ippatsu_ron_share_pct=round(100*sums["is_ippatsu_ron"]/sums["is_ippatsu_win"],4) if sums["is_ippatsu_win"] else None,
       ippatsu_tsumo_share_pct=round(100*sums["is_ippatsu_tsumo"]/sums["is_ippatsu_win"],4) if sums["is_ippatsu_win"] else None,
       reach_win_pct=round(100*sums["is_reach_win"]/count,4))
  assert sums["is_reach_win"]==sums["is_reach_ron"]+sums["is_reach_tsumo"]
  assert sums["is_ippatsu_win"]==sums["is_ippatsu_ron"]+sums["is_ippatsu_tsumo"]
  assert sums["is_ippatsu_win"]<=sums["is_reach_win"]
  out.append(d)
 return out
league=aggs(rows)[0]
player=aggs(rows,("player_name",))
season=aggs(rows,("start_year",))
player_season=aggs(rows,("start_year","player_name"))
stage=aggs(rows,("stage",))
player_stage=aggs(rows,("stage","player_name"))
season_stage=aggs(rows,("start_year","stage"))

# Validate all ippatsu yaku wins exactly match an accepted reach and the winner's event.
ippatsu_ari={a["event_id"] for a in agari if a["ippatsu"]}
accepted_keys={(r["kyoku_id"],r["player_id"]):r["event_order"] for r in accepted}
assert len(accepted_keys)==len(accepted), "Duplicate accepted riichi by player in kyoku"
paired={a["event_id"] for a in agari if a["ippatsu"]
      and (a["kyoku_id"],a["player_id"]) in accepted_keys
      and accepted_keys[(a["kyoku_id"],a["player_id"])] < a["event_order"]}
assert ippatsu_ari==paired, ("Ippatsu yaku missing accepted reach",len(ippatsu_ari),len(paired))
assert league["ippatsu_total"]==len(ippatsu_ari)
assert sum(r["reach_count"] for r in player)==league["reach_count"]
assert sum(r["ippatsu_total"] for r in player)==league["ippatsu_total"]
assert sum(r["ippatsu_ron"] for r in player)==league["ippatsu_ron"]
assert sum(r["ippatsu_tsumo"] for r in player)==league["ippatsu_tsumo"]

for list_ in (player,player_season,player_stage,season,stage,season_stage):
 list_.sort(key=lambda x:(-x["ippatsu_per_reach_pct"],-x["reach_count"],x.get("player_name","")))
out=Path("results");out.mkdir(exist_ok=True)
for fname,data in (("ippatsu_all_players.csv",player),("ippatsu_season_all.csv",season),
 ("ippatsu_player_season.csv",player_season),("ippatsu_stage_all.csv",stage),
 ("ippatsu_player_stage.csv",player_stage),("ippatsu_season_stage_all.csv",season_stage)):
 with (out/fname).open("w",encoding="utf-8-sig",newline="") as f:
  w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
summary=dict(league=league,riichi_all=len(reach),accepted_riichi=len(accepted),
 all_wins=len(agari),ippatsu_yaku_wins=len(ippatsu_ari),
 top_unrestricted=player[:20],
 top_min100=[r for r in player if r["reach_count"]>=100][:20],
 top_min300=[r for r in player if r["reach_count"]>=300][:20],
 bottom_min100=sorted([r for r in player if r["reach_count"]>=100],
    key=lambda r:(r["ippatsu_per_reach_pct"],-r["reach_count"]))[:15])
(out/"ippatsu_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
print("AUDIT",json.dumps({k:summary[k] for k in
 ("league","riichi_all","accepted_riichi","all_wins","ippatsu_yaku_wins")},ensure_ascii=False),flush=True)
for r in player:
 print("PLAYER",json.dumps(r,ensure_ascii=False),flush=True)
print("TOP_MIN_100",json.dumps(summary["top_min100"][:15],ensure_ascii=False),flush=True)
print("TOP_MIN_300",json.dumps(summary["top_min300"][:15],ensure_ascii=False),flush=True)
print("BOTTOM_MIN_100",json.dumps(summary["bottom_min100"][:10],ensure_ascii=False),flush=True)
print("SEASON_TOTAL",json.dumps(season,ensure_ascii=False),flush=True)
