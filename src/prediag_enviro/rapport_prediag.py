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

from . import chemins, statuts_especes as se, zonages as mod_zonages
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

def _constat_famille(retenus: list, projet: Projet) -> list[str]:
    """Les phrases factuelles qui ouvrent une rubrique de zonages.

    Toutes sont du dénombrement ou de la mesure, donc toutes automatisables.
    La tournure évite d'accorder en genre : « on recense » marche pour une
    ZNIEFF comme pour un arrêté de protection de biotope, là où « sont
    présentes » obligerait à connaître le genre de chaque type de zonage.
    """
    if not retenus:
        return ["Aucun zonage de cette nature n'est présent dans les aires "
                "d'étude du projet."]

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


def _groupes_tableau(retenus: list) -> list[tuple[str, list[dict]]]:
    """Lignes du tableau, groupées par type sous une ligne fusionnée.

    C'est la forme du document de référence : « Zone Naturelle d'Intérêt
    Écologique Faunistique et Floristique de type I » occupe une ligne à lui
    seul, et ses entrées suivent dessous.
    """
    par_type: dict[str, list[dict]] = {}
    for zonage in retenus:
        par_type.setdefault(zonage.type, []).append({
            "nom": zonage.nom,
            "distance": zonage.distance_lisible,
            "identifiant": zonage.identifiant,
            "interet": zonage.interet,
            "aires": ", ".join(zonage.aires),
        })
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
        par_groupe.setdefault(se.groupe_de(taxon).cle, []).append(espece)
    return par_groupe


