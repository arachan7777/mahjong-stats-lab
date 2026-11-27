"""Stage 2A: independent actual-win audit. Run on the pinned DB only."""
import argparse, csv, hashlib, json, os, sqlite3, traceback
from collections import Counter, defaultdict
from pathlib import Path
from importlib.metadata import version
from mahjong.hand_calculating.hand import HandCalculator
from mahjong.hand_calculating.fu import FuCalculator
from mahjong.hand_calculating.hand_config import HandConfig, OptionalRules
from mahjong.meld import Meld
from mahjong.utils import plus_dora
from dontsuka_v026_extract import connect_readonly, verify_database, sha256_file
from dontsuka_v026_2a_replay import Replay, normal, tile, TYPES

NAMES = dict(tsumo="門前清自摸和", riichi="立直", ippatsu="一発", chankan="搶槓",
 rinshan="嶺上開花", haitei="海底摸月", houtei="河底撈魚", daburu_riichi="ダブル立直",
 pinfu="平和", tanyao="断么九", iipeiko="一盃口", haku="白", hatsu="發", chun="中",
 yakuhai_place="自風", yakuhai_round="場風", sanshoku="三色同順", ittsu="一気通貫",
 chantai="混全帯么九", honroto="混老頭", toitoi="対々和", sanankou="三暗刻",
 sankantsu="三槓子", sanshoku_douko="三色同刻", chiitoitsu="七対子", shosangen="小三元",
 honitsu="混一色", junchan="純全帯么九", ryanpeiko="二盃口", chinitsu="清一色",
 kokushi="国士無双", daburu_kokushi="国士無双", chuuren_poutou="九蓮宝燈",
 daburu_chuuren_poutou="九蓮宝燈", suuankou="四暗刻", suuankou_tanki="四暗刻",
 daisangen="大三元", shosuushi="小四喜", daisuushi="大四喜", ryuisou="緑一色",
 suukantsu="四槓子", tsuisou="字一色", chinroto="清老頭", tenhou="天和", chiihou="地和",
 aka_dora="赤ドラ", dora="ドラ")

# M.League official rule chapter 6: double-wind pair is 2 fu, not 4.
# https://m-league.jp/about/ ; deduplicate only the fu input, not wind-yaku evaluation.
_original_fu = FuCalculator.calculate_fu
def mleague_fu(self,hand,win_tile,win_group,config,valued_tiles=None,melds=None):
    return _original_fu(self,hand,win_tile,win_group,config,
                        list(dict.fromkeys(valued_tiles or [])),melds)
FuCalculator.calculate_fu = mleague_fu

def index(t):
    t=normal(tile(t))
    return "mpsz".index(t[1])*9+int(t[0])-1

def physical(h,m,win):
    used=set()
    def alloc(t):
        i=index(t)*4
        ids=[i] if t[0]=="0" else list(range(i,i+4))
        if t[0]!="0" and index(t) in (4,13,22): ids=ids[1:]
        for n in ids:
            if n not in used:
                used.add(n); return n
        raise ValueError("physical allocation failed: "+t)
    concealed=[alloc(t) for t in h]
    w=concealed[len(h)-1-h[::-1].index(win)]
    melds=[]
    for k,b in m:
        melds.append(Meld(meld_type=Meld.CHI if k=="chi" else Meld.PON if k=="pon" else Meld.KAN,
                          tiles=[alloc(t) for t in b], opened=k!="ankan"))
    return concealed+[n for m in melds for n in m.tiles],w,melds

def evaluate(h,m,win,flags,player_wind,round_wind,omote,ura):
    tiles,w,melds=physical(h,m,win)
    f=dict(flags)
    first=f.pop("first_uninterrupted")
    f["is_tenhou"]=first and player_wind=="1z"
    f["is_chiihou"]=first and player_wind!="1z"
    config=HandConfig(**f,player_wind=index(player_wind),round_wind=index(round_wind),
       options=OptionalRules(has_open_tanyao=True,has_aka_dora=True,has_double_yakuman=False,
         kazoe_limit=HandConfig.KAZOE_SANBAIMAN,kiriage=True))
    om=[index(x)*4 for x in omote]
    ur=[index(x)*4 for x in ura] if f["is_riichi"] else []
    result=HandCalculator().estimate_hand_value(tiles,w,melds=melds,dora_indicators=om+ur,config=config)
    if result.error: raise ValueError("hand calculator: "+result.error)
    mapping={type(getattr(config.yaku,key)):val for key,val in NAMES.items()}
    yaku=Counter()
    opened=any(k!="ankan" for k,b in m)
    for y in result.yaku:
        name=mapping[type(y)]
        han=y.han_open if opened and y.han_open else y.han_closed
        if name=="ドラ":
            a=sum(plus_dora(n,om) for n in tiles)
            b=sum(plus_dora(n,ur) for n in tiles)
            if a+b!=han: raise ValueError("dora decomposition differs")
            if a: yaku["ドラ"]=a
            if b: yaku["裏ドラ"]=b
        else: yaku[name]+=han
    return dict(yaku=dict(yaku),fu=result.fu,han=result.han,yakuman=any(y.is_yakuman for y in result.yaku),
      points=result.cost["main"]+2*result.cost["additional"],fu_details=result.fu_details)

