# -*- coding: utf-8 -*-
"""Les espèces déterminantes ZNIEFF, liste par liste et territoire par territoire.

**Une ZNIEFF n'est pas une protection mais un inventaire**, et une espèce
« déterminante » est celle dont la présence justifie d'en créer ou d'en
délimiter une. Le statut n'emporte aucune obligation : c'est un signal d'enjeu
local, propre à chaque liste régionale.

**Les listes sont régionales ; BDC-Statuts les range par département.** 85 %
de ses lignes déterminantes sont saisies à la maille départementale : la liste
d'Occitanie de 2021 y figure treize fois, une par département. Ne lire que les
lignes régionales — ce que faisait la première version de l'enrichissement des
classeurs — manque donc l'essentiel : les listes d'Occitanie,
d'Auvergne-Rhône-Alpes, d'Île-de-France, du Centre-Val de Loire.

Chaque liste est rapportée au **territoire qu'elle couvre**, déduit de ses
départements : l'ancienne région quand ils y tiennent tous — la liste de 2004
de Midi-Pyrénées reste une liste de Midi-Pyrénées —, la région actuelle sinon.
Un département étranger à ce territoire est écarté et compté : BDC v18 range
ainsi sous « Rhône » des lignes des listes des Hauts-de-France, où le Nord
manque.

**La réserve fait la valeur du statut.** Près de la moitié des lignes en
portent une. Elle est reprise telle quelle, sauf deux formes condensées sans
perte :

* les domaines d'Occitanie — « Déterminant Massif Central - Déterminant Zone
  Méditerranéenne » devient « MC, MED », la notation que le classeur des
  mammifères emploie déjà ;
* le vecteur par zone d'Auvergne-Rhône-Alpes — « Alpine : Déterminante ;
  Méditerranéenne : Non déterminante ; … » —, dont on garde les zones où
  l'espèce compte, regroupées par condition.

Une remarque que BDC a coupée à 255 caractères finit par « … » (voir
`COUPURE_BDC`) : la reprendre telle quelle la donnerait pour entière.

**Toutes les listes ne sont pas dans BDC.** La v18 cite la liste des oiseaux
nicheurs de Nouvelle-Aquitaine (2023) mais n'en porte aucun oiseau. L'export
qu'en publie l'INPN, liste régionale par liste régionale, s'ajoute alors par
`ajouter_export_inpn`.
"""
from __future__ import annotations

import copy
import csv
import html
import io
import pickle
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .bdc import Entree
from .statuts_especes import REGIONS
from .taxref import Index, normaliser

#: Domaines biogéographiques d'Occitanie, dans la notation du classeur des
#: mammifères — « Oui (MC, MED, SO) » —, et dans son ordre alphabétique.
DOMAINES_OCCITANIE = (
    ("massif central", "MC"),
    ("méditerranéenne", "MED"),
    ("pyrénées", "PYR"),
    ("sud-ouest", "SO"),
)

#: Zones du vecteur d'Auvergne-Rhône-Alpes. Aucun classeur ne suit encore ce
#: territoire : pas de notation à reprendre, on écrit les zones en clair.
ZONES_AURA = (
    ("massif central", "Massif central"),
    ("plaine rhodanienne", "Plaine rhodanienne"),
    ("alpine", "Alpin"),
    ("méditerranéenne", "Méditerranéen"),
)

#: Libellé d'en-tête d'un territoire, quand celui de BDC ne convient pas à une
#: colonne. Chacun se relit en libellé BDC par `classeurs.territoire_bdc` :
#: « PACA », que le classeur des mammifères emploie, ne se relit pas.
AFFICHAGE = {
    "Provence-Alpes-Côte-d'Azur": "Provence-Alpes-Côte d'Azur",
    "Centre": "Centre-Val de Loire",
    "Ile-de-France": "Île-de-France",
    "Pays-de-la-Loire": "Pays de la Loire",
}

#: Libellés de région connus, actuels et anciens — tout autre territoire de
#: BDC est d'outre-mer.
_REGIONS_CONNUES = {libelle for libelles in REGIONS.values() for libelle in libelles}


