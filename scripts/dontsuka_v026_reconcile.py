#!/usr/bin/env python3
"""Reconcile inherited basic don-tsuka counts with the approved 20261120 baseline.

The hit判定 CTE is inherited verbatim from rank_dontsuka_all_matches.py.
This audit only adds season filtering and exact count/rate comparisons; it does
not alter or reinterpret the established indicator.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import time
from pathlib import Path


SQL = r"""
WITH
draws AS MATERIALIZED (
 SELECT e.id draw_id,e.kyoku_id,e.event_order draw_order,g.id game_id,
 CASE WHEN substr(d.tile,1,1)='0' THEN '5'||substr(d.tile,2) ELSE d.tile END tile
 FROM draw_event d JOIN event e ON e.id=d.event_id
 JOIN kyoku k ON k.id=e.kyoku_id JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
 WHERE d.actor_player_id=? AND ls.start_year=?
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
 AND se.event_order<a.draw_order ORDER BY se.event_order DESC,se.id DESC LIMIT 1) snapshot_event_id
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
SELECT COUNT(*),COUNT(h.draw_id),COUNT(DISTINCT d.kyoku_id)
FROM draws d LEFT JOIN hit_draws h ON h.draw_id=d.draw_id
"""


def load_reference(path: Path) -> tuple[
    dict[str, dict[str, tuple[int, int, float]]],
    dict[str, tuple[int, int, float]],
]:
    by_season: dict[str, dict[str, tuple[int, int, float]]] = {}
    overall: dict[str, tuple[int, int, float]] = {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            scope, player = row["集計範囲"], row["選手"]
            counts = (
                int(row["掴み回数"]),
                int(row["ツモ数"]),
                float(row["ドンツカ率（%）"]),
            )
            if scope == "全期間・全ステージ":
                overall[player] = counts
            else:
                by_season.setdefault(scope, {})[player] = counts
    return by_season, overall


def connect_readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    connection.row_factory = sqlite3.Row
    return connection


def audit(db_path: Path, reference_path: Path, out_path: Path) -> dict:
    by_season, overall = load_reference(reference_path)
    con = connect_readonly(db_path)
    check = con.execute("PRAGMA quick_check").fetchall()
    if [row[0] for row in check] != ["ok"]:
        raise RuntimeError(f"SQLite quick_check failed: {check[:5]}")

    seasons = con.execute("""
      SELECT DISTINCT ls.start_year
      FROM game g JOIN season_stage ss ON ss.id=g.season_stage_id
      JOIN league_season ls ON ls.id=ss.league_season_id
      ORDER BY ls.start_year
    """).fetchall()
    lines: list[dict] = []
    mismatches: list[dict] = []
    started = time.monotonic()
    for season_row in seasons:
        year = int(season_row[0])
        season = f"{year}-{str(year + 1)[-2:]}"
        expected_players = by_season.get(season, {})
        players = con.execute("""
          SELECT DISTINCT p.id,p.name
          FROM player p JOIN game_player_result gr ON gr.player_id=p.id
          JOIN game g ON g.id=gr.game_id
          JOIN season_stage ss ON ss.id=g.season_stage_id
          JOIN league_season ls ON ls.id=ss.league_season_id
          WHERE ls.start_year=? ORDER BY p.id
        """, (year,)).fetchall()
        for player in players:
            draws, hits, kyoku = con.execute(SQL, (player["id"], year, player["id"])).fetchone()
            expected = expected_players.get(player["name"])
            computed_rate = round(100.0 * hits / draws, 6) if draws else None
            status = (
                "match"
                if expected is not None
                and expected[:2] == (hits, draws)
                and computed_rate == round(expected[2], 6)
                else "mismatch"
            )
            entry = {
                "season": season,
                "player_id": player["id"],
                "player_name": player["name"],
                "reference_hits": expected[0] if expected else None,
                "reference_draws": expected[1] if expected else None,
                "reference_rate_pct": expected[2] if expected else None,
                "computed_hits": hits,
                "computed_draws": draws,
                "computed_rate_pct": computed_rate,
                "kyoku_with_draw": kyoku,
                "status": status,
            }
            lines.append(entry)
            if status != "match":
                mismatches.append(entry)
            print(f"{len(lines)} row(s): {season} {player['name']} {status}", flush=True)

    overall_rows: list[dict] = []
    # The all-season reference is independently rechecked using the repository's
    # inherited all-matches runner output, because its SQL has no season filter.
    all_stage_csv = out_path.parent / "dontsuka_all_matches.csv"
    if not all_stage_csv.exists():
        raise RuntimeError(f"Missing inherited all-stages output: {all_stage_csv}")
    with all_stage_csv.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            expected = overall.get(row["player_name"])
            computed = (int(row["hit_draws"]), int(row["total_draws"]))
            computed_rate = round(100.0 * computed[0] / computed[1], 6) if computed[1] else None
            entry = {
                "player_name": row["player_name"],
                "reference_hits": expected[0] if expected else None,
                "reference_draws": expected[1] if expected else None,
                "reference_rate_pct": expected[2] if expected else None,
                "computed_hits": computed[0],
                "computed_draws": computed[1],
                "computed_rate_pct": computed_rate,
                "status": "match"
                if expected is not None
                and expected[:2] == computed
                and expected[2] == computed_rate
                else "mismatch",
            }
            overall_rows.append(entry)
            if entry["status"] != "match":
                mismatches.append({"scope": "all_stages", **entry})

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as stream:
        fields = list(lines[0]) if lines else []
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(lines)
    summary = {
        "status": "一致" if not mismatches else "不一致",
        "db_file": str(db_path),
        "reference_file": str(reference_path),
        "season_player_rows": len(lines),
        "season_reconciliation_seconds": round(time.monotonic() - started, 2),
        "season_mismatch_count": sum(row["status"] != "match" for row in lines),
        "all_stage_player_rows": len(overall_rows),
        "all_stage_mismatch_count": sum(row["status"] != "match" for row in overall_rows),
        "all_stage_hits": sum(row["computed_hits"] for row in overall_rows),
        "all_stage_draws": sum(row["computed_draws"] for row in overall_rows),
        "season_player_mismatches": [row for row in mismatches if row.get("season")],
        "all_stage_player_mismatches": [row for row in mismatches if row.get("scope") == "all_stages"],
        "note": "既存ドンツカ判定の照合のみ。v0.26派生指標の実装・検証結果ではない。",
    }
    (out_path.parent / "dontsuka_v026_reconciliation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    con.close()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("reference_csv", type=Path)
    parser.add_argument("--output", type=Path, default=Path("results/dontsuka_v026_season_reconciliation.csv"))
    args = parser.parse_args()
    report = audit(args.database, args.reference_csv, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "一致" else 1


if __name__ == "__main__":
    raise SystemExit(main())
