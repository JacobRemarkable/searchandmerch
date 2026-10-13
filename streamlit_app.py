#!/usr/bin/env python3
'''Remarkable Prospect Intelligence — clearer, 3-stage sales workflow UI.

Start from Codespaces:
    python -m streamlit run streamlit_app.py --server.address 0.0.0.0 --server.port 8501
The upload/scan engine and evidence-gating remain unchanged.
'''
import io
import json
import zipfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

from dashboard_core import parse_upload, write_inputs, merged_results
from upload_tables import load_upload_tables, detected_header, mapping_defaults, display_column, parse_mapped_table
from dashboard_runner import run_batch
from account_profiles import build_profiles, export as export_profiles

ROOT = Path(__file__).resolve().parent
RUNS = ROOT / 'runs'
RUNS.mkdir(exist_ok=True)

st.set_page_config(page_title='Remarkable | Prospect Intelligence', page_icon='🔎',
                   layout='wide', initial_sidebar_state='collapsed')
st.markdown('''<style>
.block-container {max-width: 1340px; padding-top: 1.3rem; padding-bottom: 3rem}
[data-testid="stAppViewContainer"] {background: #f7f9fc}
h1,h2,h3 {color: #1e304b; letter-spacing: -.02em}
[data-testid="stMetric"] {background: #fff; padding: 13px 17px; border: 1px solid #e4e9f0; border-radius: 12px}
[data-testid="stMetricLabel"] {font-size: .83rem}
[data-testid="stMetricValue"] {font-size: 1.6rem}
[data-testid="stButton"] button[kind="primary"] {background: #173e62; border: 0; font-weight: 650; min-height: 2.9rem}
[data-testid="stButton"] button[kind="primary"]:hover {background: #265d83}
[data-testid="stTabs"] [data-baseweb="tab-list"] {background: #eef2f7; padding: 5px; border-radius: 10px; gap: 8px}
[data-testid="stTabs"] button[role="tab"] {font-weight: 650; border-radius: 7px; padding: 11px 16px}
[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {background: white; color: #193a56}
.hero {padding: 23px 27px; background: #152e48; border-radius: 14px; margin-bottom: 12px}
.hero .eyebrow {color: #d0a65b; letter-spacing: .12em; font-size: .73rem; font-weight: 800}
.hero h1 {font-size: 1.7rem; color: #fff!important; margin: 5px 0 4px}
.hero p {color: #dce5ee; margin: 0; font-size: .96rem}
.step-note {border-left: 3px solid #89a8ba; padding: .45rem 0 .45rem 12px; color: #465f75; font-size: .88rem; margin: 12px 0 20px}
.quiet {color: #617288; font-size: .85rem}
.status-good {border:1px solid #bedacc; background:#eff8f2; border-radius: 9px; padding: 10px 13px; font-weight: 600; color:#21543b}
.panel-head {font-weight:700; font-size: 1.03rem; color: #182f49; margin:10px 0}
</style>''', unsafe_allow_html=True)
st.markdown('''<div class="hero"><div class="eyebrow">REMARKABLE COMMERCE · PROSPECT INTELLIGENCE</div>
<h1>Find your next Search & Merch opportunity</h1>
<p>Upload companies, scan their public storefronts, and build a shortlist with evidence and outreach angles.</p></div>''',unsafe_allow_html=True)

with st.sidebar:
    st.header('How to use this tool')
    st.markdown('**1. Add targets** — Upload Numbers, Excel or CSV; confirm two columns.')
    st.markdown('**2. Run scan** — Choose a quick technology check or full opportunity audit.')
    st.markdown('**3. Review accounts** — One business at a time: Search, Merch, other solutions and tech stack.')
    st.divider()
    st.caption('Tech providers are identified from public signals; “Not detected” does not mean absent. An opportunity is a reason to investigate, not proof of lost sales.')
    st.caption('Scans respect site restrictions. Files and results remain in this Codespaces workspace. Keep port 8501 private and avoid including confidential information in a public repository.')

