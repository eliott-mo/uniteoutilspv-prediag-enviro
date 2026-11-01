# -*- coding: utf-8 -*-
"""Où et comment implanter des colonnes dans un classeur UNITe.

Un classeur B-Statuts a deux faces. L'onglet `Statuts` est la table de
référence : une ligne par taxon, une colonne par statut. « Saisie étude » est
le gabarit d'étude de la responsable environnement : on y tape un nom, et
chaque colonne va chercher son statut par RECHERCHEV dans une plage fixe de
`Statuts`, avec le numéro de colonne porté en tête.

Ajouter une colonne à `Statuts` ne suffit donc pas : il faut aussi la déclarer
dans la saisie, sous le numéro qui convient, et que la plage la couvre. Ce
module lit, sans rien écrire, tout ce qu'il faut savoir pour le faire : la
première colonne libre de `Statuts`, la plage et les lignes de déclaration de
la saisie, la colonne qui sert de modèle et l'endroit où insérer.

Les six gabarits ne sont pas faits pareil :

* déclarations en lignes 5-6-7 (oiseaux, mammifères, amphibiens-reptiles) ou
  6-7-8 (les trois autres) ;
* plage commençant en A ou en B, donc numéros décalés d'un cran ;
* une colonne par région chez la plupart, mais une seule colonne de liste
  rouge régionale chez les amphibiens-reptiles, qui suit la « Région d'étude »
  par une table de `Statuts`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl
from openpyxl.utils import column_index_from_string, get_column_letter

#: La RECHERCHEV type de « Saisie étude » : plage de `Statuts`, puis numéro de
#: colonne lu dans une cellule de tête — `C$5` ou `AK$6` selon le classeur.
_RECHERCHEV = re.compile(
    r"Statuts!\$?([A-Z]+)\$?(\d+):\$?([A-Z]+)\$?(\d+)\s*[,;]\s*\$?[A-Z]+\$(\d+)",
    re.IGNORECASE)

#: Une colonne de saisie qui suit la « Région d'étude » : son numéro est
#: cherché dans une table de `Statuts`, région → numéro de colonne.
_TABLE_REGION = re.compile(
    r"VLOOKUP\(\s*\$?B\$?\d+\s*[,;]\s*Statuts!\$?([A-Z]+)\$?(\d+):\$?([A-Z]+)\$?(\d+)",
    re.IGNORECASE)


def colonne(n: int) -> str:
    return get_column_letter(n)


@dataclass
class ColonneSaisie:
    """Une colonne déclarée de « Saisie étude »."""
    colonne: int                   # 1 pour A
    numero: int | None             # lu en ligne d'index ; None si absent
    territoire: str
    champ: str


@dataclass
class Saisie:
    """Comment « Saisie étude » lit `Statuts`."""
    ligne_index: int               # numéro de colonne ; territoire et champ suivent
    plage: str                     # « Statuts!$B$2:$BY$327 », tel qu'écrit
    plage_premiere_colonne: int    # 1 pour A
    plage_derniere_colonne: int
    plage_derniere_ligne: int
    derniere_ligne_formules: int
    colonnes: list[ColonneSaisie]
    #: Première colonne « EEE » : les colonnes de statut s'insèrent devant.
    colonne_eee: int | None
    #: Cellules fusionnées de la feuille, à éviter comme modèles de format.
    fusions: list[str]
    #: Table région → numéro, quand une colonne suit la « Région d'étude ».
    table_region: tuple[int, int, int, int] | None = None   # col1, ligne1, col2, ligne2
    colonne_region: int | None = None                       # la colonne qui la suit

    def numero(self, colonne_statuts: int) -> int:
        """Le numéro à déclarer pour une colonne de `Statuts`."""
        return colonne_statuts - self.plage_premiere_colonne + 1

    def colonne_lue(self, numero: int) -> int:
        """La colonne de `Statuts` qu'un numéro désigne."""
        return numero + self.plage_premiere_colonne - 1

    def fusionnee(self, ligne: int, col: int) -> bool:
        for plage in self.fusions:
            debut, _, fin = plage.partition(":")
            if not fin:
                continue
            c1, l1 = openpyxl.utils.cell.coordinate_from_string(debut)
            c2, l2 = openpyxl.utils.cell.coordinate_from_string(fin)
            if (l1 <= ligne <= l2 and column_index_from_string(c1) <= col
                    <= column_index_from_string(c2)):
                return True
        return False


