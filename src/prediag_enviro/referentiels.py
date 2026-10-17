"""Récupération et épinglage des référentiels INPN (TaxRef, BDC-Statuts).

Principe : on ne tape jamais un service en direct pendant une étude. On
télécharge une fois, on fige, et chaque sortie porte la version utilisée.
Trois raisons :

1. La Licence Ouverte (Etalab) impose de citer la source **et sa date**.
2. Deux prédiags faits à six mois d'écart doivent être comparables.
3. Le site de l'INPN est en reconstruction : les appels directs tombent.

Le téléchargement reprend là où il s'est arrêté (`Range`) — l'archive TaxRef
fait 58 Mo et la connexion coupe régulièrement.
"""
from __future__ import annotations

import json
import time
import urllib.parse
from dataclasses import dataclass, asdict
from datetime import date
from pathlib import Path

import requests

_UA = {"User-Agent": "Mozilla/5.0 (prediag-enviro ; UNITe)"}
_TENTATIVES = 8

#: Nom lisible de chaque référentiel, pour tout ce qui s'affiche.
NOMS_AFFICHES = {
    "taxref": "TaxRef",
    "bdc_statuts": "BDC-Statuts",
    "znieff": "ZNIEFF",
    "natura2000": "Natura 2000",
    "espaces_proteges": "Espaces protégés",
    "patrimoine_geologique": "Inventaire du patrimoine géologique",
    "ens": "Espaces naturels sensibles (flux WFS de l'INPN)",
    "zico": "Zones importantes pour la conservation des oiseaux (flux WFS)",
    "mc_polygones": "Mesures compensatoires — emprises surfaciques (CEREMA)",
    "mc_lineaires": "Mesures compensatoires — emprises linéaires (CEREMA)",
    "mc_ponctuelles": "Mesures compensatoires — emprises ponctuelles (CEREMA)",
}


@dataclass
class Referentiel:
    cle: str                 # "taxref" | "bdc_statuts"
    version: str             # "18"
    chemin: Path             # archive locale
    recupere_le: str         # ISO date
    url: str
    #: Producteur de ce référentiel-ci, quand ce n'est pas celui que
    #: `sources.yml` déclare pour l'ensemble. Les mesures compensatoires
    #: viennent du Cerema et non du Muséum : les citer sous l'attribution
    #: globale était une faute de licence autant qu'une erreur de fait.
    attribution: str = ""

    def citation(self, attribution: str) -> str:
        """Mention de paternité exigée par la Licence Ouverte.

        L'attribution propre au référentiel l'emporte sur celle du fichier de
        configuration, qui ne vaut que par défaut.
        """
        nom = NOMS_AFFICHES.get(self.cle, self.cle)
        attribution = self.attribution or attribution
        # Un flux ne publie pas de version : sa date de récupération en tient
        # lieu, et c'est elle que la Licence Ouverte exige de citer. Écrire
        # « v » suivi de rien ferait croire à une version perdue.
        millesime = f" v{self.version}" if self.version else ""
        return (f"{nom}{millesime} — {attribution}, "
                f"récupéré le {self.recupere_le}")


def _taille_distante(url: str) -> int | None:
    try:
        r = requests.head(url, headers=_UA, timeout=30, allow_redirects=True)
        n = r.headers.get("content-length")
        return int(n) if n else None
    except Exception:  # noqa: BLE001
        return None


