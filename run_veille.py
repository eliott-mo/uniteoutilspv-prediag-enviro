#!/usr/bin/env python
"""Veille sur les classeurs B-Statuts : ce qui a bougé depuis la dernière révision.

    python run_veille.py                              # tout
    python run_veille.py --groupes oiseaux insectes   # cibler des groupes
    python run_veille.py --territoires Normandie      # cibler un territoire
    python run_veille.py --maj-referentiels           # rafraîchir TaxRef / BDC
    python run_veille.py --relire sorties/veille.xlsx # enregistrer les arbitrages

Les classeurs sont lus dans `classeurs/`, jamais modifiés.
"""
from __future__ import annotations
import argparse
import sys
from datetime import date
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import yaml

RACINE = Path(__file__).resolve().parent
sys.path.insert(0, str(RACINE / "src"))

from prediag_enviro import (bdc, classeurs, determinantes, rapport,  # noqa: E402
                            referentiels, taxref, veille)
from prediag_enviro.memoire import Memoire  # noqa: E402
from prediag_enviro import chemins, service  # noqa: E402

# Une seule table, dans `service`. Il y en avait deux, identiques, et c'est
# exactement ce que le module `service` existe pour éviter : ajouter la flore
# d'un seul côté aurait donné une interface qui la lit et une ligne de
# commande qui l'ignore.
MOTIFS = service.MOTIFS


def main() -> int:
    ap = argparse.ArgumentParser(description="Veille des classeurs B-Statuts")
    ap.add_argument("--groupes", nargs="*", help="limiter à certains groupes")
    ap.add_argument("--territoires", nargs="*", help="limiter à certains territoires")
    ap.add_argument("--maj-referentiels", action="store_true",
                    help="retélécharger TaxRef et BDC-Statuts")
    ap.add_argument("--relire", type=Path,
                    help="relire un rapport annoté et mémoriser les arbitrages")
    ap.add_argument("--sortie", type=Path, help="chemin du rapport produit")
    args = ap.parse_args()

    cfg = yaml.safe_load((RACINE / "config" / "sources.yml").read_text(encoding="utf-8"))
    service.emplacements(RACINE)
    memoire = Memoire(chemins.memoire() / "arbitrages.json",
                      dossier_alias=chemins.alias())

    if args.relire:
        retenus = rapport.relire_decisions(args.relire, memoire)
        print(f"{retenus} arbitrage(s) enregistré(s) dans {memoire.chemin}")
        return 0

    print("\n=== Veille des classeurs B-Statuts ===\n")

    print("Référentiels")
    refs = referentiels.assurer(cfg, chemins.referentiels(),
                                forcer=args.maj_referentiels,
                                cles=("taxref", "bdc_statuts"))
    citations = referentiels.bandeau_versions(refs, cfg["attribution"])
    for c in citations:
        print(f"  {c}")

    cache = chemins.referentiels()
    spec_tax = cfg["referentiels"]["taxref"]
    idx = taxref.Index.charger(refs["taxref"].chemin, spec_tax["membres"],
                               spec_tax["version"], cache / "taxref_index.pkl")
    spec_bdc = cfg["referentiels"]["bdc_statuts"]
    statuts = bdc.Statuts.charger(refs["bdc_statuts"].chemin,
                                  spec_bdc["membres"]["principal"],
                                  spec_bdc["version"], cache / "bdc_index.pkl")
    listes = determinantes.charger(refs["bdc_statuts"].chemin, spec_bdc["version"],
                                   cache / "determinantes_index.pkl")
    print(f"  TaxRef : {len(idx):,} taxons · BDC : {len(statuts):,} statuts indexés"
          f" · {len(listes.territoires())} territoires de listes ZNIEFF"
          .replace(",", " "))

    print("\nClasseurs")
    dossier = chemins.classeurs()
    cs = classeurs.lire_tous(dossier, MOTIFS)
    if not cs:
        print(f"  aucun classeur dans {dossier}/ — y déposer les fichiers B-Statuts")
        return 1
    for oublie in classeurs.non_reconnus(dossier, MOTIFS):
        print(f"  ⚠ {oublie} n'est reconnu par aucun motif : il n'est pas lu.")
    # La veille ne porte que sur la curation de la responsable environnement.
    cs = {cle: c for cle, c in cs.items()
          if cle not in service.GROUPES_HORS_VEILLE}
    for groupe, cl in cs.items():
        comparables = sum(1 for c in cl.colonnes if c.comparable)
        print(f"  {groupe:18s} {len(cl.taxons):>5} taxons · {len(cl.colonnes):>3} colonnes "
              f"({comparables} comparables)")

    print("\nAnalyse…")
    res = veille.analyser(cs, idx, statuts, groupes=args.groupes,
                          territoires=args.territoires,
                          determinantes=determinantes.Statuts(listes))

    avant = len(res.constats)
    res.constats = [c for c in res.constats
                    if not memoire.deja_tranche(c.cle, c.propose)]
    masques = avant - len(res.constats)

    for cle, titre in veille.FAMILLES:
        combien = len(res.par_famille(cle))
        print(f"  {titre:38s} {combien:>5}")
    if masques:
        print(f"  {'(déjà arbitrés, masqués)':38s} {masques:>5}")

    filtres = " · ".join(filter(None, [
        "groupes : " + ", ".join(args.groupes) if args.groupes else "",
        "territoires : " + ", ".join(args.territoires) if args.territoires else "",
    ]))
    sortie = args.sortie or (chemins.sorties() /
                             f"veille_{date.today().isoformat()}.xlsx")
    rapport.ecrire(res, sortie, citations, memoire, filtres)
    print(f"\n-> {sortie}")
    print("\nAucun classeur n'a été modifié. Renseigne la colonne « Décision »,")
    print(f"puis : python run_veille.py --relire \"{sortie.name}\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
