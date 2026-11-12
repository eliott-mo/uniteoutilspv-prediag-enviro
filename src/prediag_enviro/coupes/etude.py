# -*- coding: utf-8 -*-
"""L'étude d'un site : lire une fois, couper huit fois, livrer.

La BD TOPO est lue une seule fois par site, sur un carré qui couvre la plus
longue coupe ; les profils des coupes de 4 km sont pris dans ceux de 10 km.
Quatre requêtes altimétriques et cinq couches suffisent donc aux huit coupes,
et tout est rangé en cache : un second rendu ne demande plus rien au réseau.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from matplotlib.backends.backend_pdf import PdfPages
from shapely.geometry import Point, box
from shapely.geometry.base import BaseGeometry

from . import geometrie as geo
from . import ign, profil, rendu
from .profil import Coupe, Donnees
from .reglages import (AU_DELA_LIBRE, AZIMUTS, COUCHES, DEMI_LONGUEURS, DPI,
                       EXTREMITES, LIBELLE_EMPRISE, MARGE_REQUETE, PAS,
                       RECUL_LIBRE, TAILLE_COUPE, TAILLE_COUPE_DOCUMENT,
                       TAILLE_PLAN, TAILLE_PLAN_DOCUMENT, TAMPON_HABITATIONS)

#: Ce que les messages d'erreur appellent chaque couche.
LIBELLES_COUCHES = {"vegetation": "zones de végétation", "communes": "communes",
                    "cours_d_eau": "cours d'eau", "routes": "routes",
                    "habitations": "zones d'habitation"}


def _identifiant(nom: str, demi_longueur: float) -> str:
    return f"{nom}_{int(round(2 * demi_longueur / 1000))}km"


def nom_de_fichier(site: str) -> str:
    """« Bédarieux » → « Bedarieux » : un nom de fichier sans accent ni espace."""
    sans_accent = unicodedata.normalize("NFKD", site).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9_-]+", "_", sans_accent).strip("_") or "site"


@dataclass
class Etude:
    """Les données d'un site et ses coupes, prêtes à dessiner."""
    emprise: BaseGeometry
    centre: Point
    donnees: Donnees
    coupes: list = field(default_factory=list)
    surface_utile: BaseGeometry | None = None
    libelle_emprise: str = LIBELLE_EMPRISE
    source_emprise: str = "fichier fourni"
    cache: Path | None = None
    pas: float = PAS

    def coupe(self, identifiant: str) -> Coupe:
        for c in self.coupes:
            if c.identifiant == identifiant:
                return c
        raise KeyError(identifiant)

    @property
    def jour(self):
        return self.donnees.date

    def altitudes_emprise(self) -> tuple[float, float] | None:
        """Les altitudes extrêmes de l'emprise, lues sur les coupes centrées."""
        z = [v for c in self.coupes if c.demi_longueur for v in c.altitudes_emprise()]
        return (min(z), max(z)) if z else None


def charger_donnees(bbox, cache: Path | None = None) -> Donnees:
    """Les cinq couches de la BD TOPO sur le carré de la requête."""
    lectures = {}
    for cle, (couche, proprietes, filtre) in COUCHES.items():
        lectures[cle] = ign.entites(couche, bbox, proprietes=proprietes,
                                    filtre=filtre, cache=cache,
                                    libelle=LIBELLES_COUCHES[cle])
    return Donnees.depuis_lectures(bbox, lectures)


def _profil(ligne, xs, ys, pas: float, cache: Path | None) -> list[float]:
    """Les altitudes d'un trait, relues du cache si elles y sont."""
    fichier = None
    if cache is not None:
        cle = json.dumps([ign.FORMAT_CACHE, [round(v, 1) for c in ligne.coords
                                             for v in c], pas])
        fichier = Path(cache) / f"profil_{hashlib.sha1(cle.encode()).hexdigest()[:12]}.json"
        if fichier.exists():
            z = json.loads(fichier.read_text(encoding="utf-8"))
            if len(z) == len(xs):
                return z
    z = ign.altitudes(list(zip(xs, ys)))
    if fichier is not None:
        fichier.parent.mkdir(parents=True, exist_ok=True)
        fichier.write_text(json.dumps(z), encoding="utf-8")
    return z


