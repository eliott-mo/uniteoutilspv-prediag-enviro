"""Assemblage du prédiagnostic écologique, dans la forme du document interne.

Deux documents de référence coexistent dans le dossier de l'équipe, et ils ne
visent pas la même chose. L'**externe** est une étude d'impact en bonne forme,
avec méthodologies et bioévaluation. L'**interne** est ce que l'outil doit
produire : un prédiagnostic court, factuel, que le chef de projet génère et que
la responsable environnement complète là où il faut de l'expertise.

Sa structure, reprise ici :

    Prédiagnostic <commune> (<département>)
      Zone d'étude : analyse générale
      Patrimoine naturel
      Zones humides
      Espèces recensées sur la commune
        Flore · Avifaune · Amphibiens · Reptiles · Mammifères · …
      Conclusion
        note de risque de 0 à 10 par groupe

**La frontière entre l'outil et l'experte ne passe pas là où on la met
d'instinct.** « Dans l'aire d'étude rapprochée, on recense 7 ZNIEFF de type I
et 3 de type II » est du comptage : l'outil l'écrit. « Les interactions avec la
ZIP sont limitées et peu probables pour ces groupes » est un jugement : l'outil
le laisse, en disant précisément ce qu'on attend à cet endroit. La première
version du générateur laissait les deux à Marie, et sortait donc des tableaux
nus là où il pouvait sortir un rapport presque fini.

Chaque trou laissé est écrit en couleur et formule sa consigne, pour que le
document puisse être parcouru une fois et qu'on sache quoi faire.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import chemins, flore, statuts_especes as se, zonages as mod_zonages
from .sortie_word import Colonne, Rapport, colonnes_zonages
from .taxref import cle_alphabetique, nom_vernaculaire


@dataclass
class Projet:
    """Ce qui identifie l'étude, et ce sur quoi portent les distances."""
    nom: str
    communes: list = field(default_factory=list)
    departements: list[str] = field(default_factory=list)
    surface_ha: float = 0.0
    aires: list = field(default_factory=list)

    @property
    def libelle_communes(self) -> str:
        noms = [c.nom for c in self.communes]
        return _enumerer(noms) if noms else "la zone d'étude"

    @property
    def intitule(self) -> str:
        departements = ", ".join(self.departements)
        if departements:
            return f"Prédiagnostic écologique — {self.nom} ({departements})"
        return f"Prédiagnostic écologique — {self.nom}"

    def aire(self, code: str):
        return next((a for a in self.aires if a.code == code), None)

    def libelle_aire(self, code: str, defaut: str) -> str:
        trouvee = self.aire(code)
        return trouvee.libelle.lower() if trouvee else defaut


#: Article que TaxRef repousse en fin de nom vernaculaire pour que ses listes
#: se trient alphabétiquement : « Alyte accoucheur (L') », « Crapaud calamite
#: (Le) ».
#: `nom_vernaculaire` et `cle_alphabetique` vivent dans `taxref` : la
#: construction des extraits en a besoin elle aussi, et `zonages` ne peut pas
#: importer ce module-ci sans boucler.





def _enumerer(elements: list[str]) -> str:
    """« a », « a et b », « a, b et c » — jamais « a, b, c »."""
    propres = [e for e in elements if e]
    if not propres:
        return ""
    if len(propres) == 1:
        return propres[0]
    return ", ".join(propres[:-1]) + " et " + propres[-1]


def _libelle_aire_rayon(aire) -> str:
    """« la zone d'implantation potentielle », « l'aire d'étude immédiate
    (200 m) », « l'aire d'étude rapprochée (5 km) »."""
    nom = aire.libelle.lower()
    if aire.rayon_m <= 0:
        return f"la {nom}"
    if aire.rayon_m >= 1000:
        rayon = f"{aire.rayon_m / 1000:.0f} km"
    else:
        rayon = f"{aire.rayon_m:.0f} m"
    return f"l'{nom} ({rayon})"


def complement_de(nom: str) -> str:
    """« de Paris », « des Islettes », « du Mans », « d'Avignon ».

    Sans cela, les légendes de cartes portaient « projet de Les Islettes ».
    Un tiers des communes françaises commence par un article, donc le cas est
    courant et pas un détail.
    """
    propre = str(nom or "").strip()
    if not propre:
        return ""
    for article, forme in (("Les ", "des "), ("Le ", "du ")):
        if propre.startswith(article):
            return forme + propre[len(article):]
    # « de La Rochelle » et « de L'Isle-Adam » sont les formes d'usage :
    # l'article fait partie du nom et garde sa capitale.
    if propre.startswith(("La ", "L'", "L\u2019")):
        return "de " + propre
    if propre[0].upper() in "AEIOUY":
        return "d'" + propre
    return "de " + propre


def _compte_type(type_libelle: str, nombre: int) -> str:
    """« 1 ZNIEFF de type I », « 2 Zones de Protection Spéciale »."""
    return f"{nombre} {mod_zonages.pluriel(type_libelle, nombre)}"


def _compter(zonages_retenus: list) -> list[tuple[str, int]]:
    """Comptage par type, du plus nombreux au moins nombreux.

    Pas de pluralisation automatique : « ZNIEFF de type I » ne se met pas au
    pluriel en « ZNIEFF de type Is ». Le nombre devant suffit à le dire.
    """
    compte: dict[str, int] = {}
    for zonage in zonages_retenus:
        compte[zonage.type] = compte.get(zonage.type, 0) + 1
    return sorted(compte.items(), key=lambda x: (-x[1], x[0]))


# ═══════════════════════════════════════════════════════════ phrases de constat

#: Ce qu'une rubrique vide écrit, quand « aucun zonage » dirait trop.
AUCUN_ZONAGE = {
    "zones_humides": "Aucune zone humide ni tourbière délimitée au titre de la "
                     "BCAE 2 n'est présente dans les aires d'étude du projet.",
}

#: Ce que la couche de la BCAE 2 ne prouve pas. Le prédiagnostic de Bédarieux
#: du 1er novembre 2026 écrivait « Aucun zonage de cette nature n'est
#: présent » sous cette couche, sans rien de plus : la lecture « pas de zone
#: humide » que `zonages._enrichir_zones_humides` voulait justement empêcher.
NOTE_BCAE = (
    "cette couche délimite les zones humides et tourbières que protège la "
    "norme BCAE 2 de la politique agricole commune. Ce n'est pas un inventaire "
    "des zones humides : sa couverture suit l'avancement de leur délimitation, "
    "inégal d'une région à l'autre. L'absence de polygone ne vaut donc pas "
    "absence de zone humide ; la rubrique « Zone humide » réunit les autres "
    "indices."
)


def _constat_famille(retenus: list, projet: Projet,
                     famille: str = "") -> list[str]:
    """Les phrases factuelles qui ouvrent une rubrique de zonages.

    Toutes sont du dénombrement ou de la mesure, donc toutes automatisables.
    La tournure évite d'accorder en genre : « on recense » marche pour une
    ZNIEFF comme pour un arrêté de protection de biotope, là où « sont
    présentes » obligerait à connaître le genre de chaque type de zonage.
    """
    if not retenus:
        return [AUCUN_ZONAGE.get(
            famille, "Aucun zonage de cette nature n'est présent dans les "
                     "aires d'étude du projet.")]

    phrases = []
    libelle_aer = projet.libelle_aire("AER", "aire d'étude rapprochée")
    bouts = [_compte_type(type_zonage, nombre)
             for type_zonage, nombre in _compter(retenus)]
    phrases.append(f"Dans l'{libelle_aer}, on recense {_enumerer(bouts)}.")

    dans_zip = [z for z in retenus if "ZIP" in z.aires]
    dans_aei = [z for z in retenus if "AEI" in z.aires and "ZIP" not in z.aires]

    if dans_zip:
        cites = _citer(dans_zip[:4])
        if len(dans_zip) == 1:
            phrases.append(
                "L'un d'entre eux recouvre la zone d'implantation "
                f"potentielle : {cites}."
            )
        else:
            phrases.append(
                f"{len(dans_zip)} d'entre eux recouvrent la zone "
                f"d'implantation potentielle : {cites}."
            )
    libelle_aei = projet.libelle_aire("AEI", "aire d'étude immédiate")
    if dans_aei:
        verbe = "concerne" if len(dans_aei) == 1 else "concernent"
        phrases.append(
            f"{len(dans_aei)} {verbe} l'{libelle_aei} sans atteindre la zone "
            "d'implantation potentielle."
        )
    if not dans_zip and not dans_aei:
        phrases.append(
            f"Aucun n'intersecte la zone d'implantation potentielle ni "
            f"l'{libelle_aei}."
        )
        plus_proche = min(retenus, key=lambda z: z.distance_m)
        phrases.append(
            f"Le plus proche se situe à {plus_proche.distance_lisible} de la "
            f"zone d'implantation potentielle : {_citer([plus_proche])}."
        )
    return phrases


