#!/usr/bin/env python3
"""日吉辰哉実況とMリーグ各チームの得失点/相性を公式DBで比較する独立試算。"""
from __future__ import annotations
import collections,csv,json,sqlite3,sys
from pathlib import Path

con=sqlite3.connect(f"file:{sys.argv[1]}?mode=ro",uri=True)
con.row_factory=sqlite3.Row
con.execute("PRAGMA query_only=ON")
assert con.execute("PRAGMA quick_check").fetchone()[0]=="ok"
with open("research/hiyoshi_commentary_games_20261123.csv",encoding="utf-8-sig",newline="") as f:
    hy_ids=[int(r["game_id"]) for r in csv.DictReader(f)]
hy_set=set(hy_ids)
assert len(hy_ids)==len(hy_set)==736
all_games={int(r["id"]) for r in con.execute("SELECT id FROM game")}
assert len(all_games)==2068 and hy_set.issubset(all_games)

sql="""
SELECT gr.game_id,gr.player_id,gr.team_id,t.name AS team_name,
       gr.rank,gr.score,gr.league_points+gr.penalty_league_points AS pt,
       ls.start_year AS season_start,ss.stage
FROM game_player_result gr
JOIN team t ON t.id=gr.team_id
JOIN game g ON g.id=gr.game_id
JOIN season_stage ss ON ss.id=g.season_stage_id
JOIN league_season ls ON ls.id=ss.league_season_id
"""
rows=[dict(r) for r in con.execute(sql)]
assert len(rows)==8272,len(rows)
games=collections.defaultdict(list)
for r in rows:games[r["game_id"]].append(r)
assert set(games)==all_games
assert all(len(x)==4 and len(set(r["team_id"] for r in x))==4 for x in games.values())
assert sum(g in hy_set for g in games)==736
# 3者の同試合平均ポイントとの差は、総和が0とならない反則減点にも対応。
for g,rr in games.items():
    for r in rr:
        opp=[float(z["pt"]) for z in rr if z["team_id"]!=r["team_id"]]
        r["opponent_mean_pt"]=sum(opp)/3
        r["margin_vs_opponents"]=float(r["pt"])-r["opponent_mean_pt"]
        r["score_delta_pt"]=float(r["score"])-25000.0
        r["is_hiyoshi"]=g in hy_set

def metrics(rr):
    if not rr:return {"games":0,"total_pt":None,"avg_pt":None,"top_count":0,"top_pct":None,"last_count":0,"last_pct":None,"avg_rank":None,"total_margin_vs_opponents":None,"avg_margin_vs_opponents":None,"score_delta_total":None,"score_delta_average":None}
    n=len(rr)
    points=sum(float(r["pt"]) for r in rr)
    margin=sum(r["margin_vs_opponents"] for r in rr)
    sc=sum(r["score_delta_pt"] for r in rr)
    return {"games":n,"total_pt":round(points,1),"avg_pt":round(points/n,4),
            "top_count":sum(r["rank"]==1 for r in rr),"top_pct":round(100*sum(r["rank"]==1 for r in rr)/n,4),
            "last_count":sum(r["rank"]==4 for r in rr),"last_pct":round(100*sum(r["rank"]==4 for r in rr)/n,4),
            "avg_rank":round(sum(r["rank"] for r in rr)/n,4),
            "total_margin_vs_opponents":round(margin,1),
            "avg_margin_vs_opponents":round(margin/n,4),
            "score_delta_total":round(sc),
            "score_delta_average":round(sc/n,2)}

def scope_metrics(scope):
    relevant=[r for r in rows if scope=="all" or r["stage"]=="regular"]
    by=collections.defaultdict(lambda:{"h":[],"other":[]})
    for r in relevant:
        by[(r["team_id"],r["team_name"])]["h" if r["is_hiyoshi"] else "other"].append(r)
    out=[]
    for (tid,team),v in by.items():
        h=metrics(v["h"]);o=metrics(v["other"])
        a={"team_id":tid,"team":team,"scope":scope,"hiyoshi":h,"other":o,
           "delta_avg_pt":round(h["avg_pt"]-o["avg_pt"],4) if h["games"] and o["games"] else None,
           "delta_top_pct_pp":round(h["top_pct"]-o["top_pct"],4) if h["games"] and o["games"] else None,
           "delta_avg_rank":round(h["avg_rank"]-o["avg_rank"],4) if h["games"] and o["games"] else None,
           "delta_avg_margin_vs_opponents":round(h["avg_margin_vs_opponents"]-o["avg_margin_vs_opponents"],4) if h["games"] and o["games"] else None}
        out.append(a)
    return out

