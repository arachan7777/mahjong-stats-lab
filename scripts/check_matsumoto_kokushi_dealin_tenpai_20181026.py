#!/usr/bin/env python3
"""2018-10-26 Mリーグ初の役満放銃局の松本吉弘状態を固定牌譜DBで照合する（読取専用）。"""
import sqlite3,sys,os,json
db=sqlite3.connect('file:'+os.path.abspath(sys.argv[1])+'?mode=ro',uri=True)
db.row_factory=sqlite3.Row
db.execute("PRAGMA query_only=ON")
def fetch(sql,*args): return [dict(r) for r in db.execute(sql,args)]
def printrows(n,rows):print(n+" "+json.dumps(rows,ensure_ascii=False,default=str),flush=True)
for t in ('event','discard_event','draw_event','player_state','reach_event','player_tenpai_state','agari_event','kyoku'):
 printrows('SCHEMA_'+t,fetch('PRAGMA table_info("'+t+'")'))
ron=fetch("SELECT e.id,e.kyoku_id,e.event_order,e.type,ae.agari_tile,ae.actor_player_id,ae.target_player_id FROM event e JOIN agari_event ae ON ae.event_id=e.id WHERE e.id=2561068")
assert len(ron)==1 and ron[0]['kyoku_id']==23464 and ron[0]['type']=='ron',ron
printrows('RON',ron)
mid=db.execute("SELECT id FROM player WHERE name='松本吉弘'").fetchone()[0]
rid=ron[0]['event_order']
events=fetch("""
SELECT e.id event_id,e.event_order,e.type,
 d.actor_player_id d_actor,d.tile discarded_tile,
 dr.actor_player_id draw_actor,dr.tile drawn_tile,
 re.actor_player_id reach_actor,re.is_accepted reach_accepted,
 ps.player_id state_player,ps.shanten_count state_shanten
FROM event e
LEFT JOIN discard_event d ON d.event_id=e.id
LEFT JOIN draw_event dr ON dr.event_id=e.id
LEFT JOIN reach_event re ON re.event_id=e.id
LEFT JOIN player_state ps ON ps.event_id=e.id AND ps.player_id=?
WHERE e.kyoku_id=? AND e.event_order <= ?
ORDER BY e.event_order DESC,e.id DESC LIMIT 40
""",mid,ron[0]['kyoku_id'],rid)
printrows('PREVIOUS_40_EVENTS_DESC',events)
state=fetch("""
SELECT e.id,e.type,e.event_order,ps.shanten_count,ps.*
FROM player_state ps JOIN event e ON e.id=ps.event_id
WHERE e.kyoku_id=? AND ps.player_id=? AND e.event_order <= ?
ORDER BY e.event_order DESC,e.id DESC LIMIT 15
""",ron[0]['kyoku_id'],mid,rid)
printrows('MATSUMOTO_15_STATE_ROWS_DESC',state)
reaches=fetch("""
SELECT e.id,e.event_order,re.actor_player_id,re.is_accepted,re.*
FROM reach_event re JOIN event e ON e.id=re.event_id
WHERE e.kyoku_id=? AND re.actor_player_id=?
ORDER BY e.event_order
""",ron[0]['kyoku_id'],mid)
printrows('MATSUMOTO_REACH_EVENTS',reaches)
discards=fetch("""
SELECT e.id,e.event_order,e.type,d.*
FROM event e JOIN discard_event d ON d.event_id=e.id
WHERE e.kyoku_id=? AND d.actor_player_id=?
ORDER BY e.event_order DESC LIMIT 10
""",ron[0]['kyoku_id'],mid)
printrows('MATSUMOTO_DISCARDS_DESC',discards)
print('VALIDATION_SUCCESS')
