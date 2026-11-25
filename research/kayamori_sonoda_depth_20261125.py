import sqlite3,sys,json,collections,csv
from pathlib import Path
c=sqlite3.connect("file:"+str(Path(sys.argv[1]).resolve())+"?mode=ro",uri=True);c.row_factory=sqlite3.Row
c.execute("PRAGMA query_only=ON")
def q(s,*a):return [dict(r) for r in c.execute(s,a)]
assert c.execute("select count(*) from game").fetchone()[0]==2068
assert c.execute("select count(*) from kyoku").fetchone()[0]==25238
P={r["name"]:r["id"] for r in q("select id,name from player")};K=P["茅森早香"];S=P["園田賢"]
games=collections.defaultdict(set)
for r in q("select game_id,player_id from game_player_result"):games[r["game_id"]].add(r["player_id"])
joint={g for g,p in games.items() if K in p and S in p};assert len(joint)==32
# All first riichi exposures in games involving either target, exact prior exposure/decision definition.
gids=[g for g,p in games.items() if K in p or S in p]
ph=",".join("?" for g in gids)
rounds=q(f"""select k.id ky,k.game_id,k.oya_player_id,k.round,k.honba_count,ls.start_year year,ss.stage
 from kyoku k join game g on g.id=k.game_id join season_stage ss on ss.id=g.season_stage_id
 join league_season ls on ls.id=ss.league_season_id where k.game_id in ({ph})""",*gids)
RM={r["ky"]:r for r in rounds}
def events(sql):return q(sql+f" where k.game_id in ({ph})",*gids)
D=collections.defaultdict(list);R=collections.defaultdict(list);W=collections.defaultdict(list);ST=collections.defaultdict(list)
for r in events("select e.kyoku_id ky,e.event_order o,e.id,d.actor_player_id p,d.tile,d.is_reach_declaration decl from discard_event d join event e on e.id=d.event_id join kyoku k on k.id=e.kyoku_id"):D[r["ky"]].append(r)
for r in events("select e.kyoku_id ky,e.event_order o,e.id,r.actor_player_id p,r.is_accepted ok from reach_event r join event e on e.id=r.event_id join kyoku k on k.id=e.kyoku_id"):R[r["ky"]].append(r)
for r in events("select e.kyoku_id ky,e.event_order o,e.type,a.actor_player_id w,a.target_player_id l,a.agari_points pts,a.honba_points hb from agari_event a join event e on e.id=a.event_id join kyoku k on k.id=e.kyoku_id"):W[r["ky"]].append(r)
# only latest snapshot at declaration is needed; use ordered snapshots per player.
for r in events("select e.kyoku_id ky,e.event_order o,e.id,ps.player_id p,ps.shanten_count sh from player_state ps join event e on e.id=ps.event_id join kyoku k on k.id=e.kyoku_id"):ST[(r["ky"],r["p"])].append(r)
for lst in [*D.values(),*R.values(),*W.values(),*ST.values()]:lst.sort(key=lambda r:(r["o"],r.get("id",0)))
scores=q(f"""select k.id ky,k.game_id,r.player_id p,r.score from kyoku k join kyoku_player_result r on r.kyoku_id=k.id where k.game_id in ({ph}) order by k.game_id,r.player_id,k.id""",*gids)
prev={};start={};net={}
for x in scores:
 key=(x["game_id"],x["p"]);kp=(x["ky"],x["p"]);start[kp]=prev.get(key,25000);net[kp]=x["score"]-start[kp];prev[key]=x["score"]
def norm(t):return "5"+t[1:] if t.startswith("0") else t
rows=[];inf=float("inf")
for ky,m in RM.items():
 rr=[r for r in R[ky] if r["ok"]]
 if not rr:continue
 f=rr[0];p=f["p"]
 decls=[d for d in D[ky] if d["p"]==p and d["decl"] and d["o"]>f["o"]];assert decls,(ky,p)
 o=decls[0]["o"]
 assert not any(w["o"]<=o for w in W[ky])
 for a in games[m["game_id"]]-{p}:
  if a!=K and p!=S:continue
  own=min((r["o"] for r in rr if r["p"]==a and r["o"]>f["o"]),default=inf)
  third=min((r["o"] for r in rr if r["p"] not in (p,a) and r["o"]>f["o"]),default=inf)
  own_decl=min((d["o"] for d in D[ky] if d["p"]==a and d["decl"] and d["o"]>own),default=inf)
  choices=[d for d in D[ky] if d["p"]==a and o<d["o"]<third and d["o"]<=own_decl]
  flags=[norm(d["tile"]) not in {norm(x["tile"]) for x in D[ky] if x["p"]==p and x["o"]<d["o"]} for d in choices]
  states=[x for x in ST[(ky,a)] if x["o"]<=o]
  sh=states[-1]["sh"] if states else None
  wins=[w for w in W[ky] if w["w"]==a];loss=[w for w in W[ky] if w["type"]=="ron" and w["l"]==a]
  directwin=[w for w in wins if w["type"]=="ron" and w["l"]==p];directloss=[w for w in loss if w["w"]==p]
  points=lambda ws:sum((w["pts"] or 0)+(w["hb"] or 0) for w in ws)
  rows.append(dict(**m,a=a,p=p,same=m["game_id"] in joint,sh=sh,own_oya=a==m["oya_player_id"],opp_oya=p==m["oya_player_id"],start=start[(ky,a)],rank=1+sum(start[(ky,b)]>start[(ky,a)] for b in games[m["game_id"]]),reach_turn=sum(d["p"]==p and d["o"]<=o for d in D[ky]),n=len(flags),ng=sum(flags),first_ng=flags[0] if flags else None,chase=own<inf,chase_before_third=own<third,third=third<inf,win=bool(wins),loss=bool(loss),direct_win=len(directwin),direct_loss=len(directloss),win_pts=points(wins),loss_pts=points(loss),direct_win_pts=points(directwin),direct_loss_pts=points(directloss),net=net[(ky,a)],riicher_net=net[(ky,p)],riicher_win=any(w["w"]==p for w in W[ky])))
