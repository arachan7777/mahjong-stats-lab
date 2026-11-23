#!/usr/bin/env python3
"""高め三色リーチ実証（隔離研究）
定義：宣言打牌直後、リーチ成立、聴牌状態が両面2種、
片側の和了には三色同順が付き、反対側の和了には三色同順が付かない。
牌譜のtenpai_agari_matrix/tenpai_yakuを使用。リーチ宣言時点の役だけを判定。
DBは読み取り専用。公式21独自指標の定義は変更しない。
"""
import sqlite3,json,csv,sys,collections
from pathlib import Path
db=sys.argv[1]
con=sqlite3.connect("file:"+db+"?mode=ro",uri=True)
con.row_factory=sqlite3.Row
con.execute("PRAGMA query_only=ON")
players={r["id"]:r["name"] for r in con.execute("SELECT id,name FROM player")}
assert len(players)==56
yaku_ids=[r["id"] for r in con.execute("SELECT id FROM yaku_name WHERE name='三色同順'")]
assert len(yaku_ids)==1
yk=yaku_ids[0]

# 両イベントを局・選手キーで紐づけ、順序の一致も全件検証する
reaches=[dict(r) for r in con.execute("""
 SELECT re.event_id reach_id, re.actor_player_id player_id, re.is_accepted,
        e.kyoku_id kyoku_id,e.event_order reach_order,
        ls.start_year season,g.id game_id
 FROM reach_event re JOIN event e ON e.id=re.event_id
 JOIN kyoku k ON k.id=e.kyoku_id JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id JOIN league_season ls ON ls.id=ss.league_season_id
""")]
discards=[dict(r) for r in con.execute("""
 SELECT d.event_id discard_id,d.actor_player_id player_id,
        e.kyoku_id kyoku_id,e.event_order discard_order,d.tile discarded
 FROM discard_event d JOIN event e ON e.id=d.event_id
 WHERE d.is_reach_declaration=1
""")]
dmap=collections.defaultdict(list)
for d in discards:dmap[(d["kyoku_id"],d["player_id"])].append(d)
assert len(reaches)==len(discards),(len(reaches),len(discards))
paired=[]
for re in reaches:
 ds=dmap[(re["kyoku_id"],re["player_id"])]
 assert len(ds)==1,(re,ds)
 d=ds[0]
 assert d["discard_order"]<re["reach_order"],(d,re)
 paired.append({**re,**d,"player_name":players[re["player_id"]]})
assert len(set(r["discard_id"] for r in paired))==len(paired)
assert sum(x["is_accepted"] for x in paired)==22205, sum(x["is_accepted"] for x in paired)
accepted=[r for r in paired if r["is_accepted"]]
status={}
pstats=[r["discard_id"] for r in accepted]
# The existing DB is indexed by event_id. Fetch all relevant states with temp-filtered chunks
for i in range(0,len(pstats),500):
 batch=pstats[i:i+500]
 marks=",".join("?" for _ in batch)
 rows=con.execute(f"""
 SELECT pts.event_id discard_id,pts.player_id,pts.waiting_type,pts.waiting_tiles,
        pts.tile_type_count,pts.is_actor,pts.is_reached,
        ps.hand,ps.called_blocks,ps.is_menzen
 FROM player_tenpai_state pts JOIN player_state ps
 ON ps.event_id=pts.event_id AND ps.player_id=pts.player_id
 WHERE pts.event_id IN ({marks}) AND pts.is_actor=1
 """,batch)
 for x in rows:
  r=dict(x);status[(r["discard_id"],r["player_id"])]=r
no_state=[r for r in accepted if (r["discard_id"],r["player_id"]) not in status]
assert not no_state,(len(no_state),no_state[:3])
def norm(t):return t.strip().replace("r","")   # Check actual tile format before normalizing.
high=[]; both=[]; one_any=[]; misses=[]
candidate=[r for r in accepted if status[(r["discard_id"],r["player_id"])]["waiting_type"]=="両面"
           and status[(r["discard_id"],r["player_id"])]["tile_type_count"]==2]
# Each candidate matrix id: yaku mapping for ron + tsumo
matrix_rows=[]
ids=[r["discard_id"] for r in candidate]
for i in range(0,len(ids),500):
 batch=ids[i:i+500];marks=",".join("?" for _ in batch)
 rows=con.execute(f"""
 SELECT m.event_id discard_id,m.player_id,m.waiting_tile,
        m.is_ron_agari,CASE WHEN y.tenpai_agari_matrix_id IS NOT NULL THEN 1 ELSE 0 END has_sanshoku
 FROM tenpai_agari_matrix m
 LEFT JOIN tenpai_yaku y ON y.tenpai_agari_matrix_id=m.id AND y.yaku_name_id=?
 WHERE m.event_id IN ({marks})
 """,[yk]+batch)
 matrix_rows.extend(dict(x) for x in rows)
