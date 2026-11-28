"""Stage 6: merge validated round shards, independently reconcile count dimensions."""
import argparse,csv,gzip,json,hashlib
from collections import Counter,defaultdict
from fractions import Fraction
from pathlib import Path
from itertools import product
from dontsuka_v026_6_core import require,sign
from dontsuka_v026_6 import DETAIL,COVER,js,jsonout
from dontsuka_v026_extract import sha256_file

CLASSES=("advantage","equal","disadvantage")
COMBINED=tuple(a+"_"+b for a,b in product(CLASSES,repeat=2))
def read(p):
    with gzip.open(p,"rt",encoding="utf-8",newline="") as f:yield from csv.DictReader(f)
def writer(f,fields):
    w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");w.writeheader();return w
def dims(r):
    y,s=r["season_start_year"],r["stage"]
    return (("all","",""),("season",y,""),("stage","",s),("season_stage",y,s))
def keys(r):
    for d in dims(r):yield ("",*d);yield (r["player_id"],*d)
def pct(n,d):return "" if not d else f"{100*n/d:.9f}"
def emit(p,fields,rs):
    with p.open("w",encoding="utf-8-sig",newline="") as f:writer(f,fields).writerows(rs)
def validate_row(r):
    a,b,c,d=(int(r[k]) for k in ("self_visible","target_visible","self_wall","target_wall"))
    require(0<=c<=a and 0<=d<=b,"remaining count inequality")
    require(int(r["visible_diff"])==a-b and int(r["wall_diff"])==c-d,"difference")
    v,w=sign(a-b),sign(c-d)
    require((r["visible_class"],r["wall_class"],r["combined"])==(v,w,v+"_"+w),"classification")
    require(r["self_state"] in ("riichi","damaten","open") and r["target_state"] in ("riichi","damaten","open"),"both tenpai")
