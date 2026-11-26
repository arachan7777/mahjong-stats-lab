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

# 成立リーチが複数の局。本人より早い他家が一人でもいれば追いかけ。
fight = """
WITH rr AS (
 SELECT e.kyoku_id,r.actor_player_id pid,e.event_order ord
 FROM reach_event r JOIN event e ON e.id=r.event_id WHERE r.is_accepted=1
), contested AS (
 SELECT *,min(ord) OVER(PARTITION BY kyoku_id) earliest,
 count(*) OVER(PARTITION BY kyoku_id) participants FROM rr
)
SELECT p.name,r.ord=r.earliest first,r.participants,
 CASE WHEN a.actor_player_id=r.pid THEN w.type
 WHEN a.actor_player_id IS NULL THEN 'draw'
 WHEN EXISTS(SELECT 1 FROM rr o WHERE o.kyoku_id=r.kyoku_id AND o.pid=a.actor_player_id) THEN 'rival'
 ELSE 'third' END outcome
FROM contested r JOIN player p ON p.id=r.pid
LEFT JOIN (event w JOIN agari_event a ON a.event_id=w.id) ON w.kyoku_id=r.kyoku_id
WHERE r.participants>=2
"""
duels=defaultdict(Counter)
for name, first, participants, outcome in db.execute(fight):
    for g in (name,'全体'):
        duels[g,first][outcome]+=1
for g in ('伊達朱里紗','全体'):
    for first in (0,1):
        print('DUEL',g,first,dict(duels[g,first]))
prior = split_query[:split_query.index("SELECT p.name")] + """
SELECT EXISTS(SELECT 1 FROM reach_event z JOIN event re ON re.id=z.event_id
 WHERE re.kyoku_id=e.kyoku_id AND z.actor_player_id=h.actor_player_id AND z.is_accepted=1 AND re.event_order<w.event_order),
 EXISTS(SELECT 1 FROM reach_event z JOIN event re ON re.id=z.event_id
 WHERE re.kyoku_id=e.kyoku_id AND z.actor_player_id<>h.actor_player_id AND z.is_accepted=1 AND re.event_order<w.event_order)
FROM haipai_event h JOIN event e ON e.id=h.event_id
JOIN player_state s ON s.event_id=h.event_id AND s.player_id=h.actor_player_id
JOIN player p ON p.id=h.actor_player_id
LEFT JOIN candidates f ON f.kyoku_id=e.kyoku_id AND f.pos=1
JOIN event w ON w.kyoku_id=e.kyoku_id AND w.type='tsumo'
JOIN agari_event a ON a.event_id=w.id AND a.actor_player_id=h.actor_player_id
WHERE s.shanten_count=2 AND p.name='伊達朱里紗' AND f.player_id IS NOT h.actor_player_id
"""
prior_counts=Counter(db.execute(prior))
assert sum(prior_counts.values())==15
print('PRIOR15',dict(prior_counts))

# 先制を取れなかった配牌2シャンテンを終局結果と他家成立リーチで分類。
outcome_query = split_query[:split_query.index("SELECT p.name")] + """
SELECT p.name,e.kyoku_id,
 EXISTS(SELECT 1 FROM reach_event z JOIN event re ON re.id=z.event_id
 WHERE re.kyoku_id=e.kyoku_id AND z.actor_player_id<>h.actor_player_id
 AND z.is_accepted=1 AND re.event_order<end_e.event_order),
 CASE WHEN end_e.type='ryukyoku' THEN 'draw'
 WHEN a.actor_player_id=h.actor_player_id THEN end_e.type
 WHEN a.target_player_id=h.actor_player_id THEN 'deal_in'
 WHEN end_e.type='tsumo' THEN 'other_tsumo' ELSE 'side_ron' END
FROM haipai_event h JOIN event e ON e.id=h.event_id
JOIN player_state s ON s.event_id=h.event_id AND s.player_id=h.actor_player_id
JOIN player p ON p.id=h.actor_player_id
LEFT JOIN candidates f ON f.kyoku_id=e.kyoku_id AND f.pos=1
JOIN event end_e ON end_e.kyoku_id=e.kyoku_id AND end_e.type IN ('ryukyoku','ron','tsumo')
LEFT JOIN agari_event a ON a.event_id=end_e.id
WHERE s.shanten_count=2 AND f.player_id IS NOT h.actor_player_id
"""
ends = defaultdict(Counter)
seen = set()
for name, kid, exposed, result in db.execute(outcome_query):
    assert (name,kid) not in seen
    seen.add((name,kid))
    for group in (name,'全体'):
        ends[group,exposed][result]+=1
