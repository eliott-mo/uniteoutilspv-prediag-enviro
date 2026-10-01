"""Orchestration partagée entre la ligne de commande et l'interface.

Les deux entrées — `run_veille.py` et `app.py` — enchaînent les mêmes étapes.
Les factoriser ici évite qu'elles divergent : une correction de la veille ne
doit pas n'arriver que d'un côté.

Les chargements lourds (TaxRef : 708 685 taxons ; BDC : 294 730 statuts) sont
construits une fois puis relus depuis un cache sur disque. L'interface les
garde en plus en mémoire entre deux interactions, Streamlit relançant le script
entier à chaque clic.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from . import bdc, classeurs, referentiels, taxref, veille
from .memoire import Memoire

#: Motifs de reconnaissance des classeurs déposés, par groupe.
MOTIFS = {
    "oiseaux": "*oiseaux*.xlsx",
    "mammiferes": "*mammif*.xlsx",
    "amphib-reptiles": "*amphib*.xlsx",
    "insectes": "*insectes*.xlsx",
    "macroheteroceres": "*macroh*.xlsx",
    "araignees": "*araign*.xlsx",
}


@dataclass
class Contexte:
    """Tout ce qu'il faut pour travailler : référentiels chargés et cités."""
    index: taxref.Index
    statuts: bdc.Statuts
    citations: list[str]
    versions: dict[str, referentiels.Referentiel]
    racine: Path

    @property
    def resume_versions(self) -> str:
        return " · ".join(f"{c}" for c in (
            f"TaxRef v{self.index.version}", f"BDC-Statuts v{self.statuts.version}"
        ))


def lire_config(racine: Path) -> dict:
    return yaml.safe_load((racine / "config" / "sources.yml").read_text(encoding="utf-8"))


def charger_contexte(racine: Path, forcer: bool = False,
                     progression=None) -> Contexte:
    """Garantit les référentiels puis construit les index.

    `progression` : fonction optionnelle appelée avec un message d'étape, pour
    que l'interface dise ce qui se passe pendant les premières minutes.
    """
    def dire(message: str) -> None:
        if progression is not None:
            progression(message)

    cfg = lire_config(racine)
    dossier = racine / "referentiels"

    dire("Récupération des référentiels INPN…")
    refs = referentiels.assurer(cfg, dossier, forcer=forcer)
    citations = referentiels.bandeau_versions(refs, cfg["attribution"])

    spec_tax = cfg["referentiels"]["taxref"]
    dire(f"Index TaxRef v{spec_tax['version']}…")
    index = taxref.Index.charger(refs["taxref"].chemin, spec_tax["membres"],
                                 spec_tax["version"], dossier / "taxref_index.pkl")

    spec_bdc = cfg["referentiels"]["bdc_statuts"]
    dire(f"Index BDC-Statuts v{spec_bdc['version']}…")
    statuts = bdc.Statuts.charger(refs["bdc_statuts"].chemin,
                                  spec_bdc["membres"]["principal"],
                                  spec_bdc["version"], dossier / "bdc_index.pkl")

    return Contexte(index=index, statuts=statuts, citations=citations,
                    versions=refs, racine=racine)


def charger_classeurs(racine: Path) -> dict[str, classeurs.Classeur]:
    return classeurs.lire_tous(racine / "classeurs", MOTIFS)


def lancer_veille(contexte: Contexte, cs: dict[str, classeurs.Classeur],
                  memoire: Memoire, groupes: list[str] | None = None,
                  territoires: list[str] | None = None) -> tuple[veille.Resultat, int]:
    """Analyse, puis masque ce qui a déjà été arbitré sans changement.

    Renvoie (résultat, nombre masqué) — afficher le second compte autant que le
    premier : il dit que la mémoire travaille.
    """
    res = veille.analyser(cs, contexte.index, contexte.statuts,
                          groupes=groupes, territoires=territoires)
    avant = len(res.constats)
    res.constats = [c for c in res.constats if not memoire.deja_tranche(c.cle, c.propose)]
    return res, avant - len(res.constats)


def memoire_projet(racine: Path) -> Memoire:
    return Memoire(racine / "memoire" / "arbitrages.json")
