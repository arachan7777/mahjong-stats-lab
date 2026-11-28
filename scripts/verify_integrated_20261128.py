#!/usr/bin/env python3
"""Audit an actual 2068+16 SQLite merge against the pinned 2084-game release.

Produces a durable small manifest. The accepted operational master can be the
byte-original upstream full SQLite only if all tables of the merged database
are proved logically identical; original research archives are never edited.
"""
import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from export_weekly_delta_20261128 import source_release, export_slice
from check_latest_db import download_asset, extract_sqlite

BASELINE_TAG="20261120-2341-04338cbb"
CURRENT_TAG="20261128-0102-1b6bd367"
DATES=("2026-11-20","2026-11-27")
EXPECT={"game":16,"kyoku":199,"event":21973}
FINAL_COUNTS={"game":2084,"kyoku":25437,"event":2779703}

def hexdigest(p):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for b in iter(lambda:f.read(1048576),b""):
            h.update(b)
    return h.hexdigest()

def download_db(tag,folder):
    r,asset=source_release(tag)
    z=folder/(tag+".zip")
    d=folder/(tag+".sqlite3")
    sha=download_asset(asset["browser_download_url"],asset["size"],z)
    upstream_digest=asset.get("digest")
    if upstream_digest and upstream_digest!="sha256:"+sha:
        raise RuntimeError("Release digest mismatch "+tag)
    extract_sqlite(z,d)
    with sqlite3.connect(d.resolve().as_uri()+"?mode=ro",uri=True) as conn:
        if conn.execute("PRAGMA quick_check").fetchone()[0]!="ok":
            raise RuntimeError("Upstream integrity check failed "+tag)
    return d,{"tag":tag,"asset_bytes":asset["size"],"asset_sha256":sha,
              "sqlite_sha256":hexdigest(d),"sqlite_bytes":d.stat().st_size}

