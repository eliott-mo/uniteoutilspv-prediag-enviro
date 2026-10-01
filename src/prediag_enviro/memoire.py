"""Mémoire des arbitrages : ce qui rend la veille supportable dans la durée.

Sans elle, chaque passage reproposerait les mêmes dizaines de divergences et
l'outil finirait par ne plus être ouvert. Le « refusé » compte donc autant que
l'« accepté » : il est retenu, et le constat ne revient que si la source a
rebougé depuis.

C'est aussi une trace. « Écarté en septembre 2026, notre édition odonates est
plus récente que BDC » vaut mieux que de re-trancher la même question dans six
mois sans se rappeler pourquoi.
"""
from __future__ import annotations

import json
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


class Memoire:
    """Arbitrages et alias, persistés en JSON à côté du projet."""

    def __init__(self, chemin: Path):
        self.chemin = chemin
        self._arbitrages: dict[str, Arbitrage] = {}
        self._alias: dict[str, str] = {}
        self._charger()

    def _charger(self) -> None:
        if not self.chemin.exists():
            return
        try:
            brut = json.loads(self.chemin.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return
        self._arbitrages = {
            k: Arbitrage(**v) for k, v in brut.get("arbitrages", {}).items()
        }
        self._alias = dict(brut.get("alias", {}))

    def enregistrer(self) -> None:
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        self.chemin.write_text(json.dumps({
            "arbitrages": {k: vars(v) for k, v in self._arbitrages.items()},
            "alias": self._alias,
        }, indent=2, ensure_ascii=False), encoding="utf-8")

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

    @property
    def nb_alias(self) -> int:
        return len(self._alias)
