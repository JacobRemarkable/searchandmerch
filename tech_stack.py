#!/usr/bin/env python3
"""Identify *visible* client-side ecommerce/search/merch technologies on public pages.

No hidden/paid signals; no internal APIs, credentials, subdomains, robots bypass or
fingerprinting beyond links/scripts/network requests exposed by a public storefront.
Detection is evidence-oriented, never a claim that a non-detected product is absent.
"""
import argparse
import csv
import html
import json
import re
import time
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright
from auditor import USER_AGENT, valid_website, robots_allows, detect_challenge


@dataclass(frozen=True)
class Provider:
    name: str
    role: str
    assets: tuple
    runtime: tuple = ()

# Asset patterns are deliberately specific. We do not look for company names in
# visible page copy: a retailer mentioning 'Shopify' in a blog is not evidence.
PROVIDERS = [
    Provider('Shopify', 'Ecommerce', (r'cdn\.shopify\.com/', r'\.myshopify\.com/', r'/cdn/shop/'),
             (r'window\.Shopify\s*=', r'Shopify\.theme', r'ShopifyAnalytics')),
    Provider('Adobe Commerce / Magento', 'Ecommerce',
             (r'/static/(?:version\d+/)?frontend/', r'/mage/', r'/Magento_[A-Za-z]+/', r'/static/frontend/'),
             (r'\bMagento_Ui\b', r'\bmage/cookies\b', r'\bMagento_Catalog\b')),
    Provider('WooCommerce', 'Ecommerce',
             (r'/wp-content/plugins/woocommerce/', r'[?&]wc-ajax=', r'/wc/store/v1/'),
             (r'\bwc_add_to_cart_params\b', r'\bwoocommerce_params\b')),
    Provider('BigCommerce', 'Ecommerce', (r'cdn\d*\.bigcommerce\.com/', r'/stencil-utils(?:\.|/)', r'/stencil/'),
             (r'\bwindow\.BCData\b',)),
    Provider('Salesforce Commerce Cloud', 'Ecommerce',
             (r'demandware\.static', r'/on/demandware\.store/', r'demandware\.net/'),
             (r'\bdwfrm_',)),
    Provider('Shopware', 'Ecommerce', (r'/bundles/storefront/', r'/bundles/shopware/', r'/storefront/js/'),
             (r'\bShopware\.Storefront\b',)),
    Provider('Wix', 'Website platform', (r'static\.wixstatic\.com/', r'parastorage\.com/'),
             (r'\bwindow\.wixBiSession\b',)),
    Provider('Squarespace', 'Website platform', (r'static1\.squarespace\.com/', r'assets\.squarespace\.com/'),
             (r'\bStatic\.SQUARESPACE_CONTEXT\b',)),
    Provider('Algolia', 'Search', (r'algolia\.net/', r'algolianet\.com/', r'algoliasearch(?:\.|/)',
                                  r'cdn\.jsdelivr\.net/npm/instantsearch\.js'),
             (r'\b(?:algoliasearch|instantsearch)\s*\(',)),
    Provider('Klevu', 'Search', (r'js\.klevu\.com/', r'cdn\.klevu\.com/', r'api\.klevu\.com/'),
             (r'\bklevu\.search\b', r'\bwindow\.klevu\b')),
    Provider('Doofinder', 'Search', (r'(?:cdn|api|eu1|us1)\.doofinder\.com/', r'/doofinder(?:\.|/)'),
             (r'\bdoofinder\s*\(',)),
    Provider('Searchspring', 'Search & Merch',
             (r'(?:api|cdn)\.searchspring\.(?:net|io)/', r'/searchspring(?:\.|/)'),
             (r'\bSearchspring\.\w+',)),
    Provider('Constructor', 'Search & Merch',
             (r'ac\.cnstrc\.com/', r'cdn\.constructor\.io/', r'constructorio\.com/'),
             (r'\bConstructorIO\b',)),
    Provider('Bloomreach Discovery', 'Search & Merch',
             (r'discovery\.bloomreach\.com/', r'cdn\.brcdn\.com/', r'/bloomreach-discovery/'),
             (r'\bbrTrk\.getTracker\b',)),
    Provider('Nosto', 'Merch', (r'connect\.nosto\.com/', r'\bnosto\.com/[a-z]', r'api\.nosto\.com/'),
             (r'\bnostojs\s*\(',)),
    Provider('Dynamic Yield', 'Merch',
             (r'cdn\.dynamicyield\.com/', r'async-px\.dynamicyield\.com/'),
             (r'\bDY\.API\b',)),
    Provider('Clerk.io', 'Search & Merch', (r'cdn\.clerk\.io/', r'api\.clerk\.io/'),
             (r'\bClerk\s*\(',)),
    Provider('Boost Commerce', 'Search & Merch',
             (r'boostcommerce\.net/', r'boost-pfs-filter', r'boost-ai-search'),
             (r'\bboostPFSFilter\b',)),
    Provider('Searchanise', 'Search', (r'searchanise\.com/', r'searchanise\.io/'),
             (r'\bSearchanise\b',)),
    Provider('Luigi’s Box', 'Search & Merch', (r'luigisbox\.com/', r'luigisbox\.io/'),
             (r'\bLuigis\.Autocomplete\b',)),
    Provider('Voyado / Apptus', 'Search & Merch',
             (r'api\.apptus\.com/', r'\bvoyado\.com/engage/', r'\bvoyado\.com/elevate/'),
             (r'\bApptus\.Esales\b',)),
    Provider('Kimonix', 'Merch', (r'kimonix\.com/', r'kimonix\.io/')),
    Provider('Depict', 'Merch', (r'api\.depict\.ai/', r'cdn\.depict\.ai/')),
]


