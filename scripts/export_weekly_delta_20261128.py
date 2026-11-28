#!/usr/bin/env python3
"""Export only games after a frozen baseline, with all dependent SQLite rows.

The upstream release DB is read-only. No existing Drive DB or research original
is modified. The output is a self-contained SQLite slice + verified manifest.
"""
from __future__ import annotations
import argparse
import collections
import hashlib
import json
import re
import sqlite3
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

from check_latest_db import download_asset, extract_sqlite, request, validate_sqlite

DIMENSIONS = {"league_season", "season_stage", "team", "player",
              "player_team", "yaku_name"}
EXCLUDE = {"sqlite_sequence"}

def q(identifier):
    return '"' + identifier.replace('"', '""') + '"'

def hash_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def source_release(tag):
    api = "https://api.github.com/repos/konoui/m-league-game-db/releases/tags/" + tag
    with urlopen(request(api), timeout=90) as response:
        info = json.load(response)
    assets = [a for a in info["assets"] if a["name"] == "database.zip"]
    if len(assets) != 1:
        raise RuntimeError("Expected exactly one database.zip in pinned release")
    return info, assets[0]

def prefixed_ddl(sql, kind):
    match = re.match(
        r"(?is)^(\s*CREATE\s+(?:TEMP\s+)?(?:TABLE|VIEW)\s+"
        r"(?:IF\s+NOT\s+EXISTS\s+)?)", sql
    )
    if not match:
        raise RuntimeError("Unsupported " + kind + " DDL: " + sql[:160])
    return sql[:match.end()] + "delta." + sql[match.end():]

def fk_groups(db, table):
    rows = db.execute("PRAGMA main.foreign_key_list(" + q(table) + ")").fetchall()
    groups = collections.defaultdict(list)
    for ident, seq, parent, child_col, parent_col, *rest in rows:
        groups[ident].append((seq, parent, child_col, parent_col))
    return [[(parent, child_col, parent_col) for _, parent, child_col, parent_col
             in sorted(seq_rows)] for seq_rows in groups.values()]

def columns(db, table):
    cols = db.execute("PRAGMA main.table_info(" + q(table) + ")").fetchall()
    if not cols:
        raise RuntimeError("No insertable columns: " + table)
    return [c[1] for c in cols]

def count(db, table, schema="delta"):
    return db.execute("SELECT COUNT(*) FROM " + schema + "." + q(table)).fetchone()[0]

