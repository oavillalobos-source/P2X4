# P2X4 Dock — Streamlit demonstration edition

This is a read-only, free-hosting-compatible demonstration of the frozen
223-compound SNP-library reproducibility campaign. It accepts a compound code,
name or SMILES and returns an exact match only when that standardized structure
already exists in the bundled precomputed dataset.

It deliberately does **not** run AutoDock Vina, estimate a score for an unseen
SMILES, predict biological activity, or retain user uploads.

## Optional live docking bridge

The Streamlit process never executes Vina. When a separately hosted P2X4
backend is configured, the interface can submit one atomic job, poll its
checkpointed status, and retrieve its completed JSON result. The backend keeps
PostgreSQL, the worker and all generated files outside Community Cloud.

Configure the backend with the matching values documented in
`deployment/.env.example`, then add these values in the Streamlit Community
Cloud Secrets editor:

```toml
P2X4_API_URL = "https://YOUR-DOCKING-API"
P2X4_API_TOKEN = "A-LONG-RANDOM-SHARED-BRIDGE-TOKEN"
```

The backend service account identified by `P2X4_STREAMLIT_OWNER_EMAIL` must
already exist and be verified. Keep `P2X4_STREAMLIT_SUBMISSIONS_ENABLED=0`
until a known reference-compound acceptance test passes. This pilot bridge is
shared and must not be used for confidential structures or unrestricted public
submissions.

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

