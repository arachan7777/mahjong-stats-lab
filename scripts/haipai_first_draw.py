import csv
import sqlite3
from collections import defaultdict, Counter
from mahjong.shanten import Shanten

db = sqlite3.connect("file:fixed.db?mode=ro", uri=True)
query = """
WITH first_draw AS (
 SELECT e.kyoku_id,d.actor_player_id,d.tile,row_number() OVER
 (PARTITION BY e.kyoku_id,d.actor_player_id ORDER BY e.event_order,e.id) rn
 FROM draw_event d JOIN event e ON e.id=d.event_id
), initial_dora AS (
 SELECT e.kyoku_id,d.dora_tile,row_number() OVER
 (PARTITION BY e.kyoku_id ORDER BY e.event_order,e.id) rn
 FROM dora_indicator_event d JOIN event e ON e.id=d.event_id WHERE d.dora_type='omote'
)
SELECT p.name,l.start_year,h.hand,s.shanten_count,i.dora_tile,f.tile
FROM haipai_event h JOIN event e ON e.id=h.event_id
JOIN player_state s ON s.event_id=h.event_id AND s.player_id=h.actor_player_id
JOIN player p ON p.id=h.actor_player_id JOIN kyoku k ON k.id=e.kyoku_id
JOIN game g ON g.id=k.game_id JOIN season_stage t ON t.id=g.season_stage_id
JOIN league_season l ON l.id=t.league_season_id
LEFT JOIN initial_dora i ON i.kyoku_id=k.id AND i.rn=1
LEFT JOIN first_draw f ON f.kyoku_id=k.id AND f.actor_player_id=p.id AND f.rn=1
"""
def tile_id(tile):
    return 'mpsz'.index(tile[1])*9+(int(tile[0]) or 5)-1

groups = defaultdict(Counter)
calc = Shanten()
for player, year, hand, before, dora, draw in db.execute(query):
    tiles = hand.split(',')
    assert len(tiles)==13 and dora
    counts = [0]*34
    for t in tiles:
        counts[tile_id(t)] += 1
    assert calc.calculate_shanten(counts)==before
    red = sum(t[0]=='0' for t in tiles)
    normal = counts[tile_id(dora)]
    hit = 0
    if draw:
        counts[tile_id(draw)] += 1
        hit = calc.calculate_shanten(counts)<before
    for key in [('全体','通算'),(player,'通算'),('全体',year),(player,year)]:
        c = groups[key]
        c.update({'配牌数':1,'向聴合計':before,'通常ドラ合計':normal,'赤合計':red,'ドラ3以上':int(normal+red>=3),'初ツモ数':int(bool(draw)),'有効数':int(hit),f'{before}向聴':1})
total = groups['全体','通算']
assert total['配牌数']==100952 and total['赤合計']==29197
keys = ['配牌数','平均向聴','平均通常ドラ','平均赤','ドラ3以上','ドラ3以上率','初ツモ数','有効数','初手有効牌ツモ率']+[f'{i}向聴' for i in range(7)]
with open('配牌格差と初手有効牌ツモ率.csv','w',encoding='utf-8-sig',newline='') as out:
    writer=csv.writer(out)
    writer.writerow(['選手','年度']+keys)
    for (player,year),c in groups.items():
        for k,num in [('平均向聴','向聴合計'),('平均通常ドラ','通常ドラ合計'),('平均赤','赤合計')]:
            c[k]=round(c[num]/c['配牌数'],4)
        c['ドラ3以上率']=round(100*c['ドラ3以上']/c['配牌数'],4)
        c['初手有効牌ツモ率']=round(100*c['有効数']/c['初ツモ数'],4)
        writer.writerow([player,year]+[c[k] for k in keys])
        if year=='通算': print('RESULT',player,[c[k] for k in keys])

