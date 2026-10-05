"""Cartes des zonages — une par famille, au format du document de référence.

Trois cartes, qui répondent aux cartes 2 à 4 de l'état initial :

    ZNIEFF de types I et II · Natura 2000 · Autres zonages

A4 paysage, fond OpenStreetMap, cadrage sur l'aire d'étude rapprochée. Le
bandeau latéral porte le titre, la légende, l'échelle, le nord, la source et le
logo — comme les planches des autres outils UNITe.

La machinerie de placement des étiquettes vient de l'outil raccordement, où
elle a été mise au point sur des cas réels. Elle vaut d'être reprise plutôt que
réécrite, parce que les problèmes qu'elle résout ne sont visibles qu'à l'usage :

* une étiquette ne doit jamais masquer l'élément qu'elle désigne, ni l'emprise
  du projet, ni une autre étiquette ;
* quand il faut la décaler, une **ligne de rappel** doit la relier à sa zone,
  sinon on ne sait plus ce qu'elle nomme ;
* elle ne doit pas déborder du cadre, d'où le repli sur plusieurs lignes puis
  le recadrage mesuré au rendu ;
* le découpage des zonages se fait dans la projection d'affichage, pas dans
  celle de calcul — sinon un liseré blanc apparaît entre le bord de la carte et
  le zonage coupé.
"""
from __future__ import annotations

import textwrap
from dataclasses import dataclass
from pathlib import Path

import contextily as cx
import geopandas as gpd
import matplotlib
import matplotlib.patheffects as pe
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle
from shapely.geometry import Point, box

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

CRS_METRIQUE = 2154
CRS_AFFICHAGE = 3857

#: Fond de plan. Le serveur de tuiles public d'OpenStreetMap a d'abord ete
#: essaye : il renvoie « Access blocked : app is not following the tile usage
#: policy of OpenStreetMap's volunteer-run servers », en toutes lettres sur
#: chaque tuile. Leur politique interdit l'usage automatise de ce serveur
#: beneficiaire de dons, et il n'est pas question de la contourner.
#:
#: Le Plan IGN rend le meme service — fond clair, routes et toponymes, sans la
#: charge visuelle d'une ortho au 1/50 000 —, releve de la donnee publique
#: francaise, et c'est deja le fond des autres outils du parc.
FOND = {
    "url": ("https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile"
            "&VERSION=1.0.0&LAYER=GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2"
            "&STYLE=normal&TILEMATRIXSET=PM&TILEMATRIX={z}&TILEROW={y}"
            "&TILECOL={x}&FORMAT=image/png"),
    "attribution": "Plan IGN — Geoplateforme",
}

#: Emprise du projet, en rouge comme sur les planches des autres outils.
COULEUR_EMPRISE = "#ff2d00"
#: Cercles des aires d'étude : présents mais discrets, ce sont des repères.
COULEUR_AIRE = "#1C2445"

#: Une teinte par type de zonage. Deux zonages de même couleur seraient
#: indiscernables sur la carte ; la palette est donc sans doublon, et les
#: Natura 2000 se distinguent en plus par un contour tireté.
COULEURS = {
    "ZNIEFF de type I": "#e31a1c",
    "ZNIEFF de type II": "#fd8d3c",
    "Zone de Protection Spéciale": "#5e3c99",
    "Zone Spéciale de Conservation": "#c51b7d",
    "Arrêté de protection de biotope": "#1b7837",
    "Arrêté de protection d'habitats": "#4d9221",
    "Réserve naturelle nationale": "#b30000",
    "Réserve naturelle régionale": "#e7298a",
    "Réserve naturelle de Corse": "#ce1256",
    "Réserve biologique dirigée": "#35978f",
    "Réserve biologique intégrale": "#01665e",
    "Parc national (zone cœur)": "#762a83",
    "Parc national (aire d'adhésion)": "#9970ab",
    "Parc naturel régional": "#5aae61",
    "Terrain de Conservatoire d'espaces naturels": "#2166ac",
    "Terrain du Conservatoire du Littoral": "#4393c3",
    "Site Ramsar": "#17becf",
    "Site d'intérêt géologique (INPG)": "#8c510a",
}
COULEUR_DEFAUT = "#636363"

#: Contour tireté pour Natura 2000 : le violet et le magenta se ressemblent
#: trop à l'impression pour que la seule teinte les distingue.
TIRETE = {"Zone de Protection Spéciale", "Zone Spéciale de Conservation"}


