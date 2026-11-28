"""Stage 4B only. Read-only pinned DB, approved origin, possession and point evidence."""
import argparse,json,os,traceback
from collections import Counter,defaultdict
from pathlib import Path
from dontsuka_v026_extract import connect_readonly,verify_database,sha256_file
from dontsuka_v026_2a_audit import events
from dontsuka_v026_2a_replay import Replay,normal,tile
from dontsuka_v026_2b_replay import RELEASE,DB_SHA,ranks
from dontsuka_v026_3b import verified_zip,read_csv_zip,write_csv,rates,STAGE3A_SHA,STAGE2B_SHA
from dontsuka_v026_4a import STAGE3B_SHA,keys
from dontsuka_v026_4b_core import origin_key,active_at,state,coexists,transition,ron_result

STAGE4A_SHA="bb74f4748e9e0b5bb13a32e838ed022ab66cf20a9bac2d75d0e7ebcf6c10a6d1"
STAGE2A_SHA="77a165910c731a63a52d3eda966050dddf164cd12ab0b0130979c9ce39e58a17"
def js(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"))
def emit(out,name,rs,fields):
    write_csv(out/name,rs,list(dict.fromkeys(fields+[k for r in rs for k in r])))
def group(rs,fn):
    d=defaultdict(list)
    for r in rs:d[fn(r)].append(r)
    return d
def scoremap(s):return {int(k):int(v) for k,v in json.loads(s).items()}

class RonState:
    """Use approved Stage 1 action/snapshot freshness and ordinary ron matrix.
    Physical replay prevents a target with a 14-tile effective hand being
    treated as waiting for an ordinary discard. No historical origin is changed.
    """
    def __init__(self,c,ky):
        self.rp=Replay();self.ps={};self.ts={};self.wait={};self.last_stable={}
        self.actions=group((dict(r) for r in c.execute("""SELECT ps.*,e.event_order FROM player_state ps JOIN event e ON e.id=ps.event_id WHERE e.kyoku_id=?""",(ky,))),lambda r:r["event_id"])
        self.snaps=group((dict(r) for r in c.execute("""SELECT ps.*,e.event_order FROM player_tenpai_state ps JOIN event e ON e.id=ps.event_id WHERE e.kyoku_id=?""",(ky,))),lambda r:r["event_id"])
        self.matrix=group((dict(r) for r in c.execute("""SELECT m.event_id,m.player_id,m.waiting_tile,m.is_ron_agari FROM tenpai_agari_matrix m JOIN event e ON e.id=m.event_id WHERE e.kyoku_id=?""",(ky,))),lambda r:(r["event_id"],r["player_id"]))
    def detail(self,p,typ):
        h=self.rp.hands.get(p,[]);m=self.rp.melds.get(p,[])
        a=self.ps.get(p);s=self.ts.get(p)
        d=dict(action_event_id=a["event_id"] if a else None,snapshot_event_id=s["event_id"] if s else None,
               shanten=a["shanten_count"] if a else None,furiten=s["is_furiten"] if s else None,
               effective_tiles=len(h)+3*len(m),legal=None,reason="")
        if d["effective_tiles"]!=13:d.update(legal=False,reason="not_13_tile_waiting_state")
        elif not a:d.update(reason="missing_action_state")
        elif a["shanten_count"] is None:d.update(reason="missing_shanten")
        elif a["shanten_count"]!=0:d.update(legal=False,reason="not_tenpai")
        elif not s or s["event_order"]<a["event_order"]:d.update(reason="missing_fresh_tenpai_snapshot")
        elif s["is_furiten"] is None:d.update(reason="missing_furiten")
        elif s["is_furiten"]:d.update(legal=False,reason="furiten")
        else:
            ms=self.matrix.get((s["event_id"],p),[])
            if not ms:d.update(reason="missing_ron_matrix")
            else:
                valid=any(normal(tile(r["waiting_tile"]))==typ and r["is_ron_agari"]==1 for r in ms)
                d.update(legal=valid,reason="ordinary_ron" if valid else "no_ordinary_ron_for_type")
        return d
    def step(self,e):
        p=e.get("actor");kind=e["type"]
        if kind=="draw":
            a=self.ps.get(p)
            self.last_stable[p]=a["shanten_count"] if a else None
        if kind not in ("ron","tsumo","ryukyoku"):self.rp.step(e)
        for a in self.actions.get(e["id"],[]):self.ps[a["player_id"]]=a
        for s in self.snaps.get(e["id"],[]):self.ts[s["player_id"]]=s

def main():
    ap=argparse.ArgumentParser()
    for n in ("db","stage2a","stage2b","stage3a","stage3b","stage4a","out"):ap.add_argument(n,type=Path)
    a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    c=connect_readonly(a.db);dbm=verify_database(c,RELEASE)
    if sha256_file(a.db)!=DB_SHA:raise ValueError("DB hash")
    zs={}
    for n,digest in (("stage2a",STAGE2A_SHA),("stage2b",STAGE2B_SHA),("stage3a",STAGE3A_SHA),("stage3b",STAGE3B_SHA),("stage4a",STAGE4A_SHA)):
        z,m=verified_zip(getattr(a,n),digest)
        if m["database_sha256"]!=DB_SHA:raise ValueError(n+" DB identity")
        zs[n]=z
    z4=zs["stage4a"];z3=zs["stage3a"];z2=zs["stage2b"]
    origins=read_csv_zip(z4,"tile_possession_intervals.csv")
    changes=read_csv_zip(z4,"tile_possession_changes.csv")
    links=read_csv_zip(z4,"origin_ron_links.csv")
    actual=read_csv_zip(z4,"actual_ron_classification.csv")
    old_round=read_csv_zip(z4,"dontsuka_kyoku_classification.csv")
    orig3=read_csv_zip(z3,"opponent_hypothetical_all.csv")
    bykey={origin_key(r):r for r in origins};base={origin_key(r):r for r in orig3}
    if len(origins)!=len(bykey)!=28060:raise ValueError("origin duplicates")
    if set(bykey)!=set(base) or len(bykey)!=28060 or len({k[0] for k in bykey})!=27578:raise ValueError("origin identity")
    for k,o in bykey.items():
        if any(o[f]!=base[k][f] for f in ("kyoku_id","drawer","target","tile","rank_drop","event_order")):raise ValueError("origin changed")
    if (sum(float(o["rank_drop"])>0 for o in origins),sum(float(o["rank_drop"])==0 for o in origins),len(changes),len(links),len(old_round))!=(13170,14890,9518,8428,23535):raise ValueError("approved counts")
    if Counter(r["category"] for r in old_round)!=Counter(immediate=6227,subsequent=969,different_tile=542,no_ron=15795,special_excluded=2):raise ValueError("approved 4A categories")
    prev3=read_csv_zip(zs["stage3b"],"rank_drop_kyoku_details.csv")
    if (len(prev3),sum(int(r["rank_maintained_or_improved"]) for r in prev3),sum(int(r["ron_avoided"]) for r in prev3))!=(11143,4518,7762):raise ValueError("approved 3B counts")
    if len(actual)!=11031 or len({r["ron_event_id"] for r in actual})!=11031:raise ValueError("actual ron identity")
    dbactual={int(r[0]):(int(r[1]),int(r[2]),int(r[3]),r[4]) for r in c.execute("""SELECT a.event_id,e.kyoku_id,a.target_player_id,a.actor_player_id,a.agari_tile FROM agari_event a JOIN event e ON e.id=a.event_id WHERE e.type='ron'""")}
    if dbactual!={int(r["ron_event_id"]):(int(r["kyoku_id"]),int(r["player_id"]),int(r["winner"]),r["tile"]) for r in actual}:raise ValueError("actual ron DB mismatch")
    if len({(origin_key(r),r["ron_event_id"]) for r in links})!=len(links):raise ValueError("duplicate origin links")
    byplayer=group(origins,lambda r:(int(r["kyoku_id"]),int(r["drawer"])))
    candidates={k:v for k,v in byplayer.items() if any(float(x["rank_drop"])>0 for x in v) and any(float(x["rank_drop"])==0 for x in v)}
    if {k for k,v in byplayer.items() if any(float(x["rank_drop"])>0 for x in v)}!={(int(r["kyoku_id"]),int(r["player_id"])) for r in prev3}:raise ValueError("3B key identity")
    byky=group(candidates,lambda k:k[0]);byron=group(links,lambda r:int(r["ron_event_id"]))
    bysource=group(actual,lambda r:int(r["source_event_id"]))
    all_changes=group(changes,lambda r:origin_key(r))
    for k,o in bykey.items():
        count=int(o["start_count"]);order=int(o["start_event_order"])
        if count<=0:raise ValueError("origin start count")
        for ch in sorted(all_changes[k],key=lambda r:int(r["event_order"])):
            if int(ch["event_order"])<=order or int(ch["before_count"])!=count or count<=0:raise ValueError("possession chain")
            count=int(ch["after_count"]);order=int(ch["event_order"])
        if count!=int(o["end_count"]) or (count==0)!=(o["end_reason"]=="zero"):raise ValueError("possession end")
        if count==0 and order!=int(o["end_event_order"]):raise ValueError("possession end event")
    endrows=read_csv_zip(z2,"kyoku_comparison.csv")
    end={int(r["kyoku_id"]):r for r in endrows}
    if len(end)!=25238 or any(r["match"] not in ("1","True","true") or r["error"] for r in endrows):raise ValueError("2B round comparison")
    moves=group(read_csv_zip(z2,"point_movements.csv"),lambda r:int(r["kyoku_id"]))
    meta={int(r[0]):dict(game_id=int(r[1]),game_date=r[2],season_start_year=int(r[3]),stage=r[4]) for r in c.execute("""SELECT k.id,g.id,g.date,ls.start_year,ss.stage FROM kyoku k JOIN game g ON g.id=k.game_id JOIN season_stage ss ON ss.id=g.season_stage_id JOIN league_season ls ON ls.id=ss.league_season_id""")}
    names={int(r[0]):r[1] for r in c.execute("SELECT id,name FROM player")}
    if (len(meta),len({m["game_id"] for m in meta.values()}),len(names),c.execute("SELECT count(*) FROM draw_event").fetchone()[0])!=(25238,2068,56,1257732):raise ValueError("DB counts")
    timeline=[];rounds=[];decisions=[];uncertain=[];errors=[];examples={}
    for idx,(ky,ks) in enumerate(sorted(byky.items())):
        ev=None
        try:
            rs=RonState(c,ky)
            sc=scoremap(end[ky]["start_scores"]);final=scoremap(end[ky]["recorded_end_scores"])
            if final!=scoremap(end[ky]["replayed_end_scores"]):raise ValueError("end scores")
            mvs={int(r["event_id"]):r for r in moves[ky]}
            prev={k:((),(),()) for k in ks};ever=set();starts=Counter();ends=Counter();restarts=Counter()
            info=lambda k:dict(kyoku_id=ky,player_id=k[1],**meta[ky])
            evs=list(events(c,ky))
            for ev in evs:
                eid=ev["id"];order=ev["event_order"];kind=ev["type"]
                for k in ks:
                    os_=candidates[k]
                    eligible={};evidence={}
                    for o in os_:
                        if not active_at(o,order,"before"):continue
                        pair=(int(o["target"]),o["tile_type"])
                        d=rs.detail(*pair);eligible[pair]=d["legal"];evidence[origin_key(o)]=d
                    s=state(os_,order,eligible,"before")
                    if s!=prev[k]:raise ValueError("pre/post state continuity")
                    for o in os_:
                        if int(o["start_event_order"])==order:
                            d=rs.detail(int(o["target"]),o["tile_type"])
                            if d["legal"] is not True:
                                uncertain.append(dict(**info(k),event_id=eid,origin=js(origin_key(o)),reason="approved_origin_eligibility_not_reproduced",evidence=js(d)))
                    for r in bysource.get(eid,[]):
                        if int(r["player_id"])!=k[1]:continue
                        rid=int(r["ron_event_id"]);mv=mvs[rid];p=k[1]
                        if scoremap(mv["before_scores"])!=sc:raise ValueError("source/ron score movement mismatch")
                        if scoremap(mv["after_scores"])!=final:raise ValueError("ron/end score mismatch")
                        if r["source_kind"]!=kind or r["tile"]!=ev["tile"]:raise ValueError("source event identity")
                        accepted=p in rs.rp.reaches
                        opened=any(m[0]!="ankan" for m in rs.rp.melds[p])
                        stable=rs.last_stable.get(p)
                        rr=ron_result(s,byron[rid],int(r["winner"]),ranks(sc)[p],ranks(final)[p],kind,int(r["tsumogiri"]),bool(ev.get("declaration")),accepted,opened,None if stable is None else stable==0)
                        matched=rr.pop("matching_origins")
                        rr.update(**info(k),source_event_id=eid,ron_event_id=rid,winner=int(r["winner"]),tile=r["tile"],source_kind=kind,tsumogiri=int(r["tsumogiri"]),declaration=int(bool(ev.get("declaration"))),accepted_before=int(accepted),open_before=int(opened),stable_shanten_before_draw=stable,ever_coexisted_before=int(k in ever),matching_origins=js(matched),down_origins=js(s[0]),maintain_origins=js(s[1]),unknown_origins=js(s[2]),all_approved_links=js(byron[rid]),scores_before=js(sc),scores_end=js(final))
                        decisions.append(rr);examples.setdefault(rr["reason"],rr)
                        if rr["reason"].startswith("unresolved"):uncertain.append(dict(**info(k),event_id=eid,reason=rr["reason"],evidence=js(rr)))
                rs.step(ev)
                if eid in mvs:
                    mv=mvs[eid]
                    if scoremap(mv["before_scores"])!=sc:raise ValueError("2B point continuity")
                    sc=scoremap(mv["after_scores"])
                for k in ks:
                    os_=candidates[k];eligible={};evidence={};active=[]
                    for o in os_:
                        if not active_at(o,order):continue
                        pair=(int(o["target"]),o["tile_type"])
                        d=rs.detail(*pair);eligible[pair]=d["legal"];evidence[origin_key(o)]=d;active.append(o)
                        n=sum(normal(t)==o["tile_type"] for t in rs.rp.hands[k[1]])
                        if n<=0:raise ValueError("4A active interval replay mismatch")
                    s=state(os_,order,eligible)
                    possible_down=any(float(o["rank_drop"])>0 and eligible[(int(o["target"]),o["tile_type"])] is not False for o in active)
                    possible_same=any(float(o["rank_drop"])==0 and eligible[(int(o["target"]),o["tile_type"])] is not False for o in active)
                    if s[2] and possible_down and possible_same:
                        uncertain.append(dict(**info(k),event_id=eid,reason="unknown_legal_ron_with_possible_coexistence",evidence=js([[list(x),d] for x,d in evidence.items()])))
                    t=transition(prev[k],s,k in ever)
                    if t:
                        starts[k]+=t=="start";ends[k]+=t=="end";restarts[k]+=t=="restart"
                        row=dict(**info(k),event_id=eid,event_order=order,event_type=kind,actor=ev.get("actor"),transition=t,previous_down=js(prev[k][0]),previous_maintain=js(prev[k][1]),down_origins=js(s[0]),maintain_origins=js(s[1]),unknown_origins=js(s[2]),active_origins=js([origin_key(o) for o in active]),evidence=js([[list(x),d] for x,d in evidence.items()]),ended_possession_origins=js([origin_key(o) for o in os_ if int(o["end_event_order"])==order and o["end_reason"]=="zero"]))
                        timeline.append(row);examples.setdefault(t,row)
                    if coexists(s):ever.add(k)
                    prev[k]=s
            if sc!=final:raise ValueError("2B final score mismatch")
            for k in ks:
                if k in ever:rounds.append(dict(**info(k),starts=starts[k],ends=ends[k],restarts=restarts[k]))
        except Exception as ex:
            errors.append(dict(kyoku_id=ky,event_id=ev["id"] if ev else "",error=repr(ex),traceback=traceback.format_exc()))
        if idx%500==0:print("candidate kyoku",idx,"errors",len(errors),"unresolved rows",len(uncertain),flush=True)
    unique=lambda rows,fields:len(rows)==len({tuple(r[f] for f in fields) for r in rows})
    if not unique(rounds,("kyoku_id","player_id")) or not unique(decisions,("ron_event_id",)) or not unique(timeline,("kyoku_id","player_id","event_id")):errors.append(dict(error="duplicate output"))
    rrmap={(r["kyoku_id"],r["player_id"]):r for r in rounds}
    for r in rounds:r.update(tolerated=0,sage=0,reach_tsumogiri_excluded=0)
    for r in decisions:
        k=(r["kyoku_id"],r["player_id"])
        if k in rrmap:
            for f in ("tolerated","sage","reach_tsumogiri_excluded"):rrmap[k][f]+=r[f]
        elif r["tolerated"] or r["sage"]:errors.append(dict(error="decision without coexistence",detail=js(r)))
    stats=defaultdict(Counter)
    for p,s,t in c.execute("""SELECT DISTINCT gr.player_id,ls.start_year,ss.stage FROM game_player_result gr JOIN game g ON g.id=gr.game_id JOIN season_stage ss ON ss.id=g.season_stage_id JOIN league_season ls ON ls.id=ss.league_season_id"""):
        for key in keys(s,t):stats[(p,*key)]
    for r in rounds:
        for key in keys(r["season_start_year"],r["stage"]):
            stats[(r["player_id"],*key)].update({f:r[f] for f in ("starts","ends","restarts","tolerated","sage","reach_tsumogiri_excluded")})
            stats[(r["player_id"],*key)]["coexist_kyoku"]+=1
    def metrics(s):
        return dict(coexist_kyoku=s["coexist_kyoku"],starts=s["starts"],ends=s["ends"],restarts=s["restarts"],tolerated=s["tolerated"],sage_numerator=s["sage"],sage_denominator=s["coexist_kyoku"],reach_tsumogiri_excluded=s["reach_tsumogiri_excluded"],sage_rate=rates(s["sage"],s["coexist_kyoku"]))
    prs=[];combined=defaultdict(Counter)
    for (p,scope,season,stage),s in sorted(stats.items()):
        prs.append(dict(player_id=p,player_name=names[p],scope=scope,season_start_year=season,stage=stage,**metrics(s)))
        combined[(scope,season,stage)].update(s)
    totals=[dict(scope=k[0],season_start_year=k[1],stage=k[2],**metrics(v)) for k,v in sorted(combined.items())]
    overall=metrics(combined[("all_period","","")])
    if overall["sage_numerator"]>overall["tolerated"] or overall["tolerated"]>overall["coexist_kyoku"] or overall["coexist_kyoku"]!=len(rounds) or any(r["starts"]!=1 or r["starts"]+r["restarts"]!=r["ends"] for r in rounds):errors.append(dict(error="aggregate conservation"))
    emit(a.out,"coexistence_timeline.csv",timeline,["kyoku_id","player_id","event_id","transition"])
    emit(a.out,"coexistence_kyoku.csv",rounds,["kyoku_id","player_id"])
    emit(a.out,"all_ron_decisions.csv",decisions,["ron_event_id","reason"])
    emit(a.out,"tolerance_details.csv",[r for r in decisions if r["tolerated"]],["ron_event_id"])
    emit(a.out,"sage_qualified_and_excluded.csv",[r for r in decisions if r["tolerated"]],["ron_event_id","sage","reason"])
    emit(a.out,"metrics_by_player.csv",prs,["player_id","scope"])
    emit(a.out,"metrics_all_scopes.csv",totals,["scope"])
    emit(a.out,"discrepancies.csv",errors,["kyoku_id","event_id","error"])
    emit(a.out,"unresolved.csv",uncertain,["kyoku_id","player_id","event_id","reason"])
    (a.out/"real_examples.json").write_text(js(examples),encoding="utf-8")
    manifest=dict(scope="Stage 4B only",status="incomplete" if errors or uncertain else "computed",database=dbm,database_sha256=DB_SHA,approved_origin_count=len(origins),approved_change_count=len(changes),approved_link_count=len(links),candidate_player_rounds=len(candidates),candidate_rounds=len(byky),error_count=len(errors),unresolved_count=len(uncertain),counts=overall,notes=["ordinary ron state follows approved Stage 1 snapshot and action freshness; physical 13-effective-tile waiting state required","closed non-tenpai or unknown selection not inferred","results provisional when unresolved or errors exist"])
    (a.out/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(manifest,ensure_ascii=False),flush=True)
    if errors or uncertain:raise SystemExit(1)
if __name__=="__main__":main()
