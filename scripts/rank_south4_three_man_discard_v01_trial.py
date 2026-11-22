#!/usr/bin/env python3
"""三万点以上捨てる一打 v0.1。南4局で放銃によりトップ陥落し、復帰なしのケースを追跡。"""
from __future__ import annotations
from collections import Counter, defaultdict
from pathlib import Path
import csv, json, sqlite3, sys

db=Path(sys.argv[1]).resolve()
conn=sqlite3.connect(db.as_uri()+"?mode=ro",uri=True,timeout=90)
conn.row_factory=sqlite3.Row
conn.execute("PRAGMA query_only=ON")
out=Path("results")
out.mkdir(exist_ok=True)
assert conn.execute("PRAGMA quick_check").fetchone()[0]=="ok"

sql=Path("sql/south4_three_man_discard_v01_trial.sql").read_text(encoding="utf-8")
all_cases=[dict(r) for r in conn.execute(sql)]
guard_sql=Path("sql/oorasu_guardian_v01.sql").read_text(encoding="utf-8")
guard=[dict(r) for r in conn.execute(guard_sql)]
guard_by_player={r["player_id"]:r for r in guard}
assert len(guard)==56
assert sum(r["lead_opportunities"] for r in guard)==2073
assert sum(r["lost_lead_count"] for r in guard)==417
assert len(all_cases)>0

# 南4局を経験した選手が各局の直前時点で1着だった場合、試合単位で1機会を数える。
leader_opportunity_sql="""
WITH ordered AS (
 SELECT k.id AS kyoku_id,k.game_id,k.round,
        LAG(k.id) OVER (PARTITION BY k.game_id ORDER BY k.id) AS prev_kyoku_id
 FROM kyoku k
), leading AS (
 SELECT DISTINCT k.game_id,kr.player_id
 FROM ordered k
 JOIN kyoku_player_result kr ON kr.kyoku_id=k.prev_kyoku_id
 WHERE k.round='2z4' AND kr.rank=1
)
SELECT game_id,player_id FROM leading
"""
leader_opp={(r["game_id"],r["player_id"]) for r in conn.execute(leader_opportunity_sql)}
assert len(leader_opp)>=2073
assert len(set((r["game_id"],r["kyoku_id"],r["loser_player_id"]) for r in all_cases))==len(all_cases)
for r in all_cases:
    assert r["ron_winner_count"]>=1
    assert 0<=r["winner_is_parent_count"]<=r["ron_winner_count"]
    assert r["total_ron_payment"]>0
    assert r["final_rank"] in (1,2,3,4)
    assert r["after_kyoku_rank"] in (1,2,3,4)
    assert r["before_kyoku_rank"] in (1,2,3,4)
    assert r["later_first_rank_kyoku_count"]<=r["later_south4_kyoku_count"]
    assert r["first_south4_start_rank"] in (1,2,3,4)
    assert r["tied_lead_before_ron"] in (0,1)
    assert r["strict_lead_before_ron"] in (0,1)
    assert not (r["strict_lead_before_ron"] and r["tied_lead_before_ron"])
    r["has_recovered"] = r["later_first_rank_kyoku_count"]>0 or r["final_rank"]==1
    # その局でロン放銃があり、直前時点で厳密にトップ、その局終了時2着以下。
    r["lost_first_from_deal_in"] = (
        r["strict_lead_before_ron"]==1 and r["after_kyoku_rank"]!=1
    )
    r["qualified"] = r["lost_first_from_deal_in"] and not r["has_recovered"]
    # 比較用：前局終了時点でもトップだったか。これまでの「オーラス守護神率」と直接接続。
    r["was_leading_at_start_of_south4"] = r["first_south4_start_rank"]==1
    r["was_leading_before_kyoku"] = r["before_kyoku_rank"]==1
    r["ron_to_parent"] = r["winner_is_parent_count"]>0
    r["unambiguous_ron_leader"] = r["strict_lead_before_ron"]==1
    r["tied_before_ron_candidate"] = (
        r["tied_lead_before_ron"]==1 and
        r["after_kyoku_rank"]!=1 and not r["has_recovered"]
    )

