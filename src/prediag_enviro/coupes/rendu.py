# -*- coding: utf-8 -*-
"""Le dessin d'une coupe et du plan de repérage, depuis la seule structure.

Le rendu est celui du prototype validé sur Bédarieux : trois bandeaux qui
partagent l'axe des distances (communes, profil, occupation du sol), la ZIP en
bande verticale, la végétation posée sur le terrain.

Une règle de plus que le prototype : **une étiquette ne se pose que sur une
place libre**. Chaque texte est mesuré au rendu ; s'il touche la légende ou un
texte déjà posé, une autre hauteur est essayée, puis il est abandonné. Le
prototype écartait les noms à 6 % de la longueur, ce qui suffisait à 16 pouces
de large mais pas à 11, la taille du prédiagnostic.

Les figures sont construites hors de pyplot (`Figure` et toile Agg) :
l'interface Streamlit les produit depuis plusieurs fils, que l'état global de
pyplot ne supporte pas.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import geopandas as gpd
import matplotlib.patheffects as pe
import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, Patch, Rectangle
from matplotlib.transforms import Bbox
from shapely.geometry import Point, box

from .profil import Coupe, Donnees
from .reglages import (COULEURS, COULEURS_VEGETATION, DPI, LIBELLE_EMPRISE,
                       MARGE_PLAN, ORDRE_VEGETATION, PART_NOM_COMMUNE,
                       TAILLE_COUPE, TAILLE_PLAN, VEGETATION_BASSE)


#: Liseré blanc des noms posés sur le terrain ou la végétation.
LISERE = [pe.withStroke(linewidth=2.2, foreground="white", alpha=0.85)]

#: Un même nom de cours d'eau ne revient pas à moins de cette part de la
#: longueur : le Rau de Serieis recoupait la NE-SO de Bédarieux à 200 m.
FENETRE_MEME_NOM = 0.10


def en_km(metres: float) -> str:
    """10000 → « 10 », 5300 → « 5,3 »."""
    texte = f"{metres / 1000:.1f}".rstrip("0").rstrip(".")
    return texte.replace(".", ",")


def _milliers(valeur: float) -> str:
    return f"{int(round(valeur)):,}".replace(",", " ")


def _jour(jour: date | None) -> str:
    return (jour or date.today()).strftime("%d/%m/%Y")


def titre_coupe(coupe: Coupe, exageration: float) -> str:
    ve = f"{exageration:.1f}".replace(".", ",")
    if coupe.demi_longueur:
        portee = (f" ({en_km(coupe.demi_longueur)} km de part et d'autre du "
                  "projet)")
    else:
        portee = ""
    return (f"Coupe {coupe.nom} — longueur {en_km(coupe.longueur)} km{portee}"
            f"  ·  exagération verticale ×{ve}")


class _Places:
    """Ce qui est déjà écrit sur la figure : une étiquette ne s'y pose pas."""

    MARGE_PX = 2.0

    def __init__(self, fig: Figure):
        self.rendu = fig.canvas.get_renderer()
        self.etiquettes: list[tuple[str, Bbox]] = []
        self.interdites: list[Bbox] = []

    def boite(self, artiste) -> Bbox:
        return artiste.get_window_extent(self.rendu)

    def reserver(self, nom: str, artiste) -> Bbox:
        b = self.boite(artiste)
        self.etiquettes.append((nom, b))
        return b

    def interdire(self, artiste) -> Bbox:
        b = self.boite(artiste)
        self.interdites.append(b)
        return b

    def libre(self, b: Bbox, cadre: Bbox | None = None) -> bool:
        if cadre is not None and (b.x0 < cadre.x0 or b.x1 > cadre.x1
                                  or b.y0 < cadre.y0 or b.y1 > cadre.y1):
            return False
        m = self.MARGE_PX
        elargie = Bbox.from_extents(b.x0 - m, b.y0 - m, b.x1 + m, b.y1 + m)
        return not any(elargie.overlaps(o) for o in self.interdites) and \
            not any(elargie.overlaps(o) for _, o in self.etiquettes)

    def poser(self, nom: str, essais, cadre: Bbox | None = None):
        """Le premier essai qui tombe sur une place libre, ou rien."""
        for fabriquer in essais:
            artiste = fabriquer()
            if self.libre(self.boite(artiste), cadre):
                self.reserver(nom, artiste)
                return artiste
            artiste.remove()
        return None