def export_slice(source_db, dest_db, after, through, expected):
    # Open the upstream data read-only. Only the attached delta is writable.
    db = sqlite3.connect(source_db.resolve().as_uri() + "?mode=ro", uri=True)
    db.execute("ATTACH DATABASE ? AS delta", (str(dest_db),))
    db.execute("PRAGMA foreign_keys=OFF")
    ddl_rows = db.execute(
        "SELECT type, name, sql FROM main.sqlite_master "
        "WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' "
        "ORDER BY CASE type WHEN 'table' THEN 0 ELSE 1 END, name"
    ).fetchall()
    tables = {name: sql for kind, name, sql in ddl_rows if kind == "table"}
    views = [(name, sql) for kind, name, sql in ddl_rows if kind == "view"]
    if not {"game", "kyoku", "event"}.issubset(tables):
        raise RuntimeError("Required source tables missing")
    unknown_dimensions = DIMENSIONS - set(tables)
    if unknown_dimensions:
        raise RuntimeError("Missing dimension tables: " + str(unknown_dimensions))
    for table, sql in tables.items():
        db.execute(prefixed_ddl(sql, "table"))
    for name, sql in views:
        db.execute(prefixed_ddl(sql, "view"))
    for table in sorted(DIMENSIONS):
        cols = ",".join(q(c) for c in columns(db, table))
        db.execute("INSERT INTO delta." + q(table) + " (" + cols + ") "
                   "SELECT " + cols + " FROM main." + q(table))
    game_columns = ",".join(q(c) for c in columns(db, "game"))
    db.execute("INSERT INTO delta.game (" + game_columns + ") "
               "SELECT " + game_columns + " FROM main.game "
               "WHERE date > ? AND date <= ?", (after, through))
    if count(db, "game") != expected["game"]:
        raise RuntimeError("Unexpected game count: " + str(count(db, "game")))
    facts = set(tables) - DIMENSIONS
    relations = {t: fk_groups(db, t) for t in facts - {"game"}}
    reachable = {"game"}
    while True:
        newly = {t for t in facts - reachable if any(
            group and group[0][0] in reachable
            for group in relations.get(t, [])
        )}
        if not newly:
            break
        reachable |= newly
    unlinked = facts - reachable
    if unlinked:
        raise RuntimeError("Unlinked fact tables (not silently copied): " +
                           repr(sorted(unlinked)))
    passes = 0
    while True:
        passes += 1
        changed = 0
        for table in sorted(facts - {"game"}):
            predicates = []
            for group in relations[table]:
                parent = group[0][0]
                if parent not in facts:
                    continue
                if not all(p == parent and pc for p, child, pc in group):
                    raise RuntimeError("Malformed foreign key for " + table)
                terms = ["p." + q(pc) + "=c." + q(child)
                         for p, child, pc in group]
                predicates.append(
                    "EXISTS (SELECT 1 FROM delta." + q(parent) + " AS p WHERE " +
                    " AND ".join(terms) + ")"
                )
            if not predicates:
                continue
            cols = ",".join(q(c) for c in columns(db, table))
            before = db.total_changes
            db.execute("INSERT OR IGNORE INTO delta." + q(table) +
                       " (" + cols + ") SELECT " +
                       ",".join("c." + q(c) for c in columns(db, table)) +
                       " FROM main." + q(table) + " AS c WHERE " +
                       " OR ".join(predicates))
            changed += db.total_changes - before
        print("fact pass", passes, "new rows", changed, flush=True)
        if changed == 0:
            break
        if passes > len(facts) + 2:
            raise RuntimeError("Fact closure failed to converge")
    counts = {t: count(db, t) for t in sorted(tables)}
    for tab, expected_count in expected.items():
        if counts[tab] != expected_count:
            raise RuntimeError("%s count mismatch %s != %s" %
                               (tab, counts[tab], expected_count))
    for table in sorted(facts - {"game"}):
        predicates = []
        for group in relations[table]:
            if group[0][0] not in facts:
                continue
            parent = group[0][0]
            predicates.append("EXISTS (SELECT 1 FROM delta." + q(parent) +
                              " AS p WHERE " +
                              " AND ".join("p." + q(pc) + "=c." + q(child)
                                           for p, child, pc in group) + ")")
        matching = db.execute(
            "SELECT COUNT(*) FROM main." + q(table) + " AS c WHERE " +
            " OR ".join(predicates)
        ).fetchone()[0]
        if counts[table] != matching:
            raise RuntimeError("Incomplete dependency extraction: %s %d != %d"
                               % (table, counts[table], matching))
    violations = db.execute("PRAGMA delta.foreign_key_check").fetchall()
    if violations:
        raise RuntimeError("Foreign key violations: " + repr(violations[:10]))
    db.commit()
    ok = db.execute("PRAGMA delta.quick_check").fetchone()[0]
    if ok != "ok":
        raise RuntimeError("Delta SQLite quick_check failed: " + str(ok))
    dates = db.execute(
        "SELECT date, COUNT(*) FROM delta.game GROUP BY date ORDER BY date"
    ).fetchall()
    db.execute("DETACH DATABASE delta")
    db.close()
    return counts, dates, len(views)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--after", required=True)
    p.add_argument("--through", required=True)
    p.add_argument("--release-tag", required=True)
    p.add_argument("--expected-games", type=int, required=True)
    p.add_argument("--expected-kyoku", type=int, required=True)
    p.add_argument("--expected-events", type=int, required=True)
    p.add_argument("--output", default="weekly-delta-out")
    a = p.parse_args()
    out = Path(a.output)
    out.mkdir(exist_ok=True, parents=True)
    release, asset = source_release(a.release_tag)
    expect = {"game": a.expected_games, "kyoku": a.expected_kyoku,
              "event": a.expected_events}
    with tempfile.TemporaryDirectory(prefix="mahjong-delta-") as tmp:
        t = Path(tmp)
        raw_zip = t / "upstream.zip"
        src = t / "source.sqlite3"
        dest = t / "delta.sqlite3"
        archive_sha = download_asset(
            asset["browser_download_url"], asset["size"], raw_zip)
        print("downloaded upstream ZIP", asset["size"], flush=True)
        info = extract_sqlite(raw_zip, src)
        source_checks = validate_sqlite(src)
        counts, dates, nviews = export_slice(
            src, dest, a.after, a.through, expect)
        del_hash = hash_file(dest)
        report = {
            "status": "success",
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "baseline_through": a.after,
            "extract_through": a.through,
            "source_release": a.release_tag,
            "source_release_published_at": release.get("published_at"),
            "source_zip_sha256": archive_sha,
            "source_sqlite_bytes": info["sqlite_bytes"],
            "source_validation": source_checks,
            "delta_sqlite_sha256": del_hash,
            "delta_sqlite_bytes": dest.stat().st_size,
            "delta_table_counts": counts,
            "included_dates": dates,
            "view_count": nviews,
            "dimensions": sorted(DIMENSIONS),
            "policy": "source and fixed baseline are not modified; import delta as a separate, reviewed version"
        }
        out_zip = out / ("mahjong-delta-after-" + a.after + "-through-" + a.through + ".zip")
        report_txt = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        (out / "manifest.json").write_text(report_txt, encoding="utf-8")
        with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6) as z:
            z.write(dest, "delta.sqlite3")
            z.writestr("manifest.json", report_txt)
        if out_zip.stat().st_size >= 95 * 1024 * 1024:
            raise RuntimeError("Delta ZIP exceeds safe 95MiB transfer target")
        with zipfile.ZipFile(out_zip) as z:
            if z.testzip() is not None:
                raise RuntimeError("Archive CRC verification failed")
            with z.open("delta.sqlite3") as stream:
                h = hashlib.sha256()
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    h.update(block)
                if h.hexdigest() != del_hash:
                    raise RuntimeError("ZIP unpacked SQLite digest mismatch")
        print("DELTA_RESULT " + json.dumps({
            "source_release": a.release_tag,
            "game": counts["game"], "kyoku": counts["kyoku"],
            "event": counts["event"], "tables": len(counts),
            "sqlite_bytes": dest.stat().st_size,
            "zip_bytes": out_zip.stat().st_size,
            "zip_sha256": hash_file(out_zip),
            "delta_sqlite_sha256": del_hash,
            "dates": dates,
            "zip_path": str(out_zip)
        }, ensure_ascii=False), flush=True)
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("DELTA_FAILED " + repr(exc), file=sys.stderr, flush=True)
        raise
