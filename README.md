# Remarkable Commerce | Search & Merch Prospecting v5

## What's new

This update expands the existing six-site proof of concept to **20 curated UK retailer websites** and adds a commercial reporting layer.

- `prospects.csv`: 20 target websites with three realistic, low-volume search queries each.
- `prospect_context.csv`: pre-research hypotheses, suggested first product (Search, Merch, Both), buyer role and category. All platform technology remains **Unverified**. These are fit hypotheses, not claims about website problems, current vendors or budgets.
- `sales_opportunities.html`: screenshot-led, sales-facing HTML cards with evidence, hypothesis, persona and a **draft** LinkedIn opener.
- `sales_ready_shortlist.csv`: only accounts with usable public evidence and an actual local screenshot. Review-first anomalies require human verification before use. Other accounts are discovery-fit, not defects.
- `all_target_status.csv`: includes every scanned retailer and states why excluded ones were set aside.
- The existing `opportunity_dashboard.html` and technical evidence exports remain unchanged.

**Important:** Automated checks never send messages, create contacts, bypass robots.txt, access private accounts or infer lost revenue. A public site's automated access restriction is a hard stop, not a challenge to work around. The retailer's current search/commerce platform must be independently verified before platform-specific outreach. Check the account against Remarkable's current clients and HubSpot opportunities before outbound.

## Install in existing repo

Upload `Remarkable_Search_Merch_v5.zip` to the Codespaces workspace for `JacobRemarkable/searchandmerch`, then run:

```bash
cd /workspaces/searchandmerch
unzip -o Remarkable_Search_Merch_v5.zip -d .
git add auditor.py prospect_dashboard.py commercial_outreach.py prospects.csv prospect_context.csv README.md requirements.txt tests .github/workflows/audit.yml
git commit -m "Expand Remarkable prospect audit to 20 retailers and add sales shortlist"
git push origin main
```

Launch **GitHub → Actions → Remarkable prospect website audit → Run workflow**, branch `main`.

Tests run on GitHub's Ubuntu runner before website checks. You do not need to configure Chromium in Codespaces locally. The workflow has a 45-minute timeout; it may finish faster. If it times out, reduce the input to 10 sites and rerun the remaining 10 separately.

## Results

Download the **remarkable-prospect-audit** artifact from the completed GitHub Action, unzip it, and open:

- `sales_opportunities.html` — start here. Screenshot, signal, context, decision-maker and draft LinkedIn message.
- `sales_ready_shortlist.csv` — evidence-backed, triaged rows ready for human review before HubSpot import.
- `all_target_status.csv` — all scanned sites and why any were set aside.
- `opportunity_dashboard.html` — previous technical/prospecting board.
- `query_audit.csv`, `prospect_audit.csv`, `evidence.json`, `screenshots/` — supporting evidence.

**The first 20-site audit has not yet been run.** The proof-of-concept sales report was tested against a completed six-site Version 4 run, with four included and two excluded.

## How to maintain

When adding brands, keep `prospects.csv` and `prospect_context.csv` aligned by exact company name. Each `lead_with` value must be `Search`, `Merch`, or `Both`. The workflow is currently capped at 20 websites/run. Respect site access restrictions, keep volume modest and do not publish confidential CRM information in this public repository. Consider switching it to private.
