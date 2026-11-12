# -*- coding: utf-8 -*-
"""Le rendu des coupes et du plan de repérage, depuis la seule structure.

Les critères du brief qui se vérifient sur la figure : aucune étiquette ne
chevauche une autre ni la légende, l'exagération verticale est dite, et sur le
plan chaque coupe porte ses libellés aux bonnes extrémités.
"""
import math
import re
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from shapely.geometry import LineString, Point, box

from prediag_enviro.coupes import profil, reglages, rendu

ZIP = box(-50, -50, 50, 50)


def _coupe(lieux=None, cours=None, routes=None, **autres):
    distances = [5.0 * i for i in range(2001)]
    altitudes = [250 + 120 * math.sin(d / 900.0) + 40 * math.sin(d / 170.0)
                 for d in distances]
    valeurs = dict(
        identifiant="N-S_10km", nom="N-S", extremites=("N", "S"),
        depart=(0.0, 5000.0), arrivee=(0.0, -5000.0), distances=distances,
        altitudes=altitudes, demi_longueur=5000.0, emprise=[(4950.0, 5050.0)],
        vegetation={"Forêt fermée": [(100.0, 900.0), (6000.0, 6900.0)],
                    "Haie": [(3000.0, 3040.0)],
                    "Lande ligneuse": [(1500.0, 1700.0)]},
        communes=[("La Tour-sur-Orb", 0.0, 1700.0), ("Bédarieux", 1700.0, 6700.0),
                  ("Faugères", 6700.0, 10000.0)],
        cours_d_eau=cours if cours is not None else [(400.0, "Le Vernoubrel"),
                                                     (2600.0, "Rau des Canals")],
        routes=routes if routes is not None else [(4700.0, "D908E2"),
                                                  (6800.0, "D909")],
        lieux=lieux if lieux is not None else [(300.0, "Le Mas Blanc"),
                                               (4350.0, "Bédarieux")],
    )
    valeurs.update(autres)
    return profil.Coupe(**valeurs)


def _chevauchements(boites):
    paires = []
    for i, (t1, b1) in enumerate(boites):
        for t2, b2 in boites[i + 1:]:
            if b1.overlaps(b2):
                paires.append((t1, t2))
    return paires


class Coupe(unittest.TestCase):

    def setUp(self):
        self._dossier = tempfile.TemporaryDirectory()
        self.addCleanup(self._dossier.cleanup)
        self.dossier = Path(self._dossier.name)

    def test_png_et_exageration_au_titre(self):
        r = rendu.dessiner_coupe(_coupe(), self.dossier / "c.png")
        self.assertTrue(r.chemin.exists())
        self.assertGreater(r.exageration, 1.0)
        self.assertRegex(r.titre, r"exagération verticale ×\d+,\d")
        self.assertIn("5 km de part et d'autre du projet", r.titre)
        with Image.open(r.chemin) as image:
            self.assertEqual(image.size, (3200, 1440))

    def test_aucune_etiquette_ne_se_chevauche(self):
        # Trente lieux, quinze cours d'eau et autant de routes serrés : il en
        # restera moins, mais aucun ne doit en masquer un autre ni la légende.
        lieux = [(150.0 + 120 * i, f"Hameau numéro {i}") for i in range(30)]
        cours = [(200.0 + 90 * i, f"Ruisseau très long {i}") for i in range(15)]
        routes = [(250.0 + 95 * i, f"D9{i:02d}") for i in range(15)]
        for taille in (reglages.TAILLE_COUPE, reglages.TAILLE_COUPE_DOCUMENT):
            with self.subTest(taille=taille):
                r = rendu.dessiner_coupe(_coupe(lieux, cours, routes),
                                         self.dossier / "d.png", taille=taille)
                self.assertEqual(_chevauchements(r.etiquettes), [])
                for texte, boite in r.etiquettes:
                    self.assertFalse(boite.overlaps(r.legende), texte)
                self.assertIn("PROJET", [t for t, _ in r.etiquettes])
                self.assertGreater(len(r.etiquettes), 10)

    def test_un_nom_de_cours_d_eau_par_passage(self):
        # Le Rau de Serieis coupait la NE-SO deux fois à 200 m : deux marques,
        # mais son nom une seule fois.
        cours = [(6700.0, "Rau de Serieis"), (6900.0, "Rau de Serieis"),
                 (8000.0, "Rau des Canals")]
        r = rendu.dessiner_coupe(_coupe(cours=cours), self.dossier / "r.png",
                                 taille=reglages.TAILLE_COUPE_DOCUMENT)
        textes = [t for t, _ in r.etiquettes]
        self.assertEqual(textes.count("Rau de Serieis"), 1)
        self.assertEqual(textes.count("Rau des Canals"), 1)

    def test_taille_document(self):
        r = rendu.dessiner_coupe(_coupe(), self.dossier / "doc.png",
                                 taille=reglages.TAILLE_COUPE_DOCUMENT)
        with Image.open(r.chemin) as image:
            self.assertEqual(image.size, (2200, 1120))

    def test_coupe_libre(self):
        libre = _coupe(identifiant="libre_1", nom="Le Mas Blanc – SE",
                       extremites=("Le Mas Blanc", "SE"), demi_longueur=None)
        r = rendu.dessiner_coupe(libre, self.dossier / "l.png")
        self.assertTrue(r.titre.startswith("Coupe Le Mas Blanc – SE — longueur 10 km"))
        self.assertNotIn("de part et d'autre", r.titre)


