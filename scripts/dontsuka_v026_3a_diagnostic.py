"""Stage 3A diagnostic only: compare snapshot wait-matrix yaku with independent replay.
Previous interrupted program / event-level results are unavailable. Alternative
calculations below are sensitivity checks, not a reconstruction of that program."""
import csv,io,json,zipfile,argparse,os
from pathlib import Path
from collections import Counter,defaultdict
from dontsuka_v026_extract import connect_readonly,verify_database,sha256_file
from dontsuka_v026_2b_replay import DB_SHA,RELEASE
from dontsuka_v026_2a_audit import score
from dontsuka_v026_3a import settlement,normal
SOURCE_SHA="da593920add867904fc82f8f51207a6fe318fa42a2945e1880c5653112fe4ce1"
EXCLUDED={"裏ドラ","カン裏","一発","搶槓","槍槓","海底摸月","海底撈月","河底撈魚","嶺上開花","天和","地和","門前清自摸和"}
YAKUMAN={"国士無双","九蓮宝燈","四暗刻","大三元","小四喜","大四喜","緑一色","四槓子","字一色","清老頭"}
def js(v):return json.dumps(v,ensure_ascii=False,sort_keys=True)
def main():
    p=argparse.ArgumentParser();p.add_argument("db",type=Path);p.add_argument("source",type=Path);p.add_argument("out",type=Path);a=p.parse_args()
    a.out.mkdir(parents=True,exist_ok=True)
    c=connect_readonly(a.db);m=verify_database(c,RELEASE)
    assert sha256_file(a.db)==DB_SHA and sha256_file(a.source)==SOURCE_SHA
    z=zipfile.ZipFile(a.source);assert z.testzip() is None
    sm=json.loads(z.read("manifest.json"))
    import hashlib
    for n,h in sm["outputs"].items():
        with z.open(n) as f:assert hashlib.file_digest(f,"sha256").hexdigest()==h
    counts=Counter();kinds=Counter();diffs=[];allrows=[];examples={};traces=[];raw_counts=Counter()
    with z.open("opponent_hypothetical_all.csv") as f,io.TextIOWrapper(f,encoding="utf-8-sig") as t:
        for r in csv.DictReader(t):
            eid=int(r["draw_event_id"]);target=int(r["target"]);drawer=int(r["drawer"]);tile=r["tile"]
            q=c.execute("""SELECT m.id,m.waiting_tile,n.name,y.han
              FROM tenpai_agari_matrix m JOIN tenpai_yaku y ON y.tenpai_agari_matrix_id=m.id
              JOIN yaku_name n ON n.id=y.yaku_name_id
              WHERE m.event_id=? AND m.player_id=? AND m.is_ron_agari=1
                AND CASE WHEN substr(m.waiting_tile,1,1)='0' THEN '5'||substr(m.waiting_tile,2) ELSE m.waiting_tile END=? ORDER BY m.id,n.name""",
              (int(r["opponent_snapshot_event_id"]),target,normal(tile))).fetchall()
            candidates=defaultdict(dict);tiles={}
            for i,w,n,h in q:candidates[i][n]=h;tiles[i]=w
            if not candidates:raise ValueError("no DB candidate "+str(eid))
            exact=[i for i,w in tiles.items() if w==tile]
            ids=exact or list(candidates)
            counts["exact_wait_row" if exact else "normalized_only"]+=1
            if len(ids)>1:counts["ambiguous_candidates"]+=1
            current=json.loads(r["yaku"]);fu=int(r["fu"]);base=int(r["ron_base"]);before={int(k):v for k,v in json.loads(r["before_scores"]).items()}
            # Sensitivity: do not correct red status in DB snapshot; not old implementation.
            raw_filtered={n:h for n,h in candidates[ids[0]].items() if n not in EXCLUDED}
            raw_ym=set(raw_filtered)&YAKUMAN
            if raw_ym:raw_filtered={n:raw_filtered[n] for n in raw_ym}
            raw_base=score(sum(raw_filtered.values()),fu,False,r["target_wind"]=="1z",len(raw_ym))
            raw_drop=settlement(before,drawer,target,raw_base,int(r["honba"]),int(r["sticks"]))["rank_drop"]
            raw_counts["rows"]+=1;raw_counts["down"]+=raw_drop>0;raw_counts["head_down"]+=int(r["head_selected"]) and raw_drop>0
            raw_counts["base_difference"]+=raw_base!=base;raw_counts["rank_class_difference"]+=(raw_drop>0)!=(float(r["rank_drop"])>0)
            # All matched DB rows retained. Exact row preferred, otherwise adjust red status
            # to actual drawn tile; no arbitrary choice if multiple distinct rows remain.
            variants=[]
            for i in ids:
                raw=candidates[i];filtered={n:h for n,h in raw.items() if n not in EXCLUDED}
                if tiles[i]!=tile:
                    red=filtered.get("赤ドラ",0)+int(tile[0]=="0")-int(tiles[i][0]=="0")
                    if red>0:filtered["赤ドラ"]=red
                    else:filtered.pop("赤ドラ",None)
                # Yakuman suppresses unrelated yaku/dora in the scoring path.
                ym=set(filtered)&YAKUMAN
                if ym:filtered={n:filtered[n] for n in ym}
                if not set(filtered)-{"ドラ","赤ドラ"}:
                    variants.append(dict(id=i,waiting_tile=tiles[i],raw=raw,filtered=filtered,error="no ordinary yaku"));continue
                try:
                    han=sum(filtered.values())
                    alt=score(han,fu,False,r["target_wind"]=="1z",len(ym))
                    drop=settlement(before,drawer,target,alt,int(r["honba"]),int(r["sticks"]))["rank_drop"]
                    variants.append(dict(id=i,waiting_tile=tiles[i],raw=raw,filtered=filtered,han=han,base=alt,rank_drop=drop))
                except Exception as ex:variants.append(dict(id=i,waiting_tile=tiles[i],raw=raw,filtered=filtered,error=repr(ex)))
            # Comparison is a diagnostic with current independent fu, not an assertion of previous code.
            valid=[v for v in variants if "base" in v]
            unique={(v["base"],v["rank_drop"]) for v in valid}
            row=dict(draw_event_id=eid,target=target,tile=tile,head_selected=int(r["head_selected"]),snapshot_event_id=int(r["opponent_snapshot_event_id"]),current_yaku=js(current),current_han=int(r["han"]),current_fu=fu,current_base=base,current_rank_drop=float(r["rank_drop"]),matrix_candidates=js([{"id":i,"tile":tiles[i],"yaku":y} for i,y in candidates.items()]),diagnostic_variants=js(variants))
            counts["rows"]+=1
            counts["current_down"]+=float(r["rank_drop"])>0
            counts["current_head_down"]+=int(r["head_selected"]) and float(r["rank_drop"])>0
            if len(unique)==1 and len(valid)==len(variants):
                alt,drop=next(iter(unique));row.update(matrix_base=alt,matrix_rank_drop=drop,status="compared")
                counts["compared"]+=1;counts["matrix_down"]+=drop>0;counts["matrix_head_down"]+=int(r["head_selected"]) and drop>0
                if alt!=base:counts["base_difference"]+=1
                if (drop>0)!=(float(r["rank_drop"])>0):counts["rank_class_difference"]+=1;counts["head_rank_class_difference"]+=int(r["head_selected"])
                tags=[]
                for v in valid:
                    tags.extend(n for n in set(v["filtered"])|set(current) if v["filtered"].get(n,0)!=current.get(n,0))
                if tags:
                    counts["yaku_difference"]+=1;kinds.update(set(tags))
                    # Verify chronological indicator delta at the snapshot versus draw.
                    snap=int(r["opponent_snapshot_event_id"])
                    db_events=[dict(x) for x in c.execute("""SELECT e.id,e.type,e.event_order,di.dora_indicator_tile,di.dora_type
                      FROM event e LEFT JOIN dora_indicator_event di ON di.event_id=e.id
                      WHERE e.kyoku_id=? ORDER BY e.event_order,e.id""",(int(r["kyoku_id"]),))]
                    orders={x["id"]:x["event_order"] for x in db_events}
                    so,do=orders[snap],orders[eid]
                    old=[x for x in db_events if x["dora_type"]=="omote" and x["event_order"]<=so]
                    added=[x for x in db_events if x["dora_type"]=="omote" and so<x["event_order"]<do]
                    new=[x for x in db_events if x["dora_type"]=="omote" and x["event_order"]<do]
                    htiles=json.loads(r["concealed_before"])+[tile]+[t for _,b in json.loads(r["melds"]) for t in b]
                    def next_tile(ind):
                        n,s=normal(ind);v=int(n)
                        return str((v%9+1) if s!="z" else (v%4+1) if v<=4 else (5+(v-5+1)%3))+s
                    new_dora=sum(sum(normal(t)==next_tile(x["dora_indicator_tile"]) for t in htiles) for x in new)
                    old_dora=sum(sum(normal(t)==next_tile(x["dora_indicator_tile"]) for t in htiles) for x in old)
                    expected_delta=new_dora-old_dora
                    observed_delta=current.get("ドラ",0)-valid[0]["filtered"].get("ドラ",0)
                    verified=(set(tags)=={"ドラ"} and expected_delta==observed_delta and new_dora==current.get("ドラ",0) and [x["dora_indicator_tile"] for x in new]==json.loads(r["omote"]) and bool(added))
                    counts["indicator_timing_explained"]+=verified
                    traces.append(dict(draw_event_id=eid,target=target,kyoku_id=int(r["kyoku_id"]),snapshot_event_id=snap,snapshot_order=so,draw_order=do,old_indicators=old,added_indicators=added,current_indicators=new,hand_tiles=htiles,expected_delta=expected_delta,observed_delta=observed_delta,verified=verified,current_base=base,matrix_base=alt,current_rank_drop=float(r["rank_drop"]),matrix_rank_drop=drop))
                row["different_yaku"]=js(sorted(set(tags)))
                if alt!=base or tags or drop!=float(r["rank_drop"]):diffs.append(row.copy())
            else:
                row["status"]="unresolved_matrix_variant";counts["unresolved_matrix_variant"]+=1;diffs.append(row.copy())
            allrows.append(row)
    fields=list(dict.fromkeys(k for r in allrows for k in r))
    for name,rr in [("matrix_diagnostic_all.csv",allrows),("matrix_diagnostic_differences.csv",diffs)]:
        with (a.out/name).open("w",encoding="utf-8-sig",newline="") as f:
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rr)
    (a.out/"indicator_timing_traces.json").write_text(js(traces),encoding="utf-8")
    (a.out/"raw_matrix_sensitivity.json").write_text(js(dict(raw_counts)),encoding="utf-8")
    assert counts["rows"]==28060
    m.update(scope="3A diagnostic only",database_sha256=DB_SHA,source_zip_sha256=SOURCE_SHA,counts=dict(counts),different_yaku_counts=dict(kinds),raw_matrix_sensitivity=dict(raw_counts),prior_aggregate={"opponent_down":13228,"head_down":12990},limitations="Previous event-level output and exact implementation unavailable; matrix comparison uses independently reconstructed current fu and exact drawn tile where available. No prior values imposed.",status="diagnostic_not_previous_reproduction",run_id=os.getenv("GITHUB_RUN_ID"),commit=os.getenv("GITHUB_SHA"))
    (a.out/"manifest.json").write_text(js(m),encoding="utf-8");print(js(m))
if __name__=="__main__":main()
