#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Intègre aux classeurs UNITe les colonnes que la responsable environnement a demandées.

    python outils/enrichir_classeurs.py              prépare et vérifie des copies
    python outils/enrichir_classeurs.py --installer  puis en fait la référence

Ses deux demandes du 6 octobre 2026 :

* **une colonne « déterminante ZNIEFF » par région**, avec ses conditions de
  déterminance — dans quels départements, « si nicheuse », « hors Massif
  central » ;
* **pour les orthoptères, le statut par domaine biogéographique** de Sardet &
  Defaut (2004), tel que `extraire_orthopteres.py` l'a extrait.

**Comment.** Les classeurs de production sont copiés dans un dossier de
travail local ; Excel lui-même modifie ces copies (`excel_appliquer.ps1`),
pour ne rien perdre de ce qu'une bibliothèque Python ne sait pas relire :
commentaires, mises en forme conditionnelles, valeurs calculées des formules.
Les copies sont ensuite vérifiées. `--installer` sauvegarde les originaux et
met les copies à leur place, en production et dans le dépôt.

**Ce qui change dans un classeur, et rien d'autre :**

* `Statuts` : les colonnes ajoutées, après la dernière colonne occupée, dans
  la mise en forme de ses colonnes voisines, chaque en-tête commenté de sa
  source ; les cases vides de ses colonnes DZ que les listes renseignent, et
  ses « Oui » qu'une liste restreint — chaque case commentée, valeur d'avant
  comprise ;
* « Saisie étude » : les colonnes correspondantes, déclarées comme les
  siennes ; et trois défauts corrigés, chacun seulement si le classeur est
  encore dans l'état constaté (voir `corrections_saisie`) ;
* « Textes de référence » et « Suivi modifs statuts » : une ligne par ajout.

La version précédente de cet outil (`colonnes_a_coller.py`, 31 octobre 2026)
préparait des blocs à coller à la main ; c'est désormais l'outil qui écrit.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from datetime import date
from pathlib import Path

import openpyxl

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from prediag_enviro import chemins, classeurs, determinantes, implantation, service  # noqa: E402
from prediag_enviro.taxref import cle_alphabetique, normaliser  # noqa: E402
from extraire_orthopteres import DOMAINES  # noqa: E402

AUJOURD_HUI = date.today()
PERSONNE = "Eliott Moreau (outil de prédiag)"

#: L'export INPN de la liste de Nouvelle-Aquitaine, joint par la responsable
#: environnement à sa demande du 6 octobre 2026, rangé avec les référentiels.
#: BDC-Statuts v18 n'en porte pas les oiseaux.
EXPORT_NA = chemins.referentiels() / "znieff_nouvelle-aquitaine_inpn_2024-10-08.csv"
REFERENCE_NA = ("INPN — Liste des espèces déterminantes de l'inventaire ZNIEFF, "
                "région Nouvelle-Aquitaine, export du 08/10/2024")

ORTHOPTERES = RACINE / "sorties" / "orthopteres_domaines_2026-10-17.csv"
REFERENCE_ORTHOPTERES = (
    "Sardet, E. & Defaut, B. (coord.), 2004. Les Orthoptères menacés en France. "
    "Liste rouge nationale et listes rouges par domaines biogéographiques. "
    "Matériaux Orthoptériques et Entomocénotiques, 9 : 125-137. Échelle de "
    "priorité 1 à 4 (1 = la plus menacée), pas celle de l'UICN.")

FEUILLE_STATUTS = "Statuts"
FEUILLE_SAISIE = "Saisie étude"
FEUILLE_TEXTES = "Textes de référence"
FEUILLE_SUIVI = "Suivi modifs statuts"


# ----------------------------------------------------------------- territoires

def _territoire(libelle: str) -> str:
    """Libellé BDC d'un territoire."""
    return classeurs.territoire_bdc(libelle)


def _affichage(territoire: str) -> str:
    return determinantes.AFFICHAGE.get(territoire, territoire)


def _plat(v) -> str:
    return " ".join(str(v or "").split()).lower()


