from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import streamlit as st
from rdkit import Chem
from rdkit.Chem import Draw


APP_DIR = Path(__file__).resolve().parent
DATA_FILE = APP_DIR / "precomputed_results.json"

st.set_page_config(
    page_title="P2X4 Dock · Precomputed demonstration",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    :root { --ink:#173236; --teal:#287d72; --sand:#f3eadb; --gold:#d29b42; }
    .stApp { background: #f7f9f6; color: var(--ink); }
    [data-testid="stSidebar"] { background: #173236; color: white; }
    [data-testid="stSidebar"] * { color: white; }
    .hero { padding: 1.4rem 1.6rem; border-radius: 22px; color: white;
      background: linear-gradient(125deg,#173236 0%,#245b59 68%,#287d72 100%);
      box-shadow: 0 18px 44px rgba(23,50,54,.16); margin-bottom: 1rem; }
    .hero small { color:#f0c77e; letter-spacing:.14em; font-weight:800; }
    .hero h1 { margin:.25rem 0 .45rem; font-size:clamp(2rem,5vw,4rem); line-height:.98; }
    .hero p { max-width:780px; color:#e7f1ed; font-size:1.04rem; }
    .notice { padding:.9rem 1rem; border-left:5px solid var(--gold); border-radius:10px;
      background:#fff8e9; margin:.5rem 0 1.2rem; }
    .evidence { background:white; border:1px solid #dce8e3; border-radius:16px;
      padding:1rem 1.1rem; height:100%; }
    .match { border:1px solid #c9ded7; border-radius:18px; padding:1rem 1.1rem;
      background:white; box-shadow:0 8px 24px rgba(23,50,54,.08); }
    div[data-testid="stMetric"] { background:white; border:1px solid #dce8e3;
      padding:.8rem; border-radius:14px; }
    .footer-note { color:#5d706f; font-size:.85rem; border-top:1px solid #dce8e3;
      margin-top:2rem; padding-top:1rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data
def load_data() -> dict[str, object]:
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def canonicalize(value: str) -> str | None:
    mol = Chem.MolFromSmiles(value.strip())
    if mol is None:
        return None
    return Chem.MolToSmiles(mol, isomericSmiles=True, canonical=True)


def molecule_image(smiles: str):
    mol = Chem.MolFromSmiles(smiles)
    return Draw.MolToImage(mol, size=(620, 360), legend="Precomputed library structure")


def records_to_csv(records: list[dict[str, object]]) -> bytes:
    keys = [
        "compound_id", "compound_name", "compound_class", "pubchem_cid", "smiles",
        "formula", "molecular_weight", "original_vina_kcal_mol",
        "redocked_vina_kcal_mol", "score_delta_kcal_mol", "exact_score_match",
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=keys, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(records)
    return output.getvalue().encode("utf-8")


data = load_data()
records: list[dict[str, object]] = data["records"]  # type: ignore[assignment]
protocol: dict[str, object] = data["protocol"]  # type: ignore[assignment]

st.markdown(
    """
    <section class="hero">
      <small>HUMAN P2X4 · READ-ONLY SCIENTIFIC DEMONSTRATION</small>
      <h1>Explore frozen docking evidence.</h1>
      <p>Search the completed SNP-library campaign by compound code, name or SMILES.
      This edition retrieves precomputed results only—it does not run AutoDock Vina.</p>
    </section>
    """,
    unsafe_allow_html=True,
)
st.markdown(
    f'<div class="notice"><strong>Interpretation boundary.</strong> {data["interpretation_boundary"]}</div>',
    unsafe_allow_html=True,
)

with st.sidebar:
    st.subheader("Frozen protocol")
    st.write(f"**Target:** {protocol['target']}")
    st.write(f"**Structure:** {protocol['structure']}")
    st.write(f"**Site:** {protocol['site']}")
    st.write(f"**Vina:** {protocol['vina_version']}")
    st.write(f"**Seed:** `{protocol['seed']}`")
    st.write(f"**Exhaustiveness:** {protocol['exhaustiveness']}")
    st.divider()
    st.caption("No uploads are retained. No new docking, activity prediction or ADMET calculation is performed.")

metric_cols = st.columns(4)
metric_cols[0].metric("Frozen structures", len(records))
metric_cols[1].metric("Redocking complete", protocol["completed"])
metric_cols[2].metric("Exact score matches", protocol["exact_score_matches"])
metric_cols[3].metric("Score drift", "0.000 kcal/mol")

st.subheader("Search a precomputed compound")
example_options = ["", *[f"{r['compound_id']} · {r['compound_name']}" for r in records[:12]]]
example = st.selectbox("Load an example", example_options, help="Examples are drawn from the frozen library.")
default_query = example.split(" · ", 1)[0] if example else ""
with st.form("lookup", clear_on_submit=False):
    query = st.text_input(
        "Compound code, name or isomeric SMILES",
        value=default_query,
        placeholder="Example: SNP00001 or paste a SMILES",
    )
    submitted = st.form_submit_button("Retrieve precomputed evidence", type="primary", use_container_width=True)

if submitted and query.strip():
    raw = query.strip()
    canonical = canonicalize(raw)
    lowered = raw.casefold()
    matches = [
        row for row in records
        if lowered == str(row["compound_id"]).casefold()
        or lowered in str(row["compound_name"]).casefold()
        or lowered in {str(alias).casefold() for alias in row.get("aliases", [])}
        or (canonical is not None and canonical == row["canonical_smiles"])
    ]

    if not matches:
        if canonical is None and not lowered.startswith("snp"):
            st.error("The entry is neither a valid SMILES nor a recognized library identifier.")
        else:
            st.warning(
                "No exact standardized-structure match exists in the frozen demonstration library. "
                "No score has been estimated and no docking job has been started."
            )
    else:
        st.success(f"Found {len(matches)} auditable precomputed record(s).")
        for row in matches:
            st.markdown('<div class="match">', unsafe_allow_html=True)
            left, right = st.columns([1, 1.35], gap="large")
            with left:
                st.image(molecule_image(str(row["smiles"])), use_container_width=True)
            with right:
                st.caption(str(row["compound_id"]))
                st.markdown(f"### {row['compound_name']}")
                st.write(f"**Class:** {row['compound_class']}")
                st.write(f"**Formula:** {row['formula']}")
                st.write(f"**Molecular weight:** {row['molecular_weight']:.3f} g/mol")
                st.code(str(row["smiles"]), language=None)
                score_cols = st.columns(3)
                score_cols[0].metric("Original Vina", f"{row['original_vina_kcal_mol']:.3f}")
                score_cols[1].metric("Redocked Vina", f"{row['redocked_vina_kcal_mol']:.3f}")
                score_cols[2].metric("Difference", f"{row['score_delta_kcal_mol']:.3f}")
                st.caption("Units: kcal/mol. More negative Vina scores are ranking outputs, not measured affinities.")
                if row.get("aliases"):
                    st.write("**Recorded aliases:** " + ", ".join(row["aliases"]))
            st.download_button(
                "Download this frozen record (JSON)",
                data=json.dumps(row, indent=2),
                file_name=f"{row['compound_id']}_precomputed_result.json",
                mime="application/json",
                key=f"download-{row['compound_id']}",
            )
            st.markdown("</div>", unsafe_allow_html=True)

st.divider()
st.subheader("Browse the frozen library")
class_options = sorted({str(row["compound_class"]) for row in records})
selected_classes = st.multiselect("Compound classes", class_options)
filtered = [row for row in records if not selected_classes or row["compound_class"] in selected_classes]
display_rows = [
    {
        "Code": row["compound_id"],
        "Compound": row["compound_name"],
        "Class": row["compound_class"],
        "Formula": row["formula"],
        "MW": row["molecular_weight"],
        "Original Vina": row["original_vina_kcal_mol"],
        "Redocked Vina": row["redocked_vina_kcal_mol"],
        "Exact match": row["exact_score_match"],
    }
    for row in filtered
]
st.dataframe(display_rows, use_container_width=True, hide_index=True)
st.download_button(
    "Download filtered publication table (CSV)",
    data=records_to_csv(filtered),
    file_name="p2x4_snp_precomputed_demo.csv",
    mime="text/csv",
)

with st.expander("Methods and provenance"):
    st.markdown(
        """
        - Source: frozen SNP-library redocking reproducibility campaign v2.
        - Prepared ligand PDBQT files were reused without re-protonation, tautomerization or conformer rebuilding.
        - Receptor, grid, ligand hashes, seed, exhaustiveness and retained modes were locked before redocking.
        - All 223 structures reproduced the original Vina score exactly under unchanged deterministic inputs.
        - The demonstration contains no experimental activity labels and must not be used as clinical evidence.
        """
    )

st.markdown(
    '<div class="footer-note">P2X4 Dock · Precomputed demonstration edition · '
    'Computational hypotheses require experimental confirmation.</div>',
    unsafe_allow_html=True,
)

