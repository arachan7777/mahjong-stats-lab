#!/usr/bin/env python3
"""麻雀スタッツ研究所：茅森早香「打点女王」の内訳・正式DB読み取り限定研究。
2026-11-20 frozen canonical DB; no change to original data or established metrics.
"""
import sqlite3,sys,json,csv,collections,statistics
from pathlib import Path

cn=sqlite3.connect("file:"+str(Path(sys.argv[1]))+"?mode=ro",uri=True)
cn.row_factory=sqlite3.Row
cn.execute("PRAGMA query_only=ON")
assert cn.execute("SELECT COUNT(*) FROM game").fetchone()[0]==2068
assert cn.execute("SELECT COUNT(*) FROM kyoku").fetchone()[0]==25238

# Single agari event = one scoring observation; agari_points excludes honba/kyotaku,
# separate from revenue_points. Yaku rows aggregate by event before joining.
w=[dict(x) for x in cn.execute("""
 SELECT a.event_id,a.actor_player_id player_id,p.name player_name,
        ls.start_year year,ss.stage,e.type agari_type,
        a.agari_points,a.honba_points,a.kyotaku_points,a.revenue_points,
        a.han,a.fu,a.is_menzen,a.is_yakuman,a.agari_tile
 FROM agari_event a JOIN event e ON e.id=a.event_id
 JOIN player p ON p.id=a.actor_player_id
 JOIN kyoku k ON k.id=e.kyoku_id
 JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
""")]
assert len(w)==20173,(len(w),"agari count differs")
by_event={r["event_id"]:r for r in w}
for r in w:
 assert r["agari_type"] in ("ron","tsumo")
 assert r["revenue_points"]==r["agari_points"]+r["honba_points"]+r["kyotaku_points"]
 r.update(yaku_han=0,dora_han=0,aka_han=0,ura_han=0,omote_han=0,exotic_dora_han=0,
          yaku_count=0,dora_count=0,yaku_names=[],dora_names=[])

names={x["id"]:x["name"] for x in cn.execute("SELECT id,name FROM yaku_name")}
yrows=[dict(x) for x in cn.execute("SELECT agari_event_id,yaku_name_id,han FROM agari_yaku")]
seen=collections.defaultdict(lambda:collections.Counter())
for x in yrows:
 r=by_event[x["agari_event_id"]]
 name=names[x["yaku_name_id"]]
 h=x["han"]
 assert h>=0,(x,name)
 seen[name]["count"]+=1
 seen[name]["han"]+=h
 if "ドラ" in name:
  r["dora_han"]+=h
  r["dora_count"]+=1
  r["dora_names"].append(name)
  if "赤" in name:r["aka_han"]+=h
  elif "裏" in name:r["ura_han"]+=h
  elif name=="ドラ":r["omote_han"]+=h
  else:r["exotic_dora_han"]+=h
 else:
  r["yaku_han"]+=h
  r["yaku_count"]+=1
  r["yaku_names"].append(name)
discrepancies=[r for r in w if not r["is_yakuman"] and r["han"]!=r["yaku_han"]+r["dora_han"]]
print("YAKU_DEFINITIONS",json.dumps({k:v for k,v in seen.items()},ensure_ascii=False),flush=True)
print("NON_YAKUMAN_HAN_MISMATCH_COUNT",len(discrepancies),flush=True)
if discrepancies:print("MISMATCH_SAMPLES",json.dumps(discrepancies[:5],ensure_ascii=False),flush=True)
assert not discrepancies,"non-yakuman yaku data must match total han"
assert sum(r["is_yakuman"] for r in w)>=0

