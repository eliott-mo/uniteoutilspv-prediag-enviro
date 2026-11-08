# -*- coding: utf-8 -*-
"""Une sous-espèce qu'aucun classeur ne porte se lit comme son espèce.

À Bédarieux, l'Effraie des clochers relevée en *Tyto alba delicatula*
sortait sans protection : le classeur des oiseaux porte *Tyto alba*, protégée
(Art. 3), et BDC ne dit rien de la sous-espèce.
"""
import unittest
from pathlib import Path

from prediag_enviro import bdc, reference
from prediag_enviro.classeurs import Classeur, ColonneStatut, LigneTaxon
from prediag_enviro.taxref import Index, Taxon

FRANCE = "France métropolitaine"
PN = ColonneStatut(index=7, champ="PN", type_bdc="PN", territoire="France",
                   territoire_bdc=FRANCE)


def _index() -> Index:
    taxons = {
        "190481": Taxon("190481", "190481", "Cerambyx", "Cerambyx", "GN",
                        "Insectes"),
        "12336": Taxon("12336", "12336", "Cerambyx cerdo", "Cerambyx cerdo",
                       "ES", "Insectes", cd_sup="190481"),
        "251483": Taxon("251483", "251483", "Cerambyx cerdo cerdo",
                        "Cerambyx cerdo cerdo", "SSES", "Insectes",
                        cd_sup="12336"),
    }
    return Index(taxons, {}, {}, {}, "18")


def _classeur(*lignes) -> Classeur:
    return Classeur(groupe="insectes", chemin=Path("B-Statuts insectes.xlsx"),
                    taxons=list(lignes), colonnes=[PN])


ESPECE = LigneTaxon(ligne=2, cd_nom="12336", nom_scientifique="Cerambyx cerdo",
                    nom_commun="Grand Capricorne", valeurs={7: "Art. 2"})


class _Bdc:
    """Ce que BDC-Statuts dirait, par taxon et par type."""

    def __init__(self, valeurs):
        self.valeurs = valeurs

    def couvre(self, type_statut, territoire):
        return True

    def entrees(self, cd_ref, type_statut, territoire):
        rendu = self.valeurs.get((cd_ref, type_statut))
        return [bdc.Entree(code=rendu, rendu=rendu, periode="")] if rendu else []

    def rendu(self, cd_ref, type_statut, territoire, periode=None, filtre=None):
        return ", ".join(e.rendu for e in self.entrees(cd_ref, type_statut,
                                                       territoire))


class SousEspece(unittest.TestCase):

    def test_lue_a_l_espece(self):
        ref = reference.Reference({"insectes": _classeur(ESPECE)},
                                  index=_index())
        self.assertTrue(ref.connait("251483"))
        self.assertEqual(ref.lu_comme("251483"), "12336")
        self.assertEqual(ref.rendu("251483", "PN", FRANCE), "Art. 2")
        self.assertEqual(ref.groupe_classeur("251483"), "insectes")

    def test_sans_index_rien_ne_change(self):
        ref = reference.Reference({"insectes": _classeur(ESPECE)})
        self.assertFalse(ref.connait("251483"))
        self.assertEqual(ref.lu_comme("251483"), "251483")
        self.assertEqual(ref.rendu("251483", "PN", FRANCE), "")

    def test_sous_espece_portee_garde_sa_ligne(self):
        propre = LigneTaxon(ligne=3, cd_nom="251483",
                            nom_scientifique="Cerambyx cerdo cerdo",
                            nom_commun="", valeurs={7: "Art. 3"})
        ref = reference.Reference({"insectes": _classeur(ESPECE, propre)},
                                  index=_index())
        self.assertEqual(ref.lu_comme("251483"), "251483")
        self.assertEqual(ref.rendu("251483", "PN", FRANCE), "Art. 3")

    def test_espece_absente_des_classeurs(self):
        ref = reference.Reference({"insectes": _classeur()}, index=_index())
        self.assertFalse(ref.connait("251483"))
        self.assertEqual(ref.lu_comme("251483"), "251483")


class RepliBdc(unittest.TestCase):
    """Le classeur des insectes n'a pas de colonne de directive : BDC répond."""

    def _repli(self, valeurs):
        ref = reference.Reference({"insectes": _classeur(ESPECE)},
                                  index=_index())
        return reference.AvecRepli(ref, _Bdc(valeurs))

    def test_classeur_d_abord(self):
        statuts = self._repli({("251483", "PN"): "Art. 9"})
        self.assertEqual(statuts.rendu("251483", "PN", FRANCE), "Art. 2")

    def test_espece_quand_bdc_ignore_la_sous_espece(self):
        statuts = self._repli({("12336", "DH"): "Annexe II"})
        self.assertEqual(statuts.rendu("251483", "DH", FRANCE), "Annexe II")
        self.assertEqual([e.rendu for e in statuts.entrees("251483", "DH",
                                                          FRANCE)],
                         ["Annexe II"])

    def test_sous_espece_quand_bdc_la_connait(self):
        statuts = self._repli({("12336", "DH"): "Annexe II",
                               ("251483", "DH"): "Annexe IV"})
        self.assertEqual(statuts.rendu("251483", "DH", FRANCE), "Annexe IV")


if __name__ == "__main__":
    unittest.main()
