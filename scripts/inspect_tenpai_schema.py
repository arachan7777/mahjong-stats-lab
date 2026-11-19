#!/usr/bin/env python3
"""公開DBのスキーマ変更と昨シーズンの母数を確認する（独自指標は含まない）。"""

import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from check_latest_db import get_release, download_asset, extract_sqlite

def columns(db, table):
    return [r[1] for r in db.execute(f'PRAGMA table_info("{table}")')]

def scalar(db, query, params=()):
    return db.execute(query, params).fetchone()[0]

def main():
    result={"checked_at_utc":datetime.now(timezone.utc).isoformat(),"season_start_year":2025}
    rel=get_release()
    result["release_tag"]=rel["tag_name"]
    assets=[a for a in rel["assets"] if a["name"]=="database.zip"]
    if len(assets)!=1:
        raise RuntimeError("database.zip missing or duplicated")
    with tempfile.TemporaryDirectory() as d:
        tmp=Path(d)
        asset=assets[0]
        result["asset_sha256"]=download_asset(asset["browser_download_url"],asset["size"],tmp/"database.zip")
        result["archive"]=extract_sqlite(tmp/"database.zip",tmp/"db.sqlite3")
        db=sqlite3.connect((tmp/"db.sqlite3").resolve().as_uri()+"?mode=ro",uri=True)
        try:
            db.execute("PRAGMA query_only=ON")
            tables=["player_state","player_tenpai_state","tenpai_agari_matrix","draw_event"]
            result["columns"]={t:columns(db,t) for t in tables}
            ps=set(result["columns"]["player_state"])
            pts=set(result["columns"]["player_tenpai_state"])
            result["schema_checks"]={
                "old_player_state_is_furiten_absent":"is_furiten" not in ps,
                "new_player_tenpai_state_is_furiten_present":"is_furiten" in pts,
                "new_is_actor_present":"is_actor" in pts,
                "new_is_temporary_furiten_present":"is_temporary_furiten" in pts,
                "new_is_discard_furiten_present":"is_discard_furiten" in pts,
                "new_is_reach_furiten_present":"is_reach_furiten" in pts,
            }
            result["player54_season2025_draws"]=db.execute("""
                SELECT COUNT(*),COUNT(DISTINCT e.kyoku_id)
                FROM draw_event d
                JOIN event e ON e.id=d.event_id
                JOIN kyoku k ON k.id=e.kyoku_id
                JOIN game g ON g.id=k.game_id
                JOIN season_stage ss ON ss.id=g.season_stage_id
                JOIN league_season ls ON ls.id=ss.league_season_id
                WHERE ls.start_year=2025 AND d.actor_player_id=54
                """).fetchone()
            result["season2025_tsumo_accepted"]=scalar(db,"""
                SELECT COUNT(*) FROM agari_event ae
                JOIN event e ON e.id=ae.event_id
                JOIN kyoku k ON k.id=e.kyoku_id
                JOIN game g ON g.id=k.game_id
                JOIN season_stage ss ON ss.id=g.season_stage_id
                JOIN league_season ls ON ls.id=ss.league_season_id
                WHERE ls.start_year=2025 AND ss.stage='regular'
                  AND e.type='tsumo' AND ae.target_player_id IS NULL
                """)
            result["season2025_tenpai_actor_split"]=db.execute("""
                SELECT
                   COUNT(*) AS total,
                   SUM(CASE WHEN pts.is_actor=1 THEN 1 ELSE 0 END) AS actor,
                   SUM(CASE WHEN pts.is_actor=0 THEN 1 ELSE 0 END) AS other
                FROM player_tenpai_state pts
                JOIN event e ON e.id=pts.event_id
                JOIN kyoku k ON k.id=e.kyoku_id
                JOIN game g ON g.id=k.game_id
                JOIN season_stage ss ON ss.id=g.season_stage_id
                JOIN league_season ls ON ls.id=ss.league_season_id
                WHERE ls.start_year=2025
                """).fetchone()
            result["state_match"]=db.execute("""
                SELECT COUNT(*),
                  SUM(CASE WHEN pts.event_id IS NULL THEN 1 ELSE 0 END),
                  SUM(CASE WHEN pts.is_actor=0 THEN 1 ELSE 0 END)
                FROM player_state ps
                LEFT JOIN player_tenpai_state pts
                  ON pts.event_id=ps.event_id AND pts.player_id=ps.player_id
                WHERE ps.shanten_count=0
                """).fetchone()
            result["matrix_ron_during_furiten"]=scalar(db,"""
                SELECT COUNT(*) FROM tenpai_agari_matrix m
                JOIN player_tenpai_state pts
                  ON pts.event_id=m.event_id AND pts.player_id=m.player_id
                WHERE pts.is_furiten=1 AND m.is_ron_agari=1
                """)
            result["quick_check"]=list(db.execute("PRAGMA quick_check"))
        finally:
            db.close()
    Path("results").mkdir(exist_ok=True)
    Path("results/tenpai_schema_check.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
    if result["quick_check"]!=[("ok",)]:
        raise RuntimeError("integrity check failed")
    if not all(result["schema_checks"].values()):
        raise RuntimeError("unexpected schema")
    if not result["player54_season2025_draws"] or result["player54_season2025_draws"][0]==0:
        raise RuntimeError("missing 2025 season draws")

if __name__=="__main__":
    main()