def score(han,fu,tsumo,dealer,yakuman_count=0):
    if yakuman_count: base=8000*yakuman_count
    elif han>=11: base=6000
    elif han>=8: base=4000
    elif han>=6: base=3000
    elif han>=5 or (han,fu) in ((4,30),(3,60)): base=2000
    elif han>0 and fu>0: base=min(2000,fu*2**(han+2))
    else: raise ValueError("nonpositive han/fu")
    def ceil(x):return (x+99)//100*100
    return (3*ceil(base*2) if dealer else ceil(base*2)+2*ceil(base)) if tsumo else ceil(base*(6 if dealer else 4))

def events(c,kyoku):
    # Explicit source table fields; no use of the recorded winning hand.
    rows=c.execute("SELECT id,type,event_order FROM event WHERE kyoku_id=? ORDER BY event_order,id",(kyoku,))
    for row in rows:
        e=dict(row); k=e["type"]
        if k in ("ron","tsumo","ryukyoku"):
            yield e;continue
        if k not in ("haipai","draw","discard","reach","dora_indicator",*TYPES):
            raise ValueError("unexpected event type "+k)
        d=dict(c.execute(f"SELECT * FROM {k}_event WHERE event_id=?",(e["id"],)).fetchone())
        e.update(actor=d.get("actor_player_id"),target=d.get("target_player_id"),tile=d.get("tile"),
          hand=d.get("hand"),block=d.get("block"),accepted=d.get("is_accepted"),
          declaration=d.get("is_reach_declaration"),rinshan=d.get("is_rinshan"),
          wall=d.get("wall_remaining_count"),dora_type=d.get("dora_type"))
        if k=="dora_indicator":e["tile"]=d["dora_indicator_tile"]
        yield e

def write_csv(path,rows,fields):
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(rows)

