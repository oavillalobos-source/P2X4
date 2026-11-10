import csv
import io
import json
import uuid
import streamlit as st
from rdkit import Chem
from rdkit.Chem import Draw
from engine import Engine

st.set_page_config(page_title='P2X4 Dock · Live experimental edition', page_icon='🧬', layout='wide')
st.title('P2X4 Dock')
st.caption('Live experimental docking on Streamlit Community Cloud')
st.warning('Results and queued jobs are temporary. Hosting restarts can interrupt calculations or remove files. Download each completed result. Refreshing or closing the session can lose access to its jobs.')
st.info('Human P2X4 · 9BQI · BAY-1797 pocket · five frozen seeds · pH 6.8–8.0 · up to eight microspecies. Vina scores are computational scores. The activity model remains development only and has not been externally validated.')

@st.cache_resource
def engine():
    return Engine()

if 'owner' not in st.session_state:
    st.session_state.owner = uuid.uuid4().hex
owner = st.session_state.owner
worker = engine()

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

single, batch = st.tabs(['Test a compound', 'Batch campaign'])
with single:
    with st.form('single'):
        code = st.text_input('Compound code', max_chars=80)
        name = st.text_input('Compound name or IUPAC name as supplied', max_chars=500)
        smiles = st.text_area('Isomeric SMILES', max_chars=4000)
        submit = st.form_submit_button('Queue live docking')
    if submit:
        try:
            worker.submit(owner, validate([dict(compound_id=code.strip(), compound_name=name.strip(), smiles=smiles.strip())]))
            st.success('Compound queued.')
        except ValueError as exc:
            st.error(str(exc))
with batch:
    st.download_button('Download batch template', 'compound_id,Compound Name,SMILES\nEX001,Ethanol,CCO\n', 'batch-template.csv')
    upload = st.file_uploader('CSV · up to 25 compounds', type='csv')
    if st.button('Queue batch', disabled=upload is None):
        try:
            if upload.size > 200_000:
                raise ValueError('CSV must be smaller than 200 KB.')
            reader = csv.DictReader(io.StringIO(upload.getvalue().decode('utf-8-sig')))
            if not {'compound_id', 'Compound Name', 'SMILES'} <= set(reader.fieldnames or []):
                raise ValueError('Required columns: compound_id,Compound Name,SMILES')
            rows = [dict(compound_id=r['compound_id'].strip(), compound_name=r['Compound Name'].strip(), smiles=r['SMILES'].strip()) for r in reader]
            worker.submit(owner, validate(rows))
            st.success(f'{len(rows)} compounds queued.')
        except (ValueError, TypeError, AttributeError) as exc:
            st.error(str(exc))

st.subheader('Your session results')
st.caption('One compound runs at a time across the shared app. ADMET and ProLIF are not included in this experimental edition. The existing researcher accounts and registry remain on the original platform.')
if st.button('Stop my waiting compounds'):
    worker.cancel_waiting(owner)

@st.fragment(run_every=5)
def results():
    for job in worker.owned(owner):
        with st.expander(f"{job['compound_id']} · {job['compound_name']} · {job['state']}", expanded=job['state'] == 'running'):
            path = worker.root / job['job_id']
            if job['state'] == 'running':
                try:
                    progress = json.loads((path / 'status.json').read_text())
                    st.progress(min(100, int(progress.get('progress_percent', 0))), text=progress.get('detail', progress.get('step', 'Running')))
                except (OSError, ValueError):
                    st.write('Preparing calculation…')
            if job.get('error'):
                st.error(job['error'])
            if job['state'] == 'complete':
                result = json.loads((path / 'result.json').read_text())
                st.image(Draw.MolToImage(Chem.MolFromSmiles(job['smiles']), size=(450, 250)))
                st.metric('Median Vina score (kcal/mol)', result['summary']['median_vina_score_kcal_mol'])
                st.json(result['summary'], expanded=False)
            if job['state'] in ('complete', 'failed'):
                st.download_button('Download result and evidence ZIP', worker.download(owner, job['job_id']), f"{job['job_id']}.zip", key=job['job_id'])
results()
