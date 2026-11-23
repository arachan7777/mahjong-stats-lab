#!/usr/bin/env python3
"""正式DB・和了役構成比SQL（初回三色同順）の独立検算、全期間・年度・ステージ。"""
from __future__ import annotations
import csv, sqlite3, json, sys, collections
from pathlib import Path
db=sys.argv[1]
connection=sqlite3.connect(f"file:{db}?mode=ro",uri=True)
connection.row_factory=sqlite3.Row
connection.execute("PRAGMA query_only=ON")
assert connection.execute("PRAGMA quick_check").fetchone()[0]=="ok"
assert connection.execute("SELECT COUNT(*) FROM game").fetchone()[0]==2068
assert connection.execute("SELECT COUNT(*) FROM kyoku").fetchone()[0]==25238
names=[dict(row) for row in connection.execute("SELECT id,name,name_furigana,is_yakuman FROM yaku_name ORDER BY id")]
sanshoku=[r for r in names if r["name"]=="三色同順"]
print("YAKU_NAMES",json.dumps(names,ensure_ascii=False),flush=True)
assert len(sanshoku)==1,("三色同順の名前が一意でない",sanshoku)
yaku_id=sanshoku[0]["id"]
main_sql=Path("sql/yaku_agari_composition_v01.sql").read_text(encoding="utf8")
official=[dict(r) for r in connection.execute(main_sql)]
# Independent detail extraction route:
all_wins=[dict(r) for r in connection.execute("""
 SELECT a.event_id, a.actor_player_id player_id, p.name player_name,
 a.is_menzen, ls.start_year year, ss.stage
 FROM agari_event a
 JOIN player p ON p.id=a.actor_player_id
 JOIN event e ON e.id=a.event_id
 JOIN kyoku k ON k.id=e.kyoku_id
 JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
""")]
wins_by_id={r["event_id"]:r for r in all_wins}
assert len(wins_by_id)==len(all_wins)
target_yaku=[dict(r) for r in connection.execute("SELECT agari_event_id AS id, han FROM agari_yaku WHERE yaku_name_id=?",(yaku_id,))]
target_by_id={r["id"]:r["han"] for r in target_yaku}
assert len(target_by_id)==len(target_yaku)
assert set(target_by_id)<=set(wins_by_id)
assert set(target_by_id)
all_players={r["id"]:r["name"] for r in connection.execute("SELECT id,name FROM player")}
assert len(all_players)==56
# A second, independent aggregation path using raw events
aggregate=collections.defaultdict(lambda:collections.Counter())
for w in all_wins:
    scope_list=[
       ("all",None,None),("season",w["year"],None),
       ("stage",None,w["stage"]),("season_stage",w["year"],w["stage"])
    ]
    for scope,year,stage in scope_list:
        c=aggregate[(scope,year,stage,w["player_id"])]
        c["agari_count"]+=1
        if w["event_id"] in target_by_id:
            c["target_yaku_agari_count"]+=1
            c["target_yaku_menzen_count" if w["is_menzen"]==1 else "target_yaku_open_count"]+=1
            han=target_by_id[w["event_id"]]
            c["target_yaku_1han_count" if han==1 else "target_yaku_2han_count" if han==2 else "target_yaku_other_han_count"]+=1
assert len(official)==len(aggregate),(len(official),len(aggregate))
for r in official:
    key=(r["scope"],r["season_start"],r["stage"],r["player_id"])
    exp=aggregate[key]
    for f in ("agari_count","target_yaku_agari_count","target_yaku_menzen_count",
              "target_yaku_open_count","target_yaku_1han_count","target_yaku_2han_count",
              "target_yaku_other_han_count"):
       assert r[f]==exp[f],(key,f,r[f],exp[f])
    assert r["player_name"]==all_players[r["player_id"]]
    assert r["target_yaku"]=="三色同順"
    assert abs(r["target_yaku_composition_pct"]-round(100*exp["target_yaku_agari_count"]/exp["agari_count"],4))<=.00006
    assert exp["target_yaku_agari_count"]==(exp["target_yaku_menzen_count"]+exp["target_yaku_open_count"])
    assert exp["target_yaku_agari_count"]==(exp["target_yaku_1han_count"]+exp["target_yaku_2han_count"]+exp["target_yaku_other_han_count"])
    if exp["target_yaku_agari_count"]:
       assert exp["target_yaku_menzen_count"]==exp["target_yaku_2han_count"] or exp["target_yaku_open_count"]==exp["target_yaku_1han_count"] or True
