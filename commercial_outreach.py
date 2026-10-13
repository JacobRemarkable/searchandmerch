#!/usr/bin/env python3
"""Build a sales-focused, evidence-gated report from v4's existing audit.

This module NEVER visits external sites, creates CRM contacts, or sends outreach.
It separates commercial hypotheses from observed website facts.
"""
import argparse
import csv
import html
import json
from pathlib import Path
from urllib.parse import urlparse

from prospect_dashboard import analyse

CONTEXT_FIELDS = ['company', 'vertical', 'lead_with', 'primary_persona',
                  'commercial_hypothesis', 'research_source', 'platform_status']
SALES_FIELDS = ['company', 'website', 'priority', 'sales_status', 'lead_with',
                'primary_persona', 'vertical', 'commercial_hypothesis',
                'verified_observation', 'evidence_type', 'verification_required',
                'source_query', 'evidence_url', 'screenshot', 'platform_status',
                'linkedin_opener', 'follow_up_prompt', 'research_source']
STATUS_FIELDS = ['company', 'website', 'audit_status', 'sales_status',
                 'reason', 'included_in_sales_shortlist']


def escape(value):
    return html.escape(str(value or ''), quote=True)


def safe_csv(value):
    """Prevent a site-controlled CSV cell being interpreted as a spreadsheet formula."""
    if value is None:
        return ''
    t = str(value)
    if t.lstrip().startswith(('=', '+', '-', '@', '\t', '\r', '\n')):
        return "'" + t
    return t


def write_csv(path, rows, fields):
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for r in rows:
            writer.writerow({k: safe_csv(r.get(k, '')) for k in fields})


