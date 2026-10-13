# Remarkable Commerce — Search & Merch Opportunity Board v4

**Purpose:** turn a short list of retailer domains into evidence-backed prospecting conversations without assigning manual work to every site that cannot be tested.

## What changed

- Recognises more *unlabelled magnifying-glass SVG* search triggers (where the icon has a circular lens and diagonal handle). If these do not work, it will not randomly click unrelated links.
- If no search control is available, tries **at most two visible public category links** (robots.txt permitting). Captures visible product tiles and merchandising controls, not an unproven search problem.
- **Stops after a failed first search lookup**, instead of making the same failed discovery three times.
- The opportunity dashboard now has three outcomes:
  - **Review first**: a real observed anomaly from sampled search results deserves confirmation.
  - **Discovery fit**: live search or category evidence suggests a commercially relevant conversation; no defect is alleged.
  - **Not assessable**: restricted or inconclusive. Automatically **set aside**, not added to a manual testing queue.
- Includes focused browser fixtures for unlabelled search icons, public category fallback, and exclusion of restricted sites.

## Install in the existing repo

1. Upload `Remarkable_Search_Merch_v4.zip` into `/workspaces/searchandmerch` on Codespaces.
2. Run:

```bash
cd /workspaces/searchandmerch
unzip -o Remarkable_Search_Merch_v4.zip -d .
git add auditor.py prospect_dashboard.py README.md requirements.txt prospects.csv tests .github/workflows/audit.yml
git commit -m "Prioritise visible Search and Merch opportunities v4"
git push origin main
```

3. Run the `Remarkable prospect website audit` workflow on `main` in GitHub Actions. The workflow installs Chromium and runs all tests. Local Codespaces browser setup is not necessary.
4. Download the **remarkable-prospect-audit** Actions artifact and open `opportunity_dashboard.html`. The file `opportunity_shortlist.csv` is your lead triage export.

## Limitations / appropriate use

- The changes have been verified against offline browser fixtures. **We have not tested v4 live against these retailers yet.** Icons rendered as CSS pseudo-elements or unusual SVGs may still be missed.
- A product category screenshot cannot establish onsite search relevance, and existing sorting/filter controls aren't evidence of a faulty platform.
- A blocked retailer is not a low-quality retailer. It simply has **no permitted evidence** for this automated scan. Do not evade robots.txt, access blocks or CAPTCHAs.
- Never send a specific defect accusation without rechecking the supporting screenshot and behaviour manually. Only the strongest candidates require that verification.
- Keep the repository private when adding confidential target lists. Public repositories can expose prospect information and reports.

## Input

`prospects.csv` supports: `company,website,query,queries,search_url_template`. Extra queries use `|` delimiters. A maximum of three searches is attempted per retailer, and at most 20 websites per GitHub Actions run.
