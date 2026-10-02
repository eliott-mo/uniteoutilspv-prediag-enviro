"""Tableaux Word déjà mis en forme — le dernier geste manuel qu'on supprime.

L'onglet « Utilisation » des classeurs décrit la fin du processus actuel :

    Copier le tableau (sans prendre les cellules en violet) · Coller dans Word
    et appliquer les différents styles du tableau (texte tableau centré ou non
    et titre colonne tableau), réajuster les colonnes et mettre les noms latins
    en italique

Ces conventions sont lues dans le document de référence :

===================  =========================================================
en-tête de colonne   style de paragraphe « Titre colonne »
corps de cellule     style « Corps de texte - Unite »
nom scientifique     en italique
dates et codes       centrés
tableau              style « Table Grid »
légende              style « Caption »
===================  =========================================================

Ces styles appartiennent au modèle UNITe. On ouvre donc un document modèle
quand on en fournit un — n'importe quel document de l'équipe convient, on n'en
garde que les styles — et on recrée les styles manquants sinon, pour que la
sortie reste exploitable même sans modèle sous la main.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

STYLE_ENTETE = "Titre colonne"
STYLE_CORPS = "Corps de texte - Unite"
STYLE_LEGENDE = "Caption"
STYLE_TABLEAU = "Table Grid"

#: Colonnes dont le contenu se centre (codes courts, dates, statuts).
_CENTREES = {
    "dernière observation", "nidification", "annexe i directive « oiseaux »",
    "annexe ii directive « habitats »", "protection nationale", "liste rouge europe",
    "liste rouge france", "nicheurs", "hivernants", "de passage", "cd_nom",
}


@dataclass
class Colonne:
    titre: str
    cle: str                 # clé dans le dictionnaire de ligne
    italique: bool = False   # noms scientifiques
    centree: bool | None = None

    def alignee(self) -> bool:
        if self.centree is not None:
            return self.centree
        return self.titre.strip().lower() in _CENTREES


def _vider(document: Document) -> Document:
    """Ne garde du modèle que ses styles."""
    corps = document.element.body
    for enfant in list(corps):
        if enfant.tag.endswith("}sectPr"):
            continue
        corps.remove(enfant)
    return document


def _assurer_styles(document: Document) -> list[str]:
    """Crée les styles manquants. Renvoie ceux qui ont dû l'être."""
    from docx.enum.style import WD_STYLE_TYPE

    crees: list[str] = []
    existants = {s.name for s in document.styles}
    for nom, taille, gras in ((STYLE_ENTETE, 9, True), (STYLE_CORPS, 9, False)):
        if nom in existants:
            continue
        style = document.styles.add_style(nom, WD_STYLE_TYPE.PARAGRAPH)
        style.font.size = Pt(taille)
        style.font.bold = gras
        style.paragraph_format.space_before = Pt(1)
        style.paragraph_format.space_after = Pt(1)
        crees.append(nom)
    return crees


def _ecrire_cellule(cellule, texte: str, style: str, italique: bool,
                    centree: bool) -> None:
    paragraphe = cellule.paragraphs[0]
    try:
        paragraphe.style = style
    except KeyError:
        pass
    if centree:
        paragraphe.alignment = WD_ALIGN_PARAGRAPH.CENTER
    passage = paragraphe.add_run(str(texte or ""))
    if italique:
        passage.italic = True


def ecrire_tableau(document: Document, colonnes: list[Colonne],
                   lignes: list[dict], legende: str = "") -> None:
    """Ajoute un tableau mis en forme selon les conventions UNITe."""
    tableau = document.add_table(rows=1, cols=len(colonnes))
    try:
        tableau.style = STYLE_TABLEAU
    except KeyError:
        pass
    tableau.alignment = WD_TABLE_ALIGNMENT.CENTER

    for cellule, colonne in zip(tableau.rows[0].cells, colonnes):
        _ecrire_cellule(cellule, colonne.titre, STYLE_ENTETE, False, True)

    for ligne in lignes:
        cellules = tableau.add_row().cells
        for cellule, colonne in zip(cellules, colonnes):
            _ecrire_cellule(cellule, ligne.get(colonne.cle, ""), STYLE_CORPS,
                            colonne.italique, colonne.alignee())

    if legende:
        paragraphe = document.add_paragraph(legende)
        try:
            paragraphe.style = STYLE_LEGENDE
        except KeyError:
            pass


def colonnes_especes(statuts: list[str]) -> list[Colonne]:
    """Colonnes du tableau d'espèces : l'ossature fixe, puis les statuts retenus."""
    base = [
        Colonne("Nom commun", "nom_commun"),
        Colonne("Nom scientifique", "nom_scientifique", italique=True),
        Colonne("Nidification", "nidification", centree=True),
        Colonne("Dernière observation", "date_obs", centree=True),
    ]
    return base + [Colonne(s, f"statut::{s}", centree=True) for s in statuts]


def colonnes_zonages() -> list[Colonne]:
    """Colonnes des tableaux 8 à 10, dans l'ordre du document de référence."""
    return [
        Colonne("Nom", "nom"),
        Colonne("Distance à la ZIP", "distance", centree=True),
        Colonne("Identifiant", "identifiant", centree=True),
        Colonne("Intérêt", "interet"),
        Colonne("Aire(s) d'étude concernée(s)", "aires", centree=True),
    ]


def ecrire_document(chemin: Path, titre: str, blocs: list[tuple[str, list[Colonne],
                                                                list[dict], str]],
                    modele: Path | None = None,
                    mentions: list[str] | None = None) -> tuple[Path, list[str]]:
    """Produit le document. `blocs` = (intertitre, colonnes, lignes, légende).

    Renvoie (chemin, styles recréés) — si des styles ont dû être recréés, c'est
    que le modèle n'en portait pas : la mise en forme sera approchante et il
    vaut mieux le dire que de laisser croire.
    """
    if modele and Path(modele).exists():
        document = _vider(Document(str(modele)))
    else:
        document = Document()
    recrees = _assurer_styles(document)

    document.add_heading(titre, level=1)
    for intertitre, colonnes, lignes, legende in blocs:
        if intertitre:
            document.add_heading(intertitre, level=2)
        if not lignes:
            document.add_paragraph("Aucune espèce retenue pour ce groupe.")
            continue
        ecrire_tableau(document, colonnes, lignes, legende)

    if mentions:
        document.add_paragraph()
        for mention in mentions:
            paragraphe = document.add_paragraph(mention)
            paragraphe.runs[0].font.size = Pt(7)

    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(chemin))
    return chemin, recrees
