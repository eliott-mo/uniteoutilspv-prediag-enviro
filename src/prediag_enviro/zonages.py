"""Zonages du patrimoine naturel croisés avec l'emprise du projet.

Alimente les trois tableaux de l'état initial, dans l'ordre et avec les
colonnes du document de référence :

    Nom | Distance à la ZIP | Identifiant | Intérêt | Aire(s) d'étude concernée(s)

Trois familles, parce que leur portée juridique diffère et que le document les
sépare :

* **inventaire** — ZNIEFF de types I et II, ZICO. Sans opposabilité, mais
  signalent un patrimoine dont il faut tenir compte.
* **natura2000** — ZPS (directive Oiseaux) et ZSC (directive Habitats).
* **autres** — arrêtés de protection de biotope, réserves, terrains de
  conservatoire, espaces naturels sensibles, patrimoine géologique.

Tout vient des archives de l'INPN, téléchargées et figées : une étude se fait
alors sans réseau. Les WFS qui tombent au mauvais moment ne bloquent plus
personne — c'est la leçon de l'outil raccordement, où une matinée s'est perdue
sur un service indisponible.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd

from . import archives

CRS_METRIQUE = 2154

#: Aires d'étude par défaut, d'après le guide du ministère (2016) que cite le
#: document de référence. Les rayons restent modifiables : ils dépendent du
#: projet et des groupes d'espèces concernés.
#: Familles de zonages, dans l'ordre des tableaux 8 à 10 de l'état initial.
FAMILLES = [
    ("inventaire", "Zonages d'inventaire — ZNIEFF"),
    ("natura2000", "Natura 2000 — ZPS et ZSC"),
    ("autres", "Autres zonages du patrimoine naturel"),
]

AIRES_DEFAUT = [
    ("ZIP", "Zone d'implantation potentielle", 0.0),
    ("AEI", "Aire d'étude immédiate", 200.0),
    ("AER", "Aire d'étude rapprochée", 5000.0),
]


@dataclass(frozen=True)
class AireEtude:
    code: str            # ZIP, AEI, AER
    libelle: str
    rayon_m: float


@dataclass
class SourceZonage:
    """Comment tirer une couche de zonages d'une archive INPN."""
    cle: str                       # identifiant interne
    archive: str                   # clé dans sources.yml
    motif_shp: str                 # fragment du nom du shapefile
    famille: str                   # inventaire | natura2000 | autres
    type_libelle: str              # « ZNIEFF de type I », « ZPS »…
    colonnes_id: tuple[str, ...]   # candidats pour l'identifiant
    colonnes_nom: tuple[str, ...]  # candidats pour le nom
    #: Texte descriptif : soit une colonne du shapefile, soit un CSV à joindre.
    colonnes_interet: tuple[str, ...] = ()
    csv_interet: str = ""
    csv_cle: str = ""
    csv_colonnes: tuple[str, ...] = ()
    #: Filtre sur une colonne (Natura 2000 mêle ZPS et ZSC, les espaces
    #: protégés mêlent trente-six types dans une seule couche).
    filtre_colonne: str = ""
    filtre_valeurs: tuple[str, ...] = ()
    #: Couche d'un GeoPackage, quand le format n'est pas le shapefile.
    couche: str = ""
    #: Rattachement des textes descriptifs, propre à chaque base.
    enrichir: "Callable | None" = None


@dataclass
class Zonage:
    """Un zonage retenu, tel qu'il apparaîtra dans le tableau."""
    famille: str
    type: str
    identifiant: str
    nom: str
    interet: str
    distance_m: float
    aires: list[str] = field(default_factory=list)

    @property
    def distance_lisible(self) -> str:
        if self.distance_m < 10:
            return "incluse"
        if self.distance_m < 1000:
            return f"{int(round(self.distance_m / 10) * 10)} m"
        return f"{self.distance_m / 1000:.1f} km".replace(".", ",")

    @property
    def url(self) -> str:
        return f"https://inpn.mnhn.fr/zone/{self.identifiant}"


@dataclass
class Resultat:
    zonages: list[Zonage] = field(default_factory=list)
    journal: list[str] = field(default_factory=list)
    manquants: list[str] = field(default_factory=list)
    #: Géométries des zonages retenus, par type. Conservées pour la carto :
    #: les retrouver demanderait de refaire le croisement, qui prend une
    #: trentaine de secondes.
    geometries: dict[str, "gpd.GeoDataFrame"] = field(default_factory=dict)
    #: Couches locales employées — ENS et autres zonages sans source nationale
    #: fiable. Elles doivent figurer en bibliographie avec leur date.
    sources_locales: list = field(default_factory=list)
    #: Ce qu'il faut dire au lecteur sur ces zonages : une couche qui se sait
    #: incomplète, ou aucune source enregistrée pour le département.
    avertissements: list[str] = field(default_factory=list)

    def couches(self, famille: str) -> dict[str, "gpd.GeoDataFrame"]:
        """Géométries d'une famille, prêtes à cartographier."""
        types = {z.type for z in self.par_famille(famille)}
        return {t: g for t, g in self.geometries.items() if t in types}

    def par_famille(self, famille: str) -> list[Zonage]:
        return [z for z in self.zonages if z.famille == famille]

    def resume(self) -> str:
        """Phrase de synthèse, du genre de celles qui ouvrent les sections."""
        if not self.zonages:
            return "Aucun zonage du patrimoine naturel dans les aires d'étude."
        compte: dict[str, int] = {}
        for z in self.zonages:
            compte[z.type] = compte.get(z.type, 0) + 1
        bouts = [f"{n} {pluriel(t, n)}"
                 for t, n in sorted(compte.items(), key=lambda x: -x[1])]
        return "Dans les aires d'étude : " + ", ".join(bouts) + "."


