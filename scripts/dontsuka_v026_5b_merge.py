"""Stage 5B shard merge and independent denominator reconciliation."""
import argparse,csv,gzip,json,os,hashlib
from collections import Counter,defaultdict
from pathlib import Path
from dontsuka_v026_3b import dimension_keys,rates,write_csv
from dontsuka_v026_extract import sha256_file
from dontsuka_v026_5b import require,write_json,A_SHA
from dontsuka_v026_2b_replay import DB_SHA
def read(p):return json.loads(p.read_text(encoding="utf-8"))
def stream(p):
    with gzip.open(p,"rt",encoding="utf-8",newline="") as f:yield from csv.DictReader(f)
def main():
    p=argparse.ArgumentParser();p.add_argument("source",type=Path);p.add_argument("out",type=Path);p.add_argument("--shards",type=int,required=True);a=p.parse_args()
    a.out.mkdir(parents=True,exist_ok=True)
    manifests=sorted(a.source.glob("*/manifest.json"));require(len(manifests)==a.shards,"shard manifest count")
    counts=Counter();seen=set();kys=set();shards=set();rounds={};details=set();hit=set();stats=defaultdict(Counter);examples={};names=None;perf=[]
    def add(r,**metrics):
        for key in dimension_keys(r):stats[(int(r["player_id"]),*key)].update(metrics)
    for path in manifests:
        m=read(path);d=path.parent
        require(m["status"]=="computed" and not m["limited"] and not m["errors"] and m["shards"]==a.shards,"shard status")
        require(m["commit"]==os.getenv("GITHUB_SHA") and m["run_id"]==os.getenv("GITHUB_RUN_ID") and m["database_sha256"]==DB_SHA and m["stage5a_sha256"]==A_SHA,"shard provenance")
        require(m["shard"] not in shards and not kys.intersection(m["kyoku_ids"]),"overlap shard")
        shards.add(m["shard"]);kys.update(m["kyoku_ids"])
        for n,h in m["outputs"].items():require(sha256_file(d/n)==h,"member hash "+n)
        local=Counter();local_q=set();local_hit=set()
        for r in stream(d/"coverage.csv.gz"):
            eid=int(r["draw_event_id"]);dd=int(r["is_dontsuka"])
            require(eid not in seen and int(r["kyoku_id"]) in m["kyoku_ids"],"duplicate/outside draw")
            seen.add(eid);local.update(draws=1,basic=dd)
            add(r)
            if r["status"]=="not_applicable_actual_foul":
                require(not r["is_shoubute"],"excluded not blank");local.update(excluded=1,excluded_basic=dd)
            else:
                require(r["status"]=="evaluated","unresolved");local["evaluated"]+=1
                if r["physical_shanten"]=="1":
                    q=int(r["is_shoubute"]);local_q.add(eid)
                    local.update(isshanten=1,isshanten_dontsuka=dd,shoubute=q,shoubute_dontsuka=q*dd)
                    if q and dd:local_hit.add(eid)
                    add(r,isshanten_draws=1,isshanten_dontsuka=dd,shoubute_isshanten_draws=q,shoubute_isshanten_dontsuka=q*dd)
        actual_q=set()
        for r in stream(d/"isshanten_draws.csv.gz"):
            eid=int(r["draw_event_id"]);require(eid not in actual_q and eid in local_q,"details duplicate/foreign")
            actual_q.add(eid);details.add(eid)
            q=int(r["is_shoubute"]);w=json.loads(r["witness"])
            require(bool(w)==bool(q) and bool(int(r["qualifying_patterns"]))==bool(q),"witness consistency")
            local.update(progressions=int(r["progressions"]),patterns=int(r["patterns"]))
        require(actual_q==local_q,"all one-shanten details")
        actual_hit=set()
        for r in stream(d/"shoubute_dontsuka.csv.gz"):
            eid=int(r["draw_event_id"]);require(eid not in actual_hit and eid in local_hit,"hit detail mismatch");actual_hit.add(eid);hit.add(eid)
        require(actual_hit==local_hit,"hit coverage")
        round_ids=set()
        for r in read(d/"rounds.json"):
            k=(r["kyoku_id"],r["player_id"]);ids=json.loads(r["draw_event_ids"])
            require(k not in rounds and len(ids)==r["draw_count"] and len(set(ids))==len(ids) and not round_ids.intersection(ids),"round duplicate")
            rounds[k]=r;round_ids.update(ids)
            add(r,shoubute_isshanten_dontsuka_kyoku=1,self_wins=r["self_win"],actual_ron_kyoku=r["actual_ron"],kyoku_net_sum=r["kyoku_net"],**{"ron_category_"+r["approved_ron_classification"]:1})
        require(round_ids==local_hit,"round event coverage")
        require(local==Counter(m["counts"]),"shard count mismatch")
        counts.update(local)
        require(not read(d/"errors.json"),"shard error records")
        for k,v in read(d/"real_examples.json").items():examples.setdefault(k,v)
        nm=read(d/"names.json");require(names is None or names==nm,"player names mismatch");names=nm
        perf.append({k:m[k] for k in ("shard","elapsed_seconds","peak_rss_kib","scoring_cache","structural_cache","counts")})
    require(shards==set(range(a.shards)) and len(kys)==25238 and len(seen)==1257732 and len(names)==56,"full identity")
    require(tuple(counts[k] for k in ("draws","basic","evaluated","excluded","excluded_basic"))==(1257732,27578,1257599,133,1),"approved totals")
    require(len(details)==counts["isshanten"] and len(hit)==counts["shoubute_dontsuka"],"detail counts")
    fields=["isshanten_draws","isshanten_dontsuka","shoubute_isshanten_draws","shoubute_isshanten_dontsuka","shoubute_isshanten_dontsuka_kyoku","self_wins","actual_ron_kyoku","kyoku_net_sum","ron_category_immediate","ron_category_subsequent","ron_category_different_tile","ron_category_no_ron","ron_category_special_excluded"]
    def metrics(c):
        x={k:c[k] for k in fields}
        n=c["shoubute_isshanten_dontsuka_kyoku"]
        x.update(isshanten_dontsuka_rate=rates(c["isshanten_dontsuka"],c["isshanten_draws"]),shoubute_isshanten_dontsuka_rate=rates(c["shoubute_isshanten_dontsuka"],c["shoubute_isshanten_draws"]),fulfillment_rate=rates(c["self_wins"],n),actual_ron_kyoku_rate=rates(c["actual_ron_kyoku"],n),mean_kyoku_net="" if not n else f'{c["kyoku_net_sum"]/n:.9f}')
        return x
    totals=defaultdict(Counter);prs=[]
    for (p,*key),c in sorted(stats.items()):
        prs.append(dict(player_id=p,player_name=names[str(p)],scope=key[0],season_start_year=key[1],stage=key[2],**metrics(c)));totals[tuple(key)].update(c)
    tr=[dict(scope=k[0],season_start_year=k[1],stage=k[2],**metrics(c)) for k,c in sorted(totals.items())]
    overall=metrics(totals["all_period","",""])
    require(overall["isshanten_draws"]==counts["isshanten"] and overall["shoubute_isshanten_draws"]==counts["shoubute"] and overall["shoubute_isshanten_dontsuka"]==len(hit) and overall["shoubute_isshanten_dontsuka_kyoku"]==len(rounds),"overall")
    rr=list(rounds.values())
    write_csv(a.out/"metrics_by_player.csv",prs,list(prs[0]))
    write_csv(a.out/"metrics_all_scopes.csv",tr,list(tr[0]))
    write_csv(a.out/"shoubute_isshanten_dontsuka_kyoku.csv",rr,list(rr[0]) if rr else ["kyoku_id","player_id"])
    write_json(a.out/"real_examples.json",examples);write_json(a.out/"performance.json",perf)
    write_json(a.out/"unresolved.json",[])
    # Full details remain compressed per shard; manifest identifies every archive.
    manifest=dict(scope="5B only",status="computed_pending_independent_readback",release="20261120-2341-04338cbb",database_sha256=DB_SHA,stage5a_sha256=A_SHA,run_id=os.getenv("GITHUB_RUN_ID"),commit=os.getenv("GITHUB_SHA"),counts=dict(counts),overall=overall,shards=a.shards,errors=0,draw_identity_match=True,definitions_unchanged=True,stage6_started=False)
    report=["# ドンツカ総合研究 v0.26 第5工程B 集計報告","固定版DB：20261120-2341-04338cbb。第6工程以降は未着手。","全件ID・承認済み基本件数・133件適用外・分割重複欠落を照合。成果物の保存・再取得確認は別途。","## 集計値"]+[f"- {k}: {v}" for k,v in overall.items()]+["## 取り扱い","勝負手判定はツモ直前、全進行候補・ロン／ツモを評価。第5工程A採点を再利用。既存放銃分類は選手局単位で保持。局収支・成就率は発生選手局を重複計上しない。","第5工程Aとの重複識別フラグは保持するが、合算集計は実施しない。"]
    (a.out/"report.md").write_text("\n".join(report)+"\n",encoding="utf-8")
    manifest["outputs"]={f.name:sha256_file(f) for f in a.out.iterdir() if f.is_file() and f.name!="manifest.json"}
    write_json(a.out/"manifest.json",manifest);print(json.dumps(manifest,ensure_ascii=False))
if __name__=="__main__":main()
