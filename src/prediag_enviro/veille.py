"""Veille : ce qui a bougé depuis la dernière révision des classeurs.

Quatre familles de constats, délibérément séparées parce qu'elles appellent des
états d'esprit différents :

    ① à corriger      une ligne porte la taxonomie d'une autre espèce
    ② taxonomie       CD_NOM devenu synonyme ou supprimé dans TaxRef
    ③ statuts         un statut diffère de BDC-Statuts, qui cite sa source
    ④ désaccord       un statut diffère de BDC, qui ne cite pas la sienne
    ⑤ publications    une nouvelle liste rouge est parue  (non implémenté)

**Rien n'est jamais écrit dans les classeurs.** Quatre raisons, par ordre
croissant d'importance :

1. Les fichiers sont pilotés par formules, avec en-têtes fusionnés et mises en
   forme conditionnelles ; une réécriture les dégraderait.
2. BDC ne dit pas toujours de quelle édition viennent ses statuts. Mesuré
   sur la v18 : 22 de ses 24 types portent une référence complète, mais la
   liste rouge européenne et la liste rouge mondiale n'en portent aucune —
   5 831 et 19 461 lignes sans source ni date. Face à un écart sur ces
   deux-là, il n'existe pas de bonne réponse calculable, et la Licence
   Ouverte interdit même de citer la valeur. On constate sans proposer.
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
    ("desaccord", "④ Désaccords non arbitrables"),
]

#: Types dont les valeurs relèvent de la nomenclature UICN.
_TYPES_ROUGES = {"LRE", "LRN", "LRR", "LRM"}

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
    #: Codes dont on a déjà nommé la ligne fautive. Inutile d'accuser ensuite
    #: la ligne qui le portait légitimement : la Cigale rouge garde son 51916,
    #: c'est le Procris de la Vigne qui le lui avait pris.
    codes_expliques: set[str] = set()

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
                    # Le nom qu'elle a écrit tranche, quand TaxRef le
                    # reconnaît sûrement : un nom qui se résout n'est pas une
                    # coquille. Quatre issues, et elles ne se confondent pas.
                    vise = idx.apparier(t.nom_scientifique, cl.groupe)
                    if vise.sur and vise.cd_ref and vise.cd_ref != t.cd_nom:
                        # (c) son nom désigne un autre taxon que son code :
                        #     c'est le code qui est faux. Les deux
                        #     bergeronnettes portent des codes permutés —
                        #     proposer d'échanger leurs noms, comme le faisait
                        #     le seuil de proximité, aurait faussé les deux
                        #     lignes au lieu d'en corriger une.
                        bon = vise.cd_ref
                        constats.append(Constat(
                            famille="corriger", groupe=cl.groupe, ligne=t.ligne,
                            taxon=t.libelle, champ="CD_NOM",
                            actuel=t.cd_nom, propose=bon,
                            source=f"TaxRef v{idx.version}",
                            detail=f"{t.cd_nom} désigne {taxon.lb_nom} ; "
                                   f"« {t.nom_scientifique} » porte le {bon}",
                            lien=(idx.taxon(bon).url if idx.taxon(bon)
                                  else taxon.url),
                        ))
                        codes_expliques.add(t.cd_nom)
                    elif vise.sur:
                        # (d) même taxon, nom vieilli : TaxRef a renommé le
                        #     genre — « Charadrius morinellus » est devenu
                        #     « Eudromias morinellus ». Le code est bon.
                        constats.append(Constat(
                            famille="corriger", groupe=cl.groupe, ligne=t.ligne,
                            taxon=t.libelle, champ="Nom scientifique",
                            actuel=t.nom_scientifique, propose=taxon.lb_nom,
                            source=f"TaxRef v{idx.version}",
                            detail="nom en vigueur dans TaxRef ; CD_NOM confirmé",
                            lien=taxon.url,
                        ))
                    elif proximite >= 0.88:
                        # (b) orthographe très proche : c'est le nom qui porte
                        #     la coquille, le CD_NOM désigne bien l'espèce
                        #     voulue. « Photedes fiuxa » pour « fluxa ».
                        constats.append(Constat(
                            famille="corriger", groupe=cl.groupe, ligne=t.ligne,
                            taxon=t.libelle, champ="Nom scientifique",
                            actuel=t.nom_scientifique, propose=taxon.lb_nom,
                            source=f"TaxRef v{idx.version}",
                            detail="coquille probable", lien=taxon.url,
                        ))
                    else:
                        # (e) le code désigne un autre taxon et son nom ne se
                        #     résout pas : on dit ce qu'on sait, sans inventer
                        #     le code de remplacement.
                        constats.append(Constat(
                            famille="corriger", groupe=cl.groupe, ligne=t.ligne,
                            taxon=t.libelle, champ="CD_NOM",
                            actuel=t.cd_nom, propose="(à déterminer)",
                            source=f"TaxRef v{idx.version}",
                            detail=f"{t.cd_nom} désigne {taxon.lb_nom} ; "
                                   f"« {t.nom_scientifique} » ne se résout pas",
                            lien=taxon.url,
                        ))
                        codes_expliques.add(t.cd_nom)

    # Un même CD_NOM sur deux lignes qui ne sont pas des variantes déclarées :
    # c'est le cas « Faucon lanier porte la taxonomie de l'Aigle impérial ».
    for cd, lignes in vus.items():
        if len(lignes) < 2 or cd in codes_expliques:
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
            # Le nom français de la ligne tranche souvent ce que le code ne dit
            # pas. Trois issues, et il faut les distinguer : « Faucon lanier »
            # porte le 2683 et non celui de l'Aigle impérial — on propose le
            # code ; « Pluvier guignard » et « Guignard d'Eurasie » sont deux
            # noms TaxRef du même taxon — la ligne fait doublon, le code est
            # bon ; « Zygène de la Badasse » ne se résout pas — on le dit.
            vise = idx.apparier(t.nom_commun, cl.groupe) if t.nom_commun else None
            if vise is not None and vise.sur and vise.cd_ref != cd:
                propose, detail = vise.cd_ref, (
                    f"CD_NOM partagé avec « {ordinaires[0].libelle} » ; "
                    f"{cd} désigne {attendu}, et « {t.nom_commun} » "
                    f"porte le {vise.cd_ref}")
            elif vise is not None and vise.sur:
                propose, detail = "(doublon)", (
                    f"TaxRef porte « {t.nom_commun} » et "
                    f"« {ordinaires[0].libelle} » sur le même taxon "
                    f"({attendu}) : la ligne fait doublon, le CD_NOM est bon")
            else:
                propose, detail = "(à déterminer)", (
                    f"CD_NOM partagé avec « {ordinaires[0].libelle} » ; "
                    f"{cd} désigne {attendu}, et « {t.nom_commun} » ne se "
                    f"résout pas dans TaxRef")
            constats.append(Constat(
                famille="corriger", groupe=cl.groupe, ligne=t.ligne, taxon=t.libelle,
                champ="CD_NOM", actuel=cd, propose=propose,
                source=f"TaxRef v{idx.version}", detail=detail,
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
            if statuts.cite(type_bdc):
                constats.append(Constat(
                    famille="statuts", groupe=cl.groupe, ligne=t.ligne,
                    taxon=t.libelle,
                    champ=f"{type_bdc} {territoire}".strip(), actuel=valeur,
                    propose=reference, source=f"BDC-Statuts v{statuts.version}",
                    territoire=territoire, detail=detail,
                    lien=f"https://inpn.mnhn.fr/espece/cd_nom/{cd_ref}",
                ))
            else:
                # Rien à proposer : BDC ne dit pas d'où il tient sa valeur, et
                # le classeur, lui, nomme sa source. On montre le désaccord
                # sans prétendre l'arbitrer — c'est tout ce qu'on sait.
                constats.append(Constat(
                    famille="desaccord", groupe=cl.groupe, ligne=t.ligne,
                    taxon=t.libelle,
                    champ=f"{type_bdc} {territoire}".strip(), actuel=valeur,
                    propose="", source=f"BDC-Statuts v{statuts.version}",
                    territoire=territoire,
                    detail=(detail + " · " if detail else "")
                           + f"BDC écrit « {reference} » mais ne cite aucune "
                             "source pour ce type de statut",
                    lien=f"https://inpn.mnhn.fr/espece/cd_nom/{cd_ref}",
                ))
    return constats, {"taxons": apparies, "cellules_comparees": compares,
                      "couples": len(couples), "types_ecartes": sorted(ecartes)}


def _controles_internes(classeurs: dict[str, Classeur],
                        statuts: Statuts) -> list[Constat]:
    """Ce que les classeurs disent d'eux-mêmes, sans référentiel externe.

    Deux garde-fous, posés là où la confrontation à BDC a été retirée. Ils ne
    demandent aucune source : le premier vérifie la forme d'une valeur, le
    second que les classeurs ne se contredisent pas entre eux. Tous deux sont
    muets sur la base d'octobre 2026 — 0 valeur européenne hors nomenclature
    sur 1 388, 0 désaccord sur les 274 valeurs que deux classeurs portent en
    commun — et c'est le résultat attendu : ce sont des garde-fous, pas des
    chercheurs de fautes.

    Le premier ne s'applique qu'aux types que BDC ne cite pas, et c'est
    volontaire : les colonnes nationales et régionales portent 446 valeurs
    étrangères à l'échelle UICN, et à bon droit — dont 199 indices de priorité
    des orthoptères, dont la seule référence nationale classe de 1 à 4 dans le
    sens inverse de l'UICN. Les signaler serait crier au loup sur des valeurs
    voulues, et ces colonnes gardent de toute façon la surveillance de BDC.

    Le second compare sur la forme normalisée, comme le reste de l'outil :
    « CR* » et « CR » désignent le même statut, et les opposer aurait produit
    86 faux désaccords entre les classeurs insectes et macrohétérocères.
    """
    constats: list[Constat] = []

    # ① la valeur appartient-elle à la nomenclature UICN ?
    for groupe, cl in classeurs.items():
        for col in cl.colonnes:
            if col.type_bdc not in _TYPES_ROUGES or statuts.cite(col.type_bdc):
                continue
            for t in cl.taxons:
                valeur = (t.valeurs.get(col.index) or "").strip()
                if not valeur or vocabulaire.categorie_valide(valeur):
                    continue
                constats.append(Constat(
                    famille="corriger", groupe=groupe, ligne=t.ligne,
                    taxon=t.libelle,
                    champ=f"{col.type_bdc} {col.territoire_bdc}".strip(),
                    actuel=valeur, propose="(hors nomenclature UICN)",
                    source="contrôle interne",
                    detail="valeur étrangère à l'échelle UICN "
                           "(LC, NT, VU, EN, CR, RE, DD, NE, NA)",
                ))

    # ② deux classeurs, un même taxon, deux statuts
    par_cle: dict[tuple[str, str, str], dict] = defaultdict(dict)
    for groupe, cl in classeurs.items():
        for col in cl.colonnes:
            if col.type_bdc not in _TYPES_ROUGES or col.periode:
                continue
            for t in cl.taxons:
                valeur = (t.valeurs.get(col.index) or "").strip()
                if t.cd_nom and valeur:
                    cle = (t.cd_nom, col.type_bdc, col.territoire_bdc)
                    par_cle[cle][groupe] = (valeur, t)

    for (cd, type_bdc, territoire), trouves in par_cle.items():
        if len(trouves) < 2:
            continue
        items = sorted(trouves.items())
        premier, (valeur0, _) = items[0][0], items[0][1]
        forme0 = vocabulaire.normaliser_code(valeur0, type_bdc)
        for groupe, (valeur, t) in items[1:]:
            if vocabulaire.normaliser_code(valeur, type_bdc) == forme0:
                continue
            constats.append(Constat(
                famille="corriger", groupe=groupe, ligne=t.ligne,
                taxon=t.libelle,
                champ=f"{type_bdc} {territoire}".strip(),
                actuel=valeur, propose="(à arbitrer)",
                source="contrôle interne", territoire=territoire,
                detail=f"le classeur « {premier} » écrit « {valeur0} » pour "
                       f"le même taxon (CD_NOM {cd})",
                lien=f"https://inpn.mnhn.fr/espece/cd_nom/{cd}",
            ))
    return constats


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

    res.constats += _controles_internes(
        {g: cl for g, cl in classeurs.items()
         if not groupes or g in groupes}, statuts)

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
            if c.famille not in ("statuts", "desaccord")
            or _cle_territoire(c.territoire) in garder
            or c.territoire in TERRITOIRES_SUPRA
        ]

    ordre = {cle: i for i, (cle, _) in enumerate(FAMILLES)}
    res.constats.sort(key=lambda c: (ordre.get(c.famille, 9), c.groupe, c.ligne))
    return res