def _premiere_colonne(gdf: gpd.GeoDataFrame, candidats: tuple[str, ...]) -> str | None:
    """Première colonne présente parmi les candidats, casse ignorée.

    Les shapefiles tronquent les noms de champs à dix caractères et l'INPN n'a
    pas la même convention d'une base à l'autre ; on cherche donc plusieurs
    orthographes plutôt que d'en figer une.
    """
    bas = {c.lower(): c for c in gdf.columns}
    for candidat in candidats:
        if candidat.lower() in bas:
            return bas[candidat.lower()]
    for candidat in candidats:
        for nom_bas, nom in bas.items():
            if nom_bas.startswith(candidat.lower()[:8]):
                return nom
    return None


#: Couches déjà lues, par (archive, motif, couche). Les quatorze types
#: d'espaces protégés vivent dans un même GeoPackage de 148 Mo : le relire
#: quatorze fois coûterait des minutes pour un résultat identique.
_COUCHES: dict[tuple, gpd.GeoDataFrame] = {}


def charger_source(source: SourceZonage, archives_dir: Path, cache: Path,
                   fichiers: dict[str, str]) -> gpd.GeoDataFrame:
    """Charge et normalise une couche de zonages."""
    chemin = archives_dir / fichiers[source.archive]
    empreinte = (str(chemin), source.motif_shp, source.couche)
    brute = _COUCHES.get(empreinte)
    if brute is None:
        brute = archives.charger_couche(chemin, source.motif_shp, cache,
                                        CRS_METRIQUE, couche=source.couche or None)
        _COUCHES[empreinte] = brute
    # Copie obligatoire : la couche en cache est partagée entre les sources qui
    # la découpent, et les colonnes normalisées ajoutées plus bas la
    # pollueraient — la source suivante lirait les `_id` de la précédente.
    gdf = brute
    if source.filtre_colonne and source.filtre_valeurs:
        colonne = _premiere_colonne(gdf, (source.filtre_colonne,))
        if colonne is not None:
            valeurs = {v.lower() for v in source.filtre_valeurs}
            gdf = gdf[gdf[colonne].astype(str).str.lower().isin(valeurs)]
    gdf = gdf.copy()

    col_id = _premiere_colonne(gdf, source.colonnes_id)
    col_nom = _premiere_colonne(gdf, source.colonnes_nom)
    col_interet = (_premiere_colonne(gdf, source.colonnes_interet)
                   if source.colonnes_interet else None)

    gdf["_id"] = gdf[col_id].astype(str).str.strip() if col_id else ""
    gdf["_nom"] = gdf[col_nom].astype(str).str.strip() if col_nom else ""
    gdf["_interet"] = gdf[col_interet].astype(str).str.strip() if col_interet else ""

    # Texte descriptif porté par un CSV plutôt que par le shapefile.
    if source.csv_interet and source.csv_cle:
        index = archives.lire_csv(chemin, source.csv_interet,
                                  colonnes=list(source.csv_colonnes) or None,
                                  cle=source.csv_cle)
        champs = [c for c in source.csv_colonnes if c != source.csv_cle]

        def _texte(identifiant: str) -> str:
            ligne = index.get(identifiant)
            if not ligne:
                return ""
            bouts = [str(ligne.get(c, "")).strip() for c in champs]
            return " ".join(b for b in bouts if b).strip()

        rattaches = gdf["_id"].map(_texte)
        gdf["_interet"] = [a or b for a, b in zip(gdf["_interet"], rattaches)]
        if not col_nom:
            nom_csv = next((c for c in champs if "lb" in c or "nom" in c), None)
            if nom_csv:
                gdf["_nom"] = gdf["_id"].map(
                    lambda i: str((index.get(i) or {}).get(nom_csv, "")).strip()
                )

    return gdf


def croiser(emprise, sources: list[SourceZonage], archives_dir: Path, cache: Path,
            fichiers: dict[str, str],
            aires: list[AireEtude] | None = None) -> Resultat:
    """Zonages présents dans les aires d'étude, avec distance et appartenance.

    `emprise` est la géométrie du projet en Lambert-93 ; les distances sont
    donc des mètres au sol, et non des degrés.
    """
    aires = aires or [AireEtude(c, l, r) for c, l, r in AIRES_DEFAUT]
    portee = max(a.rayon_m for a in aires)
    res = Resultat()
    x0, y0, x1, y1 = emprise.bounds
    fenetre = (x0 - portee, y0 - portee, x1 + portee, y1 + portee)

    for source in sources:
        chemin = archives_dir / fichiers.get(source.archive, "")
        if not chemin.exists():
            res.manquants.append(
                f"{source.type_libelle} — archive {source.archive} absente"
            )
            continue
        try:
            gdf = charger_source(source, archives_dir, cache, fichiers)
        except Exception as erreur:  # noqa: BLE001
            res.manquants.append(f"{source.type_libelle} — {erreur}")
            continue

        # Pré-filtre par l'index spatial : la couche nationale porte des
        # dizaines de milliers de polygones, en calculer la distance une à une
        # serait absurde quand l'étude tient dans quelques kilomètres carrés.
        proches = gdf.iloc[list(gdf.sindex.intersection(fenetre))].copy()
        if proches.empty:
            res.journal.append(f"{source.type_libelle} : aucun dans la fenêtre")
            continue

        proches["_d"] = proches.geometry.distance(emprise)
        retenus = proches[proches["_d"] <= portee].sort_values("_d").copy()

        # Les textes descriptifs ne sont rattachés qu'aux zonages retenus :
        # enrichir les 17 199 ZNIEFF de type I du territoire pour n'en garder
        # onze coûtait une minute par croisement.
        if source.enrichir is not None and not retenus.empty:
            retenus = source.enrichir(retenus, archives_dir / fichiers[source.archive])
        res.journal.append(
            f"{source.type_libelle} : {len(retenus)} dans les aires d'étude "
            f"(sur {len(gdf)} au national)"
        )

        res.geometries[source.type_libelle] = retenus[["_nom", "_id", "geometry"]]

        for _, ligne in retenus.iterrows():
            distance = float(ligne["_d"])
            res.zonages.append(Zonage(
                famille=source.famille, type=source.type_libelle,
                identifiant=str(ligne["_id"]), nom=str(ligne["_nom"]),
                interet=str(ligne["_interet"]),
                distance_m=distance,
                aires=[a.code for a in aires if distance <= a.rayon_m],
            ))

    res.zonages.sort(key=lambda z: (z.famille, z.type, z.distance_m))
    return res


