"""麻雀スタッツ研究所 第15「ドラに愛された指数」独立イベント再生監査。

全局をイベント順に再生し、各選手の配牌・ツモ・鳴き・ロンで取得した
物理的な牌を一度ずつ数える。公開ドラ（カンドラ含む）への切替も監視。
公開前に捨てた牌は対象外、赤5と通常ドラが重なるときも1物理牌。
SQLのROW_NUMBER + 最初の打牌までの保有期間判定とは別のアルゴリズム。
"""
import csv,json,os,re,sqlite3,sys
from collections import defaultdict,Counter,deque
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=Path("results");OUT.mkdir(exist_ok=True)
C=sqlite3.connect("file:"+os.path.abspath(sys.argv[1])+"?mode=ro",uri=True)
C.row_factory=sqlite3.Row
C.execute("PRAGMA temp_store=MEMORY")
assert C.execute("PRAGMA quick_check").fetchone()[0]=="ok"
def qry(s):return [dict(r) for r in C.execute(s)]
def csvout(fn,rows):
 if rows:
  with (OUT/fn).open("w",encoding="utf-8-sig",newline="") as f:
   w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def jsonout(fn,obj):
 (OUT/fn).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
def norm(t):
 t=t.strip()
 assert re.fullmatch(r'(?:0[mps]|[1-9][mps]|[1-7]z)',t),("unknown tile",t)
 return "5"+t[1:] if t.startswith("0") else t
def tokens(s):
 return [t.strip() for t in s.split(",") if t.strip()]

# 局IDが各本場を独立に保持していることを前提に、全局×4選手を検算。
meta=qry("""
 SELECT k.id AS kyoku_id,ls.start_year,ss.stage,k.round,k.honba_count
 FROM kyoku k
 JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
""")
metadata={r["kyoku_id"]:r for r in meta}
players=qry("SELECT kyoku_id,player_id FROM kyoku_player_result")
participants=defaultdict(set)
for r in players:
 participants[r["kyoku_id"]].add(r["player_id"])
assert len(metadata)==len(participants),(len(metadata),len(participants))
assert all(len(v)==4 for v in participants.values()),"each physical kyoku must have 4 players"
assert len(players)==4*len(meta)
rows=[]
# 一つのイベントずつ読み取り。ほかの指標の集計SQLは参照しない。
stream=C.execute("""
 SELECT e.kyoku_id,e.event_order,e.id,e.type,
        h.actor_player_id AS haipai_player,h.hand AS haipai_hand,
        dw.actor_player_id AS draw_player,dw.tile AS draw_tile,
        ds.actor_player_id AS discard_player,ds.tile AS discard_tile,
        ch.actor_player_id AS chi_player,ch.tile AS chi_tile,
        pn.actor_player_id AS pon_player,pn.tile AS pon_tile,
        dm.actor_player_id AS daiminkan_player,dm.tile AS daiminkan_tile,
        ag.actor_player_id AS agari_player,ag.agari_tile AS agari_tile,
        di.dora_type AS dora_type,di.dora_tile AS dora_tile
 FROM event e
 LEFT JOIN haipai_event h ON h.event_id=e.id
 LEFT JOIN draw_event dw ON dw.event_id=e.id
 LEFT JOIN discard_event ds ON ds.event_id=e.id
 LEFT JOIN chi_event ch ON ch.event_id=e.id
 LEFT JOIN pon_event pn ON pn.event_id=e.id
 LEFT JOIN daiminkan_event dm ON dm.event_id=e.id
 LEFT JOIN agari_event ag ON ag.event_id=e.id AND e.type='ron'
 LEFT JOIN dora_indicator_event di ON di.event_id=e.id AND e.type='dora_indicator'
 ORDER BY e.kyoku_id,e.event_order,e.id
""")
current_kyoku=None
held=None
active_dora=None
got=None
red_got=None
ron_got=None
haipai_counts=None
stats=Counter()
errors=[]
def save_kyoku(k):
 if k is None:return
 assert set(got)==participants[k],("players missing",k,set(got),participants[k])
 assert all(haipai_counts[p]==1 for p in participants[k]),("haipai invalid",k,haipai_counts)
 for p in sorted(participants[k]):
  # All acquired physical cards were counted just once when becoming a dora.
  row={"kyoku_id":k,"player_id":p,"start_year":metadata[k]["start_year"],
       "stage":metadata[k]["stage"],"round":metadata[k]["round"],
       "honba_count":metadata[k]["honba_count"],"dora_tiles_acquired":got[p],
       "red_dora_acquired":red_got[p],"ron_dora_acquired":ron_got[p]}
  rows.append(row)