with st.expander('What should my spreadsheet look like?', expanded=False):
    st.markdown('Only **Company** and **Website** are required. Any additional columns are optional. You can map unfamiliar column headings after upload.')
    st.dataframe(pd.DataFrame([
        {'Company':'Example Fashion','Website':'https://www.example.com','Query (optional)':'summer dress'},
        {'Company':'Example Homeware','Website':'https://www.example.org','Query (optional)':'table lamp'},
    ]),hide_index=True,use_container_width=True)
    sample=('Company,Website,Query,Queries,Vertical,Lead With\n'
            'Example Fashion,https://www.example.com,summer dress,linen dress|coats,Fashion,Both\n'
            'Example Homeware,https://www.example.org,table lamp,side table|candles,Homeware,Merch\n')
    st.download_button('Download example CSV',data=sample,file_name='remarkable_target_template.csv',mime='text/csv')

tab_input, tab_scan, tab_results = st.tabs(['1  ·  Add targets', '2  ·  Run audit', '3  ·  Business profiles'])

rows=[]
warnings=[]
with tab_input:
    st.markdown('### Add your companies')
    st.markdown('<div class="step-note">Start with a Numbers, Excel or CSV file. We only need the company name and its website. You can review everything before scanning.</div>',unsafe_allow_html=True)
    left,right=st.columns([2,1],gap='large')
    with left:
        uploaded=st.file_uploader('Choose a target list',type=['numbers','xlsx','xlsm','csv'],
            help='Supports Apple Numbers, Excel and CSV. Up to 10 MB.')
        demo=st.checkbox('Try the existing example retailer list',value=False,
            disabled=uploaded is not None)
    with right:
        st.markdown('**Minimum information**')
        st.markdown('**Company** — retailer / brand name  \n**Website** — site address (e.g. `example.com`)')
        st.caption('Optional: product search terms, industry, your sales angle and preferred contact role.')
    if uploaded is not None:
        try:
            uploaded_tables=load_upload_tables(uploaded.getvalue(),uploaded.name)
            if not uploaded_tables:
                st.error('No readable table found. Check that the spreadsheet contains rows of retailers.')
            else:
                st.markdown('#### Confirm which columns to use')
                if len(uploaded_tables)>1:
                    selected=st.selectbox('Worksheet / table',range(len(uploaded_tables)),
                        format_func=lambda i:f'{uploaded_tables[i][0]} · {len(uploaded_tables[i][1])} rows')
                else:
                    selected=0
                    st.caption(f'Reading: {uploaded_tables[0][0]}')
                raw_rows=uploaded_tables[selected][1]
                if raw_rows:
                    initial=detected_header(raw_rows)
                    heading_row=st.selectbox('Which row contains column headings?',range(min(20,len(raw_rows))),
                        index=initial,format_func=lambda i:f'Row {i+1}  ·  '+ ' | '.join(raw_rows[i][:4])[:100])
                    default_company,default_website,width=mapping_defaults(raw_rows,heading_row)
                    width=min(width,100)
                    if width < 2:
                        st.error('Only one column was found. Please include a company and a website in separate columns.')
                    else:
                        c1,c2=st.columns(2)
                        with c1:
                            company_col=st.selectbox('Company / business name',list(range(width)),
                                index=default_company if default_company is not None else 0,
                                format_func=lambda i:display_column(raw_rows,heading_row,i))
                        with c2:
                            website_col=st.selectbox('Website / URL',list(range(width)),
                                index=default_website if default_website is not None else (1 if company_col != 1 else 0),
                                format_func=lambda i:display_column(raw_rows,heading_row,i))
                        no_header=st.checkbox('This file has no heading row (row 1 is a retailer)',value=False)
                        with st.expander('See original spreadsheet preview'):
                            st.dataframe(pd.DataFrame(raw_rows[:12]),hide_index=True,use_container_width=True)
                        try:
                            rows,warnings=parse_mapped_table(raw_rows,heading_row,company_col,website_col,no_header=no_header)
                        except Exception as err:
                            st.error(f'Check the selected columns: {err}')
        except Exception as err:
            st.error(f'Unable to read file: {err}')
    elif demo:
        try:
            rows,warnings=parse_upload((ROOT/'prospects.csv').read_bytes())
        except Exception as err:
            st.error(f'Could not load sample list: {err}')

    if rows:
        st.markdown(f'<div class="status-good">✓ {len(rows)} unique retailer websites recognised. Check the list below before running.</div>',unsafe_allow_html=True)
        with st.expander('Show excluded rows or duplicate warnings',expanded=False):
            if warnings:
                for message in warnings[:30]: st.warning(message)
            else:
                st.caption('No rows excluded.')
        fields=['company','website','query','queries','vertical','lead_with','primary_persona','commercial_hypothesis']
        st.markdown('#### Your target list')
        st.caption('Edit any company, URL or search term directly. Optional fields can be left blank.')
        st.session_state['targets_editor']=st.data_editor(pd.DataFrame(rows)[fields],
            hide_index=True,num_rows='fixed',use_container_width=True,key='target_rows_grid',
            column_config={
                'company':st.column_config.TextColumn('Company',required=True,width='medium'),
                'website':st.column_config.TextColumn('Website',required=True,width='large'),
                'query':st.column_config.TextColumn('Search term (optional)',width='medium'),
                'queries':st.column_config.TextColumn('More searches (separate with |)',width='large'),
                'vertical':st.column_config.TextColumn('Retail sector'),
                'lead_with':st.column_config.SelectboxColumn('Initial angle',options=['Both','Search','Merch']),
                'primary_persona':st.column_config.TextColumn('Target role'),
                'commercial_hypothesis':st.column_config.TextColumn('Notes / hypothesis',width='large'),
            })
        st.info('Targets ready. Select **2 · Run audit** above when you want to start.')
    else:
        st.session_state['targets_editor']=None
        st.info('Choose a file or select the example retailers to begin.')

