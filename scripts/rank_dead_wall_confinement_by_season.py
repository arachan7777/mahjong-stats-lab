"""Season-level aggregation of the verified dead-wall confinement v0.2 episodes."""
import csv, json, sqlite3, sys
from collections import defaultdict
from pathlib import Path

db_path = sys.argv[1]
results = Path("results")
episodes_path = results / "dead_wall_confinement_v02_episodes.csv"
with episodes_path.open(encoding="utf-8-sig", newline="") as f:
    episodes = list(csv.DictReader(f))

con = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
con.row_factory = sqlite3.Row
season_rows = con.execute("""
SELECT k.id AS kyoku_id, ls.start_year, ls.end_year
FROM kyoku k
JOIN game g ON g.id=k.game_id
JOIN season_stage ss ON ss.id=g.season_stage_id
JOIN league_season ls ON ls.id=ss.league_season_id
""").fetchall()
season_by_kyoku = {r["kyoku_id"]: (r["start_year"], r["end_year"]) for r in season_rows}
player_rows = con.execute("SELECT id, name FROM player").fetchall()
player_names = {r["id"]: r["name"] for r in player_rows}

by_player = defaultdict(lambda: {
    "eligible_exhaustive_draw_kyoku_ids": set(),
    "wait_change_episode_count": 0,
    "initial_wait_tiles_total": 0,
    "dead_wall_wait_tiles_total": 0,
    "initial_dora_indicator_wait_tiles": 0,
    "final_dora_indicator_wait_tiles": 0,
})
by_season = defaultdict(lambda: {
    "eligible_exhaustive_draw_kyoku_ids": set(),
    "wait_change_episode_count": 0,
    "initial_wait_tiles_total": 0,
    "dead_wall_wait_tiles_total": 0,
})
for row in episodes:
    kyoku_id = int(row["kyoku_id"])
    player_id = int(row["player_id"])
    if kyoku_id not in season_by_kyoku:
        raise RuntimeError(f"Missing season for kyoku_id={kyoku_id}")
    season_start, season_end = season_by_kyoku[kyoku_id]
    key = (season_start, season_end, player_id)
    totals = by_player[key]
    totals["eligible_exhaustive_draw_kyoku_ids"].add(kyoku_id)
    totals["wait_change_episode_count"] += 1
    for field in ("initial_wait_tiles_total", "dead_wall_wait_tiles_total",
                  "initial_dora_indicator_wait_tiles", "final_dora_indicator_wait_tiles"):
        totals[field] += int(row[field.replace("_total", "")] if field in row else 0)
    # Source episode fields use initial_wait_tiles / dead_wall_wait_tiles.
    totals["initial_wait_tiles_total"] += 0
    season = by_season[(season_start, season_end)]
    season["eligible_exhaustive_draw_kyoku_ids"].add(kyoku_id)
    season["wait_change_episode_count"] += 1
    season["initial_wait_tiles_total"] += int(row["initial_wait_tiles"])
    season["dead_wall_wait_tiles_total"] += int(row["dead_wall_wait_tiles"])

# Rebuild player totals from the raw, verified episode columns; the loop above
# keeps only the episode/kyoku counts, while these are the authoritative sums.
for value in by_player.values():
    value["initial_wait_tiles_total"] = 0
    value["dead_wall_wait_tiles_total"] = 0
    value["initial_dora_indicator_wait_tiles"] = 0
    value["final_dora_indicator_wait_tiles"] = 0
for row in episodes:
    kyoku_id = int(row["kyoku_id"])
    player_id = int(row["player_id"])
    season_start, season_end = season_by_kyoku[kyoku_id]
    totals = by_player[(season_start, season_end, player_id)]
    totals["initial_wait_tiles_total"] += int(row["initial_wait_tiles"])
    totals["dead_wall_wait_tiles_total"] += int(row["dead_wall_wait_tiles"])
    totals["initial_dora_indicator_wait_tiles"] += int(row["initial_dora_indicators"])
    totals["final_dora_indicator_wait_tiles"] += int(row["final_dora_indicators"])

