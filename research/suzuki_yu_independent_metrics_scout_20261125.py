#!/usr/bin/env python3
"""鈴木優：正式SQL横断スカウティング。読み取りのみ、指標定義に手を加えない。"""
import sqlite3,sys,json,time,signal,traceback
from pathlib import Path
db=Path(sys.argv[1]);cn=sqlite3.connect("file:"+str(db.resolve())+"?mode=ro",uri=True)
cn.row_factory=sqlite3.Row;cn.execute("PRAGMA query_only=ON")
assert cn.execute("SELECT count(*) FROM game").fetchone()[0]==2068
assert cn.execute("SELECT count(*) FROM kyoku").fetchone()[0]==25238
selected=[
"aka_loved_per_kyoku_v01",
"basic_avg_agari_turn_v01",
"basic_avg_first_tenpai_turn_v01",
"basic_first_tenpai_rate_v01",
"dead_wall_confinement_v02",
"dora_loved_per_kyoku_v02",
"dramatic_reach_v01",
"kumakuma_time_v01",
"last_place_escape_v01",
"oorasu_guardian_v01",
"oya_kaburi_rate_index_v01",
"protagonist_rate_v01",
"pure_empty_reach_v02",
"reach_ryukyoku_rate_v01",
"ricchi_ronhai_rate_v01",
"ryukyoku_tenpai_rate_v01",
"tsumo_share_v01",
"ura_dora_reach_agari_v01",
"yaku_agari_composition_v01",
"yattenna_haipai_rate_v01",
"junkara_reach_agari_v01",
"nishikawa_kotaro_v02",
"tsukamu_per_100_kyoku_v01",
]
def timeup(signum,frame):raise TimeoutError("query exceeded 55s")
signal.signal(signal.SIGALRM,timeup)
allout=[]
for nm in selected:
 p=Path("sql")/(nm+".sql");sql=p.read_text(encoding="utf8").strip().rstrip(";")
 print("START",nm,flush=True)
 t=time.monotonic()
 try:
  signal.alarm(55)
  rows=[dict(x) for x in cn.execute(sql)]
  signal.alarm(0)
  if rows and "period" in rows[0]: rows=[r for r in rows if r["period"]=="all"]
  if rows and "scope" in rows[0]: rows=[r for r in rows if r["scope"]=="all"]
  match=[(i,r) for i,r in enumerate(rows) if r.get("player_name")=="鈴木優" or r.get("name")=="鈴木優"]
  if not match: print("SUZUKI_YU_NOT_FOUND",nm,rows[:1],flush=True);continue
  i,r=match[0]
  rd=dict(indicator=nm,n_players=len(rows),index_order=i+1,suzuki_yu=r,top3=[{k: v for k,v in z.items() if k in ("player_name","name") or (str(k).endswith("pct") or str(k).endswith("index"))} for z in rows[:3]],elapsed=round(time.monotonic()-t,2))
  allout.append(rd);print("RESULT",json.dumps(rd,ensure_ascii=False,default=str),flush=True)
 except Exception as e:
  signal.alarm(0);print("ERROR",nm,type(e).__name__,str(e),flush=True)
print("SUMMARY",len(allout),"/",len(selected),flush=True)
Path("results").mkdir(exist_ok=True)
Path("results/suzuki_yu_independent_metrics_scout_20261125.json").write_text(json.dumps(allout,ensure_ascii=False,indent=2),encoding="utf8")
