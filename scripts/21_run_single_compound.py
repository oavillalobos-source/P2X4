#!/usr/bin/env python3
"""Run one compound through the validated human P2X4 docking workflow.

The runner accepts either a SMILES string or a single-molecule SDF, creates an
isolated job directory, prepares the ligand with Meeko, docks it to the fixed
9BQI BAY-1797 site, and writes machine-readable and human-readable results.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import itertools
import json
import math
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem, Crippen, Descriptors, Lipinski, QED, rdMolAlign, rdMolDescriptors

from p2x4_microspecies import enumerate_microspecies


ROOT = Path(__file__).resolve().parents[1]
RECEPTOR_PDBQT = ROOT / "01_receptor/prepared/P2X4_9BQI_BAY_site.pdbqt"
RECEPTOR_PDB = ROOT / "01_receptor/clean/P2X4_9BQI_trimer_protein.pdb"
BOX = ROOT / "01_receptor/prepared/P2X4_9BQI_BAY_site.box.txt"
NATIVE = ROOT / "00_reference/native_ligand/BAY-1797_9BQI_chainA_bound.sdf"
MICROSPECIES_RULE = ROOT / "05_analysis/microspecies_calibration/P2X4_microspecies_rule.json"
MEEKO_PREPARE = ROOT / "environment/.venv/bin/mk_prepare_ligand.py"
MEEKO_EXPORT = ROOT / "environment/.venv/bin/mk_export.py"
VINA = Path(shutil.which("vina") or Path.home() / ".local/bin/vina")
DEFAULT_SEEDS = (20261014, 20261015, 20261016, 20261017, 20261018)
ANCHORS = {"A:ASP88", "A:VAL90", "A:PHE296", "A:LYS298", "B:TYR299"}
SCORE_PATTERN = re.compile(r"^REMARK VINA RESULT:\s+(-?\d+(?:\.\d+)?)")
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")


def software_versions() -> dict[str, str]:
    versions = {"python": sys.version.split()[0]}
    for package in ("rdkit", "meeko", "dimorphite-dl", "numpy"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "unavailable"
    try:
        completed = subprocess.run([str(VINA), "--version"], text=True, capture_output=True, timeout=10)
        versions["vina"] = (completed.stdout or completed.stderr).strip().splitlines()[0]
    except (OSError, subprocess.SubprocessError, IndexError):
        versions["vina"] = "unavailable"
    return versions


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_seed(identifier: str) -> int:
    digest = hashlib.sha256(identifier.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


def first_mol(path: Path) -> Chem.Mol:
    for mol in Chem.SDMolSupplier(str(path), removeHs=False):
        if mol is not None:
            return mol
    raise ValueError(f"No readable molecule found in {path}")


def prepare_input(
    compound_id: str,
    output: Path,
    smiles: str | None,
    sdf: Path | None,
    conformers: int,
) -> tuple[Chem.Mol, dict[str, Any], list[str]]:
    warnings: list[str] = []
    if smiles is not None:
        base = Chem.MolFromSmiles(smiles)
        if base is None:
            raise ValueError("RDKit could not parse the supplied SMILES")
        source = "smiles"
    else:
        assert sdf is not None
        base = first_mol(sdf)
        source = str(sdf.resolve())

    fragments = len(Chem.GetMolFrags(base))
    if fragments > 1:
        warnings.append(f"Input contains {fragments} disconnected fragments; salts were not removed automatically.")
    undefined = [
        f"{symbol}{index}"
        for index, symbol in Chem.FindMolChiralCenters(base, includeUnassigned=True, useLegacyImplementation=False)
        if symbol == "?"
    ]
    if undefined:
        warnings.append("Undefined tetrahedral stereochemistry: " + ", ".join(undefined))
    charge = Chem.GetFormalCharge(base)
    if charge:
        warnings.append(f"Input has formal charge {charge:+d}; confirm that this is the intended protonation state.")
    warnings.append("Protonation and tautomer state are used as encoded; pH-based state enumeration is not performed.")

    needs_embedding = smiles is not None or base.GetNumConformers() == 0 or not base.GetConformer().Is3D()
    if needs_embedding:
        mol = Chem.AddHs(Chem.Mol(base))
        params = AllChem.ETKDGv3()
        params.randomSeed = stable_seed(compound_id)
        params.useSmallRingTorsions = True
        params.useMacrocycleTorsions = True
        conformer_ids = list(AllChem.EmbedMultipleConfs(mol, numConfs=conformers, params=params))
        if not conformer_ids:
            params.useRandomCoords = True
            conformer_ids = list(AllChem.EmbedMultipleConfs(mol, numConfs=max(1, conformers // 2), params=params))
        if not conformer_ids:
            raise ValueError("RDKit could not generate a three-dimensional conformer")
        if AllChem.MMFFHasAllMoleculeParams(mol):
            results = AllChem.MMFFOptimizeMoleculeConfs(mol, maxIters=500)
            method = "ETKDGv3+MMFF94"
        else:
            results = AllChem.UFFOptimizeMoleculeConfs(mol, maxIters=500)
            method = "ETKDGv3+UFF"
        best_id = min(zip(conformer_ids, results), key=lambda item: float(item[1][1]))[0]
        prepared = Chem.Mol(mol)
        prepared.RemoveAllConformers()
        prepared.AddConformer(Chem.Conformer(mol.GetConformer(int(best_id))), assignId=True)
    else:
        prepared = Chem.AddHs(Chem.Mol(base), addCoords=True)
        method = "input-3D"

    prepared.SetProp("_Name", compound_id)
    prepared.SetProp("compound_id", compound_id)
    prepared.SetProp("input_source", source)
    prepared.SetProp("preparation", method)
    writer = Chem.SDWriter(str(output))
    writer.write(prepared)
    writer.close()

    heavy = Chem.RemoveHs(prepared)
    canonical = Chem.MolToSmiles(Chem.RemoveHs(base), isomericSmiles=True)
    descriptors = {
        "canonical_smiles": canonical,
        "molecular_formula": rdMolDescriptors.CalcMolFormula(heavy),
        "molecular_weight": round(Descriptors.MolWt(heavy), 3),
        "clogp": round(Crippen.MolLogP(heavy), 3),
        "tpsa_A2": round(rdMolDescriptors.CalcTPSA(heavy), 3),
        "h_bond_donors": int(Lipinski.NumHDonors(heavy)),
        "h_bond_acceptors": int(Lipinski.NumHAcceptors(heavy)),
        "rotatable_bonds": int(Lipinski.NumRotatableBonds(heavy)),
        "formal_charge": int(Chem.GetFormalCharge(heavy)),
        "heavy_atoms": int(heavy.GetNumAtoms()),
        "fraction_csp3": round(rdMolDescriptors.CalcFractionCSP3(heavy), 4),
        "qed": round(QED.qed(heavy), 4),
        "preparation": method,
    }
    return prepared, descriptors, warnings


def run_logged(command: list[str], log_path: Path, section: str | None = None) -> None:
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    mode = "a" if section else "w"
    with log_path.open(mode) as handle:
        if section:
            handle.write(f"\n## {section}\n")
        handle.write(result.stdout)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}); see {log_path}")


def parse_score(path: Path) -> float:
    for line in path.read_text().splitlines():
        match = SCORE_PATTERN.match(line)
        if match:
            return float(match.group(1))
    raise ValueError(f"No Vina score found in {path}")


def receptor_atoms() -> tuple[np.ndarray, list[str]]:
    coordinates: list[list[float]] = []
    residues: list[str] = []
    for line in RECEPTOR_PDB.read_text().splitlines():
        if not line.startswith("ATOM") or line[16:17] not in {" ", "A"}:
            continue
        element = (line[76:78].strip() or line[12:16].strip()[0]).upper()
        if element == "H":
            continue
        coordinates.append([float(line[30:38]), float(line[38:46]), float(line[46:54])])
        residues.append(f"{line[21:22].strip()}:{line[17:20].strip()}{int(line[22:26])}")
    return np.asarray(coordinates), residues


def ligand_xyz(mol: Chem.Mol) -> np.ndarray:
    conformer = mol.GetConformer()
    return np.asarray([
        [
            conformer.GetAtomPosition(atom.GetIdx()).x,
            conformer.GetAtomPosition(atom.GetIdx()).y,
            conformer.GetAtomPosition(atom.GetIdx()).z,
        ]
        for atom in mol.GetAtoms()
        if atom.GetAtomicNum() > 1
    ])


def contact_set(mol: Chem.Mol, protein_xyz: np.ndarray, residues: list[str], cutoff: float = 4.0) -> set[str]:
    distances = np.linalg.norm(ligand_xyz(mol)[:, None, :] - protein_xyz[None, :, :], axis=2)
    return {residues[int(index)] for index in np.where(distances <= cutoff)[1]}


def dock_seed(
    seed: int,
    ligand_pdbqt: Path,
    docking_dir: Path,
    logs_dir: Path,
    exhaustiveness: int,
    cpu: int,
) -> tuple[int, Path, Path]:
    seed_dir = docking_dir / f"seed_{seed}"
    seed_dir.mkdir(parents=True, exist_ok=True)
    output_pdbqt = seed_dir / "poses.pdbqt"
    output_sdf = seed_dir / "poses.sdf"
    log = logs_dir / f"vina_seed_{seed}.log"
    command = [
        str(VINA), "--receptor", str(RECEPTOR_PDBQT), "--ligand", str(ligand_pdbqt),
        "--config", str(BOX), "--exhaustiveness", str(exhaustiveness), "--num_modes", "10",
        "--energy_range", "4", "--seed", str(seed), "--cpu", str(cpu), "--out", str(output_pdbqt),
    ]
    run_logged(command, log)
    if not output_pdbqt.exists() or not output_pdbqt.stat().st_size:
        raise RuntimeError(f"Vina did not create {output_pdbqt}")
    run_logged([str(MEEKO_EXPORT), str(output_pdbqt), "-s", str(output_sdf)], log, "mk_export.py")
    if not output_sdf.exists() or not output_sdf.stat().st_size:
        raise RuntimeError(f"Meeko did not create {output_sdf}")
    return seed, output_pdbqt, output_sdf


def analyze(
    compound_id: str,
    heavy_atoms: int,
    docked: list[tuple[int, Path, Path]],
    analysis_dir: Path,
    result_root: Path | None = None,
    state: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    protein_xyz, residues = receptor_atoms()
    native_contacts = contact_set(first_mol(NATIVE), protein_xyz, residues)
    rows: list[dict[str, Any]] = []
    poses: list[tuple[int, Chem.Mol]] = []
    for seed, pdbqt, sdf in sorted(docked):
        pose = first_mol(sdf)
        poses.append((seed, pose))
        distances = np.linalg.norm(ligand_xyz(pose)[:, None, :] - protein_xyz[None, :, :], axis=2)
        contacts = {residues[int(index)] for index in np.where(distances <= 4.0)[1]}
        recovery = len(contacts & native_contacts) / len(native_contacts)
        anchor_contacts = sorted(contacts & ANCHORS)
        clashes = int(np.sum(distances < 1.2))
        vina_score = parse_score(pdbqt)
        row = {
            "compound_id": compound_id,
            "seed": seed,
            "vina_score_kcal_mol": vina_score,
            "ligand_efficiency_kcal_mol_per_heavy_atom": vina_score / heavy_atoms,
            "native_contact_recovery": recovery,
            "anchor_contact_count": len(anchor_contacts),
            "anchor_residues": ";".join(anchor_contacts),
            "severe_clashes_below_1.2A": clashes,
            "site_valid": recovery >= 0.40 and len(anchor_contacts) >= 1 and clashes == 0,
            "pose_sdf": str(sdf.relative_to(result_root or analysis_dir.parent)),
        }
        if state:
            row.update({
                "microspecies_id": state["state_id"],
                "microspecies_smiles": state["smiles"],
                "microspecies_formal_charge": state["formal_charge"],
            })
        rows.append(row)

    pairwise_rmsd: list[float] = []
    for (_, pose_a), (_, pose_b) in itertools.combinations(poses, 2):
        try:
            pairwise_rmsd.append(float(rdMolAlign.GetBestRMS(Chem.RemoveHs(pose_a), Chem.RemoveHs(pose_b))))
        except RuntimeError:
            pass
    valid = [row for row in rows if row["site_valid"]]
    ranked = valid if valid else rows
    median = lambda values: float(np.median(np.asarray(values, dtype=float)))
    summary = {
        "seed_count": len(rows),
        "valid_site_count": len(valid),
        "valid_site_fraction": len(valid) / len(rows),
        "best_vina_score_kcal_mol": min(float(row["vina_score_kcal_mol"]) for row in ranked),
        "median_vina_score_kcal_mol": median([row["vina_score_kcal_mol"] for row in ranked]),
        "median_ligand_efficiency": median([
            row["ligand_efficiency_kcal_mol_per_heavy_atom"] for row in ranked
        ]),
        "median_native_contact_recovery": median([row["native_contact_recovery"] for row in rows]),
        "median_anchor_contacts": median([row["anchor_contact_count"] for row in rows]),
        "median_pairwise_pose_rmsd_A": median(pairwise_rmsd) if pairwise_rmsd else None,
    }
    summary["confirmation_criteria_pass"] = bool(
        len(rows) == 5
        and summary["valid_site_fraction"] >= 0.8
        and summary["median_vina_score_kcal_mol"] <= -7.5
        and summary["median_ligand_efficiency"] <= -0.34
        and summary["median_native_contact_recovery"] >= 0.70
        and summary["median_pairwise_pose_rmsd_A"] is not None
        and summary["median_pairwise_pose_rmsd_A"] <= 2.5
    )

    per_seed = analysis_dir / "per_seed.csv"
    with per_seed.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return rows, summary


def microspecies_consensus(state_results: list[dict[str, Any]], mode: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Summarize all states and apply the control-calibrated priority-state rule."""
    def favorable(item: dict[str, Any]) -> bool:
        summary = item["summary"]
        if mode == "confirmation":
            return bool(summary["confirmation_criteria_pass"])
        row = item["per_seed"][0]
        return bool(
            row["site_valid"]
            and row["vina_score_kcal_mol"] <= -7.5
            and row["native_contact_recovery"] >= 0.40
            and row["severe_clashes_below_1.2A"] == 0
        )

    ranked = sorted(
        state_results,
        key=lambda item: (
            -item["summary"]["valid_site_fraction"],
            item["summary"]["median_vina_score_kcal_mol"],
            item["state"]["state_id"],
        ),
    )
    representative = ranked[0]
    scores = [float(item["summary"]["median_vina_score_kcal_mol"]) for item in state_results]
    site_valid = [item for item in state_results if item["summary"]["valid_site_count"] > 0]
    favorable_states = [item for item in state_results if favorable(item)]
    protomer_best: dict[int, int] = {}
    for item in state_results:
        rank = int(item["state"].get("protomer_rank", 0))
        score = int(item["state"].get("tautomer_score", 0))
        protomer_best[rank] = max(protomer_best.get(rank, score), score)
    priority_states = [
        item for item in state_results
        if int(item["state"].get("tautomer_score", 0)) == protomer_best[int(item["state"].get("protomer_rank", 0))]
    ]
    robust_priority = [item for item in priority_states if item["summary"]["valid_site_fraction"] >= 0.8]
    priority_fraction = len(robust_priority) / len(priority_states)
    max_priority_recovery = max(item["summary"]["median_native_contact_recovery"] for item in priority_states)
    priority_scores = [item["summary"]["median_vina_score_kcal_mol"] for item in priority_states]
    rule = json.loads(MICROSPECIES_RULE.read_text()) if MICROSPECIES_RULE.is_file() else None
    calibrated_pass = None
    if rule:
        calibrated_pass = bool(
            priority_fraction >= rule["minimum_priority_robust_state_fraction"]
            and max_priority_recovery >= rule["minimum_max_priority_contact_recovery"]
        )
    consensus = {
        "basis": "Highest-scoring tautomer(s) within each pH-plausible protomer define priority states; populations are not pKa-weighted.",
        "state_count": len(state_results),
        "site_valid_state_count": len(site_valid),
        "site_valid_state_fraction": len(site_valid) / len(state_results),
        "favorable_state_count": len(favorable_states),
        "favorable_state_fraction": len(favorable_states) / len(state_results),
        "median_of_state_median_vina_kcal_mol": float(np.median(np.asarray(scores))),
        "best_state_vina_kcal_mol": min(scores),
        "worst_state_vina_kcal_mol": max(scores),
        "representative_state_id": representative["state"]["state_id"],
        "priority_state_ids": [item["state"]["state_id"] for item in priority_states],
        "priority_state_count": len(priority_states),
        "priority_robust_state_count": len(robust_priority),
        "priority_robust_state_fraction": priority_fraction,
        "max_priority_native_contact_recovery": max_priority_recovery,
        "median_priority_vina_kcal_mol": float(np.median(np.asarray(priority_scores))),
        "control_calibrated_criteria_pass": calibrated_pass,
        "consensus_criteria_pass": calibrated_pass if calibrated_pass is not None else False,
        "consensus_threshold": (
            f"Priority robust-state fraction >= {rule['minimum_priority_robust_state_fraction']:.3f} and "
            f"maximum priority-state contact recovery >= {rule['minimum_max_priority_contact_recovery']:.3f}."
            if rule else "No control-calibrated microspecies rule is installed."
        ),
        "rule_status": rule["status"] if rule else "unavailable",
    }
    return representative, consensus


