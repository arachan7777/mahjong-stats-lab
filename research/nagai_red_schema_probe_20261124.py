import sqlite3,sys,json
c=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True)
tables=[x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
for name in tables:
 if any(x in name for x in ['discard','reach','ron','tsumo','agari','haipai','chi','pon','kan','event','game','kyoku','season','player']):
  print('TABLE',name, json.dumps([r[1] for r in c.execute('PRAGMA table_info('+name+')')]),flush=True)
for name in ['event','discard_event','reach_event','agari_event','draw_event','chi_event','pon_event','haipai_event','kyoku','game']:
 if name in tables:
  print('SAMPLE',name,json.dumps(c.execute('SELECT * FROM '+name+' LIMIT 2').fetchall(),ensure_ascii=False,default=str),flush=True)