def _tableau_especes(rapport: Rapport, projet: Projet, contexte,
                     groupe, especes: list, seulement_enjeu: bool) -> int:
    """Un tableau d'espèces. Renvoie le nombre de lignes écrites.

    Le document de référence tabule deux fois les mêmes espèces, et ce n'est
    pas une redite : l'**état initial** ne retient que celles qui portent un
    enjeu, parce que c'est sur elles que porte le raisonnement ; l'**annexe**
    donne la liste exhaustive, qui fait foi sur ce qui a été consulté.
    """
    statuts, index = contexte.statuts, contexte.index
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
        ))
    qualificatif = " à enjeu" if seulement_enjeu else ""
    rapport.tableau(
        jeu.colonnes, lignes,
        legende=f"Liste des espèces {groupe.complement}{qualificatif} "
                f"recensées sur la commune "
                f"{complement_de(projet.libelle_communes)}",
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
        for famille, titre_interne in mod_zonages.FAMILLES:
            retenus = resultat_zonages.par_famille(famille)
            rapport.sous_sous_partie(TITRES_ZONAGES.get(famille, titre_interne))
            for phrase in _constat_famille(retenus, projet):
                rapport.para(phrase)
            if not retenus:
                continue
            rapport.tableau(
                colonnes_zonages(), [],
                legende=f"{TITRES_ZONAGES.get(famille, titre_interne)} dans "
                        "les aires d'étude du projet",
                groupes=_groupes_tableau(retenus),
                legende_bas=_legende_aires(projet),
            )
            carte = cartes_par_famille.get(famille)
            if carte is not None:
                rapport.carte(
                    carte.chemin,
                    f"Localisation des {titre_interne.split('—')[0].strip().lower()} "
                    f"jusqu'à {_rayon_aer(projet)} autour de la ZIP")
            # Les zonages sans source nationale fiable — les ENS en tête — se
            # rangent dans cette famille. Le lecteur doit savoir si la rubrique
            # est vide faute de zonage ou faute de recherche.
            if famille == "autres":
                for avertissement in getattr(resultat_zonages,
                                             "avertissements", []):
                    rapport.note(avertissement)

        rapport.sous_sous_partie("Plan National d'Actions (PNA)")
        if especes_pna:
            rapport.para(
                f"{len(especes_pna)} espèce"
                f"{'s' if len(especes_pna) > 1 else ''} recensée"
                f"{'s' if len(especes_pna) > 1 else ''} sur la commune "
                f"fait{'' if len(especes_pna) == 1 else 'nt'} l'objet d'un "
                f"plan national d'actions : {_enumerer(especes_pna)}."
            )
        else:
            rapport.para(
                "Aucune des espèces recensées sur la commune ne fait l'objet "
                "d'un plan national d'actions."
            )
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

    rapport.sous_partie("Zone humide")
    rapport.a_completer(
        "renseigner le type de sol de la ZIP et son caractère hydromorphe, "
        "puis les potentialités de zones humides, d'après la carte des sols "
        "(RRP du GIS Sol), les zones à dominante humide du SDAGE et les "
        "inventaires portés par la DREAL et l'agence de l'eau"
    )
    rapport.sous_sous_partie("Consultations")
    rapport.a_completer("citer les sources consultées et leur date")
    rapport.note(
        "cette rubrique n'est pas encore alimentée automatiquement : les "
        "couches de sols et de milieux humides ne sont pas nationales et "
        "relèvent de sources régionales, à brancher au cas par cas."
    )

    comptes = _compter_par_famille_etude(resultat_especes, contexte)
    par_groupe = _especes_par_groupe(resultat_especes, contexte)
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


def _rayon_aer(projet: Projet) -> str:
    aire = projet.aire("AER")
    if aire is None or aire.rayon_m < 1000:
        return "l'aire d'étude rapprochée"
    return f"{aire.rayon_m / 1000:.0f} km".replace(".", ",")


def _compter_par_famille_etude(resultat, contexte) -> dict[str, tuple[int, int]]:
    """(total, à enjeu) par volet de l'état initial."""
    if resultat is None or not resultat.especes or contexte is None:
        return {}
    par_groupe: dict[str, list] = {}
    for espece in resultat.especes:
        taxon = contexte.index.taxons.get(espece.cd_ref)
        par_groupe.setdefault(se.groupe_de(taxon).cle, []).append(espece)

    comptes: dict[str, list[int]] = {}
    for cle_groupe, especes in par_groupe.items():
        groupe = se.groupe_par_cle(cle_groupe)
        jeu = se.jeu(groupe, contexte.statuts, [e.cd_ref for e in especes],
                     [])
        enjeu = sum(1 for e in especes
                    if se.a_enjeu(jeu, contexte.statuts, e.cd_ref))
        famille = se.famille_etude(cle_groupe)
        cumul = comptes.setdefault(famille, [0, 0])
        cumul[0] += len(especes)
        cumul[1] += enjeu
    return {k: (v[0], v[1]) for k, v in comptes.items()}


def _dynamique_du_site(rapport: Rapport) -> None:
    rapport.partie("Dynamique du site")
    rapport.a_completer(
        "comparer l'occupation du sol actuelle à celle des années 1950 "
        "(photographies aériennes de l'IGN) et en tirer la dynamique des "
        "milieux sur la ZIP"
    )


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

    rapport.para(
        "Les statuts ci-dessous sont lus dans BDC-Statuts "
        f"(INPN, version {contexte.statuts.version}) et non saisis à la main. "
        "Une espèce est retenue comme présentant un enjeu — dans l'état "
        "initial — lorsqu'elle est protégée, inscrite aux annexes de la "
        "directive Habitats ou Oiseaux, classée NT, VU, EN, CR, RE ou EX sur "
        "une liste rouge, ou concernée par un plan national d'actions. Les "
        "catégories LC, DD, NA et NE n'y suffisent pas."
    )

    par_groupe = _especes_par_groupe(resultat, contexte)
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
        if not contexte.statuts.entrees(espece.cd_ref, "PNA", "France"):
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
           cadre: Path | None = None) -> tuple[Path, list[str]]:
    """Produit le prédiagnostic. Renvoie (chemin, styles qu'il a fallu recréer).

    Tout est optionnel sauf le projet : un document produit avant le croisement
    des zonages doit sortir quand même, avec à leur place une consigne qui dit
    quelle section de l'outil lancer. Refuser de produire obligerait à tout
    faire dans l'ordre, et un prédiagnostic se construit par allers-retours.
    """
    rapport = Rapport(modele)
    cartes = list(cartes or [])
    par_famille = {c.famille: c for c in cartes}
    situation = par_famille.pop("aires", None)

    _page_de_garde(rapport, projet)
    rapport.sommaire()

    cadre_insere = _cadre_et_methodologies(rapport, projet, situation,
                                           cadre)
    _etat_initial(rapport, projet, resultat_zonages, par_famille,
                  resultat_especes, contexte,
                  _especes_a_pna(resultat_especes, contexte))
    _dynamique_du_site(rapport)
    _trame_verte_et_bleue(rapport)
    _annexes(rapport, projet, resultat_especes, contexte)

    lignes_sources = list(citations or [])
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