def _citer(zonages_cites: list) -> str:
    """« ZNIEFF de type II — "Massif forestier d'Argonne" ».

    Le type précède le nom, séparé par un tiret, plutôt que de le suivre entre
    parenthèses. Plusieurs types en portent déjà — « Parc national (aire
    d'adhésion) » — et la forme précédente produisait des parenthèses
    imbriquées : « Port-Cros » (Parc national (aire d'adhésion)). Placer le
    type devant évite aussi d'avoir à l'accorder en genre.
    """
    return " · ".join(f"{z.type} — « {z.nom} »" for z in zonages_cites)


#: Au-delà de ce nombre, un type s'énumère par ses plus proches et se compte
#: pour le reste. Les zones humides BCAE en comptent 782 dans un rayon de
#: 5 km en Vendée, sans nom ni identifiant : les tabuler toutes n'aurait rien
#: appris, et aurait noyé les ZNIEFF qui suivent.
MAX_PAR_TYPE = 15


#: Ce que l'astérisque veut dire dans les tableaux de zonages.
MARQUE_OBSERVEE = "* : espèce observée sur la commune"


def _presentation_especes(projet: Projet, resultat_especes, contexte):
    """Comment ordonner et marquer les espèces qu'un zonage cite.

    Quand un groupe en compte trop pour toutes les nommer, on montre d'abord
    celles au plus fort enjeu, puis, à enjeu égal, celles observées sur la
    commune — c'est ce qui relie le zonage au projet —, puis l'ordre
    alphabétique. L'enjeu passe devant depuis le 6 novembre 2026, sur
    décision d'Eliott, avec la coupe à cinq noms. Rend (ordre, observee), ou
    (None, None) sans référentiels.
    """
    if contexte is None:
        return None, None
    index = contexte.index
    statuts = contexte.statuts_pour(projet.departements)
    regions = sorted({r for d in projet.departements
                      for r in se.REGIONS.get(str(d).strip().upper(), ())})
    observees = ({e.cd_ref for e in resultat_especes.especes if e.cd_ref}
                 if resultat_especes is not None else set())
    cd_refs: dict[str, str | None] = {}
    niveaux: dict[str, int] = {}

    def cd_ref(nom: str) -> str | None:
        if nom not in cd_refs:
            cd_refs[nom] = index.cd_ref_exact(nom)
        return cd_refs[nom]

    def observee(nom: str) -> bool:
        cd = cd_ref(nom)
        return cd is not None and cd in observees

    def ordre(nom: str) -> tuple:
        cd = cd_ref(nom)
        if cd is not None and cd not in niveaux:
            niveaux[cd] = se.niveau_enjeu(statuts, cd, regions)
        return (-niveaux.get(cd, 0), not observee(nom), cle_alphabetique(nom))

    return ordre, observee


def _groupes_tableau(retenus: list, ordre=None,
                     observee=None) -> list[tuple[str, list[dict]]]:
    """Lignes du tableau, groupées par type sous une ligne fusionnée.

    C'est la forme du document de référence : « Zone Naturelle d'Intérêt
    Écologique Faunistique et Floristique de type I » occupe une ligne à lui
    seul, et ses entrées suivent dessous.

    Un type trop fourni est écourté. Ce sont les zonages les plus proches qui
    pèsent sur un projet, et le croisement les a déjà triés par distance : on
    garde ceux-là et on dit combien d'autres suivent, plutôt que de publier
    huit cents lignes que personne ne lira.
    """
    par_type: dict[str, list[dict]] = {}
    for zonage in retenus:
        par_type.setdefault(zonage.type, []).append({
            "nom": zonage.nom,
            "distance": zonage.distance_lisible,
            "identifiant": zonage.identifiant,
            "interet": mod_zonages.blocs_interet(zonage.interet, ordre=ordre,
                                                 observee=observee),
            "aires": ", ".join(zonage.aires),
        })
    for type_zonage, lignes in par_type.items():
        if len(lignes) <= MAX_PAR_TYPE:
            continue
        reste = len(lignes) - MAX_PAR_TYPE
        par_type[type_zonage] = lignes[:MAX_PAR_TYPE] + [{
            "nom": f"… et {reste} autre{'s' if reste > 1 else ''} "
                   f"entité{'s' if reste > 1 else ''} de ce type dans les "
                   f"aires d'étude, plus éloignée"
                   f"{'s' if reste > 1 else ''}",
            "distance": "", "identifiant": "", "interet": "", "aires": "",
        }]
    # L'ordre des types suit celui du croisement, qui trie par famille puis par
    # type puis par distance : les plus proches d'abord dans chaque groupe.
    ordre = []
    for zonage in retenus:
        if zonage.type not in ordre:
            ordre.append(zonage.type)
    return [(type_zonage, par_type[type_zonage]) for type_zonage in ordre]


def _legende_aires(projet: Projet) -> str:
    """La ligne « Légende : … » que le document place sous ses tableaux."""
    bouts = [f"{a.code} : {a.libelle.lower()}" for a in projet.aires]
    return "Légende : " + " · ".join(bouts) if bouts else ""


# ═══════════════════════════════════════════════════════════════════ sections
#
# Le squelette est celui du prédiagnostic **externe** — le livrable que
# l'équipe remet. Une première version suivait le prédiagnostic interne, qui
# est un document de travail bien plus court : sa table des matières n'avait
# rien à voir, et les listes d'espèces y figuraient dans le corps alors que
# l'externe les renvoie en annexe.
#
#     Cadre général de l'étude
#         Équipe de travail · Définition des aires d'étude
#         Prise en compte des inventaires officiels et de la réglementation
#         Protection et statut de rareté des espèces
#     Méthodologies
#         Détermination des enjeux
#     État initial
#         Zonages présents dans les aires d'étude    (ZNIEFF · Natura 2000 ·
#             autres · PNA · Synthèse)
#         Zone humide · Avifaune · Chiroptères · Autre faune
#     Dynamique du site
#     Prise en compte de la Trame verte et bleue
#     Annexes            listes d'espèces par groupe
#     Bibliographie

#: Ce que localise la carte de chaque famille, dans « Localisation des … ».
#: L'intitulé de la famille passé en minuscules donnait « des natura 2000 ».
LEGENDES_CARTES = {
    "inventaire": "zonages d'inventaire",
    "natura2000": "sites Natura 2000",
    "autres": "autres zonages du patrimoine naturel",
    "compensation": "mesures compensatoires prescrites",
    "zones_humides": "zones humides et tourbières de la BCAE 2",
}

#: Intitulés de l'état initial pour chaque famille de zonages, repris du
#: document externe — ils ne sont pas ceux du registre interne.
TITRES_ZONAGES = {
    "inventaire": "ZNIEFF de type I et II et ZICO (zonages d'inventaires)",
    "natura2000": "Zonages Natura 2000 : ZPS et ZSC",
    "autres": "Autres zonages du patrimoine naturel",
}


def colonnes_aires() -> list[Colonne]:
    return [Colonne("Nom", "nom", largeur_cm=5.0),
            Colonne("Définition", "definition", largeur_cm=11.0)]


def cadre_par_defaut() -> Path:
    """Le document de partie générale livré avec l'outil."""
    return chemins.racine_application() / "modele" / "cadre_general.docx"


def _aires_etude(rapport: Rapport, projet: Projet, carte_situation) -> None:
    """Le corps de « Définition des aires d'étude », avec les rayons du projet.

    C'est la seule sous-partie du cadre général que l'outil produit lui-même :
    les rayons se règlent par projet, et la carte en découle.
    """
    rapport.para(
        "Trois aires d'étude sont définies, conformément au guide du ministère "
        "relatif à l'élaboration des études d'impact (2016). Toutes les "
        "distances citées dans ce document sont mesurées depuis la zone "
        "d'implantation potentielle."
    )
    rapport.tableau(
        colonnes_aires(),
        [{"nom": f"{a.libelle} ({a.code})", "definition": _definition_aire(a)}
         for a in projet.aires],
        legende="Définition des aires d'étude",
    )
    if carte_situation is not None:
        rapport.carte(carte_situation.chemin,
                      f"Définition des aires d'étude du projet "
                      f"{complement_de(projet.nom)}")