@dataclass
class Carte:
    famille: str
    titre: str
    chemin: Path
    nb_zonages: int


# ───────────────────────────────────────────────────────── étiquettes ──

def _halo(ax, x, y, texte, couleur="black", taille=7.5, epaisseur=2.5, **kw):
    return ax.text(x, y, texte, color=couleur, fontsize=taille, fontweight="bold",
                   path_effects=[pe.withStroke(linewidth=epaisseur,
                                               foreground="white")],
                   zorder=10, **kw)


def _replier(texte: str, largeur: int = 20, lignes_max: int = 3) -> str:
    """Replie une étiquette longue plutôt que de la tronquer."""
    texte = " ".join(str(texte).split())
    lignes = textwrap.wrap(texte, width=largeur, break_long_words=False) or [texte]
    if len(lignes) > lignes_max:
        lignes = lignes[:lignes_max]
        lignes[-1] = lignes[-1].rstrip() + "…"
    return "\n".join(lignes)


def _positions_candidates(largeur, hauteur, genre):
    """Positions d'essai du centre de l'étiquette, par ordre de préférence."""
    marge = 10
    dv, dh = hauteur / 2 + marge, largeur / 2 + marge
    anneaux = []
    for facteur in (1.0, 1.9, 2.8, 3.7):
        anneaux += [(0, dv * facteur), (0, -dv * facteur),
                    (dh * facteur, 0), (-dh * facteur, 0),
                    (dh * facteur, dv * facteur), (-dh * facteur, dv * facteur),
                    (dh * facteur, -dv * facteur), (-dh * facteur, -dv * facteur)]
    return ([(0, 0)] if genre == "zone" else []) + anneaux


def _placer_etiquettes(ax, demandes, obstacles=None, taille=7.5):
    """Place les étiquettes sans masquer ni se masquer, avec ligne de rappel.

    `demandes` : (x, y, texte, couleur, genre) en coordonnées d'affichage.
    `obstacles` : (x, y, rayon_px) à ne pas recouvrir — l'emprise du projet.
    """
    if not demandes:
        return
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.transforms import Bbox

    rendu = FigureCanvasAgg(ax.figure).get_renderer()
    cadre = ax.get_window_extent(rendu)
    inverse = ax.transData.inverted()

    occupe = []
    for ox, oy, rayon in (obstacles or []):
        px, py = ax.transData.transform((ox, oy))
        occupe.append(Bbox.from_bounds(px - rayon, py - rayon, 2 * rayon, 2 * rayon))

    for x, y, texte, couleur, genre in demandes:
        ancre_x, ancre_y = ax.transData.transform((x, y))
        etiquette = _halo(ax, x, y, texte, couleur=couleur, taille=taille,
                          ha="center", va="center")
        boite = etiquette.get_window_extent(rendu)
        largeur, hauteur = boite.width, boite.height

        meilleur, recouvrement_min = None, None
        for dx, dy in _positions_candidates(largeur, hauteur, genre):
            cx_ = min(max(ancre_x + dx, cadre.x0 + largeur / 2 + 3),
                      cadre.x1 - largeur / 2 - 3)
            cy_ = min(max(ancre_y + dy, cadre.y0 + hauteur / 2 + 3),
                      cadre.y1 - hauteur / 2 - 3)
            essai = Bbox.from_bounds(cx_ - largeur / 2, cy_ - hauteur / 2,
                                     largeur, hauteur).expanded(1.05, 1.15)
            recouvrement = sum(essai.overlaps(o) for o in occupe)
            if recouvrement == 0:
                meilleur = (cx_, cy_)
                break
            if recouvrement_min is None or recouvrement < recouvrement_min:
                meilleur, recouvrement_min = (cx_, cy_), recouvrement

        cx_, cy_ = meilleur
        etiquette.set_position(inverse.transform((cx_, cy_)))
        occupe.append(etiquette.get_window_extent(rendu))

        ecart = (cx_ - ancre_x) ** 2 + (cy_ - ancre_y) ** 2
        if ecart > (max(largeur, hauteur) * 0.55) ** 2:
            ax.annotate("", xy=(x, y), xytext=inverse.transform((cx_, cy_)),
                        arrowprops=dict(arrowstyle="-", lw=0.7, color=couleur,
                                        alpha=0.9, shrinkA=2, shrinkB=5),
                        zorder=9)


# ──────────────────────────────────────────────── habillage de la carte ──