all_rows = []
for (start, end, player_id), t in by_player.items():
    den = t["initial_wait_tiles_total"]
    num = t["dead_wall_wait_tiles_total"]
    dora_den = t["initial_dora_indicator_wait_tiles"]
    dora_num = t["final_dora_indicator_wait_tiles"]
    all_rows.append({
        "season": f"{start}-{end}",
        "season_start_year": start,
        "player_id": player_id,
        "player_name": player_names[player_id],
        "eligible_exhaustive_draw_kyoku": len(t["eligible_exhaustive_draw_kyoku_ids"]),
        "wait_change_episode_count": t["wait_change_episode_count"],
        "initial_wait_tiles_total": den,
        "dead_wall_wait_tiles_total": num,
        "dead_wall_confinement_pct": round(100 * num / den, 4) if den else None,
        "initial_dora_indicator_wait_tiles": dora_den,
        "final_dora_indicator_wait_tiles": dora_num,
        "dead_wall_non_indicator_pct": round(100 * (num-dora_num) / (den-dora_den), 4)
            if den != dora_den else None,
    })

season_summary = []
for (start, end), t in sorted(by_season.items()):
    den, num = t["initial_wait_tiles_total"], t["dead_wall_wait_tiles_total"]
    season_summary.append({
        "season": f"{start}-{end}",
        "season_start_year": start,
        "eligible_exhaustive_draw_kyoku": len(t["eligible_exhaustive_draw_kyoku_ids"]),
        "wait_change_episode_count": t["wait_change_episode_count"],
        "initial_wait_tiles_total": den,
        "dead_wall_wait_tiles_total": num,
        "league_weighted_confinement_pct": round(100 * num / den, 4) if den else None,
        "players_with_eligible_episodes": sum(1 for r in all_rows
            if r["season_start_year"] == start),
    })

summary_by_start = {r["season_start_year"]: r for r in season_summary}
for r in all_rows:
    r["league_weighted_confinement_pct"] = summary_by_start[r["season_start_year"]]["league_weighted_confinement_pct"]
    r["difference_from_league_pp"] = round(r["dead_wall_confinement_pct"] - r["league_weighted_confinement_pct"], 4)

# Rank only within each season; this does not add a sample-size cutoff.
all_rows.sort(key=lambda r: (r["season_start_year"], -r["dead_wall_confinement_pct"],
                             -r["dead_wall_wait_tiles_total"], r["player_name"]))
for start in sorted(summary_by_start):
    rank = 0
    for r in [x for x in all_rows if x["season_start_year"] == start]:
        rank += 1
        r["season_rank"] = rank

with (results / "dead_wall_confinement_v02_by_season_all_players.csv").open(
        "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(all_rows[0]))
    w.writeheader()
    w.writerows(all_rows)
with (results / "dead_wall_confinement_v02_by_season_summary.csv").open(
        "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(season_summary[0]))
    w.writeheader()
    w.writerows(season_summary)
(results / "dead_wall_confinement_v02_by_season_top_bottom.json").write_text(
    json.dumps({
        "summary": season_summary,
        "top_bottom": {
            r["season"]: {
                "top3": [x for x in all_rows if x["season"] == r["season"]][:3],
                "bottom3": [x for x in all_rows if x["season"] == r["season"]][-3:],
            } for r in season_summary
        }
    }, ensure_ascii=False, indent=2), encoding="utf-8")

# Cross-check that the season grouping exactly preserves the verified all-time
# episode count and tile totals.
career = list(csv.DictReader((results / "dead_wall_confinement_v02_all_players.csv")
                              .open(encoding="utf-8-sig", newline="")))
assert sum(int(r["wait_change_episode_count"]) for r in all_rows) == sum(
    int(r["wait_change_episode_count"]) for r in career)
assert sum(int(r["initial_wait_tiles_total"]) for r in all_rows) == sum(
    int(r["initial_wait_tiles_total"]) for r in career)
assert sum(int(r["dead_wall_wait_tiles_total"]) for r in all_rows) == sum(
    int(r["dead_wall_wait_tiles_total"]) for r in career)
print(json.dumps({
    "seasons": season_summary,
    "season_player_rows": len(all_rows),
    "all_time_episodes_crosscheck": sum(int(r["wait_change_episode_count"]) for r in all_rows),
    "all_time_wait_tiles_crosscheck": sum(int(r["initial_wait_tiles_total"]) for r in all_rows),
    "all_time_dead_wall_tiles_crosscheck": sum(int(r["dead_wall_wait_tiles_total"]) for r in all_rows),
}, ensure_ascii=False), flush=True)