@dataclass
class RenduCoupe:
    chemin: Path
    titre: str
    exageration: float
    etiquettes: list = field(default_factory=list)   # (texte, Bbox en pixels)
    legende: Bbox | None = None


def _poignees_coupe(coupe: Coupe, libelle_emprise: str) -> list:
    poignees = [Patch(color=COULEURS["terrain"], label="Terrain (RGE ALTI)")]
    if coupe.emprise:
        poignees.append(Patch(color=COULEURS["emprise"], alpha=0.4,
                              label=libelle_emprise))
    if coupe.surface_utile:
        poignees.append(Line2D([], [], color=COULEURS["surface_utile"], lw=4,
                               label="Surface utile (panneaux)"))
    poignees += [Patch(color=COULEURS_VEGETATION[c], label=c)
                 for c in ORDRE_VEGETATION if coupe.vegetation.get(c)]
    if len(coupe.communes_traversees()) > 1:
        poignees.append(Line2D([], [], color=COULEURS["commune"], ls="--",
                               label="Limite communale"))
    if coupe.cours_d_eau:
        poignees.append(Line2D([], [], marker="v", ls="", color=COULEURS["cours_d_eau"],
                               label="Cours d'eau"))
    if coupe.routes:
        poignees.append(Line2D([], [], marker="|", ls="", color=COULEURS["route"],
                               ms=9, mew=1.6, label="Route principale"))
    return poignees


def dessiner_coupe(coupe: Coupe, chemin: Path, *, taille=TAILLE_COUPE, dpi=DPI,
                   libelle_emprise: str = LIBELLE_EMPRISE,
                   source_emprise: str = "fichier fourni",
                   jour: date | None = None) -> RenduCoupe:
    """Dessine une coupe en PNG et dit ce qui a été posé."""
    fig = dessiner_figure_coupe(coupe, taille=taille, libelle_emprise=libelle_emprise,
                                source_emprise=source_emprise, jour=jour)
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(chemin, dpi=dpi)
    rendu = fig._rendu_coupe
    rendu.chemin = chemin
    return rendu


