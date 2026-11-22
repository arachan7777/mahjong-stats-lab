"""第16指標・やってんな配牌率：全局×全選手の独立検算。
配牌イベントと初期状態を別系統で読み取り、正本SQLの
分母・イーシャンテン・テンパイ・総率を選手別、年度別に照合する。
"""
import csv,json,os,sqlite3,sys
from collections import Counter,defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=Path("results");OUT.mkdir(exist_ok=True)
con=sqlite3.connect("file:"+os.path.abspath(sys.argv[1])+"?mode=ro",uri=True)
con.row_factory=sqlite3.Row
con.execute("PRAGMA temp_store=MEMORY")
assert con.execute("PRAGMA quick_check").fetchone()[0]=="ok"
def query(q):return [dict(x) for x in con.execute(q)]
def csvout(name,rows):
 if not rows:return
 with (OUT/name).open("w",newline="",encoding="utf-8-sig") as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]))
  w.writeheader();w.writerows(rows)
def jsonout(name,obj):
 (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")

participants=query("""
 SELECT r.kyoku_id,r.player_id,ls.start_year,ss.stage,k.round,k.honba_count
 FROM kyoku_player_result r
 JOIN kyoku k ON k.id=r.kyoku_id
 JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
""")
by_participant={(x["kyoku_id"],x["player_id"]):x for x in participants}
assert len(participants)==len(by_participant)
assert len(participants)%4==0
assert len(participants)==100952,(len(participants),"Unexpected DB version")

initials=query("""
 SELECT e.kyoku_id,h.actor_player_id AS player_id,h.event_id AS haipai_id,
        h.hand,ps.turn_number,ps.shanten_count AS shanten,
        ps.standard_type_shanten_count AS standard_shanten,
        ps.seven_pairs_shanten_count AS chiitoi_shanten,
        ps.thirteen_orphans_shanten_count AS kokushi_shanten,
        ps.hand AS state_hand
 FROM haipai_event h
 JOIN event e ON e.id=h.event_id
 JOIN player_state ps ON ps.event_id=h.event_id
   AND ps.player_id=h.actor_player_id
""")
by_initial={}
for r in initials:
 k=(r["kyoku_id"],r["player_id"])
 assert k in by_participant,("haipai without participant",k)
 assert k not in by_initial,("duplicate haipai",k)
 assert r["turn_number"]==0,("not pre-first-draw",r)
 hand=[t.strip() for t in r["hand"].split(",")]
 assert len(hand)==13,("not 13 initial tiles",k,len(hand))
 state_hand=[t.strip() for t in r["state_hand"].split(",")]
 assert Counter(hand)==Counter(state_hand),(k,hand,state_hand)
 shanten_candidates=[r["standard_shanten"],r["chiitoi_shanten"],r["kokushi_shanten"]]
 expected_min=min(x for x in shanten_candidates if x is not None)
 assert r["shanten"]==expected_min,(k,r,expected_min)
 assert r["shanten"]>=0,("initial 13-tile completed hand or invalid",k,r)
 by_initial[k]=r
assert len(by_initial)==len(participants),("haipai missing",len(by_initial),len(participants))

by_player=defaultdict(Counter)
by_year=defaultdict(Counter)
by_year_player=defaultdict(lambda:defaultdict(Counter))
per_kyoku=[]
hist=Counter()
for p in participants:
 k=(p["kyoku_id"],p["player_id"])
 r=by_initial[k]
 shanten=r["shanten"]
 hist[shanten]+=1
 is_tenpai=int(shanten==0)
 is_ishanten=int(shanten==1)
 is_yattenna=is_tenpai+is_ishanten
 row={"kyoku_id":p["kyoku_id"],"player_id":p["player_id"],
      "start_year":p["start_year"],"stage":p["stage"],
      "round":p["round"],"honba_count":p["honba_count"],
      "initial_shanten":shanten,
      "is_haipai_tenpai":is_tenpai,"is_haipai_ishanten":is_ishanten,
      "is_yattenna_haipai":is_yattenna}
 per_kyoku.append(row)
 for b in (by_player[p["player_id"]],by_year[p["start_year"]],
           by_year_player[p["start_year"]][p["player_id"]]):
  b["total"]+=1;b["yattenna"]+=is_yattenna
  b["tenpai"]+=is_tenpai;b["ishanten"]+=is_ishanten
assert sum(hist.values())==len(participants)
assert sum(hi for sh,hi in hist.items() if sh in (0,1))==sum(b["yattenna"] for b in by_player.values())

sql=(ROOT/"sql/yattenna_haipai_rate_v01.sql").read_text(encoding="utf-8")
period="SELECT NULL AS start_year, NULL AS stage"
assert sql.count(period)==1
sqlrows=query(sql)
def check(rows,ref,label):
 assert len(rows)==len(ref),(label,"players",len(rows),len(ref))
 for r in rows:
  p=r["player_id"]
  assert p in ref,(label,"unknown player",p)
  b=ref[p]
  exact={
   "played_kyoku_count":b["total"],
   "yattenna_haipai_count":b["yattenna"],
   "haipai_tenpai_count":b["tenpai"],
   "haipai_ishanten_count":b["ishanten"],
   "missing_initial_state_count":0
  }
  for field,n in exact.items():
   assert r[field]==n,(label,r["player_name"],field,r[field],n)
  for f,n in (
    ("yattenna_haipai_pct",b["yattenna"]),
    ("haipai_tenpai_pct",b["tenpai"]),
    ("haipai_ishanten_pct",b["ishanten"])):
   raw=100.0*n/b["total"]
   assert abs(r[f]-raw)<0.000051,(label,r["player_name"],f,r[f],raw)
  assert b["tenpai"]+b["ishanten"]==b["yattenna"]
check(sqlrows,by_player,"all_seasons")
annual=[]
for year in sorted(by_year):
 scoped=query(sql.replace(period,f"SELECT {year} AS start_year, NULL AS stage"))
 check(scoped,by_year_player[year],f"{year}_season")
 d=by_year[year]
 annual.append({
  "season":f"{year}-{str(year+1)[-2:]}",
  "participant_kyoku":d["total"],
  "yattenna_count":d["yattenna"],
  "tenpai_count":d["tenpai"],"ishanten_count":d["ishanten"],
  "yattenna_pct":round(100*d["yattenna"]/d["total"],4),
  "tenpai_pct":round(100*d["tenpai"]/d["total"],4),
  "ishanten_pct":round(100*d["ishanten"]/d["total"],4)
 })
 if year==2025:
  csvout("yattenna_haipai_v01_2025_26_all_players.csv",scoped)
  jsonout("yattenna_haipai_v01_2025_26_top10.json",scoped[:10])
  print("TOP10_2025_26",json.dumps(scoped[:10],ensure_ascii=False),flush=True)
total=len(participants)
yatt=sum(b["yattenna"] for b in by_player.values())
tenpai=sum(b["tenpai"] for b in by_player.values())
ishanten=sum(b["ishanten"] for b in by_player.values())
overall={"physical_kyoku":total//4,"participant_kyoku":total,
         "yattenna_haipai_count":yatt,
         "tenpai_haipai_count":tenpai,"ishanten_haipai_count":ishanten,
         "yattenna_pct":round(100*yatt/total,4),
         "tenpai_pct":round(100*tenpai/total,4),
         "ishanten_pct":round(100*ishanten/total,4),
         "initial_shanten_histogram":dict(sorted(hist.items()))}
assert yatt==tenpai+ishanten
summary={"sqlite_check":"ok","all_initial_13_tile_hands_verified":total,
         "all_player_state_matches_haipai":True,
         "shanten_min_of_three_types_verified":True,
         "sql_player_and_year_audit":"PASS",
         "players":len(sqlrows),"overall":overall,"annual":annual}
csvout("yattenna_haipai_v01_all_players.csv",sqlrows)
csvout("yattenna_haipai_v01_per_player_kyoku.csv",per_kyoku)
jsonout("yattenna_haipai_v01_verification.json",summary)
jsonout("yattenna_haipai_v01_top10_all.json",sqlrows[:10])
print("VALIDATION",json.dumps(summary,ensure_ascii=False),flush=True)
print("TOP10_ALL",json.dumps(sqlrows[:10],ensure_ascii=False),flush=True)
