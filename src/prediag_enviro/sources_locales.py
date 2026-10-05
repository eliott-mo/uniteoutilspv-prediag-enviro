"""Zonages qui n'ont pas de source nationale fiable — les ENS d'abord.

La question est venue des espaces naturels sensibles, et la réponse de la
responsable environnement cadre tout le module :

    « départementaux, régionaux, ça dépend, il faut fouiller à chaque fois
    pour dénicher les infos les plus à jour. J'ai même une couche nationale
    censée se mettre à jour au fur et à mesure mais comme je sais qu'elle
    n'est pas toujours à jour, et bah je fouille »

Trois conséquences, et elles dictent la conception.

**On ne branche pas la couche nationale en silence.** L'INPN la décrit
lui-même comme « en construction » et prévient qu'elle « ne peut être
considérée comme exhaustive ni utilisée comme donnée de référence ». Afficher
« 2 ENS » sans le dire remplacerait un doute éclairé par une fausse certitude,
et un chef de projet qui ne sait pas la croirait.

**Ce qu'elle trouve doit servir la fois d'après.** Aujourd'hui, un projet en
Seine-Maritime dans six mois refait la fouille de zéro. Le registre garde, par
département, ce qui a été trouvé et quand — exactement ce que le dictionnaire
d'alias fait pour les noms d'espèces, et pour la même raison : une recherche
faite une fois profite à toute l'équipe.

**Un fichier par contributeur**, et non un fichier commun. Sur un dossier
synchronisé, deux personnes qui écrivent le même fichier produisent une copie
de conflit et une des deux contributions disparaît. Chacun n'écrit que le
sien, la lecture les fusionne tous.
"""
from __future__ import annotations

import getpass
import json
import re
import shutil
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd

from . import chemins, zonages as mod_zonages

CRS_METRIQUE = 2154

#: Extensions admises pour une couche déposée.
FORMATS = {".zip", ".geojson", ".json", ".gpkg", ".shp", ".kml"}

#: Colonnes candidates pour le nom et l'identifiant d'une couche déposée. On
#: essaie, parce qu'une couche départementale ne suit aucune convention.
COLONNES_NOM = ("nom", "name", "libelle", "lib_zone", "intitule", "site",
                "nom_site", "lib", "designation", "toponyme", "nom_ens")
COLONNES_ID = ("id_mnhn", "id", "code", "identifiant", "id_site", "code_site",
               "cd_sig", "gid", "objectid", "num")

#: Avertissement attaché à la couche nationale des ENS, repris de l'INPN.
AVERTISSEMENT_NATIONAL = (
    "couche nationale en construction : l'INPN la diffuse en précisant "
    "qu'elle ne peut être considérée comme exhaustive ni utilisée comme "
    "donnée de référence"
)


@dataclass
class Source:
    """Une couche locale, et d'où elle vient."""
    departement: str          # « 76 », « 2A »
    type_libelle: str         # « Espace Naturel Sensible »
    libelle: str              # « Couche ENS du Département de Seine-Maritime »
    url: str = ""
    consulte_le: str = field(default_factory=lambda: date.today().isoformat())
    fichier: str = ""         # nom du fichier déposé, dans couches/
    avertissement: str = ""
    par: str = ""

    @property
    def citation(self) -> str:
        bouts = [self.libelle]
        if self.url:
            bouts.append(self.url)
        bouts.append(f"consultée le {_date_lisible(self.consulte_le)}")
        return " — ".join(bouts)


def _date_lisible(iso: str) -> str:
    try:
        return date.fromisoformat(iso).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return iso or ""


def _contributeur() -> str:
    try:
        brut = getpass.getuser()
    except Exception:  # noqa: BLE001
        brut = "inconnu"
    return re.sub(r"[^A-Za-z0-9._-]", "-", brut).strip("-") or "inconnu"


def dossier() -> Path:
    return chemins.sources_locales()


def dossier_couches() -> Path:
    return dossier() / "couches"


