"""Independent verification of saved Stage 4B artifact. No raw DB access."""
import csv, io, json, hashlib, zipfile, sys
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

p=Path(sys.argv[1]); digest=hashlib.sha256(p.read_bytes()).hexdigest()
assert digest=='5fad467465dc686c6c2e831cd9b870debe551f6de22302194b04cbdbb63a392a'
with zipfile.ZipFile(p) as z:
    assert z.testzip() is None
    m=json.loads(z.read('manifest.json'))
    assert set(m['outputs'])==set(z.namelist())-{'manifest.json'}
    assert all(hashlib.sha256(z.read(n)).hexdigest()==v for n,v in m['outputs'].items())
    def read(n):return list(csv.DictReader(io.TextIOWrapper(z.open(n),encoding='utf-8-sig')))
    t=read('coexistence_timeline.csv'); r=read('coexistence_kyoku.csv'); d=read('all_ron_decisions.csv'); u=read('unresolved.csv')
    pstats=read('metrics_by_player.csv'); totals=read('metrics_all_scopes.csv')
    assert not read('discrepancies.csv')
    key=lambda x:(x['kyoku_id'],x['player_id'])
    assert len({key(x) for x in r})==len(r)==340
    assert len({x['ron_event_id'] for x in d})==len(d)==72
    assert len({(*key(x),x['event_id']) for x in t})==len(t)==2700
    state={}; ever=set(); transitions=defaultdict(Counter)
    for x in t:
        k=key(x); before=bool(json.loads(x['previous_down']) and json.loads(x['previous_maintain'])); after=bool(json.loads(x['down_origins']) and json.loads(x['maintain_origins']))
        assert state.get(k,False)==before
        expected=('restart' if k in ever else 'start') if after and not before else 'end' if before and not after else 'change' if after and before else None
        assert x['transition']==expected
        if after:ever.add(k)
        state[k]=after; transitions[k][expected]+=1
    assert not any(state.values()) and ever=={key(x) for x in r}
    for x in r:
        c=transitions[key(x)]; assert (c['start'],c['end'],c['restart'])==tuple(int(x[f]) for f in ('starts','ends','restarts'))
    def rank(sc,p):
        sc=json.loads(sc); v=sc[p]; return 1+sum(w>v for w in sc.values())+(sum(w==v for w in sc.values())-1)/2
    byround=defaultdict(Counter)
    for x in d:
        assert rank(x['scores_before'],x['player_id'])==float(x['rank_before'])
        assert rank(x['scores_end'],x['player_id'])==float(x['rank_end'])
        active=set(map(tuple,json.loads(x['maintain_origins'])))
        matched={(int(a['draw_event_id']),int(a['target'])) for a in json.loads(x['all_approved_links']) if a['relation'] in ('immediate','subsequent') and int(a['same_target'])==1 and a['target']==x['winner']} & active
        assert matched==set(map(tuple,json.loads(x['matching_origins'])))
        co=bool(active and json.loads(x['down_origins'])); assert co==bool(int(x['coexist_before']))
        tol=co and bool(matched) and x['source_kind']=='discard' and x['rank_before']==x['rank_end']; assert tol==bool(int(x['tolerated']))
        assert not int(x['sage']) or tol
        assert not int(x['reach_tsumogiri_excluded']) or (tol and x['accepted_before']=='1' and x['tsumogiri']=='1')
        for f in ('tolerated','sage','reach_tsumogiri_excluded'):byround[key(x)][f]+=int(x[f])
    assert len({key(x) for x in d if int(x['tolerated'])})==29
    for x in r:
        for f in ('tolerated','sage','reach_tsumogiri_excluded'):assert int(x[f])==byround[key(x)][f]
    assert {(key(x),x['event_id']) for x in u}=={(key(x),x['source_event_id']) for x in d if x['reason'].startswith('unresolved')}
    assert {x['ron_event_id'] for x in read('tolerance_details.csv')}=={x['ron_event_id'] for x in d if x['tolerated']=='1'}
    assert {x['ron_event_id'] for x in read('sage_qualified_and_excluded.csv')}=={x['ron_event_id'] for x in d if x['tolerated']=='1'}
    fields={'coexist_kyoku':None,'starts':'starts','ends':'ends','restarts':'restarts','tolerated':'tolerated','sage_numerator':'sage','sage_denominator':None,'reach_tsumogiri_excluded':'reach_tsumogiri_excluded'}
    def audit_stats(rows,player):
        for x in rows:
            group=[q for q in r if (not player or q['player_id']==x['player_id']) and (not x['season_start_year'] or q['season_start_year']==x['season_start_year']) and (not x['stage'] or q['stage']==x['stage'])]
            for f,g in fields.items():assert int(x[f])==(sum(int(q[g]) for q in group) if g else len(group))
            a,b=int(x['sage_numerator']),int(x['sage_denominator'])
            if b:assert abs(Decimal(x['sage_rate'])-Decimal(100*a)/Decimal(b))<Decimal('0.000000001')
            else:assert x['sage_rate']==''
    audit_stats(pstats,True);audit_stats(totals,False)
    result={'status':'readback_verified_not_definition_approved','zip_sha256':digest,'manifest_files':len(m['outputs']),'timeline_rows':len(t),'coexistence_player_rounds':len(r),'ron_decisions':len(d),'tolerated':sum(int(x['tolerated']) for x in d),'sage':sum(int(x['sage']) for x in d),'reach_tsumogiri_excluded':sum(int(x['reach_tsumogiri_excluded']) for x in d),'unresolved':len(u),'unresolved_shanten_tsumogiri':{str(k):v for k,v in Counter((json.loads(x['evidence'])['stable_shanten_before_draw'],json.loads(x['evidence'])['tsumogiri']) for x in u).items()},'player_scope_rows':len(pstats),'combined_scope_rows':len(totals),'zero_denominator_player_rows':sum(x['sage_denominator']=='0' for x in pstats),'end_by_event':dict(Counter(x['event_type'] for x in t if x['transition']=='end')),'restart_by_event':dict(Counter(x['event_type'] for x in t if x['transition']=='restart')),'end_only_non_13_waiting_state':sum(x['transition']=='end' and {v['reason'] for _,v in json.loads(x['evidence']) if not v['legal']}=={'not_13_tile_waiting_state'} for x in t),'limits':'No raw DB recomputation or new artificial replay; no final approval.'}
    print(json.dumps(result,ensure_ascii=False,indent=2))
