import unittest
from dontsuka_v026_3a import settlement, head, distance, hypothetical, score
from dontsuka_v026_2a_replay import Replay, hand
class Tests(unittest.TestCase):
    def test_parent_child(self):
        self.assertEqual(score(3,40,False,True),7700)
        self.assertEqual(score(3,40,False,False),5200)
    def test_kiriage(self):
        for h,f in [(4,30),(3,60)]:
            self.assertEqual(score(h,f,False,False),8000)
            self.assertEqual(score(h,f,False,True),12000)
        self.assertEqual(score(3,30,False,False),3900)
    def test_yakuman(self):
        self.assertEqual(score(13,0,False,False,1),32000)
        self.assertEqual(score(26,0,False,True,2),96000)
    def test_honba_pot(self):
        s={1:24000,2:25000,3:25000,4:25000}
        r=settlement(s,1,2,8000,2,1)
        self.assertEqual(r["ron_loss"],8600)
        self.assertEqual(r["pot_points"],1000)
        import json
        self.assertEqual(json.loads(r["after_scores"]),{"1":15400,"2":34600,"3":25000,"4":25000})
        self.assertEqual(s[1],24000)
    def test_ties(self):
        r=settlement({1:25000,2:25000,3:25000,4:25000},1,2,1000,0,0)
        self.assertEqual((r["drawer_rank_before"],r["drawer_rank_after"],r["rank_drop"]),(2.5,4,1.5))
    def test_last(self):
        self.assertEqual(settlement({1:10000,2:30000,3:30000,4:30000},1,2,8000,0,0)["rank_drop"],0)
    def test_head_and_no_sum(self):
        w={1:"4z",2:"1z",3:"2z",4:"3z"}
        self.assertEqual(head(w,1,[4,2,3]),2)
        self.assertEqual(head(w,1,[4,3]),3)
        self.assertEqual([distance(w,1,x) for x in [2,3,4]],[1,2,3])
        s={i:25000 for i in w}
        res=[settlement(s,1,x,b,0,0) for x,b in [(2,1000),(3,3900),(4,8000)]]
        self.assertEqual([x["ron_loss"] for x in res],[1000,3900,8000])
        self.assertEqual(s[1],25000)
    def test_red_dora_and_exclusions(self):
        rp=Replay();rp.hands[2]=hand("1m,2m,3m,1p,2p,3p,4s,6s,7s,8s,9s,5p,5p");rp.melds[2]=[]
        rp.reaches.add(2);rp.declarations[2]=False;rp.ippatsu.add(2);rp.omote=["4s","4p"];rp.ura=["4s"];rp.wall=0
        r=hypothetical(rp,2,"0s","2z","1z")
        import json
        y=json.loads(r["yaku"])
        self.assertEqual(y["赤ドラ"],1);self.assertEqual(y["ドラ"],3)
        self.assertEqual(y["立直"],1)
        self.assertNotIn("一発",y);self.assertNotIn("裏ドラ",y);self.assertNotIn("河底撈魚",y)
        self.assertEqual(r["ron_base"],score(r["han"],r["fu"],False,False))
    def test_no_yaku_chankan_only(self):
        rp=Replay();rp.hands[2]=hand("1m,2m,3m,1p,2p,3p,4s,6s,7s,8s,9s,5p,5p");rp.melds[2]=[]
        rp.omote=["4s"]
        with self.assertRaises(ValueError):hypothetical(rp,2,"5s","2z","1z")
    def test_double_reach(self):
        rp=Replay();rp.hands[2]=hand("1m,2m,3m,1p,2p,3p,4s,6s,7s,8s,9s,5p,5p");rp.melds[2]=[]
        rp.reaches.add(2);rp.declarations[2]=True
        import json
        self.assertEqual(json.loads(hypothetical(rp,2,"5s","2z","1z")["yaku"])["ダブル立直"],2)
if __name__=="__main__":unittest.main(verbosity=2)
