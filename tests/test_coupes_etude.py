# -*- coding: utf-8 -*-
"""L'étude d'un site : les huit coupes, le cache, la coupe libre, les livrables.

Le service IGN est simulé : un relief en pente douce, deux communes, une forêt
et un hameau au nord-ouest de la ZIP.
"""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from shapely.geometry import box, mapping

from prediag_enviro import coupes
from prediag_enviro.coupes import ign

CX, CY = 713856.0, 6278785.0
ZIP = box(CX - 120, CY - 100, CX + 120, CY + 100)


def _entite(geometrie, **proprietes):
    return {"type": "Feature", "properties": proprietes,
            "geometry": mapping(geometrie)}


COUCHES = {
    "BDTOPO_V3:zone_de_vegetation": [
        _entite(box(CX - 3000, CY + 1000, CX + 3000, CY + 1600),
                nature="Forêt fermée de feuillus")],
    "BDTOPO_V3:commune": [
        _entite(box(CX - 9000, CY - 9000, CX + 9000, CY + 2500),
                nom_officiel="Bédarieux"),
        _entite(box(CX - 9000, CY + 2500, CX + 9000, CY + 9000),
                nom_officiel="La Tour-sur-Orb")],
    "BDTOPO_V3:cours_d_eau": [],
    "BDTOPO_V3:troncon_de_route": [],
    "BDTOPO_V3:zone_d_habitation": [
        _entite(box(CX - 2050, CY + 1950, CX - 1950, CY + 2050),
                toponyme="le Mas Blanc", importance="3"),
        _entite(box(CX + 8000, CY + 8000, CX + 8100, CY + 8100),
                toponyme="Trop loin", importance="3")],
}


class _FauxIGN:
    def __init__(self):
        self.couches = []
        self.points = 0
        self.appels_altitudes = 0

    def entites(self, couche, bbox, *, proprietes=(), filtre=None, cache=None,
                libelle="", **_):
        self.couches.append(couche)
        return ign.Lecture(COUCHES[couche], date(2026, 11, 12))

    def altitudes(self, points, **_):
        self.appels_altitudes += 1
        self.points += len(points)
        return [250.0 + (y - CY) / 50.0 for _, y in points]


