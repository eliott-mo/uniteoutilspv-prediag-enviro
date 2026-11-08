# -*- coding: utf-8 -*-
"""Les planches de photographies aériennes de la « Dynamique du site ».

Hors ligne : le fond est simulé, et sa demande enregistrée. On vérifie que la
planche demande la bonne couche, qu'elle sort quand le service ne répond pas,
et qu'elle dit d'où vient son fond.
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


class Photographies(unittest.TestCase):

    def setUp(self):
        self._dossier = tempfile.TemporaryDirectory()
        self.dossier = Path(self._dossier.name)
        self.demandes = []

        def fond_hors_ligne(ax, source=None, **options):
            self.demandes.append(source)
            raise RuntimeError("hors ligne")

        self._rustines = [
            mock.patch.object(cartes.cx, "add_basemap", fond_hors_ligne),
            mock.patch.object(cartes, "_cacher_tuiles", lambda: None),
            mock.patch("time.sleep", lambda secondes: None),
        ]
        for rustine in self._rustines:
            rustine.start()

    def tearDown(self):
        for rustine in self._rustines:
            rustine.stop()
        self._dossier.cleanup()

    def test_couche_et_attribution(self):
        carte = cartes.dessiner_photographie(
            cartes.ORTHO_1950, EMPRISE, AIRES, self.dossier / "a.png",
            "Bédarieux")
        self.assertTrue(carte.chemin.exists())
        self.assertEqual(carte.famille, "ortho_1950")
        self.assertTrue(self.demandes)
        self.assertTrue(all("ORTHOIMAGERY.ORTHOPHOTOS.1950-1965" in d
                            for d in self.demandes))
        self.assertEqual(carte.fond, cartes.ORTHO_1950["attribution"])
        self.assertRegex(carte.date, r"^\d\d/\d\d/\d{4}$")

    def test_produire_ajoute_les_deux_planches(self):
        produites = cartes.produire(mod_zonages.Resultat(), EMPRISE, AIRES,
                                    self.dossier, "Bédarieux",
                                    avec_situation=False)
        self.assertEqual([c.famille for c in produites],
                         ["ortho_1950", "ortho_actuelle"])
        self.assertTrue(any("ORTHOIMAGERY.ORTHOPHOTOS&" in d
                            for d in self.demandes))


if __name__ == "__main__":
    unittest.main()