qualified=[r for r in all_cases if r["qualified"]]
lead_at_start=[r for r in qualified if r["was_leading_at_start_of_south4"]]
new_come=[r for r in qualified if not r["was_leading_at_start_of_south4"]]
ambiguous=[r for r in all_cases if r["tied_before_ron_candidate"]]
dropped_but_recovered=[
    r for r in all_cases if r["lost_first_from_deal_in"] and r["has_recovered"]
]
# 事件数と、選手×試合ごとの被害件数の両方を保存する。
distinct_matches={(r["game_id"],r["loser_player_id"]) for r in qualified}
distinct_initial={(r["game_id"],r["loser_player_id"]) for r in lead_at_start}
assert len(distinct_initial)<=sum(r["lost_lead_count"] for r in guard)
assert len(lead_at_start)+len(new_come)==len(qualified)
assert all((r["game_id"],r["loser_player_id"]) in leader_opp or not r["was_leading_before_kyoku"]
           for r in qualified)

# 第21指標の初期トップ機会のうち、最終トップでないものに必ず包含されるか独立検証。
finals={(r["game_id"],r["player_id"]):r["rank"] for r in conn.execute("SELECT game_id,player_id,rank FROM game_player_result")}
assert all(finals[k]!=1 for k in distinct_initial)
cohort_leads = set()
for r in conn.execute("""
WITH first4 AS (
  SELECT game_id,MIN(id) AS first_id FROM kyoku WHERE round='2z4' GROUP BY game_id
)
SELECT first4.game_id,pr.player_id
FROM first4 JOIN kyoku prev
ON prev.id=(SELECT MAX(z.id) FROM kyoku z WHERE z.game_id=first4.game_id AND z.id<first4.first_id)
JOIN kyoku_player_result pr ON pr.kyoku_id=prev.id AND pr.rank=1
"""):
    cohort_leads.add((r["game_id"],r["player_id"]))
assert len(cohort_leads)==2073
assert distinct_initial.issubset(cohort_leads)

def summarize(items):
    return {
      "ron_events":len(items),
      "affected_player_games":len({(r["game_id"],r["loser_player_id"]) for r in items}),
      "started_south4_first":sum(r["was_leading_at_start_of_south4"] for r in items),
      "became_first_during_south4":sum(not r["was_leading_at_start_of_south4"] for r in items),
      "ron_to_parent_events":sum(r["ron_to_parent"] for r in items),
      "ron_to_nonparent_events":sum(not r["ron_to_parent"] for r in items),
      "parent_ron_with_continuation":sum(r["ron_to_parent"] and r["later_south4_kyoku_count"]>0 for r in items),
      "parent_ron_without_continuation":sum(r["ron_to_parent"] and r["later_south4_kyoku_count"]==0 for r in items),
      "nonparent_ron_with_continuation":sum((not r["ron_to_parent"]) and r["later_south4_kyoku_count"]>0 for r in items),
      "final_second":sum(r["final_rank"]==2 for r in items),
      "final_third":sum(r["final_rank"]==3 for r in items),
      "final_fourth":sum(r["final_rank"]==4 for r in items),
      "multi_ron_events":sum(r["ron_winner_count"]>1 for r in items),
      "total_deal_in_payment":sum(r["total_ron_payment"] for r in items),
    }

