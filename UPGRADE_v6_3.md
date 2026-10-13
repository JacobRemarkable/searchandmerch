# Remarkable Prospect Intelligence — v6.3 account profiles

## What changes

The third dashboard tab is now **Business profiles**, retaining the screenshot-led layout from v4. Each retailer has a concise, individual profile with:

1. **Search entry** — a labelled, evidence-gated Search conversation.
2. **Merch entry** — a labelled, evidence-gated Merchandising conversation.
3. **Other Remarkable opportunities** — up to two *questions worth exploring* about PIM, promotions, omnichannel/OMS, CMS or fulfilment/WMS, suggested only when the audit or public site copy supplies a relevant positive signal.
4. **Visible technology stack** — ecommerce, Search, Merch and other providers with detection confidence and evidence. **Not detected** means unknown, not absent.
5. **Useful public signals** — homepage title/description, offers, click & collect, trade/wholesale, store locations, delivery, returns, loyalty, and public website observations. Public wording is *not* a performance finding.
6. **Conversation opener**, target job role, and screenshot when the permitted scan captured one.

A **single HTML business report** and **CSV** are generated on every new scan. Download the **evidence ZIP** to retain the screenshots alongside the HTML report. Every result is available business by business; saved scans can be reopened from the dashboard's Saved scan selector.

## Update an existing v6.2 Codespaces installation

Upload the ZIP into `/workspaces/searchandmerch`, stop Streamlit in its terminal with **Ctrl+C**, then:

```bash
cd /workspaces/searchandmerch
unzip -o Remarkable_Dashboard_Business_Profiles_v6_3.zip -d .
python -m py_compile account_profiles.py tech_stack.py dashboard_runner.py streamlit_app.py
python -m streamlit run streamlit_app.py --server.address 0.0.0.0 --server.port 8501
```

No data file conversion required. To generate the new public signals and all four sections, run a **Full Search + Merch + Tech** scan. A **Quick tech-stack scan** produces the tech stack but clearly marks Search and Merch **Not tested**.

The saved old runs will show any data that was captured then; new public signals require a fresh scan. Public-site robots/access restrictions remain respected. No contacts are scraped, no messaging is sent, and other Remarkable products are marked discovery topics, never confirmed faults.

## Test status

All 55 local regression tests passed. The Streamlit interface needs a browser check in your own Codespaces instance because Streamlit was not available in the offline build environment.
