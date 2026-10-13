#!/usr/bin/env python3
"""Produce a salesperson-first, screenshot-led shortlist from auditor evidence.json.

No extra visits, no bypasses, no fabricated sales claims. Every flagged opportunity
is labelled as a review prompt, not a demonstrated conversion problem.
"""
import argparse
import csv
import html
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


@dataclass
class Prospect:
    company: str
    website: str
    bucket: str
    sort_order: int
    search_case: str
    merch_case: str
    evidence: str
    confidence: str
    suggested_question: str
    manual_next_step: str
    query: str = ''
    search_url: str = ''
    screenshot: str = ''
    cards_sampled: int = 0
    available_detail: str = ''
    flags: list = field(default_factory=list)
    queries: list = field(default_factory=list)

    def row(self):
        return {key: getattr(self, key) for key in (
            'company', 'website', 'bucket', 'search_case', 'merch_case', 'evidence',
            'confidence', 'suggested_question', 'manual_next_step', 'query', 'search_url',
            'screenshot', 'cards_sampled', 'available_detail')}


def get_overlap(q):
    """Count sampled tiles containing ANY query term; a rough review hint only."""
    match = re.match(r'^\s*(\d+)\s*/\s*(\d+)', str(q.get('query_title_overlap') or ''))
    return (int(match.group(1)), int(match.group(2))) if match else (None, None)


def analyse(a):
    tested = [q for q in a.get('query_results', []) if q.get('status') == 'tested'
              and int(q.get('product_cards_detected') or 0) > 0]
    company, website = a.get('company', ''), a.get('website', '')
    if not tested:
        category = next((q for q in a.get('query_results', [])
                         if q.get('status') == 'category_observed'
                         and int(q.get('product_cards_detected') or 0) > 0), None)
        if category:
            count = int(category.get('product_cards_detected') or 0)
            controls = [name for name, key in [('filters','filter_control'),('sorting','sort_control')]
                        if category.get(key) in ('visible','visible_custom')]
            evidence = (f"Public product category was captured with {count} sampled product tiles"
                        + (f" and visible {', '.join(controls)}" if controls else '') +
                        '. This is not search testing and no performance issue is proven.')
            return Prospect(company,website,'Discovery fit',1,
                'Search not assessed — no negative claim',
                'Category merchandising observed — discuss trading controls',
                evidence,'Public category observation only',
                'How does your team control product ranking, availability and seasonal merchandising across categories?',
                'Only qualify as a discovery conversation, not a claimed website issue.',
                category.get('query',''), category.get('search_url',''),category.get('screenshot',''),
                count, f'Category sample: {count} product tiles')
        blocked = a.get('status') in ('robots_blocked', 'access_blocked')
        note = ('Site restricts the automated checks. No website weakness inferred.' if blocked
                else 'Search/category evidence could not be captured automatically. No website weakness inferred.')
        screenshot = next((q.get('screenshot') for q in a.get('query_results', [])
                           if q.get('screenshot')), '')
        return Prospect(company, website, 'Not assessable', 3, 'Not assessed', 'Not assessed', note,
            'Insufficient verified evidence — excluded from action queue',
            'No evidence-based claim available from this scan.',
            'Set aside. Do not assign a manual test or personalised defect outreach automatically.',
            screenshot=screenshot)

    opportunities = []
    search, merch = [], []
    detail_lines = []
    for q in tested:
        sample = int(q.get('product_cards_detected') or 0)
        sold_out = int(q.get('out_of_stock_cards') or 0)
        ov_num, ov_den = get_overlap(q)
        terms = [t for t in re.findall(r'[a-z0-9]+', q['query'].casefold()) if len(t) > 2]
        if sold_out > 0:
            merch.append(f"{sold_out} of {sample} sampled products on ‘{q['query']}’ visibly labelled unavailable")
            opportunities.append(('stock', q, 'Unavailable products appear in the sampled search results'))
        if re.search(r'(?<!\w)-(?:tag|type|collection|filter)\s*:', q.get('search_heading',''), re.I):
            search.append(f"Search heading for ‘{q['query']}’ visibly includes technical filter syntax")
            opportunities.append(('syntax', q, 'Internal search syntax is displayed in a customer-facing heading'))
        # This is a weak text-only proxy; can't assess visual or semantic relevance.
        if (ov_num is not None and ov_den >= 6 and len(terms) >= 2
                and ov_num/ov_den <= 0.34):
            search.append(f"Only {ov_num}/{ov_den} sampled product titles include a keyword from ‘{q['query']}’")
            opportunities.append(('relevance', q, 'Low title-keyword match deserves a visual relevance check'))
        detail_lines.append(f"{q['query']}: {sample} sampled products"
                            + (f", {sold_out} visibly unavailable" if sold_out else ''))

    chosen = opportunities[0][1] if opportunities else tested[0]
    screenshots = [q for q in tested if q.get('screenshot')]
    if not chosen.get('screenshot') and screenshots:
        chosen = screenshots[0]

    if merch:
        m_case = 'Availability / merchandising: worth checking'
    elif any(q.get('filter_control') == 'visible' for q in tested):
        m_case = 'Merchandising controls visible — discuss trading optimisation'
    else:
        m_case = 'Merch opportunity unverified'
    if search:
        s_case = 'Search relevance: worth checking'
    elif len(tested) >= 2:
        s_case = 'Search results captured — no obvious relevance issue proved'
    else:
        s_case = 'Search results sampled — manual quality check needed'

    if opportunities:
        bucket = 'Review first'
        confidence = 'Visible observation; commercial impact unproven'
        evidence = ' | '.join((search + merch)[:3])
        typ = opportunities[0][0]
        question = (
            'I noticed some unavailable products in a sample of your search results. '
            'How does your team decide which products rank first and which alternatives to show?'
            if typ == 'stock' else
            'I noticed the search-results heading appears to include some technical filtering syntax. '
            'Is that intentional, and how does your team assess the onsite search experience?'
            if typ == 'syntax' else
            'I was testing a couple of product searches and wondered how you measure '
            'onsite search relevance, especially for detailed shopping queries?'
        )
        manual = ('Inspect screenshot and repeat that exact query in a normal browser. '
                  'Confirm the observation is visible and meaningful before sending it to a prospect.')
    elif any(q.get('filter_control') == 'visible' or q.get('sort_control') == 'visible' for q in tested):
        bucket = 'Discovery fit'
        confidence = 'Features observed; no identified defect'
        evidence = ' | '.join(detail_lines[:3]) + '; existing sorting/filtering detected'
        question = ('How much manual effort goes into ranking products and maintaining filters '
                    'for customers who know exactly what they want?')
        manual = 'Review current product ordering, filter experience and stock handling; ask about objectives rather than alleging defects.'
    else:
        bucket = 'Discovery fit'
        confidence = 'Search sampled; no identified defect'
        evidence = ' | '.join(detail_lines[:3])
        question = 'How are you measuring whether customers find the right products quickly through search?'
        manual = 'Review a screenshot and the product results before any personalised outreach.'

    return Prospect(company, website, bucket, 0 if bucket == 'Review first' else 1,
        s_case, m_case, evidence, confidence, question, manual,
        chosen.get('query',''), chosen.get('search_url',''), chosen.get('screenshot',''),
        chosen.get('product_cards_detected', 0), ' | '.join(detail_lines),
        opportunities, tested)


