# -*- coding: utf-8 -*-
"""Ce que le prédiagnostic écrit des zones humides, et la phrase des PNA.

Les vérifications portent sur le document produit : c'est lui que lit le chef
de projet, et le défaut du 1er novembre 2026 — « Aucun zonage de cette nature
n'est présent » sous la couche BCAE 2 — ne se voyait que là.
"""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from docx import Document

from prediag_enviro import communes
from prediag_enviro import rapport_prediag as rp
from prediag_enviro import zonages as mod_zonages

BCAE = "Zone humide ou tourbière (BCAE 2)"
#: Ce que la mise en garde doit dire, quelle qu'en soit la tournure.
ABSENCE = "L'absence de polygone ne vaut donc pas absence de zone humide"


def _projet():
    return rp.Projet(
        nom="Bédarieux",
        communes=[communes.Commune(code="34028", nom="Bédarieux",
                                   surface_ha=51.8, part=1.0)],
        departements=["34"], surface_ha=51.8,
        aires=[mod_zonages.AireEtude(*a) for a in mod_zonages.AIRES_DEFAUT])


def _paragraphes(resultat_zonages=None):
    """Le texte des paragraphes du document produit, dans l'ordre."""
    with tempfile.TemporaryDirectory() as dossier:
        chemin = Path(dossier) / "essai.docx"
        rp.ecrire(chemin, _projet(), resultat_zonages=resultat_zonages)
        return [p.text for p in Document(chemin).paragraphs]


def _section(paragraphes, titre, suivant):
    """Ce qui s'écrit entre un intitulé et le suivant."""
    debut = paragraphes.index(titre)
    return paragraphes[debut + 1:paragraphes.index(suivant, debut + 1)]


class Pna(unittest.TestCase):

    def test_une_espece(self):
        self.assertEqual(
            rp._phrase_pna(["Loutre d'Europe"]),
            "1 espèce recensée sur la commune fait l'objet d'un plan national "
            "d'actions : Loutre d'Europe.")

    def test_plusieurs_especes(self):
        # Bédarieux, 1er novembre 2026 : « 39 espèces recensées sur la
        # commune faitnt l'objet d'un plan national d'actions ».
        self.assertEqual(
            rp._phrase_pna(["Agrion de Mercure", "Loutre d'Europe"]),
            "2 espèces recensées sur la commune font l'objet d'un plan national "
            "d'actions : Agrion de Mercure et Loutre d'Europe.")

    def test_aucune(self):
        self.assertEqual(
            rp._phrase_pna([]),
            "Aucune des espèces recensées sur la commune ne fait l'objet d'un "
            "plan national d'actions.")


class ZonesHumidesBcae(unittest.TestCase):
    """La couche de la BCAE 2 n'est pas un inventaire : le document le dit."""

    def _texte(self, resultat):
        return " ".join(_section(_paragraphes(resultat),
                                 "Zones humides et tourbières",
                                 "Plan National d'Actions (PNA)"))

    def test_sans_polygone(self):
        texte = self._texte(mod_zonages.Resultat())
        self.assertNotIn("Aucun zonage de cette nature", texte)
        self.assertIn("Aucune zone humide ni tourbière délimitée au titre de la "
                      "BCAE 2", texte)
        self.assertIn(ABSENCE, texte)

    def test_avec_polygone(self):
        resultat = mod_zonages.Resultat(zonages=[mod_zonages.Zonage(
            famille="zones_humides", type=BCAE, identifiant="",
            nom="Tourbière", interet="3,4 ha", distance_m=1200.0,
            aires=["AER"])])
        texte = self._texte(resultat)
        self.assertIn("on recense 1 ", texte)
        self.assertIn(ABSENCE, texte)


