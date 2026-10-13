#!/usr/bin/env python3
"""Account-by-account prospect intelligence from *existing* permitted public evidence.

Makes no network requests.  This is not a technology fingerprinting or lead-scoring
truth engine: 'opportunity' text is always a discovery hypothesis; labels are explicit.
"""
import argparse
import csv
import html
import json
import re
from pathlib import Path
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

from dashboard_core import read_csv
from prospect_dashboard import analyse

PORTFOLIO = {
    'PIM': 'https://remarkable.net/commerce-platform/product-management-module/',
    'Promotions & campaigns': 'https://remarkable.net/',
    'Omnichannel / OMS': 'https://remarkable.net/commerce-platform/omnichannel-module/',
    'Content management / CMS': 'https://remarkable.net/',
    'Fulfilment / WMS': 'https://remarkable.net/',
}


def clean(value, length=350):
    return re.sub(r'\s+', ' ', str(value or '')).strip()[:length]


def safe_link(raw):
    """Use real public URLs but omit trackers, fragments and credential-like params."""
    s = str(raw or '').strip()
    u = urlparse(s)
    if u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password:
        return ''
    search_keys={'q','query','search','s','term','keyword','k'}
    query=urlencode([(k,v[:150]) for k,v in parse_qsl(u.query,keep_blank_values=False)
                     if k.lower() in search_keys][:2])
    return urlunparse((u.scheme,u.netloc,u.path or '/', '', query,''))


def safe_local(relative, root):
    """A screenshot must stay inside the report directory."""
    r = str(relative or '').strip()
    if not r or '\\' in r or '\x00' in r:
        return ''
    base = Path(root).resolve()
    candidate = (base / r).resolve()
    if not candidate.is_relative_to(base) or not candidate.is_file():
        return ''
    return candidate.relative_to(base).as_posix()


def indexed(run_dir):
    run_dir=Path(run_dir)
    out=run_dir/'results'
    def load_json(name):
        try:
            obj=json.loads((out/name).read_text(encoding='utf-8'))
            return obj if isinstance(obj,list) else []
        except (OSError, ValueError):
            return []
    return {
        'targets':read_csv(run_dir/'prospects.csv'),
        'context':{x['company'].casefold():x for x in read_csv(run_dir/'prospect_context.csv')},
        'leads':{x['company'].casefold():x for x in read_csv(out/'sales_ready_shortlist.csv')},
        'audit':{x.get('company','').casefold():x for x in load_json('evidence.json')},
        'tech':{x.get('company','').casefold():x for x in load_json('tech_stack.json')},
        'out':out,
    }


def grouped_stack(items):
    groups={'Ecommerce': [], 'Search': [], 'Merch': [], 'Other technology': []}
    for x in items:
        role=clean(x.get('role'),60)
        name=clean(x.get('provider'),80)
        if not name: continue
        info={'name':name,'confidence':clean(x.get('confidence'),24) or 'Indicative',
              'evidence':clean(x.get('evidence'),300)}
        if role=='Ecommerce':
            groups['Ecommerce'].append(info)
        elif 'Search' in role and 'Merch' in role:
            groups['Search'].append(info)
            groups['Merch'].append(info)
        elif 'Search' in role:
            groups['Search'].append(info)
        elif 'Merch' in role:
            groups['Merch'].append(info)
        else:
            groups['Other technology'].append(info)
    return groups


def relevant_signals(tech):
    """Only positive observations, not feature absence; all from public homepage."""
    allowed={'promotions','click_and_collect','store_locations','trade_or_b2b',
             'delivery','returns','loyalty','finance','newsletter','editorial_content','complex_delivery'}
    return [
        {'key':clean(x.get('key'),40),'label':clean(x.get('label'),70),
         'proof':clean(x.get('proof'),170),'url':safe_link(x.get('url'))}
        for x in tech.get('site_signals',[]) if x.get('key') in allowed
    ][:10]


