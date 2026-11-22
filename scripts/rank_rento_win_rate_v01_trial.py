#!/usr/bin/env python3
"""Mリーグ 連闘勝率：同日同卓の1戦目→2戦目、連闘2戦目と非連闘2戦目を比較。"""
from __future__ import annotations

import collections
import csv
import json
import math
import sqlite3
import sys
from pathlib import Path

db = Path(sys.argv[1]).resolve()
conn = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=90)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA query_only=ON")
out = Path("results")
out.mkdir(parents=True, exist_ok=True)

check = conn.execute("PRAGMA quick_check").fetchone()[0]
if check != "ok":
    raise RuntimeError("SQLite quick_check " + str(check))

sql = Path("sql/rento_win_rate_v01_trial.sql").read_text(encoding="utf-8")
records = [dict(row) for row in conn.execute(sql)]
if not records:
    raise RuntimeError("SQL returned no rows")

by_second = collections.defaultdict(list)
for r in records:
    by_second[r["second_game_id"]].append(r)
    assert r["is_repeat"] in (0, 1), r
    assert r["second_rank"] in (1, 2, 3, 4), r
    assert r["table_code"] in ("A", "B"), r
    assert r["first_official_id"][-1] == r["second_official_id"][-1], r
    assert r["first_game_id"] != r["second_game_id"], r
    assert r["first_rank"] in (1,2,3,4) if r["is_repeat"] else r["first_rank"] is None
    assert r["first_pt"] is not None if r["is_repeat"] else r["first_pt"] is None
    assert r["second_pt"] is not None
for second_id, group in by_second.items():
    assert len(group) == 4, (second_id,len(group))
    assert len({r["player_id"] for r in group}) == 4
    assert len({r["team_id"] for r in group}) == 4
    assert len({r["first_game_id"] for r in group}) == 1
    assert len({r["game_date"] for r in group}) == 1

# 第1・第2試合を成立させる組み合わせは1対1。
first_ids = [g[0]["first_game_id"] for g in by_second.values()]
assert len(set(first_ids)) == len(first_ids), "1戦目が複数の2戦目へ結び付いている"
# 元DBでその1戦目に本当に同じ選手がいたか独立確認。
all_first = {}
for row in conn.execute("SELECT game_id, player_id, rank FROM game_player_result WHERE game_id IN "
                        "(SELECT id FROM game WHERE day_game_number = 1)"):
    all_first[(row["game_id"],row["player_id"])] = row["rank"]
for r in records:
    first_rank = all_first.get((r["first_game_id"],r["player_id"]))
    assert first_rank == r["first_rank"], r
    assert (first_rank is not None) == bool(r["is_repeat"]), r

total_games = conn.execute("SELECT COUNT(*) FROM game").fetchone()[0]
repeated = [r for r in records if r["is_repeat"]]
nonrepeated = [r for r in records if not r["is_repeat"]]
all_second = records
players = sorted({r["player_id"] for r in records})
assert all_second and repeated and nonrepeated

def calc(rows: list[dict]) -> dict:
    n = len(rows)
    wins = sum(r["second_rank"] == 1 for r in rows)
    avg_rank = sum(r["second_rank"] for r in rows)/n if n else None
    pt = sum(float(r["second_pt"]) for r in rows)
    return {
        "opportunities": n,
        "wins": wins,
        "top_rate_pct": round(100*wins/n, 4) if n else None,
        "above_25pct": (100*wins/n > 25) if n else None,
        "fourths": sum(r["second_rank"] == 4 for r in rows),
        "fourth_pct": round(100*sum(r["second_rank"] == 4 for r in rows)/n,4) if n else None,
        "average_rank": round(avg_rank,4) if n else None,
        "average_pt": round(pt/n,4) if n else None,
    }

def check_group(name: str, subset: list[dict]) -> dict:
    repeat = [r for r in subset if r["is_repeat"]]
    normal = [r for r in subset if not r["is_repeat"]]
    first_winners = [r for r in repeat if r["first_rank"] == 1]
    first_not_winners = [r for r in repeat if r["first_rank"] != 1]
    result = {
        "total_second_game_player_rows": len(subset),
        "paired_second_games": len({r["second_game_id"] for r in subset}),
        "rento_second_game":calc(repeat),
        "not_rento_second_game":calc(normal),
        "all_second_game":calc(subset),
        "rento_after_first_game_win":calc(first_winners),
        "rento_after_first_game_not_win":calc(first_not_winners),
        "first_match_wins_in_rento":sum(r["first_rank"] == 1 for r in repeat),
        "rento_double_wins":sum(r["first_rank"] == 1 and r["second_rank"] == 1 for r in repeat)
    }
    assert len(repeat)+len(normal)==len(subset)
    assert (result["rento_after_first_game_win"]["opportunities"]+
            result["rento_after_first_game_not_win"]["opportunities"]==len(repeat))
    assert (result["rento_after_first_game_win"]["wins"]+
            result["rento_after_first_game_not_win"]["wins"]==
            result["rento_second_game"]["wins"])
    assert (result["rento_second_game"]["wins"]+
            result["not_rento_second_game"]["wins"]==
            result["all_second_game"]["wins"])
    return result

