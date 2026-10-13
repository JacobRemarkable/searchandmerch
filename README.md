# Remarkable Commerce — Search & Merch Prospect Opportunity Board (v3)

**Purpose:** Find a credible reason to contact a retailer. This is a visual sales-research tool, not a technical site-quality score or a proof of lost conversions.

The browser auditor checks a few public search results, records screenshots and samples the visible product tiles. The new **Opportunity Board** puts those screenshots next to a short Search angle, Merch angle and LinkedIn discovery question.

## Install v3 in your existing GitHub Codespace

Upload `Remarkable_Opportunity_Board_v3.zip` to your Codespace, then run:

```bash
cd /workspaces/searchandmerch
unzip -o Remarkable_Opportunity_Board_v3.zip -d .
python -m py_compile auditor.py prospect_dashboard.py
git add auditor.py prospect_dashboard.py README.md prospects.csv requirements.txt tests .github/workflows/audit.yml
git commit -m "Add Remarkable Search and Merch opportunity board"
git push origin main
```

Open [GitHub Actions](https://github.com/JacobRemarkable/searchandmerch/actions/workflows/audit.yml), choose **Run workflow**, select `main`, and run. The workflow executes local tests before the live scan.

On completion, download and **extract** the `remarkable-prospect-audit` artifact. Open **`opportunity_dashboard.html`**; this is the main sales-facing report. Extracting matters, because screenshots are in the adjacent `screenshots/` folder.

## What the new board shows

- **Review first:** A visible signal may be worth investigating (e.g., unavailable products in sampled results, very low literal title-term overlap, or technical exclusion syntax displayed in the search heading). This is **not a confirmed defect**.
- **Discovery fit:** Search results were observed and could support a Search/Merch conversation, but **no specific defect was identified**.
- **Manual review:** The test was inconclusive or the site restricted automated access. The auditor won't label it poorly performing or invent a weakness. For permitted storefronts where search is not recognised, v3 now saves a homepage-only screenshot to aid manual inspection.
- **Screenshot-first cards:** View the search-results screenshot, sampled products, the question to ask, and a link to the result page. The user can filter by lead category and copy the opener.

## Outputs

| File | What to do with it |
|---|---|
| `opportunity_dashboard.html` | **Start here.** Visual, sortable-by-priority opportunity cards and screenshots |
| `opportunity_shortlist.csv` | One retailer per row. Paste/import the prospecting angles into HubSpot |
| `report.html` | Original evidence-centric technical report (v2, retained) |
| `prospect_audit.csv` | One row per retailer with raw audit signals |
| `query_audit.csv` | One row per search query (includes captured search heading) |
| `evidence.json` | Full structured observations; use to regenerate the board |
| `screenshots/` | The actual browser screenshots; keep next to HTML when sharing |

## Add prospects

Edit `prospects.csv` (no coding required):

```csv
company,website,query,queries,search_url_template
Example Store,https://www.example.com,red boots,leather boots|women's trainers,
```

`company`, `website` and `query` are required. `queries` adds up to two extra searches separated with `|` (max three total). The last column is optional, for a **verified** search URL template like `https://www.example.com/search?q={query}`. A template is checked against robots.txt like any other page.

Keep batches at 5–20 stores; the GitHub job times out after 45 minutes. `robots.txt`, CAPTCHA, access blocks, logins, private pages, purchases and automated contact extraction remain off-limits.

## Sales-team use: 3-minute validation before outreach

1. Open an account card and enlarge its screenshot.
2. Repeat the query in a normal browser. Make sure the observed issue is real, still present, and not an intentional ecommerce choice.
3. If there is no verified issue, talk about opportunities and business objectives **without claiming the site is broken**.
4. Log the result in HubSpot and use the provided discovery question, personalised to the observation.

The board avoids fake conversion scores, made-up potential ROI and unverified competitive technology claims. A low keyword/title match is a **weak heuristic**, since valid synonyms and product descriptions may not contain the query words. A visible sort/filter control is **not** evidence of a problem.

## Offline processing (without rescanning)

If you have an old report artifact and want the new opportunity view:

```bash
python prospect_dashboard.py --input results/evidence.json --out results
```

The scheduled workflow remains **disabled** until real-world accuracy has been checked. The GitHub repository is currently public; make it private before placing confidential prospect research or client information in the repo.
