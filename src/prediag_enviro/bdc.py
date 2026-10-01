"""Lecture de BDC-Statuts (INPN) : les statuts de référence, par cd_ref.

BDC-Statuts regroupe ce que Marie va chercher à la main sur Légifrance et chez
l'UICN. Ses types couvrent presque toutes les colonnes de ses classeurs :

    LRE  liste rouge européenne      PN   protection nationale
    LRN  liste rouge nationale       PR   protection régionale
    LRR  liste rouge régionale       PD   protection départementale
    LRM  liste rouge mondiale        DH   directive Habitats
    ZDET ZNIEFF déterminantes        DO   directive Oiseaux
    PNA  plan national d'actions

Deux limites, vérifiées sur la v18 et à garder en tête :

* **BDC ne dit pas de quelle édition vient un statut** : le champ source est
  vide sur les 5 831 entrées LRE. L'outil peut donc signaler un écart, jamais
  trancher qui a raison.
* **BDC ne distingue pas les périodes** (nicheurs, hivernants, de passage) :
  `RQ_STATUT` porte les critères UICN, pas la saison. Une colonne « LRR
  Nicheurs » n'est donc comparable que lorsque l'appariement reste sans
  ambiguïté — voir `veille.comparer`.
"""
from __future__ import annotations

import csv
import io
import pickle
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

csv.field_size_limit(10 ** 7)

#: Types de statuts exploités par la veille (les autres sont lus mais ignorés).
TYPES_SUIVIS = {"LRE", "LRN", "LRR", "LRM", "ZDET", "PN", "PR", "PD", "DH", "DO", "PNA"}


@dataclass
class Statut:
    cd_ref: str
    type_statut: str         # LRE, LRR…
    territoire: str          # LB_ADM_TR : Europe, France, Normandie, Rhône…
    code: str                # LC, NT, VU, Art. 3, A072…
    libelle: str = ""


class Statuts:
    """Index des statuts BDC, interrogeable par (cd_ref, type, territoire)."""

    def __init__(self, table: dict[tuple[str, str, str], list[str]], version: str,
                 territoires: dict[str, set[str]]):
        self._table = table
        self.version = version
        self.territoires = territoires

    # ------------------------------------------------------------ construction

    @classmethod
    def construire(cls, archive: Path, membre: str, version: str) -> "Statuts":
        z = zipfile.ZipFile(archive)
        table: dict[tuple[str, str, str], list[str]] = defaultdict(list)
        territoires: dict[str, set[str]] = defaultdict(set)

        with z.open(membre) as f:
            flux = io.TextIOWrapper(f, encoding="utf-8", errors="replace", newline="")
            for ligne in csv.DictReader(flux):
                type_statut = (ligne.get("CD_TYPE_STATUT") or "").strip()
                if type_statut not in TYPES_SUIVIS:
                    continue
                code = (ligne.get("CODE_STATUT") or "").strip()
                if not code:
                    continue
                cd_ref = (ligne.get("CD_REF") or "").strip()
                terr = (ligne.get("LB_ADM_TR") or "").strip()
                cle = (cd_ref, type_statut, terr)
                if code not in table[cle]:
                    table[cle].append(code)
                territoires[type_statut].add(terr)

        return cls(dict(table), version, {k: set(v) for k, v in territoires.items()})

    @classmethod
    def charger(cls, archive: Path, membre: str, version: str,
                cache: Path | None = None) -> "Statuts":
        if cache and cache.exists():
            try:
                donnees = pickle.loads(cache.read_bytes())
                if donnees.get("version") == version:
                    return cls(donnees["table"], version, donnees["territoires"])
            except Exception:  # noqa: BLE001
                pass
        index = cls.construire(archive, membre, version)
        if cache:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(pickle.dumps({
                "table": index._table, "version": version,
                "territoires": index.territoires,
            }))
        return index

    # -------------------------------------------------------------- lecture

    def __len__(self) -> int:
        return len(self._table)

    def codes(self, cd_ref: str, type_statut: str, territoire: str) -> list[str]:
        """Codes connus pour ce taxon, ce type et ce territoire (souvent un seul)."""
        return self._table.get((str(cd_ref), type_statut, territoire), [])

    def code_unique(self, cd_ref: str, type_statut: str, territoire: str) -> str | None:
        """Code unique, ou None si absent ou si BDC en porte plusieurs."""
        trouves = self.codes(cd_ref, type_statut, territoire)
        return trouves[0] if len(trouves) == 1 else None

    def couvre(self, type_statut: str, territoire: str) -> bool:
        """BDC connaît-il ce couple type/territoire ?

        Permet de distinguer « BDC ne couvre pas la Normandie pour ce type »
        de « ce taxon n'y a pas de statut » — deux constats très différents.
        """
        return territoire in self.territoires.get(type_statut, set())
