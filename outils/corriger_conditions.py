#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Réécrit les conditions ZNIEFF que l'outil a mal condensées le 1er novembre 2026.

    python outils/corriger_conditions.py              prépare et vérifie des copies
    python outils/corriger_conditions.py --installer  puis en fait la référence

**Ce qui s'est passé.** `enrichir_classeurs.py` a écrit le 1er novembre 2026
les colonnes DZ demandées par la responsable environnement. Sa condensation
des remarques d'Auvergne-Rhône-Alpes gardait le deux-points et le tiret des
rubriques de la liste, et perdait la parenthèse fermante : « Massif central :
: - nicheur (si sites de reproduction ». Ainsi de 182 des 187 conditions de la
colonne « DZ Auvergne-Rhône-Alpes » des oiseaux ; les 5 autres, que BDC coupe
dans un nom de zone, n'étaient pas condensées du tout. Elle ne disait pas non
plus qu'une remarque était coupée : BDC-Statuts en coupe à 255 caractères,
celles de cette liste comme de cinq autres (voir `determinantes.COUPURE_BDC`).

Le 6 novembre 2026, ce script a réécrit 203 cases : les 187 des oiseaux, 12
chez les mammifères (Auvergne-Rhône-Alpes, Île-de-France, Aquitaine), 4 chez
les insectes (Corse). Relancé, il n'en trouve plus aucune.

**Ce que fait ce script.** Il calcule chaque case DZ deux fois : par la
condensation du 1er novembre, recopiée ici, et par celle d'aujourd'hui. Il ne
réécrit une case que si elle porte encore exactement ce que la première a
écrit, que la seconde écrit autrement, et que l'outil l'a bien écrite — dans
une colonne qu'il a ajoutée, ou une case qu'il a commentée. Toute autre case
est laissée et signalée : elle n'est pas, ou plus, de l'outil. Chaque case
réécrite est commentée, valeur d'avant comprise, et le « Suivi modifs
statuts » en reçoit une ligne par classeur.

Les copies, Excel et l'installation sont ceux d'`enrichir_classeurs.py`.
Seuls les classeurs qui ont une case à réécrire sont copiés, puis installés.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

import openpyxl
from openpyxl.utils import column_index_from_string, get_column_letter, range_boundaries

sys.path.insert(0, str(Path(__file__).resolve().parent))
import enrichir_classeurs as ec  # noqa: E402

from prediag_enviro import chemins, classeurs, determinantes, service  # noqa: E402

DATE = f"{ec.AUJOURD_HUI:%d/%m/%Y}"
#: Ce que l'outil a écrit en tête des colonnes qu'il a ajoutées, et dans les
#: cases qu'il a complétées ou précisées.
EN_TETE_DE_L_OUTIL = "Déterminante ZNIEFF — "
COMMENTAIRE_DE_L_OUTIL = "(outil de prédiag)"


# ------------------------------------------- la condensation du 1er novembre
# Recopiée de 7ed3a44, telle qu'elle a écrit les cases : c'est à elle qu'on
# les reconnaît.

def _etat_aura_1er_novembre(etat: str) -> tuple[bool, str]:
    etat = etat.strip()
    if etat.lower().startswith("non"):
        return False, ""
    return True, re.sub(r"(?i)^d[ée]term\w*", "", etat).strip(" ()")


def _vecteur_aura_1er_novembre(texte: str):
    paires = []
    for morceau in (m for m in texte.split(";") if m.strip()):
        cle, sep, etat = morceau.partition(":")
        zones = determinantes._zones_aura(cle) if sep else None
        if zones is None:
            return False
        oui, precision = _etat_aura_1er_novembre(etat)
        paires.extend((zone, oui, precision) for zone in zones)
    retenues = [(zone, precision) for zone, oui, precision in paires if oui]
    if not retenues:
        return None
    if (len({z for z, _ in retenues}) == len(determinantes.ZONES_AURA)
            and not any(p for _, p in retenues)):
        return ""
    if any(p for _, p in retenues):
        return " ; ".join(f"{z} : {p}" if p else z for z, p in retenues)
    return ", ".join(z for z, _ in retenues)


def condition_1er_novembre(brut, coupee: bool = False) -> str | None:
    """`determinantes.condition` au 1er novembre 2026 ; elle ignorait la coupure."""
    texte = determinantes._texte(brut)
    if not texte:
        return ""
    vecteur = _vecteur_aura_1er_novembre(texte)
    if vecteur is not False:
        return vecteur
    return determinantes._domaines_occitanie(texte) or texte


# ---------------------------------------------------------- les corrections

def _raisons(avant: str, apres: str) -> str:
    """Pourquoi la case change, dit à la responsable environnement.

    Trois raisons, qui se cumulent : la condensation fautive (« : : », un état
    « Déte » pris pour une condition, un vecteur resté brut), le regroupement
    des zones, la coupure de BDC.
    """
    raisons = []
    seule_coupure = apres.rstrip(")").removesuffix("…") == avant.rstrip(")")
    if (" : :" in avant or "Continentale" in avant
            or re.search(r"\bD[ée]te(r)?\b(?!m)", avant)):
        raisons.append("la condition écrite le 01/11/2026 était mal condensée")
    elif not seule_coupure:
        raisons.append("zones de même condition regroupées")
    if "…" in apres:
        raisons.append("la remarque de BDC-Statuts est coupée à 255 caractères : "
                       "« … » marque le texte perdu, qui ne se trouve que dans la "
                       "liste d'origine")
    return " ; ".join(raisons)


def _commentaires(chemin: Path) -> dict[tuple[int, int], str]:
    """Les commentaires de « Statuts », par (ligne, colonne) Excel."""
    wb = openpyxl.load_workbook(chemin)
    try:
        return {(c.row, c.column): c.comment.text
                for ligne in wb[ec.FEUILLE_STATUTS].iter_rows() for c in ligne
                if c.comment is not None}
    finally:
        wb.close()


def corrections(classeur, avant, apres, index, commentaires) -> tuple[list, list]:
    """Les cases à réécrire, et celles qui diffèrent sans être de l'outil.

    Une colonne par territoire, la première, comme `enrichir_classeurs`.
    """
    a_reecrire, laissees = [], []
    cd_refs = {taxon.ligne: ec._cd_ref(taxon, index) for taxon in classeur.taxons}
    vues = set()
    for col in classeur.colonnes:
        if col.type_bdc != "ZDET" or col.territoire_bdc in vues:
            continue
        vues.add(col.territoire_bdc)
        colonne = col.index + 1
        ajoutee = commentaires.get((1, colonne), "").startswith(EN_TETE_DE_L_OUTIL)
        for taxon in classeur.taxons:
            cd = cd_refs[taxon.ligne]
            if not cd:
                continue
            ancienne = avant.cellule(cd, col.territoire_bdc)
            nouvelle = apres.cellule(cd, col.territoire_bdc)
            if ancienne == nouvelle:
                continue
            sien = str(taxon.valeurs.get(col.index, "") or "").strip()
            de_l_outil = ajoutee or COMMENTAIRE_DE_L_OUTIL in commentaires.get(
                (taxon.ligne, colonne), "")
            if sien == ancienne and de_l_outil:
                a_reecrire.append({
                    "feuille": ec.FEUILLE_STATUTS, "ligne": taxon.ligne,
                    "colonne": colonne, "valeur": nouvelle,
                    "commentaire": f"Réécrit le {DATE} {COMMENTAIRE_DE_L_OUTIL} : "
                                   f"{_raisons(ancienne, nouvelle)}. Avant : « {ancienne} ».",
                    "territoire": ec._affichage(col.territoire_bdc),
                    "taxon": taxon.libelle, "avant": ancienne})
            elif sien != nouvelle:
                laissees.append((ec._affichage(col.territoire_bdc), taxon.libelle,
                                 sien, nouvelle))
    return a_reecrire, laissees


def plan(groupe: str, chemin: Path, cible: Path, cellules: list) -> dict:
    par_colonne: dict[str, int] = {}
    for c in cellules:
        par_colonne[c["territoire"]] = par_colonne.get(c["territoire"], 0) + 1
    detail = ", ".join(f"DZ {t} {n}" for t, n in sorted(par_colonne.items()))
    rubriques = sum(1 for c in cellules if " : :" in c["avant"])
    brutes = sum(1 for c in cellules if " : :" not in c["avant"] and "Continentale" in c["avant"])
    regroupees = sum(1 for c in cellules if "regroupées" in c["commentaire"])
    coupees = sum(1 for c in cellules if "…" in c["valeur"])
    raisons = (([f"{rubriques} gardaient le deux-points et le tiret des rubriques de la "
                 f"liste, et souvent perdaient leur parenthèse fermante"] if rubriques else [])
               + ([f"{brutes}, dont BDC coupe la remarque dans un nom de zone, étaient "
                   f"restées brutes"] if brutes else [])
               + ([f"{regroupees} aux zones de même condition désormais regroupées"]
                  if regroupees else [])
               + ([f"{coupees} dont la remarque est coupée par BDC-Statuts à 255 caractères, "
                   f"désormais marquées « … »"] if coupees else []))
    suivi = (f"Correction de {len(cellules)} conditions de déterminance ZNIEFF écrites le "
             f"01/11/2026 par l'outil ({detail}) : " + " ; ".join(raisons)
             + ". Chaque case commentée, valeur d'avant comprise.")
    return {"groupe": groupe, "source": str(chemin), "cible": str(cible),
            "cellules": [{k: c[k] for k in ("feuille", "ligne", "colonne", "valeur",
                                            "commentaire")} for c in cellules],
            "statuts": {"feuille": ec.FEUILLE_STATUTS, "n": 0, "lignes": 0, "depart": 0,
                        "modele": 0, "garder_mfc": False, "entetes": [], "valeurs": [],
                        "commentaires": [], "filtre": None},
            "tables": [], "saisie": None,
            "ajouts": [{"feuille": ec.FEUILLE_SUIVI, "colonnes": 3, "colonne_date": 1,
                        "lignes": [[ec.AUJOURD_HUI.isoformat(), ec.PERSONNE, suivi]]}],
            "suivi": [suivi]}


# --------------------------------------------------------- la vérification

def _cases(ws) -> dict[tuple[int, int], tuple]:
    """Les cases d'un onglet qui portent une valeur ou un commentaire."""
    return {(c.row, c.column): (c.value, c.comment.text if c.comment else None)
            for ligne in ws.iter_rows() for c in ligne
            if c.value is not None or c.comment is not None}


_REFERENCE = re.compile(r"(\$?)([A-Z]{1,3})(\$?)(\d+)")


def _relative(formule: str, ligne0: int, colonne0: int) -> str:
    """Une formule de mise en forme, ses références rapportées au coin de sa plage."""
    def rapporter(m):
        colonne, ligne = column_index_from_string(m.group(2)), int(m.group(4))
        return ((f"R{ligne}" if m.group(3) else f"R[{ligne - ligne0}]")
                + (f"C{colonne}" if m.group(1) else f"C[{colonne - colonne0}]"))
    return _REFERENCE.sub(rapporter, formule)


def _mises_en_forme(ws) -> dict:
    """Chaque règle de mise en forme conditionnelle, et les cases qu'elle couvre.

    Excel regroupe à l'enregistrement les règles identiques de plages
    voisines : les 16 règles « Oui » qu'`enrichir_classeurs` avait posées une
    à une sur les colonnes DZ des mammifères deviennent un seul bloc. Compter
    les blocs y voyait une perte ; ce qui compte, c'est que chaque règle —
    type, texte, style, formule rapportée à sa plage — couvre les mêmes cases.
    """
    couverture: dict[tuple, set] = {}
    for cf in ws.conditional_formatting:
        plages = [range_boundaries(str(r)) for r in cf.sqref.ranges]
        if any(None in p for p in plages):
            cases = {str(cf.sqref)}
        else:
            cases = {(l, c) for c1, l1, c2, l2 in plages
                     for l in range(l1, l2 + 1) for c in range(c1, c2 + 1)}
        colonne0, ligne0 = plages[0][0] or 1, plages[0][1] or 1
        for regle in cf.rules:
            signature = (regle.type, regle.operator, regle.text, regle.stopIfTrue,
                         repr(regle.dxf), tuple(_relative(f, ligne0, colonne0)
                                                for f in (regle.formula or ())))
            couverture.setdefault(signature, set()).update(cases)
    return couverture


def verifier(original: Path, copie: Path, cellules: list, suivi: list[str]) -> list[str]:
    """Ce qui distingue la copie de l'original hors des changements prévus.

    Vide si la copie est conforme : les cases prévues portent leur nouvelle
    valeur et leur commentaire, le suivi ses lignes, et rien d'autre n'a
    bougé — valeurs, formules, commentaires, mises en forme conditionnelles,
    listes de validation —, dans aucun onglet.
    """
    attendues = {(c["ligne"], c["colonne"]): c for c in cellules}
    a = openpyxl.load_workbook(original)
    b = openpyxl.load_workbook(copie)
    ecarts = []
    try:
        if a.sheetnames != b.sheetnames:
            return [f"onglets : {a.sheetnames} → {b.sheetnames}"]
        for nom in a.sheetnames:
            wa, wb_ = a[nom], b[nom]
            ca, cb = _cases(wa), _cases(wb_)
            ajoutees = []
            for cle in sorted(set(ca) | set(cb)):
                (va, na), (vb, nb) = ca.get(cle, (None, None)), cb.get(cle, (None, None))
                adresse = f"{nom}!{get_column_letter(cle[1])}{cle[0]}"
                if nom == ec.FEUILLE_STATUTS and cle in attendues:
                    c = attendues[cle]
                    if (vb != c["valeur"] or c["commentaire"] not in (nb or "")
                            or (na and not (nb or "").startswith(na))):
                        ecarts.append(f"{adresse} : {vb!r}, commentaire {(nb or '')[-80:]!r}")
                    continue
                if (va, na) == (vb, nb):
                    continue
                if nom == ec.FEUILLE_SUIVI and va is None and na is None:
                    ajoutees.append(vb)
                    continue
                ecarts.append(f"{adresse} : {va!r} → {vb!r}"
                              + (f" (commentaire changé)" if na != nb else ""))
            if nom == ec.FEUILLE_SUIVI and not all(t in ajoutees for t in suivi):
                ecarts.append(f"{nom} : lignes du suivi absentes")
            mfc_a, mfc_b = _mises_en_forme(wa), _mises_en_forme(wb_)
            for signature in set(mfc_a) | set(mfc_b):
                avant, apres = mfc_a.get(signature, set()), mfc_b.get(signature, set())
                if avant != apres:
                    ecarts.append(f"{nom} : mise en forme « {signature[2] or signature[0]} » — "
                                  f"{len(avant - apres)} cases perdues, "
                                  f"{len(apres - avant)} gagnées")
            x, y = (len(w.data_validations.dataValidation) for w in (wa, wb_))
            if x != y:
                ecarts.append(f"{nom} : listes de validation {x} → {y}")
    finally:
        a.close()
        b.close()
    return ecarts


# --------------------------------------------------------------------- main

def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--classeurs", type=Path, default=ec.production(),
                        help="les classeurs de référence (par défaut, ceux de production)")
    parser.add_argument("--travail", type=Path,
                        default=Path.home() / "prediag-enviro-travail"
                        / f"corrections_{ec.AUJOURD_HUI}")
    parser.add_argument("--installer", action="store_true",
                        help="sauvegarder les originaux et installer les copies vérifiées")
    args = parser.parse_args()

    if args.installer:
        return ec.installer(args.classeurs, args.travail)

    contexte = service.charger_contexte(ec.RACINE)
    archive = chemins.referentiels() / "BDC.zip"
    avant = determinantes.depuis_bdc(archive, condenser=condition_1er_novembre)
    apres = determinantes.depuis_bdc(archive)
    if ec.EXPORT_NA.exists():
        for listes in (avant, apres):
            determinantes.ajouter_export_inpn(listes, ec.EXPORT_NA, "Nouvelle-Aquitaine",
                                              contexte.index, ec.REFERENCE_NA)

    copies = args.travail / "classeurs"
    copies.mkdir(parents=True, exist_ok=True)
    plans, attendus = [], {}
    for chemin in sorted(args.classeurs.glob("B-Statuts*.xlsx")):
        groupe = next((g for g, m in service.MOTIFS.items() if chemin.match(m)), None)
        if groupe is None:
            continue
        classeur = classeurs.lire(chemin, groupe)
        cellules, laissees = corrections(classeur, avant, apres, contexte.index,
                                         _commentaires(chemin))
        print(f"   {groupe:<18} {len(cellules):>3} cases à réécrire"
              + (f" · {len(laissees)} laissées" if laissees else ""))
        for territoire, taxon, sien, nouvelle in laissees:
            print(f"      laissée — DZ {territoire}, {taxon} : « {sien} » "
                  f"(la condensation donnerait « {nouvelle} »)")
        if not cellules:
            continue
        cible = copies / chemin.name
        # Octet par octet, comme `enrichir_classeurs` : copy2 recopierait les
        # attributs OneDrive de l'original.
        shutil.copyfile(chemin, cible)
        p = plan(groupe, chemin, cible, cellules)
        plans.append(p)
        attendus[cible] = (chemin, cellules, p["suivi"])

    if not plans:
        print("\nAucune case à réécrire.")
        return 0
    (args.travail / "cases.json").write_text(
        json.dumps({str(k): v[1] for k, v in attendus.items()}, ensure_ascii=False,
                   indent=1), encoding="utf-8")
    plans_json = args.travail / "plans.json"
    plans_json.write_text(json.dumps(plans, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nExcel applique les plans aux copies de {copies}…")
    code = ec.appliquer(plans_json)
    if code:
        print(f"{code} classeur(s) en échec — rien n'est installé.")
        return code

    print("\nVérification des copies…")
    echecs = 0
    for cible, (chemin, cellules, suivi) in attendus.items():
        ecarts = verifier(chemin, cible, cellules, suivi)
        echecs += bool(ecarts)
        print(f"   {'conforme' if not ecarts else 'NON CONFORME'} — {cible.name}")
        for e in ecarts[:12]:
            print(f"      {e}")
    print("Aucun classeur de référence n'a été modifié."
          + ("" if not echecs else f" {echecs} copie(s) non conforme(s) : ne pas installer."))
    return 1 if echecs else 0


if __name__ == "__main__":
    raise SystemExit(main())
