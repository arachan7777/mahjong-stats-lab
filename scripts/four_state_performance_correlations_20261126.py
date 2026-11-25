#!/usr/bin/env python3
"""四区分ドンツカ率と各選手の対局戦績の相関（固定DB・読取専用）。"""
import contextlib,io,runpy,sys,os,json,math,csv
from pathlib import Path
from collections import defaultdict
dbpath=sys.argv[1]
module="scripts/all_players_reach_closed_dama_open_tenpai_dontsuka_20261126.py"
sys.argv=[module,dbpath]
buf=io.StringIO()
with contextlib.redirect_stdout(buf):
    ns=runpy.run_path(module,run_name="__main__")
assert "VALIDATION_SUCCESS" in buf.getvalue(),buf.getvalue()[-2000:]
print("FOUR_STATE_REVALIDATED",flush=True)
c=ns['c'];rows=ns['rows'];players=ns['players'];calc_all=ns['calc_all']
scopes=dict(ns['scopes'])
m=defaultdict(lambda:{'games':0,'rank_sum':0,'top':0,'last':0,'points':0.0,'kyoku':0,
                       'agari':0,'dealin':0,'furo':0,'reach':0})
gr=list(c.execute("""SELECT p.name,g.id game_id,ls.start_year year,ss.stage stage,
gr.rank,gr.league_points FROM game_player_result gr
JOIN player p ON p.id=gr.player_id JOIN game g ON g.id=gr.game_id
JOIN season_stage ss ON ss.id=g.season_stage_id JOIN league_season ls ON ls.id=ss.league_season_id"""))
assert len(gr)==2068*4,len(gr)
for x in gr:
    d=m[('all',x['name'])]; d['games']+=1;d['rank_sum']+=x['rank'];d['top']+=x['rank']==1;d['last']+=x['rank']==4;d['points']+=x['league_points']
    a=m[('season_'+str(x['year']),x['name'])];a['games']+=1;a['rank_sum']+=x['rank'];a['top']+=x['rank']==1;a['last']+=x['rank']==4;a['points']+=x['league_points']
    b=m[('regular',x['name'])] if x['stage']=='regular' else None
    if b is not None:b['games']+=1;b['rank_sum']+=x['rank'];b['top']+=x['rank']==1;b['last']+=x['rank']==4;b['points']+=x['league_points']
stats=list(c.execute("SELECT * FROM player_season_stage_stats_base"))
assert sum(x['total_game_count'] for x in stats)==2068*4
assert sum(x['total_kyoku_count'] for x in stats)==25238*4
for x in stats:
    for group in ['all','season_'+str(x['season_start_year'])]+(['regular'] if x['stage']=='regular' else []):
        d=m[(group,x['player_name'])]
        for k,b in [('kyoku','total_kyoku_count'),('agari','agari_count'),('dealin','dealin_count'),('furo','furo_count'),('reach','reach_count')]:
            d[k]+=x[b]
def cov_metrics(scope,name):
    x=m.get((scope,name))
    if not x or not x['games'] or not x['kyoku']:return None
    d={k:x[k] for k in x}
    d.update({
      'points_per_game':x['points']/x['games'],
      'avg_rank':x['rank_sum']/x['games'],
      'top_rate':100*x['top']/x['games'],
      'last_rate':100*x['last']/x['games'],
      'agari_rate':100*x['agari']/x['kyoku'],
      'dealin_rate':100*x['dealin']/x['kyoku'],
      'furo_rate':100*x['furo']/x['kyoku'],
      'reach_rate':100*x['reach']/x['kyoku'],
    })
    return d