def report_markdown(result: dict[str, Any]) -> str:
    descriptors = result["descriptors"]
    summary = result["summary"]
    warnings = result["warnings"]
    rmsd = summary["median_pairwise_pose_rmsd_A"]
    lines = [
        f"# P2X4 single-compound report: {result['compound_id']}",
        "",
        f"- Status: **{result['status']}**",
        f"- Mode: {result['mode']}",
        f"- Canonical SMILES: `{descriptors['canonical_smiles']}`",
        f"- Preparation: {descriptors['preparation']}",
        f"- Heavy atoms: {descriptors['heavy_atoms']}",
        f"- Molecular weight: {descriptors['molecular_weight']:.2f} g/mol",
        f"- cLogP: {descriptors['clogp']:.3f}",
        f"- TPSA: {descriptors['tpsa_A2']:.3f} A^2",
        "",
        "## Docking summary",
        "",
        f"- Site-valid seeds: {summary['valid_site_count']}/{summary['seed_count']}",
        f"- Best Vina score: {summary['best_vina_score_kcal_mol']:.3f} kcal/mol",
        f"- Median Vina score: {summary['median_vina_score_kcal_mol']:.3f} kcal/mol",
        f"- Median ligand efficiency: {summary['median_ligand_efficiency']:.4f} kcal/mol/heavy atom",
        f"- Median native-contact recovery: {summary['median_native_contact_recovery']:.1%}",
        f"- Median anchor contacts: {summary['median_anchor_contacts']:.1f}",
        f"- Inter-seed top-pose spread: {rmsd:.3f} A" if rmsd is not None else "- Inter-seed pose spread: not applicable in one-seed mode",
        f"- Frozen v1 descriptor: {'RULE MET' if summary['confirmation_criteria_pass'] else 'RULE NOT MET'}",
        "",
        "## Interpretation",
        "",
        "The calculation completed its procedural checks. Vina scores and the frozen v1 descriptor are not measured binding affinities or proof of P2X4 inhibition; the retrospective ROC-AUC is 0.440.",
    ]
    if warnings:
        lines.extend(["", "## Preparation warnings", ""] + [f"- {warning}" for warning in warnings])
    consensus = result.get("microspecies_consensus")
    if consensus:
        lines.extend([
            "",
            "## Microspecies consensus",
            "",
            f"- Enumerated states docked: {consensus['state_count']}",
            f"- States with a site-valid pose: {consensus['site_valid_state_count']}/{consensus['state_count']}",
            f"- Priority tautomer states: {consensus.get('priority_state_count', 0)}",
            f"- Robust priority states: {consensus.get('priority_robust_state_count', 0)}/{consensus.get('priority_state_count', 0)}",
            f"- Maximum priority-state contact recovery: {consensus.get('max_priority_native_contact_recovery', 0):.1%}",
            f"- Median of state-level median Vina scores: {consensus['median_of_state_median_vina_kcal_mol']:.3f} kcal/mol",
            f"- Score range: {consensus['best_state_vina_kcal_mol']:.3f} to {consensus['worst_state_vina_kcal_mol']:.3f} kcal/mol",
            f"- Representative state: {consensus['representative_state_id']}",
            f"- Frozen v1 consensus descriptor: {'RULE MET' if consensus['consensus_criteria_pass'] else 'RULE NOT MET'}",
            f"- Basis: {consensus['basis']}",
            "",
            "This rule separates BAY-1797 from the two inactive controls in the calibration panel but is not a statistically validated predictive model.",
        ])
    if result.get("methods_text"):
        lines.extend(["", "## Reproducible methods", "", str(result["methods_text"])])
    return "\n".join(lines) + "\n"


