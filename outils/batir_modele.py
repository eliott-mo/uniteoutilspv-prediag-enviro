#!/usr/bin/env python
"""Fabrique le modèle de prédiagnostic à partir d'un document de référence.

On garde le mobilier — styles, en-tête, pied de page avec pagination, marges —
et on vide tout le reste. Le document de départ est un livrable réel, rédigé
par une personne nommée pour une commune nommée : la vérification de non-fuite
n'est pas une formalité, et ce script l'imprime à chaque exécution.

    python outils/batir_modele.py                      # d'après le doc interne
    python outils/batir_modele.py "autre_modele.docx"  # d'après un autre

À relancer quand l'équipe fait évoluer sa charte : le modèle ne s'édite pas à
la main, il se refabrique.

Deux pièges, rencontrés et corrigés, qui reviendront si on réécrit ce script :

* la `sectPr` de fin de corps est celle de la **dernière** section du document
  source. Dans un prédiagnostic, c'est une carte — donc une page en paysage.
  Un modèle naïf sortait toutes ses pages couchées.
* seule la **première** section porte les références vers l'en-tête et le pied
  de page. Garder la dernière donnait un modèle où `header1.xml` et
  `footer1.xml` étaient bien dans le paquet mais que plus aucune section
  n'appelait : ni logo, ni pagination, sans le moindre message d'erreur.
"""
from __future__ import annotations

import re
import sys
import zipfile
from copy import deepcopy
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.shared import Twips

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

#: Document dont on reprend le mobilier. Il doit être fermé dans Word :
#: OneDrive et Word posent un verrou exclusif, et la lecture échoue alors sur
#: un `PermissionError` peu parlant.
SOURCE = Path(
    "C:/Users/eliott.moreau/OneDrive - Unite/330_DEV_PV_Autres/01_Outils"
    "/07. Diag Environnemental/02_Etudes_enviro/01_Prédiagnostic"
    "/Exemple_prédiag_Externe.docx"
)
CIBLE = RACINE / "modele" / "prediag_modele.docx"

#: Termes du livrable d'origine qui ne doivent pas subsister dans le modèle.
INTERDITS = ["elbeuf", "saint-pierre", "nardi", "seine-maritime", "normandie",
             "aubenas", "chapelle", "ardèche", "ardeche", "bonelli"]

#: Styles sans lesquels le prédiagnostic sortirait mal mis en forme.
ATTENDUS = ["Titre partie", "Style1", "Style2", "Titre colonne",
            "Corps de texte - Unite", "Table Grid", "Title", "List Paragraph",
            "Caption", "TOC Heading", "table of figures"]


def vider(document):
    """Vide le corps en gardant la mise en page de la PREMIÈRE section."""
    reference = deepcopy(document.sections[0]._sectPr)
    corps = document.element.body
    for enfant in list(corps):
        corps.remove(enfant)
    corps.append(reference)
    return document


def redresser(document) -> None:
    """A4 portrait et marges du document de référence (1417 twips = 2,5 cm)."""
    section = document.sections[-1]
    if section.page_width > section.page_height:
        section.orientation = WD_ORIENT.PORTRAIT
    section.page_width, section.page_height = Twips(11906), Twips(16838)
    for cote in ("left", "right", "top", "bottom"):
        setattr(section, f"{cote}_margin", Twips(1417))
    section.header_distance, section.footer_distance = Twips(708), Twips(418)


def anonymiser(document) -> None:
    """Retire les propriétés du livrable d'origine."""
    proprietes = document.core_properties
    proprietes.author = "UNITe"
    proprietes.last_modified_by = "UNITe"
    proprietes.title = "Prédiagnostic écologique"
    for champ in ("subject", "comments", "keywords", "category"):
        setattr(proprietes, champ, "")
    proprietes.revision = 1


def verifier(cible: Path) -> int:
    """Imprime le contrôle du modèle. Renvoie le nombre d'anomalies."""
    anomalies = 0
    paquet = zipfile.ZipFile(cible)
    corps = paquet.read("word/document.xml").decode("utf-8")

    mots = [t for t in re.findall(r"<w:t[^>]*>([^<]*)</w:t>", corps) if t.strip()]
    print(f"\ntexte restant dans le corps : {mots or 'aucun'}")
    anomalies += len(mots)

    print("\nrecherche des termes du livrable d'origine :")
    trouves = []
    for nom in paquet.namelist():
        if not nom.endswith(".xml"):
            continue
        brut = paquet.read(nom).decode("utf-8", "replace").lower()
        trouves += [f"« {t} » dans {nom}" for t in INTERDITS if t in brut]
    for ligne in trouves:
        print(f"   ⚠ {ligne}")
    print("   aucun" if not trouves else f"   {len(trouves)} À TRAITER")
    anomalies += len(trouves)

    refs = re.findall(r"<w:(headerReference|footerReference) w:type=\"(\w+)\"", corps)
    print(f"\nréférences en-tête / pied : {refs or 'AUCUNE'}")
    if len(refs) < 2:
        anomalies += 1

    document = Document(str(cible))
    section = document.sections[0]
    paysage = section.page_width > section.page_height
    print(f"mise en page : {section.page_width.twips} × {section.page_height.twips}"
          f" twips · {'PAYSAGE (anormal)' if paysage else 'portrait'}")
    anomalies += int(paysage)

    styles = {s.name for s in document.styles}
    print("\nstyles attendus :")
    for nom in ATTENDUS:
        present = nom in styles
        print(f"   {'OK      ' if present else 'MANQUANT'}  {nom}")
        anomalies += int(not present)
    return anomalies


def main() -> int:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else SOURCE
    if not source.exists():
        print(f"document de référence introuvable : {source}")
        return 1
    print(f"d'après : {source.name}")

    try:
        document = vider(Document(str(source)))
    except Exception as erreur:  # noqa: BLE001
        # python-docx rend un « Package not found » quand le fichier existe
        # mais ne s'ouvre pas : c'est le cas d'un document verrouillé par Word
        # ou en cours de synchronisation OneDrive. Le message d'origine envoie
        # chercher un fichier absent, qui est pourtant là.
        print(f"   lecture impossible : {type(erreur).__name__}")
        print("   Le fichier est présent mais ne s'ouvre pas : il est "
              "probablement ouvert dans Word,")
        print("   ou OneDrive est en train de le synchroniser. Fermez-le et "
              "relancez.")
        return 1
    redresser(document)
    anonymiser(document)
    CIBLE.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(CIBLE))
    print(f"modèle écrit : {CIBLE.relative_to(RACINE)} "
          f"({CIBLE.stat().st_size / 1024:.0f} Ko)")

    # Le bandeau gris est ancré au paragraphe dans les documents de l'équipe,
    # donc sa position dépend de ce qui l'entoure : dans l'externe il traverse
    # le texte à mi-page. On le recale au bas de la page et on l'élargit pour
    # qu'il couvre aussi les pages en paysage.
    from bandeau import corriger, imprimer  # noqa: PLC0415
    imprimer(CIBLE, corriger(CIBLE, appliquer=True))

    anomalies = verifier(CIBLE)
    print(f"\n{'MODÈLE CONFORME' if not anomalies else f'{anomalies} ANOMALIE(S)'}")
    return 0 if not anomalies else 1


if __name__ == "__main__":
    raise SystemExit(main())
