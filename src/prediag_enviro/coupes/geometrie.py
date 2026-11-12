# -*- coding: utf-8 -*-
"""Traits de coupe, intervalles croisés et choix des étiquettes.

Tout se calcule en Lambert 93, en mètres. Une distance « le long de la coupe »
se compte depuis l'extrémité de départ, celle que le titre nomme en premier.
"""
from __future__ import annotations

from math import atan2, cos, degrees, hypot, radians, sin

import numpy as np
from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry

from .reglages import AZIMUTS, ECART_LIEUX  # noqa: F401  (réexporté)


def centre(emprise: BaseGeometry) -> Point:
    """Le centre des coupes : centroïde du plus grand bloc de l'emprise.

    Une ZIP en plusieurs morceaux a son centroïde global entre eux, parfois
    dans un champ qui n'est pas du projet : les coupes passeraient à côté de
    tous les blocs.
    """
    parties = list(getattr(emprise, "geoms", [emprise]))
    return max(parties, key=lambda g: g.area).centroid


def trait(centre_: Point, azimut: float, demi_longueur: float) -> LineString:
    """Le trait de coupe, de l'extrémité d'azimut `azimut` à l'opposée."""
    a = radians(azimut)
    ux, uy = sin(a), cos(a)
    return LineString([
        (centre_.x + ux * demi_longueur, centre_.y + uy * demi_longueur),
        (centre_.x - ux * demi_longueur, centre_.y - uy * demi_longueur),
    ])


def trait_libre(depart: Point, vers: Point, recul: float = 0.0,
                au_dela: float = 0.0) -> LineString:
    """Une coupe définie par deux points, vers un hameau ou un point de vue.

    Elle part de `depart`, reculé de `recul` mètres, et dépasse `vers` de
    `au_dela` mètres : ni le lieu ni la ZIP ne restent collés au bord.
    """
    dx, dy = vers.x - depart.x, vers.y - depart.y
    longueur = hypot(dx, dy)
    if longueur < 1.0:
        raise ValueError("les deux points de la coupe sont confondus")
    ux, uy = dx / longueur, dy / longueur
    return LineString([
        (depart.x - ux * recul, depart.y - uy * recul),
        (vers.x + ux * au_dela, vers.y + uy * au_dela),
    ])


def echantillons(ligne: LineString, pas: float):
    """Distances et coordonnées des points du profil, extrémités comprises."""
    longueur = ligne.length
    # Par défaut, et non à l'arrondi : une coupe libre de 4 128 m en aurait
    # mesuré 4 130. Le dernier point est alors l'extrémité exacte.
    n = int(np.floor(longueur / pas + 1e-9))
    distances = np.linspace(0.0, n * pas, n + 1)
    if distances[-1] < longueur - 1e-6:
        distances = np.append(distances, longueur)
    (x0, y0), (x1, y1) = ligne.coords[0], ligne.coords[-1]
    t = distances / longueur
    return distances, x0 + (x1 - x0) * t, y0 + (y1 - y0) * t


def _morceaux(geometrie):
    """Les composantes d'une géométrie, à plat."""
    if geometrie.is_empty:
        return []
    if hasattr(geometrie, "geoms"):
        return [g for sous in geometrie.geoms for g in _morceaux(sous)]
    return [geometrie]


def intervalles(ligne: LineString, polygone: BaseGeometry) -> list[tuple[float, float]]:
    """Les tronçons du trait qui traversent le polygone, dans l'ordre du trait.

    Un contact ponctuel ne compte pas : le trait n'y traverse rien.
    """
    resultat = []
    for morceau in _morceaux(ligne.intersection(polygone)):
        if morceau.geom_type != "LineString" or morceau.length <= 0:
            continue
        a = ligne.project(Point(morceau.coords[0]))
        b = ligne.project(Point(morceau.coords[-1]))
        resultat.append((round(min(a, b), 6), round(max(a, b), 6)))
    return sorted(resultat)


def croisements(ligne: LineString, lineaire: BaseGeometry) -> list[float]:
    """Les points où un cours d'eau ou une route coupe le trait."""
    positions = []
    for morceau in _morceaux(ligne.intersection(lineaire)):
        if morceau.geom_type == "Point":
            positions.append(ligne.project(morceau))
        elif morceau.geom_type == "LineString":
            # Une route qui suit le trait sur quelques mètres : son milieu.
            positions.append(ligne.project(morceau.interpolate(0.5, normalized=True)))
    return sorted(positions)


def dedoublonner(positions, ecart: float) -> list[float]:
    """Garde une position sur toutes celles à moins de `ecart` d'elle.

    L'ordre reçu est celui de la priorité : la première l'emporte.
    """
    gardees: list[float] = []
    for p in positions:
        if all(abs(p - q) >= ecart for q in gardees):
            gardees.append(p)
    return gardees


def lieux_a_nommer(candidats, longueur: float,
                   ecart_relatif: float = ECART_LIEUX) -> list[tuple[float, str]]:
    """Les lieux habités à nommer sur une coupe, dans l'ordre du trait.

    Un nom une seule fois, au milieu de son plus long tronçon croisé — sinon
    « Bédarieux » revenait quatre fois —, puis un écart minimal entre deux noms,
    les plus longs tronçons servis d'abord.
    """
    meilleurs: dict[str, tuple[float, float]] = {}
    for nom, a, b in candidats:
        if nom not in meilleurs or b - a > meilleurs[nom][1] - meilleurs[nom][0]:
            meilleurs[nom] = (a, b)
    ordre = sorted(meilleurs.items(), key=lambda kv: -(kv[1][1] - kv[1][0]))
    gardes: list[tuple[float, str]] = []
    for nom, (a, b) in ordre:
        milieu = (a + b) / 2
        if all(abs(milieu - p) >= ecart_relatif * longueur for p, _ in gardes):
            gardes.append((milieu, nom))
    return sorted(gardes)


_ABREVIATIONS = (("Ruisseau de ", "Rau de "), ("Ruisseau des ", "Rau des "),
                 ("Ruisseau du ", "Rau du "), ("Ruisseau d'", "Rau d'"))


def abreger(nom: str) -> str:
    """« Ruisseau de » devient « Rau de » : les noms tiennent sous le profil."""
    for long, court in _ABREVIATIONS:
        nom = nom.replace(long, court)
    return nom


def capitale(nom: str) -> str:
    """Capitale initiale : la BD TOPO écrit « le Mas Blanc »."""
    return nom[:1].upper() + nom[1:] if nom else nom


_ROSE = ("N", "NE", "E", "SE", "S", "SO", "O", "NO")
_EN_LETTRES = {"N": "au nord", "NE": "au nord-est", "E": "à l'est",
               "SE": "au sud-est", "S": "au sud", "SO": "au sud-ouest",
               "O": "à l'ouest", "NO": "au nord-ouest"}


def rose(dx: float, dy: float) -> str:
    """La direction d'un vecteur, sur la rose à huit branches."""
    angle = degrees(atan2(dx, dy)) % 360.0
    return _ROSE[int((angle + 22.5) // 45.0) % 8]


def en_lettres(direction: str) -> str:
    """« NO » → « au nord-ouest », « E » → « à l'est » : pour une phrase."""
    return _EN_LETTRES.get(direction, f"au {direction}")