def etudier(emprise: BaseGeometry, surface_utile: BaseGeometry | None = None, *,
            cache: Path | None = None, libelle_emprise: str = LIBELLE_EMPRISE,
            source_emprise: str = "fichier fourni",
            demi_longueurs=DEMI_LONGUEURS, pas: float = PAS) -> Etude:
    """Les huit coupes d'un site, autour du plus grand bloc de l'emprise.

    `emprise` et `surface_utile` sont en Lambert 93. Une erreur du service IGN
    lève `ign.ErreurIGN`, dont le message dit quoi faire : jamais une figure
    vide.
    """
    emprise = emprise.buffer(0)
    if surface_utile is not None:
        surface_utile = surface_utile.buffer(0)
    centre = geo.centre(emprise)
    plus_longue = max(demi_longueurs)
    rayon = plus_longue + MARGE_REQUETE
    bbox = (centre.x - rayon, centre.y - rayon, centre.x + rayon, centre.y + rayon)
    donnees = charger_donnees(bbox, cache)

    longues = {}
    for nom, azimut in AZIMUTS.items():
        ligne = geo.trait(centre, azimut, plus_longue)
        distances, xs, ys = geo.echantillons(ligne, pas)
        z = _profil(ligne, xs, ys, pas, cache)
        longues[nom] = profil.assembler(
            _identifiant(nom, plus_longue), nom, EXTREMITES[nom], ligne, distances,
            z, donnees, emprise, surface_utile, demi_longueur=plus_longue)

    liste = []
    for demi in sorted(demi_longueurs):
        for nom in AZIMUTS:
            if demi == plus_longue:
                liste.append(longues[nom])
            else:
                liste.append(profil.sous_coupe(longues[nom], demi,
                                               _identifiant(nom, demi), donnees,
                                               emprise, surface_utile))
    return Etude(emprise=emprise, centre=centre, donnees=donnees, coupes=liste,
                 surface_utile=surface_utile, libelle_emprise=libelle_emprise,
                 source_emprise=source_emprise, cache=cache, pas=pas)


# ──────────────────────────────────────────────────────────── coupe libre

@dataclass
class Lieu:
    """Un lieu habité vers lequel tirer une coupe."""
    nom: str
    point: Point
    distance: float
    direction: str        # vu de la ZIP

    @property
    def libelle(self) -> str:
        distance = f"{self.distance / 1000:.1f}".replace(".", ",")
        return f"{self.nom} — {distance} km {geo.en_lettres(self.direction)}"


def lieux_proches(etude: Etude, rayon: float | None = None) -> list[Lieu]:
    """Les lieux habités autour de la ZIP, du plus proche au plus lointain.

    Un nom n'apparaît qu'une fois, à son point le plus proche ; les lieux qui
    touchent l'emprise sont écartés.
    """
    rayon = rayon or max(c.demi_longueur or 0 for c in etude.coupes) or 5000.0
    meilleurs: dict[str, Lieu] = {}
    for g, nom, _ in etude.donnees.habitations:
        if not nom or g.intersects(etude.emprise):
            continue
        point = g.representative_point()
        distance = point.distance(etude.centre)
        if distance > rayon:
            continue
        if nom not in meilleurs or distance < meilleurs[nom].distance:
            meilleurs[nom] = Lieu(nom, point, distance,
                                  geo.rose(point.x - etude.centre.x,
                                           point.y - etude.centre.y))
    return sorted(meilleurs.values(), key=lambda lieu: lieu.distance)


_VERS_L93 = None


def _dans_la_metropole(lat: float, lon: float) -> bool:
    return 41.0 <= lat <= 51.5 and -5.5 <= lon <= 10.0


def point_l93(texte: str) -> Point:
    """« 43.6123, 3.1654 », collé du Géoportail, en point Lambert 93.

    Les virgules décimales passent si les deux nombres sont séparés par un
    point-virgule ; l'ordre longitude, latitude est reconnu et remis d'aplomb.
    """
    global _VERS_L93
    brut = texte.strip()
    if ";" in brut:
        morceaux = brut.split(";")
    elif "." in brut or brut.count(",") == 1:
        morceaux = re.split(r"[,\s]+", brut)
    else:
        morceaux = brut.split()
    try:
        a, b = (float(m.strip().replace(",", ".")) for m in morceaux if m.strip())
    except ValueError:
        raise ValueError(f"« {texte} » : deux nombres attendus, latitude, "
                         "longitude en degrés décimaux") from None
    if not _dans_la_metropole(a, b) and _dans_la_metropole(b, a):
        a, b = b, a
    if not _dans_la_metropole(a, b):
        raise ValueError(f"« {texte} » : hors de France métropolitaine, que "
                         "couvrent le RGE ALTI et la BD TOPO")
    if _VERS_L93 is None:
        from pyproj import Transformer
        _VERS_L93 = Transformer.from_crs(4326, 2154, always_xy=True)
    x, y = _VERS_L93.transform(b, a)
    return Point(x, y)


