"""End-to-end synthetic haipai/draw/discard event replay through Stage 4B RonState.
SQLite state rows derived from physical hands, not injected eligibility flags.
Closed hands only; temporary furiten derived from passed ordinary ron.
"""
import sqlite3, unittest
from collections import Counter, defaultdict
from mahjong.shanten import Shanten
from dontsuka_v026_2a_audit import evaluate, index, events
from dontsuka_v026_2a_replay import normal
from dontsuka_v026_4b import RonState
from dontsuka_v026_4b_core import state, coexists, transition, ron_result
from dontsuka_v026_2b_replay import ranks

TYPES=[str(n)+s for s in "mps" for n in range(1,10)]+[str(n)+"z" for n in range(1,8)]
WINDS={1:"1z",2:"2z",3:"3z",4:"4z"}
def split(s):return s.split()
def vec(h):
    v=[0]*34
    for t in h:v[index(t)]+=1
    return v
def sh(h):return Shanten().calculate_shanten(vec(h))
def shape(h):
    if len(h)!=13 or sh(h)!=0:return set()
    return {t for t in TYPES if vec(h)[index(t)]<4 and sh(h+[t])==-1}
def legal(h,t,p):
    try:
        return evaluate(h+[t],[],t,dict(is_tsumo=False,is_riichi=False,is_daburu_riichi=False,is_ippatsu=False,is_rinshan=False,is_chankan=False,is_haitei=False,is_houtei=False,first_uninterrupted=False),WINDS[p],"1z",[],[])["points"]
    except ValueError as e:
        if str(e) in ("hand calculator: no_yaku","hand calculator: hand_not_winning"):return None
        raise

def make(mode):
    hands={1:split("1m 2m 3m 4p 5p 6p 7s 8s 9s 3z 3z 2s 9m"),
           2:split("1m 2m 3m 4m 5m 6m 7m 8m 9m 1p 1p 2s 3s"),
           3:split("1p 2p 3p 4p 5p 6p 7p 8p 9p 2z 2z 6s 7s")}
    if mode=="damaten":hands[1]=split("1m 2m 3m 4p 5p 6p 2s 3s 4s 3z 3z 1s 9m")
    turns=[(1,"1s","9m"),(2,"7z","7z"),(3,"6z","6z"),(4,"5z","5z")]
    if mode=="declaration":turns += [(1,"5s","5s")]
    else:
        turns += [(1,"5s","2s" if mode=="damaten" else "3z")]
        if mode=="wait": turns += [(2,"2s","3s")]
        elif mode=="collapse":turns += [(2,"7z","3s")]
        elif mode=="permanent":turns += [(2,"4s","4s")]
        else:turns += [(2,"7z","7z")]
        turns += [(3,"6z","6z"),(4,"4s" if mode=="temporary" else "5z","4s" if mode=="temporary" else "5z"),(1,"4z","4z")]
        if mode=="collapse":turns += [(2,"3s","7z")]
        else:turns += [(2,"1z","1z")]
        turns += [(3,"6z","6z"),(4,"5z","5z"),(1,"4z","5s")]
    # Full physical tile pool; reserve all draws before assigning fourth hand.
    pool=Counter({t:4 for t in TYPES})
    for s in "mps":pool["5"+s]=3;pool["0"+s]=1
    for h in hands.values():pool.subtract(h)
    pool.subtract([d for _,d,_ in turns])
    assert min(pool.values())>=0
    hands[4]=list(pool.elements())[:13]
    assert len(hands[4])==13
    db=sqlite3.connect(":memory:");db.row_factory=sqlite3.Row
    db.executescript("""
    CREATE TABLE kyoku(id,round); INSERT INTO kyoku VALUES(1,'1z');
    CREATE TABLE kyoku_player_result(kyoku_id,player_id,player_wind);
    CREATE TABLE event(id,type,event_order,kyoku_id);
    CREATE TABLE haipai_event(event_id,actor_player_id,hand);
    CREATE TABLE draw_event(event_id,actor_player_id,tile,wall_remaining_count,is_rinshan);
    CREATE TABLE discard_event(event_id,actor_player_id,tile,is_reach_declaration);
    CREATE TABLE agari_event(event_id,actor_player_id,target_player_id,agari_tile);
    CREATE TABLE player_state(event_id,player_id,shanten_count);
    CREATE TABLE player_tenpai_state(event_id,player_id,is_furiten);
    CREATE TABLE tenpai_agari_matrix(event_id,player_id,waiting_tile,is_ron_agari);
    """)
    for p,w in WINDS.items():db.execute("INSERT INTO kyoku_player_result VALUES(1,?,?)",(p,w))
    eid=0; raw={}; river=defaultdict(set);temp=set();tags={}; origin_ids={}
    def add(k,p=None,t=None,h=None,decl=False,tag=None,winner=None):
        nonlocal eid
        eid+=1
        db.execute("INSERT INTO event VALUES(?,?,?,1)",(eid,k,eid))
        if k=="haipai":
            raw[p]=h.copy()
            db.execute("INSERT INTO haipai_event VALUES(?,?,?)",(eid,p,",".join(h)))
        elif k=="draw":
            raw[p].append(t);temp.discard(p)
            db.execute("INSERT INTO draw_event VALUES(?,?,?,?,0)",(eid,p,t,70-eid))
            if p==1 and t in ("1s","5s"):origin_ids[t]=eid
        elif k=="discard":
            raw[p].remove(t);river[p].add(normal(t))
            db.execute("INSERT INTO discard_event VALUES(?,?,?,?)",(eid,p,t,int(decl)))
            for q,hh in raw.items():
                if q!=p and q!=winner and normal(t) in shape(hh) and not shape(hh)&river[q] and q not in temp and legal(hh,t,q):
                    temp.add(q)
        elif k=="ron":
            db.execute("INSERT INTO agari_event VALUES(?,?,?,?)",(eid,3,1,"5s"))
        for q,hh in raw.items():
            db.execute("INSERT INTO player_state VALUES(?,?,?)",(eid,q,sh(hh)))
            if len(hh)==13 and sh(hh)==0:
                waits=shape(hh); fur=bool(waits&river[q]) or q in temp
                db.execute("INSERT INTO player_tenpai_state VALUES(?,?,?)",(eid,q,int(fur)))
                for w in waits:db.execute("INSERT INTO tenpai_agari_matrix VALUES(?,?,?,?)",(eid,q,w,int(bool(legal(hh,w,q)))))
        if tag:tags[tag]=eid
    for p,h in hands.items():add("haipai",p,h=h)
    for i,(p,d,x) in enumerate(turns):
        add("draw",p,d,tag="draw"+str(i))
        add("discard",p,x,decl=mode=="declaration" and i==4,tag="discard"+str(i),winner=3 if i==len(turns)-1 else None)
    tags["final_discard"]=eid
    add("ron",tag="terminal")
    origins=[dict(draw_event_id=origin_ids[t],target=q,rank_drop=drop,start_event_order=origin_ids[t],end_event_order=eid if t=="1s" else tags["final_discard"],tile_type=t) for t,q,drop in [("1s",2,1),("5s",3,0)]]
    return db,tags,origins

