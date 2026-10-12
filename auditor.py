#!/usr/bin/env python3
"""Remarkable Commerce | Evidence-first retail site prospect auditor.

Public, low-volume checks only. Does not log in, buy, scrape contacts or bypass blocks.
Run: python auditor.py --input prospects.csv --out results
"""

import argparse
import csv
import html
import json
import ipaddress
import os
import shutil
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse
from urllib.robotparser import RobotFileParser

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError, Error as PWError

USER_AGENT = "RemarkableRetailSiteAuditor/1.0 (low-volume public-site QA; human review required)"
BLOCK_TEXT = re.compile(r"captcha|are you (a )?human|unusual traffic|access denied|please verify you are human|cloudflare challenge|just a moment\.\.\.", re.I)
NO_RESULTS_TEXT = re.compile(r"no (products|results|items|matches) (were )?(found|available)|0 results|nothing (found|matches)|your search (returned|did not match)|couldn't find any|sorry, no", re.I)
STOCK_TEXT = re.compile(r"(?:out\s+of\s+stock|sold\s+out|currently unavailable|unavailable online)", re.I)
CURRENCY_TEXT = re.compile(r"(?:£|\$|€)\s?\d[\d,.]*")
PRODUCT_SELECTORS = [
    '[data-testid*="product-card" i]', '[data-test*="product-card" i]',
    '.product-card', '.product-item', '.product-grid-item', '.grid-product',
    '[class*="ProductCard"]', '[class*="product-card"]',
    '.ais-Hits-item', '.grid__item', '.product-list-item',
    '.products .product', '[data-product-id]',
]
SEARCH_INPUT = (
    'input[type="search"], input[role="searchbox"], '
    'input[placeholder*="search" i], input[aria-label*="search" i], '
    'input[name="q"], input[name="query"], input[name="search"], '
    'input[id*="search" i]'
)
CSV_COLUMNS = [
    "company", "website", "status", "checked_utc", "query",
    "search_method", "search_url", "search_input_found", "product_cards_detected",
    "sample_products", "query_title_overlap", "sort_control", "sort_test",
    "filter_control", "out_of_stock_cards", "zero_results_state", "zero_results_url",
    "signals", "outreach_angle", "screenshot", "review_required", "notes",
]


@dataclass
class Audit:
    company: str
    website: str
    status: str = "not_started"
    checked_utc: str = ""
    query: str = ""
    search_method: str = "unknown"
    search_url: str = ""
    search_input_found: str = "unknown"
    product_cards_detected: int = 0
    sample_products: str = ""
    query_title_overlap: str = "not_assessed"
    sort_control: str = "unknown"
    sort_test: str = "not_tested"
    filter_control: str = "unknown"
    out_of_stock_cards: int = 0
    zero_results_state: str = "not_tested"
    zero_results_url: str = ""
    signals: str = ""
    outreach_angle: str = ""
    screenshot: str = ""
    review_required: str = "Yes"
    notes: str = ""
    products: list = field(default_factory=list)

    def csv_row(self):
        raw = asdict(self)
        return {col: raw[col] for col in CSV_COLUMNS}


def safe_slug(s):
    return re.sub(r"[^a-z0-9-]+", "-", s.casefold()).strip("-")[:60] or "site"


def valid_website(url):
    url = (url or "").strip()
    if not url.startswith(("https://", "http://")):
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("Invalid public website URL")
    # Avoid local/network targets: this tool is designed for public prospect websites.
    host = (parsed.hostname or "").lower()
    if host in {"localhost", "127.0.0.1", "::1"} or host.endswith((".local", ".internal", ".localhost")):
        raise ValueError("Local/private hosts are excluded")
    try:
        if not ipaddress.ip_address(host).is_global:
            raise ValueError("Local/private hosts are excluded")
    except ValueError as exc:
        if str(exc) == "Local/private hosts are excluded":
            raise
    return url


