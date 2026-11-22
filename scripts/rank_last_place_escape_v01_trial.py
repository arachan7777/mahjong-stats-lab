#!/usr/bin/env python3
"""土壇場ラス回避率 v0.1 試算。試合全期間、旧基準時点、主人公補正率と整合性照合。"""
from __future__ import annotations
import csv
import json
import sqlite3
import sys
from pathlib import Path

db = Path(sys.argv[1]).resolve()
con = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=90)
con.row_factory = sqlite3.Row
con.execute("PRAGMA query_only=ON")
out = Path("results")
out.mkdir(parents=True, exist_ok=True)
sql = Path("sql/last_place_escape_v01_trial.sql").read_text(encoding="utf-8")
protagonist_sql = Path("sql/protagonist_rate_v01.sql").read_text(encoding="utf-8")


def run(s: str):
    return [dict(r) for r in con.execute(s)]


def csv_dump(name: str, rows):
    if not rows:
        raise RuntimeError("No rows: " + name)
    with (out / name).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def save_json(name: str, data):
    (out / name).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


qc = con.execute("PRAGMA quick_check").fetchone()[0]
if qc != "ok":
    raise RuntimeError("DB quick_check: " + str(qc))


def compare(a: list[dict], p: list[dict]):
    pro = {r["player_id"]: r for r in p}
    for row in a:
        pid = row["player_id"]
        assert pid in pro, row
        # 第19指標から独立した新SQLの結果が一致すること。
        assert row["last_place_opportunities"] == pro[pid]["fourth_opportunities"], row
        assert row["fourth_to_first_count"] == pro[pid]["fourth_to_first_count"], row
        assert row["last_place_escapes"] == (
            row["fourth_to_first_count"]
            + row["fourth_to_second_count"]
            + row["fourth_to_third_count"]
        ), row
        assert row["last_place_escapes"] == (
            row["escape_with_own_agari_count"]
            + row["escape_without_own_agari_count"]
        ), row
        assert row["last_place_opportunities"] == (
            row["last_place_escapes"] + row["remained_fourth_count"]
        ), row
        if row["last_place_opportunities"] > 0:
            expected = round(100.0 * row["last_place_escapes"]
                             / row["last_place_opportunities"], 4)
            assert abs(expected - row["last_place_escape_pct"]) < .00011, row
        else:
            assert row["last_place_escape_pct"] is None, row
    # 第19指標には2～3着からの機会だけある選手も含まれる。4着経験者は部分集合。\n    assert set(r["player_id"] for r in a).issubset(set(pro)), "第19指標にない選手が含まれる"\n    assert sum(r["last_place_opportunities"] for r in a) == sum(r["fourth_opportunities"] for r in p)\n    assert sum(r["fourth_to_first_count"] for r in a) == sum(r["fourth_to_first_count"] for r in p)
    count = lambda key: sum(row[key] for row in a)
    return {
        "players": len(a),
        "opportunities": count("last_place_opportunities"),
        "escapes": count("last_place_escapes"),
        "escape_pct": round(100 * count("last_place_escapes")
                            / count("last_place_opportunities"), 4),
        "fourth_to_first": count("fourth_to_first_count"),
        "fourth_to_second": count("fourth_to_second_count"),
        "fourth_to_third": count("fourth_to_third_count"),
        "remained_fourth": count("remained_fourth_count"),
        "escape_with_own_agari": count("escape_with_own_agari_count"),
        "escape_without_own_agari": count("escape_without_own_agari_count"),
    }


all_rows = run(sql)
all_pro = run(protagonist_sql)
overall = compare(all_rows, all_pro)

# 試合日で2026-09-22までの旧基準に限定。
needle = "AND (p.stage IS NULL OR ss.stage = p.stage)"
if sql.count(needle) != 1 or protagonist_sql.count(needle) != 1:
    raise RuntimeError("期間絞り込み位置不明")
historical_sql = sql.replace(needle, needle + "\n    AND g.date <= '2026-09-22'")
historical_pro = protagonist_sql.replace(needle, needle + "\n    AND g.date <= '2026-09-22'")
old_rows = run(historical_sql)
old_summary = compare(old_rows, run(historical_pro))
assert overall["fourth_to_first"] == 21, overall
assert old_summary["fourth_to_first"] == 20, old_summary
assert overall["opportunities"] <= con.execute("SELECT COUNT(*) FROM game").fetchone()[0]
assert overall["escapes"] + overall["remained_fourth"] == overall["opportunities"]

csv_dump("last_place_escape_v01_trial_all_players.csv", all_rows)
csv_dump("last_place_escape_v01_trial_through_20260922.csv", old_rows)
save_json("last_place_escape_v01_trial_top25.json", all_rows[:25])
summary = {
    "quick_check": qc,
    "database_games": con.execute("SELECT COUNT(*) FROM game").fetchone()[0],
    "south4_games": con.execute(
        "SELECT COUNT(DISTINCT game_id) FROM kyoku WHERE round='2z4'"
    ).fetchone()[0],
    "all_periods": overall,
    "historical_through_2026_09_22": old_summary,
    "checks": [
        "same per-player starting-fourth denominator as 19th index",
        "same per-player fourth-to-first outcomes as 19th index",
        "fourth-to-first + fourth-to-second + fourth-to-third == escape total",
        "with and without self-agari == escape total",
        "escape total + remained-fourth == starting-fourth opportunities",
        "2026-09-22 historical fourth-to-first count == 20",
        "current-period fourth-to-first count == 21",
    ],
}
save_json("last_place_escape_v01_trial_summary.json", summary)
print("SUMMARY", json.dumps(summary, ensure_ascii=False), flush=True)
print("TOP25", json.dumps(all_rows[:25], ensure_ascii=False), flush=True)
print("VALIDATED all per-player and period identities", flush=True)
