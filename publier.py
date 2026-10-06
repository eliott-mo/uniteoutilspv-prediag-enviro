#!/usr/bin/env python
"""Publie l'outil depuis le dossier de travail vers le dossier de production.

    python publier.py --vers "<dossier Outils>"
    python publier.py --vers "<dossier Outils>" --avec-donnees   # 1re fois
    python publier.py --vers "<dossier Outils>" --essai          # sans rien écrire

Le dossier de travail est versionné et c'est là qu'on développe. Le dossier de
production est celui où Marie et les chefs de projet cliquent. Publier, c'est
pousser l'un vers l'autre — quand on le décide, pas à chaque enregistrement.

**La publication copie le code, jamais les données.** `classeurs/` contient les
six classeurs que la responsable environnement tient à jour ; `extraits/`
contient 36 minutes de construction et 538 Mo. Les écraser depuis un dossier de
développement effacerait le travail de quelqu'un d'autre. Ils vivent en
production et n'en bougent plus — sauf `--avec-donnees`, pour la première mise
en place, et seulement vers un dossier qui ne les a pas encore.

Chaque publication dépose un `VERSION.txt` : sans lui, personne ne peut
répondre à « tu es sur quelle version ? » quand un chef de projet appelle.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

RACINE = Path(__file__).resolve().parent

#: Dernier dossier de production utilisé. Fichier local au poste de
#: développement, hors dépôt : le chemin dépend de la machine, et le retaper
#: à chaque publication est le genre de friction qui finit par faire publier
#: au mauvais endroit.
MEMO = RACINE / ".destination-publication"

#: Ce qui part en production. Tout le reste est soit du développement, soit
#: des données qui appartiennent à la production.
CODE = [
    "app.py",
    "run_veille.py",
    "publier.py",
    "_LANCER Prediag.bat",
    "requirements.txt",
    "packages.txt",
    "logo_unite.png",
    "README.md",
    "src",
    "config",
    # Le modèle Word : en-tête au logo, pied de page paginé, styles maison.
    # Sans lui, le prédiagnostic sort avec des styles recréés à l'approchant,
    # c'est-à-dire un document qui ne ressemble à rien de ce que l'équipe
    # produit.
    "modele",
    # Le script qui refabrique le modèle : sans lui, personne ne saurait
    # comment il a été produit le jour où la charte change.
    "outils",
]

#: Données : copiées uniquement à la première mise en place, et jamais
#: écrasées. `alias/` contient ce que l'équipe a appris des noms d'espèces —
#: l'écraser depuis un dossier de développement effacerait le travail de
#: plusieurs personnes.
DONNEES = ["classeurs", "extraits", "alias", "sources_locales"]

#: Jamais publié : dépôt git, caches, environnements, fichiers de travail.
EXCLUS = {".git", "__pycache__", ".venv", "venv", ".pytest_cache", ".claude"}


def destination_memorisee() -> Path | None:
    if not MEMO.exists():
        return None
    texte = MEMO.read_text(encoding="utf-8").strip()
    return Path(texte) if texte else None


def memoriser(destination: Path) -> None:
    MEMO.write_text(str(destination), encoding="utf-8")


def _fichiers_oublies() -> list[str]:
    """Fichiers de la racine qu'aucune liste ne mentionne.

    Le piège de long terme : les listes sont écrites à la main. `src/` est
    publié en entier, donc un nouveau module suit tout seul — mais un nouveau
    fichier à la racine serait oublié en silence, et l'outil en production
    tournerait sans lui. On préfère un avertissement à chaque publication.
    """
    connus = set(CODE) | set(DONNEES) | EXCLUS | {
        MEMO.name, ".gitignore", ".gitattributes", "directes.txt",
        "VERSION.txt", "LISEZ-MOI.txt",
    }
    oublies = []
    for element in sorted(RACINE.iterdir()):
        if element.name in connus or element.name.startswith("."):
            continue
        if element.is_dir() and element.name in ("sorties", "memoire",
                                                 "referentiels"):
            continue
        oublies.append(element.name + ("/" if element.is_dir() else ""))
    return oublies


def _ignorer(_dossier, noms):
    return {n for n in noms if n in EXCLUS or n.endswith(".pyc")}


def _version() -> str:
    """Date et commit, pour pouvoir répondre « tu es sur quelle version ? »."""
    horodatage = datetime.now().strftime("%d/%m/%Y à %H:%M")
    try:
        commit = subprocess.run(
            ["git", "-C", str(RACINE), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        commit = "inconnu"
    return (
        f"Prédiag environnemental\n"
        f"Publié le {horodatage}\n"
        f"Version {commit}\n"
        f"\n"
        f"En cas de question sur le comportement de l'outil, communiquez cette\n"
        f"version : elle dit exactement quel code tourne.\n"
    )


LISEZ_MOI = """PRÉDIAG ENVIRONNEMENTAL
=======================

