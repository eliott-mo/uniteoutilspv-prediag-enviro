#!/usr/bin/env python
"""Colle le bandeau gris UNITe au bas de la page et l'élargit pour le paysage.

Le bandeau — barre grise avec les trois pictogrammes à droite — est une image
ancrée, posée tantôt dans un pied de page, tantôt dans un en-tête selon les
documents. Deux défauts se rencontrent, et ils ont la même origine : **son
ancrage est relatif au paragraphe**, donc sa position dépend de ce qui
l'entoure.

* dans le prédiagnostic interne, deux paragraphes vides suivaient le sien et le
  repoussaient d'un centimètre vers le haut : une bande blanche subsistait sous
  le gris ;
* dans le prédiagnostic externe, il est dans l'en-tête avec un décalage de
  9 cm vers le bas, et traverse donc le texte au milieu de chaque page.

Une première version supprimait les paragraphes vides. C'était le mauvais
levier : on déplace le bandeau indirectement, sans contrôler où il arrive — et
de fait il est passé trop bas. On ancre désormais le bandeau **à la page**,
aligné en bas : sa position ne dépend plus de rien.

L'élargissement répond à l'autre besoin. L'image mesure 21,76 cm, ce qui couvre
une page A4 portrait mais laisse huit centimètres de blanc à gauche en paysage.
Les colonnes de gauche de l'image sont strictement identiques — barre grise en
bas, blanc en haut —, donc on la rallonge en répliquant la première colonne,
sans jamais toucher aux pictogrammes. Une seule image sert alors aux deux
orientations : en portrait l'excédent déborde hors page à gauche et se trouve
rogné, les pictogrammes restant collés à droite.

    python outils/bandeau.py "document.docx"              # essai
    python outils/bandeau.py "document.docx" --appliquer

L'archive est recopiée entrée par entrée : seules la partie qui porte l'ancrage
et l'image du bandeau sont remplacées.
"""
from __future__ import annotations

import io
import re
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

EMU_PAR_CM = 360000

#: Largeur visée. A4 paysage fait 29,7 cm ; on déborde un peu pour qu'aucun
#: arrondi ne laisse un liseré blanc au bord.
LARGEUR_CM = 30.6

#: En deçà, l'image ancrée n'est pas le bandeau mais un logo ou un picto.
LARGEUR_MINIMALE_EMU = 5_000_000


def _parties_avec_bandeau(archive: zipfile.ZipFile) -> dict[str, str]:
    """Parties d'en-tête ou de pied qui portent une image ancrée large."""
    trouvees = {}
    for nom in archive.namelist():
        if not re.match(r"word/(header|footer)\d*\.xml$", nom):
            continue
        xml = archive.read(nom).decode("utf-8")
        for ancre in re.findall(r"<wp:anchor.*?</wp:anchor>", xml, re.S):
            etendue = re.search(r'<wp:extent cx="(\d+)" cy="(\d+)"/>', ancre)
            if etendue and int(etendue.group(1)) >= LARGEUR_MINIMALE_EMU:
                trouvees[nom] = ancre
                break
    return trouvees


def _image_du_bandeau(archive: zipfile.ZipFile, partie: str,
                      ancre: str) -> str | None:
    embarque = re.search(r'r:embed="(\w+)"', ancre)
    if not embarque:
        return None
    rels = f"word/_rels/{Path(partie).name}.rels"
    if rels not in archive.namelist():
        return None
    texte = archive.read(rels).decode("utf-8")
    cible = re.search(rf'Id="{embarque.group(1)}"[^>]*Target="media/([^"]+)"',
                      texte)
    return "word/media/" + cible.group(1) if cible else None


def _elargir(donnees: bytes, facteur: float) -> tuple[bytes, int, int]:
    """Rallonge l'image vers la gauche en répliquant sa première colonne.

    Renvoie (image, largeur d'origine, nouvelle largeur) en pixels.
    """
    from PIL import Image

    image = Image.open(io.BytesIO(donnees))
    largeur, hauteur = image.size
    nouvelle = int(round(largeur * facteur))
    if nouvelle <= largeur:
        return donnees, largeur, largeur

    colonne = image.crop((0, 0, 1, hauteur))
    elargie = Image.new(image.mode, (nouvelle, hauteur))
    for x in range(nouvelle - largeur):
        elargie.paste(colonne, (x, 0))
    elargie.paste(image, (nouvelle - largeur, 0))

    sortie = io.BytesIO()
    elargie.save(sortie, format=image.format or "PNG")
    return sortie.getvalue(), largeur, nouvelle


def _colonne_uniforme(donnees: bytes) -> int:
    """Nombre de colonnes identiques à la première, depuis la gauche."""
    from PIL import Image

    image = Image.open(io.BytesIO(donnees)).convert("RGB")
    largeur, hauteur = image.size
    premiere = [image.getpixel((0, y)) for y in range(hauteur)]
    for x in range(largeur):
        if [image.getpixel((x, y)) for y in range(hauteur)] != premiere:
            return x
    return largeur