def _cle(texte) -> str:
    """Forme de comparaison d'un libellé : sans accents, sans ponctuation."""
    t = unicodedata.normalize("NFD", str(texte or "")).encode("ascii", "ignore").decode()
    t = t.lower().replace("paca", "provence alpes cote d azur")
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def _est_non(v) -> bool:
    return _plat(v) in ("non", "0", "-", "n")


def _cd_ref(taxon, index) -> str | None:
    """Le cd_ref d'une ligne : par son CD_NOM, sinon par son nom valide exact.

    Une ligne sans CD_NOM porte d'ordinaire une espèce absente de France. Son
    nom ne se retrouve alors dans TaxRef que comme synonyme d'une autre : la
    Sérotine isabelle y est un synonyme de la Sérotine commune, dont elle
    hériterait tous les statuts.
    """
    if taxon.cd_nom:
        t = index.taxon(taxon.cd_nom)
        if t:
            return t.cd_ref
    cd = determinantes.apparier_nom_valide(index, taxon.nom_scientifique)
    if cd and normaliser(index.taxons[cd].lb_nom) == normaliser(taxon.nom_scientifique):
        return cd
    return None


# ------------------------------------------------------------- les colonnes DZ

def colonnes_zdet(classeur, dispo, listes, index) -> dict:
    """Les colonnes déterminantes à ajouter, et ses colonnes existantes confrontées."""
    cd_refs = {t.ligne: _cd_ref(t, index) for t in classeur.taxons}
    siennes = {}
    for col in classeur.colonnes:
        if col.type_bdc == "ZDET":
            siennes.setdefault(col.territoire_bdc, col)
    proposees, modifiees = [], []
    resume = {"completees": {}, "precisees": {}, "concordantes": 0,
              "non_apparies": sum(1 for cd in cd_refs.values() if not cd)}

    for territoire in sorted(listes.territoires(),
                             key=lambda t: cle_alphabetique(_affichage(t))):
        valeurs = {ligne: listes.cellule(cd, territoire)
                   for ligne, cd in cd_refs.items() if cd}
        valeurs = {ligne: v for ligne, v in valeurs.items() if v}
        if not valeurs:
            continue
        citees = listes.citations(territoire, {cd_refs[ligne] for ligne in valeurs})
        libelle = _affichage(territoire)
        colonne = siennes.get(territoire)
        if colonne is None:
            proposees.append(implantation.Proposee(
                f"DZ\n{libelle}", libelle, "DZ", valeurs,
                source=f"Déterminante ZNIEFF — {libelle}\n" + "\n".join(citees)))
            continue
        for taxon in classeur.taxons:
            sien = str(taxon.valeurs.get(colonne.index, "") or "").strip()
            notre = valeurs.get(taxon.ligne, "")
            if not notre or _est_non(sien):
                continue
            source = " ; ".join(listes.citations(territoire, {cd_refs[taxon.ligne]}))
            if not sien:
                modifiees.append((taxon.ligne, colonne.index + 1, notre,
                                  f"Complété le {AUJOURD_HUI:%d/%m/%Y} (outil de prédiag), "
                                  f"case vide auparavant. Liste : {source}"))
                resume["completees"][libelle] = resume["completees"].get(libelle, 0) + 1
            elif _plat(sien) == _plat(notre) or (notre == "Oui" and _plat(sien) in ("oui", "x")):
                resume["concordantes"] += 1
            elif _plat(sien) in ("oui", "x"):
                modifiees.append((taxon.ligne, colonne.index + 1, notre,
                                  f"Précisé le {AUJOURD_HUI:%d/%m/%Y} (outil de prédiag) : la "
                                  f"liste restreint la détermination. Avant : « {sien} ». "
                                  f"Liste : {source}"))
                resume["precisees"][libelle] = resume["precisees"].get(libelle, 0) + 1
    return {"proposees": proposees, "modifiees": modifiees, "resume": resume}