def load_context(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        missing = set(CONTEXT_FIELDS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError('Missing metadata columns: ' + ', '.join(sorted(missing)))
        result = {}
        for row in reader:
            key = row['company'].strip().casefold()
            if not key or key in result:
                raise ValueError('Duplicate or missing company in metadata')
            if row['lead_with'].strip() not in {'Search','Merch','Both'}:
                raise ValueError('Invalid lead_with for: ' + row['company'])
            result[key] = {k: str(row.get(k, '')).strip() for k in CONTEXT_FIELDS}
        return result


def local_screenshot(raw, output_dir):
    path = Path(str(raw or ''))
    if (not raw or path.is_absolute() or '..' in path.parts
        or len(path.parts) != 2 or path.parts[0] != 'screenshots'
        or path.suffix.lower() != '.png'):
        return ''
    return str(path) if (output_dir / path).is_file() else ''


def determine_observation(p):
    if p.bucket == 'Review first':
        if any(x[0] == 'stock' for x in p.flags):
            return 'Merch: unavailable products sampled', 'Search result screenshot'
        if any(x[0] == 'syntax' for x in p.flags):
            return 'Search: technical syntax visible in search heading', 'Search result screenshot'
        return 'Search: keyword relevance warrants human inspection', 'Search result screenshot'
    if p.search_case.startswith('Search not assessed'):
        return 'Merch: permitted category and products observed', 'Category screenshot (not search testing)'
    return 'Search: product results sampled; no defect established', 'Search result screenshot'


def opener_for(company, vertical, lead, status):
    # The message deliberately does not imply that the retailer has a known fault.
    topic = {
        'Search': 'onsite search and helping customers find specific products',
        'Merch': 'category ranking, stock-aware merchandising and campaign control',
        'Both': 'onsite search and category merchandising'
    }[lead]
    return (f'Hi [First Name], I was looking at {company} and its {vertical.lower()} range. '
            f'I work with retailers at Remarkable Commerce on {topic}, often without replacing their current platform. '
            'Would you be open to a quick conversation about how you manage this today?')


def followup_for(lead):
    return ({
        'Search': 'Offer to compare a couple of detailed, real customer searches against current results.',
        'Merch': 'Offer to compare category ranking, stock visibility and seasonal product placement.',
        'Both': 'Offer a 10-minute walkthrough of product-finding and merchandising opportunities.'
    }[lead])


def build_rows(evidence, context, out):
    leads, statuses = [], []
    for record in evidence:
        p = analyse(record)
        meta = context.get(p.company.strip().casefold())
        if p.bucket == 'Not assessable':
            statuses.append({'company':p.company,'website':p.website,'audit_status':p.bucket,
                             'sales_status':'Set aside','reason':p.evidence,
                             'included_in_sales_shortlist':'No'})
            continue
        if not meta:
            statuses.append({'company':p.company,'website':p.website,'audit_status':p.bucket,
                             'sales_status':'Missing commercial context',
                             'reason':'No matching company in prospect_context.csv',
                             'included_in_sales_shortlist':'No'})
            continue
        if p.bucket == 'Review first':
            priority, sales_status, verify = 'P1 · Verify signal', 'Needs evidence verification', 'Yes — repeat the exact search and inspect screenshot before claiming any issue'
        else:
            priority, sales_status, verify = 'P2 · Discovery', 'Discovery only — no defect claimed', 'No defect claim; review context before sending'
        obs, obs_type = determine_observation(p)
        screenshot=local_screenshot(p.screenshot,out)
        # A site without a usable screenshot is not sales-ready for an evidence-led review.
        if not screenshot:
            statuses.append({'company':p.company,'website':p.website,'audit_status':p.bucket,
                             'sales_status':'Missing screenshot','reason':'No local evidence image available',
                             'included_in_sales_shortlist':'No'})
            continue
        row = {
            'company':p.company,'website':p.website,'priority':priority,
            'sales_status':sales_status,'lead_with':meta['lead_with'],
            'primary_persona':meta['primary_persona'],'vertical':meta['vertical'],
            'commercial_hypothesis':meta['commercial_hypothesis'],
            'verified_observation':obs,'evidence_type':obs_type,
            'verification_required':verify,'source_query':p.query,
            'evidence_url':p.search_url,'screenshot':screenshot,
            'platform_status':meta['platform_status'],
            'linkedin_opener':opener_for(p.company,meta['vertical'],meta['lead_with'],sales_status),
            'follow_up_prompt':followup_for(meta['lead_with']),
            'research_source':meta['research_source']}
        leads.append(row)
        statuses.append({'company':p.company,'website':p.website,'audit_status':p.bucket,
                         'sales_status':sales_status,'reason':obs,'included_in_sales_shortlist':'Yes'})
    order={'P1 · Verify signal':0,'P2 · Discovery':1}
    leads.sort(key=lambda x:(order.get(x['priority'],9),x['company'].casefold()))
    statuses.sort(key=lambda x:x['company'].casefold())
    return leads, statuses


def render_html(leads, statuses, out):
    cards=[]
    for x in leads:
        site_url=x['website'] if urlparse(x['website']).scheme in ('http','https') else ''
        preview_url=x['evidence_url'] if urlparse(x['evidence_url']).scheme in ('http','https') else ''
        cards.append(f'''<article class="card">
          <a class="image" href="{escape(x['screenshot'])}" target="_blank" rel="noopener"><img src="{escape(x['screenshot'])}" alt="Screenshot of {escape(x['company'])}" loading="lazy"></a>
          <div class="detail"><div class="top"><span class="tag">{escape(x['priority'])}</span><span>{escape(x['lead_with'])} · {escape(x['primary_persona'])}</span></div>
          <h2>{escape(x['company'])}</h2><p><a href="{escape(site_url)}" target="_blank" rel="noopener">{escape(site_url)}</a></p>
          <div class="group"><b>Observed</b><p>{escape(x['verified_observation'])} <em>({escape(x['evidence_type'])})</em></p></div>
          <div class="group"><b>Commercial hypothesis — not a confirmed weakness</b><p>{escape(x['commercial_hypothesis'])}</p></div>
          <div class="group"><b>LinkedIn draft</b><blockquote>{escape(x['linkedin_opener'])}</blockquote></div>
          <div class="actions"><button data-copy="{escape(x['linkedin_opener'])}">Copy LinkedIn draft</button>
          {'<a href="'+escape(preview_url)+'" target="_blank" rel="noopener">View tested page ↗</a>' if preview_url else ''}</div>
          <small>{escape(x['verification_required'])} · Platform: {escape(x['platform_status'])}</small>
          </div></article>''')
    excluded = sum(1 for x in statuses if x['included_in_sales_shortlist'] == 'No')
    ready = sum(x['priority'].startswith('P2') for x in leads)
    verify = sum(x['priority'].startswith('P1') for x in leads)
    html_doc='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Remarkable · Sales opportunity shortlist</title>
    <style>*{box-sizing:border-box}body{margin:0;font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;color:#213047;background:#f3f5f8}header{padding:35px max(20px,calc((100vw - 1120px)/2));background:#14233c;color:white}header p{color:#d1d9e5;max-width:820px}main{max-width:1160px;margin:auto;padding:24px 18px}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.metric{padding:18px;background:white;border:1px solid #dde5ed;border-radius:13px}.metric strong{display:block;font-size:26px}.metric span{color:#607086}.note{padding:15px 18px;background:#fff;border-left:4px solid #f0af55;margin:19px 0;border-radius:8px}.card{display:grid;grid-template-columns:minmax(270px,42%) 1fr;overflow:hidden;background:#fff;border:1px solid #dce3eb;border-radius:14px;margin:17px 0;box-shadow:0 2px 9px #18243909}.image{background:#edf0f4;display:block;min-height:280px}.image img{display:block;max-height:400px;height:100%;width:100%;object-fit:contain;object-position:top}.detail{padding:22px}.top{display:flex;justify-content:space-between;align-items:center;gap:10px;font-size:12px;color:#62728c}.tag{background:#f1e6d0;color:#6c4914;border-radius:99px;padding:4px 9px;font-weight:700}h2{margin:9px 0 0;font-size:23px}.detail>p{margin:3px 0 12px}a{color:#2765a5}.group{margin:13px 0}.group>b{font-size:11px;color:#6a7a90;text-transform:uppercase;letter-spacing:.06em}.group p{margin:4px 0}.group em{font-size:12px;color:#69758b}.group blockquote{margin:7px 0;padding:11px 15px;border-left:3px solid #d5a356;background:#f8f9fb}.actions{display:flex;align-items:center;gap:15px;flex-wrap:wrap;margin:15px 0}.actions button{border:0;color:white;background:#14233c;border-radius:6px;padding:9px 12px;cursor:pointer}.detail small{color:#697b92}.footer{color:#607086;font-size:12px;padding:15px 0 30px}@media(max-width:780px){.card{grid-template-columns:1fr}.cards{grid-template-columns:1fr}.image{max-height:300px}}</style></head><body><header><div>REMARKABLE COMMERCE · SEARCH + MERCH</div><h1>Sales opportunity shortlist</h1><p>Screenshot evidence, appropriate commercial hypotheses and draft LinkedIn conversations. No claims of lost sales, defective search technology or platform compatibility without verification.</p></header><main><section class="cards"><div class="metric"><strong>__REVIEW__</strong><span>Priorities needing evidence check</span></div><div class="metric"><strong>__DISCOVERY__</strong><span>Discovery-fit opportunities</span></div><div class="metric"><strong>__EXCLUDED__</strong><span>Set aside / insufficient evidence</span></div></section><div class="note"><b>How to use:</b> Open the screenshot first. P1 means verify the observed signal before mentioning it; P2 means the opportunity is a commercial fit hypothesis, not a discovered website fault. Do not automatically send messages, and check HubSpot for existing client/opportunity relationships before contacting.</div>__ITEMS__<p class="footer">Research only · Public pages · Respects access restrictions · Human approval required before outreach</p></main><script>document.querySelectorAll('button[data-copy]').forEach(b=>b.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(b.dataset.copy);b.textContent='Copied';}catch(e){b.textContent='Select the message to copy';}}));</script></body></html>'''
    html_doc=(html_doc.replace('__REVIEW__',str(verify)).replace('__DISCOVERY__',str(ready))
                    .replace('__EXCLUDED__',str(excluded)).replace('__ITEMS__','\n'.join(cards)))
    (out / 'sales_opportunities.html').write_text(html_doc,encoding='utf-8')


def main(argv=None):
    parser=argparse.ArgumentParser(description='Evidence-backed Remarkable outbound preparation')
    parser.add_argument('--input',default='results/evidence.json')
    parser.add_argument('--context',default='prospect_context.csv')
    parser.add_argument('--out',default='results')
    args=parser.parse_args(argv)
    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)
    evidence=json.loads(Path(args.input).read_text(encoding='utf-8'))
    if not isinstance(evidence,list):
        parser.error('Evidence must be a list of retailer audits')
    context=load_context(Path(args.context))
    leads,statuses=build_rows(evidence,context,out)
    write_csv(out/'sales_ready_shortlist.csv',leads,SALES_FIELDS)
    write_csv(out/'all_target_status.csv',statuses,STATUS_FIELDS)
    render_html(leads,statuses,out)
    print('Sales report:',out/'sales_opportunities.html','| Leads:',len(leads),'| Excluded:',len(statuses)-len(leads))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
