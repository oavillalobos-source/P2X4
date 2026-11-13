"""Opt-in, structure-checked external ADMET evidence; no inferred predictions."""
import csv
import io
import json
import math
from datetime import datetime, timezone
from rdkit import Chem

MAX_BYTES = 1024 * 1024

def canonical(smiles):
    if not isinstance(smiles, str) or len(smiles) > 20000:
        raise ValueError('A valid input_smiles is required.')
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError('Invalid report structure.')
    return Chem.MolToSmiles(mol, isomericSmiles=True)

def validate_report(raw, smiles):
    if len(raw) > MAX_BYTES:
        raise ValueError('Report must be smaller than 1 MB.')
    try:
        report = json.loads(raw)
    except (ValueError, UnicodeError):
        raise ValueError('Upload a valid JSON prediction report.') from None
    if not isinstance(report, dict):
        raise ValueError('Report must be a JSON object.')
    if canonical(report.get('input_smiles')) != canonical(smiles):
        raise ValueError('Report structure does not match this submitted compound, including stereochemistry and charge. Use a report for the exact submitted structure.')
    for field in ('model', 'model_version', 'generated_at', 'source'):
        if not isinstance(report.get(field), str) or not report[field].strip() or len(report[field]) > 2000 or report[field].startswith('REPLACE'):
            raise ValueError(f'Missing or invalid {field}.')
    try:
        datetime.fromisoformat(report['generated_at'].replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('generated_at must be an ISO date or timestamp.') from None
    endpoints = report.get('endpoints')
    if not isinstance(endpoints, dict) or not 1 <= len(endpoints) <= 200:
        raise ValueError('Provide 1–200 named endpoints.')
    clean = {}
    for name, row in endpoints.items():
        if not isinstance(row, dict) or not isinstance(name,str) or len(name)>200:
            raise ValueError('Each endpoint must be a named object.')
        if name.startswith('REPLACE'):
            raise ValueError('Replace template placeholders with actual provider results.')
        value = row.get('prediction')
        if isinstance(value,bool) or not isinstance(value,(str,int,float)) or (isinstance(value,(int,float)) and not math.isfinite(value)):
            raise ValueError(f'{name}: provide a finite prediction or a category label.')
        if not isinstance(row.get('units'),str) or not row['units'].strip():
            raise ValueError(f'{name}: units or category meaning is required.')
        confidence = row.get('confidence')
        if confidence is not None and (not isinstance(confidence,dict) or not isinstance(confidence.get('method'),str) or not confidence['method'].strip() or not isinstance(confidence.get('value'),(str,int,float)) or isinstance(confidence.get('value'),bool)):
            raise ValueError(f'{name}: confidence requires value and method, or null when unavailable.')
        if confidence is not None and isinstance(confidence['value'],(int,float)) and not math.isfinite(confidence['value']):
            raise ValueError('Confidence must be finite.')
        clean[name] = {k:row.get(k) for k in ('label','prediction','units','task_type','confidence','reference_url','category')}
    return {'schema_version':'p2x4-external-admet-1', 'evidence_type':'researcher-imported prediction; not independently verified',
            'model':report['model'], 'model_version':report['model_version'], 'generated_at':report['generated_at'],
            'source':report['source'], 'input_smiles':report['input_smiles'], 'endpoints':clean,
            'imported_at':datetime.now(timezone.utc).isoformat(), 'limitations':report.get('limitations','Provider applicability domain and uncertainty must be checked against the original report.')}

def rows(report):
    return [dict(endpoint=k, category=v.get('category','Not supplied'), prediction=v['prediction'], units=v['units'],
        confidence=v['confidence']['value'] if v.get('confidence') else 'Not supplied',
        confidence_method=v['confidence']['method'] if v.get('confidence') else 'Not supplied',
        provider=report['model'], model_version=report['model_version'], generated_at=report['generated_at'], source=report['source']) for k,v in report['endpoints'].items()]

def render(job, result, save, engine=None, owner=None):
    import streamlit as st
    st.subheader('ADMET & Toxicity')
    st.write('Run ADMET-AI for this selected compound, or import an external report. Batch docking does not automatically trigger profiling.')
    if engine is not None:
        from admet_tasks import submit, get_task
        task = get_task(engine, owner, job['job_id'])
        busy = bool(task and task['state'] in ('queued','running'))
        if st.button('Run ADMET & Toxicity', key='admet-run-'+job['job_id'], disabled=busy):
            try:
                submit(engine, owner, job, save)
                task = get_task(engine, owner, job['job_id'])
            except ValueError as exc:
                st.error(str(exc))
        if task:
            if task['state'] in ('queued','running'):
                st.info('ADMET: ' + task['state'] + '. Shares the docking queue; this view refreshes automatically.')
            elif task['state'] == 'failed':
                st.error(task['error'])
            elif task.get('report'):
                result = dict(result, admet_report=task['report'])
                if task.get('save_error'):
                    st.warning(task['save_error'])
                    if st.button('Retry saving ADMET report',key='admet-retry-'+job['job_id']):
                        try:
                            save(task['report'])
                            with engine.lock:
                                engine._admet_tasks[(owner,job['job_id'])].pop('save_error',None)
                            st.success('Report saved.')
                        except (ValueError,OSError) as exc:
                            st.error(str(exc))
                else:
                    st.success('ADMET inference completed and report saved.')
    st.caption('Supports the original platform’s ADMET-AI JSON or the template below. For ProTox or other providers, transcribe the original report into the template and retain its provenance. Structures are checked exactly; provider authenticity is not independently verified.')
    template = {'input_smiles':job['smiles'], 'model':'REPLACE with provider/model', 'model_version':'REPLACE with actual version',
        'generated_at':'REPLACE with ISO date', 'source':'REPLACE with original report URL or identifier',
        'endpoints':{'REPLACE with endpoint':{'prediction':'REPLACE with reported value','units':'REPLACE with units or class definition','confidence':None}}}
    st.download_button('Download import template', json.dumps(template,indent=2),f"{job['compound_id']}-admet-template.json",mime='application/json',key='admet-template-'+job['job_id'])
    upload = st.file_uploader('Import prediction report (JSON, up to 1 MB)',type=['json'],key='admet-upload-'+job['job_id'])
    if upload is not None:
        try:
            candidate = validate_report(upload.getvalue(),job['smiles'])
            st.dataframe(rows(candidate),hide_index=True)
            st.write('Provider/model:', candidate['model'], '· Version:', candidate['model_version'])
            if st.button('Save this ADMET report',key='admet-save-'+job['job_id']):
                save(candidate)
                result['admet_report'] = candidate
                st.success('Report saved. Download the separate ADMET report below; previously downloaded docking ZIPs are unchanged.')
        except (ValueError, OSError) as exc:
            st.error(str(exc))
    report = result.get('admet_report')
    if report:
        st.markdown('**ADMET prediction report**')
        st.write('Provider/model:',report['model'],'· Version:',report['model_version'])
        st.write('Prediction date:',report['generated_at'])
        st.write('Source:',report['source'])
        if report.get('model') == 'ADMET-AI':
            st.markdown('[ADMET-AI method paper](https://doi.org/10.1093/bioinformatics/btae416) · [Model software](https://github.com/swansonk14/admet_ai)')
        with st.expander('Model and execution provenance'):
            st.json({k:report.get(k) for k in ('model_generation','software_versions','model_files_sha256','execution') if k in report})
        st.caption(report['evidence_type'])
        st.dataframe(rows(report),hide_index=True)
        st.write(report['limitations'])
        st.download_button('Download ADMET JSON',json.dumps(report,indent=2),f"{job['compound_id']}-admet.json",mime='application/json',key='admet-json-'+job['job_id'])
        output=io.StringIO(); data=rows(report);writer=csv.DictWriter(output,fieldnames=list(data[0]));writer.writeheader();writer.writerows(data)
        st.download_button('Download ADMET CSV',output.getvalue(),f"{job['compound_id']}-admet.csv",mime='text/csv',key='admet-csv-'+job['job_id'])
    else:
        st.info('No ADMET or toxicity prediction has been saved for this compound.')
    st.caption('Endpoint probabilities are predictions, not confidence estimates. Missing confidence is shown as “Not supplied.” These predictions do not establish safety or replace experimental testing.')
