"""Tableaux d'espèces par groupe, aux colonnes du prédiagnostic de référence.

Le prédiagnostic consacre une sous-section à chaque groupe, et chaque groupe a
ses colonnes. Un tableau de flore porte « Protection régionale », un tableau
d'avifaune porte « Annexe I de la Directive Oiseaux » et trois colonnes de
liste rouge nationale ; les intervertir ferait un document que personne de la
filière ne reconnaîtrait.

Trois formes suffisent à couvrir le document :

======================  ================================================
flore                   PN · PR · LRN · LRR · Directive Habitats
avifaune                DO I · LRE · PN · LRN nicheurs/hivernants/de
                        passage · LRR · Reproduction
faune (tous les autres) DH II · LRE · PN · LRN · LRR
======================  ================================================

**Le groupe ne se demande pas, il se déduit.** `GROUP3_INPN` de TaxRef porte
précisément le découpage de la filière — Odonates, Orthoptères, Lépidoptères,
Araignées — là où `GROUP2_INPN` range tout sous « Insectes ». Faire choisir le
groupe à chaque dépôt serait à la fois pénible et faux : un export de faune
mêle les groupes.

**La région n'est pas celle qu'on croit.** Les listes rouges régionales ont été
publiées avant et après la fusion de 2016, et BDC porte les deux découpages.
Le prédiagnostic de référence, pour un projet ardéchois, écrit « Liste rouge
AURA » au-dessus de son tableau d'avifaune et « Liste rouge Rhône-Alpes »
au-dessus de ses odonates — parce que la liste régionale des odonates n'a
jamais été refaite à l'échelle de la nouvelle région. On choisit donc le
découpage **par groupe, sur la donnée** : celui des deux qui couvre le plus
d'espèces du tableau.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import bdc
from .sortie_word import Colonne
from .taxref import Taxon

#: Catégories de liste rouge qui font un enjeu. `DD` (données insuffisantes),
#: `LC` (préoccupation mineure), `NA` et `NE` n'en font pas.
CATEGORIES_ENJEU = {"NT", "VU", "EN", "CR", "CR*", "RE", "EX"}

#: Découpage régional : région actuelle, puis l'ancienne région du département.
#: Les libellés sont **ceux de BDC**, accents et traits d'union compris :
#: « Ile-de-France » sans accent, « Centre » et non « Centre-Val de Loire ».
#: Les retaper proprement ferait zéro statut régional, silencieusement.
_DECOUPAGE: tuple[tuple[str, dict[str, str]], ...] = (
    ("Auvergne-Rhône-Alpes", {"Auvergne": "03 15 43 63",
                              "Rhône-Alpes": "01 07 26 38 42 69 73 74"}),
    ("Bourgogne-Franche-Comté", {"Bourgogne": "21 58 71 89",
                                 "Franche-Comté": "25 39 70 90"}),
    ("Bretagne", {"": "22 29 35 56"}),
    ("Centre", {"": "18 28 36 37 41 45"}),
    ("Corse", {"": "2A 2B"}),
    ("Grand Est", {"Alsace": "67 68",
                   "Champagne-Ardenne": "08 10 51 52",
                   "Lorraine": "54 55 57 88"}),
    ("Hauts-de-France", {"Nord-Pas-de-Calais": "59 62",
                         "Picardie": "02 60 80"}),
    ("Ile-de-France", {"": "75 77 78 91 92 93 94 95"}),
    ("Normandie", {"Basse-Normandie": "14 50 61",
                   "Haute-Normandie": "27 76"}),
    ("Nouvelle-Aquitaine", {"Aquitaine": "24 33 40 47 64",
                            "Limousin": "19 23 87",
                            "Poitou-Charentes": "16 17 79 86"}),
    ("Occitanie", {"Languedoc-Roussillon": "11 30 34 48 66",
                   "Midi-Pyrénées": "09 12 31 32 46 65 81 82"}),
    ("Pays-de-la-Loire", {"": "44 49 53 72 85"}),
    ("Provence-Alpes-Côte-d'Azur", {"": "04 05 06 13 83 84"}),
)


def _regions() -> dict[str, tuple[str, ...]]:
    table: dict[str, tuple[str, ...]] = {}
    for actuelle, anciennes in _DECOUPAGE:
        for ancienne, departements in anciennes.items():
            for departement in departements.split():
                candidats = [actuelle]
                if ancienne and ancienne != actuelle:
                    candidats.append(ancienne)
                table[departement] = tuple(candidats)
    return table


#: Département → libellés de région à essayer, du plus récent au plus ancien.
REGIONS = _regions()

#: Abréviations d'usage dans les en-têtes, pour ne pas écrire « Liste rouge
#: Provence-Alpes-Côte-d'Azur » sur une colonne de deux centimètres.
ABREGE = {
    "Auvergne-Rhône-Alpes": "AURA",
    "Provence-Alpes-Côte-d'Azur": "PACA",
    "Bourgogne-Franche-Comté": "BFC",
    "Nord-Pas-de-Calais": "NPdC",
}


@dataclass(frozen=True)
class GroupePrediag:
    """Un groupe du prédiagnostic : son intitulé et la forme de son tableau."""
    cle: str
    libelle: str
    forme: str                      # flore | avifaune | faune
    #: Valeurs de GROUP3_INPN puis de GROUP2_INPN qui mènent à ce groupe.
    etiquettes: tuple[str, ...]
    #: Formulation du dénombrement : « 308 espèces de flore sont recensées ».
    complement: str = ""


#: Groupes dans l'ordre du prédiagnostic de référence. Les derniers n'y
#: figurent pas mais remontent dans les dépôts, et un taxon sans groupe
#: disparaîtrait du document sans que personne le voie.
GROUPES: tuple[GroupePrediag, ...] = (
    GroupePrediag("flore", "Flore", "flore",
                  ("Angiospermes", "Gymnospermes", "Ptéridophytes", "Mousses",
                   "Hépatiques et Anthocérotes", "Lichens", "Algues",
                   "Chlorophytes et Charophytes", "Rhodophytes", "Ochrophytes"),
                  "de flore"),
    GroupePrediag("oiseaux", "Avifaune", "avifaune", ("Oiseaux",), "d'oiseaux"),
    GroupePrediag("amphibiens", "Amphibiens", "faune", ("Amphibiens",),
                  "d'amphibiens"),
    GroupePrediag("reptiles", "Reptiles", "faune", ("Reptiles",), "de reptiles"),
    # Les chiroptères avant les mammifères : ils en font partie, mais le
    # prédiagnostic externe leur consacre une section entière, et l'ordre de
    # ce tuple décide lequel l'emporte.
    GroupePrediag("chiropteres", "Chiroptères", "faune", ("Chiroptera",),
                  "de chiroptères"),
    GroupePrediag("mammiferes", "Mammifères", "faune", ("Mammifères",),
                  "de mammifères"),
    GroupePrediag("odonates", "Odonates", "faune", ("Odonates",), "d'odonates"),
    GroupePrediag("lepidopteres", "Papillons", "faune", ("Lépidoptères",),
                  "de papillons"),
    GroupePrediag("orthopteres", "Orthoptères", "faune", ("Orthoptères",),
                  "d'orthoptères"),
    GroupePrediag("coleopteres", "Coléoptères", "faune", ("Coléoptères",),
                  "de coléoptères"),
    GroupePrediag("araignees", "Araignées", "faune", ("Araignées", "Arachnides"),
                  "d'araignées"),
    GroupePrediag("poissons", "Poissons", "faune", ("Poissons",), "de poissons"),
    GroupePrediag("insectes", "Autres insectes", "faune",
                  ("Hyménoptères", "Diptères", "Hémiptères", "Insectes"),
                  "d'insectes"),
    GroupePrediag("autres", "Autres groupes", "faune", (), "d'espèces"),
)

#: Les trois volets que le prédiagnostic externe traite dans son état
#: initial. Les listes détaillées, elles, vont toutes en annexe.
FAMILLES_ETUDE: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("avifaune", "Avifaune", ("oiseaux",)),
    ("chiropteres", "Chiroptères", ("chiropteres",)),
    ("autre_faune", "Autre faune",
     ("mammiferes", "amphibiens", "reptiles", "odonates", "lepidopteres",
      "orthopteres", "coleopteres", "araignees", "poissons", "insectes",
      "flore", "autres")),
)


def famille_etude(cle_groupe: str) -> str:
    """Volet de l'état initial auquel ce groupe se rattache."""
    for cle, _, groupes in FAMILLES_ETUDE:
        if cle_groupe in groupes:
            return cle
    return "autre_faune"