grouping={
  "全期間":records,
  "レギュラー": [r for r in records if r["stage"] == "regular"],
  "セミファイナル":[r for r in records if r["stage"] == "semifinal"],
  "ファイナル":[r for r in records if r["stage"] == "final"],
  "2025-26以降レギュラー":[r for r in records if r["stage"] == "regular" and r["season_start_year"] >= 2025],
  "白卓2025-26以降レギュラー":[r for r in records if r["stage"] == "regular" and r["season_start_year"] >= 2025 and r["table_code"] == "A"],
  "黒卓2025-26以降レギュラー":[r for r in records if r["stage"] == "regular" and r["season_start_year"] >= 2025 and r["table_code"] == "B"],
}
for year in sorted({r["season_start_year"] for r in records}):
    grouping[f"{year}シーズン"]=[r for r in records if r["season_start_year"] == year]
summaries={name:check_group(name,subset) for name,subset in grouping.items()}
player_rows=[]
for pid in players:
    player = next(x for x in records if x["player_id"]==pid)
    row=[x for x in records if x["player_id"]==pid]
    repeat=[x for x in row if x["is_repeat"]]
    non_repeat=[x for x in row if not x["is_repeat"]]
    a=calc(repeat)
    b=calc(non_repeat)
    first_win=calc([x for x in repeat if x["first_rank"]==1])
    first_not_win=calc([x for x in repeat if x["first_rank"]!=1])
    if a["opportunities"]==0:
        continue
    player_rows.append({
        "player_id":pid,
        "player_name":player["player_name"],
        "rento_second_count":a["opportunities"],
        "rento_second_wins":a["wins"],
        "rento_top_rate_pct":a["top_rate_pct"],
        "above_25pct":a["above_25pct"],
        "rento_second_fourth_pct":a["fourth_pct"],
        "rento_second_average_rank":a["average_rank"],
        "rento_second_average_pt":a["average_pt"],
        "ordinary_second_count":b["opportunities"],
        "ordinary_second_wins":b["wins"],
        "ordinary_second_top_rate_pct":b["top_rate_pct"],
        "rento_minus_ordinary_top_rate_pts": (
            round(a["top_rate_pct"]-b["top_rate_pct"],4)
            if b["opportunities"] else None),
        "rento_first_game_wins":sum(x["first_rank"]==1 for x in repeat),
        "rento_after_first_win_count":first_win["opportunities"],
        "rento_after_first_win_second_wins":first_win["wins"],
        "rento_after_first_nonwin_count":first_not_win["opportunities"],
        "rento_after_first_nonwin_second_wins":first_not_win["wins"]
    })

player_rows.sort(key=lambda r:(-r["rento_top_rate_pct"],-r["rento_second_count"],r["player_name"]))
assert sum(r["rento_second_count"] for r in player_rows)==len(repeated)
assert sum(r["rento_second_wins"] for r in player_rows)==sum(x["second_rank"]==1 for x in repeated)

def write_csv(filename: str, rows: list[dict]):
    if not rows:return
    with (out/filename).open("w", encoding="utf-8-sig", newline="") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

write_csv("rento_v01_all_player_rankings.csv",player_rows)
write_csv("rento_v01_second_game_full_sample.csv",records)
write_csv("rento_v01_player_atleast_5.csv",[r for r in player_rows if r["rento_second_count"]>=5])
write_csv("rento_v01_player_atleast_10.csv",[r for r in player_rows if r["rento_second_count"]>=10])

summary={
    "status":"SUCCESS",
    "db_quick_check":check,
    "db_total_games":total_games,
    "paired_days_table_games":len(by_second),
    "paired_first_games":len(set(first_ids)),
    "all_paired_second_player_rows":len(records),
    "players_with_rento":len(player_rows),
    "rento_occurrences":len(repeated),
    "nonrepeat_second_player_rows":len(nonrepeated),
    "scope":"同一日・同一ステージ・同一卓（公式試合ID末尾A/B）の第1試合・第2試合を照合",
    "count_policy":"連闘2戦目のトップ率。25%は4人麻雀の基準値として表示、連闘適性は25%超を仮のラベルとして示す。最低試合数の足切りはしない。",
    "warnings":"サンプル数によるばらつきと、連闘選出の選択バイアスに留意。25%超は統計的な優位性や因果関係を保証しない。",
    "summaries":summaries,
    "all_players":player_rows
}
(out/"rento_v01_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print("SUMMARY",json.dumps({k:v for k,v in summary.items() if k!="all_players"},ensure_ascii=False),flush=True)
print("PLAYER_ALL",json.dumps(player_rows,ensure_ascii=False),flush=True)
print("PLAYER_MIN5",json.dumps([r for r in player_rows if r["rento_second_count"]>=5],ensure_ascii=False),flush=True)
print("PLAYER_MIN10",json.dumps([r for r in player_rows if r["rento_second_count"]>=10],ensure_ascii=False),flush=True)
print("VERIFIED original DB pairing and all numerator-denominator identities",flush=True)
