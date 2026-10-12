# Remarkable Commerce — Prospect Website Auditor

An evidence-first, *low-volume* browser check for **public retailer websites**. Designed to support personal LinkedIn prospecting, **not** to assert that a retailer has poor search or to produce a scientifically valid conversion score.

## What it does

For every company in `prospects.csv`, it opens the public homepage and attempts a genuine onsite search for your chosen query. It then:

- records the **observed search URL** and a screenshot of the first result page;
- samples up to **eight visible product tiles** where the page's markup is recognisable;
- detects explicitly labelled **out-of-stock / sold-out** tiles (visibility isn't automatically bad);
- detects visible **sort and filtering controls**;
- attempts a native **sort dropdown interaction** where available;
- tests a harmless, improbable search term and detects whether a **clear no-results message** appears;
- creates a standalone `report.html`, Excel-friendly `prospect_audit.csv`, and `evidence.json`.

Each report differentiates observed facts from unknowns. It **does not** prove that sorting is correct, that filters work as users expect, that a search result is genuinely irrelevant, that a retailer uses a particular search vendor, or that a merchandising issue reduces revenue. Sites built with unusual components will often need human inspection or a site-specific adapter.

## Easiest option — GitHub (no command line required after setup)

1. Create a **new private GitHub repository**. Don't add this to FormationHUB or another unrelated project.
2. Upload the contents of this folder, **including** `.github/workflows/audit.yml` (keep the folder structure).
3. Edit `prospects.csv` with the retailer/company, public website URL, and **one ordinary product search term**. Optional `search_url_template` supports a search URL you have verified; use `{query}` as the placeholder.
4. Open your repository's **Actions** tab → **Remarkable prospect website audit** → **Run workflow**.
5. After the run, click **remarkable-prospect-audit** under **Artifacts** to get `report.html`, `prospect_audit.csv`, `evidence.json`, and screenshots. **Unzip everything first**; open `report.html` in a browser so the screenshot links work.

The schedule is **off by default**. To enable a weekly scan, uncomment the `schedule` lines in `.github/workflows/audit.yml`. GitHub scheduled workflow times are in UTC and may be delayed. Scheduled actions need a repository with workflows permitted by your organisation.

## Run locally (Mac / Windows)

Prerequisites: Python 3.12+ and an internet connection.

```bash
pip install -r requirements.txt
python -m playwright install chromium
python auditor.py --input prospects.csv --out results
```

Open `results/report.html`. Import the CSV into HubSpot or Excel if useful.

## Input columns

| Column | Required | Example |
|---|---|---|
| company | Yes | First4Magnets |
| website | Yes | https://www.first4magnets.com |
| query | Yes | neodymium magnets |
| search_url_template | No | https://example.com/search?q={query} |

Keep to around 5–20 relevant domains per run. One query, one no-results query and (where applicable) one sort action per domain. The tool uses a minimum one-second delay on each request and respects robots.txt. It doesn't log in, accept marketing cookies, add to basket, submit orders or bypass bot challenges. If robots or anti-bot controls prevent testing, it records that and stops. Test websites only with a legitimate business purpose, and respect each site's usage policies.

## Turning an audit into a sensible LinkedIn opening

- **Observed fact:** “I was reviewing how product filters work across your shelving range.”
- **Question:** “How much of a focus is specification-based product discovery for your ecommerce team?”
- **Offer:** “Happy to share a couple of practical ideas if it’s relevant.”

Never tell a prospect their search is "broken" from a heuristic report. An out-of-stock item in results could be intentional. A zero title-token match could be correct due to synonyms, product codes or category intent.

## What I'd add in V2

- Add site-specific adapters to test exact user journeys (e.g. size, dimension, compatibility).
- Capture mobile vs desktop screenshots and Core Web Vitals from established measurement services.
- Connect to HubSpot *after* deduplicating company records and approving the outreach observations.
- Build a small web form so Beanstalk can submit URLs and retrieve the evidence pack without visiting GitHub.

## Troubleshooting

- **`search input not detected`:** Search might be hidden behind a nonstandard icon, built inside a custom component, or require a verified `search_url_template` in the CSV.
- **`robots_blocked` / `access_blocked`:** Leave it untested. Do not try to evade the restriction.
- **No tiles detected:** Generic product markup isn't consistent across sites. You can still review the screenshot. This is *not* the same as a zero-result search.
- **No reordering after selecting sort:** The report marks it *unverified*, not broken.
- **GitHub Actions absent:** Check that Actions is enabled for the repository, and that `.github/workflows/audit.yml` was uploaded to the default branch.
