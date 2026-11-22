#!/usr/bin/env python3
"""Mリーグの開始座位×白卓・黒卓、全体／卓別／同時開催日／年度別の試算。"""
from __future__ import annotations

import collections
import csv
import json
import math
import sqlite3
import statistics
import sys
from pathlib import Path

db = Path(sys.argv[1]).resolve()
conn = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=90)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA query_only=ON")
qc = conn.execute("PRAGMA quick_check").fetchone()[0]
if qc != "ok":
    raise RuntimeError("SQLite quick_check failed: " + str(qc))

output = Path("results")
output.mkdir(exist_ok=True)
sql = Path("research/seat_wind_white_black_v01.sql").read_text(encoding="utf-8")
records = [dict(row) for row in conn.execute(sql)]
if not records:
    raise RuntimeError("No player-game data extracted")

seat_order = ["1z", "2z", "3z", "4z"]
seat_label = {"1z": "東家", "2z": "南家", "3z": "西家", "4z": "北家"}
by_game = collections.defaultdict(list)
for row in records:
    by_game[row["game_id"]].append(row)
    assert row["seat_wind"] in seat_order, row
    assert row["table_name"] in {"白卓", "黒卓"}, row
    assert row["final_rank"] in (1, 2, 3, 4), row
    assert row["final_pt"] is not None, row

for game_id, part in by_game.items():
    assert len(part) == 4, (game_id, "not 4 player rows", len(part))
    assert set(x["seat_wind"] for x in part) == set(seat_order), game_id
    assert len(set(x["player_id"] for x in part)) == 4, game_id
    assert len(set(x["team_id"] for x in part)) == 4, game_id
    assert len(set(x["table_name"] for x in part)) == 1, game_id

db_games = conn.execute("SELECT COUNT(*) FROM game").fetchone()[0]
assert db_games == len(by_game), (db_games, len(by_game))
assert len(records) == db_games * 4

regular_since_two_table = [
    x for x in records
    if x["season_start_year"] >= 2025 and x["stage"] == "regular"
]
assert regular_since_two_table, "2025-26 onward regular season missing"

# 2卓同時開催日だけを公平に比較できるよう、両卓2試合ずつ実施された日を区別。
day_games = collections.defaultdict(lambda: {"白卓": set(), "黒卓": set()})
for r in regular_since_two_table:
    key = (r["season_start_year"], r["game_date"])
    day_games[key][r["table_name"]].add(r["game_id"])
four_games_days = {
    key for key, colors in day_games.items()
    if len(colors["白卓"]) == 2 and len(colors["黒卓"]) == 2
}
simultaneous = [
    x for x in regular_since_two_table
    if (x["season_start_year"], x["game_date"]) in four_games_days
]
assert simultaneous, "No verified 4-game concurrent days"

periods = {
    "二卓時代_レギュラー": regular_since_two_table,
    "二卓時代_同時開催日限定": simultaneous,
    "2025-26_レギュラー": [x for x in regular_since_two_table if x["season_start_year"] == 2025],
    "2026-27_レギュラー": [x for x in regular_since_two_table if x["season_start_year"] == 2026],
    "2018-19以降_全ステージ参考": records,
    "2018-19〜2024-25_全ステージ参考": [x for x in records if x["season_start_year"] < 2025],
}


def summarize(group_name: str, group: list[dict]) -> list[dict]:
    # 通算・白卓・黒卓は、最初に集計用レコードを重ねてから同じ式で算出。
    groups = {
        "白黒合算": group,
        "白卓": [r for r in group if r["table_name"] == "白卓"],
        "黒卓": [r for r in group if r["table_name"] == "黒卓"],
    }
    data = []
    for table_name, table_rows in groups.items():
        if not table_rows:
            continue
        for wind in seat_order:
            selected = [r for r in table_rows if r["seat_wind"] == wind]
            if not selected:
                raise RuntimeError("missing seat "+str((group_name,table_name,wind)))
            n = len(selected)
            rank_counts = {k: sum(r["final_rank"] == k for r in selected) for k in (1,2,3,4)}
            assert sum(rank_counts.values()) == n
            values = [float(x["final_pt"]) for x in selected]
            total = sum(values)
            data.append({
                "period": group_name,
                "table": table_name,
                "seat": seat_label[wind],
                "seat_code": wind,
                "games": n,
                "first_count": rank_counts[1],
                "second_count": rank_counts[2],
                "third_count": rank_counts[3],
                "fourth_count": rank_counts[4],
                "first_pct": round(100*rank_counts[1]/n,4),
                "fourth_pct": round(100*rank_counts[4]/n,4),
                "top2_pct": round(100*(rank_counts[1]+rank_counts[2])/n,4),
                "average_rank": round(sum(r["final_rank"] for r in selected)/n,4),
                "total_pt": round(total,4),
                "average_pt": round(total/n,4),
                "standard_error_pt": round(statistics.stdev(values)/math.sqrt(n),4) if n>1 else None,
                "average_final_score": round(sum(r["final_score"] for r in selected)/n,2),
                "team_count": len(set(r["team_id"] for r in selected)),
            })
        # 卓単位では東南西北は必ず同じ試合数
        counts = [r["games"] for r in data if r["period"]==group_name and r["table"]==table_name]
        assert len(set(counts)) == 1, (group_name,table_name,counts)
    return data