def run(mode):
    db,tags,origins=make(mode);rs=RonState(db,1)
    post={}; pre={}; details={}; changes={};prev=((),(),());ever=False;decision=None
    for e in events(db,1):
        i=e["id"]
        def current(side):
            from dontsuka_v026_4b_core import active_at
            ds={(int(o["target"]),o["tile_type"]):rs.detail(int(o["target"]),o["tile_type"]) for o in origins if active_at(o,i,side)}
            return state(origins,i,{k:d["legal"] for k,d in ds.items()},side),ds
        s,ds=current("before");pre[i]=s
        if i==tags["final_discard"]:
            # Verify source hand and actual score movement from reconstructed tiles.
            h,m=rs.rp.hands[1],rs.rp.melds[1]
            if mode=="declaration":assert not m and sh(h[:-1])==0
            points=legal(rs.rp.hands[3],"5s",3);assert points
            before={1:40000,2:35000,3:15000,4:10000}
            assert ranks(before)[1]==1
            after=dict(before);after[1]-=points;after[3]+=points
            link=dict(origins[1],relation="immediate",same_target=1)
            link["relation"]="immediate" if mode=="declaration" else "subsequent"
            decision=ron_result(s,[link],3,ranks(before)[1],ranks(after)[1],"discard",mode=="declaration",bool(e["declaration"]),1 in rs.rp.reaches,False,rs.last_stable[1]==0)
        if e["type"]=="ron":
            win=db.execute("SELECT * FROM agari_event WHERE event_id=?",(i,)).fetchone()
            h,m,flags=rs.rp.winning(win["actor_player_id"],win["agari_tile"],False,win["target_player_id"])
            assert evaluate(h,m,win["agari_tile"],flags,WINDS[3],"1z",[],[])["points"]>0
        rs.step(e)
        s,ds=current("after");post[i]=s;details[i]=ds
        for o in origins:
            if o["start_event_order"]<=i<o["end_event_order"]:assert any(normal(t)==o["tile_type"] for t in rs.rp.hands[1])
        changes[i]=transition(prev,s,ever);ever|=coexists(s);prev=s
    db.close()
    return tags,post,details,changes,decision

class PhysicalReplay(unittest.TestCase):
    def test_transient_14_and_wait_change(self):
        g,s,d,c,_=run("wait")
        self.assertEqual(c[g["draw4"]],"start")
        self.assertEqual(c[g["draw5"]],"end")
        self.assertEqual(d[g["draw5"]][(2,"1s")]["effective_tiles"],14)
        self.assertEqual(d[g["discard5"]][(2,"1s")]["reason"],"no_ordinary_ron_for_type")
        self.assertFalse(coexists(s[g["discard5"]]))
    def test_collapse_and_reestablish(self):
        g,s,d,c,_=run("collapse")
        self.assertEqual(d[g["discard5"]][(2,"1s")]["reason"],"not_tenpai")
        self.assertEqual(c[g["discard9"]],"restart")
    def test_temporary_furiten_and_clear(self):
        g,s,d,c,_=run("temporary")
        self.assertEqual(c[g["draw5"]],"end")
        self.assertEqual(c[g["discard5"]],"restart")
        self.assertEqual(c[g["discard7"]],"end")
        self.assertEqual(d[g["discard7"]][(2,"1s")]["reason"],"furiten")
        self.assertEqual(c[g["discard9"]],"restart")
    def test_permanent_furiten(self):
        g,s,d,c,_=run("permanent")
        self.assertEqual(d[g["discard5"]][(2,"1s")]["reason"],"furiten")
        self.assertEqual(d[g["discard9"]][(2,"1s")]["reason"],"furiten")
    def test_damaten_tedashi_ron(self):
        g,s,d,c,r=run("damaten")
        self.assertEqual((r["tolerated"],r["sage"],r["reason"]),(1,1,"damaten_tedashi"))
    def test_closed_nontenpai_tedashi_ron(self):
        g,s,d,c,r=run("collapse")
        self.assertEqual((r["tolerated"],r["sage"],r["reason"]),(1,1,"closed_selected_tedashi"))
    def test_declaration_ron(self):
        g,s,d,c,r=run("declaration")
        self.assertEqual((r["tolerated"],r["sage"],r["reason"]),(1,1,"reach_declaration"))
if __name__=="__main__":unittest.main(verbosity=2)