def colonnes_aires() -> list[Colonne]:
    return [Colonne("Nom", "nom", largeur_cm=5.0),
            Colonne("Définition", "definition", largeur_cm=11.0)]


def _definition_aire(aire) -> str:
    """Ce que recouvre chaque aire, dans les termes du document de référence."""
    if aire.rayon_m <= 0:
        return ("Emprise du projet, sur laquelle porteront les travaux et les "
                "aménagements.")
    rayon = _libelle_aire_rayon(aire).rsplit("(", 1)[-1].rstrip(")")
    if aire.code == "AEI":
        return (f"Zone tampon de {rayon} autour de la zone d'implantation "
                "potentielle, où les effets directs et indirects du projet "
                "sont susceptibles de s'exercer.")
    return (f"Zone tampon de {rayon} autour de la zone d'implantation "
            "potentielle, retenue pour l'inventaire des zonages du patrimoine "
            "naturel et le recensement des espèces.")


#: Intertitre du cadre après lequel s'insèrent les aires d'étude. L'apostrophe
#: est typographique, comme dans le document dont le cadre est tiré : une
#: apostrophe droite ne s'apparierait pas.
REPERE_AIRES = "Définition des aires d’étude"


def _cadre_et_methodologies(rapport: Rapport, projet: Projet,
                            carte_situation, cadre: Path | None = None) -> bool:
    """Insère « Cadre général de l'étude » et « Méthodologies ».

    Ces quatre-vingts paragraphes de contenu réglementaire ne changent pas d'un
    prédiagnostic à l'autre. Ils vivent dans `modele/cadre_general.docx`, que
    l'on édite dans Word quand la réglementation ou les habitudes de l'équipe
    évoluent — pas dans ce fichier.

    Renvoie False si le document de cadre est absent : on écrit alors le
    squelette avec ses consignes, plutôt que de sauter deux parties entières
    du rapport sans le dire.
    """
    chemin = Path(cadre) if cadre else cadre_par_defaut()
    if chemin.exists():
        rapport.inserer(chemin, reperes={
            REPERE_AIRES: lambda: _aires_etude(rapport, projet, carte_situation)
        })
        return True

    rapport.partie("Cadre général de l'étude")
    rapport.sous_partie("Équipe de travail")
    rapport.a_completer("renseigner les intervenants et leur domaine "
                        "d'intervention")
    rapport.sous_partie("Définition des aires d'étude")
    _aires_etude(rapport, projet, carte_situation)
    rapport.sous_partie(
        "Prise en compte des inventaires officiels et de la réglementation")
    rapport.a_completer(
        "le document de cadre est introuvable : reprendre ici le texte sur "
        "les ZNIEFF, Natura 2000, les autres zonages et les plans nationaux "
        "d'actions"
    )
    rapport.sous_partie("Protection et statut de rareté des espèces")
    rapport.a_completer(
        "reprendre le cadre juridique de la protection des espèces et les "
        "outils de bioévaluation"
    )
    rapport.partie("Méthodologies")
    rapport.sous_partie("Détermination des enjeux")
    rapport.a_completer("reprendre les grilles de détermination des enjeux")
    return False


def _especes_par_groupe(resultat, contexte) -> dict[str, list]:
    """Espèces déposées, rangées par groupe du prédiagnostic."""
    par_groupe: dict[str, list] = {}
    if resultat is None or contexte is None:
        return par_groupe
    for espece in resultat.especes:
        taxon = contexte.index.taxons.get(espece.cd_ref)
        par_groupe.setdefault(
            se.groupe_de(taxon, contexte.reference).cle, []).append(espece)
    return par_groupe


def _ecarter(par_groupe: dict[str, list]) -> tuple[dict[str, list],
                                                   dict[str, list]]:
    """Sépare ce que le document tabule de ce qu'il met de côté.

    `se.GROUPES_ECARTES` dit lesquels et pourquoi. On rend les deux moitiés
    plutôt que de filtrer en silence : un groupe retiré du document doit y
    être annoncé, faute de quoi son absence se confond avec l'absence
    d'observation — exactement le défaut que les colonnes de flore vides
    avaient révélé.
    """
    retenus = {cle: especes for cle, especes in par_groupe.items()
               if cle not in se.GROUPES_ECARTES}
    ecartes = {cle: especes for cle, especes in par_groupe.items()
               if cle in se.GROUPES_ECARTES}
    return retenus, ecartes


def _phrase_ecartees(ecartes: dict[str, list]) -> str:
    """« 14 espèces de poissons sont écartées de ce document. »"""
    if not ecartes:
        return ""
    bouts, total = [], 0
    for cle, especes in sorted(ecartes.items()):
        groupe = se.groupe_par_cle(cle)
        total += len(especes)
        bouts.append(f"{len(especes)} espèce{'s' if len(especes) > 1 else ''} "
                     f"{groupe.complement}")
    pluriel = total > 1
    return (
        f"{', '.join(bouts)} {'sont' if pluriel else 'est'} "
        f"écartée{'s' if pluriel else ''} de ce document. "
        f"{'Elles arrivent' if pluriel else 'Elle arrive'} avec les exports "
        f"de commune entière, sans qu'un projet photovoltaïque "
        f"{'les' if pluriel else 'la'} concerne ; la liste recoupée "
        f"{'les' if pluriel else 'la'} conserve."
    )


def _colonnes_repliees(contexte, jeu, retenues: list) -> list[str]:
    """Colonnes remplies par BDC alors que le classeur porte bien le taxon.

    Le classeur de flore n'a aucune colonne d'espèces déterminantes de
    ZNIEFF : celle-là vient de BDC quand toutes ses voisines viennent du
    classeur. Sans cette phrase, « statuts repris des classeurs UNITe »
    couvrirait une colonne qui n'en vient pas — et la Licence Ouverte
    demande de citer qui a produit la donnée, pas qui a produit le tableau.
    """
    reference = getattr(contexte, "reference", None)
    if reference is None:
        return []
    connues = [e.cd_ref for e in retenues if reference.connait(e.cd_ref)]
    if not connues:
        return []          # le tableau entier est traité par _absence_de_reference
    repliees = []
    for colonne in jeu.colonnes:
        lecture = jeu.lectures.get(colonne.cle)
        if lecture is None:
            continue
        if not any(reference.interroge(cd, lecture.type_statut,
                                       lecture.territoire) for cd in connues):
            repliees.append(colonne.titre)
    return repliees


def _absence_de_reference(contexte, jeu, retenues: list, statuts=None) -> str:
    """Ce qu'il faut dire quand les classeurs ne couvrent pas ce groupe.

    **Une cellule vide affirme quelque chose.** Un lecteur qui voit la colonne
    « Protection nationale » vide en conclut que l'espèce n'est pas protégée —
    et il a raison de le conclure, puisque rien ne lui dit le contraire.

    Or aucun des classeurs ne couvre la flore ni les poissons. À Bédarieux,
    cela faisait 800 plantes présentées sans aucun statut, dont six protégées
    au titre de l'arrêté national : la Spiranthe d'été, l'Orchis de Provence,
    la Pivoine à petits fruits. Le document affirmait le contraire de la
    réalité sur un point réglementaire.

    `Reference.connait()` existait pour ça depuis le départ — distinguer
    « absente du classeur » de « case vide » — sans avoir jamais été branchée
    sur le document. La voici.

    On va jusqu'à dire ce que BDC-Statuts en sait, parce que c'est la mesure
    de ce qui manque : annoncer 749 listes rouges non reprises est autrement
    plus parlant que « groupe non couvert ».
    """
    reference = getattr(contexte, "reference", None)
    if reference is None or not retenues:
        return ""
    inconnues = [e for e in retenues if not reference.connait(e.cd_ref)]
    if not inconnues:
        return ""

    # Ce que le tableau montre de ces espèces, colonne par colonne : elles
    # n'ont pas d'autre source que BDC. Le décompte interrogeait l'index au
    # territoire de la liste rouge régionale ; il ignorait donc les espèces
    # déterminantes de ZNIEFF, que le repli lit au département, et pouvait
    # écrire « n'en documente aucune » au-dessus d'une colonne remplie.
    if statuts is None:
        statuts = contexte.source_statuts
    su_de_bdc = sum(
        1 for e in inconnues
        if any(valeur for cle, valeur in
               se.ligne(jeu, statuts, e.cd_ref, "", "").items()
               if cle in jeu.lectures)
    )
    version = getattr(contexte.versions.get("bdc_statuts"), "version", "")
    cite = "BDC-Statuts" + (f" v{version}" if version else "")
    tous = len(inconnues) == len(retenues)
    qui = ("Les classeurs de référence d'UNITe ne couvrent pas ce groupe"
           if tous else
           f"{len(inconnues)} des {len(retenues)} espèces ci-dessus ne "
           "figurent pas dans les classeurs de référence d'UNITe")

    # Le repli n'a rien trouvé non plus : la cellule vide reste une cellule
    # vide, et c'est encore ce cas qu'il faut nommer.
    if not su_de_bdc:
        return (
            f"{qui}, et {cite} n'en documente aucune : les cellules "
            "correspondantes sont vides faute de référence, et non parce que "
            "ces espèces n'en porteraient aucune."
        )
    return (
        f"{qui} : leurs statuts sont repris de {cite}, Muséum national "
        f"d'Histoire naturelle / PatriNat, qui en documente {su_de_bdc}. "
        "Les cellules restées vides le sont faute de statut connu de cette "
        "source."
    )


