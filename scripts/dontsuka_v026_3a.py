"""Stage 3A only: independent hypothetical ron at approved draw events."""
import argparse, csv, gzip, json, os, zipfile, hashlib
from collections import Counter, defaultdict
from pathlib import Path
from dontsuka_v026_extract import connect_readonly, verify_database, sha256_file, SQL_PATH
from dontsuka_v026_2a_replay import Replay, normal, tile
from dontsuka_v026_2a_audit import events, evaluate, score
from dontsuka_v026_2b_replay import ranks, DB_SHA, RELEASE

A_SHA="77a165910c731a63a52d3eda966050dddf164cd12ab0b0130979c9ce39e58a17"
B_SHA="a81dd53043b557edbccd1dcc4ab0db798a6c71db68aebbd12532272e600a2781"
EXPECTED={1:27101,2:472,3:5}
def js(x): return json.dumps(x,ensure_ascii=False,sort_keys=True)
def wind(w): return int(w[0])-1
def distance(winds, drawer, target):
    d=(wind(winds[target])-wind(winds[drawer]))%4
    if not d: raise ValueError("same seat")
    return d
def head(winds,drawer,targets):
    return min(targets,key=lambda p:distance(winds,drawer,p))
def settlement(scores,drawer,target,base,honba,sticks):
    if len(scores)!=4 or drawer==target or base<=0 or honba<0 or sticks<0 or sum(scores.values())+1000*sticks!=100000:
        raise ValueError("invalid settlement input")
    after=dict(scores);loss=base+300*honba
    after[drawer]-=loss;after[target]+=loss+1000*sticks
    before_rank=ranks(scores);after_rank=ranks(after)
    if sum(after.values())!=100000 or sum(after_rank.values())!=10: raise ValueError("conservation")
    delta=after_rank[drawer]-before_rank[drawer]
    if delta<0 or (before_rank[drawer]==4 and delta!=0): raise ValueError("impossible rank movement")
    return dict(ron_base=base,ron_loss=loss,honba_points=honba*300,pot_points=sticks*1000,
                before_scores=js(scores),after_scores=js(after),before_ranks=js(before_rank),
                after_ranks=js(after_rank),drawer_rank_before=before_rank[drawer],
                drawer_rank_after=after_rank[drawer],rank_drop=delta)
def hypothetical(replay,p,t,pwind,rwind):
    h=list(replay.hands[p])+[tile(t)]
    m=replay.melds[p]
    if len(h)+3*len(m)!=14: raise ValueError("invalid winning structure")
    if max(Counter(normal(x) for x in h+[x for _,b in m for x in b]).values())>4:
        raise ValueError("physical tile count exceeds four")
    reached=p in replay.reaches
    flags=dict(is_tsumo=False,is_riichi=reached,is_daburu_riichi=reached and replay.declarations.get(p,False),
       is_ippatsu=False,is_rinshan=False,is_chankan=False,is_haitei=False,is_houtei=False,first_uninterrupted=False)
    v=evaluate(h,m,tile(t),flags,pwind,rwind,list(replay.omote),[])
    excluded={"裏ドラ","一発","搶槓","槍槓","海底摸月","河底撈魚","嶺上開花","天和","地和","門前清自摸和"}
    if excluded.intersection(v["yaku"]): raise ValueError("excluded yaku")
    if not set(v["yaku"])-{"ドラ","赤ドラ"}: raise ValueError("no ordinary ron yaku")
    check=score(v["han"],v["fu"],False,pwind=="1z",len(v["yaku"]) if v["yakuman"] else 0)
    if check!=v["points"]: raise ValueError("independent score arithmetic mismatch")
    return dict(concealed_before=js(replay.hands[p]),melds=js(m),flags=js(flags),omote=js(replay.omote),
                yaku=js(v["yaku"]),fu=v["fu"],han=v["han"],yakuman=v["yakuman"],fu_details=js(v["fu_details"]),
                ron_base=v["points"])
def verified_zip(path,expected,dbsha):
    if sha256_file(path)!=expected: raise ValueError("approved artifact ZIP SHA-256 mismatch")
    z=zipfile.ZipFile(path)
    if z.testzip(): raise ValueError("ZIP CRC mismatch")
    manifest=json.loads(z.read("manifest.json"))
    if manifest["database_sha256"]!=dbsha: raise ValueError("artifact DB mismatch")
    for name,digest in manifest["outputs"].items():
        with z.open(name) as f:
            if hashlib.file_digest(f,"sha256").hexdigest()!=digest: raise ValueError("artifact member mismatch "+name)
    return z,manifest