def colonnes_orthopteres(classeur, chemin_csv: Path) -> tuple[list, int]:
    """Les huit domaines de Sardet & Defaut, sur ses lignes d'orthoptères."""
    par_nom: dict[str, list] = {}
    for taxon in classeur.taxons:
        par_nom.setdefault(taxon.nom_scientifique.strip(), []).append(taxon)
    valeurs = {code: {} for code, _ in DOMAINES[1:]}
    renseignees = 0
    with open(chemin_csv, encoding="utf-8-sig", newline="") as f:
        for ligne in csv.DictReader(f):
            correspondants = par_nom.get(ligne["nom_scientifique"].strip(), [])
            if len(correspondants) != 1:
                continue
            trouvees = {code: (ligne.get(code) or "").strip() for code in valeurs}
            trouvees = {code: v for code, v in trouvees.items() if v}
            for code, v in trouvees.items():
                # Ses indices nationaux sont des nombres : on écrit de même.
                valeurs[code][correspondants[0].ligne] = int(v) if v.isdigit() else v
            renseignees += bool(trouvees)
    proposees = [implantation.Proposee(
        f"Priorité orthoptères\n{code}", f"{libelle} ({code})", "Priorité orthoptères",
        valeurs[code], source=f"Priorité orthoptères — {libelle}\n{REFERENCE_ORTHOPTERES}")
        for code, libelle in DOMAINES[1:]]
    return proposees, renseignees


# --------------------------------------------------- défauts de « Saisie étude »

def _cible(s: implantation.Saisie, dispo, numero) -> str:
    i = s.colonne_lue(numero) - 1 if numero else -1
    return dispo.entetes[i] if 0 <= i < len(dispo.entetes) else ""


def _lit(entete: str, champ: str, territoire: str) -> bool:
    """L'en-tête est-il celui qu'annoncent ce champ et ce territoire ?"""
    base = re.sub(r"(?i)\s*(nicheurs|hivernants|de passage)\s*", "", champ).upper()
    prefixe = {"DZ": "dz ", "LRR": "liste rouge "}.get(base)
    return bool(prefixe) and _cle(entete).startswith(_cle(prefixe + territoire))


