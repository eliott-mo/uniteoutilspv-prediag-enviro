"""Mise en correspondance des vocabulaires : classeurs ↔ BDC-Statuts.

Les deux sources ne codent pas les statuts de la même façon. Comparer sans
traduire produit des centaines de faux écarts — on l'a mesuré : 1 050 des
1 383 premiers constats n'étaient que des différences d'écriture.

Ce qui se compare, et comment :

===========  ===============================  ==============================
type         classeurs                        BDC-Statuts
===========  ===============================  ==============================
LRE/LRN/     LC, NT, VU, EN, CR, DD,          mêmes codes, mais « NA » seul
LRR/LRM      NA et ses variantes NAa…NAd      (sans le qualificatif)
ZDET         « Oui », « X »                   « true » — un booléen
DH           II, IV, V                        CDH2, CDH4, CDH5
===========  ===============================  ==============================

Ce qui ne se compare pas, faute de table de correspondance :

* **PN et PR** — BDC désigne l'arrêté (`NO3`, `GO3`, `RV93`), Marie l'article
  (« Art. 3 »). Deux nomenclatures sans pont automatique.
* **DO** — BDC code l'annexe (`CDO1`), Marie le code espèce (`A092`).
* **PD, PNA** — non traités à ce stade.

Mieux vaut annoncer qu'on ne compare pas que produire un écart faux : un outil
qui crie au loup se fait désactiver.
"""
from __future__ import annotations

import re

#: Types dont les deux vocabulaires se rejoignent.
TYPES_COMPARABLES = {"LRE", "LRN", "LRR", "LRM", "ZDET", "DH"}

#: Types lus mais volontairement non confrontés, avec la raison affichée.
TYPES_ECARTES = {
    "PN": "BDC code l'arrêté (NO3, GO3…), le classeur l'article (Art. 3)",
    "PR": "BDC code l'arrêté (RV93…), le classeur l'article (Art. 1)",
    "PD": "non traité à ce stade",
    "DO": "BDC code l'annexe (CDO1), le classeur le code espèce (A092)",
    "PNA": "non traité à ce stade",
}

_CATEGORIES_UICN = {"LC", "NT", "VU", "EN", "CR", "DD", "NE", "NA", "RE", "EX", "EW", "CR*"}
_VRAI = {"oui", "x", "true", "vrai", "1", "d", "det", "determinante"}
_ANNEXE_DH = {"CDH2": "II", "CDH4": "IV", "CDH5": "V", "CDH1": "I", "CDH3": "III"}


def _nettoyer(valeur: str) -> str:
    return re.sub(r"\s+", " ", str(valeur or "")).strip()


def normaliser_code(valeur: str, type_statut: str) -> str | None:
    """Forme comparable d'un code, ou None s'il n'a pas de sens pour ce type."""
    v = _nettoyer(valeur)
    if not v:
        return None

    if type_statut == "ZDET":
        return "true" if v.lower() in _VRAI else "false"

    if type_statut == "DH":
        majuscule = v.upper().replace(" ", "")
        if majuscule in _ANNEXE_DH:
            return _ANNEXE_DH[majuscule]
        trouve = re.search(r"(?i)\b(I{1,3}|IV|V)\b", v)
        return trouve.group(1).upper() if trouve else None

    # Listes rouges : « NAb », « NAo », « NAc » valent « NA » à la maille BDC.
    majuscule = v.upper()
    if majuscule.startswith("NA"):
        return "NA"
    majuscule = majuscule.rstrip("*")
    return majuscule if majuscule in _CATEGORIES_UICN else majuscule


def equivalents(cote_classeur: str, cote_bdc: str, type_statut: str) -> bool:
    """Les deux écritures désignent-elles le même statut ?"""
    a = normaliser_code(cote_classeur, type_statut)
    b = normaliser_code(cote_bdc, type_statut)
    if a is None or b is None:
        return True          # rien à comparer : on ne signale pas
    return a == b


def comparable(type_statut: str) -> bool:
    return type_statut in TYPES_COMPARABLES


def raison_ecart(type_statut: str) -> str:
    return TYPES_ECARTES.get(type_statut, "")