def _texte(brut) -> str:
    return " ".join(str(brut or "").split())


def _zones_aura(cle: str) -> list[str] | None:
    """Les zones qu'une clé du vecteur nomme, ou `None` si ce n'en est pas une."""
    zones = []
    for morceau in cle.split(","):
        bas = morceau.strip().lower().replace("–", "-")
        bas = re.sub(r"^continentale\s*-\s*", "", bas)
        nom = next((court for motif, court in ZONES_AURA if bas == motif), None)
        if nom is None:
            return None
        zones.append(nom)
    return zones


def _debut_de_zone(cle: str) -> bool:
    """Le texte est-il le début d'un nom de zone, coupé par BDC — « Alpin », « Méd » ?"""
    bas = " ".join(cle.lower().replace("–", "-").split())
    formes = [motif for motif, _ in ZONES_AURA]
    formes += [f"continentale - {motif}" for motif in formes]
    return bool(bas) and any(forme.startswith(bas) for forme in formes)


def _couper(texte: str) -> str:
    """Marque la fin d'un texte coupé, et referme ses parenthèses.

    « (si dortoi » → « (si dortoi…) ».
    """
    texte = texte.rstrip()
    return f"{texte}…" + ")" * max(0, texte.count("(") - texte.count(")"))


def _sans_parentheses(texte: str) -> str:
    """Le texte sans la parenthèse qui l'enveloppe tout entier.

    « (seulement les gîtes) » → « seulement les gîtes » ; « (a) et (b) » reste.
    """
    if not (texte.startswith("(") and texte.endswith(")")):
        return texte
    profondeur = 0
    for signe in texte[1:-1]:
        profondeur += (signe == "(") - (signe == ")")
        if profondeur < 0:
            return texte
    return texte[1:-1].strip() if profondeur == 0 else texte


def _etat_aura(etat: str, coupe: bool = False) -> tuple[bool, str]:
    """L'espèce compte-t-elle dans cette zone, et sous quelle condition ?

    La liste écrit ses rubriques derrière des tirets : « Déterminante : -
    nicheur (si sites de reproduction) - hivernant » rend « nicheur (si sites
    de reproduction), hivernant ». « Déterminante (seulement les gîtes) » rend
    « seulement les gîtes ». Jusqu'au 6 novembre 2026, la condition gardait
    son deux-points et son tiret, et perdait sa parenthèse fermante : « : -
    nicheur (si sites de reproduction ».

    BDC coupe parfois l'état (`coupe`) — « Déte », « Déterminante : -
    hivernant (si dortoi » — : c'est encore un oui, dont la condition finit
    par « … ».
    """
    etat = " ".join(etat.split())
    if etat.lower().startswith("non"):
        return False, ""
    mot = re.match(r"(?i)d[ée]t\w*", etat)
    if mot and "determinante".startswith(mot.group().lower().replace("é", "e")):
        etat = etat[mot.end():]
    precision = etat.strip().removeprefix(":").strip()
    if coupe:
        precision = _couper(precision)
    if precision.startswith("-"):
        rubriques = re.split(r"(?:^|\s)-\s", precision)
        return True, ", ".join(r.strip() for r in rubriques if r.strip())
    return True, _sans_parentheses(precision)


