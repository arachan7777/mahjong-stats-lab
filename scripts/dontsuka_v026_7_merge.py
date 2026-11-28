"""Stage 7 independent shard merge and descriptive counts."""
import argparse,csv,gzip,json,hashlib
from pathlib import Path
from collections import Counter,defaultdict
from dontsuka_v026_7 import FIELDS,PAIR,pct
from dontsuka_v026_7_core import require,movement
from dontsuka_v026_6 import js,jsonout
from dontsuka_v026_extract import sha256_file

def read(p):
    with gzip.open(p,"rt",encoding="utf-8",newline="") as f:yield from csv.DictReader(f)
def writer(f,fields):
    w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");w.writeheader();return w
def emit(p,fields,rs):
    with p.open("w",encoding="utf-8-sig",newline="") as f:writer(f,fields).writerows(rs)
def dims(r):
    y,s=r["season_start_year"],r["stage"]
    for d in (("all","",""),("season",y,""),("stage","",s),("season_stage",y,s)):
        yield ("",*d);yield (r["player_id"],*d)
def dimrow(k,names):
    p,s,y,t=k;return dict(player_id=p,player_name=names.get(p,"全選手"),scope=s,season_start_year=y,stage=t)
def valid_draw(r):
    dd=int(r["is_dontsuka"]);require(dd in (0,1) and dd==int(int(r["opponent_count"])>0),"draw flag")
    st=r["pre_state"];require(st in ("riichi","damaten","open","not_tenpai","unknown"),"four states")
    a=dict(shanten=int(r["pre_shanten"]) if r["pre_shanten"] else "",reason=r["pre_reason"])
    if st in ("riichi","damaten","open"):require(a["shanten"]==0 and not a["reason"],"tenpai")
    if st=="unknown":require(a["shanten"]=="" and a["reason"] in ("few_tiles","many_tiles"),"unknown pre")
    if int(r["has_discard"]):
        require(int(r["discard_order"])>int(r["event_order"]) and r["discard_event_id"] and r["link_reason"]=="discard","time")
        b=dict(shanten=int(r["post_shanten"]) if r["post_shanten"] else "",reason=r["post_reason"])
        d,m,why=movement(a,b)
        require((str(d),m,why)==(r["shanten_delta"],r["movement"],r["movement_reason"]),"movement calculation")
        require(not r["terminal_or_next_event_id"],"discard has terminal substitute")
        if r["tsumogiri"]=="1":require(r["draw_tile"]==r["discard_tile"],"tsumogiri mismatch")
    else:
        require(not r["discard_event_id"] and r["movement"]=="no_discard" and r["link_reason"]!="discard","no discard")
        require(int(r["terminal_or_next_order"])>int(r["event_order"]),"terminal time")
def valid_pair(r):
    require(r["is_opponent_dontsuka"]=="1" and r["target_id"]!=r["player_id"],"pair flag")
    if r["has_discard"]=="0":
        require(r["genbutsu"]=="" and r["genbutsu_reason"]=="no_corresponding_discard","no discard pair")
        return "no_discard"
    v=r["genbutsu"]
    require(v in ("0","1"),"genbutsu value")
    if v=="1":
        require(int(r["evidence_order"])<int(r["discard_order"]) and r["evidence_event_id"],"future evidence")
        if r["genbutsu_reason"]=="target_own_discard":require(r["evidence_player_id"]==r["target_id"],"own evidence")
        else:require(r["genbutsu_reason"]=="passed_after_accepted_reach" and r["target_accepted_before"]=="1" and r["target_reach_declaration_id"] and r["evidence_player_id"]!=r["target_id"],"passed evidence")
    else:require(r["genbutsu_reason"]=="no_prior_qualifying_discard" and not r["evidence_event_id"],"non-genbutsu evidence")
    return "genbutsu" if v=="1" else "non_genbutsu"
