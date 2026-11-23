#!/usr/bin/env python3
"""日吉辰哉実況と選手成績の相性分析（公式卓外台帳・正本DB、読み取り専用）。"""
import csv,sqlite3,sys,json,statistics,collections
from pathlib import Path
from datetime import datetime
db=sys.argv[1]
src=Path("research/hiyoshi_commentary_games_20261123.csv")
game_ids=[int(row["game_id"]) for row in csv.DictReader(src.open(encoding="utf-8-sig"))]
hiyoshi=set(game_ids)
assert len(game_ids)==len(hiyoshi)==736,(len(game_ids),len(hiyoshi))
con=sqlite3.connect("file:"+db+"?mode=ro",uri=True)
con.row_factory=sqlite3.Row
con.execute("PRAGMA query_only=ON")
assert con.execute("PRAGMA quick_check").fetchone()[0]=="ok"
all_games={r["id"] for r in con.execute("SELECT id FROM game")}
assert len(all_games)==2068,len(all_games)
assert hiyoshi<=all_games,("missing game ids",sorted(hiyoshi-all_games)[:50])
query="""
SELECT gpr.game_id AS game_id, gpr.player_id AS player_id, p.name AS player_name,
       ls.start_year AS season,ss.stage AS stage,
       gpr.rank AS place, COALESCE(gpr.league_points,0)+COALESCE(gpr.penalty_league_points,0) AS pt
FROM game_player_result gpr
JOIN player p ON p.id=gpr.player_id
JOIN game g ON g.id=gpr.game_id
JOIN season_stage ss ON ss.id=g.season_stage_id
JOIN league_season ls ON ls.id=ss.league_season_id
"""
rows=[dict(r) for r in con.execute(query)]
assert len(rows)==8272,len(rows)
assert {int(r["game_id"]) for r in rows}==all_games
assert all(sum(r["game_id"]==gid for r in rows)==4 for gid in list(all_games)[:4])
by=collections.defaultdict(lambda:{"h":[],"other":[]})
season_h=collections.Counter()
for r in rows:
    key="h" if r["game_id"] in hiyoshi else "other"
    by[(r["player_id"],r["player_name"])][key].append(r)
    if key=="h": season_h[(r["season"],r["stage"])]+=1
def mean(a):return sum(a)/len(a) if a else None
def metric(a):
    pts=[float(r["pt"]) for r in a]
    pl=[float(r["place"]) for r in a]
    return {
        "games":len(a),"total_pt":round(sum(pts),1),"avg_pt":round(mean(pts),4) if pts else None,
        "avg_rank":round(mean(pl),4) if pl else None,
        "first_count":sum(r["place"]==1 for r in a),
        "top_rate_pct":round(100*sum(r["place"]==1 for r in a)/len(a),4) if a else None,
        "last_rate_pct":round(100*sum(r["place"]==4 for r in a)/len(a),4) if a else None,
        "pt_stdev":round(statistics.stdev(pts),3) if len(pts)>1 else None
    }
out=[]
for (pid,name),groups in by.items():
    h=metric(groups["h"]);o=metric(groups["other"]);total=metric(groups["h"]+groups["other"])
    item={"player_id":pid,"player_name":name,"hiyoshi":h,"other":o,"overall":total,
          "delta_avg_pt":round(h["avg_pt"]-o["avg_pt"],4) if h["games"] and o["games"] else None,
          "delta_top_rate_pp":round(h["top_rate_pct"]-o["top_rate_pct"],4) if h["games"] and o["games"] else None}
    out.append(item)
