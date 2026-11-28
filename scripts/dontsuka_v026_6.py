"""Stage 6 replay and detail extraction; no future event enters the comparison."""
import argparse,csv,gzip,io,json,os,resource,time,zipfile
from pathlib import Path
from collections import Counter,defaultdict
from dontsuka_v026_6_core import Inventory,state,compare,pairs,require,normal,remaining,counts
from dontsuka_v026_2a_audit import events
from dontsuka_v026_5b import verified,cov_rows,A_SHA
from dontsuka_v026_3b import read_csv_zip
from dontsuka_v026_4b import STAGE3A_SHA,STAGE2B_SHA
from dontsuka_v026_extract import connect_readonly,verify_database,sha256_file
from dontsuka_v026_2b_replay import RELEASE,DB_SHA

B_SHA="26102c4cd6f464ff84869cab50869de72cd54acdd5afa207b2dd1f06d3826bb0"
AF_SHA="60c47f88bfa571ceb86ee632adf726981fcc148bc9ba2f284a269b2e86f12bb0"
csv.field_size_limit(100000000)
def js(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"))
def jsonout(p,x):p.write_text(js(x)+"\n",encoding="utf-8")
def rows(z,n):
    with z.open(n) as f:
        if n.endswith(".gz"):
            with gzip.GzipFile(fileobj=f) as g,io.TextIOWrapper(g,encoding="utf-8-sig") as t:yield from csv.DictReader(t)
        else:
            with io.TextIOWrapper(f,encoding="utf-8-sig") as t:yield from csv.DictReader(t)
def normwait(x):return tuple(sorted(set(normal(t.strip()) for t in x.split(",") if t.strip())))
def detail_wait(r):return tuple(sorted(set(map(normal,json.loads(r["wait_candidates"])))))
def checkzip(path,digest,manifest,field=None):
    require(sha256_file(path)==digest,"ZIP digest")
    z=zipfile.ZipFile(path)
    require(z.testzip() is None and len(set(z.namelist()))==len(z.namelist()),"ZIP integrity")
    m=json.loads(z.read(manifest));hashes=m[field] if field else m
    import hashlib
    require(set(hashes)==set(z.namelist())-{manifest},"manifest coverage")
    for n,h in hashes.items():require(hashlib.sha256(z.read(n)).hexdigest()==h,"member hash "+n)
    return z,m

DETAIL="draw_event_id event_order kyoku_id game_id game_date season_start_year stage player_id target_id self_state target_state self_waits target_waits self_effective target_effective self_visible target_visible self_wall target_wall visible_diff wall_diff visible_class wall_class combined is_dontsuka applicable reason".split()
COVER="draw_event_id event_order kyoku_id game_id game_date season_start_year stage player_id status physical_shanten is_dontsuka opponent_count self_state".split()
def main():
    ap=argparse.ArgumentParser()
    for n in ("db","stage2b","stage3a","stage5a","stage5af","stage5b","out"):ap.add_argument(n,type=Path)
    ap.add_argument("--shard",type=int,default=0);ap.add_argument("--shards",type=int,default=1);ap.add_argument("--limit-rounds",type=int,default=0)
    a=ap.parse_args();start=time.monotonic();a.out.mkdir(parents=True,exist_ok=True)
    require(0<=a.shard<a.shards,"shard")
    c=connect_readonly(a.db);verify_database(c,RELEASE);require(sha256_file(a.db)==DB_SHA,"DB hash")
    z2,_=verified(a.stage2b,STAGE2B_SHA);z3,_=verified(a.stage3a,STAGE3A_SHA)
    za,ma=checkzip(a.stage5a,A_SHA,"manifest.json","outputs")
    zaf,maf=checkzip(a.stage5af,AF_SHA,"final_manifest.json","outputs")
    zb,mb=checkzip(a.stage5b,B_SHA,"package_sha256.json")
    require(ma["database_sha256"]==maf["database_sha256"]==DB_SHA,"A database identity")
    bfinal=json.loads(zb.read("final/manifest.json"))
    require(bfinal["database_sha256"]==DB_SHA and bfinal["stage5a_sha256"]==A_SHA,"B database identity")
    require(tuple(ma["overall"][k] for k in ("tenpai_draws","tenpai_dontsuka","shoubute_draws","shoubute_dontsuka"))==(161790,5696,97757,3449),"A counts")
    require(tuple(bfinal["counts"][k] for k in ("draws","basic","excluded","isshanten","isshanten_dontsuka","shoubute","shoubute_dontsuka"))==(1257732,27578,133,299220,8956,231765,7077),"B counts")
    excluded={int(r["draw_event_id"]):r for r in rows(za,"unresolved_and_discrepancies.csv")}
    require(len(excluded)==133 and len({r["kyoku_id"] for r in excluded.values()})==11 and sum(int(r["is_dontsuka"]) for r in excluded.values())==1,"A exclusions")
    origins=defaultdict(set);orig=read_csv_zip(z3,"opponent_hypothetical_all.csv")
    require((len(orig),sum(float(r["rank_drop"])>0 for r in orig),sum(float(r["rank_drop"])==0 for r in orig))==(28060,13170,14890),"approved origins")
    for r in orig:
        eid,t=int(r["draw_event_id"]),int(r["target"])
        require(t not in origins[eid],"origin duplicate");origins[eid].add(t)
    require(len(origins)==27578,"basic origins")
    meta={int(r[0]):dict(game_id=int(r[1]),game_date=r[2],season_start_year=int(r[3]),stage=r[4]) for r in c.execute("SELECT k.id,g.id,g.date,ls.start_year,ss.stage FROM kyoku k JOIN game g ON g.id=k.game_id JOIN season_stage ss ON ss.id=g.season_stage_id JOIN league_season ls ON ls.id=ss.league_season_id")}
    names={int(r[0]):r[1] for r in c.execute("SELECT id,name FROM player")}
    require((len(meta),len({m["game_id"] for m in meta.values()}),len(names))==(25238,2068,56),"scope")
    kys=sorted(meta)[a.shard::a.shards]
    if a.limit_rounds:kys=kys[:a.limit_rounds]
    selected=set(kys);expected={};bseen=set();expected_wait={};global_a=Counter()
    for r in cov_rows(za):
        global_a.update(draws=1,basic=int(r["is_dontsuka"]),excluded=r["status"]=="unresolved")
        if int(r["kyoku_id"]) in selected:
            eid=int(r["draw_event_id"]);require(eid not in expected,"A duplicate");expected[eid]=r
    require(global_a==Counter(draws=1257732,basic=27578,excluded=133),"A coverage")
    for n in zb.namelist():
        if not n.startswith("corrected/") or not n.endswith("/coverage.csv.gz"):continue
        for r in rows(zb,n):
            if int(r["kyoku_id"]) not in selected:continue
            eid=int(r["draw_event_id"]);require(eid not in bseen and eid in expected,"B coverage identity");bseen.add(eid)
            ar=expected[eid]
            for k in ("event_order","kyoku_id","game_id","game_date","season_start_year","stage","player_id","physical_shanten","is_dontsuka"):
                require(r[k]==ar[k],"A/B attribute "+k)
            require((r["status"]=="not_applicable_actual_foul")== (eid in excluded),"B foul status")
    require(bseen==set(expected),"A/B ID set")
    for r in rows(za,"tenpai_draw_details.csv.gz"):
        eid=int(r["draw_event_id"])
        if eid in expected:
            require(eid not in expected_wait,"A wait duplicate");expected_wait[eid]=detail_wait(r)
    dbids={int(r[0]) for r in c.execute("SELECT d.event_id,e.kyoku_id FROM draw_event d JOIN event e ON e.id=d.event_id") if int(r[1]) in selected}
    require(dbids==set(expected),"DB draw ID set")
    ids2=set()
    for r in rows(z2,"draw_snapshots.csv.gz"):
        eid=int(r["event_id"])
        if eid in expected:
            require(eid not in ids2,"2B duplicate");ids2.add(eid)
    require(ids2==set(expected),"2B draw ID set")
    stats=Counter();seen=set();examples={};audit=Counter();processing=time.monotonic()
    with gzip.open(a.out/"coverage.csv.gz","wt",encoding="utf-8",newline="") as f,gzip.open(a.out/"pairs.csv.gz","wt",encoding="utf-8",newline="") as g,gzip.open(a.out/"wait_audit.csv.gz","wt",encoding="utf-8",newline="") as h:
        cw=csv.DictWriter(f,fieldnames=COVER,extrasaction="ignore");pw=csv.DictWriter(g,fieldnames=DETAIL,extrasaction="ignore")
        aw=csv.DictWriter(h,fieldnames="draw_event_id kyoku_id player_id snapshot_event_id snapshot_order reason reconstructed_waits recorded_waits reconstructed_wall recorded_wall reconstructed_visible recorded_visible".split())
        for w in (cw,pw,aw):w.writeheader()
        for ky in kys:
            rp=Inventory();last=None;snaps=defaultdict(list);current={}
            for r in c.execute("SELECT pts.*,e.event_order FROM player_tenpai_state pts JOIN event e ON e.id=pts.event_id WHERE e.kyoku_id=?",(ky,)):snaps[r["event_id"]].append(dict(r))
            for e in events(c,ky):
                eid,p=e["id"],e.get("actor")
                if e["type"]=="draw":
                    require(eid in expected and eid not in seen,"draw identity");seen.add(eid)
                    ar=expected[eid];targets=origins.get(eid,set());dd=int(bool(targets))
                    require((int(ar["kyoku_id"]),int(ar["player_id"]),int(ar["event_order"]),int(ar["is_dontsuka"]))==(ky,p,e["event_order"],dd),"draw attributes")
                    require(len(rp.hands)==4,"four hands")
                    public,private,known=rp.snapshot()
                    states={q:state(rp,q) for q in rp.hands}
                    ss,sw,se=states[p]
                    require((ss=="unknown")== (eid in excluded),"self foul agreement")
                    if ss!="unknown":
                        expected_state=ar["state"]
                        if expected_state=="structural_tenpai_no_physical_wait":expected_state="not_tenpai"
                        require(ss==expected_state,"A tenpai state mismatch")
                        if ss!="not_tenpai":require(sw==expected_wait[eid],"A wait types mismatch")
                    stats.update(draws=1,basic=dd,opponents=len(targets),excluded=ss=="unknown",self_tenpai=ss not in ("unknown","not_tenpai"),self_tenpai_dontsuka=bool(dd and ss not in ("unknown","not_tenpai")))
                    base=dict(draw_event_id=eid,event_order=e["event_order"],kyoku_id=ky,**meta[ky],player_id=p,is_dontsuka=dd,status=ar["status"],physical_shanten=ar["physical_shanten"],opponent_count=len(targets),self_state=ss)
                    cw.writerow(base)
                    for t,ok in pairs(states,p,set(rp.hands)-{p}):
                        ts,tw,te=states[t];r=dict(base,target_id=t,self_waits=js(sw),target_waits=js(tw),self_effective=se,target_effective=te,target_state=ts,is_dontsuka=int(t in targets),applicable=int(ok),reason="")
                        if ok:
                            r.update(compare(p,t,public,private,known,sw,tw));stats.update(pairs=1,pair_dontsuka=r["is_dontsuka"])
                            examples.setdefault(r["combined"],r.copy())
                            if not r["is_dontsuka"]:examples.setdefault("non_dontsuka",r.copy())
                            if sw==tw:examples.setdefault("same_wait",r.copy())
                            if len(sw)>1:examples.setdefault("multiple_wait",r.copy())
                            if not r["self_wall"] or not r["target_wall"]:examples.setdefault("wall_zero",r.copy())
                            if not r["self_visible"] or not r["target_visible"]:examples.setdefault("visible_zero",r.copy())
                            if len(targets)>1:examples.setdefault("multiple_origins",r.copy())
                        else:
                            r["reason"]="abnormal_effective_tile_count";stats.update(unknown_pairs=1,unknown_pair_dontsuka=r["is_dontsuka"])
                        pw.writerow(r)
                    # Independent existing DB wait comparison only where a current
                    # snapshot exists; stale snapshot is not a pre-draw observation.
                    for q,(typ,w,eff) in states.items():
                        if typ in ("unknown","not_tenpai"):continue
                        rec=current.get(q)
                        if not rec or rec["event_id"]!=last:
                            audit["no_exact_previous_event_snapshot"]+=1;continue
                        rw=normwait(rec["waiting_tiles"] or "")
                        wall=remaining(w,known);vis=remaining(w,public+private[q])
                        audit["exact_snapshot"]+=1
                        reason=[]
                        if rw!=w:reason.append("wait_types_disagreement")
                        if rec["available_tile_count"]!=wall:reason.append("available_count_disagreement")
                        if reason:
                            audit["disagreement"]+=1
                            aw.writerow(dict(draw_event_id=eid,kyoku_id=ky,player_id=q,snapshot_event_id=rec["event_id"],snapshot_order=rec["event_order"],reason=";".join(reason),reconstructed_waits=js(w),recorded_waits=js(rw),reconstructed_wall=wall,recorded_wall=rec["available_tile_count"],reconstructed_visible=vis))
                        else:audit["match"]+=1
                if e["type"] not in ("ron","tsumo","ryukyoku"):rp.step(e)
                for rec in snaps[eid]:current[rec["player_id"]]=rec
                last=eid
            if len(seen)%10000<100:print("draws",len(seen),"counts",dict(stats),flush=True)
    require(seen==set(expected),"coverage")
    jsonout(a.out/"examples.json",examples);jsonout(a.out/"names.json",names)
    jsonout(a.out/"summary.json",dict(shard=a.shard,shards=a.shards,limited=bool(a.limit_rounds),kyoku_ids=kys,counts=dict(stats),audit=dict(audit),database_sha256=DB_SHA,elapsed_seconds=time.monotonic()-start,processing_seconds=time.monotonic()-processing,peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,run_id=os.getenv("GITHUB_RUN_ID"),commit=os.getenv("GITHUB_SHA")))
    # The workflow writes the final manifest only after tee has exited.
    print(js(dict(stats)),flush=True)
if __name__=="__main__":main()
