"""Rapport de veille en Excel — le format dans lequel Marie travaille.

Un onglet par famille de constats, plus une synthèse. La colonne **décision**
est laissée vide, avec une liste déroulante : c'est elle qui la remplit. Cela
matérialise l'arbitrage et laisse une trace de ce qui a été écarté.

Le fichier vise l'onglet « Suivi modifs statuts » qui existe déjà dans ses six
classeurs : on remplit une place qu'elle a prévue plutôt que d'en inventer une.

La mention de source en tête de la synthèse n'est pas décorative : la Licence
Ouverte (Etalab) impose de citer la source **et sa date de mise à jour**.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .memoire import DECISIONS, Memoire
from .veille import FAMILLES, Constat, Resultat

_ENTETE = PatternFill("solid", fgColor="1F3864")
_BANDE = PatternFill("solid", fgColor="EEF2F8")
_BLANC = Font(color="FFFFFF", bold=True)
_LIEN = Font(color="1155CC", underline="single")

_COLONNES = [
    ("Groupe", 17), ("Ligne", 7), ("Taxon", 34), ("Champ", 20),
    ("Valeur actuelle", 16), ("Valeur proposée", 18), ("Détail", 46),
    ("Source", 18), ("Vérifier", 11), ("Décision", 13), ("Note", 26),
]


def _entete(ws, titre: str) -> None:
    ws.append([c for c, _ in _COLONNES])
    for i, (_, largeur) in enumerate(_COLONNES, start=1):
        ws.cell(1, i).fill = _ENTETE
        ws.cell(1, i).font = _BLANC
        ws.cell(1, i).alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = largeur
    ws.freeze_panes = "A2"
    ws.title = titre[:31]


def _ligne(ws, c: Constat, memoire: Memoire, n: int) -> None:
    arbitre = memoire.arbitrage(c.cle)
    ws.append([
        c.groupe, c.ligne, c.taxon, c.champ, c.actuel, c.propose, c.detail,
        c.source, "ouvrir" if c.lien else "",
        arbitre.decision if arbitre else "", arbitre.note if arbitre else "",
    ])
    if c.lien:
        cell = ws.cell(n, 9)
        cell.hyperlink = c.lien
        cell.font = _LIEN
    if n % 2 == 0:
        for i in range(1, len(_COLONNES) + 1):
            ws.cell(n, i).fill = _BANDE
    ws.cell(n, 6).font = Font(bold=True)
    ws.cell(n, 7).alignment = Alignment(wrap_text=True, vertical="top")


def _validation(ws, lignes: int) -> None:
    if lignes < 2:
        return
    dv = DataValidation(type="list", formula1='"' + ",".join(DECISIONS) + '"',
                        allow_blank=True, showDropDown=False)
    ws.add_data_validation(dv)
    dv.add(f"J2:J{lignes}")


def _synthese(wb: Workbook, res: Resultat, citations: list[str],
              memoire: Memoire, filtres: str) -> None:
    ws = wb.create_sheet("Synthèse", 0)
    ws.column_dimensions["A"].width = 42
    ws.column_dimensions["B"].width = 64

    ws["A1"] = "Veille des classeurs B-Statuts"
    ws["A1"].font = Font(size=14, bold=True, color="1F3864")
    ws["A2"] = f"Produit le {date.today().strftime('%d/%m/%Y')}"
    if filtres:
        ws["B2"] = filtres

    n = 4
    ws.cell(n, 1, "Constats").font = Font(bold=True)
    n += 1
    for cle, titre in FAMILLES:
        combien = len(res.par_famille(cle))
        ws.cell(n, 1, titre)
        ws.cell(n, 2, "rien à signaler" if not combien else f"{combien} ligne(s)")
        if combien:
            ws.cell(n, 2).font = Font(bold=True)
        n += 1

    n += 1
    ws.cell(n, 1, "Couverture de la comparaison").font = Font(bold=True)
    n += 1
    for groupe, (cellules, taxons) in sorted(res.couverture.items()):
        ws.cell(n, 1, f"   {groupe}")
        ws.cell(n, 2, f"{cellules} cellule(s) confrontée(s) à BDC sur {taxons} taxons")
        n += 1

    n += 1
    ws.cell(n, 1, "Mémoire").font = Font(bold=True)
    n += 1
    ws.cell(n, 1, "   arbitrages déjà rendus")
    ws.cell(n, 2, str(len(memoire._arbitrages)))
    n += 2

    ws.cell(n, 1, "Sources").font = Font(bold=True)
    n += 1
    for c in citations:
        ws.cell(n, 1, "   " + c)
        ws.merge_cells(start_row=n, start_column=1, end_row=n, end_column=2)
        n += 1
    n += 1
    ws.cell(n, 1, "Licence Ouverte / Open Licence (Etalab) — réutilisation libre, "
                  "y compris commerciale, sous réserve de citer la source et sa date.")
    ws.merge_cells(start_row=n, start_column=1, end_row=n, end_column=2)
    n += 2

    if res.avertissements:
        ws.cell(n, 1, "Avertissements de lecture").font = Font(bold=True)
        n += 1
        for a in res.avertissements:
            ws.cell(n, 1, "   " + a)
            ws.merge_cells(start_row=n, start_column=1, end_row=n, end_column=2)
            n += 1

    ws.cell(n + 1, 1, "L'outil propose, tu arbitres : aucun classeur n'a été modifié.")
    ws.cell(n + 1, 1).font = Font(italic=True, color="666666")


def ecrire(res: Resultat, chemin: Path, citations: list[str], memoire: Memoire,
           filtres: str = "") -> Path:
    wb = Workbook()
    wb.remove(wb.active)

    for cle, titre in FAMILLES:
        constats = res.par_famille(cle)
        ws = wb.create_sheet(titre[:31])
        _entete(ws, titre[:31])
        for i, c in enumerate(constats, start=2):
            _ligne(ws, c, memoire, i)
        _validation(ws, len(constats) + 1)
        if not constats:
            ws.cell(2, 1, "rien à signaler").font = Font(italic=True, color="666666")

    _synthese(wb, res, citations, memoire, filtres)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    wb.save(chemin)
    return chemin


def relire_decisions(chemin: Path, memoire: Memoire) -> int:
    """Relit un rapport annoté et enregistre les arbitrages dans la mémoire."""
    from openpyxl import load_workbook
    wb = load_workbook(chemin, data_only=True)
    retenus = 0
    for titre in wb.sheetnames:
        if titre == "Synthèse":
            continue
        ws = wb[titre]
        for ligne in ws.iter_rows(min_row=2, values_only=True):
            if not ligne or len(ligne) < 11 or not ligne[0]:
                continue
            groupe, num, _taxon, champ, actuel, propose = ligne[:6]
            decision, note = ligne[9], ligne[10]
            if not decision or str(decision).strip() not in DECISIONS:
                continue
            cle = f"{groupe}|{num}|{champ}|{actuel or ''}|{propose or ''}"
            memoire.trancher(cle, str(decision).strip(), str(propose or ""),
                             str(note or ""))
            retenus += 1
    wb.close()
    memoire.enregistrer()
    return retenus
