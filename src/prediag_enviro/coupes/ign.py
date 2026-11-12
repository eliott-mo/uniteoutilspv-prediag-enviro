# -*- coding: utf-8 -*-
"""Le RGE ALTI et la BD TOPO de la Géoplateforme, pour les coupes.

Repris du client du générateur de DP (`generateur-dp/dp_socle/ign.py`) : même
session, mêmes reprises bornées sur les aléas du service, même refus de rendre
une liste tronquée ou un point sentinelle comme s'ils étaient vrais.

Deux écarts, mesurés le 12/11/2026 sur Bédarieux :

* **altimétrie en POST, corps JSON** : 5 000 points passent en une requête
  (4,2 s), là où le GET plafonne vers 200 points par la longueur d'URL.
  `zonly` doit être la chaîne "true" : le booléen est refusé en 400
  BAD_PARAMETER. Un corps form-encoded répond 500 — d'où le constat du
  générateur de DP, qui l'avait essayé sous cette forme.
* **filtre côté serveur** (`CQL_FILTER`) : seules les routes d'importance 1 à
  3 et la végétation affichée sont lues — 589 tronçons au lieu de 6 006.
"""
from __future__ import annotations

import hashlib
import http.cookiejar
import json
import ssl
import time
import warnings
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple, Sequence

import requests
from pyproj import Transformer
from requests.adapters import HTTPAdapter
from requests.utils import DEFAULT_CA_BUNDLE_PATH

from .reglages import CHAMP_GEOMETRIE

URL_WFS = "https://data.geopf.fr/wfs/ows"
URL_ALTIMETRIE = "https://data.geopf.fr/altimetrie/1.0/calcul/alti/rest/elevation.json"
RESSOURCE_ALTIMETRIE = "ign_rge_alti_wld"
ENTETES = {"User-Agent": "prediag-enviro (UNITe)"}

#: Points par requête altimétrique : une coupe de 10 km au pas de 5 m.
PAQUET_ALTITUDES = 2000

#: Tentatives d'une requête, attente entre deux, et codes qui valent d'être
#: rejoués : surcharge (429) et panne d'un nœud (5xx). Un 400 vient de la
#: requête elle-même et se reproduirait à l'identique.
TENTATIVES = 3
ATTENTE_REPRISE_S = 2.0
CODES_TRANSITOIRES = (429, 500, 502, 503, 504)

#: Version du format du cache : à changer si ce qu'on y range change.
FORMAT_CACHE = 1

_VERS_WGS84 = Transformer.from_crs(2154, 4326, always_xy=True)


class ErreurIGN(RuntimeError):
    """Le service ne rend pas ce qu'il faut : le message dit quoi faire."""


class Lecture(NamedTuple):
    """Les entités lues, et le jour où le service les a rendues."""
    entites: list
    date: date


# ──────────────────────────────────────────────────────────────── session

class _AdaptateurTLS(HTTPAdapter):
    """Un contexte TLS chargé une fois, comme dans le générateur de DP.

    requests confie à urllib3 le chemin des autorités de certifi, qu'il
    recharge à chaque connexion : de 0,3 à 4 s sur un poste Windows (mesuré
    le 24/09/2026). Certificat et nom d'hôte restent vérifiés.
    """

    def __init__(self):
        self._contexte = ssl.create_default_context(cafile=DEFAULT_CA_BUNDLE_PATH)
        super().__init__()

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = self._contexte
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, proxy, **proxy_kwargs):
        proxy_kwargs["ssl_context"] = self._contexte
        return super().proxy_manager_for(proxy, **proxy_kwargs)

    def cert_verify(self, conn, url, verify, cert):
        super().cert_verify(conn, url, verify, cert)
        conn.ca_certs = None
        conn.ca_cert_dir = None


@lru_cache(maxsize=1)
def _session() -> requests.Session:
    session = requests.Session()
    session.mount("https://", _AdaptateurTLS())
    session.cookies.set_policy(http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))
    return session


