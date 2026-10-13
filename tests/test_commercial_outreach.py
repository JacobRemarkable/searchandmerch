import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import commercial_outreach as o

CTX={
 'company':'Example Shop',
 'vertical':'Homeware and soft furnishings',
 'lead_with':'Merch',
 'primary_persona':'Head of Ecommerce',
 'commercial_hypothesis':'Collection ranking and variants',
 'research_source':'Research',
 'platform_status':'Unverified',
}

def entry(status='tested',name='Example Shop',screenshot='screenshots/proof.png'):
    return {'company':name,'website':'https://example.com','status':'tested',
     'query_results':[{'status':status,'query':'velvet sofa',
                      'product_cards_detected':8,'out_of_stock_cards':1,
                      'search_heading':'Velvet sofas','query_title_overlap':'8/8',
                      'sort_control':'visible','filter_control':'visible',
                      'search_url':'https://example.com/search?q=velvet+sofa',
                      'screenshot':screenshot,'products':[]}]}

class CommercialTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory()
        self.root=Path(self.t.name)
        (self.root/'screenshots').mkdir()
        (self.root/'screenshots'/'proof.png').write_bytes(b'fakepng')

    def tearDown(self):
        self.t.cleanup()

    def test_verified_signal_gated_behind_human_check(self):
        leads,stats=o.build_rows([entry()],{'example shop':CTX},self.root)
        self.assertEqual(len(leads),1)
        self.assertIn('P1',leads[0]['priority'])
        self.assertIn('Yes',leads[0]['verification_required'])
        self.assertIn('Merch',leads[0]['verified_observation'])
        self.assertNotIn('unavailable',leads[0]['linkedin_opener'].lower())
        self.assertEqual(stats[0]['included_in_sales_shortlist'],'Yes')

    def test_category_only_does_not_imply_search_issue(self):
        e=entry(status='category_observed')
        e['status']='category_only'
        leads,_=o.build_rows([e],{'example shop':CTX},self.root)
        self.assertEqual(len(leads),1)
        self.assertIn('P2',leads[0]['priority'])
        self.assertIn('Category screenshot',leads[0]['evidence_type'])
        self.assertNotIn('broken',leads[0]['linkedin_opener'])

    def test_blocked_excluded_even_when_metadata_exists(self):
        e={'company':'Example Shop','website':'https://example.com','status':'robots_blocked','query_results':[]}
        leads,stats=o.build_rows([e],{'example shop':CTX},self.root)
        self.assertEqual(leads,[])
        self.assertEqual(stats[0]['sales_status'],'Set aside')

    def test_missing_context_excluded(self):
        leads,stats=o.build_rows([entry()],{},self.root)
        self.assertEqual(leads,[])
        self.assertEqual(stats[0]['sales_status'],'Missing commercial context')

    def test_missing_or_unsafe_image_excluded(self):
        leads,stats=o.build_rows([entry(screenshot='../elsewhere.png')],{'example shop':CTX},self.root)
        self.assertEqual(leads,[])
        self.assertEqual(stats[0]['sales_status'],'Missing screenshot')

    def test_xss_and_formula_string_escaped(self):
        l,_=o.build_rows([entry()],{'example shop':CTX},self.root)
        l[0]['commercial_hypothesis']='<img src=x onerror=alert(1)>'
        l[0]['linkedin_opener']='=HYPERLINK("http://evil", "click")'
        o.render_html(l,[],self.root)
        t=(self.root/'sales_opportunities.html').read_text()
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;',t)
        self.assertNotIn('<img src=x onerror=alert(1)>',t)
        o.write_csv(self.root/'test.csv',l,o.SALES_FIELDS)
        with (self.root/'test.csv').open(encoding='utf-8-sig',newline='') as f:
            s=list(csv.DictReader(f))
        self.assertTrue(s[0]['linkedin_opener'].startswith("'="))

    def test_full_output(self):
        meta=self.root/'context.csv'
        with meta.open('w',encoding='utf-8',newline='') as f:
            w=csv.DictWriter(f,fieldnames=o.CONTEXT_FIELDS);w.writeheader();w.writerow(CTX)
        ev=self.root/'evidence.json';ev.write_text(json.dumps([entry()]),encoding='utf-8')
        self.assertEqual(o.main(['--input',str(ev),'--context',str(meta),'--out',str(self.root)]),0)
        self.assertTrue((self.root/'sales_opportunities.html').exists())
        self.assertTrue((self.root/'sales_ready_shortlist.csv').exists())
        self.assertTrue((self.root/'all_target_status.csv').exists())

    def test_input_list_and_metadata_aligned(self):
        base=Path(__file__).resolve().parents[1]
        with (base/'prospects.csv').open(encoding='utf-8') as file:
            rows=list(csv.DictReader(file))
        ctx=o.load_context(base/'prospect_context.csv')
        self.assertEqual(len(rows),20)
        self.assertEqual(len(ctx),20)
        self.assertEqual({r['company'].casefold() for r in rows},set(ctx.keys()))
        self.assertNotIn('Tufferman',{r['company'] for r in rows})
        self.assertNotIn('Early Years Resources',{r['company'] for r in rows})

if __name__=='__main__':
    unittest.main()
