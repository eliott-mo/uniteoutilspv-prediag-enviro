# -*- coding: utf-8 -*-
"""Ce qu'une coupe croise, rangé dans une structure qui se sérialise.

Le rendu ne lit que cette structure : une coupe se redessine depuis son JSON,
sans réseau, et le prédiagnostic peut en citer les chiffres.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from functools import cached_property

from shapely import STRtree, force_2d
from shapely.geometry import LineString, shape
from shapely.geometry.base import BaseGeometry

from . import geometrie as geo
from .reglages import (CLASSES_VEGETATION, ECART_COURS_D_EAU, ECART_ROUTES,
                       IMPORTANCES_LIEUX, IMPORTANCES_ROUTES,
                       TAMPON_HABITATIONS)

#: Un tronçon de commune plus court ne compte pas comme une traversée : le
#: trait qui longe une limite la franchit plusieurs fois sur quelques mètres.
TRAVERSEE_MIN_M = 20.0


def _texte(valeur) -> str:
    return str(valeur).strip() if valeur not in (None, "") else ""


@dataclass
class Donnees:
    """La BD TOPO autour du site, en Lambert 93, prête à croiser."""
    bbox: tuple
    vegetation: list = field(default_factory=list)    # (géométrie, classe)
    communes: list = field(default_factory=list)      # (géométrie, nom)
    cours_d_eau: list = field(default_factory=list)   # (géométrie, toponyme)
    routes: list = field(default_factory=list)        # (géométrie, numéro)
    habitations: list = field(default_factory=list)   # (géométrie, nom, importance)
    date: date | None = None

    @classmethod
    def depuis_lectures(cls, bbox, lectures: dict) -> "Donnees":
        """Depuis les entités GeoJSON lues par `ign.entites`, couche par couche."""
        def geometries(cle):
            lecture = lectures.get(cle)
            for e in (lecture.entites if lecture else []):
                if e.get("geometry"):
                    yield force_2d(shape(e["geometry"])), e.get("properties") or {}

        vegetation = [(g, CLASSES_VEGETATION[p.get("nature")])
                      for g, p in geometries("vegetation")
                      if p.get("nature") in CLASSES_VEGETATION]
        communes = [(g, _texte(p.get("nom_officiel"))) for g, p in geometries("communes")]
        cours = [(g, geo.capitale(geo.abreger(_texte(p.get("toponyme")))))
                 for g, p in geometries("cours_d_eau")]
        routes = [(g, _texte(p.get("cpx_numero"))) for g, p in geometries("routes")
                  if _texte(p.get("importance")) in IMPORTANCES_ROUTES]
        habitations = [(g, geo.capitale(_texte(p.get("toponyme"))),
                        _texte(p.get("importance")))
                       for g, p in geometries("habitations")]
        jours = [lec.date for lec in lectures.values() if lec is not None]
        return cls(tuple(bbox), vegetation, communes, cours, routes, habitations,
                   min(jours) if jours else None)

    @cached_property
    def _index(self) -> dict:
        """Un index spatial par couche : chaque coupe n'interroge que ce qu'elle
        traverse, sur les deux mille polygones de végétation d'un carré de
        10 km."""
        return {cle: STRtree([e[0] for e in getattr(self, cle)])
                for cle in ("vegetation", "communes", "cours_d_eau", "routes",
                            "habitations")}

    def touchant(self, cle: str, geometrie: BaseGeometry) -> list:
        """Les entités d'une couche dont l'emprise touche la géométrie."""
        entites = getattr(self, cle)
        if not entites:
            return []
        return [entites[i] for i in sorted(self._index[cle].query(geometrie))]


def fusionner(intervalles) -> list[tuple[float, float]]:
    """Réunit les intervalles qui se touchent ou se chevauchent."""
    resultat: list[list[float]] = []
    for a, b in sorted(intervalles):
        if resultat and a <= resultat[-1][1]:
            resultat[-1][1] = max(resultat[-1][1], b)
        else:
            resultat.append([a, b])
    return [(a, b) for a, b in resultat]


def _arrondir(intervalles):
    return [(round(a, 2), round(b, 2)) for a, b in intervalles]


@dataclass
class Coupe:
    """Une coupe : son profil, et ce qu'elle croise, en distance du départ."""
    identifiant: str                       # « N-S_10km », « libre_1 »
    nom: str                               # « N-S », « Le Mas Blanc – SE »
    extremites: tuple                      # (« N », « S »)
    depart: tuple                          # (x, y) en Lambert 93
    arrivee: tuple
    distances: list
    altitudes: list
    demi_longueur: float | None = None     # None pour une coupe libre
    emprise: list = field(default_factory=list)
    surface_utile: list = field(default_factory=list)
    vegetation: dict = field(default_factory=dict)
    communes: list = field(default_factory=list)       # (nom, début, fin)
    cours_d_eau: list = field(default_factory=list)    # (distance, nom)
    routes: list = field(default_factory=list)         # (distance, numéro)
    lieux: list = field(default_factory=list)          # (distance, nom)

    @property
    def longueur(self) -> float:
        return self.distances[-1]

    @property
    def ligne(self) -> LineString:
        return LineString([self.depart, self.arrivee])

    @property
    def point_haut(self) -> tuple[float, float]:
        i = max(range(len(self.altitudes)), key=self.altitudes.__getitem__)
        return self.distances[i], self.altitudes[i]

    @property
    def point_bas(self) -> tuple[float, float]:
        i = min(range(len(self.altitudes)), key=self.altitudes.__getitem__)
        return self.distances[i], self.altitudes[i]

    def altitudes_emprise(self) -> list[float]:
        """Les altitudes du profil dans l'emprise."""
        return [z for d, z in zip(self.distances, self.altitudes)
                if any(a <= d <= b for a, b in self.emprise)]

    def communes_traversees(self) -> list[str]:
        """Les communes dans l'ordre du trait, une fois chacune."""
        noms: list[str] = []
        for nom, a, b in self.communes:
            if b - a >= TRAVERSEE_MIN_M and nom not in noms:
                noms.append(nom)
        return noms

    def coordonnees(self, distance: float) -> tuple[float, float]:
        (x0, y0), (x1, y1) = self.depart, self.arrivee
        t = distance / self.longueur if self.longueur else 0.0
        return x0 + (x1 - x0) * t, y0 + (y1 - y0) * t

    # ───────────────────────────────────────────────────────────── JSON

    def en_dict(self) -> dict:
        haut, bas = self.point_haut, self.point_bas
        z_emprise = self.altitudes_emprise()
        return {
            "identifiant": self.identifiant, "nom": self.nom,
            "extremites": list(self.extremites),
            "depart": list(self.depart), "arrivee": list(self.arrivee),
            "demi_longueur": self.demi_longueur,
            "longueur": self.longueur,
            "profil": [[d, *(round(v, 2) for v in self.coordonnees(d)), z]
                       for d, z in zip(self.distances, self.altitudes)],
            "point_haut": {"distance": haut[0], "altitude": haut[1]},
            "point_bas": {"distance": bas[0], "altitude": bas[1]},
            "altitude_emprise": ({"min": min(z_emprise), "max": max(z_emprise)}
                                 if z_emprise else None),
            "emprise": [list(i) for i in self.emprise],
            "surface_utile": [list(i) for i in self.surface_utile],
            "vegetation": {k: [list(i) for i in v] for k, v in self.vegetation.items()},
            "communes": [list(c) for c in self.communes],
            "cours_d_eau": [list(c) for c in self.cours_d_eau],
            "routes": [list(r) for r in self.routes],
            "lieux": [list(lieu) for lieu in self.lieux],
        }

    @classmethod
    def depuis_dict(cls, d: dict) -> "Coupe":
        return cls(
            identifiant=d["identifiant"], nom=d["nom"],
            extremites=tuple(d["extremites"]),
            depart=tuple(d["depart"]), arrivee=tuple(d["arrivee"]),
            distances=[p[0] for p in d["profil"]],
            altitudes=[p[3] for p in d["profil"]],
            demi_longueur=d.get("demi_longueur"),
            emprise=[tuple(i) for i in d["emprise"]],
            surface_utile=[tuple(i) for i in d["surface_utile"]],
            vegetation={k: [tuple(i) for i in v] for k, v in d["vegetation"].items()},
            communes=[tuple(c) for c in d["communes"]],
            cours_d_eau=[tuple(c) for c in d["cours_d_eau"]],
            routes=[tuple(r) for r in d["routes"]],
            lieux=[tuple(lieu) for lieu in d["lieux"]],
        )