def corrections_saisie(groupe: str, dispo) -> tuple[list[dict], list[str]]:
    """Les défauts de saisie relevés le 1er novembre 2026, corrigés s'ils sont encore là.

    * **Mammifères** : la colonne qui lit « DZ Nord-Pas-de-Calais » était
      déclarée « Provence-Alpes-Côte d'Azur » — deux colonnes PACA, aucune
      Nord-Pas-de-Calais. Les données le confirment : 19 de ses « Oui » sont
      sur la liste du Nord-Pas-de-Calais, 12 sur celle de PACA.
    * **Araignées** : 26 colonnes étiquetées « DZ » lisent des listes rouges
      régionales. Elles redeviennent « LRR ».
    * **Macrohétérocères** : la colonne « DZ Basse-Normandie » avait été
      ajoutée sans numéro, et les dix suivantes lisaient chacune la colonne
      voisine de gauche — « EEE » affichait la DZ PACA. Numéros rétablis, et
      l'avant-dernière, qui lit la DZ PACA, étiquetée « DZ ».

    Rend les cellules à écrire et les lignes du suivi.
    """
    s = dispo.saisie
    if s is None:
        return [], []
    cellules, suivi = [], []

    def ecrire(ligne, col, valeur):
        cellules.append({"feuille": FEUILLE_SAISIE, "ligne": ligne, "colonne": col,
                         "valeur": valeur})

    if groupe == "mammiferes":
        for c in s.colonnes:
            entete = _cible(s, dispo, c.numero)
            if (c.champ.upper() == "DZ" and _cle(c.territoire) == _cle("Provence-Alpes-Côte d'Azur")
                    and _cle(entete) == _cle("DZ Nord-Pas-de-Calais")):
                ecrire(s.ligne_index + 1, c.colonne, "Nord-Pas-de-Calais")
                suivi.append(
                    f"Correction de « Saisie étude », colonne {implantation.colonne(c.colonne)} : "
                    f"territoire « {c.territoire} » → « Nord-Pas-de-Calais ». Elle lit la "
                    f"colonne « DZ Nord-Pas-de-Calais » de « Statuts » ; la saisie affichait "
                    f"deux colonnes PACA.")

    elif groupe == "araignees":
        faux = [c for c in s.colonnes if c.champ.upper() == "DZ" and c.numero
                and _lit(_cible(s, dispo, c.numero), "LRR", c.territoire)]
        for c in faux:
            ecrire(s.ligne_index + 2, c.colonne, "LRR")
        if faux:
            suivi.append(
                f"Correction de « Saisie étude », ligne {s.ligne_index + 2} : {len(faux)} colonnes "
                f"étiquetées « DZ » lisent des listes rouges régionales de « Statuts » "
                f"({implantation.colonne(faux[0].colonne)} à {implantation.colonne(faux[-1].colonne)}) "
                f"— étiquette « LRR ».")

    elif groupe == "macroheteroceres":
        numerotees = [c for c in s.colonnes if c.numero]
        sans_numero = [c for c in s.colonnes if c.numero is None and c.champ.upper() == "DZ"]
        # Le décalage : à partir d'une colonne, chacune lit la voisine de gauche
        # de celle que son étiquette annonce.
        depart = next((i for i, c in enumerate(numerotees)
                       if not _lit(_cible(s, dispo, c.numero), c.champ, c.territoire)
                       and _lit(_cible(s, dispo, c.numero + 1), c.champ, c.territoire)), None)
        trou = next((c for c in sans_numero
                     if depart is not None and c.colonne < numerotees[depart].colonne
                     and _lit(_cible(s, dispo, numerotees[depart].numero), "DZ", c.territoire)), None)
        if depart is not None and trou is not None:
            decalees = numerotees[depart:]
            ecrire(s.ligne_index, trou.colonne, numerotees[depart].numero)
            for c in decalees:
                ecrire(s.ligne_index, c.colonne, c.numero + 1)
            relabel = [c for c in decalees
                       if not _lit(_cible(s, dispo, c.numero + 1), c.champ, c.territoire)
                       and _lit(_cible(s, dispo, c.numero + 1), "DZ", c.territoire)]
            for c in relabel:
                ecrire(s.ligne_index + 2, c.colonne, "DZ")
            suivi.append(
                f"Correction de « Saisie étude » : la colonne {implantation.colonne(trou.colonne)} "
                f"(DZ {trou.territoire}) n'avait pas de numéro, et les {len(decalees)} suivantes "
                f"({implantation.colonne(decalees[0].colonne)} à "
                f"{implantation.colonne(decalees[-1].colonne)}) lisaient chacune la colonne "
                f"voisine de gauche dans « Statuts » — « EEE » affichait la DZ PACA. Numéros "
                f"rétablis" + (f" ; {', '.join(implantation.colonne(c.colonne) for c in relabel)} "
                              f"étiquetée « DZ »" if relabel else "") + ".")
    return cellules, suivi


# ------------------------------------------------------------------- le plan

def _source_format(s: implantation.Saisie, ligne: int, col: int) -> list[int]:
    """Une cellule non fusionnée dont recopier le format, sur cette ligne."""
    for c in range(col, 0, -1):
        if not s.fusionnee(ligne, c):
            return [ligne, c]
    return [ligne, col]


def _filtre_etendu(ref: str | None, derniere: int) -> str | None:
    if not ref or ":" not in ref:
        return None
    debut, fin = ref.split(":")
    m = re.match(r"([A-Z]+)(\d+)", fin)
    if not m or int(m.group(2)) <= 1:
        return None
    from openpyxl.utils import column_index_from_string
    if column_index_from_string(m.group(1)) >= derniere:
        return None
    return f"{debut}:{implantation.colonne(derniere)}{m.group(2)}"


def _mfc_oui(chemin: Path, col: int) -> bool:
    """Sa colonne modèle porte-t-elle la mise en évidence des « Oui » ?"""
    wb = openpyxl.load_workbook(chemin)
    try:
        for cf in wb[FEUILLE_STATUTS].conditional_formatting:
            couvre = any(r.min_col <= col <= r.max_col for r in cf.sqref.ranges)
            if couvre and any(getattr(r, "text", None) == "Oui" for r in cf.rules):
                return True
        return False
    finally:
        wb.close()