with tab_scan:
    st.markdown('### Choose your audit')
    st.markdown('<div class="step-note">A tech scan checks for publicly visible providers. A full audit also attempts permitted product searches, gathers screenshots and prepares sales angles.</div>',unsafe_allow_html=True)
    sources=st.session_state.get('targets_editor')
    if sources is None or sources.empty:
        st.warning('No targets loaded yet. Open **1 · Add targets** first.')
    else:
        count=len(sources)
        st.success(f'{count} company websites ready for assessment')
        l,r=st.columns(2,gap='large')
        with l:
            mode=st.radio('Scan depth', ['Full Search + Merch + Tech','Quick tech-stack scan'],
                help='Full includes screenshots and sales evidence; quick only detects known public provider signatures.')
            max_sites=min(30,count)
            limit=st.number_input('Companies to include in this batch',min_value=1,max_value=max_sites,value=min(20,max_sites),step=1)
        with r:
            st.markdown('**What you will receive**')
            if mode.startswith('Full'):
                st.markdown('• Search and merchandising observations  \n• Storefront technology evidence  \n• Screenshots when permitted  \n• Suggested outreach priorities and questions')
            else:
                st.markdown('• Ecommerce platform signals  \n• Onsite search provider signals  \n• Merchandising provider signals  \n• Source evidence and confidence levels')
            st.caption('Some websites restrict automated visits. They will be labelled inconclusive, not described as faulty.')
        if st.button(f'▶ Scan {int(limit)} retailer websites',type='primary',use_container_width=True):
            try:
                records,_=parse_upload(sources.to_csv(index=False))
                records=records[:int(limit)]
                identifier=datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_')+uuid.uuid4().hex[:7]
                run_dir=RUNS/identifier
                write_inputs(records,run_dir)
                st.session_state['last_run_dir']=str(run_dir)
                messages=[]
                console=st.empty()
                with st.status(f'Scanning {len(records)} websites',expanded=True) as status:
                    def update(message):
                        messages.append(str(message))
                        console.code('\n'.join(messages[-12:]),language='text')
                    run_batch(run_dir,'full' if mode.startswith('Full') else 'quick',callback=update)
                    status.update(label='Scan finished — open Business profiles',state='complete')
                st.success('Scan complete. Open **3 · Business profiles** to see your results.')
            except Exception as exc:
                st.error(f'The scan stopped: {exc}')
                st.info('If some results were generated, they may still be available under View opportunities.')

