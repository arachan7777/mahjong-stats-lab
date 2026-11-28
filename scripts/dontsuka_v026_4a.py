"""Stage 4A only. Read pinned DB and approved 3A/3B/2B artifacts."""
import argparse, json, os, traceback
from collections import Counter, defaultdict
from pathlib import Path
from dontsuka_v026_extract import connect_readonly, verify_database, sha256_file
from dontsuka_v026_2b_replay import RELEASE, DB_SHA
from dontsuka_v026_2a_audit import events
from dontsuka_v026_3b import verified_zip, read_csv_zip, write_csv, rates, STAGE3A_SHA, STAGE2B_SHA
from dontsuka_v026_4a_tracker import Tracker, classify

STAGE3B_SHA="9c9d4d112f1b17d4ff75db922205887888374b72439888299105e2a0c8957668"
FIELDS=("all_draws","basic_dontsuka","opponent_dontsuka","all_ron","tsumogiri_ron",
        "dontsuka_kyoku","dontsuka_kyoku_ron","immediate","subsequent","different_tile",
        "no_ron","special_excluded","unclassified","same_target","other_target",
        "immediate_avoided_draws")
def keys(season,stage):
    return [("all_period","",""),("season",str(season),""),("stage","",stage),
            ("season_stage",str(season),stage)]