def plan(groupe, chemin, cible, classeur, dispo, zdet, ortho, citation_bdc) -> dict:
    proposees = zdet["proposees"] + (ortho[0] if ortho else [])
    n, n_dz = len(proposees), len(zdet["proposees"])
    d = dispo.premiere_libre
    dz = [c.index + 1 for c in classeur.colonnes if c.type_bdc == "ZDET"]
    modele = max(dz) if dz else dispo.derniere_entete

    cellules = [{"feuille": FEUILLE_STATUTS, "ligne": l, "colonne": c, "valeur": v,
                 "commentaire": t} for l, c, v, t in zdet["modifiees"]]
    corrections, suivi_corrections = corrections_saisie(groupe, dispo)
    cellules += corrections

    statuts = {"feuille": FEUILLE_STATUTS, "n": n, "lignes": dispo.derniere_ligne, "depart": d,
               "modele": modele, "garder_mfc": bool(dz) and _mfc_oui(chemin, modele),
               "entetes": [p.entete for p in proposees],
               "valeurs": [[ligne, j, v] for j, p in enumerate(proposees)
                           for ligne, v in sorted(p.valeurs.items()) if v not in (None, "")],
               "commentaires": [[d + j, p.source] for j, p in enumerate(proposees) if p.source],
               "filtre": _filtre_etendu(dispo.filtre, d + n - 1)}

    s = dispo.saisie
    saisie, tables, suivi_saisie = None, [], []
    if s is not None and n:
        if s.table_region and s.colonne_region:
            # La saisie suit la « Région d'étude » : une seule colonne DZ, qui
            # la suit aussi, par une table rangée sous la sienne.
            c1, _, c2, l2 = s.table_region
            ligne_table = l2 + 3
            fin_table = ligne_table + n_dz - 1
            table = (f"Statuts!${implantation.colonne(c1)}${ligne_table}:"
                     f"${implantation.colonne(c1 + 1)}${fin_table}")
            region = f"$B${s.ligne_index}"
            tables.append({"feuille": FEUILLE_STATUTS, "ligne": ligne_table, "colonne": c1,
                           "titre": "Colonnes DZ par territoire (« Région d'étude » de la saisie)",
                           "valeurs": [[p.territoire, s.numero(d + j)]
                                       for j, p in enumerate(zdet["proposees"])]})
            m = s.colonne_region
            saisie = {"feuille": FEUILLE_SAISIE, "n": 1 if n_dz else 0, "avant": m + 1,
                      "modele": m, "premiere": s.ligne_index + 2,
                      "derniere": s.derniere_ligne_formules, "ligne_index": s.ligne_index,
                      "formats": [[s.ligne_index, m], [s.ligne_index + 1, m],
                                  [s.ligne_index + 2, m]],
                      "declarations": [[
                          {"formule": f'=IFERROR(VLOOKUP({region},{table},2,FALSE),"")'},
                          {"formule": f"={region}"}, {"valeur": "DZ"}]],
                      "remplacements": []}
            suivi_saisie.append(
                f"« Saisie étude » : colonne DZ ajoutée en {implantation.colonne(m + 1)}, qui suit "
                f"la « Région d'étude » comme la liste rouge régionale, par la table "
                f"{implantation.colonne(c1)}{ligne_table}:{implantation.colonne(c1 + 1)}{fin_table} "
                f"de « Statuts ».")
        elif s.colonne_eee:
            m = s.colonne_eee - 1
            remplacements = []
            if d + n - 1 > s.plage_derniere_colonne:
                nouvelle = re.sub(r"(:\$?)([A-Z]+)(\$?\d+)$",
                                  lambda g: g.group(1) + implantation.colonne(d + n - 1) + g.group(3),
                                  s.plage)
                remplacements.append([s.plage, nouvelle])
            saisie = {"feuille": FEUILLE_SAISIE, "n": n, "avant": s.colonne_eee, "modele": m,
                      "premiere": s.ligne_index + 2, "derniere": s.derniere_ligne_formules,
                      "ligne_index": s.ligne_index,
                      "formats": [_source_format(s, s.ligne_index, m),
                                  _source_format(s, s.ligne_index + 1, m),
                                  [s.ligne_index + 2, m]],
                      "declarations": [[{"valeur": s.numero(d + j)}, {"valeur": p.territoire},
                                        {"valeur": p.champ}] for j, p in enumerate(proposees)],
                      "remplacements": remplacements}
            suivi_saisie.append(
                f"« Saisie étude » : {n} colonnes ajoutées devant « EEE », en "
                f"{implantation.colonne(s.colonne_eee)} à {implantation.colonne(s.colonne_eee + n - 1)}"
                + (f" ; plage des RECHERCHEV étendue jusqu'à la colonne "
                   f"{implantation.colonne(d + n - 1)} de « Statuts »" if remplacements else "")
                + ".")

    r = zdet["resume"]
    date_iso = AUJOURD_HUI.isoformat()
    suivi = []
    if n_dz:
        suivi.append(
            f"Ajout de {n_dz} colonnes « DZ » (espèces déterminantes ZNIEFF), une par territoire, "
            f"en {implantation.colonne(d)} à {implantation.colonne(d + n_dz - 1)} de « Statuts ». "
            f"Condition de déterminance entre parenthèses, comme « Oui (MC, SO) » ou "
            f"« Oui (dép. 33, 40) ». Sources : en-tête de chaque colonne et « Textes de référence ».")
    if ortho:
        suivi.append(
            f"Ajout de 8 colonnes « Priorité orthoptères » (domaines biogéographiques, Sardet & "
            f"Defaut 2004) en {implantation.colonne(d + n_dz)} à {implantation.colonne(d + n - 1)}"
            f" : {ortho[1]} orthoptères renseignés.")
    for cle, mot in (("completees", "Complément de"), ("precisees", "Précision de")):
        if r[cle]:
            detail = ", ".join(f"{t} {k}" for t, k in sorted(r[cle].items()))
            suivi.append(
                f"{mot} {sum(r[cle].values())} cases des colonnes DZ existantes ({detail}) "
                + ("d'après les mêmes listes" if cle == "completees" else
                   "par la condition que pose la liste, là où la case disait « Oui »")
                + " — chaque case commentée.")
    suivi += suivi_saisie + suivi_corrections

    textes = []
    for p in zdet["proposees"]:
        listes_citees = p.source.split("\n")[1:]
        via = (f" — via {citation_bdc}"
               if any(c != REFERENCE_NA for c in listes_citees) else "")
        textes.append([f"DZ {p.territoire}", " ; ".join(listes_citees) + via])
    if ortho:
        textes.append(["Priorité orthoptères (NEM à COR)", REFERENCE_ORTHOPTERES])

    return {"groupe": groupe, "source": str(chemin), "cible": str(cible), "cellules": cellules,
            "statuts": statuts, "tables": tables, "saisie": saisie,
            "ajouts": [{"feuille": FEUILLE_TEXTES, "colonnes": 2, "colonne_date": 0,
                        "lignes": textes},
                       {"feuille": FEUILLE_SUIVI, "colonnes": 3, "colonne_date": 1,
                        "lignes": [[date_iso, PERSONNE, t] for t in suivi]}],
            "suivi": suivi, "n_dz": n_dz}