def _lus_a_l_espece(contexte, retenues: list) -> list[tuple[str, str]]:
    """(taxon, espèce) pour chaque taxon que les classeurs lisent à l'espèce.

    Voir `reference.Reference.lu_comme`. Les noms sont ceux du tableau : le
    nom scientifique de TaxRef, sous-espèce comprise.
    """
    reference = getattr(contexte, "reference", None)
    if reference is None or not hasattr(reference, "lu_comme"):
        return []
    taxons = contexte.index.taxons
    paires = []
    for espece in retenues:
        lu = reference.lu_comme(espece.cd_ref)
        if lu == str(espece.cd_ref).strip():
            continue
        taxon, parent = taxons.get(espece.cd_ref), taxons.get(lu)
        paires.append(((taxon.lb_nom if taxon else "") or espece.nom_scientifique,
                       parent.lb_nom if parent else lu))
    return paires


def _phrase_lus_a_l_espece(paires: list[tuple[str, str]]) -> str:
    """Ce qu'il faut dire des taxons dont les statuts sont ceux de l'espèce."""
    if not paires:
        return ""
    noms = [f"{taxon} ({espece})" for taxon, espece in
            sorted(paires, key=lambda p: cle_alphabetique(p[0]))]
    if len(paires) == 1:
        return ("1 taxon relevé sous le rang d'espèce ne figure pas dans les "
                "classeurs de référence d'UNITe, qui portent son espèce : ses "
                f"statuts sont ceux de l'espèce — {noms[0]}.")
    return (f"{len(paires)} taxons relevés sous le rang d'espèce ne figurent "
            "pas dans les classeurs de référence d'UNITe, qui portent leur "
            "espèce : leurs statuts sont ceux de l'espèce — "
            f"{_enumerer(noms)}.")


#: Au-delà, une condition de déterminance ZNIEFF quitte le tableau pour une
#: liste dessous. La colonne fait 2,3 cm : « Oui (MC, SO) » y tient, mais les
#: listes donnent jusqu'à 261 caractères pour un oiseau d'Auvergne-Rhône-Alpes
#: et 334 pour un insecte d'Aquitaine, soit une vingtaine de lignes dans la
#: cellule. La parenthèse reste la règle des classeurs, décidée par Eliott le
#: 6 novembre 2026 : c'est au document de choisir ce qu'il imprime.
MAX_CONDITION_ZNIEFF = 40
_CONDITION = re.compile(r"^Oui \((?P<condition>.+)\)$", re.S)

#: Sous un tableau dont une condition finit par « … » : l'outil marque ainsi,
#: depuis le 6 novembre 2026, les remarques que BDC coupe (voir
#: `determinantes.COUPURE_BDC`) — 29 oiseaux d'Auvergne-Rhône-Alpes.
NOTE_COUPURE = ("« … » marque une condition que BDC-Statuts coupe à 255 caractères ; "
                "la suite ne se trouve que dans la liste d'origine.")
#: La marque de l'outil : « … », puis seulement des parenthèses qui se
#: referment, jusqu'à la fin de la case ou d'une réserve. Deux remarques du
#: Centre portent un « … » à elles — « bord de route…). » — : pas de note.
_COUPURE = re.compile(r"…(?=\)*(?:$|[ ;,]))")


def _equilibree(texte: str) -> bool:
    profondeur = 0
    for signe in texte:
        profondeur += (signe == "(") - (signe == ")")
        if profondeur < 0:
            return False
    return profondeur == 0


def _sortir_conditions(lignes: list[dict]) -> list[str]:
    """Écrit « Oui (sous conditions) » à la place des conditions trop longues.

    Rend « Espèce : condition » pour chacune, dans l'ordre du tableau.
    """
    sorties = []
    for ligne in lignes:
        valeur = ligne.get("zdet") or ""
        if len(valeur) <= MAX_CONDITION_ZNIEFF or not valeur.startswith("Oui ("):
            continue
        m = _CONDITION.match(valeur)
        # On ne retire « Oui ( … ) » que d'une parenthèse qui se referme bien.
        # Deux colonnes peuvent répondre — « Oui (…), Oui (…) » —, et une
        # cellule peut en ouvrir plus qu'elle n'en ferme : ainsi, jusqu'au
        # 6 novembre 2026, de 89 des 187 conditions d'Auvergne-Rhône-Alpes
        # chez les oiseaux, et encore de textes de listes qu'on reprend tels
        # quels. Retirer la dernière parenthèse ôterait alors celle d'une
        # précision.
        condition = (m["condition"] if m and valeur.count("Oui (") == 1
                     and _equilibree(m["condition"]) else valeur)
        ligne["zdet"] = "Oui (sous conditions)"
        sorties.append(f"{ligne.get('nom_commun') or ligne.get('nom_scientifique')}"
                       f" : {condition}")
    return sorties


def _tableau_especes(rapport: Rapport, projet: Projet, contexte,
                     groupe, especes: list, seulement_enjeu: bool) -> int:
    """Un tableau d'espèces. Renvoie le nombre de lignes écrites.

    Le document de référence tabule deux fois les mêmes espèces, et ce n'est
    pas une redite : l'**état initial** ne retient que celles qui portent un
    enjeu, parce que c'est sur elles que porte le raisonnement ; l'**annexe**
    donne la liste exhaustive, qui fait foi sur ce qui a été consulté.
    """
    statuts, index = contexte.statuts_pour(projet.departements), contexte.index
    cd_refs = [e.cd_ref for e in especes]
    jeu = se.jeu(groupe, statuts, cd_refs, projet.departements)
    retenues = ([e for e in especes if se.a_enjeu(jeu, statuts, e.cd_ref)]
                if seulement_enjeu else list(especes))
    if not retenues:
        return 0

    def _cle_tri(espece) -> str:
        taxon = index.taxons.get(espece.cd_ref)
        return cle_alphabetique(nom_vernaculaire(
            (taxon.nom_vern if taxon else "")
            or espece.nom_commun or espece.nom_scientifique))

    lignes = []
    for espece in sorted(retenues, key=_cle_tri):
        taxon = index.taxons.get(espece.cd_ref)
        lignes.append(se.ligne(
            jeu, statuts, espece.cd_ref,
            nom_vernaculaire((taxon.nom_vern if taxon else "")
                             or espece.nom_commun),
            (taxon.lb_nom if taxon else "") or espece.nom_scientifique,
            reproduction=getattr(espece, "nidification", ""),
        ))
    qualificatif = " à enjeu" if seulement_enjeu else ""
    coupee = any(_COUPURE.search(ligne.get("zdet") or "") for ligne in lignes)
    conditions = _sortir_conditions(lignes)
    rapport.tableau(
        jeu.colonnes, lignes,
        legende=f"Liste des espèces {groupe.complement}{qualificatif} "
                f"recensées sur la commune "
                f"{complement_de(projet.libelle_communes)}",
    )
    if conditions:
        lecture = jeu.lectures.get("zdet")
        territoire = f" ({lecture.territoire})" if lecture and lecture.territoire else ""
        rapport.para(f"Conditions de déterminance ZNIEFF{territoire}, trop "
                     "longues pour figurer dans le tableau :")
        rapport.puces(conditions)
    if coupee:
        rapport.note(NOTE_COUPURE)
    avertissement = _absence_de_reference(contexte, jeu, retenues, statuts)
    if avertissement:
        rapport.para(avertissement)
    lus = _phrase_lus_a_l_espece(_lus_a_l_espece(contexte, retenues))
    if lus:
        rapport.para(lus)
    repliees = _colonnes_repliees(contexte, jeu, retenues)
    if repliees:
        version = getattr(contexte.versions.get("bdc_statuts"), "version", "")
        cite = "BDC-Statuts" + (f" v{version}" if version else "")
        pluriel = len(repliees) > 1
        rapport.para(
            f"{'Les colonnes' if pluriel else 'La colonne'} "
            f"« {' », « '.join(repliees)} » "
            f"{'sont reprises' if pluriel else 'est reprise'} de {cite} : "
            f"le classeur de référence de ce groupe ne "
            f"{'les' if pluriel else 'la'} porte pas."
        )
    return len(lignes)


