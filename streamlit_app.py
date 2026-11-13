"""Original P2X4 workspace navigation adapted to temporary Streamlit sessions."""
import csv
import io
import json
import os
import uuid
from pathlib import Path
import streamlit as st
from rdkit import Chem
from rdkit.Chem import Draw, Descriptors, rdMolDescriptors
from engine import Engine

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title='P2X4 Dock · Research workspace', page_icon='🧬', layout='wide')
st.markdown((ROOT / 'workspace.css').read_text(), unsafe_allow_html=True)
st.markdown('''<div class="workspace-brand"><div class="brand-box">P2<br>X4</div><div><strong>P2X4 Dock</strong><small>9BQI · BAY-1797 allosteric site</small></div><span class="session-badge">Research workspace</span></div>''', unsafe_allow_html=True)

def setting(name, default=''):
    try:
        value = st.secrets.get(name, default)
    except FileNotFoundError:
        value = default
    return os.environ.get(name, value)

cloud_url = setting('P2X4_SUPABASE_URL')
cloud_key = setting('P2X4_SUPABASE_PUBLISHABLE_KEY')
cloud_mode = bool(cloud_url or cloud_key)

# Credentials stay in a per-browser session; no shared service-owner identity.
try:
    backend_url = st.secrets.get('P2X4_BACKEND_URL', '')
except FileNotFoundError:
    backend_url = ''
backend_url = backend_url or os.environ.get('P2X4_BACKEND_URL', '')
if backend_url and cloud_mode:
    st.error('Configure either Supabase storage or the original backend, not both.'); st.stop()
if backend_url:
    from backend_workspace import render
    from backend_client import BackendError
    try:
        render(backend_url, allow_local=os.environ.get('P2X4_BACKEND_LOCAL_TEST') == '1')
    except (BackendError, ValueError) as exc:
        st.error(str(exc))
        st.caption('Backend mode stays active when the backend is unavailable. No jobs are silently sent to temporary storage.')
    st.stop()

@st.cache_resource
def engine():
    return Engine()

if cloud_mode:
    from cloud_workspace import CloudEngine, sign_in
    from supabase_client import CloudError
    try:
        if not cloud_url or not cloud_key:
            raise CloudError('Both the Supabase project URL and publishable key must be configured.')
        client = sign_in(cloud_url, cloud_key,
            str(setting('P2X4_SUPABASE_SIGNUP_ENABLED', False)).lower() == 'true')
        from worker_compat import ensure_admin_client
        ensure_admin_client(client)
        owner = client.user['id']
        shared_worker = engine()
        if ('_cloud_worker' not in st.session_state
                or st.session_state._cloud_worker.engine is not shared_worker):
            st.session_state._cloud_worker = CloudEngine(shared_worker, client)
        worker = st.session_state._cloud_worker
    except (CloudError, ValueError) as exc:
        st.error(str(exc)); st.stop()
else:
    if 'owner' not in st.session_state:
        st.session_state.owner = uuid.uuid4().hex
    owner = st.session_state.owner
    worker = engine()

def owned_jobs():
    try:
        return worker.owned(owner)
    except ValueError as exc:
        st.error(str(exc))
        st.caption('Private cloud storage is unavailable. No fallback to anonymous temporary storage.')
        st.stop()

COMPOUND_VIEWS = ['Compound registry', 'Compound results', 'Compare compounds']

def navigate(page, job_id=None):
    if page in COMPOUND_VIEWS:
        st.session_state.nav = 'Compound workspace'
        st.session_state.compound_view = page
    else:
        st.session_state.nav = page
    if job_id:
        st.session_state.selected_job = job_id

pages = ['Test a compound', 'Compound workspace', 'More about the target receptor', 'How to cite']
is_admin = False
if cloud_mode:
    try:
        is_admin = client.is_admin()
    except CloudError:
        pass  # Fail closed if the role migration is not installed or unavailable.
