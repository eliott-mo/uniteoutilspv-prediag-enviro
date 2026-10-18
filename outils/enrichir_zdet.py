#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Propose les colonnes « espèce déterminante ZNIEFF » des classeurs UNITe.

    python outils/enrichir_zdet.py <dossier de sortie>

**Ce que l'outil produit, et ce qu'il ne fait pas.** Un fichier par classeur,
les taxons dans l'ordre des lignes de l'onglet `Statuts`, et une colonne par
région où BDC-Statuts a quelque chose à dire pour ce groupe. Le fichier se
colle donc en regard du classeur. **Rien n'est écrit dans les classeurs** :
c'est la responsable environnement qui décide ce qu'elle reprend.

**Une ZNIEFF n'est pas une protection mais un inventaire**, et une espèce
« déterminante » est celle dont la présence justifie d'en créer ou d'en
délimiter une. Le statut n'emporte aucune obligation : c'est un signal
d'enjeu local. Il est régional — BDC le porte sur 26 régions et 89
départements — et souvent conditionnel : 44 % des lignes de BDC s'assortissent
d'une réserve, « Présence d'adultes » par exemple. La condition est reprise
telle quelle, car c'est elle qui fait la valeur du statut.

La colonne `etat` dit où en est le classeur, et c'est le cœur de l'affaire :

    colonne absente   la région n'est pas suivie pour ce groupe
    case vide         la colonne existe, la cellule est vide
    déjà renseigné    le classeur porte déjà une valeur
    DIVERGENCE        le classeur dit autre chose que BDC

Trois des six classeurs ne portent aucune colonne de ce type — oiseaux,
amphibiens-reptiles et insectes —, et c'est pour eux que l'apport est entier.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from prediag_enviro import chemins, service, vocabulaire  # noqa: E402

#: Régions de métropole. Les territoires d'outre-mer de BDC sont écartés : les
#: classeurs ne les suivent pas, et aucun projet n'y est instruit à ce jour.
REGIONS_METROPOLE = (
    "Alsace", "Aquitaine", "Auvergne", "Auvergne-Rhône-Alpes",
    "Basse-Normandie", "Bourgogne", "Bourgogne-Franche-Comté", "Bretagne",
    "Centre", "Centre-Val de Loire", "Champagne-Ardenne", "Corse",
    "Franche-Comté", "Grand Est", "Haute-Normandie", "Hauts-de-France",
    "Ile-de-France", "Languedoc-Roussillon", "Limousin", "Lorraine",
    "Midi-Pyrénées", "Nord-Pas-de-Calais", "Normandie", "Nouvelle-Aquitaine",
    "Occitanie", "Pays-de-la-Loire", "Picardie", "Poitou-Charentes",
    "Provence-Alpes-Côte-d'Azur", "Rhône-Alpes",
)


def conditions_zdet() -> dict:
    """La réserve attachée à chaque statut, lue dans l'archive BDC.

    **L'index ne la retient pas.** `bdc.Entree` porte le code et son rendu,
    pas le champ `RQ_STATUT` — et c'est lui qui dit « Présence d'adultes »,
    « Uniquement en zone de montagne », « Hors période de migration ». 44 %
    des lignes déterminantes de BDC en portent une, et sans elle le statut
    dit plus qu'il ne sait.

    On relit donc l'archive plutôt que d'alourdir l'index : cet outil tourne
    de loin en loin, et la lecture coûte quelques secondes là où changer le
    format obligerait à reconstruire les 447 000 lignes.
    """
    import csv as _csv
    import io as _io
    import zipfile

    archive = zipfile.ZipFile(chemins.referentiels() / "BDC.zip")
    membre = next(n for n in archive.namelist()
                  if n.lower().endswith(".csv") and "types" not in n.lower())
    par_cle: dict[tuple[str, str], str] = {}
    with archive.open(membre) as flux:
        texte = _io.TextIOWrapper(flux, encoding="utf-8", errors="replace",
                                  newline="")
        for ligne in _csv.DictReader(texte, delimiter=","):
            if (ligne.get("CD_TYPE_STATUT") or "").strip() != "ZDET":
                continue
            reserve = (ligne.get("RQ_STATUT") or "").strip()
            if reserve:
                cle = ((ligne.get("CD_REF") or "").strip(),
                       (ligne.get("LB_ADM_TR") or "").strip())
                par_cle[cle] = reserve
    return par_cle


