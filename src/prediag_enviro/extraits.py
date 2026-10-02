"""Extraits départementaux des zonages — ce qui rend l'outil distribuable.

Les référentiels de l'INPN couvrent la France : 462 Mo d'archives, 379 Mo de
couches extraites. Un prédiag, lui, ne regarde jamais plus qu'un département et
ses voisins. Découper par département remplace ce gigaoctet par un fichier de
3 à 9 Mo que chacun télécharge pour son seul projet.

Conséquence : **seule la machine qui construit les extraits porte les archives
nationales.** Tous les autres postes n'ont que ce dont ils ont besoin, et
l'installation d'un chef de projet tombe de dix minutes à deux.

Les textes descriptifs sont rattachés **à la construction**, pas à la lecture.
C'est le point qui fait tenir l'ensemble : la colonne « Intérêt » — description
de la ZNIEFF, espèces déterminantes par groupe, caractérisation Natura 2000 —
vit dans des CSV au cœur des archives nationales. Un extrait qui ne porterait
que les géométries priverait les chefs de projet de la colonne la plus coûteuse
à produire à la main.

Un département absent **arrête l'outil**. Il ne rend pas une liste vide : entre
« je n'ai pas les données pour la Dordogne » et « aucun zonage dans les aires
d'étude », le second est un prédiag faux, et rien ne le signalerait.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

from . import zonages as mod_zonages

CRS_METRIQUE = 2154
_API = "https://geo.api.gouv.fr"
_UA = {"User-Agent": "prediag-enviro (UNITe)"}

#: Marge autour du département. L'aire d'étude rapprochée fait 5 km par défaut :
#: un projet collé à la limite départementale doit retrouver les zonages du
#: département voisin. 10 km laisse de la marge si quelqu'un élargit l'aire.
MARGE_M = 10_000

#: Colonnes conservées. `_interet` est le texte descriptif déjà rattaché.
COLONNES = ["_id", "_nom", "_interet", "_type", "_famille", "_cle", "geometry"]

MANIFESTE = "extraits.json"


@dataclass
class EtatExtraits:
    """Ce qui est construit, et avec quelles versions de référentiels."""
    departements: list[str]
    versions: dict[str, str]
    construit_le: str

    @property
    def nombre(self) -> int:
        return len(self.departements)

    def perime(self, versions_actuelles: dict[str, str]) -> list[str]:
        """Référentiels dont la version a bougé depuis la construction."""
        return [cle for cle, version in versions_actuelles.items()
                if cle in self.versions and self.versions[cle] != version]


def _contour(departement: str, cache: Path | None) -> "gpd.GeoSeries":
    """Contour du département, élargi de la marge."""
    fichier = (cache / f"communes_{departement}.geojson") if cache else None
    if fichier and fichier.exists():
        communes = gpd.read_file(fichier)
    else:
        reponse = requests.get(f"{_API}/departements/{departement}/communes",
                               headers=_UA, timeout=120,
                               params={"geometry": "contour", "format": "geojson"})
        reponse.raise_for_status()
        donnees = reponse.json()
        if fichier:
            fichier.parent.mkdir(parents=True, exist_ok=True)
            fichier.write_text(json.dumps(donnees), encoding="utf-8")
        communes = gpd.GeoDataFrame.from_features(donnees["features"], crs=4326)
    return communes.to_crs(CRS_METRIQUE).geometry.union_all().buffer(MARGE_M)


def departements_metropole() -> list[str]:
    """Les départements métropolitains, Corse comprise."""
    codes = [f"{n:02d}" for n in range(1, 96) if n != 20]
    return sorted(codes + ["2A", "2B"])


def construire(departements: list[str], archives_dir: Path, cache: Path,
               fichiers: dict[str, str], sortie: Path,
               versions: dict[str, str] | None = None,
               progression=None) -> EtatExtraits:
    """Produit un fichier par département depuis les archives nationales.

    Les couches nationales ne sont chargées qu'une fois : c'est le poste le
    plus coûteux, et le découpage lui-même prend moins d'une seconde par
    département.
    """
    def dire(message: str) -> None:
        if progression is not None:
            progression(message)

    sortie.mkdir(parents=True, exist_ok=True)
    dire("Chargement des couches nationales…")
    couches = []
    for source in mod_zonages.registre():
        try:
            gdf = mod_zonages.charger_source(source, archives_dir, cache, fichiers)
        except Exception as erreur:  # noqa: BLE001
            dire(f"  {source.type_libelle} ignorée : {erreur}")
            continue
        if not gdf.empty:
            couches.append((source, gdf))
    if not couches:
        raise RuntimeError(
            "Aucune couche nationale lisible : les archives INPN sont-elles "
            "bien présentes ?"
        )

    construits: list[str] = []
    for rang, departement in enumerate(departements, start=1):
        dire(f"Département {departement} ({rang}/{len(departements)})…")
        try:
            zone = _contour(departement, cache)
        except Exception as erreur:  # noqa: BLE001
            dire(f"  contours indisponibles pour {departement} : {erreur}")
            continue

        morceaux = []
        for source, gdf in couches:
            proches = gdf.iloc[list(gdf.sindex.intersection(zone.bounds))]
            retenus = proches[proches.intersects(zone)]
            if retenus.empty:
                continue
            # Les textes descriptifs sont rattachés ici, à la construction :
            # ils vivent dans les CSV des archives nationales, que les postes
            # qui liront l'extrait n'auront pas.
            retenus = retenus.copy()
            if source.enrichir is not None:
                retenus = source.enrichir(
                    retenus, archives_dir / fichiers[source.archive]
                )
            retenus = retenus.reindex(
                columns=[c for c in COLONNES if c != "geometry"] + ["geometry"]
            )
            retenus["_type"] = source.type_libelle
            retenus["_famille"] = source.famille
            retenus["_cle"] = source.cle
            morceaux.append(retenus)

        if not morceaux:
            dire(f"  aucun zonage dans {departement}")
            continue
        tout = gpd.GeoDataFrame(pd.concat(morceaux, ignore_index=True),
                                crs=CRS_METRIQUE)
        tout = tout.fillna({"_id": "", "_nom": "", "_interet": ""})
        chemin = sortie / f"dep-{departement}.parquet"
        tout.to_parquet(chemin, compression="zstd")
        construits.append(departement)

    etat = EtatExtraits(departements=sorted(construits),
                        versions=dict(versions or {}),
                        construit_le=date.today().isoformat())
    (sortie / MANIFESTE).write_text(
        json.dumps({"departements": etat.departements, "versions": etat.versions,
                    "construit_le": etat.construit_le},
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    dire(f"{len(construits)} département(s) construit(s).")
    return etat


def etat(sortie: Path) -> EtatExtraits | None:
    """Ce qui est construit, d'après le manifeste. None si rien ne l'est."""
    manifeste = sortie / MANIFESTE
    if not manifeste.exists():
        return None
    try:
        brut = json.loads(manifeste.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return EtatExtraits(departements=list(brut.get("departements", [])),
                        versions=dict(brut.get("versions", {})),
                        construit_le=str(brut.get("construit_le", "")))


class DepartementAbsent(RuntimeError):
    """Levée quand un projet sort du périmètre construit.

    Volontairement une exception et non une liste vide : un prédiag qui
    annonce « aucun zonage » faute de données serait faux, et personne ne
    pourrait le deviner à la lecture.
    """

    def __init__(self, manquants: list[str], disponibles: list[str]):
        self.manquants = manquants
        self.disponibles = disponibles
        super().__init__(
            "Extraits absents pour le(s) département(s) "
            + ", ".join(manquants)
            + f". {len(disponibles)} département(s) construit(s). "
            "Lancer la reconstruction des extraits depuis l'onglet « Mise à "
            "jour des tables » sur le poste qui porte les archives nationales."
        )


def charger(departements: list[str], sortie: Path) -> gpd.GeoDataFrame:
    """Charge les extraits des départements concernés, ou refuse."""
    courant = etat(sortie)
    disponibles = courant.departements if courant else []
    manquants = [d for d in departements
                 if not (sortie / f"dep-{d}.parquet").exists()]
    if manquants:
        raise DepartementAbsent(manquants, disponibles)

    morceaux = [gpd.read_parquet(sortie / f"dep-{d}.parquet") for d in departements]
    tout = gpd.GeoDataFrame(pd.concat(morceaux, ignore_index=True),
                            crs=CRS_METRIQUE)
    # Un zonage à cheval sur deux départements figure dans les deux extraits.
    return tout.drop_duplicates(subset=["_cle", "_id"]).reset_index(drop=True)


def croiser(emprise_union, departements: list[str], sortie: Path,
            aires: list[mod_zonages.AireEtude] | None = None) -> mod_zonages.Resultat:
    """Croise l'emprise avec les extraits, comme `zonages.croiser` le fait
    avec les archives nationales. Même résultat, mêmes familles."""
    aires = aires or [mod_zonages.AireEtude(c, l, r)
                      for c, l, r in mod_zonages.AIRES_DEFAUT]
    portee = max(a.rayon_m for a in aires)
    res = mod_zonages.Resultat()

    tout = charger(departements, sortie)
    courant = etat(sortie)
    res.journal.append(
        f"Extraits {', '.join(departements)} — {len(tout)} zonages"
        + (f", construits le {courant.construit_le}" if courant else "")
    )

    tout["_d"] = tout.geometry.distance(emprise_union)
    retenus = tout[tout["_d"] <= portee].sort_values("_d")

    for type_libelle, groupe in retenus.groupby("_type", sort=False):
        res.geometries[str(type_libelle)] = groupe[["_nom", "_id", "geometry"]]
        for _, ligne in groupe.iterrows():
            distance = float(ligne["_d"])
            res.zonages.append(mod_zonages.Zonage(
                famille=str(ligne["_famille"]), type=str(type_libelle),
                identifiant=str(ligne["_id"]), nom=str(ligne["_nom"]),
                interet=str(ligne.get("_interet") or ""),
                distance_m=distance,
                aires=[a.code for a in aires if distance <= a.rayon_m],
            ))
    res.zonages.sort(key=lambda z: (z.famille, z.type, z.distance_m))
    return res
