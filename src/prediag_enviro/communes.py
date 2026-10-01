"""Emprise du projet et communes concernées.

Le périmètre arrive en archive `.zip` de shapefile — le format d'échange des
équipes SIG — ou en KML/GeoJSON. Le contrôle d'entrée est affiché avant tout
calcul : une erreur de projection se voit là, pas trois étapes plus loin.

Une ZIP chevauche souvent plusieurs communes. On ne tranche pas à sa place :
on liste les communes intersectées **avec leur part de surface**, parce que
c'est ce qui fonde la décision. Une commune touchée à 0,4 % ne justifie sans
doute pas une recherche d'espèces, mais c'est son arbitrage.

Les contours viennent de `geo.api.gouv.fr`, interrogé par département : pas de
gros référentiel à télécharger, et la réponse est mise en cache.
"""
from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd
import requests

CRS_METRIQUE = 2154          # Lambert-93, pour les surfaces
CRS_GEO = 4326
_API = "https://geo.api.gouv.fr"
_UA = {"User-Agent": "prediag-enviro (UNITe)"}


@dataclass
class Emprise:
    gdf: gpd.GeoDataFrame
    source: Path
    crs_detecte: str
    n_entites: int

    @property
    def surface_ha(self) -> float:
        """Surface de l'union, pas la somme des entités.

        Une emprise livrée en plusieurs polygones peut en superposer certains
        (plan d'eau et îlots, variantes d'implantation). Sommer les aires
        compterait les recouvrements deux fois et gonflerait la surface
        annoncée dans le livrable.
        """
        return float(self.union.area) / 10_000

    @property
    def surface_cumulee_ha(self) -> float:
        """Somme des entités — à comparer à `surface_ha` pour repérer un recouvrement."""
        return float(self.gdf.geometry.area.sum()) / 10_000

    @property
    def bbox_l93(self) -> tuple[float, float, float, float]:
        return tuple(self.gdf.total_bounds)

    @property
    def union(self):
        return self.gdf.geometry.union_all()

    def controle(self) -> list[str]:
        """Lignes du contrôle d'entrée, à afficher avant tout calcul."""
        x0, y0, x1, y1 = self.bbox_l93
        lignes = [
            f"fichier : {self.source.name}",
            f"entités : {self.n_entites}",
            f"projection lue : {self.crs_detecte}"
            + ("" if self.crs_detecte.endswith(str(CRS_METRIQUE))
               else f" → reprojetée en EPSG:{CRS_METRIQUE}"),
            f"surface : {self.surface_ha:.2f} ha",
            f"emprise : {x1 - x0:.0f} m × {y1 - y0:.0f} m",
        ]
        cumul = self.surface_cumulee_ha
        if cumul > self.surface_ha * 1.01:
            lignes.append(
                f"⚠ les entités se recouvrent : {cumul:.2f} ha cumulés pour "
                f"{self.surface_ha:.2f} ha de surface réelle"
            )
        return lignes


@dataclass
class Commune:
    code: str                # INSEE
    nom: str
    surface_ha: float        # part de la ZIP dans cette commune
    part: float              # fraction de la ZIP, entre 0 et 1
    retenue: bool = True     # décochable par l'utilisatrice

    @property
    def libelle(self) -> str:
        return f"{self.nom} ({self.code})"


@dataclass
class Decoupage:
    communes: list[Commune] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)

    @property
    def retenues(self) -> list[Commune]:
        return [c for c in self.communes if c.retenue]

    @property
    def a_cheval(self) -> bool:
        return len([c for c in self.communes if c.part >= 0.01]) > 1


# ------------------------------------------------------------------- emprise

def _trouver_archive(chemin: Path) -> Path:
    if chemin.is_dir():
        archives = sorted(chemin.glob("*.zip"))
        if not archives:
            raise FileNotFoundError(f"aucune archive .zip dans {chemin}")
        if len(archives) > 1:
            raise ValueError(
                f"{len(archives)} archives dans {chemin} — une seule emprise attendue : "
                + ", ".join(a.name for a in archives)
            )
        return archives[0]
    return chemin


def _verifier_shapefile(archive: Path) -> None:
    with zipfile.ZipFile(archive) as zf:
        noms = [n.lower() for n in zf.namelist()]
        for extension in (".shp", ".shx", ".dbf", ".prj"):
            if not any(n.endswith(extension) for n in noms):
                raise ValueError(
                    f"{archive.name} : composant {extension} manquant — shapefile "
                    "incomplet (.shp/.shx/.dbf/.prj requis)"
                )