def _vecteur_aura(texte: str, coupee: bool = False) -> str | None | bool:
    """Condense un vecteur par zone ; `False` si le texte n'en est pas un.

    Les zones de même condition sont regroupées — « Massif central, Alpin :
    nicheur » —, et la condition reste seule quand elle vaut pour les quatre.

    Un vecteur que BDC a coupé (`coupee`) finit par « … », là où tombe la
    coupure : dans la condition d'une zone, ou après la dernière zone lue,
    quand c'est le nom de la suivante que la coupure a tranché.
    """
    fin_coupee = coupee and not texte.rstrip().endswith(";")
    suite_perdue = coupee and not fin_coupee
    morceaux = [m for m in texte.split(";") if m.strip()]
    paires = []
    for rang, morceau in enumerate(morceaux, 1):
        derniere = fin_coupee and rang == len(morceaux)
        cle, sep, etat = morceau.partition(":")
        if derniere and not sep and paires and _debut_de_zone(cle):
            suite_perdue = True
            break
        zones = _zones_aura(cle) if sep else None
        if zones is None:
            return False
        oui, precision = _etat_aura(etat, coupe=derniere)
        paires.extend((zone, oui, precision) for zone in zones)
    retenues = [(zone, precision) for zone, oui, precision in paires if oui]
    if not retenues:
        return "…" if coupee else None
    groupes: dict[str, list[str]] = {}
    for zone, precision in retenues:
        groupes.setdefault(precision, []).append(zone)
    if (not coupee and len(groupes) == 1
            and len({z for z, _ in retenues}) == len(ZONES_AURA)):
        return next(iter(groupes))
    rendus = [", ".join(zones) + (f" : {precision}" if precision else "")
              for precision, zones in groupes.items()]
    return " ; ".join(rendus + (["…"] if suite_perdue else []))


def _domaines_occitanie(texte: str) -> str | None:
    """« Déterminant Zone Sud-Ouest - Déterminant Massif Central » → « MC, SO »."""
    bas = texte.lower()
    if not bas.startswith("déterminant "):
        return None
    codes = []
    for motif, code in DOMAINES_OCCITANIE:
        if motif in bas:
            codes.append(code)
            bas = bas.replace(motif, " ")
    reste = re.sub(r"déterminant|\bzones?\b|\bet\b|[-,–]|\s", "", bas)
    return ", ".join(codes) if codes and not reste else None


def condition(brut, coupee: bool = False) -> str | None:
    """La réserve, ramenée à ce qu'elle restreint.

    Rend "" pour une détermination sans réserve, et `None` quand la ligne ne
    détermine rien : le vecteur d'Auvergne-Rhône-Alpes déclare parfois toutes
    ses zones « Non déterminante ». Une remarque coupée (`coupee`, voir
    `COUPURE_BDC`) finit par « … ».
    """
    texte = _texte(brut)
    if not texte:
        return ""
    vecteur = _vecteur_aura(texte, coupee)
    if vecteur is not False:
        return vecteur
    reserve = _domaines_occitanie(texte) or texte
    return _couper(reserve) if coupee else reserve


def departement_bdc(cd_sig: str) -> str:
    """« INSEED34 » → « 34 », « INSEED2A » → « 2A »."""
    return str(cd_sig or "").strip().removeprefix("INSEED")


def _citation(brut: str) -> str:
    return _texte(re.sub(r"<[^>]+>", "", html.unescape(brut or "")))


@dataclass
class Mention:
    """Ce que les listes d'un territoire disent d'un taxon.

    `regionale` porte les réserves des lignes saisies à la maille du
    territoire, `departements` celles des lignes départementales — "" pour
    une ligne sans réserve.
    """
    regionale: set[str] = field(default_factory=set)
    departements: dict[str, set[str]] = field(default_factory=dict)
    #: Les listes qui l'ont dit, pour ne citer que celles qui ont servi.
    documents: set[str] = field(default_factory=set)


