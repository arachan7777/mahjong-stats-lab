"""Stage 8: fixed-release shard replay and joins. No Stage 9 calculations."""
import argparse, gzip, json, time, resource, os
from pathlib import Path
from collections import defaultdict, Counter
from dontsuka_v026_8_core import RoundTracker, TENPAI, require
from dontsuka_v026_2a_audit import events
from dontsuka_v026_2b_replay import RELEASE, DB_SHA
from dontsuka_v026_extract import connect_readonly, verify_database, sha256_file
from dontsuka_v026_5b import cov_rows, A_SHA
from dontsuka_v026_6 import rows, checkzip, B_SHA, jsonout, js
from dontsuka_v026_7 import SIX_SHA, FOUR_B_SHA, identity
from dontsuka_v026_4b import STAGE2B_SHA, STAGE3A_SHA, STAGE4A_SHA, scoremap

SEVEN_SHA = "dc307f93e46ddd6eaf15d0cfcc37d3ae0417963d0f2ceb8541e02c6648f43143"
INPUTS = dict(stage2b=STAGE2B_SHA, stage3a=STAGE3A_SHA, stage4a=STAGE4A_SHA,
              stage4b=FOUR_B_SHA, stage5a=A_SHA, stage5b=B_SHA, stage6=SIX_SHA, stage7=SEVEN_SHA)

def emit(f, r):
    f.write(js(r)+"\n")
def keyed(rs, key):
    out = {}
    for r in rs:
        k=key(r); require(k not in out, "duplicate key "+str(k)); out[k]=r
    return out