def assembler(identifiant: str, nom: str, extremites, ligne: LineString,
              distances, altitudes, donnees: Donnees, emprise: BaseGeometry,
              surface_utile: BaseGeometry | None = None,
              demi_longueur: float | None = None) -> Coupe:
    """Croise le trait avec l'emprise et les couches de la BD TOPO."""
    longueur = ligne.length

    vegetation: dict[str, list] = {}
    for g, classe in donnees.touchant("vegetation", ligne):
        vegetation.setdefault(classe, []).extend(geo.intervalles(ligne, g))
    vegetation = {k: _arrondir(fusionner(v)) for k, v in vegetation.items() if v}

    communes = sorted(((nom_c, a, b)
                       for g, nom_c in donnees.touchant("communes", ligne)
                       for a, b in geo.intervalles(ligne, g)),
                      key=lambda c: c[1])
    communes = [(n, round(a, 2), round(b, 2)) for n, a, b in communes]

    # Les passages nommés d'abord : un doublon sans nom ne chasse pas le nom.
    passages = sorted(((d, n) for g, n in donnees.touchant("cours_d_eau", ligne)
                       for d in geo.croisements(ligne, g)),
                      key=lambda p: (p[1] == "", p[0]))
    cours = _dedoublonner(passages, ECART_COURS_D_EAU * longueur)

    traversees = sorted(((d, n) for g, n in donnees.touchant("routes", ligne)
                         for d in geo.croisements(ligne, g)),
                        key=lambda p: (p[1] == "", p[0]))
    routes = _dedoublonner(traversees, ECART_ROUTES * longueur)

    couloir = ligne.buffer(TAMPON_HABITATIONS)
    candidats = [(n, a, b)
                 for g, n, importance in donnees.touchant("habitations", couloir)
                 if n and importance in IMPORTANCES_LIEUX
                 for a, b in geo.intervalles(ligne, g.buffer(TAMPON_HABITATIONS))]
    lieux = [(round(d, 2), n) for d, n in geo.lieux_a_nommer(candidats, longueur)]

    return Coupe(
        identifiant=identifiant, nom=nom, extremites=tuple(extremites),
        depart=tuple(round(v, 2) for v in ligne.coords[0]),
        arrivee=tuple(round(v, 2) for v in ligne.coords[-1]),
        distances=[round(float(d), 2) for d in distances],
        altitudes=[round(float(z), 2) for z in altitudes],
        demi_longueur=demi_longueur,
        emprise=_arrondir(geo.intervalles(ligne, emprise)),
        surface_utile=(_arrondir(geo.intervalles(ligne, surface_utile))
                       if surface_utile is not None else []),
        vegetation=vegetation, communes=communes, cours_d_eau=cours,
        routes=routes, lieux=lieux,
    )


