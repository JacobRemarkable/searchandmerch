"""Offline, no external requests; account logic can be validated without Streamlit."""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from account_profiles import (safe_link,safe_local,grouped_stack,other_opportunities,build_profiles,
                              export,render_html)
from tech_stack import public_page_signals


class AccountProfileTests(unittest.TestCase):
    def test_public_copy_signals_positive_only(self):
        r=public_page_signals('Shop womenswear. Click & Collect. Find a store. Trade Accounts. Newsletter.', 'https://example.com')
        keys={x['key'] for x in r}
        self.assertEqual(keys,{'click_and_collect','store_locations','trade_or_b2b','newsletter'})
        self.assertTrue(all(x['url']=='https://example.com/' for x in r))

    def test_false_vendors_not_inferred(self):
        x=grouped_stack([{'provider':'Shopify','role':'Ecommerce','confidence':'High','evidence':'asset'},
                         {'provider':'Nosto','role':'Merch','confidence':'Indicative','evidence':'inline'}])
        self.assertEqual(x['Search'],[])
        self.assertEqual(x['Merch'][0]['name'],'Nosto')

    def test_multi_role_provider(self):
        x=grouped_stack([{'provider':'Klevu X','role':'Search & Merch','confidence':'High','evidence':'script'}])
        self.assertEqual(len(x['Search']),1)
        self.assertEqual(len(x['Merch']),1)

    def test_other_gaps_are_guarded(self):
        q={'query_results':[{'filter_labels':'Size | Colour'}]}
        signals=[{'key':'store_locations','label':'Stores'}, {'key':'promotions','label':'Promotions'}]
        o=other_opportunities(q,signals,{})
        self.assertEqual(len(o),2)
        self.assertEqual(o[0]['module'],'Omnichannel / OMS')
        self.assertEqual(o[1]['module'],'PIM')
        self.assertTrue(all(x['status']=='Explore, not confirmed' for x in o))
        self.assertEqual(other_opportunities({},[],{}),[])
        extra=other_opportunities({},[{'key':'editorial_content'},{'key':'complex_delivery'}],{})
        self.assertEqual([x['module'] for x in extra],['Content management / CMS','Fulfilment / WMS'])

    def test_evidence_links_drop_trackers(self):
        self.assertEqual(safe_link('https://example.com/search?q=sofas&_gl=tracking#frag'),
                         'https://example.com/search?q=sofas')
        self.assertEqual(safe_link('javascript:alert(1)'), '')

    def test_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); (p/'x.png').write_bytes(b'PNG')
            self.assertEqual(safe_local('x.png',p),'x.png')
            self.assertEqual(safe_local('../x.png',p),'')
            self.assertEqual(safe_local('/etc/passwd',p),'')

    def test_public_text_escaped(self):
        doc=render_html([{
            'company':'<img src=x onerror=alert(1)>', 'website':'https://example.com',
            'priority':'Discovery fit','category':'Homeware','persona':'Head of Ecommerce',
            'status':'tested','search':{'label':'Discovery opportunity','detail':'No gap proved'},
            'merch':{'label':'Discovery opportunity','detail':'No gap proved'},
            'other':[],'stack':{'Ecommerce':[],'Search':[],'Merch':[],'Other technology':[]},
            'signals':[],'page_title':'','page_description':'','screenshot':'','observed':'',
            'confidence':'No confirmed issue','tested_url':'','discovery_question':'Ask how?'
        }])
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;',doc)
        self.assertNotIn('<img src=x onerror=alert(1)>',doc)

    def test_end_to_end_full_profile(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);output=root/'results';output.mkdir()
            (root/'prospects.csv').write_text('company,website,query\nDemo,https://example.com,boots\n')
            (root/'prospect_context.csv').write_text('company,vertical,primary_persona,commercial_hypothesis\nDemo,Fashion,Head of Ecommerce,Explore relevance\n')
            (output/'screenshots').mkdir();(output/'screenshots'/'demo.png').write_bytes(b'png')
            evidence=[{'company':'Demo','website':'https://example.com','status':'tested',
                    'query_results':[{'status':'tested','query':'boots','product_cards_detected':10,
                                      'out_of_stock_cards':0,'query_title_overlap':'8/10',
                                      'sort_control':'visible','filter_control':'visible',
                                      'filter_labels':'Size','search_url':'https://example.com/search?q=boots',
                                      'screenshot':'screenshots/demo.png'}]}]
            (output/'evidence.json').write_text(json.dumps(evidence))
            (output/'tech_stack.json').write_text(json.dumps([{
                'company':'Demo','status':'scanned','page_title':'Demo Shoes','page_description':'Footwear',
                'technologies':[{'provider':'Shopify','role':'Ecommerce','confidence':'High','evidence':'Shopify CDN'}],
                'site_signals':[{'key':'click_and_collect','label':'Click & collect','proof':'Click & collect',
                                 'url':'https://example.com/'}]
            }]))
            profiles=export(root)
            self.assertEqual(len(profiles),1)
            self.assertEqual(profiles[0]['stack']['Ecommerce'][0]['name'],'Shopify')
            self.assertEqual(profiles[0]['screenshot'],'screenshots/demo.png')
            self.assertTrue(profiles[0]['other'])
            self.assertTrue((output/'account_profiles.html').exists())
            with (output/'account_profiles.csv').open(encoding='utf-8-sig') as report_file:
                rows=list(csv.DictReader(report_file))
            self.assertEqual(rows[0]['Company'],'Demo')

    def test_quick_mode_clear_not_tested(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); (p/'results').mkdir()
            (p/'prospects.csv').write_text('company,website\nDemo,https://example.com\n')
            prof=build_profiles(p)[0]
            self.assertEqual(prof['search']['label'],'Not tested')
            self.assertEqual(prof['merch']['label'],'Not tested')

if __name__=='__main__':
    unittest.main()
