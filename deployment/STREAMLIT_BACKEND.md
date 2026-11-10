# Connect Streamlit to the full P2X4 platform

Status: integration prepared; activation requires a persistent public backend.
The live Streamlit app continues in temporary mode until configured.

## Deployment

1. Deploy the existing Docker Compose bundle on a persistent Linux x86-64 host.
   An institutional server can serve this role; Streamlit Community Cloud does
   not run this Compose stack. Follow deployment/README.md for HTTPS, PostgreSQL,
   the result volume, SMTP, worker and backups. Do not expose the laptop database.
2. Compose enables `INSTALL_ADMET_AI=1` by default. This installs the existing
   ADMET-AI 2.0.1 model runtime in /opt/admet, separately from docking libraries.
   CPU PyTorch 2.15.0 is pinned to the local runtime version. The image build and
   model inference must be tested on the target host. Set P2X4_INSTALL_ADMET_AI=0
   if deliberately deploying without this feature; the API reports unavailable.
3. Register and verify the first administrator before allowing public registration.
   Test a second ordinary researcher account and verify that it cannot access
   administration or another account's jobs. Configure SMTP recovery links using
   the public backend URL, not localhost.
4. In the Streamlit app's Secrets, set only:

   ```toml
   P2X4_BACKEND_URL = "https://YOUR-BACKEND-HOST"
   ```

   No shared service-owner bearer token is used. End users sign in independently.
   Credentials are sent only to the operator-configured HTTPS origin. Redirects
   are rejected. For a local isolated test only, use P2X4_BACKEND_LOCAL_TEST=1 and
   an HTTP loopback origin; never enable that flag in Community Cloud.
5. The app automatically switches to backend mode. Run the acceptance checks
   below before announcing that durable research accounts are available.

## Acceptance checks

- Confirm /api/health and the worker heartbeat, database and result volumes.
- Sign in, submit a single compound and a batch, then sign out and back in.
  Confirm the registry and downloadable records remain available.
- Confirm ordinary users cannot read administrator data or another user's jobs.
- Pause/resume/stop a whole batch as administrator. Running work must finish
  safely; completed evidence must remain. These are the existing backend semantics.
- Open an audit record with run_admet=0 and confirm inference does not start.
  Run ADMET explicitly, verify versioned JSON output and complete endpoint evidence.
- Generate ProLIF JSON/CSV and the 600-DPI 2D TIFF under P2X4_JOBS_DIR, not /app/jobs.
  The optional 3D ChimeraX composite still requires a working ChimeraX installation.
- Restart web and worker containers, restore a backup on a separate host, and
  verify persisted ownership, queue state and files.

The Streamlit connection does not itself provide storage. Persistence and
availability come from the backend's database, volumes, host and backups. The
local account database and private results are not uploaded by this integration.
The existing backend rate limiter aggregates failed logins by source IP; because
Streamlit proxies requests, a shared source IP may cause temporary cross-user
login throttling. Test this before opening broad public registration. Do not
disable throttling to work around it.
