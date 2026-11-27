"""Run the separate draw-only dora analysis against a pinned SQLite release."""
import csv, json, sqlite3, sys
from pathlib import Path

db_path = Path(sys.argv[1]).resolve()
sql_path = Path("sql/dora_tsumo_only_v01.sql")
out_dir = Path("results")
out_dir.mkdir(exist_ok=True)

conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
check = conn.execute("PRAGMA quick_check").fetchone()[0]
assert check == "ok", check
rows = [dict(r) for r in conn.execute(sql_path.read_text(encoding="utf-8"))]
all_rows = [r for r in rows if r["period"] == "ALL"]
season_rows = [r for r in rows if r["period"] != "ALL"]
assert len(all_rows) == 56, f"expected 56 players, got {len(all_rows)}"
assert sum(r["played_kyoku_count"] for r in all_rows) == 100952
assert all(r["dora_draw_count"] == r["red_dora_draw_count"] + r["normal_dora_draw_count"] for r in rows)
assert all(r["dora_draw_count"] <= r["draw_event_count"] for r in rows)
db_draws = conn.execute("SELECT COUNT(*) FROM draw_event").fetchone()[0]
assert sum(r["draw_event_count"] for r in all_rows) == db_draws

fields = list(rows[0])
def add_ranks(group):
    by_rate = sorted(group, key=lambda r: (-r["dora_per_100_draws"], -r["dora_draw_count"], r["player_name"]))
    by_kyoku = sorted(group, key=lambda r: (-r["dora_per_100_kyoku"], -r["dora_draw_count"], r["player_name"]))
    rate_rank = {r["player_id"]: i for i, r in enumerate(by_rate, 1)}
    kyoku_rank = {r["player_id"]: i for i, r in enumerate(by_kyoku, 1)}
    return [{**r, "rank_by_draw_rate": rate_rank[r["player_id"]],
             "rank_by_100_kyoku": kyoku_rank[r["player_id"]]} for r in group]

all_rows = add_ranks(all_rows)
season_by_year = {}
for row in season_rows:
    season_by_year.setdefault(row["period"], []).append(row)
season_rows = [r for year in sorted(season_by_year)
               for r in add_ranks(season_by_year[year])]

for filename, data in [
    ("dora_tsumo_all_players.csv", all_rows),
    ("dora_tsumo_by_season.csv", season_rows),
]:
    if data:
        with (out_dir / filename).open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(data[0]))
            writer.writeheader()
            writer.writerows(data)

summary = {
    "baseline_release": "20261120-2341-04338cbb",
    "database_quick_check": check,
    "all_player_count": len(all_rows),
    "all_player_kyoku_count": sum(r["played_kyoku_count"] for r in all_rows),
    "database_draw_event_count": db_draws,
    "sum_player_draw_event_count": sum(r["draw_event_count"] for r in all_rows),
    "dora_draw_count": sum(r["dora_draw_count"] for r in all_rows),
    "red_dora_draw_count": sum(r["red_dora_draw_count"] for r in all_rows),
    "normal_dora_draw_count": sum(r["normal_dora_draw_count"] for r in all_rows),
    "season_rows": len(season_rows),
    "kurosawa_all": next(r for r in all_rows if r["player_name"] == "黒沢咲"),
    "kurosawa_seasons": [r for r in season_rows if r["player_name"] == "黒沢咲"],
}
(out_dir / "dora_tsumo_validation.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(summary, ensure_ascii=False, indent=2))
