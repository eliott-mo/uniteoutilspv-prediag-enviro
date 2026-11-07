# -*- coding: utf-8 -*-
"""La condensation des remarques ZNIEFF de BDC-Statuts, et les cases qu'elle donne.

Les remarques sont celles de BDC v18 : les vecteurs par zone et les remarques
coupées viennent de la liste d'Auvergne-Rhône-Alpes de 2020, les listes de
zones de celles des coléoptères saproxyliques et des bryophytes (2020).
"""
import unittest

from prediag_enviro import determinantes as d
from prediag_enviro.determinantes import condition

MC = "Continentale - Massif central"
PR = "Continentale - Plaine rhodanienne"
NIDIF = "Déterminante : - nicheur (si sites de reproduction)"
NON = "Non déterminante"
AURA = "Auvergne-Rhône-Alpes"


class Cas:
    """Un tableau de cas (nom, remarque, coupée, attendu), un sous-test chacun."""

    CAS: list = []

    def test_cas(self):
        for nom, brut, coupee, attendu in self.CAS:
            with self.subTest(nom):
                self.assertEqual(condition(brut, coupee=coupee), attendu)


class VecteurAura(Cas, unittest.TestCase):
    """« zone : état ; … » : les zones où l'espèce compte, regroupées par condition."""

    CAS = [
        ("rubrique seule",
         f"{MC} : {NIDIF};{PR} : {NON};Alpine : {NON};Méditerranéenne : {NON}",
         False, "Massif central : nicheur (si sites de reproduction)"),
        ("deux rubriques",
         f"{MC} : Déterminante : - nicheur (si sites de reproduction) - hivernant (si "
         f"régularité);{PR} : {NON};Alpine : {NON};Méditerranéenne : {NON}",
         False, "Massif central : nicheur (si sites de reproduction), hivernant (si régularité)"),
        ("zones regroupées",
         f"{MC} : Déterminante : - nicheur;{PR} : {NON};"
         "Alpine : Déterminante : - nicheur;Méditerranéenne : Déterminante : - hivernant",
         False, "Massif central, Alpin : nicheur ; Méditerranéen : hivernant"),
        ("même condition partout",
         f"{MC} : Déterminante (seulement les gîtes);{PR} : Déterminante (seulement les "
         "gîtes);Alpine : Déterminante (seulement les gîtes);Méditerranéenne : Déterminante "
         "(seulement les gîtes)",
         False, "seulement les gîtes"),
        ("sans réserve et avec",
         f"{MC} : Déterminante;Alpine : Déterminante : - nicheur",
         False, "Massif central ; Alpin : nicheur"),
        ("si … sans deux-points",
         f"{MC} : Déterminante si population naturelle;{PR} : {NON}",
         False, "Massif central : si population naturelle"),
        ("partout sans réserve",
         f"{MC} : Déterminante;{PR} : Déterminante;Alpine : Déterminante;"
         "Méditerranéenne : Déterminante",
         False, ""),
        ("nulle part",
         f"{MC} : {NON};{PR} : {NON};Alpine : {NON};Méditerranéenne : {NON}",
         False, None),
        ("zones sans réserve",
         f"{MC} : Déterminante;{PR} : {NON};Alpine : Déterminante;Méditerranéenne : {NON}",
         False, "Massif central, Alpin"),
    ]


class RemarqueCoupee(Cas, unittest.TestCase):
    """BDC coupe certaines remarques à 255 caractères : « … » marque la coupure."""

    CAS = [
        ("dans le nom d'une zone (Milan royal)",
         f"{MC} : Déterminante : - nicheur (si sites de reproduction) - hivernant (si "
         f"dortoir et régularité);{PR} : Déterminante : - nicheur (si sites de "
         "reproduction) - hivernant (si dortoir et régularité);Alpin",
         True, "Massif central, Plaine rhodanienne : nicheur (si sites de reproduction), "
               "hivernant (si dortoir et régularité) ; …"),
        ("dans l'état",
         f"{MC} : {NIDIF};{PR} : {NIDIF};Alpine : {NIDIF};Méditerranéenne : Déte",
         True, "Massif central, Plaine rhodanienne, Alpin : nicheur (si sites de "
               "reproduction) ; Méditerranéen : …"),
        ("dans la condition",
         f"{MC} : Déterminante : - hivernant;{PR} : Déterminante : - nicheur (si sites "
         "de reproduction) - hivernant (si dortoir, régularité et effectif minimum de 5);"
         "Alpine : Déterminante : - hivernant (si dortoi",
         True, "Massif central : hivernant ; Plaine rhodanienne : nicheur (si sites de "
               "reproduction), hivernant (si dortoir, régularité et effectif minimum de "
               "5) ; Alpin : hivernant (si dortoi…)"),
        ("entre parenthèses",
         f"{MC} : Déterminante (en ZNIEFF de type 2 seulement);Méditerranéenne : "
         "Déterminante (en ZNIEFF d",
         True, "Massif central : en ZNIEFF de type 2 seulement ; Méditerranéen : en ZNIEFF d…"),
        ("texte libre",
         "Espèces protégées (i) de sites de reproduction dans l'habitats hum", True,
         "Espèces protégées (i) de sites de reproduction dans l'habitats hum…"),
        ("texte libre, dans une parenthèse",
         "Populations remarquables (au moins 50 individus avec un site d'activités de "
         "rayon = 10", True,
         "Populations remarquables (au moins 50 individus avec un site d'activités de "
         "rayon = 10…)"),
    ]