def main():
    ap=argparse.ArgumentParser()
    for n in ("db","stage3a","stage2b","stage3b","out"): ap.add_argument(n,type=Path)
    a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    c=connect_readonly(a.db);dbm=verify_database(c,RELEASE)
    if sha256_file(a.db)!=DB_SHA: raise ValueError("DB hash")
    z3a,m3a=verified_zip(a.stage3a,STAGE3A_SHA)
    z2b,m2b=verified_zip(a.stage2b,STAGE2B_SHA)
    z3b,m3b=verified_zip(a.stage3b,STAGE3B_SHA)
    for m in (m3a,m2b,m3b):
        if m["database_sha256"]!=DB_SHA:raise ValueError("input DB hash")
    origins=read_csv_zip(z3a,"opponent_hypothetical_all.csv")
    by_draw=defaultdict(list)
    for r in origins:by_draw[int(r["draw_event_id"])].append(r)
    if (len(origins),len(by_draw),len({(r["draw_event_id"],r["target"]) for r in origins}),
        sum(float(r["rank_drop"])>0 for r in origins),
        sum(float(r["rank_drop"])==0 for r in origins),
        sum(any(float(r["rank_drop"])>0 for r in v) for v in by_draw.values()))!=(28060,27578,28060,13170,14890,12973):
        raise ValueError("approved 3A counts")
    heads=read_csv_zip(z3a,"head_bump_all.csv")
    if len(heads)!=27578 or sum(float(r["rank_drop"])>0 for r in heads)!=12931:
        raise ValueError("head counts")
    prior=read_csv_zip(z3b,"rank_drop_kyoku_details.csv")
    prior_map={(int(r["kyoku_id"]),int(r["player_id"])):int(r["actual_ron"]) for r in prior}
    if len(prior_map)!=11143 or sum(prior_map.values())!=3381 or sum(int(r["rank_maintained_or_improved"]) for r in prior)!=4518:
        raise ValueError("approved 3B counts")
    names={int(r[0]):r[1] for r in c.execute("SELECT id,name FROM player")}
    meta={int(r[0]):dict(game_id=int(r[1]),game_date=r[2],season_start_year=int(r[3]),stage=r[4]) for r in c.execute("""
      SELECT k.id,g.id,g.date,ls.start_year,ss.stage FROM kyoku k JOIN game g ON g.id=k.game_id
      JOIN season_stage ss ON ss.id=g.season_stage_id JOIN league_season ls ON ls.id=ss.league_season_id""")}
    stats=defaultdict(Counter)
    for p,s,t in c.execute("""SELECT DISTINCT gr.player_id,ls.start_year,ss.stage FROM game_player_result gr
      JOIN game g ON g.id=gr.game_id JOIN season_stage ss ON ss.id=g.season_stage_id
      JOIN league_season ls ON ls.id=ss.league_season_id"""):
        for key in keys(s,t):stats[(p,*key)]
    def add(p,ky,**vals):
        m=meta[ky]
        for key in keys(m["season_start_year"],m["stage"]):stats[(p,*key)].update(vals)
    all_origins=[];changes=[];links=[];class_rows=[];round_rows=[];errors=[];examples={}
    seen=set();draw_total=0;actual_pairs=set();actual_ids=set();immediate_ids=set();ron_source_ids=set()
    db_ron={int(r["event_id"]):dict(r) for r in c.execute("""SELECT a.*,e.kyoku_id FROM agari_event a
      JOIN event e ON e.id=a.event_id WHERE e.type='ron'""")}
    for index,ky in enumerate(sorted(meta)):
        tr=Tracker();local_rons=[];local_links=[];local_seen=set();local_draws=Counter()
        ev=None
        try:
            flags={int(r[0]):int(r[1]) for r in c.execute("""SELECT d.event_id,d.is_tsumogiri
              FROM discard_event d JOIN event e ON e.id=d.event_id WHERE e.kyoku_id=?""",(ky,))}
            seq=list(events(c,ky))
            for ev in seq:
                kind=ev["type"];eid=ev["id"]
                if kind=="ron":
                    r,l=classify(tr,db_ron[eid]);local_rons.append(r);local_links.extend(l)
                elif kind not in ("tsumo","ryukyoku"):
                    hit=by_draw.get(eid,())
                    if hit:local_seen.add(eid)
                    if kind=="draw":local_draws[ev["actor"]]+=1
                    tr.step(ev,hit,flags[eid] if kind=="discard" else None)
            tr.finish(seq[-1])
        except Exception as ex:
            errors.append(dict(kyoku_id=ky,event_id=ev["id"] if ev else "",error=repr(ex),traceback=traceback.format_exc()))
            continue
        seen.update(local_seen);draw_total+=sum(local_draws.values())
        for p,n in local_draws.items():add(p,ky,all_draws=n)
        all_origins.extend(tr.origins);changes.extend(tr.changes);links.extend(local_links)
        class_rows.extend(dict(r,**meta[ky]) for r in local_rons)
        own=defaultdict(list)
        for o in tr.origins:own[int(o["drawer"])].append(o)
        actual_by_player=defaultdict(list)
        for r in local_rons:
            p=r["player_id"];actual_by_player[p].append(r)
            actual_pairs.add((ky,p));actual_ids.add(r["ron_event_id"])
            ron_source_ids.add(r["source_event_id"])
            add(p,ky,all_ron=1,tsumogiri_ron=r["tsumogiri"])
            if r["category"]!="no_dontsuka":
                add(p,ky,**{r["category"]:1})
                if r["target_class"]:add(p,ky,**{r["target_class"]:1})
            examples.setdefault(r["category"],dict(r,**meta[ky]))
        for l in local_links:
            if l["relation"]=="immediate":immediate_ids.add(l["draw_event_id"])
            if l["relation"]=="same_type_after_end_unclassified":
                examples.setdefault("same_type_after_end",dict(l,kyoku_id=ky,**meta[ky]))
        for p,os_ in own.items():
            draws={int(o["draw_event_id"]) for o in os_};rr=actual_by_player[p]
            immediate=len(draws&immediate_ids)
            add(p,ky,basic_dontsuka=len(draws),opponent_dontsuka=len(os_),dontsuka_kyoku=1,
                dontsuka_kyoku_ron=int(bool(rr)),no_ron=int(not rr),immediate_avoided_draws=len(draws)-immediate)
            round_rows.append(dict(kyoku_id=ky,player_id=p,**meta[ky],basic_dontsuka=len(draws),
                                   actual_ron=int(bool(rr)),ron_events=len(rr),immediate_avoided_draws=len(draws)-immediate,
                                   category=rr[0]["category"] if len(rr)==1 else ("no_ron" if not rr else "multiple_actual_ron")))
        for o in tr.origins:
            if o["before_count"]>0:examples.setdefault("preexisting_same_type",dict(o,**meta[ky]))
        for h in tr.changes:
            if h["after_count"]>0 and h["after_count"]<h["before_count"]:examples.setdefault("partial_consumption",dict(h,kyoku_id=ky,**meta[ky]))
            if h["event_type"] in ("chi","pon","daiminkan","ankan","shominkan"):examples.setdefault(h["event_type"],dict(h,kyoku_id=ky,**meta[ky]))
        if index%1000==0:print("kyoku",index,"errors",len(errors),flush=True)
    def emit(name,rows,fields):
        write_csv(a.out/name,rows,list(dict.fromkeys(fields+[k for r in rows for k in r])))
    emit("tile_possession_intervals.csv",all_origins,["draw_event_id","target"])
    emit("tile_possession_changes.csv",changes,["draw_event_id","target","event_id"])
    emit("origin_ron_links.csv",links,["draw_event_id","target","ron_event_id"])
    emit("actual_ron_classification.csv",class_rows,["ron_event_id","category"])
    emit("dontsuka_kyoku_classification.csv",round_rows,["kyoku_id","player_id","category"])
    emit("unclassified.csv",[r for r in class_rows if r["category"]=="unclassified"],["ron_event_id","category"])
    emit("real_play_examples.csv",[dict(example_type=k,**v) for k,v in examples.items()],["example_type"])
    checks={
        "all_draws":draw_total==1257732,"all_origins":len(all_origins)==28060 and seen==set(by_draw),
        "all_actual_ron":actual_ids==set(db_ron) and len(class_rows)==len(actual_ids)==11031,
        "3b_ron":all(int(k in actual_pairs)==v for k,v in prior_map.items()),
        "3b_down_keys":{(int(o["kyoku_id"]),int(o["drawer"])) for o in all_origins if float(o["rank_drop"])>0}==set(prior_map),
        "unique_ron_source":len(ron_source_ids)==len(actual_ids),
        "unique_origin_links":len(links)==len({(r["draw_event_id"],r["target"],r["ron_event_id"]) for r in links}),
        "immediate_identity":len(immediate_ids)==sum(r["category"]=="immediate" for r in class_rows),
        "kyoku_unique":len(round_rows)==len({(r["kyoku_id"],r["player_id"]) for r in round_rows})}
    for k,v in checks.items():
        if not v:errors.append(dict(kyoku_id="",event_id="",error="failed check: "+k,traceback=""))
    def metrics(s):
        row={f:s[f] for f in FIELDS}
        for label,n,d in [("all_tsumogiri_ron_rate","tsumogiri_ron","all_draws"),
                          ("dontsuka_immediate_ron_rate","immediate","basic_dontsuka"),
                          ("tsumogiri_share_of_ron","tsumogiri_ron","all_ron"),
                          ("dontsuka_kyoku_ron_rate","dontsuka_kyoku_ron","dontsuka_kyoku")]:
            row.update({label+"_numerator":s[n],label+"_denominator":s[d],label:rates(s[n],s[d])})
        return row
    player_rows=[];combined=defaultdict(Counter)
    for (p,scope,season,stage),s in sorted(stats.items()):
        player_rows.append(dict(player_id=p,player_name=names[p],scope=scope,season_start_year=season,stage=stage,**metrics(s)))
        combined[(scope,season,stage)].update(s)
    total_rows=[dict(scope=k[0],season_start_year=k[1],stage=k[2],**metrics(v)) for k,v in sorted(combined.items())]
    overall=combined[("all_period","","")]
    if sum(overall[k] for k in ("immediate","subsequent","different_tile","special_excluded","unclassified"))!=overall["dontsuka_kyoku_ron"] or overall["no_ron"]+overall["dontsuka_kyoku_ron"]!=overall["dontsuka_kyoku"]:
        errors.append(dict(error="partition mismatch"))
    emit("metrics_by_player.csv",player_rows,["player_id","scope"])
    emit("metrics_all_scopes.csv",total_rows,["scope"])
    emit("discrepancies.csv",errors,["kyoku_id","event_id","error","traceback"])
    manifest=dict(scope="Stage 4A only",status="incomplete" if errors else "computed",
                  database=dbm,database_sha256=DB_SHA,stage3a_sha256=STAGE3A_SHA,
                  stage2b_sha256=STAGE2B_SHA,stage3b_sha256=STAGE3B_SHA,checks=checks,
                  counts=metrics(overall),error_count=len(errors),examples=list(examples),
                  unclassified_policy="same tile after continuous possession ended; not forced into different tile",
                  special_policy="all recorded ron included in all-ron and kyoku denominators; kan ron excluded from causal categories")
    (a.out/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(manifest,ensure_ascii=False),flush=True)
    if errors:raise SystemExit(1)
if __name__=="__main__":main()
