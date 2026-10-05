#!/usr/bin/env python
"""Retire d'un .docx les médias que plus rien ne référence.

Vider le corps d'un document avec python-docx ne supprime pas ses images :
elles restent dans le paquet, avec leurs relations, parce que la bibliothèque
conserve toutes les parties qu'elle a lues. Un modèle tiré d'un livrable réel
traîne donc ses cartes et ses photographies — 8,3 Mo sur 8,4 pour le
prédiagnostic externe — que chaque document produit recopierait ensuite.

On ne garde que les médias qu'une partie cite effectivement, par un
`r:embed`, `r:id` ou `r:link` présent dans son XML **et** déclaré dans ses
relations. Les relations devenues orphelines sont retirées en même temps :
une relation qui pointe vers une partie absente fait refuser le document à
l'ouverture.

    python outils/paquet.py "document.docx"              # essai
    python outils/paquet.py "document.docx" --appliquer
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass


def medias_utilises(archive: zipfile.ZipFile) -> set[str]:
    """Médias cités par au moins une partie du document."""
    utilises: set[str] = set()
    for partie in archive.namelist():
        if not partie.endswith(".xml") or "/_rels/" in partie:
            continue
        xml = archive.read(partie).decode("utf-8", "replace")
        references = set(re.findall(r'r:(?:embed|id|link)="(\w+)"', xml))
        if not references:
            continue
        dossier = "/".join(partie.split("/")[:-1])
        rels = f"{dossier}/_rels/{partie.split('/')[-1]}.rels"
        if rels not in archive.namelist():
            continue
        texte = archive.read(rels).decode("utf-8", "replace")
        for rid, cible in re.findall(r'Id="(\w+)"[^>]*Target="([^"]+)"', texte):
            if rid in references and "media/" in cible:
                utilises.add("word/media/" + cible.split("media/")[-1])
    return utilises


def purger(chemin: Path, appliquer: bool = False) -> dict:
    with zipfile.ZipFile(chemin) as archive:
        medias = [n for n in archive.namelist() if n.startswith("word/media/")]
        gardes = medias_utilises(archive)
        retires = [n for n in medias if n not in gardes]
        poids = sum(archive.getinfo(n).file_size for n in retires)
        rapport = {
            "medias": len(medias), "retires": len(retires),
            "octets": poids, "appliquer": appliquer,
        }
        if not appliquer or not retires:
            return rapport

        noms_retires = {n.split("media/")[-1] for n in retires}
        temporaire = chemin.with_suffix(chemin.suffix + ".tmp")
        with zipfile.ZipFile(temporaire, "w", zipfile.ZIP_DEFLATED) as cible:
            for entree in archive.infolist():
                if entree.filename in retires:
                    continue
                donnees = archive.read(entree.filename)
                if entree.filename.endswith(".rels"):
                    texte = donnees.decode("utf-8")
                    for nom in noms_retires:
                        # Une relation orpheline fait refuser le document.
                        texte = re.sub(
                            rf'<Relationship[^>]*Target="[^"]*media/{re.escape(nom)}"[^>]*/>',
                            "", texte)
                    donnees = texte.encode("utf-8")
                cible.writestr(entree, donnees)
    temporaire.replace(chemin)
    return rapport


def imprimer(chemin: Path, rapport: dict) -> None:
    if not rapport["retires"]:
        print(f"   médias : {rapport['medias']} · aucun à retirer")
        return
    verbe = "retirés" if rapport["appliquer"] else "à retirer"
    print(f"   médias : {rapport['medias']} dont {rapport['retires']} "
          f"{verbe} ({rapport['octets'] / 1048576:.1f} Mo)")


def main() -> int:
    arguments = [a for a in sys.argv[1:] if not a.startswith("--")]
    appliquer = "--appliquer" in sys.argv
    if not arguments:
        print(__doc__)
        return 1
    for brut in arguments:
        chemin = Path(brut)
        if not chemin.exists():
            print(f"{brut} : introuvable")
            return 1
        print(f"\n{chemin.name}")
        imprimer(chemin, purger(chemin, appliquer))
        if appliquer:
            from docx import Document
            Document(str(chemin))          # refuse d'ouvrir si une relation manque
            print(f"   relu sans erreur · "
                  f"{chemin.stat().st_size / 1024:.0f} Ko")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
