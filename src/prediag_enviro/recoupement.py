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

#: En-têtes de colonnes. **Sans ancre de fin**, et c'est volontaire : l'OCR
#: d'une capture rend « Nidificatior » pour « Nidification » et « Derniére »
#: pour « Dernière ». Exiger le mot entier faisait manquer l'en-tête, et avec
#: lui toute la colonne — aucun statut de nidification n'était capté.
_EN_TETE_DATE = re.compile(r"(?i)\b(date|derni|observ|ann[ée]e|obs)")
_EN_TETE_NIDIF = re.compile(r"(?i)\b(nidif|atlas|code|reproduction|statut biol)")

#: Lignes examinées pour trouver un en-tête. Cinq ne suffisaient pas — une
#: capture de page entière place le tableau sous le menu du site, et son
#: en-tête n'arrive qu'à la douzième ligne —, mais trente était pire : le
#: menu contient « codes atlas » et « dernières observations », et l'en-tête
#: ainsi trouvé désignait la colonne des noms. D'où la règle qui suit : le
#: contenu désigne la colonne, l'en-tête ne sert que s'il n'a rien trouvé.
_LIGNES_ENTETE = 12

#: Ce à quoi ressemble une date d'observation : jour.mois.année dans une
#: capture de Faune France, année seule dans un export du SINP.
_VALEURS_DATE = re.compile(
    r"^\(?(\d{1,2}[./-]\d{1,2}[./-](19|20)\d{2}|(19|20)\d{2})\)?$")

#: Vocabulaire des statuts de nidification, pour reconnaître la colonne par
#: son contenu — une capture rognée sur le seul tableau n'a plus d'en-tête, ce
#: qui est le cas courant. Les formes sont des préfixes : l'OCR coupe le
#: dernier caractère d'une cellule étroite et rend « probabl » pour
#: « probable ».
_VALEURS_NIDIF = re.compile(r"(?i)^(certain|probabl|possibl|nicheur)")
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


#: Confiance minimale d'un mot reconnu. En dessous, Tesseract rend surtout du
#: bruit de bordure — « Boa » pour une icône, « | » pour un trait de tableau.
_CONFIANCE_MIN = 35

#: Un blanc plus large que ce multiple de la hauteur du texte sépare deux
#: colonnes. Un espace ordinaire vaut environ un tiers de cette hauteur ; le
#: seuil laisse donc passer les espaces d'un nom composé sans couper, et
#: tranche là où le tableau laisse un vide.
_ECART_COLONNE = 1.4


def _langues_ocr(pytesseract) -> tuple[str, str]:
    """Langues à demander, et l'avertissement si le français manque.

    **Une langue absente ne fait pas échouer Tesseract**, qui rend le texte
    reconnu avec les langues restantes sans rien signaler. On lisait donc du
    français avec le seul modèle anglais, et la sortie était rigoureusement
    identique à `lang="eng"` — « Geomantis /arvoides » pour *larvoides*. Le
    silence est le vrai défaut : on vérifie et on le dit.
    """
    try:
        presentes = set(pytesseract.get_languages())
    except Exception:  # noqa: BLE001
        return "fra+eng", ""
    if "fra" in presentes:
        return "fra+eng", ""
    return "eng", ("modèle français absent de Tesseract — les noms vernaculaires "
                   "seront mal lus. Déposer fra.traineddata dans le dossier "
                   "tessdata de Tesseract-OCR.")


def _mots_reconnus(pytesseract, image, langues: str) -> list[dict]:
    """Les mots lus, avec leur position. C'est la position qui fait la colonne."""
    donnees = pytesseract.image_to_data(
        image, lang=langues, config="--psm 6",
        output_type=pytesseract.Output.DICT)
    mots = []
    for i, texte in enumerate(donnees["text"]):
        texte = (texte or "").strip()
        try:
            confiance = float(donnees["conf"][i])
        except (TypeError, ValueError):
            continue
        if texte and confiance >= _CONFIANCE_MIN:
            mots.append({"t": texte, "x": donnees["left"][i],
                         "y": donnees["top"][i], "w": donnees["width"][i],
                         "h": donnees["height"][i]})
    return mots


def _grouper_en_lignes(mots: list[dict]) -> list[list[dict]]:
    """Rassemble les mots dont les centres sont à la même hauteur."""
    lignes: list[list[dict]] = []
    for mot in sorted(mots, key=lambda m: (m["y"], m["x"])):
        centre = mot["y"] + mot["h"] / 2
        place = False
        for ligne in reversed(lignes[-3:]):          # seules les dernières
            ref = ligne[0]
            if abs(centre - (ref["y"] + ref["h"] / 2)) <= ref["h"] * 0.6:
                ligne.append(mot)
                place = True
                break
        if not place:
            lignes.append([mot])
    return lignes