@dataclass
class Listes:
    """Les listes déterminantes, rapportées chacune à son territoire."""
    mentions: dict[tuple[str, str], Mention] = field(default_factory=dict)
    #: Départements que couvrent les listes départementales d'un territoire.
    departements: dict[str, set[str]] = field(default_factory=dict)
    #: Références des listes d'un territoire, par document.
    sources: dict[str, dict[str, str]] = field(default_factory=dict)
    #: Lignes écartées, par motif.
    ecartees: Counter = field(default_factory=Counter)

    def _mention(self, cd_ref: str, territoire: str) -> Mention:
        return self.mentions.setdefault((cd_ref, territoire), Mention())

    def territoires(self) -> list[str]:
        return sorted({t for _, t in self.mentions})

    def taxons(self, territoire: str) -> set[str]:
        return {cd for cd, t in self.mentions if t == territoire}

    def cellule(self, cd_ref: str, territoire: str) -> str:
        """La valeur à écrire, dans la convention des classeurs ; "" si rien.

        « Oui » quand l'espèce compte sur tout le territoire sans réserve,
        sinon « Oui (…) » avec ce qui la restreint : départements, domaines,
        conditions.
        """
        mention = self.mentions.get((cd_ref, territoire))
        if mention is None:
            return ""
        if mention.regionale:
            reserves = ([] if "" in mention.regionale
                        else sorted(mention.regionale))
            return _oui(reserves)

        # Une ligne sans réserve l'emporte, dans un département, sur une
        # autre liste qui en poserait une.
        par_departement = {d: (frozenset() if "" in r else frozenset(r))
                           for d, r in mention.departements.items()}
        tous = self.departements.get(territoire, set())
        entier = set(par_departement) >= tous
        variantes = set(par_departement.values())
        if len(variantes) == 1:
            reserves = sorted(next(iter(variantes)))
            portee = [] if entier else [_departements(par_departement)]
            return _oui(portee + reserves)
        groupes: dict[frozenset, list[str]] = {}
        for d, r in par_departement.items():
            groupes.setdefault(r, []).append(d)
        morceaux = []
        for reserves, deps in sorted(groupes.items(),
                                     key=lambda g: sorted(g[1])[0]):
            libelle = _departements(dict.fromkeys(deps))
            morceaux.append(f"{libelle} : {', '.join(sorted(reserves))}"
                            if reserves else libelle)
        return _oui(morceaux)

    def citations(self, territoire: str, cd_refs=None) -> list[str]:
        """Les listes d'un territoire ; celles qui portent ces taxons, si on les donne."""
        sources = self.sources.get(territoire, {})
        if cd_refs is None:
            return sorted(sources.values())
        documents = set()
        for cd in cd_refs:
            mention = self.mentions.get((cd, territoire))
            if mention:
                documents |= mention.documents
        return sorted({sources[d] for d in documents if d in sources})


def _departements(deps) -> str:
    return "dép. " + ", ".join(sorted(deps))


def _oui(morceaux: list[str]) -> str:
    return f"Oui ({' ; '.join(morceaux)})" if morceaux else "Oui"


def _territoire_du_document(departements: Counter) -> tuple[str, set[str]]:
    """Le territoire qu'une liste départementale couvre, et ses départements.

    La région actuelle qui en rassemble le plus ; puis l'ancienne région si
    tous ses départements y tiennent et qu'elle est plus petite.
    """
    actuelles = Counter()
    for dep, n in departements.items():
        actuelles[REGIONS[dep][0]] += n
    region = actuelles.most_common(1)[0][0]
    retenus = {d for d in departements if REGIONS[d][0] == region}
    anciennes = {REGIONS[d][1] if len(REGIONS[d]) > 1 else region
                 for d in retenus}
    return (anciennes.pop() if len(anciennes) == 1 else region), retenus


#: BDC-Statuts coupe certaines remarques à 255 caractères : 385 lignes
#: déterminantes en ont exactement 255, aucune de 256 à 261. La coupure vient
#: de l'import de six listes, dont celle d'Auvergne-Rhône-Alpes (348 lignes) ;
#: d'autres listes portent des remarques plus longues. Le texte perdu ne se
#: retrouve que dans la liste d'origine.
COUPURE_BDC = 255


def _coupee(remarque: str) -> bool:
    """BDC a-t-il coupé cette remarque ?

    À 255 caractères ; ou à 254, quand la coupure est tombée sur un espace
    que l'export a retiré — une parenthèse restée ouverte le dit alors :
    « … - hivernant (si ». Trois remarques de la liste d'Auvergne-Rhône-Alpes
    sont dans ce cas ; une quatrième de 254 caractères est entière.
    """
    n = len(remarque)
    return n == COUPURE_BDC or (n == COUPURE_BDC - 1
                                and remarque.count("(") > remarque.count(")"))