def eid(r):return int(r["draw_event_id"])
def pairkey(r):return eid(r), int(r["target_id"])
def origin_key(r):return eid(r), int(r["target"])
def roundkey(r):return int(r["kyoku_id"]), int(r["player_id"])
def conditions(r):
    out=[]
    if r["combination"]:
        out.extend((r["relation"],r["combination"]))
    if r["self_first_reach"] and r["self_info"]["state"]=="riichi":
        # The original explicitly fixes pair units, but not whether every
        # opponent or only waiting opponents enter the general first-reach
        # exposure. Preserve both candidate denominators without certifying either.
        out.append("first_reach_all_opponents_candidate")
        if r["target_info"]["state"] in TENPAI:
            out.append("first_reach_tenpai_opponents_candidate")
        if r["first_reach_class"] in ("chase_riichi","prior_damaten","prior_open","later_damaten","later_open"):
            out.append(r["first_reach_class"])
    return out
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("db",type=Path)
    for n in INPUTS:ap.add_argument(n,type=Path)
    ap.add_argument("out",type=Path);ap.add_argument("--shard",type=int,default=0)
    ap.add_argument("--shards",type=int,default=1);ap.add_argument("--limit-rounds",type=int,default=0)
    a=ap.parse_args();start=time.monotonic();a.out.mkdir(parents=True,exist_ok=True)
    require(0<=a.shard<a.shards,"shard index")
    c=connect_readonly(a.db);verify_database(c,RELEASE);require(sha256_file(a.db)==DB_SHA,"DB hash")
    zs={}
    for n,digest in INPUTS.items():
        if n in ("stage5b","stage6","stage7"):
            z,m=checkzip(getattr(a,n),digest,"package_sha256.json")
        else:
            z,m=checkzip(getattr(a,n),digest,"manifest.json","outputs")
            require(m["database_sha256"]==DB_SHA,n+" DB hash")
        zs[n]=z
    z2,z3,z4,z4b,za,zb,z6,z7=(zs[n] for n in INPUTS)
    meta={int(r[0]):dict(game_id=int(r[1]),game_date=r[2],season_start_year=int(r[3]),stage=r[4]) for r in c.execute("SELECT k.id,g.id,g.date,ls.start_year,ss.stage FROM kyoku k JOIN game g ON g.id=k.game_id JOIN season_stage ss ON ss.id=g.season_stage_id JOIN league_season ls ON ls.id=ss.league_season_id")}
    names={int(r[0]):r[1] for r in c.execute("SELECT id,name FROM player")}
    require((len(meta),len({x["game_id"] for x in meta.values()}),len(names))==(25238,2068,56),"scope")
    kys=sorted(meta)[a.shard::a.shards]
    if a.limit_rounds:kys=kys[:a.limit_rounds]
    selected=set(kys)
    def select(z,n):
        return (r for r in rows(z,n) if int(r["kyoku_id"]) in selected)
    expected=keyed((r for r in cov_rows(za) if int(r["kyoku_id"]) in selected),eid)
    expected7=keyed(select(z7,"final/all_draws.csv.gz"),eid)
    expected6=keyed(select(z6,"final/all_draw_coverage.csv.gz"),eid)
    wait6=keyed(select(z6,"final/all_comparison_details.csv.gz"),pairkey)
    bmembers=[n for n in zb.namelist() if n.startswith("corrected/") and n.endswith("/coverage.csv.gz")]
    require(bool(bmembers),"5B coverage files")
    expectedb=keyed((r for n in bmembers for r in select(zb,n)),eid)
    dbids={int(r[0]) for r in c.execute("SELECT d.event_id,e.kyoku_id FROM draw_event d JOIN event e ON e.id=d.event_id") if int(r[1]) in selected}
    ids2={int(r["event_id"]) for r in rows(z2,"draw_snapshots.csv.gz") if int(r["event_id"]) in dbids}
    require(set(expected)==set(expected7)==set(expected6)==set(expectedb)==dbids==ids2,"coverage ID sets")
    origins=defaultdict(dict);allorig=keyed(rows(z3,"opponent_hypothetical_all.csv"),origin_key)
    require((len(allorig),len({x[0] for x in allorig}),sum(float(r["rank_drop"])>0 for r in allorig.values()),sum(float(r["rank_drop"])==0 for r in allorig.values()))==(28060,27578,13170,14890),"3A totals")
    for (d,t),r in allorig.items():
        if d in dbids:origins[d][t]=r
    ints=keyed(rows(z4,"tile_possession_intervals.csv"),origin_key)
    require(set(ints)==set(allorig),"4A key set")
    for k,r in ints.items():require(all(r[f]==allorig[k][f] for f in ("kyoku_id","drawer","target","tile","rank_drop","event_order")),"4A origin attributes")
    links=defaultdict(list)
    for r in rows(z4,"origin_ron_links.csv"):
        k=origin_key(r);require(k in allorig,"4A origin links")
        if k[0] in dbids:links[k].append(r)
    ronall=keyed(rows(z4,"actual_ron_classification.csv"),lambda r:int(r["ron_event_id"]))
    require(len(ronall)==11031,"4A ron count")
    for r in rows(z4b,"all_ron_decisions.csv"):
        x=ronall[int(r["ron_event_id"])]
        require(all(x[k]==r[k] for k in ("source_event_id","source_kind","player_id","kyoku_id","tile","tsumogiri")),"4B actual identity")
    rons=defaultdict(list)
    for r in ronall.values():
        if int(r["kyoku_id"]) in selected:rons[roundkey(r)].append(r)
    oldround=keyed(select(z4,"dontsuka_kyoku_classification.csv"),roundkey)
    ends=keyed(select(z2,"kyoku_comparison.csv"),lambda r:int(r["kyoku_id"]))
    winners=defaultdict(set)
    for ky,p in c.execute("SELECT e.kyoku_id,a.actor_player_id FROM agari_event a JOIN event e ON e.id=a.event_id WHERE e.type IN ('ron','tsumo')"):
        if ky in selected:winners[ky].add(p)
    counts=Counter();seen=set();pairseen=set();originseen=set();examples={};processing=time.monotonic()
    with gzip.open(a.out/"draws.jsonl.gz","wt",encoding="utf-8") as df, gzip.open(a.out/"pairs.jsonl.gz","wt",encoding="utf-8") as pf, gzip.open(a.out/"intervals.jsonl.gz","wt",encoding="utf-8") as itf, gzip.open(a.out/"reaches.jsonl.gz","wt",encoding="utf-8") as rf:
        for ky in kys:
            tracker=RoundTracker(ky)
            end=ends[ky];require(end["match"] in ("1","True","true") and not end["error"],"2B round match")
            start_scores=scoremap(end["start_scores"]);end_scores=scoremap(end["recorded_end_scores"])
            for e in events(c,ky):
                d=e["id"];hit=origins.get(d,{})
                draw=tracker.feed(e,hit)
                if draw is None:continue
                require(d in expected and d not in seen,"draw ID");seen.add(d)
                ar,br,sr,vr=expected[d],expectedb[d],expected6[d],expected7[d]
                draw.update(meta[ky])
                require(all(identity(draw)==identity(r) for r in (ar,br,sr,vr)),"draw attributes")
                require(all(int(r["is_dontsuka"])==draw["is_dontsuka"] for r in (ar,br,sr,vr)),"basic flag")
                st=draw["self_info"]["state"];require(st==sr["self_state"]==vr["pre_state"],"6/7 state")
                require(ar["physical_shanten"]==br["physical_shanten"]==sr["physical_shanten"]==vr["pre_shanten"],"5/6/7 shanten")
                require(draw["draw_tile"]==vr["draw_tile"] and draw["rinshan"]==int(vr["rinshan"]) and draw["opponent_count"]==int(vr["opponent_count"]),"7 tile/rinshan/opponent count")
                draw.update(physical_shanten=ar["physical_shanten"],shoubute_tenpai=ar["is_shoubute"],shoubute_isshanten=br["is_shoubute"],pre_reason=vr["pre_reason"])
                counts.update(draws=1,basic=draw["is_dontsuka"],opponents=len(hit),rank_drop=sum(float(x["rank_drop"])>0 for x in hit.values()),rank_maintain=sum(float(x["rank_drop"])==0 for x in hit.values()))
                counts["state:"+st]+=1;counts["state_hit:"+st]+=draw["is_dontsuka"]
                if st in TENPAI:
                    counts["shoubute_tenpai"]+=int(ar["is_shoubute"]);counts["shoubute_tenpai_hit"]+=int(ar["is_shoubute"])*draw["is_dontsuka"]
                if ar["physical_shanten"]=="1":
                    counts["isshanten"]+=1;counts["isshanten_hit"]+=draw["is_dontsuka"];counts["shoubute_isshanten"]+=int(br["is_shoubute"]);counts["shoubute_isshanten_hit"]+=int(br["is_shoubute"])*draw["is_dontsuka"]
                player=draw["player_id"];actual=rons[ky,player]
                if hit:require((ky,player) in oldround,"4A round presence")
                for r in draw.pop("pairs"):
                    t=r["target_id"];k=(d,t);a0,b0=r["self_info"]["state"],r["target_info"]["state"]
                    w=wait6.get(k);candidate="not_tenpai" not in (a0,b0)
                    require(bool(w)==candidate,"6 comparison key mismatch")
                    if w:
                        require(k not in pairseen,"6 duplicate");pairseen.add(k)
                        require(w["self_state"]==a0 and w["target_state"]==b0 and int(w["is_dontsuka"])==r["is_opponent_dontsuka"],"6 pair attributes")
                        counts["stage6_pairs"]+=1;counts["stage6_valid"]+=int(w["applicable"]);counts["stage6_valid_hit"]+=int(w["applicable"])*r["is_opponent_dontsuka"]
                    if not (w or r["self_first_reach"] or r["is_opponent_dontsuka"]):continue
                    r.update({x:draw[x] for x in ("draw_event_id","event_order","kyoku_id","player_id","game_id","game_date","season_start_year","stage","is_dontsuka","interval_draw_number","first_hit","shoubute_tenpai","shoubute_isshanten","pre_reason")})
                    r.update(stage6=w or {},rank_drop=hit[t]["rank_drop"] if t in hit else "",origin_links=links[k] if t in hit else [])
                    r.update(actual_ron=int(bool(actual)),actual_ron_ids=[x["ron_event_id"] for x in actual],approved_round_ron_class=oldround[ky,player]["category"] if (ky,player) in oldround else "",self_win=int(player in winners[ky]),kyoku_net=end_scores[player]-start_scores[player])
                    r["conditions"]=conditions(r)
                    if t in hit:
                        require(k not in originseen,"origin duplicate");originseen.add(k)
                        o=hit[t];require(int(o["drawer"])==player and int(o["event_order"])==draw["event_order"] and o["tile"]==draw["draw_tile"],"origin attributes")
                    if r["relation"] in ("self_earlier","self_later"):counts["strict_pairs"]+=1;counts["strict_hit"]+=r["is_opponent_dontsuka"]
                    elif a0 in TENPAI and b0 in TENPAI:counts["non_strict_both"]+=1;counts["non_strict_both_hit"]+=r["is_opponent_dontsuka"]
                    for label in (r["relation"],r["combination"],r["first_reach_class"]):
                        if label:examples.setdefault(label,r.copy())
                    emit(pf,r)
                emit(df,draw)
            for r in tracker.finish():
                r.update(meta[ky]);emit(itf,r);counts["intervals"]+=1
                if not r["start_known"]:counts["uncertain_intervals"]+=1
                if r["first_hit_event_id"] is not None:counts["hit_intervals"]+=1
            for r in tracker.reach_records:
                r.update(meta[ky]);emit(rf,r);counts["reach_declarations"]+=1;counts["accepted_reaches"]+=r["accepted"]
    require(seen==dbids and pairseen==set(wait6) and originseen=={(d,t) for d,ts in origins.items() for t in ts},"coverage at completion")
    jsonout(a.out/"names.json",names);jsonout(a.out/"examples.json",examples)
    jsonout(a.out/"summary.json",dict(shard=a.shard,shards=a.shards,limited=bool(a.limit_rounds),kyoku_ids=kys,counts=dict(counts),database_sha256=DB_SHA,inputs=INPUTS,elapsed_seconds=time.monotonic()-start,processing_seconds=time.monotonic()-processing,peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,run_id=os.getenv("GITHUB_RUN_ID"),commit=os.getenv("GITHUB_SHA")))
    print(js(dict(counts)),flush=True)
if __name__=="__main__":main()
