#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Extrait le tableau 3 de la liste rouge nationale des Orthoptères.

    python outils/extraire_orthopteres.py <LR_Orthopteres_2004.pdf> [sortie.csv]

**La source.** SARDET E. & DEFAUT B. (coordinateurs), 2004. — Les Orthoptères
menacés en France. Liste rouge nationale et listes rouges par domaines
biogéographiques. *Matériaux Orthoptériques et Entomocénotiques*, 9 : 125-137.
ASCETE. C'est la seule référence nationale pour ce groupe, et aucune édition
postérieure n'est parue : BDC-Statuts n'en porte rien, faute de pouvoir la
ramener au modèle des listes rouges UICN.

**L'échelle est inversée par rapport à l'UICN**, et c'est le piège de ce
tableau : 1 désigne les espèces proches de l'extinction et 4 celles qui ne
sont pas menacées, quand « LC » et « CR » se lisent dans l'autre sens. Les
convertir en catégories UICN serait une falsification ; on les publie telles
quelles, sous leur propre intitulé.

**Ce que l'extraction rend, et ce qu'elle ne rend pas.** Le tableau donne un
indice national et un indice pour chacun des huit domaines biogéographiques.
Mais le découpage de ces domaines n'existe dans l'article que sous forme de
carte (figure 1, page 4) : il n'y a pas de table département vers domaine, et
la méthodologie précise même qu'un département peut relever de trois domaines
à la fois. Rattacher un projet à son domaine reste donc un geste humain.
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import pdfplumber

#: Colonnes du tableau 3, dans l'ordre où elles s'y lisent.
DOMAINES = [
    ("F", "Liste nationale"),
    ("NEM", "Domaine némoral"),
    ("MC", "Massif central / Montagne Noire"),
    ("PYR", "Domaine pyrénéen"),
    ("ALP", "Domaine alpien"),
    ("LAN", "Domaine subméditerranéen languedocien"),
    ("AQU", "Domaine subméditerranéen aquitain"),
    ("MED", "Domaine méditerranéen"),
    ("COR", "Corse"),
]

#: Sens des indices, tel que la légende de l'article le définit.
PRIORITES = {
    "1": "proche de l'extinction, ou déjà éteinte",
    "2": "fortement menacée d'extinction",
    "3": "menacée, à surveiller",
    "4": "non menacée, en l'état actuel des connaissances",
    "-": "absente du territoire considéré",
    "♣": "n'appartenant vraisemblablement pas au territoire considéré",
    "?": "information insuffisante pour statuer",
    "HS": "hors sujet (synanthrope)",
}

#: Pages portant le tableau 3 (1-indexées), repérées par leur en-tête.
_ENTETE = "Domaines biogéographiques F NEM MC PYR ALP LAN AQU MED COR"

#: Une valeur de case.
_VALEUR = re.compile(r"^(?:[1-4]|-|\?|♣|HS)$")

#: Appels de note accolés à une valeur : « ♣ (1) ».
_NOTE = re.compile(r"^\(\d+\)$")

#: Marqueurs portés par le nom : annexe 4 de la directive, protection
#: nationale. Ils peuvent précéder la ligne ou la suivre.
_MARQUEURS = {"●": "directive_habitats_annexe_4", "○": "protection_nationale"}

#: Lignes de structure à ne pas confondre avec des espèces.
_IGNORER = re.compile(
    r"(?i)^(superfamille|famille|sous-famille|tableau|domaines biogéo|"
    r"listes? rouges?|\d+\s|e\. sardet)"
)


#: Début du tableau 4, qui arrête la lecture. **Il porte le même en-tête de
#: colonnes que le tableau 3 et il faut s'en méfier** : c'est une
#: récapitulation des seules espèces de priorité 1 ou 2, déjà présentes
#: au-dessus. Les lire à la suite ajoutait trente-trois doublons, dont
#: quelques-uns sous un nom légèrement différent — « Acrometopa servillea »
#: pour « Acrometopa servillea italica » — qu'un dédoublonnage sur le nom
#: n'aurait même pas rattrapés.
_FIN = re.compile(r"(?i)^tableau\s*4\b")


def _pages_du_tableau(pdf) -> list:
    """Les pages portant le tableau, repérées par leur en-tête de colonnes.

    Les repérer plutôt que de figer « pages 7 à 11 » : une réédition qui
    déplacerait le tableau d'une page serait lue sans qu'on y touche, et une
    qui le supprimerait lèverait au lieu de rendre une liste vide.
    """
    retenues = [p for p in pdf.pages if _ENTETE in (p.extract_text() or "")]
    if not retenues:
        raise SystemExit(
            "En-tête du tableau 3 introuvable : ce PDF n'est pas celui "
            "attendu, ou sa mise en page a changé."
        )
    return retenues