class Plan(unittest.TestCase):

    DONNEES = profil.Donnees(bbox=(-5400, -5400, 5400, 5400),
                             vegetation=[(box(-3000, 1000, -1000, 3000),
                                          "Forêt fermée")],
                             communes=[(box(-6000, -6000, 6000, 6000), "Bédarieux")],
                             cours_d_eau=[(LineString([(-5000, -100), (5000, 200)]),
                                           "L'Orb")],
                             routes=[], habitations=[])

    def _coupe(self, nom, demi):
        from prediag_enviro.coupes import geometrie as geo
        ligne = geo.trait(Point(0, 0), geo.AZIMUTS[nom], demi)
        return profil.assembler(f"{nom}_{int(2 * demi / 1000)}km", nom,
                                reglages.EXTREMITES[nom], ligne,
                                [0.0, ligne.length], [200.0, 300.0], self.DONNEES,
                                ZIP, demi_longueur=demi)

    def _plan(self, coupes):
        with tempfile.TemporaryDirectory() as dossier:
            r = rendu.dessiner_plan(self.DONNEES, coupes, ZIP, Point(0, 0),
                                    Path(dossier) / "plan.png", site="Essai")
            self.assertTrue(r.chemin.exists())
        return r

    def test_libelles_aux_bonnes_extremites(self):
        r = self._plan([self._coupe("N-S", 5000.0), self._coupe("NO-SE", 5000.0)])
        positions = {texte: (x, y) for texte, x, y in r.extremites}
        x, y = positions["NO"]
        self.assertLess(x, -3000)
        self.assertGreater(y, 3000)
        x, y = positions["SE"]
        self.assertGreater(x, 3000)
        self.assertLess(y, -3000)
        self.assertGreater(positions["N"][1], 4900)
        self.assertEqual(r.cercles, [5000.0])

    def test_meme_direction_libellee_au_bout_de_la_plus_longue(self):
        r = self._plan([self._coupe("N-S", 2000.0), self._coupe("N-S", 5000.0)])
        nords = [(x, y) for texte, x, y in r.extremites if texte == "N"]
        self.assertEqual(len(nords), 1)
        self.assertGreater(nords[0][1], 4900)
        self.assertEqual(r.cercles, [2000.0, 5000.0])

    def test_coupe_libre_libellee_aux_deux_bouts(self):
        # La coupe libre finit au N comme la coupe N-S : chacune garde le sien.
        from prediag_enviro.coupes import geometrie as geo
        ligne = geo.trait_libre(Point(100, -500), Point(0, 0), recul=300.0,
                                au_dela=1000.0)
        libre = profil.assembler("libre_1", "Papeterie Vieille – N",
                                 ("Papeterie Vieille", "N"), ligne,
                                 [0.0, ligne.length], [230.0, 250.0], self.DONNEES, ZIP)
        r = self._plan([self._coupe("N-S", 2000.0), libre])
        textes = [texte for texte, _, _ in r.extremites]
        self.assertEqual(textes.count("N"), 2)
        self.assertIn("Papeterie Vieille", textes)


if __name__ == "__main__":
    unittest.main()