def ajouter_coupe_libre(etude: Etude, depart: Point, nom_depart: str) -> Coupe:
    """Une coupe du lieu `depart` à travers la ZIP, ajoutée à l'étude."""
    ligne = geo.trait_libre(depart, etude.centre, recul=RECUL_LIBRE,
                            au_dela=AU_DELA_LIBRE)
    besoin = ligne.buffer(TAMPON_HABITATIONS * 2)
    if not box(*etude.donnees.bbox).contains(besoin):
        # Un point de vue au-delà du carré lu : on relit sur l'union des deux.
        x0, y0, x1, y1 = etude.donnees.bbox
        a0, b0, a1, b1 = besoin.bounds
        etude.donnees = charger_donnees((min(x0, a0), min(y0, b0), max(x1, a1),
                                         max(y1, b1)), etude.cache)
    distances, xs, ys = geo.echantillons(ligne, etude.pas)
    z = _profil(ligne, xs, ys, etude.pas, etude.cache)
    fin = geo.rose(etude.centre.x - depart.x, etude.centre.y - depart.y)
    n = 1 + sum(1 for c in etude.coupes if c.demi_longueur is None)
    coupe = profil.assembler(f"libre_{n}", f"{nom_depart} – {fin}",
                             (nom_depart, fin), ligne, distances, z, etude.donnees,
                             etude.emprise, etude.surface_utile)
    etude.coupes.append(coupe)
    return coupe


# ─────────────────────────────────────────────────────────────── livrables

@dataclass
class Livrables:
    plan: Path
    coupes: dict           # identifiant → PNG
    pdf: Path
    json: Path


def _json(etude: Etude, coupes: list[Coupe], site: str) -> dict:
    extremes = etude.altitudes_emprise()
    return {
        "site": site,
        "centre": [round(etude.centre.x, 2), round(etude.centre.y, 2)],
        "crs": "EPSG:2154",
        "consultation": etude.jour.isoformat() if etude.jour else None,
        "sources": "IGN – RGE ALTI® et BD TOPO® V3 (Géoplateforme)",
        "altitude_emprise": ({"min": extremes[0], "max": extremes[1]}
                             if extremes else None),
        "coupes": [c.en_dict() for c in coupes],
    }


def produire(etude: Etude, dossier: Path, site: str = "") -> Livrables:
    """Les livrables du brief : plan, une image par coupe, le PDF, le JSON."""
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    options = dict(libelle_emprise=etude.libelle_emprise,
                   source_emprise=etude.source_emprise, jour=etude.jour)
    figures, images = [], {}
    for c in etude.coupes:
        fig = rendu.dessiner_figure_coupe(c, taille=TAILLE_COUPE, **options)
        chemin = dossier / f"coupe_{c.identifiant}.png"
        fig.savefig(chemin, dpi=DPI)
        figures.append(fig)
        images[c.identifiant] = chemin
    fig_plan, _ = rendu.figure_plan(etude.donnees, etude.coupes, etude.emprise,
                                    etude.centre, surface_utile=etude.surface_utile,
                                    site=site, taille=TAILLE_PLAN, **options)
    plan = dossier / "plan_reperage.png"
    fig_plan.savefig(plan, dpi=DPI)
    base = f"coupes_topographiques_{nom_de_fichier(site)}"
    pdf = dossier / f"{base}.pdf"
    with PdfPages(pdf) as document:
        document.savefig(fig_plan)
        for fig in figures:
            document.savefig(fig)
    fichier_json = dossier / f"{base}.json"
    fichier_json.write_text(json.dumps(_json(etude, etude.coupes, site),
                                       ensure_ascii=False), encoding="utf-8")
    return Livrables(plan=plan, coupes=images, pdf=pdf, json=fichier_json)


@dataclass
class CoupesDuDocument:
    """Ce que le prédiagnostic insère : le plan des coupes retenues, et elles."""
    plan: Path
    coupes: list                       # (Coupe, PNG), dans l'ordre de l'étude
    altitudes_emprise: tuple | None
    jour: object
    pdf: str                           # nom du PDF des huit coupes


def pour_le_document(etude: Etude, identifiants, dossier: Path,
                     site: str = "") -> CoupesDuDocument | None:
    """Les coupes retenues, à la taille d'une page A4 couchée."""
    retenues = [c for c in etude.coupes if c.identifiant in set(identifiants)]
    if not retenues:
        return None
    dossier = Path(dossier)
    options = dict(libelle_emprise=etude.libelle_emprise,
                   source_emprise=etude.source_emprise, jour=etude.jour)
    images = []
    for c in retenues:
        chemin = dossier / f"document_coupe_{c.identifiant}.png"
        rendu.dessiner_coupe(c, chemin, taille=TAILLE_COUPE_DOCUMENT, **options)
        images.append((c, chemin))
    plan = rendu.dessiner_plan(etude.donnees, retenues, etude.emprise, etude.centre,
                               dossier / "document_plan_coupes.png",
                               surface_utile=etude.surface_utile, site=site,
                               taille=TAILLE_PLAN_DOCUMENT, **options).chemin
    return CoupesDuDocument(plan=plan, coupes=images,
                            altitudes_emprise=etude.altitudes_emprise(),
                            jour=etude.jour,
                            pdf=f"coupes_topographiques_{nom_de_fichier(site)}.pdf")