for group,total in [('全体',5659),('伊達朱里紗',147)]:
    assert sum(sum(ends[group,flag].values()) for flag in (0,1))==total
    for flag in (0,1):
        print('REACHOUT',group,flag,dict(ends[group,flag]))
assert ends['伊達朱里紗',1]['tsumo']==8

# Count each of the three responders once, from the first accepted riichi.
response_query = """
WITH reaches AS (
 SELECT e.kyoku_id,r.actor_player_id pid,
 row_number() OVER (PARTITION BY e.kyoku_id ORDER BY e.event_order,e.id) seq
 FROM event e JOIN reach_event r ON r.event_id=e.id WHERE r.is_accepted=1
)
SELECT p.name,own.seq IS NOT NULL,
 CASE WHEN a.actor_player_id=p.id THEN w.type
 WHEN a.target_player_id=p.id THEN 'deal_in' ELSE 'other' END
FROM reaches first
JOIN event e ON e.kyoku_id=first.kyoku_id AND e.type='haipai'
JOIN haipai_event h ON h.event_id=e.id
JOIN player p ON p.id=h.actor_player_id AND p.id<>first.pid
LEFT JOIN reaches own ON own.kyoku_id=e.kyoku_id AND own.pid=p.id
JOIN event w ON w.kyoku_id=e.kyoku_id AND w.type IN ('ron','tsumo','ryukyoku')
LEFT JOIN agari_event a ON a.event_id=w.id
WHERE first.seq=1
"""
responses=defaultdict(Counter)
for name,chase,result in db.execute(response_query):
    for group in (name,'全体'):
        responses[group,chase][result]+=1
for group in ('全体','伊達朱里紗'):
    chased=responses[group,1]
    assert sum(chased.values())==sum(duels[group,0].values())
    for result in ('ron','tsumo'):
        assert chased[result]==duels[group,0][result]
    for chase in (0,1):
        print('RESPONSE',group,chase,dict(responses[group,chase]))

# Fixed-version actual kyotaku net by accepted reach expenditure, agari receipts,
# and any pool remaining at game end, assigned to the game's first-place finisher.
kyotaku_query = """
WITH reach_spent AS (
 SELECT e.kyoku_id,r.actor_player_id player_id,COUNT(*) sticks
 FROM reach_event r JOIN event e ON e.id=r.event_id
 WHERE r.is_accepted=1 GROUP BY e.kyoku_id,r.actor_player_id
), win_received AS (
 SELECT e.kyoku_id,a.actor_player_id player_id,SUM(a.kyotaku_points) points
 FROM agari_event a JOIN event e ON e.id=a.event_id GROUP BY e.kyoku_id,a.actor_player_id
), last_kyoku AS (
 SELECT game_id,MAX(id) kyoku_id FROM kyoku GROUP BY game_id
), final_reach AS (
 SELECT l.game_id,COALESCE(SUM(rs.sticks),0) sticks
 FROM last_kyoku l LEFT JOIN reach_spent rs ON rs.kyoku_id=l.kyoku_id GROUP BY l.game_id
), final_win AS (
 SELECT l.game_id,COALESCE(SUM(w.points),0) points
 FROM last_kyoku l LEFT JOIN win_received w ON w.kyoku_id=l.kyoku_id GROUP BY l.game_id
), final_pool AS (
 SELECT l.game_id,k.kyotaku_count*1000+fr.sticks*1000-fw.points remaining
 FROM last_kyoku l JOIN kyoku k ON k.id=l.kyoku_id
 JOIN final_reach fr ON fr.game_id=l.game_id JOIN final_win fw ON fw.game_id=l.game_id
), per_game AS (
 SELECT gr.game_id,gr.player_id,
 COALESCE((SELECT SUM(sticks)*1000 FROM reach_spent rs JOIN kyoku k ON k.id=rs.kyoku_id
 WHERE k.game_id=gr.game_id AND rs.player_id=gr.player_id),0) spent,
 COALESCE((SELECT SUM(points) FROM win_received w JOIN kyoku k ON k.id=w.kyoku_id
 WHERE k.game_id=gr.game_id AND w.player_id=gr.player_id),0) won,
 CASE WHEN gr.rank=1 THEN fp.remaining ELSE 0 END end_pool
 FROM game_player_result gr JOIN final_pool fp ON fp.game_id=gr.game_id
)
SELECT p.name,COUNT(*),SUM(pg.spent),SUM(pg.won),SUM(pg.end_pool),
 SUM(pg.won+pg.end_pool-pg.spent)
FROM per_game pg JOIN player p ON p.id=pg.player_id
GROUP BY p.id,p.name ORDER BY SUM(pg.won+pg.end_pool-pg.spent) DESC,p.name
"""
kyotaku=db.execute(kyotaku_query).fetchall()
print('KYOTAKU_ZERO_SUM',sum(row[5] for row in kyotaku))
for row in kyotaku:
    if row[0] in ('伊達朱里紗',):
        print('KYOTAKU_PLAYER',row)
