#!/usr/bin/env python3
"""Read-only audit of win turns from frozen 2026-11-20 M-League SQLite release."""
import sqlite3, sys, json, csv
from collections import defaultdict
from pathlib import Path

con=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True)
con.row_factory=sqlite3.Row
con.execute('PRAGMA query_only=ON')
con.execute('PRAGMA temp_store=MEMORY')

def sql(q,args=()):
    return [dict(z) for z in con.execute(q,args)]

meta=sql('SELECT COUNT(*) AS games, MAX(date) AS last_game, MIN(date) AS first_game FROM game')[0]
meta['kyoku']=con.execute('SELECT COUNT(*) FROM kyoku').fetchone()[0]
assert (meta['games'],meta['kyoku'],meta['last_game'])==(2068,25238,'2026-11-20'),meta
assert con.execute('PRAGMA quick_check').fetchone()[0]=='ok'

players={z['id']:z['name'] for z in sql('SELECT id,name FROM player')}
pid={v:k for k,v in players.items()}
assert '多井隆晴' in pid
kyoku={z['id']:(z['year'],z['stage']) for z in sql('''
 SELECT k.id, ls.start_year year,ss.stage FROM kyoku k
 JOIN game g ON g.id=k.game_id
 JOIN season_stage ss ON ss.id=g.season_stage_id
 JOIN league_season ls ON ls.id=ss.league_season_id
''')}
base=sql('SELECT * FROM player_season_stage_stats_base')
assert sum(r['total_kyoku_count'] for r in base)==4*meta['kyoku']
assert sum(r['total_game_count'] for r in base)==4*meta['games']
base_player=defaultdict(lambda:{'games':0,'kyoku':0,'agari':0})
for z in base:
    bp=base_player[z['player_name']]
    bp['games']+=z['total_game_count']
    bp['kyoku']+=z['total_kyoku_count']
    bp['agari']+=z['agari_count']

# Replay chronological actor discards for each kyoku.
# Ron = winner's prior discard count; Tsumo = winner's prior discard count + 1.
q='''
 SELECT e.kyoku_id, e.event_order, e.type,
   d.actor_player_id AS discard_player_id,
   a.actor_player_id AS win_player_id,a.is_menzen,a.is_called
 FROM event e
 LEFT JOIN discard_event d ON d.event_id=e.id
 LEFT JOIN agari_event a ON a.event_id=e.id
 WHERE e.type IN ('discard','ron','tsumo')
 ORDER BY e.kyoku_id,e.event_order
'''
now_kyoku=None
by_player=defaultdict(int)
wins=[]
discard_total=0
for r in con.execute(q):
    k,ord,typ,discard_pid,win_pid,menzen,called=r
    if k!=now_kyoku:
        by_player.clear()
        now_kyoku=k
    if typ=='discard':
        assert discard_pid is not None
        by_player[discard_pid]+=1
        discard_total+=1
    else:
        assert typ in ('ron','tsumo') and win_pid is not None
        year,stage=kyoku[k]
        n=by_player[win_pid]+(typ=='tsumo')
        assert 0<=n<=25,(k,ord,typ,players[win_pid],n)
        wins.append({'player_id':win_pid,'name':players[win_pid],'year':year,'stage':stage,
                     'kyoku_id':k,'type':typ,'turn':n,'is_menzen':int(menzen),
                     'is_called':int(called)})
assert discard_total>=100000
assert len(wins)==sum(x['agari_count'] for x in base),(len(wins),sum(x['agari_count'] for x in base))
for n,d in base_player.items():
    assert d['agari']==sum(z['name']==n for z in wins),(n,d)

def stats(rows):
    n=len(rows);t=sum(z['turn'] for z in rows)
    return {'wins':n,'turn_total':t,'avg_turn':round(t/n,4) if n else None,
            'ron':sum(z['type']=='ron' for z in rows),
            'tsumo':sum(z['type']=='tsumo' for z in rows),
            'early_le6':sum(z['turn']<=6 for z in rows),
            'middle_7_12':sum(7<=z['turn']<=12 for z in rows),
            'late_ge13':sum(z['turn']>=13 for z in rows),
            'min_turn':min((z['turn'] for z in rows),default=None),
            'max_turn':max((z['turn'] for z in rows),default=None)}