# ════════════════════════════════════════════════════════════════════════════
#  Enrichissement : le texte « Intérêt », colonne la plus coûteuse à la main
# ════════════════════════════════════════════════════════════════════════════

import re  # noqa: E402

_BALISE = re.compile(r"<[^>]+>")
_ESPACES = re.compile(r"\s+")


def nettoyer_texte(brut: str, limite: int = 900) -> str:
    """Les textes de l'INPN arrivent en HTML : balises et entités.

    L'ordre compte. On décode les entités d'abord, on retire les balises
    ensuite : l'inverse laisserait un `&lt;i&gt;` se transformer en `<i>` une
    fois les balises déjà parties, et la balise ressortirait dans le livrable.

    `html.unescape` plutôt qu'une liste de remplacements : la première version
    traitait `&nbsp;`, `&amp;`, `&lt;`, `&gt;` et `&#39;` et laissait passer
    tous les accents — « basse vall&eacute;e de la Theze ». 14 % des zonages
    étaient touchés, dans 94 départements sur 96.
    """
    import html

    texte = html.unescape(str(brut or ""))
    texte = _BALISE.sub(" ", texte)
    texte = _ESPACES.sub(" ", texte).strip()
    # Description entièrement entre guillemets : plusieurs rédacteurs de
    # fiches ZNIEFF citent leur propre texte. Le guillemet fermant tombe au-delà
    # de la troncature, si bien que seul l'ouvrant arrive dans la cellule — et
    # compter les guillemets pour détecter l'orphelin ne suffisait donc pas,
    # puisqu'ils sont bien deux dans la source.
    if texte.startswith('"'):
        if texte.endswith('"'):
            texte = texte[1:-1].strip()
        elif texte.endswith('".'):
            texte = texte[1:-2].strip() + "."
        elif texte.count('"') % 2 == 1:
            # Ouvrant sans fermant : rien à préserver.
            texte = texte[1:].lstrip()
        # Sinon le rédacteur cite un passage précis : ses guillemets restent.
    if len(texte) <= limite:
        return texte
    coupe = texte[:limite].rsplit(". ", 1)[0]
    return (coupe + ".") if len(coupe) > limite * 0.5 else texte[:limite].rstrip() + "…"


#: Particules qui restent en bas de casse à l'intérieur d'un nom.
#: « à » autant que « a » : les sources mêlent les deux, et un nom déjà en
#: casse mixte porte souvent la forme accentuée — « Frayère À Esturgeons ».
_PARTICULES = {"de", "du", "des", "d", "la", "le", "les", "l", "a", "à",
               "au", "aux", "en", "et", "sur", "sous", "pres", "près",
               "vers", "par", "dans", "entre", "lez", "lès", "ou"}

#: Noms communs qui ne prennent pas de capitale, sauf en tête de nom.
#:
#: Les noms de ZNIEFF suivent presque tous la même forme : un type de milieu,
#: puis un toponyme — « RUISSEAU DE LA GORGE DE CHATRICES », « PRAIRIES AUTOUR
#: DE L'ETANG DES BERCETTES ». Le type de milieu ouvre le nom et garde donc sa
#: capitale ; les noms communs qui suivent ne devraient pas en avoir. Cette
#: liste est ce qui sépare « Bois alluviaux, marais, bras morts et fleuve la
#: Seine » de « Bois Alluviaux, Marais, Bras Morts et Fleuve la Seine ».
#:
#: Les formes sont **accentuées** : la correction des accents s'applique avant
#: cette recherche.
_COMMUNS = {
    # orientations et situations
    "nord", "sud", "est", "ouest", "nord-est", "nord-ouest", "sud-est",
    "sud-ouest", "amont", "aval", "autour", "abords", "bord", "bords",
    "environs", "confluence", "confluent", "partie", "secteur", "ensemble",
    "haute", "hautes", "haut", "hauts", "basse", "basses", "bas",
    "ancien", "ancienne", "anciens", "anciennes", "petit", "petite", "petits",
    "petites", "grand", "grande", "grands", "grandes", "vieux", "vieille",
    # milieux
    "bois", "boisement", "boisements", "forêt", "forêts", "forestier",
    "forestière", "massif", "hêtraie", "chênaie", "aulnaie", "ripisylve",
    "prairie", "prairies", "pelouse", "pelouses", "lande", "landes",
    "pâture", "pâtures", "verger", "vergers", "friche", "friches",
    "marais", "tourbière", "tourbières", "roselière", "roselières",
    "étang", "étangs", "mare", "mares", "lac", "lacs", "rivière", "rivières",
    "ruisseau", "ruisseaux", "fleuve", "cours", "eau", "eaux", "source",
    "sources", "vallée", "vallées", "vallon", "vallons", "gorge", "gorges",
    "combe", "combes", "plaine", "plaines", "plateau", "coteau", "coteaux",
    "butte", "buttes", "côtes", "falaise", "falaises", "carrière",
    "carrières", "sablière", "gravière", "bras", "méandre", "méandres",
    "île", "îles", "boucle", "bassin", "versant", "zone", "zones", "site",
    "sites", "pont", "moulin", "château", "église", "ferme", "gîte", "gîtes",
    # qualificatifs fréquents
    "alluviaux", "alluviale", "alluviales", "humide", "humides", "morts",
    "morte", "mortes", "sèche", "sèches", "calcaire", "calcaires",
    "siliceux", "tourbeux", "tourbeuse", "boisé", "boisée", "boisés",
}

