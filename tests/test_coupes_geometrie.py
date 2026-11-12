# -*- coding: utf-8 -*-
"""La géométrie des coupes topographiques : traits, intervalles, étiquettes.

Le prototype du 12 novembre 2026 avait inversé la coupe NO-SE : elle partait du
SE. Les quatre orientations sont donc vérifiées une à une, sur le terrain du
plan et non sur l'azimut annoncé.
"""
import unittest

from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box

from prediag_enviro.coupes import geometrie as geo

CENTRE = Point(713856.0, 6278785.0)


class Orientation(unittest.TestCase):
    """Chaque coupe part de l'extrémité nommée en premier."""

    def _depart_arrivee(self, nom):
        trait = geo.trait(CENTRE, geo.AZIMUTS[nom], 5000.0)
        (x0, y0), (x1, y1) = trait.coords[0], trait.coords[-1]
        return x0 - CENTRE.x, y0 - CENTRE.y, x1 - CENTRE.x, y1 - CENTRE.y

    def test_nord_sud(self):
        dx0, dy0, dx1, dy1 = self._depart_arrivee("N-S")
        self.assertAlmostEqual(dx0, 0.0, places=6)
        self.assertAlmostEqual(dy0, 5000.0, places=6)
        self.assertAlmostEqual(dy1, -5000.0, places=6)

    def test_est_ouest(self):
        dx0, dy0, dx1, _ = self._depart_arrivee("E-O")
        self.assertAlmostEqual(dx0, 5000.0, places=6)
        self.assertAlmostEqual(dy0, 0.0, places=6)
        self.assertAlmostEqual(dx1, -5000.0, places=6)

    def test_nord_est_sud_ouest(self):
        dx0, dy0, dx1, dy1 = self._depart_arrivee("NE-SO")
        self.assertGreater(dx0, 3000.0)
        self.assertGreater(dy0, 3000.0)
        self.assertLess(dx1, -3000.0)
        self.assertLess(dy1, -3000.0)

    def test_nord_ouest_sud_est(self):
        # Le piège du prototype : la coupe démarre au NO, azimut 315°.
        dx0, dy0, dx1, dy1 = self._depart_arrivee("NO-SE")
        self.assertLess(dx0, -3000.0)
        self.assertGreater(dy0, 3000.0)
        self.assertGreater(dx1, 3000.0)
        self.assertLess(dy1, -3000.0)

    def test_longueur(self):
        for nom in geo.AZIMUTS:
            self.assertAlmostEqual(
                geo.trait(CENTRE, geo.AZIMUTS[nom], 2000.0).length, 4000.0)


class Echantillons(unittest.TestCase):

    def test_pas_de_cinq_metres_extremites_comprises(self):
        trait = LineString([(0, 0), (0, 100)])
        distances, xs, ys = geo.echantillons(trait, 5.0)
        self.assertEqual(len(distances), 21)
        self.assertEqual(distances[0], 0.0)
        self.assertEqual(distances[-1], 100.0)
        self.assertAlmostEqual(ys[4], 20.0)


class Intervalles(unittest.TestCase):
    """Les tronçons du trait dans un polygone, en distance depuis le départ."""

    TRAIT = LineString([(0, 0), (1000, 0)])

    def test_un_polygone(self):
        self.assertEqual(geo.intervalles(self.TRAIT, box(200, -50, 300, 50)),
                         [(200.0, 300.0)])

    def test_polygone_troue(self):
        anneau = Polygon([(100, -50), (500, -50), (500, 50), (100, 50)],
                         [[(200, -10), (300, -10), (300, 10), (200, 10)]])
        self.assertEqual(geo.intervalles(self.TRAIT, anneau),
                         [(100.0, 200.0), (300.0, 500.0)])

    def test_multipolygone_dans_l_ordre_du_trait(self):
        deux = MultiPolygon([box(700, -5, 800, 5), box(100, -5, 150, 5)])
        self.assertEqual(geo.intervalles(self.TRAIT, deux),
                         [(100.0, 150.0), (700.0, 800.0)])

    def test_effleurement_ignore(self):
        # Un polygone qui touche le trait en un point ne le traverse pas.
        pointe = Polygon([(400, 0), (450, 30), (350, 30)])
        self.assertEqual(geo.intervalles(self.TRAIT, pointe), [])

    def test_trait_entier_dans_le_polygone(self):
        self.assertEqual(geo.intervalles(self.TRAIT, box(-10, -10, 2000, 10)),
                         [(0.0, 1000.0)])

    def test_hors_du_trait(self):
        self.assertEqual(geo.intervalles(self.TRAIT, box(0, 100, 50, 200)), [])


