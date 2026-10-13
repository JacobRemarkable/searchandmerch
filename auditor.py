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
from urllib.parse import quote, urljoin, urlparse, parse_qs
from urllib.robotparser import RobotFileParser

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError, Error as PWError

USER_AGENT = "RemarkableRetailSiteAuditor/2.0 (low-volume public-site QA; human review required)"
BLOCK_TEXT = re.compile(r"captcha|are you (a )?human|unusual traffic|access denied|please verify you are human|cloudflare challenge|just a moment\.\.\.", re.I)
NO_RESULTS_TEXT = re.compile(r"no (products|results|items|matches) (were )?(found|available)|0 results|nothing (found|matches)|your search (returned|did not match)|couldn't find any|sorry, no", re.I)
STOCK_TEXT = re.compile(r"(?:out\s+of\s+stock|sold\s+out|currently unavailable|unavailable online)", re.I)
CURRENCY_TEXT = re.compile(r"(?:£|\$|€)\s?\d[\d,.]*")
PRODUCT_SELECTORS = [
    '[itemtype*="schema.org/Product" i]', '[data-product-id]',
    '[data-product-handle]', '[data-testid*="product" i][class*="card" i]',
    'li[class*="product" i]', 'article[class*="product" i]',
    '.card-wrapper', '.product-card-wrapper', '[class*="product-tile" i]',
    '[class*="product-item" i]',
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
    "review_priority", "evidence_quality", "queries_tested", "queries_inconclusive",
    "overlay_action", "filter_labels", "screenshots",
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
    review_priority: str = "Unrated"
    evidence_quality: str = "No evidence"
    queries_tested: int = 0
    queries_inconclusive: int = 0
    overlay_action: str = "none"
    filter_labels: str = ""
    screenshots: str = ""
    products: list = field(default_factory=list)
    query_results: list = field(default_factory=list)
    observations: list = field(default_factory=list)
    follow_up_questions: list = field(default_factory=list)

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



# Only ordinary public pages. Consent overlays may be dismissed, but challenges and
# access restrictions are not bypassed. Clicks never accept marketing consent.
OVERLAY_SELECTORS = [
    '[role="dialog"]', '[aria-modal="true"]',
    '[class*="modal" i]', '[class*="cookie" i][class*="banner" i]',
    '[id*="cookie" i][class*="banner" i]',
    '[class*="country" i][class*="popup" i]',
    '[class*="location" i][class*="popup" i]',
]
FILTER_LABELS = ('Availability', 'Price', 'Colour', 'Color', 'Size', 'Brand',
                 'Compatibility', 'Material', 'Width', 'Height', 'Depth',
                 'Category', 'Product Type', 'Shop By')


def visible_first(page, selector, max_check=30):
    try:
        loc = page.locator(selector)
        for i in range(min(loc.count(), max_check)):
            item = loc.nth(i)
            if item.is_visible() and item.is_enabled():
                return item
    except Exception:
        pass
    return None


def safe_body(page, selector='body', limit=14000):
    try:
        return (page.locator(selector).first.inner_text(timeout=3000) or '')[:limit]
    except Exception:
        return ''


def detect_challenge(page):
    title = (page.title() or '')[:220]
    # Avoid rejecting a legitimate product page that mentions 'access denied' in footer.
    body = safe_body(page, limit=1700)
    if BLOCK_TEXT.search(title) or BLOCK_TEXT.search(body[:850]):
        raise RuntimeError('ACCESS_BLOCKED: access/challenge page')


def load_public(page, url, robots_cache, pause=1.0):
    allowed, note = robots_allows(url, robots_cache)
    if not allowed:
        raise RuntimeError('ROBOTS_BLOCKED: ' + note)
    response = page.goto(url, wait_until='domcontentloaded', timeout=24000)
    page.wait_for_timeout(700)
    time.sleep(max(0, pause))
    status = response.status if response else 0
    if status in {401, 403, 429}:
        raise RuntimeError(f'ACCESS_BLOCKED: HTTP {status}')
    if status >= 500:
        raise RuntimeError(f'SITE_ERROR: HTTP {status}')
    allowed, _ = robots_allows(page.url, robots_cache)
    if not allowed:
        raise RuntimeError('ROBOTS_BLOCKED: redirected to disallowed page')
    detect_challenge(page)
    return note


def dismiss_overlays(page, max_actions=2):
    '''Dismiss benign location/consent overlays, without accepting optional cookies.

    A location choice is only selected when the pop-up explicitly offers UK/US.
    No CAPTCHA, human check, log-in or access challenge is interacted with.
    '''
    actions = []
    for _ in range(max_actions):
        acted = False
        for selector in OVERLAY_SELECTORS:
            container = visible_first(page, selector)
            if container is None:
                continue
            try:
                content = container.inner_text(timeout=1200)[:1800]
                if BLOCK_TEXT.search(content[:300]):
                    continue
                is_cookie = bool(re.search(r'cookies?|tracking|consent|privacy preferences', content, re.I))
                is_country = bool(re.search(r'right place|your (country|region)|choose.*(country|region)|select.*(country|region)', content, re.I))
                # Do not pick generic UK links from the main navigation.
                if is_cookie:
                    names = [r'^reject all$', r'^decline all$', r'^reject optional$',
                             r'^necessary only$', r'^essential only$',
                             r'^only essential cookies$', r'^continue without accepting$']
                elif is_country and 'uk' in content.casefold():
                    names = [r'^UK$', r'^United Kingdom$', r'^Continue to UK$', r'^Shop UK$']
                else:
                    names = []
                # Use accessible buttons where possible; fall back to buttons/links with exact text.
                for pattern in names:
                    hits = container.get_by_role('button', name=re.compile(pattern, re.I))
                    for role in ('link',):
                        if hits.count() == 0:
                            hits = container.get_by_role(role, name=re.compile(pattern, re.I))
                    target = None
                    for i in range(min(8, hits.count())):
                        if hits.nth(i).is_visible():
                            target = hits.nth(i)
                            break
                    if target is None:
                        # Location/consent widgets sometimes use divs styled as buttons.
                        # Restrict exact-text fallback to the already-recognised overlay.
                        try:
                            candidates = container.get_by_text(re.compile(pattern,re.I))
                            for j in range(min(8,candidates.count())):
                                if candidates.nth(j).is_visible() and len(candidates.nth(j).inner_text().strip()) < 48:
                                    target = candidates.nth(j)
                                    break
                        except Exception:
                            pass
                    if target is None:
                        continue
                    if target.evaluate('(el) => el.tagName.toLowerCase() === "a"'):
                        href = target.get_attribute('href') or ''
                        nexturl = urljoin(page.url, href)
                        if urlparse(nexturl).hostname != urlparse(page.url).hostname:
                            continue
                    try:
                        target.click(timeout=2500)
                        page.wait_for_timeout(400)
                        actions.append(('consent: rejected optional' if is_cookie else 'location: selected UK'))
                        acted = True
                        break
                    except Exception:
                        pass
                if acted:
                    break
                # Safe dismissal of a non-challenge location/info overlay via explicit close.
                if not is_cookie:
                    close = container.get_by_role('button', name=re.compile(r'^(close|dismiss|not now|×|✕)$', re.I))
                    if close.count() and close.first.is_visible():
                        try:
                            close.first.click(timeout=2000)
                            page.wait_for_timeout(250)
                            actions.append('modal: closed')
                            acted = True
                            break
                        except Exception:
                            pass
            except Exception:
                continue
        if not acted:
            break
    return ' | '.join(actions) or 'none'


def find_search(page, robots_cache=None):
    # Prefer an already visible field, then a safely recognisable search toggle.
    item = visible_first(page, SEARCH_INPUT)
    if item is not None:
        return item
    toggles = [
        ('role_button', r'^(open |show |toggle )?search( (the )?(site|store|products|catalogue))?$'),
        ('role_link', r'^search( (the )?(site|store|products))?$'),
    ]
    for kind, regex in toggles:
        try:
            loc = (page.get_by_role('button', name=re.compile(regex, re.I))
                   if kind == 'role_button' else page.get_by_role('link', name=re.compile(regex, re.I)))
            for i in range(min(loc.count(), 10)):
                el = loc.nth(i)
                if not el.is_visible():
                    continue
                if kind == 'role_link' and robots_cache is not None:
                    href = el.get_attribute('href') or ''
                    target = urljoin(page.url, href)
                    if urlparse(target).hostname != urlparse(page.url).hostname or not robots_allows(target, robots_cache)[0]:
                        continue
                el.click(timeout=2200)
                page.wait_for_timeout(300)
                found = visible_first(page, SEARCH_INPUT)
                if found is not None:
                    return found
        except Exception:
            continue
    # Icon-only search controls frequently have no accessible name. Only use
    # explicit search identifiers; never click unrelated site navigation.
    selectors = [
        'header button[aria-label*="search" i]',
        'header button[title*="search" i]',
        'header [data-testid*="search" i][role="button"]',
        'header button[class*="search" i]',
        'header a[aria-label*="search" i]',
        'header a[class*="search" i]',
        'header a[href="/search"]',
        '[data-action="search"]',
        'button[data-testid*="search" i]',
        'button:has(svg[class*="search" i])',
        'button:has(svg[aria-label*="search" i])',
    ]
    for selector in selectors:
        try:
            buttons = page.locator(selector)
            for i in range(min(buttons.count(), 8)):
                button = buttons.nth(i)
                if not button.is_visible():
                    continue
                if button.evaluate('(el) => el.tagName.toLowerCase() === "a"') and robots_cache is not None:
                    target = urljoin(page.url, button.get_attribute('href') or '')
                    if urlparse(target).hostname != urlparse(page.url).hostname:
                        continue
                    if not robots_allows(target, robots_cache)[0]:
                        continue
                button.click(timeout=2200)
                page.wait_for_timeout(350)
                found = visible_first(page, SEARCH_INPUT)
                if found is not None:
                    return found
        except Exception:
            continue
    return None


def do_search(page, query, template, website, robots_cache, pause):
    '''Use an approved URL template or submit a discoverable onsite search field.'''
    if template:
        url = template.replace('{query}', quote(query, safe=''))
        p, base = urlparse(url), urlparse(website)
        if p.hostname != base.hostname or p.scheme not in ('http', 'https'):
            raise ValueError('search_url_template must remain on the same website')
        load_public(page, url, robots_cache, pause)
        dismiss_overlays(page)
        return 'configured_url', page.url, 'not_checked'
    item = find_search(page, robots_cache)
    if item is None:
        return 'not_available', '', 'No'
    form = item.locator('xpath=ancestor::form')
    if form.count():
        action = form.first.get_attribute('action') or page.url
        action_url = urljoin(page.url, action)
        if urlparse(action_url).hostname != urlparse(website).hostname:
            raise RuntimeError('ACCESS_BLOCKED: external search form action')
        if not robots_allows(action_url, robots_cache)[0]:
            raise RuntimeError('ROBOTS_BLOCKED: search form disallowed')
    item.fill(query, timeout=3000)
    item.press('Enter', timeout=3000)
    try:
        page.wait_for_load_state('domcontentloaded', timeout=7000)
    except PWTimeoutError:
        pass
    page.wait_for_timeout(1400)
    time.sleep(max(0, pause))
    detect_challenge(page)
    if not robots_allows(page.url, robots_cache)[0]:
        raise RuntimeError('ROBOTS_BLOCKED: search page disallowed')
    dismiss_overlays(page)
    return 'form_submission', page.url, 'Yes'


def extract_products(page, cap=12):
    '''Sample visible tiles with product-like markup, using a guarded link fallback.

    A count of zero means product tiles not recognised, never zero search results.
    '''
    best = []
    for selector in PRODUCT_SELECTORS:
        locator = page.locator(selector)
        try:
            n = min(locator.count(), 65)
        except Exception:
            continue
        found, seen = [], set()
        for idx in range(n):
            try:
                tile = locator.nth(idx)
                if not tile.is_visible():
                    continue
                link = tile.locator('a[href]').first
                if not link.count():
                    continue
                href = urljoin(page.url, link.get_attribute('href') or '')
                key = urlparse(href)._replace(query='', fragment='').geturl()
                if key in seen or key == page.url:
                    continue
                heading = tile.locator('h2,h3,h4,[class*="title" i],[class*="name" i]').first
                name = (heading.inner_text(timeout=1000) if heading.count() else link.inner_text(timeout=1000)).strip()
                content = tile.inner_text(timeout=1200).strip()
                price = CURRENCY_TEXT.search(content)
                if not name or len(name) > 170 or len(content) > 1400:
                    continue
                if selector in ('.grid__item', '[data-product-id]', '[data-product-handle]') and not price:
                    continue
                seen.add(key)
                found.append({'name': name[:150], 'url': key, 'price': price.group(0) if price else '',
                              'sold_out_badge': bool(STOCK_TEXT.search(content))})
                if len(found) >= cap:
                    break
            except Exception:
                continue
        if len(found) > len(best):
            best = found
        if len(best) >= 6:
            break
    # Fallback for custom storefronts, constrained to product-like URLs and
    # surrounding price+title markup. Never call the entire page a product tile.
    if len(best) < 3:
        fallback = page.evaluate(r'''() => {
          const root = document.querySelector('main,[role="main"]') || document.body;
          const seen = new Set(), rows = [];
          for (const a of root.querySelectorAll('a[href]')) {
            if (rows.length >= 16) break;
            let abs; try { abs = new URL(a.getAttribute('href'), document.baseURI); } catch(e) { continue; }
            const path = abs.pathname;
            if (!/(?:\/products?\/|\/p\/|\/item\/)/i.test(path)) continue;
            abs.search = ''; abs.hash = '';
            if (seen.has(abs.href)) continue;
            const visible = el => !!(el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden');
            if (!visible(a)) continue;
            let tile = a;
            for(let i=0;i<5 && tile.parentElement;i++) {
              const candidate = tile.parentElement;
              if (candidate === root || candidate === document.body) break;
              if ((candidate.innerText || '').length > 1400) break;
              tile = candidate;
              if (/(£|\$|€)\s?\d[\d,.]*/.test(tile.innerText || '') &&
                  (tile.querySelector('img') || tile.querySelector('h2,h3,h4'))) break;
            }
            const words = (tile.innerText || '').trim();
            const price = words.match(/(?:£|\$|€)\s?\d[\d,.]*/);
            if (!price || words.length > 1000) continue;
            const heading = tile.querySelector('h2,h3,h4,[class*="title" i],[class*="name" i]');
            const name = ((heading && heading.innerText) || a.getAttribute('aria-label') || a.innerText || a.querySelector('img')?.alt || '').trim();
            if (!name || name.length > 170) continue;
            seen.add(abs.href);
            rows.push({name:name.slice(0,150), url:abs.href, price:price[0],
              sold_out_badge:/\b(out of stock|sold out|currently unavailable|unavailable online)\b/i.test(words)});
          }
          return rows;
        }''')
        if len(fallback) > len(best):
            best = fallback[:cap]
    return best


def visible_search_heading(page):
    '''Capture a visible search heading without claiming it is a product result.'''
    try:
        root = page.locator('main,[role="main"]').first
        if not root.count():
            root = page.locator('body').first
        heads = root.locator('h1,h2,[role="heading"]').all()[:12]
        for h in heads:
            if h.is_visible():
                label = re.sub(r'\s+', ' ', h.inner_text(timeout=1000)).strip()
                if 8 < len(label) <= 450:
                    return label
    except Exception:
        pass
    return ''


def detect_sort(page):
    '''Both native selects and custom buttons/comboboxes count as UI visibility.'''
    native = visible_first(page, 'select[name*="sort" i], select[id*="sort" i], select[aria-label*="sort" i]')
    if native is not None:
        return 'visible_native', native
    selectors = [
        'button[aria-label*="sort" i]', '[role="combobox"][aria-label*="sort" i]',
        'button[class*="sort" i]', '[class*="sort" i][role="button"]',
        'summary[class*="sort" i]', 'select[class*="sort" i]',
        '[class*="sort-by" i]', '[data-testid*="sort" i]',
    ]
    for selector in selectors:
        el = visible_first(page, selector)
        if el is not None:
            return 'visible_custom', None
    main = page.locator('main,[role="main"]').first
    try:
        if main.count():
            matches = main.get_by_text(re.compile(r'^sort\s*by\b', re.I))
            for idx in range(min(matches.count(), 12)):
                if matches.nth(idx).is_visible():
                    return 'visible_custom', None
    except Exception:
        pass
    return 'not_detected', None


def test_sort(page, before, pause):
    control, select = detect_sort(page)
    if control != 'visible_native':
        return ('visible' if control == 'visible_custom' else 'not_detected',
                'custom_control_not_interacted' if control == 'visible_custom' else 'not_tested')
    try:
        options = select.locator('option')
        available = [(options.nth(i).get_attribute('value'), options.nth(i).inner_text().strip())
                     for i in range(min(options.count(), 20))]
        current = select.input_value()
        target = next(((v, t) for v,t in available if v and v != current and
                       re.search(r'price|alphabet|name',t,re.I)), None)
        if not target:
            return 'visible', 'unverified_no_suitable_option'
        select.select_option(value=target[0], timeout=4000)
        page.wait_for_timeout(800)
        time.sleep(max(0, pause))
        selected = select.input_value() == target[0] if select.count() else False
        after = extract_products(page)
        changed = bool(before and after and [p['url'] for p in before[:4]] != [p['url'] for p in after[:4]])
        return 'visible', ('accepted_and_reordered' if changed else
                           'selection_changed_order_unverified' if selected else 'inconclusive')
    except Exception:
        return 'visible', 'inconclusive'


def detect_filters(page):
    '''Return presence and explicit labels, including visually labelled facets.'''
    selectors = [
        'button[aria-label*="filter" i]', 'button[class*="filter" i]',
        '[role="button"][aria-label*="filter" i]', 'summary[class*="filter" i]',
        'fieldset input[type="checkbox"]', '[class*="facet" i] input[type="checkbox"]',
        '[class*="filter" i] input[type="checkbox"]',
        '[class*="facets" i]', '[data-testid*="filter" i]',
    ]
    explicit = any(visible_first(page,s) is not None for s in selectors)
    try:
        scope = page.locator('main,[role="main"]').first
        if not scope.count():
            scope = page.locator('body')
        entries = scope.evaluate(r'''(root) => {
          const labels = ['Availability','Price','Colour','Color','Size','Brand','Compatibility',
            'Material','Width','Height','Depth','Category','Product Type','Shop By'];
          const found = new Set();
          const els = root.querySelectorAll('button,summary,legend,label,select,[role="button"],[role="checkbox"],h2,h3,h4');
          for(const el of els) {
            if (!(el.getClientRects().length)) continue;
            let text = (el.innerText || el.textContent || '').trim().replace(/\s+/g,' ');
            for(const name of labels) {
              if (text.toLowerCase() === name.toLowerCase() ||
                  text.toLowerCase().startsWith(name.toLowerCase() + ' (')) found.add(name);
            }
          }
          return Array.from(found);
        }''')
    except Exception:
        entries = []
    return ('visible' if explicit or len(entries) >= 2 else 'not_detected', ', '.join(entries[:10]))


def zero_results_test(page, website, template, cache, pause):
    needle = 'zzzxqrareproduct'
    method, url, _ = do_search(page, needle, template, website, cache, pause)
    if method == 'not_available':
        return 'unavailable', ''
    content = safe_body(page, 'main', 12000) or safe_body(page, 'body', 12000)
    if NO_RESULTS_TEXT.search(content):
        return 'clear_message_detected', page.url
    cards = extract_products(page)
    if cards:
        return 'results_returned_review_relevance', page.url
    return 'inconclusive_manual_review', page.url


def split_queries(row):
    '''Accept original 'query' and optional pipe-delimited 'queries', max 3.'''
    base = (row.get('query') or '').strip()
    extra = (row.get('queries') or '').split('|')
    values = [base] + extra
    result = []
    for q in values:
        q = q.strip()
        if q and q.casefold() not in {x.casefold() for x in result}:
            result.append(q[:90])
    return result[:3]


def priority_for(audit):
    '''Research triage only; never represents proven commercial value or defects.'''
    if audit.status != 'tested':
        return 'Unrated', 'Insufficient evidence'
    # Presence of labelled unavailable tiles or anomalous term overlap is a
    # prompt for human checking, not evidence of lost conversions.
    coverage = audit.queries_tested
    flagged = sum(o['type'] == 'review_signal' for o in audit.observations)
    priority = 'P1' if flagged >= 2 and coverage >= 2 else 'P2' if flagged >= 1 else 'P3'
    quality = 'Good sample' if coverage >= 2 else 'Limited sample'
    return priority, quality

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


def _record_observations(audit, q):
    if re.search(r'(?<!\w)-(?:tag|type|collection|filter)\s*:', q.get('search_heading',''), re.I):
        audit.observations.append({'type': 'review_signal', 'query': q['query'],
                                   'text': 'Customer-facing search heading contains technical filter syntax; verify visually'})
    if q['product_cards_detected']:
        audit.observations.append({
            'type': 'fact', 'query': q['query'],
            'text': f"Sampled {q['product_cards_detected']} identifiable product tiles for query '{q['query']}'",
        })
        if q['out_of_stock_cards']:
            audit.observations.append({
                'type': 'review_signal', 'query': q['query'],
                'text': f"{q['out_of_stock_cards']} of {q['product_cards_detected']} sampled tiles explicitly labelled unavailable; this may be intentional",
            })
        if q['query_title_overlap'].startswith('0/'):
            audit.observations.append({
                'type': 'review_signal', 'query': q['query'],
                'text': 'Sample titles did not contain query terms; synonyms or product context may fully explain this',
            })
    if q['sort_control'] == 'visible':
        audit.observations.append({'type': 'fact', 'query': q['query'],
                                   'text': 'A visible sort control was detected'})
    if q['filter_control'] == 'visible':
        audit.observations.append({'type': 'fact', 'query': q['query'],
                                   'text': 'Visible filtering controls/facets were detected'})


def test_site(browser, row, out, robots_cache, pause, screenshot=True):
    company = (row.get('company') or '').strip()
    website = valid_website(row['website'])
    queries = split_queries(row)
    if not queries:
        raise ValueError('At least one search query required')
    template = (row.get('search_url_template') or '').strip()
    audit = Audit(company=company, website=website, query=queries[0],
                  checked_utc=datetime.now(timezone.utc).isoformat(timespec='seconds'))
    context = browser.new_context(user_agent=USER_AGENT, viewport={'width': 1440, 'height': 900},
                                  locale='en-GB', timezone_id='Europe/London', service_workers='block')
    page = context.new_page()
    page.set_default_timeout(4500)
    try:
        notes = []
        for number, query in enumerate(queries, 1):
            qr = {'query':query, 'status':'inconclusive', 'search_method':'unknown',
                  'search_url':'', 'search_input_found':'unknown', 'product_cards_detected':0,
                  'products':[], 'out_of_stock_cards':0, 'query_title_overlap':'not_assessed',
                  'sort_control':'unknown', 'sort_test':'not_tested', 'filter_control':'unknown',
                  'filter_labels':'', 'overlay_action':'none', 'screenshot':'', 'search_heading':'', 'notes':''}
            try:
                note = load_public(page, website, robots_cache, pause)
                if number == 1:
                    notes.append(note)
                qr['overlay_action'] = dismiss_overlays(page)
                method, searchurl, found = do_search(page, query, template, website, robots_cache, pause)
                qr['search_method'], qr['search_url'], qr['search_input_found'] = method, searchurl, found
                if method == 'not_available':
                    qr['notes'] = 'Search control not recognised; manual review required (homepage screenshot only, not search evidence)'
                    # A screenshot still lets sales staff inspect the visible storefront.
                    # Do not label it as search testing or score any defect from it.
                    if screenshot and number == 1:
                        name = f'screenshots/{safe_slug(company)}-homepage.png'
                        try:
                            page.screenshot(path=str(out / name), animations='disabled',
                                            full_page=False, timeout=8000)
                            qr['screenshot'] = name
                        except Exception as e:
                            qr['notes'] += f' Screenshot unavailable ({type(e).__name__}).'
                    audit.queries_inconclusive += 1
                else:
                    qr['search_url'] = page.url
                    qr['search_heading'] = visible_search_heading(page)
                    qr['products'] = extract_products(page)
                    qr['product_cards_detected'] = len(qr['products'])
                    qr['out_of_stock_cards'] = sum(p['sold_out_badge'] for p in qr['products'])
                    qr['query_title_overlap'] = query_overlap(query, qr['products'])
                    qr['filter_control'], qr['filter_labels'] = detect_filters(page)
                    if screenshot:
                        name = f'screenshots/{safe_slug(company)}-query-{number}.png'
                        try:
                            page.screenshot(path=str(out / name), animations='disabled',
                                            full_page=False, timeout=8000)
                            qr['screenshot'] = name
                        except Exception as e:
                            qr['notes'] += f'Screenshot unavailable ({type(e).__name__}). '
                    qr['sort_control'], qr['sort_test'] = test_sort(page, qr['products'], pause)
                    if qr['product_cards_detected']:
                        qr['status'] = 'tested'
                        audit.queries_tested += 1
                    else:
                        qr['notes'] += 'No recognisable product tiles; no relevance or ranking conclusion made.'
                        audit.queries_inconclusive += 1
                    _record_observations(audit, qr)
            except Exception as e:
                msg = str(e)
                qr['notes'] = msg[:300]
                audit.queries_inconclusive += 1
                if msg.startswith('ROBOTS_BLOCKED'):
                    audit.status = 'robots_blocked'
                elif msg.startswith('ACCESS_BLOCKED'):
                    audit.status = 'access_blocked'
                elif msg.startswith('SITE_ERROR'):
                    audit.status = 'site_error'
                # Hard stop on restrictions, no follow-up probes.
            audit.query_results.append(qr)
            if audit.status in ('robots_blocked', 'access_blocked', 'site_error'):
                notes.append(qr['notes'])
                break
        if audit.status not in ('robots_blocked', 'access_blocked', 'site_error'):
            audit.status = 'tested' if audit.queries_tested else 'inconclusive'
        first = audit.query_results[0] if audit.query_results else None
        if first:
            for name in ('search_method','search_url','search_input_found','product_cards_detected',
                         'sort_control','sort_test','filter_control','out_of_stock_cards',
                         'query_title_overlap','screenshot','overlay_action','filter_labels'):
                setattr(audit, name, first[name])
            audit.products = first['products']
            audit.sample_products = ' | '.join(p['name'] for p in first['products'][:5])
        audit.screenshots = ' | '.join(q['screenshot'] for q in audit.query_results if q['screenshot'])
        if audit.status == 'tested':
            try:
                load_public(page, website, robots_cache, pause)
                dismiss_overlays(page)
                audit.zero_results_state, audit.zero_results_url = zero_results_test(
                    page, website, template, robots_cache, pause)
                if audit.zero_results_state == 'clear_message_detected':
                    audit.observations.append({'type':'fact', 'query':'no-results test',
                                               'text':'Clear empty-results message detected'})
            except Exception as e:
                audit.zero_results_state = 'inconclusive_manual_review'
                notes.append('Empty-results probe unavailable: '+str(e)[:130])
        audit.review_priority, audit.evidence_quality = priority_for(audit)
        signals = [o['text'] for o in audit.observations if o['type'] == 'review_signal']
        audit.signals = ' | '.join(signals[:3]) if signals else (
            'No independently confirmed weakness; exploratory discussion only' if audit.status == 'tested'
            else 'Insufficient evidence; do not infer website weakness')
        if audit.status == 'tested':
            flagged = next((o for o in audit.observations if o['type']=='review_signal'), None)
            if flagged and flagged['text'].startswith(tuple('0123456789')):
                audit.outreach_angle = ('I was reviewing how your site handles availability within search results. '
                                        'How does your ecommerce team decide which items should surface first?')
            elif flagged:
                audit.outreach_angle = ('I was exploring your onsite search results for '+ flagged['query'] +
                                        '. How does your team currently measure search relevance?')
            else:
                audit.outreach_angle = ('I was looking at how customers find products in your '+queries[0]+
                                        ' range. Is onsite discovery a priority for your team?')
        else:
            audit.outreach_angle = 'No evidence-backed outreach claim; verify the site manually first'
        audit.notes = ' | '.join(notes + [q['notes'] for q in audit.query_results if q['notes']])[:1200]
    finally:
        context.close()
    return audit


def html_report(audits, output):
    date = html.escape(datetime.now(timezone.utc).strftime('%d %b %Y · %H:%M UTC'))
    tested = sum(a.status == 'tested' for a in audits)
    priority = sum(a.review_priority in ('P1', 'P2') for a in audits)
    blocked = sum(a.status in ('robots_blocked','access_blocked') for a in audits)
    escape = lambda value: html.escape(str(value), quote=True)
    cards = []
    for a in audits:
        observations = ''.join('<li class="obs"><span class="kind '+escape(o['type'])+'">'+
            ('Review' if o['type']=='review_signal' else 'Observed')+'</span> '+escape(o['text'])+'</li>'
            for o in a.observations[:14]) or '<li>Insufficient automated evidence.</li>'
        queries = []
        for q in a.query_results:
            products = ''.join('<li><a target="_blank" rel="noopener noreferrer" href="'+escape(p['url'])+'">'+
                escape(p['name'])+'</a> <span class="muted">'+escape(p['price'])+
                (' · Labelled unavailable' if p['sold_out_badge'] else '')+'</span></li>' for p in q['products'][:12])
            shot = ('<a target="_blank" rel="noopener noreferrer" href="'+escape(q['screenshot'])+
                    '">View evidence screenshot ↗</a>' if q['screenshot'] else 'No screenshot available')
            queries.append('<details><summary><b>'+escape(q['query'])+'</b> · '+escape(q['status'])+
                  ' · '+str(q['product_cards_detected'])+' sampled cards</summary><div class="detail">'+
                  '<p><b>Search:</b> '+escape(q['search_method'])+' · <b>Overlap:</b> '+escape(q['query_title_overlap'])+'</p>'+
                  '<p><b>Sort:</b> '+escape(q['sort_control']+' / '+q['sort_test'])+
                  ' · <b>Filters:</b> '+escape(q['filter_control'])+' '+escape(q['filter_labels'])+'</p>'+
                  '<p><b>Overlay:</b> '+escape(q['overlay_action'])+' · <b>Notes:</b> '+escape(q['notes'])+'</p>'+
                  '<p>'+shot+'</p><ul>'+products+'</ul></div></details>')
        grade = a.review_priority if a.review_priority!='Unrated' else 'Not assessed'
        gradeclass = 'grade p1' if grade=='P1' else 'grade p2' if grade=='P2' else 'grade'
        cards.append('<article class="card"><div class="top"><div><h2>'+escape(a.company)+'</h2><a class="small" target="_blank" rel="noopener noreferrer" href="'+escape(a.website)+'">'+escape(a.website)+'</a></div><span class="'+gradeclass+'">'+escape(grade)+'</span></div>'+
            '<div class="meta"><span>Status: '+escape(a.status)+'</span><span>Evidence: '+escape(a.evidence_quality)+'</span><span>Searches tested: '+str(a.queries_tested)+'/'+str(len(a.query_results))+'</span></div>'+
            '<h3>What was actually observed</h3><ul>'+observations+'</ul><h3>Suggested discovery question (not a claim)</h3><p>'+escape(a.outreach_angle)+'</p>'+
            '<h3>Search evidence</h3>'+''.join(queries)+'<p class="small">No-results: '+escape(a.zero_results_state)+
            ' · Notes: '+escape(a.notes)+'</p></article>')
    doc=r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Remarkable — Search & Merch Research Audit</title><style>
    :root{--bg:#f4f6f9;--dark:#14213d;--ink:#1c2941;--muted:#66758b;--line:#dce4ed;--accent:#e7a944}
    *{box-sizing:border-box}body{background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,-apple-system,Segoe UI,sans-serif;margin:0}
    header{background:var(--dark);color:#fff;padding:36px max(24px,calc((100vw - 1040px)/2))}header small{color:#f7c875;letter-spacing:.14em;font-weight:bold}header h1{font-size:30px;margin:8px 0}header p{max-width:850px;color:#d3dbea}
    main{max-width:1080px;margin:28px auto;padding:0 18px}.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
    .stat{background:#fff;border:1px solid var(--line);border-radius:12px;padding:15px}.stat b{font-size:28px;display:block}.stat span,.small,.muted{color:var(--muted);font-size:12px}
    .disclaimer{background:#fff;border-left:4px solid var(--accent);padding:14px 18px;margin:20px 0;border-radius:6px}.disclaimer b{display:block}
    .card{background:#fff;border:1px solid var(--line);border-radius:14px;padding:22px;margin-bottom:16px;box-shadow:0 4px 16px #14213d08}
    .top{display:flex;justify-content:space-between;gap:12px;align-items:start}.top h2{font-size:20px;margin:0}.meta{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0;color:var(--muted)}.meta span{background:#f2f4f8;border-radius:6px;padding:4px 9px;font-size:12px}
    h3{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:#596a82;margin:18px 0 6px}.grade{background:#e7edf4;color:#485c72;padding:5px 10px;border-radius:16px;white-space:nowrap;font-weight:700;font-size:12px}
    .p1{background:#fce9e4;color:#a33c26}.p2{background:#fff2d7;color:#805a14}a{color:#0e5b91;overflow-wrap:anywhere}.obs{margin:6px 0}.kind{font-size:10px;padding:3px 6px;border-radius:4px;background:#e8f5ef;color:#2c7252;font-weight:bold}.kind.review_signal{background:#fff2d7;color:#805a14}
    details{border-top:1px solid var(--line);padding:10px 0}summary{cursor:pointer}summary:hover{color:#125786}.detail{padding:2px 12px}ul{padding-left:22px}li{margin:4px 0}footer{padding:18px 0 42px;color:var(--muted);font-size:12px}
    @media(max-width:660px){.stats{grid-template-columns:repeat(2,minmax(0,1fr))}.top{flex-direction:column}header h1{font-size:24px}}
    </style></head><body><header><small>REMARKABLE COMMERCE · RESEARCH ONLY</small><h1>Search & merchandising prospect research</h1><p>Low-volume browser observations, not proof of poor onsite search, lost revenue or an ineffective provider. Every sales claim needs human verification.</p><p>__DATE__</p></header><main>
    <section class="stats"><div class="stat"><b>__TOTAL__</b><span>Sites supplied</span></div><div class="stat"><b>__TESTED__</b><span>At least one search sampled</span></div><div class="stat"><b>__PRIORITY__</b><span>Review signals (P1/P2)</span></div><div class="stat"><b>__BLOCKED__</b><span>Robots/access blocked</span></div></section>
    <div class="disclaimer"><b>Priority means review priority, not deal quality.</b>P1/P2 are prompts for a manual investigation only. A site ranked P3 isn't necessarily high-performing. A blocked or inconclusive site is not automatically weak. Cookie/location overlays are only dismissed using safe choices; anti-bot challenges are never bypassed.</div>
    __CARDS__<footer>Generated evidence is a small sample. Human review is required before any prospect outreach. Search queries, screenshots and returned URLs are retained for traceability.</footer></main></body></html>'''
    doc = (doc.replace('__DATE__',date).replace('__TOTAL__',str(len(audits)))
           .replace('__TESTED__',str(tested)).replace('__PRIORITY__',str(priority))
           .replace('__BLOCKED__',str(blocked)).replace('__CARDS__',''.join(cards)))
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
    per_query_columns = ['company','website','review_priority','query','status','search_method',
                         'search_url','product_cards_detected','out_of_stock_cards','query_title_overlap',
                         'sort_control','sort_test','filter_control','filter_labels','overlay_action','search_heading','screenshot','notes']
    with (out / 'query_audit.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer = csv.DictWriter(f, fieldnames=per_query_columns)
        writer.writeheader()
        for a in audits:
            for q in a.query_results:
                writer.writerow({k:(a.company if k=='company' else a.website if k=='website' else
                                    a.review_priority if k=='review_priority' else q.get(k,''))
                                 for k in per_query_columns})
    (out / 'evidence.json').write_text(json.dumps([asdict(a) for a in audits], indent=2, ensure_ascii=False),encoding='utf-8')
    html_report(audits,out / 'report.html')
    print(f'\nCreated HTML report, site CSV, query CSV and evidence.json in {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