if is_admin:
    pages.append('Administration')
if st.session_state.get('nav') in COMPOUND_VIEWS:
    navigate(st.session_state.nav)
if st.session_state.get('nav') not in pages:
    st.session_state.nav = pages[0]
page = st.radio('Workspace navigation', pages, horizontal=True, key='nav', label_visibility='collapsed')
if page == 'Compound workspace':
    if st.session_state.get('compound_view') not in COMPOUND_VIEWS:
        st.session_state.compound_view = COMPOUND_VIEWS[0]
    page = st.radio('Compound workspace views', COMPOUND_VIEWS, horizontal=True, key='compound_view',
                    format_func=lambda name: {'Compound registry': 'Registry', 'Compound results': 'Results', 'Compare compounds': 'Compare'}[name])
if not cloud_mode:
    st.caption('Temporary session: download results before leaving. Restarting the app or refreshing your session can lose jobs and access. No account sign-in is required.')

help_text = {
    'Test a compound': 'Enter a compound code, its supplied name and isomeric SMILES. Inspect the structure, then run the fixed five-seed protocol. For a batch, upload the provided CSV template (up to 25 rows). Recent jobs link to a separate results view.',
    'Compound registry': 'Search jobs from this browser session. Open a completed compound to review its evidence or choose up to four completed jobs in Compare compounds. Download the session table and result ZIPs before leaving.',
    'More about the target receptor': 'Read the receptor context and the limits of the fixed 9BQI docking model. Follow the primary-source links for biological and structural evidence.',
    'Compound results': 'Choose one of your jobs. Completed results include identity, scores, seed and state evidence, descriptors, warnings and provenance. Download the ZIP for structures and complete evidence. A docking score does not establish measured activity.',
    'Compare compounds': 'Select two to four completed jobs for side-by-side inspection. Compare structures, pose evidence and protocol settings; raw docking scores do not provide calibrated affinity across different scaffolds.'
}
help_text['How to cite'] = 'Choose APA or AMA, select only the methods used, and download references. Follow the dataset guidance for your own results and figures.'
help_text['Administration'] = 'Pause or resume dispatch on this worker. Running calculations finish normally. Researcher structures and results remain private.'
with st.popover('ⓘ  Help for this page'):
    st.write(help_text[page] if not cloud_mode else help_text[page].replace('this browser session', 'your private cloud registry').replace('this session', 'your account').replace('Download the session table and result ZIPs before leaving.', 'Download the registry table and result ZIPs for an independent backup.'))

def hero(kicker, title, description):
    st.markdown(f'<p class="eyebrow">{kicker}</p>', unsafe_allow_html=True)
    st.title(title)
    st.write(description)

def validate(rows):
    if not 1 <= len(rows) <= 25:
        raise ValueError('Supply between 1 and 25 compounds.')
    seen = set()
    for row in rows:
        if not row['compound_id'] or len(row['compound_id']) > 80 or row['compound_id'] in seen:
            raise ValueError('Compound codes must be unique, nonempty and at most 80 characters.')
        if not row['compound_name'] or len(row['compound_name']) > 500:
            raise ValueError('Supply a compound name of at most 500 characters.')
        if len(row['smiles']) > 4000:
            raise ValueError('SMILES exceeds the experimental hosting limit.')
        mol = Chem.MolFromSmiles(row['smiles'])
        if mol is None or not 1 <= mol.GetNumHeavyAtoms() <= 100:
            raise ValueError(f"{row['compound_id']}: supply a valid structure with 1–100 heavy atoms.")
        seen.add(row['compound_id'])
    return rows

def read_result(job):
    if job['state'] != 'complete':
        return None
    if cloud_mode:
        return worker.result(job)
    try:
        return json.loads((worker.root / job['job_id'] / 'result.json').read_text())
    except (OSError, ValueError):
        return None

