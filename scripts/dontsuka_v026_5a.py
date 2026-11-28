"""Stage 5A only. Replay each draw BEFORE applying its actual tile."""
import argparse,csv,gzip,io,json,os,traceback
from collections import Counter,defaultdict
from pathlib import Path
from dontsuka_v026_2a_audit import events
from dontsuka_v026_2a_replay import Replay
from dontsuka_v026_5a_core import evaluate_waits,sh,vector,candidates
from dontsuka_v026_extract import connect_readonly,verify_database,sha256_file
from dontsuka_v026_2b_replay import RELEASE,DB_SHA
from dontsuka_v026_3b import verified_zip,read_csv_zip,write_csv,rates,dimension_keys
from dontsuka_v026_4b import scoremap,STAGE2A_SHA,STAGE2B_SHA,STAGE3A_SHA,STAGE3B_SHA,STAGE4A_SHA
STAGE4B_SHA="bae9d9363246c7b77a809ad36538a5a6616a08fc8fbdd9badfb1503ec25c64d8"
def js(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"))
def emit(out,name,rows,fields):
    write_csv(out/name,rows,list(dict.fromkeys(fields+[k for r in rows for k in r])))
def main():
    ap=argparse.ArgumentParser()
    for n in ("db","stage2a","stage2b","stage3a","stage3b","stage4a","stage4b","out"):ap.add_argument(n,type=Path)
    a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    c=connect_readonly(a.db);dbm=verify_database(c,RELEASE)
    if sha256_file(a.db)!=DB_SHA:raise ValueError("DB identity")
    zs={}
    for n,digest in (("stage2a",STAGE2A_SHA),("stage2b",STAGE2B_SHA),("stage3a",STAGE3A_SHA),("stage3b",STAGE3B_SHA),("stage4a",STAGE4A_SHA),("stage4b",STAGE4B_SHA)):
        z,m=verified_zip(getattr(a,n),digest)
        if m["database_sha256"]!=DB_SHA:raise ValueError(n+" DB identity")
        zs[n]=z
    z2,z3,z4,z4b=(zs[x] for x in ("stage2b","stage3a","stage4a","stage4b"))
    orig=read_csv_zip(z3,"opponent_hypothetical_all.csv")
    origins=defaultdict(list)
    for r in orig:origins[int(r["draw_event_id"])].append(r)
    if (len(orig),len(origins),len({(r["draw_event_id"],r["target"]) for r in orig}),sum(float(r["rank_drop"])>0 for r in orig),sum(float(r["rank_drop"])==0 for r in orig))!=(28060,27578,28060,13170,14890):raise ValueError("approved origins")
    old=read_csv_zip(z4,"dontsuka_kyoku_classification.csv")
    oldmap={(int(r["kyoku_id"]),int(r["player_id"])):r for r in old}
    if len(oldmap)!=len(old) or len(old)!=23535:raise ValueError("approved 4A player-rounds")
    coexist=read_csv_zip(z4b,"coexistence_kyoku.csv")
    if (len(coexist),sum(int(r["tolerated"]) for r in coexist),sum(int(r["sage"]) for r in coexist),sum(int(r["reach_tsumogiri_excluded"]) for r in coexist))!=(340,29,14,15):raise ValueError("approved 4B counts")
    end={int(r["kyoku_id"]):r for r in read_csv_zip(z2,"kyoku_comparison.csv")}
    if len(end)!=25238 or any(r["match"] not in ("1","True","true") or r["error"] for r in end.values()):raise ValueError("approved 2B end scores")
    actual=defaultdict(list)
    for r in read_csv_zip(z4,"actual_ron_classification.csv"):
        actual[(int(r["kyoku_id"]),int(r["player_id"]))].append(r)
    links=defaultdict(list)
    for r in read_csv_zip(z4,"origin_ron_links.csv"):links[int(r["draw_event_id"])].append(r)
    winners=defaultdict(set)
    for ky,p in c.execute("SELECT e.kyoku_id,a.actor_player_id FROM agari_event a JOIN event e ON e.id=a.event_id WHERE e.type IN ('ron','tsumo')"):winners[ky].add(p)
    meta={int(r[0]):dict(game_id=int(r[1]),game_date=r[2],season_start_year=int(r[3]),stage=r[4]) for r in c.execute("""SELECT k.id,g.id,g.date,ls.start_year,ss.stage FROM kyoku k JOIN game g ON g.id=k.game_id JOIN season_stage ss ON ss.id=g.season_stage_id JOIN league_season ls ON ls.id=ss.league_season_id""")}
    names={int(r[0]):r[1] for r in c.execute("SELECT id,name FROM player")}
    if (len(meta),len({m["game_id"] for m in meta.values()}),len(names))!=(25238,2068,56):raise ValueError("approved scope")
    ids=set()
    with z2.open("draw_snapshots.csv.gz") as f,gzip.GzipFile(fileobj=f) as g,io.TextIOWrapper(g,encoding="utf-8") as t:
        for r in csv.DictReader(t):
            eid=int(r["event_id"])
            if eid in ids:raise ValueError("duplicate snapshot")
            ids.add(eid)
    if len(ids)!=1257732 or ids!={r[0] for r in c.execute("SELECT event_id FROM draw_event")}:raise ValueError("approved draw IDs")
    stats=defaultdict(Counter);examples={};errors=[];rounds={};seen=set();seen_orig=set();seen_base=set();counts=Counter()
    for p,s,t in c.execute("""SELECT DISTINCT gr.player_id,ls.start_year,ss.stage FROM game_player_result gr JOIN game g ON g.id=gr.game_id JOIN season_stage ss ON ss.id=g.season_stage_id JOIN league_season ls ON ls.id=ss.league_season_id"""):
        for key in dimension_keys(dict(season_start_year=s,stage=t)):stats[(p,*key)]
    def add(p,md,**values):
        for key in dimension_keys(md):stats[(p,*key)].update(values)
    fields=["draw_event_id","event_order","kyoku_id","game_id","game_date","season_start_year","stage","player_id","state","recorded_shanten","physical_shanten","state_event_id","furiten","status","is_dontsuka","is_shoubute","concealed_before","melds","omote","wait_candidates","patterns","error"]
    with gzip.open(a.out/"all_draw_coverage.csv.gz","wt",encoding="utf-8",newline="") as af,gzip.open(a.out/"tenpai_draw_details.csv.gz","wt",encoding="utf-8",newline="") as tf,(a.out/"shoubute_dontsuka.csv").open("w",encoding="utf-8-sig",newline="") as df,(a.out/"shoubute_opponent_details.csv").open("w",encoding="utf-8-sig",newline="") as of:
        aw=csv.DictWriter(af,fieldnames=fields[:16],extrasaction="ignore");tw=csv.DictWriter(tf,fieldnames=fields,extrasaction="ignore");dw=csv.DictWriter(df,fieldnames=fields+["opponents","actual_ron_links"],extrasaction="ignore")
        ow=csv.DictWriter(of,fieldnames=list(orig[0]),extrasaction="ignore")
        for w in (aw,tw,dw,ow):w.writeheader()
        for i,(ky,md) in enumerate(sorted(meta.items()),1):
            rp=Replay();ps={};ts={};actions=defaultdict(list);snaps=defaultdict(list);ev=None
            winds={r[0]:r[1] for r in c.execute("SELECT player_id,player_wind FROM kyoku_player_result WHERE kyoku_id=?",(ky,))}
            rw=c.execute("SELECT round FROM kyoku WHERE id=?",(ky,)).fetchone()[0][:2]
            for r in c.execute("SELECT ps.*,e.event_order FROM player_state ps JOIN event e ON e.id=ps.event_id WHERE e.kyoku_id=?",(ky,)):actions[r["event_id"]].append(dict(r))
            for r in c.execute("SELECT ps.*,e.event_order FROM player_tenpai_state ps JOIN event e ON e.id=ps.event_id WHERE e.kyoku_id=?",(ky,)):snaps[r["event_id"]].append(dict(r))
            try:
                for ev in events(c,ky):
                    eid=ev["id"];p=ev.get("actor")
                    if ev["type"]=="draw":
                        if eid in seen or eid not in ids:raise ValueError("draw identity")
                        seen.add(eid);rows=origins.get(eid,[])
                        if rows:
                            seen_orig.update((eid,int(r["target"])) for r in rows);seen_base.add((ky,p))
                            if any(int(r["drawer"])!=p or int(r["kyoku_id"])!=ky or int(r["event_order"])!=ev["event_order"] or r["tile"]!=ev["tile"] for r in rows):raise ValueError("origin metadata")
                        state=ps.get(p);snap=ts.get(p);h=rp.hands[p];m=rp.melds[p]
                        r=dict(draw_event_id=eid,event_order=ev["event_order"],kyoku_id=ky,**md,player_id=p,is_dontsuka=int(bool(rows)),status="evaluated",is_shoubute=0,recorded_shanten=state["shanten_count"] if state else None,state_event_id=state["event_id"] if state else None)
                        try:
                            if len(h)+3*len(m)!=13:raise ValueError("pre-draw effective tiles")
                            q=sh(vector(h));r["physical_shanten"]=q
                            if q<0:raise ValueError("winning shape before draw")
                            if q==0 and candidates(h,m):
                                reached=p in rp.reaches
                                typ="riichi" if reached else "open" if any(k!="ankan" for k,b in m) else "damaten"
                                r.update(state=typ,concealed_before=js(h),melds=js(m),omote=js(rp.omote))
                                if not state or not snap or snap["event_order"]<state["event_order"] or snap["is_furiten"] is None:raise ValueError("missing current tenpai/furiten evidence")
                                if state["shanten_count"]!=0:raise ValueError("physical/recorded tenpai disagreement")
                                furiten=bool(snap["is_furiten"]);r["furiten"]=int(furiten)
                                waits,patterns,ok=evaluate_waits(h,m,winds[p],rw,rp.omote,reached,reached and rp.declarations.get(p,False),furiten)
                                r.update(wait_candidates=js(waits),patterns=js(patterns),is_shoubute=int(ok))
                                if not patterns:raise ValueError("no wait patterns")
                                counts["tenpai"]+=1;counts["tenpai_dontsuka"]+=bool(rows)
                                add(p,md,tenpai_draws=1,tenpai_dontsuka=int(bool(rows)))
                                tw.writerow(r)
                                for pat in patterns:
                                    if pat["status"]!="evaluated":continue
                                    for label,cond in [("kiriage_3_60",(pat["han"],pat["fu"])==(3,60)),("four_20",(pat["han"],pat["fu"])==(4,20)),("virtual_riichi",pat["virtual_riichi"]),("double_riichi",pat["flags"]["is_daburu_riichi"]),("tsumo_yaku","門前清自摸和" in pat["yaku"]),("red","赤ドラ" in pat["yaku"]),("kan_dora",len(rp.omote)>1),("yakuman",pat["yakuman"]),("chiitoitsu","七対子" in pat["yaku"]),("sanshoku","三色同順" in pat["yaku"]),("open",typ=="open"),("furiten",furiten)]:
                                        if cond and label not in examples:examples[label]=dict(r,example_pattern=pat)
                                if not rows and ok:examples.setdefault("non_dontsuka_denominator",r.copy())
                                if ok:
                                    counts["shoubute_draws"]+=1;counts["shoubute_dontsuka"]+=bool(rows)
                                    add(p,md,shoubute_draws=1,shoubute_dontsuka=int(bool(rows)),**{typ+"_shoubute_draws":1,typ+"_shoubute_dontsuka":int(bool(rows))})
                                    if rows:
                                        dw.writerow(dict(r,opponents=js([int(x["target"]) for x in rows]),actual_ron_links=js(links[eid])))
                                        for x in rows:ow.writerow(x)
                                        k=(ky,p);rounds.setdefault(k,dict(kyoku_id=ky,player_id=p,**md,draw_event_ids=[],types=set()))
                                        rounds[k]["draw_event_ids"].append(eid);rounds[k]["types"].add(typ)
                                        if len(rows)>1:examples.setdefault("multiple_opponents",r.copy())
                            else:
                                r["state"]="not_tenpai"
                                if state and state["shanten_count"]==0:raise ValueError("recorded/physical non-tenpai disagreement")
                        except Exception as ex:
                            r.update(status="unresolved",is_shoubute="",error=repr(ex),concealed_before=js(h),melds=js(m),omote=js(rp.omote))
                            errors.append(r.copy())
                        aw.writerow(r);counts["all_draws"]+=1;counts["basic_dontsuka"]+=bool(rows)
                    if ev["type"] not in ("ron","tsumo","ryukyoku"):rp.step(ev)
                    for x in actions[eid]:ps[x["player_id"]]=x
                    for x in snaps[eid]:ts[x["player_id"]]=x
            except Exception as ex:
                errors.append(dict(kyoku_id=ky,draw_event_id=ev["id"] if ev else "",status="replay_error",error=repr(ex),traceback=traceback.format_exc()))
            if i%1000==0:print("rounds",i,"counts",dict(counts),"errors",len(errors),flush=True)
    if seen!=ids or seen_orig!={(int(r["draw_event_id"]),int(r["target"])) for r in orig} or seen_base!=set(oldmap):errors.append(dict(status="coverage_error",error="approved identity sets disagree"))
    roundrows=[]
    for (ky,p),r in sorted(rounds.items()):
        e=end[ky];delta=scoremap(e["recorded_end_scores"])[p]-scoremap(e["start_scores"])[p]
        won=int(p in winners[ky]);ron=int(bool(actual[(ky,p)]));cat=oldmap[(ky,p)]["category"]
        r.update(draw_count=len(r["draw_event_ids"]),draw_event_ids=js(r["draw_event_ids"]),types=js(sorted(r["types"])),actual_ron=ron,approved_ron_classification=cat,actual_ron_event_ids=js([x["ron_event_id"] for x in actual[(ky,p)]]),self_win=won,kyoku_net=delta)
        roundrows.append(r);add(p,r,shoubute_dontsuka_kyoku=1,self_wins=won,actual_ron_kyoku=ron,kyoku_net_sum=delta,**{"ron_category_"+cat:1})
    fields2=["tenpai_draws","tenpai_dontsuka","shoubute_draws","shoubute_dontsuka","riichi_shoubute_draws","riichi_shoubute_dontsuka","damaten_shoubute_draws","damaten_shoubute_dontsuka","open_shoubute_draws","open_shoubute_dontsuka","shoubute_dontsuka_kyoku","self_wins","actual_ron_kyoku","kyoku_net_sum","ron_category_immediate","ron_category_subsequent","ron_category_different_tile","ron_category_no_ron","ron_category_special_excluded"]
    def metrics(s):
        d={k:s[k] for k in fields2}
        d.update(shoubute_dontsuka_rate=rates(s["shoubute_dontsuka"],s["shoubute_draws"]),fulfillment_rate=rates(s["self_wins"],s["shoubute_dontsuka_kyoku"]),mean_kyoku_net="" if not s["shoubute_dontsuka_kyoku"] else f'{s["kyoku_net_sum"]/s["shoubute_dontsuka_kyoku"]:.9f}')
        return d
    combined=defaultdict(Counter);prs=[]
    for (p,*key),s in sorted(stats.items()):
        prs.append(dict(player_id=p,player_name=names[p],scope=key[0],season_start_year=key[1],stage=key[2],**metrics(s)))
        combined[tuple(key)].update(s)
    totals=[dict(scope=k[0],season_start_year=k[1],stage=k[2],**metrics(s)) for k,s in sorted(combined.items())]
    overall=metrics(combined[("all_period","","")])
    if overall["shoubute_dontsuka_kyoku"]!=len(roundrows) or overall["shoubute_dontsuka"]!=sum(r["draw_count"] for r in roundrows) or overall["shoubute_dontsuka"]>overall["shoubute_draws"]:errors.append(dict(status="aggregate_error",error="round reconciliation"))
    emit(a.out,"shoubute_dontsuka_kyoku.csv",roundrows,["kyoku_id","player_id"])
    emit(a.out,"metrics_by_player.csv",prs,["player_id","scope"])
    emit(a.out,"metrics_all_scopes.csv",totals,["scope"])
    emit(a.out,"unresolved_and_discrepancies.csv",errors,["draw_event_id","kyoku_id","status","error"])
    (a.out/"real_examples.json").write_text(js(examples),encoding="utf-8")
    manifest=dict(scope="5A only",status="incomplete" if errors else "computed",database=dbm,database_sha256=DB_SHA,approved_input_hashes={n:sha256_file(getattr(a,n)) for n in zs},counts=dict(counts),overall=overall,errors=len(errors),draw_identity_match=seen==ids,example_types=sorted(examples),notes=["No live-wall availability threshold: candidate variants constrained only by own physical tile inventory.","Furiten ron patterns retained but marked ineligible; tsumo is evaluated independently.","Outcome is measured once per affected player-round; existing 4A classification is attached as player-round classification, not newly attributed to every qualifying draw.","No causal claim or new event-level fulfillment denominator."])
    (a.out/"manifest.json").write_text(js(manifest),encoding="utf-8")
    print(js(manifest),flush=True)
    if errors:raise SystemExit(1)
if __name__=="__main__":main()
