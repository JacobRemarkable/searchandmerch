"""Offline integration tests for audited result interpretation and rendering.

The execution environment may block all browser navigation, so we use set_content
instead of simulated HTTP. The production GitHub workflow performs real navigation.
"""
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest import mock
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import auditor
from playwright.sync_api import sync_playwright

SEARCH_PAGE = '''<html><head><title>Test Shop</title></head><body>
<h1>Search results</h1><select name="sort" id="sort"><option value="relevance">Relevance</option><option value="price-asc">Price low to high</option></select>
<button aria-label="Filter products">Filter</button>
<div class="product-card"><a href="https://example.com/product/1"><h3>Garage shelving system</h3></a><span>£99</span></div>
<div class="product-card"><a href="https://example.com/product/2"><h3>Shelving brackets</h3></a><span>£12</span><b>Sold out</b></div>
</body></html>'''
ZERO_PAGE = '<html><head><title>Test Shop</title></head><body><h2>No products found</h2></body></html>'
HOME_PAGE = '<html><head><title>Test Shop</title></head><body><form><input type="search" name="q"></form></body></html>'

class AuditTests(unittest.TestCase):
    def test_public_url_validation(self):
        self.assertRaises(ValueError, auditor.valid_website, 'http://127.0.0.1')
        self.assertRaises(ValueError, auditor.valid_website, 'http://10.0.0.5')
        self.assertEqual(auditor.valid_website('www.sophieallport.com'), 'https://www.sophieallport.com')

    def test_browser_audit_and_report(self):
        def fake_load(page, *args, **kwargs):
            page.set_content(HOME_PAGE)
            return 'local fixture'
        def fake_search(page, query, *args):
            page.set_content(ZERO_PAGE if query.startswith('zzzxq') else SEARCH_PAGE)
            return ('form_submission', 'https://example.com/search?q='+query, 'Yes')
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out/'screenshots').mkdir()
            row = {'company':'Example retailer', 'website':'https://example.com', 'query':'garage shelving', 'search_url_template':''}
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True, **({'executable_path':shutil.which('chromium')} if shutil.which('chromium') else {}))
                with mock.patch.object(auditor, 'load_public', side_effect=fake_load), mock.patch.object(auditor, 'do_search', side_effect=fake_search):
                    audit = auditor.test_site(browser, row, out, {}, 0.01)
                browser.close()
            self.assertEqual(audit.status,'tested', audit.notes)
            self.assertEqual(audit.product_cards_detected,2)
            self.assertEqual(audit.out_of_stock_cards,1)
            self.assertEqual(audit.zero_results_state,'clear_message_detected')
            self.assertEqual(audit.filter_control,'visible')
            self.assertTrue((out/audit.screenshot).is_file())
            auditor.html_report([audit], out/'report.html')
            self.assertIn('Garage shelving',(out/'report.html').read_text())

if __name__=='__main__':
    unittest.main()