assert len(out)==56,len(out)
ranked=[x for x in out if x["hiyoshi"]["games"]>=20 and x["other"]["games"]>=20]
rank_by_delta=sorted(ranked,key=lambda x:(-x["delta_avg_pt"],-x["hiyoshi"]["games"],x["player_name"]))
rank_by_h_avg=sorted(ranked,key=lambda x:(-x["hiyoshi"]["avg_pt"],-x["hiyoshi"]["games"],x["player_name"]))
rank_by_top=sorted(ranked,key=lambda x:(-x["hiyoshi"]["top_rate_pct"],-x["hiyoshi"]["games"],x["player_name"]))
rank_top_delta=sorted(ranked,key=lambda x:(-x["delta_top_rate_pp"],-x["hiyoshi"]["games"],x["player_name"]))
all_sorted=sorted(out,key=lambda x:(-x["hiyoshi"]["games"],x["player_name"]))
assert sum(x["hiyoshi"]["games"] for x in out)==736*4
assert sum(x["other"]["games"] for x in out)==(2068-736)*4
def simple(x):return {"name":x["player_name"],"h_games":x["hiyoshi"]["games"],"h_pt":x["hiyoshi"]["total_pt"],"h_avg":x["hiyoshi"]["avg_pt"],"h_top_pct":x["hiyoshi"]["top_rate_pct"],"h_avg_rank":x["hiyoshi"]["avg_rank"],"other_games":x["other"]["games"],"other_avg":x["other"]["avg_pt"],"other_top_pct":x["other"]["top_rate_pct"],"delta":x["delta_avg_pt"],"top_delta_pp":x["delta_top_rate_pp"]}
res={
 "dataset":"official external master 2026-11-20 + DB 20261120-2341-04338cbb",
 "total_games":2068,"hiyoshi_games":736,"non_hiyoshi_games":1332,"total_player_rows":len(rows),
 "eligible_min_games_each":20, "eligible_players":len(ranked),
 "season_hiyoshi_player_appearances":[{"season":s,"stage":st,"player_appearances":cnt,"games":cnt//4} for (s,st),cnt in sorted(season_h.items())],
 "top_delta":list(map(simple,rank_by_delta)),"top_hiyoshi_average":list(map(simple,rank_by_h_avg)),
 "top_hiyoshi_top_rate":list(map(simple,rank_by_top)),"top_top_rate_delta":list(map(simple,rank_top_delta)),
 "all_players":list(map(simple,all_sorted))}
dir=Path("results");dir.mkdir(exist_ok=True)
(dir/"hiyoshi_compat_20261123.json").write_text(json.dumps(res,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
fields=list(simple(out[0]).keys())
with (dir/"hiyoshi_compat_20261123.csv").open("w",encoding="utf-8-sig",newline="") as f:
    w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(map(simple,all_sorted))
def table(block,limit=15):
    return "\n".join(f"| {i} | {x['name']} | {x['h_games']} | {x['h_avg']:+.2f} | {x['other_avg']:+.2f} | {x['delta']:+.2f} | {x['h_top_pct']:.1f}% | {x['top_delta_pp']:+.1f}pt |" for i,x in enumerate(map(simple,block[:limit]),1))
md=f"""# 日吉辰哉実況の選手別相性（2026-11-20基準）

原典：麻雀スタッツ研究所公式卓外データ（実況欄入力済み全2068試合）と、公式指定DB 20261120-2341-04338cbb を試合IDで結合。
日吉実況736試合、比較対象の日吉以外1332試合、全56選手を集計。
『相性差』＝日吉実況時の1試合平均リーグポイント−日吉以外実況時の1試合平均リーグポイント。
順位表は双方20試合以上の選手を掲載。全選手の集計はCSVとJSONに格納。
数値は条件別の実測値で、実況が成績の原因だと断定するものではない。

## 相性差が大きい順（双方20試合以上）
|順位|選手|日吉試合|日吉平均pt|非日吉平均pt|相性差pt/試合|日吉トップ率|トップ率差|
|--:|--|--:|--:|--:|--:|--:|--:|
{table(rank_by_delta,30)}

## 日吉実況時の平均獲得pt順（双方20試合以上）
|順位|選手|日吉試合|日吉平均pt|非日吉平均pt|相性差pt/試合|日吉トップ率|トップ率差|
|--:|--|--:|--:|--:|--:|--:|--:|
{table(rank_by_h_avg,30)}

## 日吉実況時のトップ率順（双方20試合以上）
|順位|選手|日吉試合|日吉平均pt|非日吉平均pt|相性差pt/試合|日吉トップ率|トップ率差|
|--:|--|--:|--:|--:|--:|--:|--:|
{table(rank_by_top,30)}

## 日吉実況時のトップ率上昇順（双方20試合以上）
|順位|選手|日吉試合|日吉平均pt|非日吉平均pt|相性差pt/試合|日吉トップ率|トップ率差|
|--:|--|--:|--:|--:|--:|--:|--:|
{table(rank_top_delta,30)}
"""
(dir/"hiyoshi_compat_20261123.md").write_text(md,encoding="utf8")
print("HIYOSHI_VERIFIED",json.dumps({k:res[k] for k in ["total_games","hiyoshi_games","non_hiyoshi_games","eligible_players"]},ensure_ascii=False),flush=True)
for k in ["top_delta","top_hiyoshi_average","top_hiyoshi_top_rate","top_top_rate_delta"]:
    print("RESULT",k,json.dumps(res[k][:12],ensure_ascii=False),flush=True)
print("BOTTOM_DELTA",json.dumps(res["top_delta"][-8:],ensure_ascii=False),flush=True)
print("SEASON_GAMES",json.dumps(res["season_hiyoshi_player_appearances"],ensure_ascii=False),flush=True)
