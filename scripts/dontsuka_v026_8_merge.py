"""Stage 8 merge: recompute counts and condition-specific player-round outcomes."""
import argparse,csv,gzip,json,hashlib
from pathlib import Path
from collections import defaultdict,Counter
from itertools import product
from dontsuka_v026_8_core import TENPAI,require,rate
from dontsuka_v026_8 import INPUTS,conditions
from dontsuka_v026_2b_replay import DB_SHA
from dontsuka_v026_6 import js,jsonout

LABELS=["self_earlier","self_later"]+[f"{r}:{a}:{b}" for r,a,b in product(("self_earlier","self_later"),sorted(TENPAI),sorted(TENPAI))]+["chase_riichi","later_damaten","later_open","prior_damaten","prior_open","first_reach_all_opponents_candidate","first_reach_tenpai_opponents_candidate"]
def read(p):
    with gzip.open(p,"rt",encoding="utf-8") as f:
        for line in f:yield json.loads(line)
def write(f,r):f.write(js(r)+"\n")
def filehash(p):
    with p.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()
def dims(r):
    p=str(r["player_id"]);y=str(r["season_start_year"]);s=r["stage"]
    for x in ("",p):
        for d in (("all","",""),("season",y,""),("stage","",s),("season_stage",y,s)):
            yield (x,*d)
def dimrow(k,names):
    p,scope,y,s=k
    return dict(player_id=p,player_name=names.get(p,"全選手"),scope=scope,season_start_year=y,stage=s)
def csvout(p,fields,rs):
    with p.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rs)
def classify_round(rows):
    r=rows[0];actual=r["actual_ron"];win=r["self_win"];net=r["kyoku_net"]
    require(all((x["actual_ron"],x["self_win"],x["kyoku_net"],x["actual_ron_ids"],x["approved_round_ron_class"])==(actual,win,net,r["actual_ron_ids"],r["approved_round_ron_class"]) for x in rows),"round outcome mismatch")
    links=[l for x in rows for l in x["origin_links"]]
    rel={l["relation"] for l in links}
    if not actual:require(not links,"link without ron");category="no_ron"
    else:
        require(set(str(l["ron_event_id"]) for l in links)==set(map(str,r["actual_ron_ids"])),"condition origin ron coverage")
        category=next((x for x in ("special_excluded","immediate","subsequent","same_type_after_end_unclassified","different_tile") if x in rel),"unclassified")
    return dict(actual_ron=actual,self_win=win,kyoku_net=net,condition_ron_class=category,
                approved_round_ron_class=r["approved_round_ron_class"],actual_ron_ids=r["actual_ron_ids"],
                origin_keys=[[x["draw_event_id"],x["target_id"]] for x in rows],
                same_target_ron=int(any(l["relation"] in ("immediate","subsequent") and int(l["same_target"]) for l in links)))
def startkey(i):return (0,0) if i["initial"] else (1,i["start_event_order"])
def check_ref(info,ky,p,order,intervals):
    iid=info["interval_id"]
    if info["state"] not in TENPAI:
        require(not iid,"non-tenpai interval");return None
    require(iid in intervals,"missing interval");i=intervals[iid]
    require((i["kyoku_id"],i["player_id"],i["start_event_id"],i["start_event_order"],int(i["start_known"]))==(ky,p,info["start_event_id"],info["start_order"],info["start_known"]),"interval key attributes")
    require(i["start_event_order"]<order or not i["start_known"] and i["start_event_order"]==order,"future interval")
    require(order<i["end_event_order"],"draw at/after interval end")
    observations=[x for x in i["states"] if x["event_order"]<order or not i["start_known"] and x["event_order"]==order]
    require(bool(observations) and (observations[-1]["state"],observations[-1]["waits"])==(info["state"],info["waits"]),"historical state mismatch")
    return i
