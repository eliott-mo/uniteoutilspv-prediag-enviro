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

from . import bdc, classeurs, referentiels, taxref, veille, zonages
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
    refs = referentiels.assurer(cfg, dossier, forcer=forcer,
                                cles=("taxref", "bdc_statuts"))
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


def territoires_disponibles(cs: dict[str, classeurs.Classeur],
                            statuts: bdc.Statuts) -> list[str]:
    """Territoires réellement confrontables, **tels que les classeurs les écrivent**.

    Proposer cette liste plutôt qu'une saisie libre évite deux pièges mesurés :
    taper « Centre-Val de Loire », le nom que porte le classeur, ne ramenait
    rien puisque BDC écrit « Centre » ; et un territoire inexistant renvoyait
    les statuts nationaux et européens, ce qui ressemblait à un résultat.

    Les libellés rendus sont ceux des colonnes, pas ceux de BDC : c'est le
    vocabulaire de celle qui choisit. La traduction se fait au filtrage.
    """
    trouves: set[str] = set()
    for cl in cs.values():
        for colonne in cl.colonnes:
            if not colonne.comparable or colonne.territoire_bdc in veille.TERRITOIRES_SUPRA:
                continue
            if statuts.couvre(colonne.type_bdc, colonne.territoire_bdc):
                trouves.add(colonne.territoire or colonne.territoire_bdc)
    # Tri sur la forme sans accents, sinon « Île-de-France » tombe après
    # « Rhône-Alpes » et on la cherche.
    return sorted(trouves, key=classeurs._cle_territoire)


#: Référentiels nécessaires aux seuls zonages — 460 Mo, téléchargés à la
#: première utilisation de la section et pas avant.
CLES_ZONAGES = ("znieff", "natura2000", "espaces_proteges", "patrimoine_geologique")


def preparer_zonages(racine: Path, progression=None) -> tuple[dict[str, str], list[str]]:
    """Garantit les archives de zonages. Renvoie (fichiers, citations)."""
    cfg = lire_config(racine)
    if progression is not None:
        progression("Récupération des référentiels de zonages (460 Mo la première "
                    "fois)…")
    refs = referentiels.assurer(cfg, racine / "referentiels", cles=CLES_ZONAGES)
    fichiers = {c: spec["fichier"] for c, spec in cfg["referentiels"].items()}
    citations = [refs[c].citation(cfg["attribution"]) for c in CLES_ZONAGES if c in refs]
    return fichiers, citations


def croiser_zonages(racine: Path, emprise_union, aires=None,
                    progression=None) -> zonages.Resultat:
    """Croise l'emprise avec les zonages du patrimoine naturel."""
    fichiers, _ = preparer_zonages(racine, progression)
    if progression is not None:
        progression("Croisement avec les zonages…")
    return zonages.croiser(
        emprise_union, zonages.registre(), racine / "referentiels",
        racine / "referentiels" / "_cache_sig", fichiers, aires=aires,
    )
