# Remarkable Commerce — Prospect Website Auditor v2

**Search & Merch prospect research, not website fault-finding.** This is a low-volume browser-based auditor for *public retail websites*. Its purpose is to give Remarkable/Beanstalk a better-informed conversation opener. It cannot prove conversion impact, lost revenue or an ineffective search solution.

## Upgrade your existing GitHub repository

Repository: `https://github.com/JacobRemarkable/searchandmerch`

1. Download `Remarkable_Website_Auditor_v2.zip` and upload it to the Codespaces file explorer **inside** `/workspaces/searchandmerch`.
2. Open the Codespaces terminal and run:

```bash
cd /workspaces/searchandmerch
unzip -o Remarkable_Website_Auditor_v2.zip -d .
python -m py_compile auditor.py
git add auditor.py requirements.txt prospects.csv README.md tests .github/workflows/audit.yml
git commit -m "Upgrade Remarkable auditor to v2"
git push origin main
```

3. Open **GitHub → searchandmerch → Actions → Remarkable prospect website audit → Run workflow**, with branch `main`.
4. Once it finishes, download the **remarkable-prospect-audit** artifact. Unzip it, then open `report.html`.

The workflow now **runs offline tests before** accessing any websites. If the tests fail, the browser audit is not attempted.

## What's new in v2

- **Overlay handling:** recognises explicit cookie/location pop-ups and may choose *Reject all / Necessary only* or **UK** when appropriate. It does **not** accept optional marketing cookies or bypass anti-bot challenges.
- **Broader search detection:** sees visible search fields, accessible search controls, search toggles and several common icon-only header buttons.
- **Product tile fallback:** samples up to 12 actual product-like items per search, using structured selectors and conservative product-link/price recognition when the layout is unfamiliar.
- **Custom sort and filter recognition:** detects both native selectors and custom "Sort By" controls; captures explicit filter labels such as Availability, Price, Colour, Size, Compatibility and Material. Custom sort controls are *observed*, not auto-clicked.
- **Multiple searches per retailer:** original required `query` plus optional `queries` separated by `|`, **maximum three per retailer**. Each query gets its own screenshot.
- **Two levels of export:** `prospect_audit.csv` (one row per company), `query_audit.csv` (one row per search), `evidence.json`, and `report.html` with evidence links.
- **P1/P2/P3 research priority:** automatically sorts *review signals*, not deal size, confirmed problems, or likelihood to buy. A site with incomplete tests is marked **Unrated**. All outreach angles are phrased as discovery questions, not accusations.
- **Offline browser tests:** covers overlays, consent, custom search, custom filters/sort, structured product discovery, multi-query grading and robots restrictions.

## Editing the CSV

```csv
company,website,query,queries,search_url_template
Example Shop,https://www.example.com,red shoes,leather boots|trainers,
```

- `company`, `website` and `query` are required (the old CSV format **still works**).
- `queries` is optional. Separate additional searches with `|`; maximum 3 in total. Don't use searches containing personal information.
- `search_url_template` is optional for known, verified search URLs, e.g. `https://www.example.com/search?q={query}`. The template must stay on the same host and obey robots.txt.
- Keep the batch small (5–20 shops). The workflow has a 45-minute maximum runtime.
- Scraping contacts, logging in, submitting orders, defeating bot checks or ignoring robots.txt is **not permitted** by the script.

## How to interpret the new report

**Observed:** Directly detected in the browser (e.g. "12 product cards sampled", "visible sort control", "2 cards labelled sold out").

**Review signal:** Something to inspect as a human (e.g. a sold-out tile or low literal query-term overlap). The retail site may be deliberately configured that way and the observation is not evidence of a mistake.

**Inconclusive:** The auditor couldn't reliably complete a test. It does **not** mean search is bad or broken. When a site blocks automated checks, the audit stops and its status is `robots_blocked` / `access_blocked`.

**Priority** is for deciding which accounts to research next, not for making claims. P1: multiple review signals across at least 2 tested queries; P2: at least 1 review signal; P3: sample completed without a review signal; Unrated: insufficient evidence.

## Outputs

| File | Use |
|---|---|
| `report.html` | Clear research report with observed findings, query screenshots and possible commercial conversation starters |
| `prospect_audit.csv` | One row per retailer for an initial HubSpot/company research list |
| `query_audit.csv` | Individual query-by-query data suitable for internal review |
| `evidence.json` | Full structured audit, observed product samples, flags and URLs |
| `screenshots/` | Screenshot evidence per query |

This is **not live-audited** from the development environment. The GitHub Actions run is the real-world check. Before Beanstalk uses a finding, a person must inspect the screenshot and verify the site behaviour.

## Privacy and rollout

Your GitHub repo is currently public. Please switch it to **private** before adding commercial prospect notes, account contacts or other confidential information. The supplied starter CSV has public company names and URLs only.

The recurring weekly schedule remains **disabled** while version 2 is being validated. You can enable it manually in `.github/workflows/audit.yml` after checking the first set of live results. For any changes to a website, verify new results rather than relying on older screenshots.