#: Accents perdus par la mise en capitales de la source. Volontairement court
#: et sans ambiguïté : « COTE » peut être une côte, un coteau ou la Côte 304
#: de Verdun, donc il n'y figure pas.
_ACCENTS = {
    "foret": "forêt", "forets": "forêts", "forestiere": "forestière",
    "riviere": "rivière", "rivieres": "rivières", "etang": "étang",
    "etangs": "étangs", "vallee": "vallée", "vallees": "vallées",
    "ile": "île", "iles": "îles", "chateau": "château", "eglise": "église",
    "chene": "chêne", "chenes": "chênes", "chenaie": "chênaie",
    "hetre": "hêtre", "hetraie": "hêtraie", "frene": "frêne",
    "frenes": "frênes", "tete": "tête", "reserve": "réserve",
    "tourbiere": "tourbière", "tourbieres": "tourbières", "paturе": "pâture",
    "pature": "pâture", "patures": "pâtures", "roseliere": "roselière",
    "roselieres": "roselières", "carriere": "carrière",
    "carrieres": "carrières", "graviere": "gravière",
    "sabliere": "sablière", "meandre": "méandre", "meandres": "méandres",
    "seche": "sèche", "seches": "sèches", "boise": "boisé",
    "boisee": "boisée", "boises": "boisés", "gite": "gîte", "gites": "gîtes",
}

#: Sigles à garder en capitales, énumérés plutôt que devinés.
#:
#: Une règle de longueur avait été essayée — « tout mot de trois lettres ou
#: moins en capitales est un sigle ». Elle ne pouvait pas marcher : la fonction
#: ne traite que des noms **entièrement** en capitales, où rien ne distingue
#: un sigle d'un mot court. « PELOUSES SECHES DE LA COTE DE BAR » sortait
#: « de la Cote de BAR », alors que c'est la ville de Bar.
_SIGLES = {"CEN", "ONF", "PNR", "RNN", "RNR", "RNC", "APB", "APPB", "ZPS",
           "ZSC", "SIC", "ZNIEFF", "ZICO", "INPG", "ENS", "RD", "RN", "A",
           "EDF", "SNCF", "LPO", "UNESCO", "CBN", "DREAL", "OFB", "MNHN",
           "VNF", "CELRL", "SMA", "EPTB"}

#: Caractères qui entourent un mot sans en faire partie.
_BORDURE = "«»\"'()[].,;:!?…"


def _mot_lisible(mot: str, premier: bool) -> str:
    """Un mot d'un nom, passé des capitales à la casse de lecture.

    L'ordre des tests compte. Le découpage sur les apostrophes et les traits
    d'union vient **avant** le test du chiffre : « L'A4 » porte un chiffre, et
    le tester d'abord renvoyait le mot intact — donc « L'A4 » au lieu de
    « l'A4 ».
    """
    # La ponctuation encadrante se met de côté : sans cela « MARAIS, » ne
    # s'apparie à aucun nom commun et garde une capitale.
    tete = ""
    while mot and mot[0] in _BORDURE:
        tete, mot = tete + mot[0], mot[1:]
    queue = ""
    while mot and mot[-1] in _BORDURE:
        queue, mot = mot[-1] + queue, mot[:-1]
    if not mot:
        return tete + queue

    for separateur in ("'", "\u2019", "-"):
        if separateur in mot:
            bouts = mot.split(separateur)
            # Un nom composé n'est « premier » que par son premier segment,
            # pour que « CLERMONT-EN-ARGONNE » donne « Clermont-en-Argonne ».
            recompose = separateur.join(
                _mot_lisible(bout, premier and rang == 0)
                for rang, bout in enumerate(bouts)
            )
            return tete + recompose + queue

    # Les codes et les immatriculations restent intacts : « A4 », « 903 ».
    if any(c.isdigit() for c in mot):
        return tete + mot + queue

    bas = _ACCENTS.get(mot.lower(), mot.lower())
    if not premier:
        if bas == "a":
            return tete + "à" + queue   # « RUISSEAU A FUTEAU » : préposition
        if bas in _PARTICULES or bas in _COMMUNS:
            return tete + bas + queue
    if mot.upper() in _SIGLES:
        return tete + mot.upper() + queue
    return tete + bas[:1].upper() + bas[1:] + queue


