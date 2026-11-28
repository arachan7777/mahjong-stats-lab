"""Verify existing stage9, preserve all previous rows, package and read back final ZIP."""
import argparse, hashlib, json, pathlib, zipfile, shutil, tempfile
import pandas as pd
from dontsuka_v026_stage9_final import verify, sha, load, OLD, DB, COLS
P=pathlib.Path

def unpack(path,root,expected=None):
 if expected:assert sha(path)==expected
 with zipfile.ZipFile(path) as z:
  names=z.namelist();assert len(names)==len(set(names));assert all(P(n).name==n for n in names);assert z.testzip() is None;z.extractall(root)
 m=json.loads((root/'stage9_manifest.json').read_text());assert set(m['files'])==set(names)-{'stage9_manifest.json'}
 for n,v in m['files'].items():assert sha(root/n)==v['sha256'] and (root/n).stat().st_size==v['size']
 return m

def baseline(root):
 d=pd.read_csv(root/'all_draws_integration.csv.gz',usecols=['draw_event_id','game_id','kyoku_id','player_id','is_dontsuka','shoubute_any','head_bump_rank_drop']);r=pd.read_csv(root/'player_round_results.csv.gz',usecols=['kyoku_id','player_id']);p=pd.read_csv(root/'source_3a_opponent_hypothetical_all.csv',usecols=['rank_drop']);c=pd.read_csv(root/'source_4b_coexistence_kyoku.csv');s=pd.read_csv(root/'shoubute_union_rounds.csv');a=pd.read_csv(root/'stage5a_shoubute_scopes.csv').query("scope=='all'").iloc[0];b=pd.read_csv(root/'stage5b_shoubute_scopes.csv').query("scope=='all'").iloc[0]
 v={'games':d.game_id.nunique(),'rounds':d.kyoku_id.nunique(),'players':d.player_id.nunique(),'player_rounds':len(r),'draws':len(d),'basic_dontsuka':int(d.is_dontsuka.sum()),'opponent_dontsuka':len(p),'opponent_rank_drop':int(p.rank_drop.gt(0).sum()),'opponent_rank_maintain':int(p.rank_drop.eq(0).sum()),'head_bump_rank_drop':int(d.head_bump_rank_drop.sum()),'rank_drop_player_rounds':len(pd.read_csv(root/'rank_drop_rounds.csv.gz')),'coexist':len(c),'tolerated':int(c.tolerated.sum()),'sage':int(c.sage.sum()),'shoubute_draws':int(d.shoubute_any.sum()),'shoubute_dontsuka':int(d.loc[d.shoubute_any.eq(1),'is_dontsuka'].sum()),'shoubute_rounds':len(s),'shoubute_overlap':int(a.shoubute_dontsuka_kyoku+b.shoubute_isshanten_dontsuka_kyoku-len(s)),'shoubute_ron':int(s.actual_ron.sum()),'shoubute_win':int(s.self_win.sum()),'shoubute_net':int(s.kyoku_net.sum())}
 expected=[2068,25238,56,100952,1257732,27578,28060,13170,14890,12931,11143,340,29,14,329522,10526,9898,212,4706,818,-27268900]
 assert list(v.values())==expected,(v,expected);assert d.draw_event_id.is_unique and not r.duplicated().any() and not s.duplicated(['kyoku_id','player_id']).any()
 return {k:int(x) for k,x in v.items()}

def check(root,oldroot,om):
 result=verify(root,oldroot);result['approved_baselines']=baseline(root)
 for name in ['opponent_integration.csv.gz','basic_dontsuka_integration.csv.gz']:
  old=load(oldroot/name);new=load(root/name);pd.testing.assert_frame_equal(new[old.columns],old);assert list(new.columns)==list(old.columns)+COLS
 changes={};unchanged=[]
 for name,v in om['files'].items():
  h=sha(root/name)
  if h==v['sha256']:unchanged.append(name)
  else:changes[name]={'old_sha256':v['sha256'],'new_sha256':h}
 result['unchanged_files']=sorted(unchanged);result['changed_files']=changes
 return result

def package(root,oldzip,out,commit):
 with tempfile.TemporaryDirectory() as tmp:
  oldroot=P(tmp);om=unpack(oldzip,oldroot,OLD);r=check(root,oldroot,om)
  (root/'final_validation.json').write_text(json.dumps(r,ensure_ascii=False,indent=2))
  # Logs are closed before the manifest is generated.
  (root/'final_validation.log').write_text('最終確定反映検証：全項目合格\n'+json.dumps({k:v for k,v in r.items() if k not in ['changed_files','unchanged_files']},ensure_ascii=False,indent=2)+'\n')
  files={p.name:{'size':p.stat().st_size,'sha256':sha(p)} for p in sorted(root.iterdir()) if p.is_file() and p.name!='stage9_manifest.json'}
  changed={n:{'old_sha256':v['sha256'],'new_sha256':files[n]['sha256']} for n,v in om['files'].items() if files[n]['sha256']!=v['sha256']};unchanged=sorted(set(om['files'])-set(changed));added=sorted(set(files)-set(om['files']))
  m={'version':'v0.26','fixed_db':DB,'status':'final_reflected_pending_independent_approval','git_commit':commit,'previous_git_commit':om['git_commit'],'previous_zip_sha256':OLD,'unresolved':[],'files':files,'changed_files':changed,'unchanged_files':unchanged,'added_files':added,'manifest_note':'stage9_manifest.json 自身はハッシュ対象外。旧Manifestは変更前ZIPに保持。'}
  (root/'stage9_manifest.json').write_text(json.dumps(m,ensure_ascii=False,indent=2))
  with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=3,allowZip64=True) as z:
   for p in sorted(root.iterdir()):
    if p.is_file():z.write(p,p.name,compress_type=zipfile.ZIP_STORED if p.name.endswith('.gz') else zipfile.ZIP_DEFLATED)
 with tempfile.TemporaryDirectory() as tmp:unpack(out,P(tmp))
 return {'size':out.stat().st_size,'sha256':sha(out),'internal_files':len(files),'changed':list(changed),'unchanged_count':len(unchanged),'added':added,'validation':r}

def readback(finalzip,oldzip,expected):
 with tempfile.TemporaryDirectory() as a,tempfile.TemporaryDirectory() as b:
  root=P(a);oldroot=P(b);m=unpack(finalzip,root,expected);om=unpack(oldzip,oldroot,OLD);r=check(root,oldroot,om);assert not m['unresolved'];assert set(m['unchanged_files'])==set(r['unchanged_files']);assert set(m['changed_files'])==set(r['changed_files']);assert set(m['added_files'])==set(m['files'])-set(om['files'])
  return {'size':finalzip.stat().st_size,'sha256':sha(finalzip),'internal_files':len(m['files']),'zip_crc':'pass','internal_hashes':'pass','duplicates_missing':'none','git_commit':m['git_commit'],'validation':r}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['package','readback']);p.add_argument('oldzip',type=P);p.add_argument('finalzip',type=P);p.add_argument('--root',type=P);p.add_argument('--commit');p.add_argument('--sha256');a=p.parse_args();print(json.dumps(package(a.root,a.oldzip,a.finalzip,a.commit) if a.mode=='package' else readback(a.finalzip,a.oldzip,a.sha256),ensure_ascii=False,indent=2))