# --------------------------------------------------------------------- main

def production() -> Path | None:
    import publier
    destination = publier.destination_memorisee()
    return destination / "classeurs" if destination else None


#: Le journal des étapes d'Excel, hors de OneDrive : la synchronisation le
#: verrouillait, et les lignes se perdaient.
JOURNAL = chemins.racine_donnees() / "sorties" / "enrichir_classeurs.log"


def appliquer(plans_json: Path) -> int:
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    JOURNAL.unlink(missing_ok=True)
    script = Path(__file__).resolve().parent / "excel_appliquer.ps1"
    resultat = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
         "-Plans", str(plans_json), "-Journal", str(JOURNAL)],
        capture_output=True)
    print(resultat.stdout.decode("utf-8", errors="replace").strip())
    if resultat.stderr:
        print(resultat.stderr.decode("cp1252", errors="replace").strip())
    return resultat.returncode


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--classeurs", type=Path, default=production(),
                        help="les classeurs de référence (par défaut, ceux de production)")
    # Ni sous %LOCALAPPDATA% — Excel piloté par automatisation n'y voit aucun
    # fichier sur ce poste —, ni sous OneDrive — Office y enregistre chaque
    # modification à mesure, et se fige à la fermeture en attendant le
    # téléversement. Un dossier local, à la racine du profil.
    parser.add_argument("--travail", type=Path,
                        default=Path.home() / "prediag-enviro-travail" / f"classeurs_{AUJOURD_HUI}")
    parser.add_argument("--installer", action="store_true",
                        help="sauvegarder les originaux et installer les copies vérifiées")
    args = parser.parse_args()

    if args.installer:
        return installer(args.classeurs, args.travail)

    contexte = service.charger_contexte(RACINE)
    listes = determinantes.depuis_bdc(chemins.referentiels() / "BDC.zip")
    if EXPORT_NA.exists():
        determinantes.ajouter_export_inpn(listes, EXPORT_NA, "Nouvelle-Aquitaine",
                                          contexte.index, REFERENCE_NA)
    citation_bdc = next(c for c in contexte.citations if c.startswith("BDC-Statuts"))

    copies = args.travail / "classeurs"
    # Les copies sont écrasées, pas le dossier supprimé : OneDrive le retient
    # le temps de synchroniser.
    copies.mkdir(parents=True, exist_ok=True)
    plans = []
    for chemin in sorted(args.classeurs.glob("B-Statuts*.xlsx")):
        groupe = next((g for g, m in service.MOTIFS.items() if chemin.match(m)), None)
        if groupe is None:
            continue
        cible = copies / chemin.name
        # Octet par octet : copy2 recopierait les attributs OneDrive de
        # l'original, et Excel n'ouvrait plus la copie.
        shutil.copyfile(chemin, cible)
        classeur = classeurs.lire(chemin, groupe)
        dispo = implantation.disposition(chemin)
        zdet = colonnes_zdet(classeur, dispo, listes, contexte.index)
        ortho = (colonnes_orthopteres(classeur, ORTHOPTERES)
                 if groupe == "insectes" and ORTHOPTERES.exists() else None)
        p = plan(groupe, chemin, cible, classeur, dispo, zdet, ortho, citation_bdc)
        plans.append(p)
        print(f"   {groupe:<18} {p['n_dz']:>2} colonnes DZ"
              + (" + 8 orthoptères" if ortho else "")
              + f" en {implantation.colonne(dispo.premiere_libre)} · "
              f"{len(zdet['modifiees'])} cases DZ existantes · "
              f"{len(p['cellules']) - len(zdet['modifiees'])} corrections de saisie")
    plans_json = args.travail / "plans.json"
    plans_json.write_text(json.dumps(plans, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nExcel applique les plans aux copies de {copies}…")
    code = appliquer(plans_json)
    print("Aucun classeur de référence n'a été modifié." if code == 0 else
          f"{code} classeur(s) en échec — rien n'est installé.")
    return code


def installer(source: Path, travail: Path) -> int:
    """Sauvegarde les originaux, puis met les copies vérifiées à leur place."""
    copies = sorted((travail / "classeurs").glob("B-Statuts*.xlsx"))
    if not copies:
        print("Aucune copie à installer : lancer d'abord sans --installer.")
        return 1
    sauvegarde = chemins.racine_donnees() / "sauvegardes" / f"classeurs_{AUJOURD_HUI}"
    sauvegarde.mkdir(parents=True, exist_ok=True)
    destinations = [source, chemins.racine_application() / "classeurs"]
    for copie in copies:
        original = source / copie.name
        if not (sauvegarde / copie.name).exists():
            shutil.copyfile(original, sauvegarde / copie.name)
        for dossier in destinations:
            shutil.copyfile(copie, dossier / copie.name)
    print(f"Originaux sauvegardés dans {sauvegarde}")
    print("Installés dans : " + " · ".join(str(d) for d in destinations))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