class Etude(unittest.TestCase):

    def setUp(self):
        self.faux = _FauxIGN()
        for nom in ("entites", "altitudes"):
            rustine = mock.patch.object(ign, nom, getattr(self.faux, nom))
            rustine.start()
            self.addCleanup(rustine.stop)
        self._dossier = tempfile.TemporaryDirectory()
        self.addCleanup(self._dossier.cleanup)
        self.dossier = Path(self._dossier.name)

    def test_huit_coupes_quatre_requetes_altimetriques(self):
        etude = coupes.etudier(ZIP, cache=self.dossier / "cache")
        self.assertEqual([c.identifiant for c in etude.coupes], [
            "N-S_4km", "E-O_4km", "NE-SO_4km", "NO-SE_4km",
            "N-S_10km", "E-O_10km", "NE-SO_10km", "NO-SE_10km"])
        # Les coupes de 4 km sont prises dans celles de 10 km.
        self.assertEqual(self.faux.appels_altitudes, 4)
        self.assertEqual(self.faux.points, 4 * 2001)
        self.assertEqual(len(self.faux.couches), 5)
        n_s = etude.coupe("N-S_10km")
        self.assertEqual(n_s.communes_traversees(), ["La Tour-sur-Orb", "Bédarieux"])
        self.assertEqual(n_s.emprise, [(4900.0, 5100.0)])

    def test_profils_relus_du_cache(self):
        coupes.etudier(ZIP, cache=self.dossier / "cache")
        self.faux.appels_altitudes = 0
        coupes.etudier(ZIP, cache=self.dossier / "cache")
        self.assertEqual(self.faux.appels_altitudes, 0)

    def test_altitudes_de_l_emprise(self):
        etude = coupes.etudier(ZIP, cache=self.dossier / "cache")
        bas, haut = etude.altitudes_emprise()
        self.assertAlmostEqual(bas, 248.0, places=1)
        self.assertAlmostEqual(haut, 252.0, places=1)

    def test_lieux_proches_et_coupe_libre(self):
        etude = coupes.etudier(ZIP, cache=self.dossier / "cache")
        lieux = coupes.lieux_proches(etude)
        self.assertEqual([lieu.nom for lieu in lieux], ["Le Mas Blanc"])
        self.assertEqual(lieux[0].direction, "NO")
        self.assertEqual(lieux[0].libelle, "Le Mas Blanc — 2,8 km au nord-ouest")
        libre = coupes.ajouter_coupe_libre(etude, lieux[0].point, lieux[0].nom)
        self.assertEqual(libre.extremites, ("Le Mas Blanc", "SE"))
        self.assertEqual(libre.nom, "Le Mas Blanc – SE")
        self.assertIsNone(libre.demi_longueur)
        self.assertIs(etude.coupes[-1], libre)
        self.assertTrue(libre.emprise)
        # Elle part derrière le hameau et dépasse la ZIP d'un kilomètre.
        self.assertAlmostEqual(libre.longueur, 2000 * 2 ** 0.5 + 300 + 1000, delta=1)

    def test_livrables(self):
        etude = coupes.etudier(ZIP, cache=self.dossier / "cache",
                               source_emprise="ZIP.zip")
        livrables = coupes.produire(etude, self.dossier / "sortie", site="Bédarieux")
        noms = sorted(p.name for p in (self.dossier / "sortie").iterdir())
        self.assertEqual(noms, sorted(
            [f"coupe_{c.identifiant}.png" for c in etude.coupes]
            + ["plan_reperage.png", "coupes_topographiques_Bedarieux.pdf",
               "coupes_topographiques_Bedarieux.json"]))
        self.assertEqual(livrables.pdf.name, "coupes_topographiques_Bedarieux.pdf")
        donnees = json.loads(livrables.json.read_text(encoding="utf-8"))
        self.assertEqual(len(donnees["coupes"]), 8)
        self.assertEqual(donnees["altitude_emprise"], {"min": 248.0, "max": 252.0})
        self.assertEqual(donnees["consultation"], "2026-11-12")

    def test_pour_le_document(self):
        etude = coupes.etudier(ZIP, cache=self.dossier / "cache")
        doc = coupes.pour_le_document(etude, ["NE-SO_10km", "N-S_4km"],
                                      self.dossier / "doc", site="Bédarieux")
        self.assertTrue(doc.plan.exists())
        # Dans l'ordre de l'étude, pas dans celui du choix.
        self.assertEqual([c.identifiant for c, _ in doc.coupes],
                         ["N-S_4km", "NE-SO_10km"])
        self.assertTrue(all(p.exists() for _, p in doc.coupes))
        self.assertEqual(doc.pdf, "coupes_topographiques_Bedarieux.pdf")
        self.assertIsNone(coupes.pour_le_document(etude, [], self.dossier / "doc"))


class PointDeVue(unittest.TestCase):
    """Des coordonnées collées depuis le Géoportail, en Lambert 93."""

    def _proche(self, texte):
        p = coupes.point_l93(texte)
        self.assertAlmostEqual(p.x, 713856.0, delta=5)
        self.assertAlmostEqual(p.y, 6278785.0, delta=5)

    def test_latitude_longitude(self):
        self._proche("43.607987, 3.171576")
        self._proche("43.607987 3.171576")

    def test_virgules_decimales(self):
        self._proche("43,607987; 3,171576")

    def test_ordre_inverse(self):
        self._proche("3.171576, 43.607987")

    def test_hors_de_france(self):
        with self.assertRaisesRegex(ValueError, "France métropolitaine"):
            coupes.point_l93("12.5, 50.1")

    def test_illisible(self):
        with self.assertRaisesRegex(ValueError, "latitude, longitude"):
            coupes.point_l93("au bout du chemin")


if __name__ == "__main__":
    unittest.main()
