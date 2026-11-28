import unittest
from dontsuka_v026_4b_core import state,coexists,transition,ron_result

def o(e,t,r,start,end,typ="3m"):
    return dict(draw_event_id=e,target=t,rank_drop=r,start_event_order=start,end_event_order=end,tile_type=typ)
D=o(1,2,1,1,8); M=o(2,3,0,2,9)
L=dict(draw_event_id=2,target=3,relation="subsequent",same_target=1)
class Test(unittest.TestCase):
    def s(self,order,flags,side="after",origins=(D,M)):
        return state(origins,order,{(2,"3m"):flags[0],(3,"3m"):flags[1]},side)
    def test_non_overlap(self):
        self.assertFalse(coexists(self.s(1,(True,True))))
        self.assertFalse(coexists(self.s(2,(False,True))))
    def test_same_type_multiple_targets_and_start(self):
        a=self.s(1,(True,True));b=self.s(2,(True,True))
        self.assertTrue(coexists(b));self.assertEqual(transition(a,b,False),"start")
    def test_same_draw_both(self):
        a=self.s(1,(True,True),origins=(D,o(1,3,0,1,9)))
        self.assertEqual(a[:2],(((1,2),),((1,3),)))
    def test_wait_change(self):
        a=self.s(2,(True,True));b=self.s(3,(False,True))
        self.assertEqual(transition(a,b,True),"end")
    def test_noten(self):
        self.assertFalse(coexists(self.s(4,(True,False))))
    def test_furiten(self):
        self.assertFalse(coexists(self.s(4,(False,True))))
    def test_recovery(self):
        self.assertEqual(transition(self.s(4,(False,True)),self.s(5,(True,True)),True),"restart")
    def test_possession_zero_and_reacquire(self):
        self.assertTrue(coexists(self.s(8,(True,True),"before")))
        self.assertFalse(coexists(self.s(8,(True,True))))
        self.assertFalse(coexists(self.s(9,(True,True))))
        self.assertTrue(coexists(self.s(8,(True,True),origins=(D,M,o(3,2,1,8,10)))))
    def test_missing_is_not_false(self):
        self.assertEqual(self.s(4,(None,True))[2],((1,2),))
    def ron(self,**kw):
        x=dict(s=self.s(5,(True,True)),links=[L],winner=3,rank_before=2.5,rank_end=2.5,source_kind="discard",tsumogiri=False,declaration=False,accepted_before=False,open_before=False,closed_tenpai_before=True)
        x.update(kw);return ron_result(**x)
    def test_tolerated(self):
        self.assertEqual(self.ron()["tolerated"],1)
        self.assertEqual(self.ron(rank_end=3)["tolerated"],0)
        self.assertEqual(self.ron(rank_end=2)["tolerated"],0)
    def test_wrong_target_or_tile(self):
        self.assertEqual(self.ron(winner=2)["tolerated"],0)
        self.assertEqual(self.ron(links=[dict(L,relation="different_tile")])["tolerated"],0)
    def test_selection(self):
        for open_ in (False,True):
            for ts in (False,True):
                self.assertEqual(self.ron(open_before=open_,tsumogiri=ts)["sage"],1)
    def test_declaration(self):
        self.assertEqual(self.ron(declaration=True,closed_tenpai_before=False)["sage"],1)
    def test_accepted_excluded(self):
        r=self.ron(accepted_before=True,tsumogiri=True)
        self.assertEqual((r["tolerated"],r["sage"],r["reach_tsumogiri_excluded"]),(1,0,1))
    def test_special(self):
        for k in ("shominkan","ankan"):
            self.assertEqual(self.ron(source_kind=k)["tolerated"],0)
    def test_multiple_links(self):
        r=self.ron(links=[L,L,dict(L,target=2,draw_event_id=1,same_target=0)])
        self.assertEqual(r["matching_origins"],[(2,3)])
        self.assertEqual(r["sage"],1)
    def test_historical_not_current(self):
        self.assertEqual(self.ron(s=self.s(5,(False,True)))["tolerated"],0)
    def test_closed_non_tenpai(self):
        for tenpai in (False,None):
            for ts in (False,True):
                self.assertEqual(self.ron(closed_tenpai_before=tenpai,tsumogiri=ts)["sage"],1)
    def test_accepted_non_tsumogiri_not_inferred(self):
        self.assertTrue(self.ron(accepted_before=True)["reason"].startswith("unresolved"))
if __name__=="__main__":unittest.main(verbosity=2)
