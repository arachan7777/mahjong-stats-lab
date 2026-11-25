import sqlite3,sys,os,json
db=sqlite3.connect('file:'+os.path.abspath(sys.argv[1])+'?mode=ro',uri=True)
db.row_factory=sqlite3.Row
db.execute('PRAGMA query_only=ON')
for t in ['game_player_result','player_season_stage_stats_base','game','player','season_stage','kyoku']:
 print('SCHEMA',t,json.dumps([dict(x) for x in db.execute(f'PRAGMA table_info("{t}")')],ensure_ascii=False),flush=True)
try:
 for t in ['game_player_result','player_season_stage_stats_base']:
  print('SAMPLE',t,json.dumps([dict(x) for x in db.execute(f'SELECT * FROM "{t}" LIMIT 2')],ensure_ascii=False),flush=True)
except Exception as e: print('ERROR',repr(e),flush=True)
print('VALIDATION_SUCCESS')