def _abaisser_particules(nom: str) -> str:
    """Abaisse les particules capitalisées d'un nom déjà en casse mixte.

    Geste chirurgical : seuls les mots de `_PARTICULES` sont touchés, et
    seulement hors première position. Tout le reste est laissé intact, parce
    qu'un nom en casse mixte peut être correctement écrit et qu'on n'a aucun
    moyen de distinguer « Mandallaz » d'un nom commun mal capitalisé.

    Un nom correctement écrit n'a pas de particule capitalisée : la
    transformation ne peut donc pas l'abîmer.
    """
    mots = nom.split()
    sortie = []
    for rang, mot in enumerate(mots):
        tete = ""
        noyau = mot
        while noyau and noyau[0] in _BORDURE:
            tete, noyau = tete + noyau[0], noyau[1:]
        queue = ""
        while noyau and noyau[-1] in _BORDURE:
            queue, noyau = noyau[-1] + queue, noyau[:-1]
        # « L'Abreuvoir » : seule la particule qui précède l'apostrophe bouge.
        for separateur in ("'", "\u2019"):
            if separateur in noyau:
                avant, _, apres = noyau.partition(separateur)
                if rang > 0 and avant.lower() in _PARTICULES:
                    noyau = avant.lower() + separateur + apres
                break
        else:
            if rang > 0 and noyau.lower() in _PARTICULES:
                noyau = noyau.lower()
        sortie.append(tete + noyau + queue)
    return " ".join(sortie)


def casse_lisible(nom: str) -> str:
    """Rend lisible un nom, quelle que soit la casse que la source lui donne.

    Les sources en mêlent quatre, et la couche des espaces protégés les a
    toutes : « PUITS D'ENFER », « etang de vigneulles », « Ruisseau De
    L'Abreuvoir » et « Montagne de la Mandallaz ». Seule la dernière est
    correctement écrite.

    **Tout en capitales, ou tout en minuscules** — la source n'a pas tranché la
    casse, on la pose : chaque mot prend sa capitale sauf les particules et les
    noms communs de `_COMMUNS`. Le passage en bas de casse pur avait été essayé
    et abandonné : il donnait « fleuve la seine » et « la villeneuve-au-
    chatelot », soit des noms propres décapitalisés — des fautes introduites
    par l'outil, plus discrètes que les capitales qu'elles remplaçaient.
    Il reste une imprécision assumée : un nom commun absent de `_COMMUNS` prend
    une capitale de trop. Coquille visible et corrigeable en un geste, préférée
    à une faute sur un nom propre.

    **Casse mixte** — la source a tranché, et elle peut avoir raison. On ne
    touche alors qu'aux particules capitalisées, qui sont une faute certaine :
    « Ruisseau De L'Abreuvoir » devient « Ruisseau de l'Abreuvoir », tandis que
    « Montagne de la Mandallaz » ressort intacte.
    """
    brut = str(nom or "").strip()
    lettres = [c for c in brut if c.isalpha()]
    if not lettres:
        return brut
    if any(c.islower() for c in lettres) and any(c.isupper() for c in lettres):
        return _abaisser_particules(brut)
    return " ".join(_mot_lisible(mot, rang == 0)
                    for rang, mot in enumerate(brut.split()))


#: Pluriel de chaque type de zonage, écrit à la main.
#:
#: Une règle automatique ne tient pas : « ZNIEFF de type I » est invariable,
#: « Zone Spéciale de Conservation » accorde deux mots, « Parc national » fait
#: « Parcs nationaux » et « Site Ramsar » garde son nom propre au singulier.
#: Dix-huit entrées écrites une fois valent mieux qu'un algorithme qui se
#: trompe sur un cas tous les cinq rapports.
PLURIELS = {
    "ZNIEFF de type I": "ZNIEFF de type I",
    "ZNIEFF de type II": "ZNIEFF de type II",
    "Zone de Protection Spéciale": "Zones de Protection Spéciale",
    "Zone Spéciale de Conservation": "Zones Spéciales de Conservation",
    "Arrêté de protection de biotope": "Arrêtés de protection de biotope",
    "Arrêté de protection d'habitats": "Arrêtés de protection d'habitats",
    "Réserve naturelle nationale": "Réserves naturelles nationales",
    "Réserve naturelle régionale": "Réserves naturelles régionales",
    "Réserve naturelle de Corse": "Réserves naturelles de Corse",
    "Réserve biologique dirigée": "Réserves biologiques dirigées",
    "Réserve biologique intégrale": "Réserves biologiques intégrales",
    "Parc national (zone cœur)": "Parcs nationaux (zone cœur)",
    "Parc national (aire d'adhésion)": "Parcs nationaux (aire d'adhésion)",
    "Parc naturel régional": "Parcs naturels régionaux",
    "Terrain de Conservatoire d'espaces naturels":
        "Terrains de Conservatoire d'espaces naturels",
    "Terrain du Conservatoire du Littoral":
        "Terrains du Conservatoire du Littoral",
    "Site Ramsar": "Sites Ramsar",
    # Déposé par l'équipe, pas issu du registre national : les ENS n'ont pas
    # de couche nationale fiable (voir sources_locales.py).
    "Espace Naturel Sensible": "Espaces Naturels Sensibles",
    "Site d'intérêt géologique (INPG)": "Sites d'intérêt géologique (INPG)",
}


def pluriel(type_libelle: str, nombre: int) -> str:
    """Le type au nombre voulu — « 2 Zones de Protection Spéciale »."""
    if nombre <= 1:
        return type_libelle
    return PLURIELS.get(type_libelle, type_libelle)