with tab_results:
    st.markdown('### Business-by-business intelligence')
    st.caption('A simple account profile for each retailer: Search entry · Merch entry · Other Remarkable offerings · Visible technology. Observations and hypotheses are labelled separately.')
    saved_runs=sorted([p for p in RUNS.iterdir() if p.is_dir() and (p/'results').exists()],reverse=True)
    previous=st.session_state.get('last_run_dir')
    if not saved_runs:
        st.info('No saved scan results yet. Start at **1 · Add targets** and **2 · Run audit**.')
    else:
        known=[str(p) for p in saved_runs]
        selected_run=st.selectbox('Saved scan',known,
            index=known.index(previous) if previous in known else 0,
            format_func=lambda p: Path(p).name.replace('_','  ',2),key='saved_run_select')
        previous=selected_run
        output=Path(previous)/'results'
        try:
            profiles=build_profiles(previous)
            if profiles and not (output/'account_profiles.html').exists():
                export_profiles(previous)
        except Exception as err:
            profiles=[]
            st.error(f'Could not display account profiles: {err}')
        if profiles:
            with_evidence=sum(x['screenshot'] != '' for x in profiles)
            with_stack=sum(any(x['stack'][r] for r in ('Ecommerce','Search','Merch')) for x in profiles)
            with_signal=sum(x['priority'].startswith('P1') for x in profiles)
            a,b,c,d=st.columns(4)
            a.metric('Companies',len(profiles))
            b.metric('With screenshots',with_evidence)
            c.metric('Technology identified',with_stack)
            d.metric('Signals to verify',with_signal)

            dl1,dl2,dl3=st.columns(3)
            account_html=output/'account_profiles.html'
            account_csv=output/'account_profiles.csv'
            if account_html.exists():
                dl1.download_button('↓ Business report (HTML)',account_html.read_bytes(),
                    file_name='remarkable_business_profiles.html',mime='text/html',use_container_width=True)
            if account_csv.exists():
                dl2.download_button('↓ Account report (CSV)',account_csv.read_bytes(),
                    file_name='remarkable_business_profiles.csv',mime='text/csv',use_container_width=True)
            zip_content=io.BytesIO()
            with zipfile.ZipFile(zip_content,'w',compression=zipfile.ZIP_DEFLATED) as archive:
                for item in output.rglob('*'):
                    if item.is_file() and item.stat().st_size<12_000_000:
                        archive.write(item,item.relative_to(output))
            dl3.download_button('↓ Screenshots + reports (ZIP)',zip_content.getvalue(),
                file_name='remarkable_prospect_evidence.zip',mime='application/zip',use_container_width=True)

            st.divider()
            st.markdown('#### Select a business')
            filter_label=st.selectbox('Show', ['All businesses','Priority signals first','Businesses with visual evidence',
                                           'Businesses with detected tech'],key='profile_filter')
            available=profiles
            if filter_label=='Businesses with visual evidence':
                available=[p for p in profiles if p['screenshot']]
            elif filter_label=='Businesses with detected tech':
                available=[p for p in profiles if any(p['stack'][r] for r in ('Ecommerce','Search','Merch'))]
            elif filter_label=='Priority signals first':
                available=sorted(profiles,key=lambda x:(not x['priority'].startswith('P1'),x['company'].casefold()))
            if not available:
                st.info('No accounts match this filter.')
            else:
                selected=st.selectbox('Business',range(len(available)),
                     format_func=lambda i:f"{available[i]['company']}  ·  {available[i]['priority']}",
                     key='selected_business')
                p=available[selected]
                with st.container(border=True):
                    headline,linkcol=st.columns([4,1.1])
                    with headline:
                        st.markdown(f"## {p['company']}")
                        st.caption(f"{p['category']} · {p['priority']} · {p['status']}")
                    with linkcol:
                        if p['website']:
                            st.link_button('↗ Open website',p['website'],use_container_width=True)
                    photo,detail=st.columns([1,1.5],gap='large')
                    with photo:
                        screenshot=p['screenshot']
                        local=(output/screenshot).resolve() if screenshot else None
                        if local and local.is_relative_to(output.resolve()) and local.is_file():
                            st.image(str(local),caption='Captured storefront evidence',use_container_width=True)
                        else:
                            st.info('No visual evidence captured. Do not assume a website problem.')
                        st.caption('EVIDENCE LEVEL: '+p['confidence'])
                        if p['tested_url']:
                            st.link_button('↗ View tested page',p['tested_url'],use_container_width=True)
                    with detail:
                        entry_search,entry_merch=st.columns(2,gap='medium')
                        with entry_search:
                            with st.container(border=True):
                                st.markdown('**Search opportunity**')
                                st.caption(p['search']['label'])
                                st.write(p['search']['detail'])
                        with entry_merch:
                            with st.container(border=True):
                                st.markdown('**Merch opportunity**')
                                st.caption(p['merch']['label'])
                                st.write(p['merch']['detail'])
                        st.markdown('**Other Remarkable opportunities**')
                        if p['other']:
                            for other in p['other']:
                                st.markdown(f"**{other['module']}** — {other['reason']}")
                                st.caption(f"To qualify: {other['question']}")
                        else:
                            st.caption('No other specific opportunity supported by this scan.')

                        st.markdown('**Visible technology stack**')
                        for role in ('Ecommerce','Search','Merch','Other technology'):
                            detected=p['stack'][role]
                            st.markdown('**'+role+':** '+(', '.join(f"{d['name']} ({d['confidence']})" for d in detected) if detected else 'Not detected / unknown'))
                        st.caption(p['stack_note'])

                st.markdown('#### Suggested first conversation')
                with st.container(border=True):
                    st.write(p['discovery_question'])
                    st.caption('Target role: '+p['persona'])
                    if p['linkedin_draft']:
                        with st.expander('LinkedIn message draft · verify before sending'):
                            st.code(p['linkedin_draft'],language='text')

                with st.expander('More public information and supporting evidence'):
                    if p['page_title']:
                        st.write('**Website title:** '+p['page_title'])
                    if p['page_description']:
                        st.write('**Website description:** '+p['page_description'])
                    st.write('**Observed audit evidence:** '+p['observed'])
                    if p['signals']:
                        st.markdown('**Other visible signals**')
                        for sig in p['signals']:
                            st.write(f"• {sig['label']} — matched public wording: '{sig['proof']}'")
                    else:
                        st.caption('No additional public buying-context signals recorded.')
                    if p['hypothesis']:
                        st.write('**Commercial hypothesis (not a finding):** '+p['hypothesis'])
                    st.markdown('**Technology evidence**')
                    for role in ('Ecommerce','Search','Merch','Other technology'):
                        for item in p['stack'][role]:
                            st.caption(f"{role}: {item['name']} · {item['confidence']} · {item['evidence']}")
                    st.caption('This tool does not measure revenue loss, tech-stack completeness or true buyer intent. Verify claims before contacting an account.')
            with st.expander('Compare all businesses at a glance'):
                compact=[]
                for p in profiles:
                    compact.append({'Company':p['company'],'Priority':p['priority'],
                        'Search':p['search']['label'],'Merch':p['merch']['label'],
                        'Other potential fit':', '.join(o['module'] for o in p['other']) or '—',
                        'Ecommerce':', '.join(x['name'] for x in p['stack']['Ecommerce']) or 'Unknown',
                        'Search vendor':', '.join(x['name'] for x in p['stack']['Search']) or 'Unknown',
                        'Merch vendor':', '.join(x['name'] for x in p['stack']['Merch']) or 'Unknown'})
                st.dataframe(pd.DataFrame(compact),use_container_width=True,hide_index=True)
        else:
            st.info('No readable company profiles from this run. Check the scan status.')

st.caption('Remarkable Commerce · Public website research only · No automatic contact scraping or outreach · Keep Codespaces private')