def depuis_bdc(archive: Path, condenser=None) -> Listes:
    """Lit les lignes `ZDET` de l'archive BDC-Statuts, métropole seulement.

    `condenser` ramène chaque remarque à sa réserve : `condition` par défaut.
    `outils/corriger_conditions.py` y passe celle du 1er novembre 2026, pour
    reconnaître les cases qu'elle a écrites.
    """
    condenser = condenser or condition
    listes = Listes()
    lignes_departementales = []
    par_document: dict[str, Counter] = {}
    citations: dict[str, str] = {}

    zf = zipfile.ZipFile(archive)
    membre = next(n for n in zf.namelist()
                  if n.lower().endswith(".csv") and "types" not in n.lower())
    with zf.open(membre) as flux:
        texte = io.TextIOWrapper(flux, encoding="utf-8", errors="replace",
                                 newline="")
        for ligne in csv.DictReader(texte):
            if (ligne.get("CD_TYPE_STATUT") or "").strip() != "ZDET":
                continue
            cd_ref = (ligne.get("CD_REF") or "").strip()
            niveau = (ligne.get("NIVEAU_ADMIN") or "").strip()
            document = (ligne.get("CD_DOC") or "").strip()
            remarque = ligne.get("RQ_STATUT") or ""
            reserve = condenser(remarque, coupee=_coupee(remarque))
            if reserve is None:
                listes.ecartees["aucune zone déterminante"] += 1
                continue
            citations.setdefault(document, _citation(ligne.get("FULL_CITATION")))
            if niveau == "Département":
                dep = departement_bdc(ligne.get("CD_SIG"))
                if dep not in REGIONS:
                    listes.ecartees["outre-mer"] += 1
                    continue
                par_document.setdefault(document, Counter())[dep] += 1
                lignes_departementales.append((cd_ref, document, dep, reserve))
            elif niveau in ("Région", "Ancienne région"):
                territoire = (ligne.get("LB_ADM_TR") or "").strip()
                if territoire not in _REGIONS_CONNUES:
                    listes.ecartees["outre-mer"] += 1
                    continue
                mention = listes._mention(cd_ref, territoire)
                mention.regionale.add(reserve)
                mention.documents.add(document)
                listes.sources.setdefault(territoire, {})[document] = citations[document]
            else:
                listes.ecartees["outre-mer"] += 1

    territoire_de: dict[str, tuple[str, set[str]]] = {}
    for document, departements in par_document.items():
        territoire, retenus = _territoire_du_document(departements)
        territoire_de[document] = (territoire, retenus)
        listes.departements.setdefault(territoire, set()).update(retenus)
        listes.sources.setdefault(territoire, {})[document] = citations[document]

    for cd_ref, document, dep, reserve in lignes_departementales:
        territoire, retenus = territoire_de[document]
        if dep not in retenus:
            listes.ecartees[f"département hors du territoire de sa liste "
                            f"({dep} dans une liste {territoire})"] += 1
            continue
        mention = listes._mention(cd_ref, territoire)
        mention.departements.setdefault(dep, set()).add(reserve)
        mention.documents.add(document)
    return listes


def apparier_nom_valide(index: Index, nom: str) -> str | None:
    """Le cd_ref d'un nom scientifique d'une liste officielle, ou `None`.

    Un appariement exact suffit d'ordinaire. Mais TaxRef range parfois le nom
    parmi les synonymes d'une autre espèce : « Certhia familiaris » désigne
    aussi, chez lui, un synonyme du Grimpereau américain, et « Muscicapa
    striata » un synonyme de la Paruline rayée. Une liste officielle écrit le
    nom valide : on retient le candidat dont c'est le nom.
    """
    appariement = index.apparier(nom)
    if appariement.sur:
        return appariement.cd_ref
    if appariement.statut != "ambigu":
        return None
    forme = normaliser(Index._sans_auteur(nom))
    exacts = {cd for cd in index.sci.get(forme, [])
              if cd in index.taxons and normaliser(index.taxons[cd].lb_nom) == forme}
    return exacts.pop() if len(exacts) == 1 else None


