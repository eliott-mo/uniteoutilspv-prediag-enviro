"""Recoupement des sources d'espèces déposées par la responsable environnement.

L'outil ne va pas chercher les occurrences : elle les trouve elle-même, au cas
par cas, sur les sources qui font autorité pour tel groupe dans telle région.
C'est un jugement qu'on n'a aucune chance de coder. Ce qu'on peut faire, c'est
**recouper ce qu'elle dépose** : exports Excel, CSV, PDF, captures d'écran.

Le pivot est TaxRef : chaque nom est apparié vers un `cd_ref`, ce qui permet de
dédoublonner entre sources quelles que soient les graphies. TaxRef joue aussi
le rôle de correcteur orthographique — un nom mal lu dans une capture ne
s'apparie pas et remonte dans les **non résolus** au lieu de passer
silencieusement. C'est ce qui rend les captures exploitables plutôt que
dangereuses.

La colonne des noms n'est pas devinée par son en-tête : on essaie chaque
colonne et on garde **celle qui s'apparie le mieux à TaxRef**. Un en-tête peut
manquer ou être exotique ; un taux d'appariement, non.
"""
from __future__ import annotations

import csv
import io
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .memoire import Memoire
from .taxref import Index, normaliser

FORMATS_TABLEUR = {".xlsx", ".xlsm", ".xls"}
FORMATS_TEXTE = {".csv", ".tsv", ".txt"}
FORMATS_PDF = {".pdf"}
FORMATS_IMAGE = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}

_EN_TETE_DATE = re.compile(r"(?i)\b(date|derni|observ|ann[ée]e|obs)\b")
_EN_TETE_NIDIF = re.compile(r"(?i)\b(nidif|atlas|code|reproduction|statut biol)\b")
_ANNEE = re.compile(r"\b(19|20)\d{2}\b")


# --------------------------------------------------------------------- modèle

@dataclass
class Depot:
    """Un fichier déposé, avec les trois étiquettes qui le qualifient."""
    chemin: Path
    commune: str = ""          # code INSEE, ou nom
    groupe: str = ""           # oiseaux, mammiferes…
    source: str = ""           # faune-normandie, ODIN…
    consulte_le: str = field(default_factory=lambda: date.today().isoformat())

    @property
    def etiquette(self) -> str:
        bouts = [b for b in (self.source, self.commune) if b]
        return " · ".join(bouts) or self.chemin.name


@dataclass
class Mention:
    """Un nom lu dans un dépôt, avec ce qu'on a pu en tirer."""
    nom_brut: str
    depot: Depot
    cd_ref: str | None = None
    statut: str = "non resolu"
    date_obs: str = ""
    nidification: str = ""
    indice: str = ""           # d'où vient la mention (feuille, page…)

    @property
    def resolu(self) -> bool:
        return self.cd_ref is not None


@dataclass
class Espece:
    """Une espèce consolidée, vue par une ou plusieurs sources."""
    cd_ref: str
    nom_scientifique: str
    nom_commun: str
    groupe: str
    date_obs: str = ""
    nidification: str = ""
    sources: list[str] = field(default_factory=list)
    communes: list[str] = field(default_factory=list)
    noms_recus: list[str] = field(default_factory=list)
    conflits: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"https://inpn.mnhn.fr/espece/cd_nom/{self.cd_ref}"


@dataclass
class Resultat:
    especes: list[Espece] = field(default_factory=list)
    non_resolus: list[Mention] = field(default_factory=list)
    journal: list[str] = field(default_factory=list)

    @property
    def taux_resolution(self) -> float:
        total = len(self.especes) + len(self.non_resolus)
        return len(self.especes) / total if total else 0.0


# ----------------------------------------------------------------- extraction

def _tesseract_disponible() -> str | None:
    """Chemin du binaire Tesseract, qui n'est pas toujours dans le PATH."""
    trouve = shutil.which("tesseract")
    if trouve:
        return trouve
    candidats = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Tesseract-OCR/tesseract.exe",
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    ]
    for c in candidats:
        if c.exists():
            return str(c)
    return None


def _lignes_tableur(chemin: Path) -> list[list[str]]:
    import openpyxl
    wb = openpyxl.load_workbook(chemin, read_only=True, data_only=True)
    lignes: list[list[str]] = []
    for ws in wb.worksheets:
        for brut in ws.iter_rows(values_only=True):
            lignes.append(["" if v is None else str(v).strip() for v in brut])
    wb.close()
    return lignes


def _lignes_texte(chemin: Path) -> list[list[str]]:
    brut = chemin.read_bytes()
    for encodage in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            texte = brut.decode(encodage)
            break
        except UnicodeDecodeError:
            continue
    else:
        return []
    try:
        dialecte = csv.Sniffer().sniff(texte[:4096], delimiters=";,\t|")
        separateur = dialecte.delimiter
    except Exception:  # noqa: BLE001
        separateur = ";" if texte.count(";") > texte.count(",") else ","
    return [[c.strip() for c in ligne]
            for ligne in csv.reader(io.StringIO(texte), delimiter=separateur)]