def _colonnes_zdet(classeur) -> dict:
    """Les colonnes déterminantes du classeur, par territoire BDC."""
    return {c.territoire_bdc: c for c in classeur.colonnes
            if c.type_bdc == "ZDET" and c.territoire_bdc}


def _etat(sien: str, celui_de_bdc: str, colonne_presente: bool) -> str:
    if not colonne_presente:
        return "colonne absente"
    if not sien:
        return "case vide"
    if vocabulaire.equivalents(sien, celui_de_bdc, "ZDET"):
        return "déjà renseigné"
    return "DIVERGENCE"


def enrichir(classeur, statuts, regions: list[str],
             conditions: dict | None = None) -> tuple[list[dict], list[str]]:
    """Une ligne par taxon et par région où BDC dit quelque chose."""
    siennes = _colonnes_zdet(classeur)
    lignes: list[dict] = []
    retenues: list[str] = []
    for region in regions:
        if not statuts.couvre("ZDET", region):
            continue
        trouve = False
        for taxon in classeur.taxons:
            if not taxon.cd_nom:
                continue
            rendu = statuts.rendu(taxon.cd_nom, "ZDET", region)
            if not rendu:
                continue
            trouve = True
            colonne = siennes.get(region)
            sien = ("" if colonne is None
                    else str(taxon.valeurs.get(colonne.index, "") or "").strip())
            # Les classeurs écrivent « Oui », BDC rend « oui » : on suit
            # sa convention, c'est son fichier.
            valeur = "Oui" if rendu.strip().lower() == "oui" else rendu
            reserve = (conditions or {}).get((taxon.cd_nom, region), "")
            lignes.append({
                "ligne_classeur": taxon.ligne,
                "cd_nom": taxon.cd_nom,
                "nom_scientifique": taxon.nom_scientifique,
                "nom_commun": taxon.nom_commun,
                "region": region,
                "determinante_bdc": valeur,
                "condition": reserve,
                "valeur_actuelle": sien,
                "etat": _etat(sien, rendu, colonne is not None),
            })
        if trouve:
            retenues.append(region)
    lignes.sort(key=lambda l: (l["region"], l["ligne_classeur"]))
    return lignes, retenues


def main() -> None:
    sortie = Path(sys.argv[1] if len(sys.argv) > 1 else "sorties/zdet")
    sortie.mkdir(parents=True, exist_ok=True)

    contexte = service.charger_contexte(Path("."))
    conditions = conditions_zdet()
    classeurs = service.charger_classeurs(Path("."))
    champs = ["ligne_classeur", "cd_nom", "nom_scientifique", "nom_commun",
              "region", "determinante_bdc", "condition", "valeur_actuelle",
              "etat"]

    print(f"BDC-Statuts v{contexte.statuts.version} — "
          f"espèces déterminantes ZNIEFF\n")
    print(f"{len(conditions)} statuts assortis d'une réserve dans l'archive")
    total = 0
    for groupe, classeur in classeurs.items():
        lignes, regions = enrichir(classeur, contexte.statuts,
                                   list(REGIONS_METROPOLE), conditions)
        if not lignes:
            print(f"   {groupe:<18} rien à proposer")
            continue
        chemin = sortie / f"zdet_{groupe}.csv"
        with open(chemin, "w", encoding="utf-8-sig", newline="") as f:
            ecrivain = csv.DictWriter(f, fieldnames=champs)
            ecrivain.writeheader()
            ecrivain.writerows(lignes)
        etats: dict[str, int] = {}
        for l in lignes:
            etats[l["etat"]] = etats.get(l["etat"], 0) + 1
        total += len(lignes)
        print(f"   {groupe:<18} {len(lignes):>5} statuts · "
              f"{len(regions):>2} régions · {etats}")
    print(f"\n{total} statuts proposés, dans {sortie}")
    print("Aucun classeur n'a été modifié.")


if __name__ == "__main__":
    main()
