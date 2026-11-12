# -*- coding: utf-8 -*-
"""Recette du brief sur Bédarieux, contre la vraie Géoplateforme.

Désactivée par défaut : elle appelle le réseau et lit l'emprise du projet, qui
n'est pas dans le dépôt. Pour la lancer :

    set PREDIAG_RESEAU=1
    set PREDIAG_EMPRISE_BEDARIEUX=<ZIP de shapefile ou KML de l'emprise>
    python -m unittest tests.test_coupes_bedarieux

Sans `PREDIAG_EMPRISE_BEDARIEUX`, le test cherche l'archive du dossier du
projet sur le OneDrive d'UNITe. Cache vide : les dix fichiers du brief doivent
sortir en moins de deux minutes.
"""
import os
import tempfile
import time
import unittest
from pathlib import Path

EMPRISE = Path(os.environ.get(
    "PREDIAG_EMPRISE_BEDARIEUX",
    Path.home() / "OneDrive - Unite" / "330_DEV_PV_Autres" / "01_Outils"
    / "11. DP-PC Instruction" / "Cas par Cas 3MW" / "34. Bédarieux"
    / "Bédarieux - Emprise SHP.zip"))


@unittest.skipUnless(os.environ.get("PREDIAG_RESEAU") == "1",
                     "recette réseau : PREDIAG_RESEAU=1 pour la lancer")
@unittest.skipUnless(EMPRISE.exists(), f"emprise introuvable : {EMPRISE}")
class RecetteBedarieux(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from prediag_enviro import coupes
        from prediag_enviro.coupes.__main__ import lire
        cls._dossier = tempfile.TemporaryDirectory()
        dossier = Path(cls._dossier.name)
        debut = time.perf_counter()
        cls.etude = coupes.etudier(lire(EMPRISE), cache=dossier / "cache")
        cls.livrables = coupes.produire(cls.etude, dossier / "sortie", site="Bédarieux")
        cls.duree = time.perf_counter() - debut

    @classmethod
    def tearDownClass(cls):
        cls._dossier.cleanup()

    def test_dix_fichiers_en_moins_de_deux_minutes(self):
        fichiers = [self.livrables.plan, self.livrables.pdf, *self.livrables.coupes.values()]
        self.assertEqual(len(fichiers), 10)
        self.assertTrue(all(f.exists() for f in fichiers))
        self.assertLess(self.duree, 120)

    def test_coupe_nord_sud(self):
        c = self.etude.coupe("N-S_10km")
        self.assertAlmostEqual(c.point_haut[1], 402, delta=10)
        self.assertAlmostEqual(c.point_bas[1], 212, delta=5)
        self.assertEqual(c.communes_traversees(),
                         ["La Tour-sur-Orb", "Bédarieux", "Faugères"])

    def test_coupe_nord_est_sud_ouest(self):
        c = self.etude.coupe("NE-SO_10km")
        self.assertEqual(c.communes_traversees(),
                         ["Carlencas-et-Levas", "Bédarieux", "Hérépian"])
        self.assertAlmostEqual(c.point_haut[1], 434, delta=10)

    def test_projet_au_centre_vers_250_260_m(self):
        for c in self.etude.coupes:
            with self.subTest(coupe=c.identifiant):
                a, b = max(c.emprise, key=lambda i: i[1] - i[0])
                self.assertLess(abs((a + b) / 2 - c.demi_longueur), 150)
                z = sorted(c.altitudes_emprise())
                self.assertTrue(245 <= z[len(z) // 2] <= 275, z[len(z) // 2])


if __name__ == "__main__":
    unittest.main()
