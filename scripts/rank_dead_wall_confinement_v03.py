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

# Derive a per-exhaustive-draw distribution from the same v0.3 per_tenpai CTE.
# This keeps the canonical rate query intact and buckets final wait tiles physically
# remaining in the dead wall as exact counts, including zero.
cte_end = sql.index("status_rows AS (")
final_select = sql.index("SELECT p.id AS player_id", cte_end)
distribution_suffix = """status_rows AS (
  SELECT player_id,tenpai_status,
         COUNT(*) AS final_tenpai_count,
         SUM(CASE WHEN dead_wall_wait_tiles>0 THEN 1 ELSE 0 END)
           AS dead_wall_confinement_count,
         SUM(dead_wall_wait_tiles) AS dead_wall_wait_tiles,
         SUM(dead_wall_wait_indicators) AS dead_wall_wait_indicators
  FROM per_tenpai
  GROUP BY player_id,tenpai_status
),
all_rows AS (
  SELECT player_id,'all' AS tenpai_status,
         COUNT(*) AS final_tenpai_count,
         SUM(CASE WHEN dead_wall_wait_tiles>0 THEN 1 ELSE 0 END)
           AS dead_wall_confinement_count,
         SUM(dead_wall_wait_tiles) AS dead_wall_wait_tiles,
         SUM(dead_wall_wait_indicators) AS dead_wall_wait_indicators
  FROM per_tenpai
  GROUP BY player_id
),
results AS (
  SELECT * FROM all_rows
  UNION ALL
  SELECT * FROM status_rows
)
SELECT p.id AS player_id,p.name AS player_name,r.tenpai_status,
       r.final_tenpai_count,r.dead_wall_confinement_count,
       ROUND(100.0*r.dead_wall_confinement_count/
             NULLIF(r.final_tenpai_count,0),4) AS dead_wall_confinement_rate_pct,
       r.dead_wall_wait_tiles,
       ROUND(1.0*r.dead_wall_wait_tiles/
             NULLIF(r.final_tenpai_count,0),4) AS dead_wall_tiles_per_tenpai,
       ROUND(1.0*r.dead_wall_wait_tiles/
             NULLIF(r.dead_wall_confinement_count,0),4)
         AS dead_wall_tiles_per_confined_tenpai,
       r.dead_wall_wait_indicators,
       r.dead_wall_wait_tiles-r.dead_wall_wait_indicators
         AS dead_wall_wait_tiles_excluding_indicators
FROM results r
JOIN player p ON p.id=r.player_id
ORDER BY p.name,
         CASE r.tenpai_status WHEN 'all' THEN 0 WHEN 'reach' THEN 1 ELSE 2 END;
"""
distribution_sql = sql[:cte_end] + """status_tenpai AS (
  SELECT kyoku_id,player_id,tenpai_status,dead_wall_wait_tiles
  FROM per_tenpai
  UNION ALL
  SELECT kyoku_id,player_id,'all' AS tenpai_status,dead_wall_wait_tiles
  FROM per_tenpai
),
distribution AS (
  SELECT tenpai_status,
         CAST(dead_wall_wait_tiles AS TEXT)
           AS dead_wall_wait_tile_count,
         COUNT(*) AS final_tenpai_count,
         SUM(dead_wall_wait_tiles) AS dead_wall_wait_tiles
  FROM status_tenpai
  GROUP BY tenpai_status,dead_wall_wait_tile_count
)
SELECT tenpai_status,dead_wall_wait_tile_count,
       final_tenpai_count,dead_wall_wait_tiles
FROM distribution
ORDER BY CASE tenpai_status WHEN 'all' THEN 0 WHEN 'reach' THEN 1
                             WHEN 'menzen_dama' THEN 2 ELSE 3 END,
         CAST(dead_wall_wait_tile_count AS INTEGER);
"""
if final_select <= cte_end:
    raise RuntimeError("Could not locate canonical query's final SELECT")
distribution_sql = distribution_sql.replace(
    "status_rows AS (", distribution_suffix, 1
)

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
distribution_rows: list[dict[str, object]] = []

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
    total_tenpai = sum(int(row["final_tenpai_count"] or 0) for row in overall)
    total_confined = sum(int(row["dead_wall_confinement_count"] or 0) for row in overall)
    summary_rows.append({
        "season": label,
        "player_count": len(overall),
        "final_tenpai_count": total_tenpai,
        "dead_wall_confinement_count": total_confined,
        "dead_wall_confinement_rate_pct": (
            round(100 * total_confined / total_tenpai, 4) if total_tenpai else None
        ),
        "dead_wall_wait_tiles": sum(int(row["dead_wall_wait_tiles"] or 0) for row in overall),
        "dead_wall_wait_indicators": sum(int(row["dead_wall_wait_indicators"] or 0) for row in overall),
        "dead_wall_wait_tiles_excluding_indicators": sum(
            int(row["dead_wall_wait_tiles_excluding_indicators"] or 0) for row in overall
        ),
    })

    dist_query = distribution_sql.replace(
        param_template,
        f"params AS (SELECT {year_sql} AS start_year, NULL AS stage)",
        1,
    )
    dist_rows = [dict(row) for row in con.execute(dist_query)]
    bucket_denominators = {
        row["tenpai_status"]: sum(
            int(item["final_tenpai_count"])
            for item in dist_rows if item["tenpai_status"] == row["tenpai_status"]
        )
        for row in dist_rows
    }
    for row in dist_rows:
        denominator = bucket_denominators[row["tenpai_status"]]
        row["season"] = label
        row["share_of_tenpai_pct"] = (
            round(100 * int(row["final_tenpai_count"]) / denominator, 4)
            if denominator else None
        )
        distribution_rows.append(row)

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
if distribution_rows:
    with (OUT_DIR / "dead_wall_confinement_v03_tile_distribution.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(distribution_rows[0]))
        writer.writeheader()
        writer.writerows(distribution_rows)
print("Wrote results/dead_wall_confinement_v03_by_player.csv", flush=True)
print("Wrote results/dead_wall_confinement_v03_summary.csv", flush=True)
print("Wrote results/dead_wall_confinement_v03_tile_distribution.csv", flush=True)