_PAR_ETIQUETTE = {etiquette: groupe
                  for groupe in GROUPES for etiquette in groupe.etiquettes}
_PAR_CLE = {groupe.cle: groupe for groupe in GROUPES}


def groupe_de(taxon: Taxon | None) -> GroupePrediag:
    """Groupe du prédiagnostic auquel ce taxon appartient.

    `GROUP3_INPN` d'abord, puisqu'il distingue odonates, papillons et
    orthoptères ; `GROUP2_INPN` ensuite, qu'il porte « Oiseaux » ou
    « Angiospermes ». Faute des deux, « Autres groupes » : un taxon sans
    rubrique sortirait du document sans que personne s'en aperçoive.
    """
    if taxon is None:
        return _PAR_CLE["autres"]
    # L'ordre taxonomique d'abord : c'est le seul endroit où les chiroptères
    # se distinguent, « Mammifères » dans GROUP2_INPN et « Autres » dans
    # GROUP3_INPN les noyant parmi les autres mammifères.
    for etiquette in (getattr(taxon, "ordre", ""),
                      getattr(taxon, "groupe3", ""), taxon.groupe):
        trouve = _PAR_ETIQUETTE.get((etiquette or "").strip())
        if trouve is not None:
            return trouve
    return _PAR_CLE["autres"]