# 配牌シャンテン数が同じ局での和了比較
rows = db.execute("""
SELECT p.name,s.shanten_count,count(*),sum(EXISTS(
 SELECT 1 FROM event w JOIN agari_event a ON a.event_id=w.id
 WHERE w.kyoku_id=e.kyoku_id AND a.actor_player_id=h.actor_player_id))
FROM haipai_event h JOIN event e ON e.id=h.event_id
JOIN player_state s ON s.event_id=h.event_id AND s.player_id=h.actor_player_id
JOIN player p ON p.id=h.actor_player_id
GROUP BY p.name,s.shanten_count
""")
buckets = defaultdict(Counter)
for name, shanten, n, wins in rows:
    for key in [(name,shanten),(name,'all'),('全体',shanten),('全体','all')]:
        buckets[key].update(n=n,w=wins)
print('DATE_COMPARE', [(key,dict(v)) for key,v in buckets.items() if key[0] in ('全体','伊達朱里紗')])

# 先制者は全員を対象に決めたうえで配牌2シャンテンに限定する。
split_query = """
WITH candidates AS MATERIALIZED (
 SELECT e.kyoku_id,t.player_id,
 ROW_NUMBER() OVER(PARTITION BY e.kyoku_id ORDER BY e.event_order,t.player_id) AS pos
 FROM player_tenpai_state t JOIN event e ON e.id=t.event_id
 WHERE t.is_actor=1 AND e.type IN ('haipai','discard')
)
SELECT p.name,CASE WHEN f.player_id=h.actor_player_id THEN 1 ELSE 0 END lead,
 COUNT(*),SUM(EXISTS(SELECT 1 FROM event w JOIN agari_event a ON a.event_id=w.id
 WHERE w.kyoku_id=e.kyoku_id AND a.actor_player_id=h.actor_player_id))
FROM haipai_event h JOIN event e ON e.id=h.event_id
JOIN player_state s ON s.event_id=h.event_id AND s.player_id=h.actor_player_id
JOIN player p ON p.id=h.actor_player_id
LEFT JOIN candidates f ON f.kyoku_id=e.kyoku_id AND f.pos=1
WHERE s.shanten_count=2 GROUP BY p.name,lead
"""
split = defaultdict(Counter)
for player, lead, n, wins in db.execute(split_query):
    for group in (player,'全体'):
        split[group,lead].update(n=n,w=wins)
for group in ('伊達朱里紗','全体'):
    for lead in (1,0):
        print('SPLIT2',group,lead,dict(split[group,lead]))
    assert sum(split[group,i]['w'] for i in (0,1)) == buckets[group,2]['w']
    assert sum(split[group,i]['n'] for i in (0,1)) == buckets[group,2]['n']

# 配牌2シャンテンの和了形を、直前の先制集計と同じ対象で照合する。
form_query = split_query[:split_query.index("SELECT p.name")] + """
SELECT p.name,CASE WHEN f.player_id=h.actor_player_id THEN 1 ELSE 0 END lead,
       w.type, a.target_player_id IS NULL, count(*)
FROM haipai_event h JOIN event e ON e.id=h.event_id
JOIN player_state s ON s.event_id=h.event_id AND s.player_id=h.actor_player_id
JOIN player p ON p.id=h.actor_player_id
LEFT JOIN candidates f ON f.kyoku_id=e.kyoku_id AND f.pos=1
JOIN event w ON w.kyoku_id=e.kyoku_id
JOIN agari_event a ON a.event_id=w.id AND a.actor_player_id=h.actor_player_id
WHERE s.shanten_count=2 GROUP BY p.name,lead,w.type,a.target_player_id IS NULL
"""
forms = defaultdict(Counter)
for player, lead, kind, no_target, n in db.execute(form_query):
    assert (kind,no_target) in [('ron',0),('tsumo',1)], (kind,no_target)
    for group in (player,'全体'):
        forms[group,lead][kind] += n
for group in ('伊達朱里紗','全体'):
    for lead in (1,0):
        assert sum(forms[group,lead].values())==split[group,lead]['w']
        print('WINFORM',group,lead,dict(forms[group,lead]))