def _etat_initial(rapport: Rapport, projet: Projet, resultat_zonages,
                  cartes_par_famille: dict, resultat_especes, contexte,
                  especes_pna: list[str]) -> None:
    rapport.partie("État initial")
    rapport.sous_partie("Zonages présents dans les aires d'étude")

    if resultat_zonages is None:
        rapport.a_completer(
            "croiser l'emprise avec les zonages du patrimoine naturel "
            "(section « Zonages » de l'outil) puis régénérer ce document"
        )
    else:
        ordre, observee = _presentation_especes(projet, resultat_especes, contexte)
        for famille, titre_interne in mod_zonages.FAMILLES:
            retenus = resultat_zonages.par_famille(famille)
            rapport.sous_sous_partie(TITRES_ZONAGES.get(famille, titre_interne))
            for phrase in _constat_famille(retenus, projet, famille):
                rapport.para(phrase)
            # Avant le `continue` : c'est justement quand le tableau est vide
            # que la mention compte le plus.
            if famille == "compensation":
                mention = _mesures_non_localisees(resultat_zonages)
                if mention:
                    rapport.para(mention)
            if famille == "zones_humides":
                rapport.note(NOTE_BCAE)
            if not retenus:
                continue
            groupes = _groupes_tableau(retenus, ordre, observee)
            # L'astérisque ne s'explique que dans les tableaux qui en portent.
            marque = any(morceau.endswith("*") or "*," in morceau
                         for _, lignes in groupes for ligne in lignes
                         if isinstance(ligne.get("interet"), list)
                         for bloc in ligne["interet"] for morceau, _ in bloc.morceaux)
            legende_bas = _legende_aires(projet)
            if marque:
                legende_bas = (f"{legende_bas} · {MARQUE_OBSERVEE}" if legende_bas
                               else f"Légende : {MARQUE_OBSERVEE}")
            rapport.tableau(
                colonnes_zonages(), [],
                legende=f"{TITRES_ZONAGES.get(famille, titre_interne)} dans "
                        "les aires d'étude du projet",
                groupes=groupes,
                legende_bas=legende_bas,
            )
            carte = cartes_par_famille.get(famille)
            if carte is not None:
                objet = LEGENDES_CARTES.get(
                    famille, titre_interne.split("—")[0].strip().lower())
                rapport.carte(
                    carte.chemin,
                    f"Localisation des {objet} jusqu'à {_rayon_aer(projet)} "
                    "autour de la ZIP")
            # Les zonages sans source nationale fiable — les ENS en tête — se
            # rangent dans cette famille. Le lecteur doit savoir si la rubrique
            # est vide faute de zonage ou faute de recherche.
            if famille == "autres":
                for avertissement in getattr(resultat_zonages,
                                             "avertissements", []):
                    rapport.note(avertissement)

        rapport.sous_sous_partie("Plan National d'Actions (PNA)")
        rapport.para(_phrase_pna(especes_pna))
        rapport.a_completer(
            "préciser les zonages de PNA qui recoupent les aires d'étude — "
            "l'outil ne lit que les espèces concernées, pas l'emprise "
            "géographique des plans"
        )

        rapport.sous_sous_partie("Synthèse")
        rapport.a_completer(
            "synthétiser les interactions attendues entre les espèces et "
            "habitats qui ont motivé ces zonages et la ZIP : groupes "
            "réellement susceptibles de fréquenter l'emprise, espèces à "
            "surveiller, probabilité de présence au regard des milieux observés"
        )
        if resultat_zonages.manquants:
            rapport.note(
                "Couches non consultées lors de cette génération : "
                + " · ".join(resultat_zonages.manquants)
                + ". Le constat ci-dessus est donc incomplet sur ces zonages."
            )

    _zone_humide(rapport, projet, resultat_especes, contexte)

    comptes = _compter_par_famille_etude(resultat_especes, contexte,
                                         projet.departements)
    par_groupe, ecartes = _ecarter(
        _especes_par_groupe(resultat_especes, contexte))
    phrase_ecartees = _phrase_ecartees(ecartes)
    if phrase_ecartees:
        rapport.para(phrase_ecartees)
    # Avifaune, chiroptères et autre faune passent en paysage, comme dans le
    # document de référence : leurs tableaux comptent jusqu'à dix colonnes, et
    # les 16 cm d'une page portrait les écrasent.
    avant = rapport.orientation(paysage=True)
    for cle, libelle, cles_groupes in se.FAMILLES_ETUDE:
        rapport.sous_partie(libelle)
        total, a_enjeu = comptes.get(cle, (0, 0))
        if total:
            rapport.para(
                f"Sur {projet.libelle_communes}, {total} espèce"
                f"{'s' if total > 1 else ''} relevant de ce volet "
                f"{'sont' if total > 1 else 'est'} recensée"
                f"{'s' if total > 1 else ''}, dont {a_enjeu} à enjeu. "
                "La liste exhaustive figure en annexe."
            )
        else:
            rapport.para(
                "Aucune espèce relevant de ce volet n'a été recensée à partir "
                "des sources déposées."
            )
        rapport.a_completer(
            "apprécier l'utilisation de la ZIP par les espèces de ce volet : "
            "milieux favorables, phase du cycle concernée, espèces exigeant "
            "une vigilance particulière"
        )
        # Les espèces à enjeu sont tabulées ici, groupe par groupe : c'est sur
        # elles que porte le raisonnement de l'état initial.
        if contexte is not None:
            for cle_groupe in cles_groupes:
                especes = par_groupe.get(cle_groupe)
                if especes:
                    _tableau_especes(rapport, projet, contexte,
                                     se.groupe_par_cle(cle_groupe), especes,
                                     seulement_enjeu=True)
        rapport.sous_sous_partie("Consultations")
        rapport.a_completer("citer les sources consultées et leur date")
    rapport.orientation(paysage=avant)


#: La liste que la rubrique « Zone humide » cite pour la flore.
LISTE_ZH = ("liste des espèces indicatrices de zones humides (arrêté du "
            "24 juin 2008 modifié, annexe 2.1)")

#: Ce que la rubrique doit à l'outil, et ce qu'elle laisse. Elle disait
#: depuis le 5 octobre 2026 n'être « pas encore alimentée automatiquement »,
#: les couches de milieux humides n'étant « pas nationales » : la BCAE 2 est
#: croisée depuis le 19 octobre, et une prélocalisation nationale existe
#: depuis 2023.
NOTE_ZONE_HUMIDE = (
    "l'outil renseigne ici la flore indicatrice des sources déposées ; les "
    "zones humides délimitées au titre de la BCAE 2 figurent avec les "
    "zonages. Les sols, les prélocalisations et les inventaires de zones "
    "humides ne sont pas lus : ils restent à consulter."
)