byevt=collections.defaultdict(lambda:collections.defaultdict(set))
for m in matrix_rows:
 byevt[(m["discard_id"],m["player_id"])][m["waiting_tile"]].add(m["has_sanshoku"])
ambiguous=[]
for r in candidate:
 st=status[(r["discard_id"],r["player_id"])]
 tiles=[x for x in st["waiting_tiles"].split(",") if x]
 mat=byevt[(r["discard_id"],r["player_id"])]
 if len(tiles)!=2 or len(mat)!=2 or set(tiles)!=set(mat):
  misses.append((r,st,dict(mat)));continue
 flags={}
 for t in tiles:
  observed=mat[t]
  if len(observed)>1:
   ambiguous.append((r["discard_id"],t,sorted(observed)))
  flags[t]=int(1 in observed)
 item={**r, "waiting_type":st["waiting_type"],"waiting_tiles":tiles,
       "hand":st["hand"],"called_blocks":st["called_blocks"],
       "sanshoku_tiles":[t for t in tiles if flags[t]],
       "non_sanshoku_tiles":[t for t in tiles if not flags[t]],
       "yaku_side_count":sum(flags.values())}
 if sum(flags.values())==1:high.append(item)
 elif sum(flags.values())==2:both.append(item)
 else:one_any.append(item)
assert not misses,(len(misses),str(misses[:3])[:1500])
# A sanshoku presence mismatch between ron/tsumo could indicate post-state conditions, separately report it.
assert not ambiguous,(len(ambiguous),ambiguous[:10])

counts=collections.Counter(x["player_name"] for x in accepted)
rct=collections.Counter(x["player_name"] for x in candidate)
hct=collections.Counter(x["player_name"] for x in high)
bct=collections.Counter(x["player_name"] for x in both)
ranks=[]
for pid,name in players.items():
 n=counts[name]
 if n==0: continue
 h=hct[name]
 ranks.append(dict(player=name,reach_count=n,ryanmen_reach_count=rct[name],
                  high_sanshoku_reach_count=h,
                  high_rate_all_reach_pct=round(h/n*100,4),
                  high_rate_ryanmen_pct=round(h/rct[name]*100,4) if rct[name] else None,
                  sanshoku_both_sides=bct[name]))
ranks.sort(key=lambda a:(-a["high_rate_all_reach_pct"],-a["high_sanshoku_reach_count"],a["player"]))
assert sum(r["reach_count"] for r in ranks)==22205
assert sum(r["high_sanshoku_reach_count"] for r in ranks)==len(high)
print("AUDIT",json.dumps(dict(reach_total=len(reaches),accepted=len(accepted),
 ryanmen_2wait=len(candidate),high_sanshoku=len(high),both_sanshoku=len(both),
 none_sanshoku=len(one_any),ambiguous=len(ambiguous),missed_states=len(no_state),
 high_rate_league=round(100*len(high)/len(accepted),4)),ensure_ascii=False),flush=True)
for name in ["萩原聖人","菅原千瑛","堀慎吾","石橋伸洋","園田賢"]:
 print("FOCUS",json.dumps(next((r for r in ranks if r["player"]==name),None),ensure_ascii=False),flush=True)
for x in ranks[:15]:print("TOP",json.dumps(x,ensure_ascii=False),flush=True)
for name in ["萩原聖人","菅原千瑛"]:
 ss=sorted((r for r in high if r["player_name"]==name),key=lambda x:(x["season"],x["game_id"]))
 print("FOCUS_CASES_"+name,json.dumps(ss[:30],ensure_ascii=False),flush=True)
 byyear=collections.Counter(r["season"] for r in ss)
 reyear=collections.Counter(r["season"] for r in accepted if r["player_name"]==name)
 print("FOCUS_BY_SEASON_"+name,json.dumps([dict(season=f"{y}-{(y+1)%100:02d}",reach_count=reyear[y],
  high_sanshoku_count=byyear[y],rate=round(100*byyear[y]/reyear[y],4) if reyear[y] else None)
  for y in sorted(reyear)],ensure_ascii=False),flush=True)
print("EXCLUDED_MIXED_WAITS",len([x for x in accepted if status[(x["discard_id"],x["player_id"])]["waiting_type"]!="両面"]),flush=True)
out=Path("results");out.mkdir(exist_ok=True)
with (out/"high_sanshoku_reach_players_20261123.csv").open("w",encoding="utf-8-sig",newline="") as f:
 wr=csv.DictWriter(f,fieldnames=list(ranks[0]));wr.writeheader();wr.writerows(ranks)
(out/"high_sanshoku_reach_focus_cases_20261123.json").write_text(json.dumps(
 dict(audit={"reach":len(reaches),"accepted":len(accepted),"ryanmen":len(candidate),"high":len(high)},
 cases=high,focus={name:next(r for r in ranks if r["player"]==name)
             for name in ["萩原聖人","菅原千瑛"]}),ensure_ascii=False,indent=2),encoding="utf8")
