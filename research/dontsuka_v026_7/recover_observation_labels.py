"""Correct only kan-successor observation labels in the unapproved Stage 7 result.
No full replay or change to existing classifications, draw IDs, or genbutsu.
"""
import csv,gzip,hashlib,io,json,sys,zipfile
from pathlib import Path
from collections import Counter,defaultdict
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"scripts"))
from dontsuka_v026_extract import connect_readonly,verify_database,sha256_file
from dontsuka_v026_2b_replay import RELEASE,DB_SHA

ORIGINAL_SHA="52a4fb032e4b7ba4847927ba1bed0fc1bcc996a6bb71d8c86974fcfa8dfd41b8"
def require(x,m):
    if not x:raise ValueError(m)
def sha(p):return sha256_file(p)
def rows(z,n):
    with z.open(n) as f,gzip.GzipFile(fileobj=f) as g,io.TextIOWrapper(g,encoding="utf-8-sig") as t:
        yield from csv.DictReader(t)
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
def main():
    db,p,out=map(Path,sys.argv[1:]);out.mkdir(parents=True,exist_ok=True)
    c=connect_readonly(db);verify_database(c,RELEASE);require(sha(db)==DB_SHA,"DB")
    require(sha(p)==ORIGINAL_SHA,"original stage7 archive")
    z=zipfile.ZipFile(p);require(z.testzip() is None and len(set(z.namelist()))==len(z.namelist()),"CRC/name")
    m=json.loads(z.read("package_sha256.json"));require(set(m)==set(z.namelist())-{"package_sha256.json"},"original manifest coverage")
    for k,v in m.items():
        with z.open(k) as f:require(hashlib.file_digest(f,"sha256").hexdigest()==v,"original member "+k)
    changes={};exceptions=[];successor_counts=Counter()
    for r in rows(z,"final/no_discard_and_not_applicable.csv.gz"):
        if r["link_reason"] not in ("kan_before_rinshan","next_draw_without_discard"):continue
        ky,o=int(r["kyoku_id"]),int(r["event_order"]);n=int(r["terminal_or_next_event_id"])
        # Read the immediate significant event after the actual kan, not after
        # any later draw; no assumed replacement event is manufactured.
        anchor=int(r["kan_order"]) if r["kan_order"] else o
        anchor_id=int(r["kan_event_id"] or r["draw_event_id"])
        action_types="('draw','ron','tsumo','ryukyoku')" if r["kan_event_id"] else "('draw','discard','chi','pon','daiminkan','ankan','shominkan','ron','tsumo','ryukyoku')"
        nxt=c.execute(f"""SELECT e.id,e.kyoku_id,e.event_order,e.type,d.actor_player_id,d.is_rinshan,d.tile
          FROM event e LEFT JOIN draw_event d ON d.event_id=e.id
          WHERE e.kyoku_id=? AND (e.event_order>? OR (e.event_order=? AND e.id>?)) AND e.type IN {action_types}
          ORDER BY e.event_order,e.id LIMIT 1""",(ky,anchor,anchor,anchor_id)).fetchone()
        require(nxt is not None and int(nxt["id"])==n and nxt["type"]=="draw","actual successor event: "+str((r["draw_event_id"],r["kan_event_id"],n,dict(nxt) if nxt else None)))
        require(int(nxt["event_order"])==int(r["terminal_or_next_order"]),"successor order")
        if r["link_reason"]=="kan_before_rinshan":
            k=c.execute("SELECT id,kyoku_id,event_order,type FROM event WHERE id=?",(int(r["kan_event_id"]),)).fetchone()
            require(k is not None and (k["kyoku_id"],k["event_order"],k["type"])==(ky,int(r["kan_order"]),r["kan_kind"]),"kan event")
            actor=c.execute(f'SELECT actor_player_id FROM {r["kan_kind"]}_event WHERE event_id=?',(int(r["kan_event_id"]),)).fetchone()
            require(actor and int(actor[0])==int(r["player_id"]),"kan actor")
            label="kan_followed_by_other_draw" if int(nxt["actor_player_id"])!=int(r["player_id"]) else "kan_followed_by_own_draw_unmarked" if int(nxt["is_rinshan"])!=1 else "kan_before_rinshan"
        else:label=r["link_reason"]
        successor_counts[label]+=1
        if label!="kan_before_rinshan":
            context=[dict(x) for x in c.execute("""SELECT e.id,e.event_order,e.type,coalesce(dr.actor_player_id,ds.actor_player_id) AS actor,
                  coalesce(dr.tile,ds.tile) AS tile,dr.is_rinshan
                FROM event e LEFT JOIN draw_event dr ON dr.event_id=e.id
                LEFT JOIN discard_event ds ON ds.event_id=e.id WHERE e.kyoku_id=?
                AND e.event_order>=? AND e.event_order<=? ORDER BY e.event_order,e.id""",(ky,o-6,int(nxt["event_order"])+6))]
            rec=dict(draw_event_id=int(r["draw_event_id"]),old_link_reason=r["link_reason"],new_link_reason=label,draw=r,successor=dict(nxt),recorded_event_context=context)
            exceptions.append(rec)
            if label!=r["link_reason"]:
                require(r["has_discard"]=="0" and r["movement"]=="no_discard","no-discard classification")
                require(r["is_dontsuka"]=="0" and r["opponent_count"]=="0","this correction must not affect opponent rows")
                changes[int(r["draw_event_id"])]=rec
    require(sum(successor_counts.values())==1710,"all recorded kan/exception successors")
    require(len(changes)>0,"no correction records")
    # Preserve the original ZIP and its global manifest; extract only the
    # unmodified source/benchmark/shard directories into a new result tree.
    for n in z.namelist():
        if n.startswith(("shards/","benchmark/","source/")):z.extract(n,out)
    recovery=out/"recovery";recovery.mkdir()
    write(recovery/"original_package_manifest.json",m);write(recovery/"observation_corrections.json",exceptions)
    seen=set();affected=[]
    for d in sorted((out/"shards").iterdir()):
        if not d.is_dir():continue
        sp=d/"summary.json";mp=d/"manifest.json";rp=d/"draws.csv.gz"
        summary=json.loads(sp.read_text());old_manifest=json.loads(mp.read_text());old_summary=dict(summary)
        old_summary["counts"]=dict(summary["counts"]);newrows=[]
        with gzip.open(rp,"rt",encoding="utf-8",newline="") as f:
            reader=csv.DictReader(f);fields=reader.fieldnames
            for r in reader:
                eid=int(r["draw_event_id"])
                if eid in changes:
                    ch=changes[eid];require(eid not in seen,"correction duplicate");seen.add(eid)
                    require(all(r[k]==v for k,v in ch["draw"].items()),"original shard/final row agreement")
                    old=r["link_reason"];new=ch["new_link_reason"]
                    require(old==r["movement_reason"]=="kan_before_rinshan","original reason")
                    r["link_reason"]=r["movement_reason"]=new
                    summary["counts"]["link_"+old]-=1
                    summary["counts"]["link_"+new]=summary["counts"].get("link_"+new,0)+1
                    newrows.append(ch)
        if not newrows:continue
        affected.append(d.name)
        # Read a second time to rewrite; all non-target rows retain every field.
        tmp=d/"draws.corrected.csv.gz"
        with gzip.open(rp,"rt",encoding="utf-8",newline="") as f,gzip.open(tmp,"wt",encoding="utf-8",newline="") as g:
            reader=csv.DictReader(f);w=csv.DictWriter(g,fieldnames=fields);w.writeheader()
            for r in reader:
                ch=changes.get(int(r["draw_event_id"]))
                if ch:r["link_reason"]=r["movement_reason"]=ch["new_link_reason"]
                w.writerow(r)
        tmp.replace(rp)
        dest=recovery/"original_shard_manifests"/d.name;dest.mkdir(parents=True)
        write(dest/"manifest.json",old_manifest);write(dest/"summary.json",old_summary)
        write(sp,summary);write(d/"observation_correction.json",newrows)
        newmanifest={f.name:sha(f) for f in d.iterdir() if f.is_file() and f.name!="manifest.json"}
        for n,h in old_manifest.items():
            if n not in ("draws.csv.gz","summary.json"):require(newmanifest[n]==h,"unexpected changed member "+n)
        write(mp,newmanifest)
    require(seen==set(changes),"all derived correction IDs")
    write(recovery/"summary.json",dict(status="corrected_unapproved_observation_labels",original_sha256=ORIGINAL_SHA,original_members=len(m),database_sha256=DB_SHA,changed_rows=len(changes),affected_shards=affected,successor_counts=dict(successor_counts),changed_basic_dontsuka=0,changed_opponent_rows=0,changed_shanten_or_movement=0,original_logs_unchanged=True))
    print(json.dumps(json.loads((recovery/"summary.json").read_text()),ensure_ascii=False),flush=True)
if __name__=="__main__":main()
