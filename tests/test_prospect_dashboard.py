"""Confidence and evidence guardrails for the prospecting dashboard."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import prospect_dashboard as d


def sample(name='Example Shop', query='work boots', cards=12, hits=10, oos=0, status='tested', screenshot='screenshots/example.png'):
    return {'company': name, 'website': 'https://example.com', 'status': status,
            'query_results': [{'query': query, 'status': 'tested' if status == 'tested' else 'inconclusive',
                'product_cards_detected': cards if status == 'tested' else 0,
                'out_of_stock_cards': oos, 'query_title_overlap': f'{hits}/{cards} sampled titles contain a query term',
                'filter_control': 'visible', 'sort_control': 'visible', 'search_url': 'https://example.com/search?q=boots',
                'screenshot': screenshot, 'products': [{'name': 'Work boots', 'price': '£20', 'sold_out_badge': False}]}]}


class ProspectDashboardTests(unittest.TestCase):
    def test_stock_signal_never_claims_lost_revenue(self):
        p=d.analyse(sample(oos=3))
        self.assertEqual(p.bucket,'Review first')
        self.assertIn('3 of 12',p.evidence)
        self.assertIn('unproven',p.confidence)

    def test_low_title_overlap_is_review_signal_only(self):
        p=d.analyse(sample(hits=3))
        self.assertEqual(p.bucket,'Review first')
        self.assertIn('Only 3/12',p.evidence)
        self.assertNotIn('broken',p.evidence.casefold())

    def test_visible_internal_search_syntax_is_review_only(self):
        data = sample(hits=12)
        data['query_results'][0]['search_heading'] = '1002 results for scooter wheels -tag:"hide from search"'
        p = d.analyse(data)
        self.assertEqual(p.bucket,'Review first')
        self.assertIn('technical filter syntax',p.evidence)
        self.assertIn('intentional',p.suggested_question)

    def test_one_word_query_low_overlap_not_conclusive(self):
        p=d.analyse(sample(query='shoes',hits=0))
        self.assertEqual(p.bucket,'Discovery fit')

    def test_visible_filters_do_not_signal_failure(self):
        p=d.analyse(sample())
        self.assertEqual(p.bucket,'Discovery fit')
        self.assertIn('no identified defect',p.confidence)

    def test_blocked_returns_manual(self):
        p=d.analyse(sample(status='robots_blocked',screenshot=''))
        self.assertEqual(p.bucket,'Manual review')
        self.assertIn('respect',p.evidence)
        self.assertFalse(p.screenshot)

    def test_unrecognised_search_homepage_not_product_evidence(self):
        p=d.analyse(sample(status='inconclusive',screenshot='screenshots/homepage.png'))
        self.assertEqual(p.bucket,'Manual review')
        self.assertIn('not product-search evidence',p.evidence)

    def test_report_safe_escaped_and_screenshot_guard(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/'screenshots').mkdir()
            (root/'screenshots'/'example.png').write_bytes(b'fakeimage')
            r=d.analyse(sample(name='<script>alert(1)</script>'))
            d.render([r],root/'opportunity_dashboard.html')
            body=(root/'opportunity_dashboard.html').read_text()
            self.assertIn('&lt;script&gt;',body)
            self.assertNotIn('<script>alert(1)</script>',body)
            self.assertIn('src="screenshots/example.png"',body)
            r.screenshot='../private.png'
            d.render([r],root/'unsafe.html')
            self.assertNotIn('src="../private.png"',(root/'unsafe.html').read_text())

    def test_end_to_end_csv_and_html(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            source=root/'evidence.json'
            source.write_text(json.dumps([sample(),sample(name='Blocked',status='robots_blocked')]))
            self.assertEqual(d.main(['--input',str(source),'--out',str(root)]),0)
            self.assertTrue((root/'opportunity_shortlist.csv').exists())
            self.assertTrue((root/'opportunity_dashboard.html').exists())
            self.assertIn('Blocked',(root/'opportunity_shortlist.csv').read_text(encoding='utf-8-sig'))


if __name__=='__main__':
    unittest.main()
