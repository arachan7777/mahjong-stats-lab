#!/usr/bin/env python3
"""Run the v0.26 draw × opponent base extraction on the approved SQLite release.

This stage covers the inherited basic don-tsuka predicate and denominator plus
single/double/triple-opponent counts. It is not the full v0.26 indicator suite.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path


APPROVED_RELEASE = "20261120-2341-04338cbb"
APPROVED_COUNTS = {"game": 2068, "kyoku": 25238, "player": 56, "draw_event": 1257732}
SQL_PATH = Path(__file__).resolve().parents[1] / "sql" / "dontsuka_v026_draw_opponent_base.sql"


def connect_readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    connection.row_factory = sqlite3.Row
    return connection


def verify_database(connection: sqlite3.Connection, release_id: str) -> dict:
    if release_id != APPROVED_RELEASE:
        raise RuntimeError(
            f"Release mismatch: requested {release_id}; approved {APPROVED_RELEASE}"
        )
    quick_check = [row[0] for row in connection.execute("PRAGMA quick_check")]
    if quick_check != ["ok"]:
        raise RuntimeError(f"SQLite quick_check failed: {quick_check[:5]}")
    counts = {
        table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in APPROVED_COUNTS
    }
    if counts != APPROVED_COUNTS:
        raise RuntimeError(f"Approved-release row counts differ: {counts}")
    latest_game_date = connection.execute("SELECT MAX(date) FROM game").fetchone()[0]
    if latest_game_date != "2026-11-20":
        raise RuntimeError(f"Unexpected latest game date: {latest_game_date}")
    return {"release_id": release_id, "quick_check": "ok", "counts": counts,
            "latest_game_date": latest_game_date}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def players(connection: sqlite3.Connection, selected_id: int | None) -> list[sqlite3.Row]:
    if selected_id is not None:
        return connection.execute("SELECT id,name FROM player WHERE id=?", (selected_id,)).fetchall()
    return connection.execute("""
      SELECT DISTINCT p.id,p.name
      FROM player p JOIN game_player_result gr ON gr.player_id=p.id
      JOIN game g ON g.id=gr.game_id
      ORDER BY p.id
    """).fetchall()


def run_player(connection: sqlite3.Connection, sql: str, player_id: int,
               start_year: int | None, stage: str | None,
               events_stream=None, events_header_written: list[bool] | None = None) -> list[dict]:
    stats: dict[tuple[int, str], dict] = defaultdict(lambda: {
        "draw_count": 0,
        "dontsuka_count": 0,
        "opponent_dontsuka_count": 0,
        "multi_opponent_draw_count": 0,
        "double_dontsuka_count": 0,
        "triple_dontsuka_count": 0,
        "non_dontsuka_draw_count": 0,
    })
    params = {"player_id": player_id, "start_year": start_year, "stage": stage}
    cursor = connection.execute(sql, params)
    event_writer = None
    if events_stream is not None:
        event_writer = csv.DictWriter(
            events_stream,
            fieldnames=[column[0] for column in cursor.description],
        )
        if events_header_written is not None and not events_header_written[0]:
            event_writer.writeheader()
            events_header_written[0] = True
    current_id = None
    current_key = None
    current_hits = 0
    current_opponent_rows = 0
    expected_opponent_rows = 0

    def flush() -> None:
        if current_id is None:
            return
        if expected_opponent_rows != 3:
            raise RuntimeError(
                f"Draw {current_id} has {expected_opponent_rows} opponent rows; expected 3"
            )
        record = stats[current_key]
        record["draw_count"] += 1
        record["opponent_dontsuka_count"] += current_hits
        if current_hits:
            record["dontsuka_count"] += 1
        else:
            record["non_dontsuka_draw_count"] += 1
        if current_hits >= 2:
            record["multi_opponent_draw_count"] += 1
            record["double_dontsuka_count"] += current_hits == 2
            record["triple_dontsuka_count"] += current_hits == 3

    while True:
        batch = cursor.fetchmany(10000)
        if not batch:
            break
        for row in batch:
            if event_writer is not None:
                event_writer.writerow(dict(row))
            draw_id = row["draw_event_id"]
            key = (row["season_start_year"], row["stage"])
            if draw_id != current_id:
                flush()
                current_id, current_key = draw_id, key
                current_hits = 0
                expected_opponent_rows = 0
            expected_opponent_rows += 1
            current_hits += int(row["is_dontsuka"] or 0)
    flush()

    return [
        {"player_id": player_id, "season_start_year": key[0], "stage": key[1], **value}
        for key, value in sorted(stats.items())
    ]


def compare_all_stage_totals(rows: list[dict], reference_csv: Path) -> dict:
    expected: dict[str, tuple[int, int, float]] = {}
    with reference_csv.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row["集計範囲"] == "全期間・全ステージ":
                expected[row["選手"]] = (
                    int(row["掴み回数"]), int(row["ツモ数"]),
                    float(row["ドンツカ率（%）"]),
                )
    totals: dict[int, dict] = defaultdict(lambda: {"hits": 0, "draws": 0})
    names: dict[int, str] = {}
    for row in rows:
        totals[row["player_id"]]["hits"] += row["dontsuka_count"]
        totals[row["player_id"]]["draws"] += row["draw_count"]
        names[row["player_id"]] = row["player_name"]
    mismatches = []
    for player_id, result in totals.items():
        name = names[player_id]
        computed_rate = round(100.0 * result["hits"] / result["draws"], 6) if result["draws"] else None
        prior = expected.get(name)
        if prior is None or prior[:2] != (result["hits"], result["draws"]) or prior[2] != computed_rate:
            mismatches.append({"player_id": player_id, "name": name,
                               "expected": prior, "computed": {**result, "rate_pct": computed_rate}})
    return {"reference_players": len(expected), "computed_players": len(totals),
            "mismatch_count": len(mismatches), "mismatches": mismatches}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("--release-id", default=APPROVED_RELEASE)
    parser.add_argument("--player-id", type=int)
    parser.add_argument("--season-start-year", type=int)
    parser.add_argument("--stage", choices=("regular", "semifinal", "final"))
    parser.add_argument("--legacy-reference-csv", type=Path)
    parser.add_argument("--events-csv", type=Path,
                        help="Write draw × opponent source rows; use player/season/stage filters to limit output")
    parser.add_argument("--output-dir", type=Path, default=Path("results/dontsuka_v026"))
    args = parser.parse_args()

    started = time.monotonic()
    connection = connect_readonly(args.database)
    manifest = verify_database(connection, args.release_id)
    manifest["database_sha256"] = sha256_file(args.database)
    sql = SQL_PATH.read_text(encoding="utf-8")
    all_rows: list[dict] = []
    selected_players = players(connection, args.player_id)
    event_header_written = [False]
    if args.events_csv:
        args.events_csv.parent.mkdir(parents=True, exist_ok=True)
        with args.events_csv.open("w", encoding="utf-8-sig", newline="") as event_stream:
            for index, player in enumerate(selected_players, 1):
                print(f"extract {index}/{len(selected_players)} {player['name']}", flush=True)
                all_rows.extend(run_player(
                    connection, sql, player["id"], args.season_start_year, args.stage,
                    event_stream, event_header_written,
                ))
    else:
        for index, player in enumerate(selected_players, 1):
            print(f"extract {index}/{len(selected_players)} {player['name']}", flush=True)
            all_rows.extend(run_player(connection, sql, player["id"],
                                       args.season_start_year, args.stage))
    connection.close()

    names = {player["id"]: player["name"] for player in selected_players}
    for row in all_rows:
        row["player_name"] = names[row["player_id"]]
        row["dontsuka_rate_pct"] = (
            round(100.0 * row["dontsuka_count"] / row["draw_count"], 6)
            if row["draw_count"] else None
        )

    totals = {key: sum(row[key] for row in all_rows) for key in (
        "draw_count", "dontsuka_count", "opponent_dontsuka_count",
        "multi_opponent_draw_count", "double_dontsuka_count",
        "triple_dontsuka_count", "non_dontsuka_draw_count",
    )}
    single_dontsuka_count = totals["dontsuka_count"] - totals["multi_opponent_draw_count"]
    consistency_checks = {
        "draw_denominator_partition": (
            totals["dontsuka_count"] + totals["non_dontsuka_draw_count"]
            == totals["draw_count"]
        ),
        "multi_target_partition": (
            totals["double_dontsuka_count"] + totals["triple_dontsuka_count"]
            == totals["multi_opponent_draw_count"]
        ),
        "opponent_rows_equal_by_type": (
            totals["opponent_dontsuka_count"]
            == single_dontsuka_count
            + 2 * totals["double_dontsuka_count"]
            + 3 * totals["triple_dontsuka_count"]
        ),
        "all_draws_have_three_opponents": True,
    }
    if not all(consistency_checks.values()):
        manifest["status"] = "mismatch"
        manifest["error"] = "Internal draw/classification consistency check failed"
    manifest["base_counts"] = totals
    manifest["single_dontsuka_count"] = single_dontsuka_count
    manifest["consistency_checks"] = consistency_checks

    manifest["scope"] = {"player_id": args.player_id,
                         "season_start_year": args.season_start_year, "stage": args.stage}
    manifest["summary_rows"] = len(all_rows)
    manifest["elapsed_seconds"] = round(time.monotonic() - started, 2)
    if args.legacy_reference_csv and args.player_id is None and args.season_start_year is None and args.stage is None:
        manifest["legacy_comparison"] = compare_all_stage_totals(all_rows, args.legacy_reference_csv)
        manifest["status"] = (
            "success"
            if not manifest["legacy_comparison"]["mismatch_count"]
            and all(consistency_checks.values())
            else "mismatch"
        )
    else:
        manifest["status"] = (
            "computed; comparison not requested"
            if all(consistency_checks.values()) else "mismatch"
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.output_dir / "dontsuka_v026_basic_by_player_season_stage.csv"
    if all_rows:
        with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(all_rows[0]))
            writer.writeheader()
            writer.writerows(all_rows)
    (args.output_dir / "dontsuka_v026_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 1 if manifest.get("status") == "mismatch" else 0


if __name__ == "__main__":
    sys.exit(main())