def _zone_humide(rapport: Rapport, projet: Projet, resultat_especes,
                 contexte) -> None:
    """La rubrique « Zone humide » : ce que l'outil sait dire, puis le reste."""
    rapport.sous_partie("Zone humide")
    plantes = _especes_par_groupe(resultat_especes, contexte).get("flore", [])
    statuts = contexte.source_statuts if contexte is not None else None
    index = contexte.index if contexte is not None else None
    rapport.para(_flore_zone_humide(projet, plantes, statuts, index))
    if _indicatrices_zh(plantes, statuts, index):
        rapport.a_completer(
            "vérifier sur la ZIP si ces espèces dominent la végétation : c'est "
            "le critère de végétation de l'arrêté du 24 juin 2008"
        )
    rapport.a_completer(
        "renseigner le type de sol de la ZIP et son caractère hydromorphe "
        "d'après la carte des sols (RRP du GIS Sol), puis les potentialités de "
        "zones humides d'après la prélocalisation nationale des zones humides "
        "probables (PatriNat, sur l'INPN et le RPDZH), les zones à dominante "
        "humide du SDAGE et les inventaires portés par la DREAL et l'agence de "
        "l'eau"
    )
    rapport.sous_sous_partie("Consultations")
    rapport.a_completer("citer les sources consultées et leur date")
    rapport.note(NOTE_ZONE_HUMIDE)


def _colonne_zh_lue(statuts) -> bool:
    """Un classeur installé porte-t-il la colonne « ZH (Arrêté 2008) » ?"""
    return statuts is not None and statuts.couvre(flore.TYPE_ZH,
                                                  flore.TERRITOIRE_ZH)


def _indicatrices_zh(plantes: list, statuts, index) -> list[str]:
    """Les plantes que le classeur de flore marque « oui » en colonne ZH.

    Le nom est celui des autres listes du document, le vernaculaire d'abord ;
    deux taxons de même nom n'en font qu'un, pour que le décompte annoncé et
    la liste qui le suit ne se contredisent pas.
    """
    if not plantes or not _colonne_zh_lue(statuts):
        return []
    noms: list[str] = []
    for espece in plantes:
        if not statuts.entrees(espece.cd_ref, flore.TYPE_ZH,
                               flore.TERRITOIRE_ZH):
            continue
        taxon = index.taxons.get(espece.cd_ref) if index is not None else None
        nom = nom_vernaculaire(
            (taxon.nom_vern if taxon else "") or espece.nom_commun
            or espece.nom_scientifique)
        if nom and nom not in noms:
            noms.append(nom)
    return sorted(noms, key=cle_alphabetique)


def _flore_zone_humide(projet: Projet, plantes: list, statuts, index) -> str:
    """Les plantes de la commune que l'arrêté du 24 juin 2008 désigne.

    Du comptage, donc l'affaire de l'outil : à Bédarieux, 66 des plantes
    recensées sur la commune figurent sur la liste. Ce qu'elles disent de la
    ZIP — y sont-elles, y dominent-elles la végétation — revient à la visite.

    La phrase dit aussi quand la question n'a pas pu être posée : sans
    plante déposée, ou sans la colonne du classeur, se taire laisserait lire
    qu'aucune plante n'est indicatrice.
    """
    if not plantes:
        return ("La flore indicatrice de zones humides n'a pas été recherchée "
                ": aucune espèce de flore ne figure dans les sources déposées.")
    if not _colonne_zh_lue(statuts):
        return ("La flore indicatrice de zones humides n'a pas été recherchée "
                ": aucun classeur de flore installé ne porte la colonne "
                f"« {flore.ENTETE_ZH} ».")
    noms = _indicatrices_zh(plantes, statuts, index)
    communes = projet.libelle_communes
    if len(plantes) == 1:
        if noms:
            return (f"La seule espèce de flore recensée sur {communes}, "
                    f"{noms[0]}, figure sur la {LISTE_ZH}.")
        return (f"La seule espèce de flore recensée sur {communes} ne figure "
                f"pas sur la {LISTE_ZH}.")
    if not noms:
        return (f"Aucune des {len(plantes)} espèces de flore recensées sur "
                f"{communes} ne figure sur la {LISTE_ZH}.")
    return (f"Parmi les {len(plantes)} espèces de flore recensées sur "
            f"{communes}, {len(noms)} figure{'nt' if len(noms) > 1 else ''} "
            f"sur la {LISTE_ZH} : {_enumerer(noms)}.")


def _phrase_pna(especes_pna: list[str]) -> str:
    """Les espèces de la commune qu'un plan national d'actions concerne.

    Le pluriel de « fait » n'est pas « faitnt » : le prédiagnostic de
    Bédarieux du 1er novembre 2026 l'écrivait pour ses 39 espèces.
    """
    if especes_pna:
        pluriel = len(especes_pna) > 1
        return (
            f"{len(especes_pna)} espèce{'s' if pluriel else ''} "
            f"recensée{'s' if pluriel else ''} sur la commune "
            f"{'font' if pluriel else 'fait'} l'objet d'un "
            f"plan national d'actions : {_enumerer(especes_pna)}."
        )
    return ("Aucune des espèces recensées sur la commune ne fait l'objet "
            "d'un plan national d'actions.")


def _mesures_non_localisees(resultat_zonages) -> str:
    """Les mesures compensatoires rattachées à une commune, sans plus.

    La base du Cerema sépare les mesures dont l'emprise est connue de celles
    dont on ne sait que la commune — ces dernières portent alors le polygone
    communal entier. On ne les cartographie pas, parce que ce polygone fait
    passer « quelque part dans la commune » pour « ici » : 11 km sur 13 à
    Nice.

    Les taire posait l'autre moitié du problème. Un tableau vide se lisait
    « aucune mesure compensatoire », alors qu'il peut exister des mesures que
    personne n'a su placer — 794 dans ce cas au niveau national. On les
    compte donc sans les situer, ce qui est exactement ce que la source
    permet d'affirmer.
    """
    mentions = resultat_zonages.par_famille("compensation_commune")
    if not mentions:
        return ""
    noms = sorted({z.nom for z in mentions if z.nom})
    detail = f" — {', '.join(noms[:3])}" if noms else ""
    if len(noms) > 3:
        reste = len(noms) - 3
        detail += f", et {reste} autre{'s' if reste > 1 else ''}"
    pluriel = len(mentions) > 1
    return (
        f"S'y ajoute{'nt' if pluriel else ''} {len(mentions)} mesure"
        f"{'s' if pluriel else ''} compensatoire{'s' if pluriel else ''} "
        f"rattachée{'s' if pluriel else ''} à une commune de l'aire d'étude "
        f"sans localisation précise{detail}. La base ne leur connaît que la "
        "commune : elles ne sont ni cartographiées ni tabulées ci-dessus, "
        "mais leur existence ne peut pas être écartée du raisonnement."
    )


def _rayon_aer(projet: Projet) -> str:
    aire = projet.aire("AER")
    if aire is None or aire.rayon_m < 1000:
        return "l'aire d'étude rapprochée"
    return f"{aire.rayon_m / 1000:.0f} km".replace(".", ",")


def _compter_par_famille_etude(resultat, contexte,
                               departements: list[str]) -> dict[str, tuple[int, int]]:
    """(total, à enjeu) par volet de l'état initial.

    Avec les mêmes statuts et les mêmes départements que les tableaux : le
    décompte ignorait la liste rouge régionale, que les tableaux lisent, et
    pouvait annoncer un autre nombre que les lignes tabulées dessous.
    """
    if resultat is None or not resultat.especes or contexte is None:
        return {}
    # Le même regroupement que les tableaux, et les mêmes écartés : un total
    # annoncé qui ne correspondrait pas aux lignes tabulées en dessous serait
    # pire que pas de total du tout.
    par_groupe, _ = _ecarter(_especes_par_groupe(resultat, contexte))

    statuts = contexte.statuts_pour(departements)
    comptes: dict[str, list[int]] = {}
    for cle_groupe, especes in par_groupe.items():
        groupe = se.groupe_par_cle(cle_groupe)
        # Les départements donnent la région de la liste rouge : sans eux,
        # `jeu.region` restait vide et la liste régionale ne comptait pas.
        jeu = se.jeu(groupe, statuts, [e.cd_ref for e in especes], departements)
        enjeu = sum(1 for e in especes if se.a_enjeu(jeu, statuts, e.cd_ref))
        famille = se.famille_etude(cle_groupe)
        cumul = comptes.setdefault(famille, [0, 0])
        cumul[0] += len(especes)
        cumul[1] += enjeu
    return {k: (v[0], v[1]) for k, v in comptes.items()}


