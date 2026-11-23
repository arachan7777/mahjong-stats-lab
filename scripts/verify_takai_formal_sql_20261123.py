#!/usr/bin/env python3
"""Formal standalone SQL regression, frozen DB, query_only mode."""
import sqlite3,sys,json,time
from pathlib import Path
con=sqlite3.connect("file:"+sys.argv[1]+"?mode=ro",uri=True)
con.row_factory=sqlite3.Row
con.execute("PRAGMA query_only=ON")
con.execute("PRAGMA temp_store=MEMORY")
assert con.execute("PRAGMA quick_check").fetchone()[0]=="ok"
assert con.execute("SELECT COUNT(*) FROM game").fetchone()[0]==2068
def run(path):
    code=Path(path).read_text(encoding="utf-8")
    t=time.monotonic()
    rows=[dict(z) for z in con.execute(code)]
    print("RUN",path,"rows",len(rows),"seconds",round(time.monotonic()-t,2),flush=True)
    assert len(rows)>100
    assert {x["period"] for x in rows}=={"all","season","stage","season_stage"}
    assert len([x for x in rows if x["period"]=="all"])==56
    return rows
def one(rows,scope="all",year=None,stage=None,name="多井隆晴"):
    match=[x for x in rows if x["period"]==scope and x["season_start_year"]==year
           and x["stage"]==stage and x["player_name"]==name]
    assert len(match)==1,(scope,year,stage,name,len(match))
    return match[0]
def matches(actual,expected):
    assert actual==expected,(actual,expected)
win=run("sql/basic_avg_agari_turn_v01.sql")
w=one(win)
matches((w["event_count"],w["turn_total"],w["avg_turn"],w["league_avg_turn"],w["league_rank"]),(741,8519,11.4966,11.6958,13))
matches((one(win,"season",2025)["event_count"],one(win,"season",2025)["turn_total"]),(97,1111))
matches(one(win,"stage",stage="semifinal")["event_count"],64)
matches(one(win,"stage",stage="final")["event_count"],74)
first=run("sql/basic_avg_first_tenpai_turn_v01.sql")
f=one(first)
matches((f["event_count"],f["turn_total"],f["avg_turn"],f["league_avg_turn"],f["league_rank"]),(872,6993,8.0195,8.1976,10))
matches((one(first,"season",2025)["event_count"],one(first,"season",2025)["turn_total"]),(109,811))
matches((one(first,"season",2026)["event_count"],one(first,"season",2026)["turn_total"]),(44,324))
freq=run("sql/basic_first_tenpai_rate_v01.sql")
fr=one(freq)
matches((fr["first_count"],fr["played_kyoku"],fr["first_rate_pct"],fr["league_rate_pct"],fr["league_rank"]),(872,3479,25.0647,24.8831,25))
matches((one(freq,"season",2025)["first_count"],one(freq,"season",2025)["played_kyoku"]),(109,480))
matches((one(freq,"season",2026)["first_count"],one(freq,"season",2026)["played_kyoku"]),(44,193))
points=run("sql/basic_mleague_points_by_period_v01.sql")
p=one(points)
matches((p["played_games"],p["total_points"],p["points_per_game"],p["rank_total_points"]),(282,554.4,1.966,10))
matches((one(points,"stage",stage="regular")["played_games"],one(points,"stage",stage="regular")["total_points"]),(224,1034.9))
matches((one(points,"stage",stage="semifinal")["played_games"],one(points,"stage",stage="semifinal")["total_points"]),(29,-345.9))
matches((one(points,"stage",stage="final")["played_games"],one(points,"stage",stage="final")["total_points"]),(29,-134.6))
matches((one(points,"season_stage",2022,"final")["played_games"],one(points,"season_stage",2022,"final")["total_points"]),(5,153.4))
summary={"source_release":"20261120-2341-04338cbb",
 "sql_count":4,"all":{ "avg_agari_turn":w,"first_tenpai_turn":f,"first_tenpai_rate":fr,"points":p},
 "2025": {"avg_agari_turn":one(win,"season",2025),"first_tenpai_turn":one(first,"season",2025),
          "first_tenpai_rate":one(freq,"season",2025),"points":one(points,"season",2025)}}
Path("results").mkdir(exist_ok=True)
Path("results/formal_common_sql_20261123_verification.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
print("FORMAL_SQL_VERIFIED",json.dumps(summary,ensure_ascii=False),flush=True)
