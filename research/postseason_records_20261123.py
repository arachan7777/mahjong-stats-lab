#!/usr/bin/env python3
"""麻雀スタッツ研究所｜ポストシーズン戦績 (semifinal+final) ・独立研究抽出。"""
import sqlite3, csv, json, sys, collections
from pathlib import Path

db=Path(sys.argv[1])
con=sqlite3.connect(f"file:{db}?mode=ro",uri=True)
con.row_factory=sqlite3.Row
con.execute("PRAGMA query_only=ON")
assert con.execute("SELECT COUNT(*) FROM game").fetchone()[0]==2068
assert con.execute("SELECT COUNT(*) FROM kyoku").fetchone()[0]==25238

SOURCE_SQL=Path("sql/basic_mleague_points_by_period_v01.sql").read_text(encoding="utf8")
official=[dict(r) for r in con.execute(SOURCE_SQL)]
p_rows=[r for r in official if r["period"]=="season_stage" and r["stage"] in ("semifinal","final")]
assert p_rows

# independent raw table reconstruction
raw=[dict(r) for r in con.execute("""
 SELECT g.id game_id, ls.start_year season_start_year, ss.stage,
        gr.player_id, p.name player_name, gr.rank,
        (gr.league_points + gr.penalty_league_points) points,
        gr.team_id, t.name team_name
 FROM game g
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
 JOIN game_player_result gr ON gr.game_id=g.id
 JOIN player p ON p.id=gr.player_id
 JOIN team t ON t.id=gr.team_id
 WHERE ss.stage IN ('semifinal','final')
 ORDER BY ls.start_year,ss.stage,g.id,p.name
""")]
assert len(raw)==4*len(set(r["game_id"] for r in raw)), "Game must have 4 participants"
expected=collections.defaultdict(list)
for r in raw:expected[(r["season_start_year"],r["stage"],r["player_id"])].append(r)
assert len(expected)==len(p_rows)
for r in p_rows:
    arr=expected[(r["season_start_year"],r["stage"],r["player_id"])]
    assert r["played_games"]==len(arr)
    assert abs(r["total_points"]-round(sum(x["points"] for x in arr),1))<0.0001
    assert r["first_place_count"]==sum(x["rank"]==1 for x in arr)
    assert abs(r["avg_rank"]-round(sum(x["rank"] for x in arr)/len(arr),4))<0.0001

def summarise(records,by):
    buckets=collections.defaultdict(list)
    for record in records:
        buckets[tuple(record[k] for k in by)].append(record)
    out=[]
    for key,rs in buckets.items():
        n=len(rs)
        pts=round(sum(r["points"] for r in rs),1)
        top=sum(r["rank"]==1 for r in rs)
        ranks=sum(r["rank"] for r in rs)
        d=dict(zip(by,key))
        d.update(played_games=n,total_points=pts,points_per_game=round(sum(r["points"] for r in rs)/n,4),
                first_place_count=top,top_rate_pct=round(top*100/n,4),
                avg_rank=round(ranks/n,4),
                last_place_count=sum(r["rank"]==4 for r in rs))
        out.append(d)
    out.sort(key=lambda r:(-r["total_points"],-r["points_per_game"],r.get("player_name",r.get("team_name",""))))
    for idx,r in enumerate(out,1):r["points_rank"]=idx
    return out

player=summarise(raw,["player_id","player_name"])
semifinal=summarise([r for r in raw if r["stage"]=="semifinal"],["player_id","player_name"])
final=summarise([r for r in raw if r["stage"]=="final"],["player_id","player_name"])
by_year=summarise(raw,["season_start_year","player_id","player_name"])
team=summarise(raw,["team_id","team_name"])
by_team_year=summarise(raw,["season_start_year","team_id","team_name"])
by_stage_year=summarise(raw,["season_start_year","stage","player_id","player_name"])

# One game-day player appears once and is partitioned among postseason stages.
assert sum(r["played_games"] for r in player)==len(raw)
assert sum(r["played_games"] for r in semifinal)+sum(r["played_games"] for r in final)==len(raw)
assert sum(r["played_games"] for r in by_year)==len(raw)
assert sum(r["played_games"] for r in team)==len(raw)
assert sum(r["played_games"] for r in by_team_year)==len(raw)
assert sum(r["played_games"] for r in by_stage_year)==len(raw)
assert abs(sum(r["total_points"] for r in player)-sum(r["total_points"] for r in team))<=.0001
assert abs(sum(r["total_points"] for r in by_stage_year)-sum(r["total_points"] for r in player))<=.0001
season_total=sorted(set(r["season_start_year"] for r in raw))
assert 2026 not in season_total  # as of Nov 20, still in the regular season

out=Path("results");out.mkdir(exist_ok=True)
for name,rows in [
  ("postseason_player_total_20261123.csv",player),
  ("postseason_player_semifinal_20261123.csv",semifinal),
  ("postseason_player_final_20261123.csv",final),
  ("postseason_player_season_20261123.csv",by_year),
  ("postseason_team_total_20261123.csv",team),
  ("postseason_team_season_20261123.csv",by_team_year),
  ("postseason_player_season_stage_20261123.csv",by_stage_year)
]:
    with (out/name).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
info={
 "definition":"Mリーグ獲得ptはgame_player_result.league_points+penalty_league_points。セミファイナルとファイナルの試合単位の合算",
 "as_of":"2026-11-20",
 "seasons":[f"{y}-{(y+1)%100:02d}" for y in season_total],
 "postseason_games":len(set(r["game_id"] for r in raw)),
 "postseason_participations":len(raw),
 "postseason_players":len(player),
 "semifinal_games":len(set(r["game_id"] for r in raw if r["stage"]=="semifinal")),
 "final_games":len(set(r["game_id"] for r in raw if r["stage"]=="final")),
 "top_player":player[:15],
 "bottom_player":player[-10:],
 "stage_summaries":{
  "semifinal":semifinal[:10],
  "final":final[:10]
 },
 "team_ranking":team
}
(out/"postseason_summary_20261123.json").write_text(json.dumps(info,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print("CHECK_PASS",json.dumps({k:info[k] for k in ("seasons","postseason_games","postseason_participations","postseason_players","semifinal_games","final_games")},ensure_ascii=False),flush=True)
for r in player:print("PLAYER",json.dumps(r,ensure_ascii=False),flush=True)
for r in team:print("TEAM",json.dumps(r,ensure_ascii=False),flush=True)
print("BY_YEAR",json.dumps(by_year[:8],ensure_ascii=False),flush=True)