def table_row(job):
    result = read_result(job) or {}
    summary = result.get('summary', {})
    return {'Code': job['compound_id'], 'Supplied name': job['compound_name'], 'Status': job['state'],
            'SMILES': job['smiles'], 'Median Vina (kcal/mol)': summary.get('median_vina_score_kcal_mol'),
            'Site-valid fraction': summary.get('valid_site_fraction'), 'Job ID': job['job_id']}

def csv_bytes(rows):
    output = io.StringIO()
    if rows:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return output.getvalue().encode('utf-8-sig')

def progress(job):
    if job['state'] == 'running':
        from docking_animation import render as render_docking_animation
        step = 'preparing'
        try:
            status = json.loads((worker.root / job['job_id'] / 'status.json').read_text())
            step = status.get('step', 'preparing')
            percent = max(0, min(100, int(status.get('progress_percent', 0))))
            st.progress(percent, text=f"{percent}% · {status.get('detail', status.get('step', 'Running'))}")
        except (OSError, ValueError):
            st.info('Preparing calculation…')
        render_docking_animation(step)
    elif job['state'] == 'queued':
        st.info('Queued · another compound may be running in the shared queue.')
    if job.get('error'):
        st.error(job['error'])
    if cloud_mode:
        if job.get('sync_error'):
            st.warning('Cloud save incomplete: ' + job['sync_error'])
        elif job.get('archive_sha256'):
            st.caption('Cloud archive saved · SHA-256 verified on download')
        elif job['state'] in ('complete', 'failed'):
            st.caption('Cloud evidence archive not yet confirmed. Keep a local download.')

@st.fragment(run_every=5)
def recent_jobs():
    jobs = owned_jobs()
    with st.expander(f'Recent jobs · {len(jobs)}', expanded=any(j['state'] in ('running', 'queued') for j in jobs)):
        if not jobs:
            st.caption('Your submitted compounds will appear here.')
        for job in reversed(jobs):
            st.write(f"**{job['compound_id']}** · {job['compound_name']} · {job['state']}")
            progress(job)
            if st.button('Open compound result', key='recent-'+job['job_id'], on_click=navigate, args=('Compound results', job['job_id'])):
                st.rerun()
        if jobs:
            if st.button('Stop my waiting compounds', key='stop-recent'):
                worker.cancel_waiting(owner)
                st.rerun(scope='fragment')
            st.caption('Stops your queued compounds only. A running calculation continues.')

def protocol():
    st.markdown('**Replicated consensus docking · 5 frozen seeds**')
    st.caption('Human P2X4 trimer · 9BQI · BAY-1797 pocket · exhaustiveness 16')
    a, b, c = st.columns(3)
    a.metric('Minimum pH', '6.8'); b.metric('Maximum pH', '8.0'); c.metric('State cap', '8')
    st.caption('Automatic microspecies enumeration. One compound at a time; up to 40 Vina runs per compound. Protocol settings are fixed.')

if page == 'Administration':
    st.title('Administration')
    st.caption('Authorized platform administrator. Researcher records remain private.')
    try:
        from worker_compat import ensure_admin_worker
        ensure_admin_worker(shared_worker)
        state = shared_worker.admin_queue(client)
        st.write('Queue dispatch: ' + ('Paused' if state['paused'] else 'Active'))
        st.json(state['counts'])
        with shared_worker.lock:
            admet_counts = {s: sum(t['state'] == s for t in getattr(shared_worker, '_admet_tasks', {}).values()) for s in ('queued', 'running', 'complete', 'failed')}
        st.write('ADMET follow-up queue')
        st.json(admet_counts)
        st.caption('Controls apply to this live worker only and reset after a host restart. Pausing holds waiting jobs; it does not interrupt running calculations or change docking settings.')
        if st.button('Resume queue' if state['paused'] else 'Pause queue'):
            shared_worker.admin_queue(client, paused=not state['paused'])
            st.rerun()
    except (CloudError, PermissionError, RuntimeError) as exc:
        st.error(str(exc))