def receive(player,t,origin):
 norm(t)
 assert player in participants[current_kyoku],(current_kyoku,player)
 token={"t":t,"counted":False}
 held[player][t].append(token)
 if t.startswith("0") or norm(t) in active_dora:
  token["counted"]=True
  got[player]+=1
  if t.startswith("0"):red_got[player]+=1
  if origin=="ron":ron_got[player]+=1

n_events=0
for e in stream:
 k=e["kyoku_id"];typ=e["type"]
 if k!=current_kyoku:
  save_kyoku(current_kyoku)
  current_kyoku=k
  held={p:defaultdict(deque) for p in participants[k]}
  active_dora=set()
  got=Counter({p:0 for p in participants[k]})
  red_got=Counter({p:0 for p in participants[k]})
  ron_got=Counter({p:0 for p in participants[k]})
  haipai_counts=Counter()
 n_events+=1
 if typ=="haipai":
  p=e["haipai_player"]
  haipai_counts[p]+=1
  hand=tokens(e["haipai_hand"])
  assert len(hand)==13,("not 13 tiles",k,p,len(hand),hand)
  for t in hand:receive(p,t,"haipai")
 elif typ=="draw":receive(e["draw_player"],e["draw_tile"],"draw")
 elif typ=="discard":
  p=e["discard_player"];t=e["discard_tile"]
  norm(t)
  if not held[p][t]:
   errors.append((k,p,e["id"],"discard unavailable",t))
   if len(errors)>=10:raise AssertionError(errors)
  else:held[p][t].popleft()
 elif typ in ("chi","pon","daiminkan"):
  receive(e[typ+"_player"],e[typ+"_tile"],typ)
 elif typ=="dora_indicator" and e["dora_type"]=="omote":
  d=norm(e["dora_tile"])
  active_dora.add(d)
  for p in participants[k]:
   for tile,stack in held[p].items():
    if norm(tile)!=d:continue
    for token in stack:
     if not token["counted"]:
      token["counted"]=True
      got[p]+=1
      if tile.startswith("0"):red_got[p]+=1
 elif typ=="ron":
  receive(e["agari_player"],e["agari_tile"],"ron")
save_kyoku(current_kyoku)
assert not errors,errors
assert len(rows)==len(players)
assert n_events>100000

sql=(ROOT/"sql/dora_loved_per_kyoku_v01.sql").read_text(encoding="utf-8")
params="SELECT NULL AS start_year, NULL AS stage"
assert sql.count(params)==1
cut=sql.index("SELECT p.id AS player_id")
sql_each=qry(sql[:cut]+"""
SELECT kyoku_id,player_id,dora_tiles_acquired,red_dora_acquired,
       ron_dora_acquired,physical_tiles_acquired
FROM by_kyoku_player ORDER BY kyoku_id,player_id
""")
assert len(sql_each)==len(rows),("SQL rows differ",len(sql_each),len(rows))
independent={(r["kyoku_id"],r["player_id"]):r for r in rows}
assert len(independent)==len(rows)
for r in sql_each:
 key=(r["kyoku_id"],r["player_id"])
 ref=independent[key]
 for col in ("dora_tiles_acquired","red_dora_acquired","ron_dora_acquired"):
  assert r[col]==ref[col],("SQL event mismatch",key,col,r[col],ref[col])
 assert r["dora_tiles_acquired"]>=r["red_dora_acquired"]>=0
 assert r["dora_tiles_acquired"]>=r["ron_dora_acquired"]>=0

