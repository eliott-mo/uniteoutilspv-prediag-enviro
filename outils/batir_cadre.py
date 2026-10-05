#!/usr/bin/env python
"""Extrait la partie générale du prédiagnostic dans un document à part.

« Cadre général de l'étude » et « Méthodologies » sont identiques d'un
prédiagnostic à l'autre : définition des ZNIEFF et des zonages Natura 2000,
plans nationaux d'actions, article L. 411-1, outils de bioévaluation, grilles
de détermination des enjeux. Quatre-vingts paragraphes et sept tableaux de
cadrage réglementaire.

Ce contenu **n'a pas sa place dans le code** : il évolue avec la
réglementation et avec les habitudes de l'équipe, et la personne qui le fera
évoluer travaille dans Word, pas dans Python. Il vit donc dans
`modele/cadre_general.docx`, que le générateur insère tel quel en tête du
rapport et que l'on édite directement quand il faut le mettre à jour.

    python outils/batir_cadre.py                      # d'après l'externe
    python outils/batir_cadre.py "autre_source.docx"

Deux parties sont écartées à l'extraction :

* **la définition des aires d'étude** — le générateur la produit avec les
  rayons réellement retenus pour le projet, et sa carte ;
* **les numéros de légende figés**. Le document source mêle des légendes à
  champ `SEQ` et des légendes sans numéro du tout ; on les normalise toutes
  au format de l'outil, pour que la numérotation du rapport soit continue et
  que les sommaires des tableaux et des cartes les reprennent.
"""
from __future__ import annotations

import re
import sys
from copy import deepcopy
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from docx import Document
from docx.oxml.ns import qn

RACINE = Path(__file__).resolve().parent.parent

SOURCE = Path(
    "C:/Users/eliott.moreau/OneDrive - Unite/330_DEV_PV_Autres/01_Outils"
    "/07. Diag Environnemental/02_Etudes_enviro/01_Prédiagnostic"
    "/Exemple_prédiag_Externe.docx"
)
CIBLE = RACINE / "modele" / "cadre_general.docx"
MODELE = RACINE / "modele" / "prediag_modele.docx"

#: Parties de premier niveau à reprendre, dans l'ordre.
PARTIES = ("Cadre général de l’étude", "Méthodologies")

#: Sous-parties dont le **corps** est écarté : le générateur les produit avec
#: les valeurs du projet. Leur intertitre reste, et sert de repère : le
#: générateur insère son contenu juste après, ce qui préserve l'ordre de la
#: table des matières sans découper le cadre en plusieurs fichiers.
REPERES = ("Définition des aires d’étude",)

_LEGENDE = re.compile(r"^\s*(Tableau|Carte|Figure)\s*\d*\s*[:：]\s*(.*)$")


def _style(paragraphe) -> str:
    pStyle = paragraphe.find(qn("w:pPr"))
    if pStyle is None:
        return ""
    noeud = pStyle.find(qn("w:pStyle"))
    return noeud.get(qn("w:val")) if noeud is not None else ""


def _texte(element) -> str:
    return "".join(n.text or "" for n in element.iter(qn("w:t")))


def extraire(source: Path) -> tuple[list, dict]:
    """Éléments de corps à reprendre, et compte rendu."""
    document = Document(str(source))
    # Les identifiants de style sont ceux du document, pas les noms affichés.
    styles = {s.style_id: s.name for s in document.styles}

    retenus: list = []
    compte = {"paragraphes": 0, "tableaux": 0, "legendes": 0, "ecartes": 0,
              "reperes": 0}
    dans_partie = False
    dans_ecartee = False

    for element in document.element.body.iterchildren():
        balise = element.tag.split("}")[-1]
        if balise == "tbl":
            if dans_partie and not dans_ecartee:
                retenus.append(deepcopy(element))
                compte["tableaux"] += 1
            elif dans_ecartee:
                compte["ecartes"] += 1
            continue
        if balise != "p":
            continue

        nom_style = styles.get(_style(element), "")
        contenu = _texte(element).strip()

        if nom_style == "Titre partie":
            dans_partie = contenu in PARTIES
            dans_ecartee = False
            if dans_partie:
                # Les titres de partie restent dans le cadre : le générateur
                # n'a alors pas à deviner où commence « Méthodologies ».
                retenus.append(deepcopy(element))
                compte["paragraphes"] += 1
            continue
        if not dans_partie:
            continue
        if nom_style == "Style1":
            dans_ecartee = contenu in REPERES
            if dans_ecartee:
                retenus.append(deepcopy(element))   # l'intertitre fait repère
                compte["paragraphes"] += 1
                compte["reperes"] += 1
                continue
        if dans_ecartee:
            compte["ecartes"] += 1
            continue
        # Les images restantes seraient des relations à recopier : il n'y en a
        # qu'une dans la source, et elle est dans la partie écartée.
        if element.find(".//" + qn("w:drawing")) is not None:
            compte["ecartes"] += 1
            continue

        retenus.append(deepcopy(element))
        compte["paragraphes"] += 1
        if nom_style == "Lgende" or _LEGENDE.match(contenu):
            compte["legendes"] += 1

    return retenus, compte


def ecrire(elements: list, cible: Path, modele: Path) -> None:
    """Dépose les éléments dans un document neuf, bâti sur le modèle."""
    document = Document(str(modele))
    corps = document.element.body
    for enfant in list(corps):
        if not enfant.tag.endswith("}sectPr"):
            corps.remove(enfant)
    sectPr = corps.find(qn("w:sectPr"))
    for element in elements:
        corps.insert(list(corps).index(sectPr), element)

    proprietes = document.core_properties
    proprietes.author = "UNITe"
    proprietes.last_modified_by = "UNITe"
    proprietes.title = "Prédiagnostic — partie générale"
    cible.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(cible))


def main() -> int:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else SOURCE
    if not source.exists():
        print(f"document source introuvable : {source}")
        return 1
    if not MODELE.exists():
        print(f"modèle introuvable : {MODELE} — lancer d'abord batir_modele.py")
        return 1
    print(f"d'après : {source.name}")

    try:
        elements, compte = extraire(source)
    except Exception as erreur:  # noqa: BLE001
        print(f"   lecture impossible : {type(erreur).__name__}")
        print("   Le fichier est peut-être ouvert dans Word, ou en cours de "
              "synchronisation OneDrive.")
        return 1

    if not elements:
        print("   aucun contenu repris — les intitulés de partie ont-ils "
              "changé ?")
        return 1

    ecrire(elements, CIBLE, MODELE)
    print(f"écrit : {CIBLE.relative_to(RACINE)} "
          f"({CIBLE.stat().st_size / 1024:.0f} Ko)")
    print(f"   {compte['paragraphes']} paragraphes · {compte['tableaux']} "
          f"tableaux · {compte['legendes']} légendes")
    print(f"   {compte['ecartes']} élément(s) écarté(s) · "
          f"{compte['reperes']} repère(s) conservé(s) : {', '.join(REPERES)}")

    relu = Document(str(CIBLE))
    titres = [p.text.strip() for p in relu.paragraphs
              if p.style is not None and p.style.name in ("Titre partie",
                                                          "Style1", "Style2")
              and p.text.strip()]
    print("\n   structure reprise :")
    for t in titres:
        print(f"      {t}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