def _decouper(ligne: str) -> tuple[str, list[str], set[str]]:
    """Sépare une ligne en (nom, valeurs, marqueurs)."""
    marqueurs = {_MARQUEURS[c] for c in _MARQUEURS if c in ligne}
    for symbole in _MARQUEURS:
        ligne = ligne.replace(symbole, " ")

    jetons = ligne.split()
    valeurs: list[str] = []
    while jetons:
        dernier = jetons[-1]
        if _NOTE.match(dernier):        # « (1) » : appel de note, pas une valeur
            jetons.pop()
            continue
        if not _VALEUR.match(dernier):
            break
        valeurs.insert(0, jetons.pop())
    return " ".join(jetons).strip(), valeurs, marqueurs


def extraire(pdf_path: Path) -> list[dict]:
    """Lit le tableau et rend une ligne par espèce."""
    lignes_brutes: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in _pages_du_tableau(pdf):
            lignes_brutes += (page.extract_text() or "").split("\n")

    especes: list[dict] = []
    attente: tuple[str, set[str]] | None = None     # nom dont les valeurs suivent
    #: Marqueurs lus sur une ligne qui n'en porte que, et qui se rapportent à
    #: l'espèce suivante. Le tableau les place ainsi trois fois — « ●○ » seul
    #: au-dessus de Saga pedo, puis deux « ○ ». Les chercher sur la seule
    #: ligne de l'espèce ne rendait donc aucun des deux statuts.
    en_attente_marqueurs: set[str] = set()

    for brute in lignes_brutes:
        brute = brute.strip()
        if _FIN.match(brute):
            break
        if not brute or _ENTETE in brute or _IGNORER.match(brute):
            attente = None
            continue

        nom, valeurs, marqueurs = _decouper(brute)
        if not nom and not valeurs and marqueurs:
            en_attente_marqueurs |= marqueurs
            continue
        marqueurs |= en_attente_marqueurs
        en_attente_marqueurs = set()

        # Une ligne de valeurs seules complète le nom laissé en attente.
        if not nom and valeurs and attente is not None:
            nom, marques_nom = attente
            marqueurs |= marques_nom
            attente = None
        elif nom and not valeurs:
            # Nom seul : ses valeurs sont sur la ligne suivante. On ne retient
            # que ce qui ressemble à un nom scientifique, pour ne pas prendre
            # une phrase coupée du corps du texte.
            attente = (nom, marqueurs) if _nom_plausible(nom) else None
            continue
        else:
            attente = None

        if not nom or not _nom_plausible(nom):
            continue
        if len(valeurs) != len(DOMAINES):
            # On ne devine pas quelle colonne manque : le signaler vaut mieux
            # que décaler neuf indices d'un cran.
            especes.append({"nom_scientifique": nom, "_incomplet": len(valeurs),
                            "_brut": brute})
            continue

        fiche = {"nom_scientifique": nom}
        fiche.update({code: v for (code, _), v in zip(DOMAINES, valeurs)})
        fiche["directive_habitats_annexe_4"] = (
            "oui" if "directive_habitats_annexe_4" in marqueurs else "")
        fiche["protection_nationale"] = (
            "oui" if "protection_nationale" in marqueurs else "")
        especes.append(fiche)

    return especes


def _nom_plausible(nom: str) -> bool:
    """Un binôme ou trinôme latin, éventuellement abrégé (« Anonconotus b. »).

    La barre oblique est admise : l'article réunit sous une seule ligne deux
    sous-espèces qu'il ne sépare pas — « Chorthippus binotatus saulcyi /
    moralesi ». La rejeter faisait perdre cette espèce, et une seule, ce qui
    se voyait au total : 215 au lieu des 216 que le résumé annonce.
    """
    mots = nom.split()
    if not (2 <= len(mots) <= 6):
        return False
    if not re.match(r"^[A-Z][a-z]+$", mots[0]):
        return False
    return all(re.match(r"^[a-z]+\.?$|^/$", m) for m in mots[1:])


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    pdf_path = Path(sys.argv[1])
    sortie = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("orthopteres.csv")

    especes = extraire(pdf_path)
    complets = [e for e in especes if "_incomplet" not in e]
    boiteux = [e for e in especes if "_incomplet" in e]

    champs = (["nom_scientifique"] + [c for c, _ in DOMAINES]
              + ["directive_habitats_annexe_4", "protection_nationale"])
    with open(sortie, "w", encoding="utf-8-sig", newline="") as f:
        ecrivain = csv.DictWriter(f, fieldnames=champs, extrasaction="ignore")
        ecrivain.writeheader()
        ecrivain.writerows(complets)

    print(f"{len(complets)} espèces écrites dans {sortie}")
    if boiteux:
        print(f"\n{len(boiteux)} ligne(s) incomplète(s), NON écrites :")
        for e in boiteux:
            print(f"   {e['_incomplet']} valeur(s) — {e['_brut'][:88]}")


if __name__ == "__main__":
    main()