def ajouter_export_inpn(listes: Listes, chemin: Path, territoire: str,
                        index: Index, reference: str) -> Counter:
    """Ajoute l'export CSV d'une liste régionale, tel que l'INPN le publie.

    L'export n'a pas de CD_NOM : chaque nom est apparié à TaxRef par
    `apparier_nom_valide`. Les départements sont ceux que la liste donne, en
    codes ; ceux d'un autre territoire sont écartés.
    """
    comptes = Counter()
    with open(chemin, encoding="utf-8-sig", newline="") as f:
        for ligne in csv.DictReader(f, delimiter=";"):
            nom = _texte(ligne.get("Espèce de référence"))
            if not nom:
                continue
            cd_ref = apparier_nom_valide(index, nom)
            if cd_ref is None:
                comptes["nom non apparié"] += 1
                continue
            reserve = condition(ligne.get("Condition déterminance"))
            if reserve is None:
                comptes["aucune zone déterminante"] += 1
                continue
            deps = [d.strip().zfill(2) for d in
                    str(ligne.get("Département") or "").split(",") if d.strip()]
            retenus = [d for d in deps
                       if d in REGIONS and REGIONS[d][0] == territoire]
            if not retenus:
                comptes["aucun département du territoire"] += 1
                continue
            mention = listes._mention(cd_ref, territoire)
            for d in retenus:
                mention.departements.setdefault(d, set()).add(reserve)
            mention.documents.add(f"export:{chemin.name}")
            listes.departements.setdefault(territoire, set()).update(retenus)
            comptes["retenue"] += 1
    listes.sources.setdefault(territoire, {})[f"export:{chemin.name}"] = reference
    return comptes


# ═════════════════════════════════════════════ pour le prédiag et la veille

#: Version du format du cache. À incrémenter dès que ce qu'il garde change :
#: il est validé par la version de BDC, qui ne bouge pas quand c'est notre
#: code qui change — même garde-fou que `bdc.FORMAT`. 2 : la condensation
#: d'Auvergne-Rhône-Alpes corrigée, et les remarques coupées marquées
#: (6 novembre 2026).
FORMAT = 2


def charger(archive: Path, version: str, cache: Path | None = None) -> Listes:
    """`depuis_bdc`, gardé sur disque.

    Relire l'archive prend une vingtaine de secondes, à chaque ouverture de
    l'outil sans ce cache. Il garde des tables plutôt que des objets : une
    `Mention` qui gagnerait un champ se relit encore, une qui en perdrait un
    fait reconstruire.
    """
    if cache and cache.exists():
        try:
            donnees = pickle.loads(cache.read_bytes())
            if (donnees.get("version") == version
                    and donnees.get("format") == FORMAT):
                return Listes(
                    mentions={cle: Mention(regionale=r, departements=d,
                                           documents=docs)
                              for cle, (r, d, docs) in donnees["mentions"].items()},
                    departements=donnees["departements"],
                    sources=donnees["sources"],
                    ecartees=Counter(donnees["ecartees"]),
                )
        except Exception:  # noqa: BLE001
            pass
    listes = depuis_bdc(archive)
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(pickle.dumps({
            "version": version, "format": FORMAT,
            "mentions": {cle: (m.regionale, m.departements, m.documents)
                         for cle, m in listes.mentions.items()},
            "departements": listes.departements,
            "sources": listes.sources,
            "ecartees": dict(listes.ecartees),
        }))
    return listes


#: Ce qu'un classeur écrit pour une espèce déterminante sans réserve, et pour
#: une espèce qui ne l'est pas. Mesuré sur les six classeurs : 2 594 « Oui »,
#: 99 « X », trois « Oui (…) » chez les mammifères, et aucun « Non ».
_OUI = {"oui", "x"}
_NON = {"non", "0", "-", "n"}


def _forme(valeur) -> str:
    """Forme comparable d'une cellule : « Oui (MC,SO) » vaut « Oui (MC, SO) »."""
    return re.sub(r"\s+", "", str(valeur or "")).lower()