elif page == 'Test a compound':
    left, right = st.columns([1.6, 1], gap='large')
    with left:
        hero('Structure-guided exploration', 'Explore the P2X4 pocket.', 'From a molecular structure to traceable docking evidence. Prepare, dock and inspect a compound against the fixed human P2X4 allosteric site.')
    with right:
        if (ROOT / 'pathway.mp4').exists():
            st.video(str(ROOT / 'pathway.mp4'), autoplay=True, muted=True, loop=True)
        st.caption('ATP–P2X4 neuroimmune signaling.')
    single, batch = st.tabs(['Single compound', 'Batch campaign'])
    with single:
        entry, workflow = st.columns([1.65, 1], gap='large')
        with entry, st.container(border=True):
            st.subheader('01 · Define compound')
            code = st.text_input('Compound code', max_chars=80, placeholder='e.g. SNP-new-001')
            name = st.text_input('Compound name or IUPAC name as supplied', max_chars=500)
            smiles = st.text_area('Isomeric SMILES', max_chars=4000, placeholder='Paste one molecular structure')
            if st.button('Inspect structure'):
                try:
                    row = validate([dict(compound_id=code.strip() or 'PREVIEW', compound_name=name.strip() or 'Preview', smiles=smiles.strip())])[0]
                    mol = Chem.MolFromSmiles(row['smiles'])
                    st.image(Draw.MolToImage(mol, size=(500, 260)))
                    st.write({'Formula': rdMolDescriptors.CalcMolFormula(mol), 'Molecular weight': round(Descriptors.MolWt(mol), 3), 'Formal charge': Chem.GetFormalCharge(mol), 'Fragments': len(Chem.GetMolFrags(mol))})
                    if any(label == '?' for _, label in Chem.FindMolChiralCenters(mol, includeUnassigned=True)):
                        st.warning('Unspecified stereochemistry detected. Review the submitted identity.')
                except ValueError as exc:
                    st.error(str(exc))
            protocol()
            if st.button('Run replicated P2X4 consensus', type='primary', use_container_width=True):
                try:
                    worker.submit(owner, validate([dict(compound_id=code.strip(), compound_name=name.strip(), smiles=smiles.strip())]))
                    st.success('Compound queued. Follow progress in Recent jobs.')
                except ValueError as exc:
                    st.error(str(exc))
        with workflow, st.container(border=True):
            st.subheader('02 · Workflow')
            for title, detail in [('Structure QC', 'SMILES parsing, charge and stereochemistry'), ('Ligand preparation', 'ETKDGv3, MMFF/UFF and Meeko'), ('P2X4 docking', 'Fixed 9BQI trimer and BAY-1797 site'), ('Pose analysis', 'Contacts, anchors, clashes and seed consistency'), ('Evidence report', 'JSON, CSV, SDF, PDBQT and readable summary')]:
                st.markdown(f'**{title}**'); st.caption(detail)
            st.info('Rigid inhibited-state receptor. Docking cannot establish agonism, antagonism or measured affinity.')
    with batch, st.container(border=True):
        st.subheader('Batch consensus campaign')
        st.write('Upload up to 25 compounds. Names are retained as supplied. The shared worker processes one compound at a time.')
        st.download_button('Download batch template', 'compound_id,Compound Name,SMILES\nEX001,Ethanol,CCO\n', 'batch-template.csv')
        upload = st.file_uploader('CSV file', type='csv')
        rows = None
        if upload:
            try:
                if upload.size > 200_000:
                    raise ValueError('CSV must be smaller than 200 KB.')
                reader = csv.DictReader(io.StringIO(upload.getvalue().decode('utf-8-sig')))
                if not {'compound_id', 'Compound Name', 'SMILES'} <= set(reader.fieldnames or []):
                    raise ValueError('Required columns: compound_id,Compound Name,SMILES')
                rows = validate([dict(compound_id=r['compound_id'].strip(), compound_name=r['Compound Name'].strip(), smiles=r['SMILES'].strip()) for r in reader])
                st.dataframe(rows, hide_index=True, use_container_width=True)
            except (ValueError, TypeError, AttributeError) as exc:
                st.error(str(exc)); rows = None
        with st.expander('Fixed batch protocol'):
            protocol()
        if st.button('Queue consensus campaign', type='primary', disabled=rows is None):
            try:
                worker.submit(owner, rows)
                st.success(f'{len(rows)} compounds queued.')
            except ValueError as exc:
                st.error(str(exc))
    recent_jobs()

