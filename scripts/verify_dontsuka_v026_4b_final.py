"""Independently compare output rows to provisional run and check all aggregations."""
import csv, json, sys, zipfile, io
from pathlib import Path
from collections import Counter, defaultdict
from decimal import Decimal
old=zipfile.ZipFile(sys.argv[1]);out=Path(sys.argv[2])
def prev(n):return list(csv.DictReader(io.TextIOWrapper(old.open(n),encoding="utf-8-sig")))
def now(n):
    with (out/n).open(encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f))
def key(x):return (x["kyoku_id"],x["player_id"])
r=now("coexistence_kyoku.csv");t=now("coexistence_timeline.csv");d=now("all_ron_decisions.csv")
assert len({key(x) for x in r})==len(r)
assert len({x["ron_event_id"] for x in d})==len(d)
assert len({(*key(x),x["event_id"]) for x in t})==len(t)
state={};ever=set();counts=defaultdict(Counter)
for x in t:
    k=key(x);before=bool(json.loads(x["previous_down"]) and json.loads(x["previous_maintain"]));after=bool(json.loads(x["down_origins"]) and json.loads(x["maintain_origins"]))
    assert state.get(k,False)==before
    expected=("restart" if k in ever else "start") if after and not before else "end" if before and not after else "change" if after and before else None
    assert x["transition"]==expected
    if after:ever.add(k)
    state[k]=after;counts[k][expected]+=1
assert not any(state.values()) and ever=={key(x) for x in r}
def rank(sc,p):
    sc=json.loads(sc);v=sc[p];return 1+sum(w>v for w in sc.values())+(sum(w==v for w in sc.values())-1)/2
byround=defaultdict(Counter)
for x in d:
    assert rank(x["scores_before"],x["player_id"])==float(x["rank_before"])
    assert rank(x["scores_end"],x["player_id"])==float(x["rank_end"])
    active=set(map(tuple,json.loads(x["maintain_origins"])))
    matched={(int(a["draw_event_id"]),int(a["target"])) for a in json.loads(x["all_approved_links"]) if a["relation"] in ("immediate","subsequent") and int(a["same_target"])==1 and int(a["target"])==int(x["winner"])} & active
    assert matched==set(map(tuple,json.loads(x["matching_origins"])))
    tol=bool(active and json.loads(x["down_origins"]) and matched and x["source_kind"]=="discard" and x["rank_before"]==x["rank_end"])
    assert tol==bool(int(x["tolerated"]))
    if tol and x["accepted_before"]=="0":assert x["sage"]=="1"
    if tol and x["accepted_before"]=="1" and x["tsumogiri"]=="1":assert x["sage"]=="0" and x["reach_tsumogiri_excluded"]=="1"
    for f in ("tolerated","sage","reach_tsumogiri_excluded"):byround[key(x)][f]+=int(x[f])
for x in r:
    for a,b in (("starts","start"),("ends","end"),("restarts","restart")):assert int(x[a])==counts[key(x)][b]
    for f in ("tolerated","sage","reach_tsumogiri_excluded"):assert int(x[f])==byround[key(x)][f]
fields={"coexist_kyoku":None,"starts":"starts","ends":"ends","restarts":"restarts","tolerated":"tolerated","sage_numerator":"sage","sage_denominator":None,"reach_tsumogiri_excluded":"reach_tsumogiri_excluded"}
for fn,player in [("metrics_by_player.csv",True),("metrics_all_scopes.csv",False)]:
    for x in now(fn):
        group=[q for q in r if (not player or q["player_id"]==x["player_id"]) and (not x["season_start_year"] or q["season_start_year"]==x["season_start_year"]) and (not x["stage"] or q["stage"]==x["stage"])]
        for f,g in fields.items():assert int(x[f])==(sum(int(q[g]) for q in group) if g else len(group))
        a,b=int(x["sage_numerator"]),int(x["sage_denominator"])
        if b:assert abs(Decimal(x["sage_rate"])-Decimal(100*a)/Decimal(b))<Decimal("0.000000001")
        else:assert x["sage_rate"]==""
olddec={x["ron_event_id"]:x for x in prev("all_ron_decisions.csv")}
newdec={x["ron_event_id"]:x for x in d}
changes=[]
for k in sorted(olddec.keys()|newdec.keys()):
    a,b=olddec.get(k,{}),newdec.get(k,{})
    delta={f:[a.get(f),b.get(f)] for f in sorted(a.keys()|b.keys()) if a.get(f)!=b.get(f)}
    if delta:changes.append({"ron_event_id":k,"kyoku_id":b.get("kyoku_id",a.get("kyoku_id")),"player_id":b.get("player_id",a.get("player_id")),"source_event_id":b.get("source_event_id",a.get("source_event_id")),"differences":delta})
m=json.loads((out/"manifest.json").read_text())
result={"status":"independent_row_and_scope_reconciliation_passed","provisional_timeline_equal":prev("coexistence_timeline.csv")==t,"changed_decisions":changes,"old_unresolved_count":len(prev("unresolved.csv")),"new_unresolved_count":len(now("unresolved.csv")),"errors":len(now("discrepancies.csv")),"counts":m["counts"],"coexistence_14_tile_audit":m["coexistence_14_tile_audit"]}
(out/"additional_verification.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
print(json.dumps(result,ensure_ascii=False))