class Statuts:
    """Les listes, interrogées comme `bdc.Statuts` — pour le seul type ZDET.

    C'est par cette interface — `couvre`, `entrees`, `rendu` — que le
    prédiagnostic lit un statut sans savoir d'où il vient (voir
    `reference.AvecRepli`). L'index de `bdc` ne pouvait pas tenir ce rôle : il
    range chaque ligne sous son territoire, et les listes saisies au
    département s'y trouvent sous « Hérault » ou « Ariège », qu'aucun tableau
    n'interroge. Il ne rendait donc, pour « Occitanie », que les lignes
    régionales : à Bédarieux, les 191 oiseaux sortaient sans un statut ZNIEFF,
    quand la liste d'Occitanie de 2021 en porte 56.

    La valeur est la cellule qu'écrirait un classeur — « Oui », « Oui (MC,
    SO) », « Oui (dép. 09, 31) » — : elle tient lieu de code et de rendu,
    comme dans `reference.Reference`.
    """

    def __init__(self, listes: Listes):
        self.listes = listes
        self._territoires = set(listes.territoires())
        #: Territoires dont une liste est saisie à la maille régionale : elle
        #: en couvre chaque département.
        self._regionaux = {t for (_, t), mention in listes.mentions.items()
                           if mention.regionale}
        #: Départements du projet, quand `pour` les a donnés.
        self.departements: frozenset[str] = frozenset()

    def pour(self, departements) -> "Statuts":
        """Les mêmes listes, pour un projet : celles qui couvrent l'un de ses départements.

        Une liste ne couvre pas toujours tout son territoire, et BDC le dit :
        celle de Midi-Pyrénées (2004) n'a aucune ligne pour le Tarn, celle des
        Hauts-de-France aucune pour le Nord. Elles ne servent donc pas un
        projet tarnais ou nordiste, même là où elles porteraient plus
        d'espèces de son tableau que la liste qui le couvre.

        La restriction vaut pour tout le tableau, pas seulement pour le choix
        de son territoire : un classeur qui a la colonne « DZ Midi-Pyrénées »
        fait concourir ce territoire, et sans cette restriction les espèces
        qu'il ne porte pas y prendraient la liste de 2004.
        """
        vue = copy.copy(self)
        vue.departements = frozenset(str(d).strip().upper() for d in departements)
        return vue

    def _couvre_departement(self, territoire: str, departement: str) -> bool:
        if (territoire in self._regionaux
                and territoire in REGIONS.get(departement, ())):
            return True
        return departement in self.listes.departements.get(territoire, ())

    def couvre(self, type_statut: str, territoire: str) -> bool:
        if type_statut != "ZDET" or territoire not in self._territoires:
            return False
        return not self.departements or any(
            self._couvre_departement(territoire, d) for d in self.departements)

    def entrees(self, cd_ref: str, type_statut: str,
                territoire: str) -> list[Entree]:
        if not self.couvre(type_statut, territoire):
            return []
        valeur = self.listes.cellule(str(cd_ref).strip(), territoire)
        return [Entree(code=valeur, rendu=valeur, periode="")] if valeur else []

    def rendu(self, cd_ref: str, type_statut: str, territoire: str,
              periode: str | None = None,
              filtre: tuple[str, ...] | None = None) -> str:
        entrees = self.entrees(cd_ref, type_statut, territoire)
        if periode:
            entrees = [e for e in entrees if e.periode == periode]
        if filtre:
            entrees = [e for e in entrees if e.rendu in filtre]
        return entrees[0].rendu if entrees else ""

    @staticmethod
    def ecart(sienne: str, cellule: str) -> str | None:
        """Ce qui sépare la valeur d'un classeur de la cellule des listes.

        `None` quand elles s'accordent : « X » dit la même chose que « Oui ».
        La réserve, elle, compte — un « Oui » face à « Oui (SO) » affirme
        l'espèce déterminante sur tout le territoire, là où la liste la
        restreint au domaine sud-ouest. Les deux valeurs sont renseignées.
        """
        sien, notre = _forme(sienne), _forme(cellule)
        if sien == notre or (sien in _OUI and notre in _OUI):
            return None
        if sien in _NON:
            return "ta case dit non"
        if sien in _OUI:
            return "la liste restreint"
        if notre in _OUI:
            return "la liste ne pose pas de réserve"
        return "réserve différente"