def robots_allows(url, cache):
    """Respect published robots rules. If unavailable, note uncertainty."""
    p = urlparse(url)
    origin = f"{p.scheme}://{p.netloc}"
    if origin not in cache:
        from urllib.request import Request, urlopen
        try:
            req = Request(origin + "/robots.txt", headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=7) as resp:
                body = resp.read(512_000).decode("utf-8", "replace")
            rp = RobotFileParser()
            rp.parse(body.splitlines())
            cache[origin] = (rp, "robots.txt read")
        except Exception as e:
            cache[origin] = (None, f"robots.txt unavailable ({type(e).__name__})")
    rp, note = cache[origin]
    if rp is not None and not rp.can_fetch(USER_AGENT, url):
        return False, "Blocked by robots.txt"
    return True, note


def visible_first(page, selector, max_check=16):
    loc = page.locator(selector)
    try:
        for i in range(min(loc.count(), max_check)):
            item = loc.nth(i)
            if item.is_visible() and item.is_enabled():
                return item
    except Exception:
        pass
    return None


def load_public(page, url, robots_cache, pause=1.0):
    allowed, note = robots_allows(url, robots_cache)
    if not allowed:
        raise RuntimeError("ROBOTS_BLOCKED: " + note)
    response = page.goto(url, wait_until="domcontentloaded", timeout=22000)
    page.wait_for_timeout(850)
    time.sleep(max(0, pause))
    status = response.status if response else 0
    if status in {401, 403, 429}:
        raise RuntimeError(f"ACCESS_BLOCKED: HTTP {status}")
    if status >= 500:
        raise RuntimeError(f"SITE_ERROR: HTTP {status}")
    title = (page.title() or "")[:200]
    body = (page.locator("body").inner_text(timeout=4000) or "")[:3000]
    if BLOCK_TEXT.search(title) or BLOCK_TEXT.search(body[:850]):
        raise RuntimeError("ACCESS_BLOCKED: access/challenge page")
    return note


def find_search(page):
    item = visible_first(page, SEARCH_INPUT)
    if item:
        return item
    # Unhide website search; do not click generic navigation.
    for pattern in [r"^search$", r"^search (the )?(site|store|products)$", r"^open search$"]:
        try:
            buttons = page.get_by_role("button", name=re.compile(pattern, re.I))
            for i in range(min(buttons.count(), 8)):
                if buttons.nth(i).is_visible():
                    buttons.nth(i).click(timeout=2500)
                    page.wait_for_timeout(350)
                    item = visible_first(page, SEARCH_INPUT)
                    if item:
                        return item
        except Exception:
            continue
    return None


def do_search(page, query, template, website, robots_cache, pause):
    """Configured search URL takes precedence; otherwise submit site's real search box."""
    if template:
        url = template.replace("{query}", quote(query, safe=""))
        p = urlparse(url)
        base = urlparse(website)
        if p.hostname != base.hostname:
            raise ValueError("search_url_template must remain on the same website")
        load_public(page, url, robots_cache, pause)
        return "configured_url", url, "not_checked"
    item = find_search(page)
    if not item:
        return "not_available", "", "No"
    # Check the declared form target before initiating a GET/POST submission.
    form = item.locator("xpath=ancestor::form")
    if form.count():
        action = form.first.get_attribute("action") or page.url
        allowed, note = robots_allows(urljoin(page.url, action), robots_cache)
        if not allowed:
            raise RuntimeError("ROBOTS_BLOCKED: search form disallowed")
    item.fill(query)
    item.press("Enter")
    try:
        page.wait_for_load_state("domcontentloaded", timeout=7000)
    except PWTimeoutError:
        pass
    page.wait_for_timeout(1600)
    if BLOCK_TEXT.search((page.title() or "")[:200]):
        raise RuntimeError("ACCESS_BLOCKED: challenge after search")
    allowed, _ = robots_allows(page.url, robots_cache)
    if not allowed:
        raise RuntimeError("ROBOTS_BLOCKED: search page disallowed")
    return "form_submission", page.url, "Yes"