class Coupure(unittest.TestCase):
    """La coupure se reconnaît à la longueur de la remarque brute."""

    def test_longueurs(self):
        for nom, brut, attendu in [
            ("255 caractères", "x" * 255, True),
            ("254, parenthèses fermées", "a (b) " + "x" * 248, False),
            ("254, parenthèse restée ouverte", "x" * 250 + " (si", True),
            ("200, parenthèse ouverte : coquille de la source", "x" * 196 + " (si", False),
            ("256 caractères", "x" * 256, False),
        ]:
            with self.subTest(nom):
                self.assertEqual(len(brut), int(nom[:3]))
                self.assertEqual(d._coupee(brut), attendu)


class ListeDeZones(Cas, unittest.TestCase):
    """Les listes de 2020 des coléoptères et des bryophytes ne nomment que des zones."""

    CAS = [
        ("une zone", "Continentale - Massif Central", False, "Massif central"),
        ("tiret long", "Continentale – Plaine rhodanienne", False, "Plaine rhodanienne"),
        ("alpine", "Alpine", False, "Alpin"),
        ("méditerranéenne", "Méditerranéenne", False, "Méditerranéen"),
        ("deux zones", "Continentale - Massif Central,Méditerranéenne", False,
         "Massif central, Méditerranéen"),
        ("virgule finale", "Continentale - Massif Central,Alpine,", False,
         "Massif central, Alpin"),
        ("les quatre zones",
         "Continentale - Massif Central,Continentale – Plaine rhodanienne,Alpine,"
         "Méditerranéenne", False, ""),
        # Ce qui n'est pas une liste de zones reste tel quel.
        ("hors zone (Nouvelle-Aquitaine)", "Hors Massif central", False,
         "Hors Massif central"),
        ("zone et texte", "Massif central, sauf la partie caussenarde", False,
         "Massif central, sauf la partie caussenarde"),
        ("texte libre", "Uniquement les colonies", False, "Uniquement les colonies"),
    ]


class DomainesOccitanie(Cas, unittest.TestCase):
    """Les domaines d'Occitanie, dans la notation du classeur des mammifères."""

    CAS = [
        ("deux domaines", "Déterminant Massif Central - Déterminant Zone Méditerranéenne",
         False, "MC, MED"),
        ("ordre alphabétique", "Déterminant Zone Sud-Ouest - Déterminant Massif Central",
         False, "MC, SO"),
        # L'avis du CSRPN d'Occitanie de 2023 écrit le mot sans accent.
        ("sans accent", "Determinant Zone Méditerranéenne", False, "MED"),
    ]


def _cellule(*remarques, regionale=False):
    """La case d'une espèce que ces remarques déclarent, dans l'Allier et le Cantal."""
    listes = d.Listes()
    mention = listes._mention("1", AURA)
    reserves = {condition(r) for r in remarques}
    if regionale:
        mention.regionale |= reserves
    else:
        listes.departements[AURA] = {"03", "15"}
        for dep in ("03", "15"):
            mention.departements.setdefault(dep, set()).update(reserves)
    return listes.cellule("1", AURA)


VECTEUR_MC = f"{MC} : Déterminante;{PR} : {NON};Alpine : {NON};Méditerranéenne : {NON}"


class Cellule(unittest.TestCase):
    """Deux listes d'un même territoire : leurs zones se réunissent."""

    def test_meme_zone(self):
        # Limoniscus violaceus, écrit « Oui (Continentale - Massif Central ;
        # Massif central) » le 1er novembre 2026.
        self.assertEqual(_cellule("Continentale - Massif Central", VECTEUR_MC),
                         "Oui (Massif central)")

    def test_zones_reunies(self):
        # Lucanus cervus : « Oui (Massif central ; Méditerranéenne) ».
        self.assertEqual(_cellule("Méditerranéenne", VECTEUR_MC),
                         "Oui (Massif central, Méditerranéen)")

    def test_zones_reunies_regionales(self):
        self.assertEqual(_cellule("Méditerranéenne", VECTEUR_MC, regionale=True),
                         "Oui (Massif central, Méditerranéen)")

    def test_quatre_zones_sans_reserve(self):
        # Rosalia alpina : les quatre zones d'une liste valent le territoire entier.
        quatre = ("Continentale - Massif Central,Continentale – Plaine rhodanienne,"
                  "Alpine,Méditerranéenne")
        self.assertEqual(_cellule(quatre, VECTEUR_MC), "Oui")

    def test_zones_reunies_en_quatre(self):
        self.assertEqual(_cellule("Continentale - Massif Central,Alpine",
                                  "Continentale – Plaine rhodanienne,Méditerranéenne"),
                         "Oui")

    def test_condition_laissee_a_cote(self):
        avec_condition = (f"{MC} : Déterminante : - nicheur;{PR} : {NON};"
                          f"Alpine : Déterminante : - nicheur;Méditerranéenne : {NON}")
        self.assertEqual(_cellule("Méditerranéenne", avec_condition),
                         "Oui (Massif central, Alpin : nicheur ; Méditerranéen)")

    def test_autres_notations_laissees(self):
        listes = d.Listes()
        mention = listes._mention("1", "Occitanie")
        mention.regionale |= {"MC, SO", "MED"}
        self.assertEqual(listes.cellule("1", "Occitanie"), "Oui (MC, SO ; MED)")


if __name__ == "__main__":
    unittest.main()