def _fleche_nord(ax):
    x, y = 0.94, 0.88
    ax.annotate("", xy=(x, y + 0.08), xytext=(x, y), xycoords="axes fraction",
                arrowprops=dict(arrowstyle="-|>", lw=2.2, color="black"), zorder=20)
    ax.text(x, y - 0.015, "N", transform=ax.transAxes, ha="center", va="top",
            fontsize=11, fontweight="bold", zorder=20)


def _barre_echelle(ax, centre_l93: Point):
    """Barre d'échelle en distance réelle.

    Mesurée par reprojection au point central : en Web Mercator un pixel ne
    vaut pas la même distance selon la latitude, et une barre calculée sur les
    unités d'affichage serait fausse.
    """
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    paire = gpd.GeoSeries([Point(centre_l93.x - 500, centre_l93.y),
                           Point(centre_l93.x + 500, centre_l93.y)],
                          crs=CRS_METRIQUE).to_crs(CRS_AFFICHAGE)
    metres_par_unite = 1000.0 / paire.iloc[0].distance(paire.iloc[1])
    largeur_m = (x1 - x0) * metres_par_unite

    paliers = [100, 200, 500, 1000, 2000, 5000, 10000, 20000]
    admissibles = [p for p in paliers if p <= largeur_m * 0.4]
    barre_m = max(admissibles) if admissibles else paliers[0]
    barre = barre_m / metres_par_unite

    mx, my = (x1 - x0) * 0.03, (y1 - y0) * 0.03
    hauteur = (y1 - y0) * 0.010
    bx, by = x0 + mx, y0 + my
    ax.add_patch(Rectangle((bx, by), barre / 2, hauteur, facecolor="black",
                           edgecolor="black", zorder=20))
    ax.add_patch(Rectangle((bx + barre / 2, by), barre / 2, hauteur,
                           facecolor="white", edgecolor="black", zorder=20))
    for fraction, texte in ((0, "0"),
                            (1, f"{barre_m / 1000:g} km" if barre_m >= 1000
                                else f"{barre_m:g} m")):
        ax.text(bx + fraction * barre, by + hauteur * 1.6, texte, fontsize=7,
                ha="center", zorder=20,
                path_effects=[pe.withStroke(linewidth=2.5, foreground="white")])


_LOGO: dict = {}


def _logo():
    if "img" not in _LOGO:
        import matplotlib.image as mpimg
        chemin = Path(__file__).resolve().parents[2] / "logo_unite.png"
        _LOGO["img"] = mpimg.imread(str(chemin)) if chemin.exists() else None
    return _LOGO["img"]


def _figure_a4():
    """A4 paysage : ces cartes s'insèrent dans le fil du document Word."""
    fig = plt.figure(figsize=(11.69, 8.27))
    grille = fig.add_gridspec(1, 2, width_ratios=[4.0, 1.25], wspace=0.0)
    ax_carte = fig.add_subplot(grille[0, 0])
    ax_carte.set_aspect("equal")
    ax_bandeau = fig.add_subplot(grille[0, 1])
    ax_bandeau.axis("off")
    return fig, ax_carte, ax_bandeau


#: Largeur du bandeau, exprimee en « caracteres x corps ». Calibree sur le
#: rendu : un titre de 12 points y tient en vingt-sept caracteres.
LARGEUR_BANDEAU = 330


def _replier_bandeau(texte: str, taille: float) -> str:
    """Replie un texte à la largeur du bandeau, avec de vrais sauts de ligne.

    `wrap=True` de matplotlib replie à l'affichage mais ne touche pas à la
    chaîne. L'avance verticale, calculée sur le nombre de sauts de ligne,
    valait donc une seule ligne quel que soit le repli réel : un titre de
    deux lignes venait mordre sur le nom du projet écrit en dessous.
    """
    largeur = max(14, int(LARGEUR_BANDEAU / max(taille, 1)))
    lignes = []
    for morceau in str(texte).split("\n"):
        lignes += textwrap.wrap(morceau, largeur) or [""]
    return "\n".join(lignes)