# First-party, visible copy only. These are buying-context signals, NOT deficiencies.
PUBLIC_SIGNALS = (
    ('click_and_collect', 'Click & collect', r'\bclick\s*(?:and|&)\s*collect\b|\bcollect in store\b'),
    ('store_locations', 'Store locations', r'\bstore locator\b|\bfind (?:a|your) store\b|\bour stores\b'),
    ('trade_or_b2b', 'Trade or wholesale', r'\btrade accounts?\b|\bwholesale\b|\btrade customer\b|\bbusiness accounts?\b'),
    ('promotions', 'Promotions', r'\b(?:sale|discounts|offers|clearance)\b'),
    ('delivery', 'Delivery information', r'\b(?:delivery|shipping)\b'),
    ('returns', 'Returns information', r'\b(?:returns|refunds)\b'),
    ('loyalty', 'Loyalty / rewards', r'\b(?:loyalty|rewards) (?:programme|program|points|club)\b'),
    ('finance', 'Payment instalments', r'\b(?:klarna|clearpay|pay in 3|pay in 4)\b'),
    ('newsletter', 'Email newsletter', r'\bnewsletter\b'),
    ('editorial_content', 'Editorial content', r'\b(?:our journal|our blog|style guide|buying guide|inspiration)\b'),
    ('complex_delivery', 'Complex delivery wording', r'\b(?:deliver from store|dispatch from store|international delivery|worldwide shipping|order in store)\b'),
)


def public_page_signals(visible_text, url):
    text = (visible_text or '')[:24000]
    items=[]
    for key,label,pattern in PUBLIC_SIGNALS:
        match = re.search(pattern,text,re.IGNORECASE)
        if match:
            # Use a precise matched term only; avoid storing unrelated personal data.
            items.append({'key':key, 'label':label,
                          'proof':match.group(0)[:65], 'url':evidence_url(url)})
    return items[:11]


class ResourceParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []
        self.generators = []
        self.script_text = []
        self.in_script = False

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if tag in ('script', 'link', 'img'):
            value = data.get('src') or data.get('href')
            if value:
                self.urls.append(value)
        if tag == 'meta' and data.get('name', '').lower() == 'generator':
            self.generators.append(data.get('content', ''))
        if tag == 'script':
            self.in_script = not bool(data.get('src'))

    def handle_endtag(self, tag):
        if tag == 'script':
            self.in_script = False

    def handle_data(self, data):
        if self.in_script and len(''.join(self.script_text)) < 100000:
            self.script_text.append(data[:20000])


def evidence_url(value):
    """Strip query strings (which can contain identifiers or tokens) before export."""
    if not value:
        return ''
    parsed = urlparse(value)
    if parsed.scheme not in ('http', 'https'):
        return value[:120].split('?')[0]
    return (f'{parsed.scheme}://{parsed.hostname or ""}{parsed.path or "/"}')[:200]


def identify(html_source, requested_urls=()):
    p = ResourceParser()
    p.feed((html_source or '')[:450000])
    asset_sources = list(dict.fromkeys([*requested_urls, *p.urls]))
    script_text = '\n'.join(p.script_text)[:100000]
    found = []
    for prov in PROVIDERS:
        direct = []
        for raw in asset_sources[:1000]:
            url = raw.lower()
            if any(re.search(pat, url, re.I) for pat in prov.assets):
                target = evidence_url(raw)
                if target and target not in direct:
                    direct.append(target)
                if len(direct) >= 2:
                    break
        runtime = [pat for pat in prov.runtime if re.search(pat, script_text, re.I)]
        if direct or runtime:
            confidence = 'High' if direct else 'Indicative'
            notes = [f'Loaded asset: {x}' for x in direct]
            if runtime and not direct:
                notes.append('Recognisable inline storefront configuration')
            found.append({'provider':prov.name, 'role':prov.role, 'confidence':confidence,
                          'evidence':' | '.join(notes)[:500]})
    # Meta generator supports a vendor claim, but may be absent or inaccurate.
    for generator in p.generators:
        for name, role in [('Shopify','Ecommerce'), ('WooCommerce','Ecommerce'),
                           ('Magento','Ecommerce'), ('BigCommerce','Ecommerce'),
                           ('Shopware','Ecommerce')]:
            if name.casefold() in generator.casefold() and not any(x['provider'].startswith(name) for x in found):
                found.append({'provider':('Adobe Commerce / Magento' if name=='Magento' else name),
                              'role':role,'confidence':'Indicative',
                              'evidence':f'Meta generator: {generator[:90]}'})
    return found


