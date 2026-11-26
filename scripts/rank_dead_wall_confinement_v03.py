from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(sys.argv[1])
SQL_PATH = Path("sql/dead_wall_confinement_v03.sql")
OUT_DIR = Path("results")
OUT_DIR.mkdir(parents=True, exist_ok=True)

sql = SQL_PATH.read_text(encoding="utf-8")
param_template = "params AS (SELECT NULL AS start_year, NULL AS stage)"
if param_template not in sql:
    raise RuntimeError("SQL parameter template not found")

con = sqlite3.connect(f"file:{DB_PATH.resolve()}?mode=ro", uri=True)
con.row_factory = sqlite3.Row
check = con.execute("PRAGMA quick_check").fetchone()[0]
print("quick_check:", check, flush=True)
if check != "ok":
    raise RuntimeError(f"SQLite integrity check failed: {check}")

years = [row[0] for row in con.execute(
    "SELECT DISTINCT ls.start_year FROM league_season ls ORDER BY ls.start_year"
)]
periods = [(None, "all")] + [(year, str(year)) for year in years]
detail_rows: list[dict[str, object]] = []
summary_rows: list[dict[str, object]] = []

for year, label in periods:
    year_sql = "NULL" if year is None else str(int(year))
    query = sql.replace(
        param_template,
        f"params AS (SELECT {year_sql} AS start_year, NULL AS stage)",
        1,
    )
    rows = [dict(row) for row in con.execute(query)]
    for row in rows:
        row["season"] = label
        detail_rows.append(row)

    overall = [row for row in rows if row["tenpai_status"] == "all"]
    summary_rows.append({
        "season": label,
        "player_count": len(overall),
        "final_tenpai_count": sum(int(row["final_tenpai_count"] or 0) for row in overall),
        "dead_wall_confinement_count": sum(int(row["dead_wall_confinement_count"] or 0) for row in overall),
        "dead_wall_confinement_rate_pct": (
            round(100 * sum(int(row["dead_wall_confinement_count"] or 0) for row in overall)
                  / sum(int(row["final_tenpai_count"] or 0) for row in overall), 4)
            if sum(int(row["final_tenpai_count"] or 0) for row in overall) else None
        ),
        "dead_wall_wait_tiles": sum(int(row["dead_wall_wait_tiles"] or 0) for row in overall),
        "dead_wall_wait_indicators": sum(int(row["dead_wall_wait_indicators"] or 0) for row in overall),
        "dead_wall_wait_tiles_excluding_indicators": sum(
            int(row["dead_wall_wait_tiles_excluding_indicators"] or 0) for row in overall
        ),
    })
    print(f"{label}: {summary_rows[-1]}", flush=True)

if detail_rows:
    with (OUT_DIR / "dead_wall_confinement_v03_by_player.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(detail_rows[0]))
        writer.writeheader()
        writer.writerows(detail_rows)
with (OUT_DIR / "dead_wall_confinement_v03_summary.csv").open("w", newline="", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=list(summary_rows[0]))
    writer.writeheader()
    writer.writerows(summary_rows)
print("Wrote results/dead_wall_confinement_v03_by_player.csv", flush=True)
print("Wrote results/dead_wall_confinement_v03_summary.csv", flush=True)