def main():
    p=argparse.ArgumentParser();p.add_argument("shards_dir",type=Path);p.add_argument("out",type=Path);p.add_argument("--shards",type=int,required=True);a=p.parse_args()
    a.out.mkdir(parents=True,exist_ok=True)
    paths=sorted(x for x in a.shards_dir.iterdir() if x.is_dir())
    require(len(paths)==a.shards,"shard count")
    k_ids=set();d_ids=set();p_ids=set();shard_ids=set();counts=Counter();audit=Counter();examples={};names={};groups=defaultdict(Counter);direct=defaultdict(Counter)
    possible=defaultdict(Counter);draw_metadata={};runs=set();commits=set()
    with gzip.open(a.out/"all_draw_coverage.csv.gz","wt",encoding="utf-8",newline="") as f:
        cw=writer(f,COVER)
        for path in paths:
            m=json.loads((path/"manifest.json").read_text());s=json.loads((path/"summary.json").read_text())
            require(set(m)=={x.name for x in path.iterdir() if x.is_file() and x.name!="manifest.json"},"manifest members")
            for n,h in m.items():require(sha256_file(path/n)==h,"shard hash "+n)
            require(not s["limited"] and s["shards"]==a.shards and s["shard"] not in shard_ids,"shard identity")
            shard_ids.add(s["shard"]);runs.add(s["run_id"]);commits.add(s["commit"])
            ks=set(s["kyoku_ids"]);require(len(ks)==len(s["kyoku_ids"]) and not ks&k_ids,"round duplicate");k_ids.update(ks)
            counts.update(s["counts"]);audit.update(s["audit"])
            for k,v in json.loads((path/"examples.json").read_text()).items():examples.setdefault(k,v)
            nm=json.loads((path/"names.json").read_text());require(not names or names==nm,"name map");names=nm
            seen=set();local=Counter()
            for r in read(path/"coverage.csv.gz"):
                eid=int(r["draw_event_id"]);ky=int(r["kyoku_id"]);require(eid not in d_ids and ky in ks,"draw overlap or wrong round")
                d_ids.add(eid);seen.add(ky);draw_metadata[eid]=(r["player_id"],r["kyoku_id"],r["event_order"],r["game_id"],r["game_date"],r["season_start_year"],r["stage"],r["is_dontsuka"],r["self_state"],int(r["opponent_count"]))
                dd=int(r["is_dontsuka"]);local.update(draws=1,basic=dd,opponents=int(r["opponent_count"]),excluded=r["self_state"]=="unknown",self_tenpai=r["self_state"] not in ("unknown","not_tenpai"),self_tenpai_dontsuka=bool(dd and r["self_state"] not in ("unknown","not_tenpai")))
                for key in keys(r):groups[key];direct[key];possible[key]
                cw.writerow(r)
            require(seen==ks,"round coverage")
            for k,v in local.items():require(v==s["counts"].get(k,0),"shard coverage count "+k)
    require(shard_ids==set(range(a.shards)) and len(runs)==len(commits)==1,"shard/run identity")
    require((len(k_ids),len(d_ids),len(names),counts["draws"],counts["basic"],counts["opponents"],counts["excluded"],counts["self_tenpai"],counts["self_tenpai_dontsuka"])==(25238,1257732,56,1257732,27578,28060,133,161790,5696),"approved global counts")
    require(len({r[3] for r in draw_metadata.values()})==2068,"game count")
    actual=Counter();pairhits=Counter()
    with gzip.open(a.out/"all_comparison_details.csv.gz","wt",encoding="utf-8",newline="") as f,gzip.open(a.out/"both_tenpai_dontsuka.csv.gz","wt",encoding="utf-8",newline="") as g,gzip.open(a.out/"not_applicable.csv.gz","wt",encoding="utf-8",newline="") as h,gzip.open(a.out/"wait_discrepancies.csv.gz","wt",encoding="utf-8",newline="") as j:
        w,wd,we=writer(f,DETAIL),writer(g,DETAIL),writer(h,DETAIL)
        audit_writer=None
        for path in paths:
            s=json.loads((path/"summary.json").read_text());local=Counter()
            for r in read(path/"pairs.csv.gz"):
                eid=int(r["draw_event_id"]);t=r["target_id"];dd=int(r["is_dontsuka"]);ok=int(r["applicable"]);k=(eid,t)
                require(k not in p_ids and t!=r["player_id"] and t in names,"duplicate/invalid pair");p_ids.add(k)
                md=draw_metadata[eid];require(tuple(r[x] for x in ("player_id","kyoku_id","event_order","game_id","game_date","season_start_year","stage"))==md[:7],"pair draw attributes")
                require(r["self_state"]==md[8] and dd in (0,1) and ok in (0,1),"pair status")
                if dd:pairhits[eid]+=1;require(md[7]=="1" and pairhits[eid]<=md[9],"pair hits exceed approved origins")
                w.writerow(r)
                if not ok:
                    require("unknown" in (r["self_state"],r["target_state"]) and r["reason"],"unclassified exclusion")
                    local.update(unknown_pairs=1,unknown_pair_dontsuka=dd);we.writerow(r)
                    for key in keys(r):possible[key].update(unknown_pairs=1,unknown_pair_dontsuka=dd)
                    continue
                validate_row(r);require(not r["reason"],"unexpected exclusion reason")
                local.update(pairs=1,pair_dontsuka=dd)
                if dd:wd.writerow(r)
                for key in keys(r):
                    c=groups[key];c[(r["combined"],"n")]+=1;c[(r["combined"],"d")]+=dd
                    d=direct[key];d[("visible",r["visible_class"],"n")]+=1;d[("visible",r["visible_class"],"d")]+=dd;d[("wall",r["wall_class"],"n")]+=1;d[("wall",r["wall_class"],"d")]+=dd
            for k,v in local.items():require(v==s["counts"].get(k,0),"pair shard count "+k)
            actual.update(local)
            for r in read(path/"wait_audit.csv.gz"):
                if audit_writer is None:audit_writer=writer(j,list(r))
                audit_writer.writerow(r)
            if audit_writer is None:
                with gzip.open(path/"wait_audit.csv.gz","rt",encoding="utf-8") as q:
                    header=next(csv.reader(q));audit_writer=writer(j,header)
    for k in ("pairs","pair_dontsuka","unknown_pairs","unknown_pair_dontsuka"):require(actual[k]==counts[k],"merge totals")
    allrows=[];visrows=[];wallrows=[];combrows=[]
    for key,c in sorted(groups.items()):
        player,scope,season,stage=key
        base=dict(player_id=player,player_name=names.get(player,"全選手"),scope=scope,season_start_year=season,stage=stage)
        N=sum(c[(k,"n")] for k in COMBINED);D=sum(c[(k,"d")] for k in COMBINED)
        ex=possible[key]
        allrows.append(dict(base,pairs=N,pair_dontsuka=D,rate_pct=pct(D,N),unknown_pairs=ex["unknown_pairs"],unknown_pair_dontsuka=ex["unknown_pair_dontsuka"]))
        for view,classes,out in (("combined",COMBINED,combrows),("visible",CLASSES,visrows),("wall",CLASSES,wallrows)):
            ns=ds=0;frac=Fraction(0)
            for cl in classes:
                subs=[cl] if view=="combined" else [k for k in COMBINED if k.split("_")[0 if view=="visible" else 1]==cl]
                n=sum(c[(k,"n")] for k in subs);d=sum(c[(k,"d")] for k in subs)
                if view!="combined":
                    require((n,d)==(direct[key][(view,cl,"n")],direct[key][(view,cl,"d")]),"independent marginal")
                require(0<=d<=n,"numerator bound");ns+=n;ds+=d
                if D:frac+=Fraction(d,D)
                out.append(dict(base,classification=cl,draws=n,dontsuka=d,rate_pct=pct(d,n),composition_denominator=D,composition_pct=pct(d,D),rate_status="defined" if n else "undefined",composition_status="defined" if D else "undefined"))
            require((ns,ds)==(N,D) and (not D or frac==1),"partition/composition")
    overall=groups[("","all","","")]
    require(sum(overall[(k,"n")] for k in COMBINED)==actual["pairs"] and sum(overall[(k,"d")] for k in COMBINED)==actual["pair_dontsuka"],"overall")
    # Each dimension independently rolls up from player rows.
    for key,c in groups.items():
        if key[0]:continue
        rolled=Counter()
        for other,d in groups.items():
            if other[0] and other[1:]==key[1:]:rolled.update(d)
        require(c==rolled,"player rollup")
    basefields="player_id player_name scope season_start_year stage".split()
    emit(a.out/"all_scope_totals.csv",basefields+"pairs pair_dontsuka rate_pct unknown_pairs unknown_pair_dontsuka".split(),allrows)
    for name,rs in (("visible",visrows),("wall",wallrows),("combined_9",combrows)):
        emit(a.out/(name+".csv"),basefields+"classification draws dontsuka rate_pct composition_denominator composition_pct rate_status composition_status".split(),rs)
    jsonout(a.out/"examples.json",examples)
    jsonout(a.out/"summary.json",dict(counts=dict(counts),existing_wait_audit=dict(audit),run_ids=sorted(runs),commits=sorted(commits),status="computed_pending_discrepancy_review_and_independent_audit",rounds=len(k_ids),draws=len(d_ids)))
    print(js(dict(counts)))
if __name__=="__main__":main()