def telecharger(url: str, dest: Path, attendu: int | None = None,
                progression=None) -> Path:
    """Télécharge avec reprise. Renvoie le chemin une fois l'archive complète.

    Les archives de zonages pèsent jusqu'à 220 Mo, souvent récupérées depuis un
    partage de connexion : la coupure n'est pas l'exception, c'est le régime
    normal. La reprise repart donc de l'octet reçu (`Range`) et l'attente
    double à chaque échec, jusqu'à une minute — une coupure DNS de trente
    secondes faisait auparavant tomber les huit tentatives en seize.

    Une tentative qui a fait progresser le fichier ne compte pas comme un
    échec : seule l'absence de progrès épuise le compteur, sans quoi un gros
    téléchargement haché en dix tronçons échouerait alors qu'il avance.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if attendu is None:
        attendu = _taille_distante(url)

    echecs_sans_progres = 0
    while echecs_sans_progres < _TENTATIVES:
        present = dest.stat().st_size if dest.exists() else 0
        if attendu and present >= attendu:
            return dest
        entetes = dict(_UA)
        if present:
            entetes["Range"] = f"bytes={present}-"
        try:
            r = requests.get(url, headers=entetes, timeout=180, stream=True)
            r.raise_for_status()
            mode = "ab" if present and r.status_code == 206 else "wb"
            with open(dest, mode) as f:
                for bloc in r.iter_content(1 << 19):
                    f.write(bloc)
                    if progression is not None and attendu:
                        progression(f.tell() if mode == "wb" else present + f.tell(),
                                    attendu)
        except Exception as e:  # noqa: BLE001
            obtenu = dest.stat().st_size if dest.exists() else 0
            if obtenu > present:
                echecs_sans_progres = 0      # ça a avancé : on ne pénalise pas
            else:
                echecs_sans_progres += 1
            if echecs_sans_progres >= _TENTATIVES:
                raise RuntimeError(
                    f"Téléchargement de {url} interrompu après {_TENTATIVES} "
                    f"tentatives sans progrès ({obtenu} octets reçus sur "
                    f"{attendu or '?'}) : {e}"
                ) from e
            time.sleep(min(2 ** echecs_sans_progres, 60))
        else:
            # Sans taille annoncée, la complétude ne se vérifie pas : une
            # requête menée à son terme sans erreur fait foi. C'est le cas
            # d'un flux WFS, qui calcule sa réponse et n'en connaît pas la
            # longueur d'avance. Faute de cette sortie, la boucle se rejouait
            # indéfiniment — sa condition de retour porte sur une taille
            # qu'on n'a pas.
            if not attendu:
                return dest

    if attendu and dest.stat().st_size < attendu:
        raise RuntimeError(
            f"{dest.name} incomplet : {dest.stat().st_size} octets reçus sur {attendu}"
        )
    return dest


#: Nom de la couche écrite dans le GeoPackage d'un flux paginé.
COUCHE_PAGINEE = "objets"


def telecharger_wfs_pagine(url: str, dest: Path, pas: int = 5000) -> Path:
    """Récupère un flux WFS que le serveur sert par tranches.

    **La Géoplateforme plafonne une requête WFS à 5 000 objets, sans le
    dire.** Les 8 086 emprises surfaciques des mesures compensatoires
    arrivaient donc tronquées à 5 000, et rien dans la réponse ne le
    signalait : même code HTTP, même archive bien formée, 3 086 objets en
    moins. Demander `COUNT=20000` n'y change rien — la charge utile revient
    identique à l'octet près, le plafond est côté serveur.

    On pagine donc avec `STARTINDEX`, et **on confronte le total obtenu au
    `numberMatched` que le flux annonce lui-même**. Un écart lève plutôt que
    de livrer une couche incomplète : un référentiel manquant se voit, un
    référentiel amputé se cite comme s'il était entier.

    Le résultat est écrit en GeoPackage dans un zip, pour entrer dans la même
    mécanique d'archive que les autres référentiels.
    """
    import zipfile

    import geopandas as gpd
    import pandas as pd

    morceaux: list = []
    annonce: int | None = None
    depart = 0
    while True:
        parts = urllib.parse.urlsplit(url)
        params = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
        params.update({"COUNT": str(pas), "STARTINDEX": str(depart)})
        page = urllib.parse.urlunsplit(
            parts._replace(query=urllib.parse.urlencode(params)))
        reponse = requests.get(page, headers=_UA, timeout=300)
        reponse.raise_for_status()
        charge = json.loads(reponse.content)
        if annonce is None:
            annonce = charge.get("numberMatched")
        objets = charge.get("features") or []
        if not objets:
            break
        morceaux.append(gpd.GeoDataFrame.from_features(
            objets, crs=_crs_geojson(charge)))
        depart += len(objets)
        if len(objets) < pas:
            break

    if not morceaux:
        raise ValueError(f"{url} : flux vide")
    tout = gpd.GeoDataFrame(pd.concat(morceaux, ignore_index=True),
                            crs=morceaux[0].crs)
    if annonce is not None and len(tout) != annonce:
        raise ValueError(
            f"{dest.name} : {len(tout)} objets récupérés pour {annonce} "
            f"annoncés par le flux — couche incomplète, rien n'est installé"
        )

    dest.parent.mkdir(parents=True, exist_ok=True)
    interne = dest.with_suffix(".gpkg")
    tout.to_file(interne, driver="GPKG", layer=COUCHE_PAGINEE)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(interne, interne.name)
    interne.unlink()
    return dest


def _crs_geojson(charge: dict) -> str:
    """Le CRS annoncé par le flux, ou WGS 84 comme le veut la norme GeoJSON."""
    nom = (((charge.get("crs") or {}).get("properties") or {}).get("name") or "")
    for bout in str(nom).replace("::", ":").split(":"):
        if bout.isdigit():
            return f"EPSG:{bout}"
    return "EPSG:4326"


def _manifeste_path(dossier: Path) -> Path:
    return dossier / "manifeste.json"


def lire_manifeste(dossier: Path) -> dict[str, Referentiel]:
    p = _manifeste_path(dossier)
    if not p.exists():
        return {}
    brut = json.loads(p.read_text(encoding="utf-8"))
    return {
        k: Referentiel(cle=k, version=v["version"], chemin=Path(v["chemin"]),
                       recupere_le=v["recupere_le"], url=v["url"],
                       attribution=v.get("attribution", ""))
        for k, v in brut.items()
    }


def _ecrire_manifeste(dossier: Path, refs: dict[str, Referentiel]) -> None:
    serial = {
        k: {**asdict(r), "chemin": str(r.chemin)} for k, r in refs.items()
    }
    for v in serial.values():
        v.pop("cle", None)
    _manifeste_path(dossier).write_text(
        json.dumps(serial, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def assurer(cfg: dict, dossier: Path, forcer: bool = False,
            cles: tuple[str, ...] | None = None) -> dict[str, Referentiel]:
    """Garantit la présence locale des référentiels déclarés dans sources.yml.

    Ne retélécharge pas ce qui est déjà là. `forcer=True` **supprime d'abord**
    l'archive locale : sans ça la reprise voyait un fichier complet et rendait
    la main sans rien faire, tout en réécrivant la date de récupération — une
    date fausse citée ensuite dans chaque rapport, alors que la licence impose
    de citer la source *et sa date*.

    Ce forçage ne sert qu'à remplacer une archive corrompue. Il ne peut pas
    apporter une version plus récente : l'URL est épinglée dans `sources.yml`.
    Pour cela, voir `versions_publiees()`.
    """
    dossier.mkdir(parents=True, exist_ok=True)
    deja = lire_manifeste(dossier)
    refs: dict[str, Referentiel] = dict(deja) if cles else {}

    for cle, spec in cfg["referentiels"].items():
        # `cles` restreint le périmètre : la veille n'a que faire des 460 Mo
        # de zonages, et le prédiag n'a pas à les attendre tant qu'on reste
        # dans l'onglet des tables.
        if cles is not None and cle not in cles:
            continue
        dest = dossier / spec["fichier"]
        connu = deja.get(cle)
        if forcer and dest.exists():
            dest.unlink()
        a_jour = (
            connu is not None
            and connu.version == spec["version"]
            and dest.exists()
        )
        if a_jour:
            refs[cle] = Referentiel(cle=cle, version=spec["version"], chemin=dest,
                                    recupere_le=connu.recupere_le, url=spec["url"],
                                    attribution=spec.get("attribution", ""))
            continue

        # Le fichier peut être là sans figurer au manifeste — première
        # utilisation d'un référentiel récupéré par ailleurs. Annoncer un
        # téléchargement qui n'aura pas lieu est le même mensonge que celui du
        # bouton « Rafraîchir » : on vérifie avant de parler.
        if spec.get("pagine"):
            # Flux servi par tranches : ni taille annoncée, ni reprise
            # possible — on refait la pagination entière.
            print(f"  téléchargement {cle} (flux paginé) …", flush=True)
            telecharger_wfs_pagine(spec["url"], dest, int(spec["pagine"]))
            print(f"    {dest.name} — {dest.stat().st_size / 1048576:.1f} Mo")
            refs[cle] = Referentiel(cle=cle, version=spec["version"], chemin=dest,
                                    recupere_le=date.today().isoformat(),
                                    url=spec["url"],
                                    attribution=spec.get("attribution", ""))
            continue

        attendu = _taille_distante(spec["url"])
        deja_complet = dest.exists() and attendu and dest.stat().st_size >= attendu
        if not deja_complet:
            # Un flux n'a pas de version : « téléchargement ens v … » se lit
            # comme une version perdue.
            millesime = f" v{spec['version']}" if spec.get("version") else ""
            print(f"  téléchargement {cle}{millesime} …", flush=True)
        telecharger(spec["url"], dest, attendu=attendu)
        taille = dest.stat().st_size / 1048576
        if not deja_complet:
            print(f"    {dest.name} — {taille:.1f} Mo")
        refs[cle] = Referentiel(cle=cle, version=spec["version"], chemin=dest,
                                recupere_le=date.today().isoformat(), url=spec["url"],
                                attribution=spec.get("attribution", ""))

    _ecrire_manifeste(dossier, refs)
    return refs


#: Libellé de chaque référentiel sur la page de l'INPN, pour y lire sa version.
_LIBELLE_INPN = {"taxref": "TaxRef", "bdc_statuts": "BDC Statuts"}


def versions_publiees(cfg: dict, timeout: int = 30) -> dict[str, str]:
    """Versions actuellement publiées par l'INPN, lues sur sa page de diffusion.

    L'épinglage protège la reproductibilité, mais il faut bien savoir un jour
    qu'une version est sortie. La page liste chaque référentiel suivi de sa
    version ; on la lit plutôt que de deviner une URL, parce que le nom de
    fichier change d'une version à l'autre (`TAXREF_v18_2025.zip`).

    Renvoie `{clé: version}` pour ce qui a pu être lu. Un dictionnaire vide
    signifie que la page n'a pas pu être consultée — à ne pas confondre avec
    « rien de neuf ».
    """
    import re

    try:
        reponse = requests.get(cfg["page_source"], headers=_UA, timeout=timeout)
        reponse.raise_for_status()
    except Exception:  # noqa: BLE001
        return {}

    plat = re.sub(r"(\s*\|\s*)+", " | ",
                  re.sub(r"<[^>]+>", " | ", re.sub(r"\s+", " ", reponse.text)))
    bouts = [b.strip() for b in plat.split("|") if b.strip()]

    trouvees: dict[str, str] = {}
    for cle, libelle in _LIBELLE_INPN.items():
        if cle not in cfg["referentiels"]:
            continue
        for i, bout in enumerate(bouts):
            if bout != libelle:
                continue
            # La version suit la description : premier jeton purement numérique
            # (« 18 ») ou daté (« 06/2025 ») dans les cellules qui suivent.
            for suivant in bouts[i + 1:i + 12]:
                if re.fullmatch(r"\d{1,2}", suivant) or re.fullmatch(r"\d{2}/\d{4}", suivant):
                    trouvees[cle] = suivant
                    break
            break
    return trouvees


def comparer_versions(cfg: dict) -> tuple[dict[str, tuple[str, str]], bool]:
    """Compare l'épinglage local aux versions publiées.

    Renvoie (`{clé: (épinglée, publiée)}`, `consultation_reussie`).
    """
    publiees = versions_publiees(cfg)
    if not publiees:
        return {}, False
    return ({cle: (spec["version"], publiees.get(cle, "?"))
             for cle, spec in cfg["referentiels"].items()}, True)


def bandeau_versions(refs: dict[str, Referentiel], attribution: str) -> list[str]:
    """Lignes de citation à reporter dans toute sortie (obligation de licence)."""
    return [r.citation(attribution) for r in refs.values()]