def esc(v):
    return html.escape(str(v or ''), quote=True)


def render(records, output):
    counts = {bucket: sum(r.bucket == bucket for r in records)
              for bucket in ('Review first','Discovery fit','Not assessable')}
    tiles = []
    for r in records:
        if r.bucket == 'Review first':
            label, tagcls = 'Review first', 'tag-orange'
        elif r.bucket == 'Discovery fit':
            label, tagcls = 'Discovery fit', 'tag-blue'
        else:
            label, tagcls = 'Not assessable', 'tag-gray'
        if r.screenshot:
            # Only accept local generated screenshots (not external URLs).
            path = Path(r.screenshot)
            valid = (not path.is_absolute() and '..' not in path.parts
                     and path.parts[0] == 'screenshots' and path.suffix.lower() == '.png'
                     and (output.parent / path).is_file())
        else:
            valid = False
        visual = (f'<a href="{esc(r.screenshot)}" target="_blank" rel="noopener">'
                  f'<img loading="lazy" alt="Recorded search evidence for {esc(r.company)}" src="{esc(r.screenshot)}">'
                  f'<span>Enlarge screenshot ↗</span></a>' if valid else
                  '<div class="image-empty">No permitted screenshot captured</div>')
        query_link = (f'<a target="_blank" rel="noopener" href="{esc(r.search_url)}">View sampled search ↗</a>'
                      if r.search_url and urlparse(r.search_url).scheme in ('http', 'https') else '')
        queries = ''.join(f'<details><summary>{esc(q.get("query"))} · {esc(q.get("product_cards_detected"))} sampled items</summary>'
                          '<ol>' + ''.join(f'<li>{esc(p.get("name"))} <em>{esc(p.get("price"))}</em>'
                                          + (' <b>Sold out</b>' if p.get('sold_out_badge') else '') + '</li>'
                                          for p in q.get('products', [])[:8]) + '</ol></details>'
                          for q in r.queries)
        tiles.append(f'''<article class="prospect" data-kind="{esc(r.bucket)}">
          <div class="photo">{visual}</div><div class="content">
          <div class="top"><span class="tag {tagcls}">{label}</span><small>{esc(r.confidence)}</small></div>
          <h2>{esc(r.company)}</h2><p class="site"><a href="{esc(r.website)}" target="_blank" rel="noopener">{esc(r.website)}</a></p>
          <div class="signals"><div><span>SEARCH</span><p>{esc(r.search_case)}</p></div>
          <div><span>MERCH</span><p>{esc(r.merch_case)}</p></div></div>
          <h3>What we actually observed</h3><p>{esc(r.evidence)}</p>
          <h3>Question to start a conversation</h3><p class="question">{esc(r.suggested_question)}</p>
          <p class="actions">{query_link} <button type="button" data-copy="{esc(r.suggested_question)}">Copy opener</button></p>
          <details><summary>Verification checklist & sampled products</summary><p>{esc(r.manual_next_step)}</p>{queries}</details>
          </div></article>''')
    doc = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Remarkable Commerce · Prospect Opportunity Board</title>