class Croisements(unittest.TestCase):

    def test_meandres(self):
        trait = LineString([(0, 0), (1000, 0)])
        riviere = LineString([(100, -50), (110, 50), (120, -50), (600, 50)])
        positions = geo.croisements(trait, riviere)
        self.assertEqual(len(positions), 3)
        self.assertAlmostEqual(positions[0], 105.0)

    def test_dedoublonner_par_proximite(self):
        # Méandres et doublons de la BD TOPO : un seul repère par passage.
        self.assertEqual(geo.dedoublonner([105.0, 115.0, 360.0, 112.0], 12.0),
                         [105.0, 360.0])


class LieuxANommer(unittest.TestCase):

    def test_un_nom_une_fois_sur_son_plus_long_troncon(self):
        candidats = [("Bédarieux", 100.0, 300.0), ("Bédarieux", 400.0, 900.0),
                     ("Bédarieux", 950.0, 1000.0)]
        self.assertEqual(geo.lieux_a_nommer(candidats, 10000.0),
                         [(650.0, "Bédarieux")])

    def test_ecart_minimal_entre_deux_noms(self):
        # À 6 % de 10 km, deux noms à moins de 600 m : le plus long gagne.
        candidats = [("Le Mas", 1000.0, 1100.0), ("Pouzes", 1200.0, 1600.0),
                     ("Levas", 5000.0, 5100.0)]
        self.assertEqual(geo.lieux_a_nommer(candidats, 10000.0),
                         [(1400.0, "Pouzes"), (5050.0, "Levas")])


class Centre(unittest.TestCase):

    def test_bloc_le_plus_grand(self):
        grand = box(0, 0, 400, 400)
        petit = box(5000, 5000, 5010, 5010)
        centre = geo.centre(MultiPolygon([petit, grand]))
        self.assertAlmostEqual(centre.x, 200.0)
        self.assertAlmostEqual(centre.y, 200.0)

    def test_polygone_simple(self):
        self.assertTrue(geo.centre(box(0, 0, 10, 10)).equals(Point(5, 5)))


class Libelles(unittest.TestCase):

    def test_ruisseau_abrege(self):
        self.assertEqual(geo.abreger("Ruisseau des Canals"), "Rau des Canals")
        self.assertEqual(geo.abreger("Ruisseau d'Arles"), "Rau d'Arles")
        self.assertEqual(geo.abreger("L'Orb"), "L'Orb")

    def test_majuscule_initiale(self):
        # La BD TOPO écrit « le Mas Blanc » : l'article prend sa capitale en
        # tête d'étiquette, le reste du nom ne bouge pas.
        self.assertEqual(geo.capitale("le Mas Blanc"), "Le Mas Blanc")
        self.assertEqual(geo.capitale("Bédarieux"), "Bédarieux")
        self.assertEqual(geo.capitale(""), "")

    def test_rose_des_vents(self):
        self.assertEqual(geo.rose(0, 1), "N")
        self.assertEqual(geo.rose(1, 1), "NE")
        self.assertEqual(geo.rose(1, 0), "E")
        self.assertEqual(geo.rose(1, -1), "SE")
        self.assertEqual(geo.rose(0, -1), "S")
        self.assertEqual(geo.rose(-1, -1), "SO")
        self.assertEqual(geo.rose(-1, 0), "O")
        self.assertEqual(geo.rose(-1, 1), "NO")


class TraitLibre(unittest.TestCase):
    """La coupe vers un hameau : du hameau à la ZIP, et un peu au-delà."""

    def test_part_du_hameau_et_depasse_la_zip(self):
        trait = geo.trait_libre(Point(0, 3000), Point(0, 0), recul=200.0,
                                au_dela=1000.0)
        self.assertEqual(trait.coords[0], (0.0, 3200.0))
        self.assertEqual(trait.coords[-1], (0.0, -1000.0))

    def test_points_confondus(self):
        with self.assertRaises(ValueError):
            geo.trait_libre(Point(10, 10), Point(10, 10))


if __name__ == "__main__":
    unittest.main()