labels=['all','reached','closed_dama','open_tenpai','nonreach_tenpai_legacy','tenpai','not_tenpai']
def build(scope,sub):
    zz=[]
    for p in players:
        name=p['name']
        per=cov_metrics(scope,name)
        if per is None: continue
        ss=calc_all([r for r in sub if r['player']==name])
        z={'name':name,'performance':per,'categories':ss,
           'closed_minus_reached':ss['closed_dama']['rate']-ss['reached']['rate'] if ss['closed_dama']['rate'] is not None and ss['reached']['rate'] is not None else None,
           'open_minus_reached':ss['open_tenpai']['rate']-ss['reached']['rate'] if ss['open_tenpai']['rate'] is not None and ss['reached']['rate'] is not None else None,
           'closed_minus_open':ss['closed_dama']['rate']-ss['open_tenpai']['rate'] if ss['closed_dama']['rate'] is not None and ss['open_tenpai']['rate'] is not None else None,
        }
        zz.append(z)
        assert ss['all']['draws']>0
    return zz
per_scope={'all':build('all',scopes['all']),
           'regular':build('regular',[r for r in rows if r['stage']=='regular'])}
for year in range(2018,2027):
    per_scope['season_'+str(year)]=build('season_'+str(year),scopes['season_'+str(year)])
def corr(a,b):
    n=len(a)
    if n<3:return None
    mx=sum(a)/n;my=sum(b)/n
    dx=[x-mx for x in a];dy=[y-my for y in b]
    den=math.sqrt(sum(x*x for x in dx)*sum(y*y for y in dy))
    if not den:return None
    return sum(x*y for x,y in zip(dx,dy))/den
def rank(arr):
    ix=sorted(range(len(arr)),key=lambda i:arr[i]);v=[0]*len(arr);i=0
    while i<len(ix):
        j=i+1
        while j<len(ix) and arr[ix[j]]==arr[ix[i]]:j+=1
        val=(i+1+j)/2
        for k in ix[i:j]:v[k]=val
        i=j
    return v
def corrs(data,xkey,ykey,cohort):
    usable=[]
    for x in data:
        if xkey.startswith('cat:'):
            k=xkey[4:];o=x['categories'][k]
            X=o['rate'];den=o['draws']
        else:
            X=x.get(xkey);den=min(x['categories']['closed_dama']['draws'],x['categories']['open_tenpai']['draws'],x['categories']['reached']['draws'])
        if cohort=='qualified' and (x['performance']['games']<50 or den<100):continue
        if cohort=='high_sample' and (x['performance']['games']<100 or den<200):continue
        Y=x['performance'].get(ykey)
        if X is not None and Y is not None:usable.append((X,Y))
    xs=[a for a,b in usable];ys=[b for a,b in usable]
    return {'n':len(usable),
            'pearson':round(corr(xs,ys),4) if corr(xs,ys) is not None else None,
            'spearman':round(corr(rank(xs),rank(ys)),4) if len(xs)>=3 and corr(rank(xs),rank(ys)) is not None else None}
metrics=['points_per_game','avg_rank','top_rate','last_rate','agari_rate','dealin_rate']
keys=['cat:'+l for l in labels]+['closed_minus_reached','open_minus_reached','closed_minus_open']
summary={}
for scope,dat in per_scope.items():
    summary[scope]={}
    for cohort in ['all','qualified','high_sample']:
        summary[scope][cohort]={}
        for key in keys:
            summary[scope][cohort][key]={m:corrs(dat,key,m,cohort) for m in metrics}
    if scope in ('all','regular'):
        print('RESULT_CORRELATIONS',scope,json.dumps(summary[scope],ensure_ascii=False,separators=(',',':')),flush=True)
    else:
        print('RESULT_SEASON_SELECTED',scope,json.dumps({
          'open_points':summary[scope]['all']['cat:open_tenpai']['points_per_game'],
          'dama_points':summary[scope]['all']['cat:closed_dama']['points_per_game'],
          'reached_points':summary[scope]['all']['cat:reached']['points_per_game'],
          'open_dealin':summary[scope]['all']['cat:open_tenpai']['dealin_rate'],
          'dama_dealin':summary[scope]['all']['cat:closed_dama']['dealin_rate']},ensure_ascii=False,separators=(',',':')),flush=True)
