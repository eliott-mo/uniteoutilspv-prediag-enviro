"""Veille : ce qui a bougé depuis la dernière révision des classeurs.

Quatre familles de constats, délibérément séparées parce qu'elles appellent des
états d'esprit différents :

    ① à corriger      une ligne porte la taxonomie d'une autre espèce
    ② taxonomie       CD_NOM devenu synonyme ou supprimé dans TaxRef
    ③ statuts         un statut diffère de BDC-Statuts
    ④ publications    une nouvelle liste rouge est parue  (non implémenté)

**Rien n'est jamais écrit dans les classeurs.** Quatre raisons, par ordre
croissant d'importance :

1. Les fichiers sont pilotés par formules, avec en-têtes fusionnés et mises en
   forme conditionnelles ; une réécriture les dégraderait.
2. BDC ne dit pas de quelle édition viennent ses statuts : face à un écart, il
   n'existe pas de bonne réponse calculable.
3. La curation de Marie contient des choix délibérés — lignes « population du
   Quercy », annotations « ssp. brookei, non reconnu TAXREF 14 » — qu'une
   synchronisation effacerait comme absents du référentiel.
4. C'est elle qui signe les études.

L'outil propose, elle arbitre.
"""
from __future__ import annotations

import difflib
import re
from collections import defaultdict
from dataclasses import dataclass, field

from . import vocabulaire
from .bdc import Statuts
from .classeurs import Classeur, ColonneStatut
from .taxref import Index, normaliser

#: Familles, dans l'ordre d'affichage du rapport.
FAMILLES = [
    ("corriger", "① À corriger dans le classeur"),
    ("taxonomie", "② Taxonomie à rafraîchir"),
    ("statuts", "③ Statuts qui ont bougé"),
]

#: Territoires qui s'appliquent partout : filtrer sur une région ne doit pas
#: masquer la liste rouge nationale ni la liste rouge européenne.
TERRITOIRES_SUPRA = {"Europe", "France", "Monde"}

#: Lignes volontairement distinctes : populations, sous-espèces, complexes.
#: Les signaler serait crier au loup — elles sont là exprès.
_DELIBERE = re.compile(
    r"(?i)(population|\bpop\.|\bssp\b|sous[- ]espece|complexe|non reconnu|\bsp\.)"
)


@dataclass
class Constat:
    famille: str             # corriger | taxonomie | statuts
    groupe: str              # oiseaux, insectes…
    ligne: int               # ligne dans l'onglet Statuts
    taxon: str               # libellé lisible
    champ: str               # CD_NOM, LRE, LRR Normandie…
    actuel: str
    propose: str
    source: str              # TaxRef v18, BDC-Statuts v18…
    territoire: str = ""     # tel que BDC l'écrit — vide hors statuts
    detail: str = ""
    lien: str = ""           # fiche à ouvrir pour vérifier en un clic
    cle: str = ""            # identité stable du constat, pour la mémoire

    def __post_init__(self):
        if not self.cle:
            self.cle = f"{self.groupe}|{self.ligne}|{self.champ}|{self.actuel}|{self.propose}"


@dataclass
class Resultat:
    constats: list[Constat] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)
    couverture: dict[str, tuple[int, int]] = field(default_factory=dict)

    def par_famille(self, famille: str) -> list[Constat]:
        return [c for c in self.constats if c.famille == famille]


# --------------------------------------------------------------------- ① & ②

