"""Cartes des zonages — une par famille, au format du document de référence.

Trois cartes, qui répondent aux cartes 2 à 4 de l'état initial :

    ZNIEFF de types I et II · Natura 2000 · Autres zonages

A4 paysage, fond Plan IGN, cadrage sur l'aire d'étude rapprochée. Le bandeau
latéral porte le titre, la légende, l'échelle, le nord, la source et le
logo — comme les planches des autres outils UNITe.

S'y ajoutent, depuis le 8 novembre 2026, deux planches de photographies
aériennes pour la « Dynamique du site », cadrées sur la ZIP et son aire
d'étude immédiate : six prises de vue de 1950-1965 à aujourd'hui sur une même
page, puis la plus récente en pleine page.

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
    "attribution": "Plan IGN — Géoplateforme",
}

#: Les photographies aériennes de la « Dynamique du site ». Le document
#: demandait de comparer l'occupation du sol d'aujourd'hui à celle des années
#: 1950 sans rien montrer : chacun allait les chercher sur le Géoportail. La
#: Géoplateforme les sert comme le Plan IGN, et l'IGN les diffuse sous
#: Licence Ouverte.
#:
#: Six prises de vue, une quinzaine d'années de l'une à l'autre : deux,
#: 1950 et aujourd'hui, montraient l'écart sans dire quand il s'était
#: creusé. Les historiques sont en PNG, les autres en JPEG, et chaque couche
#: a sa grille de tuiles. Toutes ne couvrent pas tout le territoire :
#: l'IGN produit celle de 1980-1995 département par département, et
#: Bédarieux n'en a pas — voir `_couverte`. La date de la prise de vue la
#: plus récente varie d'un département à l'autre ; l'IGN la publie à part.
_TUILE = ("https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile"
          "&VERSION=1.0.0&LAYER={couche}&STYLE={style}"
          "&TILEMATRIXSET={grille}&TILEMATRIX={{z}}&TILEROW={{y}}"
          "&TILECOL={{x}}&FORMAT=image/{image}")


def _prise_de_vue(periode: str, couche: str, style: str, grille: str,
                  image: str) -> dict:
    return {"periode": periode,
            "url": _TUILE.format(couche=couche, style=style, grille=grille,
                                 image=image),
            "attribution": f"Photographies aériennes {periode} — IGN, "
                           "Géoplateforme"}


SERIE_PHOTOGRAPHIES = (
    _prise_de_vue("1950-1965", "ORTHOIMAGERY.ORTHOPHOTOS.1950-1965",
                  "BDORTHOHISTORIQUE", "PM_0_18", "png"),
    _prise_de_vue("1965-1980", "ORTHOIMAGERY.ORTHOPHOTOS.1965-1980",
                  "BDORTHOHISTORIQUE", "PM_3_18", "png"),
    _prise_de_vue("1980-1995", "ORTHOIMAGERY.ORTHOPHOTOS.1980-1995",
                  "BDORTHOHISTORIQUE", "PM_3_18", "png"),
    _prise_de_vue("2000-2005", "ORTHOIMAGERY.ORTHOPHOTOS2000-2005",
                  "normal", "PM_6_18", "jpeg"),
    _prise_de_vue("2011-2015", "ORTHOIMAGERY.ORTHOPHOTOS2011-2015",
                  "normal", "PM_6_18", "jpeg"),
    _prise_de_vue("la plus récente", "ORTHOIMAGERY.ORTHOPHOTOS",
                  "normal", "PM_0_19", "jpeg"),
)
#: La dernière de la série, aussi en pleine page : c'est elle qu'on a sous
#: les yeux en préparant la visite.
ORTHO_ACTUELLE = {
    **SERIE_PHOTOGRAPHIES[-1],
    "famille": "ortho_actuelle",
    "titre": "Photographie aérienne la plus récente",
    "attribution": ("Photographies aériennes les plus récentes — IGN, "
                    "Géoplateforme"),
}
#: La planche qui réunit la série.
EVOLUTION = {"famille": "ortho_evolution",
             "titre": "Évolution de l'occupation du sol"}

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
    #: Ce qui fait le fond, quand il est la matière même de la carte — les
    #: photographies aériennes —, et le jour où il a été lu : la Licence
    #: Ouverte demande l'un et l'autre.
    fond: str = ""
    date: str = ""
    #: Les périodes de la série que l'IGN ne couvre pas sur le cadre.
    absentes: tuple[str, ...] = ()


# ───────────────────────────────────────────────────────── étiquettes ──

def _est_clair(couleur: str) -> bool:
    """La couleur est-elle trop claire pour porter un liseré blanc ?"""
    from matplotlib.colors import to_rgb
    try:
        r, v, b = to_rgb(couleur)
    except Exception:  # noqa: BLE001
        return False
    return (0.299 * r + 0.587 * v + 0.114 * b) > 0.6


def _halo(ax, x, y, texte, couleur="black", taille=7.5, epaisseur=2.5,
          fond=None, **kw):
    """Texte cerné d'un liseré, pour se détacher de n'importe quel fond.

    Le liseré était blanc en dur. Les noms des grands zonages, écrits en
    blanc à l'intérieur de l'aplat comme le fait le prédiagnostic de
    référence, s'y noyaient : du blanc cerné de blanc ne se lit pas. Le
    liseré suit donc la couleur du texte — sombre sous un texte clair.
    """
    if fond is None:
        fond = "#2b2b2b" if _est_clair(couleur) else "white"
    return ax.text(x, y, texte, color=couleur, fontsize=taille, fontweight="bold",
                   path_effects=[pe.withStroke(linewidth=epaisseur,
                                               foreground=fond)],
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


def _placer_etiquettes(ax, demandes, obstacles=None, taille=6.5):
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

        if meilleur is None or recouvrement_min:
            # Aucune position libre : on retire l'étiquette plutôt que de
            # l'empiler sur les précédentes. Une carte où tout est écrit est
            # une carte où rien ne se lit, et le tableau d'en face porte le
            # nom de chaque zonage.
            etiquette.remove()
            continue
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


def _remplir_bandeau(ax, lignes_titre, poignees, source, fond=None):
    fond = fond or FOND
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

    texte_source = _replier_bandeau(
        f"Source : {source}\nFond : {fond['attribution']}", 6.5)
    ax.text(0.03, 0.055, texte_source, transform=ax.transAxes, fontsize=6.5,
            va="bottom", color="#333333")

    image = _logo()
    if image is not None:
        # Au-dessus de la source, si longue soit-elle : celle de la série de
        # photographies tient sur quatre lignes et venait toucher le logo.
        lignes_source = texte_source.count("\n") + 1
        bas = max(0.12, 0.07 + 0.028 * lignes_source)
        ax_logo = ax.inset_axes([0.03, bas, 0.46, 0.11])
        ax_logo.imshow(image)
        ax_logo.axis("off")


# ──────────────────────────────────────────────────────── tracé ──

#: Dossier de cache des tuiles, mis en place une seule fois.
_CACHE_POSE = False


def _tuile_avec_reprise(tile_url, wait, max_retries, headers):
    """Télécharge une tuile, et rend bien ce qu'elle a fini par rendre.

    **Contextily 1.7.0 perd la tuile dès qu'il doit la redemander.** Dans sa
    branche de reprise, le résultat de l'appel récursif est affecté à une
    variable locale et jamais renvoyé :

        if max_retries > 0:
            ...
            request = _retryer(tile_url, wait, max_retries, headers)
        else:
            raise requests.HTTPError(...)

    La fonction tombe alors en fin de bloc et rend `None`. La tuile manquante
    ne se voit pas tout de suite : elle casse l'assemblage bien plus loin, sur
    un « int() argument must be a string… not NoneType » qui ne dit rien de sa
    cause. C'est ce qui laissait les planches sans fond de plan — le Plan IGN
    limite le débit et répond 429 sur quelques tuiles d'une mosaïque, et
    chaque reprise réussie était jetée.

    On réécrit donc la reprise en boucle plutôt qu'en récursion, ce qui ôte
    l'occasion même de l'oubli. Le reste est le comportement de contextily :
    404 abandonne tout de suite — la tuile n'existe pas, la redemander n'y
    changera rien —, les autres erreurs patientent puis réessaient.
    """
    import io
    import time

    import numpy as np
    import requests
    from PIL import Image, UnidentifiedImageError

    from contextily.tile import USER_AGENT

    for restantes in range(max_retries, -1, -1):
        reponse = requests.get(
            tile_url, headers={"user-agent": USER_AGENT, **headers})
        if reponse.status_code == 404:
            # La tuile n'existe pas : la redemander n'y changera rien.
            raise requests.HTTPError(
                "Tile URL resulted in a 404 error. "
                "Double-check your tile url:\n{}".format(tile_url))
        try:
            reponse.raise_for_status()
            with io.BytesIO(reponse.content) as flux:
                image = Image.open(flux).convert("RGBA")
                tableau = np.asarray(image)
                image.close()
                return tableau
        except (requests.HTTPError, UnidentifiedImageError):
            if restantes <= 0:
                raise requests.HTTPError(
                    "Connection reset by peer too many times.\n{}".format(
                        tile_url))
            time.sleep(wait)
    raise requests.HTTPError(tile_url)


def _purger_tuiles_perdues(dossier) -> int:
    """Retire du cache les tuiles enregistrées à `None`.

    joblib garde ce que la fonction a rendu, `None` compris : réparer la
    reprise ne suffit donc pas, les tuiles déjà perdues le resteraient d'un
    lancement à l'autre et la carte ne retrouverait jamais son fond.

    On ne relit pas tout le cache pour autant. Une tuile pèse des dizaines de
    kilo-octets, un `None` une vingtaine d'octets : seuls les fichiers
    minuscules sont ouverts, ce qui rend le balayage négligeable.
    """
    import pickle

    retires = 0
    for sortie in dossier.rglob("output.pkl"):
        try:
            if sortie.stat().st_size > 512:
                continue
            charge = pickle.loads(sortie.read_bytes())
            contenu = (charge[0] if isinstance(charge, tuple) and len(charge) == 1
                       else charge)
            if contenu is None:
                for fichier in sortie.parent.iterdir():
                    fichier.unlink()
                sortie.parent.rmdir()
                retires += 1
        except Exception:  # noqa: BLE001
            continue
    return retires


def _cacher_tuiles() -> None:
    """Range les tuiles sur le disque plutôt que de les redemander.

    Une planche reproduite pour le même site ne redemande alors rien, et le
    service public s'en trouve d'autant moins sollicité — le même souci que
    celui qui fait écarter le serveur de tuiles d'OpenStreetMap.
    """
    global _CACHE_POSE
    if _CACHE_POSE:
        return
    try:
        from . import chemins

        dossier = chemins.referentiels() / "_cache_tuiles"
        dossier.mkdir(parents=True, exist_ok=True)
        cx.set_cache_dir(str(dossier))
        perdues = _purger_tuiles_perdues(dossier)
        if perdues:
            print(f"    [fond] {perdues} tuile(s) vide(s) retirée(s) du cache")
    except Exception:  # noqa: BLE001
        pass
    try:
        from contextily import tile as _tuiles
        _tuiles._retryer = _tuile_avec_reprise
    except Exception:  # noqa: BLE001
        pass
    _CACHE_POSE = True


def _zoom_automatique(ax) -> int | None:
    """Le zoom que contextily choisirait, pour pouvoir en descendre."""
    try:
        from contextily.tile import _calculate_zoom, _sm2ll

        x0, x1 = ax.get_xlim()
        y0, y1 = ax.get_ylim()
        w, s = _sm2ll(x0, y0)
        e, n = _sm2ll(x1, y1)
        return _calculate_zoom(w, s, e, n)
    except Exception:  # noqa: BLE001
        return None


def _poser_fond(ax, tentatives: int = 3, fond=None,
                zoom_max: int | None = None) -> bool:
    """Pose le fond de plan, avec reprises.

    Une seule tuile en échec fait abandonner contextily, et la carte sort avec
    un aplat blanc. C'est arrivé en production sur un 404 transitoire : la même
    tuile répondait correctement la minute suivante. Trois tentatives espacées
    suffisent à absorber un creux de réseau ; au-delà, l'échec est signalé sur
    la carte elle-même.
    """
    import time

    _cacher_tuiles()
    # Le service limite le débit : plus la mosaïque demande de tuiles, plus
    # elle échoue. Mesuré un soir de production répétée, le zoom 10 passait
    # quand les zooms 11 à 14 tombaient tous. Contextily ne sait pas composer
    # avec une tuile manquante — il en garde un None et lève bien plus loin,
    # dans l'assemblage.
    #
    # On réessaie donc en descendant d'un cran de zoom à chaque échec. Un
    # fond un peu moins détaillé reste un fond ; une carte blanche n'est pas
    # une carte.
    # Un seul cran de repli, et pas deux : les toponymes du fond sont gravés
    # à la taille de leur zoom, si bien qu'un cran les double et deux les
    # quadruplent. Au zoom 11 pour un cadre de zoom 13, « St-Pierre-lès-Elbeuf »
    # barre la carte — on aurait troqué un fouillis contre un autre.
    fond = fond or FOND
    automatique = _zoom_automatique(ax)
    if automatique is not None and zoom_max is not None:
        # Au-delà, la couche n'a pas de tuile : un 404 qui ne dit rien de
        # la couverture et coûte deux tentatives.
        automatique = min(automatique, zoom_max)
    niveaux = [None] if automatique is None else [automatique, automatique - 1]
    for rang, zoom in enumerate(niveaux):
        for tentative in range(tentatives):
            try:
                cx.add_basemap(ax, source=fond["url"],
                               crs=f"EPSG:{CRS_AFFICHAGE}",
                               attribution_size=5,
                               **({} if zoom is None else {"zoom": zoom}))
                if rang:
                    print(f"    [fond] posé au zoom {zoom} au lieu de "
                          f"{automatique} — service limité")
                return True
            except Exception as erreur:  # noqa: BLE001
                dernier = (rang == len(niveaux) - 1
                           and tentative == tentatives - 1)
                if dernier:
                    print(f"    [fond] indisponible apres {tentatives} "
                          f"tentatives sur {len(niveaux)} zooms : {erreur}")
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


#: Part du cadre qu'un polygone doit occuper pour porter son nom en entier.
#: Au-dessous, il reçoit son identifiant — court, d'une seule ligne.
_PORTE_SON_NOM = (0.16, 0.07)


def _etiquette_zonage(ligne, largeur_cadre: float,
                      hauteur_cadre: float) -> tuple[str, str]:
    """Le texte d'une étiquette et sa couleur, selon la place disponible.

    Le prédiagnostic de référence fait ainsi, et sa carte des ZNIEFF se lit :
    les grandes ZNIEFF de type II portent leur nom en capitales pâles, posé
    à l'intérieur ; les petites ZNIEFF de type I ne portent que leur numéro,
    en rouge, à côté. Le lecteur retrouve le nom dans la colonne
    « Identifiant » du tableau, en face.

    L'outil écrivait le nom complet sur chaque polygone, en gras, replié
    jusqu'à quatre lignes. Sur vingt-quatre ZNIEFF, les pavés de texte
    recouvraient la carte — « les noms sont écrits par-dessus les zonages
    donc on ne voit plus rien », a écrit la responsable environnement.
    """
    x0, y0, x1, y1 = ligne.geometry.bounds
    assez_large = (x1 - x0) >= largeur_cadre * _PORTE_SON_NOM[0]
    assez_haut = (y1 - y0) >= hauteur_cadre * _PORTE_SON_NOM[1]
    nom = str(ligne.get("_nom") or "").strip()
    if nom and assez_large and assez_haut:
        # Capitales pâles à l'intérieur du polygone : le texte se lit sans
        # masquer l'aplat, qui reste visible au travers.
        return _replier(nom.upper(), 30, 2), "#ffffff"
    identifiant = str(ligne.get("_id") or "").strip()
    return (identifiant or _replier(nom, 18, 1)), "#8e2f2a"


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
        x0, y0, x1, y1 = cadre_affichage.bounds
        largeur_cadre, hauteur_cadre = x1 - x0, y1 - y0
        for _, ligne in decoupe.iterrows():
            point = ligne.geometry.representative_point()
            etiquettes.append(
                (point.x, point.y) + _etiquette_zonage(
                    ligne, largeur_cadre, hauteur_cadre) + ("zone",))
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


#: Couleur des repères posés sur une photographie aérienne : un trait sombre
#: s'y perd dans les bois, un trait clair dans les cultures. Le blanc cerné
#: de sombre se lit sur l'un et l'autre.
COULEUR_REPERE_PHOTO = "white"
CERNE_PHOTO = [pe.withStroke(linewidth=2.8, foreground=COULEUR_AIRE)]


def dessiner_photographie(fond: dict, emprise_gdf, aires, chemin: Path,
                          nom_projet: str, source: str = "UNITe") -> Carte:
    """Une photographie aérienne de la ZIP et de son aire d'étude immédiate.

    Le cadrage n'est pas celui des zonages : à 5 km, une photographie des
    années 1950 ne montre plus rien de la ZIP. On cadre donc sur l'aire
    d'étude immédiate, où se lit l'évolution des parcelles, des haies et du
    bâti.

    L'emprise n'est qu'un contour, sans la trame des autres cartes : la trame
    masquerait précisément ce qu'on demande de regarder.
    """
    from datetime import date

    emprise_union = emprise_gdf.geometry.union_all()
    immediate = next((a for a in aires if a.code == "AEI"), None)
    rayon = immediate.rayon_m if immediate is not None else 200.0
    cadre_l93 = _cadre(emprise_union, rayon, marge=0.15)
    x0, y0, x1, y1 = (gpd.GeoSeries([cadre_l93], crs=CRS_METRIQUE)
                      .to_crs(CRS_AFFICHAGE).total_bounds)

    fig, ax, ax_bandeau = _figure_a4()
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.apply_aspect()

    fond_pose = _poser_fond(ax, fond=fond)

    poignees = []
    if immediate is not None:
        anneau = gpd.GeoSeries([emprise_union.buffer(immediate.rayon_m)],
                               crs=CRS_METRIQUE).to_crs(CRS_AFFICHAGE)
        anneau.boundary.plot(ax=ax, color=COULEUR_REPERE_PHOTO, linewidth=1.3,
                             linestyle=(0, (6, 4)), zorder=5)
        ax.collections[-1].set_path_effects(CERNE_PHOTO)
        poignees.append(Line2D(
            [], [], color=COULEUR_REPERE_PHOTO, linewidth=1.3,
            linestyle=(0, (6, 4)), path_effects=CERNE_PHOTO,
            label=f"{immediate.libelle} "
                  f"({_rayon_lisible(immediate.rayon_m)})"))
    affichage = emprise_gdf.to_crs(CRS_AFFICHAGE)
    affichage.plot(ax=ax, facecolor="none", edgecolor="white", linewidth=4.0,
                   zorder=6)
    affichage.plot(ax=ax, facecolor="none", edgecolor=COULEUR_EMPRISE,
                   linewidth=2.0, zorder=7)
    poignees.insert(0, Patch(facecolor="none", edgecolor=COULEUR_EMPRISE,
                             linewidth=1.6, label="Emprise du projet (ZIP)"))

    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    _fleche_nord(ax)
    _barre_echelle(ax, cadre_l93.centroid)

    lignes_titre = [(fond["titre"], 12, "bold"), (nom_projet, 9, "normal")]
    if not fond_pose:
        lignes_titre.append(
            ("⚠ Photographie indisponible au moment du rendu — relancer la "
             "production des cartes", 7.5, "normal")
        )
    _remplir_bandeau(ax_bandeau, lignes_titre, poignees, source, fond=fond)

    ax.set_axis_off()
    chemin.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(chemin, dpi=200, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    return Carte(famille=fond["famille"], titre=fond["titre"], chemin=chemin,
                 nb_zonages=0, fond=fond["attribution"],
                 date=date.today().strftime("%d/%m/%Y"))


#: Le zoom le plus fin que servent toutes les couches de la série : les
#: historiques s'arrêtent à 18.
ZOOM_MAX_SERIE = 18


def _couverte(fond: dict, ax) -> bool | None:
    """La prise de vue couvre-t-elle le centre du cadre ?

    La Géoplateforme répond 404 hors couverture. Une seule tuile, au centre,
    suffit à le savoir : sans cette question, la vignette attendait trois
    tentatives sur deux zooms avant de sortir vide, sans dire pourquoi.
    Rend None quand on ne sait pas — sans réseau, une période ne doit pas
    passer pour non couverte.
    """
    import math

    import requests

    try:
        from contextily.tile import USER_AGENT, _sm2ll
    except Exception:  # noqa: BLE001
        return None
    zoom = _zoom_automatique(ax)
    if zoom is None:
        return None
    zoom = min(zoom, ZOOM_MAX_SERIE)
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    lon, lat = _sm2ll((x0 + x1) / 2, (y0 + y1) / 2)
    n = 2 ** zoom
    colonne = int((lon + 180) / 360 * n)
    rangee = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi)
                 / 2 * n)
    try:
        reponse = requests.get(fond["url"].format(z=zoom, x=colonne, y=rangee),
                               headers={"user-agent": USER_AGENT}, timeout=30)
    except Exception:  # noqa: BLE001
        return None
    if reponse.status_code == 404:
        return False
    return True if reponse.ok else None


def _vignette_vide(ax, cadre, texte: str) -> None:
    """Un aplat gris qui dit pourquoi la vignette n'a pas de photographie."""
    x0, y0, x1, y1 = cadre
    ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, facecolor="#e6e6e6",
                           edgecolor="none", zorder=1))
    # Au-dessus du contour de la ZIP, qui le barrait.
    ax.text(0.5, 0.5, texte, transform=ax.transAxes, ha="center", va="center",
            fontsize=8, color="#555555", zorder=20,
            bbox=dict(boxstyle="round,pad=0.4", facecolor="#e6e6e6",
                      edgecolor="none"))