def groupe_par_cle(cle: str) -> GroupePrediag:
    return _PAR_CLE.get(cle, _PAR_CLE["autres"])


# ------------------------------------------------------------------ territoire

def territoire_regional(statuts: bdc.Statuts, cd_refs: list[str],
                        departements: list[str],
                        type_statut: str = "LRR") -> str:
    """Découpage régional à retenir, choisi sur la donnée.

    Les deux libellés possibles — nouvelle et ancienne région — sont confrontés
    aux taxons du tableau, et on garde celui qui en couvre le plus. C'est ce
    qui donne « AURA » pour l'avifaune et « Rhône-Alpes » pour les odonates
    sans l'écrire en dur nulle part.
    """
    candidats: list[str] = []
    for departement in departements:
        for libelle in REGIONS.get(str(departement).strip().upper(), ()):
            if libelle not in candidats:
                candidats.append(libelle)
    if not candidats:
        return ""

    meilleur, score_meilleur = "", 0
    for candidat in candidats:
        if not statuts.couvre(type_statut, candidat):
            continue
        score = sum(1 for cd in cd_refs
                    if statuts.entrees(cd, type_statut, candidat))
        # À égalité, l'ordre des candidats tranche : la région actuelle
        # d'abord, ce qui est le cas le plus fréquent.
        if score > score_meilleur:
            meilleur, score_meilleur = candidat, score
    if meilleur:
        return meilleur
    # Aucune espèce du tableau n'a de statut régional : on garde quand même un
    # libellé couvert, pour que l'en-tête de colonne dise de quelle liste il
    # s'agit plutôt que de rester muet.
    for candidat in candidats:
        if statuts.couvre(type_statut, candidat):
            return candidat
    return ""


# -------------------------------------------------------------------- colonnes

