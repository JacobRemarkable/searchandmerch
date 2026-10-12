"""Locally rendered browser fixture tests: no external network or site access."""
import sys
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import auditor
from playwright.sync_api import sync_playwright

MODAL = '''<html><body><div role="dialog"><h3>ARE YOU IN THE RIGHT PLACE?</h3><button onclick="document.querySelector('[role=dialog]').remove()">UK</button><button>US</button></div><main><h1>Search for neodymium magnets</h1><div class="product-item"><a href="/products/magnet-a"><h3>Strong magnets</h3></a><span>£9</span></div></main></body></html>'''
CONSENT = '''<html><body><div class="cookie-banner"><p>Cookies / consent choices</p><button id="accept" onclick="document.body.dataset.accepted='yes'">Accept all</button><button onclick="this.parentNode.remove()">Reject all</button></div><main></main></body></html>'''
ICON = '''<html><body><header><button class="search-icon" onclick="document.getElementById('find').style.display='block'"><svg class="search-icon"></svg></button><form><input id="find" type="search" style="display:none" name="q"></form></header></body></html>'''
CUSTOM = '''<html><head><base href="https://example.com/"></head><body><main><h1>Search for wheels</h1><div class="toolbar"><button>Sort By</button><button>Availability</button><button>Colour</button><button>Price</button></div><div class="product-grid"><div class="tile"><a href="/products/wheel-1"><img alt="Scooter wheel" src="x"><span>LED wheels for scooters</span></a><p>£24.95</p></div><div class="tile"><a href="/products/wheel-2"><img alt="Scooter wheel" src="x"><span>Replacement wheel</span></a><p>£12.95</p><b>Sold out</b></div></div></main></body></html>'''

class V2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.play = sync_playwright().start()
        cls.browser = cls.play.chromium.launch(headless=True, **({'executable_path':shutil.which('chromium')} if shutil.which('chromium') else {}))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.play.stop()

    def test_location_overlay(self):
        page = self.browser.new_page()
        page.set_content(MODAL)
        self.assertEqual(auditor.dismiss_overlays(page), 'location: selected UK')
        self.assertEqual(page.locator('[role=dialog]').count(),0)
        self.assertEqual(len(auditor.extract_products(page)),1)
        page.close()

    def test_no_marketing_consent(self):
        page=self.browser.new_page()
        page.set_content(CONSENT)
        self.assertEqual(auditor.dismiss_overlays(page),'consent: rejected optional')
        self.assertIsNone(page.locator('body').get_attribute('data-accepted'))
        page.close()

    def test_hidden_search_and_icon(self):
        page=self.browser.new_page()
        page.set_content(ICON)
        control=auditor.find_search(page)
        self.assertIsNotNone(control)
        self.assertTrue(control.is_visible())
        page.close()

    def test_custom_filters_sort_and_fallback_products(self):
        page=self.browser.new_page()
        page.set_content(CUSTOM)
        products=auditor.extract_products(page)
        self.assertEqual(len(products),2,products)
        self.assertEqual(sum(x['sold_out_badge'] for x in products),1)
        self.assertEqual(auditor.detect_sort(page)[0],'visible_custom')
        self.assertEqual(auditor.detect_filters(page)[0],'visible')
        self.assertIn('Availability',auditor.detect_filters(page)[1])
        page.close()

    def test_three_queries_and_guarded_priority(self):
        row={'company':'Sample','website':'https://example.com',
             'query':'wheels','queries':'garage shelving|outdoor chairs|fourth query'}
        self.assertEqual(len(auditor.split_queries(row)),3)
        def fake_load(page, *args, **kwargs):
            page.set_content('<html><body><form><input type="search"></form></body></html>')
            return 'fixture'
        def fake_search(page, query, *args, **kwargs):
            if query=='zzzxqrareproduct':
                page.set_content('<main><h1>No products found</h1></main>')
            else:
                page.set_content('<main><div class="product-card"><a href="https://example.com/products/1"><h3>Random lamp</h3></a><span>£20</span><span>Sold out</span></div></main>')
            return 'form_submission','https://example.com/search?q='+query,'Yes'
        with tempfile.TemporaryDirectory() as d:
            out=Path(d);(out/'screenshots').mkdir()
            with mock.patch.object(auditor,'load_public',side_effect=fake_load), mock.patch.object(auditor,'do_search',side_effect=fake_search):
                result=auditor.test_site(self.browser,row,out,{},0.01)
            self.assertEqual(result.status,'tested',result.notes)
            self.assertEqual(result.queries_tested,3)
            self.assertEqual(result.review_priority,'P1')
            self.assertEqual(len(result.query_results),3)
            auditor.html_report([result],out/'report.html')
            self.assertIn('Review signals (P1/P2)',(out/'report.html').read_text())
            self.assertTrue((out/'screenshots/sample-query-2.png').exists())

    def test_robots_denial_remains_hard_stop(self):
        row={'company':'Disallowed','website':'https://example.com', 'query':'wheels','queries':'more'}
        def fake_load(page, *args, **kwargs):
            page.set_content('<form action="https://example.com/search"><input type="search"></form>')
            return 'fixture'
        def deny(url, cache):
            return (not url.endswith('/search'),'blocked')
        with tempfile.TemporaryDirectory() as d:
            out=Path(d);(out/'screenshots').mkdir()
            with mock.patch.object(auditor,'load_public',side_effect=fake_load), mock.patch.object(auditor,'robots_allows',side_effect=deny):
                result=auditor.test_site(self.browser,row,out,{},0.01)
            self.assertEqual(result.status,'robots_blocked')
            self.assertEqual(result.review_priority,'Unrated')
            self.assertEqual(len(result.query_results),1)

if __name__=='__main__':
    unittest.main()
