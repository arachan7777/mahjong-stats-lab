#!/usr/bin/env python3
"""西川幸太郎指数 Ver.2。正式保管指標の全件検証と2026-09-22固定照合。"""
from __future__ import annotations
import csv
import json
import sqlite3
import sys
from pathlib import Path

db = Path(sys.argv[1]).resolve()
con = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=60)
con.row_factory = sqlite3.Row
con.execute("PRAGMA query_only=ON")
out = Path("results")
out.mkdir(exist_ok=True)
sql = Path("sql/nishikawa_kotaro_v02.sql").read_text(encoding="utf-8")


def rows(query: str):
    return [dict(row) for row in con.execute(query)]


def dump(name: str, data):
    (out / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def csv_dump(name: str, data):
    if not data:
        raise RuntimeError(name + " の集計結果なし")
    with (out / name).open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(data[0]))
        writer.writeheader()
        writer.writerows(data)


qc = con.execute("PRAGMA quick_check").fetchone()[0]
if qc != "ok":
    raise RuntimeError("SQLite quick_check: " + str(qc))

full = rows(sql)
historical_sql = sql.replace("NULL AS end_date", "'2026-09-22' AS end_date", 1)
if historical_sql == sql:
    raise RuntimeError("historical filter injection failed")
historical = rows(historical_sql)

def audit(items):
    n = items[0]["total_yakuman_ron_dealin_count"]
    assert all(x["total_yakuman_ron_dealin_count"] == n for x in items)
    assert n == sum(x["yakuman_dealin_count"] for x in items)
    assert all(x["west_dealin_count"] <= x["total_dealin_count"] for x in items)
    assert all(x["south4_dealin_count"] <= x["total_dealin_count"] for x in items)
    assert all(x["yakuman_dealin_count"] <= x["total_dealin_count"] for x in items)
    for x in items:
        if x["total_dealin_count"] and n:
            expected = round(100 * (
                x["west_dealin_count"] / x["total_dealin_count"]
                + x["south4_dealin_count"] / x["total_dealin_count"]
                + x["yakuman_dealin_count"] / n), 4)
            assert abs(x["nishikawa_kotaro_index"] - expected) < 0.00015, x
        else:
            assert x["nishikawa_kotaro_index"] is None
    return {
        "players":len(items),
        "total_dealin":sum(x["total_dealin_count"] for x in items),
        "total_yakuman_ron_dealin":n
    }

full_summary = audit(full)
historical_summary = audit(historical)
uchikawa = [r for r in historical if r["player_name"] == "内川幸太郎"]
if len(uchikawa) != 1:
    raise RuntimeError("内川幸太郎の履歴データが一意でない")
u = uchikawa[0]
expected = {
    "total_dealin_count": 308,
    "west_dealin_count": 4,
    "south4_dealin_count": 42,
    "yakuman_dealin_count": 2,
    "total_yakuman_ron_dealin_count": 12,
}
for k, v in expected.items():
    assert u[k] == v, (k, u[k], v)
assert round(u["nishikawa_kotaro_index"], 2) == 31.60, u
assert historical[0]["player_name"] == "内川幸太郎", historical[0]

csv_dump("nishikawa_kotaro_v02_all.csv", full)
csv_dump("nishikawa_kotaro_v02_historical.csv", historical)
dump("nishikawa_kotaro_v02_top25.json", full[:25])
dump("nishikawa_kotaro_v02_historical_top25.json", historical[:25])
summary = {
    "status": "SUCCESS",
    "sql": "sql/nishikawa_kotaro_v02.sql",
    "mode": "正式保管／使用保留（独立19指標には含めない）",
    "quick_check": qc,
    "all_periods": full_summary,
    "historical_through_2026_09_22": historical_summary,
    "historical_uchikawa": u,
    "reference": expected,
}
dump("nishikawa_kotaro_v02_verification.json", summary)
print("VERIFIED", json.dumps(summary, ensure_ascii=False), flush=True)
print("TOP25", json.dumps(full[:25], ensure_ascii=False), flush=True)