def extract_products(page, cap=8):
    """Detect observable product tiles; no guessed tile count when selectors fail."""
    best = []
    for selector in PRODUCT_SELECTORS:
        locator = page.locator(selector)
        try:
            n = min(locator.count(), 40)
        except Exception:
            continue
        found, seen = [], set()
        for idx in range(n):
            try:
                tile = locator.nth(idx)
                if not tile.is_visible():
                    continue
                link = tile.locator('a[href]').first
                if link.count() == 0:
                    continue
                href = urljoin(page.url, link.get_attribute('href') or '')
                if href in seen or href == page.url:
                    continue
                heading = tile.locator('h2,h3,h4,[class*="title" i]').first
                name = (heading.inner_text(timeout=1200) if heading.count() else link.inner_text(timeout=1200)).strip()
                content = tile.inner_text(timeout=1500).strip()
                if not name or len(name) > 180 or len(content) > 1800:
                    continue
                # A broad class like grid__item may include menus; require product-style hints.
                price = CURRENCY_TEXT.search(content)
                if selector in ('.grid__item', '[data-product-id]') and not price:
                    continue
                seen.add(href)
                found.append({"name": name[:150], "url": href, "price": price.group(0) if price else "", "sold_out_badge": bool(STOCK_TEXT.search(content))})
                if len(found) >= cap:
                    break
            except Exception:
                continue
        if len(found) > len(best):
            best = found
        if len(best) >= 4:
            break
    return best


def test_sort(page, before, pause):
    # Only interact with a native sort dropdown if safely identifiable.
    select = visible_first(page, 'select[name*="sort" i], select[id*="sort" i], select[aria-label*="sort" i]')
    if not select:
        maybe = visible_first(page, '[role="button"][aria-label*="sort" i], button[class*="sort" i]')
        return ("visible" if maybe else "not_detected", "not_tested")
    try:
        options = select.locator('option')
        available = [(options.nth(i).get_attribute('value'), options.nth(i).inner_text().strip()) for i in range(min(options.count(), 15))]
        current = select.input_value()
        target = next(((v, t) for v, t in available if v and v != current and re.search(r"price|alphabet|name", t, re.I)), None)
        if not target:
            return "visible", "unverified_no_suitable_option"
        select.select_option(value=target[0], timeout=5000)
        page.wait_for_timeout(1250)
        time.sleep(max(0, pause))
        selected = select.input_value() == target[0] if select.count() else False
        after = extract_products(page)
        if not selected and not after:
            return "visible", "inconclusive"
        changed = bool(before and after and [p['url'] for p in before[:3]] != [p['url'] for p in after[:3]])
        return "visible", ("accepted_and_reordered" if changed else "selection_changed_order_unverified" if selected else "inconclusive")
    except Exception:
        return "visible", "inconclusive"


def detect_filters(page):
    selectors = [
        'button[aria-label*="filter" i]', 'button[class*="filter" i]',
        '[role="button"][aria-label*="filter" i]',
        'fieldset input[type="checkbox"]', '[class*="facet" i] input[type="checkbox"]',
        '[class*="filter" i] input[type="checkbox"]'
    ]
    for s in selectors:
        if visible_first(page, s):
            return "visible"
    return "not_detected"


def zero_results_test(page, website, template, cache, pause):
    needle = "zzzxqrareproduct"  # Near-impossible product term; does not query customer data.
    method, url, _ = do_search(page, needle, template, website, cache, pause)
    if method == "not_available":
        return "unavailable", ""
    content = (page.locator("body").inner_text(timeout=4500) or "")[:12000]
    if NO_RESULTS_TEXT.search(content):
        return "clear_message_detected", page.url
    cards = extract_products(page)
    if cards:
        return "results_returned_review_relevance", page.url
    return "inconclusive_manual_review", page.url


def query_overlap(query, products):
    """A review signal only; synonyms and attributes can make exact word overlap misleading."""
    if not products:
        return "not_assessed"
    words = [w for w in re.findall(r"[a-z0-9]+", query.casefold()) if len(w) > 2]
    if not words:
        return "not_assessed"
    hits = sum(any(w in p['name'].casefold() for w in words) for p in products)
    return f"{hits}/{len(products)} sampled titles contain a query term (heuristic only)"