def dessiner_figure_coupe(coupe: Coupe, *, taille=TAILLE_COUPE,
                          libelle_emprise: str = LIBELLE_EMPRISE,
                          source_emprise: str = "fichier fourni",
                          jour: date | None = None) -> Figure:
    """La figure d'une coupe, à enregistrer en PNG ou à verser dans un PDF."""
    largeur, hauteur = taille
    fig = Figure(figsize=taille)
    FigureCanvasAgg(fig)
    grille = fig.add_gridspec(
        3, 1, height_ratios=[0.55, 5, 1.1], hspace=0.05,
        left=1.35 / largeur, right=1 - 0.25 / largeur,
        top=1 - 0.8 / hauteur, bottom=0.62 / hauteur)
    ax_communes, ax, ax_sol = (fig.add_subplot(g) for g in grille)

    d = np.asarray(coupe.distances, dtype=float)
    z = np.asarray(coupe.altitudes, dtype=float)
    longueur = coupe.longueur

    def zi(s):
        return np.interp(s, d, z)

    zmin, zmax = float(z.min()), float(z.max())
    amplitude = max(zmax - zmin, 10.0)
    bas = float(np.floor((zmin - 0.42 * amplitude) / 10) * 10)
    haut = zmax + 0.55 * amplitude
    lignes = len(ORDRE_VEGETATION)
    for a in (ax_communes, ax, ax_sol):
        a.set_xlim(0, longueur)
    ax.set_ylim(bas, haut)
    ax_communes.set_ylim(0, 1)
    ax_sol.set_ylim(0, lignes)
    epaisseur = 0.035 * (haut - bas)

    # Emprise et surface utile : bandes verticales.
    for intervalles, couleur, opacite in ((coupe.emprise, COULEURS["emprise"], 0.28),
                                          (coupe.surface_utile,
                                           COULEURS["surface_utile"], 0.35)):
        for a, b in intervalles:
            ax.axvspan(a, b, color=couleur, alpha=opacite, lw=0, zorder=1)
            ax_sol.axvspan(a, b, color=couleur, alpha=opacite, lw=0)

    # Terrain.
    ax.fill_between(d, bas, z, color=COULEURS["terrain"], zorder=2)
    ax.plot(d, z, color=COULEURS["profil"], lw=1.3, zorder=4)

    # Végétation : bande posée sur le profil, et ligne du bandeau du bas.
    for classe, intervalles in coupe.vegetation.items():
        if classe not in ORDRE_VEGETATION:
            continue
        rang = ORDRE_VEGETATION.index(classe)
        ep = epaisseur * (0.5 if classe in VEGETATION_BASSE else 1.0)
        for a, b in intervalles:
            s = np.linspace(a, b, max(2, int((b - a) / 5)))
            zz = zi(s)
            ax.fill_between(s, zz, zz + ep, color=COULEURS_VEGETATION[classe],
                            lw=0, zorder=3)
            ax_sol.add_patch(Rectangle((a, lignes - 1 - rang + 0.1), b - a, 0.8,
                                       color=COULEURS_VEGETATION[classe], lw=0))

    # Surface utile sur le profil.
    for a, b in coupe.surface_utile:
        s = np.linspace(a, b, 50)
        ax.plot(s, zi(s), color=COULEURS["surface_utile"], lw=4, zorder=5,
                solid_capstyle="butt")

    # Limites communales sur les trois bandeaux.
    for _, a, b in coupe.communes:
        for s in (a, b):
            if 1 < s < longueur - 1:
                for axe in (ax_communes, ax, ax_sol):
                    axe.axvline(s, color=COULEURS["commune"], ls=(0, (5, 3)),
                                lw=1, zorder=6)

    # Repères des cours d'eau et des routes : les marques d'abord, les noms
    # ensuite, s'il y a la place.
    for s, _ in coupe.cours_d_eau:
        ax.plot(s, zi(s), marker="v", color=COULEURS["cours_d_eau"], ms=7, zorder=7)
    for s, _ in coupe.routes:
        ax.plot(s, zi(s), marker="|", color=COULEURS["route"], ms=9, mew=1.6,
                zorder=7)

    # Habillage des axes.
    for axe in (ax_communes, ax):
        axe.set_xticks([])
    ax_communes.set_yticks([])
    ax_communes.set_ylabel("Communes", fontsize=8, color=COULEURS["commune"],
                           rotation=0, ha="right", va="center")
    for bord in ax_communes.spines.values():
        bord.set_color("#bbbbbb")
    ax.set_ylabel("Altitude (m NGF)", fontsize=9)
    ax.tick_params(labelsize=8)
    ax.grid(axis="y", color="#dddddd", lw=0.6)
    ax.set_axisbelow(True)
    for cote in ("top", "right"):
        ax.spines[cote].set_visible(False)
    ax_sol.set_yticks([lignes - 0.5 - i for i in range(lignes)])
    ax_sol.set_yticklabels(ORDRE_VEGETATION, fontsize=7.5)
    ax_sol.tick_params(axis="y", length=0)
    ax_sol.set_xlabel("Distance (m)", fontsize=9)
    ax_sol.grid(axis="x", color="#eeeeee")
    graduations = np.arange(0, longueur + 1, 500 if longueur <= 5000 else 1000)
    ax_sol.set_xticks(graduations)
    ax_sol.set_xticklabels([_milliers(v) for v in graduations], fontsize=8)

    legende = ax.legend(handles=_poignees_coupe(coupe, libelle_emprise),
                        loc="upper left", ncol=5 if largeur >= 14 else 4,
                        fontsize=7.5, frameon=True, framealpha=0.9,
                        edgecolor="#cccccc")

    # La mise en page est fixée : l'exagération se mesure sur l'axe réel.
    places = _Places(fig)
    cadre = ax.get_window_extent(places.rendu)
    exageration = (longueur / cadre.width) / ((haut - bas) / cadre.height)
    titre = titre_coupe(coupe, exageration)
    places.interdire(legende)
    places.reserver("titre", ax_communes.set_title(
        titre, fontsize=12 if largeur >= 14 else 10.5, loc="center", pad=18))
    debut, fin = coupe.extremites
    for x, texte, aligne in ((0, debut, "left"), (1, fin, "right")):
        places.reserver(texte, ax_communes.text(
            x, 1.15, texte, transform=ax_communes.transAxes, fontsize=13,
            fontweight="bold", ha=aligne))
    places.reserver("points haut et bas", ax.text(
        0.995, 0.025, f"Point haut {zmax:.0f} m · point bas {zmin:.0f} m",
        transform=ax.transAxes, ha="right", va="bottom", fontsize=8,
        color="#555555"))

    # Noms des communes, centrés sur leur tronçon s'il est assez long et s'ils
    # y tiennent.
    for nom, a, b in coupe.communes:
        if b - a < PART_NOM_COMMUNE * longueur:
            continue
        x0, _ = ax_communes.transData.transform((a, 0))
        x1, _ = ax_communes.transData.transform((b, 0))
        haut_bande = ax_communes.get_window_extent(places.rendu)
        tronçon = Bbox.from_extents(x0, haut_bande.y0, x1, haut_bande.y1)
        places.poser(nom, [
            (lambda t=taille_police: ax_communes.text(
                (a + b) / 2, 0.5, nom, ha="center", va="center", fontsize=t,
                color="#333333"))
            for taille_police in (8.5, 7.0)], cadre=tronçon)

    # Repère du projet, sur le plus long tronçon de l'emprise.
    if coupe.emprise:
        a, b = max(coupe.emprise, key=lambda i: i[1] - i[0])
        s = (a + b) / 2
        places.poser("PROJET", [
            (lambda k=k: ax.annotate(
                "PROJET", (s, zi(s) + epaisseur * 1.2),
                xytext=(s, zi(s) + k * amplitude), ha="center", fontsize=10,
                fontweight="bold", color=COULEURS["projet"], zorder=8,
                arrowprops=dict(arrowstyle="-|>", color=COULEURS["projet"], lw=1.2)))
            for k in (0.32, 0.24, 0.40, 0.18)], cadre=cadre)

    # Lieux habités, en italique au-dessus du profil, avec un fil de rappel.
    # Le liseré blanc les détache d'une bande de forêt qu'ils survolent.
    for s, nom in coupe.lieux:
        pose = places.poser(nom, [
            (lambda k=k: ax.text(s, zi(s) + k * amplitude, nom, ha="center",
                                 fontsize=7.5, style="italic",
                                 color=COULEURS["lieu"], zorder=7,
                                 path_effects=LISERE))
            for k in (0.17, 0.11, 0.24)], cadre=cadre)
        if pose is not None:
            ax.plot([s, s], [zi(s) + epaisseur, pose.get_position()[1]],
                    color="#999999", lw=0.6, zorder=6)

    # Numéros des routes, sur fond blanc.
    for s, numero in coupe.routes:
        if not numero:
            continue
        places.poser(numero, [
            (lambda k=k: ax.text(s, zi(s) + k * amplitude + epaisseur, numero,
                                 ha="center", fontsize=7, color=COULEURS["route"],
                                 zorder=7, bbox=dict(fc="white", ec="none",
                                                     pad=0.5, alpha=0.8)))
            for k in (0.05, 0.10)], cadre=cadre)

    # Noms des cours d'eau, à la verticale sous le profil ; un même ruisseau
    # qui recoupe le trait à quelques centaines de mètres n'est nommé qu'une
    # fois.
    nommes: dict[str, list[float]] = {}
    for s, nom in coupe.cours_d_eau:
        if not nom or any(abs(s - q) < FENETRE_MEME_NOM * longueur
                          for q in nommes.get(nom, [])):
            continue
        pose = places.poser(nom, [
            (lambda dx=dx, aligne=aligne: ax.text(
                s + dx * longueur, zi(s) - 0.04 * amplitude, nom, rotation=90,
                ha=aligne, va="top", fontsize=7, color=COULEURS["cours_d_eau"],
                zorder=7, path_effects=LISERE))
            for dx, aligne in ((0.004, "left"), (-0.004, "right"))], cadre=cadre)
        if pose is not None:
            nommes.setdefault(nom, []).append(s)

    fig.text(0.01, 0.006,
             "Sources : IGN – RGE ALTI® (service altimétrique de la "
             "Géoplateforme) et BD TOPO® V3 (végétation, communes, cours d'eau, "
             f"routes, zones d'habitation), consultés le {_jour(jour)}. "
             f"Emprise : {source_emprise}.", fontsize=6.5, color="#666666")

    fig._rendu_coupe = RenduCoupe(chemin=Path(), titre=titre,
                                  exageration=exageration,
                                  etiquettes=places.etiquettes,
                                  legende=places.interdites[0])
    return fig