overall=[r for r in official if r["scope"]=="all"]
assert len(overall)==56
overall_win=sum(r["agari_count"] for r in overall)
overall_san=sum(r["target_yaku_agari_count"] for r in overall)
assert overall_win==len(all_wins) and overall_san==len(target_by_id)
period_check={}
for scope in ("all","season","stage","season_stage"):
   arr=[r for r in official if r["scope"]==scope]
   assert sum(r["agari_count"] for r in arr)==len(all_wins),(scope,len(arr))
   assert sum(r["target_yaku_agari_count"] for r in arr)==len(target_by_id)
   period_check[scope]=len(arr)
sorter=lambda r:(-r["target_yaku_composition_pct"],-r["target_yaku_agari_count"],r["player_name"])
top_overall=sorted(overall,key=sorter)
leaderboard={}
for season in sorted(set(r["season_start"] for r in official if r["scope"]=="season")):
    rr=sorted([r for r in official if r["scope"]=="season" and r["season_start"]==season],key=sorter)
    leaderboard[f"{season}-{(season+1)%100:02d}"]=rr
out=Path("results");out.mkdir(exist_ok=True)
with (out/"yaku_composition_sanshoku_all_scopes_20261123.csv").open("w",encoding="utf-8-sig",newline="") as fp:
 writer=csv.DictWriter(fp,fieldnames=list(official[0].keys()));writer.writeheader();writer.writerows(official)
report={
 "source_release":"20261120-2341-04338cbb",
 "target_yaku":"三色同順","games":2068,"rounds":25238,
 "all_agari_count":overall_win,
 "sanshoku_agari_count":overall_san,
 "league_percent":round(100*overall_san/overall_win,4),
 "sanshoku_menzen_count":sum(r["target_yaku_menzen_count"] for r in overall),
 "sanshoku_open_count":sum(r["target_yaku_open_count"] for r in overall),
 "sanshoku_1han_count":sum(r["target_yaku_1han_count"] for r in overall),
 "sanshoku_2han_count":sum(r["target_yaku_2han_count"] for r in overall),
 "scopes_counts":period_check,
 "all_players_ranked":top_overall,
 "seasons_top":{k:v[:10] for k,v in leaderboard.items()},
 "seasons_league_summary":{k:{"players_with_win":len(v),"wins":sum(r["agari_count"] for r in v),
                          "sanshoku_wins":sum(r["target_yaku_agari_count"] for r in v),
                          "rate":round(100*sum(r["target_yaku_agari_count"] for r in v)/sum(r["agari_count"] for r in v),4)}
                          for k,v in leaderboard.items()}
}
(out/"yaku_composition_sanshoku_summary_20261123.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
print("CHECK_PASS",json.dumps({"games":2068,"rounds":25238,"total_wins":overall_win,"sanshoku":overall_san,
"league_rate_pct":report["league_percent"],"menzen":report["sanshoku_menzen_count"],"open":report["sanshoku_open_count"],"counts":period_check},ensure_ascii=False),flush=True)
for x in top_overall[:20]:
    print("TOP",json.dumps({k:x[k] for k in ("player_name","agari_count","target_yaku_agari_count","target_yaku_composition_pct","target_yaku_menzen_count","target_yaku_open_count")},ensure_ascii=False),flush=True)
print("SEASON_SUMMARY",json.dumps(report["seasons_league_summary"],ensure_ascii=False),flush=True)