# rank by avg points includes all winning players, comparison only among >= 100 agari too
def score_agg(rs,name):
 n=len(rs)
 a=lambda col:sum(r[col] for r in rs)
 nonyak=[r for r in rs if not r["is_yakuman"]]
 hy=len(nonyak)
 wins0=[r for r in rs if r["dora_han"]==0]
 mans=[r for r in rs if r["agari_points"]>=8000]
 mans0=[r for r in mans if r["dora_han"]==0]
 hand2=sum((r["yaku_han"]>=3 and r["dora_han"]<=1) for r in nonyak)
 result=dict(name=name,agari_count=n,
  avg_agari_points=round(a("agari_points")/n,4),
  total_agari_points=a("agari_points"),
  avg_revenue_points=round(a("revenue_points")/n,4),
  avg_honba_points=round(a("honba_points")/n,4),
  avg_kyotaku_points=round(a("kyotaku_points")/n,4),
  ron_count=sum(r["agari_type"]=="ron" for r in rs),
  tsumo_count=sum(r["agari_type"]=="tsumo" for r in rs),
  menzen_count=a("is_menzen"),
  avg_ron_agari_points=round(sum(r["agari_points"] for r in rs if r["agari_type"]=="ron")/max(1,sum(r["agari_type"]=="ron" for r in rs)),4),
  avg_tsumo_agari_points=round(sum(r["agari_points"] for r in rs if r["agari_type"]=="tsumo")/max(1,sum(r["agari_type"]=="tsumo" for r in rs)),4),
  manganplus_count=len(mans),
  manganplus_pct=round(100*len(mans)/n,4),
  hanemanplus_count=sum(r["agari_points"]>=12000 for r in rs),
  hanemanplus_pct=round(100*sum(r["agari_points"]>=12000 for r in rs)/n,4),
  yakuman_count=a("is_yakuman"),
  nonyakuman_agari_count=hy,
  avg_han_nonyakuman=round(sum(r["han"] for r in nonyak)/max(1,hy),4),
  avg_yaku_han_nonyakuman=round(sum(r["yaku_han"] for r in nonyak)/max(1,hy),4),
  avg_dora_han_nonyakuman=round(sum(r["dora_han"] for r in nonyak)/max(1,hy),4),
  avg_omote_han_nonyakuman=round(sum(r["omote_han"] for r in nonyak)/max(1,hy),4),
  avg_aka_han_nonyakuman=round(sum(r["aka_han"] for r in nonyak)/max(1,hy),4),
  avg_ura_han_nonyakuman=round(sum(r["ura_han"] for r in nonyak)/max(1,hy),4),
  dora_han_total_nonyakuman=sum(r["dora_han"] for r in nonyak),
  yaku_han_total_nonyakuman=sum(r["yaku_han"] for r in nonyak),
  han_total_nonyakuman=sum(r["han"] for r in nonyak),
  dora_han_share_pct_nonyakuman=round(100*sum(r["dora_han"] for r in nonyak)/max(1,sum(r["han"] for r in nonyak)),4),
  no_dora_count=len(wins0),
  no_dora_pct=round(100*len(wins0)/n,4),
  manganplus_with_no_dora_count=len(mans0),
  manganplus_with_no_dora_pct_of_all_manganplus=round(100*len(mans0)/max(1,len(mans)),4),
  manganplus_with_no_dora_pct_of_all_agari=round(100*len(mans0)/n,4),
  avg_agari_points_no_dora=round(sum(r["agari_points"] for r in wins0)/max(1,len(wins0)),4),
  avg_agari_points_with_dora=round(sum(r["agari_points"] for r in rs if r["dora_han"]>0)/max(1,(n-len(wins0))),4),
  yaku_han_ge3_dora_le1_count=hand2,
 )
 return result
def group(rows,keys):
 d=collections.defaultdict(list)
 for r in rows:d[tuple(r[k] for k in keys)].append(r)
 out=[]
 for k,rs in d.items():
  item=dict(zip(keys,k));item.update(score_agg(rs,str(k)))
  out.append(item)
 return out

kaya=[r for r in w if r["player_name"]=="茅森早香"]
assert len(kaya)>100
all_player=group(w,["player_name"])
all_player.sort(key=lambda z:(-z["avg_agari_points"],-z["agari_count"]))
for i,r in enumerate(all_player,1):r["avg_points_rank_unrestricted"]=i
qualified=[r for r in all_player if r["agari_count"]>=100]
for i,r in enumerate(qualified,1):r["avg_points_rank_min100"]=i
qualified200=[r for r in all_player if r["agari_count"]>=200]
for i,r in enumerate(qualified200,1):r["avg_points_rank_min200"]=i
season=group(w,["year"])
kaya_season=group(kaya,["year"])
kaya_stage=group(kaya,["stage"])
kaya_type=group(kaya,["agari_type"])
league_type=group(w,["agari_type"])
league=score_agg(w,"リーグ全体")
kaya_stats=next(r for r in all_player if r["player_name"]=="茅森早香")
assert kaya_stats["agari_count"]==len(kaya)
# All yaku frequency -- use composition denominator all agari as in canonical yaku_agari_composition_v01
def yaku_rank(rs):
 cnt=collections.Counter()
 han=collections.Counter()
 for r in rs:
  if r["is_yakuman"]:continue
  for name in r["yaku_names"]:cnt[name]+=1
  for name in r["dora_names"]:cnt[name]+=1
 for a in rs:
  if a["is_yakuman"]:continue
  for x in yrows_by_event.get(a["event_id"],[]):
   han[names[x["yaku_name_id"]]]+=x["han"]
 return cnt,han