# ───────────────────────────────────────────────────────── plan de repérage

@dataclass
class RenduPlan:
    chemin: Path
    extremites: list = field(default_factory=list)   # (libellé, x, y)
    cercles: list = field(default_factory=list)


def _surfaces(ax, geometries, **style) -> None:
    if geometries:
        gpd.GeoSeries(list(geometries)).plot(ax=ax, **style)


def dessiner_plan(donnees: Donnees, coupes: list[Coupe], emprise, centre: Point,
                  chemin: Path, *, surface_utile=None, site: str = "",
                  taille=TAILLE_PLAN, dpi=DPI,
                  libelle_emprise: str = LIBELLE_EMPRISE,
                  source_emprise: str = "fichier fourni",
                  jour: date | None = None) -> RenduPlan:
    """Le plan de repérage : la carte à gauche, le zoom et la légende à droite.

    Ni le zoom ni la légende ne vont sur la carte : ils y masquaient les
    orientations des coupes.
    """
    fig, rendu = figure_plan(donnees, coupes, emprise, centre,
                             surface_utile=surface_utile, site=site, taille=taille,
                             libelle_emprise=libelle_emprise,
                             source_emprise=source_emprise, jour=jour)
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(chemin, dpi=dpi)
    rendu.chemin = chemin
    return rendu