def recommend_angle(audit):
    angles = []
    if audit.out_of_stock_cards:
        angles.append("Ask how unavailable items are ranked and what alternative products shoppers see")
    if audit.query_title_overlap.startswith("0/"):
        angles.append("Offer to review query relevance with their ecommerce team (synonyms may explain results)")
    if audit.sort_control == "visible":
        angles.append("Explore trading team's control over product ordering and sort rules")
    if audit.filter_control == "visible":
        angles.append("Discuss whether filters reflect how customers specify products")
    if not angles:
        angles.append("Offer a short joint review of top onsite search journeys; no issue confirmed")
    return " | ".join(angles[:2])


def test_site(browser, row, out, robots_cache, pause, screenshot=True):
    company, website, query = row['company'].strip(), valid_website(row['website']), row['query'].strip()
    template = row.get('search_url_template', '').strip()
    a = Audit(company=company, website=website, query=query, checked_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    context = browser.new_context(user_agent=USER_AGENT, viewport={"width": 1440, "height": 900}, locale="en-GB", service_workers="block")
    page = context.new_page()
    try:
        note = load_public(page, website, robots_cache, pause)
        a.notes = note
        a.search_method, a.search_url, a.search_input_found = do_search(page, query, template, website, robots_cache, pause)
        if a.search_method == "not_available":
            a.status = "inconclusive"
            a.signals = "Search input not automatically detected; manual review required"
            return a
        a.status = "tested"
        a.search_url = page.url
        products = extract_products(page)
        a.products = products
        a.product_cards_detected = len(products)
        a.sample_products = " | ".join(p['name'] for p in products[:5])
        a.out_of_stock_cards = sum(p['sold_out_badge'] for p in products)
        a.query_title_overlap = query_overlap(query, products)
        a.filter_control = detect_filters(page)
        if screenshot:
            target = f"screenshots/{safe_slug(company)}-search.png"
            try:
                page.screenshot(path=str(out / target), full_page=False, animations="disabled", timeout=7500)
                a.screenshot = target
            except Exception as e:
                a.notes += f"; screenshot unavailable ({type(e).__name__})"
        a.sort_control, a.sort_test = test_sort(page, products, pause)
        # Start the no-results check from the homepage: some result pages hide search.
        try:
            load_public(page, website, robots_cache, pause)
            a.zero_results_state, a.zero_results_url = zero_results_test(page, website, template, robots_cache, pause)
        except Exception as test_error:
            a.zero_results_state = "inconclusive_manual_review"
            a.notes += f"; no-results test unavailable ({type(test_error).__name__})"
        signals = []
        if a.out_of_stock_cards:
            signals.append(f"{a.out_of_stock_cards}/{len(products)} sampled tiles clearly labelled unavailable (not necessarily a problem)")
        if a.query_title_overlap.startswith("0/"):
            signals.append("Search-result title relevance merits human check; synonyms can be valid")
        if a.sort_test == "selection_changed_order_unverified":
            signals.append("Sort selection changed but product order was not confirmed")
        if a.zero_results_state == "inconclusive_manual_review":
            signals.append("No-results experience needs review")
        if not products:
            a.status = "inconclusive"
            signals.append("Product tile structure not recognised; no ranking judgement made")
        a.signals = " | ".join(signals) if signals else "No automatically evidenced issue; human spot check recommended"
        a.outreach_angle = recommend_angle(a)
    except Exception as e:
        text = str(e)
        if text.startswith("ROBOTS_BLOCKED"):
            a.status = "robots_blocked"
        elif text.startswith("ACCESS_BLOCKED"):
            a.status = "access_blocked"
        elif text.startswith("SITE_ERROR"):
            a.status = "site_error"
        else:
            a.status = "inconclusive"
        a.signals = "No reliable audit produced"
        a.notes = (a.notes + "; " + text).strip('; ')[:500]
    finally:
        context.close()
    return a


def html_report(audits, output):
    date = html.escape(datetime.now(timezone.utc).strftime("%d %b %Y · %H:%M UTC"))
    good = sum(a.status == "tested" for a in audits)
    signal = sum(a.status == 'tested' and ('No automatically evidenced' not in a.signals) for a in audits)
    sections = []
    for a in audits:
        isblocked = a.status in {'access_blocked','robots_blocked','site_error'}
        label = 'Not tested' if isblocked else 'Needs review' if a.status != 'tested' else 'Evidence captured'
        tag = 'warn' if label != 'Evidence captured' else 'ok'
        screenshot = (f'<a target="_blank" href="{html.escape(a.screenshot, quote=True)}">View screenshot ↗</a>' if a.screenshot else '')
        product_list = ''.join(f'<li><a href="{html.escape(p["url"], quote=True)}" target="_blank">{html.escape(p["name"])}</a>{" · " + html.escape(p["price"]) if p["price"] else ""}{" · Unavailable label" if p["sold_out_badge"] else ""}</li>' for p in a.products)
        rows = ''.join(f'<tr><th>{html.escape(k)}</th><td>{html.escape(str(v))}</td></tr>' for k,v in [
            ('Website', a.website), ('Search query', a.query), ('Search path', a.search_url or 'Not identified'),
            ('Detected product tiles', str(a.product_cards_detected)), ('Query-term overlap', a.query_title_overlap),
            ('Sort UI / test', f'{a.sort_control} / {a.sort_test}'), ('Filter UI', a.filter_control),
            ('Out-of-stock tiles sampled', str(a.out_of_stock_cards)), ('No-results test', a.zero_results_state),
            ('Review notes', a.notes or '—')])
        sections.append(f'''<article class="card"><div class="cardtop"><div><h2>{html.escape(a.company)}</h2><p class="dim">{html.escape(a.website)}</p></div><span class="pill {tag}">{html.escape(label)}</span></div>
          <div class="two"><div><h3>Evidence / questions</h3><p>{html.escape(a.signals)}</p></div><div><h3>Conversation angle</h3><p>{html.escape(a.outreach_angle or 'Revisit only after manual review')}</p></div></div>
          <details><summary>Technical checks & sampled products</summary><table>{rows}</table><ul>{product_list}</ul>{screenshot}</details></article>''')
    doc = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Remarkable — Prospect Site Audit</title>
<style>:root{{--bg:#f6f7fb;--navy:#102036;--line:#dce4ef;--sub:#64748b;--gold:#f0b54b}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--navy);font-family:system-ui,-apple-system,Segoe UI,sans-serif;font-size:15px}}header{{background:#102036;color:white;padding:32px max(24px,calc((100vw - 1120px)/2))}}header .eyebrow{{color:#efba53;letter-spacing:.15em;font-size:11px;font-weight:700}}h1{{margin:8px 0;font-size:32px}}header p{{color:#d7dfeb;max-width:780px}}main{{max-width:1120px;margin:28px auto;padding:0 18px}}.stats{{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:24px}}.stat{{background:white;border:1px solid var(--line);border-radius:12px;padding:15px 22px;min-width:160px}}.stat b{{font-size:27px;display:block}}.stat span{{font-size:12px;color:var(--sub)}}.card{{background:white;border:1px solid var(--line);border-radius:14px;padding:22px;margin:14px 0;box-shadow:0 4px 15px #10203608}}.cardtop{{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}}h2{{margin:0;font-size:19px}}h3{{margin:0 0 8px;font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:#55667b}}p{{line-height:1.65}}p.dim{{color:var(--sub);margin:3px 0}}.two{{display:grid;grid-template-columns:1fr 1fr;gap:22px;margin:20px 0}}.pill{{font-size:12px;white-space:nowrap;padding:6px 11px;border-radius:999px;background:#e4f4ee;color:#226a4d;font-weight:700}}.pill.warn{{background:#fff1df;color:#8c5716}}details{{border-top:1px solid var(--line);padding-top:13px}}summary{{cursor:pointer;font-weight:700}}table{{width:100%;border-collapse:collapse;margin:14px 0}}td,th{{padding:8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;overflow-wrap:anywhere}}th{{color:#65758a;width:28%;font-size:13px}}li{{margin:6px 0}}a{{color:#0762a7}}.foot{{color:var(--sub);font-size:12px;padding:20px 0 40px}}@media(max-width:660px){{.two{{grid-template-columns:1fr}}h1{{font-size:27px}}.cardtop{{flex-direction:column}}}}</style></head><body><header><div class="eyebrow">REMARKABLE COMMERCE · PROSPECT INTELLIGENCE</div><h1>Website discovery audit</h1><p>Automated observations to support intelligent LinkedIn outreach. Not a technical certification, conversion study, or proof of a website defect.</p><p><small>{date}</small></p></header>
<main><div class="stats"><div class="stat"><b>{len(audits)}</b><span>Prospects input</span></div><div class="stat"><b>{good}</b><span>Automated tests completed</span></div><div class="stat"><b>{signal}</b><span>Sites with review signals</span></div></div>{''.join(sections)}<div class="foot">Audit uses small samples and browser heuristics. Search ranking, conversion impact, stock rules and merchandising quality must be confirmed by a person before being stated to a prospect. Blocks, robots policies and inaccessible websites are respected. No credentials or personal data collected.</div></main></body></html>'''
    output.write_text(doc, encoding='utf-8')


def main(argv=None):
    cli = argparse.ArgumentParser(description="Low-volume ecommerce search & merchandising audit")
    cli.add_argument('--input', default='prospects.csv', help='CSV of company,website,query,search_url_template')
    cli.add_argument('--out', default='results', help='Output directory')
    cli.add_argument('--max-sites', type=int, default=20, help='Safety limit per run, max 30')
    cli.add_argument('--pause', type=float, default=1.0, help='Seconds between website requests, min 1')
    cli.add_argument('--no-screenshots', action='store_true')
    args = cli.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'screenshots').mkdir(exist_ok=True)
    with open(args.input, encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print('No prospects in CSV', file=sys.stderr)
        return 1
    needed = {'company','website','query'}
    if not needed.issubset(rows[0]):
        print('Missing required CSV columns: ' + ', '.join(sorted(needed)), file=sys.stderr)
        return 1
    audits = []
    cache = {}
    with sync_playwright() as pw:
        browser_args = {"headless": True, "args": ["--disable-dev-shm-usage"]}
        override = os.environ.get("AUDIT_CHROMIUM_PATH", "").strip()
        if override:
            browser_args["executable_path"] = override
        try:
            browser = pw.chromium.launch(**browser_args)
        except PWError:
            system_chromium = shutil.which("chromium") or shutil.which("google-chrome")
            if not system_chromium or override:
                raise
            browser = pw.chromium.launch(executable_path=system_chromium, **browser_args)
        for idx, row in enumerate(rows[:max(1,min(30,args.max_sites))], start=1):
            name = (row.get('company') or '').strip()
            if not name or not row.get('website') or not row.get('query'):
                print(f'Skip invalid row {idx}: company, website and query required')
                continue
            print(f'[{idx}] {name}...', flush=True)
            try:
                a = test_site(browser,row,out,cache,max(1.0,args.pause),not args.no_screenshots)
            except Exception as e:
                a = Audit(company=name, website=row.get('website',''), status='inconclusive', notes=f'Input/runtime error: {e}')
            audits.append(a)
            print(f'    {a.status}; {a.product_cards_detected} tiles; no-results: {a.zero_results_state}', flush=True)
        browser.close()
    with (out / 'prospect_audit.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(a.csv_row() for a in audits)
    (out / 'evidence.json').write_text(json.dumps([asdict(a) for a in audits], indent=2, ensure_ascii=False),encoding='utf-8')
    html_report(audits,out / 'report.html')
    print(f'\nCreated {out / "report.html"}, {out / "prospect_audit.csv"} and {out / "evidence.json"}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
