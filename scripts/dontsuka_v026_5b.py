"""Stage 5B runner. Shard by whole rounds; verify all pre-draw states against 5A."""
import argparse,csv,gzip,hashlib,io,json,os,resource,time,traceback,zipfile
from collections import Counter,defaultdict
from pathlib import Path
from dontsuka_v026_2a_audit import events
from dontsuka_v026_2a_replay import Replay
from dontsuka_v026_5a_core import sh,vector
from dontsuka_v026_5b_core import classify,scoring,structural_options
from dontsuka_v026_extract import connect_readonly,verify_database,sha256_file
from dontsuka_v026_2b_replay import RELEASE,DB_SHA
from dontsuka_v026_3b import read_csv_zip
from dontsuka_v026_4b import scoremap,STAGE2B_SHA,STAGE3A_SHA,STAGE4A_SHA

A_SHA="5d2885cc4e19fdd0bb18a37a587145f9ab8699ef70efd385964ff11511f4edff"
def js(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"))
def write_json(p,v):p.write_text(js(v)+"\n",encoding="utf-8")
def require(b,msg):
    if not b:raise ValueError(msg)
def verified(path,digest):
    require(sha256_file(path)==digest,"archive digest "+str(path))
    z=zipfile.ZipFile(path);m=json.loads(z.read("manifest.json"))
    require(m["database_sha256"]==DB_SHA,"archive DB "+str(path))
    for n,h in m.get("outputs",{}).items():
        require(hashlib.sha256(z.read(n)).hexdigest()==h,"member digest "+n)
    return z,m
def cov_rows(z):
    with z.open("all_draw_coverage.csv.gz") as f,gzip.GzipFile(fileobj=f) as g,io.TextIOWrapper(g,encoding="utf-8") as t:
        yield from csv.DictReader(t)
def main():
    p=argparse.ArgumentParser()
    for n in ("db","stage2b","stage3a","stage4a","stage5a","out"):p.add_argument(n,type=Path)
    p.add_argument("--shard",type=int,default=0);p.add_argument("--shards",type=int,default=1)
    p.add_argument("--limit-rounds",type=int,default=0)
    a=p.parse_args();start=time.monotonic();a.out.mkdir(parents=True,exist_ok=True)
    require(0<=a.shard<a.shards,"shard")
    c=connect_readonly(a.db);verify_database(c,RELEASE);require(sha256_file(a.db)==DB_SHA,"DB digest")
    z2,_=verified(a.stage2b,STAGE2B_SHA);z3,_=verified(a.stage3a,STAGE3A_SHA)
    z4,_=verified(a.stage4a,STAGE4A_SHA);za,ma=verified(a.stage5a,A_SHA)
    ov=ma["overall"]
    require(tuple(ov[k] for k in ("tenpai_draws","tenpai_dontsuka","shoubute_draws","shoubute_dontsuka","shoubute_dontsuka_kyoku"))==(161790,5696,97757,3449,3426),"approved 5A totals")
    excluded={int(r["draw_event_id"]):r for r in read_csv_zip(za,"unresolved_and_discrepancies.csv")}
    require(len(excluded)==133 and len({r["kyoku_id"] for r in excluded.values()})==11 and sum(int(r["is_dontsuka"]) for r in excluded.values())==1,"approved exclusions")
    a_rounds={(int(r["kyoku_id"]),int(r["player_id"])) for r in read_csv_zip(za,"shoubute_dontsuka_kyoku.csv")}
    require(len(a_rounds)==3426,"approved A rounds")
    orig=read_csv_zip(z3,"opponent_hypothetical_all.csv");origins=defaultdict(list)
    for r in orig:origins[int(r["draw_event_id"])].append(r)
    require((len(orig),len(origins),len({(r["draw_event_id"],r["target"]) for r in orig}),sum(float(r["rank_drop"])>0 for r in orig),sum(float(r["rank_drop"])==0 for r in orig))==(28060,27578,28060,13170,14890),"approved origins")
    old={(int(r["kyoku_id"]),int(r["player_id"])):r for r in read_csv_zip(z4,"dontsuka_kyoku_classification.csv")}
    actual=defaultdict(list);links=defaultdict(list)
    for r in read_csv_zip(z4,"actual_ron_classification.csv"):actual[int(r["kyoku_id"]),int(r["player_id"])].append(r)
    for r in read_csv_zip(z4,"origin_ron_links.csv"):links[int(r["draw_event_id"])].append(r)
    end={int(r["kyoku_id"]):r for r in read_csv_zip(z2,"kyoku_comparison.csv")}
    require(len(end)==25238 and all(r["match"] in ("1","True","true") and not r["error"] for r in end.values()),"approved end scores")
    winners=defaultdict(set)
    for ky,p in c.execute("SELECT e.kyoku_id,a.actor_player_id FROM agari_event a JOIN event e ON e.id=a.event_id WHERE e.type IN ('ron','tsumo')"):winners[ky].add(p)
    meta={int(r[0]):dict(game_id=int(r[1]),game_date=r[2],season_start_year=int(r[3]),stage=r[4]) for r in c.execute("""SELECT k.id,g.id,g.date,ls.start_year,ss.stage FROM kyoku k JOIN game g ON g.id=k.game_id JOIN season_stage ss ON ss.id=g.season_stage_id JOIN league_season ls ON ls.id=ss.league_season_id""")}
    names={int(r[0]):r[1] for r in c.execute("SELECT id,name FROM player")}
    require((len(meta),len({m["game_id"] for m in meta.values()}),len(names))==(25238,2068,56),"scope")
    kys=sorted(meta)[a.shard::a.shards]
    if a.limit_rounds:kys=kys[:a.limit_rounds]
    selected=set(kys);expected={};globalcounts=Counter()
    for r in cov_rows(za):
        eid=int(r["draw_event_id"]);ky=int(r["kyoku_id"]);dd=int(r["is_dontsuka"])
        globalcounts.update(draws=1,basic=dd,excluded=r["status"]=="unresolved")
        if ky in selected:
            require(eid not in expected,"duplicate A event")
            expected[eid]=r
    require(globalcounts==Counter(draws=1257732,basic=27578,excluded=133),"A coverage")
    dbids={int(r[0]) for r in c.execute("SELECT d.event_id,e.kyoku_id FROM draw_event d JOIN event e ON e.id=d.event_id") if int(r[1]) in selected}
    require(set(expected)==dbids,"A vs DB IDs")
    fields=["draw_event_id","event_order","kyoku_id","game_id","game_date","season_start_year","stage","player_id","status","physical_shanten","is_dontsuka","is_shoubute","progressions","patterns","qualifying_progressions","qualifying_patterns","concealed_before","melds","omote","past_discards","witness","opponents","actual_ron_links","error"]
    seen=set();counts=Counter();rounds={};errors=[];examples={};fouls=[];processing_start=time.monotonic()
    with gzip.open(a.out/"coverage.csv.gz","wt",encoding="utf-8",newline="") as cf,gzip.open(a.out/"isshanten_draws.csv.gz","wt",encoding="utf-8",newline="") as qf,gzip.open(a.out/"shoubute_dontsuka.csv.gz","wt",encoding="utf-8",newline="") as df:
        cw=csv.DictWriter(cf,fieldnames=fields[:12],extrasaction="ignore")
        qw=csv.DictWriter(qf,fieldnames=fields,extrasaction="ignore")
        dw=csv.DictWriter(df,fieldnames=fields,extrasaction="ignore")
        for w in (cw,qw,dw):w.writeheader()
        for i,ky in enumerate(kys,1):
            rp=Replay();discards=defaultdict(set);md=meta[ky]
            winds={r[0]:r[1] for r in c.execute("SELECT player_id,player_wind FROM kyoku_player_result WHERE kyoku_id=?",(ky,))}
            rw=c.execute("SELECT round FROM kyoku WHERE id=?",(ky,)).fetchone()[0][:2]
            for ev in events(c,ky):
                eid=ev["id"];p=ev.get("actor")
                if ev["type"]=="draw":
                    require(eid in expected and eid not in seen,"unexpected/duplicate draw")
                    seen.add(eid);before=expected[eid];dd=int(eid in origins)
                    require((int(before["kyoku_id"]),int(before["player_id"]),int(before["event_order"]),int(before["is_dontsuka"]))==(ky,p,ev["event_order"],dd),"A draw identity")
                    h=rp.hands[p];m=rp.melds[p]
                    r=dict(draw_event_id=eid,event_order=ev["event_order"],kyoku_id=ky,**md,player_id=p,status="evaluated",is_dontsuka=dd,is_shoubute=0)
                    counts.update(draws=1,basic=dd)
                    try:
                        valid=len(h)+3*len(m)==13
                        require(valid==(eid not in excluded),"A exclusion mismatch")
                        if not valid:
                            require(before["status"]=="unresolved","A exclusion status")
                            r.update(status="not_applicable_actual_foul",is_shoubute="")
                            counts.update(excluded=1,excluded_basic=dd)
                            effective=len(h)+3*len(m)
                            fouls.append(dict(excluded[eid],effective_tiles=effective,reason="少牌" if effective<13 else "多牌",final_status="not_applicable_actual_foul"))
                        else:
                            q=sh(vector(h));r["physical_shanten"]=q
                            require(before["status"]=="evaluated" and q==int(before["physical_shanten"]),"A shanten mismatch")
                            counts["evaluated"]+=1
                            if q==1:
                                require(p not in rp.reaches,"accepted riichi one-shanten")
                                result=classify(h,m,winds[p],rw,rp.omote,discards[p])
                                r.update({k:v for k,v in result.items() if k!="witness"})
                                r.update(concealed_before=js(h),melds=js(m),omote=js(rp.omote),past_discards=js(sorted(discards[p])),witness=js(result["witness"]))
                                counts.update(isshanten=1,isshanten_dontsuka=dd,progressions=result["progressions"],patterns=result["patterns"],shoubute=result["is_shoubute"],shoubute_dontsuka=dd*result["is_shoubute"])
                                if result["is_shoubute"]:
                                    w=result["witness"]; pat=w["pattern"]
                                    for label,cond in (("non_dontsuka",not dd),("doutsuka",dd),("open",any(k!="ankan" for k,b in m)),("red","赤ドラ" in pat["yaku"]),("kan_dora",len(rp.omote)>1),("chiitoitsu","七対子" in pat["yaku"]),("yakuman",pat["yakuman"]),("sanshoku","三色同順" in pat["yaku"]),("four20",(pat["han"],pat["fu"])==(4,20)),("kiriage",(pat["han"],pat["fu"])==(3,60)),("virtual_riichi",pat["virtual_riichi"])):
                                        if cond:examples.setdefault(label,dict(r))
                                    if dd:
                                        r.update(opponents=js(origins[eid]),actual_ron_links=js(links[eid]))
                                        dw.writerow(r)
                                        rounds.setdefault((ky,p),[]).append(eid)
                                qw.writerow(r)
                    except Exception as ex:
                        r.update(status="unresolved",is_shoubute="",error=repr(ex))
                        errors.append(dict(r,traceback=traceback.format_exc()))
                    cw.writerow(r)
                if ev["type"] not in ("ron","tsumo","ryukyoku"):rp.step(ev)
                if ev["type"]=="discard":discards[p].add(ev["tile"])
            if i%25==0:print("rounds",i,"of",len(kys),"counts",dict(counts),"seconds",round(time.monotonic()-start,2),flush=True)
    require(seen==set(expected),"draw coverage missing")
    rows=[]
    for (ky,p),ids in sorted(rounds.items()):
        e=end[ky];delta=scoremap(e["recorded_end_scores"])[p]-scoremap(e["start_scores"])[p]
        rows.append(dict(kyoku_id=ky,player_id=p,**meta[ky],draw_count=len(ids),draw_event_ids=js(ids),also_shoubute_tenpai_dontsuka=int((ky,p) in a_rounds),actual_ron=int(bool(actual[ky,p])),approved_ron_classification=old[ky,p]["category"],actual_ron_event_ids=js([r["ron_event_id"] for r in actual[ky,p]]),self_win=int(p in winners[ky]),kyoku_net=delta))
    write_json(a.out/"rounds.json",rows);write_json(a.out/"errors.json",errors);write_json(a.out/"exclusions.json",fouls)
    write_json(a.out/"real_examples.json",examples)
    write_json(a.out/"names.json",names)
    manifest=dict(scope="5B only",status="incomplete" if errors else "computed",shard=a.shard,shards=a.shards,limited=bool(a.limit_rounds),kyoku_ids=kys,counts=dict(counts),errors=len(errors),elapsed_seconds=time.monotonic()-start,processing_seconds=time.monotonic()-processing_start,peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,scoring_cache=str(scoring.cache_info()),structural_cache=str(structural_options.cache_info()),database_sha256=DB_SHA,stage5a_sha256=A_SHA,commit=os.getenv("GITHUB_SHA"),run_id=os.getenv("GITHUB_RUN_ID"))
    manifest["outputs"]={f.name:sha256_file(f) for f in a.out.iterdir() if f.is_file() and f.name!="manifest.json"}
    write_json(a.out/"manifest.json",manifest);print(js({k:v for k,v in manifest.items() if k!="kyoku_ids"}),flush=True)
    if errors:raise SystemExit(1)
if __name__=="__main__":main()