POUR LANCER L'OUTIL
-------------------
Double-cliquez sur « _LANCER Prediag.bat ».

Au premier lancement, l'outil prépare son environnement sur votre poste :
comptez deux à cinq minutes. Les fois suivantes, il démarre en quelques
secondes.

Une fenêtre noire s'ouvre et reste ouverte : c'est normal, elle fait tourner
l'outil. Laissez-la tant que vous travaillez, fermez-la pour quitter.
L'outil lui-même s'affiche dans votre navigateur.

SI ÇA NE DÉMARRE PAS
--------------------
Le message affiché dans la fenêtre noire dit quoi faire. Les deux cas
courants :

  « Python n'est pas installé sur ce poste »
      À installer depuis python.org, ou à demander au service informatique.

  « L'installation des composants a échoué »
      Le réseau de l'entreprise bloque l'accès à pypi.org. Montrez le message
      au service informatique.

CONSEIL ONEDRIVE
----------------
Faites un clic droit sur ce dossier et choisissez « Toujours conserver sur cet
appareil ». Cela ne représente que quelques mégaoctets et évite des lenteurs
au démarrage.

Ne le faites PAS sur le sous-dossier « extraits » : il pèse plus de 500 Mo, et
l'outil n'y prend que les un ou deux départements de votre projet.

CE QUE L'OUTIL ÉCRIT, ET OÙ
---------------------------
Les documents que vous produisez se téléchargent par votre navigateur : vous
les enregistrez où vit votre projet.

Le reste — environnement, référentiels, fichiers de travail — va dans un
dossier technique sur votre poste, et non ici : c'est ce qui évite que
OneDrive synchronise des centaines de mégaoctets pour chaque personne.

LES DEUX ONGLETS
----------------
  A · Mise à jour des tables
      Réservé à la responsable environnement : tenue à jour des classeurs de
      statuts, reconstruction des extraits départementaux, et dépôt des
      couches sans source nationale (espaces naturels sensibles et assimilés).

  B · Prédiag
      Pour tout le monde : emprise du projet, communes, zonages, espèces,
      cartes, et le prédiagnostic Word complet.

LE DOCUMENT PRODUIT
-------------------
Il suit la forme du prédiagnostic externe de l'équipe, et part du modèle rangé
dans « modele » : en-tête au logo, pied de page paginé, styles maison.

Les passages SURLIGNÉS EN JAUNE signalent ce qui reste à compléter, avec à
chaque fois la consigne de ce qu'on attend à cet endroit.

À la première ouverture, Word met les sommaires à jour. Si ce n'est pas le
cas : Ctrl+A puis F9.

