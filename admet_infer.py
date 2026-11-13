"""CPU-only, isolated ADMET-AI inference for one selected structure."""
import csv
import hashlib
import importlib.metadata
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def predict(smiles):
    import torch
    import admet_ai
    from admet_ai import ADMETModel
    torch.set_num_threads(1)
    package = Path(admet_ai.__file__).parent
    metadata_path = package / 'resources/data/admet.csv'
    with metadata_path.open() as handle:
        metadata = list(csv.DictReader(handle))
    model = ADMETModel(include_physchem=False, drugbank_path=None, num_workers=0)
    values = model.predict(smiles=smiles)
    endpoints = {}
    for row in metadata:
        key = row['id']
        if row['category'] == 'Physicochemical' or key not in values:
            continue
        classification = row['task_type'] == 'classification'
        endpoints[key] = {'label': row['name'], 'category':row['category'], 'prediction':float(values[key]),
            'task_type':row['task_type'], 'units':'probability of model-positive endpoint' if classification else row['units'] or 'model scale',
            'confidence':None, 'reference_url':row['url'], 'species':row.get('species')}
    if not endpoints:
        raise RuntimeError('Model returned no supported ADMET endpoints.')
    return {'schema_version':'p2x4-external-admet-1', 'evidence_type':'ADMET-AI inference on the application server',
        'model':'ADMET-AI', 'model_version':importlib.metadata.version('admet-ai'),
        'model_generation':'v2 / Chemprop v2', 'generated_at':datetime.now(timezone.utc).isoformat(),
        'source':'https://github.com/swansonk14/admet_ai', 'paper':'https://doi.org/10.1093/bioinformatics/btae416',
        'input_smiles':smiles, 'endpoints':endpoints, 'execution':'CPU; one inference task at a time in the shared docking executor',
        'software_versions':{name:importlib.metadata.version(name) for name in ('admet-ai','chemprop','torch','rdkit')},
        'model_files_sha256':{str(p.relative_to(package)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((package/'resources/models').rglob('*')) if p.is_file()},
        'limitations':'In-silico screening only; not a safety determination. Per-compound confidence and applicability-domain estimates are not supplied by this interface. ADMET-AI v2 was retrained and does not reproduce the published/web-server v1 predictions exactly.'}

if __name__ == '__main__':
    request = json.loads(Path(sys.argv[1]).read_text())
    result = predict(request['smiles'])
    Path(sys.argv[2]).write_text(json.dumps(result,indent=2,allow_nan=False))