#: Les planches de photographies aériennes, dans l'ordre du document — la
#: série, puis la plus récente en pleine page —, et leur légende.
LEGENDES_PHOTOGRAPHIES = {
    "ortho_evolution": ("Évolution de l'occupation du sol de la zone "
                        "d'implantation potentielle, de 1950-1965 à la prise "
                        "de vue la plus récente"),
    "ortho_actuelle": ("Photographie aérienne la plus récente de la zone "
                       "d'implantation potentielle"),
}
FAMILLES_PHOTOGRAPHIES = tuple(LEGENDES_PHOTOGRAPHIES)


def _dynamique_du_site(rapport: Rapport, photographies: list) -> None:
    """Les photographies d'hier à aujourd'hui, puis ce qu'on en tire.

    Les montrer revient à l'outil ; lire l'évolution des milieux — un
    boisement spontané, une prairie retournée, une haie arrachée — revient à
    l'experte. Sans planche, la consigne seule reste, comme avant le
    8 novembre 2026.
    """
    rapport.partie("Dynamique du site")
    if photographies:
        phrase = ("Les photographies aériennes de l'IGN montrent la zone "
                  "d'implantation potentielle et son aire d'étude immédiate de "
                  "1950-1965 à aujourd'hui.")
        absentes = [p for carte in photographies
                    for p in getattr(carte, "absentes", ())]
        if absentes:
            phrase += (f" L'IGN n'a pas de prise de vue de "
                       f"{_enumerer(absentes)} sur ce secteur.")
        rapport.para(phrase)
        for carte in photographies:
            rapport.carte(carte.chemin, LEGENDES_PHOTOGRAPHIES.get(
                carte.famille, carte.titre))
    rapport.a_completer(
        "comparer l'occupation du sol actuelle à celle des années 1950 "
        "(photographies aériennes de l'IGN) et en tirer la dynamique des "
        "milieux sur la ZIP"
    )


def _km(metres: float) -> str:
    """1400 → « 1,4 », 10000 → « 10 »."""
    return f"{metres / 1000:.1f}".rstrip("0").rstrip(".").replace(".", ",")


#: Les directions qu'une extrémité de coupe peut porter : les autres sont des
#: noms de lieux, ceux des coupes libres.
_DIRECTIONS = {"N": "au nord", "NE": "au nord-est", "E": "à l'est",
               "SE": "au sud-est", "S": "au sud", "SO": "au sud-ouest",
               "O": "à l'ouest", "NO": "au nord-ouest"}

_NOMBRES = {1: "une", 2: "deux", 3: "trois", 4: "quatre", 5: "cinq"}


def _nom_coupe(coupe) -> str:
    if coupe.demi_longueur:
        return f"La coupe {coupe.nom} de {_km(coupe.longueur)} km"
    return f"La coupe depuis {coupe.extremites[0]}"


def _legende_coupe(coupe) -> str:
    if coupe.demi_longueur:
        return (f"Coupe topographique {coupe.nom} de {_km(coupe.longueur)} km, "
                "centrée sur la ZIP")
    return (f"Coupe topographique depuis {coupe.extremites[0]}, à travers la ZIP "
            f"({_km(coupe.longueur)} km)")


