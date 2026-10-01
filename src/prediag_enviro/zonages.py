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

    def par_famille(self, famille: str) -> list[Zonage]:
        return [z for z in self.zonages if z.famille == famille]

    def resume(self) -> str:
        """Phrase de synthèse, du genre de celles qui ouvrent les sections."""
        if not self.zonages:
            return "Aucun zonage du patrimoine naturel dans les aires d'étude."
        compte: dict[str, int] = {}
        for z in self.zonages:
            compte[z.type] = compte.get(z.type, 0) + 1
        # Pas de « s » automatique : « ZNIEFF de type I » ne se pluralise pas
        # en « ZNIEFF de type Is ». Le nombre devant suffit à dire le pluriel.
        bouts = [f"{n} {t}" for t, n in sorted(compte.items(), key=lambda x: -x[1])]
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
    """Les textes de l'INPN arrivent en HTML : `<p>`, `<i>` autour des latins."""
    texte = _BALISE.sub(" ", str(brut or ""))
    texte = (texte.replace("&nbsp;", " ").replace("&amp;", "&")
             .replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'"))
    texte = _ESPACES.sub(" ", texte).strip()
    if len(texte) <= limite:
        return texte
    coupe = texte[:limite].rsplit(". ", 1)[0]
    return (coupe + ".") if len(coupe) > limite * 0.5 else texte[:limite].rstrip() + "…"


def casse_lisible(nom: str) -> str:
    """Renvoie le nom tel que le référentiel le porte. Volontairement.

    Les fiches ZNIEFF sont souvent en capitales — « BOIS ALLUVIAUX, MARAIS,
    BRAS MORTS ET FLEUVE LA SEINE » — et la tentation est de les passer en
    casse normale. On l'a essayé : ça donne « fleuve la seine », « la
    villeneuve-au-chatelot », « la louverie ». Des noms propres décapitalisés,
    donc des fautes introduites par l'outil, et plus discrètes que les
    capitales qu'elles remplacent — donc plus susceptibles de passer dans le
    livrable.

    Entre une laideur visible qui vient de la source et une faute invisible qui
    vient de nous, on garde la laideur. Les quelques noms retenus seront
    reformatés à la relecture, en connaissance de cause.
    """
    return str(nom or "").strip()


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
        nom = nettoyer_texte(ligne.get("nom_cite") or "", 120)
        # Le nom cité porte son auteur : « Cordulia aenea (Linnaeus, 1758) ».
        # Dans un tableau de synthèse, l'auteur encombre sans rien apporter.
        nom = re.sub(r"\s*\((?:[^()]*\d{4}[^()]*)\)\s*$", "", nom).strip()
        if numero and nom:
            especes[numero][groupe].add(nom)

    def _texte(numero: str) -> str:
        fiche = fiches.get(numero) or {}
        bouts = [nettoyer_texte(fiche.get("TX_GENE") or fiche.get("TX_INTERET") or "")]
        groupes = especes.get(numero)
        if groupes:
            details = []
            for groupe, noms in sorted(groupes.items(), key=lambda x: -len(x[1])):
                echantillon = sorted(noms)[:6]
                suite = f" et {len(noms) - 6} autres" if len(noms) > 6 else ""
                details.append(f"{groupe} : {', '.join(echantillon)}{suite}")
            bouts.append("Espèces déterminantes — " + " · ".join(details[:5]) + ".")
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


def _source_ep(libelle: str, types: tuple[str, ...]) -> SourceZonage:
    return SourceZonage(
        cle="ep_" + libelle.lower().replace(" ", "_")[:24],
        archive="espaces_proteges", motif_shp="sig_metrop.gpkg",
        famille="autres", type_libelle=libelle,
        colonnes_id=("id_mnhn",), colonnes_nom=("nom",),
        # Pas de colonne descriptive : « objectif_protection » vaut « Nature »
        # sur la quasi-totalité des entités. Afficher « Intérêt : Nature » dans
        # un tableau d'état initial ne renseigne personne.
        colonnes_interet=(),
        enrichir=lambda g, c: g.assign(_nom=g["_nom"].map(casse_lisible)),
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