def main():
    ap=argparse.ArgumentParser();ap.add_argument("shards_dir",type=Path);ap.add_argument("out",type=Path);ap.add_argument("--shards",type=int,required=True);a=ap.parse_args()
    a.out.mkdir(parents=True,exist_ok=True)
    paths=sorted(x for x in a.shards_dir.iterdir() if x.is_dir());require(len(paths)==a.shards,"shards")
    rounds=set();draws=set();pairids=set();originids=set();reachids=set();interval_ids=set();games=set();shardids=set();runs=set();commits=set();names={};examples={};counts=Counter();metrics=defaultdict(Counter);combos=Counter();scopes=set();firstmetrics=defaultdict(Counter);special=Counter()
    with gzip.open(a.out/"all_draws.jsonl.gz","wt",encoding="utf-8") as df,gzip.open(a.out/"opponent_details.jsonl.gz","wt",encoding="utf-8") as pf,gzip.open(a.out/"tenpai_intervals.jsonl.gz","wt",encoding="utf-8") as itf,gzip.open(a.out/"reach_history.jsonl.gz","wt",encoding="utf-8") as rf,gzip.open(a.out/"condition_player_rounds.jsonl.gz","wt",encoding="utf-8") as cf,gzip.open(a.out/"exceptions.jsonl.gz","wt",encoding="utf-8") as xf:
        for path in paths:
            m=json.loads((path/"manifest.json").read_text());s=json.loads((path/"summary.json").read_text())
            require(set(m)=={x.name for x in path.iterdir() if x.is_file() and x.name!="manifest.json"},"shard file set")
            for n,h in m.items():require(filehash(path/n)==h,"shard hash "+n)
            require(not s["limited"] and s["shards"]==a.shards and s["shard"] not in shardids and s["database_sha256"]==DB_SHA and s["inputs"]==INPUTS,"shard metadata")
            shardids.add(s["shard"]);runs.add(s["run_id"]);commits.add(s["commit"])
            ks=set(s["kyoku_ids"]);require(len(ks)==len(s["kyoku_ids"]) and not ks&rounds,"round overlap");rounds.update(ks)
            nm=json.loads((path/"names.json").read_text());require(not names or names==nm,"player map");names=nm
            for k,v in json.loads((path/"examples.json").read_text()).items():examples.setdefault(k,v)
            loc=Counter();intervals={};byplayer=defaultdict(list);reachhist=defaultdict(dict);localdraws={};obs=defaultdict(list);targetobs=defaultdict(dict);roundconditions=defaultdict(list);loc_rounds=set()
            for i in read(path/"intervals.jsonl.gz"):
                iid=i["interval_id"];require(iid not in interval_ids and i["kyoku_id"] in ks,"interval identity");interval_ids.add(iid);intervals[iid]=i
                require(i["start_event_order"]<=i["end_event_order"] and i["end_event_id"] is not None,"interval closure")
                require(all(x["event_order"]<=y["event_order"] for x,y in zip(i["states"],i["states"][1:])),"state sequence")
                byplayer[i["kyoku_id"],i["player_id"]].append(i)
                loc["intervals"]+=1;loc["uncertain_intervals"]+=not i["start_known"];loc["hit_intervals"]+=i["first_hit_event_id"] is not None
                for k in dims(i):
                    q=firstmetrics[k];q["intervals"]+=1;q["onset_unknown"]+=not i["start_known"];q["observed_draws"]+=i["draw_count"]
                    if i["first_hit_draw_number"] is None:q["no_hit"]+=1
                    else:
                        q["hit"]+=1
                        if i["start_known"]:
                            q["known_hit"]+=1;q["first_draw_sum"]+=i["first_hit_draw_number"]
                if not i["start_known"]:write(xf,dict(kind="uncertain_interval_onset",detail=i))
                write(itf,i)
            for v in byplayer.values():
                v.sort(key=lambda x:x["start_event_order"])
                require(all(x["end_event_order"]<=y["start_event_order"] for x,y in zip(v,v[1:])),"interval overlap")
            for r in read(path/"reaches.jsonl.gz"):
                rid=r["marker_event_id"];require(rid not in reachids and r["kyoku_id"] in ks,"reach marker duplicate");reachids.add(rid)
                require(r["marker_order"]<=r["declaration_order"],"marker future")
                loc["reach_declarations"]+=1;loc["accepted_reaches"]+=r["accepted"]
                if r["accepted"]:
                    require(r["established_event_id"]==r["declaration_event_id"] and r["established_order"]==r["declaration_order"],"acceptance boundary")
                    require(r["player_id"] not in reachhist[r["kyoku_id"]],"double acceptance")
                    reachhist[r["kyoku_id"]][r["player_id"]]=r
                else:require(not r["established_event_id"],"rejected reach established")
                write(rf,r)
            for r in read(path/"draws.jsonl.gz"):
                d,ky,p,o=r["draw_event_id"],r["kyoku_id"],r["player_id"],r["event_order"]
                require(d not in draws and ky in ks,"draw identity");draws.add(d);loc_rounds.add(ky);games.add(r["game_id"]);localdraws[d]=r
                dd=r["is_dontsuka"];require(dd==int(r["opponent_count"]>0),"basic unit")
                st=r["self_info"]["state"];i=check_ref(r["self_info"],ky,p,o,intervals)
                loc.update(draws=1,basic=dd);loc["state:"+st]+=1;loc["state_hit:"+st]+=dd
                if st in TENPAI:
                    loc["shoubute_tenpai"]+=int(r["shoubute_tenpai"]);loc["shoubute_tenpai_hit"]+=dd*int(r["shoubute_tenpai"])
                    vv=obs[i["interval_id"]];vv.append((d,dd));require(r["interval_draw_number"]==len(vv),"interval draw count")
                    first=dd and not any(x[1] for x in vv[:-1]);require(r["first_hit"]==int(first),"first basic hit")
                else:require(r["interval_draw_number"]=="" and not r["first_hit"],"non-tenpai first count")
                if r["physical_shanten"]=="1":
                    loc["isshanten"]+=1;loc["isshanten_hit"]+=dd;loc["shoubute_isshanten"]+=int(r["shoubute_isshanten"]);loc["shoubute_isshanten_hit"]+=dd*int(r["shoubute_isshanten"])
                if r["pre_reason"]:write(xf,dict(kind="draw_special",detail=r))
                scopes.update(dims(r));write(df,r)
            require(loc_rounds==ks,"round coverage")
            for r in read(path/"pairs.jsonl.gz"):
                d,t,p,ky,o=r["draw_event_id"],r["target_id"],r["player_id"],r["kyoku_id"],r["event_order"];key=d,t
                require(key not in pairids and d in localdraws and t!=p and str(t) in names,"pair identity");pairids.add(key)
                base=localdraws[d];require(all(r[k]==base[k] for k in ("kyoku_id","player_id","event_order","is_dontsuka","interval_draw_number","first_hit")) and r["self_info"]==base["self_info"],"pair/draw identity")
                hit=r["is_opponent_dontsuka"];require(hit in (0,1) and hit<=base["is_dontsuka"],"hit bound")
                i=check_ref(r["self_info"],ky,p,o,intervals);j=check_ref(r["target_info"],ky,t,o,intervals)
                if "unknown" in (r["self_info"]["state"],r["target_info"]["state"]):rel="undetermined_state"
                elif i and j:
                    rel="undetermined" if not (i["start_known"] and j["start_known"]) else "self_earlier" if startkey(i)<startkey(j) else "self_later" if startkey(i)>startkey(j) else "simultaneous"
                else:rel="not_both_tenpai"
                require(rel==r["relation"],"relationship recomputation")
                expected_combo=f'{rel}:{r["self_info"]["state"]}:{r["target_info"]["state"]}' if rel in ("self_earlier","self_later") else ""
                require(expected_combo==r["combination"],"18 class recomputation")
                prior={q:x for q,x in reachhist[ky].items() if x["established_order"]<o}
                first=min(prior.values(),key=lambda x:x["established_order"]) if prior else None
                require(r["first_reach_player"]==(first["player_id"] if first else "") and r["first_reach_event"]==(first["established_event_id"] if first else ""),"first reach chronology")
                require(r["self_first_reach"]==int(bool(first and first["player_id"]==p)),"first reach flag")
                for q,f in ((p,"self_reach"),(t,"target_reach")):
                    x=prior.get(q);require(r[f]["established_id"]==(x["established_event_id"] if x else ""),"reach history")
                if first and first["player_id"]==p:
                    cl="";st=r["target_info"]["state"]
                    if st=="riichi":cl="chase_riichi" if t in prior and prior[t]["established_order"]>first["established_order"] else "undetermined_reach_order"
                    elif st in ("damaten","open"):
                        cl="undetermined_tenpai_onset" if not j or not j["start_known"] else "prior_"+st if j["initial"] or j["start_event_order"]<first["established_order"] else "later_"+st if j["start_event_order"]>first["established_order"] else "simultaneous_reach_tenpai"
                    elif st=="unknown":cl="undetermined_state"
                    require(r["first_reach_class"]==cl,"first reach class recomputation")
                else:require(not r["first_reach_class"],"not first reach")
                if hit:
                    originids.add(key);loc["opponents"]+=1;loc["rank_drop"]+=float(r["rank_drop"])>0;loc["rank_maintain"]+=float(r["rank_drop"])==0
                    if i:
                        v=targetobs[i["interval_id"]];firsttarget=t not in v
                        if firsttarget:v[t]=dict(event_id=d,draw_number=base["interval_draw_number"])
                        require(r["first_target_hit"]==int(firsttarget),"first target hit")
                if r["stage6"]:
                    loc["stage6_pairs"]+=1;loc["stage6_valid"]+=int(r["stage6"]["applicable"]);loc["stage6_valid_hit"]+=int(r["stage6"]["applicable"])*hit
                if expected_combo:loc["strict_pairs"]+=1;loc["strict_hit"]+=hit
                elif i and j:loc["non_strict_both"]+=1;loc["non_strict_both_hit"]+=hit
                require(r["conditions"]==conditions(r),"condition labels")
                for cond in r["conditions"]:
                    require(cond in LABELS,"unknown label")
                    for k in dims(r):
                        m=metrics[k,cond];m["denominator"]+=1;m["numerator"]+=hit
                        if hit:
                            for label,value in (("rank_drop",str(int(float(r["rank_drop"])>0))),("shoubute_tenpai",str(r["shoubute_tenpai"])),("shoubute_isshanten",str(r["shoubute_isshanten"])),("wait_comparison",r["stage6"].get("combined") or "not_applicable")):
                                combos[k,cond,label,value]+=1
                            combos[k,cond,"joint",js([int(float(r["rank_drop"])>0),r["shoubute_tenpai"],r["shoubute_isshanten"],r["stage6"].get("combined") or "not_applicable"])]+=1
                    if hit:roundconditions[cond,ky,p].append(r)
                if rel in ("undetermined","undetermined_state","simultaneous") or r["first_reach_class"].startswith("undetermined") or r["first_reach_class"]=="simultaneous_reach_tenpai":
                    special[(rel,r["first_reach_class"])]+=1;write(xf,dict(kind="pair_boundary",detail=r))
                write(pf,r)
            for iid,i in intervals.items():
                v=obs[iid];require(len(v)==i["draw_count"],"interval draw total")
                first=next(((d,n) for n,(d,h) in enumerate(v,1) if h),(None,None))
                require(first==(i["first_hit_event_id"],i["first_hit_draw_number"]),"interval first hit recomputation")
                require({str(k):v for k,v in targetobs[iid].items()}==i["first_target_hits"],"interval first target recomputation")
            for (cond,ky,p),rr in roundconditions.items():
                outcome=classify_round(rr);r=rr[0];data=dict(condition=cond,kyoku_id=ky,player_id=p,game_id=r["game_id"],season_start_year=r["season_start_year"],stage=r["stage"],**outcome)
                write(cf,data)
                for k in dims(r):
                    m=metrics[k,cond];m["hit_rounds"]+=1;m["ron_rounds"]+=outcome["actual_ron"];m["win_rounds"]+=outcome["self_win"];m["net_sum"]+=outcome["kyoku_net"];m["ron_"+outcome["condition_ron_class"]]+=1
            for k,v in loc.items():require(v==s["counts"].get(k,0),"shard count "+k)
            counts.update(loc)
    require(shardids==set(range(a.shards)) and len(runs)==len(commits)==1,"shard/run identity")
    require((len(rounds),len(games),len(names),len(draws),len(originids))==(25238,2068,56,1257732,28060),"scope")
    expected={"draws":1257732,"basic":27578,"opponents":28060,"rank_drop":13170,"rank_maintain":14890,"accepted_reaches":22205,"state:riichi":90653,"state_hit:riichi":2838,"state:damaten":21201,"state_hit:damaten":893,"state:open":49936,"state_hit:open":1965,"state:not_tenpai":1095809,"state_hit:not_tenpai":21881,"state:unknown":133,"state_hit:unknown":1,"shoubute_tenpai":97757,"shoubute_tenpai_hit":3449,"isshanten":299220,"isshanten_hit":8956,"shoubute_isshanten":231765,"shoubute_isshanten_hit":7077,"stage6_pairs":109425,"stage6_valid":109273,"stage6_valid_hit":5785}
    for k,v in expected.items():require(counts[k]==v,"approved total "+k)
    allkey=("","all","","")
    require(sum(metrics[allkey,c]["denominator"] for c in LABELS if c.count(":")==2)==counts["strict_pairs"],"18 denominator")
    require(sum(metrics[allkey,c]["numerator"] for c in LABELS if c.count(":")==2)==counts["strict_hit"],"18 numerator")
    require(counts["strict_pairs"]+counts["non_strict_both"]==counts["stage6_valid"],"both-tenpai coverage")
    require(counts["strict_hit"]+counts["non_strict_both_hit"]==counts["stage6_valid_hit"],"both-tenpai hit coverage")
    out=[]
    for k in sorted(scopes):
        for cond in LABELS:
            m=metrics[k,cond];n,d,r=m["numerator"],m["denominator"],m["hit_rounds"]
            require(0<=n<=d and 0<=m["ron_rounds"]<=r<=n and 0<=m["win_rounds"]<=r,"aggregate bounds")
            require(sum(v for x,v in m.items() if x.startswith("ron_") and x!="ron_rounds")==r,"conditional ron classes")
            parent="self_earlier" if cond.startswith("self_earlier:") else "self_later" if cond.startswith("self_later:") else ""
            composition_d=metrics[k,parent]["numerator"] if parent else sum(metrics[k,x]["numerator"] for x in ("self_earlier","self_later")) if cond in ("self_earlier","self_later") else metrics[k,"first_reach_all_opponents_candidate"]["numerator"]
            out.append(dict(**dimrow(k,names),condition=cond,definition_status="candidate_unconfirmed" if cond.endswith("_candidate") else "computed_pending_audit",numerator=n,denominator=d,rate_pct=rate(n,d),composition_numerator=n,composition_denominator=composition_d,composition_pct=rate(n,composition_d) if n<=composition_d else "",hit_rounds=r,ron_rounds=m["ron_rounds"],ron_rate_pct=rate(m["ron_rounds"],r),win_rounds=m["win_rounds"],win_rate_pct=rate(m["win_rounds"],r),net_sum=m["net_sum"],mean_net="" if not r else f'{m["net_sum"]/r:.9f}',**{"ron_"+x:m["ron_"+x] for x in ("immediate","subsequent","different_tile","no_ron","special_excluded","same_type_after_end_unclassified","unclassified")}))
    csvout(a.out/"condition_summary.csv",list(out[0]),out)
    comp=[dict(**dimrow(k,names),condition=c,dimension=f,value=v,overlap_hits=n) for (k,c,f,v),n in sorted(combos.items())]
    if comp:csvout(a.out/"compound_summary.csv",list(comp[0]),comp)
    first=[dict(**dimrow(k,names),**{x:v[x] for x in ("intervals","onset_unknown","observed_draws","no_hit","hit","known_hit","first_draw_sum")},mean_first_draw="" if not v["known_hit"] else f'{v["first_draw_sum"]/v["known_hit"]:.9f}') for k,v in sorted(firstmetrics.items())]
    if first:csvout(a.out/"first_hit_summary.csv",list(first[0]),first)
    jsonout(a.out/"examples.json",examples)
    jsonout(a.out/"summary.json",dict(status="computed_pending_independent_audit",counts=dict(counts),approved_expected=expected,run_ids=list(runs),commits=list(commits),database_sha256=DB_SHA,inputs=INPUTS,rounds=len(rounds),draws=len(draws),pair_detail_rows=len(pairids),condition_rows=len(out),boundary_counts=[dict(relation=k[0],first_reach_class=k[1],count=v) for k,v in sorted(special.items())],first_reach_general_denominator_status="candidate_only"))
    print(js(dict(counts)))
if __name__=="__main__":main()