def _extrait(texte: str) -> str:
    """Le début d'une réponse, sur une ligne, pour un message lisible."""
    return " ".join(texte[:150].split())


def _demander(envoi, libelle: str, lire):
    """Ce que `lire` tire de la réponse HTTP 200, en rejouant les aléas.

    Une réponse 200 illisible en est un : le 12/11/2026, le WFS a rendu la page
    de métriques d'un serveur Java au lieu du GeoJSON des zones d'habitation de
    Bédarieux, et la même requête, rejouée, passait quatre fois sur quatre.
    `lire` lève `ValueError` sur une réponse qu'il ne sait pas lire.
    """
    for tentative in range(1, TENTATIVES + 1):
        rejouable = True
        try:
            reponse = envoi()
        except requests.RequestException as exc:
            echec = f"{libelle} : service de la Géoplateforme injoignable ({exc})."
        else:
            if reponse.status_code == 200:
                try:
                    return lire(reponse)
                except ValueError:
                    echec = (f"{libelle} : réponse illisible de la Géoplateforme "
                             f"(« {_extrait(reponse.text)} »).")
            else:
                rejouable = reponse.status_code in CODES_TRANSITOIRES
                echec = (f"{libelle} : réponse HTTP {reponse.status_code} de la "
                         f"Géoplateforme (« {_extrait(reponse.text)} »).")
        if not rejouable:
            raise ErreurIGN(f"{echec} La même requête donnerait la même réponse.")
        if tentative == TENTATIVES:
            raise ErreurIGN(
                f"{echec} Échec après {TENTATIVES} tentatives : les coupes n'ont "
                "pas été produites. Vérifier la connexion, puis réessayer dans "
                "quelques minutes.")
        warnings.warn(f"{echec} Nouvelle tentative dans {ATTENTE_REPRISE_S:.0f} s.",
                      RuntimeWarning, stacklevel=3)
        _session().close()
        time.sleep(ATTENTE_REPRISE_S)
    raise AssertionError("inatteignable")


# ──────────────────────────────────────────────────────────────── BD TOPO

def chemin_cache(cache: Path, couche: str, bbox, proprietes, filtre) -> Path:
    """Un fichier par couche, emprise, attributs et filtre."""
    cle = json.dumps([FORMAT_CACHE, couche, [round(v, 1) for v in bbox],
                      list(proprietes), filtre], ensure_ascii=False)
    empreinte = hashlib.sha1(cle.encode("utf-8")).hexdigest()[:12]
    return Path(cache) / f"{couche.split(':')[-1]}_{empreinte}.geojson"


def _lire_page(reponse) -> list:
    """Les entités d'une page GeoJSON ; `ValueError` si ce n'en est pas une."""
    donnees = reponse.json()
    if not isinstance(donnees, dict) or "features" not in donnees:
        raise ValueError("pas une collection GeoJSON")
    return donnees["features"] or []


def _lire_altitudes(reponse):
    donnees = reponse.json()
    if not isinstance(donnees, dict) or "elevations" not in donnees:
        raise ValueError("pas une réponse altimétrique")
    return donnees["elevations"]