def main():
    p=argparse.ArgumentParser();p.add_argument("shards_dir",type=Path);p.add_argument("out",type=Path);p.add_argument("--shards",type=int,required=True);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    paths=sorted(x for x in a.shards_dir.iterdir() if x.is_dir());require(len(paths)==a.shards,"shard count")
    counts=Counter();names={};round_ids=set();draw_ids=set();discard_ids=set();pair_ids=set();ron_ids=set();shard_ids=set();examples={};runs=set();commits=set();games=set()
    gdraw=defaultdict(Counter);gpair=defaultdict(Counter);gbasic=defaultdict(Counter);gmove=defaultdict(Counter)
    with gzip.open(a.out/"all_draws.csv.gz","wt",encoding="utf-8",newline="") as f,gzip.open(a.out/"dontsuka_draws.csv.gz","wt",encoding="utf-8",newline="") as g,gzip.open(a.out/"no_discard_and_not_applicable.csv.gz","wt",encoding="utf-8",newline="") as h,gzip.open(a.out/"opponent_genbutsu.csv.gz","wt",encoding="utf-8",newline="") as j,gzip.open(a.out/"ron_audit.csv.gz","wt",encoding="utf-8",newline="") as z:
        dw=writer(f,FIELDS);bw=writer(g,FIELDS);xw=writer(h,FIELDS);pw=writer(j,FIELDS+PAIR);rw=None
        for path in paths:
            m=json.loads((path/"manifest.json").read_text());s=json.loads((path/"summary.json").read_text())
            require(set(m)=={x.name for x in path.iterdir() if x.is_file() and x.name!="manifest.json"},"manifest members")
            for n,v in m.items():require(sha256_file(path/n)==v,"shard hash "+n)
            require(not s["limited"] and s["shards"]==a.shards and s["shard"] not in shard_ids,"shard identity")
            shard_ids.add(s["shard"]);runs.add(s["run_id"]);commits.add(s["commit"])
            ks=set(s["kyoku_ids"]);require(len(ks)==len(s["kyoku_ids"]) and not ks&round_ids,"round overlap");round_ids.update(ks)
            nm=json.loads((path/"names.json").read_text());require(not names or names==nm,"name map");names=nm
            for k,v in json.loads((path/"examples.json").read_text()).items():examples.setdefault(k,v)
            local=Counter();localdraws={};hitrows={};seen_rounds=set()
            for r in read(path/"draws.csv.gz"):
                eid=int(r["draw_event_id"]);ky=int(r["kyoku_id"]);require(eid not in draw_ids and ky in ks,"draw overlap");draw_ids.add(eid);seen_rounds.add(ky);games.add(r["game_id"])
                valid_draw(r);dd=int(r["is_dontsuka"]);opp=int(r["opponent_count"])
                if r["has_discard"]=="1":
                    did=r["discard_event_id"];require(did not in discard_ids,"discard reused");discard_ids.add(did)
                if dd:hitrows[eid]=r;bw.writerow(r)
                if r["movement"] in ("not_applicable","no_discard"):xw.writerow(r)
                localdraws[eid]=opp;dw.writerow(r)
                local.update(draws=1,basic=dd,opponents=opp,pre_unknown=r["pre_state"]=="unknown",tenpai=r["pre_state"] in ("riichi","damaten","open"),tenpai_dontsuka=dd*(r["pre_state"] in ("riichi","damaten","open")),isshanten=r["pre_shanten"]=="1",isshanten_dontsuka=dd*(r["pre_shanten"]=="1"))
                local["link_"+r["link_reason"]]+=1;local["movement_"+r["movement"]]+=1
                for key in dims(r):
                    gd=gdraw[key];gd["draws"]+=1;gd["basic"]+=dd
                    for name,cl in (("tenpai4",r["pre_state"]),("shanten",r["pre_shanten"] if r["pre_shanten"] else "unknown")):
                        if name=="shanten" and r["pre_reason"]=="structural_no_physical_wait":cl="structural_no_physical_wait"
                        gd[(name,cl,"n")]+=1;gd[(name,cl,"d")]+=dd
                    mkey=(r["movement"],r["link_reason"])
                    gmove[key][(*mkey,"n")]+=1;gmove[key][(*mkey,"d")]+=dd
                    if dd:gbasic[key][(r["discard_kind"] or "no_discard",r["movement"])]+=1
            require(seen_rounds==ks,"round coverage")
            for r in read(path/"opponents.csv.gz"):
                eid,t=int(r["draw_event_id"]),r["target_id"];require((eid,t) not in pair_ids and t in names and eid in hitrows,"pair key");pair_ids.add((eid,t))
                require(all(r[k]==hitrows[eid][k] for k in FIELDS),"pair base fields")
                localdraws[eid]-=1;require(localdraws[eid]>=0,"pair overcount")
                v=valid_pair(r);pw.writerow(r)
                local["gen_"+("1" if v=="genbutsu" else "0" if v=="non_genbutsu" else "no_discard")]+=1
                for key in dims(r):gpair[key][(r["movement"],v)]+=1
            require(not any(localdraws.values()),"pair undercount")
            for r in read(path/"ron_audit.csv.gz"):
                rid=r["ron_event_id"];require(rid not in ron_ids,"duplicate actual ron");ron_ids.add(rid)
                if rw is None:rw=writer(z,list(r))
                rw.writerow(r);local["4a_ron"]+=1
                local["4a_immediate_links"]+=int(r["immediate_origin_rows"]) if r["category"]=="immediate" else 0
            for k,v in local.items():require(v==s["counts"].get(k,0),"shard count "+k)
            counts.update(s["counts"])
    require(shard_ids==set(range(a.shards)) and len(runs)==len(commits)==1,"run IDs")
    require((len(round_ids),len(draw_ids),len(games),len(names),len(pair_ids),len(ron_ids))==(25238,1257732,2068,56,28060,11031),"scope")
    require(tuple(counts[k] for k in ("draws","basic","opponents","pre_unknown","tenpai","tenpai_dontsuka","isshanten","isshanten_dontsuka","stage6_comparison","stage6_valid","stage6_valid_hit"))==(1257732,27578,28060,133,161790,5696,299220,8956,109425,109273,5785),"approved totals")
    require(sum(counts[k] for k in counts if k.startswith("link_"))==counts["draws"],"link totals")
    require(counts["gen_0"]+counts["gen_1"]+counts["gen_no_discard"]==counts["opponents"],"genbutsu totals")
    bases=[];state_rows=[];move_rows=[];basic_rows=[];pair_rows=[]
    for key,d in sorted(gdraw.items()):
        base=dimrow(key,names);bases.append(dict(base,draws=d["draws"],basic=d["basic"],classified_draws=d["draws"]-d[("tenpai4","unknown","n")],excluded=d[("tenpai4","unknown","n")]))
        for name,cls in (("tenpai4",("riichi","damaten","open","not_tenpai","unknown")),("shanten",tuple(str(i) for i in range(9))+("structural_no_physical_wait","unknown"))):
            ns=ds=0
            for cl in cls:
                n,dd=d[(name,cl,"n")],d[(name,cl,"d")];require(0<=dd<=n,"numerator bound");ns+=n;ds+=dd
                rate=pct(dd,n) if name=="tenpai4" and cl!="unknown" or name=="shanten" and cl in ("0","1") else ""
                state_rows.append(dict(base,dimension=name,classification=cl,draws=n,dontsuka=dd,rate_pct=rate,rate_status="not_defined" if name=="shanten" and cl not in ("0","1") or cl=="unknown" else "defined" if n else "undefined"))
            require((ns,ds)==(d["draws"],d["basic"]),"state partition")
        for cl,n in sorted(gmove[key].items()):
            mv,reason,kind=cl
            if kind=="n":move_rows.append(dict(base,movement=mv,link_reason=reason,draws=n,dontsuka=gmove[key][(mv,reason,"d")]))
        require(sum(v for k,v in gmove[key].items() if k[-1]=="n")==d["draws"],"movement partition")
        require(sum(gbasic[key].values())==d["basic"],"basic partition")
        for (kind,mv),n in sorted(gbasic[key].items()):basic_rows.append(dict(base,discard_kind=kind,movement=mv,count=n))
        for (mv,gen),n in sorted(gpair[key].items()):pair_rows.append(dict(base,movement=mv,genbutsu=gen,count=n))
        if not key[0]:
            for group in (gdraw,gmove,gbasic,gpair):
                total=Counter()
                for k,v in group.items():
                    if k[0] and k[1:]==key[1:]:total.update(v)
                require(total==group[key],"player rollup")
    allkey=("","all","","");require(sum(gpair[allkey].values())==28060,"pair aggregate")
    bfields="player_id player_name scope season_start_year stage".split()
    emit(a.out/"all_scope_totals.csv",bfields+"draws basic classified_draws excluded".split(),bases)
    emit(a.out/"shanten_and_tenpai4.csv",bfields+"dimension classification draws dontsuka rate_pct rate_status".split(),state_rows)
    emit(a.out/"movement.csv",bfields+"movement link_reason draws dontsuka".split(),move_rows)
    emit(a.out/"basic_discard_movement.csv",bfields+"discard_kind movement count".split(),basic_rows)
    emit(a.out/"opponent_movement_genbutsu.csv",bfields+"movement genbutsu count".split(),pair_rows)
    jsonout(a.out/"examples.json",examples)
    jsonout(a.out/"summary.json",dict(status="computed_pending_independent_audit",counts=dict(counts),rounds=len(round_ids),draws=len(draw_ids),run_ids=sorted(runs),commits=sorted(commits)))
    print(js(dict(counts)))
if __name__=="__main__":main()