def _periodes(periodes: list[str]) -> str:
    """« 1950-1965, 1965-1980 et la plus récente »."""
    if len(periodes) < 2:
        return "".join(periodes)
    return ", ".join(periodes[:-1]) + " et " + periodes[-1]


def dessiner_evolution(fonds, emprise_gdf, aires, chemin: Path,
                       nom_projet: str, source: str = "UNITe") -> Carte:
    """La série des photographies aériennes, de 1950-1965 à aujourd'hui.

    Six vignettes au même cadrage que la pleine page — la ZIP et son aire
    d'étude immédiate —, pour lire quand l'occupation du sol a changé et non
    seulement qu'elle a changé. Une période que l'IGN ne couvre pas sur le
    cadre garde sa place, en gris, et le dit : une vignette qui disparaîtrait
    laisserait croire à une série complète.
    """
    from datetime import date

    emprise_union = emprise_gdf.geometry.union_all()
    immediate = next((a for a in aires if a.code == "AEI"), None)
    rayon = immediate.rayon_m if immediate is not None else 200.0
    cadre_l93 = _cadre(emprise_union, rayon, marge=0.15)
    cadre = tuple(gpd.GeoSeries([cadre_l93], crs=CRS_METRIQUE)
                  .to_crs(CRS_AFFICHAGE).total_bounds)
    x0, y0, x1, y1 = cadre
    affichage = emprise_gdf.to_crs(CRS_AFFICHAGE)

    # Moins haute qu'une A4 : deux rangées de vignettes carrées laissaient
    # sinon un grand blanc entre elles. Le document l'ajuste à la page.
    colonnes = 3
    lignes = -(-len(fonds) // colonnes)
    fig = plt.figure(figsize=(11.69, 0.5 + 3.05 * lignes))
    grille = fig.add_gridspec(1, 2, width_ratios=[4.0, 1.25], wspace=0.0,
                              left=0.02, right=0.98, top=0.98, bottom=0.02)
    vignettes = grille[0, 0].subgridspec(lignes, colonnes, wspace=0.05,
                                         hspace=0.08)
    ax_bandeau = fig.add_subplot(grille[0, 1])
    ax_bandeau.axis("off")

    montrees, absentes, muettes = [], [], []
    for rang, fond in enumerate(fonds):
        ax = fig.add_subplot(vignettes[rang // colonnes, rang % colonnes])
        ax.set_aspect("equal")
        ax.set_xlim(x0, x1)
        ax.set_ylim(y0, y1)
        ax.apply_aspect()
        couverte = _couverte(fond, ax)
        if couverte is False:
            absentes.append(fond["periode"])
            _vignette_vide(ax, cadre, "Pas de prise de vue de l'IGN\n"
                                      "sur ce secteur")
        elif _poser_fond(ax, fond=fond, zoom_max=ZOOM_MAX_SERIE):
            montrees.append(fond["periode"])
        else:
            muettes.append(fond["periode"])
            _vignette_vide(ax, cadre, "Photographie indisponible\n"
                                      "au moment du rendu")
        affichage.plot(ax=ax, facecolor="none", edgecolor="white",
                       linewidth=2.6, zorder=6)
        affichage.plot(ax=ax, facecolor="none", edgecolor=COULEUR_EMPRISE,
                       linewidth=1.3, zorder=7)
        ax.set_xlim(x0, x1)
        ax.set_ylim(y0, y1)
        periode = fond["periode"]
        ax.text(0.03, 0.97, periode[0].upper() + periode[1:],
                transform=ax.transAxes, ha="left", va="top", fontsize=9,
                fontweight="bold", zorder=20,
                bbox=dict(boxstyle="round,pad=0.25", facecolor="white",
                          edgecolor="none", alpha=0.85))
        if rang == len(fonds) - 1:
            _fleche_nord(ax)
            _barre_echelle(ax, cadre_l93.centroid)
        ax.set_axis_off()

    attribution = (f"Photographies aériennes {_periodes(montrees)} — IGN, "
                   "Géoplateforme")
    lignes_titre = [(EVOLUTION["titre"], 12, "bold"), (nom_projet, 9, "normal")]
    if muettes:
        lignes_titre.append(
            (f"⚠ Indisponible au moment du rendu : {_periodes(muettes)} — "
             "relancer la production des cartes", 7.5, "normal"))
    poignees = [Patch(facecolor="none", edgecolor=COULEUR_EMPRISE,
                      linewidth=1.6, label="Emprise du projet (ZIP)")]
    _remplir_bandeau(ax_bandeau, lignes_titre, poignees, source,
                     fond={"attribution": attribution})

    chemin.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(chemin, dpi=200, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    return Carte(famille=EVOLUTION["famille"], titre=EVOLUTION["titre"],
                 chemin=chemin, nb_zonages=0, fond=attribution,
                 date=date.today().strftime("%d/%m/%Y"),
                 absentes=tuple(absentes))


def produire(resultat, emprise_gdf, aires, dossier: Path, nom_projet: str,
             familles=None, source: str = "UNITe",
             avec_situation: bool = True,
             avec_photographies: bool = True) -> list[Carte]:
    """Produit la carte de situation, une carte par famille présente, puis
    les photographies aériennes de la « Dynamique du site ».

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
    if avec_photographies:
        produites.append(dessiner_evolution(
            SERIE_PHOTOGRAPHIES, emprise_gdf, aires,
            dossier / f"carte_{EVOLUTION['famille']}.png", nom_projet, source))
        produites.append(dessiner_photographie(
            ORTHO_ACTUELLE, emprise_gdf, aires,
            dossier / f"carte_{ORTHO_ACTUELLE['famille']}.png", nom_projet,
            source))
    return produites
