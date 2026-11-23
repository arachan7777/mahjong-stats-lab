#!/usr/bin/env python3
"""萩原聖人 年度成績レギュラー／通算内訳。公式共通統計SQLを利用。"""
import sqlite3,json,csv,sys
from pathlib import Path
con=sqlite3.connect(f"file:{sys.argv[1]}?mode=ro",uri=True)
con.row_factory=sqlite3.Row
con.execute("PRAGMA query_only=ON")
assert con.execute("SELECT COUNT(*) FROM game").fetchone()[0]==2068
s=Path("sql/basic_mleague_points_by_period_v01.sql").read_text(encoding="utf8")
all_rows=[dict(r) for r in con.execute(s) if r["player_name"]=="萩原聖人"]
assert len([r for r in all_rows if r["period"]=="all"])==1
total=[r for r in all_rows if r["period"]=="all"][0]
year_all=sorted([r for r in all_rows if r["period"]=="season"],key=lambda x:x["season_start_year"])
year_regular=sorted([r for r in all_rows if r["period"]=="season_stage" and r["stage"]=="regular"],key=lambda x:x["season_start_year"])
assert len(year_all)==9 and len(year_regular)==9
assert sum(r["played_games"] for r in year_all)==total["played_games"]
assert abs(sum(r["total_points"] for r in year_all)-total["total_points"])<.001
assert all(r["player_name"]=="萩原聖人" for r in all_rows)
print("ALL",json.dumps(total,ensure_ascii=False))
for r in year_all:print("YEAR_ALL",json.dumps(r,ensure_ascii=False))
for r in year_regular:print("YEAR_REG",json.dumps(r,ensure_ascii=False))
print("OTHER_STAGE",json.dumps([r for r in all_rows if r["period"]=="season_stage" and r["stage"]!="regular"],ensure_ascii=False))