def validate_runtime() -> None:
    required = [RECEPTOR_PDBQT, RECEPTOR_PDB, BOX, NATIVE, MEEKO_PREPARE, MEEKO_EXPORT, VINA]
    missing = [str(path) for path in required if not path.exists() or not path.stat().st_size]
    if missing:
        raise FileNotFoundError("Missing required workflow files:\n" + "\n".join(missing))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--smiles", help="Isomeric SMILES for one compound")
    inputs.add_argument("--sdf", type=Path, help="Single-molecule SDF with a 3D conformer")
    parser.add_argument("--compound-id", required=True, help="Safe identifier used in reports")
    parser.add_argument("--job-id", help="Job directory name; defaults to the compound identifier")
    parser.add_argument("--mode", choices=("quick", "confirmation"), default="quick")
    parser.add_argument("--microspecies", action="store_true", help="Enumerate and dock pH-plausible protomers and tautomers")
    parser.add_argument("--ph-min", type=float, default=6.8)
    parser.add_argument("--ph-max", type=float, default=8.0)
    parser.add_argument("--max-microspecies", type=int, default=8)
    parser.add_argument("--output-root", type=Path, default=ROOT / "jobs")
    parser.add_argument("--conformers", type=int, default=20)
    parser.add_argument("--exhaustiveness", type=int, default=16)
    parser.add_argument("--cpu-per-job", type=int, default=2)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--force", action="store_true", help="Permit overwriting files in an existing job directory")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    validate_runtime()
    job_id = args.job_id or args.compound_id
    if not args.compound_id.strip() or len(args.compound_id) > 200 or any(ord(char) < 32 for char in args.compound_id):
        raise SystemExit("compound-id must be non-empty, contain no control characters, and be at most 200 characters")
    if not SAFE_ID.fullmatch(job_id):
        raise SystemExit("job-id must contain only letters, digits, dot, underscore or hyphen (max 80 characters)")
    if args.conformers < 1 or args.exhaustiveness < 1 or args.cpu_per_job < 1 or args.workers < 1:
        raise SystemExit("conformers, exhaustiveness, cpu-per-job and workers must be positive")
    if args.sdf is not None and not args.sdf.is_file():
        raise SystemExit(f"SDF does not exist: {args.sdf}")
    if args.microspecies and args.smiles is None:
        raise SystemExit("--microspecies currently requires a SMILES input")
    if not 0.0 <= args.ph_min <= args.ph_max <= 14.0:
        raise SystemExit("pH range must satisfy 0 <= ph-min <= ph-max <= 14")
    if not 1 <= args.max_microspecies <= 32:
        raise SystemExit("max-microspecies must be between 1 and 32")

    job_dir = args.output_root.resolve() / job_id
    if job_dir.exists() and any(job_dir.iterdir()) and not args.force:
        raise SystemExit(f"Job directory is not empty: {job_dir}; choose another --job-id or pass --force")
    analysis_dir = job_dir / "analysis"
    logs_dir = job_dir / "logs"
    for directory in (analysis_dir, logs_dir):
        directory.mkdir(parents=True, exist_ok=True)

    status_path = job_dir / "status.json"

    last_progress = 4

    def set_status(
        status: str,
        step: str,
        error: str | None = None,
        detail: str | None = None,
        progress_percent: int | None = None,
        completed_units: int | None = None,
        total_units: int | None = None,
        completed_docking_runs: int | None = None,
        total_docking_runs: int | None = None,
    ) -> None:
        nonlocal last_progress
        if progress_percent is not None:
            last_progress = max(0, min(100, int(progress_percent)))
        payload = {
            "job_id": job_id,
            "compound_id": args.compound_id,
            "mode": args.mode,
            "microspecies_enabled": args.microspecies,
            "status": status,
            "step": step,
            "progress_percent": last_progress,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if error:
            payload["error"] = error
        if detail:
            payload["detail"] = detail
        if completed_units is not None and total_units is not None:
            payload["completed_work_units"] = completed_units
            payload["total_work_units"] = total_units
        if completed_docking_runs is not None and total_docking_runs is not None:
            payload["completed_docking_runs"] = completed_docking_runs
            payload["total_docking_runs"] = total_docking_runs
        status_path.write_text(json.dumps(payload, indent=2) + "\n")

    try:
        seeds = DEFAULT_SEEDS if args.mode == "confirmation" else DEFAULT_SEEDS[:1]
        enumeration: dict[str, Any] | None = None
        if args.microspecies:
            set_status("running", "enumerating_microspecies", progress_percent=8)
            enumeration = enumerate_microspecies(
                args.smiles or "", args.ph_min, args.ph_max, args.max_microspecies
            )
            state_specs: list[dict[str, Any] | None] = enumeration["states"]
            if not state_specs:
                raise RuntimeError("No microspecies could be generated")
        else:
            state_specs = [None]

        total_docking_runs = len(state_specs) * len(seeds)
        total_units = len(state_specs) * (len(seeds) + 3) + 1
        completed_docking_runs = 0
        completed_units = 0

        def unit_progress() -> int:
            return min(96, 10 + round(86 * completed_units / total_units))

        state_results: list[dict[str, Any]] = []
        all_rows: list[dict[str, Any]] = []
        all_warnings: list[str] = list(enumeration["warnings"] if enumeration else [])
        for state_index, state in enumerate(state_specs, start=1):
            state_id = state["state_id"] if state else None
            state_root = job_dir / "states" / state_id if state_id else job_dir
            input_dir = state_root / "input"
            prepared_dir = state_root / "prepared"
            docking_dir = state_root / "docking"
            state_analysis_dir = state_root / "analysis"
            state_logs_dir = state_root / "logs"
            for directory in (input_dir, prepared_dir, docking_dir, state_analysis_dir, state_logs_dir):
                directory.mkdir(parents=True, exist_ok=True)
            state_label = f"microspecies {state_index}/{len(state_specs)}" if state else "submitted state"
            set_status("running", "preparing_structure", detail=state_label, progress_percent=unit_progress(), completed_units=completed_units, total_units=total_units, completed_docking_runs=completed_docking_runs, total_docking_runs=total_docking_runs)
            input_sdf = input_dir / "structure.sdf"
            state_smiles = state["smiles"] if state else args.smiles
            _, descriptors, state_warnings = prepare_input(
                f"{args.compound_id}-{state_id}" if state_id else args.compound_id,
                input_sdf,
                state_smiles,
                None if state else (args.sdf.resolve() if args.sdf else None),
                args.conformers,
            )
            completed_units += 1
            if not args.microspecies:
                all_warnings.extend(state_warnings)

            set_status("running", "preparing_pdbqt", detail=state_label, progress_percent=unit_progress(), completed_units=completed_units, total_units=total_units, completed_docking_runs=completed_docking_runs, total_docking_runs=total_docking_runs)
            ligand_pdbqt = prepared_dir / "ligand.pdbqt"
            prep_log = state_logs_dir / "meeko_prepare.log"
            run_logged([str(MEEKO_PREPARE), "-i", str(input_sdf), "-o", str(ligand_pdbqt)], prep_log)
            if not ligand_pdbqt.exists() or not ligand_pdbqt.stat().st_size:
                raise RuntimeError(f"Meeko did not create the ligand PDBQT for {state_label}")
            completed_units += 1

            set_status("running", "docking", detail=state_label, progress_percent=unit_progress(), completed_units=completed_units, total_units=total_units, completed_docking_runs=completed_docking_runs, total_docking_runs=total_docking_runs)
            docked: list[tuple[int, Path, Path]] = []
            with ThreadPoolExecutor(max_workers=min(args.workers, len(seeds))) as pool:
                futures = {
                    pool.submit(
                        dock_seed, seed, ligand_pdbqt, docking_dir, state_logs_dir,
                        args.exhaustiveness, args.cpu_per_job
                    ): seed
                    for seed in seeds
                }
                for future in as_completed(futures):
                    docked.append(future.result())
                    completed_units += 1
                    completed_docking_runs += 1
                    set_status(
                        "running", "docking",
                        detail=f"{state_label} · seed {futures[future]} complete ({completed_docking_runs}/{total_docking_runs} docking runs)",
                        progress_percent=unit_progress(), completed_units=completed_units, total_units=total_units,
                        completed_docking_runs=completed_docking_runs, total_docking_runs=total_docking_runs,
                    )
                    print(f"Completed {state_label}, seed {futures[future]}", flush=True)

            set_status("running", "analyzing", detail=state_label, progress_percent=unit_progress(), completed_units=completed_units, total_units=total_units, completed_docking_runs=completed_docking_runs, total_docking_runs=total_docking_runs)
            per_seed, state_summary = analyze(
                args.compound_id,
                descriptors["heavy_atoms"],
                docked,
                state_analysis_dir,
                result_root=job_dir,
                state=state,
            )
            state_entry = {
                "state": state or {
                    "state_id": "submitted",
                    "smiles": descriptors["canonical_smiles"],
                    "formal_charge": descriptors["formal_charge"],
                    "matches_submitted_state": True,
                },
                "descriptors": descriptors,
                "summary": state_summary,
                "per_seed": per_seed,
                "files": {
                    "input_sdf": str(input_sdf.relative_to(job_dir)),
                    "ligand_pdbqt": str(ligand_pdbqt.relative_to(job_dir)),
                    "per_seed_csv": str((state_analysis_dir / "per_seed.csv").relative_to(job_dir)),
                },
            }
            state_results.append(state_entry)
            all_rows.extend(per_seed)
            completed_units += 1
            set_status("running", "analyzing", detail=f"{state_label} analyzed", progress_percent=unit_progress(), completed_units=completed_units, total_units=total_units, completed_docking_runs=completed_docking_runs, total_docking_runs=total_docking_runs)

        if args.microspecies:
            representative, consensus = microspecies_consensus(state_results, args.mode)
            all_warnings.extend([
                f"Automatically enumerated and docked {len(state_results)} unique microspecies between pH {args.ph_min:g} and {args.ph_max:g}.",
                "Highest-scoring tautomer(s) within each protomer define priority states; solution-state population fractions are not estimated.",
                "The consensus rule separates BAY-1797 from two inactive controls but is not a statistically validated predictive model.",
            ])
        else:
            representative = state_results[0]
            consensus = None
        descriptors = representative["descriptors"]
        summary = representative["summary"]
        per_seed = all_rows

        combined_csv = analysis_dir / "per_seed.csv"
        with combined_csv.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(per_seed[0]))
            writer.writeheader()
            writer.writerows(per_seed)

        representative_files = representative["files"]
        result = {
            "schema_version": "2.0" if args.microspecies else "1.0",
            "job_id": job_id,
            "compound_id": args.compound_id,
            "status": "complete",
            "mode": args.mode,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "input": {"type": "smiles" if args.smiles is not None else "sdf", "source": args.smiles or str(args.sdf.resolve())},
            "descriptors": descriptors,
            "warnings": all_warnings,
            "settings": {
                "target": "human P2X4",
                "structure": "9BQI trimer",
                "site": "BAY-1797-centered inter-subunit pocket; full A/B/C trimer retained",
                "receptor_chains": ["A", "B", "C"],
                "seeds": list(seeds),
                "exhaustiveness": args.exhaustiveness,
                "num_modes": 10,
                "energy_range_kcal_mol": 4,
                "receptor_sha256": sha256(RECEPTOR_PDBQT),
                "box_sha256": sha256(BOX),
                "microspecies_enabled": args.microspecies,
                "ph_min": args.ph_min if args.microspecies else None,
                "ph_max": args.ph_max if args.microspecies else None,
                "max_microspecies": args.max_microspecies if args.microspecies else None,
                "software_versions": software_versions(),
            },
            "summary": summary,
            "per_seed": per_seed,
            "files": {
                "input_sdf": representative_files["input_sdf"],
                "ligand_pdbqt": representative_files["ligand_pdbqt"],
                "per_seed_csv": str(combined_csv.relative_to(job_dir)),
                "report": "report.md",
            },
        }
        if enumeration:
            result["microspecies_enumeration"] = {key: value for key, value in enumeration.items() if key != "states"}
            result["microspecies"] = state_results
            result["microspecies_consensus"] = consensus
        result["methods_text"] = (
            f"The submitted structure was prepared with {descriptors['preparation']} and docked with "
            f"AutoDock Vina ({result['settings']['software_versions']['vina']}) into the rigid full A/B/C human "
            f"P2X4 trimer from PDB 9BQI (receptor SHA-256 {result['settings']['receptor_sha256']}). The BAY-1797-centered "
            f"grid used configuration SHA-256 {result['settings']['box_sha256']}, exhaustiveness {args.exhaustiveness}, "
            f"10 modes, a 4 kcal/mol energy range, and seeds {', '.join(map(str, seeds))}. "
            "Scores were treated as prioritization values rather than binding affinities."
        )
        set_status("running", "analyzing", detail="Finalizing auditable result files", progress_percent=96, completed_units=completed_units, total_units=total_units, completed_docking_runs=completed_docking_runs, total_docking_runs=total_docking_runs)
        (job_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        (job_dir / "report.md").write_text(report_markdown(result))
        completed_units += 1
        set_status("complete", "complete", progress_percent=100, completed_units=completed_units, total_units=total_units, completed_docking_runs=completed_docking_runs, total_docking_runs=total_docking_runs)
        print(f"Result: {job_dir / 'result.json'}")
        print(f"Report: {job_dir / 'report.md'}")
    except Exception as exc:
        set_status("failed", "failed", str(exc))
        print(f"ERROR: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
