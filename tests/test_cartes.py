# -*- coding: utf-8 -*-
"""Les planches de photographies aériennes de la « Dynamique du site ».

Hors ligne : le fond est simulé, et sa demande enregistrée. On vérifie que les
planches demandent les bonnes couches, qu'elles sortent quand le service ne
répond pas, qu'une période que l'IGN ne couvre pas est dite, et que chaque
planche dit d'où vient son fond.
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import geopandas as gpd
from shapely.geometry import box

from prediag_enviro import cartes
from prediag_enviro import zonages as mod_zonages

#: Un carré de 600 m près de Bédarieux, en Lambert 93.
EMPRISE = gpd.GeoDataFrame(geometry=[box(722000, 6278000, 722600, 6278600)],
                           crs=2154)
AIRES = [mod_zonages.AireEtude(*a) for a in mod_zonages.AIRES_DEFAUT]


def _couche(url: str) -> str:
    return url.split("LAYER=")[1].split("&")[0]


class Photographies(unittest.TestCase):

    def setUp(self):
        self._dossier = tempfile.TemporaryDirectory()
        self.dossier = Path(self._dossier.name)
        self.demandes = []
        #: Couches que l'IGN ne couvre pas sur le cadre, pour le test.
        self.absentes = set()
        #: Couches dont le service ne répond pas au moment du rendu.
        self.en_panne = set()

        def fond_hors_ligne(ax, source=None, **options):
            self.demandes.append(_couche(source))
            if _couche(source) in self.en_panne:
                raise RuntimeError("hors ligne")

        def couverte(fond, ax):
            return False if _couche(fond["url"]) in self.absentes else None

        self._rustines = [
            mock.patch.object(cartes.cx, "add_basemap", fond_hors_ligne),
            mock.patch.object(cartes, "_cacher_tuiles", lambda: None),
            mock.patch.object(cartes, "_couverte", couverte),
            mock.patch("time.sleep", lambda secondes: None),
        ]
        for rustine in self._rustines:
            rustine.start()

    def tearDown(self):
        for rustine in self._rustines:
            rustine.stop()
        self._dossier.cleanup()

    def test_pleine_page(self):
        carte = cartes.dessiner_photographie(
            cartes.ORTHO_ACTUELLE, EMPRISE, AIRES, self.dossier / "a.png",
            "Bédarieux")
        self.assertTrue(carte.chemin.exists())
        self.assertEqual(carte.famille, "ortho_actuelle")
        self.assertEqual(set(self.demandes), {"ORTHOIMAGERY.ORTHOPHOTOS"})
        self.assertEqual(carte.fond, cartes.ORTHO_ACTUELLE["attribution"])
        self.assertRegex(carte.date, r"^\d\d/\d\d/\d{4}$")

    def test_serie_demande_chaque_periode(self):
        carte = cartes.dessiner_evolution(
            cartes.SERIE_PHOTOGRAPHIES, EMPRISE, AIRES, self.dossier / "e.png",
            "Bédarieux")
        self.assertTrue(carte.chemin.exists())
        self.assertEqual(carte.famille, "ortho_evolution")
        self.assertEqual(
            list(dict.fromkeys(self.demandes)),
            [_couche(f["url"]) for f in cartes.SERIE_PHOTOGRAPHIES])
        self.assertEqual(carte.absentes, ())
        self.assertRegex(carte.date, r"^\d\d/\d\d/\d{4}$")

    def test_periode_non_couverte(self):
        # À Bédarieux, l'IGN n'a pas de prise de vue de 1980-1995 : le
        # service répond 404.
        self.absentes = {"ORTHOIMAGERY.ORTHOPHOTOS.1980-1995"}
        carte = cartes.dessiner_evolution(
            cartes.SERIE_PHOTOGRAPHIES, EMPRISE, AIRES, self.dossier / "e.png",
            "Bédarieux")
        self.assertEqual(carte.absentes, ("1980-1995",))
        self.assertNotIn("ORTHOIMAGERY.ORTHOPHOTOS.1980-1995", self.demandes)
        self.assertEqual(carte.fond, (
            "Photographies aériennes 1950-1965, 1965-1980, 2000-2005, "
            "2011-2015 et la plus récente — IGN, Géoplateforme"))

    def test_periode_indisponible_au_rendu(self):
        # Le service ne répond pas : la vignette le dit, la planche sort, et
        # la période n'est pas citée — elle n'est pas montrée.
        self.en_panne = {"ORTHOIMAGERY.ORTHOPHOTOS2011-2015"}
        carte = cartes.dessiner_evolution(
            cartes.SERIE_PHOTOGRAPHIES, EMPRISE, AIRES, self.dossier / "e.png",
            "Bédarieux")
        self.assertTrue(carte.chemin.exists())
        self.assertEqual(carte.absentes, ())
        self.assertNotIn("2011-2015", carte.fond)

    def test_produire_ajoute_les_deux_planches(self):
        produites = cartes.produire(mod_zonages.Resultat(), EMPRISE, AIRES,
                                    self.dossier, "Bédarieux",
                                    avec_situation=False)
        self.assertEqual([c.famille for c in produites],
                         ["ortho_evolution", "ortho_actuelle"])


if __name__ == "__main__":
    unittest.main()