elif page == 'Compound registry':
    hero('In-silico P2X4 portfolio', 'Compound registry.', 'Search your private compounds, open their evidence and compare completed calculations.' if cloud_mode else 'Search this session’s compounds, open their evidence and compare completed calculations.')
    @st.fragment(run_every=5)
    def registry():
        jobs = owned_jobs()
        cols = st.columns(3)
        for col, label, count in zip(cols, ['Your compounds', 'Completed', 'Waiting / running'], [len(jobs), sum(j['state']=='complete' for j in jobs), sum(j['state'] in ('queued','running') for j in jobs)]):
            col.metric(label, count)
        search = st.text_input('Search code, supplied name or SMILES').lower().strip()
        status = st.selectbox('Status', ['All', 'complete', 'running', 'queued', 'failed', 'cancelled', 'interrupted'])
        filtered = [j for j in jobs if (status == 'All' or j['state']==status) and search in ' '.join([j['compound_id'], j['compound_name'], j['smiles']]).lower()]
        if not jobs:
            st.info('No compounds yet. Submit a structure in Test a compound.')
        if filtered:
            st.dataframe([table_row(j) for j in filtered], hide_index=True, use_container_width=True)
            chosen = st.selectbox('Open a compound', [j['job_id'] for j in filtered], format_func=lambda jid: next(f"{j['compound_id']} · {j['compound_name']} · {j['state']}" for j in filtered if j['job_id']==jid))
            if st.button('Open result', on_click=navigate, args=('Compound results', chosen), type='primary'):
                st.rerun()
            st.download_button('Export registry CSV', csv_bytes([table_row(j) for j in filtered]), 'p2x4-session-registry.csv')
        if st.button('Compare completed compounds', on_click=navigate, args=('Compare compounds',)):
            st.rerun()
        st.caption('Private Supabase records. Existing laptop accounts and jobs have not been migrated.' if cloud_mode else 'Session records only. This view does not import private records from the original platform or automatically resolve duplicate identities.')
    registry()