yrows_by_event=collections.defaultdict(list)
for x in yrows:yrows_by_event[x["agari_event_id"]].append(x)
names_all=set(seen)
k_count,k_han=yaku_rank(kaya)
l_count,l_han=yaku_rank(w)
yaku_comparison=[]
for name in sorted(names_all):
 kc=k_count[name];lc=l_count[name]
 yaku_comparison.append(dict(yaku_name=name,
   kaya_count=kc,kaya_pct=round(100*kc/len(kaya),4),
   league_count=lc,league_pct=round(100*lc/len(w),4),
   kaya_han_total=k_han[name],league_han_total=l_han[name],
   ratio_vs_league=round((kc/len(kaya))/(lc/len(w)),4) if lc else None))
yaku_comparison.sort(key=lambda r:(-r["kaya_count"],r["yaku_name"]))

# Distribution of dora and points: unconditional and high-point
def bname(r):
 if r["dora_han"]<=0:return "0"
 if r["dora_han"]==1:return "1"
 if r["dora_han"]==2:return "2"
 return "3+"
def dora_dist(rs):
 d=collections.defaultdict(list)
 for r in rs:d[bname(r)].append(r)
 return [dict(dora_han_band=k,agari_count=len(d[k]),
  agari_pct=round(100*len(d[k])/len(rs),4),
  avg_agari_points=round(sum(z["agari_points"] for z in d[k])/len(d[k]),4),
  manganplus_count=sum(z["agari_points"]>=8000 for z in d[k]),
  manganplus_pct=round(100*sum(z["agari_points"]>=8000 for z in d[k])/len(d[k]),4))
  for k in ("0","1","2","3+") if d[k]]
def savecsv(path,records):
 assert records
 with open(path,"w",encoding="utf-8-sig",newline="") as f:
  wr=csv.DictWriter(f,list(records[0].keys()));wr.writeheader();wr.writerows(records)
out=Path("results");out.mkdir(exist_ok=True)
savecsv(out/"kayamori_all_player_avg_points.csv",all_player)
savecsv(out/"kayamori_by_season.csv",kaya_season)
savecsv(out/"kayamori_by_stage.csv",kaya_stage)
savecsv(out/"kayamori_all_yaku_comparison.csv",yaku_comparison)
savecsv(out/"kayamori_all_wins.csv",[{**{k:v for k,v in r.items() if k not in ("yaku_names","dora_names")}, "yaku_names":" / ".join(r["yaku_names"]),"dora_names":" / ".join(r["dora_names"])} for r in kaya])
summary={
 "base":"konoui/m-league-game-db 20261120-2341-04338cbb",
 "total_wins":len(w),
 "kayamori":kaya_stats,"league":league,
 "player_count":len(all_player),"qualified_min100":len(qualified),"qualified_min200":len(qualified200),
 "top15_average_points":all_player[:15],
 "top15_min100":qualified[:15],
 "top15_min200":qualified200[:15],
 "kayamori_by_season":sorted(kaya_season,key=lambda r:r["year"]),
 "kayamori_by_stage":kaya_stage,
 "kayamori_by_ron_tsumo":kaya_type,"league_by_ron_tsumo":league_type,
 "kayamori_dora_distribution":dora_dist(kaya),
 "league_dora_distribution":dora_dist(w),
 "kayamori_yaku_top20":yaku_comparison[:20],
 "kayamori_yaku_overrepresented":sorted(
  [v for v in yaku_comparison if v["kaya_count"]>=5 and v["league_count"]>=20],
  key=lambda r:-r["ratio_vs_league"])[:25],
 "kayamori_high_points_without_dora":[{
  "event_id":r["event_id"],"year":r["year"],"stage":r["stage"],"agari_type":r["agari_type"],
  "agari_points":r["agari_points"],"han":r["han"],"yaku_names":r["yaku_names"]}
  for r in sorted(kaya,key=lambda r:-r["agari_points"]) if r["agari_points"]>=8000 and r["dora_han"]==0][:20],
 "dora_category_names":[name for name in names.values() if "ドラ" in name],
}
(out/"kayamori_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
for name in ("kayamori","league","qualified_min100","qualified_min200","kayamori_by_season",
             "kayamori_by_ron_tsumo","league_by_ron_tsumo","kayamori_dora_distribution","league_dora_distribution",
             "kayamori_yaku_top20","kayamori_yaku_overrepresented",
             "top15_min100","kayamori_high_points_without_dora","dora_category_names"):
 print("RESULT",name,json.dumps(summary[name],ensure_ascii=False),flush=True)
print("VALIDATION_OK",len(w),len(kaya),len(yrows),flush=True)