def write(path,rows,fields):
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(rows)
def main():
    p=argparse.ArgumentParser();p.add_argument("db",type=Path);p.add_argument("a_zip",type=Path);p.add_argument("b_zip",type=Path);p.add_argument("out",type=Path);a=p.parse_args()
    a.out.mkdir(parents=True,exist_ok=True)
    c=connect_readonly(a.db);manifest=verify_database(c,RELEASE)
    dbsha=sha256_file(a.db)
    if dbsha!=DB_SHA:raise ValueError("DB hash mismatch")
    za,ma=verified_zip(a.a_zip,A_SHA,dbsha);zb,mb=verified_zip(a.b_zip,B_SHA,dbsha)
    # Preserve actual recorded differences unmodified, never use as hypothetical input.
    (a.out/"stage2a_actual_differences.csv").write_bytes(za.read("actual_wins_differences.csv"))
    targets=defaultdict(list);keys=set();sql=SQL_PATH.read_text(encoding="utf-8").strip().rstrip(";")
    for r in c.execute("SELECT id FROM player ORDER BY id").fetchall():
        for raw in c.execute("SELECT * FROM ("+sql+") WHERE is_dontsuka=1",dict(player_id=r[0],start_year=None,stage=None)):
            row=dict(raw);key=(row["draw_event_id"],row["opponent_player_id"])
            if key in keys:raise ValueError("duplicate stage1 key")
            keys.add(key);targets[row["kyoku_id"]].append(row)
        print("stage1 player",r[0],flush=True)
    bydraw=Counter(k[0] for k in keys)
    if len(keys)!=28060 or len(bydraw)!=27578 or dict(Counter(bydraw.values()))!=EXPECTED:raise ValueError("stage1 counts mismatch")
    snap={};all_ids=set()
    import io
    with zb.open("draw_snapshots.csv.gz") as f, gzip.GzipFile(fileobj=f) as g, io.TextIOWrapper(g,encoding="utf-8") as t:
        for r in csv.DictReader(t):
            eid=int(r["event_id"])
            if eid in all_ids:raise ValueError("duplicate snapshot")
            all_ids.add(eid)
            if eid in bydraw:snap[eid]=r
    if len(all_ids)!=1257732 or set(snap)!=set(bydraw):raise ValueError("stage2b event coverage")
    # Verify the full draw-event identity set directly against the pinned DB.
    if all_ids!={r[0] for r in c.execute("SELECT event_id FROM draw_event")}:raise ValueError("stage2b event IDs mismatch")
    result=[];errors=[];heads=[];examples={};replayed_keys=set()
    for ky,group in sorted(targets.items()):
        k=dict(c.execute("SELECT * FROM kyoku WHERE id=?",(ky,)).fetchone())
        winds={r[0]:r[1] for r in c.execute("SELECT player_id,player_wind FROM kyoku_player_result WHERE kyoku_id=?",(ky,))}
        if set(winds.values())!={"1z","2z","3z","4z"}:raise ValueError("invalid winds")
        byevent=defaultdict(list)
        for row in group:byevent[row["draw_event_id"]].append(row)
        rp=Replay()
        for e in events(c,ky):
            eid=e["id"]
            if eid in byevent:
                s=snap[eid];drawer=e["actor"];scores={int(s[f"player_id_{i}"]):int(s[f"score_{i}"]) for i in range(1,5)}
                if e["type"]!="draw" or int(s["event_order"])!=e["event_order"] or int(s["kyoku_id"])!=ky or int(s["game_id"])!=k["game_id"] or int(s["draw_actor_player_id"])!=drawer or s["tile"]!=e["tile"] or int(s["honba"])!=k["honba_count"] or set(scores)!=set(winds):
                    raise ValueError("snapshot/event metadata mismatch")
                if ranks(scores)!={int(s[f"player_id_{i}"]):float(s[f"average_rank_{i}"]) for i in range(1,5)}:raise ValueError("snapshot rank mismatch")
                if int(s["kyotaku_sticks"])!=k["kyotaku_count"]+len(rp.reaches):raise ValueError("pot mismatch")
                selected=head(winds,drawer,[r["opponent_player_id"] for r in byevent[eid]])
                for row in sorted(byevent[eid],key=lambda x:x["opponent_player_id"]):
                    target=row["opponent_player_id"];key=(eid,target)
                    if key in replayed_keys:raise ValueError("duplicate replayed key")
                    replayed_keys.add(key)
                    if row["drawer_player_id"]!=drawer or row["recorded_draw_tile"]!=e["tile"] or row["game_id"]!=k["game_id"]:raise ValueError("stage1 metadata mismatch")
                    r=dict(draw_event_id=eid,kyoku_id=ky,game_id=k["game_id"],event_order=e["event_order"],drawer=drawer,target=target,tile=e["tile"],round=k["round"],drawer_wind=winds[drawer],target_wind=winds[target],honba=int(s["honba"]),sticks=int(s["kyotaku_sticks"]),target_count=bydraw[eid],head_priority=distance(winds,drawer,target),head_selected=int(target==selected),opponent_snapshot_event_id=row["opponent_snapshot_event_id"],opponent_action_event_id=row["opponent_action_event_id"])
                    try:
                        v=hypothetical(rp,target,e["tile"],winds[target],k["round"][:2]);r.update(v)
                        r.update(settlement(scores,drawer,target,v["ron_base"],r["honba"],r["sticks"]))
                        r["status"]="evaluated"
                    except Exception as ex:
                        r.update(status="evaluation_failed",error=repr(ex),concealed_before=js(rp.hands.get(target)),melds=js(rp.melds.get(target)),omote=js(rp.omote))
                        errors.append(r.copy())
                    result.append(r)
                    if target==selected:heads.append(r.copy())
                    if r["status"]=="evaluated":
                        for label,cond in [("parent",winds[target]=="1z"),("child",winds[target]!="1z"),("red",e["tile"][0]=="0"),("kan_dora",len(rp.omote)>1),("yakuman",r["yakuman"]),("honba_pot",r["honba"]>0 and r["sticks"]>0),("tie",len(set(scores.values()))<4),("last",r["drawer_rank_before"]==4),("double",bydraw[eid]==2),("triple",bydraw[eid]==3),("kiriage",(r["han"],r["fu"]) in ((4,30),(3,60)))]:
                            if cond and label not in examples:examples[label]=r.copy()
            rp.step(e)
    if replayed_keys!=keys or len(heads)!=len(bydraw) or len({r["draw_event_id"] for r in heads})!=len(bydraw):raise ValueError("output coverage mismatch")
    fields=list(dict.fromkeys(k for r in result for k in r))
    write(a.out/"opponent_hypothetical_all.csv",result,fields);write(a.out/"head_bump_all.csv",heads,fields);write(a.out/"evaluation_failures.csv",errors,fields)
    (a.out/"real_examples.json").write_text(js(examples),encoding="utf-8")
    # Counts are stage3A verification only, not derived rates or round outcomes.
    counts=dict(opponent_rows=len(result),draws=len(heads),opponent_down=sum(r.get("rank_drop",0)>0 for r in result),opponent_same=sum(r.get("rank_drop")==0 for r in result),head_down=sum(r.get("rank_drop",0)>0 for r in heads),evaluation_failures=len(errors))
    prior=dict(opponent_down=13228,opponent_same=14832,head_down=12990)
    manifest.update(scope="3A only",database_sha256=dbsha,approved_2a_zip_sha256=A_SHA,approved_2b_zip_sha256=B_SHA,stage1_partition=dict(Counter(bydraw.values())),stage2b_draw_identity_match=True,counts_3a=counts,previous_unconfirmed_counts=prior,delta_from_previous={k:counts[k]-v for k,v in prior.items()},status="requires_review" if errors or any(counts[k]!=v for k,v in prior.items()) else "matched",commit=os.getenv("GITHUB_SHA"),run_id=os.getenv("GITHUB_RUN_ID"))
    (a.out/"manifest.json").write_text(js(manifest),encoding="utf-8");print(js(manifest),flush=True)
    return 1 if errors else 0
if __name__=="__main__":raise SystemExit(main())