class RubriqueZoneHumide(unittest.TestCase):
    """La note de la rubrique dit ce que l'outil renseigne, et rien de faux."""

    def test_note_a_jour(self):
        texte = " ".join(_section(_paragraphes(mod_zonages.Resultat()),
                                  "Zone humide", "Avifaune"))
        # La note du 5 octobre 2026, antérieure à la BCAE 2 et contredite par
        # la carte nationale de prélocalisation parue en 2023.
        self.assertNotIn("pas encore alimentée automatiquement", texte)
        self.assertNotIn("ne sont pas nationales", texte)
        self.assertIn("BCAE 2", texte)
        self.assertIn("restent à consulter", texte)


def _plante(cd_ref, nom_scientifique):
    return SimpleNamespace(cd_ref=cd_ref, nom_commun="",
                           nom_scientifique=nom_scientifique)


class _Statuts:
    """Ce que les classeurs répondent pour la colonne des zones humides."""

    def __init__(self, indicatrices, colonne=True):
        self.indicatrices, self.colonne = set(indicatrices), colonne

    def couvre(self, type_statut, territoire):
        return self.colonne and type_statut == "ZH"

    def entrees(self, cd_ref, type_statut, territoire):
        if type_statut == "ZH" and cd_ref in self.indicatrices:
            return [SimpleNamespace(code="oui", rendu="oui", periode="")]
        return []


INDEX = SimpleNamespace(taxons={
    "1": SimpleNamespace(nom_vern="Salicaire commune"),
    "2": SimpleNamespace(nom_vern="Jonc épars"),
    "3": SimpleNamespace(nom_vern="Chêne vert"),
})
PLANTES = [_plante("1", "Lythrum salicaria"), _plante("2", "Juncus effusus"),
           _plante("3", "Quercus ilex")]
REFERENCE = ("liste des espèces indicatrices de zones humides (arrêté du "
             "24 juin 2008 modifié, annexe 2.1)")


class FloreIndicatrice(unittest.TestCase):
    """Les plantes de la commune que l'arrêté du 24 juin 2008 désigne."""

    def _phrase(self, plantes, statuts):
        return rp._flore_zone_humide(_projet(), plantes, statuts, INDEX)

    def test_indicatrices_nommees(self):
        self.assertEqual(
            self._phrase(PLANTES, _Statuts({"1", "2"})),
            f"Parmi les 3 espèces de flore recensées sur Bédarieux, 2 figurent "
            f"sur la {REFERENCE} : Jonc épars et Salicaire commune.")

    def test_une_indicatrice(self):
        self.assertEqual(
            self._phrase(PLANTES, _Statuts({"2"})),
            f"Parmi les 3 espèces de flore recensées sur Bédarieux, 1 figure "
            f"sur la {REFERENCE} : Jonc épars.")

    def test_aucune_indicatrice(self):
        self.assertEqual(
            self._phrase(PLANTES, _Statuts(set())),
            f"Aucune des 3 espèces de flore recensées sur Bédarieux ne figure "
            f"sur la {REFERENCE}.")

    def test_une_seule_plante(self):
        self.assertEqual(
            self._phrase(PLANTES[1:2], _Statuts({"2"})),
            f"La seule espèce de flore recensée sur Bédarieux, Jonc épars, "
            f"figure sur la {REFERENCE}.")
        self.assertEqual(
            self._phrase(PLANTES[2:], _Statuts({"2"})),
            f"La seule espèce de flore recensée sur Bédarieux ne figure pas "
            f"sur la {REFERENCE}.")

    def test_sans_flore(self):
        # Ne rien dire laisserait croire qu'aucune plante n'est indicatrice.
        self.assertEqual(
            self._phrase([], _Statuts({"2"})),
            "La flore indicatrice de zones humides n'a pas été recherchée : "
            "aucune espèce de flore ne figure dans les sources déposées.")

    def test_sans_colonne(self):
        self.assertEqual(
            self._phrase(PLANTES, _Statuts({"2"}, colonne=False)),
            "La flore indicatrice de zones humides n'a pas été recherchée : "
            "aucun classeur de flore installé ne porte la colonne « ZH "
            "(Arrêté 2008) ».")


if __name__ == "__main__":
    unittest.main()