def _coherence_et_taxonomie(cl: Classeur, idx: Index) -> list[Constat]:
    constats: list[Constat] = []
    vus: dict[str, list] = defaultdict(list)

    for t in cl.taxons:
        if t.cd_nom:
            vus[t.cd_nom].append(t)

        if not t.cd_nom:
            continue

        disparu = idx.est_disparu(t.cd_nom)
        if disparu:
            remplacement, raison = disparu
            constats.append(Constat(
                famille="taxonomie", groupe=cl.groupe, ligne=t.ligne, taxon=t.libelle,
                champ="CD_NOM", actuel=t.cd_nom, propose=remplacement or "—",
                source=f"TaxRef v{idx.version}", detail=raison[:120],
                lien=f"https://taxref.mnhn.fr/taxref-web/taxa/{t.cd_nom}",
            ))
            continue

        taxon = idx.taxon(t.cd_nom)
        if taxon is None:
            constats.append(Constat(
                famille="taxonomie", groupe=cl.groupe, ligne=t.ligne, taxon=t.libelle,
                champ="CD_NOM", actuel=t.cd_nom, propose="—",
                source=f"TaxRef v{idx.version}", detail="inconnu de TaxRef",
            ))
            continue

        if taxon.est_synonyme:
            constats.append(Constat(
                famille="taxonomie", groupe=cl.groupe, ligne=t.ligne, taxon=t.libelle,
                champ="CD_NOM", actuel=t.cd_nom, propose=taxon.cd_ref,
                source=f"TaxRef v{idx.version}",
                detail=f"synonyme — nom valide : {taxon.nom_valide}",
                lien=taxon.url,
            ))
            continue

        # Nom scientifique désaligné. Trois cas très différents, et un seul
        # mérite d'être remonté comme défaut.
        if t.nom_scientifique and not _DELIBERE.search(t.libelle):
            sien = normaliser(t.nom_scientifique)
            tax_ref = normaliser(taxon.lb_nom)
            if sien and tax_ref and sien != tax_ref:
                # (a) binôme contre trinôme : elle nomme l'espèce, le CD_NOM
                #     pointe la sous-espèce (ou l'inverse). Volontaire.
                prefixe = sien.startswith(tax_ref + " ") or tax_ref.startswith(sien + " ")
                if not prefixe:
                    proximite = difflib.SequenceMatcher(None, sien, tax_ref).ratio()
                    # (b) orthographe très proche : coquille probable.
                    # (c) noms franchement différents : mauvais CD_NOM.
                    detail = (
                        "coquille probable" if proximite >= 0.88
                        else f"CD_NOM {t.cd_nom} désigne un autre taxon"
                    )
                    constats.append(Constat(
                        famille="corriger", groupe=cl.groupe, ligne=t.ligne,
                        taxon=t.libelle, champ="Nom scientifique",
                        actuel=t.nom_scientifique, propose=taxon.lb_nom,
                        source=f"TaxRef v{idx.version}", detail=detail,
                        lien=taxon.url,
                    ))

    # Un même CD_NOM sur deux lignes qui ne sont pas des variantes déclarées :
    # c'est le cas « Faucon lanier porte la taxonomie de l'Aigle impérial ».
    for cd, lignes in vus.items():
        if len(lignes) < 2:
            continue
        ordinaires = [t for t in lignes if not _DELIBERE.search(t.libelle)]
        if len(ordinaires) < 2:
            continue
        noms = {normaliser(t.nom_commun) for t in ordinaires if t.nom_commun}
        if len(noms) < 2:
            continue
        taxon = idx.taxon(cd)
        attendu = taxon.lb_nom if taxon else "?"
        for t in ordinaires[1:]:
            constats.append(Constat(
                famille="corriger", groupe=cl.groupe, ligne=t.ligne, taxon=t.libelle,
                champ="CD_NOM", actuel=cd, propose="(à déterminer)",
                source=f"TaxRef v{idx.version}",
                detail=f"CD_NOM partagé avec « {ordinaires[0].libelle} » ; "
                       f"{cd} désigne {attendu}",
                lien=f"https://taxref.mnhn.fr/taxref-web/taxa/{cd}",
            ))
    return constats


# ----------------------------------------------------------------------- ③

def _valeur_unique_par_territoire(cl: Classeur, t, type_bdc: str,
                                  territoire: str) -> tuple[str, ColonneStatut] | None:
    """Valeur de Marie pour ce couple, toutes périodes confondues.

    BDC ne distingue pas nicheurs/hivernants/de passage. On ne peut donc
    comparer une colonne périodisée que si une seule de ses périodes est
    renseignée : l'appariement est alors sans ambiguïté.
    """
    candidates = [c for c in cl.colonnes
                  if c.type_bdc == type_bdc and c.territoire_bdc == territoire]
    remplies = [(t.valeurs[c.index], c) for c in candidates if t.valeurs.get(c.index)]
    return remplies[0] if len(remplies) == 1 else None


