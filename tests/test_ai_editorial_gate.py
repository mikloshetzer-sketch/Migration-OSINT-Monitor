import unittest
from analysis.ai_editorial_gate import apply,collect,fingerprint
class TestGate(unittest.TestCase):
 def test_no_decision_no_publication(self):
  d={'live_events':[{'id':1,'text':'If she is deported'}],'signal_timeline':{'items':[{'timeline_id':'operational:1','layer':'OPERATIONAL'}]}}
  apply(d,{})
  self.assertEqual(d['live_events'],[])
  self.assertEqual(d['signal_timeline']['operational_count'],0)
 def test_approved_visible(self):
  d={'live_events':[{'id':2,'text':'Rescue reported'}]}
  apply(d,{'post:2':{'decision':'PUBLISH'}})
  self.assertEqual(len(d['live_events']),1)
 def test_cache_hash_changes_with_text(self):
  a=fingerprint('post',{'id':1,'text':'one'})[0]
  b=fingerprint('post',{'id':1,'text':'two'})[0]
  self.assertNotEqual(a,b)
if __name__=='__main__':unittest.main()
