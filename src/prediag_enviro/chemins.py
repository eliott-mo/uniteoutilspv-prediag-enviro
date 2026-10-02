"""Où vont les fichiers : ce qui se partage et ce qui reste sur la machine.

L'outil est prévu pour vivre sur SharePoint, d'où n'importe qui de l'équipe le
lance. Mais tout ne peut pas y vivre, et le départage n'est pas une question de
goût : OneDrive synchronise ce qu'il voit.

**Sur SharePoint — ce qui se partage et change rarement**

* le code ;
* `classeurs/`, les six classeurs B-Statuts. C'est tout l'intérêt : un maître
  unique, celui que la responsable environnement tient à jour, et non six
  copies divergentes sur six postes.

**Sur la machine — ce qui est lourd, dérivé ou écrit en cours d'exécution**

* `referentiels/` : 550 Mo d'archives INPN et autant d'extraction. Les mettre
  sous OneDrive ferait télécharger un gigaoctet à chaque personne, puis le
  resynchroniser à la moindre modification.
* l'environnement Python : 300 Mo avec geopandas, et propre à la machine.
* `sorties/` et `memoire/` : écrits pendant l'exécution. OneDrive qui
  synchronise un fichier pendant qu'on l'écrit produit des « copies en
  conflit », et la mémoire des arbitrages est justement le fichier qu'il ne
  faut pas voir se dédoubler.

Le dossier local suit la convention Windows : `%LOCALAPPDATA%`, que OneDrive ne
synchronise pas. `PREDIAG_ENVIRO_DONNEES` permet de le déplacer — par exemple
vers un disque plus grand, ou vers un dossier commun sur un poste partagé.
"""
from __future__ import annotations

import os
from pathlib import Path

#: Nom du dossier de données, sous %LOCALAPPDATA% par défaut.
DOSSIER = "prediag-enviro"


def racine_application() -> Path:
    """Dossier du code — celui qui peut vivre sur SharePoint."""
    return Path(__file__).resolve().parents[2]


def racine_donnees() -> Path:
    """Dossier local des données lourdes et des fichiers écrits.

    Jamais sous OneDrive, sauf si quelqu'un force `PREDIAG_ENVIRO_DONNEES` —
    auquel cas c'est un choix assumé, pas un effet de bord.
    """
    impose = os.environ.get("PREDIAG_ENVIRO_DONNEES")
    if impose:
        return Path(impose).expanduser()

    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME")
    if base:
        return Path(base) / DOSSIER
    return Path.home() / f".{DOSSIER}"


def _sous_onedrive(chemin: Path) -> bool:
    """Le chemin est-il dans un dossier synchronisé ?

    Détection par le nom : OneDrive crée des dossiers « OneDrive », « OneDrive
    - <Organisation> » ou « SharePoint ». C'est grossier, mais ça suffit pour
    avertir, et un avertissement faux coûte moins cher qu'un gigaoctet
    resynchronisé en silence.
    """
    parties = [p.lower() for p in chemin.parts]
    return any(p.startswith("onedrive") or "sharepoint" in p for p in parties)


def referentiels() -> Path:
    return racine_donnees() / "referentiels"


def sorties() -> Path:
    return racine_donnees() / "sorties"


def memoire() -> Path:
    return racine_donnees() / "memoire"


def classeurs() -> Path:
    """Les classeurs B-Statuts, à côté du code : c'est un actif partagé.

    Un dossier local prend le pas s'il existe, pour qui veut travailler sur une
    copie sans toucher au maître.
    """
    local = racine_donnees() / "classeurs"
    if local.exists() and any(local.glob("*.xlsx")):
        return local
    return racine_application() / "classeurs"


def preparer() -> dict[str, Path]:
    """Crée les dossiers locaux et renvoie la carte des emplacements."""
    emplacements = {
        "application": racine_application(),
        "donnees": racine_donnees(),
        "referentiels": referentiels(),
        "sorties": sorties(),
        "memoire": memoire(),
        "classeurs": classeurs(),
    }
    for cle in ("referentiels", "sorties", "memoire"):
        emplacements[cle].mkdir(parents=True, exist_ok=True)
    return emplacements


def avertissements() -> list[str]:
    """Signale les configurations qui vont mal se passer."""
    messages = []
    donnees = racine_donnees()
    if _sous_onedrive(donnees):
        messages.append(
            f"Le dossier de données est sous OneDrive ({donnees}). Un "
            "gigaoctet de référentiels y serait synchronisé pour chaque "
            "personne, et les fichiers écrits en cours d'exécution risquent "
            "des copies en conflit. Définir PREDIAG_ENVIRO_DONNEES vers un "
            "dossier local."
        )
    return messages