def _phrase_coupe(coupe) -> str:
    """Ce que l'outil sait dire d'une coupe : son relief, et qui domine la ZIP.

    Le point haut se situe par rapport au milieu de la ZIP sur le trait, du
    côté d'une extrémité — une direction, ou le lieu d'où part une coupe
    libre. Un relief qui domine la ZIP est un lieu d'où elle peut se voir :
    c'est à l'experte de le dire, mais le chiffre lui revient d'ici.
    """
    (_, z_bas), (d_haut, z_haut) = coupe.point_bas, coupe.point_haut
    phrase = (f"{_nom_coupe(coupe)} va de {z_bas:.0f} à {z_haut:.0f} m "
              "d'altitude.")
    if coupe.emprise:
        a, b = max(coupe.emprise, key=lambda i: i[1] - i[0])
        z_zip = sorted(coupe.altitudes_emprise())
        mediane = z_zip[len(z_zip) // 2] if z_zip else None
        if a <= d_haut <= b:
            phrase += " Son point haut est dans la ZIP."
        elif mediane is not None:
            cote = coupe.extremites[0] if d_haut < (a + b) / 2 else coupe.extremites[1]
            ecart = _km(abs(d_haut - (a + b) / 2))
            if cote in _DIRECTIONS:
                ou = f"à {ecart} km {_DIRECTIONS[cote]} de la ZIP"
            else:
                ou = f"à {ecart} km de la ZIP en direction de {cote}"
            phrase += f" Son point haut, {ou}"
            if z_haut - mediane >= 5:
                phrase += f", la domine de {z_haut - mediane:.0f} m."
            else:
                phrase += ", est à peine plus haut qu'elle."
    lieux = [nom for _, nom in coupe.lieux]
    if lieux:
        phrase += f" Lieux habités croisés : {', '.join(lieux)}."
    return phrase


def _contexte_topographique(rapport: Rapport, coupes) -> None:
    """Les coupes retenues dans l'outil, et ce qu'elles disent du relief.

    Les textes d'abord, puis le plan et les coupes à la suite, en paysage : une
    phrase posée avant chaque figure resterait seule sur sa page en portrait.
    Tracer les coupes revient à l'outil ; lire d'où la ZIP se voit et ce qui
    l'écrante revient à l'experte.
    """
    rapport.partie("Contexte topographique")
    if coupes is None or not coupes.coupes:
        rapport.a_completer(
            "produire les coupes topographiques (section « Coupes "
            "topographiques » de l'outil), en retenir une à trois, puis "
            "régénérer ce document")
        return
    n = len(coupes.coupes)
    phrase = ""
    if coupes.altitudes_emprise:
        bas, haut = coupes.altitudes_emprise
        phrase = (f"La ZIP s'étend entre {bas:.0f} et {haut:.0f} m d'altitude "
                  "(NGF), d'après le RGE ALTI de l'IGN. ")
    if n == 1:
        phrase += ("La coupe ci-après la situe dans son relief, avec les "
                   "boisements, les cours d'eau, les routes principales et les "
                   "lieux habités qu'elle croise ; la carte qui la précède la "
                   "localise.")
    else:
        phrase += (f"Les {_NOMBRES.get(n, str(n))} coupes ci-après la situent "
                   "dans son relief, avec les boisements, les cours d'eau, les "
                   "routes principales et les lieux habités qu'elles croisent ; "
                   "la carte qui les précède les localise.")
    rapport.para(phrase)
    for coupe, _ in coupes.coupes:
        rapport.para(_phrase_coupe(coupe))
    rapport.a_completer(
        "lire sur les coupes d'où la ZIP peut être vue — lieux habités, routes, "
        "points hauts — et ce qui l'écrante (relief, boisements) ; les huit "
        f"coupes calculées par l'outil sont dans le fichier « {coupes.pdf} »")
    avant = rapport.orientation(paysage=True)
    rapport.carte(coupes.plan, "Localisation des coupes topographiques retenues "
                               "autour de la ZIP")
    for coupe, image in coupes.coupes:
        rapport.figure(image, _legende_coupe(coupe))
    rapport.orientation(paysage=avant)


def _trame_verte_et_bleue(rapport: Rapport) -> None:
    rapport.partie("Prise en compte de la Trame verte et bleue")
    rapport.a_completer(
        "situer la ZIP vis-à-vis des réservoirs de biodiversité et des "
        "corridors de la trame verte puis de la trame bleue, d'après le SRCE "
        "ou le SRADDET de la région"
    )


def _annexes(rapport: Rapport, projet: Projet, resultat, contexte) -> list[str]:
    """Listes exhaustives par groupe. Renvoie les groupes traités.

    Exhaustives, et non filtrées sur l'enjeu : l'annexe fait foi sur ce qui a
    été consulté, et c'est l'état initial qui retient les espèces à enjeu.
    """
    # La bascule précède le titre : dans le document de référence, « Annexes »
    # ouvre la page couchée, il n'est pas relégué en bas de la page portrait
    # précédente.
    avant = rapport.orientation(paysage=True)
    rapport.partie("Annexes")

    if resultat is None or not resultat.especes or contexte is None:
        rapport.a_completer(
            "déposer les sources d'espèces de la commune (exports, tableaux, "
            "captures) dans la section « Espèces » de l'outil, puis régénérer "
            "ce document"
        )
        rapport.orientation(paysage=avant)
        return []

    provenance = (
        f"les classeurs de référence d'UNITe ({len(contexte.reference)} taxons), "
        "tenus à jour par la responsable environnement"
        if contexte.reference is not None else
        f"BDC-Statuts (INPN, version {contexte.statuts.version})"
    )
    rapport.para(
        f"Les statuts ci-dessous sont lus dans {provenance} et non saisis à "
        "la main. "
        "Une espèce est retenue comme présentant un enjeu — dans l'état "
        "initial — lorsqu'elle est protégée, inscrite aux annexes de la "
        "directive Habitats ou Oiseaux, classée NT, VU, EN, CR, RE ou EX sur "
        "une liste rouge, ou concernée par un plan national d'actions. Les "
        "catégories LC, DD, NA et NE n'y suffisent pas. Chez les oiseaux, "
        "presque tous protégés, la protection seule n'en fait pas un enjeu."
    )

    # L'annexe « fait foi sur ce qui a été consulté » : elle doit donc dire
    # ce qu'elle ne tabule pas, sans quoi sa prétention à l'exhaustivité est
    # fausse.
    par_groupe, ecartes = _ecarter(_especes_par_groupe(resultat, contexte))
    phrase_ecartees = _phrase_ecartees(ecartes)
    if phrase_ecartees:
        rapport.para(phrase_ecartees)
    traites: list[str] = []
    for groupe in se.GROUPES:
        especes = par_groupe.get(groupe.cle)
        if not especes:
            continue
        rapport.sous_partie(
            f"Liste des espèces {groupe.complement} recensées sur la commune "
            f"{complement_de(projet.libelle_communes)}")
        _tableau_especes(rapport, projet, contexte, groupe, especes,
                         seulement_enjeu=False)
        traites.append(groupe.libelle)

    if resultat.non_resolus:
        nombre = len(resultat.non_resolus)
        if nombre == 1:
            rapport.note(
                "1 nom déposé n'a pas été apparié à TaxRef et ne figure dans "
                "aucun tableau. Il est repris dans l'outil, section "
                "« Espèces », pour correction."
            )
        else:
            rapport.note(
                f"{nombre} noms déposés n'ont pas été appariés à TaxRef et ne "
                "figurent dans aucun tableau. Ils sont repris dans l'outil, "
                "section « Espèces », pour correction."
            )
    rapport.orientation(paysage=avant)
    return traites


def _bibliographie(rapport: Rapport, lignes: list[str]) -> None:
    """Sources et dates de consultation.

    La Licence Ouverte 2.0 sous laquelle l'INPN diffuse ses référentiels impose
    de citer la source **et sa date** : ce bloc n'est pas une politesse, c'est
    la condition d'usage de la donnée.
    """
    rapport.partie("Bibliographie")
    vues: list[str] = []
    for ligne in lignes:
        if ligne and ligne not in vues:
            vues.append(ligne)
    for ligne in vues:
        rapport.para(ligne)
    rapport.a_completer(
        "compléter par les sources consultées hors référentiels nationaux : "
        "portails régionaux, études antérieures, documents d'urbanisme"
    )


# ═══════════════════════════════════════════════════════════════════ assemblage

def _especes_a_pna(resultat, contexte) -> list[str]:
    """Noms des espèces de la commune concernées par un plan national d'actions.

    BDC porte l'information par taxon : elle n'a donc de sens qu'avec une liste
    d'espèces, et ne dit rien de l'emprise géographique des plans.
    """
    if resultat is None or contexte is None:
        return []
    noms = []
    for espece in resultat.especes:
        if not contexte.source_statuts.entrees(espece.cd_ref, "PNA", "France"):
            continue
        taxon = contexte.index.taxons.get(espece.cd_ref)
        nom = nom_vernaculaire(
            (taxon.nom_vern if taxon else "") or espece.nom_commun
            or espece.nom_scientifique)
        if nom and nom not in noms:
            noms.append(nom)
    return sorted(noms, key=cle_alphabetique)


def _page_de_garde(rapport: Rapport, projet: Projet) -> None:
    """La première page : sur quoi porte le document, et à quelle date."""
    lignes = []
    if projet.communes:
        lignes.append(("Commune" + ("s" if len(projet.communes) > 1 else ""),
                       ", ".join(c.libelle for c in projet.communes)))
    if projet.departements:
        lignes.append(("Département" + ("s" if len(projet.departements) > 1 else ""),
                       ", ".join(projet.departements)))
    if projet.surface_ha:
        lignes.append(("Surface de la ZIP",
                       f"{projet.surface_ha:.1f} ha".replace(".", ",")))
    aires = [_libelle_aire_rayon(a) for a in projet.aires]
    if aires:
        lignes.append(("Aires d'étude", _enumerer(aires)))
    lignes.append(("Date d'édition", date.today().strftime("%d/%m/%Y")))

    rapport.page_de_garde(
        titre="Prédiagnostic écologique",
        sous_titre=f"Projet {complement_de(projet.nom)}",
        lignes=lignes,
        mention="Document généré à partir des référentiels nationaux cités en "
                "bibliographie.\nLes passages surlignés signalent ce qui reste "
                "à compléter par la responsable environnement.",
    )


def ecrire(chemin: Path, projet: Projet, *, resultat_zonages=None,
           cartes=(), resultat_especes=None, contexte=None,
           citations: list[str] | None = None,
           modele: Path | None = None,
           cadre: Path | None = None,
           coupes=None) -> tuple[Path, list[str]]:
    """Produit le prédiagnostic. Renvoie (chemin, styles qu'il a fallu recréer).

    Tout est optionnel sauf le projet : un document produit avant le croisement
    des zonages doit sortir quand même, avec à leur place une consigne qui dit
    quelle section de l'outil lancer. Refuser de produire obligerait à tout
    faire dans l'ordre, et un prédiagnostic se construit par allers-retours.

    `coupes` porte les coupes topographiques retenues dans l'outil
    (`coupes.CoupesDuDocument`), ou rien.
    """
    rapport = Rapport(modele)
    cartes = list(cartes or [])
    par_famille = {c.famille: c for c in cartes}
    situation = par_famille.pop("aires", None)
    photographies = [par_famille.pop(f) for f in FAMILLES_PHOTOGRAPHIES
                     if f in par_famille]

    _page_de_garde(rapport, projet)
    rapport.sommaire(avec_figures=bool(coupes is not None and coupes.coupes))

    cadre_insere = _cadre_et_methodologies(rapport, projet, situation,
                                           cadre)
    _etat_initial(rapport, projet, resultat_zonages, par_famille,
                  resultat_especes, contexte,
                  _especes_a_pna(resultat_especes, contexte))
    _dynamique_du_site(rapport, photographies)
    _contexte_topographique(rapport, coupes)
    _trame_verte_et_bleue(rapport)
    _annexes(rapport, projet, resultat_especes, contexte)

    lignes_sources = list(citations or [])
    # Le fond des cartes de situation et de zonages : l'interface l'ajoutait,
    # un document produit hors d'elle ne le citait pas. Le dédoublonnage de la
    # bibliographie absorbe la ligne quand l'interface l'écrit aussi.
    if any(c.famille not in FAMILLES_PHOTOGRAPHIES for c in cartes):
        from .cartes import FOND
        lignes_sources.append(f"Fond de carte : {FOND['attribution']}")
    # Les photographies sont lues au rendu des planches, non figées comme les
    # référentiels : la date est celle de ce rendu.
    for carte in photographies:
        if carte.fond:
            lignes_sources.append(
                carte.fond + (f", consultées le {carte.date}" if carte.date
                              else ""))
    if coupes is not None and coupes.coupes:
        jour = coupes.jour.strftime("%d/%m/%Y") if coupes.jour else ""
        lignes_sources.append(
            "IGN – RGE ALTI® (service altimétrique de la Géoplateforme) et "
            "BD TOPO® V3" + (f", consultés le {jour}" if jour else ""))
    for source in getattr(resultat_zonages, "sources_locales", []) or []:
        lignes_sources.append(f"{source.type_libelle} : {source.citation}")
    if resultat_especes is not None and resultat_especes.especes:
        deposees = sorted({s for e in resultat_especes.especes for s in e.sources})
        if deposees:
            lignes_sources.append("Occurrences d'espèces : "
                                  + ", ".join(deposees))
    _bibliographie(rapport, lignes_sources)

    if not cadre_insere:
        rapport.note(
            "le document de partie générale (modele/cadre_general.docx) est "
            "introuvable : le cadre général et les méthodologies sont sortis "
            "en squelette, à compléter."
        )
    return rapport.enregistrer(chemin), rapport.styles_recrees