def _decouper_en_colonnes(ligne: list[dict]) -> list[str]:
    """Coupe une ligne là où le blanc dépasse la largeur d'un espace."""
    mots = sorted(ligne, key=lambda m: m["x"])
    hauteur = sorted(m["h"] for m in mots)[len(mots) // 2]
    cellules, courante = [], [mots[0]["t"]]
    precedent = mots[0]
    for mot in mots[1:]:
        if mot["x"] - (precedent["x"] + precedent["w"]) > hauteur * _ECART_COLONNE:
            cellules.append(" ".join(courante))
            courante = []
        courante.append(mot["t"])
        precedent = mot
    cellules.append(" ".join(courante))
    return [c.strip() for c in cellules if c.strip()]


def _lignes_image(chemin: Path) -> tuple[list[list[str]], str]:
    """Lit une capture d'écran de tableau, colonne par colonne.

    **On lisait la capture en lignes de texte, ce qui écrasait les
    colonnes** : chaque ligne du tableau revenait en une cellule unique, si
    bien que le nom, la date et le statut de nidification se mêlaient ou se
    perdaient. Le repérage de la colonne des noms n'avait alors rien à
    départager, et aucune date n'était captée.

    Tesseract sait pourtant rendre la position de chaque mot. On la lui
    demande, on rassemble les mots par hauteur pour reconstituer les lignes,
    puis on coupe là où le blanc s'élargit. Les colonnes d'un tableau rendu en
    HTML — ce que sont ces captures — se retrouvent ainsi sans avoir à figer
    leurs abscisses, qui changent d'un site et d'une largeur de fenêtre à
    l'autre.
    """
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

    langues, avertissement = _langues_ocr(pytesseract)
    mots = _mots_reconnus(pytesseract, Image.open(chemin), langues)
    if not mots:
        return [], (avertissement or "aucun texte reconnu dans la capture")
    lignes = [_decouper_en_colonnes(l) for l in _grouper_en_lignes(mots)]
    return [l for l in lignes if l], avertissement


def lire_depot(depot: Depot) -> tuple[list[list[str]], str]:
    """Renvoie les lignes brutes du fichier et un éventuel avertissement."""
    suffixe = depot.chemin.suffix.lower()
    if suffixe in FORMATS_TABLEUR:
        # openpyxl ne lit que l'OOXML. Un .xls hérité — ce que produisent
        # encore certains exports de portails — le fait lever, et l'exception
        # remontait jusqu'à l'écran alors que le format était proposé au
        # dépôt. Mieux vaut le dire, avec la manœuvre pour s'en sortir.
        try:
            return _lignes_tableur(depot.chemin), ""
        except Exception as erreur:  # noqa: BLE001
            if suffixe == ".xls":
                return [], ("classeur .xls hérité, illisible en l'état — "
                            "rouvrez-le dans Excel et enregistrez-le en .xlsx")
            return [], f"classeur illisible : {erreur}"
    if suffixe in FORMATS_TEXTE:
        return _lignes_texte(depot.chemin), ""
    if suffixe in FORMATS_PDF:
        try:
            return _lignes_pdf(depot.chemin), ""
        except Exception as erreur:  # noqa: BLE001
            return [], f"PDF illisible : {erreur}"
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
    for ligne in lignes[:_LIGNES_ENTETE]:
        for i, cellule in enumerate(ligne):
            if cellule and motif.search(cellule):
                return i
    return None


def _colonne_par_valeurs(lignes: list[list[str]], motif: re.Pattern,
                         minimum: int = 2) -> int | None:
    """Colonne dont les valeurs relèvent d'un vocabulaire connu.

    Repli quand l'en-tête manque. On exige plusieurs occurrences : un mot
    isolé peut venir du bruit de l'OCR, une colonne entière non.
    """
    comptes: dict[int, int] = {}
    for ligne in lignes:
        for i, cellule in enumerate(ligne):
            if cellule and motif.match(cellule.strip()):
                comptes[i] = comptes.get(i, 0) + 1
    if not comptes:
        return None
    meilleure = max(comptes, key=lambda i: comptes[i])
    return meilleure if comptes[meilleure] >= minimum else None


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


#: En deçà de ce taux d'appariement, la colonne des noms est tenue pour
#: introuvable et chaque ligne est fouillée séparément.
_TAUX_COLONNE_SURE = 0.15


#: Formes entières des statuts de nidification, à rétablir après l'OCR qui
#: ampute la dernière lettre d'une cellule étroite : « probabl », « certain ».
#: Un livrable n'a pas à porter la trace de l'outil qui l'a lu.
_NIDIF_ENTIER = {"certain": "certaine", "probabl": "probable",
                 "possibl": "possible", "nicheur": "nicheur"}


def _nidification_lisible(texte: str) -> str:
    """Le statut, écrit en entier."""
    bas = texte.strip().lower()
    for prefixe, entier in _NIDIF_ENTIER.items():
        if bas.startswith(prefixe):
            return entier
    return texte.strip()


#: Ce qu'une capture d'écran colle devant le nom : le nombre d'observations
#: et les pictogrammes que l'OCR rend en « @ », « » », « e ».
_ORNEMENT = re.compile(r"^(?:\s*\d+\s*[x×]|\s*[^\w(]+)+", re.UNICODE)


def _nom_affichable(brut: str, nom_vern: str) -> str:
    """Le nom à imprimer, débarrassé de ce que la lecture a ramassé.

    Le tableau d'étude porte le nom tel que la source l'écrit — c'est son
    vocabulaire, et il a sa valeur. Mais une capture d'écran écrit
    « 1x « Pyrausta aurata » et « @ Eudonia mercurella » : le livrable
    héritait du nombre d'observations et des pictogrammes du site.

    On retire donc l'ornement. S'il reste de quoi douter — un chiffre, une
    arobase, un guillemet au milieu du nom —, on préfère le nom vernaculaire
    de TaxRef, qui est propre. Faute des deux, on rend ce qu'on a : une
    cellule vide serait pire qu'un nom imparfait.
    """
    # La parenthèse n'est pas rognée en tête du motif — elle ouvre souvent le
    # nom scientifique —, mais aucun nom ne commence par elle.
    propre = _ORNEMENT.sub("", str(brut or "")).strip(" .·|-–—(«»")
    if propre and not re.search(r"[\d@«»|~^]", propre):
        return propre
    return nom_vern or propre or str(brut or "").strip()


def _cellule_par_motif(ligne: list[str], motif) -> str:
    """Première cellule de la ligne qui relève d'un motif donné."""
    for cellule in ligne:
        texte = (cellule or "").strip()
        if texte and motif.match(texte):
            return texte
    return ""


#: Rangs taxonomiques qui valent une espèce. Au-dessus — genre, famille,
#: ordre — il faut que la source ait déclaré son indétermination.
_RANGS_ESPECE = frozenset({"ES", "SSES", "VAR", "SVAR", "FO", "CAR", "AB"})

#: Ce par quoi une source annonce qu'elle n'a pas déterminé l'espèce.
#: Sans ancre de fin sur les formes longues : « indéterminée » porte sa
#: terminaison, et l'exiger entière faisait manquer le mot.
_INDETERMINE = re.compile(r"(?i)\b(sp|spp)\b\.?|ind[ée]termin|/")


def _espece_plausible(idx: Index, cd_ref: str, texte: str) -> bool:
    """Le taxon apparié vaut-il une espèce, ou la source le dit-elle indéterminé ?"""
    taxon = idx.taxon(cd_ref)
    if taxon is None or taxon.rang in _RANGS_ESPECE:
        return True
    return bool(_INDETERMINE.search(texte))


def _nom_dans_la_ligne(ligne: list[str], idx: Index, groupe: str) -> tuple[str, int]:
    """Cellule de la ligne qui s'apparie à TaxRef, et son rang.

    **Les captures de page entière décalent les colonnes.** Celle des oiseaux
    porte le menu du site à gauche du tableau, si bien qu'une ligne sur deux
    compte une cellule de plus et que le nom glisse d'un cran. Un index fixe
    ne pouvait pas suivre : il tombait sur la colonne des icônes, avec 2 %
    d'appariement, et l'essentiel des oiseaux se perdait.

    **Mais fouiller toute la ligne, c'est aussi offrir le bruit à TaxRef.**
    Les icônes d'action du site se lisent « Boa », « BOB », « 808 » ; la
    première s'apparie au genre des boas et la deuxième à leur famille, et
    deux serpents fantômes entraient dans le tableau des reptiles. Un
    appariement au-dessus de l'espèce n'est donc retenu que si la source a
    écrit son indétermination — « Pelophylax sp. », « Grenouille
    indéterminée » —, ce qu'une icône ne fait jamais.

    Chercher le nom dans chaque ligne coûte quelques interrogations de TaxRef
    de plus, et ne sert que lorsque la colonne globale a échoué.
    """
    for rang, cellule in enumerate(ligne):
        texte = (cellule or "").strip()
        if len(texte) < 4:
            continue
        appariement = idx.apparier(texte, groupe)
        if not appariement.resolu:
            continue
        if not _espece_plausible(idx, appariement.cd_ref, texte):
            continue
        return texte, rang
    return "", -1


# ------------------------------------------------------------- consolidation

def extraire(depot: Depot, idx: Index, memoire: Memoire | None = None) -> tuple[list[Mention], str]:
    """Lit un dépôt et en tire des mentions appariées."""
    lignes, avertissement = lire_depot(depot)
    if not lignes:
        return [], avertissement or "aucune ligne exploitable"

    col_nom, taux = _colonne_des_noms(lignes, idx, depot.groupe)
    # Le contenu désigne la colonne des dates : une suite de « 09.04.2026 »
    # ne se confond avec rien, là où un en-tête lu par l'OCR, ou un mot du
    # menu du site, désignait la colonne des noms et publiait « 10x Pisaur »
    # comme date d'observation.
    col_date = (_colonne_par_valeurs(lignes, _VALEURS_DATE, minimum=3)
                or _colonne_par_entete(lignes, _EN_TETE_DATE))
    # Le contenu d'abord, l'en-tête ensuite : un en-tête ne se croit pas sans
    # vérification. Élargir sa recherche au-delà des premières lignes lui
    # faisait accrocher un « codes atlas » du menu du site sur des captures
    # sans colonne de nidification, et la colonne des dates se retrouvait
    # publiée comme un statut de reproduction.
    col_nidif = _colonne_par_valeurs(lignes, _VALEURS_NIDIF)
    if col_nidif is None:
        candidate = _colonne_par_entete(lignes, _EN_TETE_NIDIF)
        if candidate is not None and candidate != col_date:
            col_nidif = candidate
    # Le bruit n'existe que dans ce qui a été lu par OCR : un export propre
    # peut légitimement porter un genre seul, une capture non.
    issu_image = depot.chemin.suffix.lower() in FORMATS_IMAGE
    par_ligne = taux < _TAUX_COLONNE_SURE
    if par_ligne:
        avertissement = (avertissement or "") + (
            f" colonnes décalées (appariement de la meilleure : {taux:.0%}) —"
            " lecture ligne à ligne"
        ).strip()

    # En-tête et préambule : plutôt que de les reconnaître à leurs mots, on
    # commence à la première ligne dont le nom s'apparie. Ce qui précède est
    # du titre, de la légende ou des colonnes — pas des espèces.
    debut = 0
    for i, ligne in enumerate(lignes):
        if par_ligne:
            if _nom_dans_la_ligne(ligne, idx, depot.groupe)[0]:
                debut = i
                break
        elif col_nom < len(ligne) and ligne[col_nom].strip():
            if idx.apparier(ligne[col_nom], depot.groupe).resolu:
                debut = i
                break

    mentions: list[Mention] = []
    vus: set[str] = set()
    for ligne in lignes[debut:]:
        if par_ligne:
            brut = _nom_dans_la_ligne(ligne, idx, depot.groupe)[0]
        elif col_nom < len(ligne):
            brut = (ligne[col_nom] or "").strip()
        else:
            continue
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
        if issu_image and cd_ref and not _espece_plausible(idx, cd_ref, brut):
            # « Boa » lu sur une icône d'action s'appariait au genre des
            # boas, et un serpent fantôme entrait dans le tableau des
            # reptiles. Au-dessus de l'espèce, on exige que la source ait
            # écrit son indétermination.
            continue
        if cd_ref is None and memoire is not None:
            appris = memoire.alias(cle)
            if appris:
                cd_ref, statut = appris, "alias"

        mentions.append(Mention(
            nom_brut=brut, depot=depot, cd_ref=cd_ref, statut=statut,
            date_obs=(_cellule_par_motif(ligne, _VALEURS_DATE) if par_ligne
                      else _valeur_date(lignes, ligne, col_date)),
            nidification=_nidification_lisible(
                _cellule_par_motif(ligne, _VALEURS_NIDIF) if par_ligne
                else (ligne[col_nidif].strip()
                      if col_nidif is not None
                      and col_nidif < len(ligne) else "")),
        ))
    return mentions, avertissement


def consolider(depots: list[Depot], idx: Index,
               memoire: Memoire | None = None) -> Resultat:
    """Recoupe tous les dépôts en une liste unique, dédoublonnée par cd_ref."""
    res = Resultat()
    par_espece: dict[str, Espece] = {}

    for depot in depots:
        # Un fichier illisible ne doit pas emporter les autres : un recoupement
        # porte couramment sur cinq ou six dépôts, et perdre les cinq bons
        # parce que le sixième est corrompu obligerait à tout recommencer.
        try:
            mentions, avertissement = extraire(depot, idx, memoire)
        except Exception as erreur:  # noqa: BLE001
            mentions, avertissement = [], f"non lu — {erreur}"
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
                    taxon.nom_vern if (en_latin and taxon.nom_vern)
                    else _nom_affichable(m.nom_brut,
                                         taxon.nom_vern if taxon else "")
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