def js(x):return json.dumps(x,ensure_ascii=False,sort_keys=True)
def main():
    p=argparse.ArgumentParser();p.add_argument("db",type=Path);p.add_argument("out",type=Path);args=p.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    c=connect_readonly(args.db); manifest=verify_database(c,"20261120-2341-04338cbb")
    manifest.update(database_sha256=sha256_file(args.db),library_version=version("mahjong"),commit=os.getenv("GITHUB_SHA"),run_id=os.getenv("GITHUB_RUN_ID"),scope="2A only",status="in_progress")
    wins=[dict(x) for x in c.execute("""SELECT a.*,e.type,e.kyoku_id,e.event_order,k.game_id,k.round,k.honba_count,
      k.kyotaku_count,k.oya_player_id,g.date,r.player_wind
      FROM agari_event a JOIN event e ON e.id=a.event_id JOIN kyoku k ON k.id=e.kyoku_id
      JOIN game g ON g.id=k.game_id JOIN kyoku_player_result r ON r.kyoku_id=k.id AND r.player_id=a.actor_player_id
      ORDER BY e.kyoku_id,e.event_order,e.id""")]
    if len(wins)!=20173 or len({a["event_id"] for a in wins})!=20173:raise ValueError("win count/identity mismatch")
    recorded=defaultdict(dict)
    for r in c.execute("SELECT y.agari_event_id,n.name,y.han FROM agari_yaku y JOIN yaku_name n ON n.id=y.yaku_name_id"):
        recorded[r[0]][r[1]]=r[2]
    grouped=defaultdict(list)
    for w in wins:grouped[w["kyoku_id"]].append(w)
    rows=[];special=[]
    for ky,group in grouped.items():
        replay=Replay(); error=None
        try:
            ev=list(events(c,ky))
        except Exception as ex:
            ev=[];error=repr(ex)
        for w in group:
            eid=w["event_id"]; y=recorded[eid]; tsumo=w["type"]=="tsumo";dealer=w["actor_player_id"]==w["oya_player_id"]
            r={k:w[k] for k in ("event_id","kyoku_id","game_id","date","round","type","actor_player_id","target_player_id","agari_tile","is_menzen","is_yakuman","honba_count","description")}
            r.update(db_yaku=js(y),db_fu=w["fu"],db_han=w["han"],db_points=w["agari_points"],
              db_honba=w["honba_points"],db_kyotaku=w["kyotaku_points"],
              calc_honba=w["honba_count"]*300, db_anomaly_tsumo_houtei=bool(tsumo and "河底撈魚" in y))
            differences=[]
            try:
                # Secondary arithmetic check only; it is explicitly NOT independent yaku reproduction.
                yakuman_count=len(y) if w["is_yakuman"] else 0
                r["points_from_db_han_fu"]=score(w["han"],w["fu"],tsumo,dealer,yakuman_count)
                if r["points_from_db_han_fu"]!=r["db_points"]:differences.append("db_han_fu_arithmetic")
                if r["calc_honba"]!=r["db_honba"]:differences.append("honba")
                if r["db_anomaly_tsumo_houtei"]:differences.append("tsumo_houtei_record")
                if error:raise ValueError(error)
                for e in ev:
                    if e["id"]==eid:break
                    if e["type"] in ("ron","tsumo"):continue
                    if not replay.trace or (e["event_order"],e["id"])>(replay.trace[-1]["event_order"],replay.trace[-1]["id"]):
                        replay.step(e)
                else:raise ValueError("win event not found")
                h,m,flags=replay.winning(w["actor_player_id"],w["agari_tile"],tsumo,w["target_player_id"])
                r.update(concealed=js(h),melds=js(m),flags=js(flags),omote=js(replay.omote),ura=js(replay.ura),
                    calc_kyotaku=1000*(w["kyotaku_count"]+len(replay.reaches)))
                if r["calc_kyotaku"]!=r["db_kyotaku"]:differences.append("kyotaku")
                v=evaluate(h,m,tile(w["agari_tile"]),flags,w["player_wind"],w["round"][:2],replay.omote,replay.ura)
                r.update(calc_yaku=js(v["yaku"]),calc_fu=v["fu"],calc_han=v["han"],calc_points=v["points"],
                         calc_yakuman=v["yakuman"],fu_details=js(v["fu_details"]))
                for field in ("yaku","fu","han","points","yakuman"):
                    if r["calc_"+field]!=(r["db_"+field] if field!="yakuman" else bool(w["is_yakuman"])): differences.append(field)
                if bool(w["is_menzen"])!=all(k=="ankan" for k,b in m):differences.append("menzen")
            except Exception as ex:
                r["error"]=repr(ex);differences.append("evaluation_error")
            r["differences"]=";".join(differences)
            # Never classify a difference as a DB error solely on a library mismatch.
            r["cause_status"]="unresolved" if differences else "matched"
            rows.append(r)
            if eid==2530825 or r["db_anomaly_tsumo_houtei"] or differences:
                special.append(dict(event_id=eid,differences=differences,error=r.get("error"),events=ev))
    fields=list(dict.fromkeys(k for r in rows for k in r))
    write_csv(args.out/"actual_wins_all.csv",rows,fields)
    bad=[r for r in rows if r["differences"]]
    write_csv(args.out/"actual_wins_differences.csv",bad,fields)
    (args.out/"difference_event_traces.json").write_text(js(special),encoding="utf-8")
    counts=Counter(d for r in bad for d in r["differences"].split(";"))
    manifest.update(wins=len(rows),ron=sum(r["type"]=="ron" for r in rows),tsumo=sum(r["type"]=="tsumo" for r in rows),
      evaluated=sum("calc_points" in r for r in rows),difference_rows=len(bad),difference_types=dict(counts),
      previous_42_ids_available=False,previous_42_comparison="aggregate only; previous IDs not preserved",
      status="requires_individual_review" if bad else "all_matched")
    manifest["outputs"]={p.name:sha256_file(p) for p in args.out.iterdir() if p.is_file() and p.name!="manifest.json"}
    (args.out/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(manifest,ensure_ascii=False,indent=2))
    c.close()
if __name__=="__main__":main()