#: Le nom scientifique s'arrête au premier mot qui n'est pas une épithète :
#: une capitale, une parenthèse ou un chiffre ouvre la citation d'auteur.
_EPITHETE = re.compile(r"^[a-zà-ÿ][a-zà-ÿ-]*$")
_RANG_INFRA = {"subsp.", "ssp.", "var.", "f.", "cv."}


def nom_scientifique_court(cite: str) -> str:
    """« Achillea millefolium L., 1753 » devient « Achillea millefolium ».

    Les noms cités des fiches ZNIEFF portent leur auteur et sa date, sous des
    formes qui ne se ramènent pas à une seule expression : « Alnus glutinosa
    (L.) Gaertn., 1790 », « Baetis Leach, 1815 », « Cordulia aenea (Linnaeus,
    1758) », « Myotis alcathoe Helversen & Heller, 2001 ». Une première version
    ne retirait que les auteurs entre parenthèses en fin de chaîne, et laissait
    donc passer la plupart des cas : le tableau d'une seule ZNIEFF affichait
    cinquante-six noms suivis de leur bibliographie.

    On s'appuie sur la forme du nom plutôt que sur celle de l'auteur : un genre
    capitalisé, puis des épithètes en bas de casse. Le premier mot qui n'en est
    pas une termine le nom.
    """
    mots = str(cite or "").strip().split()
    if not mots:
        return ""
    garde = [mots[0]]
    for mot in mots[1:]:
        if mot in _RANG_INFRA or _EPITHETE.match(mot):
            garde.append(mot)
            continue
        break
    return " ".join(garde)


def _enrichir_znieff(gdf, chemin: Path):
    """Description générale + espèces déterminantes groupées par taxon.

    C'est la forme même qu'emploie le document de référence : un paragraphe de
    présentation, puis « La création de cette ZNIEFF a été motivée par la
    présence d'espèces déterminantes : Odonates : … / Flore : … ».
    """
    from collections import defaultdict

    fiches = archives.lire_csv(chemin, "REF_ZNIEFF",
                               colonnes=["NM_SFFZN", "LB_ZN", "TX_GENE", "TX_INTERET"],
                               cle="NM_SFFZN")
    especes: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for ligne in archives.lire_csv(chemin, "REF_ESPECE.csv",
                                   colonnes=["nm_sffzn", "groupe_taxo", "nom_cite",
                                             "fg_supp"]):
        if (ligne.get("fg_supp") or "").strip().lower() == "true":
            continue
        numero = (ligne.get("nm_sffzn") or "").strip()
        groupe = (ligne.get("groupe_taxo") or "").strip() or "Autres"
        # Le nom cité porte son auteur et sa date : dans un tableau de
        # synthèse, la citation encombre sans rien apporter.
        nom = nom_scientifique_court(
            nettoyer_texte(ligne.get("nom_cite") or "", 120))
        if numero and nom:
            especes[numero][groupe].add(nom)

    def _sans_repetition(texte: str, nom: str) -> str:
        """Retire la redite du nom en tête de description.

        Les fiches lorraines se contentent souvent de reprendre le nom suivi
        d'un comptage — « FORÊT D'ARGONNE AU NORD DE L'A4 (1 espèce
        confidentielle et 56 espèces déterminantes) ». Le nom figure déjà dans
        la colonne d'à côté du tableau : le répéter occupe une place qui
        manque au reste.
        """
        if not texte or not nom:
            return texte
        # Comparaison sur les chaînes brutes, et non sur une forme normalisée :
        # la position de coupe est une longueur de caractères, donc elle n'a de
        # sens que si les deux chaînes sont comparées telles quelles. Une
        # version antérieure comparait les formes normalisées — sans accents ni
        # ponctuation, donc de longueur différente — puis coupait le texte brut
        # à la longueur du nom brut. Elle appelait de surcroît un `normaliser`
        # jamais importé : la fonction levait une NameError dès qu'elle était
        # atteinte, ce qui faisait échouer toute reconstruction d'extraits.
        # Le nom et la description viennent de la même fiche : ils portent les
        # mêmes accents, et la casse seule peut différer.
        if texte[:len(nom)].casefold() != nom.casefold():
            return texte
        reste = texte[len(nom):].lstrip(" :–—-(")
        reste = reste.rstrip(" )")
        # Ce qui reste est souvent un simple comptage — « 1 espèce
        # confidentielle et 56 espèces déterminantes » — qui n'apprend rien
        # puisque les espèces sont énumérées juste après, dans la même cellule.
        # Une phrase de description porte au moins un point ; un comptage, non.
        if "." not in reste:
            return ""
        return reste

    def _texte(numero: str) -> str:
        fiche = fiches.get(numero) or {}
        brut = nettoyer_texte(fiche.get("TX_GENE") or fiche.get("TX_INTERET") or "")
        bouts = [_sans_repetition(brut, str(fiche.get("LB_ZN") or "").strip())]
        groupes = especes.get(numero)
        if groupes:
            # L'échantillon se resserre quand une description existe déjà : la
            # cellule d'un tableau doit rester lisible, et une ZNIEFF de type II
            # porte parfois deux cents espèces déterminantes. Quand la fiche n'a
            # pas de description, cette énumération est la seule information
            # disponible et vaut qu'on lui laisse de la place.
            avec_description = bool(bouts and bouts[0])
            max_groupes, max_noms = (3, 4) if avec_description else (5, 6)
            details = []
            for groupe, noms in sorted(groupes.items(), key=lambda x: -len(x[1])):
                echantillon = sorted(noms)[:max_noms]
                reste = len(noms) - max_noms
                suite = f" et {reste} autres" if reste > 0 else ""
                details.append(f"{groupe} : {', '.join(echantillon)}{suite}")
            bouts.append("Espèces déterminantes — "
                         + " · ".join(details[:max_groupes]) + ".")
        return " ".join(b for b in bouts if b)

    gdf["_interet"] = gdf["_id"].map(_texte)
    manquants = gdf["_nom"].eq("") | gdf["_nom"].isna()
    if manquants.any():
        gdf.loc[manquants, "_nom"] = gdf.loc[manquants, "_id"].map(
            lambda i: (fiches.get(i) or {}).get("LB_ZN", "")
        )
    gdf["_nom"] = gdf["_nom"].map(casse_lisible)
    return gdf


