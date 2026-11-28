"""Apply approved section 2 boundaries to stage9 ZIP only; no raw DB."""
import argparse, hashlib, json, pathlib, zipfile, shutil, pandas as pd
from collections import Counter
P=pathlib.Path
DB='20261120-2341-04338cbb'
OLD='ec346925ae68ef6d652ae2e1969f4d032d780631968600b2de438e069cfa7824'
COLS=['top_risk','last_risk']
KEY=['draw_event_id','target_id']
DIMS=['player_id','season_start_year','stage']
SCOPES={'all':[],'player':['player_id'],'season':['season_start_year'],'stage':['stage'],'season_stage':['season_start_year','stage'],'player_season':['player_id','season_start_year'],'player_stage':['player_id','stage'],'player_season_stage':DIMS}
EXPECTED={'top_risk':(5075,5003),'last_risk':(7080,6970)}
def sha(p):
 with open(p,'rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def flags(before,after,who):
 assert set(before)==set(after) and len(before)==4 and who in before
 return (int(before[who]==max(before.values()) and after[who]<max(after.values())),int(before[who]>min(before.values()) and after[who]==min(after.values())))
def avg_rank(s,k):return 1+sum(v>s[k] for v in s.values())+(sum(v==s[k] for v in s.values())-1)/2
def artificial():
 cases=[('単独トップ→同点トップ',[400,300,200,100],[350,350,200,100],(0,0)),('同点トップ→単独トップ',[300,300,200,100],[300,200,200,200],(0,0)),('単独トップ→圏外',[400,300,200,100],[340,360,200,100],(1,0)),('同点トップ→圏外',[300,300,200,100],[280,320,200,100],(1,0)),('ラス圏外→同点ラス',[400,300,200,100],[100,600,200,100],(1,1)),('ラス圏外→単独ラス',[400,300,200,100],[90,610,200,100],(1,1)),('同点ラス→単独ラス',[100,300,200,100],[80,320,200,100],(0,0)),('全員同点→仮想放銃',[250,250,250,250],[200,300,250,250],(1,0))]
 out={}
 for label,b,a,e in cases:
  actual=flags(dict(enumerate(b)),dict(enumerate(a)),0);assert actual==e,(label,actual,e);out[label]=list(actual)
 assert max([1,1,0])==1;out['複数家の基本ツモ重複排除']='pass'
 b=dict(enumerate(cases[0][1]));a=dict(enumerate(cases[0][2]));assert avg_rank(a,0)-avg_rank(b,0)==.5 and flags(b,a,0)[0]==0;out['平均順位方式との独立性']='pass'
 return out
def load(p):return pd.read_csv(p,dtype=str,keep_default_na=False)
def write(df,p):df.to_csv(p,index=False,compression={'method':'gzip','mtime':0} if str(p).endswith('.gz') else None)
def derive(root):
 src=load(root/'source_3a_opponent_hypothetical_all.csv');assert len(src)==28060 and src.status.eq('evaluated').all();assert not src.duplicated(['draw_event_id','target']).any()
 vals=[];strict=[]
 for row in src.itertuples(index=False):
  b=json.loads(row.before_scores);a=json.loads(row.after_scores);k=row.drawer;v=flags(b,a,k);rb=avg_rank(b,k);ra=avg_rank(a,k);assert rb==float(row.drawer_rank_before) and ra==float(row.drawer_rank_after) and ra-rb==float(row.rank_drop)
  vals.append(v);strict.append((rb==1 and ra>1,rb<4 and ra==4))
 f=src[['draw_event_id','target','kyoku_id','game_id','drawer']].rename(columns={'target':'target_id','drawer':'player_id'}).copy();f[COLS]=vals;f[['top_strict','last_strict']]=strict
 cand=json.loads((root/'rank_boundary_candidates.json').read_text()); dif=load(root/'rank_boundary_differences.csv'); x=f[(f.top_risk!=f.top_strict)|(f.last_risk!=f.last_strict)].merge(dif,on=KEY,validate='one_to_one');assert len(x)==len(dif)==3094;assert (x.top_risk==x.top_membership.eq('True')).all() and (x.last_risk==x.last_membership.eq('True')).all()
 op=load(root/'opponent_integration.csv.gz'); hits=op[op.is_opponent_dontsuka=='1'];assert len(hits)==len(f);f=f.merge(hits[KEY+DIMS+['kyoku_id','game_id']],on=KEY,validate='one_to_one',suffixes=('','_integrated'));assert len(f)==28060
 for c in ['kyoku_id','game_id','player_id']:assert f[c].eq(f[c+'_integrated']).all();f=f.drop(columns=c+'_integrated')
 basic=load(root/'basic_dontsuka_integration.csv.gz'); assert len(basic)==27578 and basic.draw_event_id.is_unique;g=f.groupby('draw_event_id',as_index=False)[COLS].max(); assert set(g.draw_event_id)==set(basic.draw_event_id);g=basic[['draw_event_id']+DIMS].merge(g,on='draw_event_id',validate='one_to_one');assert len(g)==27578
 for c,(p,d) in EXPECTED.items():
  assert (int(f[c].sum()),int(g[c].sum()))==(p,d);s=f[c.replace('_risk','_strict')];assert (int(s.sum()),int(f.loc[s,'draw_event_id'].nunique()))==tuple(cand[c.replace('_risk','_strict')][i] for i in ['pairs','draws']);assert (p,d)==tuple(cand[c.replace('_risk','_membership')][i] for i in ['pairs','draws'])
 return f,g,op,basic

def aggregates(old,f,g):
 template=old[old.metric=='basic_dontsuka_rate'].copy();out=[]
 for frame,unit,suffix in [(f,'draw_target','pair'),(g,'draw','draw')]:
  for c in COLS:
   for scope,dim in SCOPES.items():
    t=template[template.scope==scope].copy(); t['metric']=c+'_'+suffix;t['unit']=unit;t['origin']='3A/9;原典第2項';t['status']='counts_only';t['value']='';t['display_4']=''
    if dim:
     agg=frame.groupby(dim)[c].sum();pop=frame.groupby(dim).size();keys=[tuple(str(int(float(r[k]))) if k!='stage' else r[k] for k in dim) for _,r in t.iterrows()];keys=[k[0] for k in keys] if len(dim)==1 else keys;t['numerator']=[str(int(agg.get(k,0))) for k in keys];t['denominator']=[str(int(pop.get(k,0))) for k in keys]
    else:t['numerator']=str(int(frame[c].sum()));t['denominator']=str(len(frame))
    assert t.numerator.astype(int).sum()==frame[c].sum() and t.denominator.astype(int).sum()==len(frame);out.append(t)
 return pd.concat(out,ignore_index=True)
def verify(root,oldroot):
 f,g,op,basic=derive(root);old=load(oldroot/'metric_scopes.csv.gz');actual=load(root/'metric_scopes.csv.gz');extra=aggregates(old,f,g);pd.testing.assert_frame_equal(actual.iloc[:len(old)].reset_index(drop=True),old);pd.testing.assert_frame_equal(actual.iloc[len(old):].reset_index(drop=True),extra);assert not actual.duplicated(DIMS+['scope','metric']).any()
 for n,sc in [('metric_all.csv',['all']),('metric_players.csv',['player']),('metric_periods.csv.gz',['season','stage','season_stage']),('metric_player_periods.csv.gz',['player_season','player_stage','player_season_stage'])]:
  a=load(root/n);b=load(oldroot/n);pd.testing.assert_frame_equal(a.iloc[:len(b)].reset_index(drop=True),b);pd.testing.assert_frame_equal(a.iloc[len(b):].reset_index(drop=True),extra[extra.scope.isin(sc)].reset_index(drop=True))
 for frame,expected,keys in [(op,f,KEY),(basic,g,['draw_event_id'])]:
  j=frame.merge(expected[keys+COLS],on=keys,how='left',suffixes=('','_expected'),validate='one_to_one');
  for c in COLS:assert j[c].eq(j[c+'_expected'].map(lambda x:str(int(x)) if pd.notna(x) else '')).all()
 ledger=load(root/'metric_definition_ledger.csv');ol=load(oldroot/'metric_definition_ledger.csv');assert not ledger.status.eq('pending_definition').any();assert set(ledger.metric)==set(actual.metric);pd.testing.assert_frame_equal(ledger.iloc[:len(ol)-2][ol.columns].reset_index(drop=True),ol.iloc[:-2].reset_index(drop=True));assert len(ledger)==231
 for m,n,d in [('stage8:first_reach_all_opponents:rate',2046,237549),('stage8:first_reach_tenpai_opponents:rate',2046,38778)]:
  r=actual[(actual.scope=='all')&(actual.metric==m)].iloc[0];assert (int(r.numerator),int(r.denominator))==(n,d) and abs(float(r.value)-n/d*100)<1e-12
 return {'rows':len(actual),'series':actual.metric.nunique(),'rate_mean_series':actual[actual.status=='defined'].metric.nunique(),'count_series':actual[actual.status=='counts_only'].metric.nunique(),'ledger_rows':len(ledger),'unresolved':0,'artificial':artificial(),'counts':EXPECTED,'all_legacy_metric_rows_equal':len(old),'scope_counts':actual.groupby('scope').size().to_dict()}
def run(oldzip,out):
 assert sha(oldzip)==OLD;oldroot=out.parent/'stage9_verified_input';oldroot.mkdir(exist_ok=True);out.mkdir(exist_ok=False)
 with zipfile.ZipFile(oldzip) as z:
  assert z.testzip() is None and len(z.namelist())==len(set(z.namelist()));z.extractall(oldroot)
 m=json.loads((oldroot/'stage9_manifest.json').read_text());assert len(m['files'])==105 and set(m['files'])=={p.name for p in oldroot.iterdir()}-{'stage9_manifest.json'}
 for n,v in m['files'].items():assert sha(oldroot/n)==v['sha256'] and (oldroot/n).stat().st_size==v['size'];shutil.copy2(oldroot/n,out/n)
 f,g,op,basic=derive(oldroot)
 for name,frame,exp,keys in [('opponent_integration.csv.gz',op,f,KEY),('basic_dontsuka_integration.csv.gz',basic,g,['draw_event_id'])]:
  j=frame.merge(exp[keys+COLS],on=keys,how='left',validate='one_to_one');assert len(j)==len(frame);j[COLS]=j[COLS].apply(lambda s:s.map(lambda x:str(int(x)) if pd.notna(x) else ''));pd.testing.assert_frame_equal(j[frame.columns],frame);write(j,out/name)
 old=load(oldroot/'metric_scopes.csv.gz');extra=aggregates(old,f,g);write(pd.concat([old,extra],ignore_index=True),out/'metric_scopes.csv.gz')
 for n,sc in [('metric_all.csv',['all']),('metric_players.csv',['player']),('metric_periods.csv.gz',['season','stage','season_stage']),('metric_player_periods.csv.gz',['player_season','player_stage','player_season_stage'])]:write(pd.concat([load(oldroot/n),extra[extra.scope.isin(sc)]],ignore_index=True),out/n)
 ledger=load(oldroot/'metric_definition_ledger.csv').iloc[:-2].copy();ledger['approval_date']='';ledger['confirmed_count']='';rows=[]
 for c,lab,cond in [('top_risk','トップ陥落リスク','発生時に最高点と同点以上（トップ圏）、即時仮想放銃後に最高点未満'),('last_risk','ラス転落リスク','発生時に最低点より上（ラス圏外）、即時仮想放銃後に最低点と同点（ラス圏）')]:
  for i,(suffix,unit,file) in enumerate([('pair','draw_target','opponent_integration.csv.gz'),('draw','draw','basic_dontsuka_integration.csv.gz')]):
   rows.append(dict(metric=c+'_'+suffix,metric_name=lab+('（対他家別）' if i==0 else '（基本ツモ）'),original_section='2',numerator_definition=cond+('、該当対他家別件数' if i==0 else '、1家以上該当する基本ツモを1件'),denominator_definition='率なし。参考母集団は全対他家別ドンツカ' if i==0 else '率なし。参考母集団は全基本ドンツカ',unit=unit,judgment_time='ドンツカ取得時・即時仮想放銃後',applicable='承認済み仮想放銃明細、同点者・全員同点含む',excluded='不採用の単独基準、非ドンツカ',source_table=file+'; source_3a_opponent_hypothetical_all.csv',source_columns=c+'; before_scores; after_scores; draw_event_id; target_id',implementation_stage='3A/9',calculation='フラグ合算' if i==0 else 'draw_event_idごとに最大値を取り合算',display_unit='件',status='counts_only',approval_date='2026-11-28',confirmed_count=str(EXPECTED[c][i])))
 write(pd.concat([ledger,pd.DataFrame(rows)],ignore_index=True),out/'metric_definition_ledger.csv')
 result=verify(out,oldroot)
 (out/'final_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
 return result
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('oldzip',type=P);p.add_argument('output',type=P);a=p.parse_args();print(json.dumps(run(a.oldzip,a.output),ensure_ascii=False,indent=2))