def other_opportunities(audit, signals, context):
    """Suggest a *discussion topic*, never assert a gap or a missing integration."""
    keys={s['key'] for s in signals}
    candidates=[]
    def offer(module, why, ask, grounding):
        candidates.append({'module':module,'reason':why,'question':ask,
                           'evidence':grounding,'url':PORTFOLIO[module], 'status':'Explore, not confirmed'})

    if 'click_and_collect' in keys or 'store_locations' in keys:
        proof='Click & collect or store-location wording on the public site'
        offer('Omnichannel / OMS','Store and online buying journeys appear relevant.',
              'How are store inventory, online orders and customer collection managed together?',proof)
    if 'trade_or_b2b' in keys:
        offer('PIM','Public trade/wholesale references suggest product-data workflows may be worth discussing.',
              'Are product specifications and prices maintained centrally across your channels?',
              'Trade / wholesale wording on the public site')
    labels=' '.join(str(x.get('filter_labels','')) for x in (audit or {}).get('query_results',[])).casefold()
    if any(word in labels for word in ('compatibility','material','size','colour','color','width','dimension')):
        offer('PIM','Faceted product attributes were visible in the audit.',
              'How are product attributes and compatibility data managed for search and filtering?',
              'Filters observed in public product listings')
    if 'promotions' in keys:
        offer('Promotions & campaigns','Promotional language appears on the storefront.',
              'How much manual effort is needed to schedule and manage trading campaigns?',
              'Promotion or sale wording on the public site')
    if 'editorial_content' in keys:
        offer('Content management / CMS','Editorial content is publicly visible alongside the retail experience.',
              'How easily can your trading team publish product-linked content and campaigns?',
              'Editorial or buying-guide wording on the public site')
    if 'complex_delivery' in keys:
        offer('Fulfilment / WMS','More involved delivery arrangements appear to be mentioned publicly.',
              'Does your fulfilment operation need more visibility or automation as order volumes grow?',
              'Delivery-operations wording on the public site')
    # Do not suggest a product merely because it exists in the Remarkable catalogue.
    unique=[];seen=set()
    for x in candidates:
        if x['module'] not in seen:
            unique.append(x);seen.add(x['module'])
    return unique[:2]


def opportunity_parts(audit, lead, meta):
    if not audit:
        return {'label':'Not tested','detail':'Search was not assessed in this scan.','evidence':''}, {
            'label':'Not tested','detail':'Merchandising was not assessed in this scan.','evidence':''}, None
    p=analyse(audit)
    if p.bucket=='Not assessable':
        reason=clean(p.evidence,200)
        return {'label':'Not assessed','detail':reason,'evidence':''},{'label':'Not assessed','detail':reason,'evidence':''},p
    signal='Review observed signal' if p.bucket=='Review first' else 'Discovery opportunity'
    def part(detail,section):
        label='Review observed signal' if 'worth checking' in detail.lower() else 'Discovery opportunity'
        if section=='search' and detail.lower().startswith('search not assessed'):
            label='Not assessed'
        return {'label':label,'detail':clean(detail,250),
                'evidence':clean(p.evidence,250) if p.bucket=='Review first' else ''}
    return part(p.search_case,'search'),part(p.merch_case,'merch'),p


def build_profiles(run_dir):
    data=indexed(run_dir); profiles=[];out=data['out']
    for row in data['targets']:
        company=clean(row.get('company'),120)
        key=company.casefold()
        meta=data['context'].get(key,{})
        audit=data['audit'].get(key)
        tech=data['tech'].get(key,{})
        lead=data['leads'].get(key,{})
        search,merch,p=opportunity_parts(audit,lead,meta)
        signals=relevant_signals(tech)
        others=other_opportunities(audit,signals,meta)
        stack=grouped_stack(tech.get('technologies',[]))
        screenshot=safe_local(p.screenshot,out) if p else ''
        if not screenshot and audit:
            for q in audit.get('query_results',[]):
                screenshot=safe_local(q.get('screenshot'),out)
                if screenshot: break
        website=safe_link(row.get('website'))
        profile={
            'company':company,'website':website,'status':clean(audit.get('status') if audit else 'Not run',50),
            'tech_status':clean(tech.get('status','Not run'),50),
            'priority':clean(lead.get('priority') or ('Not assessed' if not p or p.bucket=='Not assessable' else 'Discovery fit'),60),
            'category':clean(meta.get('vertical') or 'Retail',80),
            'persona':clean(lead.get('primary_persona') or meta.get('primary_persona') or 'Head of Ecommerce',75),
            'search':search,'merch':merch,'other':others,
            'stack':stack,'stack_note':('Publicly detected signals only; not detected does not mean not installed.'),
            'signals':signals,'page_title':clean(tech.get('page_title'),120),
            'page_description':clean(tech.get('page_description'),220),
            'screenshot':screenshot,
            'observed':clean(p.evidence if p else 'No audited search or merchandising evidence available.',420),
            'confidence':clean(p.confidence if p else 'No audit evidence',140),
            'tested_url':safe_link(p.search_url if p else ''),
            'discovery_question':clean(p.suggested_question if p else 'What are your current product discovery and trading priorities?',260),
            'linkedin_draft':clean(lead.get('linkedin_opener'),600),
            'hypothesis':clean(meta.get('commercial_hypothesis'),240),
            'checked_utc':clean(audit.get('checked_utc') if audit else tech.get('checked_utc',''),45),
        }
        profiles.append(profile)
    return profiles


