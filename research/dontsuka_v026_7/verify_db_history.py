"""Stage 7 independent DB history audit; no shanten replay or new research definitions.
Use SQL event succession and prior discard history, not the stage 7 Linker/History classes.
"""
import csv,gzip,hashlib,io,json,sys,time,zipfile
from pathlib import Path
from collections import Counter,defaultdict
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"scripts"))
from dontsuka_v026_extract import connect_readonly,verify_database,sha256_file
from dontsuka_v026_2b_replay import DB_SHA,RELEASE

def require(x,m):
    if not x:raise ValueError(m)
def rows(z,n):
    with z.open(n) as f,gzip.GzipFile(fileobj=f) as g,io.TextIOWrapper(g,encoding="utf-8-sig") as t:
        yield from csv.DictReader(t)
def norm(t):return "5"+t[1:] if t.startswith("0") else t
def main():
    db,p,out=map(Path,sys.argv[1:4]);expected=sys.argv[4]
    out.mkdir(parents=True,exist_ok=True);start=time.monotonic()
    c=connect_readonly(db);verify_database(c,RELEASE);require(sha256_file(db)==DB_SHA,"DB digest")
    require(sha256_file(p)==expected,"stage7 archive digest")
    z=zipfile.ZipFile(p);require(z.testzip() is None,"CRC")
    m=json.loads(z.read("package_sha256.json"))
    require(set(m)==set(z.namelist())-{"package_sha256.json"},"package members")
    for k,v in m.items():
        with z.open(k) as f:require(hashlib.file_digest(f,"sha256").hexdigest()==v,"hash "+k)
    # Independently determine action successor using a SQL window over event
    # order; reach and indicator metadata do not constitute a draw's discard.
    sql="""WITH actions AS (
      SELECT id,kyoku_id,event_order,type FROM event
      WHERE type IN ('draw','discard','chi','pon','daiminkan','ankan','shominkan','ron','tsumo','ryukyoku')
    ), seq AS (
      SELECT *,lead(id) OVER w AS n1,lead(type) OVER w AS t1,lead(event_order) OVER w AS o1,
        lead(id,2) OVER w AS n2,lead(type,2) OVER w AS t2,lead(event_order,2) OVER w AS o2
      FROM actions WINDOW w AS (PARTITION BY kyoku_id ORDER BY event_order,id)
    )
    SELECT s.*,d.actor_player_id AS p,d.tile AS tile,d.is_rinshan AS rinshan,
      nd.actor_player_id AS next_discard_actor,nd.tile AS next_discard_tile,
      nd.is_tsumogiri AS next_tsumogiri,nd.is_reach_declaration AS next_decl,
      coalesce(ak.actor_player_id,sk.actor_player_id) AS kan_actor,
      rd.actor_player_id AS rinshan_actor,rd.is_rinshan AS next_rinshan
    FROM seq s JOIN draw_event d ON d.event_id=s.id
    LEFT JOIN discard_event nd ON nd.event_id=s.n1
    LEFT JOIN ankan_event ak ON ak.event_id=s.n1
    LEFT JOIN shominkan_event sk ON sk.event_id=s.n1
    LEFT JOIN draw_event rd ON rd.event_id=s.n2
    WHERE s.type='draw'"""
    expected_draw={}
    for r in c.execute(sql):
        eid,ky,o,pid=int(r["id"]),int(r["kyoku_id"]),int(r["event_order"]),int(r["p"])
        n1,t1,o1,n2,t2,o2=(r[k] for k in ("n1","t1","o1","n2","t2","o2"))
        require(n1 is not None,"draw without successor")
        if t1=="discard" and r["next_discard_actor"]==pid:
            link="discard";d=(n1,o1,r["next_discard_tile"],int(r["next_tsumogiri"]),int(r["next_decl"]));end=();kan=()
        else:
            d=();end=(n1,o1);kan=()
            if t1 in ("ankan","shominkan") and r["kan_actor"]==pid:
                kan=(n1,t1,o1);end=(n2,o2)
                require(t2 in ("draw","ron","tsumo","ryukyoku"),"unexpected successor after kan")
                link="kan_robbed" if t2=="ron" else "kan_before_rinshan" if t2=="draw" else "kan_round_end"
                if t2=="draw":
                    if r["rinshan_actor"]!=pid:link="kan_followed_by_other_draw"
                    elif r["next_rinshan"]!=1:link="kan_followed_by_own_draw_unmarked"
            elif t1=="draw":link="next_draw_without_discard"
            elif t1=="discard":link="other_discard_before_own_discard"
            elif t1 in ("chi","pon","daiminkan","ankan","shominkan"):link="call_without_own_discard"
            elif t1=="tsumo":link="tsumo_win"
            else:link="round_end_without_discard"
        require(eid not in expected_draw,"duplicate DB draw")
        expected_draw[eid]=(ky,o,pid,r["tile"],int(r["rinshan"]),link,d,end,kan)
    require(len(expected_draw)==1257732,"DB draw scope")
    seen=set();counts=Counter();accepted_draw_discard={};unexpected=[]
    for r in rows(z,"final/all_draws.csv.gz"):
        eid=int(r["draw_event_id"]);require(eid not in seen and eid in expected_draw,"stage7 draw key");seen.add(eid)
        ky,o,pid,tile,rinshan,link,d,end,kan=expected_draw[eid]
        require((ky,o,pid,tile,rinshan,link)==(int(r["kyoku_id"]),int(r["event_order"]),int(r["player_id"]),r["draw_tile"],int(r["rinshan"]),r["link_reason"]),"draw attributes and next action")
        if d:
            require(r["has_discard"]=="1" and d==(int(r["discard_event_id"]),int(r["discard_order"]),r["discard_tile"],int(r["tsumogiri"]),int(r["declaration"])),"discard event identity")
            accepted_draw_discard[int(r["discard_event_id"])]=(ky,pid,int(r["discard_order"]),int(r["accepted_before"]),int(r["accepted_after"]))
        else:
            require(r["has_discard"]=="0" and end==(int(r["terminal_or_next_event_id"]),int(r["terminal_or_next_order"])),"no-discard successor")
            if kan:require(kan==(int(r["kan_event_id"]),r["kan_kind"],int(r["kan_order"])),"kan event identity")
        counts[link]+=1
        if link not in ("discard","tsumo_win","kan_before_rinshan","kan_robbed"):
            context=[dict(x) for x in c.execute("""SELECT e.id,e.event_order,e.type,
              coalesce(dr.actor_player_id,ds.actor_player_id) AS actor,
              coalesce(dr.tile,ds.tile) AS tile
              FROM event e LEFT JOIN draw_event dr ON dr.event_id=e.id
              LEFT JOIN discard_event ds ON ds.event_id=e.id
              WHERE e.kyoku_id=? AND e.event_order>=? AND e.event_order<=?
              ORDER BY e.event_order,e.id""",(ky,o-6,end[1]+6))]
            unexpected.append(dict(detail=r,recorded_event_context=context))
    require(seen==set(expected_draw),"draw coverage")
    del expected_draw
    # Accepted riichi marker is emitted before its declaration discard in
    # this DB. The established boundary is that accepted declaration discard.
    declarations={}
    for r in c.execute("""SELECT e.kyoku_id,r.actor_player_id AS p,e.event_order AS marker,
         de.id AS declaration_id,de.event_order AS declaration_order
       FROM reach_event r JOIN event e ON e.id=r.event_id
       JOIN discard_event d ON d.actor_player_id=r.actor_player_id AND d.is_reach_declaration=1
       JOIN event de ON de.id=d.event_id AND de.kyoku_id=e.kyoku_id AND de.event_order>e.event_order
       WHERE r.is_accepted=1"""):
        key=(int(r["kyoku_id"]),int(r["p"]))
        require(key not in declarations,"accepted declaration duplicate")
        declarations[key]=(int(r["declaration_id"]),int(r["declaration_order"]),int(r["marker"]))
    require(len(declarations)==22205,"accepted riichi count")
    for did,(ky,pid,o,ab,aa) in accepted_draw_discard.items():
        d=declarations.get((ky,pid));require(ab==int(d is not None and d[1]<o) and aa==int(d is not None and d[1]<=o),"established reach boundary")
    pairs=list(rows(z,"final/opponent_genbutsu.csv.gz"))
    relevant={int(r["kyoku_id"]) for r in pairs}
    history=defaultdict(list)
    for r in c.execute("""SELECT e.kyoku_id,e.event_order,e.id,d.actor_player_id,d.tile
      FROM discard_event d JOIN event e ON e.id=d.event_id ORDER BY e.kyoku_id,e.event_order,e.id"""):
        if int(r[0]) in relevant:history[(int(r[0]),norm(r[4]))].append((int(r[1]),int(r[2]),int(r[3])))
    pairseen=set();g=Counter();proof=defaultdict(list)
    for r in pairs:
        key=(int(r["draw_event_id"]),int(r["target_id"]));require(key not in pairseen,"pair duplicate");pairseen.add(key)
        if r["has_discard"]=="0":
            require(r["genbutsu"]=="" and r["genbutsu_reason"]=="no_corresponding_discard","pair without discard")
            g["no_discard"]+=1;continue
        ky,t,o=int(r["kyoku_id"]),key[1],int(r["discard_order"]);d=declarations.get((ky,t))
        reached=d is not None and d[1]<o
        require(int(r["target_accepted_before"])==int(reached),"target reach state")
        require(r["target_reach_declaration_id"]==(str(d[0]) if reached else ""),"target reach evidence")
        past=[x for x in history[(ky,norm(r["discard_tile"]))] if x[0]<o]
        own=[x for x in past if x[2]==t]
        passed=[x for x in past if reached and d[1]<x[0] and x[2]!=t]
        choice=own[-1] if own else passed[-1] if passed else None
        why="target_own_discard" if own else "passed_after_accepted_reach" if passed else "no_prior_qualifying_discard"
        require(r["genbutsu"]==str(int(choice is not None)) and r["genbutsu_reason"]==why,"genbutsu classification vs SQL history")
        if choice:require(choice==(int(r["evidence_order"]),int(r["evidence_event_id"]),int(r["evidence_player_id"])),"genbutsu evidence vs SQL")
        else:require(not r["evidence_event_id"] and not r["evidence_order"] and not r["evidence_player_id"],"unexpected evidence")
        g[why]+=1
        if len(proof[why])<5:proof[why].append(r)
    require(len(pairseen)==28060,"opponent coverage")
    result=dict(status="verified",database_sha256=DB_SHA,stage7_sha256=expected,package_members=len(m),draw_link_verified=len(seen),link_counts=dict(counts),accepted_declarations=len(declarations),discard_reach_boundary_verified=len(accepted_draw_discard),opponent_history_verified=len(pairseen),genbutsu_evidence_counts=dict(g),unexpected_successors=len(unexpected),elapsed_seconds=time.monotonic()-start)
    (out/"summary.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"unexpected_successors.json").write_text(json.dumps(unexpected,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"examples.json").write_text(json.dumps(proof,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