print('KYOTAKU_RANK',next(i for i,row in enumerate(kyotaku,1) if row[0]=='伊達朱里紗'),len(kyotaku))

# Agari points per winning hand, with bonus payments shown separately.
avg_agari = db.execute("""
SELECT p.name,COUNT(*),SUM(a.agari_points),AVG(a.agari_points),
       SUM(a.honba_points),SUM(a.kyotaku_points),SUM(a.revenue_points),AVG(a.revenue_points)
FROM agari_event a JOIN event e ON e.id=a.event_id
JOIN player p ON p.id=a.actor_player_id WHERE e.type IN ('ron','tsumo')
GROUP BY p.id,p.name HAVING p.name='伊達朱里紗'
""").fetchone()
league_agari = db.execute("""
SELECT COUNT(*),SUM(a.agari_points),AVG(a.agari_points),
       SUM(a.honba_points),SUM(a.kyotaku_points),SUM(a.revenue_points),AVG(a.revenue_points)
FROM agari_event a JOIN event e ON e.id=a.event_id WHERE e.type IN ('ron','tsumo')
""").fetchone()
print('AVG_AGARI_DATE',avg_agari)
print('AVG_AGARI_LEAGUE',league_agari)

# Head-to-head final score comparisons in games shared with Date.
h2h = """
WITH last_kyoku AS (SELECT game_id,MAX(id) kyoku_id FROM kyoku GROUP BY game_id),
scores AS (
 SELECT l.game_id,kpr.player_id,kpr.score
 FROM last_kyoku l JOIN kyoku_player_result kpr ON kpr.kyoku_id=l.kyoku_id
), date_games AS (
 SELECT s.game_id,s.score date_score FROM scores s JOIN player p ON p.id=s.player_id
 WHERE p.name='伊達朱里紗'
)
SELECT p.name,COUNT(*),SUM(CASE WHEN d.date_score>s.score THEN 1 ELSE 0 END),
       SUM(CASE WHEN d.date_score=s.score THEN 1 ELSE 0 END),
       SUM(CASE WHEN d.date_score<s.score THEN 1 ELSE 0 END),
       SUM(d.date_score-s.score),AVG(d.date_score-s.score)
FROM date_games d JOIN scores s ON s.game_id=d.game_id
JOIN player p ON p.id=s.player_id
WHERE p.name<>'伊達朱里紗'
GROUP BY p.id,p.name ORDER BY COUNT(*) DESC,p.name
"""
for row in db.execute(h2h):
    print('HEAD_TO_HEAD',row)
