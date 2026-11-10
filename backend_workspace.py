"""Optional full backend UI. No service-account token or shared researcher cache."""
import csv
import io
import json
import streamlit as st
from rdkit import Chem
from rdkit.Chem import Draw
from backend_client import BackendClient, BackendError


def render(base_url, allow_local=False):
    key = '_researcher_backend_client'
    if key not in st.session_state or st.session_state[key].base_url != base_url.rstrip('/'):
        st.session_state[key] = BackendClient(base_url, allow_local=allow_local)
    client = st.session_state[key]
    st.caption('Connected researcher workspace · accounts and records are managed by the original P2X4 backend.')
    if not client.session().get('authenticated'):
        st.title('Sign in to your research workspace')
        st.write('Use the account registered on the connected backend. Existing laptop accounts are available only if that account database has been migrated.')
        with st.form('backend-login', clear_on_submit=True):
            email = st.text_input('Email address')
            password = st.text_input('Password', type='password')
            submit = st.form_submit_button('Sign in', type='primary')
        if submit:
            try:
                client.login(email.strip(), password)
                st.rerun()
            except BackendError as exc:
                st.error(str(exc))
        st.link_button('Register, verify email or recover password', client.base_url + '/login.html')
        return
    st.write(f"Signed in as **{client.user['email']}**")
    if st.button('Sign out'):
        try:
            client.logout()
        finally:
            st.session_state.pop('_backend_selected_job', None)
        st.rerun()
    pages = ['Test a compound', 'Compound registry', 'More about the target receptor', 'Compound results', 'Compare compounds']
    if client.user.get('is_admin'):
        pages.append('Administration')
    page = st.radio('Research workspace', pages, horizontal=True, key='backend_nav')
    if page == pages[0]:
        submission(client)
    elif page == 'Compound registry':
        registry(client)
    elif page == 'Compound results':
        results(client)
    elif page == 'Administration':
        administration(client)
    elif page == 'Compare compounds':
        comparison(client)
    else:
        st.title('Human P2X4 · 9BQI')
        st.write('The fixed workflow evaluates poses in the BAY-1797 allosteric pocket. Docking scores do not establish measured affinity, efficacy or safety.')
        st.link_button('Open complete receptor reference', client.base_url + '/target.html')


def submission(client):
    st.title('Test a compound')
    single, batch = st.tabs(['Single compound', 'Batch campaign'])
    settings = dict(mode='confirmation', microspecies=True, ph_min=6.8, ph_max=8.0, max_microspecies=8)
    st.caption('Five frozen seeds per microspecies · pH 6.8–8.0 · maximum eight states. Jobs run on the persistent backend worker.')
    with single:
        with st.form('backend-single'):
            code = st.text_input('Compound code', max_chars=80)
            name = st.text_input('Compound name or IUPAC name as supplied', max_chars=300)
            smiles = st.text_area('Isomeric SMILES', max_chars=4000)
            replicate = st.checkbox('Intentional replicate: allow an exact structure already in my registry')
            inspect = st.form_submit_button('Inspect structure and duplicates')
            submit = st.form_submit_button('Run replicated P2X4 consensus', type='primary')
        if inspect:
            st.json(client.request('POST', '/api/inspect', dict(smiles=smiles, **settings)))
        if submit:
            if not code.strip() or not name.strip():
                st.error('Supply both code and compound name.'); return
            response = client.request('POST', '/api/jobs', dict(compound_id=code.strip(), compound_name=name.strip(), smiles=smiles.strip(), allow_duplicate=replicate, **settings))
            st.session_state['_backend_selected_job'] = response['job_id']
            st.success('Job accepted by the backend. Open Compound results to follow progress.')
    with batch:
        st.download_button('Download batch template', 'compound_id,Compound Name,SMILES\nEX001,Ethanol,CCO\n', 'batch-template.csv')
        upload = st.file_uploader('CSV · up to 25 compounds', type='csv')
        allow = st.checkbox('Intentional batch replicates: allow exact duplicates')
        if st.button('Submit batch', disabled=upload is None):
            if upload.size > 200_000:
                st.error('CSV exceeds 200 KB.'); return
            try:
                reader = csv.DictReader(io.StringIO(upload.getvalue().decode('utf-8-sig')))
                rows = [dict(compound_id=r['compound_id'], compound_name=r['Compound Name'], smiles=r['SMILES']) for r in reader]
                if not 1 <= len(rows) <= 25:
                    raise ValueError('Supply 1–25 compounds.')
            except (KeyError, ValueError) as exc:
                st.error(f'Invalid CSV: {exc}'); return
            response = client.request('POST', '/api/batches', dict(compounds=rows, allow_duplicate=allow, **settings))
            st.success('Batch submitted. Review accepted and rejected rows below.')
            st.json(response)
    st.button('Refresh recent jobs')
    with st.expander('Recent backend jobs'):
        st.dataframe(client.request('GET', '/api/jobs')['jobs'], hide_index=True)