def charger_emprise(chemin: str | Path) -> Emprise:
    """Charge le périmètre et le reprojette en Lambert-93."""
    chemin = Path(chemin)
    if chemin.suffix.lower() in (".kml", ".geojson", ".json"):
        gdf = gpd.read_file(chemin)
        source = chemin
    else:
        source = _trouver_archive(chemin)
        _verifier_shapefile(source)
        gdf = gpd.read_file(f"zip://{source.as_posix()}")

    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    if gdf.empty:
        raise ValueError(f"{source.name} : aucune entité géométrique exploitable")
    if gdf.crs is None:
        raise ValueError(f"{source.name} : projection non détectée — vérifier le .prj")

    crs_detecte = str(gdf.crs)
    if gdf.crs.to_epsg() != CRS_METRIQUE:
        gdf = gdf.to_crs(CRS_METRIQUE)
    return Emprise(gdf=gdf, source=source, crs_detecte=crs_detecte, n_entites=len(gdf))


# ------------------------------------------------------------------ communes

def _departements(emprise: Emprise, cache: Path | None) -> list[str]:
    """Départements touchés, par géocodage inverse de points de l'emprise."""
    centres = emprise.gdf.to_crs(CRS_GEO)
    points = [centres.geometry.union_all().representative_point()]
    x0, y0, x1, y1 = centres.total_bounds
    from shapely.geometry import Point
    enveloppe = centres.geometry.union_all()
    for x, y in ((x0, y0), (x0, y1), (x1, y0), (x1, y1), ((x0 + x1) / 2, (y0 + y1) / 2)):
        p = Point(x, y)
        points.append(p if enveloppe.contains(p) else enveloppe.centroid)

    trouves: list[str] = []
    for p in points:
        try:
            r = requests.get(f"{_API}/communes", headers=_UA, timeout=25,
                             params={"lat": p.y, "lon": p.x, "fields": "departement"})
            for item in r.json() if r.ok else []:
                code = (item.get("departement") or {}).get("code")
                if code and code not in trouves:
                    trouves.append(code)
        except Exception:  # noqa: BLE001
            continue
    return trouves


def _contours(departement: str, cache: Path | None) -> gpd.GeoDataFrame | None:
    fichier = (cache / f"communes_{departement}.geojson") if cache else None
    if fichier and fichier.exists():
        return gpd.read_file(fichier).to_crs(CRS_METRIQUE)
    try:
        r = requests.get(f"{_API}/departements/{departement}/communes", headers=_UA,
                         timeout=90, params={"geometry": "contour", "format": "geojson"})
        r.raise_for_status()
        donnees = r.json()
    except Exception:  # noqa: BLE001
        return None
    if fichier:
        fichier.parent.mkdir(parents=True, exist_ok=True)
        fichier.write_text(json.dumps(donnees), encoding="utf-8")
    return gpd.GeoDataFrame.from_features(donnees["features"], crs=CRS_GEO).to_crs(CRS_METRIQUE)


def communes_concernees(emprise: Emprise, cache: Path | None = None,
                        seuil_retenue: float = 0.01) -> Decoupage:
    """Communes intersectées, avec leur part de surface de l'emprise.

    `seuil_retenue` : en dessous de cette fraction, la commune est listée mais
    décochée — à elle de la réintégrer si elle le juge utile.
    """
    decoupage = Decoupage()
    zone = emprise.union
    surface_totale = zone.area or 1.0

    departements = _departements(emprise, cache)
    if not departements:
        decoupage.avertissements.append(
            "département non déterminé (geo.api.gouv.fr injoignable) — "
            "saisir le code INSEE à la main"
        )
        return decoupage

    couches = [c for c in (_contours(d, cache) for d in departements) if c is not None]
    if not couches:
        decoupage.avertissements.append(
            f"contours communaux indisponibles pour {', '.join(departements)} — "
            "saisir le code INSEE à la main"
        )
        return decoupage

    import pandas as pd
    communes = pd.concat(couches, ignore_index=True)
    candidates = communes[communes.intersects(zone)]
    for _, ligne in candidates.iterrows():
        part_geom = ligne.geometry.intersection(zone)
        if part_geom.is_empty:
            continue
        part = part_geom.area / surface_totale
        decoupage.communes.append(Commune(
            code=str(ligne.get("code", "")), nom=str(ligne.get("nom", "")),
            surface_ha=part_geom.area / 10_000, part=part,
            retenue=part >= seuil_retenue,
        ))

    decoupage.communes.sort(key=lambda c: -c.part)
    if decoupage.a_cheval:
        decoupage.avertissements.append(
            "emprise à cheval sur plusieurs communes : un fichier par commune pour "
            "la télétransmission, un tableau unique pour l'état initial"
        )
    return decoupage


def commune_par_code(code: str, cache: Path | None = None) -> Commune | None:
    """Ajout manuel d'une commune par son code INSEE."""
    try:
        r = requests.get(f"{_API}/communes/{code}", headers=_UA, timeout=25,
                         params={"fields": "nom,code"})
        if not r.ok:
            return None
        item = r.json()
    except Exception:  # noqa: BLE001
        return None
    return Commune(code=str(item.get("code", code)), nom=str(item.get("nom", "")),
                   surface_ha=0.0, part=0.0, retenue=True)