<style>
:root{--bg:#f3f5f8;--white:#fff;--navy:#15233c;--muted:#64748b;--line:#dce2eb;--orange:#f1ab4d}
*{box-sizing:border-box}[hidden]{display:none!important}body{font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;background:var(--bg);color:var(--navy);margin:0}
a{color:#2466ad}header{background:var(--navy);color:#fff;padding:38px max(20px,calc((100vw - 1170px)/2))}header p{color:#d4dfed;max-width:900px}
.eyebrow{color:#fdc474;font-size:12px;font-weight:750;letter-spacing:.14em}h1{font-size:32px;margin:9px 0 12px}
main{max-width:1210px;margin:auto;padding:25px 20px}.summary{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:22px}
.metric{background:white;border:1px solid var(--line);padding:18px 20px;border-radius:14px}.metric b{display:block;font-size:28px}.metric span{color:var(--muted)}
.note{background:#fff;padding:16px;border-left:4px solid var(--orange);border-radius:6px;margin:12px 0 24px}
.filters{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 18px}.filters button{background:white;color:var(--navy);border:1px solid #cbd5e1;padding:9px 14px;border-radius:10px;cursor:pointer}
.filters button.active{background:var(--navy);color:#fff}.prospect{display:grid;grid-template-columns:minmax(280px,.95fr) minmax(320px,1.1fr);border:1px solid var(--line);border-radius:15px;overflow:hidden;background:white;margin:16px 0;box-shadow:0 5px 18px #14233c09}
.photo{background:#e5e9ef;display:grid;align-items:start}.photo a{display:block;position:relative}.photo img{width:100%;height:100%;min-height:290px;object-fit:contain;object-position:top;background:#f9fafb}.photo a span{position:absolute;bottom:8px;right:10px;color:white;background:#14233cdd;padding:5px 9px;border-radius:5px;font-size:12px}.image-empty{min-height:260px;display:grid;place-items:center;padding:25px;color:#66758b}
.content{padding:24px}.top{display:flex;align-items:center;justify-content:space-between;gap:12px}.top small{color:var(--muted);text-align:right}.tag{font-weight:700;font-size:12px;padding:5px 10px;border-radius:99px}.tag-orange{background:#fff0d7;color:#87520b}.tag-blue{background:#e7f0fb;color:#245786}.tag-gray{background:#eef0f3;color:#576373}
h2{font-size:24px;margin:13px 0 0}.site{margin:1px 0 15px;font-size:12px}.signals{display:grid;grid-template-columns:1fr 1fr;gap:10px}.signals>div{background:#f4f6fa;padding:12px;border-radius:9px}.signals span,h3{color:#69788d;font-weight:750;font-size:11px;letter-spacing:.065em}.signals p{margin:5px 0 0;font-weight:650}.content h3{margin:16px 0 5px}.content>p{margin:6px 0 9px}.question{font-size:15px;font-weight:600}.actions{display:flex;gap:16px;align-items:center;flex-wrap:wrap}.actions button{border:0;background:var(--navy);color:white;padding:8px 12px;border-radius:7px;cursor:pointer}
details{border-top:1px solid var(--line);padding-top:10px;margin-top:13px}summary{cursor:pointer;color:#255a91;font-size:12px}details details{margin-top:8px}li{margin:4px 0}em{color:#64748b;font-style:normal}footer{color:#65758a;font-size:12px;padding:22px 0 40px}
@media(max-width:740px){.prospect{grid-template-columns:1fr}.photo img{max-height:320px}.summary{grid-template-columns:1fr 1fr}h1{font-size:25px}.signals{grid-template-columns:1fr}}
@media print{header{padding:16px}.filters,.actions{display:none}.prospect{break-inside:avoid}.photo img{min-height:140px;max-height:180px}.content{padding:14px}main{padding:12px}}
</style></head><body><header><div class="eyebrow">REMARKABLE COMMERCE · SEARCH + MERCH</div><h1>Website opportunity shortlist</h1>
<p>See the retail experience, spot credible questions and start better conversations. This is research, not proof of lost revenue or a defective technology platform.</p></header>
<main><section class="summary"><div class="metric"><b>__REV__</b><span>Visible signals to review</span></div><div class="metric"><b>__DISC__</b><span>Discovery conversations</span></div><div class="metric"><b>__MAN__</b><span>Set aside · insufficient evidence</span></div></section>
<div class="note"><b>How to use this:</b> Open the screenshot, repeat the exact search in a normal browser, and only then personalise outreach. A detected filter or sorting control is not a weakness. Low keyword matches are an imperfect proxy, not a search accuracy score. Restricted/inconclusive websites are set aside, not sent to a manual-testing queue.</div>
<nav class="filters" aria-label="Filter opportunities"><button type="button" class="active" data-filter="all">All prospects</button><button type="button" data-filter="Review first">Review first</button><button type="button" data-filter="Discovery fit">Discovery fit</button><button type="button" data-filter="Not assessable">Set aside</button></nav>
__CARDS__<footer>Generated from public pages with low-volume checks. Human verification is required before sales claims; do not circumvent robots.txt, CAPTCHA or site access restrictions.</footer></main>
<script>document.querySelectorAll('[data-filter]').forEach(b=>b.addEventListener('click',()=>{document.querySelectorAll('[data-filter]').forEach(x=>x.classList.toggle('active',x===b));document.querySelectorAll('.prospect').forEach(x=>{x.hidden=b.dataset.filter!=='all'&&x.dataset.kind!==b.dataset.filter;});}));document.querySelectorAll('[data-copy]').forEach(b=>b.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(b.dataset.copy);b.textContent='Copied!';}catch(e){b.textContent='Select text to copy';}}));</script></body></html>'''
    doc = (doc.replace('__REV__',str(counts['Review first']))
           .replace('__DISC__',str(counts['Discovery fit']))
           .replace('__MAN__',str(counts['Not assessable']))
           .replace('__CARDS__','\n'.join(tiles)))
    output.write_text(doc, encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Screenshot-led Search & Merch prospecting report')
    parser.add_argument('--input', default='results/evidence.json')
    parser.add_argument('--out', default='results')
    args = parser.parse_args(argv)
    source, out = Path(args.input), Path(args.out)
    if not source.exists():
        parser.error(f'Cannot find evidence file: {source}')
    out.mkdir(parents=True,exist_ok=True)
    data = json.loads(source.read_text(encoding='utf-8'))
    records = sorted([analyse(entry) for entry in data],key=lambda r:(r.sort_order,r.company.casefold()))
    render(records,out / 'opportunity_dashboard.html')
    path = out / 'opportunity_shortlist.csv'
    with path.open('w',encoding='utf-8-sig',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=list(records[0].row()) if records else list(Prospect('','','',3,'','','','','','').row()))
        writer.writeheader()
        writer.writerows(r.row() for r in records)
    print(f'Created {out / "opportunity_dashboard.html"} and {path}')
    for name in ('Review first','Discovery fit','Not assessable'):
        print(f'{name}: {sum(r.bucket==name for r in records)}')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
