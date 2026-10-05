"""Lecture de BDC-Statuts (INPN) : les statuts de référence, par cd_ref.

BDC-Statuts regroupe ce que Marie va chercher à la main sur Légifrance et chez
l'UICN. Ses types couvrent presque toutes les colonnes de ses classeurs :

    LRE  liste rouge européenne      PN   protection nationale
    LRN  liste rouge nationale       PR   protection régionale
    LRR  liste rouge régionale       PD   protection départementale
    LRM  liste rouge mondiale        DH   directive Habitats
    ZDET ZNIEFF déterminantes        DO   directive Oiseaux
    PNA  plan national d'actions

**Le code brut n'est pas ce qui s'écrit dans un tableau.** BDC stocke `NO3`
pour l'article 3 de la protection nationale, `CDH2` pour l'annexe II de la
directive Habitats, `CDO1` pour l'annexe I de la directive Oiseaux. Les
prédiagnostics écrivent « Art. 3 », « Annexe II », « Annexe I ». Chaque entrée
porte donc à la fois son code brut — que la veille compare aux classeurs — et
son **rendu**, ce qui s'écrit dans la cellule.

Les périodes, elles, sont bien dans BDC, contrairement à ce que cette
docstring affirmait : elles vivent dans `RQ_STATUT`, mêlées aux critères UICN.

    Alauda arvensis  NT  'pr. A2b - Nicheur'
    Alauda arvensis  LC  'Hivernant'
    Alauda arvensis  NA  'd - Visiteur'

Le tableau d'avifaune du prédiagnostic de référence porte pour cette espèce
« NT | LC | NAd » en nicheurs, hivernants et de passage : les trois colonnes
sont donc reproductibles à l'identique, et la lettre de `NAd` est le critère
qui précède la période. Une limite subsiste en revanche :

* **BDC ne dit pas de quelle édition vient un statut** : le champ source est
  vide sur les 5 831 entrées LRE. L'outil peut donc signaler un écart, jamais
  trancher qui a raison.
"""
from __future__ import annotations

import csv
import io
import pickle
import re
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

csv.field_size_limit(10 ** 7)

#: Version du format d'index. À incrémenter dès que `Entree` change : le cache
#: sur disque est validé par la version du référentiel, qui ne bouge pas quand
#: c'est notre code qui change. Sans ce garde-fou, un index construit par une
#: version antérieure se recharge et rend des cellules vides sans rien dire.
FORMAT = 4

#: Types de statuts exploités par la veille (les autres sont lus mais ignorés).
TYPES_SUIVIS = {"LRE", "LRN", "LRR", "LRM", "ZDET", "PN", "PR", "PD", "DH", "DO", "PNA"}

#: Territoires à interroger selon le type, du plus précis au plus général.
TERRITOIRES_FIXES = {
    "LRE": ("Europe",),
    "LRM": ("Monde",),
    "LRN": ("France métropolitaine", "France"),
    "PN": ("France métropolitaine", "France"),
    "DH": ("France métropolitaine",),
    "DO": ("France métropolitaine",),
    "PNA": ("France",),
    "ZDET": (),
}

_ARTICLE = re.compile(r"[Aa]rticle\s*(\d+)")
_ANNEXE = re.compile(r"[Aa]nnexe\s*([IVX]+(?:/\d)?)")
#: Critère UICN réduit à une lettre minuscule, qui suffixe les « NA ».
#: « b - Visiteur » donne NAb ; « pr. A2b - Nicheur » n'est pas un suffixe.
_CRITERE_NA = re.compile(r"^([a-z])(?:\s*-|\s*$)")

#: Critères « NA » qui ne s'écrivent pas, par alignement sur les livrables.
#:
#: « a » désigne une espèce introduite. Les prédiagnostics de référence
#: écrivent alors « NA » tout court : sur les 138 cellules « NA » du livrable
#: externe, 134 portent un suffixe b, c ou d, et les 4 nues sont les deux
#: seules espèces dont BDC donne le critère « a » — le surmulot et le Brun des
#: pélargoniums, tous deux introduits. Publier « NAa » faisait donc apparaître
#: un écart dans les comparaisons là où les deux documents disent la même
#: chose. Le code brut, lui, reste « NA » dans `Entree.code`, et la veille
#: ramène de toute façon tout « NA* » à « NA » (`vocabulaire.normaliser_code`).
CRITERES_NA_MUETS = frozenset({"a"})