@dataclass
class Disposition:
    """Où des colonnes s'implantent dans un classeur."""
    premiere_libre: int            # première colonne libre de `Statuts`, 1 pour A
    derniere_entete: int
    lignes: list[int]              # lignes de `Statuts` qui portent un taxon
    saisie: Saisie | None
    filtre: str | None             # plage du filtre automatique de `Statuts`
    entetes: list[str] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)

    @property
    def derniere_ligne(self) -> int:
        return max(self.lignes)


def _saisie(wb) -> Saisie | None:
    nom = next((n for n in wb.sheetnames
                if n.strip().lower().startswith("saisie")), None)
    if nom is None:
        return None
    ws = wb[nom]
    plages: dict[tuple, int] = {}
    textes: dict[tuple, str] = {}
    for ligne in ws.iter_rows(min_row=5, max_row=12):
        for cellule in ligne:
            if not isinstance(cellule.value, str):
                continue
            for m in _RECHERCHEV.finditer(cellule.value):
                cle = (int(m.group(5)), column_index_from_string(m.group(1).upper()),
                       column_index_from_string(m.group(3).upper()), int(m.group(4)))
                plages[cle] = plages.get(cle, 0) + 1
                textes[cle] = m.group(0).split(",")[0].split(";")[0].strip()
        if plages:
            break
    if not plages:
        return None
    cle = max(plages, key=plages.get)
    ligne_index, premiere, derniere, fin = cle

    table, colonne_region = None, None
    for ligne in ws.iter_rows(min_row=1, max_row=8):
        for cellule in ligne:
            m = (_TABLE_REGION.search(cellule.value)
                 if isinstance(cellule.value, str) else None)
            if m:
                table = (column_index_from_string(m.group(1).upper()), int(m.group(2)),
                         column_index_from_string(m.group(3).upper()), int(m.group(4)))
                colonne_region = cellule.column

    colonnes = []
    for j in range(1, ws.max_column + 1):
        brut = ws.cell(ligne_index, j).value
        champ = " ".join(str(ws.cell(ligne_index + 2, j).value or "").split())
        territoire = " ".join(str(ws.cell(ligne_index + 1, j).value or "").split())
        numero = (int(brut) if isinstance(brut, (int, float)) or
                  (isinstance(brut, str) and brut.strip().isdigit()) else None)
        if numero is not None or (champ and territoire):
            colonnes.append(ColonneSaisie(j, numero, territoire, champ))
    eee = next((c.colonne for c in colonnes if c.champ.upper().startswith("EEE")), None)
    derniere_formule = max((c.row for r in ws.iter_rows(min_row=ligne_index + 3)
                            for c in r if isinstance(c.value, str)
                            and c.value.startswith("=")), default=ligne_index + 3)
    return Saisie(ligne_index, textes[cle], premiere, derniere, fin, derniere_formule,
                  colonnes, eee, [str(m) for m in ws.merged_cells.ranges],
                  table, colonne_region)


def disposition(chemin: Path) -> Disposition:
    """Lit, sans rien écrire, la place libre de `Statuts` et la saisie."""
    wb = openpyxl.load_workbook(chemin, read_only=False, data_only=False)
    try:
        ws = wb["Statuts"]
        entetes = [" ".join(str(c.value or "").split()) for c in ws[1]]
        derniere_entete = max(i for i, v in enumerate(entetes, start=1) if v)
        lignes = [r[0].row for r in ws.iter_rows(min_row=2)
                  if any(c.value not in (None, "") for c in r[:6])]
        avertissements = []
        # On implante après tout ce qui est occupé, pas seulement après la
        # dernière en-tête : le classeur des amphibiens-reptiles range une
        # table de correspondance sous ses données, en AM125:AN151.
        occupees = [c for r in ws.iter_rows(min_row=2, min_col=derniere_entete + 1)
                    for c in r if c.value not in (None, "")]
        premiere_libre = derniere_entete + 1
        if occupees:
            premiere_libre = max(c.column for c in occupees) + 1
            avertissements.append(
                f"« Statuts » porte des cellules à droite de sa dernière en-tête, "
                f"de {occupees[0].coordinate} à {occupees[-1].coordinate} : les "
                f"colonnes sont implantées après elles, en "
                f"{get_column_letter(premiere_libre)}")
        return Disposition(premiere_libre, derniere_entete, lignes, _saisie(wb),
                           ws.auto_filter.ref, entetes, avertissements)
    finally:
        wb.close()


@dataclass
class Proposee:
    """Une colonne ajoutée au classeur."""
    entete: str                    # tel qu'il s'écrit en ligne 1 de `Statuts`
    territoire: str                # à déclarer dans « Saisie étude »
    champ: str                     # idem, ligne du champ
    valeurs: dict[int, object]     # ligne de `Statuts` → valeur
    #: Commentaire de l'en-tête : la liste d'où viennent les valeurs.
    source: str = ""
