# -*- coding: utf-8 -*-
"""L'assemblage d'une coupe : ce qu'elle croise, et dans quel ordre.

Un site fictif de 2 km de côté, la ZIP au centre : chaque couche y est posée à
une distance connue du départ de la coupe N-S, qui part du nord.
"""
import json
import math
import unittest
from datetime import date

from shapely.geometry import LineString, box, mapping

from prediag_enviro.coupes import ign, profil

ZIP = box(950, 950, 1050, 1050)


def _entite(geometrie, **proprietes):
    return {"type": "Feature", "properties": proprietes,
            "geometry": mapping(geometrie)}


def _donnees():
    jour = date(2026, 11, 12)
    lectures = {
        "vegetation": ign.Lecture([
            _entite(box(990, 1200, 1010, 1300), nature="Forêt fermée mixte"),
            _entite(box(990, 1250, 1010, 1350), nature="Forêt fermée de feuillus"),
            _entite(box(990, 600, 1010, 640), nature="Vigne"),
        ], jour),
        "communes": ign.Lecture([
            _entite(box(0, 1100, 2000, 2000), nom_officiel="Nord"),
            _entite(box(0, 0, 2000, 1100), nom_officiel="Sud"),
        ], jour),
        "cours_d_eau": ign.Lecture([
            _entite(LineString([(900, 1400), (1100, 1400)]),
                    toponyme="Ruisseau des Canals"),
            # Le même, en double et sans nom, 4 m plus loin.
            _entite(LineString([(900, 1404), (1100, 1404)]), toponyme=None),
        ], jour),
        "routes": ign.Lecture([
            _entite(LineString([(900, 700), (1100, 700)]), importance="2",
                    cpx_numero="D908"),
            _entite(LineString([(900, 750), (1100, 750)]), importance="5",
                    cpx_numero=None),
        ], jour),
        "habitations": ign.Lecture([
            _entite(box(995, 600, 1005, 620), toponyme="le Mas Blanc",
                    importance="3"),
            _entite(box(995, 1450, 1005, 1460), toponyme="la Grange",
                    importance="6"),
        ], jour),
    }
    return profil.Donnees.depuis_lectures((0, 0, 2000, 2000), lectures)


def _bosse(d):
    return 200.0 + 100.0 * math.exp(-((d - 800.0) / 100.0) ** 2)


class Assemblage(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.donnees = _donnees()
        trait = LineString([(1000, 1500), (1000, 500)])
        distances = [5.0 * i for i in range(201)]
        cls.coupe = profil.assembler(
            "N-S_1km", "N-S", ("N", "S"), trait, distances,
            [_bosse(d) for d in distances], cls.donnees, ZIP, demi_longueur=500.0)

    def test_emprise_au_centre(self):
        self.assertEqual(self.coupe.emprise, [(450.0, 550.0)])

    def test_vegetation_regroupee_et_fusionnee(self):
        # Deux forêts fermées qui se chevauchent : un seul tronçon ; la vigne
        # n'est pas affichée.
        self.assertEqual(self.coupe.vegetation, {"Forêt fermée": [(150.0, 300.0)]})

    def test_communes_dans_l_ordre_du_trait(self):
        self.assertEqual(self.coupe.communes,
                         [("Nord", 0.0, 400.0), ("Sud", 400.0, 1000.0)])
        self.assertEqual(self.coupe.communes_traversees(), ["Nord", "Sud"])

    def test_cours_d_eau_nomme_et_dedoublonne(self):
        self.assertEqual(self.coupe.cours_d_eau, [(100.0, "Rau des Canals")])

    def test_routes_principales_seules(self):
        self.assertEqual(self.coupe.routes, [(800.0, "D908")])

    def test_lieux_habites(self):
        # Tampon de 80 m : le Mas Blanc est croisé de 800 à 980 m. La grange,
        # d'importance 6, n'est pas nommée.
        self.assertEqual(self.coupe.lieux, [(890.0, "Le Mas Blanc")])

    def test_points_haut_et_bas(self):
        self.assertEqual(self.coupe.point_haut, (800.0, 300.0))
        self.assertAlmostEqual(self.coupe.point_bas[1], 200.0, places=3)

    def test_altitudes_de_l_emprise(self):
        z = self.coupe.altitudes_emprise()
        self.assertEqual(len(z), 21)
        # Au centimètre, comme le RGE ALTI les rend.
        self.assertAlmostEqual(min(z), _bosse(450.0), places=2)

    def test_sous_coupe_de_quatre_cents_metres(self):
        courte = profil.sous_coupe(self.coupe, 200.0, "N-S_400m", self.donnees, ZIP)
        self.assertEqual(courte.distances[0], 0.0)
        self.assertEqual(courte.distances[-1], 400.0)
        self.assertEqual(courte.altitudes[0], self.coupe.altitudes[60])
        self.assertEqual(courte.emprise, [(150.0, 250.0)])
        self.assertEqual(courte.communes, [("Nord", 0.0, 100.0),
                                           ("Sud", 100.0, 400.0)])
        self.assertEqual(courte.demi_longueur, 200.0)

    def test_aller_retour_json(self):
        texte = json.dumps(self.coupe.en_dict())
        relue = profil.Coupe.depuis_dict(json.loads(texte))
        self.assertEqual(relue, self.coupe)
        dico = json.loads(texte)
        # Le profil (distance, x, y, z), comme le brief le demande.
        self.assertEqual(dico["profil"][0], [0.0, 1000.0, 1500.0,
                                             round(_bosse(0.0), 2)])


if __name__ == "__main__":
    unittest.main()