def _remplir_bandeau(ax, lignes_titre, poignees, source):
    y = 0.98
    for texte, taille, graisse in lignes_titre:
        replie = _replier_bandeau(texte, taille)
        ax.text(0.03, y, replie, transform=ax.transAxes, fontsize=taille,
                fontweight=graisse, va="top")
        y -= (0.048 if taille > 10 else 0.034) * (replie.count("\n") + 1)
    # Un peu d'air avant la légende, qui suit immédiatement.
    y -= 0.012

    if poignees:
        # Les libellés longs sont repliés : sans cela, « Terrain de
        # Conservatoire d'espaces naturels » déborde hors du bandeau.
        for poignee in poignees:
            libelle = poignee.get_label()
            if libelle and not libelle.startswith("_"):
                poignee.set_label("\n".join(textwrap.wrap(libelle, 26)) or libelle)
        legende = ax.legend(handles=poignees, loc="upper left",
                            bbox_to_anchor=(0.0, y - 0.02),
                            bbox_transform=ax.transAxes, frameon=False,
                            fontsize=7, title="Légende", title_fontsize=9,
                            alignment="left", handlelength=1.4, labelspacing=0.6)
        legende.get_title().set_fontweight("bold")

    ax.text(0.03, 0.055, f"Source : {source}\nFond : {FOND['attribution']}",
            transform=ax.transAxes, fontsize=6.5, va="bottom", color="#333333")

    image = _logo()
    if image is not None:
        ax_logo = ax.inset_axes([0.03, 0.12, 0.46, 0.11])
        ax_logo.imshow(image)
        ax_logo.axis("off")


# ──────────────────────────────────────────────────────── tracé ──

def _poser_fond(ax, tentatives: int = 3) -> bool:
    """Pose le fond de plan, avec reprises.

    Une seule tuile en échec fait abandonner contextily, et la carte sort avec
    un aplat blanc. C'est arrivé en production sur un 404 transitoire : la même
    tuile répondait correctement la minute suivante. Trois tentatives espacées
    suffisent à absorber un creux de réseau ; au-delà, l'échec est signalé sur
    la carte elle-même.
    """
    import time

    for tentative in range(tentatives):
        try:
            cx.add_basemap(ax, source=FOND["url"], crs=f"EPSG:{CRS_AFFICHAGE}",
                           attribution_size=5)
            return True
        except Exception as erreur:  # noqa: BLE001
            if tentative == tentatives - 1:
                print(f"    [fond] indisponible apres {tentatives} tentatives :"
                      f" {erreur}")
                return False
            time.sleep(2 * (tentative + 1))
    return False


def _cadre(emprise_union, rayon_m: float, marge: float = 0.08):
    """Rectangle de cadrage, carré autour de l'emprise élargie de l'AER."""
    x0, y0, x1, y1 = emprise_union.buffer(rayon_m).bounds
    demi = max(x1 - x0, y1 - y0) / 2 * (1 + marge)
    cx_, cy_ = (x0 + x1) / 2, (y0 + y1) / 2
    return box(cx_ - demi, cy_ - demi, cx_ + demi, cy_ + demi)


#: Ordre d'affichage des types, repris du registre des sources : c'est celui
#: du document, et il ne dépend ni du projet ni des distances.
_ORDRE_TYPES: list[str] = []


def _rang_type(type_libelle: str) -> int:
    global _ORDRE_TYPES
    if not _ORDRE_TYPES:
        from . import zonages as mod_zonages
        _ORDRE_TYPES = [s.type_libelle for s in mod_zonages.registre()]
    try:
        return _ORDRE_TYPES.index(type_libelle)
    except ValueError:
        return len(_ORDRE_TYPES)


def _dessiner_zonages(ax, couches, cadre_l93):
    """Dessine les zonages d'une famille. Renvoie (poignées, étiquettes)."""
    # Découpage dans la projection d'AFFICHAGE : couper en Lambert-93 puis
    # reprojeter laisse un liseré blanc entre le bord du cadre et le zonage,
    # les deux rectangles n'étant pas superposables d'une projection à l'autre.
    cadre_affichage = box(*gpd.GeoSeries([cadre_l93], crs=CRS_METRIQUE)
                          .to_crs(CRS_AFFICHAGE).total_bounds)
    poignees, etiquettes = [], []
    vus = set()

    # Les couches arrivent dans l'ordre des distances, ce qui donnait une
    # légende où « ZNIEFF de type II » précédait « ZNIEFF de type I » dès
    # qu'une type II touchait l'emprise. L'ordre du registre est celui du
    # document, et il ne dépend pas du projet.
    for type_zonage, gdf in sorted(couches.items(),
                                   key=lambda c: _rang_type(c[0])):
        couleur = COULEURS.get(type_zonage, COULEUR_DEFAUT)
        style = "--" if type_zonage in TIRETE else "-"
        decoupe = gdf.to_crs(CRS_AFFICHAGE).clip(cadre_affichage)
        decoupe = decoupe[~decoupe.geometry.is_empty & decoupe.geometry.notna()]
        if decoupe.empty:
            continue
        decoupe.plot(ax=ax, facecolor=couleur, edgecolor=couleur, alpha=0.28,
                     linewidth=1.3, linestyle=style, zorder=4)
        if type_zonage not in vus:
            poignees.append(Patch(facecolor=couleur, edgecolor=couleur,
                                  alpha=0.45, linestyle=style, label=type_zonage))
            vus.add(type_zonage)
        for _, ligne in decoupe.iterrows():
            point = ligne.geometry.representative_point()
            etiquettes.append((point.x, point.y,
                               _replier(ligne.get("_nom") or "", 22, 4),
                               couleur, "zone"))
    return poignees, etiquettes


