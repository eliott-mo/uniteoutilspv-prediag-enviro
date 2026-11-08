# -*- coding: utf-8 -*-
"""Le parent d'un taxon, et l'espèce dont relève une sous-espèce.

Une archive TaxRef de quelques lignes, aux colonnes de la v18 : le Grand
Capricorne, sa sous-espèce nominale, une variété de cette sous-espèce, et une
sous-espèce dont TaxRef donne le parent sous un synonyme.
"""
import copy
import csv
import io
import pickle
import tempfile
import unittest
import zipfile
from pathlib import Path

from prediag_enviro import taxref

MEMBRES = {"principal": "TAXREFv18.txt", "vernaculaires": "TAXVERNv18.txt",
           "disparus": "CDNOM_DISPARUS.txt"}
COLONNES = ("CD_NOM", "CD_TAXSUP", "CD_SUP", "CD_REF", "RANG", "LB_NOM",
            "NOM_VALIDE", "NOM_VERN", "GROUP2_INPN", "GROUP3_INPN", "ORDRE")
LIGNES = (
    ("190481", "", "", "190481", "GN", "Cerambyx", "Cerambyx", ""),
    ("12336", "190481", "190481", "12336", "ES", "Cerambyx cerdo",
     "Cerambyx cerdo", "Grand Capricorne"),
    # Un synonyme de l'espèce : un parent peut être donné sous ce nom-là.
    ("12340", "190481", "190481", "12336", "ES", "Cerambyx heros",
     "Cerambyx cerdo", ""),
    ("251483", "12336", "12336", "251483", "SSES", "Cerambyx cerdo cerdo",
     "Cerambyx cerdo cerdo", ""),
    ("251484", "12340", "12340", "251484", "SSES", "Cerambyx cerdo acuminatus",
     "Cerambyx cerdo acuminatus", ""),
    ("999", "251483", "251483", "999", "VAR", "Cerambyx cerdo cerdo var. x",
     "Cerambyx cerdo cerdo var. x", ""),
)


def _tsv(colonnes, lignes) -> str:
    sortie = io.StringIO()
    ecrivain = csv.writer(sortie, delimiter="\t", lineterminator="\n")
    ecrivain.writerow(colonnes)
    ecrivain.writerows(lignes)
    return sortie.getvalue()


def _archive(dossier: Path) -> Path:
    chemin = dossier / "TAXREF.zip"
    with zipfile.ZipFile(chemin, "w") as z:
        z.writestr(MEMBRES["principal"], _tsv(COLONNES, [
            ligne + ("Insectes", "Autres", "Coleoptera") for ligne in LIGNES]))
        z.writestr(MEMBRES["vernaculaires"],
                   _tsv(("CD_NOM", "LB_VERN", "ISO639_3"), []))
        z.writestr(MEMBRES["disparus"],
                   _tsv(("CD_NOM", "CD_NOM_REMPLACEMENT", "RAISON_SUPPRESSION"),
                        []))
    return chemin


class Parent(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._dossier = tempfile.TemporaryDirectory()
        cls.dossier = Path(cls._dossier.name)
        cls.archive = _archive(cls.dossier)
        cls.index = taxref.Index.construire(cls.archive, MEMBRES, "18")

    @classmethod
    def tearDownClass(cls):
        cls._dossier.cleanup()

    def test_parent_lu(self):
        self.assertEqual(self.index.taxons["251483"].cd_sup, "12336")

    def test_espece_d_une_sous_espece(self):
        # Cerambyx cerdo cerdo, relevé à Bédarieux : le classeur des insectes
        # porte l'espèce, pas la sous-espèce.
        self.assertEqual(self.index.espece("251483"), "12336")

    def test_espece_d_une_variete_de_sous_espece(self):
        self.assertEqual(self.index.espece("999"), "12336")

    def test_parent_donne_sous_un_synonyme(self):
        self.assertEqual(self.index.espece("251484"), "12336")

    def test_pas_d_espece_au_dessus(self):
        for cd in ("12336", "190481", "inconnu"):
            with self.subTest(cd):
                self.assertIsNone(self.index.espece(cd))

    def test_cache_ancien_reconstruit(self):
        # Un index mis en cache avant qu'on lise le parent n'en a pas : le
        # reprendre ne trouverait l'espèce d'aucune sous-espèce.
        cache = self.dossier / "taxref_index.pkl"
        ancien = {cd: copy.copy(t) for cd, t in self.index.taxons.items()}
        for taxon in ancien.values():
            taxon.__dict__.pop("cd_sup", None)
        cache.write_bytes(pickle.dumps({
            "taxons": ancien, "vern": {}, "sci": {}, "disparus": {},
            "version": "18", "format": 4}))
        index = taxref.Index.charger(self.archive, MEMBRES, "18", cache)
        self.assertEqual(index.espece("251483"), "12336")


if __name__ == "__main__":
    unittest.main()
