"""Stage 2B only. Replay actual recorded transfers; never repair DB or use hypothetical honba as actual."""
import argparse, csv, json, os, gzip, sys
from collections import Counter
from pathlib import Path
from dontsuka_v026_extract import connect_readonly, verify_database, sha256_file

RELEASE="20261120-2341-04338cbb"
DB_SHA="edeccd86e100f6ffba88871d7c418a06488d3f515b22cdd2e2b9dced17573e6c"
SPECIAL=2530825
NEUTRAL={"haipai","discard","pon","chi","daiminkan","shominkan","ankan","dora_indicator"}

def ranks(scores):
    # Average of occupied ranks: 1 + number above + (number equal - 1)/2.
    return {p:1+sum(v>s for v in scores.values())+(sum(v==s for v in scores.values())-1)/2
            for p,s in scores.items()}

def tsumo_split(total, winner, dealer, ids):
    # In units of 100: parent winner has three identical payments.
    # Child winner: dealer pays 2*c or 2*c-1, other two each c.
    if total<=0 or total%100: raise ValueError("invalid recorded tsumo total")
    n=total//100
    if winner==dealer:
        if n%3: raise ValueError("nondivisible dealer tsumo")
        return {p:100*(n//3) for p in ids if p!=winner}
    c=(n+3)//4
    d=n-2*c
    if d not in (2*c,2*c-1) or d<=0: raise ValueError("invalid child tsumo split")
    return {p:100*(d if p==dealer else c) for p in ids if p!=winner}

class Ledger:
    def __init__(self,scores,sticks,dealer,honba):
        self.s=dict(scores); self.sticks=sticks; self.dealer=dealer; self.honba=honba
        self.reached=set(); self.terminal=False
        self.check()
    def check(self):
        if len(self.s)!=4 or self.sticks<0 or sum(self.s.values())+1000*self.sticks!=100000:
            raise ValueError(f"point conservation: {self.s} sticks={self.sticks}")
        if sum(ranks(self.s).values())!=10: raise ValueError("rank sum")
    def step(self,kind,row):
        if self.terminal: raise ValueError("event after terminal")
        if kind=="reach":
            p=row["actor_player_id"]
            if row["is_accepted"] not in (0,1): raise ValueError("invalid reach flag")
            if row["is_accepted"]:
                if p in self.reached: raise ValueError("duplicate accepted reach")
                self.reached.add(p);self.s[p]-=1000;self.sticks+=1
        elif kind in ("ron","tsumo"):
            p=row["actor_player_id"];base=row["agari_points"];honba=row["honba_points"];pot=row["kyotaku_points"]
            if pot!=1000*self.sticks: raise ValueError("recorded pot differs from replay")
            if kind=="ron":
                target=row["target_player_id"]
                if target==p: raise ValueError("self ron")
                pay={target:base+honba}
            else:
                if honba%3: raise ValueError("nondivisible recorded honba")
                pay={q:v+honba//3 for q,v in tsumo_split(base,p,self.dealer,self.s).items()}
            for q,v in pay.items():self.s[q]-=v
            self.s[p]+=sum(pay.values())+pot;self.sticks=0;self.terminal=True
        elif kind=="ryukyoku":
            delta=row["delta"]
            if set(delta)!=set(self.s) or sum(delta.values())!=0: raise ValueError("invalid draw delta")
            for p,v in delta.items():self.s[p]+=v
            self.terminal=True
        elif kind=="draw" or kind in NEUTRAL: pass
        else: raise ValueError("unexpected type "+kind)
        self.check()

def js(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"))
def jwrite(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
def rows(c,sql,args=()):return [dict(r) for r in c.execute(sql,args)]
def event_rows(c,ky):
    return c.execute("""SELECT e.id,e.type,e.event_order,
      d.actor_player_id AS draw_actor,d.tile AS draw_tile,d.is_rinshan,
      r.actor_player_id AS reach_actor,r.is_accepted,
      a.actor_player_id AS winner,a.target_player_id,a.agari_points,a.honba_points,a.kyotaku_points
      FROM event e LEFT JOIN draw_event d ON d.event_id=e.id
      LEFT JOIN reach_event r ON r.event_id=e.id
      LEFT JOIN agari_event a ON a.event_id=e.id
      WHERE e.kyoku_id=? ORDER BY e.event_order,e.id""",(ky,))
def finish(s,sticks,initial_seats):
    # Reference-only possible final settlement. DB game.score retains unclaimed sticks outside player scores; do not apply this to actual replay or match criterion.
    final=dict(s)
    top=min(s,key=lambda p:(-s[p],initial_seats[p]))
    final[top]+=1000*sticks
    return final,top

def main():
    ap=argparse.ArgumentParser();ap.add_argument("db",type=Path);ap.add_argument("out",type=Path);a=ap.parse_args()
    a.out.mkdir(parents=True,exist_ok=True)
    c=connect_readonly(a.db);m=verify_database(c,RELEASE)
    dbsha=sha256_file(a.db)
    if dbsha!=DB_SHA:raise ValueError("SQLite hash mismatch")
    m.update(scope="2B only",database_sha256=dbsha,commit=os.getenv("GITHUB_SHA"),run_id=os.getenv("GITHUB_RUN_ID"))
    counters=Counter();bad=[];special=None;seen=set();errors=[];examples={}
    games=rows(c,"SELECT id,date FROM game ORDER BY id")
    with gzip.open(a.out/"draw_snapshots.csv.gz","wt",encoding="utf-8",newline="") as ds, \
         (a.out/"kyoku_comparison.csv").open("w",encoding="utf-8",newline="") as ks, \
         (a.out/"game_comparison.csv").open("w",encoding="utf-8",newline="") as gs, \
         (a.out/"point_movements.csv").open("w",encoding="utf-8",newline="") as ps:
        dw=csv.writer(ds);kw=csv.writer(ks);gw=csv.writer(gs);pw=csv.writer(ps)
        dw.writerow(["event_id","event_order","game_id","kyoku_id","draw_actor_player_id","tile","rinshan","honba","kyotaku_sticks"]+[f"{field}_{i}" for i in range(1,5) for field in ("player_id","score","average_rank")])
        kw.writerow(["game_id","kyoku_id","round","honba","start_scores","start_sticks","replayed_end_scores","recorded_end_scores","end_sticks","replayed_average_ranks","recorded_score_average_ranks","match","error"])
        gw.writerow(["game_id","raw_end_scores","remaining_sticks","reference_settlement_top","reference_settled_scores","recorded_scores","raw_match","reference_settled_match","match","error"])
        pw.writerow(["game_id","kyoku_id","event_id","event_order","type","before_scores","after_scores","before_sticks","after_sticks","recorded_base","recorded_honba","recorded_kyotaku","actor","target","accepted","error"])
        for g in games:
            gid=g["id"]
            # Order by chronological event_order, never by event_id.
            kys=rows(c,"""SELECT k.*, (SELECT MIN(event_order) FROM event WHERE kyoku_id=k.id) AS first_order
                          FROM kyoku k WHERE game_id=? ORDER BY first_order,k.id""",(gid,))
            gr={r["player_id"]:r["score"] for r in rows(c,"SELECT player_id,score FROM game_player_result WHERE game_id=?",(gid,))}
            s={p:25000 for p in gr};sticks=0;game_error="";last=None;initial_seats=None
            for k in kys:
                ky=k["id"];kr=rows(c,"SELECT player_id,score,player_wind,rank FROM kyoku_player_result WHERE kyoku_id=?",(ky,))
                expected={r["player_id"]:r["score"] for r in kr}
                if initial_seats is None:initial_seats={r["player_id"]:r["player_wind"] for r in kr}
                start=dict(s);start_sticks=sticks;err="";l=None;trace=[];last_order=None
                try:
                    if set(expected)!=set(s):raise ValueError("player roster mismatch")
                    if sticks!=k["kyotaku_count"]:raise ValueError("carry-in sticks mismatch")
                    l=Ledger(s,sticks,k["oya_player_id"],k["honba_count"])
                    for raw in event_rows(c,ky):
                        e=dict(raw);kind=e["type"];eid=e["id"];order=e["event_order"]
                        if last_order is not None and order<=last_order:raise ValueError("ambiguous event order")
                        last_order=order
                        if kind=="draw":
                            if eid in seen:raise ValueError("duplicate draw id")
                            if e["draw_actor"] not in s:raise ValueError("unknown draw actor")
                            seen.add(eid);r=ranks(l.s)
                            dw.writerow([eid,order,gid,ky,e["draw_actor"],e["draw_tile"],e["is_rinshan"],l.honba,l.sticks]+[v for p in sorted(s) for v in (p,l.s[p],r[p])])
                            counters["snapshots"]+=1
                            counters["rank_sum_10"]+=sum(r.values())==10
                            counters["tied_snapshots"]+=len(set(l.s.values()))<4
                            if l.sticks and "pre_draw_after_reach" not in examples:
                                examples["pre_draw_after_reach"]={"event":e,"scores":dict(l.s),"sticks":l.sticks,"ranks":r}
                        if kind=="reach":e["actor_player_id"]=e["reach_actor"]
                        if kind in ("ron","tsumo"):e["actor_player_id"]=e["winner"]
                        if kind=="ryukyoku":
                            e["delta"]={r["player_id"]:r["tenpai_points"] for r in rows(c,"SELECT player_id,tenpai_points FROM ryukyoku_player WHERE ryukyoku_event_id=?",(eid,))}
                        before=dict(l.s);pot=l.sticks
                        l.step(kind,e)
                        if kind in ("reach","ron","tsumo","ryukyoku"):
                            counters[kind]+=1
                            if kind=="reach":counters["accepted_reach" if e["is_accepted"] else "rejected_reach"]+=1
                            movement={"event":e,"before":before,"after":dict(l.s),"sticks_before":pot,"sticks_after":l.sticks}
                            trace.append(movement)
                            pw.writerow([gid,ky,eid,order,kind,js(before),js(l.s),pot,l.sticks,e["agari_points"],e["honba_points"],e["kyotaku_points"],e.get("actor_player_id"),e["target_player_id"],e["is_accepted"],""])
                            exkey=kind if kind!="reach" else ("accepted_reach" if e["is_accepted"] else "rejected_reach")
                            examples.setdefault(exkey,movement)
                        if eid==SPECIAL:
                            alt=Ledger(before,pot,k["oya_player_id"],k["honba_count"])
                            altered=dict(e,honba_points=k["honba_count"]*300);alt.step(kind,altered)
                            special={"event_id":eid,"game_id":gid,"kyoku_id":ky,"date":g["date"],"round":k["round"],"honba":k["honba_count"],"recorded_honba":e["honba_points"],"normal_honba":altered["honba_points"],"before":before,"recorded_transfer_end":dict(l.s),"normal_transfer_end":dict(alt.s),"db_kyoku_end":expected,"recorded_matches":l.s==expected,"normal_matches":alt.s==expected,"actual_delta":{p:l.s[p]-before[p] for p in before},"normal_delta":{p:alt.s[p]-before[p] for p in before},"movements":trace.copy()}
                    if not l.terminal:raise ValueError("missing terminal")
                    s=dict(l.s);sticks=l.sticks
                except Exception as ex:
                    err=repr(ex);errors.append({"game_id":gid,"kyoku_id":ky,"error":err})
                    # Never reseed from current recorded result: preserve continuous replay and mark rest invalid.
                    game_error=err
                ok=not err and not game_error and s==expected
                counters["kyoku_checked"]+=1;counters["kyoku_match"]+=ok
                kw.writerow([gid,ky,k["round"],k["honba_count"],js(start),start_sticks,js(s),js(expected),sticks,js(ranks(s)),js(ranks(expected)),int(ok),err or game_error])
                if not ok:bad.append({"level":"kyoku","game_id":gid,"kyoku_id":ky,"replayed":s.copy(),"recorded":expected,"error":err or game_error})
                last=ky
            final,top=finish(s,sticks,initial_seats)
            raw_ok=s==gr; settled_ok=final==gr
            ok=not game_error and raw_ok
            counters["game_checked"]+=1;counters["game_match"]+=ok;counters["game_raw_match"]+=raw_ok
            counters["game_remaining_pot"]+=bool(sticks)
            counters["reference_settlement_matches_db"]+=settled_ok
            gw.writerow([gid,js(s),sticks,top,js(final),js(gr),int(raw_ok),int(settled_ok),int(ok),game_error])
            if not ok:bad.append({"level":"game","game_id":gid,"replayed":s.copy(),"recorded":gr,"error":game_error})
    m.update(dict(counters));m.update(game_comparison_basis="raw reconstructed scores vs DB game_player_result.score; remaining sticks recorded separately", reference_settlement_basis="illustrative only; not actual score", unique_draw_ids=len(seen),difference_rows=len(bad),errors=len(errors),special_event_found=special is not None)
    jwrite(a.out/"differences.json",bad);jwrite(a.out/"errors.json",errors);jwrite(a.out/"honba_2530825.json",special);jwrite(a.out/"real_examples.json",examples)
    ok=(counters["snapshots"]==1257732==len(seen)==counters["rank_sum_10"] and counters["kyoku_match"]==25238==counters["kyoku_checked"] and counters["game_match"]==2068==counters["game_checked"] and not bad and not errors and special is not None)
    m["status"]="matched" if ok else "requires_review"
    jwrite(a.out/"manifest.json",m);print(json.dumps(m,ensure_ascii=False,indent=2))
    return 0 if ok else 1
if __name__=="__main__":sys.exit(main())
