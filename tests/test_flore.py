# -*- coding: utf-8 -*-
"""La colonne des zones humides du classeur de flore, et son cache.

Le classeur réel pèse 38 Mo : on en fabrique un de trois lignes, avec la
colonne « ZH (Arrêté 2008) » ailleurs qu'en 117e position, où elle est dans
celui de la responsable environnement.
"""
import pickle
import tempfile
import unittest
from pathlib import Path

import openpyxl

from prediag_enviro import flore, reference

COLONNE_ZH = 55


def _classeur(dossier: Path) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = flore.ONGLET_STATUTS
    entete = [None] * COLONNE_ZH
    entete[0], entete[1], entete[4] = "CD_REF", "LB_NOM", "NOM_VERN"
    entete[COLONNE_ZH - 1] = "ZH (Arrêté 2008)"
    ws.append(entete)
    for cd_ref, nom, vern, zh in (("1", "Juncus effusus", "Jonc épars", "oui"),
                                  ("2", "Quercus ilex", "Chêne vert", 0),
                                  ("3", "Lythrum salicaria", "Salicaire", None)):
        ligne = [None] * COLONNE_ZH
        ligne[0], ligne[1], ligne[4] = cd_ref, nom, vern
        ligne[COLONNE_ZH - 1] = zh
        ws.append(ligne)
    chemin = dossier / "A - Statut FLORE.xlsx"
    wb.save(chemin)
    return chemin


class ColonneZonesHumides(unittest.TestCase):

    def setUp(self):
        self._dossier = tempfile.TemporaryDirectory()
        self.dossier = Path(self._dossier.name)
        self.chemin = _classeur(self.dossier)

    def tearDown(self):
        self._dossier.cleanup()

    def _zh(self, classeur, cd_ref):
        statuts = reference.Reference({"flore": classeur})
        return [e.code for e in statuts.entrees(cd_ref, "ZH",
                                                "France métropolitaine")]

    def test_indicatrice_lue(self):
        classeur = flore.lire(self.chemin)
        self.assertEqual(self._zh(classeur, "1"), ["oui"])
        # Le classeur écrit 0 pour « non » : ce n'est pas un statut.
        self.assertEqual(self._zh(classeur, "2"), [])
        self.assertEqual(self._zh(classeur, "3"), [])

    def test_cache_ancien_ignore(self):
        # Un cache écrit avant que la colonne soit lue a la même signature de
        # fichier : le reprendre rendrait une flore sans aucune indicatrice.
        etat = self.chemin.stat()
        cache = self.dossier / "flore_index.pkl"
        cache.write_bytes(pickle.dumps({
            "signature": f"{etat.st_size}-{int(etat.st_mtime)}",
            "taxons": [], "colonnes": [], "avertissements": [],
            "citations": {}}))
        classeur = flore.lire(self.chemin, cache=cache)
        self.assertEqual(self._zh(classeur, "1"), ["oui"])

    def test_cache_relu(self):
        cache = self.dossier / "flore_index.pkl"
        flore.lire(self.chemin, cache=cache)
        classeur = flore.lire(self.chemin, cache=cache)
        self.assertEqual(self._zh(classeur, "1"), ["oui"])


if __name__ == "__main__":
    unittest.main()
