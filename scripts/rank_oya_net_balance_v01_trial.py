#!/usr/bin/env python3
"""親番純収支 v0.1 試算：親番の総収入/総支出、局終了点差、親被り原典との照合。"""
from __future__ import annotations
import csv
import json
import sqlite3
import sys
from pathlib import Path

db=Path(sys.argv[1]).resolve()
conn=sqlite3.connect(db.as_uri()+"?mode=ro",uri=True,timeout=90)
conn.row_factory=sqlite3.Row
conn.execute("PRAGMA query_only=ON")
out=Path("results")
out.mkdir(parents=True,exist_ok=True)
sql=Path("sql/oya_net_balance_v01_trial.sql").read_text(encoding="utf-8")
kaburi_sql=Path("sql/oya_kaburi_rate_index_v01.sql").read_text(encoding="utf-8")
expected=conn.execute("PRAGMA quick_check").fetchone()[0]
assert expected=="ok", expected

def select_rows(text: str):
    return [dict(x) for x in conn.execute(text)]

def data_filter(text: str,year: int,stage: str):
    needle="SELECT NULL AS start_year,NULL AS stage"
    assert text.count(needle)==1, needle
    return text.replace(needle,f"SELECT {year} AS start_year,'{stage}' AS stage")

def write_csv(filename,rows):
    if not rows:return
    with (out/filename).open("w",encoding="utf-8-sig",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

def topleague(rows):
    vals={
      "players":len(rows),
      "parent_kyoku":sum(r["parent_kyoku_count"] for r in rows),
      "income":sum(r["total_income_points"] for r in rows),
      "expense":sum(r["total_expense_points"] for r in rows),
      "net":sum(r["parent_net_points"] for r in rows),
      "agari_income":sum(r["agari_income_points"] for r in rows),
      "tenpai_income":sum(r["tenpai_income_points"] for r in rows),
      "deal_in_expense":sum(r["deal_in_expense_points"] for r in rows),
      "kaburi_expense":sum(r["kaburi_expense_points"] for r in rows),
      "noten_expense":sum(r["noten_expense_points"] for r in rows),
      "reach_expense":sum(r["reach_expense_points"] for r in rows),
      "score_delta_net":sum(r["score_delta_net_points"] for r in rows),
      "audit_mismatches":sum(r["audit_mismatch_kyoku_count"] for r in rows),
      "plus_kyoku":sum(r["plus_kyoku_count"] for r in rows),
      "minus_kyoku":sum(r["minus_kyoku_count"] for r in rows),
      "zero_kyoku":sum(r["zero_kyoku_count"] for r in rows),
    }
    if not vals["parent_kyoku"]:raise RuntimeError("no parent rounds")
    vals["net_per_parent_kyoku"]=round(vals["net"]/vals["parent_kyoku"],2)
    assert vals["agari_income"]+vals["tenpai_income"]==vals["income"]
    assert (vals["deal_in_expense"]+vals["kaburi_expense"]+vals["noten_expense"]+
            vals["reach_expense"]==vals["expense"])
    assert vals["income"]-vals["expense"]==vals["net"]
    assert vals["plus_kyoku"]+vals["minus_kyoku"]+vals["zero_kyoku"]==vals["parent_kyoku"]
    return vals

def check_individual(rows):
    for r in rows:
        assert r["agari_income_points"]+r["tenpai_income_points"]==r["total_income_points"],r
        assert (r["deal_in_expense_points"]+r["kaburi_expense_points"]+
                r["noten_expense_points"]+r["reach_expense_points"]==r["total_expense_points"]),r
        assert r["total_income_points"]-r["total_expense_points"]==r["parent_net_points"],r
        assert r["plus_kyoku_count"]+r["minus_kyoku_count"]+r["zero_kyoku_count"]==r["parent_kyoku_count"],r
        if r["parent_kyoku_count"] <= 0:raise AssertionError(r)

# primary
rows=select_rows(sql)
if not rows: raise RuntimeError("No parent players")
check_individual(rows)
league=topleague(rows)

# Verify parent counts and baseline/parent monetary payouts against existing formally adopted #6.
kaburi=select_rows(kaburi_sql)
by_p={r["player_id"]:r for r in kaburi}
assert set(r["player_id"] for r in rows)==set(by_p), "player IDs disagree with #6"
for r in rows:
    old=by_p[r["player_id"]]
    assert r["parent_kyoku_count"]==old["oya_kyoku_count"],("parent count",r["player_name"],r["parent_kyoku_count"],old["oya_kyoku_count"])
    assert r["kaburi_expense_points"]==old["kaburi_total_loss_points"],("kaburi amount",r["player_name"],r["kaburi_expense_points"],old["kaburi_total_loss_points"])
assert league["parent_kyoku"]==25238, league
assert league["parent_kyoku"]==conn.execute("SELECT COUNT(*) FROM kyoku").fetchone()[0]

def filtered(year,stage):
    current=select_rows(data_filter(sql,year,stage))
    independent=select_rows(kaburi_sql.replace("SELECT NULL AS start_year, NULL AS stage",f"SELECT {year} AS start_year, '{stage}' AS stage"))
    by_old={r["player_id"]:r for r in independent}
    check_individual(current)
    for r in current:
        assert r["parent_kyoku_count"]==by_old[r["player_id"]]["oya_kyoku_count"]
        assert r["kaburi_expense_points"]==by_old[r["player_id"]]["kaburi_total_loss_points"]
    return {"year":year,"stage":stage,"summary":topleague(current),"top_by_net":current[:10]}

old=filtered(2025,"regular")
recent=filtered(2026,"regular")

# Track each round's mismatch separately for explaining any non-standard payout.
# Reuse the event ledger CTE without final player SELECT.
sentinel="SELECT p.id AS player_id,p.name AS player_name,b.*"
assert sql.count(sentinel)==1
with_sql=sql.split(sentinel)[0]
diag_sql=with_sql + (
    "SELECT k.kyoku_id,k.game_id,k.player_id,k.before_score,k.score,k.score_delta,\n"
    "       k.income_points,k.expense_points,k.reconstructed_net,k.audit_diff,\n"
    "       k.agari_income,k.tenpai_income,k.deal_in_expense,\n"
    "       k.kaburi_expense,k.noten_expense,k.reach_expense\n"
    "FROM verified k WHERE k.audit_diff<>0 "
    "ORDER BY ABS(k.audit_diff) DESC,k.kyoku_id LIMIT 100"
)
diag=select_rows(diag_sql)
write_csv("oya_net_balance_v01_mismatches.csv",diag)
write_csv("oya_net_balance_v01_all_players.csv",rows)
write_csv("oya_net_balance_v01_min100_rounds.csv",
          sorted([r for r in rows if r["parent_kyoku_count"]>=100],
                 key=lambda x:(-x["net_per_parent_kyoku"],x["player_name"])))
write_csv("oya_net_balance_v01_min300_rounds.csv",
          sorted([r for r in rows if r["parent_kyoku_count"]>=300],
                 key=lambda x:(-x["net_per_parent_kyoku"],x["player_name"])))
data={
    "validation":"PASSED" if league["audit_mismatches"]==0 else "MISMATCHES_PRESENT",
    "db_quick_check":expected,
    "all_period":league,
    "2025_regular":old,
    "2026_regular":recent,
    "top_by_total_net":rows[:20],
    "top_by_per_round_min300":sorted(
        [r for r in rows if r["parent_kyoku_count"]>=300],
        key=lambda x:(-x["net_per_parent_kyoku"],x["player_name"]))[:20],
    "bottom_by_total_net":sorted(rows,key=lambda r:r["parent_net_points"])[:15],
    "sample_of_mismatches":diag[:10],
    "notes":[
        "親番での収入／支出は局のイベントごとに総額計上する。",
        "親番のリーチ供託を支出に、戻った供託を和了収入に計上する。",
        "総収入と総支出は順位点・オカ・ウマを含まない局内点棒。",
        "局終了時の親の持ち点差分とイベント積算の差が0であることを検証。",
        "第6指標 親被り率・親被り指数の親局数・ツモ失点と選手別に照合。",
        "時間差・打牌意図による因果評価は含まない。"
    ]
}
(out/"oya_net_balance_v01_summary.json").write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print("SUMMARY",json.dumps({k:v for k,v in data.items() if k not in ("top_by_total_net","top_by_per_round_min300","bottom_by_total_net","sample_of_mismatches")},ensure_ascii=False),flush=True)
for k in ("top_by_total_net","top_by_per_round_min300","bottom_by_total_net","sample_of_mismatches"):
    vals=data[k]
    print(k.upper(),json.dumps(vals,ensure_ascii=False),flush=True)
if league["audit_mismatches"] or any(x["summary"]["audit_mismatches"] for x in (old,recent)):
    raise RuntimeError(f"親番のイベント積算と局終了時点数の差異が {league['audit_mismatches']} 局。追加調査が必要。")
print("ALL_PLAYERS",json.dumps(rows,ensure_ascii=False),flush=True)
print("VALIDATED full parent ledger, every event type, #6 parent kaburi, score changes",flush=True)