def _statuts(cl: Classeur, idx: Index, statuts: Statuts) -> tuple[list[Constat], dict]:
    constats: list[Constat] = []
    couples: list[tuple[str, str]] = []
    ecartes: set[str] = set()
    vus: set[tuple[str, str]] = set()
    for c in cl.colonnes:
        if not c.type_bdc:
            continue
        if not vocabulaire.comparable(c.type_bdc):
            ecartes.add(c.type_bdc)
            continue
        cle = (c.type_bdc, c.territoire_bdc)
        if cle in vus:
            continue
        vus.add(cle)
        if statuts.couvre(c.type_bdc, c.territoire_bdc):
            couples.append(cle)

    apparies = compares = 0
    for t in cl.taxons:
        if not t.cd_nom:
            continue
        taxon = idx.taxon(t.cd_nom)
        cd_ref = taxon.cd_ref if taxon else t.cd_nom
        apparies += 1
        for type_bdc, territoire in couples:
            trouve = _valeur_unique_par_territoire(cl, t, type_bdc, territoire)
            if trouve is None:
                continue
            valeur, colonne = trouve
            reference = statuts.code_unique(cd_ref, type_bdc, territoire)
            if reference is None:
                continue
            compares += 1
            if vocabulaire.equivalents(valeur, reference, type_bdc):
                continue
            detail = ""
            if colonne.periode:
                detail = f"colonne « {colonne.periode} » — BDC ne distingue pas les périodes"
            if colonne.annee:
                detail = (detail + " · " if detail else "") + f"ton édition : {colonne.annee}"
            constats.append(Constat(
                famille="statuts", groupe=cl.groupe, ligne=t.ligne, taxon=t.libelle,
                champ=f"{type_bdc} {territoire}".strip(), actuel=valeur,
                propose=reference, source=f"BDC-Statuts v{statuts.version}",
                territoire=territoire, detail=detail,
                lien=f"https://inpn.mnhn.fr/espece/cd_nom/{cd_ref}",
            ))
    return constats, {"taxons": apparies, "cellules_comparees": compares,
                      "couples": len(couples), "types_ecartes": sorted(ecartes)}


# -------------------------------------------------------------------- façade

def analyser(classeurs: dict[str, Classeur], idx: Index, statuts: Statuts,
             groupes: list[str] | None = None,
             territoires: list[str] | None = None) -> Resultat:
    """Produit tous les constats. Aucune écriture dans les classeurs."""
    res = Resultat()
    ecartes: set[str] = set()
    for groupe, cl in classeurs.items():
        if groupes and groupe not in groupes:
            continue
        res.avertissements += [f"{groupe} : {a}" for a in cl.avertissements]
        res.constats += _coherence_et_taxonomie(cl, idx)
        constats, couverture = _statuts(cl, idx, statuts)
        res.constats += constats
        res.couverture[groupe] = (couverture["cellules_comparees"], couverture["taxons"])
        ecartes.update(couverture["types_ecartes"])

    for type_statut in sorted(ecartes):
        res.avertissements.append(
            f"{type_statut} non confronté — {vocabulaire.raison_ecart(type_statut)}"
        )

    if territoires:
        # Comparaison sur la forme normalisée : « Centre-Val de Loire » dans le
        # classeur et « Centre » dans BDC désignent la même région, et l'accent
        # d'« Île-de-France » ne doit pas faire rater douze constats. Le filtre
        # était une recherche de sous-chaîne dans le libellé : un territoire
        # mal orthographié — ou simplement écrit comme le classeur l'écrit —
        # renvoyait zéro constat régional sans rien dire.
        from .classeurs import _cle_territoire, territoire_bdc
        garder = {_cle_territoire(territoire_bdc(t)) for t in territoires}
        res.constats = [
            c for c in res.constats
            if c.famille != "statuts"
            or _cle_territoire(c.territoire) in garder
            or c.territoire in TERRITOIRES_SUPRA
        ]

    ordre = {cle: i for i, (cle, _) in enumerate(FAMILLES)}
    res.constats.sort(key=lambda c: (ordre.get(c.famille, 9), c.groupe, c.ligne))
    return res