A=[r for r in rows if r["a"]==K and r["p"]==S];B=[r for r in rows if r["a"]==K and r["p"]!=S and r["same"]];C=[r for r in rows if r["a"]!=K and r["p"]==S and r["same"]];Dall=[r for r in rows if r["a"]!=K and r["p"]==S];E=[r for r in rows if r["a"]==K and r["p"]!=S]
assert len(A)==79 and len(B)==116 and len(C)==158
assert sum(r["win"] for r in A)==12 and sum(r["direct_win"] for r in A)==5 and sum(r["direct_loss"] for r in A)==4
assert sum(r["net"] for r in A)==-48100 and sum(r["riicher_net"] for r in A)==236400
def div(a,b):return round(a/b,4) if b else None
def summ(v):
 n=len(v);w=sum(r["win"] for r in v);l=sum(r["loss"] for r in v);d=sum(r["n"] for r in v);ng=sum(r["ng"] for r in v);fd=[r for r in v if r["n"]]
 dw=sum(r["direct_win"] for r in v);dl=sum(r["direct_loss"] for r in v)
 return dict(n=n,decisions=len(fd),discards=d,non_genbutsu=ng,non_genbutsu_pct=div(100*ng,d),first_ng_n=sum(r["first_ng"] is True for r in fd),first_ng_pct=div(100*sum(r["first_ng"] is True for r in fd),len(fd)),chase=sum(r["chase"] for r in v),chase_before_third=sum(r["chase_before_third"] for r in v),third=sum(r["third"] for r in v),wins=w,win_pct=div(100*w,n),losses=l,loss_pct=div(100*l,n),direct_win=dw,direct_loss=dl,direct_win_pts=sum(r["direct_win_pts"] for r in v),direct_loss_pts=sum(r["direct_loss_pts"] for r in v),avg_win_pts=div(sum(r["win_pts"] for r in v),w),avg_loss_pts=div(sum(r["loss_pts"] for r in v),l),avg_direct_win_pts=div(sum(r["direct_win_pts"] for r in v),dw),avg_direct_loss_pts=div(sum(r["direct_loss_pts"] for r in v),dl),net=sum(r["net"] for r in v),avg_net=div(sum(r["net"] for r in v),n),riicher_win=sum(r["riicher_win"] for r in v))
groups={"K_vs_S":A,"K_vs_other_same":B,"other_vs_S_same":C,"other_vs_S_all":Dall,"K_vs_other_all":E}
out={}
for name,v in groups.items():
 d={"all":summ(v),"sh":{str(sh):summ([r for r in v if r["sh"]==sh]) for sh in sorted({r["sh"] for r in v},key=str)}}
 d["first_choice"]={name2:summ([r for r in v if fn(r)]) for name2,fn in [("genbutsu",lambda r:r["first_ng"] is False),("non_genbutsu",lambda r:r["first_ng"] is True),("no_decision",lambda r:r["first_ng"] is None)]}
 d["sh_choice"]={str(sh):{name2:summ([r for r in v if r["sh"]==sh and r["first_ng"] is flag]) for name2,flag in [("genbutsu",False),("non_genbutsu",True),("none",None)]} for sh in [0,1,2,3,4]}
 d["oya"]={key:summ([r for r in v if fn(r)]) for key,fn in [("own",lambda r:r["own_oya"]),("riicher",lambda r:r["opp_oya"]),("neither",lambda r:not r["own_oya"] and not r["opp_oya"])]}
 d["rank"]={str(i):summ([r for r in v if r["rank"]==i]) for i in range(1,5)}
 d["reach_turn"]={key:summ([r for r in v if fn(r)]) for key,fn in [("1-6",lambda r:r["reach_turn"]<=6),("7-12",lambda r:7<=r["reach_turn"]<=12),("13+",lambda r:r["reach_turn"]>=13)]}
 out[name]=d
 print("GROUP",name,json.dumps(d["all"],ensure_ascii=False),flush=True)
 for kind in ["sh","first_choice","sh_choice","oya","rank","reach_turn"]:
  print("DETAIL",name,kind,json.dumps({k:({kk:{f:vv[f] for f in ("n","wins","losses","avg_net","non_genbutsu_pct","chase","first_ng_n","decisions")} for kk,vv in x.items()} if kind=="sh_choice" else {f:x[f] for f in ("n","wins","losses","avg_net","non_genbutsu_pct","chase","first_ng_n","decisions")}) for k,x in d[kind].items()},ensure_ascii=False),flush=True)
# descriptive standardized comparison for shanten distribution only; no causal inference.
for name,v in groups.items():
 if name=="K_vs_S":continue
 keys={r["sh"] for r in A};w={sh:sum(r["sh"]==sh for r in A)/len(A) for sh in keys}
 stats={sh:summ([r for r in v if r["sh"]==sh]) for sh in keys}
 if all(stats[sh]["n"] for sh in keys):
  print("STANDARD",name,json.dumps({f:sum(w[sh]*stats[sh][f] for sh in keys) for f in ["win_pct","loss_pct","avg_net"]}),flush=True)
p=Path("results");p.mkdir(exist_ok=True)
(p/"depth.json").write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf8")
with (p/"exposures.csv").open("w",encoding="utf-8-sig",newline="") as f:
 w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
