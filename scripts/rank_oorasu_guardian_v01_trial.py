#!/usr/bin/env python3
"""オーラス守護神率 v0.1 試算。第19指標と順位遷移の整合性を検証。"""
from __future__ import annotations

import csv
import json
import sqlite3
import sys
from pathlib import Path

db = Path(sys.argv[1]).resolve()
conn = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=90)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA query_only=ON")
output = Path("results")
output.mkdir(parents=True, exist_ok=True)

guardian_sql = Path("sql/oorasu_guardian_v01_trial.sql").read_text(encoding="utf-8")
protagonist_sql = Path("sql/protagonist_rate_v01.sql").read_text(encoding="utf-8")
needle = "AND (p.stage IS NULL OR ss.stage = p.stage)"


def rows(s: str):
    return [dict(r) for r in conn.execute(s)]


def csv_dump(filename: str, records):
    if not records:
        raise RuntimeError("empty result " + filename)
    with (output / filename).open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def dump_json(filename: str, data):
    (output / filename).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )


def select_period(sql: str, cutoff: str | None):
    if cutoff is None:
        return sql
    if sql.count(needle) != 1:
        raise RuntimeError("SQL date-filter insertion point not unique")
    return sql.replace(needle, needle + "\n    AND g.date <= '" + cutoff + "'")


def checked_data(cutoff: str | None):
    g = rows(select_period(guardian_sql, cutoff))
    p = rows(select_period(protagonist_sql, cutoff))
    if not g or not p:
        raise RuntimeError("集計対象が空")
    sum_g = lambda key: sum(x[key] for x in g)
    sum_p = lambda key: sum(x[key] for x in p)

    for x in g:
        assert x["lead_opportunities"] == x["lead_defense_count"] + x["lost_lead_count"], x
        assert x["lead_defense_count"] == (
            x["defense_with_own_agari_count"] +
            x["defense_without_own_agari_count"]
        ), x
        assert x["lost_lead_count"] == (
            x["first_to_second_count"] +
            x["first_to_third_count"] +
            x["first_to_fourth_count"]
        ), x
        rate = round(100.0 * x["lead_defense_count"] / x["lead_opportunities"], 4)
        assert abs(rate - x["oorasu_guardian_pct"]) < 0.00011, x

    date_clause = " AND g.date <= '2026-09-22'" if cutoff else ""
    # 独立した試合・順位の行数照合。分母は第19指標の2～4着機会と排他的。
    game_count = conn.execute(
        "SELECT COUNT(*) FROM game g" +
        (" WHERE g.date <= '2026-09-22'" if cutoff else "")
    ).fetchone()[0]
    result_rows = conn.execute(
        "SELECT COUNT(*), SUM(CASE WHEN gpr.rank=1 THEN 1 ELSE 0 END) "
        "FROM game_player_result gpr JOIN game g ON g.id=gpr.game_id "
        "WHERE EXISTS (SELECT 1 FROM kyoku k WHERE k.game_id=g.id AND k.round='2z4')"
        + date_clause
    ).fetchone()
    total_participations, total_final_first = result_rows

    assert sum_g("lead_opportunities") + sum_p("opportunities") == total_participations, (
        "初期1着と2～4着の機会数で全参加者数を網羅", sum_g("lead_opportunities"), sum_p("opportunities"), total_participations
    )
    assert sum_g("lead_defense_count") + sum_p("protagonist_count") == total_final_first, (
        "開始1着の逃げ切りと2～4着の逆転で全トップを網羅",
        sum_g("lead_defense_count"), sum_p("protagonist_count"), total_final_first
    )
    assert sum_g("lead_defense_count") + sum_g("lost_lead_count") == sum_g("lead_opportunities")
    assert sum_g("defense_with_own_agari_count") + sum_g("defense_without_own_agari_count") == sum_g("lead_defense_count")
    assert sum_g("first_to_second_count") + sum_g("first_to_third_count") + sum_g("first_to_fourth_count") == sum_g("lost_lead_count")
    return g, {
        "database_games": game_count,
        "players_with_first_place_start": len(g),
        "first_place_start_opportunities": sum_g("lead_opportunities"),
        "lead_defenses": sum_g("lead_defense_count"),
        "guardian_pct": round(100.0 * sum_g("lead_defense_count") / sum_g("lead_opportunities"), 4),
        "defense_with_own_agari": sum_g("defense_with_own_agari_count"),
        "defense_without_own_agari": sum_g("defense_without_own_agari_count"),
        "lost_lead": sum_g("lost_lead_count"),
        "first_to_second": sum_g("first_to_second_count"),
        "first_to_third": sum_g("first_to_third_count"),
        "first_to_fourth": sum_g("first_to_fourth_count"),
        "protagonist_opportunities": sum_p("opportunities"),
        "protagonist_successes": sum_p("protagonist_count"),
        "all_final_first_rows": total_final_first,
        "all_player_game_rows": total_participations,
    }


qc = conn.execute("PRAGMA quick_check").fetchone()[0]
assert qc == "ok", qc
current_rows, current = checked_data(None)
old_rows, old = checked_data("2026-09-22")
assert current["protagonist_successes"] == 418, current
assert old["protagonist_successes"] == 395, old
assert current["protagonist_opportunities"] == 6199, current
assert old["protagonist_opportunities"] == 5792, old
assert current["database_games"] == 2068, current
assert old["database_games"] == 1932, old

csv_dump("oorasu_guardian_v01_trial_players.csv", current_rows)
csv_dump("oorasu_guardian_v01_trial_players_20260922.csv", old_rows)
dump_json("oorasu_guardian_v01_trial_top25.json", current_rows[:25])
dump_json("oorasu_guardian_v01_trial_min30.json", [
    x for x in current_rows if x["lead_opportunities"] >= 30
])
summary = {
    "sql": "sql/oorasu_guardian_v01_trial.sql",
    "validation": "SUCCESS",
    "database_quick_check": qc,
    "all_periods": current,
    "historical_through_2026_09_22": old,
    "consistency_checks": [
        "保持+陥落=1着開始機会",
        "保持（和了あり+なし）=保持総数",
        "陥落（2着+3着+4着）=陥落総数",
        "1着開始機会+第19指標の2～4着開始機会=全参加選手試合行",
        "1着防衛成功+第19指標の逆転トップ成功=全最終1着選手試合行",
        "第19指標の現行・過去の分子分母完全一致",
    ],
}
dump_json("oorasu_guardian_v01_trial_summary.json", summary)
print("SUMMARY", json.dumps(summary, ensure_ascii=False), flush=True)
print("TOP25", json.dumps(current_rows[:25], ensure_ascii=False), flush=True)
print("MIN30", json.dumps([r for r in current_rows if r["lead_opportunities"] >= 30][:25], ensure_ascii=False), flush=True)
print("VALIDATED all aggregate and cross-index identities", flush=True)