def summarize_by_player(inputrows):
 by=defaultdict(Counter)
 for r in inputrows:
  q=by[r["player_id"]]
  q["played_kyoku_count"]+=1
  q["dora_total_tiles"]+=r["dora_tiles_acquired"]
  q["red_dora_total_tiles"]+=r["red_dora_acquired"]
  q["ron_dora_total_tiles"]+=r["ron_dora_acquired"]
  q["kyoku_with_dora_count"]+=int(r["dora_tiles_acquired"]>0)
  q["max_dora_tiles_in_kyoku"]=max(q["max_dora_tiles_in_kyoku"],r["dora_tiles_acquired"])
 return by
def check_rank(qrows,source,label):
 reference=summarize_by_player(source)
 assert len(reference)==len(qrows),(label,len(reference),len(qrows))
 for q in qrows:
  p=q["player_id"]
  assert p in reference,(label,"missing",p)
  x=reference[p]
  for name in ("played_kyoku_count","dora_total_tiles","red_dora_total_tiles",
               "ron_dora_total_tiles","kyoku_with_dora_count","max_dora_tiles_in_kyoku"):
   assert x[name]==q[name],(label,p,name,x[name],q[name])
  assert abs(q["dora_loved_per_kyoku"]-round(x["dora_total_tiles"]/x["played_kyoku_count"],4))<.00006
  # sqlite ROUND is half-away-from-zero; Python round is bankers rounding.
  # Exact integer numerator/denominator have already matched above.
  actual100=100.0*x["dora_total_tiles"]/x["played_kyoku_count"]
  assert abs(q["dora_loved_per_100kyoku"]-actual100)<.000051,(label,p,"dora100",q["dora_loved_per_100kyoku"],actual100)
  assert abs(q["kyoku_with_dora_pct"]-round(100*x["kyoku_with_dora_count"]/x["played_kyoku_count"],4))<.00006

ranking=qry(sql)
check_rank(ranking,rows,"all")
seasons=sorted(set(x["start_year"] for x in rows))
annual=[]
for year in seasons:
 selected=[x for x in rows if x["start_year"]==year]
 year_sql=qry(sql.replace(params,f"SELECT {year} AS start_year, NULL AS stage"))
 check_rank(year_sql,selected,year)
 np=len(selected)
 nd=sum(x["dora_tiles_acquired"] for x in selected)
 annual.append({"season":f"{year}-{str(year+1)[-2:]}",
                "player_kyoku":np,"total_dora_tiles":nd,"dora_per_kyoku":round(nd/np,4),
                "red_dora_tiles":sum(x["red_dora_acquired"] for x in selected)})
 if year==2025:
  csvout("dora_loved_v01_2025_26_all_players.csv",year_sql)
  jsonout("dora_loved_v01_2025_26_top10.json",year_sql[:10])
  print("TOP10_2025_26",json.dumps(year_sql[:10],ensure_ascii=False),flush=True)
total_kyoku=len(meta);totals=len(rows);dr=sum(x["dora_tiles_acquired"] for x in rows)
hist=dict(sorted(Counter(x["dora_tiles_acquired"] for x in rows).items()))
assert len(rows)==4*total_kyoku
assert sum(hist.values())==totals and sum(k*v for k,v in hist.items())==dr
overall={"kyoku_total":total_kyoku,"player_kyoku":totals,
         "dora_total_tiles":dr,"dora_per_player_kyoku":round(dr/totals,4),
         "red_dora_total_tiles":sum(x["red_dora_acquired"] for x in rows),
         "ron_dora_total_tiles":sum(x["ron_dora_acquired"] for x in rows),
         "dora_count_distribution":hist}
summary={"sqlite_check":"ok","events_replayed":n_events,
         "all_kyoku_player_records_checked":len(rows),
         "players":len(ranking),"overall":overall,"annual":annual}
csvout("dora_loved_v01_all_players.csv",ranking)
csvout("dora_loved_v01_all_kyoku_player.csv",rows)
jsonout("dora_loved_v01_validation.json",summary)
jsonout("dora_loved_v01_top10_all.json",ranking[:10])
print("VALIDATION",json.dumps(summary,ensure_ascii=False),flush=True)
print("TOP10_ALL",json.dumps(ranking[:10],ensure_ascii=False),flush=True)
