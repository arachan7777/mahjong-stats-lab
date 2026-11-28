"""Stage 7 fixed-DB replay. Outputs are facts, not strategy labels."""
import argparse,csv,gzip,json,os,time,resource,traceback
from pathlib import Path
from collections import Counter,defaultdict
from dontsuka_v026_2a_audit import events
from dontsuka_v026_2b_replay import RELEASE,DB_SHA
from dontsuka_v026_extract import connect_readonly,verify_database,sha256_file
from dontsuka_v026_6 import rows,js,jsonout,checkzip,B_SHA
from dontsuka_v026_5b import verified,cov_rows,A_SHA
from dontsuka_v026_4b import STAGE3A_SHA,STAGE4A_SHA,STAGE2B_SHA
from dontsuka_v026_7_core import Inventory,History,Linker,hand_state,movement,disposition,require,normal

SIX_SHA="baf795d5eb101a868113745030ea2c857f37da58e225bbc1b2fd555b58cc90a2"
FOUR_B_SHA="bae9d9363246c7b77a809ad36538a5a6616a08fc8fbdd9badfb1503ec25c64d8"
BASE="draw_event_id event_order kyoku_id game_id game_date season_start_year stage player_id draw_tile rinshan is_dontsuka opponent_count pre_shanten pre_state pre_effective pre_reason after_draw_shanten after_draw_effective after_draw_reason after_draw_hand after_draw_melds".split()
LINK="discard_event_id discard_order discard_tile discard_tile_type tsumogiri discard_kind declaration accepted_before accepted_marker_before accepted_after target_reach_count post_shanten post_state post_effective post_reason shanten_delta movement movement_reason has_discard link_reason terminal_or_next_event_id terminal_or_next_order kan_event_id kan_kind kan_order".split()
PAIR="target_id is_opponent_dontsuka target_accepted_before target_reach_declaration_id genbutsu genbutsu_reason evidence_event_id evidence_order evidence_player_id".split()
FIELDS=BASE+LINK
def writer(f,fields):
    w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");w.writeheader();return w
