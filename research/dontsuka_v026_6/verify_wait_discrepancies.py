"""Stage 6 targeted audit of the 55 recorded wait-type discrepancies only.
The original stage 6 output is read-only; this script does not rerun the full set.
"""
import csv,gzip,io,json,zipfile,hashlib,sys
from collections import Counter,defaultdict
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"scripts"))
from dontsuka_v026_6_core import Inventory,state,compare,remaining,counts,require
from dontsuka_v026_2a_audit import events
from dontsuka_v026_extract import connect_readonly,sha256_file
from dontsuka_v026_2b_replay import DB_SHA
from dontsuka_v026_6 import rows,js,jsonout

def main():
    db,zpath,out=map(Path,sys.argv[1:]);out.mkdir(parents=True,exist_ok=True)
    require(sha256_file(db)==DB_SHA,"fixed DB digest")
    require(sha256_file(zpath)=="baf795d5eb101a868113745030ea2c857f37da58e225bbc1b2fd555b58cc90a2","stage 6 artifact digest")
    c=connect_readonly(db);z=zipfile.ZipFile(zpath)
    require(z.testzip() is None,"ZIP CRC")
    for n,h in json.loads(z.read("package_sha256.json")).items():require(hashlib.sha256(z.read(n)).hexdigest()==h,"member "+n)
    differences=list(rows(z,"final/wait_discrepancies.csv.gz"))
    require(len(differences)==55,"expected difference count")
    look=defaultdict(dict)
    for r in differences:
        k,eid,p=map(int,(r["kyoku_id"],r["draw_event_id"],r["player_id"]))
        require(p not in look[k].get(eid,{}),"duplicate")
        look[k].setdefault(eid,{})[p]=r
    require(len(look)==7,"expected rounds")
    affected=defaultdict(list)
    for r in rows(z,"final/all_comparison_details.csv.gz"):
        k,eid,p,t=map(int,(r["kyoku_id"],r["draw_event_id"],r["player_id"],r["target_id"]))
        selected=look.get(k,{}).get(eid,{})
        if p in selected or t in selected:affected[eid].append(r)
    require(sum(map(len,affected.values()))==23 and sum(int(r["is_dontsuka"]) for rs in affected.values() for r in rs)==2,"affected pairs")
    proof=[];pairproof=[];seen=set()
    for ky,ids in sorted(look.items()):
        rp=Inventory();last=None
        for e in events(c,ky):
            eid=e["id"]
            if e["type"]=="draw" and eid in ids:
                public,private,known=rp.snapshot();states={p:state(rp,p) for p in rp.hands};alt={}
                for p,r in ids[eid].items():
                    require((eid,p) not in seen,"duplicate diagnostic");seen.add((eid,p))
                    require(last==int(r["snapshot_event_id"]),"snapshot time")
                    old=set(json.loads(r["recorded_waits"]));new=set(json.loads(r["reconstructed_waits"]))
                    actual=set(states[p][1]);own=counts(rp.hands[p]+[t for _,b in rp.melds[p] for t in b])
                    require(actual==new and new<old,"expected strict wait subset")
                    missing=old-new
                    require(all(own[t]==4 and known[t]==4 and (public+private[p])[t]==4 for t in missing),"not own four copies")
                    oldvis=remaining(old,public+private[p]);newvis=remaining(new,public+private[p]);oldwall=remaining(old,known);newwall=remaining(new,known)
                    require(oldvis==newvis==int(r["reconstructed_visible"]) and oldwall==newwall==int(r["recorded_wall"])==int(r["reconstructed_wall"]),"wait count change")
                    alt[p]=old
                    proof.append(dict(r,concealed_before=rp.hands[p],melds=rp.melds[p],extra_recorded_types=sorted(missing),own_counts={t:own[t] for t in sorted(missing)},visible_count_with_recorded=oldvis,visible_count_with_reconstructed=newvis,wall_count_with_recorded=oldwall,wall_count_with_reconstructed=newwall,cause="recorded_theoretical_completion_requiring_fifth_own_copy",impact="zero"))
                for r in affected[eid]:
                    p,t=int(r["player_id"]),int(r["target_id"])
                    require(r["applicable"]=="1","unexpected unavailable affected pair")
                    sw,tw=states[p][1],states[t][1]
                    orig=compare(p,t,public,private,known,sw,tw)
                    other=compare(p,t,public,private,known,alt.get(p,sw),alt.get(t,tw))
                    require(orig==other and all(str(v)==r[k] for k,v in orig.items()),"classification change")
                    pairproof.append(dict(draw_event_id=eid,kyoku_id=ky,player_id=p,target_id=t,is_dontsuka=int(r["is_dontsuka"]),classification=r["combined"],identical=True,old=other,new=orig))
            if e["type"] not in ("ron","tsumo","ryukyoku"):rp.step(e)
            last=eid
    require(len(proof)==55 and len(pairproof)==23,"diagnostic coverage")
    cols=[r[1] for r in c.execute("PRAGMA table_info(player_tenpai_state)")]
    jsonout(out/"discrepancy_evidence.json",proof);jsonout(out/"affected_pair_evidence.json",pairproof)
    jsonout(out/"summary.json",dict(status="resolved",rounds=sorted(look),differences=len(proof),affected_pairs=len(pairproof),affected_dontsuka=sum(x["is_dontsuka"] for x in pairproof),changed_counts=0,changed_classifications=0,cause="DB records theoretical fifth-copy completion types; approved 5A excludes physically impossible own fifth copy",database_sha256=DB_SHA,source_artifact_sha256=sha256_file(zpath),tenpai_state_columns=cols))
    print(js(json.loads((out/"summary.json").read_text())),flush=True)
if __name__=="__main__":main()