overall=per_scope['all']
for name in ['松本吉弘','多井隆晴','佐々木寿人','鈴木大介','鈴木たろう','茅森早香','園田賢','小林剛','堀慎吾','白鳥翔','伊達朱里紗','瑞原明奈','中田花奈','前原雄大','藤崎智','萩原聖人','黒沢咲','醍醐大','永井孝典','勝又健志','内川幸太郎']:
    obj=next(z for z in overall if z['name']==name)
    print('RESULT_PLAYER',json.dumps(obj,ensure_ascii=False,separators=(',',':')),flush=True)
for category in ['reached','closed_dama','open_tenpai','not_tenpai']:
    p=sorted([x for x in overall if x['categories'][category]['draws']>=150 and x['performance']['games']>=50],
              key=lambda x:x['categories'][category]['rate'],reverse=True)
    print('RESULT_RANKING',category,json.dumps([{'name':x['name'],'rate':x['categories'][category]['rate'],'hits':x['categories'][category]['hits'],'draws':x['categories'][category]['draws'],'points_per_game':round(x['performance']['points_per_game'],2),'top_rate':round(x['performance']['top_rate'],2),'dealin_rate':round(x['performance']['dealin_rate'],2)} for x in p[:12]],ensure_ascii=False,separators=(',',':')),flush=True)
for metric in ['points_per_game','avg_rank','top_rate','last_rate']:
    p=sorted([x for x in overall if x['performance']['games']>=50],key=lambda x:x['performance'][metric],reverse=metric not in ('avg_rank',))
    print('RESULT_PERFORMANCE_TOP',metric,json.dumps([{'name':x['name'],'games':x['performance']['games'],'value':round(x['performance'][metric],3),'closed_dama':x['categories']['closed_dama']['rate'],'open_tenpai':x['categories']['open_tenpai']['rate'],'reached':x['categories']['reached']['rate']} for x in p[:12]],ensure_ascii=False,separators=(',',':')),flush=True)
out=Path('results');out.mkdir(exist_ok=True)
(out/'four_state_performance_correlations_20261126.json').write_text(json.dumps({'data_scope':'固定版20261120全試合全ステージ、post-season倍率なし','player_data':per_scope,'correlations':summary},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
with (out/'four_state_performance_correlations_20261126.csv').open('w',newline='',encoding='utf-8-sig') as f:
    writer=csv.writer(f)
    writer.writerow(['scope','name','games','kyoku','points','points_per_game','average_rank','top_rate','last_rate','agari_rate','dealin_rate','reach_hits','reach_draws','reach_rate','closed_hits','closed_draws','closed_rate','open_hits','open_draws','open_rate','non_tenpai_hits','non_tenpai_draws','non_tenpai_rate'])
    for scope,rr in per_scope.items():
        for x in rr:
            p=x['performance'];cat=x['categories']
            writer.writerow([scope,x['name'],p['games'],p['kyoku'],p['points'],round(p['points_per_game'],6),round(p['avg_rank'],6),round(p['top_rate'],6),round(p['last_rate'],6),round(p['agari_rate'],6),round(p['dealin_rate'],6),
               cat['reached']['hits'],cat['reached']['draws'],cat['reached']['rate'],cat['closed_dama']['hits'],cat['closed_dama']['draws'],cat['closed_dama']['rate'],cat['open_tenpai']['hits'],cat['open_tenpai']['draws'],cat['open_tenpai']['rate'],cat['not_tenpai']['hits'],cat['not_tenpai']['draws'],cat['not_tenpai']['rate']])
print('COUNTS',json.dumps({'players':len(overall),'games':len(gr),'seasons':len(per_scope)-2},ensure_ascii=False),flush=True)
print('VALIDATION_SUCCESS',flush=True)
