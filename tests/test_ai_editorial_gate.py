import unittest
from analysis.ai_editorial_gate import collect, review_entries, apply, fingerprint

class GateV2Tests(unittest.TestCase):
    def test_information_does_not_consume_calls(self):
        d={'signal_timeline':{'items':[{'timeline_id':f'information:{i}','layer':'INFORMATION','text':'general'} for i in range(1700)]}}
        self.assertEqual(collect(d),{})
        apply(d,{})
        self.assertEqual(len(d['signal_timeline']['items']),1700)
    def test_conflicting_group_id_cannot_pass(self):
        d={'event_groups':[{'id':243,'text':'Five migrants die at sea'}],
           'signal_timeline':{'items':[{'timeline_id':'correlated:243','text':'Historic migration to America','layer':'CORRELATED'}]}}
        decisions,calls,conflicts=review_entries(collect(d),{},offline=True)
        self.assertIn('group:243',conflicts)
        self.assertEqual(calls,0)
        apply(d,decisions)
        self.assertEqual(d['event_groups'],[])
        self.assertEqual(d['signal_timeline']['correlated_count'],0)
    def test_high_priority_group_id(self):
        d={'high_priority_intelligence':[{'id':474,'group_id':474,'text':'Ceuta text'}]}
        self.assertIn('group:474',collect(d))
    def test_approval_and_signal_warning(self):
        d={'live_events':[{'id':2,'text':'Rescue at sea'}],
           'early_warning_signals':[{'id':5,'text':'Border closure planned'}]}
        approved={'post:2':{'decision':'PUBLISH'},'signal:5':{'decision':'PUBLISH'}}
        apply(d,approved)
        self.assertEqual(len(d['live_events']),1)
        self.assertEqual(len(d['early_warning_signals']),1)
    def test_pending_fails_closed(self):
        d={'live_events':[{'id':1,'text':'If deported'}]}
        apply(d,{})
        self.assertEqual(d['live_events'],[])
    def test_v2_fingerprint(self):
        a={'id':1,'text':'A'}
        self.assertNotEqual(fingerprint('post',a)[0],fingerprint('post',{'id':1,'text':'B'})[0])

if __name__=='__main__': unittest.main()
