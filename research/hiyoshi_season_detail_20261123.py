#!/usr/bin/env python3
"""日吉実況シーズン内訳／指定5選手の年度推移／全56選手の平均順位を正本DBで集計。"""
import csv,json,sqlite3,sys,collections
from pathlib import Path
db=sys.argv[1]
con=sqlite3.connect("file:"+db+"?mode=ro",uri=True)
con.row_factory=sqlite3.Row
con.execute("PRAGMA query_only=OFF")
con.executescript(Path("sql/broadcast_commentary_master_20261120_v01.sql").read_text(encoding="utf8"))
con.execute("PRAGMA query_only=ON")
p_base=json.loads(Path("results/hiyoshi_compat_20261123.json").read_text(encoding="utf8"))
t_base=json.loads(Path("results/hiyoshi_team_compat_20261123.json").read_text(encoding="utf8"))
q="""
SELECT g.id game_id, g.date game_date, s.stage, ls.start_year season_year, bc.commentator,
       r.player_id,p.name player_name,r.rank place,
       COALESCE(r.league_points,0)+COALESCE(r.penalty_league_points,0) pt
FROM game g
JOIN season_stage s ON g.season_stage_id=s.id
JOIN league_season ls ON s.league_season_id=ls.id
JOIN broadcast_commentary_game bc ON bc.game_id=g.id
JOIN game_player_result r ON r.game_id=g.id
JOIN player p ON p.id=r.player_id
"""
rows=[dict(r) for r in con.execute(q)]
assert len(rows)==8272,len(rows)
assert len({r["game_id"] for r in rows})==2068
assert sum(r["commentator"]=="日吉辰哉" for r in rows)==736*4
gmap={}
for r in rows:
 if r["game_id"] not in gmap:
  gmap[r["game_id"]]=dict(game_id=r["game_id"],season_year=r["season_year"],stage=r["stage"],is_hiyoshi=(r["commentator"]=="日吉辰哉"))
assert len(gmap)==2068
spot_names=["伊達朱里紗","園田賢","二階堂瑠美","浅井堂岐","村上淳"]
years=sorted({r["season_year"] for r in rows})
assert years==list(range(2018,2027)),years
stages=["regular","semifinal","final"]
def fmt_year(y):return f"{y}-{(y+1)%100:02d}"
def summ(items):
 if not items:
  return dict(games=0,total_pt=0,avg_pt=None,avg_rank=None,top_count=0,top_rate_pct=None,last_count=0,last_rate_pct=None)
 n=len(items);pt=sum(float(x["pt"]) for x in items)
 rank_sum=sum(x["place"] for x in items)
 top=sum(x["place"]==1 for x in items)
 last=sum(x["place"]==4 for x in items)
 return dict(games=n,total_pt=round(pt,1),avg_pt=round(pt/n,4),avg_rank=round(rank_sum/n,4),
 top_count=top,top_rate_pct=round(100*top/n,4),last_count=last,last_rate_pct=round(100*last/n,4))
def diff(a,b,metric):
 if a["games"] and b["games"]: return round(a[metric]-b[metric],4)
 return None
season_counts=[]
for y in years:
 g=[x for x in gmap.values() if x["season_year"]==y]
 h=[x for x in g if x["is_hiyoshi"]]
 x=dict(season=fmt_year(y),season_year=y,total_games=len(g),hiyoshi_games=len(h),
 other_games=len(g)-len(h),hiyoshi_share_pct=round(100*len(h)/len(g),2))
 for st in stages:
  gs=[x for x in g if x["stage"]==st]
  x[st+"_games"]=len(gs)
  x[st+"_hiyoshi_games"]=sum(x["is_hiyoshi"] for x in gs)
 season_counts.append(x)
assert sum(x["total_games"] for x in season_counts)==2068
assert sum(x["hiyoshi_games"] for x in season_counts)==736
assert sum(x["other_games"] for x in season_counts)==1332
assert all(x["total_games"]==x["regular_games"]+x["semifinal_games"]+x["final_games"] for x in season_counts)
spot=[]
for name in spot_names:
 all_p=[r for r in rows if r["player_name"]==name]
 assert all_p
 for y in years:
  rr=[r for r in all_p if r["season_year"]==y]
  rh=[r for r in rr if r["commentator"]=="日吉辰哉"]
  ro=[r for r in rr if r["commentator"]!="日吉辰哉"]
  hh,oo,tt=summ(rh),summ(ro),summ(rr)
  spot.append(dict(player_name=name,season=fmt_year(y),season_year=y,hiyoshi=hh,other=oo,all=tt,
                  delta_avg_pt=diff(hh,oo,"avg_pt"),delta_top_pct_pp=diff(hh,oo,"top_rate_pct"),
                  delta_avg_rank=diff(hh,oo,"avg_rank")))
  assert hh["games"]+oo["games"]==tt["games"]
 prev=next(x for x in p_base["all_players"] if x["name"]==name)
 chk=[x for x in spot if x["player_name"]==name]
 assert sum(x["hiyoshi"]["games"] for x in chk)==prev["h_games"],name
 assert sum(x["other"]["games"] for x in chk)==prev["other_games"],name
 assert abs(sum(x["hiyoshi"]["total_pt"] for x in chk)-prev["h_pt"])<.101,(name,prev["h_pt"])