by_player={}
player_names={}
for r in all_cases:player_names[r["loser_player_id"]]=r["loser_name"]
for r in guard:player_names[r["player_id"]]=r["player_name"]
for pid in sorted(player_names):
    events=[x for x in qualified if x["loser_player_id"]==pid]
    first_events=[x for x in events if x["was_leading_at_start_of_south4"]]
    g=guard_by_player.get(pid)
    n=g["lead_opportunities"] if g else 0
    if not events and not n:continue
    by_player[pid]={
      "player_id":pid,"player_name":player_names[pid],
      "south4_initial_first_opportunities":n,
      "south4_initial_first_final_lost":g["lost_lead_count"] if g else 0,
      "three_man_discard_events":len(events),
      "three_man_discard_player_games":len({x["game_id"] for x in events}),
      "initial_first_three_man_discard_events":len(first_events),
      "initial_first_three_man_discard_pct":round(100*len(first_events)/n,4) if n else None,
      "gained_lead_then_three_man_discard_events":len(events)-len(first_events),
      "ron_to_parent":sum(x["ron_to_parent"] for x in events),
      "ron_to_nonparent":sum(not x["ron_to_parent"] for x in events),
      "final_second":sum(x["final_rank"]==2 for x in events),
      "final_third":sum(x["final_rank"]==3 for x in events),
      "final_fourth":sum(x["final_rank"]==4 for x in events),
      "total_ron_payment":sum(x["total_ron_payment"] for x in events)
    }
players=list(by_player.values())
players.sort(key=lambda x:(-x["three_man_discard_player_games"],
                           -x["initial_first_three_man_discard_events"],
                           x["player_name"]))

assert sum(x["three_man_discard_events"] for x in players)==len(qualified)
assert sum(x["initial_first_three_man_discard_events"] for x in players)==len(lead_at_start)
assert sum(x["south4_initial_first_opportunities"] for x in players)==2073

def write_csv(name,items):
    if not items:return
    with (out/name).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(items[0]))
        w.writeheader();w.writerows(items)
write_csv("three_man_discard_v01_all_ron_south4.csv",all_cases)
write_csv("three_man_discard_v01_qualified_events.csv",qualified)
write_csv("three_man_discard_v01_all_players.csv",players)
write_csv("three_man_discard_v01_top_before_ron_but_recovered.csv",dropped_but_recovered)
write_csv("three_man_discard_v01_ambiguous_tied_top.csv",ambiguous)

summary={
  "status":"SUCCESS",
  "db_quick_check":"ok",
  "all_db_games":conn.execute("SELECT COUNT(*) FROM game").fetchone()[0],
  "first_south4_initial_top_player_games":len(cohort_leads),
  "guardian_initial_top_failed_to_hold":sum(r["lost_lead_count"] for r in guard),
  "distinct_game_player_top_before_south4_kyoku":len(leader_opp),
  "all_south4_ron_loser_rounds":len(all_cases),
  "strict_before_ron_lost_top_and_never_returned":summarize(qualified),
  "initial_top_subset":summarize(lead_at_start),
  "gained_top_during_south4_subset":summarize(new_come),
  "lost_top_then_recovered":summarize(dropped_but_recovered),
  "tied_lead_ambiguous_candidates":summarize(ambiguous),
  "years":{str(y):summarize([r for r in qualified if r["season_start_year"]==y])
           for y in sorted({r["season_start_year"] for r in all_cases})},
  "stages":{s:summarize([r for r in qualified if r["stage"]==s])
            for s in ("regular","semifinal","final")},
  "explanation":"南4の当該局ロン直前に、成立リーチの供託支出後の持ち点が他3名を明確に上回っていた放銃者を抽出。放銃後の局順位が2着以下、最終2着以下、かつ後続局で一度も1着に復帰していなければ成立。1局のダブロンも1打と数える。",
  "note":"名前の三万点は順位点差からの命名。放銃点数が30000点以上かどうかの条件ではない。開始時1着組と途中トップ獲得組の内訳は別掲。タイのトップは要判定として候補を分離。",
  "rank_top20":players[:20],
  "events":qualified,
  "players":players
}
(out/"three_man_discard_v01_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print("SUMMARY",json.dumps({k:v for k,v in summary.items() if k not in ("rank_top20","events","players")},ensure_ascii=False),flush=True)
print("ALL_PLAYERS",json.dumps(players,ensure_ascii=False),flush=True)
print("EVENTS",json.dumps(qualified,ensure_ascii=False),flush=True)
print("AMBIGUOUS",json.dumps(ambiguous[:30],ensure_ascii=False),flush=True)
print("VERIFIED whole table, south4 rank changes and no-regain, guardian compatibility",flush=True)
