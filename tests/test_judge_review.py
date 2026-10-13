import importlib.util
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location('judge_review',Path(__file__).resolve().parents[1]/'scripts/review_contract_v2_judge.py')
review=importlib.util.module_from_spec(spec);spec.loader.exec_module(review)

class JudgeEvidenceTests(unittest.TestCase):
    def test_exact_short_values_and_original_unicode(self):
        sources={'status':{'text':'409'},'empty':{'text':'[]'},'body':{'text':'称呼用户为“老师”。'}}
        evidence=[{'source_id':s,'quote':v['text']} for s,v in sources.items()]
        self.assertTrue(review.citations_valid({'evidence':evidence},sources))
        self.assertFalse(review.citations_valid({'evidence':[{'source_id':'body','quote':'老师'}]},sources))
        self.assertFalse(review.citations_valid({'evidence':[{'source_id':'body','quote':'称呼用户为老师。'}]},sources))
    def test_empty_state_and_json_pointer_provenance_are_retained(self):
        self.assertEqual(dict(review.leaves({'items':[],'http_status':403,'a/b':{}})),{'/items':'[]','/http_status':'403','/a~1b':'{}'})
    def test_wrong_record_or_unmatched_quote_fails(self):
        self.assertFalse(review.citations_valid({'evidence':[{'source_id':'missing','quote':'409'}]},{}))
        self.assertFalse(review.citations_valid({'evidence':[]},{}))