def _enrichir_natura(gdf, chemin: Path):
    """Nom du site et caractérisation : le shapefile ne porte que le code."""
    sites = archives.lire_csv(chemin, "biotop.csv",
                              colonnes=["sitecode", "site_name", "cd_sig"],
                              cle="cd_sig")
    commentaires = archives.lire_csv(chemin, "commentaire.csv",
                                     colonnes=["sitecode", "charact", "quality"],
                                     cle="sitecode")

    def _nom(cd_sig: str) -> str:
        return (sites.get(cd_sig) or {}).get("site_name", "")

    def _code(cd_sig: str) -> str:
        # cd_sig vaut « I098FR5312003 » : le code du site en est la fin.
        fiche = sites.get(cd_sig) or {}
        if fiche.get("sitecode"):
            return fiche["sitecode"]
        trouve = re.search(r"(FR\d{7,})", str(cd_sig))
        return trouve.group(1) if trouve else str(cd_sig)

    def _texte(cd_sig: str) -> str:
        fiche = commentaires.get(_code(cd_sig)) or {}
        bouts = [nettoyer_texte(fiche.get("charact") or "", 600),
                 nettoyer_texte(fiche.get("quality") or "", 500)]
        return " ".join(b for b in bouts if b)

    gdf["_nom"] = gdf["_id"].map(_nom)
    gdf["_interet"] = gdf["_id"].map(_texte)
    gdf["_id"] = gdf["_id"].map(_code)
    return gdf


def _enrichir_inpg(gdf, chemin: Path):
    """Libellé et présentation succincte du site géologique."""
    # La présentation succincte manque sur une partie des fiches — le
    # Santonien de la Butte des Hauts Buissons n'en a pas, mais porte une
    # description géologique nourrie. On prend la première renseignée plutôt
    # que de rendre une colonne vide là où la donnée existe.
    champs = ["present_succincte", "descr_geol", "descr_phys", "interet_hist_geol"]
    fiches = archives.lire_csv(
        chemin, "inpg_data_site.csv",
        colonnes=["identifiant_metier", "lb_site", *champs],
        cle="identifiant_metier")

    def _texte(identifiant: str) -> str:
        fiche = fiches.get(identifiant) or {}
        for champ in champs:
            valeur = nettoyer_texte(fiche.get(champ) or "")
            if valeur:
                return valeur
        return ""

    gdf["_nom"] = gdf["_id"].map(
        lambda i: casse_lisible((fiches.get(i) or {}).get("lb_site", "")))
    gdf["_interet"] = gdf["_id"].map(_texte)
    return gdf


# ════════════════════════════════════════════════════════════════════════════
#  Registre des sources
# ════════════════════════════════════════════════════════════════════════════

#: Types d'espaces protégés retenus, groupés comme le document les présente.
#: La couche nationale en porte trente-six ; tous ne relèvent pas d'un prédiag
#: de parc photovoltaïque terrestre (conventions marines, biens UNESCO…).
_TYPES_EP = {
    "Arrêté de protection de biotope": "Arrêté de protection de biotope",
    "Arrêté de protection des habitats naturels": "Arrêté de protection d'habitats",
    "Réserve naturelle nationale": "Réserve naturelle nationale",
    "Réserve naturelle régionale": "Réserve naturelle régionale",
    "Réserve naturelle de Corse": "Réserve naturelle de Corse",
    "Réserve biologique dirigée": "Réserve biologique dirigée",
    "Réserve biologique intégrale": "Réserve biologique intégrale",
    "Parc national, zone cœur": "Parc national (zone cœur)",
    "Parc national, aire d'adhésion": "Parc national (aire d'adhésion)",
    "Parc naturel régional": "Parc naturel régional",
    "Terrain acquis (ou assimilé) par un Conservatoire d'espaces naturels":
        "Terrain de Conservatoire d'espaces naturels",
    "Terrain géré (location, convention de gestion) par un Conservatoire d'espaces naturels":
        "Terrain de Conservatoire d'espaces naturels",
    "Terrain acquis par le Conservatoire du Littoral":
        "Terrain du Conservatoire du Littoral",
    "Zone humide protégée par la convention de Ramsar": "Site Ramsar",
}


def _date_acte(brut) -> str:
    """Date de l'acte de protection, telle qu'on peut l'affirmer.

    Le champ est rempli à 100 %, mais certaines valeurs sont des années seules
    complétées au 1ᵉʳ janvier : 56 entités portent « 2007-01-01 », 49
    « 2017-01-01 », 48 « 2019-01-01 ». Aucun arrêté préfectoral n'est signé un
    1ᵉʳ janvier à cette fréquence. Pour ces valeurs on ne publie que l'année —
    écrire « arrêté du 01/01/2007 » affirmerait une précision que la source
    n'a pas.
    """
    texte = str(brut or "").strip()
    if len(texte) < 10 or texte[:4].isdigit() is False:
        return ""
    annee, mois, jour = texte[:4], texte[5:7], texte[8:10]
    if not (mois.isdigit() and jour.isdigit()):
        return ""
    if (mois, jour) == ("01", "01"):
        return annee
    return f"{jour}/{mois}/{annee}"