all_results = []
for period_name, subset in periods.items():
    all_results.extend(summarize(period_name, subset))
assert len(all_results) > 24

# 各集計単位の累計ポイントと1-4着件数を、元試合行へ復元して整合性検査。
for period_name, subset in periods.items():
    for table in ("白黒合算","白卓","黒卓"):
        relevant = subset if table=="白黒合算" else [r for r in subset if r["table_name"]==table]
        chosen = [r for r in all_results if r["period"]==period_name and r["table"]==table]
        if not relevant: continue
        assert len(chosen) == 4
        assert sum(x["games"] for x in chosen) == len(relevant)
        assert abs(sum(x["total_pt"] for x in chosen)-sum(x["final_pt"] for x in relevant)) < 0.005
        assert sum(x["first_count"] for x in chosen) == sum(x["final_rank"]==1 for x in relevant)
        assert sum(x["fourth_count"] for x in chosen) == sum(x["final_rank"]==4 for x in relevant)

def csv_write(filename: str, array: list[dict]):
    with (output / filename).open("w",newline="",encoding="utf-8-sig") as file:
        w = csv.DictWriter(file,fieldnames=list(array[0]))
        w.writeheader()
        w.writerows(array)

csv_write("seat_wind_all_splits.csv", all_results)

rankings={}
for period in periods:
    per_group={}
    for table in ("白黒合算","白卓","黒卓"):
        selected=[r for r in all_results if r["period"]==period and r["table"]==table]
        if selected:
            per_group[table]=sorted(selected,key=lambda x:(-x["average_pt"],x["average_rank"],-x["first_pct"]))
    rankings[period]=per_group

color_game_counts=collections.Counter(
    (r["season_start_year"],r["table_name"]) for r in regular_since_two_table
)
# 原票からの行なので4行で1試合
assert all(v % 4 == 0 for v in color_game_counts.values())

timeline={}
for k in ((2025,"白卓"),(2025,"黒卓"),(2026,"白卓"),(2026,"黒卓")):
    dates=sorted(x["game_date"] for x in regular_since_two_table
                 if (x["season_start_year"],x["table_name"])==k)
    timeline[str(k[0])+"-"+k[1]]={
       "games":color_game_counts.get(k,0)//4,
       "first_date":dates[0] if dates else None,
       "last_date":dates[-1] if dates else None
    }

summary={
  "status":"SUCCESS",
  "db_quick_check":qc,
  "all_db_games":db_games,
  "all_db_player_game_rows":len(records),
  "scope_regular_since_2025":"2025-26及び2026-27、レギュラーのみ。旧季とポストシーズン除外。",
  "regular_since_2025_games":len(regular_since_two_table)//4,
  "concurrent_days":len(four_games_days),
  "concurrent_games":len(simultaneous)//4,
  "table_timeline":timeline,
  "ranking_rule":"まず平均獲得ptの高い順。参考として1着率、4着率、平均順位を同時表示。優位性の因果は主張しない。",
  "seat_definition":"東1局最初の局のplayer_wind (1z=東 2z=南 3z=西 4z=北)",
  "table_definition":"公式試合ID末尾 A=白卓、B=黒卓（2025-26以降導入、以前Aのみ）。",
  "rank_definition":"DB保存の試合最終順位。Mリーグ同点順位はそのまま。",
  "points_definition":"リーグポイント+反則ポイント",
  "warning":"同じチームが年間の座位を事前に持つため、席そのものの因果効果とは限らない。2025-26は白卓だけの日やポストシーズンがある。",
  "rankings":rankings
}
(output/"seat_wind_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print("META",json.dumps({k:v for k,v in summary.items() if k!="rankings"},ensure_ascii=False),flush=True)
for kind in ["二卓時代_レギュラー","二卓時代_同時開催日限定",
             "2025-26_レギュラー","2026-27_レギュラー",
             "2018-19以降_全ステージ参考"]:
    for table,items in rankings[kind].items():
        simple=[{k:r[k] for k in ("seat","games","first_count","fourth_count","first_pct","fourth_pct","average_rank","average_pt","total_pt","standard_error_pt","team_count")} for r in items]
        print("RANKING",json.dumps({"period":kind,"table":table,"seats":simple},ensure_ascii=False),flush=True)
print("VERIFIED all four seat rows and point totals in each group",flush=True)
