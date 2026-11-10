# P2X4 Dock — Streamlit demonstration edition

This is a read-only, free-hosting-compatible demonstration of the frozen
223-compound SNP-library reproducibility campaign. It accepts a compound code,
name or SMILES and returns an exact match only when that standardized structure
already exists in the bundled precomputed dataset.

It deliberately does **not** run AutoDock Vina, estimate a score for an unseen
SMILES, predict biological activity, or retain user uploads.

## Refresh the frozen dataset

From the project root, using the validated project environment:

```bash
environment/.venv/bin/python streamlit_demo/prepare_demo_data.py
```

## Run locally

```bash
python -m venv streamlit_demo/.venv
streamlit_demo/.venv/bin/pip install -r streamlit_demo/requirements.txt
streamlit_demo/.venv/bin/streamlit run streamlit_demo/streamlit_app.py
```

## Deploy to Streamlit Community Cloud

Place `streamlit_demo/` in a GitHub repository, connect that repository at
`share.streamlit.io`, and choose `streamlit_demo/streamlit_app.py` as the entry
point. No secrets are required. The app may sleep when inactive and generated
files are not durable, but this edition depends only on its versioned read-only
JSON dataset.