#: Périodes du cycle annuel, telles que `RQ_STATUT` les nomme.
PERIODE_NICHEUR = "nicheur"
PERIODE_HIVERNANT = "hivernant"
PERIODE_PASSAGE = "passage"


def _periode(rq: str, citation: str = "") -> str:
    """Période du cycle annuel de ce statut, ou chaîne vide.

    Deux endroits la portent, et il faut les deux.

    `RQ_STATUT` la donne pour les listes rouges nationales, mêlée aux critères
    UICN : « Nicheur », « Hivernant », « d - Visiteur ».

    Les listes rouges **régionales** ne la portent pas là : leurs entrées ont un
    `RQ_STATUT` vide ou purement technique (« pr. A2b »), et la période est
    dans le titre du document cité. Le Grand Est a publié en 2024 deux listes
    distinctes — « Liste rouge des Oiseaux nicheurs du Grand Est » et « … des
    Oiseaux hivernants … » — et sans lire la citation, les deux valeurs
    revenaient jointes dans la même cellule : « NA, NT » pour l'Alouette des
    champs, là où le prédiagnostic de référence porte « NT ».
    """
    for texte in (rq, citation):
        bas = (texte or "").lower()
        if "nicheur" in bas:
            return PERIODE_NICHEUR
        if "hivernant" in bas:
            return PERIODE_HIVERNANT
        if "visiteur" in bas or "passage" in bas or "migrat" in bas:
            return PERIODE_PASSAGE
    return ""


def _rendu(type_statut: str, code: str, libelle: str, rq: str) -> str:
    """Ce qui s'écrit dans la cellule d'un tableau d'espèces.

    Les codes de BDC sont des identifiants de liste, pas des valeurs
    publiables : `NO3` désigne « la liste des oiseaux protégés sur l'ensemble
    du territoire, article 3 ». C'est l'article qu'on écrit.
    """
    if type_statut in ("DH", "DO"):
        trouve = _ANNEXE.search(libelle)
        return f"Annexe {trouve.group(1)}" if trouve else code
    if type_statut == "PN":
        trouve = _ARTICLE.search(libelle)
        return f"Art. {trouve.group(1)}" if trouve else "oui"
    if type_statut in ("PR", "PD"):
        # Les arrêtés régionaux et départementaux n'ont pas d'article qui
        # distingue des régimes : la protection est acquise ou non.
        return "oui"
    if type_statut in ("PNA", "ZDET"):
        return "oui"
    if code == "NA":
        # « Non applicable » se publie avec son critère : NAb, NAc, NAd — mais
        # pas NAa, voir CRITERES_NA_MUETS.
        trouve = _CRITERE_NA.match(rq.strip())
        critere = trouve.group(1) if trouve else ""
        return "NA" if critere in CRITERES_NA_MUETS else f"NA{critere}"
    return code


#: Valeur de tri des annexes, pour les joindre dans l'ordre de lecture.
_RANG_ANNEXE = {"I": 1, "II": 2, "II/1": 3, "II/2": 4, "III": 5, "III/1": 6,
                "III/2": 7, "IV": 8, "V": 9}


def _ordre_rendu(rendu: str) -> tuple[int, str]:
    if rendu.startswith("Annexe "):
        return (_RANG_ANNEXE.get(rendu[7:].strip(), 99), rendu)
    return (0, rendu)


@dataclass(frozen=True)
class Entree:
    """Un statut, tel qu'il se compare et tel qu'il s'écrit."""
    code: str         # CODE_STATUT brut : LC, NA, CDH2, NO3…
    rendu: str        # ce qui s'écrit dans la cellule : LC, NAd, Annexe II, Art. 3
    periode: str      # nicheur | hivernant | passage | "" (avifaune surtout)


@dataclass
class Statut:
    cd_ref: str
    type_statut: str         # LRE, LRR…
    territoire: str          # LB_ADM_TR : Europe, France, Normandie, Rhône…
    code: str                # LC, NT, VU, NO3, CDO1…
    libelle: str = ""


