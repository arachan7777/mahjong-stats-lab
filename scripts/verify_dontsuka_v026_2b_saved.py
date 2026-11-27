import csv,gzip,hashlib,io,json,sys,zipfile,collections
from pathlib import Path
p=Path(sys.argv[1]); prior=Path(sys.argv[2])
with zipfile.ZipFile(prior) as za:
    with io.TextIOWrapper(za.open('actual_wins_all.csv'),encoding='utf-8-sig') as f:
        wins={int(r['event_id']):r for r in csv.DictReader(f)}
with zipfile.ZipFile(p) as z:
    assert z.testzip() is None
    m=json.loads(z.read('manifest.json')); hash_checks={}
    for n,h in m['outputs'].items():
        with z.open(n) as f: hash_checks[n]=hashlib.file_digest(f,'sha256').hexdigest()==h
    assert all(hash_checks.values())
    def rows(n):
        return csv.DictReader(io.TextIOWrapper(z.open(n),encoding='utf-8-sig'))
    krows=list(rows('kyoku_comparison.csv')); grows=list(rows('game_comparison.csv'))
    movements=collections.defaultdict(list); win_matches=0; win_diff=[]
    for r in rows('point_movements.csv'):
        movements[int(r['kyoku_id'])].append(r)
        if r['type'] in ('ron','tsumo'):
            w=wins.get(int(r['event_id']))
            fields={'db_points':'recorded_base','db_honba':'recorded_honba','db_kyotaku':'recorded_kyotaku','actor_player_id':'actor','target_player_id':'target','type':'type','kyoku_id':'kyoku_id','game_id':'game_id'}
            if w and all(w[k]==r[v] for k,v in fields.items()): win_matches+=1
            else:win_diff.append(r['event_id'])
    ky={int(r['kyoku_id']):r for r in krows};counts=collections.Counter();seen=set();positions=collections.defaultdict(int);score_cache={};bad=[]
    def rank(s):
        groups=collections.defaultdict(list)
        for q,v in s.items():groups[v].append(q)
        result={};pos=1
        for v,ps in sorted(groups.items(),reverse=True):
            for q in ps:result[q]=sum(range(pos,pos+len(ps)))/len(ps)
            pos+=len(ps)
        return result
    with gzip.GzipFile(fileobj=z.open('draw_snapshots.csv.gz')) as gz,io.TextIOWrapper(gz,encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            eid=int(r['event_id']);kid=int(r['kyoku_id']);order=int(r['event_order']);stick=int(r['kyotaku_sticks']);counts['snapshots']+=1
            if eid in seen:counts['duplicate_ids']+=1
            seen.add(eid)
            s={r[f'player_id_{i}']:int(r[f'score_{i}']) for i in range(1,5)}
            ranks={r[f'player_id_{i}']:float(r[f'average_rank_{i}']) for i in range(1,5)}
            ok=(len(s)==4 and rank(s)==ranks and sum(ranks.values())==10 and sum(s.values())+stick*1000==100000)
            counts['rank_and_conservation_match']+=ok
            if kid not in score_cache:score_cache[kid]=(json.loads(ky[kid]['start_scores']),int(ky[kid]['start_sticks']))
            ms=movements[kid];idx=positions[kid]
            while idx<len(ms) and int(ms[idx]['event_order'])<order:
                mr=ms[idx];score_cache[kid]=(json.loads(mr['after_scores']),int(mr['after_sticks']));idx+=1
            positions[kid]=idx
            ok=score_cache[kid]==(s,stick) and int(ky[kid]['honba'])==int(r['honba']) and r['draw_actor_player_id'] in s
            counts['movement_snapshot_match']+=ok
            if not ok and len(bad)<10:bad.append(eid)
    report={'zip_sha256':hashlib.file_digest(p.open('rb'),'sha256').hexdigest(),'zip_bytes':p.stat().st_size,'internal_hash_checks':hash_checks,'manifest_status':m.get('status'),'snapshot_checks':dict(counts),'unique_draw_ids':len(seen),'snapshot_bad_examples':bad,'kyoku_rows':len(krows),'kyoku_matches':sum(r['match']=='1' for r in krows),'game_rows':len(grows),'game_matches':sum(r['match']=='1' for r in grows),'A_win_records':len(wins),'A_win_matches':win_matches,'A_win_differences':win_diff[:20]}
    print(json.dumps(report,ensure_ascii=False,indent=2))