def entites(couche: str, bbox, *, proprietes: Sequence[str] = (),
            filtre: str | None = None, cache: Path | None = None,
            taille_page: int = 1000, maximum: int = 50000,
            libelle: str = "") -> Lecture:
    """Les entités d'une couche du WFS qui coupent la bbox, en Lambert 93.

    Les pages se lisent jusqu'à la première incomplète. Une page pleine qui
    mènerait au plafond lève plutôt que de rendre une liste tronquée.
    """
    libelle = libelle or couche
    fichier = chemin_cache(cache, couche, bbox, proprietes, filtre) if cache else None
    if fichier is not None and fichier.exists():
        with open(fichier, encoding="utf-8") as f:
            lues = json.load(f)["features"]
        return Lecture(lues, date.fromtimestamp(fichier.stat().st_mtime))

    minx, miny, maxx, maxy = bbox
    if maxx <= minx or maxy <= miny:
        raise ErreurIGN(f"{libelle} : emprise de requête dégénérée {bbox}.")
    condition = (f"BBOX({CHAMP_GEOMETRIE},{minx:.3f},{miny:.3f},{maxx:.3f},"
                 f"{maxy:.3f},'EPSG:2154')")
    if filtre:
        condition += f" AND ({filtre})"

    lues: list = []
    index = 0
    while True:
        parametres = {
            "SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
            "TYPENAMES": couche, "OUTPUTFORMAT": "application/json",
            "SRSNAME": "EPSG:2154", "CQL_FILTER": condition,
            "COUNT": str(taille_page), "STARTINDEX": str(index),
        }
        if proprietes:
            parametres["PROPERTYNAME"] = ",".join([*proprietes, CHAMP_GEOMETRIE])
        page = _demander(
            lambda p=parametres: _session().get(URL_WFS, params=p, headers=ENTETES,
                                                timeout=120),
            f"BD TOPO ({libelle})", _lire_page)
        lues.extend(page)
        if len(page) < taille_page:
            break
        if index + taille_page >= maximum:
            raise ErreurIGN(
                f"BD TOPO ({libelle}) : plafond de {maximum} entités atteint, la "
                "dernière page lue étant pleine. Le service en porte peut-être "
                "davantage : une liste tronquée n'est pas rendue à la place.")
        index += taille_page

    if fichier is not None:
        fichier.parent.mkdir(parents=True, exist_ok=True)
        provisoire = fichier.with_suffix(".partiel")
        with open(provisoire, "w", encoding="utf-8") as f:
            json.dump({"type": "FeatureCollection", "features": lues}, f,
                      ensure_ascii=False)
        provisoire.replace(fichier)
    return Lecture(lues, date.today())


# ──────────────────────────────────────────────────────────────── RGE ALTI

def altitudes(points_l93: Sequence[tuple[float, float]], *,
              paquet: int = PAQUET_ALTITUDES) -> list[float]:
    """Altitudes NGF du RGE ALTI aux points donnés en Lambert 93, dans l'ordre.

    Une altitude manquante ou hors couverture lève : un point à zéro se
    dessinerait sans que personne ne le voie.
    """
    if not len(points_l93):
        raise ErreurIGN("Altimétrie : aucun point à interroger, le trait est vide.")
    resultat: list[float] = []
    for debut in range(0, len(points_l93), paquet):
        morceau = points_l93[debut:debut + paquet]
        lons, lats = _VERS_WGS84.transform([p[0] for p in morceau],
                                           [p[1] for p in morceau])
        corps = {"lon": "|".join(f"{v:.6f}" for v in lons),
                 "lat": "|".join(f"{v:.6f}" for v in lats),
                 "resource": RESSOURCE_ALTIMETRIE, "zonly": "true",
                 "delimiter": "|"}
        brutes = _demander(
            lambda c=corps: _session().post(URL_ALTIMETRIE, json=c, headers=ENTETES,
                                            timeout=120),
            "Altimétrie (RGE ALTI)", _lire_altitudes)
        if not isinstance(brutes, list) or len(brutes) != len(morceau):
            n = len(brutes) if isinstance(brutes, list) else 0
            raise ErreurIGN(f"Altimétrie : {n} altitude(s) rendue(s) pour "
                            f"{len(morceau)} points demandés.")
        for i, valeur in enumerate(brutes):
            if isinstance(valeur, dict):
                valeur = valeur.get("z")
            try:
                z = float(valeur)
            except (TypeError, ValueError) as exc:
                raise ErreurIGN(f"Altimétrie : valeur illisible au point "
                                f"{debut + i + 1} ({valeur!r}).") from exc
            if z < -1000.0:
                raise ErreurIGN(
                    f"Le RGE ALTI ne couvre pas le point {debut + i + 1} de la "
                    f"coupe (altitude {z:g}) : hors de France ou en mer.")
            resultat.append(z)
    return resultat