def registry(client):
    st.title('Compound registry')
    st.caption('Records are fetched from your authenticated backend account. Signing out does not delete them.')
    data = client.request('GET', '/api/registry')
    query = st.text_input('Search code or name').lower()
    rows = [r for r in data['records'] if query in f"{r['compound_id']} {r['compound_name']}".lower()]
    st.dataframe(rows, hide_index=True)
    if rows:
        jid = st.selectbox('Compound', [r['job_id'] for r in rows], format_func=lambda j: next(f"{r['compound_id']} · {r['compound_name']}" for r in rows if r['job_id']==j))
        st.session_state['_backend_selected_job'] = jid
        st.info('Select Compound results above to open this record.')
        output = io.StringIO(); writer = csv.DictWriter(output, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
        st.download_button('Export registry CSV', output.getvalue(), 'p2x4-registry.csv')


def fetch_download(client, label, path, filename, mime=None):
    # Do not hold private evidence in a process-wide cache or persist cookies.
    if st.button('Prepare ' + label, key='fetch-'+filename):
        data = client.request('GET', path, binary=True)
        st.download_button(label, data, filename, mime=mime, key='save-'+filename)


def comparison(client):
    st.title('Compare compounds')
    rows = client.request('GET', '/api/registry')['records']
    selected = st.multiselect('Choose two to four compounds', [r['job_id'] for r in rows], max_selections=4,
        format_func=lambda jid: next(f"{r['compound_id']} · {r['compound_name']}" for r in rows if r['job_id']==jid))
    if len(selected) < 2:
        st.info('Select at least two completed records.'); return
    for col, jid in zip(st.columns(len(selected)),selected):
        row = next(r for r in rows if r['job_id']==jid)
        with col:
            st.subheader(row['compound_id']); st.write(row['compound_name'])
            mol = Chem.MolFromSmiles(row['canonical_smiles'])
            if mol: st.image(Draw.MolToImage(mol,size=(350,240)))
            st.metric('Median Vina · kcal/mol', row['median_vina_score_kcal_mol'])
            st.metric('Site-valid fraction', f"{row['valid_site_fraction']:.1%}")
            st.write(f"Native-contact recovery: {row['median_native_contact_recovery']:.1%}")
    st.caption('Backend-owned evidence only. Scores are not calibrated affinities across dissimilar scaffolds.')


def results(client):
    st.title('Compound results')
    jobs = client.request('GET', '/api/jobs')['jobs']
    registry_rows = client.request('GET', '/api/registry')['records']
    ids = list(dict.fromkeys([r['job_id'] for r in registry_rows] + [j['job_id'] for j in jobs]))
    preferred = st.session_state.get('_backend_selected_job')
    if not ids:
        st.info('No records in this backend account yet.'); return
    jid = st.selectbox('Job', ids, index=ids.index(preferred) if preferred in ids else 0)
    st.button('Refresh status')
    status = client.request('GET', client.job_path(jid))
    st.write(f"**{status.get('compound_id', jid)}** · {status.get('compound_name') or ''} · {status.get('status')}")
    st.progress(max(0,min(100,int(status.get('progress_percent', 0)))), text=status.get('detail',status.get('step','')))
    if status.get('status') != 'complete':
        st.json(status, expanded=False); return
    result = client.request('GET', client.job_path(jid, '/files/result.json'))
    mol = Chem.MolFromSmiles(result.get('descriptors', {}).get('canonical_smiles', ''))
    if mol is not None:
        st.image(Draw.MolToImage(mol, size=(450,250)))
    st.metric('Median Vina · kcal/mol', result['summary']['median_vina_score_kcal_mol'])
    overview, admet, prolif, downloads = st.tabs(['Evidence', 'ADMET / toxicity', 'ProLIF interactions', 'Downloads'])
    with overview:
        st.write(result.get('methods_text',''))
        with st.expander('Per-seed evidence'):
            st.dataframe(result.get('per_seed',[]), hide_index=True)
        with st.expander('State-level evidence'):
            st.json(result.get('microspecies',[]), expanded=False)
        if st.button('Load auditable record'):
            st.json(client.request('GET', client.job_path(jid, '/audit-record.json?run_admet=0')), expanded=False)
    with admet:
        st.caption('Explicit opt-in. Model estimates are not measured safety or pharmacokinetic evidence.')
        if st.button('Run ADMET-AI on this compound', type='primary'):
            with st.spinner('Running inference on the backend…'):
                st.json(client.request('POST', client.job_path(jid, '/admetox'), {}))
        if st.button('View available ADMET profile'):
            audit = client.request('GET', client.job_path(jid, '/audit-record.json?run_admet=0'))
            st.json(audit.get('admetox', {}), expanded=False)
    with prolif:
        st.caption('Geometry-based interaction evidence from the representative docked pose. Available files are supplied by the backend.')
        try:
            assets = client.request('GET', client.job_path(jid, '/publication-pose'))
        except BackendError as exc:
            if exc.status != 404:
                raise
            st.info('ProLIF output is not available for this job yet. The backend worker must generate it.')
        else:
            st.write(assets['methods']); st.json(assets.get('analysis', {}), expanded=False)
            if assets.get('preview_url'):
                st.image(client.request('GET', assets['preview_url'], binary=True))
            for item in assets.get('downloads', []):
                ext = 'tif' if 'tiff' in item['key'] else 'csv' if item['key']=='prolif_csv' else 'json'
                fetch_download(client, item['label'], item['url'], f"{jid}-{item['key']}.{ext}")
    with downloads:
        st.download_button('Result JSON', json.dumps(result, indent=2), f'{jid}-result.json')
        fetch_download(client, 'Methods report', client.job_path(jid, '/files/report.md'), f'{jid}-report.md')
        fetch_download(client, 'Seed evidence CSV', client.job_path(jid, '/files/analysis/per_seed.csv'), f'{jid}-seeds.csv')
    st.caption('The legacy activity rule is not externally validated. Docking evidence does not establish pharmacological activity.')


def administration(client):
    st.title('Administration')
    # The backend independently authorizes every read and action.
    payload = client.request('GET', '/api/admin/queue')
    st.write('Queue paused' if payload['paused'] else 'Queue accepting work')
    if st.button('Resume queue' if payload['paused'] else 'Pause queue'):
        client.request('POST', '/api/admin/queue/pause', {'paused': not payload['paused']}); st.rerun()
    st.dataframe(payload['jobs'], hide_index=True)
    st.subheader('Whole-batch controls')
    batches = payload.get('batches', [])
    if batches:
        st.dataframe(batches, hide_index=True)
        bid = st.selectbox('Batch', [b['batch_id'] for b in batches])
        action = st.selectbox('Batch action', ['pause', 'resume', 'stop', 'retry'])
        st.caption('Pause and stop affect eligible waiting jobs. Already-running compounds finish safely; completed evidence is retained.')
        if st.button('Apply to batch', type='primary'):
            st.json(client.request('POST', f'/api/admin/batches/{bid}/action', {'action': action}))
    else:
        st.info('No batches found.')
