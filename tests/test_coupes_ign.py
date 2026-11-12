# -*- coding: utf-8 -*-
"""Le client IGN des coupes, sur des réponses enregistrées : aucun appel réseau.

Ce qu'on vérifie est ce qui a déjà coûté ailleurs : une liste tronquée rendue
comme complète, un aléa du service qui fait tout perdre, une altitude
sentinelle dessinée comme un vrai point, un message d'erreur qui ne dit pas
quoi faire.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

from prediag_enviro.coupes import ign

BBOX = (0.0, 0.0, 10.0, 10.0)


class _Reponse:
    def __init__(self, statut=200, donnees=None, texte=None):
        self.status_code = statut
        self._donnees = donnees
        self.text = texte if texte is not None else json.dumps(donnees)

    def json(self):
        if self._donnees is None:
            raise ValueError("pas du JSON")
        return self._donnees


def _page(n, depart=0):
    return _Reponse(donnees={"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"n": depart + i},
         "geometry": {"type": "Point", "coordinates": [1.0, 2.0]}}
        for i in range(n)]})


class _Session:
    """Rejoue des réponses dans l'ordre, et note ce qu'on lui demande."""

    def __init__(self, reponses):
        self.reponses = list(reponses)
        self.demandes = []

    def _suivante(self, demande):
        self.demandes.append(demande)
        reponse = self.reponses.pop(0)
        if isinstance(reponse, Exception):
            raise reponse
        return reponse

    def get(self, url, params=None, headers=None, timeout=None):
        return self._suivante(("GET", url, dict(params or {})))

    def post(self, url, json=None, headers=None, timeout=None):
        return self._suivante(("POST", url, json))

    def close(self):
        pass


class _AvecSession(unittest.TestCase):

    def rejouer(self, reponses):
        self.session = _Session(reponses)
        rustines = [mock.patch.object(ign, "_session", lambda: self.session),
                    mock.patch.object(ign.time, "sleep", lambda s: None)]
        for r in rustines:
            r.start()
            self.addCleanup(r.stop)
        return self.session


class Wfs(_AvecSession):

    def test_pagination_jusqu_a_la_page_incomplete(self):
        session = self.rejouer([_page(2), _page(2, 2), _page(1, 4)])
        lecture = ign.entites("BDTOPO_V3:troncon_de_route", BBOX,
                              proprietes=("importance",),
                              filtre="importance IN ('1')", taille_page=2)
        self.assertEqual([e["properties"]["n"] for e in lecture.entites],
                         [0, 1, 2, 3, 4])
        self.assertEqual([d[2]["STARTINDEX"] for d in session.demandes],
                         ["0", "2", "4"])
        parametres = session.demandes[0][2]
        self.assertEqual(
            parametres["CQL_FILTER"],
            "BBOX(geometrie,0.000,0.000,10.000,10.000,'EPSG:2154') "
            "AND (importance IN ('1'))")
        self.assertNotIn("BBOX", parametres)
        self.assertEqual(parametres["PROPERTYNAME"], "importance,geometrie")

    def test_plafond_plutot_qu_une_liste_tronquee(self):
        self.rejouer([_page(2), _page(2, 2)])
        with self.assertRaisesRegex(ign.ErreurIGN, "plafond"):
            ign.entites("BDTOPO_V3:commune", BBOX, taille_page=2, maximum=4)

    def test_reprise_apres_un_alea(self):
        session = self.rejouer([_Reponse(503, texte="indisponible"), _page(1)])
        with self.assertWarns(RuntimeWarning):
            lecture = ign.entites("BDTOPO_V3:commune", BBOX)
        self.assertEqual(len(lecture.entites), 1)
        self.assertEqual(len(session.demandes), 2)

    def test_reponse_illisible_rejouee(self):
        # Constaté le 12/11/2026 sur les zones d'habitation de Bédarieux : un
        # HTTP 200 portant la page de métriques d'un serveur Java au lieu du
        # GeoJSON. La même requête, rejouée, passait quatre fois sur quatre.
        metriques = _Reponse(texte="# HELP jmx_exporter_build_info A metric")
        session = self.rejouer([metriques, _page(2)])
        with self.assertWarns(RuntimeWarning):
            lecture = ign.entites("BDTOPO_V3:zone_d_habitation", BBOX)
        self.assertEqual(len(lecture.entites), 2)
        self.assertEqual(len(session.demandes), 2)

    def test_reponse_illisible_persistante(self):
        metriques = _Reponse(texte="# HELP jmx_exporter_build_info " + "x" * 2000)
        self.rejouer([metriques] * ign.TENTATIVES)
        with self.assertWarns(RuntimeWarning), \
                self.assertRaises(ign.ErreurIGN) as contexte:
            ign.entites("BDTOPO_V3:zone_d_habitation", BBOX,
                        libelle="zones d'habitation")
        message = str(contexte.exception)
        self.assertIn("illisible", message)
        self.assertLess(len(message), 500)

    def test_altitudes_illisibles_rejouees(self):
        session = self.rejouer([_Reponse(texte="<html>passerelle</html>"),
                                _Reponse(donnees={"elevations": [250.0]})])
        with self.assertWarns(RuntimeWarning):
            self.assertEqual(ign.altitudes([(700000.0, 6600000.0)]), [250.0])
        self.assertEqual(len(session.demandes), 2)

    def test_requete_refusee_sans_reprise(self):
        session = self.rejouer([_Reponse(400, texte="mauvais filtre")])
        with self.assertRaisesRegex(ign.ErreurIGN, "HTTP 400"):
            ign.entites("BDTOPO_V3:commune", BBOX, libelle="communes")
        self.assertEqual(len(session.demandes), 1)

    def test_service_injoignable_message_clair(self):
        panne = requests.ConnectionError("hors ligne")
        session = self.rejouer([panne, panne, panne])
        with self.assertWarns(RuntimeWarning), \
                self.assertRaises(ign.ErreurIGN) as contexte:
            ign.entites("BDTOPO_V3:commune", BBOX, libelle="communes")
        message = str(contexte.exception)
        self.assertIn("communes", message)
        self.assertIn("injoignable", message)
        self.assertIn("réessayer", message)
        self.assertEqual(len(session.demandes), ign.TENTATIVES)

    def test_cache_relu_sans_reseau(self):
        with tempfile.TemporaryDirectory() as dossier:
            self.rejouer([_page(3)])
            premiere = ign.entites("BDTOPO_V3:commune", BBOX, cache=Path(dossier))
            session = self.rejouer([])
            seconde = ign.entites("BDTOPO_V3:commune", BBOX, cache=Path(dossier))
            self.assertEqual(seconde.entites, premiere.entites)
            self.assertEqual(session.demandes, [])
            # Une autre emprise ne relit pas ce cache.
            self.rejouer([_page(1)])
            autre = ign.entites("BDTOPO_V3:commune", (0, 0, 20, 20),
                                cache=Path(dossier))
            self.assertEqual(len(autre.entites), 1)


class Altitudes(_AvecSession):

    def test_paquets_en_post_json(self):
        points = [(700000.0 + i, 6600000.0) for i in range(4500)]
        session = self.rejouer([
            _Reponse(donnees={"elevations": [100.0] * 2000}),
            _Reponse(donnees={"elevations": [200.0] * 2000}),
            _Reponse(donnees={"elevations": [300.0] * 500}),
        ])
        z = ign.altitudes(points, paquet=2000)
        self.assertEqual(len(z), 4500)
        self.assertEqual((z[0], z[2000], z[-1]), (100.0, 200.0, 300.0))
        methodes = {d[0] for d in session.demandes}
        self.assertEqual(methodes, {"POST"})
        corps = session.demandes[0][2]
        # Les deux pièges du brief : corps JSON, et zonly en chaîne.
        self.assertEqual(corps["zonly"], "true")
        self.assertEqual(corps["delimiter"], "|")
        self.assertEqual(corps["resource"], "ign_rge_alti_wld")
        self.assertEqual(len(corps["lon"].split("|")), 2000)
        self.assertEqual(len(session.demandes[2][2]["lat"].split("|")), 500)

    def test_valeur_sentinelle_refusee(self):
        self.rejouer([_Reponse(donnees={"elevations": [250.0, -99999.0]})])
        with self.assertRaisesRegex(ign.ErreurIGN, "ne couvre pas"):
            ign.altitudes([(700000.0, 6600000.0), (700005.0, 6600000.0)])

    def test_nombre_d_altitudes_controle(self):
        self.rejouer([_Reponse(donnees={"elevations": [250.0]})])
        with self.assertRaisesRegex(ign.ErreurIGN, "1 altitude"):
            ign.altitudes([(700000.0, 6600000.0), (700005.0, 6600000.0)])


if __name__ == "__main__":
    unittest.main()
