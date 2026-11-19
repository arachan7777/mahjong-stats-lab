#!/usr/bin/env python3
"""2025-26に限定した公開DBの構造・母数確認。非公開の独自SQL全文は扱わない。"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from check_latest_db import download_asset, extract_sqlite, get_release, validate_sqlite

OLD_BASELINE = {
    "player_54_draws_2025": 4164,
    "player_54_kyoku_2025": 337,
    "regular_tsumo_2025": 1367,
    "player_54_dontsuka_hits_2025": 101,
    "regular_confirmed_last_tile_2025": 199,
}

def run():
    release = get_release()
    asset = next(a for a in release["assets"] if a["name"] == "database.zip")
    print("検証対象リリース", release["tag_name"], flush=True)
    with tempfile.TemporaryDirectory(prefix="mahjong2025-") as tmp:
        folder = Path(tmp)
        z = folder / "source.zip"
        db = folder / "database.sqlite3"
        download_asset(asset["browser_download_url"], asset["size"], z)
        extract_sqlite(z, db)
        validated = validate_sqlite(db)
        connection = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=60)
        try:
            connection.execute("PRAGMA query_only=ON")
            def scalar(sql):
                return connection.execute(sql).fetchone()[0]

            season = """
              FROM event e
              JOIN kyoku k ON k.id = e.kyoku_id
              JOIN game g ON g.id = k.game_id
              JOIN season_stage ss ON ss.id = g.season_stage_id
              JOIN league_season ls ON ls.id = ss.league_season_id
              WHERE ls.start_year = 2025
            """
            # SQL 01のドンツカ率の母数と同じ抽出条件。
            draws = scalar("SELECT COUNT(*) " + season + """
                AND EXISTS (
                  SELECT 1 FROM draw_event d
                  WHERE d.event_id = e.id AND d.actor_player_id = 54
                )
            """)
            distinct_kyoku = scalar("SELECT COUNT(DISTINCT e.kyoku_id) " + season + """
                AND EXISTS (
                  SELECT 1 FROM draw_event d
                  WHERE d.event_id = e.id AND d.actor_player_id = 54
                )
            """)
            # SQL 02のレギュラーのツモ和了母数と同じ条件。
            # SQL 02の母数と同じWHERE条件で集計する。
            regular_tsumo = scalar("""
                SELECT COUNT(*)
                FROM event e
                JOIN agari_event ae ON ae.event_id=e.id
                JOIN kyoku k ON k.id=e.kyoku_id
                JOIN game g ON g.id=k.game_id
                JOIN season_stage ss ON ss.id=g.season_stage_id
                JOIN league_season ls ON ls.id=ss.league_season_id
                WHERE ls.start_year=2025 AND ss.stage='regular'
                  AND e.type='tsumo' AND ae.target_player_id IS NULL
            """)
            season_games = scalar("""
                SELECT COUNT(*) FROM game g
                JOIN season_stage ss ON ss.id=g.season_stage_id
                JOIN league_season ls ON ls.id=ss.league_season_id
                WHERE ls.start_year=2025
            """)
            tables = {v[0] for v in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            relevant = [
                "event", "kyoku", "game", "draw_event", "player_state",
                "player_tenpai_state", "tenpai_agari_matrix", "agari_event",
                "reach_event", "game_player_result", "season_stage", "league_season",
                "haipai_event", "dora_indicator_event", "ankan_event",
                "shominkan_event", "daiminkan_event", "discard_event"
            ]
            columns = {
                t: [r[1] for r in connection.execute(f"PRAGMA table_info({t})")]
                if t in tables else []
                for t in relevant
            }
            try:
                connection.execute(
                    "SELECT ps.is_furiten FROM player_state ps LIMIT 1"
                ).fetchone()
                old_dontsuka_compatible = True
                old_dontsuka_error = None
            except sqlite3.Error as exc:
                old_dontsuka_compatible = False
                old_dontsuka_error = str(exc)

            output = {
                "release": release["tag_name"],
                "latest_db_checked": validated["quick_check"],
                "season": "2025-26",
                "measurements": {
                    "player_54_draws_2025": draws,
                    "player_54_kyoku_2025": distinct_kyoku,
                    "regular_tsumo_2025": regular_tsumo,
                    "games_2025": season_games,
                },
                "old_baseline": OLD_BASELINE,
                "denominators_match": {
                    "player_54_draws_2025": draws == 4164,
                    "player_54_kyoku_2025": distinct_kyoku == 337,
                    "regular_tsumo_2025": regular_tsumo == 1367,
                },
                "old_furiten_column_works": old_dontsuka_compatible,
                "old_furiten_column_error": old_dontsuka_error,
                "schema_columns": columns,
                "scope": "公開SQLを避け、共通期間の母数と構造だけ検査。独自指標の分子・率は未実行。",
            }
            print("=== 2025-26 比較結果 ===", flush=True)
            print(json.dumps(output, ensure_ascii=False, indent=2), flush=True)
            return output
        finally:
            connection.close()

if __name__ == "__main__":
    result = run()
    Path("2025_schema_report.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )
