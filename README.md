# P2X4 Dock: experimental live Streamlit edition

This edition executes AutoDock Vina within the Streamlit host. Deploy the
allowlisted bundle produced by scripts/53_package_streamlit_live.py, using
streamlit_app.py as the entrypoint and Python 3.12. No external API is required.

The same receptor, grid, five seeds, exhaustiveness 16 and microspecies policy
are retained. Execution is serialized at one CPU per Vina process. Linux output
is a new run and need not reproduce the exact numerical scores from macOS.

Each submission has 1–25 compounds, and the entire shared queue is capped at 25
waiting/running jobs. A job is stopped after two hours; partial output is marked
failed. The pilot rejects structures above 100 heavy atoms. No reduced protocol
is silently substituted for compounds that exceed hosting resources.

Storage and session access are temporary. Download the evidence ZIP when each
job completes. A refresh, hosting restart or cache reset can lose access or
remove results. There is no durable checkpoint restore in this edition.

Researcher accounts, persistent registries, administrator batch controls, ADMET
and ProLIF remain features of the original platform. This experimental edition
uses random session identifiers and does not list another session's compounds.
It is intended for nonconfidential testing.

The interface follows the original green P2/X4 workspace: Test a compound,
Compound registry, More about the target receptor, dedicated Compound results,
and Compare compounds. The registry is session-only; comparison supports two
to four completed jobs. Seed evidence, state evidence and the auditable record
are collapsible. The original pathway video supplies biological context only.
Identity names remain as submitted; chemical classes and verified IUPAC names
are not inferred. No login, admin or external analysis controls are simulated.

## Optional authenticated backend mode

Set `P2X4_BACKEND_URL` in Streamlit Secrets to the HTTPS origin of the original
production backend. The app then uses per-researcher login, backend-owned jobs,
the persistent registry, explicit ADMET requests, existing ProLIF downloads and
role-restricted whole-batch administration. Cookies and CSRF tokens stay in that
researcher's Streamlit session, never a global cache. Passwords are not written
to files. Register, email verification and password recovery use the backend's
existing login page. Backend ownership and administrator checks remain authoritative.

Do not configure the old shared `P2X4_API_TOKEN` bridge for private researchers.
Backend mode fails closed if the backend is down; it never silently sends jobs
to the temporary local worker. Streamlit refresh can require signing in again,
but backend records survive when the backend's database and results volumes
are persistent and backed up. Existing temporary jobs are not automatically migrated.

Without this setting the experimental session-only app remains unchanged.
See `deployment/STREAMLIT_BACKEND.md` in the local full-platform repository for
host requirements and acceptance checks. Laptop-only hosting does not provide
laptop-independent availability or permanent cloud storage.

Do not upload the original jobs directory, account database, tokens or private
validation truth to the deployment repository. The package builder includes
only source code and fixed reference inputs.

After deployment, confirm the app builds on Linux and complete a reference
compound before distributing the live docking link. Community Cloud can sleep,
restart or throttle computation. Completing the deployment does not validate
the biological activity model, which remains development only.

## Optional Supabase cloud storage (no original backend needed)

Set `P2X4_SUPABASE_URL` and `P2X4_SUPABASE_PUBLISHABLE_KEY` to enable per-user
Supabase sign-in, private registry records and private result ZIPs while keeping
experimental docking on Streamlit. Install the provided Supabase schema and
complete access-isolation tests first. The app rejects service-role keys. Do
not configure this alongside `P2X4_BACKEND_URL`.

Save failures remain visible; a completed docking run is not automatically a
successful cloud archive. Interrupted jobs do not resume from checkpoints.
Public signup/recovery stays disabled until SMTP and email templates are set
up and tested. See `deployment/supabase/README.md` in the full local project.
The earlier session-only limitations apply when neither storage mode is set.


### Optional ADMET-AI follow-up
Completed compounds have a Run ADMET & Toxicity button. Requests share the
single docking executor, honor queue pause, and never run automatically for a
batch. ADMET-AI 2.0.1 / Chemprop 2.2.2 uses CPU inference in a subprocess with a
10-minute timeout. The model is released from memory when that process exits.
Reports contain 41 supported ADMET endpoints, model file SHA-256 hashes,
software versions, source and timestamp. Probabilities are not confidence
estimates; unavailable per-compound uncertainty is explicitly missing.
Results save to the private result JSON; separate JSON/CSV downloads include
ADMET evidence. Existing archived docking ZIPs are not automatically replaced.
If cloud save fails (including sign-out), the worker retains the report for
download/retry while that worker survives. Host restart loses unsaved reports.
A local macOS reference test peaked at 574 MB RSS; this is not a Linux cloud
resource guarantee. Free-host interruption or memory failure remains possible.