elif page == 'Compound results':
    hero('Traceable computational evidence', 'Compound result.', 'Review one calculation in a dedicated workspace.')
    @st.fragment(run_every=5)
    def detail():
        jobs = owned_jobs()
        if not jobs:
            st.info('Submit a compound to create a result.'); return
        ids = [j['job_id'] for j in jobs]
        preferred = st.session_state.get('selected_job')
        if preferred not in ids:
            st.session_state.selected_job = ids[-1]
        selected = st.selectbox('Compound', ids, key='selected_job', format_func=lambda jid: next(f"{j['compound_id']} · {j['compound_name']}" for j in jobs if j['job_id']==jid))
        job = next(j for j in jobs if j['job_id']==selected)
        st.caption(f"Status: {job['state']} · Job {job['job_id']}")
        progress(job)
        result = read_result(job)
        if result:
            structure, identity = st.columns([1, 1.5])
            with structure:
                st.image(Draw.MolToImage(Chem.MolFromSmiles(job['smiles']), size=(500, 300)))
            with identity:
                st.subheader(job['compound_id']); st.write(job['compound_name'])
                st.caption('Name as supplied; not an independently verified IUPAC assignment.')
                desc = result.get('descriptors', {})
                st.write(f"**Molecular formula:** {desc.get('molecular_formula', 'Unavailable')}")
                st.write(f"**Molecular weight:** {desc.get('molecular_weight', 'Unavailable')} g/mol")
                st.caption('Chemical class: not assigned in this edition.')
            summary = result['summary']
            cols = st.columns(3)
            cols[0].metric('Median Vina · kcal/mol', summary['median_vina_score_kcal_mol'])
            cols[1].metric('Site-valid seeds', f"{summary['valid_site_count']}/{summary['seed_count']}")
            cols[2].metric('Native-contact recovery', f"{summary['median_native_contact_recovery']:.1%}")
            st.info('Computational evidence only. The activity rule remains development only; scores and contact recovery do not establish measured affinity or activity.')
            overview, evidence, properties, admet, exports = st.tabs(['Overview', 'Pose & interaction evidence', 'Molecular properties', 'ADMET & Toxicity', 'Report & downloads'])
            with overview:
                st.write(result.get('methods_text', ''))
                with st.expander('Auditable compound record'):
                    st.json({k: result.get(k) for k in ['submitted_identity', 'input', 'settings', 'hosting', 'microspecies_enumeration']})
                with st.expander('Warnings and interpretation'):
                    for warning in result.get('warnings', []):
                        st.write(warning)
            with evidence:
                with st.expander('Per-seed evidence'):
                    st.dataframe(result.get('per_seed', []), hide_index=True, use_container_width=True)
                with st.expander('State-level evidence'):
                    st.dataframe([dict(m['state'], **m['summary']) for m in result.get('microspecies', [])], hide_index=True, use_container_width=True)
                    st.json(result.get('microspecies_consensus', {}), expanded=False)
                st.caption('Contacts above come from the docking runner. ProLIF interaction diagrams and TIFF generation are not available in this cloud edition.')
            with properties:
                st.dataframe([{'Property': k, 'Value': str(v)} for k,v in desc.items()], hide_index=True, use_container_width=True)
                st.caption('Calculated descriptors, not an ADMET or toxicity prediction. External predictions, if imported, are available under ADMET & Toxicity.')
            with admet:
                from admet_reports import render as render_admet
                def save_admet(report):
                    updated = dict(result, admet_report=report)
                    if cloud_mode:
                        client.update_job(selected, {'result': updated})
                        worker._at = float('-inf')
                    path = worker.root / selected / 'result.json'
                    if path.is_file():
                        temporary = path.with_suffix('.admet.tmp')
                        temporary.write_text(json.dumps(updated, indent=2))
                        temporary.replace(path)
                render_admet(job, result, save_admet, shared_worker if cloud_mode else worker, owner)
            with exports:
                st.download_button('Download result JSON', json.dumps(result, indent=2), f'{selected}-result.json', mime='application/json')
                st.download_button('Download per-seed CSV', csv_bytes(result.get('per_seed', [])), f'{selected}-seeds.csv')
                st.caption('The complete ZIP below includes prepared structures, docked poses, logs and the methods report.')
        if job['state'] in ('complete', 'failed'):
            if cloud_mode and not job.get('archive_sha256'):
                if st.button('Retry cloud save', key='retry-save-' + selected):
                    try:
                        worker.retry_save(owner, selected)
                        st.success('Cloud save completed.')
                    except ValueError as exc:
                        st.error(str(exc))
            # Prepare explicitly to avoid fetching private archives every five seconds.
            if st.button('Prepare evidence ZIP download', key='prepare-' + selected):
                try:
                    data = worker.download(owner, selected)
                    st.download_button('Download evidence ZIP', data, f'{selected}.zip', type='primary')
                except (ValueError, PermissionError) as exc:
                    st.error(str(exc))
    detail()

elif page == 'How to cite':
    from citations import render
    render()