def _dessiner_emprise(ax, emprise_gdf):
    """Trace l'emprise du projet — l'objet même de la carte.

    Elle était dessinée comme les zonages : un aplat teinté à 30 %. Sur une
    carte de ZNIEFF, où le type I est rouge lui aussi, l'emprise disparaissait
    dans le zonage qui la recouvrait. Or c'est le seul objet que le lecteur
    cherche d'abord.

    Elle se distingue donc par sa **nature** et pas par sa teinte : un liseré
    blanc qui la détache de tout fond, une trame hachurée qu'aucun zonage
    n'emploie, et un contour franc par-dessus. Changer la teinte des ZNIEFF
    aurait réglé le cas des ZNIEFF, et pas celui des réserves rouges.
    """
    affichage = emprise_gdf.to_crs(CRS_AFFICHAGE)
    # Liseré blanc dessous : il détache le contour aussi bien d'un aplat
    # sombre que du fond de plan clair.
    affichage.plot(ax=ax, facecolor="none", edgecolor="white", linewidth=5.0,
                   zorder=6)
    affichage.plot(ax=ax, facecolor="none", edgecolor=COULEUR_EMPRISE,
                   linewidth=2.4, hatch="///", zorder=7)
    centre = affichage.geometry.union_all().representative_point()
    return [(centre.x, centre.y, 26)]


def _poignee_emprise():
    """Poignée de légende reprenant exactement la trame de l'emprise."""
    return Patch(facecolor="none", edgecolor=COULEUR_EMPRISE, linewidth=1.6,
                 hatch="///", label="Emprise du projet (ZIP)")


def _rayon_lisible(metres: float) -> str:
    """« 200 m », « 5 km » — et non « 5000 m », qui se relit deux fois.

    L'espace est insécable : le repli des libellés de légende coupait sinon
    entre le nombre et son unité, « (5 » restant seul en fin de ligne.
    """
    if metres >= 1000:
        return f"{metres / 1000:.0f} km".replace(".", ",")
    return f"{metres:.0f} m"


def _dessiner_aires(ax, emprise_union, aires):
    """Cercles des aires d'étude, en repère discret."""
    poignees = []
    for aire in aires:
        if aire.rayon_m <= 0:
            continue
        anneau = gpd.GeoSeries([emprise_union.buffer(aire.rayon_m)],
                               crs=CRS_METRIQUE).to_crs(CRS_AFFICHAGE)
        anneau.boundary.plot(ax=ax, color=COULEUR_AIRE, linewidth=1.1,
                             linestyle=(0, (6, 4)), alpha=0.75, zorder=5)
        poignees.append(Line2D(
            [], [], color=COULEUR_AIRE, linewidth=1.1, linestyle=(0, (6, 4)),
            label=f"{aire.libelle} ({_rayon_lisible(aire.rayon_m)})"))
    return poignees