def figure_plan(donnees: Donnees, coupes: list[Coupe], emprise, centre: Point, *,
                surface_utile=None, site: str = "", taille=TAILLE_PLAN,
                libelle_emprise: str = LIBELLE_EMPRISE,
                source_emprise: str = "fichier fourni",
                jour: date | None = None):
    largeur, hauteur = taille
    fig = Figure(figsize=taille)
    FigureCanvasAgg(fig)
    grille = fig.add_gridspec(2, 2, width_ratios=[11, 4], height_ratios=[1, 1.25],
                              wspace=0.04, hspace=0.12, left=0.75 / largeur,
                              right=1 - 0.2 / largeur, top=1 - 0.55 / hauteur,
                              bottom=0.45 / hauteur)
    ax = fig.add_subplot(grille[:, 0])
    zoom = fig.add_subplot(grille[0, 1])
    ax_legende = fig.add_subplot(grille[1, 1])
    ax_legende.axis("off")

    cx, cy = centre.x, centre.y
    portee = max([Point(c.depart).distance(centre) for c in coupes]
                 + [Point(c.arrivee).distance(centre) for c in coupes] + [1000.0])
    rayon = portee + MARGE_PLAN
    vue = box(cx - rayon, cy - rayon, cx + rayon, cy + rayon)

    for classe in reversed(ORDRE_VEGETATION):
        _surfaces(ax, [g for g, c in donnees.touchant("vegetation", vue) if c == classe],
                  color=COULEURS_VEGETATION[classe], linewidth=0, alpha=0.85)
    _surfaces(ax, [g for g, _ in donnees.touchant("cours_d_eau", vue)],
              color=COULEURS["cours_d_eau_plan"], linewidth=0.8)
    _surfaces(ax, [g for g, _ in donnees.touchant("routes", vue)],
              color=COULEURS["route_plan"], linewidth=0.8)
    _surfaces(ax, [g.boundary for g, _ in donnees.touchant("communes", vue)],
              color=COULEURS["commune"], linestyle="--", linewidth=1.1)

    cercles = sorted({c.demi_longueur for c in coupes if c.demi_longueur})
    for r in cercles:
        ax.add_patch(Circle((cx, cy), r, fill=False, ls=":", color="#333333", lw=0.8))
    for c in coupes:
        (x0, y0), (x1, y1) = c.depart, c.arrivee
        ax.plot([x0, x1], [y0, y1], color="k", lw=1.4, zorder=8)
    _surfaces(ax, [emprise], color=COULEURS["emprise"],
              edgecolor=COULEURS["emprise_bord"], linewidth=1.5, zorder=9)
    if surface_utile is not None:
        _surfaces(ax, [surface_utile], color=COULEURS["surface_utile"], zorder=10)
    ax.set_xlim(cx - rayon, cx + rayon)
    ax.set_ylim(cy - rayon, cy + rayon)
    ax.set_aspect("equal")
    ax.ticklabel_format(useOffset=False, style="plain")
    ax.tick_params(labelsize=7)
    titre = "Plan de repérage des coupes topographiques"
    if site:
        titre += f" — {site}"
    ax.set_title(titre + " (Lambert 93)", fontsize=12 if largeur >= 14 else 11)

    places = _Places(fig)
    # Deux coupes de même direction se superposent : la plus longue porte les
    # libellés, à ses extrémités. Une coupe libre porte toujours les siens,
    # même quand elle finit au N comme la coupe N-S.
    plus_longues: dict[str, Coupe] = {}
    for c in coupes:
        if c.demi_longueur and (c.nom not in plus_longues
                                or c.longueur > plus_longues[c.nom].longueur):
            plus_longues[c.nom] = c
    portees = list(plus_longues.values()) + [c for c in coupes if not c.demi_longueur]
    extremites = [(texte, x, y) for c in portees
                  for (x, y), texte in ((c.depart, c.extremites[0]),
                                        (c.arrivee, c.extremites[1]))]
    for texte, x, y in extremites:
        places.reserver(texte, ax.text(
            x, y, texte, fontsize=11 if largeur >= 14 else 9.5, fontweight="bold",
            ha="center", va="center", zorder=11,
            bbox=dict(fc="white", ec="k")))
    for r in cercles:
        places.poser(f"{en_km(r)} km", [lambda r=r: ax.text(
            cx + r * 0.924, cy + r * 0.383, f"{en_km(r)} km", fontsize=9, zorder=11,
            bbox=dict(fc="white", ec="none", alpha=0.7))])
    cadre = ax.get_window_extent(places.rendu)
    for g, nom in donnees.touchant("communes", vue):
        p = g.intersection(vue).representative_point() if not g.is_empty else None
        if p is None or p.is_empty:
            continue
        places.poser(nom, [lambda p=p, nom=nom: ax.text(
            p.x, p.y, nom, color=COULEURS["commune"], fontsize=8, ha="center",
            fontweight="bold", alpha=0.85, zorder=11)], cadre=cadre)

    # Zoom sur l'emprise : l'emprise en aplat, la surface utile hachurée
    # par-dessus, pour que les deux restent visibles.
    x0, y0, x1, y1 = emprise.buffer(120).bounds
    cote = max(x1 - x0, y1 - y0) / 2
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    proche = box(mx - cote, my - cote, mx + cote, my + cote)
    for classe in reversed(ORDRE_VEGETATION):
        _surfaces(zoom, [g for g, c in donnees.touchant("vegetation", proche)
                         if c == classe],
                  color=COULEURS_VEGETATION[classe], linewidth=0, alpha=0.85)
    _surfaces(zoom, [emprise], color=COULEURS["emprise"],
              edgecolor=COULEURS["emprise_bord"], linewidth=1.5)
    if surface_utile is not None:
        _surfaces(zoom, [surface_utile], facecolor=COULEURS["surface_utile"],
                  alpha=0.55, edgecolor="#99000d", linewidth=1.2, hatch="///")
    for c in coupes:
        (a0, b0), (a1, b1) = c.depart, c.arrivee
        zoom.plot([a0, a1], [b0, b1], color="k", lw=0.8)
    zoom.set_xlim(mx - cote, mx + cote)
    zoom.set_ylim(my - cote, my + cote)
    zoom.set_aspect("equal")
    zoom.set_xticks([])
    zoom.set_yticks([])
    zoom.set_title("Zoom sur l'emprise du projet", fontsize=10)

    poignees = [Patch(color=COULEURS["emprise"], label=libelle_emprise)]
    if surface_utile is not None:
        poignees.append(Patch(color=COULEURS["surface_utile"], label="Surface utile"))
    poignees += [Patch(color=COULEURS_VEGETATION[c], label=c) for c in ORDRE_VEGETATION]
    poignees += [Line2D([], [], color=COULEURS["commune"], ls="--",
                        label="Limite communale"),
                 Line2D([], [], color="k", label="Trait de coupe"),
                 Line2D([], [], color=COULEURS["cours_d_eau_plan"], label="Cours d'eau"),
                 Line2D([], [], color=COULEURS["route_plan"], label="Route principale")]
    ax_legende.legend(handles=poignees, loc="upper left",
                      fontsize=10 if largeur >= 14 else 8.5, frameon=False)
    fig.text(0.01, 0.006, f"Sources : IGN – BD TOPO® V3, consultée le {_jour(jour)}. "
             f"Emprise : {source_emprise}.", fontsize=7, color="#666666")
    return fig, RenduPlan(chemin=Path(), extremites=extremites, cercles=cercles)
