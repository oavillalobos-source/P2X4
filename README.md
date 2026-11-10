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

Do not upload the original jobs directory, account database, tokens or private
validation truth to the deployment repository. The package builder includes
only source code and fixed reference inputs.

After deployment, confirm the app builds on Linux and complete a reference
compound before distributing the live docking link. Community Cloud can sleep,
restart or throttle computation. Completing the deployment does not validate
the biological activity model, which remains development only.