def _surface_lisible(brut) -> str:
    """« 1 240 ha », « 12,4 ha », « 0,8 ha » — l'ordre de grandeur suffit."""
    try:
        valeur = float(brut)
    except (TypeError, ValueError):
        return ""
    if valeur <= 0:
        return ""
    if valeur >= 100:
        rendu = f"{valeur:,.0f}".replace(",", "\u202f")
    elif valeur >= 1:
        rendu = f"{valeur:.1f}".replace(".", ",")
    else:
        rendu = f"{valeur:.2f}".replace(".", ",")
    return f"{rendu} ha"


def _enrichir_ep(gdf, chemin: Path):
    """Ce qu'on peut dire d'un espace protégé, faute de description.

    La couche n'en porte pas. `objectif_protection` vaut « Nature » sur 8 798
    des 10 872 entités, `lien_fiche` et `statut` sont vides partout : afficher
    « Intérêt : Nature » dans un tableau d'état initial ne renseigne personne,
    et c'est pourquoi la colonne avait d'abord été laissée vide.

    Mais vide sur **toutes** les lignes, elle dépare dans un livrable, alors
    que la couche porte deux faits que tout prédiagnostic énonce : la date de
    l'acte qui a créé la protection, et la superficie du site. « Arrêté du
    21/09/2015 · 1 240 ha » est court, exact et utile.
    """
    colonne_date = _premiere_colonne(gdf, ("date_crea_sign",))
    colonne_surface = _premiere_colonne(gdf, ("superficie_ha",))
    colonne_gestion = _premiere_colonne(gdf, ("doc_gestion",))

    def _texte(ligne) -> str:
        bouts = []
        if colonne_date:
            date = _date_acte(ligne.get(colonne_date))
            if date:
                bouts.append(f"Acte de protection du {date}" if "/" in date
                             else f"Acte de protection de {date}")
        if colonne_surface:
            surface = _surface_lisible(ligne.get(colonne_surface))
            if surface:
                bouts.append(surface)
        if colonne_gestion and str(ligne.get(colonne_gestion)).strip().lower() == "true":
            bouts.append("document de gestion en vigueur")
        return " · ".join(bouts)

    gdf = gdf.copy()
    gdf["_interet"] = gdf.apply(_texte, axis=1)
    gdf["_nom"] = gdf["_nom"].map(casse_lisible)
    return gdf


def _source_ep(libelle: str, types: tuple[str, ...]) -> SourceZonage:
    return SourceZonage(
        cle="ep_" + libelle.lower().replace(" ", "_")[:24],
        archive="espaces_proteges", motif_shp="sig_metrop.gpkg",
        famille="autres", type_libelle=libelle,
        colonnes_id=("id_mnhn",), colonnes_nom=("nom",),
        colonnes_interet=(),
        enrichir=_enrichir_ep,
        filtre_colonne="type_espace", filtre_valeurs=types,
    )


def registre() -> list[SourceZonage]:
    """Les sources dans l'ordre où elles apparaissent dans l'état initial."""
    sources = [
        SourceZonage(
            cle="znieff1", archive="znieff", motif_shp="ZNIEFF1_G2",
            famille="inventaire", type_libelle="ZNIEFF de type I",
            colonnes_id=("ID_MNHN",), colonnes_nom=("NOM",),
            enrichir=_enrichir_znieff,
        ),
        SourceZonage(
            cle="znieff2", archive="znieff", motif_shp="ZNIEFF2_G2",
            famille="inventaire", type_libelle="ZNIEFF de type II",
            colonnes_id=("ID_MNHN",), colonnes_nom=("NOM",),
            enrichir=_enrichir_znieff,
        ),
        SourceZonage(
            cle="n2000_zps", archive="natura2000", motif_shp="natura_sig",
            famille="natura2000", type_libelle="Zone de Protection Spéciale",
            colonnes_id=("cd_sig",), colonnes_nom=(),
            filtre_colonne="type_espac", filtre_valeurs=("ZPS",),
            enrichir=_enrichir_natura,
        ),
        SourceZonage(
            cle="n2000_zsc", archive="natura2000", motif_shp="natura_sig",
            famille="natura2000", type_libelle="Zone Spéciale de Conservation",
            colonnes_id=("cd_sig",), colonnes_nom=(),
            filtre_colonne="type_espac", filtre_valeurs=("ZSC", "SIC", "pSIC"),
            enrichir=_enrichir_natura,
        ),
    ]
    # Un type d'espace protégé par libellé affiché, les doublons du référentiel
    # (CEN acquis et CEN géré) étant regroupés sous un seul intitulé.
    groupes: dict[str, list[str]] = {}
    for brut, affiche in _TYPES_EP.items():
        groupes.setdefault(affiche, []).append(brut)
    sources += [_source_ep(affiche, tuple(bruts))
                for affiche, bruts in groupes.items()]
    sources.append(SourceZonage(
        cle="inpg", archive="patrimoine_geologique", motif_shp="metrop",
        famille="autres", type_libelle="Site d'intérêt géologique (INPG)",
        colonnes_id=("identifi_1",), colonnes_nom=(),
        enrichir=_enrichir_inpg,
    ))
    return sources
