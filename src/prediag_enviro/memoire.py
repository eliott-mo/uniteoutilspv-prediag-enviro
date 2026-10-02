"""Ce dont l'outil se souvient, et où.

Deux mémoires, de natures différentes, et c'est pourquoi elles ne vivent pas
au même endroit.

**Les arbitrages** — les décisions rendues sur les constats de veille. Elles
n'appartiennent qu'à la personne qui tient les classeurs à jour, et elles
restent sur sa machine. Sans elles, chaque passage reproposerait les mêmes
dizaines de divergences et l'outil finirait par ne plus être ouvert : le
« refusé » compte donc autant que l'« accepté », et un constat écarté ne revient
que si la source a rebougé. C'est aussi une trace — « écarté en septembre 2026,
notre édition odonates est plus récente que BDC » vaut mieux que de retrancher
la même question six mois plus tard.

**Les alias** — les noms d'espèces que TaxRef ne reconnaît pas et que quelqu'un
a corrigés à la main. « Grande Tortue », « Demi-Deuil », « Machaon » : des noms
que tout naturaliste emploie et que le référentiel n'indexe pas sous cette
forme. Ceux-là sont **partagés**, parce que la correction vaut pour tout le
monde : garder le carnet sur chaque poste reviendrait à le reconstruire autant
de fois qu'il y a de chefs de projet, et le bac des non résolus ne se viderait
jamais.

Un fichier d'alias **par contributeur**, et non un fichier commun. Sur un
dossier synchronisé, deux personnes qui écrivent le même fichier produisent une
copie de conflit et une des deux contributions disparaît. Chacun n'écrit que le
sien, la lecture les fusionne tous.
"""
from __future__ import annotations

import getpass
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ACCEPTE = "accepté"
REFUSE = "refusé"
A_REVOIR = "à revoir"
DECISIONS = (ACCEPTE, REFUSE, A_REVOIR)


@dataclass
class Arbitrage:
    decision: str
    note: str
    le: str
    propose: str      # valeur proposée au moment de l'arbitrage


def _nom_contributeur() -> str:
    """Nom de fichier sûr, tiré de l'identifiant Windows."""
    try:
        brut = getpass.getuser()
    except Exception:  # noqa: BLE001
        brut = "inconnu"
    propre = re.sub(r"[^A-Za-z0-9._-]", "-", brut).strip("-")
    return propre or "inconnu"


class Memoire:
    """Arbitrages (locaux) et alias (partagés)."""

    def __init__(self, chemin: Path, dossier_alias: Path | None = None):
        self.chemin = chemin
        self.dossier_alias = dossier_alias
        self._arbitrages: dict[str, Arbitrage] = {}
        self._alias: dict[str, str] = {}
        self._alias_locaux: dict[str, str] = {}   # ce que ce poste a appris
        self._charger()

    # ------------------------------------------------------------ chargement

    def _charger(self) -> None:
        if self.chemin.exists():
            try:
                brut = json.loads(self.chemin.read_text(encoding="utf-8"))
                self._arbitrages = {k: Arbitrage(**v)
                                    for k, v in brut.get("arbitrages", {}).items()}
                # Les alias vivaient autrefois ici : on les reprend sans rien
                # perdre, et ils repartiront dans le dossier partagé.
                self._alias_locaux = dict(brut.get("alias", {}))
                self._alias.update(self._alias_locaux)
            except Exception:  # noqa: BLE001
                pass

        if self.dossier_alias and self.dossier_alias.exists():
            for fichier in sorted(self.dossier_alias.glob("*.json")):
                try:
                    partages = json.loads(fichier.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    continue
                if isinstance(partages, dict):
                    self._alias.update(partages)
                    if fichier.name == f"{_nom_contributeur()}.json":
                        self._alias_locaux.update(partages)

    def enregistrer(self) -> None:
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        self.chemin.write_text(json.dumps(
            {"arbitrages": {k: vars(v) for k, v in self._arbitrages.items()}},
            indent=2, ensure_ascii=False), encoding="utf-8")

        if self.dossier_alias is not None and self._alias_locaux:
            self.dossier_alias.mkdir(parents=True, exist_ok=True)
            fichier = self.dossier_alias / f"{_nom_contributeur()}.json"
            # On relit avant d'écrire : le fichier a pu être synchronisé depuis
            # un autre poste de la même personne.
            fusion = dict(self._alias_locaux)
            if fichier.exists():
                try:
                    ancien = json.loads(fichier.read_text(encoding="utf-8"))
                    if isinstance(ancien, dict):
                        fusion = {**ancien, **fusion}
                except Exception:  # noqa: BLE001
                    pass
            fichier.write_text(json.dumps(fusion, indent=2, ensure_ascii=False,
                                          sort_keys=True), encoding="utf-8")

    # ---------------------------------------------------------- arbitrages

    def arbitrage(self, cle: str) -> Arbitrage | None:
        return self._arbitrages.get(cle)

    def deja_tranche(self, cle: str, propose: str) -> bool:
        """Constat déjà arbitré, et la proposition n'a pas changé depuis."""
        a = self._arbitrages.get(cle)
        return a is not None and a.decision in (ACCEPTE, REFUSE) and a.propose == propose

    def trancher(self, cle: str, decision: str, propose: str, note: str = "") -> None:
        if decision not in DECISIONS:
            raise ValueError(f"décision inconnue : {decision!r} (attendu {DECISIONS})")
        self._arbitrages[cle] = Arbitrage(decision=decision, note=note,
                                          le=date.today().isoformat(), propose=propose)

    @property
    def en_attente(self) -> int:
        return sum(1 for a in self._arbitrages.values() if a.decision == A_REVOIR)

    # --------------------------------------------------------------- alias

    def alias(self, forme: str) -> str | None:
        """cd_ref retenu pour un nom que l'appariement n'avait pas résolu."""
        return self._alias.get(forme)

    def apprendre_alias(self, forme: str, cd_ref: str) -> None:
        self._alias[forme] = str(cd_ref)
        self._alias_locaux[forme] = str(cd_ref)

    @property
    def nb_alias(self) -> int:
        return len(self._alias)

    @property
    def nb_alias_locaux(self) -> int:
        """Ce que ce poste a appris — le reste vient des collègues."""
        return len(self._alias_locaux)