def schema_rows(c, db):
    return c.execute("SELECT type, name, sql FROM "+db+".sqlite_master "
                     "WHERE type IN ('table','view','index','trigger') "
                     "AND name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()

def q(s):
    return '"'+s.replace('"','""')+'"'

def merge_validate(old,new,delta,merged):
    shutil.copyfile(old,merged)
    c=sqlite3.connect(merged)
    c.execute("PRAGMA foreign_keys=OFF")
    c.execute("ATTACH DATABASE ? AS inc",(str(delta),))
    c.execute("ATTACH DATABASE ? AS fresh",(new.resolve().as_uri()+"?mode=ro",))
    c.execute("ATTACH DATABASE ? AS prev",(old.resolve().as_uri()+"?mode=ro",))
    schemas={"old":schema_rows(c,"prev"),"new":schema_rows(c,"fresh")}
    if schemas["old"]!=schemas["new"]:
        changed=list(set((t,n,str(v)) for t,n,v in schemas["old"]) ^
                     set((t,n,str(v)) for t,n,v in schemas["new"]))
        raise RuntimeError("Upstream schema differs; merge requires review: "+repr(changed[:20]))
    names=[name for kind,name,_ in schemas["old"] if kind=="table"]
    for table in names:
        cols=[row[1] for row in c.execute("PRAGMA main.table_info("+q(table)+")")]
        if not cols:
            raise RuntimeError("Missing columns "+table)
        col_list=",".join(q(x) for x in cols)
        c.execute("INSERT OR IGNORE INTO main."+q(table)+" ("+col_list+
                  ") SELECT "+col_list+" FROM inc."+q(table))
    c.commit()
    old_counts={}
    merged_counts={}
    latest_counts={}
    for table in names:
        old_counts[table]=c.execute("SELECT COUNT(*) FROM prev."+q(table)).fetchone()[0]
        merged_counts[table]=c.execute("SELECT COUNT(*) FROM main."+q(table)).fetchone()[0]
        latest_counts[table]=c.execute("SELECT COUNT(*) FROM fresh."+q(table)).fetchone()[0]
        if merged_counts[table]!=latest_counts[table]:
            raise RuntimeError("Count mismatch "+table+": "+str((merged_counts[table],latest_counts[table])))
        # SQL EXCEPT proves row content, not merely PK IDs or count equality.
        diff1=c.execute("SELECT COUNT(*) FROM (SELECT * FROM main."+q(table)+
                        " EXCEPT SELECT * FROM fresh."+q(table)+")").fetchone()[0]
        diff2=c.execute("SELECT COUNT(*) FROM (SELECT * FROM fresh."+q(table)+
                        " EXCEPT SELECT * FROM main."+q(table)+")").fetchone()[0]
        if diff1 or diff2:
            raise RuntimeError("Row value mismatch "+table+": "+str((diff1,diff2)))
        # All existing rows must remain logically intact after integration.
        changed=c.execute("SELECT COUNT(*) FROM (SELECT * FROM prev."+q(table)+
                          " EXCEPT SELECT * FROM main."+q(table)+")").fetchone()[0]
        if changed:
            raise RuntimeError("Old rows altered in "+table+": "+str(changed))
        print("TABLE_VERIFIED",table,old_counts[table],merged_counts[table],flush=True)
    for name,n in FINAL_COUNTS.items():
        if merged_counts[name]!=n:
            raise RuntimeError("Final "+name+" mismatch")
    if merged_counts["game"]-old_counts["game"]!=16:
        raise RuntimeError("Game delta mismatch")
    if merged_counts["kyoku"]-old_counts["kyoku"]!=199:
        raise RuntimeError("Kyoku delta mismatch")
    if merged_counts["event"]-old_counts["event"]!=21973:
        raise RuntimeError("Event delta mismatch")
    if c.execute("PRAGMA main.quick_check").fetchone()[0]!="ok":
        raise RuntimeError("Merged quick_check not ok")
    fk=c.execute("PRAGMA main.foreign_key_check").fetchmany(10)
    if fk:raise RuntimeError("Merged foreign-key violations: "+repr(fk))
    matches=c.execute("SELECT date,COUNT(*) FROM main.game WHERE date>? AND date<=? "
                      "GROUP BY date ORDER BY date",DATES).fetchall()
    if matches!=[("2026-11-23",4),("2026-11-24",4),
                 ("2026-11-26",4),("2026-11-27",4)]:
        raise RuntimeError("New game dates mismatch "+str(matches))
    c.close()
    return {"old_counts":old_counts,"merged_counts":merged_counts,
            "new_release_counts":latest_counts,"matched_new_dates":matches,
            "table_count":len(names),"all_table_rows_equal":True,
            "old_rows_preserved":True,"quick_check":"ok",
            "foreign_key_check":"ok","merged_sqlite_bytes":merged.stat().st_size,
            "merged_sqlite_sha256":hexdigest(merged)}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--output",default="integrated-audit-20261128")
    a=p.parse_args()
    output=Path(a.output);output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="integrate-ml-") as tmp:
        folder=Path(tmp)
        old,old_info=download_db(BASELINE_TAG,folder)
        print("baseline downloaded and checked",flush=True)
        new,new_info=download_db(CURRENT_TAG,folder)
        print("current release downloaded and checked",flush=True)
        delta=folder/"delta.sqlite3"
        delta_counts, dates,nviews=export_slice(new,delta,*DATES,EXPECT)
        merged=folder/"merged.sqlite3"
        audit=merge_validate(old,new,delta,merged)
        report={"status":"success","checked_at_utc":datetime.now(timezone.utc).isoformat(),
                "old":old_info,"new_release":new_info,"delta_counts":delta_counts,
                "delta_dates":dates,"views":nviews,"integrated":audit,
                "canonical_use":"The pinned 20261128 original 2084-game source SQLite is row-identical across all audited tables to 20261120 + 16-game delta; existing verified split source release files may be used as primary database after reconstruction.",
                "backup_policy":"Old baseline 20261120 is emergency backup only; no use without explicit user approval.",
                "warning":"Independently verified here: old/new from pinned GitHub releases. Drive file bytes not directly SHA-rehashed in this workflow. Canonical files are not changed."}
        name=output/"integrated-master-audit.json"
        name.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print("MERGE_AUDIT_SUCCESS "+json.dumps({
            "old_games":audit["old_counts"]["game"],
            "new_games":audit["merged_counts"]["game"],
            "new_hands":audit["merged_counts"]["kyoku"],
            "new_events":audit["merged_counts"]["event"],
            "table_count":audit["table_count"],
            "all_table_rows_equal":audit["all_table_rows_equal"],
            "old_rows_preserved":audit["old_rows_preserved"],
            "new_sha256":new_info["sqlite_sha256"],
            "merged_sha256":audit["merged_sqlite_sha256"],
            "manifest_path":str(name)
        },ensure_ascii=False),flush=True)

if __name__=="__main__":
    try:main()
    except Exception as ex:
        print("MERGE_AUDIT_FAILED "+repr(ex),file=sys.stderr,flush=True)
        raise
