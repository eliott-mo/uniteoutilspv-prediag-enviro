# -*- coding: utf-8 -*-
"""Coupes topographiques autour de la zone d'implantation potentielle.

D'après le prototype de Mélina, validé sur Bédarieux le 12 novembre 2026, et
son brief « Module de coupes topographiques » :

    etudier(emprise)            lit le RGE ALTI et la BD TOPO, calcule 8 coupes
    ajouter_coupe_libre(...)    une coupe vers un hameau ou un point de vue
    produire(etude, dossier)    plan de repérage, PNG, PDF et JSON
    pour_le_document(...)       les coupes retenues pour le prédiagnostic

Les briques se remplacent une à une : `geometrie` (traits, intervalles),
`ign` (client, cache), `profil` (structure sérialisable), `rendu` (dessin
depuis la seule structure), `reglages` (valeurs par défaut, couleurs).

En ligne de commande :  python -m prediag_enviro.coupes --emprise ZIP.zip
"""
from .etude import (CoupesDuDocument, Etude, Lieu, Livrables,  # noqa: F401
                    ajouter_coupe_libre, etudier, lieux_proches, nom_de_fichier,
                    point_l93, pour_le_document, produire)
from .ign import ErreurIGN  # noqa: F401
from .rendu import en_km  # noqa: F401
from .profil import Coupe  # noqa: F401
