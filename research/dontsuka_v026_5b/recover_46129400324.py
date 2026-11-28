"""Stage 5B recovery only; never run the search or modify original archives."""
import csv,gzip,hashlib,json,os,shutil,sys,zipfile
from pathlib import Path
from collections import Counter
from itertools import zip_longest
def check(b,msg):
    if not b:raise ValueError(msg)
def sha(b):return hashlib.sha256(b).hexdigest()
def filehash(p):
    with p.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()
def js(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"))
def read(p):return json.loads(p.read_text(encoding="utf-8"))
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
SRC_RUN="46129400324"
SRC_COMMIT="10859209fbef7e1ec475d382a74785ce3fe123d4"
SRC_SHA="335dba8115484123b301fb1250fdd1bfe5315849063bf66f5a39c73733614662"
A_SHA="5d2885cc4e19fdd0bb18a37a587145f9ab8699ef70efd385964ff11511f4edff"
EXPECTED={"draws":1257732,"basic":27578,"excluded":133,"evaluated":1257599,"excluded_basic":1,"isshanten":299220,"isshanten_dontsuka":8956,"shoubute":231765,"shoubute_dontsuka":7077}
def prepare(archive,approved,root):
    check(filehash(archive)==SRC_SHA,"source ZIP digest")
    check(filehash(approved)==A_SHA,"approved 5A ZIP digest")
    root.mkdir(parents=True,exist_ok=True)
    source=root/"original"; corrected=root/"corrected"; evidence=root/"evidence"
    evidence.mkdir()
    with zipfile.ZipFile(archive) as z:
        check(z.testzip() is None,"source ZIP CRC")
        check(len(z.namelist())==len(set(z.namelist())),"duplicate ZIP entry")
        for n in z.namelist():
            p=Path(n);check(not p.is_absolute() and ".." not in p.parts,"unsafe ZIP path")
        z.extractall(source)
    paths=sorted(source.glob("**/shards/*/manifest.json"))
    # Artifact layout has shards/ and benchmark/ at root.
    check(len(paths)==16,"original manifest count")
    a_ids={};a_rounds=set()
    with zipfile.ZipFile(approved) as z:
        m=json.loads(z.read("manifest.json"))
        for n,d in m["outputs"].items():check(sha(z.read(n))==d,"approved 5A member "+n)
        with z.open("all_draw_coverage.csv.gz") as f,gzip.open(f,"rt",encoding="utf-8") as g:
            for r in csv.DictReader(g):
                eid=int(r["draw_event_id"]);check(eid not in a_ids,"duplicate A ID")
                a_ids[eid]=(r["kyoku_id"],r["player_id"],r["event_order"],r["is_dontsuka"],r["physical_shanten"],r["status"])
        import io
        for r in csv.DictReader(io.StringIO(z.read("shoubute_dontsuka_kyoku.csv").decode("utf-8-sig"))):a_rounds.add((int(r["kyoku_id"]),int(r["player_id"])))
    check(len(a_ids)==1257732 and len(a_rounds)==3426,"approved A scope")
    rows=[];counts=Counter();seen=set();seen_ky=set();seen_shards=set();nfiles=0
    for p in paths:
        m=read(p);d=p.parent;i=m["shard"]
        check(m["status"]=="computed" and not m["errors"] and not m["limited"] and m["shards"]==16 and m["run_id"]==SRC_RUN and m["commit"]==SRC_COMMIT,"source provenance")
        check(i not in seen_shards and not seen_ky.intersection(m["kyoku_ids"]),"overlap");seen_shards.add(i);seen_ky.update(m["kyoku_ids"])
        check(set(m["outputs"])=={"coverage.csv.gz","isshanten_draws.csv.gz","shoubute_dontsuka.csv.gz","rounds.json","errors.json","exclusions.json","real_examples.json","names.json","run.log"},"expected member set")
        check({f.name for f in d.iterdir() if f.is_file()}==set(m["outputs"])|{"manifest.json"},"unexpected member")
        for n,h in m["outputs"].items():
            if n!="run.log":
                check(filehash(d/n)==h,"original data hash "+str(i)+"/"+n);nfiles+=1
        log=(d/"run.log").read_bytes()
        # Runner hashes the tee file, writes manifest, then prints the manifest
        # summary into the same open pipe. Reconstruct exact final print bytes.
        suffix=(js({k:v for k,v in m.items() if k!="kyoku_ids"})+"\n").encode("utf-8")
        check(log.endswith(suffix),"unexpected final log text shard "+str(i))
        prefix=log[:-len(suffix)]
        check(sha(prefix)==m["outputs"]["run.log"],"historical log prefix digest shard "+str(i))
        check(sha(log)!=sha(prefix),"expected appended bytes")
        out=corrected/d.name;shutil.copytree(d,out)
        new=dict(m,outputs=dict(m["outputs"]))
        new["outputs"]["run.log"]=sha(log)
        # Original manifest remains in original/; corrected is separately derived.
        (out/"manifest.json").write_text(js(new)+"\n",encoding="utf-8")
        for n,h in new["outputs"].items():check(filehash(out/n)==h,"corrected member "+n)
        rows.append(dict(shard=i,original_manifest_sha256=filehash(p),corrected_manifest_sha256=filehash(out/"manifest.json"),original_log_hash=sha(prefix),final_log_hash=sha(log),appended_bytes=len(suffix),appended_sha256=sha(suffix),prefix_verified=True,exact_appended_summary_verified=True,nonlog_members_verified=8))
        local={};qids=set();hits=set();roundids=set();localcounts=Counter()
        with gzip.open(d/"coverage.csv.gz","rt",encoding="utf-8") as f:
            for r in csv.DictReader(f):
                eid=int(r["draw_event_id"]);check(eid not in seen and eid in a_ids,"global event identity")
                seen.add(eid);a=a_ids[eid]
                check(tuple(r[k] for k in ("kyoku_id","player_id","event_order","is_dontsuka","physical_shanten"))==a[:5],"A/B event metadata")
                check((r["status"]=="not_applicable_actual_foul")== (a[5]=="unresolved"),"A/B applicability")
                local[eid]=r;dd=int(r["is_dontsuka"])
                localcounts.update(draws=1,basic=dd)
                if r["status"]=="not_applicable_actual_foul":localcounts.update(excluded=1,excluded_basic=dd);check(r["is_shoubute"]=="","foul classification")
                else:
                    check(r["status"]=="evaluated","unresolved");localcounts["evaluated"]+=1
                    if r["physical_shanten"]=="1":
                        q=int(r["is_shoubute"]);check(q in (0,1),"one-shanten flag")
                        qids.add(eid);localcounts.update(isshanten=1,isshanten_dontsuka=dd,shoubute=q,shoubute_dontsuka=q*dd)
                        if q and dd:hits.add(eid)
        for filename,target in (("isshanten_draws.csv.gz",qids),("shoubute_dontsuka.csv.gz",hits)):
            ids=set()
            with gzip.open(d/filename,"rt",encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    eid=int(r["draw_event_id"]);check(eid in target and eid not in ids,"detail identity")
                    ids.add(eid);check(all(r[k]==v for k,v in local[eid].items()),"coverage/detail disagreement")
            check(ids==target,"detail completeness")
        for r in read(d/"rounds.json"):
            key=(r["kyoku_id"],r["player_id"])
            check(r["also_shoubute_tenpai_dontsuka"]==int(key in a_rounds),"A/B round overlap")
            for eid in json.loads(r["draw_event_ids"]):
                check(eid in hits and eid not in roundids,"round event identity")
                check((int(local[eid]["kyoku_id"]),int(local[eid]["player_id"]))==key,"round event key")
                roundids.add(eid)
        check(roundids==hits,"round coverage")
        for k,v in localcounts.items():check(m["counts"][k]==v,"independent count "+k)
        counts.update(localcounts)
    check(nfiles==128 and seen_shards==set(range(16)) and len(seen_ky)==25238 and seen==set(a_ids),"complete coverage")
    check(dict(counts)==EXPECTED,"provisional comparison "+str(counts))
    write(evidence/"recovery_audit.json",dict(original_run=SRC_RUN,original_commit=SRC_COMMIT,original_artifact_sha256=SRC_SHA,approved_5a_sha256=A_SHA,nonlog_hashes_verified=nfiles,original_log_prefixes_verified=16,exact_appended_summaries_verified=16,corrected_full_log_hashes_verified=16,originals_unchanged=True,counts=dict(counts),shards=rows,all_draw_ids_and_metadata_match_5a=True,full_exploration_rerun=False))
    print(js(dict(counts=counts,nonlog=nfiles,logs=len(rows))),flush=True)
if __name__=="__main__":prepare(*map(Path,sys.argv[1:]))