full_avg=[]
for r in p_base["all_players"]:
 name=r["name"];p=[x for x in rows if x["player_name"]==name]
 hh=summ([x for x in p if x["commentator"]=="日吉辰哉"])
 oo=summ([x for x in p if x["commentator"]!="日吉辰哉"])
 assert hh["games"]==r["h_games"],name
 assert oo["games"]==r["other_games"],name
 assert abs(hh["avg_rank"]-r["h_avg_rank"])<1e-3 if hh["games"] else r["h_avg_rank"] is None
 full_avg.append(dict(player_name=name,hiyoshi=hh,other=oo,all=summ(p),
                      delta_avg_rank=diff(hh,oo,"avg_rank"),delta_avg_pt=diff(hh,oo,"avg_pt"),
                      eligible=(hh["games"]>=20 and oo["games"]>=20)))
assert len(full_avg)==56
sort_full=sorted(full_avg,key=lambda x:(x["hiyoshi"]["avg_rank"] is None,x["hiyoshi"]["avg_rank"] if x["hiyoshi"]["avg_rank"] is not None else 99,-x["hiyoshi"]["games"],x["player_name"]))
# average rank difference: negative indicates better finishing position during the Hiyoshi commentary.
eligible=[r for r in full_avg if r["eligible"]]
eligible_drank=sorted(eligible,key=lambda x:x["delta_avg_rank"])
res=dict(source_db_release="20261120-2341-04338cbb",hiyoshi_games=736,
 season_counts=season_counts,spot_names=spot_names,spot_by_season=spot,all_player_avg_rank=sort_full,
 ranking_avg_rank_eligible=sorted(eligible,key=lambda x:x["hiyoshi"]["avg_rank"]),
 ranking_delta_rank_eligible=eligible_drank)
out=Path("results");out.mkdir(exist_ok=True)
(out/"hiyoshi_season_detail_20261123.json").write_text(json.dumps(res,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
def flatten_spot(r):
 h,o,all_=r["hiyoshi"],r["other"],r["all"]
 return dict(player_name=r["player_name"],season=r["season"],h_games=h["games"],h_total_pt=h["total_pt"],
 h_avg_pt=h["avg_pt"],h_avg_rank=h["avg_rank"],h_top_pct=h["top_rate_pct"],
 other_games=o["games"],other_total_pt=o["total_pt"],other_avg_pt=o["avg_pt"],other_avg_rank=o["avg_rank"],other_top_pct=o["top_rate_pct"],
 delta_avg_pt=r["delta_avg_pt"],delta_avg_rank=r["delta_avg_rank"],delta_top_pct_pp=r["delta_top_pct_pp"],
 all_games=all_["games"],all_total_pt=all_["total_pt"])
def write_csv(path, records):
 with (out/path).open("w",encoding="utf-8-sig",newline="") as f:
  w=csv.DictWriter(f,fieldnames=list(records[0]));w.writeheader();w.writerows(records)
write_csv("hiyoshi_season_counts_20261123.csv",season_counts)
write_csv("hiyoshi_spot5_seasons_20261123.csv",[flatten_spot(x) for x in spot])
def flat_rank(x):
 h,o=x["hiyoshi"],x["other"]
 return dict(player_name=x["player_name"],h_games=h["games"],h_avg_rank=h["avg_rank"],h_top_pct=h["top_rate_pct"],h_avg_pt=h["avg_pt"],
 other_games=o["games"],other_avg_rank=o["avg_rank"],other_top_pct=o["top_rate_pct"],other_avg_pt=o["avg_pt"],delta_avg_rank=x["delta_avg_rank"],delta_avg_pt=x["delta_avg_pt"],eligible=int(x["eligible"]))
write_csv("hiyoshi_player_avg_rank_20261123.csv",[flat_rank(x) for x in sort_full])
print("SEASON_COUNTS",json.dumps(season_counts,ensure_ascii=False),flush=True)
print("SPOT_SEASONS",json.dumps([flatten_spot(x) for x in spot if x["all"]["games"]],ensure_ascii=False),flush=True)
print("AVG_RANK_ELIGIBLE_TOP10",json.dumps([flat_rank(x) for x in res["ranking_avg_rank_eligible"][:10]],ensure_ascii=False),flush=True)
print("AVG_RANK_DELTA_BEST10",json.dumps([flat_rank(x) for x in eligible_drank[:10]],ensure_ascii=False),flush=True)
print("AVG_RANK_DELTA_WORST10",json.dumps([flat_rank(x) for x in eligible_drank[-10:]],ensure_ascii=False),flush=True)
print("SEASON_REPORT_PASS",len(spot),len(full_avg),flush=True)