@dataclass(frozen=True)
class Lecture:
    """Où lire un statut, et ce qu'on en retient.

    `filtre` existe parce qu'une colonne nomme souvent une annexe précise. La
    colonne « Annexe II de la Directive Habitats » ne doit pas afficher
    « Annexe IV » sous prétexte que le taxon y figure aussi : le Castor est aux
    deux annexes, et le prédiagnostic de référence n'écrit que la II.
    """
    type_statut: str
    territoire: str
    periode: str = ""
    filtre: tuple[str, ...] = ()
    #: Relire sans filtre de période si la période demandée ne donne rien.
    #:
    #: Vrai pour la **seule** colonne régionale de l'avifaune : le tableau de
    #: référence n'en a qu'une, et c'est l'évaluation des nicheurs qui y
    #: figure — mais toutes les listes régionales ne distinguent pas les
    #: périodes, et la colonne resterait vide pour celles-là.
    #:
    #: Faux pour les trois colonnes nationales, et ce n'est pas un détail :
    #: une case « Hivernants » vide dit qu'il n'existe pas d'évaluation
    #: hivernale. Y reporter la valeur des nicheurs serait inventer un statut.
    repli_sans_periode: bool = False


@dataclass
class Jeu:
    """Les colonnes d'un groupe et de quoi remplir ses lignes."""
    groupe: GroupePrediag
    colonnes: list[Colonne]
    region: str = ""
    #: Clés de statut à lire, par colonne :
    #: (type, territoire, période, rendus acceptés — vide pour tous).
    lectures: dict[str, Lecture] = field(default_factory=dict)


def _entete_regional(prefixe: str, region: str) -> str:
    if not region:
        return f"{prefixe} régionale"
    return f"{prefixe} {ABREGE.get(region, region)}"


def jeu(groupe: GroupePrediag, statuts: bdc.Statuts, cd_refs: list[str],
        departements: list[str]) -> Jeu:
    """Colonnes et lectures du tableau d'un groupe."""
    region = territoire_regional(statuts, cd_refs, departements)
    region_pr = territoire_regional(statuts, cd_refs, departements, "PR")

    colonnes: list[Colonne] = [
        Colonne("Nom commun", "nom_commun", largeur_cm=3.6),
        Colonne("Nom scientifique", "nom_scientifique", italique=True,
                largeur_cm=3.6),
    ]
    lectures: dict[str, Lecture] = {}

    def ajouter(titre: str, cle: str, type_statut: str, territoire: str,
                periode: str = "", largeur: float = 1.9,
                filtre: tuple[str, ...] = (), repli: bool = False) -> None:
        colonnes.append(Colonne(titre, cle, centree=True, largeur_cm=largeur))
        lectures[cle] = Lecture(type_statut, territoire, periode, filtre,
                                repli)

    if groupe.forme == "flore":
        ajouter("Protection nationale", "pn", "PN", "France métropolitaine")
        ajouter("Protection régionale", "pr", "PR", region_pr)
        ajouter("Liste rouge nationale", "lrn", "LRN", "France métropolitaine")
        ajouter(_entete_regional("Liste rouge", region), "lrr", "LRR", region)
        ajouter("Directive Habitats", "dh", "DH", "France métropolitaine",
                filtre=("Annexe II", "Annexe IV"))

    elif groupe.forme == "avifaune":
        ajouter("Annexe I de la Directive Oiseaux", "do", "DO",
                "France métropolitaine", largeur=2.1, filtre=("Annexe I",))
        ajouter("Liste rouge Europe", "lre", "LRE", "Europe")
        ajouter("Protection nationale", "pn", "PN", "France métropolitaine")
        # Les trois périodes du cycle annuel, que BDC porte dans RQ_STATUT.
        ajouter("Nicheurs", "lrn_nicheur", "LRN", "France métropolitaine",
                bdc.PERIODE_NICHEUR, largeur=1.5)
        ajouter("Hivernants", "lrn_hivernant", "LRN", "France métropolitaine",
                bdc.PERIODE_HIVERNANT, largeur=1.5)
        ajouter("De passage", "lrn_passage", "LRN", "France métropolitaine",
                bdc.PERIODE_PASSAGE, largeur=1.5)
        # Une seule colonne régionale, comme dans le tableau de référence,
        # et c'est l'évaluation des nicheurs. Sans ce filtre, BDC rend les
        # périodes jointes — « NA, NT » pour l'Alouette des champs, là où le
        # document de référence porte « NT ».
        ajouter(_entete_regional("Liste rouge", region), "lrr", "LRR", region,
                bdc.PERIODE_NICHEUR, repli=True)
        # Laissée vide : savoir si l'espèce se reproduit sur l'aire d'étude
        # relève du terrain, pas du référentiel.
        colonnes.append(Colonne("Reproduction", "reproduction", centree=True,
                                largeur_cm=1.7))

    else:
        ajouter("Annexe II de la Directive Habitats", "dh", "DH",
                "France métropolitaine", largeur=2.1, filtre=("Annexe II",))
        ajouter("Liste rouge Europe", "lre", "LRE", "Europe")
        ajouter("Protection nationale", "pn", "PN", "France métropolitaine")
        ajouter("Liste rouge France", "lrn", "LRN", "France métropolitaine")
        ajouter(_entete_regional("Liste rouge", region), "lrr", "LRR", region)

    return Jeu(groupe=groupe, colonnes=colonnes, region=region,
               lectures=lectures)


