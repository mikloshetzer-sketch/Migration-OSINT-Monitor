import unittest
from analysis.historical_dashboard_cleanup import clean, layer_key, load_manifest
from pathlib import Path
class CleanupTests(unittest.TestCase):
    def test_timeline_key(self):
        self.assertEqual(layer_key({'timeline_id':'early_warning:1035'}),('influence_signal',1035))
        self.assertEqual(layer_key({'timeline_id':'operational:630'}),('post',630))
    def test_filter_and_recount(self):
        data={'live_events':[{'id':630},{'id':1}], 'event_groups':[{'id':2},{'id':3}], 'influence_signals':[{'id':1035},{'id':10}], 'signal_timeline':{'items':[{'timeline_id':'operational:630','layer':'OPERATIONAL','source':'X','type':'DEPORTATION'},{'timeline_id':'early_warning:1035','layer':'EARLY_WARNING','source':'X','type':'MOBILIZATION_COORDINATION'},{'timeline_id':'operational:1','layer':'OPERATIONAL','source':'X','type':'RESCUE'}]}, 'operational_assessment':{'activity_level':'HIGH'}}
        out,_=clean(data,{'post':{630},'influence_signal':{1035}},{2})
        self.assertEqual(len(out['live_events']),1)
        self.assertEqual(len(out['event_groups']),1)
        self.assertEqual(out['signal_timeline']['total_items'],1)
        self.assertEqual(out['signal_timeline']['operational_count'],1)
        self.assertEqual(out['operational_assessment']['historical_review_status'],'PROVISIONAL_UNRECALCULATED')
    def test_manifest(self):
        p=Path(__file__).resolve().parents[1]/'analysis'/'historical_suppression_manifest.json'
        self.assertEqual(len(load_manifest(p)['post']),5)
if __name__=='__main__':unittest.main()
