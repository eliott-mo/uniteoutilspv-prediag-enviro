# -*- coding: utf-8 -*-
"""Les coupes d'un site en ligne de commande, hors de l'interface.

    python -m prediag_enviro.coupes --emprise ZIP.zip --site Bédarieux \
        --sortie sorties/coupes_bedarieux [--surface-utile SU.kml] \
        [--libelle-emprise "Emprise cadastrale"] [--cache dossier]

L'emprise est une archive ZIP de shapefile, un .shp, un KML ou un GeoJSON, en
n'importe quelle projection. Sorties : plan_reperage.png, une image par coupe,
coupes_topographiques_<site>.pdf et .json.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import geopandas as gpd

from .. import chemins
from ..communes import CRS_METRIQUE, charger_emprise
from . import ErreurIGN, etudier, produire
from .reglages import LIBELLE_EMPRISE


def lire(chemin: str | Path):
    """L'emprise d'un fichier, en un seul objet, en Lambert 93."""
    chemin = Path(chemin)
    if chemin.suffix.lower() == ".shp":
        gdf = gpd.read_file(chemin)
        if gdf.crs is None:
            raise ValueError(f"{chemin.name} : projection non détectée (.prj absent)")
        gdf = gdf.to_crs(CRS_METRIQUE)
    else:
        gdf = charger_emprise(chemin).gdf
    return gdf.geometry.union_all()


def main(arguments=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    lecteur = argparse.ArgumentParser(
        description="Coupes topographiques autour d'une emprise de projet.")
    lecteur.add_argument("--emprise", required=True,
                         help="ZIP de shapefile, .shp, KML ou GeoJSON")
    lecteur.add_argument("--surface-utile", help="surface des panneaux (facultatif)")
    lecteur.add_argument("--site", default="", help="nom du site, pour les titres")
    lecteur.add_argument("--sortie", default="coupes", help="dossier de sortie")
    lecteur.add_argument("--libelle-emprise", default=LIBELLE_EMPRISE,
                         help="ce que la légende appelle l'emprise")
    lecteur.add_argument("--cache", help="dossier du cache IGN")
    args = lecteur.parse_args(arguments)

    debut = time.perf_counter()
    emprise = lire(args.emprise)
    surface_utile = lire(args.surface_utile) if args.surface_utile else None
    if surface_utile is not None:
        hors = surface_utile.difference(emprise).area
        if hors > 1:
            print(f"Attention : {hors:.0f} m² de surface utile hors de l'emprise.")
    cache = Path(args.cache) if args.cache else chemins.cache_coupes()
    try:
        etude = etudier(emprise, surface_utile, cache=cache,
                        libelle_emprise=args.libelle_emprise,
                        source_emprise=Path(args.emprise).name)
    except ErreurIGN as erreur:
        print(f"Coupes non produites. {erreur}", file=sys.stderr)
        return 2
    livrables = produire(etude, Path(args.sortie), site=args.site)
    for c in etude.coupes:
        haut, bas = c.point_haut, c.point_bas
        print(f"{c.identifiant:>11} : {bas[1]:.0f}–{haut[1]:.0f} m, "
              + " → ".join(c.communes_traversees()))
    extremes = etude.altitudes_emprise()
    if extremes:
        print(f"Emprise entre {extremes[0]:.0f} et {extremes[1]:.0f} m NGF.")
    print(f"{len(livrables.coupes) + 2} fichiers dans {Path(args.sortie).resolve()} "
          f"en {time.perf_counter() - debut:.0f} s.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
