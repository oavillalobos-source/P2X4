# Supabase + Streamlit pilot

This mode stores accounts in Supabase Auth, researcher-owned submission/result
records in Postgres, and completed evidence ZIPs in a private Storage bucket.
Streamlit still executes the existing five-seed protocol serially. It is not a
persistent docking-worker service. No receptor, seed, rule, threshold, pH or
microspecies setting is changed.

## Provision and activate

1. Create a Free Supabase project. Enable Data API and automatic row-level
   security; turn off automatic table exposure. Save the database password
   yourself. This application does not need that password or a service-role key.
2. Apply `schema.sql` in the project's SQL editor. Check RLS and a private
   `p2x4-evidence` bucket. Do not add permissive policies to these tables/bucket.
3. Use the Project URL and **publishable** key from Project Settings > API Keys.
   Add them in Streamlit Secrets, following the packaged
   `supabase-secrets.example.toml`. Never commit credentials. Backend mode and
   Supabase mode are mutually exclusive. Configuration/network errors fail
   closed, not back to anonymous operation.
4. Set Authentication Site URL to `https://p2x4-live.streamlit.app/`.
   Keep email confirmation enabled. Configure a custom SMTP provider before
   public registrations: Supabase's default mailer only sends to project team
   addresses. Verify the provider's quotas, domain and deliverability.
5. In the Reset Password email template include `{{ .Token }}` (recovery code),
   with instructions to enter it in the app's Forgot password form. The app
   validates this code with Supabase before accepting a new password. Signup
   uses Supabase's normal confirmation link then a separate password sign-in.
6. Only after SMTP, recovery and ownership checks pass, set
   `P2X4_SUPABASE_SIGNUP_ENABLED = true`. Otherwise signup/recovery forms remain
   disabled. This flag is an interface gate; Supabase's own signup setting must
   also be restricted if invitations-only membership is intended.

## Acceptance checks before inviting researchers

- Two controlled test identities: A and B can each create/list/update their own
  job records. They cannot read/change each other's job IDs, even through a
  direct REST request. Anonymous API reads/writes must fail.
- Evidence uploaded to A's folder can be downloaded by A and cannot be read or
  overwritten by B or anonymously. No public bucket or public URL is used.
- Downloaded ZIP SHA-256 and size match the registry. A failed upload shows a
  warning; Retry cloud save does not run docking again.
- A refresh/sign-out/sign-in restores saved records to the same verified user.
  A different user's sign-in never inherits job selection or downloaded bytes.
- Validate registration, email confirmation and password-recovery code with
  the actual SMTP configuration, including expired/reused recovery codes.
- Execute a disposable reference compound on the deployed Linux runner and
  confirm result JSON plus full ZIP persistence. A saved record alone does not
  prove the evidence ZIP was uploaded.

## Honest operating limits

- This is a pilot with a 25 MB per-archive cap and provider storage/request/
  egress limits. Supabase Free projects can pause after low activity; no free
  always-on guarantee is made. Maintain independent backups.
- Queued/running metadata is saved before submission, and finished/failed
  evidence is archived after the process exits. Abrupt host termination can
  lose unsaved intermediate files. This runner rejects nonempty output
  directories and does NOT support checkpoint resume. A missing local worker's
  unfinished records are labeled interrupted, not complete. Resubmit as a new
  traceable calculation; do not force-overwrite old evidence.
- The one-worker limit is per Streamlit process, not a distributed queue lease.
  Do not deploy multiple workers against this project assuming global serial
  execution. Administration/batch scheduling is not migrated here.
- Signing out revokes/clears that session's credentials. A calculation may
  finish locally without being able to save; sign in and retry saving before
  the Streamlit instance disappears. Refreshing the browser alone does not
  revoke the worker's existing session.
- Registry rows are owner-editable via authenticated APIs. They are private
  research records, not immutable or independently signed publication evidence.
- Original laptop accounts/jobs are NOT automatically uploaded or migrated.
  ADMET, ProLIF, privileged admin controls and permanent external workers are
  not enabled by adding Supabase storage.

## Sources

- https://supabase.com/docs/guides/database/postgres/row-level-security
- https://supabase.com/docs/guides/storage/security/access-control
- https://supabase.com/docs/guides/auth/auth-smtp
- https://supabase.github.io/auth/
- https://supabase.com/docs/guides/platform/free-project-pausing

## Administrator role
Apply admin.sql in the Supabase SQL editor as project owner after reviewing the named confirmed account. Only that user receives the role. Authenticated users cannot read or edit the role table; the RPC reports only their own membership. Every queue control rechecks the server role. Remove membership via owner SQL to revoke access. Existing job/storage ownership policies are unchanged.

The Administration page exposes aggregate counts and pause/resume dispatch for the current Streamlit worker. Running jobs finish; waiting jobs remain queued. Pause state resets on host restart. It does not expose private structures, manage researcher credentials, or stop/resume running calculations.