def rank(rows):
    bags=defaultdict(list)
    for r in rows:bags[r['name']].append(r)
    out=[]
    for name,rs in bags.items():
        a=stats(rs);a.update({'name':name,**base_player[name]})
        a['early_per_kyoku_pct']=round(100*a['early_le6']/a['kyoku'],4) if a['kyoku'] else None
        out.append(a)
    out.sort(key=lambda z:(z['turn_total']/z['wins'],-z['wins'],z['name']))
    for i,r in enumerate(out):r['rank']=i+1
    return out

def pack(rs):
    ranking=rank(rs)
    target=next((x for x in ranking if x['name']=='多井隆晴'),None)
    return {'league':stats(rs),'players_with_wins':len(ranking),'takai':target}

annual={str(y):pack([w for w in wins if w['year']==y]) for y in sorted({x['year'] for x in wins})}
stages={st:pack([w for w in wins if w['stage']==st]) for st in sorted({x['stage'] for x in wins})}
takai=[w for w in wins if w['name']=='多井隆晴']
season_stages=[]
for yr in sorted({w['year'] for w in takai}):
    for stage in sorted({w['stage'] for w in takai if w['year']==yr}):
        subset=[w for w in wins if w['year']==yr and w['stage']==stage]
        data=pack(subset)
        season_stages.append({'year':yr,'stage':stage,'league':data['league'],
                              'takai':data['takai'],'players_with_wins':data['players_with_wins']})
categories={}
for kind in ('ron','tsumo','menzen','furo'):
    cond=lambda w:(w['type']==kind) if kind in ('ron','tsumo') else ((w['is_menzen']==1) if kind=='menzen' else (w['is_menzen']==0))
    categories[kind]={'takai':stats([w for w in takai if cond(w)]),'league':stats([w for w in wins if cond(w)])}
all_players=rank(wins)
eligible=[x for x in all_players if x['games']>=50]
for i,x in enumerate(eligible):x['rank_50games']=i+1
res={'source':'konoui/m-league-game-db release 20261120-2341-04338cbb',
     'audit':'Read-only event replay; 1 discard counts as 1 turn for actor; Ron=#prior actor discards, Tsumo=#prior actor discards+1',
     'meta':meta,'discard_events':discard_total,'win_events':len(wins),
     'all':pack(wins),'takai_50games_rank':next((x['rank_50games'] for x in eligible if x['name']=='多井隆晴'),None),
     'eligible_count':len(eligible),'annual':annual,'stages':stages,
     'season_stages':season_stages,'categories':categories,'all_players':all_players}
assert res['all']['takai']['wins']==res['all']['takai']['agari']
assert sum(v['league']['wins'] for v in annual.values())==len(wins)
assert sum(v['league']['wins'] for v in stages.values())==len(wins)
out=Path('results');out.mkdir(exist_ok=True)
(out/'takai_win_turns_20261120.json').write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
with (out/'all_players_win_turn_ranking.csv').open('w',newline='',encoding='utf-8-sig') as fh:
    writer=csv.DictWriter(fh,fieldnames=list(all_players[0]));writer.writeheader();writer.writerows(all_players)
with (out/'takai_wins_detail.csv').open('w',newline='',encoding='utf-8-sig') as fh:
    writer=csv.DictWriter(fh,fieldnames=list(takai[0]));writer.writeheader();writer.writerows(takai)
print('VERIFIED',json.dumps({'meta':meta,'win_events':len(wins),'league':res['all']['league'],
       'takai':res['all']['takai'],'rank_50games':res['takai_50games_rank'],
       'annual':{k:v['takai'] for k,v in annual.items()},'categories':categories},ensure_ascii=False),flush=True)