def export(run_dir):
    data=indexed(run_dir);out=data['out'];out.mkdir(parents=True,exist_ok=True)
    profiles=build_profiles(run_dir)
    (out/'account_profiles.json').write_text(json.dumps(profiles,ensure_ascii=False,indent=2),encoding='utf-8')
    fields=['Company','Website','Priority','Search entry','Search evidence','Merch entry','Merch evidence',
            'Other Remarkable opportunities','Ecommerce','Search tech','Merch tech',
            'Public signals','Contact role','Suggested question','LinkedIn draft','Evidence screenshot','Verified status']
    with (out/'account_profiles.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for p in profiles:
            def tech(k): return '; '.join(x['name']+' ('+x['confidence']+')' for x in p['stack'][k]) or 'Not detected'
            d={'Company':p['company'],'Website':p['website'],'Priority':p['priority'],
               'Search entry':p['search']['detail'],'Search evidence':p['search']['evidence'],
               'Merch entry':p['merch']['detail'],'Merch evidence':p['merch']['evidence'],
               'Other Remarkable opportunities':'; '.join(x['module']+': '+x['reason'] for x in p['other']) or 'None indicated',
               'Ecommerce':tech('Ecommerce'),'Search tech':tech('Search'),'Merch tech':tech('Merch'),
               'Public signals':'; '.join(x['label'] for x in p['signals']),
               'Contact role':p['persona'],'Suggested question':p['discovery_question'],
               'LinkedIn draft':p['linkedin_draft'],'Evidence screenshot':p['screenshot'],
               'Verified status':p['confidence']}
            w.writerow({k:("'"+str(v) if str(v).lstrip().startswith(('=','+','-','@')) else str(v)) for k,v in d.items()})
    (out/'account_profiles.html').write_text(render_html(profiles),encoding='utf-8')
    return profiles


def render_html(profiles):
    e=lambda value:html.escape(str(value or ''),quote=True)
    content=[]
    for p in profiles:
        stack=[]
        for kind in ('Ecommerce','Search','Merch','Other technology'):
            arr=p['stack'][kind]
            if arr:
                stack.append(f'<div><strong>{e(kind)}</strong><div>'+''.join(f'<span title="{e(x["evidence"])}">{e(x["name"])} · {e(x["confidence"])}</span>' for x in arr)+'</div></div>')
            else: stack.append(f'<div><strong>{e(kind)}</strong><p class="muted">Not detected / unknown</p></div>')
        other=''.join(f'<p><b>{e(x["module"])}</b> — {e(x["reason"])}<br><small>Ask: {e(x["question"])}</small></p>' for x in p['other']) or '<p class="muted">No additional gap supported by the public evidence.</p>'
        signals=''.join(f'<li>{e(x["label"])} <small>({e(x["proof"])})</small></li>' for x in p['signals']) or '<li>No additional public signals captured</li>'
        link=safe_link(p['website'])
        picture=f'<img src="{e(p["screenshot"])}" alt="Evidence screenshot for {e(p["company"])}" loading="lazy">' if p['screenshot'] else '<div class="missing">No permitted visual evidence</div>'
        content.append(f'''<article class="account"><div class="visual">{picture}<p>{e(p['confidence'])}</p></div><div class="info">
        <div class="top"><span>{e(p['priority'])}</span><span>{e(p['category'])}</span></div><h2>{e(p['company'])}</h2>
        <a href="{e(link)}" rel="noopener noreferrer" target="_blank">{e(link)}</a>
        <div class="two"><section><h3>Search entry</h3><small>{e(p['search']['label'])}</small><p>{e(p['search']['detail'])}</p></section>
        <section><h3>Merch entry</h3><small>{e(p['merch']['label'])}</small><p>{e(p['merch']['detail'])}</p></section></div>
        <section><h3>Other gaps Remarkable could explore</h3>{other}</section>
        <section><h3>Visible technology stack</h3><div class="techgrid">{''.join(stack)}</div><small>Not detected does not mean absent. Hover detected providers for evidence.</small></section>
        <details><summary>Other public signals & evidence</summary><ul>{signals}</ul><p>Page title: {e(p['page_title']) or 'Unknown'}</p><p>Audited observation: {e(p['observed'])}</p>
        {f'<a href="{e(p["tested_url"])}" target="_blank" rel="noopener noreferrer">View tested page ↗</a>' if p['tested_url'] else ''}</details>
        <div class="next"><strong>Conversation opener</strong><p>{e(p['discovery_question'])}</p><small>Target: {e(p['persona'])}</small></div>
        </div></article>''')
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Remarkable · Account intelligence</title>
    <style>*{box-sizing:border-box}body{margin:0;background:#f4f6f9;color:#21314a;font:14px/1.5 system-ui,Segoe UI,Arial,sans-serif}
    header{background:#192f49;color:white;padding:34px max(20px,calc((100vw - 1180px)/2))}header h1{margin:6px 0;font-size:26px}header p{color:#dce5ee;max-width:760px;margin:5px 0}
    main{max-width:1200px;margin:auto;padding:22px 14px}.account{display:grid;grid-template-columns:minmax(250px,38%) 1fr;background:white;border:1px solid #e0e7ee;border-radius:14px;overflow:hidden;margin-bottom:20px;box-shadow:0 2px 14px #1b2c4207}
    .visual{background:#f0f3f7;border-right:1px solid #edf0f3;padding:15px;min-height:265px}.visual img{width:100%;object-fit:contain;object-position:top;max-height:460px}.visual p{color:#67758b;font-size:12px}.missing{min-height:210px;display:grid;place-items:center;color:#7c8798}.info{padding:22px 26px}.top{display:flex;justify-content:space-between;color:#5f6f85;font-size:12px}.top span:first-child{font-weight:700;color:#275475}h2{font-size:24px;margin:6px 0 0}h3{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:#526a83;margin:0 0 5px}a{color:#245f96;text-decoration:none}p{margin:5px 0 12px}small,.muted{font-size:12px;color:#63758c}section{border-top:1px solid #e9eef2;padding-top:12px;margin-top:12px}.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}.two section{background:#f7f9fb;padding:13px;border:1px solid #e6ecf2;border-radius:9px}
    .techgrid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.techgrid span{display:inline-block;background:#edf3f8;padding:4px 7px;border-radius:5px;margin:3px 5px 3px 0;font-size:12px}.techgrid strong{display:block}details{margin-top:14px;padding:10px 0;border-top:1px solid #e7edf3}summary{cursor:pointer;font-weight:600;color:#245371}.next{background:#f5f8fb;padding:14px;border-radius:8px;margin-top:10px}.next p{margin:6px 0}.footer{padding:18px;color:#667a90;text-align:center}
    @media(max-width:820px){.account{grid-template-columns:1fr}.visual{border-right:0;border-bottom:1px solid #eceff4}.two{grid-template-columns:1fr}.info{padding:18px}.techgrid{grid-template-columns:1fr 1fr}}
    </style></head><body><header><div>REMARKABLE COMMERCE · PROSPECT INTELLIGENCE</div><h1>Account-by-account opportunities</h1><p>Search · Merchandising · Other Remarkable offerings · Publicly detected tech stack. Every suggested entry point requires qualification; public website evidence cannot establish budget, vendor dissatisfaction or lost revenue.</p></header><main>'''+''.join(content)+'''<p class="footer">Public research only · Respect robots and access restrictions · Human review before outreach</p></main></body></html>'''


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--run-dir',required=True)
    args=ap.parse_args()
    print('Generated',len(export(args.run_dir)),'account profiles')