def _lignes_pdf(chemin: Path) -> list[list[str]]:
    lignes: list[list[str]] = []
    try:
        import pdfplumber
    except ImportError:
        return lignes
    with pdfplumber.open(chemin) as pdf:
        for page in pdf.pages:
            for tableau in page.extract_tables() or []:
                for brut in tableau:
                    lignes.append(["" if c is None else str(c).strip() for c in brut])
            if not (page.extract_tables() or []):
                texte = page.extract_text() or ""
                lignes += [[bout] for bout in texte.splitlines() if bout.strip()]
    return lignes


def _lignes_image(chemin: Path) -> tuple[list[list[str]], str]:
    binaire = _tesseract_disponible()
    if binaire is None:
        return [], ("Tesseract introuvable — capture non lue. Installer Tesseract-OCR, "
                    "ou préférer un export du site quand il en propose un.")
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return [], "pytesseract ou Pillow absent — capture non lue"
    pytesseract.pytesseract.tesseract_cmd = binaire
    texte = pytesseract.image_to_string(Image.open(chemin), lang="fra+eng")
    lignes = [[bout.strip()] for bout in texte.splitlines() if bout.strip()]
    return lignes, ""


def lire_depot(depot: Depot) -> tuple[list[list[str]], str]:
    """Renvoie les lignes brutes du fichier et un éventuel avertissement."""
    suffixe = depot.chemin.suffix.lower()
    if suffixe in FORMATS_TABLEUR:
        return _lignes_tableur(depot.chemin), ""
    if suffixe in FORMATS_TEXTE:
        return _lignes_texte(depot.chemin), ""
    if suffixe in FORMATS_PDF:
        return _lignes_pdf(depot.chemin), ""
    if suffixe in FORMATS_IMAGE:
        return _lignes_image(depot.chemin)
    return [], f"format non pris en charge : {suffixe}"


# ------------------------------------------------- repérage des colonnes

def _colonne_des_noms(lignes: list[list[str]], idx: Index,
                      groupe: str) -> tuple[int, float]:
    """Colonne qui s'apparie le mieux à TaxRef — plus fiable qu'un en-tête.

    Renvoie (index, taux). Un échantillon suffit : l'appariement approché est
    coûteux et on ne cherche ici qu'à départager des colonnes.
    """
    if not lignes:
        return 0, 0.0
    largeur = max(len(l) for l in lignes)
    echantillon = [l for l in lignes if any(c.strip() for c in l)][:60]
    meilleur, taux_max = 0, 0.0
    for col in range(largeur):
        valeurs = [l[col] for l in echantillon if col < len(l) and l[col].strip()]
        if len(valeurs) < 2:
            continue
        touches = sum(
            1 for v in valeurs[:40]
            if normaliser(v) in idx.vern or normaliser(v) in idx.sci
        )
        taux = touches / min(len(valeurs), 40)
        if taux > taux_max:
            meilleur, taux_max = col, taux
    return meilleur, taux_max


def _colonne_par_entete(lignes: list[list[str]], motif: re.Pattern) -> int | None:
    for ligne in lignes[:5]:
        for i, cellule in enumerate(ligne):
            if cellule and motif.search(cellule):
                return i
    return None


def _valeur_date(lignes: list[list[str]], ligne: list[str], col: int | None) -> str:
    if col is not None and col < len(ligne) and ligne[col].strip():
        brut = ligne[col].strip()
        trouve = _ANNEE.search(brut)
        return trouve.group(0) if trouve else brut[:10]
    # Repli : une année isolée quelque part sur la ligne.
    for cellule in ligne:
        trouve = _ANNEE.search(str(cellule))
        if trouve:
            return trouve.group(0)
    return ""


# ------------------------------------------------------------- consolidation

