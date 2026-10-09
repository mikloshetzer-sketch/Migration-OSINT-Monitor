import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from validate_event_lifecycle import classify

class LifecycleTests(unittest.TestCase):
    def test_historical_case(self):
        e = classify({'title': 'Prosecutors closed investigation into 2025 drone incident', 'published_at': '2026-10-08T10:00:00Z', 'event_subtype': 'incident', 'hybrid_threat_score': 45})
        self.assertEqual(e['event_subtype'], 'assessment')
        self.assertEqual(e['hybrid_threat_score'], 0)
        self.assertEqual(e['original_hybrid_threat_score'], 45)
    def test_new_attack_not_suppressed(self):
        e = classify({'title': 'New drone incident in Latvia', 'published_at': '2026-10-08T10:00:00Z', 'event_subtype': 'incident', 'hybrid_threat_score': 45})
        self.assertEqual(e['event_subtype'], 'incident')
    def test_old_year_alone_requires_review(self):
        e = classify({'title': 'After 2025 warnings, new sabotage in Latvia', 'published_at': '2026-10-08T10:00:00Z', 'event_subtype': 'incident', 'hybrid_threat_score': 45})
        self.assertEqual(e['event_subtype'], 'incident')
        self.assertEqual(e['lifecycle_review']['status'], 'needs_review')

if __name__ == '__main__':
    unittest.main()