def dessiner_aires_etude(emprise_gdf, aires, chemin: Path, nom_projet: str,
                         source: str = "UNITe") -> Carte:
    """Carte de situation : l'emprise et ses aires d'étude, sans aucun zonage.

    C'est la première carte du prédiagnostic de référence, et elle vient avant
    qu'on parle d'enjeux : elle situe le projet et montre ce que recouvrent la
    ZIP, l'aire d'étude immédiate et l'aire d'étude rapprochée. Sans elle, le
    lecteur découvre les aires d'étude dans la légende d'une carte de ZNIEFF,
    alors que toutes les distances du rapport s'y réfèrent.
    """
    emprise_union = emprise_gdf.geometry.union_all()
    rayon = max((a.rayon_m for a in aires), default=5000.0)
    cadre_l93 = _cadre(emprise_union, rayon)
    x0, y0, x1, y1 = (gpd.GeoSeries([cadre_l93], crs=CRS_METRIQUE)
                      .to_crs(CRS_AFFICHAGE).total_bounds)

    fig, ax, ax_bandeau = _figure_a4()
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.apply_aspect()

    fond_pose = _poser_fond(ax)
    poignees_a = _dessiner_aires(ax, emprise_union, aires)
    obstacles = _dessiner_emprise(ax, emprise_gdf)

    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    _placer_etiquettes(ax, [], obstacles=obstacles)
    _fleche_nord(ax)
    _barre_echelle(ax, cadre_l93.centroid)

    poignees = [_poignee_emprise()]
    poignees += poignees_a
    lignes_titre = [("Aires d'étude du projet", 12, "bold"),
                    (nom_projet, 9, "normal")]
    if not fond_pose:
        lignes_titre.append(
            ("⚠ Fond de plan indisponible au moment du rendu — relancer la "
             "production des cartes", 7.5, "normal")
        )
    _remplir_bandeau(ax_bandeau, lignes_titre, poignees, source)

    ax.set_axis_off()
    chemin.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(chemin, dpi=200, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    return Carte(famille="aires", titre="Aires d'étude du projet",
                 chemin=chemin, nb_zonages=0)


def dessiner_famille(famille: str, titre: str, couches: dict, emprise_gdf,
                     aires, chemin: Path, nom_projet: str,
                     source: str = "UNITe") -> Carte | None:
    """Produit une carte A4 paysage pour une famille de zonages."""
    if not couches:
        return None
    emprise_union = emprise_gdf.geometry.union_all()
    rayon = max((a.rayon_m for a in aires), default=5000.0)
    cadre_l93 = _cadre(emprise_union, rayon)
    x0, y0, x1, y1 = (gpd.GeoSeries([cadre_l93], crs=CRS_METRIQUE)
                      .to_crs(CRS_AFFICHAGE).total_bounds)

    fig, ax, ax_bandeau = _figure_a4()
    # Les limites sont posées AVANT tout tracé : le placement des étiquettes
    # mesure des pixels, donc il lui faut la transformation définitive.
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.apply_aspect()

    fond_pose = _poser_fond(ax)

    poignees_z, etiquettes = _dessiner_zonages(ax, couches, cadre_l93)
    poignees_a = _dessiner_aires(ax, emprise_union, aires)
    obstacles = _dessiner_emprise(ax, emprise_gdf)

    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    _placer_etiquettes(ax, etiquettes, obstacles=obstacles)
    _fleche_nord(ax)
    _barre_echelle(ax, cadre_l93.centroid)

    poignees = [_poignee_emprise()]
    poignees += poignees_a + poignees_z
    lignes_titre = [(titre, 12, "bold"), (nom_projet, 9, "normal")]
    if not fond_pose:
        # Une carte sans fond doit le dire. Sinon elle part dans le livrable
        # avec un aplat blanc, et personne ne sait si c'est voulu.
        lignes_titre.append(
            ("⚠ Fond de plan indisponible au moment du rendu — relancer la "
             "production des cartes", 7.5, "normal")
        )
    _remplir_bandeau(ax_bandeau, lignes_titre, poignees, source)

    ax.set_axis_off()
    chemin.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(chemin, dpi=200, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    return Carte(famille=famille, titre=titre, chemin=chemin,
                 nb_zonages=sum(len(g) for g in couches.values()))


def produire(resultat, emprise_gdf, aires, dossier: Path, nom_projet: str,
             familles=None, source: str = "UNITe",
             avec_situation: bool = True) -> list[Carte]:
    """Produit la carte de situation, puis une carte par famille présente.

    Une carte par famille plutôt qu'une carte unique : superposer ZNIEFF,
    Natura 2000 et espaces protégés sur un même fond donne un dégradé illisible
    dès qu'ils se recouvrent, ce qui est le cas général en vallée alluviale.
    """
    from . import zonages as mod_zonages

    familles = familles or mod_zonages.FAMILLES
    produites: list[Carte] = []
    if avec_situation:
        produites.append(dessiner_aires_etude(
            emprise_gdf, aires, dossier / "carte_aires.png", nom_projet, source))
    for famille, titre in familles:
        couches = resultat.couches(famille)
        if not couches:
            continue
        chemin = dossier / f"carte_{famille}.png"
        carte = dessiner_famille(famille, titre, couches, emprise_gdf, aires,
                                 chemin, nom_projet, source)
        if carte is not None:
            produites.append(carte)
    return produites