elif page == 'Compare compounds':
    hero('Side-by-side evidence', 'Compare compounds.', 'Review up to four completed calculations without treating docking scores as measured affinities.')
    jobs = [j for j in owned_jobs() if read_result(j)]
    if len(jobs) < 2:
        st.info('Complete at least two compounds in this session to compare them.')
    else:
        selected = st.multiselect('Choose two to four compounds', [j['job_id'] for j in jobs], max_selections=4, format_func=lambda jid: next(f"{j['compound_id']} · {j['compound_name']} ({jid[:6]})" for j in jobs if j['job_id']==jid))
        if len(selected) >= 2:
            chosen = [next(j for j in jobs if j['job_id']==jid) for jid in selected]
            for col, job in zip(st.columns(len(chosen)), chosen):
                result = read_result(job)
                with col, st.container(border=True):
                    st.subheader(job['compound_id']); st.write(job['compound_name'])
                    st.image(Draw.MolToImage(Chem.MolFromSmiles(job['smiles']), size=(350, 240)))
                    st.metric('Median Vina · kcal/mol', result['summary']['median_vina_score_kcal_mol'])
                    st.metric('Site-valid fraction', f"{result['summary']['valid_site_fraction']:.1%}")
                    st.write(f"Native-contact recovery: {result['summary']['median_native_contact_recovery']:.1%}")
                    st.write(f"Molecular weight: {result['descriptors']['molecular_weight']} g/mol")
                    with st.expander('Protocol and provenance'):
                        st.json(result['settings'])
            st.download_button('Export comparison CSV', csv_bytes([table_row(j) for j in chosen]), 'p2x4-comparison.csv')

else:
    hero('Target receptor reference', 'More about P2X4.', 'An ATP-gated cation channel with a structurally defined allosteric pocket.')
    biology, structure, scope = st.tabs(['P2X family & activation', 'Structural model', 'Workflow scope & sources'])
    with biology:
        st.subheader('Three subunits. One central pore.')
        st.write('P2X receptors are ATP-gated ion channels, distinct from metabotropic P2Y receptors. P2X1–P2X7 comprise the family. Each subunit has two transmembrane helices and a large extracellular domain; three subunits form a channel.')
        st.write('ATP binds between neighboring subunits, driving conformational changes that open a nonselective cation pathway. P2X4 is studied in neuroimmune signaling, pain, inflammation and vascular biology. Findings depend on species, tissue and assay conditions.')
        st.markdown('**Apo closed → ATP engaged → Open pore → Desensitized**')
        if (ROOT / 'pathway.mp4').exists():
            st.video(str(ROOT / 'pathway.mp4'))
        st.caption('Explanatory biological context; not a molecular dynamics simulation.')
    with structure:
        st.subheader('PDB 9BQI · BAY-1797 pocket')
        st.write('The workflow retains the human P2X4 A/B/C trimer in a rigid inhibited-state configuration. The search box is centered on the BAY-1797 allosteric pocket. Five deterministic seeds are run for each retained microspecies.')
        protocol()
    with scope:
        st.write('Supports pose generation, pocket-contact analysis, clash checks, replicated Vina scores and traceable evidence downloads. It does not establish measured affinity, functional antagonism, selectivity, efficacy, safety or therapeutic benefit.')
        st.markdown('[RCSB PDB 9BQI](https://www.rcsb.org/structure/9BQI) · [Primary structural study](https://pubmed.ncbi.nlm.nih.gov/39823330/) · [IUPHAR P2X family review](https://pubmed.ncbi.nlm.nih.gov/33125712/)')

st.divider()
st.caption('P2X4 Dock · Experimental live edition | Private Supabase accounts and saved evidence | Role-protected queue administration | Optional ADMET-AI inference available · ProLIF is not enabled in this edition.' if cloud_mode else 'P2X4 Dock · Experimental live edition | Session storage only | Researcher accounts, permanent registry and administrator controls remain on the original platform.')
