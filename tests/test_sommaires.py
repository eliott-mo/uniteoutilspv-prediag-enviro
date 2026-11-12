# -*- coding: utf-8 -*-
"""Les numéros de page des sommaires, calculés par Word en produisant le document.

La recette avec Word ne tourne que sur demande (`PREDIAG_WORD=1`) : elle lance
Word en arrière-plan, ce qui demande un poste Windows qui l'a, et une minute.
Les autres cas simulent Word : ils disent ce que l'outil fait quand il manque.
"""
import os
import re
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from prediag_enviro import communes
from prediag_enviro import rapport_prediag as rp
from prediag_enviro import sommaires
from prediag_enviro import zonages as mod_zonages


def _projet():
    return rp.Projet(
        nom="Bédarieux",
        communes=[communes.Commune(code="34028", nom="Bédarieux",
                                   surface_ha=4.9, part=1.0)],
        departements=["34"], surface_ha=4.9,
        aires=[mod_zonages.AireEtude(*a) for a in mod_zonages.AIRES_DEFAUT])


def _photographies(dossier):
    """Les deux planches de la dynamique du site, en paysage l'une après l'autre."""
    from PIL import Image

    from prediag_enviro import cartes
    planches = []
    for famille, nom in (("ortho_evolution", "e.png"), ("ortho_actuelle", "a.png")):
        chemin = Path(dossier) / nom
        Image.new("RGB", (300, 200), "white").save(chemin)
        planches.append(cartes.Carte(famille=famille, titre=famille,
                                     chemin=chemin, nb_zonages=0))
    return planches


def _lignes(chemin: Path) -> list[str]:
    """Le texte de chaque paragraphe, tabulations comprises, champs compris."""
    from docx import Document
    from docx.oxml.ns import qn
    lignes = []
    for p in Document(chemin).element.body.iter(qn("w:p")):
        morceaux = []
        for noeud in p.iter(qn("w:t"), qn("w:tab")):
            morceaux.append("\t" if noeud.tag == qn("w:tab") else noeud.text or "")
        lignes.append("".join(morceaux))
    return lignes


@unittest.skipUnless(os.environ.get("PREDIAG_WORD") == "1",
                     "recette Word : PREDIAG_WORD=1 pour la lancer")
class AvecWord(unittest.TestCase):

    def test_numeros_de_page(self):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / "essai.docx"
            rp.ecrire(chemin, _projet(), cartes=_photographies(dossier))
            self.assertIsNone(sommaires.calculer(chemin))
            lignes = _lignes(chemin)
            with zipfile.ZipFile(chemin) as archive:
                corps = archive.read("word/document.xml").decode("utf-8")

        self.assertNotIn("Sommaire à mettre à jour", corps)
        self.assertNotIn("w:dirty", corps)
        # Une entrée de sommaire : son intitulé, une tabulation, sa page. Word
        # la fait précéder de tabulations, selon son niveau.
        entrees = [(m.group(1).strip(), m.group(2)) for m in
                   (re.match(r"(.+?)\t(\d+)$", ligne) for ligne in lignes) if m]
        legende = re.compile(r"(Carte|Tableau|Figure) (\d+) :")

        parties = [int(p) for t, p in entrees if not legende.match(t)]
        self.assertGreaterEqual(len(parties), 5)
        # Dans l'ordre du document, et non plus « 1 » partout.
        self.assertEqual(parties, sorted(parties))
        self.assertGreater(parties[-1], 3)

        cartes = {int(legende.match(t).group(2)): int(p) for t, p in entrees
                  if legende.match(t) and t.startswith("Carte")}
        # Les deux photographies se suivent, sans page blanche entre elles.
        self.assertEqual(cartes[2], cartes[1] + 1)


class SansWord(unittest.TestCase):
    """Quand Word manque ou se fige, le document reste tel que l'outil l'a écrit."""

    ORIGINE = b"le document tel que python-docx l'a produit"

    def setUp(self):
        self._dossier = tempfile.TemporaryDirectory()
        self.chemin = Path(self._dossier.name) / "essai.docx"
        self.chemin.write_bytes(self.ORIGINE)

    def tearDown(self):
        self._dossier.cleanup()

    def test_word_absent(self):
        echec = subprocess.CompletedProcess(
            args=[], returncode=1,
            stdout="ERREUR La récupération de la fabrique de classes COM pour "
                   "le composant a échoué : 80040154 Classe non enregistrée\n"
                   .encode("utf-8"),
            stderr=b"")
        with mock.patch.object(sommaires.subprocess, "run", return_value=echec):
            message = sommaires.calculer(self.chemin)
        self.assertIn("Classe non enregistrée", message)
        self.assertEqual(self.chemin.read_bytes(), self.ORIGINE)

    def test_word_fige(self):
        fige = subprocess.TimeoutExpired(cmd="powershell", timeout=600)
        with mock.patch.object(sommaires.subprocess, "run", side_effect=fige), \
                mock.patch.object(sommaires, "_arreter_word_lance_apres") as arreter:
            message = sommaires.calculer(self.chemin, delai_s=600)
        self.assertIn("10 min", message)
        # Le Word lancé pour l'occasion ne doit pas rester ouvert, invisible,
        # avec le document verrouillé.
        arreter.assert_called_once()
        self.assertEqual(self.chemin.read_bytes(), self.ORIGINE)


if __name__ == "__main__":
    unittest.main()
