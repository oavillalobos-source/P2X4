#!/usr/bin/env python3
"""Deterministic protonation/tautomer enumeration for the P2X4 workflow."""

from __future__ import annotations

from typing import Any

from dimorphite_dl import protonate_smiles
from rdkit import Chem
from rdkit.Chem.MolStandardize import rdMolStandardize


def enumerate_microspecies(
    smiles: str,
    ph_min: float = 6.8,
    ph_max: float = 8.0,
    max_states: int = 8,
) -> dict[str, Any]:
    """Return unique pH-plausible protomers and tautomers in stable order.

    Dimorphite-DL supplies the pH-dependent protonation variants. RDKit then
    enumerates tautomers for each variant. Canonical isomeric SMILES are used
    as the deduplication key so the same state is never counted twice.
    """
    if not 0.0 <= ph_min <= ph_max <= 14.0:
        raise ValueError("pH range must satisfy 0 ≤ minimum ≤ maximum ≤ 14")
    if not 1 <= max_states <= 32:
        raise ValueError("max_states must be between 1 and 32")
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError("RDKit could not parse the supplied SMILES")

    cleaned = rdMolStandardize.Cleanup(Chem.Mol(mol))
    parent = rdMolStandardize.FragmentParent(cleaned)
    parent_smiles = Chem.MolToSmiles(parent, isomericSmiles=True)
    submitted_smiles = Chem.MolToSmiles(mol, isomericSmiles=True)
    protomers = protonate_smiles(
        parent_smiles,
        ph_min=ph_min,
        ph_max=ph_max,
        max_variants=max(32, max_states * 4),
        validate_output=True,
    )
    if not protomers:
        protomers = [parent_smiles]

    enumerator = rdMolStandardize.TautomerEnumerator()
    enumerator.SetMaxTautomers(max(64, max_states * 8))
    candidates: dict[str, dict[str, Any]] = {}
    for protomer_rank, protomer_smiles in enumerate(dict.fromkeys(protomers)):
        protomer = Chem.MolFromSmiles(protomer_smiles)
        if protomer is None:
            continue
        for tautomer in enumerator.Enumerate(protomer):
            canonical = Chem.MolToSmiles(tautomer, isomericSmiles=True)
            if canonical in candidates:
                continue
            candidates[canonical] = {
                "smiles": canonical,
                "formal_charge": int(Chem.GetFormalCharge(tautomer)),
                "protomer_rank": protomer_rank,
                "tautomer_score": int(enumerator.ScoreTautomer(tautomer)),
                "matches_submitted_state": canonical == submitted_smiles,
                "population_fraction": None,
                "ranking_basis": "Dimorphite-DL protomer order then RDKit tautomer score; not an abundance estimate",
            }

    by_protomer: dict[int, list[dict[str, Any]]] = {}
    for item in candidates.values():
        by_protomer.setdefault(int(item["protomer_rank"]), []).append(item)
    for family in by_protomer.values():
        family.sort(key=lambda item: (-item["tautomer_score"], item["smiles"]))

    # Preserve at least one representative from each protonation family before
    # filling the remaining state budget with lower-ranked tautomers.  This is
    # deterministic and chemically more defensible than allowing one protomer
    # family to consume the cap.  It is still not a population estimate.
    ordered: list[dict[str, Any]] = []
    depth = 0
    while any(depth < len(family) for family in by_protomer.values()):
        for protomer_rank in sorted(by_protomer):
            family = by_protomer[protomer_rank]
            if depth < len(family):
                ordered.append(family[depth])
        depth += 1
    total = len(ordered)
    states = []
    selected = ordered[:max_states]
    dropped = ordered[max_states:]
    for index, item in enumerate(selected, start=1):
        states.append({"state_id": f"ms{index:03d}", **item})
    warnings: list[str] = []
    original_fragments = len(Chem.GetMolFrags(mol))
    if original_fragments > 1:
        warnings.append(
            f"Selected the RDKit parent fragment from {original_fragments} input fragments before enumeration."
        )
    if total > max_states:
        warnings.append(
            f"Enumeration produced {total} unique states; docking retained {max_states} states using protomer-family round-robin selection with RDKit tautomer-score ordering. {len(dropped)} states were logged but not docked. No solution-state population model is available."
        )
    return {
        "method": "Dimorphite-DL 2.1.0 protonation + RDKit tautomer enumeration",
        "ph_min": ph_min,
        "ph_max": ph_max,
        "max_states": max_states,
        "parent_smiles": parent_smiles,
        "candidate_count": total,
        "truncated": total > max_states,
        "states": states,
        "selection_policy": "protomer-family representatives first, then lower-ranked tautomers within each family",
        "selection_policy_version": "protomer_family_round_robin_v2",
        "dropped_state_count": len(dropped),
        "dropped_states": [
            {
                "smiles": item["smiles"],
                "formal_charge": item["formal_charge"],
                "protomer_rank": item["protomer_rank"],
                "tautomer_score": item["tautomer_score"],
                "reason": "state cap reached after protomer-family representative selection",
            }
            for item in dropped
        ],
        "population_model": "not_available",
        "population_interpretation": "States are pH-plausible rule-generated candidates, not population-ranked microspecies.",
        "warnings": warnings,
    }