def ligne(jeu_groupe: Jeu, statuts: bdc.Statuts, cd_ref: str, nom_commun: str,
          nom_scientifique: str) -> dict:
    """Une ligne de tableau d'espèces, statuts résolus."""
    valeurs = {"nom_commun": nom_commun, "nom_scientifique": nom_scientifique,
               "reproduction": ""}
    for cle, lecture in jeu_groupe.lectures.items():
        if not lecture.territoire:
            valeurs[cle] = ""
            continue
        rendu = statuts.rendu(cd_ref, lecture.type_statut, lecture.territoire,
                              lecture.periode or None,
                              filtre=lecture.filtre or None)
        if not rendu and lecture.periode and lecture.repli_sans_periode:
            rendu = statuts.rendu(cd_ref, lecture.type_statut,
                                  lecture.territoire,
                                  filtre=lecture.filtre or None)
        valeurs[cle] = rendu
    return valeurs


def a_enjeu(jeu_groupe: Jeu, statuts: bdc.Statuts, cd_ref: str) -> bool:
    """L'espèce porte-t-elle un enjeu réglementaire ou patrimonial ?

    Le prédiagnostic de référence ne tabule pas toutes les espèces de la
    commune mais celles « à enjeu » — « 308 espèces de flore sont recensées
    dont 6 espèces à enjeu ». La règle retenue, qui est écrite dans le
    document produit pour qu'elle puisse être contestée :

    * protégée, au niveau national, régional ou départemental ;
    * inscrite à l'annexe II ou IV de la directive Habitats, ou à l'annexe I
      de la directive Oiseaux ;
    * classée NT, VU, EN, CR, RE ou EX sur une liste rouge ;
    * concernée par un plan national d'actions.

    `DD` et `LC` n'en font pas partie, ni les `NA` : une espèce non applicable
    sur une liste rouge n'est pas pour autant un enjeu.
    """
    for type_statut in ("PN", "PR"):
        territoire = next((l.territoire for l in jeu_groupe.lectures.values()
                           if l.type_statut == type_statut and l.territoire),
                          None)
        if territoire and statuts.entrees(cd_ref, type_statut, territoire):
            return True
    if statuts.entrees(cd_ref, "PNA", "France"):
        return True
    for annexe in statuts.entrees(cd_ref, "DH", "France métropolitaine"):
        if annexe.rendu in ("Annexe II", "Annexe IV"):
            return True
    if jeu_groupe.groupe.forme == "avifaune":
        for annexe in statuts.entrees(cd_ref, "DO", "France métropolitaine"):
            if annexe.rendu == "Annexe I":
                return True
    for type_statut, territoire in (("LRE", "Europe"),
                                    ("LRN", "France métropolitaine"),
                                    ("LRR", jeu_groupe.region)):
        if not territoire:
            continue
        for entree in statuts.entrees(cd_ref, type_statut, territoire):
            if entree.code in CATEGORIES_ENJEU:
                return True
    return False