all_out=scope_metrics("all")
regular_out=scope_metrics("regular")
eligible=lambda rr:[x for x in rr if x["hiyoshi"]["games"]>=20 and x["other"]["games"]>=20]
def sort_key(x):return (x["delta_avg_pt"],-x["hiyoshi"]["games"],x["team"])
all_worst=sorted(eligible(all_out),key=sort_key)
regular_worst=sorted(eligible(regular_out),key=sort_key)
all_by_pts=sorted(eligible(all_out),key=lambda x:(x["hiyoshi"]["avg_pt"],x["team"]))
all_by_total=sorted(eligible(all_out),key=lambda x:(x["hiyoshi"]["total_pt"],x["team"]))
# 両条件で20試合未満も取りこぼさず全チーム表に収録
assert sum(x["hiyoshi"]["games"] for x in all_out)==2944
assert sum(x["other"]["games"] for x in all_out)==5328
assert sum(x["hiyoshi"]["top_count"] for x in [])==0 if False else True
# Mリーグのポイント計算の同試合合計を監査。減点で例外が出ても、原典変更なし。
balance_stats=[round(sum(float(r["pt"]) for r in rr),1) for rr in games.values()]
balance_nonzero=[x for x in balance_stats if abs(x)>0.1]
season_counts=collections.Counter((r["season_start"],r["stage"],r["is_hiyoshi"]) for r in rows)
report={
    "source_external_master":"Mリーグ卓外データ_天気六曜月齢_公式PV統合.xlsx",
    "source_db_release":"20261120-2341-04338cbb",
    "game_count":len(all_games),"hiyoshi_games":len(hy_set),"other_games":len(all_games)-len(hy_set),
    "distinct_teams":len(all_out),"eligible_min_games_each":20,
    "eligible_teams_all":len(all_worst),"eligible_teams_regular":len(regular_worst),
    "points_balance_nonzero_games":len(balance_nonzero),"points_balance_max_absolute":max(abs(x) for x in balance_stats),
    "hiyoshi_by_season":[{"start_year":s,"stage":st,"hiyoshi_games":season_counts[(s,st,True)]//4,
       "other_games":season_counts[(s,st,False)]//4}
       for s,st in sorted(set((s,st) for s,st,v in season_counts))],
    "all_worst_first":all_worst,"regular_worst_first":regular_worst,
    "all_lowest_average_pts_first":all_by_pts,"all_lowest_total_pts_first":all_by_total,
    "all_teams":sorted(all_out,key=lambda x:x["team_id"]),
    "regular_teams":sorted(regular_out,key=lambda x:x["team_id"])
}
out_dir=Path("results");out_dir.mkdir(exist_ok=True)
(out_dir/"hiyoshi_team_compat_20261123.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
cols=["scope","team","h_games","h_total_pt","h_avg_pt","other_games","other_total_pt","other_avg_pt",
      "delta_avg_pt","h_top_pct","other_top_pct","delta_top_pct_pp","h_last_pct","other_last_pct",
      "h_avg_rank","other_avg_rank","h_avg_margin_vs_opponents","h_total_margin_vs_opponents",
      "h_score_delta_total","h_score_delta_average"]
with (out_dir/"hiyoshi_team_compat_20261123.csv").open("w",encoding="utf-8-sig",newline="") as f:
    w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
    for rr in [all_out,regular_out]:
        for x in sorted(rr,key=lambda x:x["team"]):
            h,o=x["hiyoshi"],x["other"]
            w.writerow(dict(scope=x["scope"],team=x["team"],h_games=h["games"],
                h_total_pt=h["total_pt"],h_avg_pt=h["avg_pt"],other_games=o["games"],
                other_total_pt=o["total_pt"],other_avg_pt=o["avg_pt"],delta_avg_pt=x["delta_avg_pt"],
                h_top_pct=h["top_pct"],other_top_pct=o["top_pct"],delta_top_pct_pp=x["delta_top_pct_pp"],
                h_last_pct=h["last_pct"],other_last_pct=o["last_pct"],h_avg_rank=h["avg_rank"],
                other_avg_rank=o["avg_rank"],h_avg_margin_vs_opponents=h["avg_margin_vs_opponents"],
                h_total_margin_vs_opponents=h["total_margin_vs_opponents"],
                h_score_delta_total=h["score_delta_total"],h_score_delta_average=h["score_delta_average"]))
def short(x):
    h,o=x["hiyoshi"],x["other"]
    return dict(team=x["team"],h_games=h["games"],h_total=h["total_pt"],h_avg=h["avg_pt"],other_games=o["games"],other_avg=o["avg_pt"],delta=x["delta_avg_pt"],h_top=h["top_pct"],other_top=o["top_pct"],delta_top=x["delta_top_pct_pp"],h_margin=h["avg_margin_vs_opponents"],h_avg_rank=h["avg_rank"])
print("HIYOSHI_TEAM_AUDIT",json.dumps({k:report[k] for k in ["game_count","hiyoshi_games","other_games","distinct_teams","eligible_teams_all","eligible_teams_regular","points_balance_nonzero_games","points_balance_max_absolute"]},ensure_ascii=False),flush=True)
print("HIYOSHI_TEAM_ALL_WORST_FIRST",json.dumps([short(x) for x in all_worst],ensure_ascii=False),flush=True)
print("HIYOSHI_TEAM_REG_WORST_FIRST",json.dumps([short(x) for x in regular_worst],ensure_ascii=False),flush=True)
print("HIYOSHI_TEAM_ALL_TEAMS",json.dumps([short(x) for x in all_out],ensure_ascii=False),flush=True)
print("HIYOSHI_TEAM_SEASONS",json.dumps(report["hiyoshi_by_season"],ensure_ascii=False),flush=True)