def _recaler(ancre: str, cx: int) -> str:
    """Ancre le bandeau au bas de la page et lui donne sa nouvelle largeur."""
    ancre = re.sub(
        r"<wp:positionV relativeFrom=\"\w+\">.*?</wp:positionV>",
        '<wp:positionV relativeFrom="page"><wp:align>bottom</wp:align>'
        "</wp:positionV>", ancre, count=1, flags=re.S)
    ancre = re.sub(
        r"<wp:positionH relativeFrom=\"\w+\">.*?</wp:positionH>",
        '<wp:positionH relativeFrom="page"><wp:align>right</wp:align>'
        "</wp:positionH>", ancre, count=1, flags=re.S)
    # La largeur figure deux fois : dans le cadre du dessin et dans la forme.
    ancre = re.sub(r'(<wp:extent cx=")\d+(")', rf"\g<1>{cx}\g<2>", ancre)
    ancre = re.sub(r'(<a:ext cx=")\d+(")', rf"\g<1>{cx}\g<2>", ancre)
    return ancre


def corriger(chemin: Path, appliquer: bool = False,
             largeur_cm: float = LARGEUR_CM) -> dict:
    """Corrige le bandeau. Renvoie un compte rendu."""
    rapport: dict = {"parties": {}, "modifie": False}
    with zipfile.ZipFile(chemin) as archive:
        trouvees = _parties_avec_bandeau(archive)
        if not trouvees:
            return rapport
        remplacements: dict[str, bytes] = {}
        for partie, ancre in trouvees.items():
            etendue = re.search(r'<wp:extent cx="(\d+)" cy="(\d+)"/>', ancre)
            cx, cy = int(etendue.group(1)), int(etendue.group(2))
            media = _image_du_bandeau(archive, partie, ancre)
            pv = re.search(r'<wp:positionV relativeFrom="(\w+)"', ancre)
            facteur = (largeur_cm * EMU_PAR_CM) / cx
            detail = {
                "largeur_cm": cx / EMU_PAR_CM,
                "hauteur_cm": cy / EMU_PAR_CM,
                "ancrage_vertical": pv.group(1) if pv else "?",
                "media": media,
                "facteur": facteur,
            }
            if media:
                donnees = archive.read(media)
                detail["colonnes_uniformes"] = _colonne_uniforme(donnees)
                elargie, avant, apres = _elargir(donnees, facteur)
                detail["pixels"] = (avant, apres)
                remplacements[media] = elargie
            cx_nouveau = int(round(cx * facteur))
            detail["largeur_cible_cm"] = cx_nouveau / EMU_PAR_CM
            remplacements[partie] = archive.read(partie).decode("utf-8").replace(
                ancre, _recaler(ancre, cx_nouveau), 1).encode("utf-8")
            rapport["parties"][partie] = detail

    if not appliquer:
        return rapport

    sauvegarde = chemin.with_name(
        f"{chemin.stem}.avant-bandeau-{datetime.now():%Y%m%d-%H%M%S}"
        f"{chemin.suffix}")
    shutil.copy2(chemin, sauvegarde)
    rapport["sauvegarde"] = sauvegarde.name

    temporaire = chemin.with_suffix(chemin.suffix + ".tmp")
    with zipfile.ZipFile(chemin) as source:
        with zipfile.ZipFile(temporaire, "w", zipfile.ZIP_DEFLATED) as cible:
            for entree in source.infolist():
                donnees = remplacements.get(entree.filename,
                                            source.read(entree.filename))
                cible.writestr(entree, donnees)
    temporaire.replace(chemin)
    rapport["modifie"] = True
    return rapport


def imprimer(chemin: Path, rapport: dict) -> None:
    print(f"\n{chemin.name}")
    if not rapport["parties"]:
        print("   aucun bandeau trouvé dans les en-têtes ni les pieds")
        return
    for partie, d in rapport["parties"].items():
        print(f"   {partie}")
        print(f"      bandeau : {d['largeur_cm']:.2f} × {d['hauteur_cm']:.2f} cm"
              f" · ancrage vertical « {d['ancrage_vertical']} »")
        if d.get("pixels"):
            print(f"      image   : {d['media']} · {d['pixels'][0]} → "
                  f"{d['pixels'][1]} px ({d['colonnes_uniformes']} colonnes "
                  "uniformes à gauche)")
        print(f"      après   : {d['largeur_cible_cm']:.2f} cm · ancré "
              "« page / bas / droite »")
    if rapport.get("sauvegarde"):
        print(f"   sauvegarde : {rapport['sauvegarde']}")
    print("   document réécrit" if rapport["modifie"]
          else "   (essai — rien n'est écrit ; relancer avec --appliquer)")


def main() -> int:
    arguments = [a for a in sys.argv[1:] if not a.startswith("--")]
    appliquer = "--appliquer" in sys.argv
    if not arguments:
        print(__doc__)
        return 1
    for brut in arguments:
        chemin = Path(brut)
        if not chemin.exists():
            print(f"\n{brut} : introuvable")
            return 1
        try:
            zipfile.ZipFile(chemin).namelist()
        except Exception:  # noqa: BLE001
            print(f"\n{chemin.name} : illisible — probablement ouvert dans "
                  "Word, ou en cours de synchronisation OneDrive.")
            return 1
        imprimer(chemin, corriger(chemin, appliquer))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
