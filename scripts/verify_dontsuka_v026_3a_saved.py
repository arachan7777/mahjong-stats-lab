"""Independent readback verifier for Stage 3A evidence ZIP and approved Stage 2A/B ZIPs.
No database, no writes to approved files, no Stage 3B computations."""
import argparse, csv, gzip, io, json, hashlib, zipfile
from collections import Counter, defaultdict
from pathlib import Path
def digest(f):return hashlib.file_digest(f,"sha256").hexdigest()
def read_csv(z,name):
    with z.open(name) as b,io.TextIOWrapper(b,encoding="utf-8-sig",newline="") as f:
        yield from csv.DictReader(f)
def checked(p):
    z=zipfile.ZipFile(p)
    assert z.testzip() is None
    m=json.loads(z.read("manifest.json"))
    for n,h in m["outputs"].items():
        with z.open(n) as f:assert digest(f)==h,n
    with open(p,"rb") as f:h=digest(f)
    return z,m,h
def rnk(s):
    # Independently derive occupied rank averages, not the implementation formula.
    out={};i=1
    for value,n in sorted(Counter(s.values()).items(),reverse=True):
        for p in s:
            if s[p]==value:out[p]=(i+i+n-1)/2
        i+=n
    return out
def numbers(r,field):
    return {int(k):v for k,v in json.loads(r[field]).items()}
def main():
    p=argparse.ArgumentParser();p.add_argument("stage3a",type=Path);p.add_argument("stage2a",type=Path);p.add_argument("stage2b",type=Path);a=p.parse_args()
    z,m,h=checked(a.stage3a);za,ma,ha=checked(a.stage2a);zb,mb,hb=checked(a.stage2b)
    assert m["scope"]=="3A only" and m["database_sha256"]==ma["database_sha256"]==mb["database_sha256"]
    assert ha==m["approved_2a_zip_sha256"] and hb==m["approved_2b_zip_sha256"]
    assert z.read("stage2a_actual_differences.csv")==za.read("actual_wins_differences.csv")
    rows=list(read_csv(z,"opponent_hypothetical_all.csv"));heads=list(read_csv(z,"head_bump_all.csv"))
    assert len(rows)==28060 and len(heads)==27578
    keys={(r["draw_event_id"],r["target"]) for r in rows};assert len(keys)==len(rows)
    by=defaultdict(list)
    for r in rows:by[r["draw_event_id"]].append(r)
    assert Counter(map(len,by.values()))=={1:27101,2:472,3:5}
    hp={r["draw_event_id"]:r for r in heads};assert len(hp)==len(heads) and hp.keys()==by.keys()
    assert all(hp[e]==min(group,key=lambda r:(int(r["target_wind"][0])-int(r["drawer_wind"][0]))%4) for e,group in by.items())
    ids=set();snapshots=0
    with zb.open("draw_snapshots.csv.gz") as b,gzip.GzipFile(fileobj=b) as g,io.TextIOWrapper(g,encoding="utf-8",newline="") as f:
        for s in csv.DictReader(f):
            eid=s["event_id"];snapshots+=1
            if eid not in by:continue
            assert eid not in ids;ids.add(eid)
            scores={int(s[f"player_id_{i}"]):int(s[f"score_{i}"]) for i in range(1,5)}
            for r in by[eid]:
                for x,y in [("game_id","game_id"),("kyoku_id","kyoku_id"),("event_order","event_order"),("drawer","draw_actor_player_id"),("tile","tile"),("honba","honba"),("sticks","kyotaku_sticks")]:assert r[x]==s[y],(eid,x)
                if r["status"]!="evaluated":continue
                assert numbers(r,"before_scores")==scores
                d,t=int(r["drawer"]),int(r["target"]);loss=int(r["ron_base"])+300*int(r["honba"]);pot=1000*int(r["sticks"])
                after={p:v+(loss+pot if p==t else -loss if p==d else 0) for p,v in scores.items()}
                assert sum(after.values())==100000
                assert int(r["ron_loss"])==loss and int(r["pot_points"])==pot
                assert numbers(r,"after_scores")==after
                assert numbers(r,"before_ranks")==rnk(scores) and numbers(r,"after_ranks")==rnk(after)
                assert float(r["rank_drop"])==rnk(after)[d]-rnk(scores)[d]
                assert float(r["drawer_rank_before"])==rnk(scores)[d] and float(r["drawer_rank_after"])==rnk(after)[d]
                assert float(r["rank_drop"])>=0
                assert not set(json.loads(r["yaku"]))&{"裏ドラ","一発","搶槓","槍槓","海底摸月","河底撈魚","嶺上開花"}
    assert snapshots==1257732 and ids==by.keys()
    fails=[r for r in rows if r["status"]!="evaluated"];assert fails==list(read_csv(z,"evaluation_failures.csv"))
    counts={"opponent_rows":len(rows),"draws":len(heads),"opponent_down":sum(float(r["rank_drop"] or 0)>0 for r in rows),"opponent_same":sum(r["rank_drop"]!="" and float(r["rank_drop"])==0 for r in rows),"head_down":sum(float(r["rank_drop"] or 0)>0 for r in heads),"evaluation_failures":len(fails)}
    assert counts==m["counts_3a"]
    print(json.dumps({"stage3a_zip_sha256":h,"stage2a_zip_sha256":ha,"stage2b_zip_sha256":hb,"all_manifest_members_matched":True,"snapshots":snapshots,"target_events_matched":len(ids),"counts":counts,"status":"matched" if not fails else "evaluation_failures_remain"},indent=2))
if __name__=="__main__":main()
