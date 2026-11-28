import unittest
from dontsuka_v026_4a_tracker import Tracker,classify

class TestTracker(unittest.TestCase):
    def setup_tracker(self,hand="3m,4m,5m"):
        tr=Tracker()
        tr.step(dict(id=1,event_order=1,type="haipai",actor=1,hand=hand))
        return tr
    def step(self,tr,i,kind,t,targets=(),ts=False,**kw):
        e=dict(id=i,event_order=i,type=kind,actor=1,tile=t,wall=20,declaration=False,**kw)
        r=[dict(draw_event_id=i,drawer=1,target=x,event_order=i,tile=t,rank_drop=1,kyoku_id=1) for x in targets]
        tr.step(e,r,ts if kind=="discard" else None)
    def ron(self,tr,t,winner=2):
        return classify(tr,dict(event_id=99,kyoku_id=1,actor_player_id=winner,target_player_id=1,agari_tile=t))
    def test_immediate(self):
        tr=self.setup_tracker();self.step(tr,2,"draw","3m",[2]);self.step(tr,3,"discard","3m",ts=True)
        r,l=self.ron(tr,"3m");self.assertEqual(r["category"],"immediate");self.assertEqual(r["target_class"],"same_target")
    def test_same_tile_hand_discard_not_immediate(self):
        tr=self.setup_tracker();self.step(tr,2,"draw","3m",[2]);self.step(tr,3,"discard","3m")
        self.assertEqual(self.ron(tr,"3m")[0]["category"],"subsequent")
    def test_partial_and_wait_change_other_target(self):
        tr=self.setup_tracker();self.step(tr,2,"draw","3m",[2]);self.step(tr,3,"discard","3m",ts=True)
        self.step(tr,4,"draw","6m");self.step(tr,5,"discard","3m")
        r,l=self.ron(tr,"3m",3)
        self.assertEqual((r["category"],r["target_class"]),("subsequent","other_target"))
        self.assertEqual(tr.origins[0]["before_count"],1)
        self.assertEqual(tr.origins[0]["end_event_id"],5)
    def test_zero_reacquire(self):
        tr=self.setup_tracker("4m,5m");self.step(tr,2,"draw","3m",[2]);self.step(tr,3,"discard","3m",ts=True)
        self.step(tr,4,"draw","3m");self.step(tr,5,"discard","3m",ts=True)
        self.assertEqual(self.ron(tr,"3m")[0]["category"],"unclassified")
        self.assertEqual(tr.origins[0]["end_event_id"],3)
    def test_different(self):
        tr=self.setup_tracker();self.step(tr,2,"draw","3m",[2]);self.step(tr,3,"discard","4m")
        self.assertEqual(self.ron(tr,"4m")[0]["category"],"different_tile")
    def test_red_normal(self):
        tr=self.setup_tracker();self.step(tr,2,"draw","0m",[2]);self.step(tr,3,"discard","0m",ts=True)
        self.step(tr,4,"draw","6m");self.step(tr,5,"discard","5m")
        self.assertEqual(self.ron(tr,"5m")[0]["category"],"subsequent")
    def test_multiple_origins(self):
        tr=self.setup_tracker();self.step(tr,2,"draw","3m",[2,3]);self.step(tr,3,"discard","4m")
        self.step(tr,4,"draw","3m",[4]);self.step(tr,5,"discard","3m",ts=True)
        r,l=self.ron(tr,"3m",2)
        self.assertEqual(r["category"],"immediate");self.assertEqual(len(l),3)
        self.assertEqual(r["causal_origin_count"],2)
        self.assertEqual({x["relation"] for x in l},{"immediate","subsequent"})
    def test_ankan_excluded(self):
        tr=self.setup_tracker("3m,3m,3m");self.step(tr,2,"draw","3m",[2])
        self.step(tr,3,"ankan","3m",block="3333m")
        self.assertEqual(self.ron(tr,"3m")[0]["category"],"special_excluded")
        self.assertEqual(tr.origins[0]["end_count"],0)
    def test_pon_consumes(self):
        tr=self.setup_tracker("3m,4m");self.step(tr,2,"draw","3m",[2]);self.step(tr,3,"discard","4m")
        tr.step(dict(id=4,event_order=4,type="haipai",actor=2,hand="3m,7m"))
        tr.step(dict(id=5,event_order=5,type="discard",actor=2,tile="3m",declaration=False),tsumogiri=False)
        self.step(tr,6,"pon","3m",block="333m",target=2)
        self.assertEqual(tr.origins[0]["end_event_id"],6)
    def test_finish(self):
        tr=self.setup_tracker();self.step(tr,2,"draw","3m",[2]);tr.finish(dict(id=3,event_order=3))
        self.assertEqual(tr.origins[0]["end_reason"],"kyoku_end")
if __name__=="__main__":unittest.main(verbosity=2)
