"""Artificial cases for stage 2A. No real DB values are used."""
import unittest
from dontsuka_v026_2a_replay import Replay, block
from dontsuka_v026_2a_audit import evaluate,score

def step(r,k,p=1,t=None,**kw):
    r.step(dict(type=k,actor=p,tile=t,**kw))

def seed(tiles):
    r=Replay();step(r,"haipai",hand=tiles);return r

def draw(r,t,rinshan=False,wall=40):
    step(r,"draw",t=t,rinshan=rinshan,wall=wall)
def discard(r,t,p=1,declaration=False):
    step(r,"discard",p,t,declaration=declaration)
def score_hand(r,t,tsumo=True,target=None):
    h,m,f=r.winning(1,t,tsumo,target)
    return evaluate(h,m,t,f,"2z","1z",r.omote,r.ura)

class Stage2ATests(unittest.TestCase):
    def test_blocks(self):
        self.assertEqual(block("5-050m"),["5m","0m","5m","0m"])
        self.assertEqual(block("-123s"),["1s","2s","3s"])
    def test_ankan_rinshan(self):
        r=seed("1m,1m,1m,2m,3m,4m,2p,3p,4p,2s,3s,4s,5z")
        draw(r,"1m");step(r,"ankan",t="1m",block="1111m");draw(r,"5z",True)
        h,m,f=r.winning(1,"5z",True)
        self.assertEqual(m,[("ankan",["1m"]*4)])
        self.assertEqual(len(h),11)
        self.assertTrue(f["is_rinshan"])
        self.assertIn("嶺上開花",score_hand(r,"5z")["yaku"])
    def test_daiminkan_rinshan(self):
        r=seed("1m,1m,1m,2m,3m,4m,2p,3p,4p,2s,3s,4s,5z")
        step(r,"haipai",2,hand="1m")
        discard(r,"1m",2)
        step(r,"daiminkan",t="1m",block="-1111m",target=2)
        draw(r,"5z",True)
        self.assertEqual(r.winning(1,"5z",True)[1][0][0],"daiminkan")
        self.assertIn("嶺上開花",score_hand(r,"5z")["yaku"])
    def test_shominkan_rinshan(self):
        r=seed("5m,0m,2m,3m,4m,2p,3p,4p,2s,3s,4s,5z,6z")
        step(r,"haipai",2,hand="5m")
        discard(r,"5m",2)
        step(r,"pon",t="5m",block="-550m",target=2)
        discard(r,"6z")
        draw(r,"5m")
        step(r,"shominkan",t="5m",block="-5505m")
        draw(r,"5z",True)
        h,m,f=r.winning(1,"5z",True)
        self.assertEqual(m,[("shominkan",["5m","5m","0m","5m"])])
        self.assertIn("嶺上開花",score_hand(r,"5z")["yaku"])
        self.assertEqual(score_hand(r,"5z")["yaku"]["赤ドラ"],1)
    def test_chankan(self):
        r=seed("1m,2m,3m,4p,5p,6p,4s,5s,6s,2z,2z,7m,8m")
        step(r,"haipai",2,hand="9m")
        r.last_action=("shominkan",2,"9m")
        self.assertIn("搶槓",score_hand(r,"9m",False,2)["yaku"])
    def test_haitei_not_houtei(self):
        r=seed("1m,2m,3m,4p,5p,6p,4s,5s,6s,2z,2z,7m,8m")
        r.draws[1]=2
        draw(r,"9m",False,0)
        y=score_hand(r,"9m")["yaku"]
        self.assertIn("海底摸月",y);self.assertNotIn("河底撈魚",y)
    def test_ippatsu_cleared_by_kan(self):
        r=seed("1m,1m,1m,2m,3m,4m,2p,3p,4p,2s,3s,4s,5z")
        draw(r,"6z");discard(r,"6z",declaration=True);step(r,"reach",accepted=True)
        draw(r,"1m");step(r,"ankan",t="1m",block="1111m");draw(r,"5z",True)
        self.assertFalse(r.winning(1,"5z",True)[2]["is_ippatsu"])
    def test_honba_separate_and_score(self):
        self.assertEqual(score(4,30,False,False),8000)
        self.assertEqual(score(3,60,True,True),12000)
        self.assertEqual(score(13,30,False,False),24000)
        self.assertEqual(score(26,0,True,False,2),64000)
        self.assertEqual(score(1,30,False,False),1000)
        self.assertEqual(score(2,20,True,False),1500)
    def test_red_and_ura_separate(self):
        r=seed("2m,3m,4m,4p,0p,6p,2s,3s,4s,6s,7s,8s,5z")
        draw(r,"6z");discard(r,"6z",declaration=True);step(r,"reach",accepted=True)
        draw(r,"5z");r.omote=["4p"];r.ura=["4z"]
        y=score_hand(r,"5z")["yaku"]
        self.assertEqual(y["ドラ"],1);self.assertEqual(y["赤ドラ"],1);self.assertEqual(y["裏ドラ"],2)
    def test_no_silent_tile_substitution(self):
        r=seed("5m")
        with self.assertRaises(ValueError):discard(r,"0m")

if __name__=="__main__":unittest.main(verbosity=2)