def _dedoublonner(passages, ecart: float) -> list[tuple[float, str]]:
    gardes: list[tuple[float, str]] = []
    for d, n in passages:
        if all(abs(d - q) >= ecart for q, _ in gardes):
            gardes.append((d, n))
    return sorted((round(d, 2), n) for d, n in gardes)


def sous_coupe(coupe: Coupe, demi_longueur: float, identifiant: str,
               donnees: Donnees, emprise: BaseGeometry,
               surface_utile: BaseGeometry | None = None) -> Coupe:
    """La coupe plus courte de même centre et même direction, sans réseau.

    Ses points sont ceux de la longue : le pas part de l'extrémité, et l'écart
    entre les deux demi-longueurs en est un multiple.
    """
    pas = coupe.distances[1] - coupe.distances[0]
    decalage = int(round((coupe.demi_longueur - demi_longueur) / pas))
    n = int(round(2 * demi_longueur / pas))
    (x0, y0), (x1, y1) = coupe.depart, coupe.arrivee
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    ux, uy = (x1 - x0) / coupe.longueur, (y1 - y0) / coupe.longueur
    ligne = LineString([(mx - ux * demi_longueur, my - uy * demi_longueur),
                        (mx + ux * demi_longueur, my + uy * demi_longueur)])
    distances = [d - coupe.distances[decalage]
                 for d in coupe.distances[decalage:decalage + n + 1]]
    return assembler(identifiant, coupe.nom, coupe.extremites, ligne, distances,
                     coupe.altitudes[decalage:decalage + n + 1], donnees, emprise,
                     surface_utile, demi_longueur=demi_longueur)
