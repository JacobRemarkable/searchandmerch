"""Version 4 public-category fallback and visual search-icon tests (offline)."""
import sys
import shutil
import unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import auditor
import prospect_dashboard
from playwright.sync_api import sync_playwright

MAGNIFIER = '''<html><body><header>
<button id="magnifier" onclick="document.getElementById('search').style.display='block'">
<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"></circle><line x1="17" y1="17" x2="22" y2="22"></line></svg></button>
<input id="search" name="q" type="search" style="display:none"></header></body></html>'''
CATEGORY_HOME = '''<html><body><header><a href="/collections/mugs">Shop mugs</a></header><main></main></body></html>'''
CATEGORY_PAGE = '''<html><body><main><h1>Mugs</h1><button>Sort By</button><button>Price</button>
<div class="product-card"><a href="/products/mug1">Hedgehog mug</a><span>£15</span></div>
<div class="product-card"><a href="/products/mug2">Robin mug</a><span>£12</span></div>
</main></body></html>'''

class V4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.play=sync_playwright().start()
        cls.browser=cls.play.chromium.launch(headless=True, **({'executable_path':shutil.which('chromium')} if shutil.which('chromium') else {}))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.play.stop()

    def test_unlabelled_magnifying_glass_opens_search(self):
        page=self.browser.new_page()
        page.set_content(MAGNIFIER)
        field=auditor.find_search(page)
        self.assertIsNotNone(field)
        self.assertTrue(field.is_visible())
        page.close()

    def test_category_fallback_uses_permitted_public_page(self):
        page=self.browser.new_page()
        page.goto('about:blank')
        page.set_content(CATEGORY_HOME)
        # Need absolute base URL for urljoin so add an explicit base tag.
        page.evaluate("document.head.innerHTML='<base href=\"https://example.com/\">'")
        def fake_load(page,url,cache,pause):
            self.assertEqual(url,'https://example.com/collections/mugs')
            page.set_content(CATEGORY_PAGE)
            return 'fixture'
        with mock.patch.object(auditor,'robots_allows',return_value=(True,'fixture')),mock.patch.object(auditor,'load_public',side_effect=fake_load):
            found=auditor.find_public_category(page,'https://example.com',{},0)
        self.assertIsNotNone(found)
        self.assertEqual(len(found['products']),2)
        self.assertEqual(found['sort_control'],'visible_custom')
        page.close()

    def test_category_evidence_is_discovery_not_search_defect(self):
        a={'company':'Sample','website':'https://example.com','status':'category_only',
            'query_results':[{'status':'category_observed','query':'mugs','product_cards_detected':2,
                              'sort_control':'visible_custom','filter_control':'visible',
                              'search_url':'https://example.com/collections/mugs',
                              'screenshot':'screenshots/sample-category.png'}]}
        p=prospect_dashboard.analyse(a)
        self.assertEqual(p.bucket,'Discovery fit')
        self.assertIn('not search testing',p.evidence.lower())
        self.assertNotIn('broken',p.evidence.lower())

    def test_blocked_site_does_not_require_manual_queue(self):
        p=prospect_dashboard.analyse({'company':'Blocked','website':'https://example.com',
             'status':'robots_blocked','query_results':[]})
        self.assertEqual(p.bucket,'Not assessable')
        self.assertIn('Do not assign a manual test',p.manual_next_step)

if __name__=='__main__': unittest.main()
