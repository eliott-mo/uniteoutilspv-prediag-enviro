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
from dataclasses import dataclass, asdict
from datetime import date
from pathlib import Path

import requests

_UA = {"User-Agent": "Mozilla/5.0 (prediag-enviro ; UNITe)"}
_TENTATIVES = 8


@dataclass
class Referentiel:
    cle: str                 # "taxref" | "bdc_statuts"
    version: str             # "18"
    chemin: Path             # archive locale
    recupere_le: str         # ISO date
    url: str

    def citation(self, attribution: str) -> str:
        """Mention de paternité exigée par la Licence Ouverte."""
        nom = {"taxref": "TaxRef", "bdc_statuts": "BDC-Statuts"}.get(self.cle, self.cle)
        return f"{nom} v{self.version} — {attribution}, récupéré le {self.recupere_le}"


def _taille_distante(url: str) -> int | None:
    try:
        r = requests.head(url, headers=_UA, timeout=30, allow_redirects=True)
        n = r.headers.get("content-length")
        return int(n) if n else None
    except Exception:  # noqa: BLE001
        return None


def telecharger(url: str, dest: Path, attendu: int | None = None) -> Path:
    """Télécharge avec reprise. Renvoie le chemin une fois l'archive complète."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if attendu is None:
        attendu = _taille_distante(url)

    for tentative in range(_TENTATIVES):
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
        except Exception as e:  # noqa: BLE001
            if tentative == _TENTATIVES - 1:
                raise RuntimeError(
                    f"Téléchargement de {url} interrompu après {_TENTATIVES} tentatives "
                    f"({dest.stat().st_size if dest.exists() else 0} octets reçus) : {e}"
                ) from e
            time.sleep(2)

    if attendu and dest.stat().st_size < attendu:
        raise RuntimeError(
            f"{dest.name} incomplet : {dest.stat().st_size} octets reçus sur {attendu}"
        )
    return dest


def _manifeste_path(dossier: Path) -> Path:
    return dossier / "manifeste.json"


def lire_manifeste(dossier: Path) -> dict[str, Referentiel]:
    p = _manifeste_path(dossier)
    if not p.exists():
        return {}
    brut = json.loads(p.read_text(encoding="utf-8"))
    return {
        k: Referentiel(cle=k, version=v["version"], chemin=Path(v["chemin"]),
                       recupere_le=v["recupere_le"], url=v["url"])
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


def assurer(cfg: dict, dossier: Path, forcer: bool = False) -> dict[str, Referentiel]:
    """Garantit la présence locale des référentiels déclarés dans sources.yml.

    Ne retélécharge pas ce qui est déjà là, sauf `forcer=True`.
    """
    dossier.mkdir(parents=True, exist_ok=True)
    deja = lire_manifeste(dossier)
    refs: dict[str, Referentiel] = {}

    for cle, spec in cfg["referentiels"].items():
        dest = dossier / spec["fichier"]
        connu = deja.get(cle)
        a_jour = (
            not forcer
            and connu is not None
            and connu.version == spec["version"]
            and dest.exists()
        )
        if a_jour:
            refs[cle] = Referentiel(cle=cle, version=spec["version"], chemin=dest,
                                    recupere_le=connu.recupere_le, url=spec["url"])
            continue

        print(f"  téléchargement {cle} v{spec['version']} …", flush=True)
        telecharger(spec["url"], dest)
        taille = dest.stat().st_size / 1048576
        print(f"    {dest.name} — {taille:.1f} Mo")
        refs[cle] = Referentiel(cle=cle, version=spec["version"], chemin=dest,
                                recupere_le=date.today().isoformat(), url=spec["url"])

    _ecrire_manifeste(dossier, refs)
    return refs


def bandeau_versions(refs: dict[str, Referentiel], attribution: str) -> list[str]:
    """Lignes de citation à reporter dans toute sortie (obligation de licence)."""
    return [r.citation(attribution) for r in refs.values()]