def scan_site(browser, name, website, robots_cache):
    data={'company':name,'website':website,'status':'unscanned','technologies':[],
          'checked_utc':datetime.now(timezone.utc).isoformat(timespec='seconds'), 'notes':'',
          'site_signals':[], 'page_title':'', 'page_description':''}
    try:
        website=valid_website(website)
        data['website']=website
        allowed, note=robots_allows(website,robots_cache)
        if not allowed:
            data['status']='robots_blocked'
            data['notes']='Homepage disallowed by robots.txt; no scan performed.'
            return data
        ctx=browser.new_context(user_agent=USER_AGENT, service_workers='block', viewport={'width':1280,'height':800})
        page=ctx.new_page()
        urls=[]
        page.on('request', lambda r: urls.append(r.url) if len(urls)<1300 else None)
        try:
            response=page.goto(website,wait_until='domcontentloaded',timeout=18000)
            if response and response.status in (401,403,429):
                data['status']='access_blocked';data['notes']='Access restrictions; no result inferred.';return data
            page.wait_for_timeout(1100)
            if not robots_allows(page.url,robots_cache)[0]:
                data['status']='robots_blocked';data['notes']='Redirected to a disallowed page.';return data
            detect_challenge(page)
            technology=identify(page.content(),urls)
            data['technologies']=technology
            try:
                data['page_title']=(page.title() or '')[:140]
                description=page.locator('meta[name="description"]').first.get_attribute('content',timeout=1500)
                data['page_description']=(description or '')[:260]
            except Exception:
                pass
            try:
                visible=page.locator('body').inner_text(timeout=3000)
                data['site_signals']=public_page_signals(visible, page.url)
            except Exception:
                pass
            data['status']='scanned'
            data['notes']=('No recognisable public signals; stack unknown.' if not technology
                           else 'Detected from publicly loaded resources and/or page configuration.')
        finally:
            ctx.close()
    except Exception as e:
        data['status']='inconclusive'
        data['notes']=f'Unable to confirm visible technologies ({type(e).__name__}).'
    return data


def run(input_path, output_path, max_sites=30):
    with open(input_path, encoding='utf-8-sig',newline='') as f:
        rows=list(csv.DictReader(f))
    output_path=Path(output_path);output_path.parent.mkdir(parents=True,exist_ok=True)
    results=[];cache={}
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,args=['--disable-dev-shm-usage'])
        try:
            for i,row in enumerate(rows[:min(max_sites,30)],1):
                name=(row.get('company') or '').strip()
                website=(row.get('website') or '').strip()
                if not name or not website:continue
                print(f'[Tech {i}/{min(len(rows),max_sites,30)}] {name}',flush=True)
                result=scan_site(browser,name,website,cache)
                results.append(result)
                print('   ',result['status'],', '.join(x['provider'] for x in result['technologies']) or 'Not detected',flush=True)
                time.sleep(0.3)
        finally:
            browser.close()
    output_path.write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding='utf-8')
    fieldnames=['company','website','status','ecommerce','site_builder','search','merch','confidence','evidence','notes']
    with output_path.with_name('tech_stack.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=fieldnames);writer.writeheader()
        for item in results:
            tech=item['technologies']
            roles={
                'ecommerce':[t['provider'] for t in tech if t['role']=='Ecommerce'],
                'site_builder':[t['provider'] for t in tech if t['role']=='Website platform'],
                'search':[t['provider'] for t in tech if 'Search' in t['role']],
                'merch':[t['provider'] for t in tech if 'Merch' in t['role']],
            }
            evidence='; '.join(t['provider']+': '+t['evidence'] for t in tech)
            def clean(x):
                s=str(x or '')
                return "'"+s if s.lstrip().startswith(('=','+','-','@')) else s
            writer.writerow({k:clean(v) for k,v in {
                'company':item['company'],'website':item['website'],'status':item['status'],
                'ecommerce':' | '.join(roles['ecommerce']) or 'Not detected',
                'site_builder':' | '.join(roles['site_builder']) or 'Not detected',
                'search':' | '.join(roles['search']) or 'Not detected',
                'merch':' | '.join(roles['merch']) or 'Not detected',
                'confidence':' | '.join(sorted(set(t['confidence'] for t in tech))) or 'Unknown',
                'evidence':evidence[:1000], 'notes':item['notes']}.items()})
    return results

if __name__=='__main__':
    cli=argparse.ArgumentParser()
    cli.add_argument('--input',default='prospects.csv')
    cli.add_argument('--out',default='results/tech_stack.json')
    cli.add_argument('--max-sites',type=int,default=30)
    a=cli.parse_args()
    run(a.input,a.out,a.max_sites)