Le cadre général et les méthodologies viennent de « modele/cadre_general.docx ».
Ce fichier s'édite dans Word : quand la réglementation ou vos habitudes
évoluent, c'est là qu'on le dit, pas dans le code.
"""


def publier(vers: Path, avec_donnees: bool = False, essai: bool = False) -> None:
    vers = vers.expanduser()
    if not essai:
        vers.mkdir(parents=True, exist_ok=True)
    elif not vers.exists():
        print(f"  [essai] le dossier {vers} serait créé")

    print(f"\nPublication vers {vers}\n")
    copies = 0
    for nom in CODE:
        source = RACINE / nom
        if not source.exists():
            print(f"  ! absent du dossier de travail : {nom}")
            continue
        cible = vers / nom
        taille = (sum(f.stat().st_size for f in source.rglob("*") if f.is_file())
                  if source.is_dir() else source.stat().st_size)
        print(f"  {'[essai] ' if essai else ''}{nom}"
              f"{'/' if source.is_dir() else ''} — {taille / 1024:.0f} Ko")
        if essai:
            copies += 1
            continue
        try:
            if source.is_dir():
                shutil.copytree(source, cible, dirs_exist_ok=True,
                                ignore=_ignorer)
            else:
                shutil.copy2(source, cible)
        except PermissionError:
            # Cas courant : l'outil tourne en production et verrouille un
            # fichier. Une publication à moitié faite ne démarrerait pas, donc
            # on s'arrête net plutôt que de continuer.
            print(f"\n  ✗ {nom} est verrouillé en production.")
            print("    L'outil y est probablement ouvert : fermer la fenêtre "
                  "noire sur le poste concerné, puis relancer la publication.")
            print("    Publication interrompue — la production est dans un "
                  "état mixte, à ne pas laisser ainsi.\n")
            raise SystemExit(1)
        copies += 1

    for nom in DONNEES:
        source, cible = RACINE / nom, vers / nom
        presents = cible.exists() and any(cible.iterdir())
        if presents:
            print(f"  = {nom}/ conservé — ce sont les données de production, "
                  "jamais écrasées")
            continue
        if not avec_donnees:
            print(f"  ! {nom}/ absent en production. Relancer avec "
                  "--avec-donnees pour la première mise en place.")
            continue
        if not source.exists() or not any(source.iterdir()):
            print(f"  ! {nom}/ vide dans le dossier de travail, rien à copier")
            continue
        taille = sum(f.stat().st_size for f in source.rglob("*") if f.is_file())
        print(f"  {'[essai] ' if essai else ''}{nom}/ — {taille / 1048576:.0f} Mo "
              "(première mise en place)")
        if not essai:
            shutil.copytree(source, cible, dirs_exist_ok=True, ignore=_ignorer)

    if not essai:
        (vers / "VERSION.txt").write_text(_version(), encoding="utf-8")
        (vers / "LISEZ-MOI.txt").write_text(LISEZ_MOI, encoding="utf-8")
        memoriser(vers)
    print(f"\n  {copies} élément(s) de code"
          f"{' seraient publiés' if essai else ' publiés'}.")
    if not essai:
        print(f"  VERSION.txt et LISEZ-MOI.txt déposés.")
        print("\n  La synchronisation OneDrive peut prendre un moment, surtout "
              "si les extraits viennent d'être copiés.")


def main() -> int:
    ap = argparse.ArgumentParser(description="Publier l'outil en production")
    ap.add_argument("--vers", type=Path,
                    help="dossier de production ; mémorisé après la première "
                         "publication, donc facultatif ensuite")
    ap.add_argument("--avec-donnees", action="store_true",
                    help="copier aussi classeurs/ et extraits/ — première mise "
                         "en place seulement, jamais par-dessus des données "
                         "existantes")
    ap.add_argument("--essai", action="store_true",
                    help="afficher ce qui serait fait, sans rien écrire")
    args = ap.parse_args()

    destination = args.vers or destination_memorisee()
    if destination is None:
        print("\n  Aucune destination. Indiquez-la une fois avec --vers :\n"
              '    python publier.py --vers "<dossier Outils>" --avec-donnees\n'
              "  Elle sera mémorisée pour les publications suivantes.\n")
        return 1
    if args.vers is None:
        print(f"  Destination mémorisée : {destination}")

    oublies = _fichiers_oublies()
    if oublies:
        print("\n  ⚠ Fichiers présents dans le dossier de travail mais dans "
              "aucune liste de publication :")
        for nom in oublies:
            print(f"      {nom}")
        print("    S'ils doivent partir en production, les ajouter à CODE "
              "dans publier.py.\n")

    publier(destination, avec_donnees=args.avec_donnees, essai=args.essai)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
