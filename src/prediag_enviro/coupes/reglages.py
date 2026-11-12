# -*- coding: utf-8 -*-
"""Les réglages des coupes topographiques, en un seul endroit.

Valeurs du prototype de Mélina, validé sur Bédarieux le 12 novembre 2026 (brief
« Module de coupes topographiques ») : quatre directions, coupes de 4 et 10 km,
un point tous les 5 m, rendu sans bâtiments.
"""
from __future__ import annotations

#: Azimut de l'extrémité de départ, celle nommée en premier : la coupe NO-SE
#: part du NO, à 315°, et non à 135° comme le prototype l'avait d'abord tracée.
AZIMUTS = {"N-S": 0.0, "E-O": 90.0, "NE-SO": 45.0, "NO-SE": 315.0}
EXTREMITES = {"N-S": ("N", "S"), "E-O": ("E", "O"),
              "NE-SO": ("NE", "SO"), "NO-SE": ("NO", "SE")}

#: Demi-longueurs, en mètres : des coupes de 4 et de 10 km.
DEMI_LONGUEURS = (2000.0, 5000.0)

#: Pas d'échantillonnage le long du trait, en mètres.
PAS = 5.0

#: Marge autour de la plus longue coupe pour la requête des couches, en mètres.
MARGE_REQUETE = 300.0

#: Coupe vers un lieu : recul derrière le lieu, et prolongement au-delà de la
#: ZIP, pour que ni l'un ni l'autre ne soit collé au bord de la figure.
RECUL_LIBRE = 300.0
AU_DELA_LIBRE = 1000.0

# ──────────────────────────────────────────────────────── lecture des couches

#: Les couches de la BD TOPO lues, les attributs gardés, et le filtre posé côté
#: serveur. Le filtre divise par dix la lecture des routes : 589 tronçons
#: d'importance 1 à 3 sur le carré de Bédarieux, contre 6 006 en tout
#: (mesuré le 12/11/2026).
COUCHES = {
    "vegetation": ("BDTOPO_V3:zone_de_vegetation", ("nature",),
                   "nature IN ('Forêt fermée de feuillus', 'Forêt fermée de "
                   "conifères', 'Forêt fermée mixte', 'Bois', 'Forêt ouverte', "
                   "'Haie', 'Lande ligneuse', 'Peupleraie')"),
    "communes": ("BDTOPO_V3:commune", ("nom_officiel", "code_insee"), None),
    "cours_d_eau": ("BDTOPO_V3:cours_d_eau", ("toponyme",), None),
    "routes": ("BDTOPO_V3:troncon_de_route", ("importance", "cpx_numero"),
               "importance IN ('1', '2', '3')"),
    "habitations": ("BDTOPO_V3:zone_d_habitation",
                    ("toponyme", "importance", "nature"), None),
}

#: Le nom du champ géométrique des couches BD TOPO V3 sur le WFS.
CHAMP_GEOMETRIE = "geometrie"

#: Regroupement des natures de végétation. Vigne et verger ne sont pas
#: affichés. La peupleraie n'est pas au brief, faute d'en avoir rencontré à
#: Bédarieux : elle forme un écran aussi fermé qu'une forêt.
CLASSES_VEGETATION = {
    "Forêt fermée de feuillus": "Forêt fermée",
    "Forêt fermée de conifères": "Forêt fermée",
    "Forêt fermée mixte": "Forêt fermée",
    "Peupleraie": "Forêt fermée",
    "Bois": "Bois / forêt ouverte",
    "Forêt ouverte": "Bois / forêt ouverte",
    "Lande ligneuse": "Lande ligneuse",
    "Haie": "Haie",
}
ORDRE_VEGETATION = ("Forêt fermée", "Bois / forêt ouverte", "Lande ligneuse",
                    "Haie")
#: Classes posées en demi-épaisseur sur le profil.
VEGETATION_BASSE = ("Lande ligneuse", "Haie")

#: Importance BD TOPO des routes et des lieux habités repérés sur les coupes.
IMPORTANCES_ROUTES = ("1", "2", "3")
IMPORTANCES_LIEUX = ("1", "2", "3", "4")

#: Tampon autour des zones d'habitation : un hameau que le trait frôle compte.
TAMPON_HABITATIONS = 80.0

#: Écarts relatifs à la longueur de la coupe : deux noms de lieux, deux cours
#: d'eau, deux routes ; et le tronçon minimal pour écrire un nom de commune.
ECART_LIEUX = 0.06
ECART_COURS_D_EAU = 0.012
ECART_ROUTES = 0.015
PART_NOM_COMMUNE = 0.06

# ──────────────────────────────────────────────────────────────────── rendu

COULEURS = {
    "terrain": "#e9e2d6",
    "profil": "#5b4a3a",
    "emprise": "#f2a541",
    "emprise_bord": "#b35806",
    "surface_utile": "#d7301f",
    "projet": "#b2182b",
    "commune": "#7b3294",
    "cours_d_eau": "#2171b5",
    "cours_d_eau_plan": "#6baed6",
    "route": "#444444",
    "route_plan": "#666666",
    "lieu": "#555555",
}
COULEURS_VEGETATION = {
    "Forêt fermée": "#2f6b2f",
    "Bois / forêt ouverte": "#6fa35a",
    "Haie": "#a3c26b",
    "Lande ligneuse": "#d6d39a",
}

#: Taille des figures, en pouces. Les PNG et le PDF des huit coupes gardent
#: celle du prototype ; le prédiagnostic prend une taille qui tient sur une page
#: A4 couchée sans réduire les textes : à 16 pouces, posée sur 25 cm, une
#: étiquette de 7 points en ferait 4,4.
TAILLE_COUPE = (16.0, 7.2)
TAILLE_COUPE_DOCUMENT = (11.0, 5.6)
TAILLE_PLAN = (15.0, 11.0)
TAILLE_PLAN_DOCUMENT = (11.0, 7.6)
DPI = 200

#: Le plan de repérage déborde la plus longue coupe de cette marge, en mètres.
MARGE_PLAN = 400.0

#: Ce que la légende appelle l'emprise, faute d'autre indication.
LIBELLE_EMPRISE = "Zone d'implantation potentielle"