def extraire(depot: Depot, idx: Index, memoire: Memoire | None = None) -> tuple[list[Mention], str]:
    """Lit un dépôt et en tire des mentions appariées."""
    lignes, avertissement = lire_depot(depot)
    if not lignes:
        return [], avertissement or "aucune ligne exploitable"

    col_nom, taux = _colonne_des_noms(lignes, idx, depot.groupe)
    col_date = _colonne_par_entete(lignes, _EN_TETE_DATE)
    col_nidif = _colonne_par_entete(lignes, _EN_TETE_NIDIF)
    if taux < 0.15:
        avertissement = (avertissement or "") + (
            f" colonne des noms peu sûre (taux d'appariement {taux:.0%}) —"
            " vérifier le fichier"
        ).strip()

    # En-tête et préambule : plutôt que de les reconnaître à leurs mots, on
    # commence à la première ligne dont le nom s'apparie. Ce qui précède est
    # du titre, de la légende ou des colonnes — pas des espèces.
    debut = 0
    for i, ligne in enumerate(lignes):
        if col_nom < len(ligne) and ligne[col_nom].strip():
            if idx.apparier(ligne[col_nom], depot.groupe).resolu:
                debut = i
                break

    mentions: list[Mention] = []
    vus: set[str] = set()
    for ligne in lignes[debut:]:
        if col_nom >= len(ligne):
            continue
        brut = (ligne[col_nom] or "").strip()
        if not brut or len(brut) < 3:
            continue
        cle = normaliser(brut)
        # Totaux, numérotations et cellules vidées par le nettoyage : ce ne
        # sont pas des espèces, inutile de les faire relire.
        if not cle or cle.isdigit() or not re.search(r"[a-z]{3}", cle):
            continue
        if cle in vus:
            continue
        vus.add(cle)

        appariement = idx.apparier(brut, depot.groupe)
        cd_ref, statut = appariement.cd_ref, appariement.statut
        if cd_ref is None and memoire is not None:
            appris = memoire.alias(cle)
            if appris:
                cd_ref, statut = appris, "alias"

        mentions.append(Mention(
            nom_brut=brut, depot=depot, cd_ref=cd_ref, statut=statut,
            date_obs=_valeur_date(lignes, ligne, col_date),
            nidification=(ligne[col_nidif].strip()
                          if col_nidif is not None and col_nidif < len(ligne) else ""),
        ))
    return mentions, avertissement


def consolider(depots: list[Depot], idx: Index,
               memoire: Memoire | None = None) -> Resultat:
    """Recoupe tous les dépôts en une liste unique, dédoublonnée par cd_ref."""
    res = Resultat()
    par_espece: dict[str, Espece] = {}

    for depot in depots:
        mentions, avertissement = extraire(depot, idx, memoire)
        res.journal.append(
            f"{depot.chemin.name} — {len(mentions)} mention(s)"
            + (f" · {avertissement}" if avertissement else "")
        )
        for m in mentions:
            if not m.resolu:
                res.non_resolus.append(m)
                continue

            taxon = idx.taxon(m.cd_ref)
            espece = par_espece.get(m.cd_ref)
            if espece is None:
                espece = Espece(
                    cd_ref=m.cd_ref,
                    # LB_NOM, pas NOM_VALIDE : le binôme seul, sans l'auteur.
                    # Dans ses tableaux l'auteur a sa propre colonne.
                    nom_scientifique=taxon.lb_nom if taxon else m.nom_brut,
                    nom_commun=m.nom_brut,
                    groupe=depot.groupe,
                )
                # Nom affiché : ce que la source a écrit, sauf si elle n'a
                # donné que le latin — le tableau d'étude veut le nom français.
                en_latin = (taxon is not None
                            and normaliser(m.nom_brut) == normaliser(taxon.lb_nom))
                espece.nom_commun = (
                    taxon.nom_vern if (en_latin and taxon.nom_vern) else m.nom_brut
                )
                par_espece[m.cd_ref] = espece

            if depot.source and depot.source not in espece.sources:
                espece.sources.append(depot.source)
            if depot.commune and depot.commune not in espece.communes:
                espece.communes.append(depot.commune)
            if m.nom_brut not in espece.noms_recus:
                espece.noms_recus.append(m.nom_brut)

            # Date : on retient la plus récente, et on signale le désaccord.
            if m.date_obs:
                if not espece.date_obs:
                    espece.date_obs = m.date_obs
                elif m.date_obs != espece.date_obs:
                    ancienne, nouvelle = espece.date_obs, m.date_obs
                    espece.date_obs = max(ancienne, nouvelle)
                    conflit = f"dates divergentes : {ancienne} / {nouvelle}"
                    if conflit not in espece.conflits:
                        espece.conflits.append(conflit)

            if m.nidification and not espece.nidification:
                espece.nidification = m.nidification
            elif (m.nidification and espece.nidification
                  and m.nidification != espece.nidification):
                conflit = (f"nidification divergente : {espece.nidification} / "
                           f"{m.nidification}")
                if conflit not in espece.conflits:
                    espece.conflits.append(conflit)

    res.especes = sorted(par_espece.values(), key=lambda e: normaliser(e.nom_commun))
    return res


def apprendre(res: Resultat, corrections: dict[str, str], memoire: Memoire) -> int:
    """Enregistre les appariements corrigés à la main : ils valent pour toujours.

    `corrections` associe un nom brut à un cd_ref. Au bout de quelques études
    sur la même région, le bac des non résolus se vide presque.
    """
    retenus = 0
    for brut, cd_ref in corrections.items():
        cle = normaliser(brut)
        if cle and cd_ref:
            memoire.apprendre_alias(cle, str(cd_ref))
            retenus += 1
    if retenus:
        memoire.enregistrer()
    return retenus