class Statuts:
    """Index des statuts BDC, interrogeable par (cd_ref, type, territoire)."""

    def __init__(self, table: dict[tuple[str, str, str], list[Entree]],
                 version: str, territoires: dict[str, set[str]]):
        self._table = table
        self.version = version
        self.territoires = territoires

    # ------------------------------------------------------------ construction

    @classmethod
    def construire(cls, archive: Path, membre: str, version: str) -> "Statuts":
        z = zipfile.ZipFile(archive)
        table: dict[tuple[str, str, str], list[Entree]] = defaultdict(list)
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
                rq = (ligne.get("RQ_STATUT") or "").strip()
                libelle = (ligne.get("LABEL_STATUT") or "").strip()
                citation = (ligne.get("FULL_CITATION") or "").strip()
                entree = Entree(code=code,
                                rendu=_rendu(type_statut, code, libelle, rq),
                                periode=_periode(rq, citation))
                cle = (cd_ref, type_statut, terr)
                if entree not in table[cle]:
                    table[cle].append(entree)
                territoires[type_statut].add(terr)

        return cls(dict(table), version, {k: set(v) for k, v in territoires.items()})

    @classmethod
    def charger(cls, archive: Path, membre: str, version: str,
                cache: Path | None = None) -> "Statuts":
        if cache and cache.exists():
            try:
                donnees = pickle.loads(cache.read_bytes())
                if (donnees.get("version") == version
                        and donnees.get("format") == FORMAT):
                    return cls(donnees["table"], version, donnees["territoires"])
            except Exception:  # noqa: BLE001
                pass
        index = cls.construire(archive, membre, version)
        if cache:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(pickle.dumps({
                "table": index._table, "version": version, "format": FORMAT,
                "territoires": index.territoires,
            }))
        return index

    # -------------------------------------------------------------- lecture

    def __len__(self) -> int:
        return len(self._table)

    def entrees(self, cd_ref: str, type_statut: str,
                territoire: str) -> list[Entree]:
        return self._table.get((str(cd_ref), type_statut, territoire), [])

    def codes(self, cd_ref: str, type_statut: str, territoire: str) -> list[str]:
        """Codes bruts connus pour ce taxon, ce type et ce territoire.

        Ce que la veille compare aux classeurs. Pour ce qui s'écrit dans un
        tableau, voir `rendu`.
        """
        vus: list[str] = []
        for entree in self.entrees(cd_ref, type_statut, territoire):
            if entree.code not in vus:
                vus.append(entree.code)
        return vus

    def code_unique(self, cd_ref: str, type_statut: str,
                    territoire: str) -> str | None:
        """Code unique, ou None si absent ou si BDC en porte plusieurs."""
        trouves = self.codes(cd_ref, type_statut, territoire)
        return trouves[0] if len(trouves) == 1 else None

    def rendu(self, cd_ref: str, type_statut: str, territoire: str,
              periode: str | None = None,
              filtre: tuple[str, ...] | None = None) -> str:
        """Ce qui s'écrit dans la cellule, pour une période donnée s'il y en a.

        `filtre` restreint aux rendus attendus par la colonne : une colonne
        « Annexe II » ne doit pas afficher l'annexe IV d'un taxon inscrit aux
        deux. Sans filtre, tout est joint — masquer une entrée reviendrait à
        publier une information incomplète.
        """
        entrees = self.entrees(cd_ref, type_statut, territoire)
        if periode:
            entrees = [e for e in entrees if e.periode == periode]
        if filtre:
            entrees = [e for e in entrees if e.rendu in filtre]
        rendus: list[str] = []
        for entree in entrees:
            if entree.rendu and entree.rendu not in rendus:
                rendus.append(entree.rendu)
        # Les annexes se lisent dans l'ordre : « Annexe II, Annexe IV », jamais
        # l'inverse. L'ordre du fichier source n'a aucune raison de l'être.
        return ", ".join(sorted(rendus, key=_ordre_rendu))

    def couvre(self, type_statut: str, territoire: str) -> bool:
        """BDC connaît-il ce couple type/territoire ?

        Permet de distinguer « BDC ne couvre pas la Normandie pour ce type »
        de « ce taxon n'y a pas de statut » — deux constats très différents.
        """
        return territoire in self.territoires.get(type_statut, set())

    def premier_territoire(self, type_statut: str,
                           candidats: tuple[str, ...] | list[str]) -> str:
        """Premier territoire que BDC couvre, parmi des candidats ordonnés.

        Les listes rouges régionales existent sous l'ancien et le nouveau
        découpage — « Rhône-Alpes » pour les odonates, « Auvergne-Rhône-Alpes »
        pour l'avifaune — et aucune règle ne dit lequel porte tel groupe. On
        essaie donc, dans l'ordre de préférence.
        """
        for candidat in candidats:
            if self.couvre(type_statut, candidat):
                return candidat
        return ""