def registre() -> dict[str, list[Source]]:
    """Sources connues, par département, tous contributeurs confondus."""
    trouvees: dict[str, list[Source]] = {}
    racine = dossier()
    if not racine.exists():
        return trouvees
    for fichier in sorted(racine.glob("*.json")):
        try:
            brut = json.loads(fichier.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for departement, entrees in (brut or {}).items():
            for entree in entrees:
                try:
                    source = Source(**entree)
                except TypeError:
                    continue
                trouvees.setdefault(str(departement), []).append(source)
    return trouvees


def pour(departements: list[str], type_libelle: str | None = None) -> list[Source]:
    """Sources enregistrées pour ces départements."""
    tout = registre()
    retenues: list[Source] = []
    for departement in departements:
        for source in tout.get(str(departement), []):
            if type_libelle and source.type_libelle != type_libelle:
                continue
            retenues.append(source)
    return retenues


def enregistrer(source: Source) -> Path:
    """Ajoute une source au fichier du contributeur, sans écraser les autres."""
    racine = dossier()
    racine.mkdir(parents=True, exist_ok=True)
    fichier = racine / f"{_contributeur()}.json"
    contenu: dict[str, list[dict]] = {}
    if fichier.exists():
        try:
            contenu = json.loads(fichier.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001
            contenu = {}
    source.par = source.par or _contributeur()
    entrees = contenu.setdefault(str(source.departement), [])
    # Une même couche redéposée remplace la précédente plutôt que de s'ajouter.
    entrees[:] = [e for e in entrees
                  if not (e.get("type_libelle") == source.type_libelle
                          and e.get("libelle") == source.libelle)]
    entrees.append(asdict(source))
    fichier.write_text(json.dumps(contenu, indent=2, ensure_ascii=False,
                                  sort_keys=True), encoding="utf-8")
    return fichier


def _nom_sur(libelle: str) -> str:
    plat = unicodedata.normalize("NFD", libelle).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "-", plat).strip("-")[:40] or "couche"


def deposer(chemin: Path, departement: str, type_libelle: str, libelle: str,
            url: str = "", consulte_le: str = "") -> Source:
    """Range une couche à côté de l'outil et l'inscrit au registre.

    La couche est copiée, pas référencée là où elle se trouve : un chemin vers
    le bureau de quelqu'un ne vaut rien pour le collègue qui reprendra le
    dossier dans six mois.
    """
    chemin = Path(chemin)
    if chemin.suffix.lower() not in FORMATS:
        raise ValueError(f"format non pris en charge : {chemin.suffix} "
                         f"(attendus : {', '.join(sorted(FORMATS))})")
    cible_dossier = dossier_couches()
    cible_dossier.mkdir(parents=True, exist_ok=True)
    nom = f"{departement}_{_nom_sur(libelle)}{chemin.suffix.lower()}"
    shutil.copy2(chemin, cible_dossier / nom)

    source = Source(departement=str(departement), type_libelle=type_libelle,
                    libelle=libelle, url=url, fichier=nom,
                    consulte_le=consulte_le or date.today().isoformat())
    enregistrer(source)
    return source


# ──────────────────────────────────────────────────────────────── croisement

def _charger(chemin: Path) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(chemin)
    if gdf.crs is None:
        raise ValueError("la couche ne déclare pas sa projection (.prj absent)")
    return gdf.to_crs(CRS_METRIQUE)


def _colonne(gdf: gpd.GeoDataFrame, candidats: tuple[str, ...]) -> str | None:
    bas = {c.lower(): c for c in gdf.columns}
    for candidat in candidats:
        if candidat in bas:
            return bas[candidat]
    # à défaut, la première colonne de texte qui n'est pas la géométrie
    for colonne in gdf.columns:
        if colonne != gdf.geometry.name and gdf[colonne].dtype == object:
            return colonne
    return None


def croiser(emprise_union, departements: list[str],
            aires: list | None = None, type_libelle: str | None = None
            ) -> tuple[list, dict, list[Source], list[str]]:
    """Croise les couches déposées avec l'emprise.

    Renvoie (zonages, géométries par type, sources employées, anomalies). Les
    géométries servent la cartographie : sans elles, un ENS figurerait au
    tableau mais pas sur la carte, ce qui se remarque. Les anomalies sont dites
    plutôt que tues : une couche illisible doit se voir, sinon son absence
    passe pour une absence d'enjeu.
    """
    aires = aires or [mod_zonages.AireEtude(c, l, r)
                      for c, l, r in mod_zonages.AIRES_DEFAUT]
    portee = max(a.rayon_m for a in aires)
    trouves: list = []
    geometries: dict = {}
    employees: list[Source] = []
    anomalies: list[str] = []

    for source in pour(departements, type_libelle):
        if not source.fichier:
            # Source documentée mais sans couche : elle compte pour la
            # bibliographie, pas pour le croisement.
            employees.append(source)
            continue
        chemin = dossier_couches() / source.fichier
        if not chemin.exists():
            anomalies.append(f"{source.libelle} : fichier absent "
                             f"({source.fichier})")
            continue
        try:
            gdf = _charger(chemin)
        except Exception as erreur:  # noqa: BLE001
            anomalies.append(f"{source.libelle} : {erreur}")
            continue

        colonne_nom = _colonne(gdf, COLONNES_NOM)
        colonne_id = _colonne(gdf, COLONNES_ID)
        gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()]
        if gdf.empty:
            anomalies.append(f"{source.libelle} : aucune géométrie exploitable")
            continue

        distances = gdf.geometry.distance(emprise_union)
        retenus = gdf[distances <= portee].copy()
        retenus["_d"] = distances[distances <= portee]
        employees.append(source)
        if not retenus.empty:
            couche = retenus.rename(columns={
                colonne_nom or "": "_nom", colonne_id or "": "_id"})
            for manquante in ("_nom", "_id"):
                if manquante not in couche.columns:
                    couche[manquante] = ""
            couche["_nom"] = couche["_nom"].astype(str).map(
                mod_zonages.casse_lisible)
            precedent = geometries.get(source.type_libelle)
            extrait = couche[["_nom", "_id", "geometry"]]
            geometries[source.type_libelle] = (
                gpd.GeoDataFrame(pd.concat([precedent, extrait]),
                                 crs=extrait.crs)
                if precedent is not None else extrait)
        for _, ligne in retenus.sort_values("_d").iterrows():
            distance = float(ligne["_d"])
            trouves.append(mod_zonages.Zonage(
                famille="autres", type=source.type_libelle,
                identifiant=str(ligne[colonne_id]) if colonne_id else "",
                nom=mod_zonages.casse_lisible(
                    str(ligne[colonne_nom]) if colonne_nom else ""),
                interet="",
                distance_m=distance,
                aires=[a.code for a in aires if distance <= a.rayon_m],
            ))
    return trouves, geometries, employees, anomalies


def avertissements(departements: list[str],
                   type_libelle: str = "Espace Naturel Sensible") -> list[str]:
    """Ce qu'il faut dire au lecteur sur ce type de zonage.

    Deux cas, et il faut les distinguer : aucune source enregistrée — personne
    n'a cherché —, ou une source qui se sait incomplète. Un tableau vide ne dit
    ni l'un ni l'autre.
    """
    sources = pour(departements, type_libelle)
    if not sources:
        ou = ("ce département" if len(departements) == 1
              else "ces départements")
        pluriel = mod_zonages.pluriel(type_libelle, 2).lower()
        return [
            f"aucune source n'est enregistrée pour les {pluriel} "
            f"sur {ou} ({', '.join(departements)}). Ces zonages n'ont pas de "
            "couche nationale fiable : ils relèvent du Département ou de la "
            "région et se recherchent au cas par cas. L'absence de ligne "
            "ci-dessus ne vaut donc pas absence de zonage."
        ]
    dits = []
    for source in sources:
        if source.avertissement:
            dits.append(f"{source.libelle} — {source.avertissement}.")
    return dits