def identity(r):return tuple(str(r[k]) for k in ("event_order","kyoku_id","game_id","game_date","season_start_year","stage","player_id"))
def origin_key(r):return int(r["draw_event_id"]),int(r["target"])
def approved(z,n):return list(rows(z,n))
def pct(n,d):return "" if not d else f"{100*n/d:.9f}"
def main():
    p=argparse.ArgumentParser()
    for n in ("db","stage2b","stage3a","stage4a","stage4b","stage5a","stage5b","stage6","out"):p.add_argument(n,type=Path)
    p.add_argument("--shard",type=int,default=0);p.add_argument("--shards",type=int,default=1);p.add_argument("--limit-rounds",type=int,default=0)
    a=p.parse_args();start=time.monotonic();a.out.mkdir(parents=True,exist_ok=True)
    c=connect_readonly(a.db);verify_database(c,RELEASE);require(sha256_file(a.db)==DB_SHA,"DB digest")
    z2,_=verified(a.stage2b,STAGE2B_SHA);z3,_=verified(a.stage3a,STAGE3A_SHA)
    z4,m4=checkzip(a.stage4a,STAGE4A_SHA,"manifest.json","outputs")
    z4b,m4b=checkzip(a.stage4b,FOUR_B_SHA,"manifest.json","outputs")
    za,ma=checkzip(a.stage5a,A_SHA,"manifest.json","outputs")
    zb,mb=checkzip(a.stage5b,B_SHA,"package_sha256.json")
    z6,m6=checkzip(a.stage6,SIX_SHA,"package_sha256.json")
    require(all(m["database_sha256"]==DB_SHA for m in (m4,m4b,ma)),"approved DB")
    b=json.loads(zb.read("final/manifest.json"));s6=json.loads(z6.read("final/summary.json"))["counts"]
    require(b["database_sha256"]==DB_SHA and b["stage5a_sha256"]==A_SHA,"B DB")
    require(tuple(ma["overall"][k] for k in ("tenpai_draws","tenpai_dontsuka","shoubute_draws","shoubute_dontsuka"))==(161790,5696,97757,3449),"5A counts")
    require(tuple(b["counts"][k] for k in ("draws","basic","excluded","isshanten","isshanten_dontsuka","shoubute","shoubute_dontsuka"))==(1257732,27578,133,299220,8956,231765,7077),"5B counts")
    require(tuple(s6[k] for k in ("pairs","pair_dontsuka","unknown_pairs","unknown_pair_dontsuka"))==(109273,5785,152,1),"6 counts")
    orig=approved(z3,"opponent_hypothetical_all.csv");origins=defaultdict(dict)
    require((len(orig),sum(float(r["rank_drop"])>0 for r in orig),sum(float(r["rank_drop"])==0 for r in orig))==(28060,13170,14890),"3A counts")
    for r in orig:
        eid,t=origin_key(r);require(t not in origins[eid],"duplicate origin");origins[eid][t]=r
    require(len(origins)==27578,"basic origins")
    keys={(e,t) for e,ts in origins.items() for t in ts}
    ints=approved(z4,"tile_possession_intervals.csv")
    require(len(ints)==len(keys) and {origin_key(r) for r in ints}==keys,"4A interval keys")
    links=approved(z4,"origin_ron_links.csv");immediate=defaultdict(list)
    for r in links:
        require(origin_key(r) in keys,"4A link key")
        if r["relation"]=="immediate":immediate[int(r["draw_event_id"])].append(r)
    ronrows=approved(z4,"actual_ron_classification.csv");ron_by_round=defaultdict(list);ron_by_id={}
    for r in ronrows:
        eid=int(r["ron_event_id"]);require(eid not in ron_by_id,"4A ron duplicate");ron_by_id[eid]=r;ron_by_round[int(r["kyoku_id"])].append(r)
    require(len(ron_by_id)==11031,"4A ron total")
    decisions=approved(z4b,"all_ron_decisions.csv");decision_by_source={}
    for r in decisions:
        rr=ron_by_id[int(r["ron_event_id"])]
        require(all(rr[k]==r[k] for k in ("source_event_id","source_kind","player_id","kyoku_id","tile","tsumogiri")),"4A/B ron attributes")
        decision_by_source[int(r["source_event_id"])]=r
    exclusions={int(r["draw_event_id"]):r for r in approved(za,"unresolved_and_discrepancies.csv")}
    require(len(exclusions)==133 and len({r["kyoku_id"] for r in exclusions.values()})==11 and sum(int(r["is_dontsuka"]) for r in exclusions.values())==1,"5A exclusions")
    meta={int(r[0]):dict(game_id=int(r[1]),game_date=r[2],season_start_year=int(r[3]),stage=r[4]) for r in c.execute("SELECT k.id,g.id,g.date,ls.start_year,ss.stage FROM kyoku k JOIN game g ON g.id=k.game_id JOIN season_stage ss ON ss.id=g.season_stage_id JOIN league_season ls ON ls.id=ss.league_season_id")}
    names={int(r[0]):r[1] for r in c.execute("SELECT id,name FROM player")}
    require((len(meta),len({m["game_id"] for m in meta.values()}),len(names))==(25238,2068,56),"scope")
    kys=sorted(meta)[a.shard::a.shards]
    if a.limit_rounds:kys=kys[:a.limit_rounds]
    selected=set(kys);expected={};counts=Counter()
    for r in cov_rows(za):
        if int(r["kyoku_id"]) in selected:
            eid=int(r["draw_event_id"]);require(eid not in expected,"5A duplicate");expected[eid]=r
    for label,z,members in (("5B",zb,[n for n in zb.namelist() if n.startswith("corrected/") and n.endswith("/coverage.csv.gz")]),("6",z6,["final/all_draw_coverage.csv.gz"])):
        seen=set()
        for n in members:
            for r in rows(z,n):
                if int(r["kyoku_id"]) not in selected:continue
                eid=int(r["draw_event_id"]);require(eid not in seen and eid in expected,label+" ID");seen.add(eid);ar=expected[eid]
                require(identity(r)==identity(ar) and all(r[k]==ar[k] for k in ("physical_shanten","is_dontsuka")),label+" attribute")
                if label=="6":
                    st=ar["state"];st="unknown" if eid in exclusions else "not_tenpai" if st=="structural_tenpai_no_physical_wait" else st
                    require(r["self_state"]==st,"6 state")
        require(seen==set(expected),label+" coverage")
    dbids={int(r[0]) for r in c.execute("SELECT d.event_id,e.kyoku_id FROM draw_event d JOIN event e ON e.id=d.event_id") if int(r[1]) in selected}
    require(dbids==set(expected),"DB ID coverage")
    ids2=set()
    for r in rows(z2,"draw_snapshots.csv.gz"):
        eid=int(r["event_id"])
        if eid in expected:require(eid not in ids2,"2B duplicate");ids2.add(eid)
    require(ids2==set(expected),"2B ID coverage")
    s6keys=set()
    for r in rows(z6,"final/all_comparison_details.csv.gz"):
        eid,t=int(r["draw_event_id"]),int(r["target_id"])
        if int(r["kyoku_id"]) not in selected:continue
        require(eid in expected and (eid,t) not in s6keys,"6 pair identity");s6keys.add((eid,t))
        require(int(r["is_dontsuka"])==int(t in origins.get(eid,{})),"6 opponent hit identity")
        counts.update(stage6_comparison=1,stage6_valid=int(r["applicable"]),stage6_valid_hit=int(r["applicable"])*int(r["is_dontsuka"]))
    del s6keys
    seen=set();seen_pairs=set();seen_discards=set();examples={};processing=time.monotonic()
    with gzip.open(a.out/"draws.csv.gz","wt",encoding="utf-8",newline="") as f,gzip.open(a.out/"opponents.csv.gz","wt",encoding="utf-8",newline="") as g,gzip.open(a.out/"ron_audit.csv.gz","wt",encoding="utf-8",newline="") as h:
        dw=writer(f,FIELDS);pw=writer(g,FIELDS+PAIR);rw=writer(h,"ron_event_id kyoku_id player_id source_event_id source_kind tsumogiri declaration accepted_before linked_draw_id category immediate_origin_rows".split())
        for ky in kys:
            rp=Inventory();hist=History();linker=Linker();pending={};discard_map={};sources={}
            flags={int(r[0]):int(r[1]) for r in c.execute("SELECT d.event_id,d.is_tsumogiri FROM discard_event d JOIN event e ON e.id=d.event_id WHERE e.kyoku_id=?",(ky,))}
            for e in events(c,ky):
                eid,p,k=e["id"],e.get("actor"),e["type"]
                resolved=linker.feed(e)
                if k=="draw":
                    require(eid in expected and eid not in seen,"draw ID");seen.add(eid);ar=expected[eid];hit=origins.get(eid,{})
                    pre=hand_state(rp,p,13)
                    require((pre["state"]=="unknown")== (eid in exclusions),"foul identity")
                    require((str(pre["shanten"])==ar["physical_shanten"]),"5A shanten")
                    st=ar["state"];st="unknown" if eid in exclusions else "not_tenpai" if st=="structural_tenpai_no_physical_wait" else st
                    require(pre["state"]==st,"5A state")
                    r=dict(draw_event_id=eid,event_order=e["event_order"],kyoku_id=ky,**meta[ky],player_id=p,draw_tile=e["tile"],rinshan=int(bool(e["rinshan"])),is_dontsuka=int(bool(hit)),opponent_count=len(hit),pre_shanten=pre["shanten"],pre_state=st,pre_effective=pre["effective"],pre_reason=pre["reason"])
                    require(identity(r)==identity(ar) and r["is_dontsuka"]==int(ar["is_dontsuka"]),"draw identity")
                    for t,o in hit.items():require(int(o["drawer"])==p and int(o["event_order"])==e["event_order"] and o["tile"]==e["tile"],"origin attributes")
                    pending[eid]=(r,pre)
                if k in ("ankan","shominkan","daiminkan"):
                    if linker.kan_pending:
                        rr,_=pending[linker.kan_pending["id"]];rr.update(kan_event_id=eid,kan_kind=k,kan_order=e["event_order"])
                    sources[eid]=dict(player_id=p,kind=k,tile=e["tile"],tsumogiri=0,declaration=0,accepted_before=int(p in hist.established))
                facts={}
                if k=="discard":
                    tsum=flags[eid];accepted=p in hist.established
                    sources[eid]=dict(player_id=p,kind=k,tile=e["tile"],tsumogiri=tsum,declaration=int(bool(e["declaration"])),accepted_before=int(accepted),accepted_marker_before=int(p in rp.reaches))
                    for old,reason,_ in resolved:
                        if reason!="discard":continue
                        oldid=old["id"];rr,_=pending[oldid]
                        require(oldid!=eid and old["event_order"]<e["event_order"] and old["actor"]==p and eid not in seen_discards,"discard link identity")
                        seen_discards.add(eid);discard_map[eid]=oldid
                        if tsum:require(old["tile"]==e["tile"],"4A tsumogiri physical draw")
                        if accepted:require(tsum,"accepted riichi non-tsumogiri")
                        rr.update(discard_event_id=eid,discard_order=e["event_order"],discard_tile=e["tile"],discard_tile_type=normal(e["tile"]),tsumogiri=tsum,discard_kind=disposition(e,tsum,accepted),declaration=int(bool(e["declaration"])),accepted_before=int(accepted),accepted_marker_before=int(p in rp.reaches),target_reach_count=sum(t in hist.established for t in origins.get(oldid,{})),has_discard=1,link_reason="discard")
                        facts[oldid]={}
                        for t in origins.get(oldid,{}):
                            gen,why,ev_id,order,actor=hist.genbutsu(t,e)
                            if gen:require(order<e["event_order"],"future evidence")
                            reach=hist.established.get(t)
                            facts[oldid][t]=dict(target_id=t,is_opponent_dontsuka=1,target_accepted_before=int(bool(reach)),target_reach_declaration_id=reach[1] if reach else "",genbutsu=gen,genbutsu_reason=why,evidence_event_id=ev_id,evidence_order=order,evidence_player_id=actor)
                if k not in ("ron","tsumo","ryukyoku"):rp.step(e);hist.record(e)
                if k=="draw":
                    rr,_=pending[eid];post=hand_state(rp,p,14)
                    rr.update(after_draw_shanten=post["shanten"],after_draw_effective=post["effective"],after_draw_reason=post["reason"],after_draw_hand=js(rp.hands[p]),after_draw_melds=js(rp.melds[p]))
                for old,reason,end in resolved:
                    oldid=old["id"];r,pre=pending.pop(oldid);hit=origins.get(oldid,{})
                    if reason=="discard":
                        post=hand_state(rp,p,13);delta,mv,why=movement(pre,post)
                        r.update(post_shanten=post["shanten"],post_state=post["state"],post_effective=post["effective"],post_reason=post["reason"],shanten_delta=delta,movement=mv,movement_reason=why,accepted_after=int(p in hist.established))
                        for t,x in facts[oldid].items():
                            require((oldid,t) not in seen_pairs,"pair duplicate");seen_pairs.add((oldid,t));pw.writerow(dict(r,**x));counts["gen_"+str(x["genbutsu"])]+=1
                    else:
                        r.update(has_discard=0,link_reason=reason,terminal_or_next_event_id=end["id"],terminal_or_next_order=end["event_order"],movement="no_discard",movement_reason=reason)
                        for t in hit:
                            require((oldid,t) not in seen_pairs,"pair duplicate");seen_pairs.add((oldid,t));pw.writerow(dict(r,target_id=t,is_opponent_dontsuka=1,genbutsu_reason="no_corresponding_discard"));counts["gen_no_discard"]+=1
                    for x in immediate.get(oldid,[]):
                        actual=ron_by_id[int(x["ron_event_id"])]
                        require(reason=="discard" and int(actual["source_event_id"])==r["discard_event_id"] and r["tsumogiri"]==1,"4A immediate origin link")
                        if int(x["same_target"]):require(facts[oldid][int(x["target"])]["genbutsu"]==0,"actual target ron cannot be genbutsu")
                        counts["4a_immediate_links"]+=1
                    dd=r["is_dontsuka"];counts.update(draws=1,basic=dd,opponents=len(hit),pre_unknown=r["pre_state"]=="unknown",tenpai=r["pre_state"] in ("riichi","damaten","open"),tenpai_dontsuka=dd*(r["pre_state"] in ("riichi","damaten","open")),isshanten=r["pre_shanten"]==1,isshanten_dontsuka=dd*(r["pre_shanten"]==1))
                    counts["link_"+reason]+=1;counts["movement_"+r["movement"]]+=1
                    if dd:
                        examples.setdefault("movement_"+r["movement"],r.copy());examples.setdefault("link_"+reason,r.copy())
                        if reason=="discard":examples.setdefault("discard_"+r["discard_kind"],r.copy())
                    if r["pre_reason"] or r.get("post_reason"):examples.setdefault("special_"+(r["pre_reason"] or r["post_reason"]),r.copy())
                    dw.writerow(r)
                if k=="ron":
                    rr=ron_by_id[eid];src=sources[int(rr["source_event_id"])]
                    require((str(src["player_id"]),src["kind"],src["tile"],str(src["tsumogiri"]))==(rr["player_id"],rr["source_kind"],rr["tile"],rr["tsumogiri"]),"4A source")
                    sourceid=int(rr["source_event_id"]);dec=decision_by_source.get(sourceid)
                    if dec and src["kind"]=="discard":require(str(src["accepted_marker_before"])==dec["accepted_before"] and str(src["declaration"])==dec["declaration"],"4B discard flags")
                    if rr["category"]=="immediate":require(discard_map.get(sourceid) in immediate,"4A immediate draw")
                    rw.writerow(dict(rr,**{k:src[k] for k in ("declaration","accepted_before")},linked_draw_id=discard_map.get(sourceid,""),immediate_origin_rows=len(immediate.get(discard_map.get(sourceid),[]))))
                    counts["4a_ron"]+=1
            linker.finish();require(not pending,"pending data")
        require(seen==set(expected),"draw coverage")
        require(seen_pairs=={(e,t) for e in expected for t in origins.get(e,{})},"pair key coverage")
    jsonout(a.out/"examples.json",examples);jsonout(a.out/"names.json",names)
    jsonout(a.out/"summary.json",dict(shard=a.shard,shards=a.shards,limited=bool(a.limit_rounds),kyoku_ids=kys,counts=dict(counts),database_sha256=DB_SHA,elapsed_seconds=time.monotonic()-start,processing_seconds=time.monotonic()-processing,peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,run_id=os.getenv("GITHUB_RUN_ID"),commit=os.getenv("GITHUB_SHA")))
    print(js(dict(counts)),flush=True)
if __name__=="__main__":main()
